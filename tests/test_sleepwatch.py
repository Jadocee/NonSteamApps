import os
import queue
import select
import shutil
import socket
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
from nonsteamapps import appmenu, apps, sleepwatch

LAUNCHER = ["python3", "-B", "-E", "-s", "/home/deck/.local/share/nonsteamapps/lib/nonsteamapps-cli", "launch", "youtube"]

TREE = r"""
import os, signal, subprocess, sys, time
role, name, folder = sys.argv[1], sys.argv[2], sys.argv[3]
def mark(what):
    open(os.path.join(folder, f"{name}-{what}"), "w").close()
if role == "wrapper":
    signal.signal(signal.SIGTERM, lambda *_: mark("term"))
    child = subprocess.Popen(sys.argv[4:])
    with open(os.path.join(folder, f"{name}-child"), "w") as out:
        out.write(str(child.pid))
    child.wait()
else:
    def quit(*_):
        mark("term")
        sys.exit(0)
    signal.signal(signal.SIGTERM, quit if role == "app" else lambda *_: mark("term"))
    mark("ready")
    time.sleep(60)
"""


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def make_proc(root: Path, processes):
    """A stand-in for ``/proc``: each ``pid: (parent, argv)``."""
    for pid, (parent, argv) in processes.items():
        folder = root / str(pid)
        folder.mkdir(parents=True)
        (folder / "stat").write_text(f"{pid} (x) S {parent} 1 1 0 -1\n")
        (folder / "cmdline").write_bytes(b"".join(part.encode() + b"\0" for part in argv))
    return root


class AppliesTests(unittest.TestCase):
    def test_each_app_decides_unless_the_setting_names_apps(self):
        youtube, prism, files, netflix = (apps.by_id(name) for name in ("youtube", "prism", "files", "netflix"))
        for value in (None, "default", " Default "):
            self.assertEqual([sleepwatch.applies(value, app) for app in (youtube, prism, files, netflix)], [True, False, False, True])
        self.assertTrue(sleepwatch.applies("all", prism))
        self.assertFalse(sleepwatch.applies("off", youtube))
        self.assertFalse(sleepwatch.applies("", youtube))
        self.assertEqual([sleepwatch.applies("youtube, prism", app) for app in (youtube, prism, netflix)], [True, True, False])

    def test_the_apps_that_stay_open_are_those_where_closing_could_lose_work(self):
        self.assertEqual(sorted(app.id for app in apps.APPS if app.stays_open_in_sleep),
                         ["bottles", "eden", "edennx2", "files", "kytyps5", "lichii", "prism", "protontricks", "protonup", "winetricks"])


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.fake = _fakes.FakeFlatpak(self.folder)
        patch = mock.patch.dict(os.environ, self.fake.env)
        patch.start()
        self.addCleanup(patch.stop)

    def target(self, processes, pid, app_id, instances=""):
        proc = make_proc(Path(tempfile.mkdtemp(dir=self.folder)), processes)
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_PS": instances}):
            return sleepwatch.target(pid, app_id, LAUNCHER, flatpak=self.fake.command, proc=proc)

    def test_a_flatpaks_main_process_is_the_first_in_its_sandbox_past_bubblewrap_and_shells(self):
        processes = {
            100: (1, ["bwrap", "--args", "40"]),
            101: (100, LAUNCHER),
            102: (100, ["bwrap", "--args", "41"]),
            103: (100, ["bwrap", "--args", "42"]),
            104: (103, ["xdg-dbus-proxy", "--args=43"]),
            105: (102, ["/bin/sh", "/app/bin/startvacuumtube"]),
            106: (105, ["/app/vacuumtube/vacuumtube", "--enable-features=x"]),
            107: (106, ["/app/vacuumtube/vacuumtube", "--type=renderer"]),
            200: (1, ["bwrap", "--args", "50"]),
            202: (200, ["/app/vacuumtube/vacuumtube"]),
        }
        instances = "200 202 rocks.shy.VacuumTube;100 102 rocks.shy.VacuumTube"
        self.assertEqual(self.target(processes, 100, "rocks.shy.VacuumTube", instances), 106)
        self.assertEqual(self.fake.calls("ps"), [["ps", "--columns=pid,child-pid,application"]])
        self.assertIsNone(self.target(processes, 100, "rocks.shy.VacuumTube", "200 202 rocks.shy.VacuumTube"))

    def test_an_app_the_launcher_stays_with_is_found_in_its_own_sandbox(self):
        processes = {
            300: (1, LAUNCHER),
            301: (300, ["bwrap", "--args", "40"]),
            302: (301, ["bwrap", "--args", "41"]),
            303: (302, ["/app/bin/element", "--hidden"]),
            304: (300, ["/usr/bin/xdg-open", "x"]),
        }
        self.assertEqual(self.target(processes, 300, "im.riot.Riot", "301 302 im.riot.Riot"), 303)

    def test_an_app_that_is_not_a_flatpak_is_the_process_the_launcher_became_or_the_first_under_its_shell(self):
        self.assertEqual(self.target({400: (1, ["/home/deck/.local/share/nonsteamapps/helium/0.6/helium", "--app=x"])}, 400, ""), 400)
        processes = {
            500: (1, ["/usr/bin/bash", "/opt/app/wrapper"]),
            501: (500, LAUNCHER),
            502: (500, ["/opt/app/app", "--tv"]),
        }
        self.assertEqual(self.target(processes, 500, ""), 502)
        self.assertIsNone(self.target({600: (1, LAUNCHER)}, 600, ""))


class Processes:
    """Real processes that stand in for an app, named as its programs are."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.script = self.folder / "tree.py"
        self.script.write_text(TREE)
        self.lines = []

    def start(self, role, name):
        program = self.folder / name
        _fakes.sleeper(program)
        process = subprocess.Popen([str(program), "-S", str(self.script), role, name, str(self.folder)],
                                   env={**os.environ, "PYTHONHOME": sys.base_prefix})
        self.addCleanup(lambda: (process.kill(), process.wait()))
        self.assertTrue(wait_for(lambda: (self.folder / f"{name}-ready").exists()))
        return process


class CloseTests(Processes, unittest.TestCase):
    def test_the_app_is_asked_to_quit_and_given_time_to_close(self):
        process = self.start("app", "vacuumtube")
        self.assertTrue(sleepwatch.close(process.pid, process.pid, "VacuumTube", grace=5, log=self.lines.append))
        self.assertTrue((self.folder / "vacuumtube-term").exists())
        self.assertEqual(self.lines, ["  closed VacuumTube"])

    def test_an_app_that_does_not_quit_is_left_once_the_grace_is_over(self):
        process = self.start("stubborn", "jellyfin")
        started = time.monotonic()
        self.assertFalse(sleepwatch.close(process.pid, process.pid, "Jellyfin", grace=0.3, log=self.lines.append))
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(wait_for(lambda: (self.folder / "jellyfin-term").exists()))
        self.assertEqual(self.lines, ["  Jellyfin did not close within 0.3 seconds"])

    def test_nothing_to_close_is_said(self):
        self.assertFalse(sleepwatch.close(os.getpid(), None, "VLC", log=self.lines.append))
        self.assertEqual(self.lines, ["  VLC could not be found to close"])


def strings(body: bytes, count: int):
    found, offset = [], 0
    for _ in range(count):
        offset += -offset % 4
        (length,) = struct.unpack_from("<I", body, offset)
        found.append(body[offset + 4:offset + 4 + length].decode())
        offset += 4 + length + 1
    return found


class FakeLogind(threading.Thread):
    """Owns logind's name on a test bus: hands out delay locks and sends the announcements a test asks for."""

    def __init__(self, address):
        super().__init__(daemon=True)
        self.connection = appmenu.Connection(address, unix_fds=True)
        self.connection.bus("Hello")
        name = bytes(appmenu.Writer().string(sleepwatch.LOGIN).uint32(appmenu.DO_NOT_QUEUE).data)
        assert appmenu.uint32(self.connection.bus("RequestName", "su", name)) == appmenu.PRIMARY_OWNER
        self.inhibits, self.locks = [], []
        self.outbox, self.stopping = queue.Queue(), threading.Event()

    def stop(self):
        self.stopping.set()
        self.join(10)
        for lock in self.locks:
            lock.close()
        self.connection.close()

    def announce(self, member, value):
        self.outbox.put((member, value))

    def released(self, index=0, timeout=10.0):
        lock = self.locks[index]
        lock.settimeout(timeout)
        try:
            return lock.recv(1) == b""
        except socket.timeout:
            return False

    def run(self):
        while not self.stopping.is_set():
            while not self.outbox.empty():
                member, value = self.outbox.get()
                fields = {appmenu.PATH: sleepwatch.LOGIN_PATH, appmenu.INTERFACE: sleepwatch.MANAGER, appmenu.MEMBER: member, appmenu.SIGNATURE: "b"}
                self.connection.send(appmenu.SIGNAL, fields, bytes(appmenu.Writer().uint32(1 if value else 0).data))
            if self.connection.pending or select.select([self.connection.socket], [], [], 0.01)[0]:
                for message in self.connection.messages():
                    self.answer(message)

    def answer(self, call):
        if call.kind != appmenu.METHOD_CALL:
            return
        fields = {appmenu.REPLY_SERIAL: call.serial, appmenu.DESTINATION: call.fields[appmenu.SENDER]}
        if call.fields.get(appmenu.MEMBER) != "Inhibit":
            self.connection.send(appmenu.ERROR, {**fields, appmenu.ERROR_NAME: "org.freedesktop.DBus.Error.UnknownMethod"})
            return
        self.inhibits.append(strings(call.body, 4))
        ours, theirs = socket.socketpair()
        self.locks.append(ours)
        self.connection.serial += 1
        reply = appmenu.encode(appmenu.METHOD_RETURN, self.connection.serial, {**fields, appmenu.SIGNATURE: "h", appmenu.UNIX_FDS: 1},
                               bytes(appmenu.Writer().uint32(0).data))
        self.connection.socket.sendmsg([reply], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", theirs.fileno()))])
        theirs.close()


@unittest.skipUnless(shutil.which("dbus-daemon"), "needs dbus-daemon")
class BusTests(Processes, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.address = str(self.folder / "bus")
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", f"--address=unix:path={self.address}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (daemon.terminate(), daemon.wait(timeout=10)))
        self.assertTrue(wait_for(lambda: Path(self.address).exists()))
        self.environ = {"DBUS_SYSTEM_BUS_ADDRESS": f"unix:path={self.address}"}
        self.fake = _fakes.FakeFlatpak(self.folder)
        patch = mock.patch.dict(os.environ, self.fake.env)
        patch.start()
        self.addCleanup(patch.stop)

    def logind(self):
        fake = FakeLogind(self.address)
        fake.start()
        self.addCleanup(fake.stop)
        return fake

    def flatpak_tree(self):
        """bubblewrap, the shell of the app's start script, and the app, as a Flatpak runs VacuumTube."""
        argv = []
        for name in ("bwrap", "sh", "vacuumtube"):
            _fakes.sleeper(self.folder / name)
        for role, name in (("wrapper", "bwrap"), ("wrapper", "sh"), ("app", "vacuumtube")):
            argv += [str(self.folder / name), "-S", str(self.script), role, name, str(self.folder)]
        process = subprocess.Popen(argv, env={**os.environ, "PYTHONHOME": sys.base_prefix})
        self.addCleanup(lambda: (process.kill(), process.wait()))
        self.assertTrue(wait_for(lambda: (self.folder / "vacuumtube-ready").exists()))
        sandbox = int((self.folder / "bwrap-child").read_text())
        os.environ["FAKE_FLATPAK_PS"] = f"{process.pid} {sandbox} rocks.shy.VacuumTube"
        return process

    def follow(self, pid, app_id="rocks.shy.VacuumTube", grace=5.0):
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("closed", sleepwatch.follow(
            pid, app_id, "VacuumTube", LAUNCHER, environ=self.environ, grace=grace, flatpak=self.fake.command, log=self.lines.append)))
        thread.start()
        self.addCleanup(thread.join, 15)
        return thread, result

    def test_a_delay_lock_is_held_and_the_app_closes_when_logind_announces_sleep(self):
        logind = self.logind()
        tree = self.flatpak_tree()
        thread, result = self.follow(tree.pid)
        self.assertTrue(wait_for(lambda: logind.inhibits))
        self.assertEqual(logind.inhibits, [["sleep:shutdown", "NonSteamApps", "Closes VacuumTube first", "delay"]])
        logind.announce("PrepareForSleep", False)
        time.sleep(0.3)
        self.assertFalse((self.folder / "vacuumtube-term").exists())
        logind.announce("PrepareForSleep", True)
        thread.join(15)
        self.assertEqual(result, {"closed": True})
        self.assertTrue((self.folder / "vacuumtube-term").exists())
        self.assertFalse((self.folder / "bwrap-term").exists())
        self.assertFalse((self.folder / "sh-term").exists())
        self.assertTrue(logind.released())
        self.assertEqual(self.lines, ["  closing VacuumTube: the Steam Machine sleeps", "  closed VacuumTube"])

    def test_a_shutdown_closes_the_app_too(self):
        logind = self.logind()
        tree = self.flatpak_tree()
        thread, result = self.follow(tree.pid)
        self.assertTrue(wait_for(lambda: logind.inhibits))
        logind.announce("PrepareForShutdown", True)
        thread.join(15)
        self.assertEqual(result, {"closed": True})
        self.assertEqual(self.lines[0], "  closing VacuumTube: the Steam Machine shuts down")

    def test_an_app_that_ends_by_itself_lets_the_lock_go(self):
        logind = self.logind()
        process = self.start("app", "vlc")
        thread, result = self.follow(process.pid, app_id="")
        self.assertTrue(wait_for(lambda: logind.inhibits))
        process.terminate()
        process.wait()
        thread.join(15)
        self.assertEqual(result, {"closed": False})
        self.assertTrue(logind.released())
        self.assertEqual(self.lines, [])

    def test_without_logind_the_app_is_left_alone(self):
        process = self.start("app", "discord")
        thread, result = self.follow(process.pid, app_id="")
        thread.join(15)
        self.assertEqual(result, {"closed": False})
        self.assertEqual(len(self.lines), 1)
        self.assertTrue(self.lines[0].startswith("  cannot close VacuumTube before sleep: "))
        self.assertIsNone(process.poll())

    def test_without_a_system_bus_the_app_is_left_alone(self):
        lines = []
        self.assertFalse(sleepwatch.follow(os.getpid(), "", "VLC", LAUNCHER, environ={"DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent/bus"},
                                           log=lines.append))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("  cannot close VLC before sleep: "))


if __name__ == "__main__":
    unittest.main()
