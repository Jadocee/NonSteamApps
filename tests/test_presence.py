import contextlib
import io
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _fakes
import _paths  # noqa: F401
from nonsteamapps import presence

LOCALCONFIG = '"UserLocalConfigStore"\n{\n\t"friends"\n\t{\n\t\t"VoiceReceiveVolume"\t\t"0"\n\t\t"PersonaStateDesired"\t\t"%s"\n\t}\n}\n'


class SettingTests(unittest.TestCase):
    def test_every_app_by_default_none_when_off_or_only_those_listed(self):
        for value in (None, "all", " ALL ", "1", "yes"):
            self.assertTrue(presence.applies(value, "youtube"), value)
        for value in ("", "off", "0", "no", "none"):
            self.assertFalse(presence.applies(value, "youtube"), value)
        self.assertTrue(presence.applies("eden, EdenNX2 kytyps5", "edennx2"))
        self.assertFalse(presence.applies("eden edennx2 kytyps5", "youtube"))

    def test_the_status_chosen_last_comes_from_localconfig(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "localconfig.vdf"
            self.assertIsNone(presence.desired_state(path))
            for written, read in (("7", 7), ("3", 3), ("1", 1), ("x", None)):
                path.write_text(LOCALCONFIG % written)
                self.assertEqual(presence.desired_state(path), read)
            path.write_text('"userlocalconfigstore" { "Friends" { "personastatedesired" "0" } }')
            self.assertEqual(presence.desired_state(path), 0)
            path.write_text('"UserLocalConfigStore" { "friends" { } }')
            self.assertIsNone(presence.desired_state(path))
            path.write_text('"UserLocalConfigStore" {')
            self.assertIsNone(presence.desired_state(path))
        self.assertEqual([presence.status_name(state) for state in (presence.AWAY, presence.ONLINE, None, 4)], ["away", "online", "online", "online"])

    def test_a_process_counts_until_it_has_ended(self):
        child = subprocess.Popen(["sleep", "30"])
        begun = presence.started(child.pid)
        self.assertTrue(begun and begun.isdigit())
        self.assertEqual(presence.started(child.pid), begun)
        child.kill()
        child.wait()
        self.assertIsNone(presence.started(child.pid))
        self.assertIsNotNone(presence.started(os.getpid()))


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.localconfig = Path(self.tmp.name) / "localconfig.vdf"
        self.steam = _fakes.FakeSteam(Path(self.tmp.name))
        patch = mock.patch.dict(os.environ, self.steam.env)
        patch.start()
        self.addCleanup(patch.stop)
        self.keeper = presence.Presence(self.state, self.localconfig, self.steam.command)
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app.kill()
            app.wait()

    def app(self, seconds="30"):
        process = subprocess.Popen(["sleep", seconds])
        self.apps.append(process)
        return process

    def end(self, process):
        process.kill()
        process.wait()

    def record(self):
        return json.loads((self.state / "presence.json").read_text())

    def test_the_first_app_hides_the_account_and_the_last_one_to_close_brings_it_back(self):
        first, second = self.app(), self.app()
        invisible, message = self.keeper.hide(first.pid)
        self.assertTrue(invisible)
        self.assertIn("making the Steam account invisible", message)
        self.assertEqual(self.keeper.hide(second.pid), (False, None))
        self.assertEqual([app["pid"] for app in self.record()["apps"]], [first.pid, second.pid])
        self.end(first)
        self.assertIsNone(self.keeper.release(first.pid))
        self.assertEqual(self.steam.statuses(timeout=0), [])
        self.assertEqual(self.keeper.release(second.pid), "set the Steam account back to online")
        self.assertEqual(self.steam.calls(), [["-ifrunning", "steam://friends/status/online"]])
        self.assertEqual({key: value for key, value in self.record().items() if key != "restored"}, {"previous": None, "changed": False})

    def test_an_app_started_just_after_the_status_came_back_uses_it_rather_than_localconfig(self):
        self.localconfig.write_text(LOCALCONFIG % "3")
        app = self.app()
        self.assertTrue(self.keeper.hide(app.pid)[0])
        self.assertEqual(self.keeper.release(app.pid), "set the Steam account back to away")
        self.localconfig.write_text(LOCALCONFIG % "7")
        again = self.app()
        self.assertTrue(self.keeper.hide(again.pid)[0])
        self.assertEqual(self.record()["previous"], 3)
        self.keeper.release(again.pid)
        record = self.record()
        record["restored"] -= presence.RECENT
        (self.state / "presence.json").write_text(json.dumps(record))
        later = self.app()
        self.assertEqual(self.keeper.hide(later.pid), (False, "the Steam account is already invisible or offline, so friends cannot see the app"))

    def test_an_account_already_invisible_or_offline_is_left_alone_and_away_comes_back_as_away(self):
        for state in ("7", "0"):
            self.localconfig.write_text(LOCALCONFIG % state)
            app = self.app()
            self.assertEqual(self.keeper.hide(app.pid), (False, "the Steam account is already invisible or offline, so friends cannot see the app"))
            self.assertIsNone(self.keeper.release(app.pid))
        self.assertEqual(self.steam.calls(), [])
        self.localconfig.write_text(LOCALCONFIG % "3")
        app = self.app()
        self.assertTrue(self.keeper.hide(app.pid)[0])
        self.assertEqual(self.keeper.release(app.pid), "set the Steam account back to away")

    def test_after_apps_ended_without_a_word_the_status_they_replaced_still_comes_back(self):
        self.localconfig.write_text(LOCALCONFIG % "3")
        lost = self.app()
        self.assertTrue(self.keeper.hide(lost.pid)[0])
        self.end(lost)
        self.localconfig.write_text(LOCALCONFIG % "7")
        later = self.app()
        self.assertEqual(self.keeper.hide(later.pid), (False, None))
        self.assertEqual([app["pid"] for app in self.record()["apps"]], [later.pid])
        self.assertEqual(self.keeper.release(later.pid), "set the Steam account back to away")

    def test_without_the_steam_command_nothing_is_changed(self):
        keeper = presence.Presence(self.state, None)
        app = self.app()
        with mock.patch("nonsteamapps.presence.steamclient.command", return_value=None):
            self.assertEqual(keeper.hide(app.pid), (False, "the steam command was not found, so friends see the app"))
            self.assertIsNone(keeper.release(app.pid))
            self.assertFalse(keeper.send("online"))

    def test_the_watcher_hides_the_account_then_brings_it_back_when_the_app_ends_or_steam_stops_it(self):
        app = self.app("0.3")
        with contextlib.redirect_stdout(io.StringIO()):
            watcher = self.keeper.watch(app.pid, self.keeper.hide(app.pid)[0])
        app.wait()
        self.assertEqual(os.waitpid(watcher, 0)[1], 0)
        self.assertEqual(self.steam.statuses(), ["invisible", "online"])
        app = self.app()
        with contextlib.redirect_stdout(io.StringIO()):
            watcher = self.keeper.watch(app.pid, self.keeper.hide(app.pid)[0])
        self.assertEqual(self.steam.statuses(count=3)[2:], ["invisible"])
        time.sleep(0.2)
        os.kill(watcher, signal.SIGTERM)
        self.assertEqual(os.waitpid(watcher, 0)[1], 0)
        self.assertEqual(self.steam.statuses(), ["invisible", "online", "invisible", "online"])
        self.assertIsNone(app.poll())


if __name__ == "__main__":
    unittest.main()
