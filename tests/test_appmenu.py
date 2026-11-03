import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from nonsteamapps import appmenu

MENU_PATH = "/com/canonical/menu/4200001"


class WireTests(unittest.TestCase):
    def test_a_message_reads_back_as_it_was_written(self):
        body = bytes(appmenu.Writer().uint32(0x4200001).string(MENU_PATH).data)
        fields = {appmenu.PATH: "/com/canonical/AppMenu/Registrar", appmenu.INTERFACE: appmenu.REGISTRAR, appmenu.MEMBER: "RegisterWindow",
                  appmenu.DESTINATION: appmenu.REGISTRAR, appmenu.SIGNATURE: "uo", appmenu.REPLY_SERIAL: 9}
        data = appmenu.encode(appmenu.METHOD_CALL, 7, fields, body, appmenu.NO_REPLY_EXPECTED)
        self.assertEqual(len(data) % 8, len(body) % 8)
        message = appmenu.decode(data + b"next")
        self.assertEqual((message.kind, message.flags, message.serial, message.fields, message.body),
                         (appmenu.METHOD_CALL, appmenu.NO_REPLY_EXPECTED, 7, fields, body))
        self.assertEqual(appmenu.size(data + b"next"), len(data))
        self.assertEqual(appmenu.uint32(message), 0x4200001)
        self.assertIsNone(appmenu.decode(data[:-1]))
        self.assertIsNone(appmenu.decode(data[:15]))

    def test_big_endian_messages_are_read_too(self):
        member = b"Ping"
        field = bytes((appmenu.MEMBER, 1)) + b"s\0" + struct.pack(">I", len(member)) + member + b"\0"
        data = b"B" + bytes((appmenu.SIGNAL, 0, 1)) + struct.pack(">III", 4, 3, len(field)) + field
        data += bytes(-len(data) % 8) + struct.pack(">I", 5)
        message = appmenu.decode(data)
        self.assertEqual((message.kind, message.serial, message.fields, appmenu.uint32(message)), (appmenu.SIGNAL, 3, {appmenu.MEMBER: "Ping"}, 5))

    def test_anything_else_is_refused(self):
        with self.assertRaises(ValueError):
            appmenu.size(b"GET / HTTP/1.1\r\n\r\n")
        with self.assertRaises(ValueError):
            appmenu.size(b"l\x01\x00\x01" + struct.pack("<III", appmenu.MAX_MESSAGE, 1, 0))

    def test_the_session_bus_is_found_from_its_address(self):
        cases = (
            ({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}, "/run/user/1000/bus"),
            ({"DBUS_SESSION_BUS_ADDRESS": "tcp:host=localhost,port=1;unix:abstract=/tmp/dbus-a%2Cb,guid=1f"}, "\0/tmp/dbus-a,b"),
            ({"DBUS_SESSION_BUS_ADDRESS": "tcp:host=localhost,port=1", "XDG_RUNTIME_DIR": "/run/user/1001"}, "/run/user/1001/bus"),
            ({}, None),
        )
        for environ, expected in cases:
            with self.subTest(environ=environ):
                self.assertEqual(appmenu.session_bus(environ), expected)

    def test_without_a_bus_nothing_is_done(self):
        self.assertFalse(appmenu.stand_in(lambda: True, environ={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}))
        self.assertFalse(appmenu.stand_in(lambda: True, environ={}))


@unittest.skipUnless(shutil.which("dbus-daemon"), "needs dbus-daemon")
class BusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "bus"
        self.daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", f"--address=unix:path={path}"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_daemon)
        deadline = time.monotonic() + 10
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.environ = {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={path}"}
        self.client = appmenu.Connection(str(path))
        self.addCleanup(self.client.close)
        self.client.bus("Hello")

    def stop_daemon(self):
        self.daemon.terminate()
        self.daemon.wait(timeout=10)

    def owner(self):
        return self.client.bus("GetNameOwner", "s", bytes(appmenu.Writer().string(appmenu.REGISTRAR).data))

    def registrar(self, member, signature, body):
        return self.client.call(appmenu.REGISTRAR, "/com/canonical/AppMenu/Registrar", appmenu.REGISTRAR, member, signature, body)

    def test_the_stand_in_owns_the_name_answers_apps_and_lets_go_when_told(self):
        alive, ready, result = threading.Event(), threading.Event(), []
        alive.set()
        thread = threading.Thread(target=lambda: result.append(appmenu.stand_in(alive.is_set, ready.set, self.environ, 0.02)))
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(alive.clear)
        self.assertTrue(ready.wait(10))
        self.assertEqual(self.owner().kind, appmenu.METHOD_RETURN)
        reply = self.registrar("RegisterWindow", "uo", bytes(appmenu.Writer().uint32(0x4200001).string(MENU_PATH).data))
        self.assertEqual((reply.kind, reply.body), (appmenu.METHOD_RETURN, b""))
        self.assertEqual(self.registrar("UnregisterWindow", "u", bytes(appmenu.Writer().uint32(0x4200001).data)).kind, appmenu.METHOD_RETURN)
        with self.assertRaises(OSError):
            self.registrar("GetMenuForWindow", "u", bytes(appmenu.Writer().uint32(0x4200001).data))
        self.assertFalse(appmenu.stand_in(lambda: True, environ=self.environ))
        alive.clear()
        thread.join(10)
        self.assertEqual(result, [True])
        with self.assertRaises(OSError):
            self.owner()

    def test_a_helper_stands_in_while_the_app_runs(self):
        app = subprocess.Popen(["sleep", "30"])
        self.addCleanup(app.kill)
        with mock.patch.dict(os.environ, self.environ):
            self.assertTrue(appmenu.watch(app.pid))
        self.assertEqual(self.owner().kind, appmenu.METHOD_RETURN)
        app.kill()
        app.wait()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                self.owner()
            except OSError:
                break
            time.sleep(0.05)
        else:
            self.fail("the helper kept the name after the app exited")


if __name__ == "__main__":
    unittest.main()
