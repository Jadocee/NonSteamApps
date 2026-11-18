import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _fakes
from nonsteamapps import appmenu, mpris

YOUTUBE = "org.mpris.MediaPlayer2.chromium.instance2"
QUIET = "org.mpris.MediaPlayer2.chromium.instance9"
VLC = "org.mpris.MediaPlayer2.vlc"


def wait_for(condition, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class WireTests(unittest.TestCase):
    def test_a_reader_takes_an_array_of_strings_and_a_variants_value(self):
        names = [b"org.freedesktop.DBus", b":1.7", b"org.mpris.MediaPlayer2.vlc"]
        array = b""
        for name in names:
            array += bytes(-len(array) % 4) + struct.pack("<I", len(name)) + name + b"\0"
        self.assertEqual(appmenu.Reader(struct.pack("<I", len(array)) + array).strings(), [name.decode() for name in names])
        self.assertEqual(appmenu.Reader(struct.pack("<I", 0)).strings(), [])
        status = b"\x01s\x00\x00" + struct.pack("<I", 7) + b"Playing\0"
        self.assertEqual(appmenu.Reader(status).variant("s").string(), "Playing")
        self.assertIsNone(appmenu.Reader(status).variant("q"))
        with self.assertRaises(appmenu.UNREADABLE):
            appmenu.Reader(status[:-1]).variant("s").string()


@unittest.skipUnless(shutil.which("dbus-daemon"), "needs dbus-daemon")
class PlayersTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.address = str(self.folder / "bus")
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--nopidfile", f"--address=unix:path={self.address}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(daemon.wait, 10)
        self.addCleanup(daemon.terminate)
        self.assertTrue(wait_for(lambda: Path(self.address).exists()))
        self.connection = appmenu.Connection(self.address)
        self.addCleanup(self.connection.close)
        self.connection.bus("Hello")
        self.lines = []

    def media(self, *players, wrapped=False):
        process = _fakes.media_players(self.folder, self.address, *players, wrapped=wrapped)
        self.addCleanup(_fakes.stop_media, process)
        return process

    def test_only_the_apps_own_players_are_paused_and_only_while_they_play(self):
        app = self.media(f"{YOUTUBE}=Playing", f"{QUIET}=Paused", wrapped=True)
        self.media(f"{VLC}=Playing")
        players = mpris.Players(app.pid, "YouTube")
        self.assertEqual(players.names(self.connection), [YOUTUBE, QUIET])
        self.assertEqual(players.pause(self.connection, "the TV switched to 2.0.0.0", self.lines.append), 1)
        self.assertEqual(players.pause(self.connection, "the TV is turning off", self.lines.append), 0)
        self.assertEqual(_fakes.paused(self.folder), [YOUTUBE])
        self.assertEqual(mpris.status(self.connection, VLC), "Playing")
        self.assertEqual(self.lines, ["  the TV switched to 2.0.0.0; paused YouTube", "  the TV is turning off; YouTube was not playing"])

    def test_an_app_without_a_player_was_not_playing(self):
        self.media(f"{VLC}=Playing")
        app = subprocess.Popen(["sleep", "30"])
        self.addCleanup(app.wait)
        self.addCleanup(app.kill)
        self.assertEqual(mpris.Players(app.pid, "Element").pause(self.connection, "the TV switched to its own apps", self.lines.append), 0)
        self.assertEqual(self.lines, ["  the TV switched to its own apps; Element was not playing"])
        self.assertEqual(_fakes.paused(self.folder), [])

    def test_a_player_that_will_not_pause_is_written_down(self):
        app = self.media("org.mpris.MediaPlayer2.Jellyfin.broken=Playing")
        self.assertEqual(mpris.Players(app.pid, "Jellyfin").pause(self.connection, "the TV is turning off", self.lines.append), 0)
        self.assertEqual(len(self.lines), 1)
        self.assertTrue(self.lines[0].startswith("  the TV is turning off; could not pause Jellyfin: "), self.lines)

    def test_a_player_that_does_not_say_whether_it_plays_is_paused(self):
        app = self.media(f"{YOUTUBE}=Playing")
        players = mpris.Players(app.pid, "YouTube")
        with mock.patch.object(mpris, "status", return_value=None):
            self.assertEqual(players.pause(self.connection, "the TV switched to 3.0.0.0", self.lines.append), 1)
        self.assertEqual(_fakes.paused(self.folder), [YOUTUBE])


if __name__ == "__main__":
    unittest.main()
