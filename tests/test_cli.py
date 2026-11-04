import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
from _fakes import ALPHA, BETA
from nonsteamapps import __version__, apps, cli, collection, compat, config, selfupdate, steam, vdf


class Exec(Exception):
    """Raised instead of replacing the test process."""


def fake_exec(file, argv):
    raise Exec(argv)


class CliTestCase(unittest.TestCase):
    self_update = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.root = _fakes.make_steam(self.home)
        self.paths = _fakes.make_paths(self.home)
        self.fake = _fakes.FakeFlatpak(Path(self.tmp.name), self.preinstalled())
        self.flatpak = cli.Flatpak(self.fake.command)
        self.wall = _fakes.FakeFirewall(Path(self.tmp.name))
        (Path(self.tmp.name) / "release").mkdir()
        self.helium_archive = _fakes.make_helium_archive(Path(self.tmp.name) / "release")
        self.kyty_archive = _fakes.make_kyty_archive(Path(self.tmp.name) / "release")
        patches = [
            mock.patch.dict(os.environ, _fakes.environment(self.home, self.fake, wall=self.wall), clear=True),
            mock.patch("nonsteamapps.steamclient.running", return_value=False),
            mock.patch("nonsteamapps.cli._firewall", side_effect=self.wall.firewall),
        ]
        if not self.self_update:
            patches.append(mock.patch("nonsteamapps.cli._update_program"))
        self.watch = mock.patch("nonsteamapps.cli.x11.watch")
        patches.append(self.watch)
        patches.append(mock.patch("nonsteamapps.cli.appmenu.watch", return_value=False))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def preinstalled(self):
        return {}

    def run_cli(self, *argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = cli.main(list(argv), self.paths, self.flatpak)
        self.output, self.errors = output.getvalue(), errors.getvalue()
        return status

    def install(self, *names):
        options = ("--yes", "--no-auto-update", "--helium-archive", str(self.helium_archive), "--kytyps5-archive", str(self.kyty_archive), "--skip-verify")
        self.assertEqual(self.run_cli("install", *names, *options), 0, self.errors)

    def entries(self, account):
        data = (steam.config_dir(self.root, account) / "shortcuts.vdf").read_bytes()
        return {entry.get("AppName"): entry for entry in vdf.loads_binary(data).get("shortcuts").values()}

    def customise(self, account=ALPHA):
        """Rename YouTube's shortcut, add a launch option, choose its hero and change its TV settings, as a user might."""
        path = steam.config_dir(self.root, account) / "shortcuts.vdf"
        shortcuts = steam.ShortcutsFile.load(path)
        entry = shortcuts.find(str(self.paths.app_link("youtube")))[0]
        entry.set("AppName", "My Tube")
        entry.set("LaunchOptions", f"--steam-account {account} --debug-gpu")
        shortcuts.save()
        hero = steam.config_dir(self.root, account) / "grid" / f"{steam.to_unsigned32(entry.get('appid'))}_hero.jpg"
        hero.write_bytes(b"chosen in Steam")
        self.launch("youtube", "--steam-account", str(account))
        settings = apps.by_id("youtube").home(self.home) / f"config/VacuumTube-steam-{account}/config.json"
        settings.write_text(json.dumps({"disabled_tabs": [], "fullscreen": False, "volume": 80}))
        return hero, settings

    def launch(self, *argv):
        with mock.patch("nonsteamapps.cli.os.execvp", side_effect=fake_exec), \
                mock.patch("nonsteamapps.cli.os.execv", side_effect=fake_exec), \
                mock.patch("nonsteamapps.cli._redirect") as redirect, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Exec) as raised:
                cli.main(["launch", *argv], self.paths, self.flatpak)
        return raised.exception.args[0], redirect


class InstallTests(CliTestCase):
    def test_first_install_adds_every_app_for_every_account(self):
        self.install()
        self.assertEqual(
            [call[-1] for call in self.fake.calls("install")],
            ["rocks.shy.VacuumTube", "im.riot.Riot", "org.signal.Signal", "com.bitwarden.desktop", "org.jellyfin.JellyfinDesktop",
             "org.localsend.localsend_app", "org.prismlauncher.PrismLauncher", "dev.eden_emu.eden", "net.davidotek.pupgui2",
             "com.github.Matoking.protontricks"],
        )
        record = config.Record.load(self.paths.record)
        self.assertEqual(record.managed(), apps.ids())
        self.assertEqual(
            [app.id for app in apps.APPS if record.owns_flatpak(app.id)],
            ["youtube", "element", "signal", "bitwarden", "jellyfin", "localsend", "prism", "eden", "protonup", "protontricks"],
        )
        self.assertIn("Note:", self.errors)
        self.assertIn("Signal keeps its database key unencrypted on disk", self.errors)
        self.assertEqual(cli._runtime(self.paths).current(), "0.0.0.1")
        for account in (ALPHA, BETA):
            entries = self.entries(account)
            self.assertEqual(sorted(entries), sorted(app.name for app in apps.APPS))
            for app in apps.APPS:
                entry = entries[app.name]
                self.assertEqual(entry.get("Exe"), f'"{self.paths.app_link(app.id)}"')
                self.assertEqual(entry.get("LaunchOptions"), f"--steam-account {account}")
                self.assertEqual(entry.get("AllowOverlay"), 0)
                appid = steam.to_unsigned32(entry.get("appid"))
                grid = steam.config_dir(self.root, account) / "grid"
                self.assertTrue((grid / f"{appid}p.png").is_file())
                self.assertTrue((grid / f"{appid}_hero.jpg").is_file())
        for app_id in apps.ids():
            link = self.paths.app_link(app_id)
            self.assertEqual(link.resolve(), self.paths.launcher.resolve())
        self.assertTrue(self.paths.settings.is_file())

    def test_summary_lines_up_and_names_each_client_once(self):
        self.install("youtube", "localsend")
        self.assertIn("    YouTube:   Steam ▸ Library ▸ Non-Steam ▸ YouTube (VacuumTube)\n", self.errors)
        self.assertIn("    LocalSend: Steam ▸ Library ▸ Non-Steam ▸ LocalSend\n", self.errors)
        self.assertIn("    Sign-ins:  separate for each Steam account\n", self.errors)
        self.assertNotIn("Note:", self.errors)

    def test_rerunning_without_names_installs_every_app_and_puts_back_their_set_up(self):
        self.install("youtube")
        hero, settings = self.customise()
        self.install()
        self.assertEqual([call[-1] for call in self.fake.calls("install")], [app.flatpak for app in apps.APPS if app.flatpak])
        entries = self.entries(ALPHA)
        self.assertEqual(sorted(entries), sorted(app.name for app in apps.APPS))
        self.assertEqual(entries["YouTube"].get("LaunchOptions"), f"--steam-account {ALPHA}")
        self.assertEqual(hero.read_bytes(), (self.paths.artwork("youtube") / "hero.jpg").read_bytes())
        data = json.loads(settings.read_text())
        self.assertEqual((data["disabled_tabs"], data["fullscreen"], data["volume"]), (["shorts", "podcasts"], True, 80))
        self.assertIn("Put back YouTube's TV settings (1 data folder); sign-ins are kept", self.errors)

    def test_a_full_install_asks_first_and_declining_changes_nothing(self):
        self.install("youtube")
        asked = []

        def confirm(question, default=False, unattended=None):
            asked.append(question)
            return False

        with mock.patch("nonsteamapps.ui.confirm", side_effect=confirm):
            self.assertEqual(self.run_cli("install", "--no-auto-update"), 1)
        self.assertTrue(asked[0].startswith("Install YouTube (VacuumTube), Element (Element Desktop), "))
        self.assertIn("The apps already installed get NonSteamApps' set-up back; their sign-ins and data are kept.", asked[0])
        self.assertIn(f"or update the apps you have with: {self.paths.launcher} update", self.errors)
        self.assertEqual(sorted(self.entries(ALPHA)), ["YouTube"])

    def test_unknown_app_is_rejected(self):
        self.assertEqual(self.run_cli("install", "kodi", "--yes"), 1)
        self.assertIn("unknown app 'kodi'", self.errors)

    def test_refuses_to_close_steam_in_game_mode(self):
        with mock.patch("nonsteamapps.steamclient.running", return_value=True), \
                mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True):
            self.assertEqual(self.run_cli("install", "youtube", "--yes", "--no-auto-update"), 1)
        self.assertIn("Switch to Desktop Mode", self.errors)
        self.assertFalse((steam.config_dir(self.root, ALPHA) / "shortcuts.vdf").exists())

    def test_update_timer_runs_the_launcher_weekly(self):
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        calls = Path(self.tmp.name) / "systemctl.log"
        (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
        (bin_dir / "systemctl").chmod(0o755)
        service = self.paths.systemd / "nonsteamapps-update.service"
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
            self.assertEqual(self.run_cli("install", "youtube", "--yes"), 0, self.errors)
            self.assertIn(f'ExecStart="{self.paths.launcher}" update --quiet --apps-only\n', service.read_text())
            self.assertIn("--user enable --now nonsteamapps-update.timer", calls.read_text())
            service.write_text("from an older NonSteamApps")
            reloads = calls.read_text().count("daemon-reload")
            self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
            self.assertIn("update --quiet --apps-only", service.read_text())
            self.assertEqual(calls.read_text().count("daemon-reload"), reloads + 1)
            self.assertEqual(self.run_cli("install", "youtube", "--yes", "--no-auto-update"), 0, self.errors)
        self.assertFalse((self.paths.systemd / "nonsteamapps-update.timer").exists())


class ExistingFlatpakTests(CliTestCase):
    def preinstalled(self):
        return {"im.riot.Riot": {"version": "1.12.33", "installation": "system"}}

    def test_uses_an_installed_app_and_never_uninstalls_it(self):
        self.install("element")
        self.assertEqual(self.fake.calls("install"), [])
        self.assertIn("Element Desktop 1.12.33 is already installed (system installation)", self.errors)
        self.assertFalse(config.Record.load(self.paths.record).owns_flatpak("element"))
        self.assertEqual(self.run_cli("remove", "element", "--yes"), 0, self.errors)
        self.assertEqual(self.fake.calls("uninstall"), [])
        self.assertIn("stays installed", self.errors)
        self.assertEqual(self.entries(ALPHA), {})


class MigrationTests(CliTestCase):
    def test_takes_over_steamos_yt_and_its_shortcut(self):
        appid = _fakes.make_legacy(self.home, self.root, shared_sign_in=True)
        self.install("element")
        for account in (ALPHA, BETA):
            youtube = self.entries(account)["YouTube"]
            self.assertEqual(steam.to_unsigned32(youtube.get("appid")), appid)
            self.assertEqual(youtube.get("Exe"), f'"{self.paths.app_link("youtube")}"')
        self.assertEqual(config.Record.load(self.paths.record).managed(), ["youtube", "element"])
        self.assertFalse((self.home / ".local/share/steamos-yt").exists())
        self.assertFalse((self.home / ".config/steamos-yt").exists())
        self.assertEqual(config.read_settings(self.paths.settings)[cli.PER_ACCOUNT], "0")

    def test_keeps_steamos_yt_when_the_steam_library_is_left_alone(self):
        _fakes.make_legacy(self.home, self.root)
        self.assertEqual(self.run_cli("install", "youtube", "--yes", "--no-auto-update", "--no-steam"), 0, self.errors)
        self.assertTrue((self.home / ".local/share/steamos-yt/bin/steamos-yt").exists())
        self.assertIn("Kept SteamOS YT", self.errors)


class LaunchTests(CliTestCase):
    def test_each_account_gets_its_own_vacuumtube_folder(self):
        self.install("youtube")
        argv, redirect = self.launch("youtube", "--steam-account", str(BETA), "--", "--debug-gpu")
        folder = self.home / f".var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-{BETA}"
        self.assertEqual(argv, [self.fake.command, "run", "rocks.shy.VacuumTube", "--fullscreen", f"--portable={folder}", "--debug-gpu"])
        self.assertTrue(folder.is_dir())
        redirect.assert_called_once_with(self.paths.log("youtube"))

    def test_vacuumtube_gets_the_steamos_theme_and_keeps_the_styles_turned_off(self):
        self.install("youtube")
        folder = self.home / f".var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-{BETA}"
        source = self.paths.userstyles / "nonsteamapps-steamos.css"
        self.launch("youtube", "--steam-account", str(BETA))
        sheet = folder / "userstyles" / "nonsteamapps-steamos.css"
        self.assertEqual(sheet.read_bytes(), source.read_bytes())
        settings = json.loads((folder / "config.json").read_text())
        self.assertTrue(settings["userstyles"])
        settings["disabled_userstyles"] = ["nonsteamapps-steamos.css"]
        (folder / "config.json").write_text(json.dumps(settings))
        sheet.write_text("/* changed */")
        self.launch("youtube", "--steam-account", str(BETA))
        self.assertEqual(sheet.read_bytes(), source.read_bytes())
        self.assertEqual(json.loads((folder / "config.json").read_text())["disabled_userstyles"], ["nonsteamapps-steamos.css"])
        config.set_setting(self.paths.settings, cli.PER_ACCOUNT, "0")
        self.launch("youtube", "--steam-account", str(BETA))
        self.assertTrue((self.home / ".var/app/rocks.shy.VacuumTube/config/VacuumTube/userstyles/nonsteamapps-steamos.css").is_file())
        self.launch("element", "--steam-account", str(BETA))
        self.assertFalse((self.home / ".var/app/im.riot.Riot/config/Element/userstyles").exists())

    def test_launch_outside_steam_uses_the_most_recent_account(self):
        argv, _ = self.launch("element")
        self.assertEqual(argv[-1], f"--profile=steam-{ALPHA}")

    def test_shared_data_when_separate_sign_ins_are_off(self):
        self.install("element")
        config.set_setting(self.paths.settings, cli.PER_ACCOUNT, "0")
        argv, _ = self.launch("element", "--steam-account", str(BETA))
        self.assertEqual(argv[3:], ["--password-store=basic", "--storage-mode=allow-plaintext"])
        argv, _ = self.launch("youtube", "--steam-account", str(BETA))
        self.assertEqual(argv[3:], ["--fullscreen"])
        self.assertTrue((self.home / ".var/app/rocks.shy.VacuumTube/config/VacuumTube/config.json").is_file())

    def test_jellyfin_profile_is_created_before_it_is_selected(self):
        argv, _ = self.launch("jellyfin", f"--steam-account={BETA}")
        self.assertEqual(self.fake.calls("run"), [["run", "org.jellyfin.JellyfinDesktop", "--create-profile", f"steam-{BETA}"]])
        self.assertEqual(argv[3:], ["--tv", "--fullscreen", f"--profile=steam-{BETA}"])
        self.launch("jellyfin", f"--steam-account={BETA}")
        self.assertEqual(len(self.fake.calls("run")), 1)

    def test_falls_back_to_shared_data_when_jellyfin_cannot_create_a_profile(self):
        with mock.patch.dict(os.environ, {"FAKE_FLATPAK_FAIL": "run"}):
            argv, _ = self.launch("jellyfin", "--steam-account", str(ALPHA))
        self.assertEqual(argv[3:], ["--tv", "--fullscreen"])

    def test_localsend_starts_dark_in_its_oled_colours_with_one_set_of_settings_for_every_account(self):
        argv, redirect = self.launch("localsend", "--steam-account", str(BETA))
        self.assertEqual(argv, [self.fake.command, "run", "org.localsend.localsend_app"])
        settings = self.home / ".var/app/org.localsend.localsend_app/data/org.localsend.localsend_app/shared_preferences.json"
        self.assertEqual(json.loads(settings.read_text())["flutter.ls_color"], "oled")
        settings.write_text(json.dumps({"flutter.ls_theme": "light", "flutter.ls_color": "localsend"}))
        self.launch("localsend", "--steam-account", str(ALPHA))
        self.assertEqual(json.loads(settings.read_text()), {"flutter.ls_theme": "light", "flutter.ls_color": "localsend"})
        redirect.assert_called_once_with(self.paths.log("localsend"))

    def test_bitwarden_starts_with_each_accounts_folder_and_its_tokens_on_disk(self):
        argv, _ = self.launch("bitwarden", "--steam-account", str(ALPHA))
        folder = self.home / f".var/app/com.bitwarden.desktop/config/Bitwarden-steam-{ALPHA}"
        self.assertEqual(argv, [
            self.fake.command, "run", f"--env=BITWARDEN_APPDATA_DIR={folder}", "--env=ACCESS_TOKEN_LOCATION=DISK", "com.bitwarden.desktop",
        ])
        self.assertFalse(json.loads((folder / "data.json").read_text())["global_desktopSettings_runInBackground"])

    def test_in_game_mode_bitwarden_fills_the_screen_without_its_menu_bar(self):
        folder = self.home / f".var/app/com.bitwarden.desktop/config/Bitwarden-steam-{ALPHA}"
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_height", return_value=1080), \
                mock.patch("nonsteamapps.cli.x11.watch") as watch, \
                mock.patch("nonsteamapps.cli.appmenu.watch", return_value=True) as menu:
            argv, _ = self.launch("bitwarden", "--steam-account", str(ALPHA))
        watch.assert_called_once_with("bitwarden", os.getpid())
        menu.assert_called_once_with(os.getpid())
        self.assertIn("--env=DISPLAY_MODE=X11", argv)
        self.assertIn("--force-device-scale-factor=1.5", argv)
        self.assertEqual(json.loads((folder / "data.json").read_text())["global_theming_selection"], "dark")
        with mock.patch("nonsteamapps.cli.x11.watch") as watch, mock.patch("nonsteamapps.cli.appmenu.watch") as menu:
            argv, _ = self.launch("bitwarden", "--steam-account", str(ALPHA))
        watch.assert_not_called()
        menu.assert_not_called()
        self.assertNotIn("--env=DISPLAY_MODE=X11", argv)

    def test_element_is_scaled_for_a_tv_only_in_game_mode(self):
        in_game_mode = mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True)
        with in_game_mode, mock.patch("nonsteamapps.display.screen_height", return_value=2160):
            argv, _ = self.launch("element", "--steam-account", str(ALPHA))
            youtube, _ = self.launch("youtube", "--steam-account", str(ALPHA))
        self.assertEqual(
            argv[3:],
            ["--password-store=basic", "--storage-mode=allow-plaintext", f"--profile=steam-{ALPHA}", "--force-device-scale-factor=3"],
        )
        self.assertEqual(youtube[-1], "--force-device-scale-factor=2")
        with mock.patch("nonsteamapps.display.screen_height", return_value=2160):
            argv, _ = self.launch("element", "--steam-account", str(ALPHA))
        self.assertEqual(argv[-1], f"--profile=steam-{ALPHA}")

    def test_vacuumtube_fits_youtubes_1080p_layout_and_keeps_the_tvs_video_resolution(self):
        folder = self.home / f".var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-{ALPHA}"
        settings = folder / "config.json"
        argv, _ = self.launch("youtube", "--steam-account", str(ALPHA))
        self.assertEqual(argv[3:], ["--fullscreen", f"--portable={folder}"])
        self.assertNotIn("unlock_resolution", json.loads(settings.read_text()))
        for height, scale in ((1080, []), (1440, ["--force-device-scale-factor=1.25"]), (2160, ["--force-device-scale-factor=2"])):
            with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                    mock.patch("nonsteamapps.display.screen_height", return_value=height):
                argv, _ = self.launch("youtube", "--steam-account", str(ALPHA))
            self.assertEqual(argv[3:], ["--fullscreen", f"--portable={folder}", *scale])
            self.assertEqual(json.loads(settings.read_text()).get("unlock_resolution"), True if scale else None)
        settings.write_text(json.dumps({"unlock_resolution": False}))
        self.launch("youtube", "--steam-account", str(ALPHA))
        self.assertFalse(json.loads(settings.read_text())["unlock_resolution"])

    def test_signal_starts_through_env_with_the_accounts_folder(self):
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_height", return_value=1080):
            argv, redirect = self.launch("signal", "--steam-account", str(BETA))
        folder = self.home / f".var/app/org.signal.Signal/config/Signal-steam-{BETA}"
        self.assertEqual(
            argv,
            [self.fake.command, "run", "--command=env", "org.signal.Signal", f"XDG_CONFIG_HOME={folder}",
             "SIGNAL_PASSWORD_STORE=basic", "signal-desktop", "--force-device-scale-factor=1.5"],
        )
        self.assertEqual(json.loads((folder / "Signal/config.json").read_text()), {})
        redirect.assert_called_once_with(self.paths.log("signal"))
        self.paths.settings.parent.mkdir(parents=True, exist_ok=True)
        self.paths.settings.write_text(f"{cli.PER_ACCOUNT}=0\n")
        argv, _ = self.launch("signal", "--steam-account", str(BETA))
        self.assertEqual(argv, [self.fake.command, "run", "org.signal.Signal"])

    def test_jellyfin_and_localsend_are_scaled_for_a_tv_in_game_mode(self):
        self.launch("jellyfin", "--steam-account", str(ALPHA))
        for height, jellyfin, localsend in ((2160, "--scale-factor=3", ["--env=GDK_SCALE=3"]), (1080, "--scale-factor=1.5", [])):
            with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                    mock.patch("nonsteamapps.display.screen_height", return_value=height):
                argv, _ = self.launch("jellyfin", "--steam-account", str(ALPHA))
                self.assertEqual(argv[3:], ["--tv", "--fullscreen", f"--profile=steam-{ALPHA}", jellyfin])
                argv, _ = self.launch("localsend", "--steam-account", str(ALPHA))
                self.assertEqual(argv, [self.fake.command, "run", *localsend, "org.localsend.localsend_app"])

    def test_prism_starts_with_each_accounts_folder_and_is_scaled_for_a_tv(self):
        folder = self.home / f".var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher-steam-{ALPHA}"
        argv, _ = self.launch("prism", "--steam-account", str(ALPHA))
        self.assertEqual(argv, [self.fake.command, "run", "org.prismlauncher.PrismLauncher", f"--dir={folder}"])
        self.assertTrue((folder / "prismlauncher.cfg").is_file())
        self.assertTrue((folder / "assets").is_symlink())
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_size", return_value=(3840, 2160)):
            argv, _ = self.launch("prism", "--steam-account", str(ALPHA))
        self.assertEqual(argv, [
            self.fake.command, "run", "--env=QT_SCALE_FACTOR=3", "--env=QT_QPA_PLATFORM=xcb", "org.prismlauncher.PrismLauncher", f"--dir={folder}",
            "-qwindowgeometry", "1280x720+0+0",
        ])

    def test_eden_starts_in_each_accounts_folder_full_screen_on_x11_and_scaled_for_a_tv(self):
        folder = self.home / f".var/app/dev.eden_emu.eden/data/eden-steam-{ALPHA}"
        games = self.home / "Games" / "Switch"
        x11 = ["--socket=x11", "--nosocket=fallback-x11", "--env=QT_QPA_PLATFORM=xcb"]
        argv, _ = self.launch("eden", "--steam-account", str(ALPHA))
        self.assertEqual(argv, [self.fake.command, "run", f"--cwd={folder}", f"--filesystem={games}:ro", *x11, "dev.eden_emu.eden", "-f"])
        settings = (folder / "user/config/qt-config.ini").read_text()
        self.assertIn(f"Paths\\gamedirs\\4\\path={games}\nPaths\\gamedirs\\4\\deep_scan=true\nPaths\\gamedirs\\size=4\n", settings)
        self.assertTrue(games.is_dir())
        self.assertEqual((folder / "user/keys").resolve(), (self.home / ".var/app/dev.eden_emu.eden/data/eden/keys").resolve())
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_size", return_value=(3840, 2160)):
            argv, _ = self.launch("eden", "--steam-account", str(ALPHA))
        self.assertEqual(argv, [
            self.fake.command, "run", f"--cwd={folder}", f"--filesystem={games}:ro", "--env=QT_SCALE_FACTOR=3", *x11,
            "dev.eden_emu.eden", "-f", "-qwindowgeometry", "1280x720+0+0",
        ])
        self.assertEqual((folder / "user/config/qt-config.ini").read_text().count(str(games)), 1)
        self.install("eden")
        config.set_setting(self.paths.settings, cli.PER_ACCOUNT, "0")
        argv, _ = self.launch("eden", "--steam-account", str(ALPHA))
        self.assertEqual(argv[2:], [f"--filesystem={games}:ro", *x11, "dev.eden_emu.eden", "-f"])
        self.assertIn(f"path={games}\n", (self.home / ".var/app/dev.eden_emu.eden/config/eden/qt-config.ini").read_text())

    def test_the_proton_tools_start_with_a_tv_set_up_and_reach_every_steam_library(self):
        library = Path(self.tmp.name) / "SD Card"
        library.mkdir()
        (self.root / "steamapps").mkdir()
        (self.root / "steamapps/libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{self.root}" }} "1" {{ "path" "{library}" }} "2" {{ "path" "/run/media/gone" }} }}\n'
        )
        argv, _ = self.launch("protonup", "--steam-account", str(ALPHA))
        self.assertEqual(argv, [
            self.fake.command, "run", "--env=PUPGUI2_DISABLE_GAMEPAD=1", f"--filesystem={self.root}", f"--filesystem={library}", "net.davidotek.pupgui2",
        ])
        config_ini = self.home / ".var/app/net.davidotek.pupgui2/config/pupgui/config.ini"
        self.assertEqual(config_ini.read_text(), "[pupgui2]\ntheme=steam\n")
        config_ini.write_text("[pupgui2]\ntheme = light\n\n[pupgui]\ninstalldir = /home/deck/.steam/root/compatibilitytools.d/\n")
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_height", return_value=1080), \
                mock.patch.dict(os.environ, {"STEAM_COMPAT_DATA_PATH": "/somewhere/compatdata/1245620"}):
            argv, _ = self.launch("protonup", "--steam-account", str(ALPHA))
            self.assertEqual(argv[2:5], ["--env=QT_SCALE_FACTOR=1.5", "--env=PUPGUI2_DISABLE_GAMEPAD=1", "--env=QT_QPA_PLATFORM=xcb"])
            argv, _ = self.launch("protontricks", "--steam-account", str(ALPHA))
            self.assertEqual(argv, [
                self.fake.command, "run", "--env=GDK_DPI_SCALE=1.5", "--env=GDK_BACKEND=x11", f"--filesystem={self.root}", f"--filesystem={library}",
                "com.github.Matoking.protontricks", "--no-term", "--gui",
            ])
            self.assertNotIn("STEAM_COMPAT_DATA_PATH", os.environ)
        self.assertIn("theme = light", config_ini.read_text())
        self.install("protonup")
        self.assertEqual(config_ini.read_text(), "[pupgui2]\ntheme=steam\n\n[pupgui]\ninstalldir = /home/deck/.steam/root/compatibilitytools.d/\n")
        self.assertIn("Put back ProtonUp-Qt's TV settings (1 data folder)", self.errors)

    def test_prism_gets_the_minecraft_layout(self):
        folder = _fakes.add_controller_templates(self.root)
        self.install("prism")
        self.assertTrue((folder / "controller_xboxone_nonsteamapps_minecraft.vdf").is_file())
        config = steam_controller_config(self.root, BETA)
        entry = vdf.loads_text((config / "configset_controller_neptune.vdf").read_text()).get("controller_config").get("prism launcher")
        self.assertEqual(entry.get("template"), "controller_neptune_nonsteamapps_minecraft.vdf")
        self.assertIn("Gave Prism Launcher the Minecraft (NonSteamApps) controller layout", self.errors)
        self.assertIn("Prism Launcher asks for a language and the Microsoft account", self.errors)
        self.assertEqual(self.run_cli("remove", "prism", "--yes"), 0, self.errors)
        self.assertFalse((folder / "controller_xboxone_nonsteamapps_minecraft.vdf").exists())

    def test_keeping_the_sandbox_hides_game_mode_from_vacuumtube_only(self):
        os.environ.update({"SteamOS": "1", "SteamGamepadUI": "1"})
        self.launch("youtube", "--steam-account", str(ALPHA))
        self.assertEqual(os.environ.get("SteamGamepadUI"), "1")
        self.paths.settings.parent.mkdir(parents=True, exist_ok=True)
        self.paths.settings.write_text(f"{cli.GAME_MODE_SANDBOX}=1\n")
        self.launch("element", "--steam-account", str(ALPHA))
        self.assertEqual(os.environ.get("SteamGamepadUI"), "1")
        argv, _ = self.launch("youtube", "--steam-account", str(ALPHA))
        self.assertNotIn("SteamGamepadUI", os.environ)
        self.assertEqual(os.environ["SteamOS"], "1")
        self.assertEqual(argv[3], "--fullscreen")

    def test_unknown_or_missing_app(self):
        self.assertEqual(self.run_cli("launch", "kodi"), 1)
        self.assertEqual(self.run_cli("launch", "--steam-account", "1"), 1)


class CollectionTests(CliTestCase):
    def storage(self, account):
        return collection.storage_file(self.root, account)

    def test_every_app_goes_in_its_own_collection_in_every_account(self):
        self.install()
        for account in (ALPHA, BETA):
            appids = sorted(steam.to_unsigned32(entry.get("appid")) for entry in self.entries(account).values())
            self.assertEqual(sorted(collection.members(self.storage(account))), appids)
            stored = {key: value for key, value in json.loads(self.storage(account).read_text())}
            self.assertEqual(json.loads(stored[collection.KEY]["value"])["name"], "NonSteamApps")
            for key, original in _fakes.USER_COLLECTIONS:
                self.assertEqual(stored[key], original)
        self.assertIn('Put YouTube (VacuumTube), ', self.errors)
        self.assertIn('in the "NonSteamApps" collection', self.errors)
        youtube = steam.to_unsigned32(self.entries(ALPHA)["YouTube"].get("appid"))
        self.assertEqual(self.run_cli("remove", "youtube", "--yes"), 0, self.errors)
        self.assertNotIn(youtube, collection.members(self.storage(ALPHA)))
        self.assertEqual(self.run_cli("uninstall", "--yes"), 0, self.errors)
        for account in (ALPHA, BETA):
            stored = {key: value for key, value in json.loads(self.storage(account).read_text())}
            self.assertTrue(stored[collection.KEY]["is_deleted"])

    def test_the_setting_names_the_collection_or_turns_it_off(self):
        self.install("youtube")
        config.set_setting(self.paths.settings, cli.COLLECTION, "Living room")
        self.install()
        stored = {key: value for key, value in json.loads(self.storage(ALPHA).read_text())}
        self.assertEqual(json.loads(stored[collection.KEY]["value"])["name"], "Living room")
        config.set_setting(self.paths.settings, cli.COLLECTION, "")
        self.install()
        self.assertEqual(collection.members(self.storage(ALPHA)), [])

    def test_an_account_steam_has_not_set_up_is_reported(self):
        shutil.rmtree(steam.config_dir(self.root, BETA) / "cloudstorage")
        self.install("youtube")
        self.assertIn("Steam has not set up collections for P222 yet", self.errors)
        self.assertEqual(len(collection.members(self.storage(ALPHA))), 1)


class FirewallTests(CliTestCase):
    def test_localsend_gets_its_port_while_installed(self):
        self.wall.set(running=True)
        self.install("localsend")
        for permanent in (True, False):
            self.assertEqual(self.wall.ports(permanent=permanent), ["53317/tcp", "53317/udp"])
        self.assertIn("Opened port 53317 (TCP and UDP) in the firewall for LocalSend", self.errors)
        self.assertEqual(config.Record.load(self.paths.record).opened_ports("localsend"), {"public": ["53317/tcp", "53317/udp"]})
        changes = len(self.wall.changes())
        self.install()
        self.assertEqual(len(self.wall.changes()), changes)
        self.assertEqual(self.run_cli("doctor"), 0, self.errors)
        self.assertIn("firewalld running; LocalSend's port 53317 (TCP and UDP) open", self.output)
        self.assertEqual(self.run_cli("remove", "localsend", "--yes"), 0, self.errors)
        self.assertEqual((self.wall.ports(), self.wall.ports(permanent=False)), ([], []))
        self.assertIn("Closed port 53317 (TCP and UDP), which NonSteamApps opened for LocalSend", self.errors)

    def test_nothing_is_opened_without_a_running_firewall_or_for_other_apps(self):
        self.install("localsend")
        self.wall.set(running=True)
        self.install("youtube", "element")
        self.assertEqual(self.wall.changes(), [])
        self.assertEqual(self.run_cli("doctor"), 0, self.errors)
        self.assertIn("LocalSend's port 53317 (TCP and UDP) closed in public; run the installer again to open it", self.output)

    def test_without_sudo_the_commands_to_run_are_shown(self):
        self.wall.set(running=True, active=("home", "public"))
        with mock.patch.dict(os.environ, {"FAKE_SUDO_FAIL": "1"}):
            self.install("localsend")
        self.assertIn("Could not open port 53317 (TCP and UDP) for LocalSend (sudo: a password is required)", self.errors)
        self.assertIn("sudo firewall-cmd --permanent --zone=home --add-port=53317/tcp --add-port=53317/udp", self.errors)
        self.assertIn("sudo firewall-cmd --zone=public --add-port=53317/tcp --add-port=53317/udp", self.errors)
        self.assertEqual(config.Record.load(self.paths.record).opened_ports("localsend"), {})
        self.install("localsend")
        self.assertEqual(self.wall.ports("home"), ["53317/tcp", "53317/udp"])
        self.assertEqual(self.wall.ports("public"), ["53317/tcp", "53317/udp"])

    def test_keeping_the_app_keeps_its_port(self):
        self.wall.set(running=True)
        self.install("localsend")
        self.assertEqual(self.run_cli("remove", "localsend", "--keep-app", "--yes"), 0, self.errors)
        self.assertEqual(self.wall.ports(), ["53317/tcp", "53317/udp"])


class RemovalTests(CliTestCase):
    def test_remove_with_purge_deletes_only_per_account_data(self):
        self.install("youtube", "element")
        app_home = apps.by_id("youtube").home(self.home)
        ours, theirs = app_home / f"config/VacuumTube-steam-{ALPHA}", app_home / "config/VacuumTube"
        ours.mkdir(parents=True)
        theirs.mkdir(parents=True)
        self.assertEqual(self.run_cli("remove", "youtube", "--purge", "--yes"), 0, self.errors)
        self.assertFalse(ours.exists())
        self.assertTrue(theirs.is_dir())
        self.assertEqual(sorted(self.entries(BETA)), ["Element"])
        self.assertFalse(self.paths.app_link("youtube").is_symlink())
        self.assertNotIn("rocks.shy.VacuumTube", self.fake.apps())
        self.assertEqual(self.fake.calls("uninstall")[-1], ["uninstall", "--user", "--unused", "--noninteractive", "-y"])
        self.assertEqual(config.Record.load(self.paths.record).managed(), ["element"])

    def test_purge_needs_a_clear_yes(self):
        self.install("youtube")
        with mock.patch("nonsteamapps.ui.confirm", return_value=False):
            self.assertEqual(self.run_cli("remove", "youtube", "--purge"), 1)
        self.assertEqual(sorted(self.entries(ALPHA)), ["YouTube"])

    def test_keep_app_only_removes_the_shortcut(self):
        self.install("jellyfin")
        self.assertEqual(self.run_cli("remove", "jellyfin", "--keep-app", "--yes"), 0, self.errors)
        self.assertIn("org.jellyfin.JellyfinDesktop", self.fake.apps())
        self.assertEqual(self.entries(ALPHA), {})

    def test_uninstall_removes_everything_but_settings_and_sign_ins(self):
        self.install()
        data = apps.by_id("element").home(self.home) / f"config/Element-steam-{ALPHA}"
        data.mkdir(parents=True)
        self.assertEqual(self.run_cli("uninstall", "--yes"), 0, self.errors)
        self.assertFalse(self.paths.program.exists())
        self.assertFalse(self.paths.state.exists())
        self.assertTrue(self.paths.settings.is_file())
        self.assertTrue(data.is_dir())
        self.assertEqual(self.fake.apps(), {})
        self.assertEqual(self.entries(ALPHA), {})

    def test_uninstall_refuses_an_unexpected_folder(self):
        (self.paths.program / "lib" / "nonsteamapps" / "__init__.py").unlink()
        self.assertEqual(self.run_cli("uninstall", "--yes"), 1)
        self.assertTrue(self.paths.program.is_dir())


class InformationTests(CliTestCase):
    def test_update_only_touches_apps_it_installed(self):
        self.fake.state.write_text('{"apps": {"im.riot.Riot": {"version": "1", "installation": "user"}}}')
        self.install("youtube", "element")
        self.assertEqual(self.run_cli("update", "--quiet"), 0, self.errors)
        self.assertEqual(self.fake.calls("update"), [["update", "--user", "--noninteractive", "-y", "rocks.shy.VacuumTube"]])

    def test_list_status_and_doctor(self):
        self.install("youtube")
        self.assertEqual(self.run_cli("list"), 0)
        self.assertRegex(self.output, r"youtube\s+in use\s+VacuumTube 1\.0\.0 \(user installation, installed by NonSteamApps\)")
        self.assertRegex(self.output, r"element\s+available\s+not installed")
        self.assertEqual(self.run_cli("steam", "status"), 0)
        self.assertIn(f'Steam account P{BETA} ({BETA}): present "YouTube"', self.output)
        self.assertEqual(self.run_cli("doctor"), 0)
        self.assertIn("youtube", self.output)
        self.assertIn('in the library as "YouTube"', self.output)



class SteamPlayTests(CliTestCase):
    def force(self, app_id, tool):
        app = apps.by_id(app_id)
        appid = steam.shortcut_appid(steam.quote(str(self.paths.app_link(app.id))), app.name)
        path = compat.config_file(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(vdf.dumps_pairs([("InstallConfigStore", [("Software", [("Valve", [("Steam", [("CompatToolMapping", [
            (str(appid), [("name", tool), ("config", ""), ("priority", "250")]),
            ("1245620", [("name", "proton_9"), ("config", ""), ("priority", "250")]),
        ])])])])])]))
        return appid

    def test_a_forced_steam_play_tool_is_removed_so_the_app_runs_natively(self):
        appid = self.force("localsend", "proton_experimental")
        self.install("localsend")
        self.assertIn("LocalSend no longer forces the Steam Play tool proton_experimental", self.errors)
        self.assertEqual(compat.forced(self.root, [appid, 1245620]), {1245620: "proton_9"})
        self.force("localsend", "steamlinuxruntime_sniper")
        self.assertEqual(self.run_cli("doctor"), 0, self.errors)
        self.assertIn("forced to the Steam Play tool steamlinuxruntime_sniper", self.output)
        self.assertEqual(self.run_cli("remove", "localsend", "--yes"), 0, self.errors)
        self.assertNotIn(str(appid), compat.config_file(self.root).read_text())
        self.assertEqual(compat.forced(self.root, [1245620]), {1245620: "proton_9"})


class FilesTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        (self.bin / "dolphin").symlink_to(_fakes.FAKES / "dolphin")
        patch = mock.patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        patch.start()
        self.addCleanup(patch.stop)
        self.profile = self.paths.profile("files", None)

    def launch_files(self, game_mode=False, height=2160):
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=game_mode), \
                mock.patch("nonsteamapps.display.screen_height", return_value=height), \
                mock.patch.dict(os.environ):
            argv, _ = self.launch("files", "--steam-account", str(ALPHA))
            environ = dict(os.environ)
        return argv, environ

    def test_files_starts_steamos_dolphin_with_its_tv_profile(self):
        self.install("files")
        self.assertIn(f"Dolphin is part of the system ({self.bin / 'dolphin'})", self.errors)
        argv, environ = self.launch_files()
        self.assertEqual(argv, [str(self.bin / "dolphin"), "--new-window"])
        self.assertEqual(environ["XDG_CONFIG_HOME"], str(self.profile / "config"))
        self.assertEqual(environ["XDG_STATE_HOME"], str(self.profile / "state"))
        self.assertTrue(environ["XDG_CONFIG_DIRS"].startswith(f"{self.home / '.config'}:"))
        self.assertFalse([name for name in environ if name.startswith("QT_")])
        self.assertTrue((self.profile / "config" / "dolphinrc").is_file())

    def test_in_game_mode_files_is_scaled_and_themed_for_a_tv(self):
        for height, factor in ((2160, "3"), (1080, "1.5")):
            argv, environ = self.launch_files(game_mode=True, height=height)
            self.assertEqual(argv, [str(self.bin / "dolphin"), "--new-window"])
            self.assertEqual(
                (environ["QT_SCALE_FACTOR"], environ["QT_QPA_PLATFORM"], environ["QT_QPA_PLATFORMTHEME"]), (factor, "xcb", "kde")
            )
            self.assertEqual(environ["XDG_CONFIG_HOME"], str(self.profile / "config"))

    def test_in_game_mode_files_opens_as_large_as_the_screen(self):
        self.install("files")
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_size", return_value=(1920, 1080)), mock.patch.dict(os.environ):
            argv, _ = self.launch("files", "--steam-account", str(ALPHA))
        self.assertEqual(argv[1:], ["--new-window", "-qwindowgeometry", "1280x720+0+0"])
        argv, _ = self.launch_files()
        self.assertEqual(argv[1:], ["--new-window"])

    def test_without_dolphin_files_says_what_is_missing(self):
        (self.bin / "dolphin").unlink()
        self.install("files")
        self.assertIn("Dolphin (dolphin) was not found", self.errors)
        self.assertEqual(self.run_cli("list"), 0)
        self.assertIn("not found (dolphin)", self.output)
        self.assertNotEqual(self.run_cli("launch", "files", "--verbose"), 0)
        self.assertIn("Dolphin (dolphin) is not installed", self.errors)

    def test_files_gets_its_own_controller_layout_until_it_is_removed(self):
        folder = _fakes.add_controller_templates(self.root)
        self.install("files")
        ours = ["controller_neptune_nonsteamapps_files.vdf", "controller_xboxone_nonsteamapps_files.vdf"]
        self.assertTrue(all((folder / name).is_file() for name in ours))
        for account in (ALPHA, BETA):
            config = steam_controller_config(self.root, account)
            self.assertEqual(vdf.loads_text((config / "configset_controller_neptune.vdf").read_text()).get("controller_config").get("files").get("template"), ours[0])
            self.assertEqual(vdf.loads_text((config / "configset_controller_xboxone.vdf").read_text()).get("controller_config").get("files").get("template"), ours[1])
        self.assertIn("Gave Files (Dolphin) the Files (NonSteamApps) controller layout", self.errors)
        (folder / ours[1]).unlink()
        self.assertEqual(self.run_cli("update"), 0, self.errors)
        self.assertTrue((folder / ours[1]).is_file())
        self.assertIn("Refreshed the Files (NonSteamApps) controller layout", self.errors)
        self.assertEqual(self.run_cli("update"), 0, self.errors)
        self.assertNotIn("Refreshed", self.errors)
        self.launch_files()
        self.assertEqual(self.run_cli("remove", "files", "--purge", "--yes"), 0, self.errors)
        self.assertFalse(any((folder / name).exists() for name in ours))
        self.assertTrue((folder / "controller_neptune_webbrowser.vdf").is_file())
        self.assertIsNone(vdf.loads_text((steam_controller_config(self.root, ALPHA) / "configset_controller_neptune.vdf").read_text()).get("controller_config").get("files"))
        self.assertFalse(self.profile.exists())


def steam_controller_config(root, account):
    return root / f"steamapps/common/Steam Controller Configs/{account}/config"


class HeliumAppTests(CliTestCase):
    def configset(self, account=ALPHA):
        path = self.root / f"steamapps/common/Steam Controller Configs/{account}/config/configset_controller_neptune.vdf"
        return vdf.loads_text(path.read_text()).get("controller_config") if path.exists() else vdf.KeyValues()

    def test_helium_apps_share_one_helium_and_get_the_browser_layout(self):
        _fakes.add_controller_templates(self.root)
        self.install("youtube", "element", "helium", "primevideo", "hbomax", "netflix", "disneyplus")
        self.assertEqual(cli._runtime(self.paths).current(), "0.0.0.1")
        for account in (ALPHA, BETA):
            self.assertEqual(sorted(self.configset(account)),
                             ["disney+", "element", "hbo max", "helium", "netflix", "prime video", "youtube"])
            self.assertEqual(self.configset(account).get("youtube").get("template"), "controller_neptune_nonsteamapps_youtube.vdf")
            self.assertEqual(self.configset(account).get("element").get("template"), "controller_neptune_webbrowser.vdf")
            self.assertEqual(self.configset(account).get("netflix").get("template"), "controller_neptune_nonsteamapps_browser.vdf")
        self.assertIn("Gave Element (Element Desktop) the Web Browser controller layout", self.errors)
        self.assertIn("Gave Helium, Prime Video (Helium), HBO Max (Helium), Netflix (Helium) and Disney+ (Helium) the Browser (NonSteamApps) controller layout", self.errors)
        self.assertIn("Gave YouTube (VacuumTube) the YouTube (NonSteamApps) controller layout", self.errors)
        self.assertEqual(self.run_cli("remove", "element", "hbomax", "disneyplus", "--yes"), 0, self.errors)
        self.assertEqual(sorted(self.configset()), ["helium", "netflix", "prime video", "youtube"])

    def test_missing_layouts_are_reported_not_fatal(self):
        self.install("helium")
        self.assertIn("The Browser (NonSteamApps) controller layout was not found", self.errors)

    def test_prime_video_starts_full_screen_in_its_own_profile_for_each_account(self):
        self.install("primevideo")
        argv, redirect = self.launch("primevideo", "--steam-account", str(BETA))
        runtime = cli._runtime(self.paths)
        profile = self.paths.profiles / "primevideo" / str(BETA)
        self.assertEqual(argv[0], str(runtime.executable))
        self.assertEqual(argv[1], f"--user-data-dir={profile}")
        self.assertIn("--kiosk", argv)
        self.assertIn("--enable-spatial-navigation", argv)
        self.assertIn("--force-dark-mode", argv)
        self.assertEqual(argv[-1], "https://www.primevideo.com/")
        self.assertIn(f"--load-extension={self.paths.focus_extension}", argv)
        self.assertTrue((self.paths.focus_extension / "focus.css").is_file())
        preferences = json.loads((profile / "Default" / "Preferences").read_text())
        self.assertEqual(preferences["helium"]["browser"]["custom_accelerators"]["34031"], {"added": ["Control+Shift+KeyQ"]})
        self.assertEqual(preferences["helium"]["services"]["schema_version"], 1)
        self.assertTrue(preferences["helium"]["global_privacy_control"])
        self.assertEqual(json.loads((profile / "Local State").read_text())["helium"]["crash_reporting"]["mode"], -1)
        self.assertEqual((profile / "WidevineCdm").resolve(), runtime.widevine.resolve())
        redirect.assert_called_once_with(self.paths.log("primevideo"))

    def test_protondb_opens_the_library_of_the_account_that_starts_it(self):
        self.install("protondb")
        argv, _ = self.launch("protondb", "--steam-account", str(BETA))
        self.assertEqual(argv[-1], f"https://www.protondb.com/dashboard/{76561197960265728 + BETA}")
        self.assertIn("--kiosk", argv)
        config.set_setting(self.paths.settings, cli.PER_ACCOUNT, "0")
        argv, _ = self.launch("protondb", "--steam-account", str(BETA))
        self.assertEqual(argv[-1], "https://www.protondb.com/")

    def test_the_settings_choose_the_scale_and_services(self):
        self.install("helium")
        config.set_setting(self.paths.settings, cli.TV_SCALE, "1.25")
        config.set_setting(self.paths.settings, cli.HELIUM_SERVICES, "0")
        argv, _ = self.launch("helium")
        self.assertIn("--force-device-scale-factor=1.25", argv)
        self.assertIn("--start-maximized", argv)
        preferences = json.loads((self.paths.profiles / "helium" / str(ALPHA) / "Default" / "Preferences").read_text())
        self.assertFalse(preferences["helium"]["services"]["enabled"])

    def test_the_old_helium_scale_setting_still_applies(self):
        self.install("helium")
        self.paths.settings.write_text(f"{cli.HELIUM_SCALE}=1.75\n")
        argv, _ = self.launch("helium")
        self.assertIn("--force-device-scale-factor=1.75", argv)

    def test_helium_and_flatpak_apps_start_without_steams_overlay_or_runtime(self):
        self.install("hbomax")
        steam = {
            "LD_PRELOAD": "/home/deck/.local/share/Steam/ubuntu12_32/gameoverlayrenderer.so:"
                          "/home/deck/.local/share/Steam/ubuntu12_64/gameoverlayrenderer.so",
            "LD_LIBRARY_PATH": "/home/deck/.local/share/Steam/ubuntu12_32/steam-runtime/lib",
            "SYSTEM_LD_LIBRARY_PATH": "",
        }
        for app_id in ("hbomax", "youtube"):
            os.environ.update(steam)
            self.launch(app_id, "--steam-account", str(ALPHA))
            self.assertNotIn("LD_PRELOAD", os.environ, app_id)
            self.assertNotIn("LD_LIBRARY_PATH", os.environ, app_id)

    def test_in_game_mode_the_browser_window_fills_the_screen_and_keeps_its_tabs(self):
        self.install("helium", "netflix")
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_size", return_value=(1920, 1080)), \
                mock.patch("nonsteamapps.cli.x11.watch") as watch:
            argv, _ = self.launch("helium", "--steam-account", str(ALPHA))
            watch.assert_called_once_with("nonsteamapps-helium", os.getpid())
            self.assertIn("--window-size=1280,720", argv)
            self.assertIn("--window-position=0,0", argv)
            self.assertNotIn("--start-maximized", argv)
            watch.reset_mock()
            argv, _ = self.launch("netflix", "--steam-account", str(ALPHA))
            watch.assert_not_called()
            self.assertIn("--kiosk", argv)
        argv, _ = self.launch("helium", "--steam-account", str(ALPHA))
        self.assertIn("--start-maximized", argv)

    def test_game_mode_scales_the_pages_for_the_tv(self):
        self.install("hbomax")
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True), \
                mock.patch("nonsteamapps.display.screen_height", return_value=2160):
            argv, _ = self.launch("hbomax", "--steam-account", str(ALPHA))
        self.assertIn("--force-device-scale-factor=3", argv)
        self.assertIn("--ozone-platform=x11", argv)
        self.assertEqual(argv[-1], "https://www.hbomax.com/")

    def test_helium_goes_with_the_last_app_that_uses_it(self):
        self.install("helium", "primevideo")
        self.assertEqual(self.run_cli("remove", "primevideo", "--yes"), 0, self.errors)
        self.assertTrue(self.paths.helium.is_dir())
        self.assertEqual(self.run_cli("remove", "helium", "--yes"), 0, self.errors)
        self.assertFalse(self.paths.helium.exists())
        with mock.patch("nonsteamapps.cli._redirect"):
            self.assertEqual(self.run_cli("launch", "helium"), 1)
        self.assertIn("Helium is not installed", self.errors)

    def test_uninstall_keeps_helium_sign_ins_unless_purged(self):
        self.install("helium")
        self.launch("helium")
        self.assertEqual(self.run_cli("uninstall", "--yes"), 0, self.errors)
        self.assertEqual([path.name for path in self.paths.program.iterdir()], ["profiles"])
        self.assertTrue((self.paths.profiles / "helium" / str(ALPHA) / "Default" / "Preferences").is_file())

    def test_update_checks_helium_and_rollback_switches_back(self):
        self.install("helium")
        with mock.patch.object(cli.Runtime, "update", return_value="0.0.0.2"):
            self.assertEqual(self.run_cli("update"), 0, self.errors)
        self.assertIn("Updated Helium to 0.0.0.2", self.errors)
        self.assertEqual(self.run_cli("rollback"), 1)
        newer = Path(self.tmp.name) / "newer"
        newer.mkdir()
        self.assertEqual(self.run_cli("install", "helium", "--yes", "--no-auto-update",
                                      "--helium-archive", str(_fakes.make_helium_archive(newer, "0.0.0.2")), "--skip-verify"), 0, self.errors)
        self.assertEqual(self.run_cli("rollback"), 0, self.errors)
        self.assertEqual(cli._runtime(self.paths).current(), "0.0.0.1")


class KytyTests(CliTestCase):
    def launch_kyty(self, account=BETA, game_mode=False):
        with mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=game_mode), \
                mock.patch("nonsteamapps.display.screen_height", return_value=1080), \
                mock.patch("nonsteamapps.cli.os.chdir") as chdir, \
                mock.patch("nonsteamapps.cli.x11.watch") as watch, \
                mock.patch.dict(os.environ):
            argv, _ = self.launch("kytyps5", "--steam-account", str(account))
            environ = dict(os.environ)
        return argv, environ, chdir, watch

    def test_kytyps5_starts_in_each_accounts_folder_with_its_saves_and_no_terminal_window(self):
        self.install("kytyps5")
        self.assertIn("installing KytyPS5 2026-11-02 (dfec14a) without checking it against GitHub (--skip-verify)", self.errors)
        build = self.paths.kyty / "current"
        argv, environ, chdir, watch = self.launch_kyty()
        home = self.paths.profile("kytyps5", BETA)
        self.assertEqual(argv, [str(home / "kyty_launcher")])
        chdir.assert_called_once_with(home)
        self.assertTrue(os.path.samefile(home / "kyty_emulator", build / "kyty_emulator"))
        self.assertFalse(os.path.lexists(home / "kyty_updater"))
        self.assertEqual(environ["TERMINAL"], str(self.paths.program / "share" / "kytyps5" / "terminal"))
        self.assertTrue(os.access(environ["TERMINAL"], os.X_OK))
        settings = (home / "Kyty.ini").read_text()
        for line in ("check_updates_on_startup=false", "theme=1", "grid_view=true", "grid_icon_width=256"):
            self.assertIn(line + "\n", settings)
        self.assertEqual(json.loads((home / "nonsteamapps.json").read_text()), {"changes": ["2.23.0"]})
        self.assertNotIn("RESOURCE_NAME", environ)
        watch.assert_not_called()
        argv, environ, _, watch = self.launch_kyty(game_mode=True)
        watch.assert_called_once_with("nonsteamapps-kytyps5", os.getpid())
        self.assertEqual([environ[name] for name in ("RESOURCE_NAME", "SDL_APP_ID", "QT_QPA_PLATFORM", "QT_SCALE_FACTOR")],
                         ["nonsteamapps-kytyps5", "nonsteamapps-kytyps5", "xcb", "1.5"])
        games = self.home / "Games" / "PS5"
        self.assertIn(f"game_dirs={games}\n", (home / "Kyty.ini").read_text())
        self.assertTrue(games.is_dir())
        card = self.home / "SD card" / "PS5"
        card.mkdir(parents=True)
        apps.IniSettings("Kyty.ini", (("Launcher", "game_dirs", f"{card}, /home/deck/PS5"),)).apply(home)
        self.launch_kyty(account=ALPHA)
        alpha = self.paths.profile("kytyps5", ALPHA)
        self.assertIn(f"game_dirs={card}, /home/deck/PS5\n", (alpha / "Kyty.ini").read_text())
        self.assertNotIn(str(games), (alpha / "Kyty.ini").read_text())
        self.assertIn("check_updates_on_startup=false", (alpha / "Kyty.ini").read_text())
        self.assertEqual((alpha / "_DownloadData").resolve(), (home / "_DownloadData").resolve())
        self.assertEqual((alpha / "_DownloadData").resolve(), self.paths.profiles / "kytyps5" / "games" / "_DownloadData")
        (home / "Kyty.ini").write_text("[MainDialog]\ncheck_updates_on_startup=true\n[GameConfigurations]\nsize=1\n")
        self.install("kytyps5")
        self.assertEqual((home / "Kyty.ini").read_text(), "[MainDialog]\ncheck_updates_on_startup=false\ntheme=1\n[GameConfigurations]\nsize=1\n"
                                                          "\n[Launcher]\ngrid_view=true\ngrid_icon_width=256\n")

    def test_kytyps5_gets_a_games_folder_while_none_it_lists_exists(self):
        self.install("kytyps5")
        home = self.paths.profile("kytyps5", BETA)
        home.mkdir(parents=True)
        old = self.home / "Old PS5"
        old.mkdir()
        (home / "Kyty.ini").write_text(f"[Launcher]\ngame_dir={old}\n")
        self.launch_kyty()
        self.assertEqual((home / "Kyty.ini").read_text().count("game_dir"), 1)
        self.assertFalse((self.home / "Games").exists())
        games = self.home / "Games" / "PS5"
        old.rmdir()
        self.launch_kyty()
        self.assertIn(f"game_dirs={old}, {games}\n", (home / "Kyty.ini").read_text())
        self.assertTrue(games.is_dir())
        (home / "Kyty.ini").write_text('[Launcher]\ngame_dirs="/run/media/deck/SD, card/PS5"\n')
        self.launch_kyty()
        self.assertIn(f'game_dirs="/run/media/deck/SD, card/PS5", {games}\n', (home / "Kyty.ini").read_text())
        self.launch_kyty()
        self.assertEqual((home / "Kyty.ini").read_text().count(str(games)), 1)

    def test_an_existing_kytyps5_folder_turns_dark_once_and_keeps_a_theme_chosen_later(self):
        self.install("kytyps5")
        home = self.paths.profile("kytyps5", BETA)
        home.mkdir(parents=True)
        (home / "Kyty.ini").write_text("[MainDialog]\ntheme=0\n[Launcher]\ngrid_view=false\n")
        self.launch_kyty()
        settings = (home / "Kyty.ini").read_text()
        self.assertIn("theme=1\n", settings)
        self.assertIn("grid_view=true\n", settings)
        (home / "Kyty.ini").write_text(settings.replace("theme=1", "theme=2"))
        self.launch_kyty()
        self.assertIn("theme=2\n", (home / "Kyty.ini").read_text())

    def test_kytyps5_updates_only_when_asked_and_rolls_back(self):
        self.install("kytyps5")
        newer = "KytyPS5-2026-11-05-5555555"
        archive = _fakes.make_kyty_archive(Path(self.tmp.name) / "newer", newer)
        releases = json.dumps([_fakes.kyty_release(archive, newer, "2026-11-05T08:00:00Z")])
        with mock.patch("nonsteamapps.kyty.net.fetch_text", return_value=releases), \
                mock.patch("nonsteamapps.kyty.net.download", side_effect=lambda url, target: shutil.copyfile(archive, target)):
            self.assertEqual(self.run_cli("update", "--apps-only"), 0, self.errors)
            self.assertEqual(cli._kyty(self.paths).current(), _fakes.KYTY_TAG)
            self.assertEqual(self.run_cli("update"), 0, self.errors)
        self.assertIn("Updated KytyPS5 to 2026-11-05 (5555555)", self.errors)
        self.assertEqual(cli._kyty(self.paths).current(), newer)
        self.assertEqual(self.run_cli("rollback", "kytyps5"), 0, self.errors)
        self.assertEqual(cli._kyty(self.paths).current(), _fakes.KYTY_TAG)
        self.assertEqual(self.run_cli("doctor"), 0)
        self.assertIn("KytyPS5    2026-11-02 (dfec14a) (also 2026-11-05 (5555555))", self.output)

    def test_removing_kytyps5_removes_its_builds_and_keeps_the_saves_unless_purged(self):
        self.install("kytyps5")
        self.launch_kyty()
        saves = self.paths.profile("kytyps5", BETA) / "_SaveData"
        saves.mkdir()
        self.assertEqual(self.run_cli("remove", "kytyps5", "--yes"), 0, self.errors)
        self.assertFalse(self.paths.kyty.exists())
        self.assertTrue(saves.is_dir())
        self.assertEqual(sorted(path.name for path in saves.parent.iterdir()), ["Kyty.ini", "_DownloadData", "_PipelineCache", "_SaveData", "nonsteamapps.json"])
        self.assertTrue((saves.parent / "_DownloadData").is_symlink())
        self.assertTrue((self.paths.profiles / "kytyps5" / "games" / "_DownloadData").is_dir())
        self.install("kytyps5")
        self.assertEqual(self.run_cli("remove", "kytyps5", "--purge", "--yes"), 0, self.errors)
        self.assertFalse((self.paths.profiles / "kytyps5").exists())

    def test_without_its_download_the_other_apps_are_installed_and_kytyps5_alone_fails(self):
        with mock.patch("nonsteamapps.kyty.net.fetch_text", side_effect=OSError("offline")):
            self.assertEqual(self.run_cli("install", "localsend", "kytyps5", "--yes", "--no-auto-update"), 0, self.errors)
            self.assertIn("KytyPS5 was not installed, so it is left out", self.errors)
            self.assertEqual(config.Record.load(self.paths.record).managed(), ["localsend"])
            self.assertNotEqual(self.run_cli("install", "kytyps5", "--yes", "--no-auto-update"), 0)
        self.assertIn("could not read KytyPS5's releases from GitHub: offline", self.errors)


class UpdateTests(CliTestCase):
    def test_update_keeps_the_apps_and_what_the_user_changed_and_renews_nonsteamapps_artwork(self):
        self.install("youtube", "localsend")
        hero, settings = self.customise()
        before = settings.read_text()
        (self.paths.artwork("localsend") / "capsule.png").write_bytes(b"newer capsule")
        self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
        self.assertEqual([call[-1] for call in self.fake.calls("install")], ["rocks.shy.VacuumTube", "org.localsend.localsend_app"])
        self.assertEqual(config.Record.load(self.paths.record).managed(), ["youtube", "localsend"])
        entries = self.entries(ALPHA)
        self.assertEqual(sorted(entries), ["LocalSend", "My Tube"])
        self.assertEqual(entries["My Tube"].get("LaunchOptions"), f"--steam-account {ALPHA} --debug-gpu")
        self.assertEqual(hero.read_bytes(), b"chosen in Steam")
        self.assertEqual(settings.read_text(), before)
        for account in (ALPHA, BETA):
            appid = steam.to_unsigned32(self.entries(account)["LocalSend"].get("appid"))
            self.assertEqual((steam.config_dir(self.root, account) / "grid" / f"{appid}p.png").read_bytes(), b"newer capsule")
        self.assertNotIn("Put back", self.errors)
        self.assertIn("The Steam library is up to date", self.errors)

    def test_update_closes_steam_only_when_a_shortcut_must_change(self):
        self.install("localsend")
        with mock.patch("nonsteamapps.steamclient.stop", return_value=False) as stop:
            self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
            stop.assert_not_called()
            path = steam.config_dir(self.root, BETA) / "shortcuts.vdf"
            shortcuts = steam.ShortcutsFile.load(path)
            shortcuts.find(str(self.paths.app_link("localsend")))[0].set("StartDir", '"/somewhere/else"')
            shortcuts.save()
            self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
            stop.assert_called_once()
        self.assertEqual(self.entries(BETA)["LocalSend"].get("StartDir"), f'"{self.paths.program}"')
        self.assertIn(f'Steam account P{BETA} ({BETA}): updated "LocalSend"', self.errors)
        self.assertNotIn(f"P{ALPHA}", self.errors)

    def test_update_adds_no_shortcut_to_an_account_without_one(self):
        self.install("localsend", "--steam-user", str(ALPHA))
        self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
        self.assertFalse((steam.config_dir(self.root, BETA) / "shortcuts.vdf").exists())

    def test_a_steam_that_cannot_be_closed_leaves_the_library_as_it_was(self):
        self.install("localsend")
        path = steam.config_dir(self.root, ALPHA) / "shortcuts.vdf"
        shortcuts = steam.ShortcutsFile.load(path)
        shortcuts.find(str(self.paths.app_link("localsend")))[0].set("StartDir", '"/somewhere/else"')
        shortcuts.save()
        with mock.patch("nonsteamapps.steamclient.running", return_value=True), \
                mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=True):
            self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
        self.assertIn("left the Steam library as it was: Steam is running in Game Mode", self.errors)
        self.assertEqual(self.entries(ALPHA)["LocalSend"].get("StartDir"), '"/somewhere/else"')

    def test_apps_only_leaves_nonsteamapps_and_the_steam_library_alone(self):
        self.install("youtube")
        with mock.patch("nonsteamapps.cli.steam_add") as add:
            self.assertEqual(self.run_cli("update", "--quiet", "--apps-only"), 0, self.errors)
        add.assert_not_called()
        cli._update_program.assert_not_called()
        self.assertEqual(self.fake.calls("update"), [["update", "--user", "--noninteractive", "-y", "rocks.shy.VacuumTube"]])


class SelfUpdateTests(CliTestCase):
    self_update = True

    def make_source(self, script):
        source = Path(self.tmp.name) / "source"
        source.mkdir()
        (source / "install.sh").write_text(script)
        selfupdate.remember(self.paths, {selfupdate.SOURCE_VARIABLE: str(source)})
        return source

    def test_update_copies_nonsteamapps_from_its_source_and_hands_over_to_the_new_version(self):
        self.install("localsend")
        marker = Path(self.tmp.name) / "copied"
        self.make_source(f'#!/bin/bash\necho "$NONSTEAMAPPS_COPY_ONLY $NONSTEAMAPPS_HOME" > "{marker}"\n')
        with mock.patch("nonsteamapps.cli.os.execv", side_effect=fake_exec), mock.patch.dict(os.environ):
            with self.assertRaises(Exec) as raised:
                self.run_cli("update", "--yes", "--no-restart-steam")
            handed_over = os.environ.get(selfupdate.UPDATED_FROM_VARIABLE)
        self.assertEqual(raised.exception.args[0], [str(self.paths.launcher), "update", "--yes", "--no-restart-steam"])
        self.assertEqual(handed_over, __version__)
        self.assertEqual(marker.read_text(), f"1 {self.paths.program}\n")
        self.assertEqual(self.fake.calls("update"), [])

    def test_the_new_version_says_what_it_replaced_and_updates_the_apps(self):
        self.install("localsend")
        with mock.patch.dict(os.environ, {selfupdate.UPDATED_FROM_VARIABLE: "2.0.0"}):
            self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
            self.assertNotIn(selfupdate.UPDATED_FROM_VARIABLE, os.environ)
        self.assertIn(f"Updated NonSteamApps from 2.0.0 to {__version__}", self.errors)
        self.assertIn("The Steam library is up to date", self.errors)

    def test_when_nonsteamapps_cannot_be_copied_the_apps_are_still_updated(self):
        self.install("localsend")
        self.make_source("#!/bin/bash\necho 'error: run the installer as your normal user' >&2\nexit 1\n")
        self.assertEqual(self.run_cli("update", "--yes"), 0, self.errors)
        self.assertIn("could not update NonSteamApps (error: run the installer as your normal user)", self.errors)
        self.assertIn("The Steam library is up to date", self.errors)



class SignInTests(CliTestCase):
    def sign_in(self, app_id, authorize, callback):
        runtime = Path(self.tmp.name) / "run"
        runtime.mkdir(exist_ok=True)
        variables = {
            "XDG_CURRENT_DESKTOP": "gamescope",
            "XDG_RUNTIME_DIR": str(runtime),
            "FAKE_FLATPAK_OPEN": authorize,
            "FAKE_FLATPAK_DONE": str(Path(self.tmp.name) / "signed-in"),
            "FAKE_HELIUM_OPEN": callback,
            "FAKE_HELIUM_LOG": str(Path(self.tmp.name) / "helium.log"),
        }
        with mock.patch.dict(os.environ, variables), mock.patch("nonsteamapps.cli._redirect"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            status = cli.main(["launch", app_id, "--steam-account", str(ALPHA)], self.paths, self.flatpak)
        return status, output.getvalue(), runtime

    def test_in_game_mode_element_signs_in_in_helium_and_the_callback_returns_to_it(self):
        self.install("element", "helium")
        authorize = "https://account.example.org/authorize?redirect_uri=io.element.desktop%3A%2Fvector%2Fwebapp%2F&state=s"
        callback = "io.element.desktop:/vector/webapp/?no_universal_links=true#code=c&state=s"
        status, output, runtime = self.sign_in("element", authorize, callback)
        self.assertEqual(status, 0, output)
        app, relay = self.fake.calls("run")
        scripts = self.paths.program / "share" / "sandbox"
        for option in (f"--filesystem={scripts}:ro", f"--env=PATH={scripts}:/app/bin:/usr/bin", "--env=NONSTEAMAPPS_SCHEMES=io.element.desktop element",
                       f"--profile=steam-{ALPHA}"):
            self.assertIn(option, app)
        self.assertEqual(relay, [*app, callback])
        profile = self.paths.profile("element", ALPHA)
        [helium] = [json.loads(line) for line in (Path(self.tmp.name) / "helium.log").read_text().splitlines()]
        self.assertEqual((helium[0], helium[-1]), (f"--user-data-dir={profile}", authorize))
        self.assertIn("--ozone-platform=x11", helium)
        preferences = json.loads((profile / "Default" / "Preferences").read_text())
        self.assertTrue(preferences["protocol_handler"]["allowed_origin_protocol_pairs"]["https://account.example.org"]["io.element.desktop"])
        self.assertIn("opening the sign-in page at account.example.org in Helium", output)
        self.assertIn("handing the sign-in back to Element Desktop", output)
        self.assertNotIn("code=c", output)
        self.assertEqual(list((runtime / "app" / "im.riot.Riot" / "nonsteamapps").iterdir()), [])
        self.assertEqual(self.run_cli("remove", "element", "--purge", "--yes"), 0, self.errors)
        self.assertFalse(profile.exists())

    def test_a_bitwarden_sso_callback_reaches_the_accounts_own_bitwarden(self):
        self.install("bitwarden", "helium")
        sso = "https://vault.bitwarden.com/#/sso?clientId=desktop&redirectUri=bitwarden%3A%2F%2Fsso-callback&state=s"
        status, output, _ = self.sign_in("bitwarden", sso, "bitwarden://sso-callback?code=c&state=s")
        self.assertEqual(status, 0, output)
        app, relay = self.fake.calls("run")
        folder = self.home / f".var/app/com.bitwarden.desktop/config/Bitwarden-steam-{ALPHA}"
        self.assertIn(f"--env=BITWARDEN_APPDATA_DIR={folder}", relay)
        self.assertEqual(relay, [*app, "bitwarden://sso-callback?code=c&state=s"])
        self.assertIn("opening the sign-in page at vault.bitwarden.com in Helium", output)

    def test_outside_game_mode_or_without_helium_element_starts_as_before(self):
        self.install("element")
        argv, _ = self.launch("element", "--steam-account", str(ALPHA))
        self.assertFalse(any("NONSTEAMAPPS" in argument for argument in argv))
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "gamescope"}):
            argv, _ = self.launch("element", "--steam-account", str(ALPHA))
        self.assertFalse(any("NONSTEAMAPPS" in argument for argument in argv))


if __name__ == "__main__":
    unittest.main()
