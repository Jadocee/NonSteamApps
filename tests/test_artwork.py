import functools
import hashlib
import http.server
import json
import os
import shutil
import struct
import tempfile
import threading
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

    def test_an_apps_own_icon_inside_its_flatpak_comes_before_the_one_flatpak_exports(self):
        user, system = self.dir / "user", self.dir / "system"
        exported = self.icon("user/exports/share/icons/hicolor/scalable/apps/org.winehq.Wine.svg", b"<svg/>")
        self.assertEqual(artwork.flatpak_icon("org.winehq.Wine", [user, system], "winetricks"), exported)
        own = self.icon("system/app/org.winehq.Wine/current/active/files/share/icons/hicolor/scalable/apps/winetricks.svg", b"<svg/>")
        self.assertEqual(artwork.flatpak_icon("org.winehq.Wine", [user, system], "winetricks"), own)
        self.assertEqual(artwork.flatpak_icon("org.winehq.Wine", [user, system]), exported)

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
        self.assertEqual(artwork._suffix("https://example.com/icon.svg", b'\xef\xbb\xbf<svg width="357" xmlns="http://www.w3.org/2000/svg"/>'), ".svg")
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

    def test_a_site_answering_with_cloudflares_check_is_reported_and_nothing_is_downloaded(self):
        self.environment["FAKE_DEVTOOLS_SITE_ICONS"] = "null"
        self.downloads = {"https://www.nexusmods.com/apple-touch-icon.png": png(4, 4)}
        with mock.patch.object(self, "download", wraps=self.download) as download, \
                self.assertRaisesRegex(artwork.ArtworkError, "www.nexusmods.com answers a headless browser with a check that a person is visiting"):
            self.studio.download = download
            self.studio.make("nexusmods", "Nexus Mods", artwork.Source("site", "https://www.nexusmods.com/"))
        download.assert_not_called()
        self.assertEqual(self.studio.files("nexusmods"), {})

    def test_a_manifest_the_site_does_not_name_is_read_too_and_names_the_source(self):
        self.environment["FAKE_DEVTOOLS_SITE_ICONS"] = json.dumps([{"url": "https://steamdb.info/static/logos/512px.png", "sizes": "512x512", "kind": "manifest"}])
        self.downloads = {"https://steamdb.info/static/logos/512px.png": png(4, 4)}
        plain = artwork.Source("site", "https://steamdb.info/")
        named = artwork.Source("site", "https://steamdb.info/", "https://steamdb.info/steamdb.webmanifest")
        self.assertEqual(plain.key, "site:https://steamdb.info/")
        self.assertNotEqual(named.key, plain.key)
        self.assertEqual(self.studio.make("steamdb", "SteamDB", named), "made")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        scripts = [call["params"].get("expression", "") for call in calls if call["method"] == "Runtime.evaluate"]
        self.assertTrue(any(script.endswith('(["https://steamdb.info/steamdb.webmanifest"])') for script in scripts))
        self.assertEqual(json.loads((self.dir / "made/steamdb" / artwork.RECORD).read_text())["source"], named.key)
        self.assertEqual(self.studio.make("steamdb", "SteamDB", named), "kept")

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

    def test_a_projects_own_library_artwork_fills_its_slots_and_the_icon_the_rest(self):
        base = "https://raw.githubusercontent.com/zortos293/Lichii/build-83/dist/branding"
        icon = f"{base}/lichii_icon.png"
        official = {"capsule": f"{base}/lichii_vertical_grid.png", "wide": f"{base}/lichii_square_grid.png", "logo": f"{base}/lichii_logo.png"}
        art = {"icon": png(9, 9), "capsule": png(6, 9), "wide": png(8, 8), "logo": png(16, 9)}
        self.downloads = {icon: art["icon"], **{official[slot]: art[slot] for slot in official}}
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", icon), official=official), "made")
        files = self.studio.files("lichii")

        def drawn(slot, kind="png"):
            return f"fake {kind} {slot} {hashlib.sha256(art[slot if slot in official else 'icon']).hexdigest()[:12]}".encode()

        for slot in ("capsule", "wide", "logo", "icon"):
            self.assertEqual(files[slot].read_bytes(), drawn(slot), slot)
        self.assertEqual(files["hero"].read_bytes(), drawn("hero", "jpeg"))
        record = json.loads((self.dir / "made/lichii" / artwork.RECORD).read_text())
        self.assertEqual(sorted(record["official"]), ["capsule", "logo", "wide"])
        self.assertIn("its project's own library artwork for the capsule, logo, wide", self.studio.origin("lichii"))
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", icon), official=official), "kept")
        self.assertEqual(self.screenshots(), 5)
        newer = {slot: url.replace("build-83", "build-84") for slot, url in official.items()}
        self.downloads.update({newer[slot]: art[slot] for slot in newer})
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", icon), official=newer), "kept")
        self.assertEqual(json.loads((self.dir / "made/lichii" / artwork.RECORD).read_text())["official"]["capsule"]["url"], newer["capsule"])
        self.downloads[newer["wide"]] = png(2, 2) + b"tiny"
        changed = {**newer, "wide": newer["wide"] + "?v=2"}
        self.downloads[changed["wide"]] = png(2, 2) + b"tiny"
        self.assertEqual(self.studio.make("lichii", "Lichii", artwork.Source("url", icon), official=changed), "made")
        files = self.studio.files("lichii")
        self.assertEqual(files["wide"].read_bytes(), drawn("icon").replace(b" icon ", b" wide "))
        self.assertEqual(files["capsule"].read_bytes(), drawn("capsule"))
        self.assertNotIn("wide", json.loads((self.dir / "made/lichii" / artwork.RECORD).read_text())["official"])

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


class QuietSite(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class SiteIconTests(unittest.TestCase):
    """The script that lists a site's icons, in a real Chromium, on a small site served here; skipped where none starts."""

    def setUp(self):
        program = chromium()
        if program is None:
            self.skipTest("no Chromium on this machine")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        site = Path(self.tmp.name)
        mark = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"
        (site / "index.html").write_text(f'<!doctype html><title>Site</title><link rel="icon" href="{mark}">')
        (site / "named.html").write_text('<!doctype html><title>Named</title><link rel="manifest" href="/app.webmanifest">')
        (site / "checked.html").write_text('<!doctype html><title>Just a moment...</title><link rel="icon" href="/favicon.ico">'
                                           '<script>window._cf_chl_opt = {cType: "managed"};</script>')
        (site / "orchestrated.html").write_text('<!doctype html><title>Just a moment...</title>'
                                                '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>')
        (site / "app.webmanifest").write_text(json.dumps({"icons": [
            {"src": "/logos/512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/logos/maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]}))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietSite, directory=str(site)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.browser = artwork.Browser(program, timeout=30)
        try:
            self.browser.start()
        except artwork.BrowserError as exc:
            self.skipTest(f"Chromium did not start here: {exc}")
        self.addCleanup(self.browser.close)
        self.session = self.browser.page()

    def icons(self, page, manifests=()):
        self.assertTrue(self.browser.load(self.session, f"{self.base}/{page}", 640, 480, transparent=False))
        found = self.browser.evaluate(self.session, artwork.site_icons(manifests))
        return [(icon["url"].replace(self.base, ""), icon["kind"]) for icon in found]

    def test_cloudflares_check_is_told_from_a_page_and_names_no_icon(self):
        for page in ("checked.html", "orchestrated.html"):
            with self.subTest(page=page):
                self.assertTrue(self.browser.load(self.session, f"{self.base}/{page}", 640, 480, transparent=False))
                self.assertIsNone(self.browser.evaluate(self.session, artwork.site_icons()))

    def test_a_manifest_the_page_does_not_name_is_read_when_given_and_maskable_icons_are_left_out(self):
        self.assertEqual([kind for _, kind in self.icons("index.html")], ["icon", "guess"])
        self.assertEqual(self.icons("index.html", [f"{self.base}/app.webmanifest"])[1:],
                         [("/logos/512.png", "manifest"), ("/apple-touch-icon.png", "guess")])
        self.assertEqual(self.icons("named.html", [f"{self.base}/app.webmanifest"]),
                         [("/logos/512.png", "manifest"), ("/apple-touch-icon.png", "guess")])
