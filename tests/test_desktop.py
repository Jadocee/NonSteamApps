import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from nonsteamapps import appmenu, desktop

ENTRY = "applications:nonsteamapps-helium.desktop"
DEFAULTS = ",".join(desktop.DEFAULT_LAUNCHERS)
LAYOUT = (
    "[Containments][1]\nplugin=org.kde.panel\n\n"
    "[Containments][1][Applets][2]\nplugin=org.kde.plasma.icontasks\n\n"
    "[Containments][3][Applets][4]\nplugin=org.kde.plasma.taskmanager\n\n"
    "[Containments][3][Applets][4][Configuration][General]\nlaunchers=applications:steam.desktop,file:///a\\,b.desktop\n\n"
    "[Containments][3][Applets][5]\nplugin=org.kde.plasma.kickoff\n"
)


def reply(body: bytes) -> appmenu.Message:
    return appmenu.Message(appmenu.METHOD_RETURN, 0, 1, {}, body, "<")


class EntryTests(unittest.TestCase):
    def test_the_entry_runs_the_app_with_links_and_names_its_window_class(self):
        text = desktop.entry_text("Helium", "A browser", Path("/p/apps/helium"), Path("/p/artwork/helium/icon.png"), "nonsteamapps-helium",
                                  "Web Browser", ("Network", "WebBrowser"))
        self.assertEqual(text, (
            "[Desktop Entry]\nType=Application\nName=Helium\nGenericName=Web Browser\nComment=A browser\n"
            'Exec="/p/apps/helium" %U\nIcon=/p/artwork/helium/icon.png\nTerminal=false\nCategories=Network;WebBrowser;\n'
            "StartupWMClass=nonsteamapps-helium\nStartupNotify=true\n"))
        self.assertEqual(desktop.launcher(Path("/h/.local/share/applications/nonsteamapps-helium.desktop")), ENTRY)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "applications" / "nonsteamapps-helium.desktop"
            self.assertEqual([desktop.write_entry(path, text), desktop.write_entry(path, text)], [True, False])
            self.assertEqual(path.read_text(), text)

    def test_arguments_come_before_the_links(self):
        text = desktop.entry_text("Helium", "A browser", Path("/p/helium/current/helium-wrapper"), Path("/p/icon.png"), "nonsteamapps-helium",
                                  arguments=("--class=nonsteamapps-helium",))
        self.assertIn('Exec="/p/helium/current/helium-wrapper" --class=nonsteamapps-helium %U\n', text)

    def test_a_programs_own_entry_starts_it_where_it_is_installed_with_its_icon_and_window_class(self):
        shipped = (
            "[Desktop Entry]\nVersion=1.0\nName=Helium\n\n# A comment = kept\nGenericName[de]=Web-Browser\nExec=helium %U\n"
            "TryExec=helium\nIcon=helium\nStartupWMClass=helium\nMimeType=text/html;x-scheme-handler/https;\n"
            "Actions=new-window;new-private-window;\n\n"
            "[Desktop Action new-window]\nName=New Window\nExec=helium\n\n"
            "[Desktop Action new-private-window]\nName=New Incognito Window\nExec = helium --incognito\n"
        )
        text = desktop.program_entry(shipped, Path("/p/helium/current/helium-wrapper"), Path("/p/helium/current/product_logo_256.png"),
                                     "nonsteamapps-helium")
        self.assertEqual(text, (
            "[Desktop Entry]\nStartupWMClass=nonsteamapps-helium\nVersion=1.0\nName=Helium\n\n# A comment = kept\nGenericName[de]=Web-Browser\n"
            'Exec="/p/helium/current/helium-wrapper" --class=nonsteamapps-helium %U\n'
            "Icon=/p/helium/current/product_logo_256.png\nMimeType=text/html;x-scheme-handler/https;\n"
            "Actions=new-window;new-private-window;\n\n"
            '[Desktop Action new-window]\nName=New Window\nExec="/p/helium/current/helium-wrapper" --class=nonsteamapps-helium\n\n'
            '[Desktop Action new-private-window]\nName=New Incognito Window\n'
            'Exec="/p/helium/current/helium-wrapper" --class=nonsteamapps-helium --incognito\n'))

    def test_kconfig_lists_keep_escaped_commas(self):
        self.assertEqual(desktop.split_list("a,b\\,c,d\\\\"), ["a", "b,c", "d\\"])
        self.assertEqual(desktop.join_list(["a", "b,c", "d\\"]), "a,b\\,c,d\\\\")
        self.assertEqual(desktop.split_list(""), [])


class TaskbarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.layout = Path(self.tmp.name) / desktop.LAYOUT
        patches = [mock.patch("nonsteamapps.desktop.plasma_running", return_value=False)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_without_plasma_the_layout_file_gets_the_launcher_after_the_others(self):
        self.layout.write_text(LAYOUT)
        self.assertTrue(desktop.pin(ENTRY, self.layout, {}))
        text = self.layout.read_text()
        self.assertIn(f"[Containments][1][Applets][2][Configuration][General]\nlaunchers={DEFAULTS},{ENTRY}\n", text)
        self.assertIn(f"launchers=applications:steam.desktop,file:///a\\,b.desktop,{ENTRY}\n", text)
        self.assertNotIn("[Containments][3][Applets][5][Configuration]", text)
        self.assertFalse(desktop.pin(ENTRY, self.layout, {}))
        self.assertTrue(desktop.unpin(ENTRY, self.layout, {}))
        text = self.layout.read_text()
        self.assertNotIn(ENTRY, text)
        self.assertIn(f"launchers={DEFAULTS}\n", text)
        self.assertIn("launchers=applications:steam.desktop,file:///a\\,b.desktop\n", text)
        self.assertFalse(desktop.unpin(ENTRY, self.layout, {}))

    def test_a_layout_without_a_taskbar_or_a_file_changes_nothing(self):
        self.assertIsNone(desktop.pin(ENTRY, self.layout, {}))
        self.layout.write_text("[Containments][1][Applets][2]\nplugin=org.kde.plasma.kickoff\n")
        self.assertIsNone(desktop.pin(ENTRY, self.layout, {}))
        self.assertEqual(self.layout.read_text(), "[Containments][1][Applets][2]\nplugin=org.kde.plasma.kickoff\n")

    def test_a_running_plasma_is_asked_and_its_file_left_alone(self):
        self.layout.write_text(LAYOUT)
        with mock.patch("nonsteamapps.desktop._through_plasma", return_value=(True, True)) as plasma:
            self.assertTrue(desktop.pin(ENTRY, self.layout, {}))
        plasma.assert_called_once_with(ENTRY, True, {})
        with mock.patch("nonsteamapps.desktop._through_plasma", return_value=(True, None)):
            self.assertIsNone(desktop.unpin(ENTRY, self.layout, {}))
        with mock.patch("nonsteamapps.desktop._through_plasma", return_value=(False, None)), \
                mock.patch("nonsteamapps.desktop.plasma_running", return_value=True):
            self.assertIsNone(desktop.pin(ENTRY, self.layout, {}))
        self.assertEqual(self.layout.read_text(), LAYOUT)

    def test_plasmas_script_keeps_its_defaults_and_reports_what_changed(self):
        script = desktop.script(ENTRY, True)
        self.assertIn(f'var entry = "{ENTRY}", add = true, defaults = ["applications:systemsettings.desktop", ', script)
        self.assertIn('var types = ["org.kde.plasma.taskmanager", "org.kde.plasma.icontasks"]', script)
        for call in ('panel.widgets(type)', 'widget.readConfig("launchers", defaults)', 'widget.writeConfig("launchers", launchers)',
                     "widget.reloadConfig()", "print(changed)"):
            self.assertIn(call, script)
        self.assertIn("add = false", desktop.script(ENTRY, False))

    def test_the_session_bus_carries_the_script_to_plasma(self):
        calls = []

        class Bus:
            def __init__(self, address, timeout):
                calls.append(("connect", address))

            def bus(self, member, signature="", body=b""):
                calls.append((member, body))
                return reply(struct.pack("<I", 1) if member == "NameHasOwner" else b"")

            def call(self, destination, path, interface, member, signature, body):
                calls.append((destination, path, interface, member, signature, body))
                return reply(bytes(appmenu.Writer().string("2").data))

            def close(self):
                calls.append(("close",))

        with mock.patch("nonsteamapps.desktop.appmenu.Connection", Bus):
            self.assertEqual(desktop._through_plasma(ENTRY, True, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/bus"}), (True, True))
        self.assertEqual(calls[0], ("connect", "/run/bus"))
        self.assertEqual(calls[2], ("NameHasOwner", bytes(appmenu.Writer().string("org.kde.plasmashell").data)))
        self.assertEqual(calls[3][:5], ("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript", "s"))
        self.assertEqual(calls[3][5], bytes(appmenu.Writer().string(desktop.script(ENTRY, True)).data))
        self.assertEqual(calls[-1], ("close",))
        self.assertEqual(desktop._through_plasma(ENTRY, True, {}), (False, None))


class RunningTests(unittest.TestCase):
    def test_only_this_users_plasmashell_counts_as_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            for pid, name in (("12", "konsole"), ("self", "plasmashell")):
                (proc / pid).mkdir()
                (proc / pid / "comm").write_text(name + "\n")
            self.assertFalse(desktop.plasma_running(proc))
            (proc / "34").mkdir()
            (proc / "34" / "comm").write_text("plasmashell\n")
            self.assertTrue(desktop.plasma_running(proc))
            with mock.patch("nonsteamapps.desktop.os.getuid", return_value=os.getuid() + 1):
                self.assertFalse(desktop.plasma_running(proc))


if __name__ == "__main__":
    unittest.main()
