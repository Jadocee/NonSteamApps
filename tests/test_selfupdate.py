import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

import _paths
from nonsteamapps import selfupdate
from nonsteamapps.config import Paths


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.paths = Paths.detect(self.dir / "program", {"HOME": str(self.dir / "home")})
        self.work = self.dir / "work"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, members):
        path = self.dir / "archive.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_updates_come_from_where_the_installer_came_from(self):
        self.assertEqual(selfupdate.source(self.paths), selfupdate.DEFAULT_SOURCE)
        selfupdate.remember(self.paths, {})
        self.assertFalse(self.paths.source.exists())
        selfupdate.remember(self.paths, {selfupdate.SOURCE_VARIABLE: "https://example.com/branch.tar.gz"})
        self.assertEqual(selfupdate.source(self.paths), "https://example.com/branch.tar.gz")
        clone = self.dir / "clone"
        clone.mkdir()
        (clone / "install.sh").write_text("")
        selfupdate.remember(self.paths, {selfupdate.SOURCE_VARIABLE: str(clone)})
        self.assertEqual(selfupdate.source(self.paths), str(clone))
        (clone / "install.sh").unlink()
        self.assertEqual(selfupdate.source(self.paths), selfupdate.DEFAULT_SOURCE)

    def test_an_archive_is_unpacked_without_githubs_top_folder_and_a_local_copy_is_used_as_it_is(self):
        archive = self.archive({
            "steamos-yt-main/install.sh": b"#!/bin/bash\n",
            "steamos-yt-main/src/lib/nonsteamapps/__init__.py": b'__version__ = "9.9.9"\n',
        })
        tree = selfupdate.fetch(archive.as_uri(), self.work)
        self.assertEqual((tree / "src/lib/nonsteamapps/__init__.py").read_text(), '__version__ = "9.9.9"\n')
        self.assertEqual(selfupdate.fetch(str(self.dir / "clone"), self.work), self.dir / "clone")

    def test_a_missing_or_foreign_archive_is_reported(self):
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.fetch((self.dir / "missing.tar.gz").as_uri(), self.work)
        foreign = self.archive({"project/README": b"hello"})
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.fetch(foreign.as_uri(), self.work)

    def test_the_new_installer_copies_only_the_program(self):
        home = self.dir / "home"
        environ = {"HOME": str(home), "PATH": os.environ["PATH"], "NONSTEAMAPPS_ALLOW_ROOT": "1", selfupdate.SOURCE_VARIABLE: "x"}
        program = self.dir / "program"
        selfupdate.copy(_paths.ROOT, program, environ)
        self.assertTrue(os.access(program / "bin" / "nonsteamapps", os.X_OK))
        shipped = (_paths.ROOT / "src/lib/nonsteamapps/__init__.py").read_text()
        self.assertEqual((program / "lib/nonsteamapps/__init__.py").read_text(), shipped)
        self.assertTrue((program / "artwork" / "youtube").is_dir())
        self.assertFalse(home.exists())

    def test_a_failing_installer_is_reported_with_its_last_words(self):
        tree = self.dir / "tree"
        tree.mkdir()
        (tree / "install.sh").write_text("echo starting >&2\necho 'error: python3 is required' >&2\nexit 1\n")
        with self.assertRaises(selfupdate.UpdateError) as raised:
            selfupdate.copy(tree, self.dir / "program", {"PATH": os.environ["PATH"]})
        self.assertEqual(str(raised.exception), "error: python3 is required")


if __name__ == "__main__":
    unittest.main()
