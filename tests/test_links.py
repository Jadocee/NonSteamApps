import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import _paths
from nonsteamapps import links

SCRIPT = _paths.ROOT / "src" / "share" / "sandbox" / "xdg-open"
SCHEMES = ("io.element.desktop", "element")


class LinkKindTests(unittest.TestCase):
    def test_web_links_and_the_apps_callbacks_pass_and_nothing_else(self):
        self.assertEqual(links.kind("https://account.matrix.org/authorize?x=1", SCHEMES), "web")
        self.assertEqual(links.kind("HTTP://example.org/", SCHEMES), "web")
        self.assertEqual(links.kind("io.element.desktop:/vector/webapp/?no_universal_links=true#code=1", SCHEMES), "callback")
        self.assertEqual(links.kind("Element://vector/webapp/?element-desktop-ssoid=x", SCHEMES), "callback")
        for url in ("", "https:", "https:/x", "file:///etc/passwd", "mailto:a@b", "bitwarden://sso-callback", "/home/deck/a.pdf",
                    "https://example.org/\nhttps://evil.example/", "https://example.org/\x7f", "https://example.org/" + "a" * links.MAX_URL):
            with self.subTest(url=url[:40]):
                self.assertIsNone(links.kind(url, SCHEMES))

    def test_the_app_and_its_browser_find_nonsteamapps_xdg_open_first(self):
        scripts, pipe = Path("/opt/nsa/share/sandbox"), Path("/run/user/1000/app/im.riot.Riot/nonsteamapps/open-7")
        self.assertEqual(links.sandbox_options(scripts, pipe, SCHEMES), [
            "--filesystem=/opt/nsa/share/sandbox:ro",
            "--env=PATH=/opt/nsa/share/sandbox:/app/bin:/usr/bin",
            f"--env=NONSTEAMAPPS_OPEN={pipe}",
            "--env=NONSTEAMAPPS_SCHEMES=io.element.desktop element",
        ])
        environment = links.browser_environment({"PATH": "/usr/bin", "HOME": "/home/deck"}, scripts, pipe, SCHEMES)
        self.assertEqual(environment["PATH"], "/opt/nsa/share/sandbox:/usr/bin")
        self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/dev/null")
        self.assertEqual((environment["HOME"], environment["NONSTEAMAPPS_OPEN"]), ("/home/deck", str(pipe)))
        self.assertEqual(links.channel_dir("im.riot.Riot", {"XDG_RUNTIME_DIR": "/run/user/1000"}), Path("/run/user/1000/app/im.riot.Riot/nonsteamapps"))


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pipe, self.fd = links.open_channel(self.dir / "app" / "nonsteamapps")
        self.addCleanup(os.close, self.fd)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_pipe_is_private_to_the_user(self):
        self.assertTrue(stat.S_ISFIFO(self.pipe.stat().st_mode))
        self.assertEqual(stat.S_IMODE(self.pipe.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.pipe.parent.stat().st_mode), 0o700)

    def test_links_from_the_app_are_served_until_it_exits_with_its_status(self):
        writes = (
            "printf 'https://account.example.org/a\\nnot a link\\nfile:///etc/passwd\\nio.element' >\"$1\"; sleep 0.3; "
            "printf '.desktop:/vector/webapp/#code=1\\n' >\"$1\"; sleep 0.3; exit 3"
        )
        child = subprocess.Popen(["sh", "-c", writes, "sh", str(self.pipe)])
        opened, delivered = [], []
        self.assertEqual(links.serve(child, self.fd, SCHEMES, opened.append, delivered.append), 3)
        self.assertEqual((opened, delivered), (["https://account.example.org/a"], ["io.element.desktop:/vector/webapp/#code=1"]))

    def test_an_app_ended_by_a_signal_reports_it_like_a_shell(self):
        child = subprocess.Popen(["sh", "-c", "kill -TERM $$"])
        self.assertEqual(links.serve(child, self.fd, SCHEMES, print, print), 128 + 15)

    def test_stop_ends_a_browser_with_the_processes_it_started(self):
        browser = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
        links.stop([browser])
        self.assertIsNotNone(browser.wait(timeout=5))
        time.sleep(0.2)
        group = subprocess.run(["pgrep", "-g", str(browser.pid)], capture_output=True, text=True)
        self.assertEqual(group.stdout.strip(), "")


class XdgOpenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pipe, self.fd = links.open_channel(self.dir / "pipe")
        self.addCleanup(os.close, self.fd)
        self.fallback_log = self.dir / "fallback.log"
        fallback = self.dir / "xdg-open"
        fallback.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >>"{self.fallback_log}"\n')
        fallback.chmod(0o755)
        self.environment = {"PATH": os.environ["PATH"], "NONSTEAMAPPS_XDG_OPEN": str(fallback), "NONSTEAMAPPS_SCHEMES": " ".join(SCHEMES)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *arguments, **variables):
        return subprocess.run([str(SCRIPT), *arguments], env={**self.environment, **variables}, timeout=10).returncode

    def received(self):
        time.sleep(0.05)
        try:
            return os.read(self.fd, 65536).decode().splitlines()
        except BlockingIOError:
            return []

    def fallbacks(self):
        return self.fallback_log.read_text().splitlines() if self.fallback_log.exists() else []

    def test_web_links_and_callbacks_go_to_nonsteamapps(self):
        for url in ("https://account.matrix.org/authorize?redirect_uri=io.element.desktop%3A&state=a b", "element://vector/webapp/?x=1"):
            self.assertEqual(self.run_script(url, NONSTEAMAPPS_OPEN=str(self.pipe)), 0)
            self.assertEqual(self.received(), [url])
        self.assertEqual(self.fallbacks(), [])

    def test_everything_else_goes_to_the_usual_xdg_open(self):
        self.assertEqual(self.run_script("/home/deck/Downloads/a.pdf", NONSTEAMAPPS_OPEN=str(self.pipe)), 0)
        self.assertEqual(self.run_script("bitwarden://sso-callback", NONSTEAMAPPS_OPEN=str(self.pipe)), 0)
        self.assertEqual(self.run_script("https://example.org/", "--extra", NONSTEAMAPPS_OPEN=str(self.pipe)), 0)
        self.assertEqual(self.run_script("https://example.org/"), 0)
        self.assertEqual(self.run_script("https://example.org/", NONSTEAMAPPS_OPEN=str(self.dir / "missing")), 0)
        self.assertEqual(self.received(), [])
        self.assertEqual(self.fallbacks(), [
            "/home/deck/Downloads/a.pdf", "bitwarden://sso-callback", "https://example.org/ --extra", "https://example.org/", "https://example.org/",
        ])


if __name__ == "__main__":
    unittest.main()
