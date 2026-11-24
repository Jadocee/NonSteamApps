import json
import os
import tempfile
import unittest
from pathlib import Path

import _fakes
import _paths  # noqa: F401
from nonsteamapps import browser


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = Path(self.tmp.name) / "profile"
        self.preferences = self.profile / "Default" / "Preferences"

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        return json.loads(self.preferences.read_text())

    def test_steams_input_method_gives_way_to_gtks_simple_one_and_others_stay(self):
        for given, used, changed in (("Steam", "simple", True), ("steam", "simple", True), ("ibus", "ibus", False), (None, None, False)):
            environ = {} if given is None else {"GTK_IM_MODULE": given}
            self.assertEqual(browser.single_keystrokes(environ), changed, given)
            self.assertEqual(environ.get("GTK_IM_MODULE"), used, given)

    def test_new_full_screen_profiles_skip_onboarding_and_prompts(self):
        browser.write_preferences(self.profile, services=True, kiosk=True)
        data = self.read()
        self.assertTrue(data["helium"]["completed_onboarding"])
        self.assertTrue(data["helium"]["global_privacy_control"])
        self.assertEqual(data["helium"]["services"], {"enabled": True, "user_consented": True, "schema_version": 1})
        self.assertEqual(data["profile"]["exit_type"], "Normal")
        self.assertFalse(data["translate"]["enabled"])
        self.assertFalse(data["credentials_enable_service"])
        self.assertEqual(data["profile"]["default_content_setting_values"], {"notifications": 2, "geolocation": 2})

    def test_the_browser_keeps_its_password_manager_and_translation(self):
        browser.write_preferences(self.profile, services=True, kiosk=False)
        data = self.read()
        self.assertNotIn("translate", data)
        self.assertNotIn("credentials_enable_service", data)
        self.assertTrue(data["helium"]["global_privacy_control"])
        self.assertEqual(data["profile"]["default_content_setting_values"], {"notifications": 2})

    def test_later_starts_mark_a_clean_exit_and_keep_the_users_choices(self):
        browser.write_preferences(self.profile, services=True, kiosk=True)
        data = self.read()
        data["translate"]["enabled"] = True
        del data["helium"]["global_privacy_control"]
        data["profile"]["exit_type"] = "Crashed"
        data["helium"]["services"]["schema_version"] = 3
        self.preferences.write_text(json.dumps(data))
        browser.write_preferences(self.profile, services=False, kiosk=True)
        data = self.read()
        self.assertTrue(data["translate"]["enabled"])
        self.assertNotIn("global_privacy_control", data["helium"])
        self.assertEqual((data["profile"]["exit_type"], data["profile"]["exited_cleanly"]), ("Normal", True))
        self.assertFalse(data["helium"]["services"]["enabled"])
        self.assertEqual(data["helium"]["services"]["schema_version"], 3)

    def test_every_start_binds_ctrl_shift_q_to_exit_and_keeps_the_users_other_shortcuts(self):
        browser.write_preferences(self.profile, services=True, kiosk=True)
        self.assertEqual(self.read()["helium"]["browser"]["custom_accelerators"], {"34031": {"added": ["Control+Shift+KeyQ"]}})
        data = self.read()
        data["helium"]["browser"]["custom_accelerators"] = {
            "34031": {"added": ["F9"], "removed": ["Control+Shift+KeyQ", 7]},
            "34014": {"added": ["Control+KeyN"]},
        }
        self.preferences.write_text(json.dumps(data))
        browser.write_preferences(self.profile, services=True, kiosk=True)
        self.assertEqual(self.read()["helium"]["browser"]["custom_accelerators"], {
            "34031": {"added": ["F9", "Control+Shift+KeyQ"]},
            "34014": {"added": ["Control+KeyN"]},
        })
        data = self.read()
        data["helium"]["browser"]["custom_accelerators"]["34031"] = {"added": "F9"}
        self.preferences.write_text(json.dumps(data))
        browser.write_preferences(self.profile, services=True, kiosk=True)
        self.assertEqual(self.read()["helium"]["browser"]["custom_accelerators"]["34031"], {"added": ["Control+Shift+KeyQ"]})
        data = self.read()
        data["helium"]["browser"] = "damaged"
        self.preferences.write_text(json.dumps(data))
        browser.write_preferences(self.profile, services=True, kiosk=True)
        self.assertEqual(self.read()["helium"]["browser"], {"custom_accelerators": {"34031": {"added": ["Control+Shift+KeyQ"]}}})

    def test_an_install_puts_the_new_profile_settings_back_and_keeps_the_rest(self):
        self.assertFalse(browser.reset(self.profile, kiosk=True))
        browser.write_preferences(self.profile, services=True, kiosk=True)
        browser.write_local_state(self.profile)
        data = self.read()
        data["translate"]["enabled"] = True
        data["profile"]["default_content_setting_values"]["notifications"] = 1
        data["homepage"] = "https://example.com/"
        self.preferences.write_text(json.dumps(data))
        (self.profile / "Local State").write_text(json.dumps({"helium": {"crash_reporting": {"mode": 1}}, "browser": {"x": 1}}))
        self.assertTrue(browser.reset(self.profile, kiosk=True))
        data = self.read()
        self.assertFalse(data["translate"]["enabled"])
        self.assertEqual(data["profile"]["default_content_setting_values"]["notifications"], 2)
        self.assertEqual(data["homepage"], "https://example.com/")
        self.assertEqual(json.loads((self.profile / "Local State").read_text()), {"helium": {"crash_reporting": {"mode": -1}}, "browser": {"x": 1}})
        self.assertFalse(browser.reset(self.profile, kiosk=True))
        self.preferences.write_text("{")
        self.assertFalse(browser.reset(self.profile, kiosk=True))
        self.assertEqual(self.preferences.read_text(), "{")

    def test_a_sign_in_page_may_hand_its_callback_to_the_app_without_asking(self):
        browser.write_preferences(self.profile, services=True, kiosk=False)
        authorize = "https://account.matrix.org/authorize?response_type=code&redirect_uri=io.element.desktop%3A%2Fvector%2Fwebapp%2F&state=x"
        self.assertEqual(browser.allow_callbacks(self.profile, authorize, ("io.element.desktop", "element")), ["io.element.desktop"])
        sso = "https://vault.bitwarden.com/#/sso?clientId=desktop&redirectUri=bitwarden%3A%2F%2Fsso-callback&state=y"
        self.assertEqual(browser.allow_callbacks(self.profile, sso, ("bitwarden",)), ["bitwarden"])
        for url in ("https://example.org/news?redirect_uri=https://example.org/", "http://account.matrix.org/authorize?redirect_uri=io.element.desktop:x",
                    "https://example.org/"):
            self.assertEqual(browser.allow_callbacks(self.profile, url, ("io.element.desktop", "bitwarden")), [])
        self.assertEqual(self.read()["protocol_handler"]["allowed_origin_protocol_pairs"], {
            "https://account.matrix.org": {"io.element.desktop": True},
            "https://vault.bitwarden.com": {"bitwarden": True},
        })

    def test_a_sign_in_page_names_the_addresses_it_returns_to(self):
        login = "https://auth.example.com/2.0/oauth/authorize?response_type=code&redirect_uri=https://app.example.com/redirect&scope=a b&"
        self.assertEqual(browser.return_addresses(login), ["https://app.example.com/redirect"])
        self.assertEqual(browser.return_addresses("https://vault.example.com/#/sso?redirectUri=bitwarden%3A%2F%2Fsso"), ["bitwarden://sso"])
        self.assertEqual(browser.return_addresses("http://auth.example.com/?redirect_uri=https://app.example.com/"), [])

    def test_a_web_store_extension_is_offered_pinned_once_and_withdrawn_leaving_other_files(self):
        extension, other = "nngceckbapebfimnlniiiahkandclblb", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        browser.write_preferences(self.profile, services=True, kiosk=False)
        folder = self.profile / "External Extensions"
        folder.mkdir()
        (folder / f"{other}.json").write_text("{}")
        self.assertEqual(browser.offer_extensions(self.profile, [extension], [extension]), ([extension], []))
        self.assertEqual(json.loads((folder / f"{extension}.json").read_text()), {"external_update_url": "https://clients2.google.com/service/update2/crx"})
        self.assertEqual(self.read()["extensions"]["pinned_extensions"], [extension])
        data = self.read()
        data["extensions"]["pinned_extensions"] = [other]
        self.preferences.write_text(json.dumps(data))
        self.assertEqual(browser.offer_extensions(self.profile, [extension], [extension]), ([], []))
        self.assertEqual(self.read()["extensions"]["pinned_extensions"], [other])
        self.assertEqual(browser.offer_extensions(self.profile, [], [extension]), ([], [extension]))
        self.assertEqual(sorted(path.name for path in folder.iterdir()), [f"{other}.json"])
        self.assertEqual(browser.offer_extensions(self.profile, [], [extension]), ([], []))
        self.preferences.write_text("{")
        self.assertEqual(browser.offer_extensions(self.profile, [extension], [extension]), ([extension], []))
        self.assertEqual(self.preferences.read_text(), "{")

    def test_a_native_messaging_host_is_offered_rewritten_when_it_differs_and_withdrawn(self):
        manifest = browser.native_host("com.8bit.bitwarden", "Bitwarden's desktop app", Path("/p/share/bitwarden/desktop-proxy"),
                                       "nngceckbapebfimnlniiiahkandclblb")
        self.assertEqual(manifest, {"name": "com.8bit.bitwarden", "description": "Bitwarden's desktop app", "path": "/p/share/bitwarden/desktop-proxy",
                                    "type": "stdio", "allowed_origins": ["chrome-extension://nngceckbapebfimnlniiiahkandclblb/"]})
        folder = self.profile / "NativeMessagingHosts"
        folder.mkdir(parents=True)
        (folder / "org.keepassxc.keepassxc_browser.json").write_text("{}")
        hosts, wanted = {"com.8bit.bitwarden": manifest}, ["com.8bit.bitwarden"]
        self.assertEqual(browser.offer_native_hosts(self.profile, hosts, wanted), (["com.8bit.bitwarden"], []))
        self.assertEqual(json.loads((folder / "com.8bit.bitwarden.json").read_text()), manifest)
        self.assertEqual(browser.offer_native_hosts(self.profile, hosts, wanted), ([], []))
        moved = {"com.8bit.bitwarden": {**manifest, "description": "Bitwarden"}}
        self.assertEqual(browser.offer_native_hosts(self.profile, moved, wanted), (["com.8bit.bitwarden"], []))
        self.assertEqual(browser.offer_native_hosts(self.profile, hosts, []), ([], ["com.8bit.bitwarden"]))
        self.assertEqual(browser.offer_native_hosts(self.profile, hosts, []), ([], []))
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["org.keepassxc.keepassxc_browser.json"])

    def test_a_host_that_runs_another_program_is_replaced_while_wanted_and_otherwise_left_alone(self):
        ours = browser.native_host("com.8bit.bitwarden", "Bitwarden's desktop app", Path("/p/share/bitwarden/desktop-proxy"),
                                   "nngceckbapebfimnlniiiahkandclblb")
        theirs = {**ours, "description": "Bitwarden desktop <-> browser bridge", "path": "/home/deck/Applications/Bitwarden/desktop_proxy"}
        path = self.profile / "NativeMessagingHosts" / "com.8bit.bitwarden.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(theirs))
        self.assertEqual(browser.offer_native_hosts(self.profile, {"com.8bit.bitwarden": ours}, []), ([], []))
        self.assertEqual(json.loads(path.read_text()), theirs)
        path.write_text("{broken")
        self.assertEqual(browser.offer_native_hosts(self.profile, {"com.8bit.bitwarden": ours}, []), ([], []))
        self.assertEqual(browser.offer_native_hosts(self.profile, {"com.8bit.bitwarden": ours}, ["com.8bit.bitwarden"]),
                         (["com.8bit.bitwarden"], []))
        self.assertEqual(json.loads(path.read_text()), ours)

    def test_a_corrupt_file_is_kept_aside(self):
        self.preferences.parent.mkdir(parents=True)
        self.preferences.write_text("{broken")
        browser.write_preferences(self.profile, services=True, kiosk=True)
        self.assertEqual(self.preferences.with_name("Preferences.corrupt").read_text(), "{broken")
        self.assertTrue(self.read()["helium"]["completed_onboarding"])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profile = self.dir / "profile"
        self.profile.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_lock_left_by_a_closed_helium_is_cleared(self):
        (self.profile / "SingletonLock").symlink_to("steamdeck-999999999")
        (self.profile / "SingletonSocket").symlink_to("/tmp/gone/socket")
        self.assertTrue(browser.clear_stale_lock(self.profile))
        self.assertFalse(os.path.lexists(self.profile / "SingletonLock"))
        self.assertFalse(os.path.lexists(self.profile / "SingletonSocket"))
        self.assertFalse(browser.clear_stale_lock(self.profile))

    def test_a_profile_is_in_use_while_a_running_helium_holds_its_lock(self):
        self.assertFalse(browser.in_use(self.profile))
        program = self.dir / "helium"
        _fakes.sleeper(program)
        helium = _fakes.sleeping(program)
        self.addCleanup(helium.wait)
        self.addCleanup(helium.kill)
        lock = self.profile / "SingletonLock"
        lock.symlink_to(f"steamdeck-{helium.pid}")
        self.assertTrue(browser.in_use(self.profile))
        self.assertFalse(browser.clear_stale_lock(self.profile))
        lock.unlink()
        lock.symlink_to(f"steamdeck-{os.getpid()}")
        self.assertFalse(browser.in_use(self.profile))

    def test_a_profile_was_last_used_when_its_local_state_was_written(self):
        self.assertEqual(browser.last_used(self.profile), 0.0)
        (self.profile / "Local State").write_text("{}")
        os.utime(self.profile / "Local State", (1000, 1000))
        self.assertEqual(browser.last_used(self.profile), 1000)

    def test_new_profiles_start_with_crash_reports_off_and_keep_a_later_choice(self):
        state = browser.write_local_state(self.profile)
        self.assertEqual(json.loads(state.read_text()), {"helium": {"crash_reporting": {"mode": -1}}})
        state.write_text(json.dumps({"helium": {"crash_reporting": {}}, "browser": {"enabled_labs_experiments": []}}))
        browser.write_local_state(self.profile)
        self.assertEqual(json.loads(state.read_text())["helium"]["crash_reporting"], {})

    def test_on_a_steam_deck_profiles_start_spacious_and_an_install_puts_it_back(self):
        state = browser.write_local_state(self.profile, handheld=True)
        self.assertEqual(json.loads(state.read_text()), {"helium": {"crash_reporting": {"mode": -1}, "browser": {"ui_density": 1}}})
        state.write_text(json.dumps({"helium": {"crash_reporting": {"mode": -1}, "browser": {"ui_density": 0, "x": 1}}}))
        self.assertFalse(browser.reset(self.profile, kiosk=False))
        self.assertTrue(browser.reset(self.profile, kiosk=False, handheld=True))
        self.assertEqual(json.loads(state.read_text())["helium"]["browser"], {"ui_density": 1, "x": 1})
        self.assertFalse(browser.reset(self.profile, kiosk=False, handheld=True))
        other = self.dir / "machine"
        other.mkdir()
        self.assertEqual(json.loads(browser.write_local_state(other).read_text()), {"helium": {"crash_reporting": {"mode": -1}}})

    def test_every_profile_shares_one_widevine_folder(self):
        shared = self.dir / "helium" / "WidevineCdm"
        browser.link_widevine(self.profile, shared)
        self.assertEqual((self.profile / "WidevineCdm").resolve(), shared.resolve())
        shared.rmdir()
        browser.link_widevine(self.profile, shared)
        self.assertTrue(shared.is_dir())
        other = self.dir / "other"
        (other / "WidevineCdm").mkdir(parents=True)
        browser.link_widevine(other, shared)
        self.assertFalse((other / "WidevineCdm").is_symlink())


class FlagTests(unittest.TestCase):
    def test_full_screen_apps_run_as_a_kiosk_with_tv_input(self):
        arguments = browser.flags(Path("/p"), "https://www.primevideo.com/", True, True, 1.5, "nonsteamapps-primevideo")
        self.assertEqual(arguments[:3], ["--user-data-dir=/p", "--class=nonsteamapps-primevideo", "--no-first-run"])
        for flag in ("--kiosk", "--enable-spatial-navigation", "--force-dark-mode", "--password-store=basic", "--ozone-platform=x11",
                     "--force-device-scale-factor=1.5", "--autoplay-policy=no-user-gesture-required"):
            self.assertIn(flag, arguments)
        self.assertEqual(arguments[-1], "https://www.primevideo.com/")

    def test_a_browser_window_can_be_given_the_screens_size_instead_of_being_maximised(self):
        arguments = browser.flags(Path("/p"), "https://example.org/", False, True, 1.5, "nonsteamapps-helium", (1280, 720))
        self.assertEqual(arguments[-3:], ["--window-position=0,0", "--window-size=1280,720", "https://example.org/"])
        self.assertNotIn("--start-maximized", arguments)
        kiosk = browser.flags(Path("/p"), "https://example.org/", True, True, 1.5, "nonsteamapps-netflix", (1280, 720))
        self.assertFalse(any(flag.startswith("--window-") for flag in kiosk))

    def test_the_focus_outline_loads_when_it_is_installed_and_full_screen_hints_stay_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            extension = Path(tmp) / "focus"
            missing = browser.flags(Path("/p"), "https://example.org/", True, True, None, "nonsteamapps-netflix", extensions=[extension])
            self.assertFalse(any(flag.startswith("--load-extension") for flag in missing))
            extension.mkdir()
            (extension / "manifest.json").write_text("{}")
            other = Path(tmp) / "protondb"
            other.mkdir()
            (other / "manifest.json").write_text("{}")
            arguments = browser.flags(Path("/p"), "https://example.org/", True, True, None, "nonsteamapps-netflix", extensions=[extension, other, Path(tmp) / "gone"])
            self.assertIn(f"--load-extension={extension},{other}", arguments)
            self.assertIn("--hide-fullscreen-exit-ui", arguments)
            self.assertEqual(arguments[-1], "https://example.org/")

    def test_the_shipped_focus_outline_is_an_extension_that_styles_only_keyboard_focus(self):
        folder = _paths.ROOT / "src" / "share" / "extensions" / "focus"
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["manifest_version"], 3)
        [scripts] = manifest["content_scripts"]
        self.assertEqual((scripts["matches"], scripts["css"], scripts.get("js")), (["<all_urls>"], ["focus.css"], None))
        self.assertNotIn("permissions", manifest)
        css = (folder / "focus.css").read_text()
        self.assertTrue(css.startswith(":focus-visible:not(video):not(:has(video)) {"))
        self.assertIn("outline: 3px solid", css)

    def test_on_a_steam_deck_pages_get_overlay_scrollbars(self):
        arguments = browser.flags(Path("/p"), "", False, True, 1.25, "nonsteamapps-helium", (1024, 640), handheld=True)
        self.assertIn(f"--enable-features={browser.FEATURES},OverlayScrollbar:mode/overlay", arguments)
        self.assertEqual(arguments[-2:], ["--window-position=0,0", "--window-size=1024,640"])
        self.assertIn("--force-device-scale-factor=1.25", arguments)
        self.assertNotIn("--disable-pinch", arguments)
        kiosk = browser.flags(Path("/p"), "https://www.netflix.com/", True, True, 1.25, "nonsteamapps-netflix", handheld=True)
        self.assertIn(f"--enable-features={browser.FEATURES},OverlayScrollbar:mode/overlay", kiosk)
        self.assertIn("--disable-pinch", kiosk)
        self.assertIn(f"--enable-features={browser.FEATURES}", browser.flags(Path("/p"), "", False, True, None, "nonsteamapps-helium"))

    def test_the_browser_opens_maximised_with_its_own_interface(self):
        arguments = browser.flags(Path("/p"), "", False, False, None, "nonsteamapps-helium")
        self.assertIn("--start-maximized", arguments)
        self.assertIn("--ozone-platform-hint=auto", arguments)
        self.assertNotIn("--kiosk", arguments)
        self.assertFalse(any(flag.startswith("--force-device-scale-factor") for flag in arguments))


if __name__ == "__main__":
    unittest.main()
