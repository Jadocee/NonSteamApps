import json
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from nonsteamapps import remote


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "config" / remote.FILE
        self.record = Path(self.tmp.name) / "state" / remote.RECORD

    def test_only_the_remote_stays_and_an_uninstall_puts_back_what_was_there(self):
        self.assertEqual(remote.remote_only(self.settings, self.record, force=False), ["EnableJoystick", "EnableEvdev"])
        self.assertEqual(self.settings.read_text(), "[General]\nEnableJoystick=false\nEnableEvdev=false\n")
        self.assertEqual(json.loads(self.record.read_text()), {"EnableJoystick": None, "EnableEvdev": None})
        self.assertEqual(remote.remote_only(self.settings, self.record, force=True), [])
        self.assertTrue(remote.restore(self.settings, self.record))
        self.assertEqual(self.settings.read_text(), "[General]\n")
        self.assertFalse(self.record.exists())
        self.assertFalse(remote.restore(self.settings, self.record))

    def test_an_update_keeps_a_backend_the_user_named_and_an_install_turns_it_off(self):
        self.settings.parent.mkdir()
        self.settings.write_text("[General]\nEnableCEC=true\nEnableJoystick=true\n\n[Mapping]\nButtonUp=1\n")
        self.assertEqual(remote.remote_only(self.settings, self.record, force=False), ["EnableEvdev"])
        self.assertIn("EnableJoystick=true\n", self.settings.read_text())
        self.assertEqual(remote.remote_only(self.settings, self.record, force=True), ["EnableJoystick"])
        self.assertEqual(self.settings.read_text(),
                         "[General]\nEnableCEC=true\nEnableJoystick=false\nEnableEvdev=false\n\n[Mapping]\nButtonUp=1\n")
        self.assertEqual(json.loads(self.record.read_text()), {"EnableJoystick": "true", "EnableEvdev": None})
        self.settings.write_text(self.settings.read_text().replace("EnableEvdev=false", "EnableEvdev=true"))
        self.assertTrue(remote.restore(self.settings, self.record))
        self.assertEqual(self.settings.read_text(), "[General]\nEnableCEC=true\nEnableJoystick=true\nEnableEvdev=true\n\n[Mapping]\nButtonUp=1\n")

    def test_the_service_counts_only_where_its_unit_is_installed(self):
        units = Path(self.tmp.name) / "units"
        self.assertFalse(remote.present([units]))
        units.mkdir()
        (units / remote.UNIT).write_text("[Unit]\n")
        self.assertTrue(remote.present([Path(self.tmp.name) / "none", units]))


if __name__ == "__main__":
    unittest.main()
