import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import _paths
from nonsteamapps import artwork

ROOT = Path(_paths.ROOT)
SHARE = ROOT / "src" / "share" / "artwork"
DEVTOOLS = ROOT / "tests" / "fakes" / "devtools"


def png(width: int, height: int, colour=(229, 9, 20, 255)) -> bytes:
    """A plain PNG of one colour."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\0" + bytes(colour) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def chromium():
    """A Chromium to draw with, as NonSteamApps' Helium does, if this machine has one."""
    for candidate in (os.environ.get("NONSTEAMAPPS_TEST_CHROMIUM"), shutil.which("chromium"), shutil.which("chromium-browser"),
                      shutil.which("google-chrome"), "/opt/pw-browsers/chromium"):
        if candidate and os.access(candidate, os.X_OK):
            return Path(candidate)
    return None


class FinderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def icon(self, path: str, data: bytes = b"icon") -> Path:
        target = self.dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_a_flatpaks_scalable_icon_wins_then_its_largest_from_either_installation(self):
        user, system = self.dir / "user", self.dir / "system"
        icons = "exports/share/icons/hicolor"
        self.icon(f"user/{icons}/64x64/apps/org.example.App.png")
        self.assertIsNone(artwork.flatpak_icon("org.example.App", [user, system]))
        self.icon(f"user/{icons}/128x128/apps/org.example.App.png")
        large = self.icon(f"system/{icons}/512x512/apps/org.example.App.png")
        self.icon(f"user/{icons}/256x256/apps/org.example.Other.png")
        self.assertEqual(artwork.flatpak_icon("org.example.App", [user, system]), large)
        vector = self.icon(f"system/{icons}/scalable/apps/org.example.App.svg", b"<svg/>")
        self.assertEqual(artwork.flatpak_icon("org.example.App", [user, system]), vector)

    def test_a_system_apps_icon_comes_from_its_menu_entry_through_the_icon_theme(self):
        applications, breeze, hicolor = self.dir / "applications", self.dir / "icons/breeze", self.dir / "icons/hicolor"
        (applications).mkdir()
        (applications / "org.kde.dolphin.desktop").write_text("[Desktop Entry]\nName=Dolphin\nExec=dolphin %u\nIcon=system-file-manager\n")
        (applications / "org.kde.konsole.desktop").write_text("[Desktop Entry]\nExec=konsole\nIcon=utilities-terminal\n")
        self.assertIsNone(artwork.desktop_icon("dolphin", [applications], [breeze, hicolor]))
        self.icon("icons/hicolor/256x256/apps/system-file-manager.png")
        small = self.icon("icons/breeze/apps/22/system-file-manager.svg", b"<svg/>")
        self.assertEqual(artwork.desktop_icon("dolphin", [applications], [breeze, hicolor]), small)
        large = self.icon("icons/breeze/apps/48/system-file-manager.svg", b"<svg/>")
        self.assertEqual(artwork.desktop_icon("dolphin", [applications], [breeze, hicolor]), large)
        self.assertIsNone(artwork.desktop_icon("kate", [applications, self.dir / "missing"], [breeze]))
        own = self.icon("own/dolphin.png")
        (applications / "org.kde.dolphin.desktop").write_text(f"[Desktop Entry]\nExec=/usr/bin/dolphin\nIcon={own}\n")
        self.assertEqual(artwork.desktop_icon("dolphin", [applications], [breeze]), own)

    def test_a_sites_icons_rank_vector_then_largest_and_only_https_counts(self):
        candidates = [
            {"url": "https://example.com/favicon-32.png", "sizes": "32x32", "kind": "icon"},
            {"url": "https://example.com/touch.png", "sizes": "", "kind": "touch"},
            {"url": "https://example.com/512.png", "sizes": "192x192 512x512", "kind": "manifest"},
            {"url": "https://example.com/apple-touch-icon.png", "sizes": "180x180", "kind": "guess"},
            {"url": "https://example.com/mark.svg", "sizes": "", "kind": "icon"},
            {"url": "http://example.com/plain.png", "sizes": "1024x1024", "kind": "icon"},
            {"url": "file:///etc/passwd", "sizes": "any", "kind": "icon"},
            {"url": "https://example.com/512.png", "sizes": "512x512", "kind": "icon"},
            "nonsense",
        ]
        self.assertEqual(artwork.rank(candidates), [
            "https://example.com/mark.svg", "https://example.com/512.png", "https://example.com/touch.png",
            "https://example.com/apple-touch-icon.png", "https://example.com/favicon-32.png",
        ])

    def test_an_icons_type_comes_from_its_content(self):
        self.assertEqual(artwork._suffix("https://example.com/icon", png(1, 1)), ".png")
        self.assertEqual(artwork._suffix("x.png", b"\xff\xd8\xff\xe0 jpeg"), ".jpg")
        self.assertEqual(artwork._suffix("x", b"RIFF\0\0\0\0WEBPVP8 "), ".webp")
        self.assertEqual(artwork._suffix("x", b"\0\0\1\0\1\0 ico"), ".ico")
        self.assertEqual(artwork._suffix("x", b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'), ".svg")
        self.assertEqual(artwork._suffix("https://example.com/icon.svg?v=2", b"<!-- drawn --><svg/>"), ".svg")
        self.assertEqual(artwork._suffix("https://example.com/page", b"<!doctype html><title>Not found</title>"), "")

    def test_only_https_icons_of_reasonable_size_are_downloaded(self):
        with self.assertRaisesRegex(artwork.ArtworkError, "not an https address"):
            artwork.fetch("http://example.com/icon.png")
        with self.assertRaisesRegex(artwork.ArtworkError, "not an https address"):
            artwork.fetch("file:///etc/passwd")


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "devtools.log"
        environment = {**os.environ, "FAKE_DEVTOOLS_LOG": str(self.log)}
        self.environment = environment
        self.downloads = {}
        self.studio = artwork.Studio(self.dir / "made", SHARE, lambda: artwork.Browser(DEVTOOLS, timeout=10, environment=self.environment),
                                     download=self.download)
        self.addCleanup(self.studio.close)
        self.icon = self.dir / "icon.png"
        self.icon.write_bytes(png(4, 4))

    def download(self, url):
        if url not in self.downloads:
            raise artwork.ArtworkError(f"could not download {url}: offline")
        return self.downloads[url]

    def screenshots(self):
        return sum(1 for line in self.log.read_text().splitlines() if json.loads(line)["method"] == "Page.captureScreenshot") if self.log.exists() else 0

    def test_artwork_is_drawn_around_the_icon_once_and_again_when_the_icon_changes(self):
        source = artwork.Source("file", str(self.icon))
        self.assertEqual(self.studio.make("netflix", "Netflix", source), "made")
        files = self.studio.files("netflix")
        self.assertEqual(sorted(files), ["capsule", "hero", "icon", "logo", "wide"])
        self.assertTrue(files["capsule"].read_bytes().startswith(b"fake png capsule "))
        self.assertTrue(files["hero"].read_bytes().startswith(b"fake jpeg hero "))
        self.assertEqual(self.screenshots(), 5)
        self.assertEqual(self.studio.make("netflix", "Netflix", source), "kept")
        self.assertEqual(self.screenshots(), 5)
        self.icon.write_bytes(png(8, 8))
        self.assertEqual(self.studio.make("netflix", "Netflix", source), "made")
        self.assertEqual(self.screenshots(), 10)
        self.assertEqual(json.loads((self.dir / "made/netflix" / artwork.RECORD).read_text())["source"], f"file:{self.icon}")
        loads = [json.loads(line)["params"]["url"] for line in self.log.read_text().splitlines() if json.loads(line)["method"] == "Page.navigate"]
        self.assertTrue(all(url.startswith((SHARE / artwork.TEMPLATE).as_uri() + "?slot=") for url in loads))
        self.assertIn("name=Netflix", loads[-1])
        self.assertIn("a=%23e50914", loads[-1])

    def test_a_template_change_draws_everything_again_and_a_missing_file_does_too(self):
        source = artwork.Source("file", str(self.icon))
        self.studio.make("eden", "Eden", source)
        (self.dir / "made/eden/wide.png").unlink()
        self.assertEqual(self.studio.files("eden"), {})
        self.assertEqual(self.studio.make("eden", "Eden", source), "made")
        with mock.patch.object(artwork, "VERSION", artwork.VERSION + 1):
            self.assertEqual(self.studio.files("eden"), {})
            self.assertEqual(self.studio.make("eden", "Eden", source), "made")
            self.assertEqual(sorted(self.studio.files("eden")), ["capsule", "hero", "icon", "logo", "wide"])

    def test_an_icon_too_small_or_not_an_image_leaves_the_artwork_drawn_before(self):
        source = artwork.Source("file", str(self.icon))
        self.studio.make("signal", "Signal", source)
        drawn = self.studio.files("signal")["capsule"].read_bytes()
        self.icon.write_bytes(png(2, 2) + b"tiny")
        with self.assertRaisesRegex(artwork.ArtworkError, "smaller than 128 pixels"):
            self.studio.make("signal", "Signal", source)
        self.icon.write_bytes(png(2, 2) + b"broken")
        with self.assertRaisesRegex(artwork.ArtworkError, "not an image Helium can show"):
            self.studio.make("signal", "Signal", source)
        self.assertEqual(self.studio.files("signal")["capsule"].read_bytes(), drawn)
        self.icon.write_bytes(b"<!doctype html>")
        with self.assertRaisesRegex(artwork.ArtworkError, "is not an icon"):
            self.studio.make("signal", "Signal", source)
        self.assertEqual(artwork.Studio(self.dir / "none", SHARE, lambda: None).files("signal"), {})

    def test_a_sites_best_usable_icon_is_used_and_fetched_again_only_when_asked(self):
        self.environment["FAKE_DEVTOOLS_SITE_ICONS"] = json.dumps([
            {"url": "https://www.netflix.com/favicon.ico", "sizes": "16x16 32x32", "kind": "icon"},
            {"url": "https://assets.example.com/app-icon.png", "sizes": "512x512", "kind": "manifest"},
            {"url": "https://assets.example.com/broken.png", "sizes": "1024x1024", "kind": "manifest"},
        ])
        self.downloads = {"https://assets.example.com/app-icon.png": png(4, 4), "https://assets.example.com/broken.png": png(1, 1) + b"broken"}
        source = artwork.Source("site", "https://www.netflix.com/")
        self.assertEqual(self.studio.make("netflix", "Netflix", source), "made")
        self.assertEqual(json.loads((self.dir / "made/netflix" / artwork.RECORD).read_text())["file"], "original.png")
        self.assertEqual(self.studio.make("netflix", "Netflix", source), "kept")
        self.assertEqual(self.screenshots(), 5)
        self.assertEqual(self.studio.make("netflix", "Netflix", source, refresh=True), "kept")
        self.assertEqual(self.screenshots(), 5)
        self.downloads["https://assets.example.com/app-icon.png"] = png(6, 6)
        self.assertEqual(self.studio.make("netflix", "Netflix", source, refresh=True), "made")
        self.environment["FAKE_DEVTOOLS_SITE_ICONS"] = "[]"
        self.studio.close()
        with self.assertRaisesRegex(artwork.ArtworkError, "www.disneyplus.com names no icon"):
            self.studio.make("disneyplus", "Disney+", artwork.Source("site", "https://www.disneyplus.com/"))

    def test_a_projects_icon_is_downloaded_once_for_each_address(self):
        url = "https://raw.githubusercontent.com/zortos293/Lichii/build-83/dist/branding/lichii_icon.png"
        with self.assertRaisesRegex(artwork.ArtworkError, "offline"):
            self.studio.make("lichii", "Lichii", artwork.Source("url", url))
        self.downloads[url] = png(4, 4)
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", url)), "made")
        del self.downloads[url]
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", url)), "kept")
        newer = url.replace("build-83", "build-84")
        self.downloads[newer] = png(4, 4)
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", newer)), "kept")
        self.assertEqual(json.loads((self.dir / "made/lichii" / artwork.RECORD).read_text())["source"], f"url:{newer}")
        self.assertEqual(self.screenshots(), 5)
        changed = url.replace("build-83", "build-85")
        self.downloads[changed] = png(5, 5)
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", changed)), "made")
        self.assertEqual(self.screenshots(), 10)
        self.studio.forget("lichii")
        self.assertFalse((self.dir / "made/lichii").exists())

    def test_a_program_that_does_not_speak_devtools_is_reported_at_once(self):
        program = self.dir / "not-a-browser"
        program.write_text("#!/bin/sh\necho 'unknown option --headless' >&2\nexit 1\n")
        program.chmod(0o755)
        studio = artwork.Studio(self.dir / "made", SHARE, lambda: artwork.Browser(program, timeout=10))
        with self.assertRaisesRegex(artwork.BrowserError, "closed its DevTools pipe.*unknown option --headless"):
            studio.make("eden", "Eden", artwork.Source("file", str(self.icon)))
        studio.close()


class ChromiumTests(unittest.TestCase):
    """Draws real artwork, as Helium does on a device, with a Chromium on this machine; skipped where none starts."""

    def setUp(self):
        program = chromium()
        if program is None:
            self.skipTest("no Chromium on this machine")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.studio = artwork.Studio(self.dir / "made", SHARE, lambda: artwork.Browser(program, timeout=60))
        self.addCleanup(self.studio.close)

    def test_each_slot_is_drawn_at_steams_size_around_a_square_icon_with_rounded_corners(self):
        icon = self.dir / "icon.png"
        icon.write_bytes(png(256, 256))
        try:
            self.assertEqual(self.studio.make("netflix", "Netflix", artwork.Source("file", str(icon))), "made")
        except artwork.BrowserError as exc:
            self.skipTest(f"Chromium did not start here: {exc}")
        files = self.studio.files("netflix")
        for slot, name, width, height in artwork.SLOTS:
            data = files[slot].read_bytes()
            if name.endswith(".png"):
                self.assertEqual((data[:8], struct.unpack(">II", data[16:24])), (b"\x89PNG\r\n\x1a\n", (width, height)), slot)
                if slot in ("logo", "icon"):
                    self.assertEqual(data[25], 6, f"{slot} keeps its transparency")
            else:
                self.assertTrue(data.startswith(b"\xff\xd8"), slot)
        with self.assertRaisesRegex(artwork.ArtworkError, "smaller than 128 pixels"):
            small = self.dir / "small.png"
            small.write_bytes(png(48, 48))
            self.studio.make("signal", "Signal", artwork.Source("file", str(small)))


if __name__ == "__main__":
    unittest.main()
