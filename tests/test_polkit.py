import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
import _paths
from nonsteamapps import polkit

POLICY = _paths.ROOT / "src" / "share" / "bitwarden" / "com.bitwarden.Bitwarden.policy"


class PolicyTests(unittest.TestCase):
    def test_bitwardens_policy_defines_the_action_it_asks_polkit_for_with_the_users_own_password(self):
        self.assertEqual(polkit.action_id(POLICY), "com.bitwarden.Bitwarden.unlock")
        text = POLICY.read_text()
        for line in ("<allow_any>no</allow_any>", "<allow_inactive>no</allow_inactive>", "<allow_active>auth_self</allow_active>"):
            self.assertIn(line, text)
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.policy"
            empty.write_text("<policyconfig/>")
            with self.assertRaises(ValueError):
                polkit.action_id(empty)


class LocalActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "etc" / "polkit-1" / "actions"
        patcher = mock.patch.dict(os.environ, {polkit.VARIABLE: str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.action = _fakes.fake_polkit(POLICY)

    def test_the_action_goes_into_the_local_folder_through_sudo_and_comes_out_again(self):
        self.assertEqual(self.action.path, self.folder / "com.bitwarden.Bitwarden.policy")
        self.assertFalse(self.action.present())
        self.action.install()
        self.assertEqual(self.action.path.read_text(), POLICY.read_text())
        self.assertEqual(self.action.path.stat().st_mode & 0o777, 0o644)
        self.assertTrue(self.action.present())
        self.action.remove()
        self.assertFalse(self.action.path.exists())
        self.action.remove()

    def test_without_a_password_the_command_to_run_is_given(self):
        with mock.patch.dict(os.environ, {"FAKE_SUDO_FAIL": "1"}), self.assertRaises(polkit.PolkitError) as raised:
            self.action.install()
        self.assertEqual(str(raised.exception), "sudo: a password is required")
        self.assertEqual(raised.exception.commands, [f"sudo install -D -m 644 {POLICY} {self.action.path}"])
        self.assertFalse(self.action.present())

    def test_an_action_the_system_ships_counts_as_present(self):
        system = self.root / "usr" / "share" / "polkit-1" / "actions"
        system.mkdir(parents=True)
        (system / POLICY.name).write_text("<policyconfig/>")
        self.assertEqual(self.action.system, system)
        self.assertTrue(self.action.present())
        self.assertFalse(self.action.path.exists())

    def test_polkit_126_and_later_read_the_local_folder(self):
        for version, reads in (("124", False), ("125", False), ("126", True), ("127", True), ("128", True)):
            with self.subTest(version), mock.patch.dict(os.environ, {"FAKE_PKACTION_VERSION": version}):
                self.assertEqual(self.action.version(), int(version))
                self.assertEqual(self.action.reads_local(), reads)
        self.assertIsNone(polkit.Polkit(POLICY, pkaction="nonsteamapps-no-pkaction").reads_local())
        with mock.patch("nonsteamapps.polkit.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "pkaction\n", "")):
            self.assertIsNone(self.action.version())
        with mock.patch("nonsteamapps.polkit.subprocess.run", side_effect=OSError("gone")):
            self.assertIsNone(self.action.version())

    def test_the_folders_are_the_systems_own_unless_the_variable_names_another_root(self):
        with mock.patch.dict(os.environ, {polkit.VARIABLE: ""}):
            action = polkit.Polkit(POLICY)
        self.assertEqual(action.path, Path("/etc/polkit-1/actions/com.bitwarden.Bitwarden.policy"))
        self.assertEqual(action.system, Path("/usr/share/polkit-1/actions"))


class DesktopProxyTests(unittest.TestCase):
    def test_the_host_runs_bitwardens_own_proxy_in_its_flatpak_with_the_browsers_streams(self):
        script = _paths.ROOT / "src" / "share" / "bitwarden" / "desktop-proxy"
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            log = bin_dir / "args"
            (bin_dir / "flatpak").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\nexec cat\n')
            (bin_dir / "flatpak").chmod(0o755)
            result = subprocess.run([str(script), "chrome-extension://nngceckbapebfimnlniiiahkandclblb/"], input=b"\x05\x00\x00\x00hello",
                                    capture_output=True, env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, timeout=30, check=True)
            self.assertEqual(result.stdout, b"\x05\x00\x00\x00hello")
            self.assertEqual(log.read_text().splitlines(), ["run", "--command=/app/Bitwarden/desktop_proxy", "com.bitwarden.desktop",
                                                            "chrome-extension://nngceckbapebfimnlniiiahkandclblb/"])


if __name__ == "__main__":
    unittest.main()
