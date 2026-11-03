"""Test doubles: fake flatpak, firewall-cmd and sudo commands, and a throwaway home with Steam and a NonSteamApps program folder."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import _paths
from nonsteamapps import controllers, firewall, steam, vdf
from nonsteamapps.config import Paths

FAKES = Path(__file__).resolve().parent / "fakes"
ALPHA, BETA = 111, 222


class FakeFlatpak:
    def __init__(self, directory: Path, installed=None):
        self.state = directory / "flatpak.json"
        self.log = directory / "flatpak.log"
        self.state.write_text(json.dumps({"apps": installed or {}}))
        self.command = str(FAKES / "flatpak")
        self.env = {"FAKE_FLATPAK_STATE": str(self.state), "FAKE_FLATPAK_LOG": str(self.log)}

    def calls(self, command=None):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        calls = [json.loads(line) for line in lines]
        return [call for call in calls if command is None or call[0] == command]

    def apps(self):
        return json.loads(self.state.read_text())["apps"]


class FakeFirewall:
    """firewalld as seen through tests/fakes/firewall-cmd, with tests/fakes/sudo in front of changes."""

    def __init__(self, directory: Path, running: bool = False):
        self.state = directory / "firewall.json"
        self.log = directory / "firewall.log"
        self.env = {"FAKE_FIREWALL_STATE": str(self.state), "FAKE_FIREWALL_LOG": str(self.log)}
        self.set(running)

    def set(self, running: bool = True, active=("public",)):
        self.state.write_text(json.dumps({"running": running, "default": "public", "active": list(active), "runtime": {}, "permanent": {}}))

    def ports(self, zone="public", permanent=True):
        state = json.loads(self.state.read_text())
        return sorted(state.get("permanent" if permanent else "runtime", {}).get(zone, []))

    def changes(self):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [call for call in map(json.loads, lines) if any("-port=" in argument and "query" not in argument for argument in call)]

    def firewall(self):
        return firewall.Firewall(str(FAKES / "firewall-cmd"), str(FAKES / "sudo"))


USER_COLLECTIONS = [
    ["user-collections.favorite", {"key": "user-collections.favorite", "timestamp": 1700000000,
                                   "value": '{"id":"favorite","name":"","added":[570],"removed":[]}', "version": "12",
                                   "conflictResolutionMethod": "custom", "strMethodId": "union-collections"}],
    ["user-collections.uc-rpg", {"key": "user-collections.uc-rpg", "timestamp": 1700000000,
                                 "value": '{"id":"uc-rpg","name":"RPGs","added":[292030],"removed":[]}', "version": "13",
                                 "conflictResolutionMethod": "custom", "strMethodId": "union-collections"}],
]


def make_cloud_storage(root: Path, account: int, namespace: int = 1) -> Path:
    """Steam's collections file for an account, holding Favourites and one collection of the user's own."""
    directory = root / "userdata" / str(account) / "config" / "cloudstorage"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cloud-storage-namespaces.json").write_text(json.dumps([[1, "0"], [namespace, "798"]]))
    path = directory / f"cloud-storage-namespace-{namespace}.json"
    path.write_text(json.dumps(USER_COLLECTIONS))
    return path


def make_steam(home: Path, accounts=(ALPHA, BETA)) -> Path:
    root = home / ".local/share/Steam"
    for account in accounts:
        (root / "userdata" / str(account) / "config").mkdir(parents=True)
        make_cloud_storage(root, account)
    users = "".join(
        f'"{steam.STEAM_ID64_BASE + account}" {{ "AccountName" "u{account}" "PersonaName" "P{account}" '
        f'"MostRecent" "{1 if account == accounts[0] else 0}" }}\n'
        for account in accounts
    )
    (root / "config").mkdir(parents=True)
    (root / "config/loginusers.vdf").write_text(f'"users"\n{{\n{users}}}\n')
    return root


WEB_BROWSER = [
    ("switch", "switches", {
        "button_escape": ["key_press ESCAPE"],
        "button_menu": ["key_press LEFT_CONTROL, ⛔", "key_press W"],
        "left_bumper": ["mouse_button BACK, ◀️"],
        "right_bumper": ["mouse_button FORWARD, ▶️"],
        "button_back_left": ["mouse_button MIDDLE"],
        "button_back_right": ["key_press LEFT_CONTROL"],
        "button_capture": ["controller_action system_key_1"],
        "always_on_action": ["controller_action ts_n"],
    }),
    ("button_diamond", "four_buttons", {
        "button_a": ["key_press RETURN, ⏯️", "key_press SPACE"],
        "button_b": ["mouse_button BACK, ◀️"],
        "button_x": ["controller_action SHOW_KEYBOARD, ⌨️"],
        "button_y": ["mouse_button FORWARD, ▶️", "key_press S"],
    }),
    ("joystick", "dpad", {"dpad_north": ["mouse_wheel SCROLL_UP, ⏫"], "dpad_south": ["mouse_wheel SCROLL_DOWN, ⏬"]}),
    ("left_trackpad", "dpad", {}, False),
    ("left_trackpad", "scrollwheel", {"scroll_clockwise": ["mouse_wheel SCROLL_UP"]}),
    ("right_trackpad", "absolute_mouse", {"click": ["mouse_button LEFT"]}),
    ("left_trigger", "trigger", {"edge": ["mouse_button RIGHT"]}),
    ("right_trigger", "trigger", {"edge": ["mouse_button LEFT"]}),
    ("gyro", "mouse_joystick", {}, False),
    ("dpad", "dpad", {
        "dpad_north": ["key_press UP_ARROW, ⏫"],
        "dpad_south": ["key_press DOWN_ARROW, ⏬"],
        "dpad_east": ["key_press RIGHT_ARROW, ⏩"],
        "dpad_west": ["key_press LEFT_ARROW, ⏪"],
    }),
    ("right_joystick", "joystick_mouse", {"click": ["mouse_button LEFT"]}),
]


WASD = [
    ("switch", "switches", {
        "button_escape": ["key_press ESCAPE"],
        "button_menu": ["key_press TAB"],
        "left_bumper": ["mouse_wheel SCROLL_DOWN"],
        "right_bumper": ["mouse_wheel SCROLL_UP"],
    }),
    ("button_diamond", "four_buttons", {
        "button_a": ["key_press SPACE"],
        "button_b": ["key_press E"],
        "button_x": ["key_press R"],
        "button_y": ["key_press F"],
    }),
    ("left_trackpad", "dpad", {"dpad_north": ["key_press 1"]}),
    ("right_trackpad", "absolute_mouse", {"click": ["mouse_button LEFT"]}),
    ("joystick", "dpad", {"dpad_north": ["key_press W"], "dpad_west": ["key_press A"], "click": ["key_press LEFT_SHIFT"]}),
    ("left_trigger", "trigger", {"edge": ["mouse_button RIGHT"]}),
    ("right_trigger", "trigger", {"edge": ["mouse_button LEFT"]}),
    ("right_joystick", "joystick_mouse", {"click": ["mouse_button LEFT"]}),
    ("dpad", "dpad", {"dpad_north": ["key_press UP_ARROW"]}),
]

def gamepad_groups(switch_inputs, trackpads=False):
    """The groups of a Valve Gamepad layout for a controller with these ``switch`` inputs."""
    groups = [
        ("switch", "switches", {name: [f"xinput_button {name}"] for name in switch_inputs}),
        ("button_diamond", "four_buttons", {f"button_{key}": [f"xinput_button {key.upper()}"] for key in "abxy"}),
        ("joystick", "joystick_move", {}),
        ("left_trigger", "trigger", {}),
        ("right_trigger", "trigger", {}),
        ("right_joystick", "joystick_move", {}),
        ("dpad", "dpad", {"dpad_north": ["xinput_button dpad_up"]}),
    ]
    if trackpads:
        groups[2:2] = [("left_trackpad", "single_button", {}), ("right_trackpad", "single_button", {})]
    return groups


def controller_layout(kind, title, groups, settings=(("left_trackpad_mode", "0"),)):
    """A layout in Valve's format; each group is ``(source, mode, {input: [binding…]}[, active])``."""
    mappings = [
        ("version", "3"),
        ("title", "#Title"),
        ("controller_type", kind),
        ("localization", [("english", [("Title", title)])]),
    ]
    sources = []
    for index, (source, mode, inputs, *active) in enumerate(groups):
        pairs = [
            (name, [("activators", [("Full_Press", [("bindings", [("binding", binding) for binding in bindings])])])])
            for name, bindings in inputs.items()
        ]
        mappings.append(("group", [("id", str(index)), ("mode", mode), ("inputs", pairs), ("settings", [("requires_click", "0")])]))
        sources.append((str(index), f"{source} {'active' if not active or active[0] else 'inactive'}"))
    mappings.append(("preset", [("id", "0"), ("name", "Default"), ("group_source_bindings", sources)]))
    mappings.append(("settings", [tuple(setting) for setting in settings]))
    return vdf.dumps_pairs([("controller_mappings", mappings)])


XBOX_SWITCH = ("button_escape", "button_menu", "left_bumper", "right_bumper", "button_capture")
DECK_SWITCH = ("button_escape", "button_menu", "left_bumper", "right_bumper", "button_back_left", "button_back_right")


def add_controller_templates(root: Path) -> Path:
    """Valve's Web Browser and WASD layouts for the Deck, and Gamepad layouts for the Deck, an Xbox controller and touch."""
    folder = controllers.templates_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "controller_neptune_webbrowser.vdf").write_text("\ufeff" + controller_layout("controller_neptune", "Web Browser", WEB_BROWSER), encoding="utf-8")
    (folder / "controller_neptune_wasd.vdf").write_text(
        "\ufeff" + controller_layout("controller_neptune", "Keyboard (WASD) and Mouse", WASD), encoding="utf-8"
    )
    (folder / "controller_neptune_gamepad_joystick.vdf").write_text(
        controller_layout("controller_neptune", "Gamepad", gamepad_groups(DECK_SWITCH, trackpads=True)), encoding="utf-8"
    )
    (folder / "controller_xboxone_gamepad_joystick.vdf").write_text(
        controller_layout("controller_xboxone", "Gamepad", gamepad_groups(XBOX_SWITCH), settings=(("xbox", "1"),)), encoding="utf-8"
    )
    (folder / "controller_mobile_touch_gamepad_joystick.vdf").write_text(
        controller_layout("controller_mobile_touch", "Gamepad", gamepad_groups(("button_escape",))), encoding="utf-8"
    )
    return folder


def make_program(directory: Path) -> Path:
    shutil.copytree(_paths.ROOT / "src" / "share", directory / "share")
    shutil.copytree(_paths.ROOT / "assets" / "artwork", directory / "artwork")
    (directory / "lib" / "nonsteamapps").mkdir(parents=True)
    (directory / "lib" / "nonsteamapps" / "__init__.py").write_text("")
    (directory / "bin").mkdir()
    (directory / "bin" / "nonsteamapps").write_text("#!/bin/sh\n")
    return directory


def make_paths(home: Path) -> Paths:
    return Paths.detect(make_program(home / ".local/share/nonsteamapps"), {"HOME": str(home)})


def make_legacy(home: Path, root: Path, shared_sign_in: bool = False):
    """A SteamOS YT installation with its shortcut in every account; returns the old shortcut's app ID."""
    program = home / ".local/share/steamos-yt"
    (program / "bin").mkdir(parents=True)
    (program / "lib").mkdir()
    (program / "profiles" / str(ALPHA)).mkdir(parents=True)
    (program / "bin" / "steamos-yt").write_text("#!/bin/sh\n")
    (program / "lib" / "common.sh").write_text("")
    settings = home / ".config/steamos-yt"
    settings.mkdir(parents=True)
    (settings / "steamos-yt.conf").write_text(f"YT_PROFILE_PER_STEAM_ACCOUNT={0 if shared_sign_in else 1}\n")
    spec = steam.ShortcutSpec(
        name="YouTube",
        exe=str(program / "bin" / "steamos-yt"),
        start_dir=str(program),
        launch_options=f"--steam-account {steam.ACCOUNT_PLACEHOLDER}",
    )
    [first, *_] = steam.add_shortcut(root, steam.account_ids(root), spec)
    return first.appid


def environment(home: Path, flatpak: FakeFlatpak, extra_path: str = "", wall: "FakeFirewall" = None) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("XDG_")}
    env.update(flatpak.env, HOME=str(home), NO_COLOR="1", NONSTEAMAPPS_ALLOW_ROOT="1")
    if wall:
        env.update(wall.env)
    if extra_path:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    return env


def make_helium_archive(directory: Path, version: str = "0.0.0.1") -> Path:
    """A Helium-shaped release archive whose wrapper records its arguments in $FAKE_HELIUM_LOG and its LD_PRELOAD in $FAKE_HELIUM_ENV_LOG.

    With $FAKE_HELIUM_OPEN, the wrapper then opens that link with xdg-open from its PATH, as a page sending a
    sign-in back to an app would, and stays open until it is ended.
    """
    staging = directory / f"build-{version}"
    inner = staging / f"helium-{version}-x86_64_linux"
    inner.mkdir(parents=True)
    (inner / "helium").write_text("#!/bin/sh\n")
    (inner / "helium-wrapper").write_text(
        '#!/usr/bin/env python3\nimport json, os, sys\n'
        'log = os.environ.get("FAKE_HELIUM_LOG")\n'
        'if log:\n    open(log, "a").write(json.dumps(sys.argv[1:]) + "\\n")\n'
        'env_log = os.environ.get("FAKE_HELIUM_ENV_LOG")\n'
        'if env_log:\n    open(env_log, "a").write(os.environ.get("LD_PRELOAD", "<unset>") + "\\n")\n'
        'if os.environ.get("FAKE_HELIUM_OPEN"):\n'
        '    import subprocess, time\n'
        '    subprocess.run(["xdg-open", os.environ["FAKE_HELIUM_OPEN"]], check=True)\n'
        '    time.sleep(15)\n'
    )
    for name in ("helium", "helium-wrapper"):
        (inner / name).chmod(0o755)
    archive = directory / f"helium-{version}-x86_64_linux.tar.xz"
    subprocess.run(["tar", "-cJf", str(archive), "-C", str(staging), inner.name], check=True)
    return archive
