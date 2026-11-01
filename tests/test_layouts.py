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
        layout = layouts.files_layout(self.read(layouts.BASE), self.read("controller_neptune_gamepad_joystick.vdf"))
        mappings = find(layout, "controller_mappings")
        self.assertEqual(find(mappings, "title"), layouts.FILES_TITLE)
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
        layout = layouts.files_layout(self.read(layouts.BASE), self.read("controller_xboxone_gamepad_joystick.vdf"))
        mappings = find(layout, "controller_mappings")
        found = groups(layout)
        self.assertNotIn("left_trackpad", found)
        self.assertEqual(
            [name for name, _ in find(found["switch"], "inputs")],
            ["button_escape", "button_menu", "left_bumper", "right_bumper", "button_capture"],
        )
        self.assertEqual(bindings(found["button_diamond"], "button_a"), ["key_press RETURN, Open"])
        self.assertEqual(find(mappings, "settings"), [("xbox", "1")])

    def test_install_writes_a_layout_for_each_controller_and_remove_deletes_only_those(self):
        written = layouts.install(self.root)
        self.assertEqual(written, ["controller_neptune_nonsteamapps_files.vdf", "controller_xboxone_nonsteamapps_files.vdf"])
        self.assertEqual(
            controllers.find_templates(self.root, layouts.FILES_TITLE),
            {"controller_neptune": written[0], "controller_xboxone": written[1]},
        )
        stamp = (self.folder / written[0]).stat().st_mtime_ns
        self.assertEqual(layouts.install(self.root), [])
        self.assertEqual((self.folder / written[0]).stat().st_mtime_ns, stamp)
        (self.folder / written[1]).unlink()
        self.assertEqual(layouts.install(self.root), written[1:])
        self.assertEqual(layouts.remove(self.root), written)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), [
            "controller_mobile_touch_gamepad_joystick.vdf",
            "controller_neptune_gamepad_joystick.vdf",
            "controller_neptune_webbrowser.vdf",
            "controller_xboxone_gamepad_joystick.vdf",
        ])

    def test_without_valves_web_browser_layout_nothing_is_written(self):
        (self.folder / layouts.BASE).unlink()
        self.assertEqual(layouts.install(self.root), [])
        self.assertEqual(layouts.install(self.root / "elsewhere"), [])


if __name__ == "__main__":
    unittest.main()
