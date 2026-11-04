import json
import os
import re
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from nonsteamapps import apps

HOME = Path("/home/deck")


class RegistryTests(unittest.TestCase):
    def test_ids_and_lookup(self):
        self.assertEqual(
            apps.ids(),
            ["youtube", "element", "signal", "bitwarden", "jellyfin", "localsend", "prism", "eden", "kytyps5", "protonup", "protontricks", "files",
             "helium", "primevideo", "hbomax", "netflix", "disneyplus", "protondb", "protoncalendar"],
        )
        self.assertEqual(apps.by_id(" YouTube ").flatpak, "rocks.shy.VacuumTube")
        self.assertEqual(apps.by_id("DisneyPlus").name, "Disney+")
        with self.assertRaises(KeyError):
            apps.by_id("kodi")

    def test_every_app_ships_its_artwork(self):
        artwork = Path(_paths.ROOT) / "assets" / "artwork"
        for app in apps.APPS:
            names = sorted(path.name for path in (artwork / app.id).iterdir())
            self.assertEqual(names, ["capsule.png", "hero.jpg", "icon.png", "logo.png", "wide.png"], app.id)


class ArgumentTests(unittest.TestCase):
    def test_youtube_points_vacuumtube_at_a_folder_per_account(self):
        youtube = apps.by_id("youtube")
        self.assertEqual(
            youtube.arguments(HOME, 111),
            ["--fullscreen", "--portable=/home/deck/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-111"],
        )
        self.assertEqual(youtube.arguments(HOME, None), ["--fullscreen"])

    def test_element_keeps_secrets_the_same_way_in_game_and_desktop_mode(self):
        self.assertEqual(
            apps.by_id("element").arguments(HOME, 222),
            ["--password-store=basic", "--storage-mode=allow-plaintext", "--profile=steam-222"],
        )

    def test_localsend_has_no_sign_in_so_every_account_shares_its_settings(self):
        localsend = apps.by_id("localsend")
        self.assertIsNone(localsend.profile)
        self.assertEqual(localsend.arguments(HOME, 111), [])

    def test_helium_apps_run_in_helium_with_the_web_browser_layout(self):
        for app_id, url, kiosk in (("helium", "", False), ("primevideo", "https://www.primevideo.com/", True),
                                   ("hbomax", "https://www.hbomax.com/", True), ("netflix", "https://www.netflix.com/", True),
                                   ("disneyplus", "https://www.disneyplus.com/", True),
                                   ("protondb", "https://www.protondb.com/", True),
                                   ("protoncalendar", "https://calendar.proton.me/", True)):
            app = apps.by_id(app_id)
            self.assertEqual((app.flatpak, app.client, app.browser.url, app.browser.kiosk), ("", "Helium", url, kiosk))
            self.assertEqual(app.controller, "Browser (NonSteamApps)")
        self.assertEqual([app.id for app in apps.APPS if app.controller == apps.WEB_BROWSER], ["element", "signal"])
        self.assertEqual(apps.by_id("protondb").browser.start_url(111), "https://www.protondb.com/dashboard/76561197960265839")
        self.assertEqual(apps.by_id("protondb").browser.start_url(None), "https://www.protondb.com/")
        self.assertEqual(apps.by_id("netflix").browser.start_url(111), "https://www.netflix.com/")
        self.assertEqual(apps.by_id("localsend").controller, "LocalSend (NonSteamApps)")
        self.assertEqual(apps.by_id("youtube").controller, "YouTube (NonSteamApps)")
        self.assertEqual([app.id for app in apps.APPS if not app.controller], ["jellyfin"])

    def test_flathub_apps_scale_for_a_tv_and_vacuumtube_can_keep_its_sandbox(self):
        self.assertEqual(
            [app.id for app in apps.APPS if app.tv_scale],
            ["youtube", "element", "signal", "bitwarden", "jellyfin", "localsend", "prism", "eden", "kytyps5", "protonup", "protontricks", "files"],
        )
        youtube = apps.by_id("youtube").tv_scale
        self.assertEqual((youtube.layout, apps.by_id("element").tv_scale.layout), (1080, 720))
        self.assertEqual(youtube.apply(2.0), (["--force-device-scale-factor=2"], []))
        self.assertEqual(youtube.requires.values, (("unlock_resolution", True),))
        self.assertEqual(
            {app.id: app.sandbox_off_when for app in apps.APPS if app.sandbox_off_when},
            {"youtube": ("SteamGamepadUI",)},
        )

    def test_signal_starts_its_own_script_with_the_accounts_folder_and_plain_key_store(self):
        signal = apps.by_id("signal")
        self.assertEqual(
            signal.arguments(HOME, 111),
            [
                "XDG_CONFIG_HOME=/home/deck/.var/app/org.signal.Signal/config/Signal-steam-111",
                "SIGNAL_PASSWORD_STORE=basic",
                "signal-desktop",
            ],
        )
        self.assertEqual(signal.run_options(HOME, 111), ["--command=env"])
        self.assertEqual((signal.arguments(HOME, None), signal.run_options(HOME, None)), ([], []))
        self.assertEqual(apps.by_id("element").run_options(HOME, 111), [])

    def test_each_toolkit_takes_the_tv_scale_its_own_way(self):
        self.assertEqual(apps.by_id("element").tv_scale.apply(1.5), (["--force-device-scale-factor=1.5"], []))
        self.assertEqual(apps.by_id("jellyfin").tv_scale.apply(3.0), (["--scale-factor=3"], []))
        localsend = apps.by_id("localsend").tv_scale
        self.assertEqual([localsend.apply(factor) for factor in (1.5, 2.0, 2.75, 3.0)],
                         [([], []), ([], ["--env=GDK_SCALE=2"]), ([], ["--env=GDK_SCALE=2"]), ([], ["--env=GDK_SCALE=3"])])
        protontricks = apps.by_id("protontricks").tv_scale
        self.assertEqual([protontricks.apply(factor) for factor in (1.5, 2.0, 2.5, 3.0)], [
            ([], ["--env=GDK_DPI_SCALE=1.5"]),
            ([], ["--env=GDK_SCALE=2"]),
            ([], ["--env=GDK_SCALE=2", "--env=GDK_DPI_SCALE=1.25"]),
            ([], ["--env=GDK_SCALE=3"]),
        ])
        self.assertEqual(apps.by_id("protonup").tv_scale.apply(1.5), ([], ["--env=QT_SCALE_FACTOR=1.5"]))

    def test_the_proton_tools_run_in_their_own_sandbox_with_a_tv_set_up_and_the_steam_libraries(self):
        protonup, protontricks = apps.by_id("protonup"), apps.by_id("protontricks")
        self.assertEqual((protonup.flatpak, protontricks.flatpak), ("net.davidotek.pupgui2", "com.github.Matoking.protontricks"))
        self.assertEqual((protonup.args, protontricks.args), ((), ("--no-term", "--gui")))
        self.assertEqual(protonup.env, (("PUPGUI2_DISABLE_GAMEPAD", "1"),))
        self.assertEqual((protonup.game_mode_env, protontricks.game_mode_env), ((("QT_QPA_PLATFORM", "xcb"),), (("GDK_BACKEND", "x11"),)))
        self.assertTrue(protonup.libraries and protontricks.libraries)
        self.assertEqual({protonup.controller, protontricks.controller}, {"Tools (NonSteamApps)"})
        self.assertEqual([app.id for app in apps.APPS if app.libraries], ["protonup", "protontricks"])

    def test_bitwarden_gets_each_accounts_folder_in_a_variable_and_keeps_its_tokens_on_disk(self):
        bitwarden = apps.by_id("bitwarden")
        self.assertEqual(bitwarden.arguments(HOME, 111), [])
        self.assertEqual(bitwarden.run_options(HOME, 111),
                         ["--env=BITWARDEN_APPDATA_DIR=/home/deck/.var/app/com.bitwarden.desktop/config/Bitwarden-steam-111"])
        self.assertEqual(bitwarden.run_options(HOME, None), [])
        self.assertEqual((bitwarden.env, bitwarden.controller), ((("ACCESS_TOKEN_LOCATION", "DISK"),), "Bitwarden (NonSteamApps)"))
        self.assertEqual((bitwarden.game_mode_env, bitwarden.fullscreen_class, bitwarden.hide_menu_bar), ((("DISPLAY_MODE", "X11"),), "bitwarden", True))
        self.assertEqual([app.id for app in apps.APPS if app.hide_menu_bar], ["bitwarden"])
        self.assertEqual([app.id for app in apps.APPS if app.fullscreen_class], ["bitwarden", "kytyps5"])
        self.assertEqual(bitwarden.tv_scale.apply(1.5), (["--force-device-scale-factor=1.5"], []))

    def test_kytyps5_is_downloaded_from_its_releases_with_its_own_updater_off(self):
        app = apps.by_id("kytyps5")
        self.assertEqual((app.flatpak, app.browser, app.system), ("", None, None))
        tv = (("MainDialog", "theme", "1"), ("Launcher", "grid_view", "true"), ("Launcher", "grid_icon_width", "256"))
        self.assertEqual(app.release.settings, (apps.IniSettings("Kyty.ini", (("MainDialog", "check_updates_on_startup", "false"), *tv)),))
        self.assertEqual(app.release.changes, (("2.23.0", apps.IniSettings("Kyty.ini", tv)),))
        self.assertEqual((app.controller, app.fullscreen_class), ("Emulator (NonSteamApps)", "nonsteamapps-kytyps5"))
        self.assertEqual(app.tv_scale.variables(1.5), {"QT_SCALE_FACTOR": "1.5"})
        self.assertEqual([candidate.id for candidate in apps.APPS if candidate.release], ["kytyps5"])

    def test_eden_starts_full_screen_from_each_accounts_folder(self):
        eden = apps.by_id("eden")
        folder = HOME / ".var/app/dev.eden_emu.eden/data/eden-steam-111"
        self.assertEqual((eden.arguments(HOME, 111), eden.run_options(HOME, 111)), (["-f"], [f"--cwd={folder}"]))
        self.assertEqual((eden.arguments(HOME, None), eden.run_options(HOME, None)), (["-f"], []))
        self.assertEqual((eden.controller, eden.qt_window, eden.game_mode_env), ("Emulator (NonSteamApps)", True, ()))
        self.assertEqual([(app.id, app.env) for app in apps.APPS if app.x11], [("eden", (("QT_QPA_PLATFORM", "xcb"),))])
        self.assertEqual(eden.tv_scale.apply(1.5), ([], ["--env=QT_SCALE_FACTOR=1.5"]))
        self.assertEqual([app.id for app in apps.APPS if isinstance(app.profile, apps.PortableProfile)], ["eden"])

    def test_the_steamos_theme_changes_colours_only_and_wins_over_youtubes(self):
        self.assertEqual([(app.id, app.userstyles) for app in apps.APPS if app.userstyles], [("youtube", ("nonsteamapps-steamos.css",))])
        css = (Path(_paths.ROOT) / "src/share/userstyles/nonsteamapps-steamos.css").read_text()
        body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual(body.count("{"), body.count("}"))
        rules = [rule.split("{") for rule in body.split("}") if rule.strip()]
        self.assertTrue(all(len(rule) == 2 and rule[0].strip() for rule in rules))
        declarations = [part.strip() for _, block in rules for part in block.split(";") if part.strip()]
        properties = {declaration.split(":", 1)[0].strip() for declaration in declarations}
        self.assertLessEqual({name for name in properties if not name.startswith("--")},
                             {"background", "background-color", "background-image", "border-color", "color", "fill", "filter"})
        selectors = " ".join(selector for selector, _ in rules)
        self.assertEqual(re.findall(r"\.(?!zylon-focus|vt-|WEB_PAGE_TYPE_)[A-Za-z][\w-]*", selectors), [])
        self.assertTrue(all(declaration.endswith("!important") for declaration in declarations if not declaration.startswith("--nonsteamapps-")))

    def test_jellyfin_starts_in_its_tv_layout_with_a_named_profile(self):
        self.assertEqual(apps.by_id("jellyfin").arguments(HOME, 333), ["--tv", "--fullscreen", "--profile=steam-333"])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_profiles_are_created_and_found_by_pattern(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        self.assertEqual(youtube.profile.existing(app_home), [])
        self.assertTrue(youtube.profile.prepare(app_home, 111, lambda options: 0))
        youtube.profile.prepare(app_home, 222, lambda options: 0)
        (app_home / "config" / "VacuumTube").mkdir()
        (app_home / "config" / "VacuumTube-steam-x").mkdir()
        self.assertEqual(
            [path.name for path in youtube.profile.existing(app_home)],
            ["VacuumTube-steam-111", "VacuumTube-steam-222"],
        )

    def test_new_vacuumtube_folders_start_set_up_for_a_tv(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        settings = app_home / "config/VacuumTube-steam-111/config.json"
        self.assertEqual(
            json.loads(settings.read_text()),
            {
                "sponsorblock": True,
                "sponsorblock_skip_sponsor": True,
                "sponsorblock_skip_selfpromo": True,
                "sponsorblock_skip_interaction": True,
                "sponsorblock_skip_intro": True,
                "sponsorblock_skip_outro": True,
                "sponsorblock_skip_preview": True,
                "sponsorblock_skip_hook": True,
                "dearrow": True,
                "dislikes": True,
                "block_continue_watching": True,
                "hide_shorts": True,
                "features_enabled": True,
                "remaining_time_feature": True,
                "wayland_hdr": True,
                "userstyles": True,
                "fullscreen": True,
                "no_window_decorations": True,
                "disabled_tabs": ["shorts", "podcasts"],
            },
        )
        settings.write_text('{"sponsorblock": false}')
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual(json.loads(settings.read_text()), {"sponsorblock": False})
        youtube.profile.prepare_shared(app_home)
        shared = json.loads((app_home / "config/VacuumTube/config.json").read_text())
        self.assertTrue(shared["dearrow"] and shared["no_window_decorations"])

    def test_existing_vacuumtube_folders_get_the_window_and_guide_settings_once(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        folder = app_home / "config/VacuumTube-steam-111"
        folder.mkdir(parents=True)
        settings = folder / "config.json"
        settings.write_text(json.dumps({"sponsorblock": False, "fullscreen": False, "no_window_decorations": False, "volume": 80}))
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual(
            json.loads(settings.read_text()),
            {"sponsorblock": False, "fullscreen": True, "no_window_decorations": True, "volume": 80, "disabled_tabs": ["shorts", "podcasts"],
             **{f"sponsorblock_skip_{category}": True for category in ("selfpromo", "interaction", "intro", "outro", "preview", "hook")},
             "userstyles": True},
        )
        self.assertEqual(json.loads((folder / "nonsteamapps.json").read_text()), {"changes": ["2.11.0", "2.21.0", "2.22.0"]})
        settings.write_text(json.dumps({"fullscreen": False, "disabled_tabs": [], "sponsorblock_skip_outro": False}))
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual(json.loads(settings.read_text()), {"fullscreen": False, "disabled_tabs": [], "sponsorblock_skip_outro": False})

    def test_folders_set_up_before_2_21_0_skip_the_new_segments_once_and_keep_the_rest(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        folder = app_home / "config/VacuumTube-steam-111"
        folder.mkdir(parents=True)
        (folder / "nonsteamapps.json").write_text(json.dumps({"changes": ["2.11.0"]}))
        settings = folder / "config.json"
        settings.write_text(json.dumps({"sponsorblock": False, "sponsorblock_skip_sponsor": False, "sponsorblock_skip_filler": True}))
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        data = json.loads(settings.read_text())
        self.assertEqual(
            [data[key] for key in ("sponsorblock", "sponsorblock_skip_sponsor", "sponsorblock_skip_filler", "sponsorblock_skip_outro", "sponsorblock_skip_selfpromo")],
            [False, False, True, True, True],
        )
        self.assertNotIn("fullscreen", data)
        self.assertEqual(json.loads((folder / "nonsteamapps.json").read_text()), {"changes": ["2.11.0", "2.21.0", "2.22.0"]})

    def test_a_damaged_vacuumtube_config_is_left_for_vacuumtube_and_changed_later(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        folder = app_home / "config/VacuumTube-steam-111"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text("{")
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual((folder / "config.json").read_text(), "{")
        self.assertFalse((folder / "nonsteamapps.json").exists())
        (folder / "config.json").write_text("{}")
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        self.assertTrue(json.loads((folder / "config.json").read_text())["fullscreen"])

    def test_each_prism_folder_starts_set_up_for_a_tv_and_shares_minecrafts_downloads(self):
        prism = apps.by_id("prism")
        app_home = prism.home(self.home)
        self.assertEqual(prism.arguments(self.home, 111), [f"--dir={app_home}/data/PrismLauncher-steam-111"])
        prism.profile.prepare(app_home, 111, lambda options: 0)
        folder = app_home / "data/PrismLauncher-steam-111"
        settings = (folder / "prismlauncher.cfg").read_text()
        for line in ("[General]", "ApplicationTheme=dark", "IconTheme=flat_white", "CloseAfterLaunch=true", "QuitAfterGameStop=true"):
            self.assertIn(line + "\n", settings)
        for name in ("assets", "libraries", "java"):
            self.assertEqual(os.readlink(folder / name), f"../PrismLauncher/{name}")
            self.assertTrue((app_home / "data/PrismLauncher" / name).is_dir())
        self.assertFalse((folder / "instances").exists())
        (folder / "prismlauncher.cfg").write_text("[General]\nApplicationTheme=bright\n")
        prism.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual((folder / "prismlauncher.cfg").read_text(), "[General]\nApplicationTheme=bright\n")
        self.assertEqual([path.name for path in prism.profile.existing(app_home)], ["PrismLauncher-steam-111"])

    def test_new_element_folders_quit_when_the_window_closes(self):
        element = apps.by_id("element")
        app_home = element.home(self.home)
        element.profile.prepare(app_home, 111, lambda options: 0)
        settings = app_home / "config/Element-steam-111/electron-config.json"
        self.assertEqual(json.loads(settings.read_text()), {"minimizeToTray": False})
        settings.write_text('{"minimizeToTray": true}')
        element.profile.prepare(app_home, 111, lambda options: 0)
        self.assertTrue(json.loads(settings.read_text())["minimizeToTray"])
        element.profile.prepare_shared(app_home)
        self.assertFalse((app_home / "config/Element").exists())

    def test_new_signal_folders_skip_the_flatpaks_first_start_question(self):
        signal = apps.by_id("signal")
        app_home = signal.home(self.home)
        signal.profile.prepare(app_home, 111, lambda options: 0)
        settings = app_home / "config/Signal-steam-111/Signal/config.json"
        self.assertEqual(json.loads(settings.read_text()), {})
        settings.write_text('{"key": "secret"}')
        signal.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual(json.loads(settings.read_text()), {"key": "secret"})
        signal.profile.prepare_shared(app_home)
        self.assertFalse((app_home / "config/Signal").exists())
        self.assertEqual([path.name for path in signal.profile.existing(app_home)], ["Signal-steam-111"])

    def test_an_install_puts_each_accounts_tv_settings_back_and_the_shared_ones_only_when_used(self):
        youtube = apps.by_id("youtube")
        app_home = youtube.home(self.home)
        youtube.profile.prepare(app_home, 111, lambda options: 0)
        youtube.profile.prepare_shared(app_home)
        folder, shared = app_home / "config/VacuumTube-steam-111", app_home / "config/VacuumTube"
        for path in (folder, shared):
            (path / "config.json").write_text(json.dumps({"sponsorblock": False, "disabled_tabs": [], "volume": 80}))
        (folder / "nonsteamapps.json").unlink()
        self.assertEqual(youtube.profile.reset(app_home), [folder])
        data = json.loads((folder / "config.json").read_text())
        self.assertEqual((data["sponsorblock"], data["disabled_tabs"], data["fullscreen"], data["volume"]), (True, ["shorts", "podcasts"], True, 80))
        self.assertEqual(json.loads((folder / "nonsteamapps.json").read_text()), {"changes": ["2.11.0", "2.21.0", "2.22.0"]})
        self.assertFalse(json.loads((shared / "config.json").read_text())["sponsorblock"])
        self.assertEqual(youtube.profile.reset(app_home, shared=True), [shared])
        self.assertEqual(youtube.profile.reset(app_home, shared=True), [])
        self.assertEqual(apps.by_id("signal").profile.reset(apps.by_id("signal").home(self.home)), [])
        self.assertEqual(apps.by_id("jellyfin").profile.reset(apps.by_id("jellyfin").home(self.home)), [])

    def test_an_install_puts_prisms_tv_settings_back_and_keeps_its_other_settings(self):
        prism = apps.by_id("prism")
        app_home = prism.home(self.home)
        prism.profile.prepare(app_home, 111, lambda options: 0)
        settings = app_home / "data/PrismLauncher-steam-111/prismlauncher.cfg"
        settings.write_text("[General]\nApplicationTheme=bright\nJavaPath=/usr/bin/java\nLanguage=en_AU\n")
        self.assertEqual(len(prism.profile.reset(app_home)), 1)
        self.assertEqual(settings.read_text(), (
            "[General]\nApplicationTheme=dark\nJavaPath=/usr/bin/java\nLanguage=en_AU\n"
            "IconTheme=flat_white\nCloseAfterLaunch=true\nQuitAfterGameStop=true\nLaunchMaximized=true\n"
        ))

    def test_each_eden_account_keeps_its_saves_and_shares_games_keys_and_firmware(self):
        eden = apps.by_id("eden")
        app_home = eden.home(self.home)
        self.assertTrue(eden.profile.prepare(app_home, 111, lambda options: 0))
        user = app_home / "data/eden-steam-111/user"
        settings = user / "config/qt-config.ini"
        pad = "engine:sdl,port:0,guid:03000000de280000ff11000001000000"
        for line in ("[UI]", "fullscreen\\default=false", "fullscreen=true", "confirmStop=2", "gui_hide_backend_warning=true",
                     "theme=colorful_dark", "UIGameList\\game_list_mode=1", "UIGameList\\game_icon_size=256", "[Controls]",
                     "player_0_button_a\\default=false", f'player_0_button_a="{pad},button:1"', f'player_0_button_zr="{pad},axis:5,threshold:0.5,invert:+"',
                     f'player_0_button_dup="{pad},hat:0,direction:up"',
                     f'player_0_rstick="{pad},axis_x:3,axis_y:4,offset_x:0.000000,offset_y:0.000000,invert_x:+,invert_y:+"'):
            self.assertIn(line + "\n", settings.read_text())
        shared = {"keys": "../../eden/keys", "load": "../../eden/load", "shader": "../../eden/shader",
                  "nand/system/Contents/registered": "../../../../../eden/nand/system/Contents/registered",
                  "nand/user/Contents/registered": "../../../../../eden/nand/user/Contents/registered"}
        for name, target in shared.items():
            self.assertEqual(os.readlink(user / name), target)
            self.assertEqual((user / name).resolve(), (app_home / "data/eden" / name).resolve())
        for name in ("nand/user/save", "nand/system/save", "sdmc"):
            self.assertFalse((user / name).exists())
        settings.write_text("[UI]\ntheme=default\n")
        eden.profile.prepare(app_home, 111, lambda options: 0)
        self.assertEqual(settings.read_text(), "[UI]\ntheme=default\n")
        self.assertEqual([path.name for path in eden.profile.existing(app_home)], ["eden-steam-111"])

    def test_a_new_eden_account_starts_with_the_game_folders_last_saved(self):
        eden = apps.by_id("eden")
        app_home = eden.home(self.home)
        shared = app_home / "config/eden/qt-config.ini"
        eden.profile.prepare_shared(app_home)
        self.assertIn("theme=colorful_dark\n", shared.read_text())
        shared.write_text("[UI]\ntheme=default\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=/home/deck/Switch\n"
                          "Paths\\gamedirs\\2\\deep_scan\\default=false\nPaths\\gamedirs\\2\\deep_scan=true\nPaths\\gamedirs\\size=2\n")
        os.utime(shared, (1, 1))
        eden.profile.prepare(app_home, 111, lambda options: 0)
        first = app_home / "data/eden-steam-111/user/config/qt-config.ini"
        for line in ("theme=colorful_dark", "Paths\\gamedirs\\2\\path=/home/deck/Switch", "Paths\\gamedirs\\2\\deep_scan=true", "Paths\\gamedirs\\size=2"):
            self.assertIn(line + "\n", first.read_text())
        first.write_text(first.read_text().replace(
            "Paths\\gamedirs\\size=2", "Paths\\gamedirs\\3\\path=/run/media/deck/SD/Switch\nPaths\\gamedirs\\size=3\n"
                                       "Paths\\external_content_dirs\\1\\path=/run/media/deck/SD/Updates\nPaths\\external_content_dirs\\size=1"))
        eden.profile.prepare(app_home, 222, lambda options: 0)
        second = app_home / "data/eden-steam-222/user/config/qt-config.ini"
        for line in ("Paths\\gamedirs\\3\\path=/run/media/deck/SD/Switch", "Paths\\gamedirs\\size=3",
                     "Paths\\external_content_dirs\\1\\path=/run/media/deck/SD/Updates", "Paths\\external_content_dirs\\size=1"):
            self.assertIn(line + "\n", second.read_text())
        self.assertNotIn("theme=default", second.read_text())
        before = second.read_text()
        first.write_text("[UI]\nPaths\\gamedirs\\size=0\n")
        eden.profile.prepare(app_home, 222, lambda options: 0)
        self.assertEqual(second.read_text(), before)

    def test_an_install_puts_edens_tv_settings_back_and_keeps_the_controls_chosen(self):
        eden = apps.by_id("eden")
        app_home = eden.home(self.home)
        eden.profile.prepare(app_home, 111, lambda options: 0)
        settings = app_home / "data/eden-steam-111/user/config/qt-config.ini"
        settings.write_text('[UI]\nfullscreen\\default=true\nfullscreen=false\ntheme=default\n\n[Controls]\nplayer_0_button_a="engine:keyboard,code:67"\n')
        self.assertEqual(eden.profile.reset(app_home), [settings.parents[2]])
        for line in ("fullscreen\\default=false", "fullscreen=true", "theme=colorful_dark", 'player_0_button_a="engine:keyboard,code:67"'):
            self.assertIn(line + "\n", settings.read_text())
        self.assertNotIn("player_0_button_b", settings.read_text())
        self.assertEqual(eden.profile.reset(app_home), [])
        self.assertEqual(eden.profile.reset(app_home, shared=True), [])
        self.assertFalse((app_home / "config/eden").exists())
        eden.profile.prepare_shared(app_home)
        shared = app_home / "config/eden/qt-config.ini"
        self.assertIn('player_0_button_a="engine:sdl,port:0,guid:03000000de280000ff11000001000000,button:1"\n', shared.read_text())
        shared.write_text("[UI]\ntheme=default\n")
        eden.profile.prepare_shared(app_home)
        self.assertEqual(shared.read_text(), "[UI]\ntheme=default\n")
        self.assertEqual(eden.profile.reset(app_home, shared=True), [app_home])
        self.assertIn("theme=colorful_dark\n", shared.read_text())
        self.assertNotIn("[Controls]", shared.read_text())

    def test_style_sheets_are_written_only_when_missing_or_changed(self):
        source, folder = self.home / "share", self.home / "VacuumTube-steam-111"
        source.mkdir()
        (source / "theme.css").write_text("a { color: red; }")
        self.assertEqual(apps.place_userstyles(source, folder, ["theme.css"]), ["theme.css"])
        sheet = folder / "userstyles" / "theme.css"
        stamp = sheet.stat().st_mtime_ns
        self.assertEqual(apps.place_userstyles(source, folder, ["theme.css"]), [])
        self.assertEqual(sheet.stat().st_mtime_ns, stamp)
        sheet.write_text("a { color: blue; }")
        self.assertEqual(apps.place_userstyles(source, folder, ["theme.css"]), ["theme.css"])
        self.assertEqual(sheet.read_text(), "a { color: red; }")
        with self.assertRaises(OSError):
            apps.place_userstyles(source, folder, ["missing.css"])

    def test_edens_game_list_gets_the_games_folder_while_no_folder_added_to_it_exists(self):
        settings, games = self.home / "qt-config.ini", self.home / "Games" / "Switch"
        settings.write_text("[UI]\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=UserNAND\nPaths\\gamedirs\\3\\path=SysNAND\n"
                            "Paths\\gamedirs\\size=3\n")
        self.assertTrue(apps.add_game_folder(settings, games))
        for line in (f"Paths\\gamedirs\\4\\path={games}", "Paths\\gamedirs\\4\\deep_scan=true", "Paths\\gamedirs\\size=4"):
            self.assertIn(line + "\n", settings.read_text())
        self.assertNotIn("size=3", settings.read_text())
        self.assertFalse(apps.add_game_folder(settings, games))
        own = self.home / "My Switch games"
        own.mkdir()
        settings.write_text(f"[UI]\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=\"{own}\"\nPaths\\gamedirs\\size=2\n")
        self.assertFalse(apps.add_game_folder(settings, games))
        own.rmdir()
        self.assertTrue(apps.add_game_folder(settings, games))
        self.assertIn(f"Paths\\gamedirs\\3\\path={games}\n", settings.read_text())
        self.assertIn("Paths\\gamedirs\\size=3\n", settings.read_text())
        fresh = self.home / "fresh" / "qt-config.ini"
        self.assertTrue(apps.add_game_folder(fresh, games))
        self.assertEqual(fresh.read_text(), "[UI]\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=UserNAND\nPaths\\gamedirs\\3\\path=SysNAND\n"
                                            f"Paths\\gamedirs\\4\\path={games}\nPaths\\gamedirs\\4\\deep_scan=true\nPaths\\gamedirs\\size=4\n")

    def test_localsend_settings_go_where_localsend_reads_them_and_keep_the_rest(self):
        localsend = apps.by_id("localsend")
        home = localsend.home(self.home)
        [settings] = localsend.settings
        current = home / "data/org.localsend.localsend_app/shared_preferences.json"
        self.assertEqual(settings.target(home), current)
        self.assertTrue(settings.apply(home))
        self.assertEqual(json.loads(current.read_text()), {"flutter.ls_whats_new": "1.18.2", "flutter.ls_theme": "dark", "flutter.ls_color": "oled"})
        current.unlink()
        current.parent.rmdir()
        legacy = home / "data/localsend_app/shared_preferences.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"flutter.ls_version": 3, "flutter.ls_theme": "light", "flutter.ls_alias": "Deck"}))
        self.assertEqual(settings.target(home), legacy)
        self.assertTrue(settings.apply(home))
        self.assertEqual(json.loads(legacy.read_text()),
                         {"flutter.ls_version": 3, "flutter.ls_theme": "dark", "flutter.ls_alias": "Deck", "flutter.ls_color": "oled"})
        self.assertFalse(current.parent.exists())

    def test_each_bitwarden_folder_starts_dark_and_quitting_when_closed(self):
        bitwarden = apps.by_id("bitwarden")
        app_home = bitwarden.home(self.home)
        bitwarden.profile.prepare(app_home, 111, lambda options: 0)
        data = app_home / "config/Bitwarden-steam-111/data.json"
        self.assertEqual(json.loads(data.read_text()), {
            "global_desktopSettings_runInBackground": False, "global_desktopSettings_openAtLogin": False, "global_theming_selection": "dark",
        })
        data.write_text(json.dumps({"stateVersion": 86, "global_desktopSettings_runInBackground": True, "global_theming_selection": "light",
                                    "user_x": {"key": 1}}))
        self.assertEqual(bitwarden.profile.reset(app_home), [data.parent])
        self.assertEqual(json.loads(data.read_text()), {
            "stateVersion": 86, "global_desktopSettings_runInBackground": False, "global_theming_selection": "dark", "user_x": {"key": 1},
            "global_desktopSettings_openAtLogin": False,
        })

    def make_jellyfin_profile(self, app_home, name, folder):
        directory = app_home / "data/jellyfin-desktop/profiles" / folder
        directory.mkdir(parents=True)
        (directory / "profile.json").write_text(json.dumps({"name": name}))
        return directory

    def test_jellyfin_profile_is_created_once_through_the_app(self):
        jellyfin = apps.by_id("jellyfin")
        app_home = jellyfin.home(self.home)
        calls = []

        def run_app(options):
            calls.append(list(options))
            self.make_jellyfin_profile(app_home, options[1], "a1")
            return 0

        self.assertTrue(jellyfin.profile.prepare(app_home, 111, run_app))
        self.assertTrue(jellyfin.profile.prepare(app_home, 111, run_app))
        self.assertEqual(calls, [["--create-profile", "steam-111"]])

    def test_jellyfin_reports_failure_when_the_profile_does_not_appear(self):
        jellyfin = apps.by_id("jellyfin")
        self.assertFalse(jellyfin.profile.prepare(jellyfin.home(self.home), 111, lambda options: 1))

    def test_jellyfin_existing_lists_only_steam_profiles_and_their_caches(self):
        jellyfin = apps.by_id("jellyfin")
        app_home = jellyfin.home(self.home)
        ours = self.make_jellyfin_profile(app_home, "steam-111", "b2")
        self.make_jellyfin_profile(app_home, "Default", "c3")
        (app_home / "data/jellyfin-desktop/profiles/broken").mkdir()
        cache = app_home / "cache/jellyfin-desktop/profiles/b2"
        cache.mkdir(parents=True)
        self.assertEqual(jellyfin.profile.existing(app_home), [ours, cache])



class IniSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_values_go_into_their_groups_and_everything_else_stays(self):
        settings = apps.IniSettings("app.ini", (("General", "Theme", "dark"), ("Window", "Bar", "off"), ("General", "Scale", "2")))
        path = self.folder / "app.ini"
        path.write_text("; comment\n[General]\nTheme = light\nOther=x=y\n\n[Other]\nTheme=red\n")
        self.assertTrue(settings.apply(self.folder))
        self.assertEqual(path.read_text(), "; comment\n[General]\nTheme=dark\nOther=x=y\nScale=2\n\n[Other]\nTheme=red\n\n[Window]\nBar=off\n")
        self.assertFalse(settings.apply(self.folder))

    def test_a_new_file_holds_only_the_values_and_an_unreadable_one_is_left_alone(self):
        settings = apps.IniSettings("sub/app.ini", (("General", "Theme", "dark"),))
        self.assertTrue(settings.apply(self.folder))
        self.assertEqual((self.folder / "sub/app.ini").read_text(), "[General]\nTheme=dark\n")
        (self.folder / "sub/app.ini").write_bytes(b"\xff\xfe[General]")
        self.assertIsNone(settings.apply(self.folder))
        self.assertEqual((self.folder / "sub/app.ini").read_bytes(), b"\xff\xfe[General]")


class SystemAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "profile"
        self.desktop = Path(self.tmp.name) / ".config"
        self.desktop.mkdir()
        (self.desktop / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Downloads"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_files_profile_starts_set_up_for_a_tv_and_keeps_later_changes(self):
        files = apps.by_id("files").system
        files.prepare(self.profile, self.desktop)
        config = self.profile / "config"
        self.assertEqual((config / "dolphinrc").read_text(), (
            "[General]\nRememberOpenedTabs=false\nConfirmClosingMultipleTabs=false\nBrowseThroughArchives=true\n\n"
            "[MainWindow]\nMenuBar=Disabled\n\n[IconsMode]\nPreviewSize=96\n\n[PlacesPanel]\nIconSize=32\n"
        ))
        self.assertEqual((config / "kdeglobals").read_text(), "[KDE]\nSingleClick=true\n")
        self.assertEqual((config / "user-dirs.dirs").resolve(), (self.desktop / "user-dirs.dirs").resolve())
        self.assertFalse((config / "user-dirs.locale").exists())
        self.assertTrue((self.profile / "state").is_dir())
        (config / "dolphinrc").write_text("[General]\nRememberOpenedTabs=true\n")
        files.prepare(self.profile, self.desktop)
        self.assertEqual((config / "dolphinrc").read_text(), "[General]\nRememberOpenedTabs=true\n")

    def test_an_install_puts_the_files_tv_settings_back_once_the_profile_exists(self):
        files = apps.by_id("files").system
        self.assertFalse(files.reset(self.profile))
        self.assertFalse(self.profile.exists())
        files.prepare(self.profile, self.desktop)
        config = self.profile / "config"
        (config / "dolphinrc").write_text("# mine\n[General]\nRememberOpenedTabs=true\nShowFullPath=true\n\n[MainWindow]\nMenuBar=Enabled\n")
        (config / "kdeglobals").unlink()
        self.assertTrue(files.reset(self.profile))
        self.assertEqual((config / "dolphinrc").read_text(), (
            "# mine\n[General]\nRememberOpenedTabs=false\nShowFullPath=true\nConfirmClosingMultipleTabs=false\nBrowseThroughArchives=true\n\n"
            "[MainWindow]\nMenuBar=Disabled\n\n[IconsMode]\nPreviewSize=96\n\n[PlacesPanel]\nIconSize=32\n"
        ))
        self.assertEqual((config / "kdeglobals").read_text(), "[KDE]\nSingleClick=true\n")
        self.assertFalse(files.reset(self.profile))

    def test_the_profile_is_layered_over_the_desktops_settings(self):
        files = apps.by_id("files").system
        desktop_mode = files.environment(self.profile, self.desktop, {"XDG_CONFIG_DIRS": "/etc/xdg:/usr/share/kf6"}, game_mode=False)
        self.assertEqual(desktop_mode, {
            "XDG_CONFIG_HOME": str(self.profile / "config"),
            "XDG_CONFIG_DIRS": f"{self.desktop}:/etc/xdg:/usr/share/kf6",
            "XDG_STATE_HOME": str(self.profile / "state"),
        })
        game_mode = files.environment(self.profile, self.desktop, {}, game_mode=True)
        self.assertEqual(game_mode["XDG_CONFIG_DIRS"], f"{self.desktop}:/etc/xdg")
        self.assertEqual((game_mode["QT_QPA_PLATFORM"], game_mode["QT_QPA_PLATFORMTHEME"]), ("xcb", "kde"))

    def test_a_scale_variable_suits_apps_started_without_flatpak(self):
        self.assertEqual(apps.by_id("files").tv_scale.variables(1.5), {"QT_SCALE_FACTOR": "1.5"})
        self.assertEqual(apps.by_id("localsend").tv_scale.variables(1.5), {})
        self.assertEqual(apps.by_id("localsend").tv_scale.variables(3.0), {"GDK_SCALE": "3"})
        self.assertEqual(apps.by_id("element").tv_scale.variables(2.0), {})


if __name__ == "__main__":
    unittest.main()
