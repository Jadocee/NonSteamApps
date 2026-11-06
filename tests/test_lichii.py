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
from nonsteamapps import builds, lichii

TAG = _fakes.LICHII_TAG


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.appimage = _fakes.make_lichii_appimage(Path(self.tmp.name))

    def test_the_newest_prerelease_with_the_pgo_appimage_is_chosen(self):
        windows_only = {"tag_name": "build-90", "prerelease": True, "assets": [{"name": "lichii-windows-x86_64-pgo.zip"}]}
        releases = [{"draft": True, "tag_name": "build-91"}, {"tag_name": "nx2-20261031", "prerelease": True}, windows_only,
                    _fakes.lichii_release(self.appimage), _fakes.lichii_release(self.appimage, "build-82")]
        build = lichii.newest_build(releases)
        self.assertEqual((build.tag, build.size, build.published), (TAG, self.appimage.stat().st_size, "2026-11-05T08:00:00Z"))
        self.assertEqual(build.url, f"https://github.com/zortos293/Lichii/releases/download/{TAG}/lichii-linux-x86_64-pgo.AppImage")
        self.assertEqual((lichii.describe(TAG), lichii.describe("local-0123456789ab")), ("build 83", "local build 0123456789ab"))

    def test_a_build_without_githubs_checksum_or_from_elsewhere_is_refused(self):
        release = _fakes.lichii_release(self.appimage)
        release["assets"][1]["digest"] = None
        with self.assertRaisesRegex(lichii.LichiiError, "no SHA-256"):
            lichii.newest_build([release])
        release = _fakes.lichii_release(self.appimage)
        release["assets"][1]["browser_download_url"] = "https://example.org/lichii.AppImage"
        with self.assertRaisesRegex(lichii.LichiiError, "not among"):
            lichii.newest_build([release])
        with self.assertRaisesRegex(lichii.LichiiError, "has lichii-linux-x86_64-pgo.AppImage"):
            lichii.newest_build([])

    def test_only_a_file_carrying_the_appimage_mark_counts_as_one(self):
        self.assertTrue(lichii.is_appimage(self.appimage))
        page = Path(self.tmp.name) / "error.html"
        page.write_text("<!doctype html><title>Not Found</title>")
        self.assertFalse(lichii.is_appimage(page))
        self.assertFalse(lichii.is_appimage(Path(self.tmp.name) / "missing"))
        elf = Path(self.tmp.name) / "program"
        elf.write_bytes(self.appimage.read_bytes()[:8] + bytes(3) + self.appimage.read_bytes()[11:])
        self.assertFalse(lichii.is_appimage(elf))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.runtime = lichii.Runtime(self.dir / "lichii")
        self.appimages = {tag: _fakes.make_lichii_appimage(self.dir / tag) for tag in (TAG, "build-9", "build-10")}
        self.releases = [_fakes.lichii_release(self.appimages[TAG])]
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
        shutil.copyfile(self.appimages[url.rsplit("/", 2)[-2]], target)

    def test_the_newest_build_is_downloaded_checked_and_run_as_an_appimage(self):
        self.assertEqual(self.runtime.install(), TAG)
        self.assertEqual(self.runtime.current(), TAG)
        self.assertTrue(os.access(self.runtime.program, os.X_OK))
        self.assertEqual(self.runtime.program, self.runtime.root / "current" / lichii.PROGRAM)
        self.assertEqual(json.loads((self.runtime.root / TAG / builds.BUILD_RECORD).read_text())["published"], "2026-11-05T08:00:00Z")
        self.assertFalse(self.runtime.downloads.exists())
        self.assertEqual(self.runtime.install(), TAG)
        self.assertEqual(len(self.downloads), 1)
        self.assertIsNone(self.runtime.update())
        log = self.dir / "run.log"
        subprocess.run([str(self.runtime.program), "-f"], cwd=self.dir, env={**os.environ, "FAKE_LICHII_LOG": str(log)}, check=True)
        self.assertEqual(json.loads(log.read_text())["argv"], ["-f"])

    def test_a_download_that_does_not_match_githubs_checksum_or_is_no_appimage_is_not_installed(self):
        self.releases = [_fakes.lichii_release(self.appimages[TAG], digest="sha256:" + "f" * 64)]
        with self.assertRaisesRegex(lichii.LichiiError, "does not match"):
            self.runtime.install()
        page = self.dir / "page.html"
        page.write_text("<html>")
        self.appimages[TAG] = page
        self.releases = [_fakes.lichii_release(page)]
        with self.assertRaisesRegex(lichii.LichiiError, "is not an AppImage"):
            self.runtime.install()
        self.assertIsNone(self.runtime.current())
        self.assertEqual(self.runtime.versions(), [])

    def test_build_numbers_sort_as_numbers_and_the_build_before_stays_for_a_rollback(self):
        self.releases = [_fakes.lichii_release(self.appimages["build-9"], "build-9", "")]
        self.runtime.install()
        self.releases = [_fakes.lichii_release(self.appimages["build-10"], "build-10", "")]
        self.assertEqual(self.runtime.update(), "build-10")
        self.assertEqual(self.runtime.versions(), ["build-10", "build-9"])
        self.assertEqual(self.runtime.rollback(), "build-9")
        self.assertEqual(self.runtime.current(), "build-9")
        self.releases = [_fakes.lichii_release(self.appimages[TAG])]
        self.assertEqual(self.runtime.update(), TAG)
        self.assertEqual(self.runtime.versions(), [TAG, "build-10"])

    def test_an_appimage_from_a_file_is_found_among_the_releases_by_its_checksum_unless_told_not_to(self):
        self.assertEqual(self.runtime.install(self.appimages[TAG]), TAG)
        self.assertEqual(self.downloads, [])
        self.assertTrue(self.appimages[TAG].is_file())
        with self.assertRaisesRegex(lichii.LichiiError, "is not the lichii-linux-x86_64-pgo.AppImage of any"):
            self.runtime.install(self.appimages["build-9"])
        offline = lichii.Runtime(self.dir / "offline")
        tag = offline.install(self.appimages["build-9"], verify=False)
        self.assertEqual(tag, "local-" + builds.sha256(self.appimages["build-9"])[:12])
        self.assertEqual(offline.current(), tag)
        self.assertIsNone(offline.icon_url())
        self.assertEqual(self.runtime.icon_url(), f"https://raw.githubusercontent.com/zortos293/Lichii/{TAG}/dist/branding/lichii_icon.png")


if __name__ == "__main__":
    unittest.main()
