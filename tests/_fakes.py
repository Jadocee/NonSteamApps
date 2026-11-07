"""Test doubles: fake flatpak, steam, firewall-cmd and sudo commands, and a throwaway home with Steam and a NonSteamApps program folder."""

import json
import os
import shutil
import subprocess
import time
from typing import Optional
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

    def state_value(self, key):
        return json.loads(self.state.read_text()).get(key)


class FakeSteam:
    """The steam command as tests/fakes/steam stands in for it, recording what is sent to a running Steam."""

    def __init__(self, directory: Path):
        self.log = directory / "steam.log"
        self.command = str(FAKES / "steam")
        self.env = {"FAKE_STEAM_LOG": str(self.log)}

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def statuses(self, timeout: float = 5.0, count: int = 0):
        """The ``steam://friends/status`` commands sent so far, waiting up to ``timeout`` for ``count`` of them."""
        deadline = time.monotonic() + timeout
        while True:
            found = [call[-1].rsplit("/", 1)[-1] for call in self.calls() if call and call[-1].startswith("steam://friends/status/")]
            if len(found) >= count or time.monotonic() > deadline:
                return found
            time.sleep(0.05)


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
    ("right_trackpad", "absolute_mouse", {"click": ("Soft_Press", ["mouse_button LEFT"])}),
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
    ("right_trackpad", "absolute_mouse", {"click": ("Soft_Press", ["mouse_button LEFT"])}),
    ("joystick", "dpad", {"dpad_north": ["key_press W"], "dpad_west": ["key_press A"], "click": ["key_press LEFT_SHIFT"]}),
    ("left_trigger", "trigger", {"edge": ["mouse_button RIGHT"]}),
    ("right_trigger", "trigger", {"edge": ["mouse_button LEFT"]}),
    ("right_joystick", "joystick_mouse", {"click": ["mouse_button LEFT"]}),
    ("dpad", "dpad", {"dpad_north": ["key_press UP_ARROW"]}),
]

GAMEPAD_BUTTONS = {"button_escape": "start", "button_menu": "select"}


def gamepad_groups(switch_inputs, trackpads=False):
    """The groups of a Valve Gamepad layout for a controller with these ``switch`` inputs.

    As in Valve's, ``button_escape``, the Menu button, presses the gamepad's Start, and ``button_menu``, the View
    button, its Select.
    """
    groups = [
        ("switch", "switches", {name: [f"xinput_button {GAMEPAD_BUTTONS.get(name, name)}"] for name in switch_inputs}),
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
    """A layout in Valve's format; each group is ``(source, mode, {input: [binding…]}[, active])``.

    An input's bindings are on a full press, or on the activator named first, as ``("Soft_Press", [binding…])``,
    as Valve binds a trackpad's press.
    """
    mappings = [
        ("version", "3"),
        ("title", "#Title"),
        ("controller_type", kind),
        ("localization", [("english", [("Title", title)])]),
    ]
    sources = []
    for index, (source, mode, inputs, *active) in enumerate(groups):
        pairs = [
            (name, [("activators", [(activator, [("bindings", [("binding", binding) for binding in bindings])])])])
            for name, (activator, bindings) in ((name, value if isinstance(value, tuple) else ("Full_Press", value)) for name, value in inputs.items())
        ]
        mappings.append(("group", [("id", str(index)), ("mode", mode), ("inputs", pairs), ("settings", [("requires_click", "0")])]))
        sources.append((str(index), f"{source} {'active' if not active or active[0] else 'inactive'}"))
    mappings.append(("preset", [("id", "0"), ("name", "Default"), ("group_source_bindings", sources)]))
    mappings.append(("settings", [tuple(setting) for setting in settings]))
    return vdf.dumps_pairs([("controller_mappings", mappings)])


XBOX_SWITCH = ("button_escape", "button_menu", "left_bumper", "right_bumper", "button_capture")
DECK_SWITCH = ("button_escape", "button_menu", "left_bumper", "right_bumper", "button_back_left", "button_back_right")


def add_controller_templates(root: Path) -> Path:
    """Valve's Web Browser, WASD and Gamepad with Mouse Trackpad layouts for the Deck, and Gamepad layouts for the Deck, an Xbox controller and touch."""
    folder = controllers.templates_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "controller_neptune_webbrowser.vdf").write_text("\ufeff" + controller_layout("controller_neptune", "Web Browser", WEB_BROWSER), encoding="utf-8")
    (folder / "controller_neptune_wasd.vdf").write_text(
        "\ufeff" + controller_layout("controller_neptune", "Keyboard (WASD) and Mouse", WASD), encoding="utf-8"
    )
    (folder / "controller_neptune_gamepad_joystick.vdf").write_text(
        controller_layout("controller_neptune", "Gamepad", gamepad_groups(DECK_SWITCH, trackpads=True)), encoding="utf-8"
    )
    (folder / "controller_neptune_gamepad+mouse.vdf").write_text(
        controller_layout("controller_neptune", "Gamepad with Mouse Trackpad", [
            *gamepad_groups(DECK_SWITCH),
            ("left_trackpad", "dpad", {"dpad_north": ["xinput_button dpad_up"]}),
            ("right_trackpad", "absolute_mouse", {"click": ("Soft_Press", ["xinput_button JOYSTICK_RIGHT"])}),
        ]), encoding="utf-8"
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


def environment(home: Path, flatpak: FakeFlatpak, extra_path: str = "", wall: "FakeFirewall" = None) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("XDG_", "DBUS_"))}
    env.update(flatpak.env, HOME=str(home), NO_COLOR="1", NONSTEAMAPPS_ALLOW_ROOT="1")
    if wall:
        env.update(wall.env)
    if extra_path:
        env["PATH"] = f"{extra_path}{os.pathsep}{env.get('PATH', '')}"
    return env


KYTY_TAG = "KytyPS5-2026-11-02-dfec14a"
LICHII_TAG = "build-83"
NX2_COMMIT = "50fa86bbbc403ad565eb44fcc281f16f77c69e15"
NX2_NEWER = "c0ffee00d15ea5e0123456789abcdef012345678"


def make_kyty_build(directory: Path) -> Path:
    """A folder laid out like KytyPS5's Linux build, whose programs record what they were started with in $FAKE_KYTY_LOG.

    Like KytyPS5's launcher, the fake launcher runs the emulator through $TERMINAL with ``-e``, in the
    emulator's own folder, from a shell that waits for a key, and ignores how that ends; the fake emulator
    writes a save and downloaded game content there.
    """
    directory.mkdir(parents=True)
    (directory / "kyty_launcher").write_text(
        "#!/usr/bin/env python3\nimport json, os, subprocess, sys\n"
        "here = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
        "record = {\"argv\": sys.argv[1:], \"cwd\": os.getcwd(), \"folder\": here,\n"
        "          \"env\": {name: os.environ.get(name, \"\") for name in (\"TERMINAL\", \"RESOURCE_NAME\", \"SDL_APP_ID\", \"QT_QPA_PLATFORM\", \"QT_SCALE_FACTOR\")},\n"
        "          \"settings\": open(\"Kyty.ini\").read() if os.path.exists(\"Kyty.ini\") else None}\n"
        "log = os.environ.get(\"FAKE_KYTY_LOG\")\n"
        "if log:\n    open(log, \"a\").write(json.dumps(record) + \"\\n\")\n"
        "terminal = os.environ.get(\"TERMINAL\")\n"
        "if terminal and os.environ.get(\"FAKE_KYTY_PLAY\"):\n"
        "    command = ['bash', '-c', '\"$@\"; echo Press any key...; read -n1', 'kyty', os.path.join(here, 'kyty_emulator'), '--game', os.environ['FAKE_KYTY_PLAY']]\n"
        "    subprocess.run([terminal, '-e', *command], cwd=here, timeout=20, check=False)\n"
    )
    (directory / "kyty_emulator").write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "log = os.environ.get(\"FAKE_KYTY_LOG\")\n"
        "if log:\n    open(log, \"a\").write(json.dumps({\"emulator\": sys.argv[1:], \"cwd\": os.getcwd()}) + \"\\n\")\n"
        "os.makedirs(os.path.join(\"_SaveData\", \"PPSA00000\"), exist_ok=True)\n"
        "os.makedirs(os.path.join(\"_DownloadData\", \"PPSA00000\"), exist_ok=True)\n"
    )
    (directory / "kyty_updater").write_text("#!/bin/sh\nexit 1\n")
    for name in ("kyty_launcher", "kyty_emulator", "kyty_updater"):
        (directory / name).chmod(0o755)
    (directory / "lib").mkdir()
    (directory / "lib" / "libQt6Core.so.6").write_text("")
    (directory / "plugins" / "platforms").mkdir(parents=True)
    (directory / "plugins" / "platforms" / "libqxcb.so").write_text("")
    (directory / "qt.conf").write_text("[Paths]\nPlugins = plugins\n")
    return directory


def make_kyty_archive(directory: Path, tag: str = KYTY_TAG) -> Path:
    """A KytyPS5 Linux build archive, packed as KytyPS5's release workflow packs it (``tar -C build -czf … .``)."""
    build = make_kyty_build(directory / f"kyty-build-{tag}")
    archive = directory / f"{tag}-Linux-x86_64.tar.gz"
    subprocess.run(["tar", "-C", str(build), "-czf", str(archive), "."], check=True)
    return archive


def appimage_stub(script: Path) -> bytes:
    """A tiny x86-64 Linux program with the AppImage mark that runs ``script`` with its own arguments, where it was started.

    It stands in for an AppImage: ``lea`` the script's path, then ``execve(path, argv, envp)`` and, if that fails, ``exit(127)``.
    """
    import struct
    path = str(script).encode() + b"\0"
    code = (bytes.fromhex("488d3d") + struct.pack("<i", 33)
            + bytes.fromhex("488d742408" "488b0424" "488d54c410" "b83b000000" "0f05" "bf7f000000" "b83c000000" "0f05"))
    base, start = 0x400000, 64 + 56
    size = start + len(code) + len(path)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"AI\x02" + bytes(5)
    header = ident + struct.pack("<HHIQQQIHHHHHH", 2, 0x3E, 1, base + start, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    program = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, size, size, 0x1000)
    return header + program + code + path


def make_lichii_appimage(directory: Path, name: str = "lichii-linux-x86_64-pgo.AppImage") -> Path:
    """A stand-in for Lichii's AppImage that records where and how it was started, as JSON, in $FAKE_LICHII_LOG."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"{name}.py"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "record = {\"argv\": sys.argv[1:], \"cwd\": os.getcwd(), \"portable\": os.path.isdir(\"user\"),\n"
        "          \"env\": {name: os.environ.get(name, \"\") for name in (\"QT_QPA_PLATFORM\", \"QT_SCALE_FACTOR\")}}\n"
        "log = os.environ.get(\"FAKE_LICHII_LOG\")\n"
        "if log:\n    open(log, \"a\").write(json.dumps(record) + \"\\n\")\n"
    )
    script.chmod(0o755)
    appimage = directory / name
    appimage.write_bytes(appimage_stub(script))
    appimage.chmod(0o755)
    return appimage


def lichii_release(appimage: Path, tag: str = LICHII_TAG, published: str = "2026-11-05T08:00:00Z", digest: Optional[str] = None) -> dict:
    """GitHub's description of a Lichii prerelease whose PGO AppImage is ``appimage``."""
    import hashlib
    base = f"https://github.com/zortos293/Lichii/releases/download/{tag}"
    name = "lichii-linux-x86_64-pgo.AppImage"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": True,
        "published_at": published,
        "assets": [
            {"name": "lichii-linux-x86_64.AppImage", "browser_download_url": f"{base}/lichii-linux-x86_64.AppImage", "size": 1, "digest": "sha256:" + "0" * 64},
            {"name": name, "browser_download_url": f"{base}/{name}", "size": appimage.stat().st_size,
             "digest": digest or "sha256:" + hashlib.sha256(appimage.read_bytes()).hexdigest()},
        ],
    }


def kyty_release(archive: Path, tag: str = KYTY_TAG, published: str = "2026-11-02T08:00:00Z", digest: Optional[str] = None) -> dict:
    """GitHub's description of a KytyPS5 release whose Linux build is ``archive``."""
    import hashlib
    name = f"{tag}-Linux-x86_64.tar.gz"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": published,
        "assets": [
            {"name": f"{tag}-Windows-x64.zip", "browser_download_url": f"https://github.com/KytyPS5/KytyPS5/releases/download/{tag}/{tag}-Windows-x64.zip",
             "size": 1, "digest": "sha256:" + "0" * 64},
            {"name": name, "browser_download_url": f"https://github.com/KytyPS5/KytyPS5/releases/download/{tag}/{name}",
             "size": archive.stat().st_size, "digest": digest or "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()},
        ],
    }


HELIUM_DESKTOP = """[Desktop Entry]
Version=1.0
Name=Helium

# Only KDE 4 seems to use GenericName, so we reuse the KDE strings.
GenericName=Web Browser
GenericName[de]=Web-Browser
Comment=Access the Internet
Exec=helium %U
StartupNotify=true
Terminal=false
Icon=helium
Type=Application
Categories=Network;WebBrowser;
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
Actions=new-window;new-private-window;

[Desktop Action new-window]
Name=New Window
Exec=helium

[Desktop Action new-private-window]
Name=New Incognito Window
Exec=helium --incognito
"""


def make_helium_archive(directory: Path, version: str = "0.0.0.1", own_entry: bool = True) -> Path:
    """A Helium-shaped release archive whose wrapper records its arguments in $FAKE_HELIUM_LOG, its LD_PRELOAD in $FAKE_HELIUM_ENV_LOG
    and its GTK_IM_MODULE in $FAKE_HELIUM_INPUT_LOG. Started headless with a DevTools pipe, it is ``fakes/devtools`` instead.

    With $FAKE_HELIUM_OPEN, the wrapper then opens that link with xdg-open from its PATH, as a page sending a
    sign-in back to an app would, and stays open until it is ended. With ``own_entry``, it ships Helium's
    desktop file and icon, as Helium's releases do.
    """
    staging = directory / f"build-{version}"
    inner = staging / f"helium-{version}-x86_64_linux"
    inner.mkdir(parents=True)
    (inner / "helium").write_text("#!/bin/sh\n")
    devtools = Path(__file__).resolve().parent / "fakes" / "devtools"
    (inner / "helium-wrapper").write_text(
        '#!/usr/bin/env python3\nimport json, os, sys\n'
        'if "--remote-debugging-pipe" in sys.argv:\n'
        f'    os.execv({str(devtools)!r}, [{str(devtools)!r}, *sys.argv[1:]])\n'
        'log = os.environ.get("FAKE_HELIUM_LOG")\n'
        'if log:\n    open(log, "a").write(json.dumps(sys.argv[1:]) + "\\n")\n'
        'env_log = os.environ.get("FAKE_HELIUM_ENV_LOG")\n'
        'if env_log:\n    open(env_log, "a").write(os.environ.get("LD_PRELOAD", "<unset>") + "\\n")\n'
        'input_log = os.environ.get("FAKE_HELIUM_INPUT_LOG")\n'
        'if input_log:\n    open(input_log, "a").write(os.environ.get("GTK_IM_MODULE", "<unset>") + "\\n")\n'
        'if os.environ.get("FAKE_HELIUM_OPEN"):\n'
        '    import subprocess, time\n'
        '    subprocess.run(["xdg-open", os.environ["FAKE_HELIUM_OPEN"]], check=True)\n'
        '    time.sleep(15)\n'
    )
    for name in ("helium", "helium-wrapper"):
        (inner / name).chmod(0o755)
    if own_entry:
        (inner / "helium.desktop").write_text(HELIUM_DESKTOP)
        (inner / "product_logo_256.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    archive = directory / f"helium-{version}-x86_64_linux.tar.xz"
    subprocess.run(["tar", "-cJf", str(archive), "-C", str(staging), inner.name], check=True)
    return archive
