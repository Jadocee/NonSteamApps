import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
from nonsteamapps import ui
from nonsteamapps.flatpak import Flatpak, FlatpakError, Installed, Progress

PLAIN = [
    "Looking for matches…",
    "Required runtime for rocks.shy.VacuumTube/x86_64/stable (runtime/org.freedesktop.Platform/x86_64/24.08) found in remote flathub",
    "",
    " 1.\t   \torg.freedesktop.Platform\t24.08\ti\tflathub\t< 263.2\u00a0MB",
    " 2.\t   \trocks.shy.VacuumTube\tstable\ti\tflathub\t< 107.7\u00a0MB",
    "",
    "Installing 1/2…",
    "Installing 1/2…                        0%  0 bytes/s",
    "Installing 1/2… ████████▌            43%  2.3\u00a0MB/s  00:12",
    "Installing 1/2… ████████████████████ 100%",
    "Installing 2/2…",
    "Installing 2/2… ██████████           50%  1.1\u00a0MB/s",
    "Installation complete.",
]


class FlatpakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        installed = {
            "rocks.shy.VacuumTube": {"version": "2.0.1", "installation": "user"},
            "im.riot.Riot": {"version": "", "installation": "system"},
        }
        self.fake = _fakes.FakeFlatpak(Path(self.tmp.name), installed)
        self.env = mock.patch.dict(os.environ, self.fake.env)
        self.env.start()
        self.flatpak = Flatpak(self.fake.command)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_lists_installed_apps_with_their_installation(self):
        self.assertTrue(self.flatpak.available())
        self.assertEqual(
            self.flatpak.installed(),
            {"rocks.shy.VacuumTube": Installed("2.0.1", "user"), "im.riot.Riot": Installed("", "system")},
        )
        self.assertEqual(self.flatpak.installation("im.riot.Riot"), "system")
        self.assertIsNone(self.flatpak.installation("org.jellyfin.JellyfinDesktop"))

    def test_installs_into_the_user_installation_from_flathub(self):
        self.flatpak.install("org.jellyfin.JellyfinDesktop")
        self.assertEqual(
            self.fake.calls()[-2:],
            [
                ["remote-add", "--user", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"],
                ["install", "--user", "--noninteractive", "-y", "flathub", "org.jellyfin.JellyfinDesktop"],
            ],
        )
        self.assertEqual(self.flatpak.installation("org.jellyfin.JellyfinDesktop"), "user")

    def test_failures_raise_and_listing_failures_mean_nothing_installed(self):
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_FAIL": "install"}):
            with self.assertRaises(FlatpakError):
                self.flatpak.install("org.jellyfin.JellyfinDesktop")
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_FAIL": "list"}):
            self.assertEqual(self.flatpak.installed(), {})

    def test_update_uninstall_and_run(self):
        self.flatpak.update([])
        self.assertEqual(self.fake.calls("update"), [])
        self.flatpak.update(["rocks.shy.VacuumTube"], quiet=True)
        self.flatpak.uninstall("rocks.shy.VacuumTube")
        self.flatpak.remove_unused()
        self.assertEqual(
            self.fake.calls()[-3:],
            [
                ["update", "--user", "--noninteractive", "-y", "rocks.shy.VacuumTube"],
                ["uninstall", "--user", "--noninteractive", "-y", "rocks.shy.VacuumTube"],
                ["uninstall", "--user", "--unused", "--noninteractive", "-y"],
            ],
        )
        self.assertEqual(self.flatpak.run_args("im.riot.Riot", ["--a"]), [self.fake.command, "run", "im.riot.Riot", "--a"])
        self.assertEqual(
            self.flatpak.run_args("org.signal.Signal", ["A=1", "signal-desktop"], ["--command=env"]),
            [self.fake.command, "run", "--command=env", "org.signal.Signal", "A=1", "signal-desktop"],
        )
        self.assertEqual(self.flatpak.run_quietly("im.riot.Riot", ["--b"]), 0)
        self.assertEqual(self.fake.calls()[-1], ["run", "im.riot.Riot", "--b"])

    def test_progress_comes_from_the_lines_flatpak_prints_when_its_output_is_not_a_terminal(self):
        reader = Progress()
        self.assertEqual([reader.read(line + "\n") for line in PLAIN], [None] * 7 + [
            (0.0, "part 1 of 2, 0%, 0 bytes/s"),
            (0.215, "part 1 of 2, 43%, 2.3 MB/s"),
            (0.5, "part 1 of 2, 100%"),
            None,
            (0.75, "part 2 of 2, 50%, 1.1 MB/s"),
            None,
        ])

    def test_progress_does_not_rely_on_the_words_of_the_users_language(self):
        reader = Progress()
        lines = ["Installation…", "Installation… ███   45 %  2,3\u00a0Mo/s  00:12", "Installation terminée."]
        self.assertEqual([reader.read(line) for line in lines], [None, (0.45, "45%, 2,3 Mo/s"), None])
        reader = Progress()
        lines = ["Yükleniyor 2/3…", "Yükleniyor 2/3… ██ %30"]
        self.assertEqual([reader.read(line) for line in lines], [None, (0.43333333333333335, "part 2 of 3, 30%")])

    def test_installs_with_flatpaks_progress_on_the_bar_while_one_is_shown(self):
        terminal = _fakes.Terminal()
        with mock.patch.dict(os.environ, {"TERM": "xterm", "FAKE_FLATPAK_WARN": "Warning: Jellyfin's runtime is end-of-life"}), \
                mock.patch.object(ui, "_COLOUR", False), contextlib.redirect_stderr(terminal), ui.progress(2):
            ui.step("Jellyfin")
            self.flatpak.install("org.jellyfin.JellyfinDesktop")
        self.assertEqual(self.fake.calls()[-2:], [
            ["remote-add", "--user", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"],
            ["install", "--user", "-y", "flathub", "org.jellyfin.JellyfinDesktop"],
        ])
        self.assertEqual(self.fake.state_value("fancy_output"), "0")
        self.assertEqual(self.flatpak.installation("org.jellyfin.JellyfinDesktop"), "user")
        drawn = [line.split("%", 1)[1] for line in _fakes.bars(terminal.getvalue())]
        self.assertEqual(drawn[:4], ["  1 of 2 · Jellyfin", "  1 of 2 · Jellyfin · part 1 of 2, 0%", "  1 of 2 · Jellyfin · part 1 of 2, 50%, 1.0 MB/s",
                                     "  1 of 2 · Jellyfin · part 1 of 2, 100%, 1.0 MB/s"])
        self.assertIn("  1 of 2 · Jellyfin · part 2 of 2, 100%, 1.0 MB/s", drawn)
        self.assertTrue(_fakes.bars(terminal.getvalue())[-1].startswith("█" * 9 + "░" * 9 + "  50%"))
        self.assertEqual(_fakes.screen(terminal.getvalue()), ["    Warning: Jellyfin's runtime is end-of-life", ""])

    def test_updates_with_flatpaks_progress_on_the_bar_while_one_is_shown(self):
        terminal = _fakes.Terminal()
        with mock.patch.dict(os.environ, {"TERM": "xterm"}), mock.patch.object(ui, "_COLOUR", False), contextlib.redirect_stderr(terminal), \
                ui.progress(1):
            ui.step("Flathub apps")
            self.flatpak.update(["rocks.shy.VacuumTube", "im.riot.Riot"], quiet=True)
            self.flatpak.remove_unused()
        self.assertEqual(self.fake.calls()[-2:], [["update", "--user", "-y", "rocks.shy.VacuumTube", "im.riot.Riot"],
                                                  ["uninstall", "--user", "--unused", "--noninteractive", "-y"]])
        self.assertEqual(self.fake.state_value("fancy_output"), "0")
        drawn = [line.split("%", 1)[1] for line in _fakes.bars(terminal.getvalue())]
        self.assertIn("  1 of 1 · Flathub apps · part 1 of 3, 50%, 1.0 MB/s", drawn)
        self.assertIn("  1 of 1 · Flathub apps · part 3 of 3, 100%, 1.0 MB/s", drawn)
        self.assertEqual(_fakes.screen(terminal.getvalue()), [""])

    def test_a_failed_install_on_the_bar_says_why_and_raises(self):
        terminal = _fakes.Terminal()
        with mock.patch.dict(os.environ, {"TERM": "xterm", "FAKE_FLATPAK_FAIL": "install"}), mock.patch.object(ui, "_COLOUR", False), \
                contextlib.redirect_stderr(terminal), ui.progress(1):
            ui.step("Jellyfin")
            with self.assertRaisesRegex(FlatpakError, "'flatpak install --user -y flathub org.jellyfin.JellyfinDesktop' failed with exit status 1"):
                self.flatpak.install("org.jellyfin.JellyfinDesktop")
        self.assertEqual(_fakes.screen(terminal.getvalue()), ["    error: install failed", ""])

    def test_missing_command_is_reported(self):
        missing = Flatpak("/nonexistent/flatpak")
        self.assertFalse(missing.available())
        self.assertEqual(missing.installed(), {})
        with self.assertRaises(FlatpakError):
            missing.install("im.riot.Riot")
        with mock.patch.dict(os.environ, {"TERM": "xterm"}), contextlib.redirect_stderr(_fakes.Terminal()), ui.progress(1):
            with self.assertRaisesRegex(FlatpakError, "could not run /nonexistent/flatpak"):
                missing.install("im.riot.Riot")


if __name__ == "__main__":
    unittest.main()
