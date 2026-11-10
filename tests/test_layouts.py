import tempfile
import unittest
from pathlib import Path

import _fakes
import _paths  # noqa: F401
from nonsteamapps import controllers, layouts, vdf


def find(pairs, key):
    return next(value for name, value in pairs if name == key)


def groups(layout):
    mappings = find(layout, "controller_mappings")
    sources = dict(find(find(mappings, "preset"), "group_source_bindings"))
    return {sources[find(group, "id")].split()[0]: group for name, group in mappings if name == "group"}


def bindings(group, button, kind="Full_Press"):
    activator = find(find(find(find(group, "inputs"), button), "activators"), kind)
    return [value for _, value in find(activator, "bindings")]


class FilesLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = _fakes.add_controller_templates(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        return vdf.loads_pairs((self.folder / name).read_text(encoding="utf-8"))

    def test_the_deck_gets_the_web_browser_layout_changed_for_a_file_manager(self):
        layout = layouts.build(layouts.FILES, self.read(layouts.FILES.base), self.read("controller_neptune_gamepad_joystick.vdf"))
        mappings = find(layout, "controller_mappings")
        self.assertEqual(find(mappings, "title"), layouts.FILES.title)
        self.assertEqual(find(mappings, "controller_type"), "controller_neptune")
        found = groups(layout)
        self.assertEqual(
            sorted(found),
            ["button_diamond", "dpad", "joystick", "left_trackpad", "left_trigger", "right_joystick", "right_trackpad", "right_trigger", "switch"],
        )
        self.assertEqual(bindings(found["button_diamond"], "button_a"), ["key_press RETURN, Open"])
        self.assertEqual(bindings(found["button_diamond"], "button_y"), ["mouse_button FORWARD, ▶️"])
        self.assertEqual(bindings(found["button_diamond"], "button_b"), ["mouse_button BACK, ◀️"])
        self.assertEqual(find(found["joystick"], "mode"), "dpad")
        self.assertEqual(bindings(found["joystick"], "dpad_west"), ["key_press LEFT_ARROW, ⏪"])
        self.assertEqual(find(found["left_trackpad"], "mode"), "scrollwheel")
        self.assertEqual(
            [name for name, _ in find(found["switch"], "inputs")],
            ["button_escape", "button_menu", "left_bumper", "right_bumper", "button_back_left", "button_back_right", "always_on_action"],
        )
        self.assertEqual((bindings(found["switch"], layouts.MENU), bindings(found["switch"], layouts.VIEW)),
                         (["key_press LEFT_CONTROL, Close tab", "key_press W"], ["key_press ESCAPE, Escape"]))
        self.assertEqual(find(mappings, "settings"), [("left_trackpad_mode", "0")])
        ids = [find(group, "id") for name, group in mappings if name == "group"]
        self.assertEqual(ids, [str(index) for index in range(len(ids))])

    def test_other_controllers_keep_only_the_inputs_they_have(self):
        layout = layouts.build(layouts.FILES, self.read(layouts.FILES.base), self.read("controller_xboxone_gamepad_joystick.vdf"))
        mappings = find(layout, "controller_mappings")
        found = groups(layout)
        self.assertNotIn("left_trackpad", found)
        self.assertEqual(
            [name for name, _ in find(found["switch"], "inputs")],
            ["button_escape", "button_menu", "left_bumper", "right_bumper", "button_capture"],
        )
        self.assertEqual(bindings(found["button_diamond"], "button_a"), ["key_press RETURN, Open"])
        self.assertEqual(find(mappings, "settings"), [("xbox", "1")])

    def test_minecraft_starts_from_the_wasd_layout_with_minecrafts_keys(self):
        layout = layouts.build(layouts.MINECRAFT, self.read(layouts.MINECRAFT.base), self.read("controller_xboxone_gamepad_joystick.vdf"))
        mappings = find(layout, "controller_mappings")
        self.assertEqual(find(mappings, "title"), layouts.MINECRAFT.title)
        found = groups(layout)
        self.assertNotIn("left_trackpad", found)
        self.assertEqual(
            [bindings(found["button_diamond"], button) for button in ("button_a", "button_b", "button_x", "button_y")],
            [["key_press SPACE"], ["key_press E"], ["key_press Q, Drop"], ["key_press F"]],
        )
        self.assertEqual(
            [bindings(found["switch"], button) for button in (layouts.MENU, layouts.VIEW, "left_bumper", "right_bumper")],
            [["key_press ESCAPE, Pause"], ["key_press TAB, Players"], ["mouse_wheel SCROLL_UP"], ["mouse_wheel SCROLL_DOWN"]],
        )
        self.assertEqual(bindings(found["joystick"], "click"), ["key_press LEFT_CONTROL, Sprint"])
        self.assertEqual(bindings(found["joystick"], "dpad_north"), ["key_press W"])
        self.assertEqual(bindings(found["right_joystick"], "click"), ["key_press LEFT_SHIFT, Sneak"])
        self.assertEqual(bindings(found["right_trigger"], "edge"), ["mouse_button LEFT"])

    def test_install_writes_a_layout_for_each_controller_and_remove_deletes_only_those(self):
        written = layouts.install(self.root, layouts.FILES)
        self.assertEqual(written, ["controller_neptune_nonsteamapps_files.vdf", "controller_xboxone_nonsteamapps_files.vdf"])
        self.assertEqual(
            controllers.find_templates(self.root, layouts.FILES.title),
            {"controller_neptune": written[0], "controller_xboxone": written[1]},
        )
        stamp = (self.folder / written[0]).stat().st_mtime_ns
        self.assertEqual(layouts.install(self.root, layouts.FILES), [])
        self.assertEqual((self.folder / written[0]).stat().st_mtime_ns, stamp)
        (self.folder / written[1]).unlink()
        self.assertEqual(layouts.install(self.root, layouts.FILES), written[1:])
        minecraft = layouts.install(self.root, layouts.MINECRAFT)
        self.assertEqual(minecraft, ["controller_neptune_nonsteamapps_minecraft.vdf", "controller_xboxone_nonsteamapps_minecraft.vdf"])
        self.assertEqual(layouts.remove(self.root, layouts.FILES), written)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [
            "controller_mobile_touch_gamepad_joystick.vdf",
            "controller_neptune_gamepad+mouse.vdf",
            "controller_neptune_gamepad_joystick.vdf",
            "controller_neptune_nonsteamapps_minecraft.vdf",
            "controller_neptune_wasd.vdf",
            "controller_neptune_webbrowser.vdf",
            "controller_xboxone_gamepad_joystick.vdf",
            "controller_xboxone_nonsteamapps_minecraft.vdf",
        ])

    def test_the_emulator_layout_replaces_the_kytyps5_layout_of_2_19_0(self):
        old = ["controller_neptune_nonsteamapps_kytyps5.vdf", "controller_xboxone_nonsteamapps_kytyps5.vdf"]
        for name in old:
            (self.folder / name).write_text('"controller_mappings" {}')
        written = layouts.install(self.root, layouts.EMULATOR)
        self.assertEqual(written, ["controller_neptune_nonsteamapps_emulator.vdf", "controller_xboxone_nonsteamapps_emulator.vdf"])
        self.assertFalse(any((self.folder / name).exists() for name in old))
        (self.folder / old[0]).write_text('"controller_mappings" {}')
        self.assertEqual(layouts.remove(self.root, layouts.EMULATOR), [*written, old[0]])
        self.assertEqual(list(self.folder.glob("*_nonsteamapps_*")), [])

    def test_without_valves_base_layout_nothing_is_written(self):
        (self.folder / layouts.FILES.base).unlink()
        self.assertEqual(layouts.install(self.root, layouts.FILES), [])
        self.assertEqual(layouts.install(self.root / "elsewhere", layouts.MINECRAFT), [])

    def test_tools_select_with_a_confirm_with_y_and_step_between_controls_with_the_dpad(self):
        layout = layouts.build(layouts.TOOLS, self.read(layouts.TOOLS.base), self.read("controller_neptune_gamepad_joystick.vdf"))
        found = groups(layout)
        self.assertEqual(
            [bindings(found["button_diamond"], button) for button in ("button_a", "button_b", "button_x", "button_y")],
            [["key_press SPACE, Select"], ["key_press ESCAPE, Cancel"], ["controller_action SHOW_KEYBOARD, ⌨️"], ["key_press RETURN, OK"]],
        )
        self.assertEqual(
            [bindings(found["dpad"], button) for button in ("dpad_north", "dpad_south", "dpad_west", "dpad_east")],
            [["key_press UP_ARROW, ⏫"], ["key_press DOWN_ARROW, ⏬"], ["key_press LEFT_SHIFT", "key_press TAB, Previous"], ["key_press TAB, Next"]],
        )
        self.assertEqual(bindings(found["right_trigger"], "edge"), ["mouse_button LEFT"])
        self.assertEqual(find(found["joystick"], "mode"), "dpad")
        self.assertEqual(bindings(found["joystick"], "dpad_north"), ["mouse_wheel SCROLL_UP, ⏫"])

    def test_menu_and_view_are_the_buttons_valves_layouts_press_start_and_select_and_escape_and_tab_with(self):
        for template, menu, view in (("controller_neptune_gamepad_joystick.vdf", ["xinput_button start"], ["xinput_button select"]),
                                     ("controller_xboxone_gamepad_joystick.vdf", ["xinput_button start"], ["xinput_button select"]),
                                     ("controller_neptune_wasd.vdf", ["key_press ESCAPE"], ["key_press TAB"]),
                                     ("controller_neptune_webbrowser.vdf", ["key_press ESCAPE"], ["key_press LEFT_CONTROL, ⛔", "key_press W"])):
            with self.subTest(template=template):
                switch = groups(self.read(template))["switch"]
                self.assertEqual((bindings(switch, layouts.MENU), bindings(switch, layouts.VIEW)), (menu, view))

    def test_holding_menu_quits_helium_and_files_and_a_short_press_still_closes_the_tab(self):
        for layout, quit_keys in ((layouts.BROWSER, ["key_press LEFT_CONTROL, Quit", "key_press LEFT_SHIFT", "key_press W", "key_press Q"]),
                                  (layouts.FILES, ["key_press LEFT_CONTROL, Quit", "key_press Q"])):
            built = layouts.build(layout, self.read(layout.base), self.read("controller_xboxone_gamepad_joystick.vdf"))
            switch = groups(built)["switch"]
            self.assertEqual(bindings(switch, layouts.MENU), ["key_press LEFT_CONTROL, Close tab", "key_press W"])
            self.assertEqual(bindings(switch, layouts.MENU, "Long_Press"), quit_keys)
            self.assertEqual(bindings(switch, layouts.VIEW), ["key_press ESCAPE, Escape"])
            self.assertEqual([kind for kind, _ in find(find(find(switch, "inputs"), layouts.VIEW), "activators")], ["Full_Press"])
            full = find(find(find(find(switch, "inputs"), layouts.MENU), "activators"), "Full_Press")
            self.assertEqual(find(full, "settings"), [("interruptable", "1")])
        found = groups(layouts.build(layouts.BROWSER, self.read(layouts.BROWSER.base), self.read("controller_neptune_gamepad_joystick.vdf")))
        self.assertEqual(bindings(found["button_diamond"], "button_a"), ["key_press RETURN, ⏯️", "key_press SPACE"])
        switch = found["switch"]
        self.assertEqual([bindings(switch, bumper) for bumper in ("left_bumper", "right_bumper")], [["mouse_button BACK, ◀️"], ["mouse_button FORWARD, ▶️"]])
        self.assertEqual([bindings(switch, bumper, "Long_Press") for bumper in ("left_bumper", "right_bumper")],
                         [["key_press LEFT_CONTROL, Previous tab", "key_press PAGE_UP"], ["key_press LEFT_CONTROL, Next tab", "key_press PAGE_DOWN"]])

    def test_localsend_selects_once_goes_back_with_b_and_quits_when_menu_is_held(self):
        found = groups(layouts.build(layouts.LOCALSEND, self.read(layouts.LOCALSEND.base), self.read("controller_neptune_gamepad_joystick.vdf")))
        self.assertEqual(
            [bindings(found["button_diamond"], button) for button in ("button_a", "button_b", "button_x", "button_y")],
            [["key_press RETURN, Select"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"], ["key_press LEFT_CONTROL, Paste", "key_press V"]],
        )
        self.assertEqual(bindings(found["dpad"], "dpad_west"), ["key_press LEFT_ARROW, ⏪"])
        switch = found["switch"]
        self.assertEqual(
            [bindings(switch, button) for button in ("left_bumper", "right_bumper", layouts.MENU)],
            [["key_press LEFT_SHIFT", "key_press TAB, Previous"], ["key_press TAB, Next"], ["key_press ESCAPE"]],
        )
        self.assertEqual(bindings(switch, layouts.MENU, "Long_Press"), ["key_press LEFT_CONTROL, Quit", "key_press Q"])
        self.assertEqual(bindings(switch, layouts.VIEW), ["key_press LEFT_CONTROL, ⛔", "key_press W"])

    def test_jellyfin_gets_its_own_keys_and_b_never_holds_escape(self):
        for pad in ("controller_neptune_gamepad_joystick.vdf", "controller_xboxone_gamepad_joystick.vdf"):
            found = groups(layouts.build(layouts.JELLYFIN, self.read(layouts.JELLYFIN.base), self.read(pad)))
            diamond, switch = found["button_diamond"], found["switch"]
            self.assertEqual(
                [bindings(diamond, button) for button in ("button_a", "button_b", "button_x", "button_y")],
                [["key_press RETURN, Select"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"],
                 ["key_press LEFT_CONTROL, Search", "key_press F"]],
            )
            self.assertEqual(bindings(diamond, "button_b", "Long_Press"), ["key_press H, Home"])
            self.assertEqual(
                [bindings(switch, button) for button in (layouts.MENU, layouts.VIEW, "left_bumper", "right_bumper")],
                [["key_press SPACE, Play or pause"], ["key_press H, Home"], ["key_press PAGE_UP, Rewind"], ["key_press PAGE_DOWN, Fast forward"]],
            )
            self.assertEqual(bindings(switch, layouts.MENU, "Long_Press"), ["key_press LEFT_CONTROL, Quit", "key_press Q"])
            self.assertEqual((find(found["joystick"], "mode"), bindings(found["joystick"], "dpad_west")), ("dpad", ["key_press LEFT_ARROW, ⏪"]))
            self.assertEqual(bindings(found["dpad"], "dpad_north"), ["key_press UP_ARROW, ⏫"])

    def test_bitwarden_moves_with_the_d_pad_and_left_stick_and_reaches_what_its_hidden_menu_holds(self):
        found = groups(layouts.build(layouts.BITWARDEN, self.read(layouts.BITWARDEN.base), self.read("controller_xboxone_gamepad_joystick.vdf")))
        arrows = [["key_press UP_ARROW, ⏫"], ["key_press DOWN_ARROW, ⏬"], ["key_press RIGHT_ARROW, ⏩"], ["key_press LEFT_ARROW, ⏪"]]
        for source in ("dpad", "joystick"):
            self.assertEqual((find(found[source], "mode"), [bindings(found[source], f"dpad_{way}") for way in ("north", "south", "east", "west")]),
                             ("dpad", arrows), source)
        self.assertEqual([bindings(found["button_diamond"], f"button_{key}") for key in "abxy"],
                         [["key_press RETURN, Select"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"], ["key_press SPACE, Tick"]])
        switch = found["switch"]
        self.assertEqual(
            [bindings(switch, button) for button in (layouts.MENU, layouts.VIEW, "left_bumper", "right_bumper")],
            [["key_press LEFT_CONTROL, Settings", "key_press COMMA"], ["key_press LEFT_CONTROL, Lock", "key_press L"],
             ["key_press LEFT_CONTROL, Search", "key_press F"], ["key_press LEFT_CONTROL, Generator", "key_press G"]],
        )
        self.assertEqual(bindings(switch, layouts.MENU, "Long_Press"), ["key_press LEFT_CONTROL, Quit", "key_press Q"])

    def test_element_signal_and_discord_move_with_the_d_pad_and_left_stick_and_change_room_with_the_bumpers(self):
        arrows = [["key_press UP_ARROW, ⏫"], ["key_press DOWN_ARROW, ⏬"], ["key_press RIGHT_ARROW, ⏩"], ["key_press LEFT_ARROW, ⏪"]]
        menus = {
            layouts.ELEMENT: (["key_press LEFT_CONTROL, User menu", "key_press BACK_TICK"], ["key_press LEFT_CONTROL, Jump to room", "key_press K"],
                              ["key_press F6, Next area"], ["key_press LEFT_CONTROL, Quit", "key_press LEFT_SHIFT", "key_press W", "key_press Q"]),
            layouts.SIGNAL: (["key_press LEFT_CONTROL, Settings", "key_press COMMA"], ["key_press LEFT_CONTROL, Search", "key_press F"],
                             ["key_press LEFT_CONTROL, Next section", "key_press T"], ["key_press LEFT_CONTROL, Quit", "key_press Q"]),
            layouts.DISCORD: (["key_press LEFT_CONTROL, Settings", "key_press COMMA"], ["key_press LEFT_CONTROL, Quick Switcher", "key_press K"],
                              None, ["key_press LEFT_CONTROL, Quit", "key_press Q"]),
        }
        for layout, (menu, view, held_view, held_menu) in menus.items():
            with self.subTest(layout=layout.slug):
                found = groups(layouts.build(layout, self.read(layout.base), self.read("controller_xboxone_gamepad_joystick.vdf")))
                for source in ("dpad", "joystick"):
                    self.assertEqual([bindings(found[source], f"dpad_{way}") for way in ("north", "south", "east", "west")], arrows, source)
                self.assertEqual([bindings(found["button_diamond"], f"button_{key}") for key in "abxy"],
                                 [["key_press RETURN, Select"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"], ["key_press SPACE, Tick"]])
                switch = found["switch"]
                self.assertEqual([bindings(switch, "left_bumper"), bindings(switch, "right_bumper")],
                                 [["key_press LEFT_ALT, Previous", "key_press UP_ARROW"], ["key_press LEFT_ALT, Next", "key_press DOWN_ARROW"]])
                self.assertEqual((bindings(switch, layouts.MENU), bindings(switch, layouts.VIEW)), (menu, view))
                self.assertEqual(bindings(switch, layouts.MENU, "Long_Press"), held_menu)
                if held_view is None:
                    self.assertEqual([kind for kind, _ in find(find(find(switch, "inputs"), layouts.VIEW), "activators")], ["Full_Press"])
                else:
                    self.assertEqual(bindings(switch, layouts.VIEW, "Long_Press"), held_view)

    def test_vlc_plays_seeks_and_opens_with_its_own_keys_and_a_selects_without_pausing(self):
        for pad in ("controller_neptune_gamepad_joystick.vdf", "controller_xboxone_gamepad_joystick.vdf"):
            with self.subTest(pad=pad):
                found = groups(layouts.build(layouts.VLC, self.read(layouts.VLC.base), self.read(pad)))
                diamond, switch = found["button_diamond"], found["switch"]
                self.assertEqual([bindings(diamond, f"button_{key}") for key in "abxy"],
                                 [["key_press RETURN, Select"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"],
                                  ["key_press F, Full screen"]])
                buttons = (layouts.MENU, layouts.VIEW, "left_bumper", "right_bumper")
                self.assertEqual([bindings(switch, button) for button in buttons], [
                    ["key_press SPACE, Play or pause"], ["key_press LEFT_CONTROL, Open file", "key_press O"],
                    ["key_press LEFT_ALT, Back 10 seconds", "key_press LEFT_ARROW"], ["key_press LEFT_ALT, Forward 10 seconds", "key_press RIGHT_ARROW"],
                ])
                self.assertEqual([bindings(switch, button, "Long_Press") for button in buttons], [
                    ["key_press LEFT_CONTROL, Quit", "key_press Q"], ["key_press LEFT_CONTROL, Playlist", "key_press L"],
                    ["key_press P, Previous"], ["key_press N, Next"],
                ])
                self.assertEqual(bindings(found["dpad"], "dpad_west"), ["key_press LEFT_ARROW, ⏪"])
                self.assertEqual(bindings(found["joystick"], "dpad_north"), ["mouse_wheel SCROLL_UP, ⏫"])

    def test_bottles_is_the_emulator_layout_under_a_name_of_its_own(self):
        shift = self.read(layouts.EMULATOR.shift.template)
        pad = self.read("controller_neptune_gamepad_joystick.vdf")
        built = find(layouts.build(layouts.BOTTLES, self.read(layouts.BOTTLES.base), pad, shift), "controller_mappings")
        emulator = find(layouts.build(layouts.EMULATOR, self.read(layouts.EMULATOR.base), pad, shift), "controller_mappings")
        self.assertEqual((find(built, "title"), find(built, "revision")), ("Bottles (NonSteamApps)", "1"))
        self.assertEqual([pair for pair in built if isinstance(pair[1], list)], [pair for pair in emulator if isinstance(pair[1], list)])
        self.assertEqual((layouts.BOTTLES.base, layouts.BOTTLES.shift), (layouts.EMULATOR.base, layouts.EMULATOR.shift))

    def test_emulators_play_with_a_gamepad_and_the_trackpad_clicks_in_their_menus(self):
        deck = groups(layouts.build(layouts.EMULATOR, self.read(layouts.EMULATOR.base), self.read("controller_neptune_gamepad_joystick.vdf")))
        self.assertEqual(find(deck["right_trackpad"], "mode"), "absolute_mouse")
        self.assertEqual(bindings(deck["right_trackpad"], "click", "Soft_Press"), ["mouse_button LEFT"])
        self.assertNotIn("JOYSTICK_RIGHT", vdf.dumps_pairs([("group", deck["right_trackpad"])]))
        self.assertEqual(bindings(deck["button_diamond"], "button_a"), ["xinput_button A"])
        self.assertEqual((bindings(deck["switch"], layouts.MENU), bindings(deck["switch"], layouts.VIEW)), (["xinput_button start"], ["xinput_button select"]))
        xbox = groups(layouts.build(layouts.EMULATOR, self.read(layouts.EMULATOR.base), self.read("controller_xboxone_gamepad_joystick.vdf")))
        self.assertNotIn("right_trackpad", xbox)
        self.assertEqual(bindings(xbox["button_diamond"], "button_y"), ["xinput_button Y"])

    def test_holding_view_turns_the_emulator_layout_into_a_pointer_for_launcher_windows(self):
        shift = self.read(layouts.EMULATOR.shift.template)
        for template in ("controller_neptune_gamepad_joystick.vdf", "controller_xboxone_gamepad_joystick.vdf"):
            with self.subTest(template=template):
                built = layouts.build(layouts.EMULATOR, self.read(layouts.EMULATOR.base), self.read(template), shift)
                mappings = find(built, "controller_mappings")
                by_id = {find(group, "id"): group for name, group in mappings if name == "group"}
                bound = find(find(mappings, "preset"), "group_source_bindings")
                shifted = {binding.split()[0]: by_id[group_id] for group_id, binding in bound if binding.endswith("active modeshift")}
                active = {binding.split()[0]: by_id[group_id] for group_id, binding in bound if binding.endswith(" active")}
                self.assertEqual(sorted(shifted), ["button_diamond", "right_joystick"])
                ids = {binding.split()[0]: group_id for group_id, binding in bound if binding.endswith("active modeshift")}
                self.assertEqual(bindings(active["switch"], layouts.VIEW),
                                 ["xinput_button select", f"mode_shift right_joystick {ids['right_joystick']}",
                                  f"mode_shift button_diamond {ids['button_diamond']}"])
                self.assertEqual(bindings(active["switch"], layouts.MENU), ["xinput_button start"])
                self.assertEqual(find(shifted["right_joystick"], "mode"), "joystick_mouse")
                self.assertEqual(bindings(shifted["right_joystick"], "click"), ["mouse_button LEFT"])
                self.assertEqual([bindings(shifted["button_diamond"], button) for button in ("button_a", "button_b", "button_x", "button_y")],
                                 [["mouse_button LEFT, Click"], ["key_press ESCAPE, Back"], ["controller_action SHOW_KEYBOARD, ⌨️"],
                                  ["key_press RETURN, OK"]])
                self.assertEqual(bindings(active["button_diamond"], "button_a"), ["xinput_button A"])
                self.assertEqual(find(active["right_joystick"], "mode"), "joystick_move")
                self.assertEqual(find(mappings, "revision"), "4")
        alone = layouts.build(layouts.EMULATOR, self.read(layouts.EMULATOR.base), self.read("controller_xboxone_gamepad_joystick.vdf"))
        self.assertFalse(any(binding.endswith("modeshift") for _, binding in find(find(find(alone, "controller_mappings"), "preset"), "group_source_bindings")))
        (self.folder / layouts.EMULATOR.shift.template).unlink()
        self.assertEqual(len(layouts.install(self.root, layouts.EMULATOR)), 2)

    def test_youtube_stays_a_gamepad_and_holding_view_reloads_it(self):
        for template in ("controller_neptune_gamepad_joystick.vdf", "controller_xboxone_gamepad_joystick.vdf"):
            with self.subTest(template=template):
                found = groups(layouts.build(layouts.YOUTUBE, self.read(layouts.YOUTUBE.base), self.read(template)))
                switch = found["switch"]
                self.assertEqual(bindings(switch, layouts.VIEW), ["xinput_button select"])
                self.assertEqual(bindings(switch, layouts.VIEW, "Long_Press"), ["key_press LEFT_CONTROL, Reload", "key_press R"])
                full = find(find(find(find(switch, "inputs"), layouts.VIEW), "activators"), "Full_Press")
                self.assertEqual(find(full, "settings"), [("interruptable", "1")])
                self.assertEqual(bindings(switch, layouts.MENU), ["xinput_button start"])
                self.assertEqual([kind for kind, _ in find(find(find(switch, "inputs"), layouts.MENU), "activators")], ["Full_Press"])
                self.assertEqual(bindings(found["button_diamond"], "button_a"), ["xinput_button A"])

    def test_apps_find_the_layouts_they_ask_for(self):
        self.assertEqual(layouts.used_by(["Web Browser", layouts.MINECRAFT.title, layouts.FILES.title]), [layouts.FILES, layouts.MINECRAFT])
        self.assertEqual(layouts.used_by([layouts.TOOLS.title]), [layouts.TOOLS])
        self.assertEqual(layouts.used_by([layouts.LOCALSEND.title, layouts.BROWSER.title]), [layouts.BROWSER, layouts.LOCALSEND])
        self.assertEqual(layouts.used_by([layouts.YOUTUBE.title, layouts.EMULATOR.title]), [layouts.EMULATOR, layouts.YOUTUBE])
        self.assertEqual(layouts.used_by([layouts.VLC.title, layouts.DISCORD.title, layouts.BOTTLES.title]),
                         [layouts.BOTTLES, layouts.DISCORD, layouts.VLC])
        self.assertEqual(layouts.used_by(["Gamepad", ""]), [])


if __name__ == "__main__":
    unittest.main()
