import os
import queue
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import _fakes
from nonsteamapps import appmenu, apps, cecwatch, mpris

DEVICE_PATH = "/com/steampowered/CecDaemon1/Devices/cec0"
MAPPED = ((b"\x00", 28), (b"\x0d", 1), (b"\x44", 200))
YOUTUBE = "org.mpris.MediaPlayer2.chromium.instance2"
VLC = "org.mpris.MediaPlayer2.vlc"


def message(member, body, order="<", kind=appmenu.SIGNAL, interface=cecwatch.DEVICE):
    return appmenu.Message(kind, 0, 1, {appmenu.INTERFACE: interface, appmenu.MEMBER: member}, body, order)


def received(initiator, destination, nanoseconds, data, order="<"):
    return bytes((initiator, destination)) + bytes(6) + struct.pack(order + "QI", nanoseconds, len(data)) + data


def pressed(button, initiator=0):
    return struct.pack("<I", len(button)) + button + bytes((initiator,))


def mappings(entries):
    data = bytearray(b"\x06a(ayq)\x00")
    at = len(data)
    data += bytes(8)
    for button, key in entries:
        data += bytes(-len(data) % 8) + struct.pack("<I", len(button)) + button
        data += bytes(-len(data) % 2) + struct.pack("<H", key)
    struct.pack_into("<I", data, at, len(data) - at - 8)
    return bytes(data)


def boolean(value):
    return b"\x01b\x00\x00" + struct.pack("<I", int(value))


def strings(body, count):
    found, offset = [], 0
    for _ in range(count):
        offset += -offset % 4
        (length,) = struct.unpack_from("<I", body, offset)
        found.append(body[offset + 4:offset + 4 + length].decode())
        offset += length + 5
    return found


def wait_for(condition, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class WireTests(unittest.TestCase):
    def test_what_cecd_maps_is_read_from_its_mappings(self):
        self.assertEqual(cecwatch.mapped_buttons(message("", mappings(MAPPED), kind=appmenu.METHOD_RETURN)), {b"\x00", b"\x0d", b"\x44"})
        self.assertEqual(cecwatch.mapped_buttons(message("", mappings([(b"\x60\x05", 207)]), kind=appmenu.METHOD_RETURN)), {b"\x60\x05"})
        self.assertEqual(cecwatch.mapped_buttons(message("", mappings([]), kind=appmenu.METHOD_RETURN)), frozenset())
        self.assertIsNone(cecwatch.mapped_buttons(message("", boolean(True), kind=appmenu.METHOD_RETURN)))
        with self.assertRaises(struct.error):
            cecwatch.mapped_buttons(message("", mappings(MAPPED)[:-3], kind=appmenu.METHOD_RETURN))

    def test_whether_cecd_has_its_keyboard_is_read(self):
        self.assertIs(cecwatch.switched_on(message("", boolean(True))), True)
        self.assertIs(cecwatch.switched_on(message("", boolean(False))), False)
        self.assertIsNone(cecwatch.switched_on(message("", mappings(MAPPED))))

    def test_what_the_tv_sends_reads_as_a_line_for_the_log(self):
        self.assertEqual(cecwatch.describe(message("ReceivedMessage", received(0, 4, 12_345_678_901, b"\x44\x0d"))), "  CEC 12.346 0>4: 44 0d")
        self.assertEqual(cecwatch.describe(message("ReceivedMessage", received(0, 15, 2_000_000, b"\x36", ">"), ">")), "  CEC 0.002 0>f: 36")
        self.assertIsNone(cecwatch.describe(message("UserControlPressed", pressed(b"\x00"))))
        with self.assertRaises(struct.error):
            cecwatch.describe(message("ReceivedMessage", received(0, 4, 1, b"\x44\x0d")[:-1]))

    def test_a_key_is_due_once_it_is_held_without_a_repeat_or_a_release(self):
        follower = cecwatch.Follower(2.0)
        follower.press(b"\x01", 10.0)
        self.assertIsNone(follower.due(11.75))
        follower.press(b"\x01", 11.75)
        self.assertIsNone(follower.due(13.5))
        self.assertEqual(follower.due(13.75), b"\x01")
        self.assertIsNone(follower.due(20.0))
        follower.press(b"\x02", 20.0)
        follower.release()
        self.assertIsNone(follower.due(30.0))

    def test_the_followers_signals_set_the_key_held(self):
        follower, lines = cecwatch.Follower(1.0), []
        cecwatch._handle(message("ReceivedMessage", received(0, 4, 1_000_000_000, b"\x44\x01")), follower, 0.0, lines.append)
        cecwatch._handle(message("UserControlPressed", pressed(b"\x01")), follower, 0.0, lines.append)
        self.assertEqual((follower.held, lines), (b"\x01", ["  CEC 1.000 0>4: 44 01"]))
        cecwatch._handle(message("UserControlPressed", b"\xff\xff\xff\xff"), follower, 0.5, lines.append)
        cecwatch._handle(message("UserControlReleased", b"\x00", interface="org.example.Other"), follower, 0.5, lines.append)
        cecwatch._handle(message("UserControlReleased", b"\x00", kind=appmenu.METHOD_CALL), follower, 0.5, lines.append)
        self.assertEqual((follower.held, follower.since), (b"\x01", 0.0))
        cecwatch._handle(message("UserControlReleased", b"\x00"), follower, 0.5, lines.append)
        self.assertIsNone(follower.held)

    def test_without_a_bus_nothing_is_followed(self):
        lines = []
        self.assertEqual(cecwatch.follow(lambda: True, environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}, log=lines.append), (False, 0))
        self.assertEqual(cecwatch.follow(lambda: True, environ={}, log=lines.append), (False, 0))
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("  cannot follow the TV remote's keys") for line in lines))


class RoutingTests(unittest.TestCase):
    def test_a_route_reaches_the_device_or_a_switch_on_its_way(self):
        leads = cecwatch.leads_to
        self.assertTrue(leads(0x1000, 0x1000))
        self.assertTrue(leads(0x1000, 0x1100))
        self.assertTrue(leads(0x1100, 0x1120))
        self.assertFalse(leads(0x1200, 0x1100))
        self.assertFalse(leads(0x2000, 0x1000))
        self.assertFalse(leads(0x1100, 0x1000))
        self.assertFalse(leads(0x0000, 0x1000))
        self.assertFalse(leads(0x2000, cecwatch.NO_ADDRESS))
        self.assertFalse(leads(cecwatch.NO_ADDRESS, cecwatch.NO_ADDRESS))
        self.assertEqual(cecwatch.address_text(0x1A20), "1.a.2.0")

    def departures(self, address, cases):
        for initiator, message, expected in cases:
            with self.subTest(address=hex(address) if address is not None else None, initiator=initiator, message=message):
                self.assertEqual(cecwatch.departure(initiator, bytes.fromhex(message), address), expected)

    def test_a_tv_that_shows_something_else_takes_the_picture_away(self):
        self.departures(0x1000, [
            (0, "82 00 00", "the TV switched to its own apps"),
            (4, "82 20 00", "the device at 2.0.0.0 took over the TV"),
            (4, "82 10 00", None),
            (0, "86 30 00", "the TV switched to 3.0.0.0"),
            (0, "86 10 00", None),
            (0, "80 10 00 20 00", "the TV switched to 2.0.0.0"),
            (0, "80 30 00 20 00", "the TV switched to 2.0.0.0"),
            (0, "80 20 00 10 00", None),
            (0, "80 10 00 00 00", "the TV switched to its own apps"),
            (5, "81 21 00", None),
            (0, "36", "the TV is turning off"),
            (5, "36", "the audio system asked for standby"),
            (0, "44 00", None),
            (0, "45", None),
            (0, "82 20", None),
            (0, "80 10 00 20", None),
            (0, "", None),
        ])

    def test_what_tvs_send_all_day_never_pauses_and_turning_off_does(self):
        """Frames from real TVs: a Sony's in SteamOS issue 2916, an LG's vendor ID broadcast every 15 seconds in issue
        2626, and what libCEC's handler for Samsung TVs expects of them, from their power-up announcement and remote
        keys to their menu language."""
        self.departures(0x1000, [
            (0, "8f", None),
            (0, "a0 08 00 46 00 3f 00 00 00 00 00", None),
            (0, "00 71 01", None),
            (0, "84 00 00 00", None),
            (0, "87 00 e0 91", None),
            (0, "87 00 00 f0", None),
            (0, "a0 00 00 f0 23", None),
            (0, "8a 91", None),
            (0, "8b", None),
            (0, "32 65 6e 67", None),
            (0, "90 01", None),
            (0, "85", None),
            (0, "83", None),
            (0, "46", None),
            (0, "36", "the TV is turning off"),
        ])

    def test_through_an_av_receiver_only_the_receivers_own_input_counts(self):
        self.departures(0x1100, [
            (0, "80 20 00 10 00", None),
            (0, "86 10 00", None),
            (5, "81 11 00", None),
            (5, "81 12 00", "the audio system switched to 1.2.0.0"),
            (5, "80 11 00 12 00", "the audio system switched to 1.2.0.0"),
            (5, "80 12 00 13 00", None),
            (5, "80 21 00 22 00", None),
            (5, "82 10 00", "the device at 1.0.0.0 took over the TV"),
            (0, "80 10 00 20 00", "the TV switched to 2.0.0.0"),
        ])

    def test_without_the_devices_address_only_standby_counts(self):
        self.departures(None, [(0, "82 00 00", None), (0, "80 10 00 20 00", None), (0, "36", "the TV is turning off")])
        self.departures(cecwatch.NO_ADDRESS, [(0, "86 10 00", "the TV switched to 1.0.0.0"), (5, "81 12 00", None)])

    def test_the_apps_that_play_media_pause_unless_the_setting_names_apps(self):
        youtube, jellyfin, element, netflix, prism = (apps.by_id(name) for name in ("youtube", "jellyfin", "element", "netflix", "prism"))
        for value in (None, "default", " Default "):
            self.assertEqual([cecwatch.pauses(value, app) for app in (youtube, jellyfin, element, netflix, prism)], [True, True, False, True, False])
        self.assertTrue(cecwatch.pauses("all", element))
        self.assertFalse(cecwatch.pauses("off", youtube))
        self.assertEqual([cecwatch.pauses("element jellyfin", app) for app in (youtube, jellyfin, element)], [False, True, True])
        self.assertEqual(sorted(app.id for app in apps.APPS if app.plays_media),
                         ["disneyplus", "hbomax", "helium", "jellyfin", "netflix", "primevideo", "vlc", "youtube"])


class FakeCecd(threading.Thread):
    """Owns cecd's name on a test bus: answers what the follower asks and sends the signals a test asks for."""

    def __init__(self, address, buttons=MAPPED, keyboard=True, physical=0x1000):
        super().__init__(daemon=True)
        self.connection = appmenu.Connection(address)
        self.connection.bus("Hello")
        reply = self.connection.bus("RequestName", "su", bytes(appmenu.Writer().string(cecwatch.SERVICE).uint32(appmenu.DO_NOT_QUEUE).data))
        assert appmenu.uint32(reply) == appmenu.PRIMARY_OWNER
        self.buttons, self.keyboard, self.physical = buttons, keyboard, physical
        self.calls, self.outbox, self.stopping = [], queue.Queue(), threading.Event()

    @property
    def reloads(self):
        return sum(1 for member, _ in self.calls if member == "Reload")

    def stop(self):
        self.stopping.set()
        self.join(10)
        self.connection.close()

    def press(self, button, nanoseconds=1_000_000_000):
        self.outbox.put(("ReceivedMessage", "yytay", received(0, 4, nanoseconds, b"\x44" + button)))
        self.outbox.put(("UserControlPressed", "ayy", pressed(button)))

    def release(self, nanoseconds=2_000_000_000):
        self.outbox.put(("ReceivedMessage", "yytay", received(0, 4, nanoseconds, b"\x45")))
        self.outbox.put(("UserControlReleased", "y", b"\x00"))

    def receive(self, initiator, destination, message, nanoseconds=3_000_000_000):
        """Signal a message from the TV or another device, given in hexadecimal."""
        self.outbox.put(("ReceivedMessage", "yytay", received(initiator, destination, nanoseconds, bytes.fromhex(message))))

    def run(self):
        while not self.stopping.is_set():
            while not self.outbox.empty():
                member, signature, body = self.outbox.get()
                fields = {appmenu.PATH: DEVICE_PATH, appmenu.INTERFACE: cecwatch.DEVICE, appmenu.MEMBER: member, appmenu.SIGNATURE: signature}
                self.connection.send(appmenu.SIGNAL, fields, body)
            if self.connection.pending or select.select([self.connection.socket], [], [], 0.01)[0]:
                for received_message in self.connection.messages():
                    self.answer(received_message)

    def answer(self, call):
        if call.kind != appmenu.METHOD_CALL:
            return
        member = call.fields.get(appmenu.MEMBER)
        self.calls.append((member, call.flags))
        fields = {appmenu.REPLY_SERIAL: call.serial, appmenu.DESTINATION: call.fields[appmenu.SENDER]}
        if member == "Reload" and call.fields.get(appmenu.INTERFACE) == cecwatch.CONFIG:
            self.connection.send(appmenu.METHOD_RETURN, fields)
            return
        if member == "Get" and strings(call.body, 2) == [cecwatch.CONFIG, "Mappings"]:
            self.connection.send(appmenu.METHOD_RETURN, {**fields, appmenu.SIGNATURE: "v"}, mappings(self.buttons))
            return
        if member == "Get" and strings(call.body, 2) == [cecwatch.DEVICE, "PhysicalAddress"] and call.fields.get(appmenu.PATH) == DEVICE_PATH:
            self.connection.send(appmenu.METHOD_RETURN, {**fields, appmenu.SIGNATURE: "v"}, b"\x01q\x00\x00" + struct.pack("<H", self.physical))
            return
        if member == "Get" and strings(call.body, 2) == [cecwatch.CONFIG, "Uinput"]:
            self.connection.send(appmenu.METHOD_RETURN, {**fields, appmenu.SIGNATURE: "v"}, boolean(self.keyboard))
            return
        self.connection.send(appmenu.ERROR, {**fields, appmenu.ERROR_NAME: "org.freedesktop.DBus.Error.UnknownMethod"})


@unittest.skipUnless(shutil.which("dbus-daemon"), "needs dbus-daemon")
class BusTests(unittest.TestCase):
    timeout = 0.6

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.address = str(self.folder / "bus")
        self.daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", f"--address=unix:path={self.address}"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_daemon)
        self.assertTrue(wait_for(lambda: Path(self.address).exists()))
        self.environ = {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={self.address}"}

    def stop_daemon(self):
        self.daemon.terminate()
        self.daemon.wait(timeout=10)

    def cecd(self, **options):
        fake = FakeCecd(self.address, **options)
        fake.start()
        self.addCleanup(fake.stop)
        return fake

    def media(self, *players, wrapped=False):
        process = _fakes.media_players(self.folder, self.address, *players, wrapped=wrapped)
        self.addCleanup(_fakes.stop_media, process)
        return process

    def watch(self, pid, **options):
        """Start the helper as the launcher does, with its lines in a log file; return its ID and the log."""
        log = self.folder / "app.log"
        sys.stdout.flush()
        saved = os.dup(1)
        try:
            descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.dup2(descriptor, 1)
            os.close(descriptor)
            with mock.patch.dict(os.environ, self.environ):
                helper = cecwatch.watch(pid, self.timeout, **options)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
        self.assertGreater(helper, 0)
        return helper, log

    def follow(self, players=None):
        alive, ready, lines, result = threading.Event(), threading.Event(), [], []
        alive.set()
        thread = threading.Thread(target=lambda: result.append(
            cecwatch.follow(alive.is_set, ready.set, self.environ, lines.append, self.timeout, 0.01, players=players)))
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(alive.clear)
        self.assertTrue(ready.wait(10))

        def stop():
            alive.clear()
            thread.join(10)
            return result

        return lines, stop

    def test_a_key_the_tv_repeats_and_lets_go_is_left_alone(self):
        fake = self.cecd()
        lines, stop = self.follow()
        for repeat in range(8):
            fake.press(b"\x00", 1_000_000_000 + repeat * 100_000_000)
            time.sleep(0.1)
        fake.release(1_800_000_000)
        self.assertTrue(wait_for(lambda: "  CEC 1.800 0>4: 45" in lines))
        time.sleep(self.timeout * 2)
        self.assertEqual(stop(), [(True, 0)])
        self.assertEqual(fake.reloads, 0)
        self.assertEqual(lines[:3], ["  following the TV remote's keys, to let go of one the TV leaves pressed", "  CEC 1.000 0>4: 44 00", "  CEC 1.100 0>4: 44 00"])

    def test_a_key_the_tv_leaves_pressed_is_let_go_once(self):
        fake = self.cecd()
        lines, stop = self.follow()
        fake.press(b"\x0d")
        self.assertTrue(wait_for(lambda: fake.reloads == 1))
        time.sleep(self.timeout * 2)
        self.assertEqual(stop(), [(True, 1)])
        self.assertEqual(fake.reloads, 1)
        self.assertIn("  the TV left 0d pressed without letting go; cecd reloads to let its key go", lines)
        self.assertEqual([member for member, _ in fake.calls], ["Get", "Get", "Reload"])
        self.assertTrue(all(flags & appmenu.NO_AUTO_START for _, flags in fake.calls))

    def test_a_button_cecd_gives_no_key_is_left_alone(self):
        fake = self.cecd()
        lines, stop = self.follow()
        fake.press(b"\x09")
        self.assertTrue(wait_for(lambda: "  the TV left 09 pressed, for which cecd presses no key" in lines))
        self.assertEqual(stop(), [(True, 0)])
        self.assertEqual(fake.reloads, 0)

    def test_without_its_keyboard_cecd_is_not_reloaded(self):
        fake = self.cecd(keyboard=False)
        lines, stop = self.follow()
        fake.press(b"\x00")
        self.assertTrue(wait_for(lambda: "  the TV left 00 pressed, for which cecd presses no key" in lines))
        self.assertEqual(stop(), [(True, 0)])
        self.assertEqual(fake.reloads, 0)

    def test_a_helper_follows_while_the_app_runs_and_writes_to_its_log(self):
        app = subprocess.Popen(["sleep", "30"])
        self.addCleanup(app.wait)
        self.addCleanup(app.kill)
        helper, log = self.watch(app.pid)
        self.assertTrue(wait_for(lambda: "following the TV remote's keys" in log.read_text()))
        fake = self.cecd()
        fake.press(b"\x0d")
        self.assertTrue(wait_for(lambda: fake.reloads == 1))
        app.kill()
        app.wait()
        self.assertTrue(wait_for(lambda: os.waitpid(helper, os.WNOHANG)[0] == helper), "the helper outlived the app")
        text = log.read_text()
        self.assertIn("  CEC 1.000 0>4: 44 0d\n", text)
        self.assertIn("  the TV left 0d pressed without letting go; cecd reloads to let its key go\n", text)
        self.assertNotIn("following the TV's input", text)

    def test_the_app_pauses_when_the_tv_switches_to_another_input_and_no_other_player_does(self):
        fake = self.cecd()
        app = self.media(f"{YOUTUBE}=Playing", wrapped=True)
        self.media(f"{VLC}=Playing")
        lines, stop = self.follow(mpris.Players(app.pid, "YouTube"))
        fake.receive(0, 0xF, "80 20 00 10 00")
        fake.receive(0, 0xF, "80 10 00 20 00")
        self.assertTrue(wait_for(lambda: "  the TV switched to 2.0.0.0; paused YouTube" in lines))
        self.assertEqual(stop(), [(True, 0)])
        self.assertEqual(_fakes.paused(self.folder), [YOUTUBE])
        self.assertEqual(lines, [
            "  following the TV remote's keys, to let go of one the TV leaves pressed",
            "  following the TV's input, to pause YouTube when the TV switches away or turns off",
            "  CEC 3.000 0>f: 80 20 00 10 00",
            "  CEC 3.000 0>f: 80 10 00 20 00",
            "  the TV switched to 2.0.0.0; paused YouTube",
        ])
        self.assertEqual([member for member, _ in fake.calls], ["Get", "Get"])
        self.assertTrue(all(flags & appmenu.NO_AUTO_START for _, flags in fake.calls))

    def test_the_tv_turning_off_pauses_the_app_once_without_asking_cecd(self):
        fake = self.cecd()
        app = self.media(f"{YOUTUBE}=Playing", "org.mpris.MediaPlayer2.chromium.instance9=Stopped")
        lines, stop = self.follow(mpris.Players(app.pid, "YouTube"))
        fake.receive(0, 0xF, "36")
        self.assertTrue(wait_for(lambda: "  the TV is turning off; paused YouTube" in lines))
        fake.receive(0, 0xF, "36")
        self.assertTrue(wait_for(lambda: "  the TV is turning off; YouTube was not playing" in lines))
        stop()
        self.assertEqual(_fakes.paused(self.folder), [YOUTUBE])
        self.assertEqual(fake.calls, [])

    def test_without_players_the_tvs_messages_are_only_written_down(self):
        fake = self.cecd()
        self.media(f"{YOUTUBE}=Playing")
        lines, stop = self.follow()
        fake.receive(0, 0xF, "82 00 00")
        self.assertTrue(wait_for(lambda: "  CEC 3.000 0>f: 82 00 00" in lines))
        time.sleep(0.2)
        stop()
        self.assertEqual(fake.calls, [])
        self.assertEqual(_fakes.paused(self.folder), [])

    def test_a_helper_started_to_pause_pauses_the_app_it_follows(self):
        app = self.media(f"{YOUTUBE}=Playing", wrapped=True)
        helper, log = self.watch(app.pid, pausing="YouTube")
        self.assertTrue(wait_for(lambda: "following the TV's input, to pause YouTube" in log.read_text()))
        fake = self.cecd()
        fake.receive(0, 0xF, "86 30 00")
        self.assertTrue(wait_for(lambda: "  the TV switched to 3.0.0.0; paused YouTube\n" in log.read_text()))
        _fakes.stop_media(app)
        self.assertTrue(wait_for(lambda: os.waitpid(helper, os.WNOHANG)[0] == helper), "the helper outlived the app")
        self.assertEqual(_fakes.paused(self.folder), [YOUTUBE])


class BusClientTests(unittest.TestCase):
    """What arrives while a call waits for its reply is kept for the next read."""

    @unittest.skipUnless(shutil.which("dbus-daemon"), "needs dbus-daemon")
    def test_a_signal_that_arrives_during_a_call_is_kept(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        address = str(Path(tmp.name) / "bus")
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", f"--address=unix:path={address}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(daemon.wait, 10)
        self.addCleanup(daemon.terminate)
        self.assertTrue(wait_for(lambda: Path(address).exists()))
        listener, sender = appmenu.Connection(address), appmenu.Connection(address)
        self.addCleanup(listener.close)
        self.addCleanup(sender.close)
        listener.bus("Hello")
        sender.bus("Hello")
        listener.bus("AddMatch", "s", bytes(appmenu.Writer().string("type='signal',interface='org.example.Test'").data))
        listener.pending.clear()
        sender.send(appmenu.SIGNAL, {appmenu.PATH: "/org/example", appmenu.INTERFACE: "org.example.Test", appmenu.MEMBER: "Ping"})
        sender.bus("GetId")
        self.assertEqual(listener.bus("GetId").kind, appmenu.METHOD_RETURN)
        self.assertEqual([found.fields.get(appmenu.MEMBER) for found in listener.messages()], ["Ping"])
        self.assertEqual(listener.pending, [])


if __name__ == "__main__":
    unittest.main()
