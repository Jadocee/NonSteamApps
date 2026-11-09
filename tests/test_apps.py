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
            ["youtube", "element", "signal", "discord", "bitwarden", "jellyfin", "vlc", "localsend", "prism", "eden", "edennx2", "lichii",
             "kytyps5", "protonup", "protontricks", "winetricks", "bottles", "files", "helium", "primevideo", "hbomax", "netflix", "disneyplus",
             "protondb", "steamdb", "nexusmods", "protonmail", "protoncalendar"],
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
            ["--password-store=basic", "--storage-mode=allow-plaintext", "--enable-spatial-navigation", "--profile=steam-222"],
        )

    def test_element_and_signal_move_with_the_arrow_keys_fill_the_tv_and_have_layouts_of_their_own(self):
        element, signal = apps.by_id("element"), apps.by_id("signal")
        self.assertEqual([app.id for app in apps.APPS if "--enable-spatial-navigation" in app.args], ["element", "signal", "discord", "bitwarden"])
        self.assertEqual((element.controller, signal.controller), ("Element (NonSteamApps)", "Signal (NonSteamApps)"))
        self.assertEqual((element.fullscreen_class, signal.fullscreen_class), ("element", "signal"))
        self.assertEqual((element.hide_menu_bar, signal.hide_menu_bar), (True, True))
        self.assertEqual(element.profile.changes, (("2.34.0", apps.JsonSettings("electron-config.json", (("warnBeforeExit", False), ("autoHideMenuBar", True)))),))

    def test_localsend_has_no_sign_in_so_every_account_shares_its_settings(self):
        localsend = apps.by_id("localsend")
        self.assertIsNone(localsend.profile)
        self.assertEqual(localsend.arguments(HOME, 111), [])

    def test_helium_apps_run_in_helium_with_the_web_browser_layout(self):
        for app_id, url, kiosk in (("helium", "", False), ("primevideo", "https://www.primevideo.com/", True),
                                   ("hbomax", "https://www.hbomax.com/", True), ("netflix", "https://www.netflix.com/", True),
                                   ("disneyplus", "https://www.disneyplus.com/", True),
                                   ("protondb", "https://www.protondb.com/", True),
                                   ("steamdb", "https://steamdb.info/", True),
                                   ("nexusmods", "https://www.nexusmods.com/", True),
                                   ("protonmail", "https://mail.proton.me/", True),
                                   ("protoncalendar", "https://calendar.proton.me/", True)):
            app = apps.by_id(app_id)
            self.assertEqual((app.flatpak, app.client, app.browser.url, app.browser.kiosk), ("", "Helium", url, kiosk))
            self.assertEqual(app.controller, "Browser (NonSteamApps)")
        self.assertEqual([app.id for app in apps.APPS if app.controller == "Web Browser"], [])
        self.assertEqual(apps.by_id("protondb").browser.start_url(111), "https://www.protondb.com/dashboard/76561197960265839?nonsteamapps=library")
        self.assertEqual([app.id for app in apps.APPS if app.browser and app.browser.extensions], ["protondb", "steamdb"])
        self.assertEqual([(app.id, app.desktop) for app in apps.APPS if app.desktop],
                         [("helium", apps.DesktopEntry("Web Browser", ("Network", "WebBrowser"), "helium.desktop", "product_logo_256.png"))])
        self.assertEqual(apps.by_id("protondb").browser.start_url(None), "https://www.protondb.com/")
        self.assertEqual(apps.by_id("netflix").browser.start_url(111), "https://www.netflix.com/")
        self.assertEqual(apps.by_id("localsend").controller, "LocalSend (NonSteamApps)")
        self.assertEqual(apps.by_id("youtube").controller, "YouTube (NonSteamApps)")
        self.assertEqual(apps.by_id("jellyfin").controller, "Jellyfin (NonSteamApps)")
        self.assertEqual([app.id for app in apps.APPS if not app.controller], [])

    def test_flathub_apps_scale_for_a_tv_and_vacuumtube_can_keep_its_sandbox(self):
        self.assertEqual(
            [app.id for app in apps.APPS if app.tv_scale],
            ["youtube", "element", "signal", "discord", "bitwarden", "jellyfin", "vlc", "localsend", "prism", "eden", "edennx2", "lichii",
             "kytyps5", "protonup", "protontricks", "winetricks", "bottles", "files"],
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
                "--enable-spatial-navigation",
            ],
        )
        self.assertEqual(signal.run_options(HOME, 111), ["--command=env"])
        self.assertEqual((signal.arguments(HOME, None), signal.run_options(HOME, None)), (["--enable-spatial-navigation"], []))
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

    def test_winetricks_runs_in_flathubs_wine_on_its_stable_branch_with_protontricks_tv_set_up(self):
        winetricks, protontricks = apps.by_id("winetricks"), apps.by_id("protontricks")
        self.assertEqual((winetricks.flatpak, winetricks.ref, winetricks.icon), ("org.winehq.Wine", "org.winehq.Wine//stable", "winetricks"))
        self.assertEqual(winetricks.run_options(HOME, 111), ["--command=winetricks"])
        self.assertEqual(winetricks.arguments(HOME, 111), [])
        self.assertEqual((winetricks.tv_scale, winetricks.game_mode_env, winetricks.controller),
                         (protontricks.tv_scale, protontricks.game_mode_env, protontricks.controller))
        self.assertFalse(winetricks.libraries or winetricks.profile)
        self.assertEqual((protontricks.ref, protontricks.run_options(HOME, 111)), ("com.github.Matoking.protontricks", []))
        self.assertEqual([app.id for app in apps.APPS if app.branch or app.command], ["winetricks"])

    def test_protons_apps_share_one_helium_profile_for_each_account_for_its_single_sign_on(self):
        mail, calendar = apps.by_id("protonmail"), apps.by_id("protoncalendar")
        self.assertEqual((mail.browser.profile, calendar.browser.profile, mail.profiles_name, calendar.profiles_name), ("proton",) * 4)
        self.assertEqual((apps.sharing_profiles(mail), apps.sharing_profiles(calendar)), ((calendar,), (mail,)))
        self.assertEqual([app.id for app in apps.APPS if app.profiles_name != app.id], ["protonmail", "protoncalendar"])
        self.assertEqual((apps.sharing_profiles(apps.by_id("protondb")), apps.by_id("netflix").profiles_name), ((), "netflix"))

    def test_discord_starts_its_own_script_with_the_accounts_folder_and_quits_when_its_window_closes(self):
        discord = apps.by_id("discord")
        folder = "/home/deck/.var/app/com.discordapp.Discord/config/Discord-steam-111"
        self.assertEqual(discord.arguments(HOME, 111),
                         [f"XDG_CONFIG_HOME={folder}", "com.discordapp.Discord", "--password-store=basic", "--enable-spatial-navigation"])
        self.assertEqual((discord.run_options(HOME, 111), discord.run_options(HOME, None)), (["--command=env"], []))
        self.assertEqual(discord.arguments(HOME, None), ["--password-store=basic", "--enable-spatial-navigation"])
        self.assertEqual((discord.controller, discord.fullscreen_class, discord.hide_menu_bar), ("Discord (NonSteamApps)", "discord", False))
        self.assertEqual(discord.tv_scale.apply(1.5), (["--force-device-scale-factor=1.5"], []))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertTrue(discord.profile.prepare(home, 111, lambda args: 0))
            settings = home / "config/Discord-steam-111/discord/settings.json"
            self.assertEqual(json.loads(settings.read_text()), {"MINIMIZE_TO_TRAY": False})
            settings.write_text(json.dumps({"MINIMIZE_TO_TRAY": True, "SKIP_HOST_UPDATE": True}))
            discord.profile.prepare_shared(home)
            self.assertEqual(json.loads((home / "config/discord/settings.json").read_text()), {"MINIMIZE_TO_TRAY": False})
            self.assertEqual(discord.profile.reset(home), [home / "config/Discord-steam-111"])
            self.assertEqual(json.loads(settings.read_text()), {"MINIMIZE_TO_TRAY": False, "SKIP_HOST_UPDATE": True})

    def test_vlc_keeps_each_accounts_history_apart_and_starts_set_up_for_a_tv(self):
        vlc = apps.by_id("vlc")
        tv = ["--fullscreen", "--no-qt-video-autoresize", "--qt-continue=2", "--qt-dark-palette", "--no-qt-privacy-ask"]
        self.assertEqual(vlc.arguments(HOME, 222), ["XDG_CONFIG_HOME=/home/deck/.var/app/org.videolan.VLC/config/VLC-steam-222", "vlc", *tv])
        self.assertEqual((vlc.arguments(HOME, None), vlc.run_options(HOME, 222), vlc.run_options(HOME, None)), (tv, ["--command=env"], []))
        self.assertEqual((vlc.controller, vlc.fullscreen_class, vlc.qt_window), ("VLC (NonSteamApps)", "vlc", False))
        self.assertEqual(vlc.tv_scale.apply(1.5), ([], ["--env=QT_SCALE_FACTOR=1.5"]))

    def test_bottles_shares_its_bottles_and_starts_dark_in_game_mode_on_x11(self):
        bottles = apps.by_id("bottles")
        self.assertEqual((bottles.flatpak, bottles.profile, bottles.args, bottles.settings), ("com.usebottles.bottles", None, (), ()))
        self.assertEqual(bottles.game_mode_env, (("GDK_BACKEND", "x11"), ("ADW_DEBUG_COLOR_SCHEME", "prefer-dark")))
        self.assertEqual((bottles.controller, bottles.fullscreen_class), ("Bottles (NonSteamApps)", "bottles"))
        self.assertEqual([bottles.tv_scale.apply(factor) for factor in (1.5, 2.0, 3.0)],
                         [([], []), ([], ["--env=GDK_SCALE=2"]), ([], ["--env=GDK_SCALE=3"])])

    def test_bitwarden_gets_each_accounts_folder_in_a_variable_and_keeps_its_tokens_on_disk(self):
        bitwarden = apps.by_id("bitwarden")
        self.assertEqual(bitwarden.arguments(HOME, 111), ["--enable-spatial-navigation"])
        self.assertEqual(bitwarden.arguments(HOME, None), ["--enable-spatial-navigation"])
        self.assertEqual(bitwarden.run_options(HOME, 111),
                         ["--env=BITWARDEN_APPDATA_DIR=/home/deck/.var/app/com.bitwarden.desktop/config/Bitwarden-steam-111"])
        self.assertEqual(bitwarden.run_options(HOME, None), [])
        self.assertEqual((bitwarden.env, bitwarden.controller), ((("ACCESS_TOKEN_LOCATION", "DISK"),), "Bitwarden (NonSteamApps)"))
        self.assertEqual((bitwarden.game_mode_env, bitwarden.fullscreen_class, bitwarden.hide_menu_bar), ((("DISPLAY_MODE", "X11"),), "bitwarden", True))
        self.assertEqual([app.id for app in apps.APPS if app.hide_menu_bar], ["element", "signal", "bitwarden"])
        self.assertEqual([app.id for app in apps.APPS if app.fullscreen_class],
                         ["element", "signal", "discord", "bitwarden", "vlc", "kytyps5", "bottles"])
        self.assertEqual(bitwarden.tv_scale.apply(1.5), (["--force-device-scale-factor=1.5"], []))

    def test_kytyps5_is_downloaded_from_its_releases_with_its_own_updater_off(self):
        app = apps.by_id("kytyps5")
        self.assertEqual((app.flatpak, app.browser, app.system), ("", None, None))
        tv = (("MainDialog", "theme", "1"), ("Launcher", "grid_view", "true"), ("Launcher", "grid_icon_width", "256"))
        self.assertEqual(app.release.settings, (apps.IniSettings("Kyty.ini", (("MainDialog", "check_updates_on_startup", "false"), *tv)),))
        self.assertEqual(app.release.changes, (("2.23.0", apps.IniSettings("Kyty.ini", tv)), ("2.25.0", apps.KYTY_GAMES)))
        self.assertEqual(app.game_mode_env, (("QT_QPA_PLATFORM", "xcb"), ("SDL_VIDEO_DRIVER", "x11")))
        self.assertEqual((app.controller, app.fullscreen_class), ("Emulator (NonSteamApps)", "nonsteamapps-kytyps5"))
        self.assertEqual(app.tv_scale.variables(1.5), {"QT_SCALE_FACTOR": "1.5"})
        self.assertEqual([candidate.id for candidate in apps.APPS if candidate.release], ["kytyps5"])

    def test_eden_starts_full_screen_from_each_accounts_folder(self):
        eden = apps.by_id("eden")
        folder = HOME / ".var/app/dev.eden_emu.eden/data/eden-steam-111"
        self.assertEqual((eden.arguments(HOME, 111), eden.run_options(HOME, 111)), (["-f"], [f"--cwd={folder}"]))
        self.assertEqual((eden.arguments(HOME, None), eden.run_options(HOME, None)), (["-f"], []))
        self.assertEqual((eden.controller, eden.qt_window, eden.game_mode_env), ("Emulator (NonSteamApps)", True, ()))
        self.assertEqual([(app.id, app.env) for app in apps.APPS if app.x11], [(name, (("QT_QPA_PLATFORM", "xcb"),)) for name in ("eden", "edennx2")])
        self.assertEqual(eden.tv_scale.apply(1.5), ([], ["--env=QT_SCALE_FACTOR=1.5"]))
        self.assertEqual([app.id for app in apps.APPS if isinstance(app.profile, apps.PortableProfile)], ["eden", "edennx2", "lichii"])

    def test_eden_nx2_is_eden_built_here_with_a_games_folder_of_its_own(self):
        eden, nx2 = apps.by_id("eden"), apps.by_id("edennx2")
        self.assertEqual((nx2.flatpak, nx2.from_source, nx2.release), ("io.github.jadocee.nonsteamapps.EdenNX2", True, None))
        self.assertEqual([app.id for app in apps.APPS if app.from_source], ["edennx2"])
        folder = HOME / ".var/app/io.github.jadocee.nonsteamapps.EdenNX2/data/eden-steam-111"
        self.assertEqual((nx2.arguments(HOME, 111), nx2.run_options(HOME, 111)), (["-f"], [f"--cwd={folder}"]))
        self.assertIs(nx2.profile, eden.profile)
        self.assertEqual((nx2.games, eden.games), (("Games/Switch2",), ("Games/Switch",)))
        same = ("controller", "tv_scale", "env", "x11", "qt_window", "console_mode", "logo_position", "args")
        self.assertEqual([getattr(nx2, name) for name in same], [getattr(eden, name) for name in same])
        self.assertEqual([(app.id, app.keys_from) for app in apps.APPS if app.keys_from], [("edennx2", "eden"), ("lichii", "eden")])

    def test_lichii_is_an_appimage_that_keeps_edens_layout_in_nonsteamapps_profiles(self):
        app, eden = apps.by_id("lichii"), apps.by_id("eden")
        self.assertEqual((app.flatpak, app.release, app.from_source, app.appimage), ("", None, False, True))
        self.assertEqual([candidate.id for candidate in apps.APPS if candidate.appimage], ["lichii"])
        home = HOME / ".local/share/nonsteamapps/profiles/lichii"
        profile = app.profile
        self.assertEqual(profile.path(home, 111), home / "111")
        self.assertEqual(profile.settings_file(home, 111), home / "111/user/config/qt-config.ini")
        self.assertEqual(profile.settings_file(home, None), home / "shared/user/config/qt-config.ini")
        self.assertEqual(profile.shared_path(home, apps.EDEN_KEYS), home / "shared/user/keys")
        self.assertEqual(profile.shared_links, eden.profile.shared_links)
        self.assertIn(("UI", "check_for_updates", "false"), profile.settings[0].values)
        self.assertEqual(profile.settings[0].new, apps.EDEN_CONTROLS)
        self.assertEqual((app.games, app.keys_from, app.firmware_from, app.console_mode, app.env),
                         (("Games/Switch", "Games/Switch2"), "eden", "eden", True, (("QT_QPA_PLATFORM", "xcb"),)))
        self.assertEqual(profile.shared_path(home, apps.EDEN_FIRMWARE), home / "shared/user/nand/system/Contents/registered")
        self.assertIn(("user/nand/system/Contents/registered", apps.EDEN_FIRMWARE), profile.shared_links)
        self.assertEqual([candidate.id for candidate in apps.APPS if candidate.firmware_from], ["lichii"])
        same = ("controller", "tv_scale", "qt_window", "logo_position", "args")
        self.assertEqual([getattr(app, name) for name in same], [getattr(eden, name) for name in same])

    def test_both_emulators_run_on_vulkan_and_eden_nx2_keeps_astc_textures_small(self):
        vulkan = (("Renderer", "backend\\default", "true"), ("Renderer", "backend", "1"),
                  ("Renderer", "vulkan_device\\default", "true"), ("Renderer", "vulkan_device", "0"))
        astc = (("Renderer", "accelerate_astc\\default", "true"), ("Renderer", "accelerate_astc", "1"),
                ("Renderer", "astc_recompression\\default", "false"), ("Renderer", "astc_recompression", "2"))
        bc3 = (("Renderer", "accelerate_astc\\default", "true"), ("Renderer", "accelerate_astc", "1"),
               ("Renderer", "astc_recompression\\default", "true"), ("Renderer", "astc_recompression", "2"))
        self.assertEqual([(app.id, app.graphics) for app in apps.APPS if app.graphics],
                         [("eden", vulkan), ("edennx2", vulkan + astc), ("lichii", vulkan + bc3)])

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
        self.assertEqual(json.loads(settings.read_text()), {"minimizeToTray": False, "warnBeforeExit": False, "autoHideMenuBar": True})
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

    def test_lichiis_game_list_keeps_the_switch_and_switch_2_folders_beside_any_other(self):
        settings = self.home / "qt-config.ini"
        switch, switch2 = self.home / "Games" / "Switch", self.home / "Games" / "Switch2"
        own = self.home / "SD card"
        own.mkdir()
        settings.write_text(f"[UI]\nPaths\\gamedirs\\1\\path=SDMC\nPaths\\gamedirs\\2\\path=\"{own}\"\nPaths\\gamedirs\\size=2\n")
        self.assertFalse(apps.add_game_folder(settings, switch2))
        self.assertTrue(apps.add_game_folder(settings, switch, always=True))
        self.assertTrue(apps.add_game_folder(settings, switch2, always=True))
        for line in (f"Paths\\gamedirs\\2\\path=\"{own}\"", f"Paths\\gamedirs\\3\\path={switch}", "Paths\\gamedirs\\3\\deep_scan=true",
                     f"Paths\\gamedirs\\4\\path={switch2}", "Paths\\gamedirs\\4\\deep_scan=true", "Paths\\gamedirs\\size=4"):
            self.assertIn(line + "\n", settings.read_text())
        self.assertFalse(apps.add_game_folder(settings, switch, always=True))
        self.assertFalse(apps.add_game_folder(settings, switch2, always=True))
        lichii = apps.by_id("lichii")
        self.assertEqual((lichii.games, lichii.games_listed), (("Games/Switch", "Games/Switch2"), True))
        self.assertEqual(lichii.games, (*apps.by_id("eden").games, *apps.by_id("edennx2").games))
        self.assertEqual([app.id for app in apps.APPS if app.games_listed], ["lichii"])
        self.assertTrue(lichii.summary.startswith("Switch and Switch 2 games you own"))

    def test_edens_graphics_go_into_its_renderer_settings_and_replace_a_fallback_it_saved(self):
        settings = self.home / "config" / "qt-config.ini"
        settings.parent.mkdir()
        settings.write_text("[Renderer]\nbackend\\default=false\nbackend=0\nresolution_setup=3\n\n[UI]\ntheme=default\n")
        self.assertTrue(apps.write_eden_settings(settings, apps.EDEN_GRAPHICS))
        self.assertEqual(settings.read_text(), "[Renderer]\nbackend\\default=true\nbackend=1\nresolution_setup=3\n"
                                               "vulkan_device\\default=true\nvulkan_device=0\n\n[UI]\ntheme=default\n")
        self.assertFalse(apps.write_eden_settings(settings, apps.EDEN_GRAPHICS))

    def test_keys_are_copied_where_missing_or_older_and_ones_installed_since_stay(self):
        source, target = self.home / "eden" / "keys", self.home / "nx2" / "keys"
        self.assertEqual(apps.copy_keys(source, target), [])
        source.mkdir(parents=True)
        (source / "prod.keys").write_text("header_key = 00\n")
        os.utime(source / "prod.keys", ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(apps.copy_keys(source, target), ["prod.keys"])
        self.assertEqual(((target / "prod.keys").read_text(), (target / "prod.keys").stat().st_mode & 0o777), ("header_key = 00\n", 0o600))
        self.assertEqual(apps.copy_keys(source, target), [])
        (source / "prod.keys").write_text("header_key = 11\n")
        (source / "title.keys").write_text("0100 = 22\n")
        for name, when in (("prod.keys", 3), ("title.keys", 3)):
            os.utime(source / name, ns=(when * 1_000_000_000, when * 1_000_000_000))
        self.assertEqual(apps.copy_keys(source, target), ["prod.keys", "title.keys"])
        self.assertEqual((target / "prod.keys").read_text(), "header_key = 11\n")
        (target / "title.keys").write_text("0100 = 33\n")
        os.utime(target / "title.keys", ns=(5_000_000_000, 5_000_000_000))
        os.utime(source / "title.keys", ns=(4_000_000_000, 4_000_000_000))
        self.assertEqual(apps.copy_keys(source, target), [])
        self.assertEqual((target / "title.keys").read_text(), "0100 = 33\n")

    def test_edens_firmware_reaches_lichii_whole_and_hard_linked_while_lichii_has_none_of_its_own(self):
        source, target = self.home / "eden" / "registered", self.home / "lichii" / "registered"
        record = target.parent / apps.FIRMWARE_RECORD
        self.assertEqual(apps.share_firmware(source, target), 0)
        source.mkdir(parents=True)
        (source / "aa.nca").write_bytes(b"first")
        (source / "bb.nca").mkdir()
        (source / "bb.nca" / "00").write_bytes(b"part one")
        (source / "bb.nca" / "01").write_bytes(b"part two")
        (source / "notes.txt").write_text("not firmware")
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("the user's")
        self.assertEqual(apps.share_firmware(source, target), 2)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["aa.nca", "bb.nca", "keep.txt"])
        self.assertEqual((target / "aa.nca").stat().st_ino, (source / "aa.nca").stat().st_ino)
        self.assertEqual(((target / "bb.nca" / "00").read_bytes(), (target / "bb.nca" / "01").read_bytes()), (b"part one", b"part two"))
        self.assertEqual(json.loads(record.read_text())["files"], {"aa.nca": 5, "bb.nca": 16})
        self.assertEqual(apps.share_firmware(source, target), 0)
        self.assertEqual(sorted(path.name for path in target.parent.iterdir()), [apps.FIRMWARE_RECORD, "registered"])
        (source / "aa.nca").unlink()
        (source / "cc.nca").write_bytes(b"newer firmware")
        self.assertEqual(apps.share_firmware(source, target), 2)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["bb.nca", "cc.nca", "keep.txt"])
        (target / "dd.nca").write_bytes(b"installed in Lichii")
        (source / "ee.nca").write_bytes(b"newest")
        self.assertEqual(apps.share_firmware(source, target), 0)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["bb.nca", "cc.nca", "dd.nca", "keep.txt"])

    def test_firmware_the_emulator_installed_ncas_singly_into_is_mirrored_too(self):
        source, target = self.home / "eden" / "registered", self.home / "lichii" / "registered"
        (source / "0000001F").mkdir(parents=True)
        (source / "0000001F" / "aa.nca").write_bytes(b"single")
        (source / "yuzu_meta").mkdir()
        (source / "yuzu_meta" / "SystemProgram_0100000000000809.cnmt").write_bytes(b"meta")
        (source / "placeholder").mkdir()
        self.assertEqual(apps.share_firmware(source, target), 2)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["0000001F", "yuzu_meta"])
        self.assertEqual((target / "0000001F" / "aa.nca").stat().st_ino, (source / "0000001F" / "aa.nca").stat().st_ino)
        self.assertEqual(json.loads((target.parent / apps.FIRMWARE_RECORD).read_text())["files"], {"0000001F": 6, "yuzu_meta": 4})

    def test_firmware_is_not_given_to_a_folder_that_holds_its_own_or_is_a_link(self):
        source, target = self.home / "eden" / "registered", self.home / "lichii" / "registered"
        source.mkdir(parents=True)
        (source / "aa.nca").write_bytes(b"first")
        target.mkdir(parents=True)
        (target / "zz.nca").write_bytes(b"installed in Lichii")
        self.assertEqual(apps.share_firmware(source, target), 0)
        self.assertEqual([path.name for path in target.iterdir()], ["zz.nca"])
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        linked = self.home / "linked" / "registered"
        linked.parent.mkdir()
        linked.symlink_to(elsewhere)
        self.assertEqual(apps.share_firmware(source, linked), 0)
        self.assertEqual(list(elsewhere.iterdir()), [])

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

    def test_kytyps5_gets_steams_gamepad_and_1080p_only_where_the_user_kept_its_defaults(self):
        path = self.folder / "Kyty.ini"
        mapping = ", ".join(f'"{entry}"' for entry in apps.KYTY_PAD)
        defaults = ("trophy_duration_seconds=6\nshader_optimization_type=Performance\nshader_log_folder=_Shaders\n"
                    "command_buffer_dump_folder=_Buffers\nprintf_output_file=_kyty.txt\n")
        self.assertEqual(len(apps.KYTY_PAD), 17)
        self.assertNotIn("Pad:GyroToggle=Back", apps.KYTY_PAD)
        path.write_text("[MainDialog]\ntheme=1\n")
        self.assertTrue(apps.KYTY_GAMES.apply(self.folder))
        self.assertEqual(path.read_text(), "[MainDialog]\ntheme=1\n\n[GlobalConfiguration]\npresent_mode=Mailbox\n"
                                           f"{defaults}host_input_mapping={mapping}\nscreen_resolution=1920x1080\n")
        path.write_text("[GlobalConfiguration]\npresent_mode=Fifo\nscreen_resolution=1280x720\nhost_input_mapping=@Invalid()\n")
        self.assertTrue(apps.KYTY_GAMES.apply(self.folder))
        self.assertEqual(path.read_text(), "[GlobalConfiguration]\npresent_mode=Fifo\nscreen_resolution=1920x1080\n"
                                           f"host_input_mapping={mapping}\n{defaults}")
        path.write_text("[GlobalConfiguration]\nhost_input_mapping=Cross=Space\nscreen_resolution=1280x720\n")
        self.assertTrue(apps.KYTY_GAMES.apply(self.folder))
        self.assertIn("host_input_mapping=Cross=Space\nscreen_resolution=1920x1080\n", path.read_text())
        own = "[GlobalConfiguration]\nhost_input_mapping=Cross=Space\nscreen_resolution=2560x1440\n"
        path.write_text(own)
        self.assertFalse(apps.KYTY_GAMES.apply(self.folder))
        self.assertEqual(path.read_text(), own)
        path.write_bytes(b"\xff\xfe")
        self.assertIsNone(apps.KYTY_GAMES.apply(self.folder))

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
