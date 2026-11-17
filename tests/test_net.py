import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

import _paths
from nonsteamapps import net


class Response:
    def __init__(self, headers):
        self.headers = headers


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_progress_hears_each_part_and_the_size(self):
        size = net.CHUNK * 2 + 10
        source = self.folder / "helium.tar.xz"
        source.write_bytes(os.urandom(size))
        target, heard = self.folder / "download", []
        net.download(source.as_uri(), target, lambda received, total: heard.append((received, total)))
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(heard, [(net.CHUNK, size), (2 * net.CHUNK, size), (size, size)])
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["download", "helium.tar.xz"])

    def test_without_progress_and_on_failure_no_part_is_left(self):
        source = self.folder / "kytyps5.zip"
        source.write_bytes(b"archive")
        net.download(source.as_uri(), self.folder / "download")
        self.assertEqual((self.folder / "download").read_bytes(), b"archive")
        with self.assertRaises(urllib.error.URLError):
            net.download((self.folder / "missing").as_uri(), self.folder / "other", lambda received, total: None)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["download", "kytyps5.zip"])

    def test_size_is_zero_when_the_server_does_not_give_one(self):
        self.assertEqual(net._size(Response({"Content-Length": "120"})), 120)
        for headers in ({}, {"Content-Length": "lots"}, {"Content-Length": "-4"}):
            self.assertEqual(net._size(Response(headers)), 0)
        self.assertEqual(net._size(object()), 0)


if __name__ == "__main__":
    unittest.main()
