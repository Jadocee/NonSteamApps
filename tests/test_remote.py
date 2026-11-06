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


class CecdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config"
        self.fragment = self.config / remote.CECD_FRAGMENT
        self.record = Path(self.tmp.name) / "state" / remote.CECD_RECORD

    def test_the_mappings_keep_cecds_own_but_the_tv_menus_whose_keys_tvs_leave_pressed(self):
        names = dict(remote.CECD_MAPPINGS)
        self.assertEqual(len(names), len(remote.CECD_MAPPINGS))
        self.assertFalse(set(names) & set(remote.CECD_LEFT_OUT))
        self.assertEqual({name: names[name] for name in ("select", "up", "down", "left", "right", "back", "play", "pause", "f1")},
                         {"select": 28, "up": 103, "down": 108, "left": 105, "right": 106, "back": 1, "play": 200, "pause": 201, "f1": 401})
        self.assertEqual((len(names), len(remote.CECD_LEFT_OUT)), (60, 14))
        self.assertIn("device-root-menu", remote.CECD_LEFT_OUT)
        text = remote.cecd_fragment()
        self.assertTrue(text.startswith("# NonSteamApps: "))
        self.assertIn('[mappings]\n"select" = 28\n', text)
        self.assertNotIn("root-menu", text)
        try:
            import tomllib
        except ImportError:
            return
        self.assertEqual(tomllib.loads(text), {"mappings": names})

    def test_an_install_writes_the_mappings_an_update_keeps_what_the_user_changed_and_an_uninstall_removes_them(self):
        self.assertTrue(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.assertEqual(self.fragment.read_text(), remote.cecd_fragment())
        self.assertFalse(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.fragment.unlink()
        self.assertFalse(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.assertFalse(self.fragment.exists())
        self.assertTrue(remote.leave_out_tv_menus(self.config, self.record, force=True))
        self.fragment.write_text(remote.cecd_fragment() + '"device-root-menu" = 618\n')
        self.assertFalse(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.assertFalse(remote.restore_cecd(self.config, self.record))
        self.assertTrue(self.fragment.exists())
        self.assertTrue(remote.leave_out_tv_menus(self.config, self.record, force=True))
        self.assertTrue(remote.restore_cecd(self.config, self.record))
        self.assertFalse(self.fragment.exists() or self.record.exists())
        self.assertFalse(remote.restore_cecd(self.config, self.record))

    def test_an_update_writes_the_mappings_of_a_newer_nonsteamapps_but_not_over_a_file_it_did_not_write(self):
        self.fragment.parent.mkdir(parents=True)
        self.fragment.write_text("[mappings]\nup = 103\n")
        self.assertFalse(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.assertEqual(self.fragment.read_text(), "[mappings]\nup = 103\n")
        older = "[mappings]\nselect = 28\n"
        self.fragment.write_text(older)
        self.record.parent.mkdir(parents=True)
        self.record.write_text(json.dumps({"sha256": remote._digest(older)}))
        self.assertTrue(remote.leave_out_tv_menus(self.config, self.record, force=False))
        self.assertEqual(self.fragment.read_text(), remote.cecd_fragment())

    def test_cecd_counts_only_where_its_unit_is_installed(self):
        units = Path(self.tmp.name) / "units"
        self.assertFalse(remote.cecd_present([units]))
        units.mkdir()
        (units / remote.CECD_UNIT).write_text("[Unit]\n")
        self.assertTrue(remote.cecd_present([units]))
        self.assertFalse(remote.present([units]))


if __name__ == "__main__":
    unittest.main()
