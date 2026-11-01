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


def bindings(group, button):
    activator = find(find(find(find(group, "inputs"), button), "activators"), "Full_Press")
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
        self.assertEqual(bindings(found["switch"], "button_menu"), ["key_press LEFT_CONTROL, ⛔", "key_press W"])
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
            [bindings(found["switch"], button) for button in ("button_menu", "button_escape", "left_bumper", "right_bumper")],
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
            "controller_neptune_gamepad_joystick.vdf",
            "controller_neptune_nonsteamapps_minecraft.vdf",
            "controller_neptune_wasd.vdf",
            "controller_neptune_webbrowser.vdf",
            "controller_xboxone_gamepad_joystick.vdf",
            "controller_xboxone_nonsteamapps_minecraft.vdf",
        ])

    def test_without_valves_base_layout_nothing_is_written(self):
        (self.folder / layouts.FILES.base).unlink()
        self.assertEqual(layouts.install(self.root, layouts.FILES), [])
        self.assertEqual(layouts.install(self.root / "elsewhere", layouts.MINECRAFT), [])

    def test_apps_find_the_layouts_they_ask_for(self):
        self.assertEqual(layouts.used_by(["Web Browser", layouts.MINECRAFT.title, layouts.FILES.title]), [layouts.FILES, layouts.MINECRAFT])
        self.assertEqual(layouts.used_by(["Gamepad", ""]), [])


if __name__ == "__main__":
    unittest.main()
