import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
import _paths  # noqa: F401
from nonsteamapps import builds, kyty

TAG = _fakes.KYTY_TAG
OLDER = "KytyPS5-2026-10-30-0123abc"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = _fakes.make_kyty_archive(Path(self.tmp.name))

    def test_the_newest_release_with_a_linux_build_is_chosen(self):
        windows_only = {"tag_name": "KytyPS5-2026-11-03-1111111", "assets": [{"name": "KytyPS5-2026-11-03-1111111-Windows-x64.zip"}]}
        releases = [{"draft": True, "tag_name": "KytyPS5-2026-11-04-2222222"}, {"prerelease": True, "tag_name": "KytyPS5-2026-11-04-3333333"},
                    {"tag_name": "nightly"}, windows_only, _fakes.kyty_release(self.archive), _fakes.kyty_release(self.archive, OLDER)]
        build = kyty.newest_build(releases)
        self.assertEqual((build.tag, build.size, build.published), (TAG, self.archive.stat().st_size, "2026-11-02T08:00:00Z"))
        self.assertTrue(build.url.startswith("https://github.com/KytyPS5/KytyPS5/releases/download/"))
        self.assertEqual(kyty.describe(TAG), "2026-11-02 (dfec14a)")

    def test_a_build_without_githubs_checksum_or_from_elsewhere_is_refused(self):
        for digest in ("", "md5:0123", "sha256:XYZ", None):
            with self.subTest(digest=digest):
                release = _fakes.kyty_release(self.archive)
                release["assets"][1]["digest"] = digest
                with self.assertRaisesRegex(kyty.KytyError, "no SHA-256"):
                    kyty.newest_build([release])
        release = _fakes.kyty_release(self.archive)
        release["assets"][1]["browser_download_url"] = "https://example.org/kyty.tar.gz"
        with self.assertRaisesRegex(kyty.KytyError, "not among"):
            kyty.newest_build([release])
        with self.assertRaisesRegex(kyty.KytyError, "has a Linux build"):
            kyty.newest_build([])

    def test_an_unpacked_build_may_only_hold_files_folders_and_links_inside_it(self):
        root = Path(self.tmp.name) / "tree"
        (root / "lib").mkdir(parents=True)
        (root / "lib" / "libfoo.so.1").write_text("")
        os.symlink("libfoo.so.1", root / "lib" / "libfoo.so")
        kyty.check_tree(root)
        for target in ("../../outside", "/etc/passwd"):
            with self.subTest(target=target):
                os.symlink(target, root / "lib" / "escape")
                with self.assertRaises(kyty.KytyError):
                    kyty.check_tree(root)
                (root / "lib" / "escape").unlink()
        os.mkfifo(root / "pipe")
        with self.assertRaisesRegex(kyty.KytyError, "neither a file nor a folder"):
            kyty.check_tree(root)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.runtime = kyty.Runtime(self.dir / "kytyps5")
        self.archives = {tag: _fakes.make_kyty_archive(self.dir / tag, tag) for tag in (TAG, OLDER)}
        self.releases = [_fakes.kyty_release(self.archives[TAG])]
        patches = [
            mock.patch("nonsteamapps.builds.net.fetch_text", side_effect=lambda url, accept="": json.dumps(self.releases)),
            mock.patch("nonsteamapps.builds.net.download", side_effect=self.download),
            mock.patch("nonsteamapps.builds.platform.machine", return_value="x86_64"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.downloads = []

    def download(self, url, target):
        self.downloads.append(url)
        shutil.copyfile(self.archives[url.rsplit("/", 2)[-2]], target)

    def test_the_newest_build_is_downloaded_checked_unpacked_and_made_current(self):
        self.assertEqual(self.runtime.install(), TAG)
        self.assertEqual(self.runtime.current(), TAG)
        build = self.runtime.root / TAG
        self.assertTrue(os.access(build / kyty.LAUNCHER, os.X_OK))
        self.assertEqual(json.loads((build / builds.BUILD_RECORD).read_text())["published"], "2026-11-02T08:00:00Z")
        self.assertFalse(self.runtime.downloads.exists())
        self.assertEqual(self.runtime.install(), TAG)
        self.assertEqual(len(self.downloads), 1)
        self.assertIsNone(self.runtime.update())

    def test_a_download_that_does_not_match_githubs_checksum_is_not_installed(self):
        self.releases = [_fakes.kyty_release(self.archives[TAG], digest="sha256:" + "f" * 64)]
        with self.assertRaisesRegex(kyty.KytyError, "does not match"):
            self.runtime.install()
        self.assertIsNone(self.runtime.current())
        self.assertEqual(self.runtime.versions(), [])

    def test_a_failed_download_is_reported_as_kytyps5s_own_error(self):
        with mock.patch("nonsteamapps.builds.net.download", side_effect=OSError("connection reset")):
            with self.assertRaisesRegex(kyty.KytyError, "could not download .*connection reset"):
                self.runtime.install()
        self.assertIsNone(self.runtime.current())

    def test_only_x86_64_is_supported(self):
        with mock.patch("nonsteamapps.builds.platform.machine", return_value="aarch64"), self.assertRaisesRegex(kyty.KytyError, "x86-64"):
            self.runtime.install()

    def test_updates_keep_the_build_before_for_a_rollback_and_prune_older_ones(self):
        self.releases = [_fakes.kyty_release(self.archives[OLDER], OLDER, "2026-10-30T08:00:00Z")]
        self.runtime.install()
        self.releases = [_fakes.kyty_release(self.archives[TAG])]
        self.assertEqual(self.runtime.update(), TAG)
        self.assertEqual(self.runtime.versions(), [TAG, OLDER])
        self.assertEqual(self.runtime.rollback(), OLDER)
        self.assertEqual(self.runtime.current(), OLDER)
        self.assertEqual(self.runtime.update(), TAG)
        third = "KytyPS5-2026-11-03-4444444"
        self.archives[third] = _fakes.make_kyty_archive(self.dir / third, third)
        self.releases = [_fakes.kyty_release(self.archives[third], third, "2026-11-03T08:00:00Z")]
        self.assertEqual(self.runtime.update(), third)
        self.assertEqual(self.runtime.versions(), [third, TAG])

    def test_an_archive_is_checked_against_github_unless_told_not_to(self):
        self.assertEqual(self.runtime.install(self.archives[TAG]), TAG)
        self.assertEqual(self.downloads, [])
        other = kyty.Runtime(self.dir / "offline")
        with mock.patch("nonsteamapps.builds.net.fetch_text", side_effect=OSError("offline")):
            with self.assertRaisesRegex(kyty.KytyError, "could not read"):
                other.install(self.archives[TAG])
            self.assertEqual(other.install(self.archives[TAG], verify=False), TAG)
        renamed = self.dir / "kyty.tar.gz"
        shutil.copyfile(self.archives[TAG], renamed)
        with self.assertRaisesRegex(kyty.KytyError, "not named like"):
            self.runtime.install(renamed)


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "kytyps5"
        self.runtime = kyty.Runtime(self.root)
        for tag in (TAG, OLDER):
            _fakes.make_kyty_build(self.root / tag)
        self.runtime.activate(TAG)
        self.home = Path(self.tmp.name) / "profiles" / "kytyps5" / "111"

    def test_an_accounts_folder_runs_the_current_build_and_keeps_its_own_data(self):
        launcher = self.runtime.prepare_home(self.home)
        self.assertEqual(launcher, self.home / kyty.LAUNCHER)
        build = self.root / TAG
        for name in (kyty.LAUNCHER, kyty.EMULATOR):
            self.assertFalse((self.home / name).is_symlink())
            self.assertTrue(os.path.samefile(self.home / name, build / name))
        self.assertEqual({os.readlink(self.home / name) for name in ("lib", "plugins", "qt.conf")},
                         {str(build / name) for name in ("lib", "plugins", "qt.conf")})
        self.assertFalse(os.path.lexists(self.home / kyty.UPDATER))
        (self.home / "_SaveData").mkdir()
        (self.home / kyty.SETTINGS_FILE).write_text("[MainDialog]\n")
        (self.home / "notes.txt").write_text("mine")
        self.runtime.activate(OLDER)
        (self.root / OLDER / "qt.conf").unlink()
        self.runtime.prepare_home(self.home)
        self.assertTrue(os.path.samefile(self.home / kyty.EMULATOR, self.root / OLDER / kyty.EMULATOR))
        self.assertEqual(os.readlink(self.home / "lib"), str(self.root / OLDER / "lib"))
        self.assertFalse(os.path.lexists(self.home / "qt.conf"))
        self.assertTrue((self.home / "_SaveData").is_dir())
        self.assertEqual((self.home / kyty.SETTINGS_FILE).read_text(), "[MainDialog]\n")
        self.assertEqual((self.home / "notes.txt").read_text(), "mine")

    def test_the_links_can_be_taken_out_again_leaving_the_data(self):
        self.runtime.prepare_home(self.home)
        (self.home / "_SaveData").mkdir()
        (self.home / kyty.SETTINGS_FILE).write_text("[MainDialog]\n")
        self.assertEqual(sorted(kyty.unlink_home(self.home)), ["kyty_emulator", "kyty_launcher", "lib", "plugins", "qt.conf"])
        self.assertEqual(sorted(path.name for path in self.home.iterdir()), ["Kyty.ini", "_SaveData"])
        self.assertEqual(kyty.unlink_home(self.home), [])

    def test_game_content_is_shared_by_every_accounts_folder_and_saves_are_not(self):
        games = self.home.parent / kyty.GAMES
        other = self.home.parent / "222"
        (self.home / "_DownloadData" / "PPSA00001").mkdir(parents=True)
        (self.home / "_SaveData").mkdir()
        self.assertEqual(kyty.share_game_data(self.home, games), [])
        self.assertEqual(kyty.share_game_data(other, games), [])
        for home in (self.home, other):
            self.assertEqual(os.readlink(home / "_DownloadData"), os.path.join("..", kyty.GAMES, "_DownloadData"))
            self.assertTrue((home / "_DownloadData" / "PPSA00001").is_dir())
            self.assertTrue((home / "_PipelineCache").is_dir())
        self.assertFalse((other / "_SaveData").exists())
        third = self.home.parent / "333"
        (third / "_PipelineCache").mkdir(parents=True)
        (third / "_PipelineCache" / "PPSA00001.bin").write_text("mine")
        (games / "_PipelineCache" / "PPSA00001.bin").write_text("shared")
        self.assertEqual(kyty.share_game_data(third, games), ["_PipelineCache"])
        self.assertEqual((third / "_PipelineCache" / "PPSA00001.bin").read_text(), "mine")
        self.assertTrue((third / "_DownloadData").is_symlink())

    def test_a_new_account_gets_the_game_folders_saved_last(self):
        older, newer, empty = (self.home.parent / name / kyty.SETTINGS_FILE for name in ("1", "2", "3"))
        for path, text in ((older, "[Launcher]\ngame_dirs=/old\n"), (newer, "[MainDialog]\ngame_dirs=/not-here\n[Launcher]\ngame_dirs=/run/media/deck/SD/PS5, /home/deck/PS5\n"),
                           (empty, "[Launcher]\nsize=0\n")):
            path.parent.mkdir(parents=True)
            path.write_text(text)
        os.utime(older, (1, 1))
        self.assertEqual(kyty.game_folders([older, newer, empty]), "/run/media/deck/SD/PS5, /home/deck/PS5")
        self.assertIsNone(kyty.game_folders([empty, self.home / "missing.ini"]))

    def test_a_users_own_file_in_the_folder_is_never_replaced(self):
        self.home.mkdir(parents=True)
        (self.home / "lib").mkdir()
        (self.home / "lib" / "mine").write_text("")
        self.runtime.prepare_home(self.home)
        self.assertFalse((self.home / "lib").is_symlink())
        self.assertTrue((self.home / "lib" / "mine").is_file())

    def test_a_build_runs_on_through_its_links_and_is_then_kept(self):
        sleep = shutil.which("sleep")
        if not sleep:
            self.skipTest("needs sleep")
        (self.root / OLDER / kyty.EMULATOR).unlink()
        shutil.copy2(sleep, self.root / OLDER / kyty.EMULATOR)
        self.runtime.activate(OLDER)
        self.runtime.prepare_home(self.home)
        game = subprocess.Popen([str(self.home / kyty.EMULATOR), "30"])
        self.addCleanup(game.wait)
        self.addCleanup(game.kill)
        self.assertTrue(self.runtime.in_use(OLDER))
        self.assertFalse(self.runtime.in_use(TAG))


if __name__ == "__main__":
    unittest.main()
