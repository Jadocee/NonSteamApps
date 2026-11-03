import re
import subprocess
import unittest
from unittest import mock

import _paths  # noqa: F401
from nonsteamapps import steamclient

OVERLAY_32 = "/home/deck/.local/share/Steam/ubuntu12_32/gameoverlayrenderer.so"
OVERLAY_64 = "/home/deck/.local/share/Steam/ubuntu12_64/gameoverlayrenderer.so"
RUNTIME = "/home/deck/.local/share/Steam/ubuntu12_32/steam-runtime/usr/lib/x86_64-linux-gnu"
COMMANDS = {"steam": "/usr/bin/steam", "systemd-run": "/usr/bin/systemd-run"}
XDG_DESKTOP_PORTAL_SCOPE = re.compile(r"^app-(?:[A-Za-z0-9]+-)?(.+?)(?:-[A-Za-z0-9]*)(?:\.scope|\.slice)$")


class SteamEnvironmentTests(unittest.TestCase):
    def test_steams_overlay_and_runtime_paths_are_removed(self):
        environ = {
            "LD_PRELOAD": f"{OVERLAY_32}:{OVERLAY_64} /usr/lib/mangohud/libMangoHud.so",
            "LD_LIBRARY_PATH": RUNTIME,
            "SYSTEM_LD_LIBRARY_PATH": "",
            "PATH": "/home/deck/.local/share/Steam/ubuntu12_32/steam-runtime/usr/bin:/usr/bin",
            "SYSTEM_PATH": "/usr/local/bin:/usr/bin",
        }
        self.assertTrue(steamclient.leave_steam_environment(environ))
        self.assertEqual(
            environ,
            {
                "LD_PRELOAD": "/usr/lib/mangohud/libMangoHud.so",
                "SYSTEM_LD_LIBRARY_PATH": "",
                "PATH": "/usr/local/bin:/usr/bin",
                "SYSTEM_PATH": "/usr/local/bin:/usr/bin",
            },
        )

    def test_a_proton_prefix_from_steam_is_dropped(self):
        environ = {"STEAM_COMPAT_DATA_PATH": "/home/deck/.local/share/Steam/steamapps/compatdata/1245620", "PATH": "/usr/bin"}
        self.assertTrue(steamclient.leave_steam_environment(environ))
        self.assertEqual(environ, {"PATH": "/usr/bin"})

    def test_the_systems_own_library_path_comes_back(self):
        environ = {"LD_PRELOAD": OVERLAY_64, "LD_LIBRARY_PATH": f"{RUNTIME}:/opt/lib", "SYSTEM_LD_LIBRARY_PATH": "/opt/lib"}
        self.assertTrue(steamclient.leave_steam_environment(environ))
        self.assertEqual(environ, {"LD_LIBRARY_PATH": "/opt/lib", "SYSTEM_LD_LIBRARY_PATH": "/opt/lib"})

    def test_outside_steam_nothing_changes(self):
        environ = {"LD_LIBRARY_PATH": "/opt/lib", "PATH": "/usr/bin"}
        self.assertFalse(steamclient.leave_steam_environment(environ))
        self.assertEqual(environ, {"LD_LIBRARY_PATH": "/opt/lib", "PATH": "/usr/bin"})


class SteamStartTests(unittest.TestCase):
    def start(self, commands=COMMANDS, probe=0):
        outcome = probe if isinstance(probe, BaseException) else subprocess.CompletedProcess([], probe)
        with mock.patch("nonsteamapps.steamclient.shutil.which", side_effect=commands.get), \
                mock.patch("nonsteamapps.steamclient.subprocess.run", side_effect=[outcome]) as run, \
                mock.patch("nonsteamapps.steamclient.subprocess.Popen") as popen, \
                mock.patch("nonsteamapps.steamclient.ui.log"):
            steamclient.start()
        popen.assert_called_once()
        return run, popen.call_args

    def test_steam_starts_in_its_own_unit_which_portals_identify_as_steam(self):
        run, call = self.start()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--", "true"])
        args = call.args[0]
        unit = args[4].partition("--unit=")[2]
        self.assertEqual(
            args[:4] + args[5:],
            ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--slice=app.slice", "--", "/usr/bin/steam", "-silent"],
        )
        self.assertRegex(unit, r"^app-steam-[0-9a-f]{32}\.scope$")
        self.assertEqual(XDG_DESKTOP_PORTAL_SCOPE.match(unit).group(1), "steam")
        self.assertEqual(XDG_DESKTOP_PORTAL_SCOPE.match("app-org.kde.konsole-2a1d6e0f.scope").group(1), "org.kde.konsole")
        self.assertTrue(call.kwargs["start_new_session"])

    def test_without_a_user_service_manager_steam_starts_directly(self):
        for commands, probe in (
            ({"steam": "/usr/bin/steam"}, 0),
            (COMMANDS, 1),
            (COMMANDS, subprocess.TimeoutExpired("systemd-run", steamclient.UNIT_TIMEOUT)),
            (COMMANDS, OSError("systemd-run")),
        ):
            with self.subTest(commands=sorted(commands), probe=probe):
                _, call = self.start(commands, probe)
                self.assertEqual(call.args[0], ["/usr/bin/steam", "-silent"])

    def test_each_start_gets_a_unit_of_its_own(self):
        units = set()
        for _ in range(2):
            _, call = self.start()
            units.add(call.args[0][4])
        self.assertEqual(len(units), 2)


class SteamStopTests(unittest.TestCase):
    def test_without_a_terminal_steam_is_closed_only_when_told_to(self):
        with mock.patch("nonsteamapps.steamclient.running", return_value=True), \
                mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=False), \
                mock.patch("nonsteamapps.ui.open", side_effect=OSError("no terminal"), create=True), \
                mock.patch("nonsteamapps.steamclient._detach") as detach, \
                mock.patch.object(steamclient.ui, "assume_yes", False):
            with self.assertRaises(steamclient.ui.Abort) as raised:
                steamclient.stop("nonsteamapps update")
        self.assertIn("Steam was left running", str(raised.exception))
        detach.assert_not_called()
        with mock.patch("nonsteamapps.steamclient.running", side_effect=[True, False]), \
                mock.patch("nonsteamapps.steamclient.in_game_mode", return_value=False), \
                mock.patch("nonsteamapps.steamclient.command", return_value="/usr/bin/steam"), \
                mock.patch("nonsteamapps.steamclient._detach") as detach, \
                mock.patch("nonsteamapps.steamclient.time.sleep"), \
                mock.patch("nonsteamapps.steamclient.ui.log"), \
                mock.patch.object(steamclient.ui, "assume_yes", True):
            self.assertTrue(steamclient.stop("nonsteamapps update"))
        detach.assert_called_once_with(["/usr/bin/steam", "-shutdown"])


if __name__ == "__main__":
    unittest.main()
