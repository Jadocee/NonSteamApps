"""The apps NonSteamApps can install, and how each keeps separate data per Steam account."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import nx2
from .display import TV_HEIGHT
from .fsutil import atomic_write_bytes, atomic_write_json
from .layouts import BITWARDEN, BROWSER, ELEMENT, EMULATOR, FILES, JELLYFIN, LOCALSEND, MINECRAFT, SIGNAL, TOOLS, YOUTUBE
from .steam import STEAM_ID64_BASE

RunApp = Callable[[Sequence[str]], int]
_STEAM_PROFILE = re.compile(r"steam-\d+\Z")
VACUUMTUBE_SKIPPED = ("sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "hook")
VACUUMTUBE_SKIPS = tuple((f"sponsorblock_skip_{category}", True) for category in VACUUMTUBE_SKIPPED)
VACUUMTUBE_DEFAULTS = {
    "sponsorblock": True,
    **dict(VACUUMTUBE_SKIPS),
    "dearrow": True,
    "dislikes": True,
    "block_continue_watching": True,
    "hide_shorts": True,
    "features_enabled": True,
    "remaining_time_feature": True,
    "wayland_hdr": True,
    "userstyles": True,
}
CHANGES_FILE = "nonsteamapps.json"
USERSTYLES = "userstyles"


def _json(value: object) -> object:
    return list(value) if isinstance(value, tuple) else value


@dataclass(frozen=True)
class JsonSettings:
    """Values for one of an app's JSON settings files, at ``file`` in its data folder.

    ``new`` are further values a file NonSteamApps creates starts with. ``legacy`` is an older location of the
    file, used instead while ``file``'s folder does not exist and the older one's does, as the app itself does.
    """

    file: str
    values: Tuple[Tuple[str, object], ...]
    new: Tuple[Tuple[str, object], ...] = ()
    legacy: str = ""

    def target(self, folder: Path) -> Path:
        """The file the app reads its settings from in ``folder``."""
        current = Path(folder) / self.file
        if self.legacy and not current.parent.exists() and (Path(folder) / self.legacy).parent.exists():
            return Path(folder) / self.legacy
        return current

    def apply(self, folder: Path) -> Optional[bool]:
        """Write the values into the file, keeping its other settings; return whether it changed.

        Returns ``None``, and leaves the file alone, when it does not hold a JSON object: the app replaces such a file itself.
        """
        path = self.target(folder)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {key: _json(value) for key, value in self.new}
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        wanted = {key: _json(value) for key, value in self.values}
        if all(key in data and data[key] == value for key, value in wanted.items()):
            return False
        data.update(wanted)
        atomic_write_json(path, data)
        return True


def set_ini(lines: List[str], group: str, key: str, value: str) -> bool:
    """Set ``key`` in ``[group]`` of an INI file's lines; return whether they changed."""
    header, wanted = f"[{group}]", f"{key}={value}"
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, wanted])
        return True
    end = next((index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")), len(lines))
    for index in range(start + 1, end):
        name, separator, current = lines[index].partition("=")
        if separator and name.strip() == key:
            if current.strip() == value:
                return False
            lines[index] = wanted
            return True
    lines.insert(max(index for index in range(start, end) if lines[index].strip()) + 1, wanted)
    return True


@dataclass(frozen=True)
class IniSettings:
    """Values for one of an app's INI settings files, as Qt's QSettings and KDE's KConfig write them, at ``file`` in a folder.

    ``values`` are ``(group, key, value)``; the file's other groups, keys and comments stay as they are. ``new``
    are further values a file NonSteamApps creates starts with.
    """

    file: str
    values: Tuple[Tuple[str, str, str], ...]
    new: Tuple[Tuple[str, str, str], ...] = ()

    def target(self, folder: Path) -> Path:
        return Path(folder) / self.file

    def apply(self, folder: Path) -> Optional[bool]:
        """Write the values into the file, keeping the rest of it; return whether it changed.

        Returns ``None``, and leaves the file alone, when it cannot be read as text.
        """
        path = self.target(folder)
        fresh = False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines, fresh = [], True
        except (OSError, UnicodeDecodeError):
            return None
        wanted = [*self.values, *(self.new if fresh else ())]
        if not any([set_ini(lines, group, key, value) for group, key, value in wanted]):
            return False
        atomic_write_bytes(path, ("\n".join(lines) + "\n").encode("utf-8"))
        return True


def place_userstyles(source: Path, folder: Path, names: Sequence[str]) -> List[str]:
    """Copy the style sheets ``names`` from ``source`` into ``folder``'s ``userstyles``; return those written.

    A sheet is written only when it is missing or differs, so that VacuumTube, which watches the folder,
    reloads only what changed. Which sheets VacuumTube applies is its own setting, which is left alone.
    """
    written = []
    for name in names:
        content = (Path(source) / name).read_bytes()
        target = Path(folder) / USERSTYLES / name
        try:
            current = target.read_bytes()
        except OSError:
            current = None
        if current != content:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, content)
            written.append(name)
    return written


EDEN_GAME_LIST = "Paths\\gamedirs\\"
EDEN_BUILT_IN = ("SDMC", "UserNAND", "SysNAND")
EDEN_KEYS = "keys"
EDEN_KEY_FILES = ("prod.keys", "title.keys")
EDEN_FIRMWARE = "nand/system/Contents/registered"
FIRMWARE_RECORD = "nonsteamapps-firmware.json"


def add_game_folder(settings_file: Path, folder: Path, always: bool = False) -> bool:
    """Add ``folder`` to Eden's game list in ``settings_file`` while none of the folders added to it exists; return whether it was.

    With ``always``, ``folder`` is added wherever it is missing, beside the folders listed. Eden lists its SD card
    and NAND first, and adds them itself only to an empty list, so an empty list gets them as well. ``folder`` is
    scanned with its subfolders.
    """
    entries = dict(ini_entries(settings_file, "UI", EDEN_GAME_LIST))
    try:
        size = int(entries.get(f"{EDEN_GAME_LIST}size", "0").strip('"'))
    except ValueError:
        size = 0
    listed = [entries.get(f"{EDEN_GAME_LIST}{index}\\path", "").replace('"', "") for index in range(1, size + 1)]
    added = [path for path in listed if path and path not in EDEN_BUILT_IN]
    if str(folder) in added or (not always and any(Path(path).is_dir() for path in added)):
        return False
    values = [("UI", f"{EDEN_GAME_LIST}{index}\\path", name) for index, name in enumerate(EDEN_BUILT_IN, 1)] if not size else []
    index = (size or len(EDEN_BUILT_IN)) + 1
    values += [("UI", f"{EDEN_GAME_LIST}{index}\\path", str(folder)), ("UI", f"{EDEN_GAME_LIST}{index}\\deep_scan", "true"),
               ("UI", f"{EDEN_GAME_LIST}size", str(index))]
    return bool(IniSettings(Path(settings_file).name, tuple(values)).apply(Path(settings_file).parent))


def set_console_mode(settings_file: Path, docked: bool) -> bool:
    """Run Eden's console docked or handheld, in ``settings_file``; return whether that changed.

    A game's own console mode, in its properties, still takes precedence.
    """
    return write_eden_settings(settings_file, _eden_setting("System", "use_docked_mode", "1" if docked else "0"))


def write_eden_settings(settings_file: Path, values: Sequence[Tuple[str, str, str]]) -> bool:
    """Write ``(group, key, value)`` entries into Eden's ``settings_file``; return whether it changed."""
    return bool(IniSettings(Path(settings_file).name, tuple(values)).apply(Path(settings_file).parent))


def copy_keys(source: Path, target: Path) -> List[str]:
    """Copy the decryption keys in the folder ``source`` into ``target`` where they are missing or older; return the files copied.

    They are the keys from the user's own Switch, installed once in Eden, which Eden-NX2 would otherwise ask
    for at every start. A key file installed in ``target`` after it was copied there is newer, so it stays.
    """
    copied = []
    for name in EDEN_KEY_FILES:
        given, kept = Path(source) / name, Path(target) / name
        try:
            if not given.is_file() or (kept.is_file() and kept.stat().st_mtime_ns >= given.stat().st_mtime_ns):
                continue
            atomic_write_bytes(kept, given.read_bytes())
            os.chmod(kept, 0o600)
            stat = given.stat()
            os.utime(kept, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        except OSError:
            continue
        copied.append(name)
    return copied


_FIRMWARE_ENTRY = re.compile(r"(?i:.+\.nca|000000[0-9a-f]{2}|yuzu_meta)\Z")


def _size(path: Path) -> int:
    if not path.is_dir():
        return path.stat().st_size
    return sum(part.stat().st_size for part in sorted(path.rglob("*")) if part.is_file())


def _ncas(folder: Path) -> Dict[str, int]:
    """The contents of a NAND's ``registered`` folder, by name, with their sizes: NCAs, an NCA kept in parts as a folder,
    the ``000000XX`` folders the emulator installs single NCAs in, and its ``yuzu_meta`` folder."""
    found: Dict[str, int] = {}
    try:
        entries = sorted(Path(folder).iterdir())
    except OSError:
        return found
    for entry in entries:
        if not _FIRMWARE_ENTRY.match(entry.name):
            continue
        try:
            found[entry.name] = _size(entry)
        except OSError:
            continue
    return found


def _link_tree(source: Path, target: Path) -> None:
    """Hard-link the file ``source`` to ``target``, or copy it where it cannot be linked; a folder is linked file by file."""
    if source.is_dir():
        target.mkdir()
        for part in sorted(source.iterdir()):
            _link_tree(part, target / part.name)
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def share_firmware(source: Path, target: Path) -> int:
    """Give ``target`` the firmware installed in ``source`` while ``target`` holds none, or only what this gave it before; return the NCAs given.

    It is the firmware from the user's own Switch, installed once in Eden. Each NCA is named after its content, and
    the emulator deletes one before writing another in its place, so each file is hard-linked where both folders
    share a file system, and copied elsewhere. A record beside ``target`` keeps what was given, so that firmware
    installed in ``target`` itself stays, and a newer one in ``source`` replaces the copy. The firmware is put in
    place whole, by renaming a complete folder, or not at all.
    """
    source, target = Path(source), Path(target)
    given = _ncas(source)
    present = _ncas(target)
    record = target.parent / FIRMWARE_RECORD
    try:
        previous = json.loads(record.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, TypeError, KeyError):
        previous = None
    if not given or target.is_symlink() or present == given or (present and present != previous):
        return 0
    staging, retired = target.parent / f".{target.name}.nonsteamapps", target.parent / f".{target.name}.nonsteamapps-old"
    try:
        for leftover in (staging, retired):
            shutil.rmtree(leftover, ignore_errors=True)
        staging.mkdir(parents=True)
        for name in given:
            _link_tree(source / name, staging / name)
        if target.exists():
            os.rename(target, retired)
        try:
            os.rename(staging, target)
        except OSError:
            if retired.exists():
                os.rename(retired, target)
            raise
        for entry in sorted(retired.iterdir()) if retired.is_dir() else []:
            if entry.name not in present:
                os.rename(entry, target / entry.name)
        atomic_write_json(record, {"files": given})
    except OSError:
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
    return len(given)


def apply_changes(folder: Path, changes: Sequence[Tuple[str, Settings]]) -> List[str]:
    """Make each change not yet recorded in ``folder``'s ``nonsteamapps.json`` once; return the names made now.

    A change whose file cannot be read stays pending, so it is made at a later start instead.
    """
    if not changes:
        return []
    record = Path(folder) / CHANGES_FILE
    try:
        done = list(json.loads(record.read_text(encoding="utf-8"))["changes"])
    except (OSError, ValueError, TypeError, KeyError):
        done = []
    applied = [name for name, settings in changes if name not in done and settings.apply(folder) is not None]
    if applied:
        atomic_write_json(record, {"changes": done + applied})
    return applied


def ini_entries(path: Path, group: str, prefix: str) -> List[Tuple[str, str]]:
    """The keys of ``[group]`` in an INI file that start with ``prefix``, with their values as they are written."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    found, current = [], ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            continue
        key, separator, value = stripped.partition("=")
        if current == group and separator and key.startswith(prefix):
            found.append((key, value))
    return found


KYTY_GLOBAL = "GlobalConfiguration"
KYTY_PAD = tuple(f"Pad:{control}={source}" for control, source in (
    ("Cross", "South"), ("Circle", "East"), ("Square", "West"), ("Triangle", "North"), ("Options", "Start"),
    ("L3", "LeftStick"), ("R3", "RightStick"), ("L1", "LeftShoulder"), ("R1", "RightShoulder"),
    ("L2", "LeftTrigger"), ("R2", "RightTrigger"), ("Up", "DpadUp"), ("Down", "DpadDown"),
    ("Left", "DpadLeft"), ("Right", "DpadRight"), ("TouchPad", "Touchpad"), ("TouchPadRight", "Back"),
))
KYTY_GLOBAL_DEFAULTS = (
    ("present_mode", "Mailbox"), ("trophy_duration_seconds", "6"), ("shader_optimization_type", "Performance"),
    ("shader_log_folder", "_Shaders"), ("command_buffer_dump_folder", "_Buffers"), ("printf_output_file", "_kyty.txt"),
)


@dataclass(frozen=True)
class KytyGlobal:
    """Values for KytyPS5's global game settings in ``Kyty.ini``, each written while it is missing or still KytyPS5's default.

    ``values`` are ``(key, value, defaults)``, where ``defaults`` are how the launcher writes the key's default; an
    empty value counts as one too. The launcher reads its ``[GlobalConfiguration]`` group whole once it holds a key,
    and a key missing there becomes zero, so the defaults that are not zero go in with them.
    """

    values: Tuple[Tuple[str, str, Tuple[str, ...]], ...]
    file: str = "Kyty.ini"

    def target(self, folder: Path) -> Path:
        return Path(folder) / self.file

    def apply(self, folder: Path) -> Optional[bool]:
        """Write the values the user has not changed; return whether the file changed, or ``None`` if it cannot be read."""
        entries = dict(ini_entries(self.target(folder), KYTY_GLOBAL, ""))
        wanted = [(KYTY_GLOBAL, key, value) for key, value, defaults in self.values if entries.get(key, "").strip() in ("", *defaults)]
        if not wanted:
            return False
        values = [(KYTY_GLOBAL, key, value) for key, value in KYTY_GLOBAL_DEFAULTS if key not in entries]
        return IniSettings(self.file, (*values, *wanted)).apply(folder)


KYTY_GAMES = KytyGlobal((
    ("host_input_mapping", ", ".join(f'"{entry}"' for entry in KYTY_PAD), ("@Invalid()",)),
    ("screen_resolution", "1920x1080", ("1280x720",)),
))
Settings = Union[JsonSettings, IniSettings, KytyGlobal]
VACUUMTUBE_TV = JsonSettings(
    "config.json",
    (("fullscreen", True), ("no_window_decorations", True), ("disabled_tabs", ("shorts", "podcasts"))),
)
VACUUMTUBE_SETTINGS = JsonSettings("config.json", (*VACUUMTUBE_DEFAULTS.items(), *VACUUMTUBE_TV.values))
VACUUMTUBE_SEGMENTS = JsonSettings("config.json", tuple((f"sponsorblock_skip_{category}", True) for category in VACUUMTUBE_SKIPPED if category != "sponsor"))
VACUUMTUBE_STYLES = JsonSettings("config.json", (("userstyles", True),))
ELEMENT_CONSOLE = JsonSettings("electron-config.json", (("warnBeforeExit", False), ("autoHideMenuBar", True)))
ELEMENT_SETTINGS = JsonSettings("electron-config.json", (("minimizeToTray", False), *ELEMENT_CONSOLE.values))
LOCALSEND_SETTINGS = JsonSettings(
    "data/org.localsend.localsend_app/shared_preferences.json",
    (("flutter.ls_theme", "dark"), ("flutter.ls_color", "oled")),
    new=(("flutter.ls_whats_new", "1.18.2"),),
    legacy="data/localsend_app/shared_preferences.json",
)
BITWARDEN_SETTINGS = JsonSettings(
    "data.json",
    (("global_desktopSettings_runInBackground", False), ("global_desktopSettings_openAtLogin", False), ("global_theming_selection", "dark")),
)
KYTY_TV = IniSettings("Kyty.ini", (("MainDialog", "theme", "1"), ("Launcher", "grid_view", "true"), ("Launcher", "grid_icon_width", "256")))
KYTY_SETTINGS = IniSettings("Kyty.ini", (("MainDialog", "check_updates_on_startup", "false"), *KYTY_TV.values))
STEAM_VIRTUAL_GAMEPAD = "03000000de280000ff11000001000000"


def _eden_setting(group: str, key: str, value: str) -> Tuple[Tuple[str, str, str], ...]:
    return ((group, f"{key}\\default", "false"), (group, key, value))


def _eden_default(group: str, key: str, value: str) -> Tuple[Tuple[str, str, str], ...]:
    """A setting at Eden's own default, written as Eden writes it, so that Eden saving it changes nothing."""
    return ((group, f"{key}\\default", "true"), (group, key, value))


def _eden_pad(binding: str) -> str:
    return f'"engine:sdl,port:0,guid:{STEAM_VIRTUAL_GAMEPAD},{binding}"'


EDEN_TV = (
    *_eden_setting("UI", "fullscreen", "true"),
    *_eden_setting("UI", "confirmStop", "2"),
    *_eden_setting("UI", "gui_hide_backend_warning", "true"),
    *_eden_setting("UI", "theme", "colorful_dark"),
    *_eden_setting("UI", "UIGameList\\game_list_mode", "1"),
    *_eden_setting("UI", "UIGameList\\game_icon_size", "256"),
)
EDEN_CONTROLS = tuple(
    value
    for key, binding in (
        ("button_a", "button:1"), ("button_b", "button:0"), ("button_x", "button:3"), ("button_y", "button:2"),
        ("button_lstick", "button:9"), ("button_rstick", "button:10"), ("button_l", "button:4"), ("button_r", "button:5"),
        ("button_zl", "axis:2,threshold:0.5,invert:+"), ("button_zr", "axis:5,threshold:0.5,invert:+"),
        ("button_plus", "button:7"), ("button_minus", "button:6"), ("button_home", "button:8"),
        ("button_dleft", "hat:0,direction:left"), ("button_dup", "hat:0,direction:up"),
        ("button_dright", "hat:0,direction:right"), ("button_ddown", "hat:0,direction:down"),
        ("lstick", "axis_x:0,axis_y:1,offset_x:0.000000,offset_y:0.000000,invert_x:+,invert_y:+"),
        ("rstick", "axis_x:3,axis_y:4,offset_x:0.000000,offset_y:0.000000,invert_x:+,invert_y:+"),
    )
    for value in _eden_setting("Controls", f"player_0_{key}", _eden_pad(binding))
)
EDEN_SETTINGS = IniSettings("user/config/qt-config.ini", EDEN_TV, new=EDEN_CONTROLS)
EDEN_SHARED_SETTINGS = IniSettings("config/eden/qt-config.ini", EDEN_TV, new=EDEN_CONTROLS)
EDEN_GRAPHICS = (
    *_eden_default("Renderer", "backend", "1"),
    *_eden_default("Renderer", "vulkan_device", "0"),
)
NX2_GRAPHICS = (
    *EDEN_GRAPHICS,
    *_eden_default("Renderer", "accelerate_astc", "1"),
    *_eden_setting("Renderer", "astc_recompression", "2"),
)
LICHII_TV = (*EDEN_TV, *_eden_setting("UI", "check_for_updates", "false"))
LICHII_GRAPHICS = (
    *EDEN_GRAPHICS,
    *_eden_default("Renderer", "accelerate_astc", "1"),
    *_eden_default("Renderer", "astc_recompression", "2"),
)
PRISM_SETTINGS = IniSettings(
    "prismlauncher.cfg",
    tuple(("General", key, value) for key, value in (
        ("ApplicationTheme", "dark"),
        ("IconTheme", "flat_white"),
        ("CloseAfterLaunch", "true"),
        ("QuitAfterGameStop", "true"),
        ("LaunchMaximized", "true"),
    )),
)


@dataclass(frozen=True)
class FolderProfile:
    """Per-account data in a folder chosen with one command-line argument.

    ``defaults`` are files written into a data folder that does not have them yet, and ``settings`` are
    NonSteamApps' TV set-up, written into a folder without their files and put back by :meth:`reset`, which
    every install runs. Both reach the app's own ``shared`` folder too, used when accounts share data.
    ``changes`` are settings changed once in every data folder, new or existing, each under its own name.
    The names done are kept in the folder's ``nonsteamapps.json``, so a setting the user changes afterwards
    stays as they set it until the next install. ``links`` are folders each account's folder links to in the
    ``shared`` one, so that large downloads are kept once.
    """

    folder: str
    argument: str
    shared: str = ""
    defaults: Tuple[Tuple[str, str], ...] = ()
    settings: Tuple[Settings, ...] = ()
    changes: Tuple[Tuple[str, Settings], ...] = ()
    links: Tuple[str, ...] = ()

    def path(self, app_home: Path, account: int) -> Path:
        return Path(app_home) / self.folder.format(account=account)

    def data_folder(self, app_home: Path, account: Optional[int]) -> Optional[Path]:
        """The folder an account's data is in, or without one the shared folder."""
        if account:
            return self.path(app_home, account)
        return Path(app_home) / self.shared if self.shared else None

    def arguments(self, app_home: Path, account: int) -> List[str]:
        return [self.argument.format(folder=self.path(app_home, account), account=account)]

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*args, *self.arguments(app_home, account)]

    def run_options(self, app_home: Path, account: int) -> List[str]:
        return []

    def _seed(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in self.defaults:
            target = folder / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        for settings in self.settings:
            if not settings.target(folder).exists():
                settings.apply(folder)
        self._change(folder)

    def _change(self, folder: Path) -> None:
        apply_changes(folder, self.changes)

    def _link(self, folder: Path, shared: Path) -> None:
        for name in self.links:
            target, link = shared / name, folder / name
            target.mkdir(parents=True, exist_ok=True)
            if not link.exists() and not link.is_symlink():
                link.symlink_to(os.path.relpath(target, folder), target_is_directory=True)

    def prepare(self, app_home: Path, account: int, run_app: RunApp) -> bool:
        folder = self.path(app_home, account)
        self._seed(folder)
        if self.shared:
            self._link(folder, Path(app_home) / self.shared)
        return True

    def prepare_shared(self, app_home: Path) -> None:
        if self.shared and (self.defaults or self.settings or self.changes):
            self._seed(Path(app_home) / self.shared)

    def reset(self, app_home: Path, shared: bool = False) -> List[Path]:
        """Put the ``settings`` back in each account's data folder, and in the shared one while accounts share it; return the folders changed."""
        folders = self.existing(app_home)
        common = Path(app_home) / self.shared if self.shared else None
        if shared and common and common.is_dir():
            folders.append(common)
        changed = []
        for folder in folders:
            if any([settings.apply(folder) for settings in self.settings]):
                changed.append(folder)
            self._change(folder)
        return changed

    def existing(self, app_home: Path) -> List[Path]:
        pattern = re.compile(re.escape(Path(self.folder).name).replace(r"\{account\}", r"\d+") + r"\Z")
        parent = self.path(app_home, 0).parent
        if not parent.is_dir():
            return []
        return sorted(path for path in parent.iterdir() if path.is_dir() and pattern.match(path.name))


@dataclass(frozen=True)
class ScriptProfile(FolderProfile):
    """A folder handed to the app's own launch script in an environment variable (``argument`` is ``VAR={folder}``).

    ``flatpak run --env`` cannot set the XDG directories, because Flatpak sets them afterwards, so the
    script (``command``) starts through ``env`` inside the sandbox, after any ``fixed`` assignments.
    """

    command: str = ""
    fixed: Tuple[str, ...] = ()

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*self.arguments(app_home, account), *self.fixed, self.command, *args]

    def run_options(self, app_home: Path, account: int) -> List[str]:
        return ["--command=env"]


@dataclass(frozen=True)
class EnvProfile(FolderProfile):
    """A folder handed to the app in an environment variable that Flatpak passes on as it is (``argument`` is ``VAR={folder}``)."""

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return list(args)

    def run_options(self, app_home: Path, account: int) -> List[str]:
        return [f"--env={assignment}" for assignment in self.arguments(app_home, account)]


@dataclass(frozen=True)
class PortableProfile(FolderProfile):
    """Per-account data in a ``user`` folder in the app's working directory, in which the app then keeps everything, as Eden does.

    ``flatpak run --cwd`` starts the app in the account's folder; ``argument`` is unused. ``settings`` are files
    in that folder, and ``shared_settings`` the same settings at the app's own paths, for when accounts share
    its data. ``shared_links`` pair a path in the account's folder with one in the ``shared`` data folder, which
    it links to, so that games and what they need are kept once. ``carried`` are ``(group, key prefix)``
    entries that a new account's first settings file takes from the most recently saved of the other accounts'
    and the app's own: the settings that point at the shared games.
    """

    shared_settings: Tuple[IniSettings, ...] = ()
    shared_links: Tuple[Tuple[str, str], ...] = ()
    carried: Tuple[Tuple[str, str], ...] = ()

    def arguments(self, app_home: Path, account: int) -> List[str]:
        return []

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return list(args)

    def run_options(self, app_home: Path, account: int) -> List[str]:
        return [f"--cwd={self.path(app_home, account)}"]

    def prepare(self, app_home: Path, account: int, run_app: RunApp) -> bool:
        folder = self.path(app_home, account)
        first = self.settings[0] if self.settings else None
        fresh = first is not None and not first.target(folder).exists()
        self._seed(folder)
        shared = Path(app_home) / self.shared
        for name, target_name in self.shared_links:
            target, link = shared / target_name, folder / name
            target.mkdir(parents=True, exist_ok=True)
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.exists() and not link.is_symlink():
                link.symlink_to(os.path.relpath(target, link.parent), target_is_directory=True)
        if fresh and self.carried and isinstance(first, IniSettings):
            self._carry(Path(app_home), folder, first)
        return True

    def _carry(self, app_home: Path, folder: Path, settings: IniSettings) -> None:
        sources = [settings.target(other) for other in self.existing(app_home) if other != folder]
        sources += [shared.target(app_home) for shared in self.shared_settings[:1]]
        files = [source for source in sources if source.is_file()]
        if not files:
            return
        newest = max(files, key=lambda source: source.stat().st_mtime)
        values = tuple((group, key, value) for group, prefix in self.carried for key, value in ini_entries(newest, group, prefix))
        if values:
            IniSettings(settings.file, values).apply(folder)

    def prepare_shared(self, app_home: Path) -> None:
        for settings in self.shared_settings:
            if not settings.target(app_home).exists():
                settings.apply(app_home)

    def shared_path(self, app_home: Path, name: str) -> Path:
        """The folder ``name`` in the app's own data, which every account's folder links to."""
        return Path(app_home) / self.shared / name

    def settings_file(self, app_home: Path, account: Optional[int]) -> Optional[Path]:
        """The app's main settings file for ``account``, or the app's own when accounts share its data."""
        if account:
            return self.settings[0].target(self.path(app_home, account)) if self.settings else None
        return self.shared_settings[0].target(Path(app_home)) if self.shared_settings else None

    def reset(self, app_home: Path, shared: bool = False) -> List[Path]:
        """Put the ``settings`` back in each account's folder, and the ``shared_settings`` in the app's own data while accounts share it."""
        changed = [folder for folder in self.existing(app_home) if any([settings.apply(folder) for settings in self.settings])]
        if shared and any([settings.target(app_home).exists() and bool(settings.apply(app_home)) for settings in self.shared_settings]):
            changed.append(Path(app_home))
        return changed


@dataclass(frozen=True)
class JellyfinProfile:
    """Jellyfin Desktop's named profiles, which must exist before ``--profile`` can select one."""

    data: str = "data/jellyfin-desktop"
    cache: str = "cache/jellyfin-desktop"

    @staticmethod
    def name(account: int) -> str:
        return f"steam-{account}"

    def arguments(self, app_home: Path, account: int) -> List[str]:
        return [f"--profile={self.name(account)}"]

    def data_folder(self, app_home: Path, account: Optional[int]) -> Optional[Path]:
        return None

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*args, *self.arguments(app_home, account)]

    def run_options(self, app_home: Path, account: int) -> List[str]:
        return []

    def prepare_shared(self, app_home: Path) -> None:
        return None

    def reset(self, app_home: Path, shared: bool = False) -> List[Path]:
        """Jellyfin Desktop takes its TV layout from its arguments, so there is nothing to put back."""
        return []

    def profiles(self, app_home: Path) -> Dict[str, Path]:
        """Map profile names to their folders, as Jellyfin Desktop records them."""
        found: Dict[str, Path] = {}
        directory = Path(app_home) / self.data / "profiles"
        if not directory.is_dir():
            return found
        for folder in sorted(directory.iterdir()):
            try:
                name = json.loads((folder / "profile.json").read_text(encoding="utf-8")).get("name")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(name, str):
                found.setdefault(name, folder)
        return found

    def prepare(self, app_home: Path, account: int, run_app: RunApp) -> bool:
        name = self.name(account)
        if name in self.profiles(app_home):
            return True
        run_app(["--create-profile", name])
        return name in self.profiles(app_home)

    def existing(self, app_home: Path) -> List[Path]:
        folders = []
        for name, folder in self.profiles(app_home).items():
            if _STEAM_PROFILE.match(name):
                folders.append(folder)
                cache = Path(app_home) / self.cache / "profiles" / folder.name
                if cache.is_dir():
                    folders.append(cache)
        return folders


Profile = Union[FolderProfile, ScriptProfile, EnvProfile, PortableProfile, JellyfinProfile]


@dataclass(frozen=True)
class SystemApp:
    """An app SteamOS includes (``command``), started from Steam with a TV profile of its own.

    The profile gives the app its own ``XDG_CONFIG_HOME`` and ``XDG_STATE_HOME``. The desktop's settings stay
    readable underneath, through ``XDG_CONFIG_DIRS``, so the app keeps its look and file associations, but
    what it saves stays in the profile, as it does for the apps it opens. ``settings`` are written into the
    profile's config folder when their files are missing and put back by :meth:`reset`, ``shared`` files there
    are links to the desktop's own, and ``game_mode`` variables are set only in Game Mode.
    """

    command: str
    settings: Tuple[IniSettings, ...] = ()
    shared: Tuple[str, ...] = ()
    game_mode: Tuple[Tuple[str, str], ...] = ()

    def prepare(self, profile: Path, desktop_config: Path) -> None:
        config = Path(profile) / "config"
        for settings in self.settings:
            if not settings.target(config).exists():
                settings.apply(config)
        for name in self.shared:
            link, source = config / name, Path(desktop_config) / name
            if source.is_file() and not link.exists() and not link.is_symlink():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source)
        (Path(profile) / "state").mkdir(parents=True, exist_ok=True)

    def reset(self, profile: Path) -> bool:
        """Put the ``settings`` back in the profile once it exists; return whether it changed."""
        config = Path(profile) / "config"
        return config.is_dir() and any([settings.apply(config) for settings in self.settings])

    def environment(self, profile: Path, desktop_config: Path, environ: Mapping[str, str], game_mode: bool) -> Dict[str, str]:
        """The variables that start the app with its profile, layered over the desktop's settings."""
        variables = {
            "XDG_CONFIG_HOME": str(Path(profile) / "config"),
            "XDG_CONFIG_DIRS": ":".join([str(desktop_config), environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"]),
            "XDG_STATE_HOME": str(Path(profile) / "state"),
        }
        if game_mode:
            variables.update(self.game_mode)
        return variables


@dataclass(frozen=True)
class Release:
    """An app NonSteamApps downloads itself from its project's GitHub releases, as it does for KytyPS5 (see :mod:`kyty`).

    Each Steam account runs it from a folder of its own, where it keeps its data. ``settings`` are written there
    when their files are missing and put back by every install; ``changes`` are made once in folders that
    already exist, as :attr:`FolderProfile.changes` are.
    """

    settings: Tuple[IniSettings, ...] = ()
    changes: Tuple[Tuple[str, IniSettings], ...] = ()


@dataclass(frozen=True)
class Browser:
    """An app that runs in NonSteamApps' own Helium: the browser itself, or one site full screen (kiosk).

    ``account_url``, with ``{steam_id}`` in it, opens in place of ``url`` when Steam starts the app for an account.
    ``extensions`` are folders of NonSteamApps' ``share/extensions`` that the app loads beside the focus outline.
    ``profile`` names a folder of Helium profiles, one for each Steam account, that the apps naming it share, as
    Proton Mail and Proton Calendar do, whose single sign-on works within one browser profile; an app without one
    has its own. ``manifest`` is a web app manifest the site publishes without naming it in ``url``'s page, read for
    the site's icons as well.
    """

    url: str = ""
    kiosk: bool = False
    account_url: str = ""
    extensions: Tuple[str, ...] = ()
    profile: str = ""
    manifest: str = ""

    def start_url(self, account: Optional[int]) -> str:
        """The page to open: ``account_url`` with ``account``'s SteamID64, or ``url`` when there is no account."""
        if self.account_url and account:
            return self.account_url.format(steam_id=STEAM_ID64_BASE + account)
        return self.url


@dataclass(frozen=True)
class TvScale:
    """How an app takes its TV scale: a command-line ``argument`` with ``{factor}`` in it, or an environment ``variable``.

    A ``whole`` scale is rounded down, and dropped below 2, for toolkits that only scale by whole numbers; a
    ``text`` variable then scales the text by what is left over, as ``GDK_DPI_SCALE`` does for GTK. ``layout``
    is the screen height the app's layout is made for, which the automatic scale fits a TV to. ``requires``
    are settings the app needs while it is scaled, set before each scaled start.
    """

    argument: str = ""
    variable: str = ""
    whole: bool = False
    text: str = ""
    layout: int = TV_HEIGHT
    requires: Optional[JsonSettings] = None

    def _text(self, factor: float) -> Optional[str]:
        value = float(int(factor)) if self.whole else factor
        return None if self.whole and value < 2 else f"{value:g}"

    def apply(self, factor: float) -> Tuple[List[str], List[str]]:
        """Return the app's arguments and ``flatpak run`` options for this scale."""
        text = self._text(factor)
        arguments = [self.argument.format(factor=text)] if self.argument and text else []
        return arguments, [f"--env={name}={value}" for name, value in self.variables(factor).items()]

    def variables(self, factor: float) -> Dict[str, str]:
        """The environment variables this scale sets, which ``apply`` passes to Flatpak."""
        text = self._text(factor)
        found = {self.variable: text} if self.variable and text else {}
        rest = factor / (int(factor) if text and self.whole else 1)
        if self.text and rest > 1:
            found[self.text] = f"{round(rest, 2):g}"
        return found


CHROMIUM_SCALE = TvScale(argument="--force-device-scale-factor={factor}")


@dataclass(frozen=True)
class DesktopEntry:
    """How an app appears in Desktop Mode's applications menu, where an install also pins it to Plasma's taskbar (see :mod:`desktop`).

    A Helium app with an ``own`` entry gets the desktop file of that name in Helium's release, with the release's
    ``icon``, so that Desktop Mode starts Helium itself, as Helium's own entry does, rather than NonSteamApps'
    launcher. ``generic`` and ``categories`` describe the entry NonSteamApps writes otherwise.
    """

    generic: str = ""
    categories: Tuple[str, ...] = ()
    own: str = ""
    icon: str = ""


@dataclass(frozen=True)
class App:
    """An app NonSteamApps adds to Steam: from Flathub (``flatpak``), in its own Helium (``browser``), one SteamOS includes
    (``system``), one it downloads from its project's releases (``release``), a Flatpak it builds on this machine
    from its project's source (``from_source``), as it does for Eden-NX2 (see :mod:`nx2`), which then runs as
    a Flathub app does, or an ``appimage`` it downloads from its project's releases, as it does for Lichii (see
    :mod:`lichii`), which keeps its data per account in NonSteamApps' profiles, laid out as Eden's.

    ``controller`` names the controller layout to give the shortcut, one of Valve's or one of
    :mod:`layouts`. ``tv_scale`` says how a Flathub or system app is scaled for a TV in Game Mode, as the
    Helium apps always are. ``sandbox_off_when`` names
    environment variables that make the app turn Chromium's sandbox off; the launcher hides them when
    the user chooses to keep the sandbox. ``notice`` is shown after installing. ``ports`` are opened in
    the firewall, when one is running, so other devices can reach the app.

    For a Flathub app, ``env`` is set for every start from Steam and ``game_mode_env`` for starts in Game
    Mode. ``command`` is the program in the Flatpak to run in place of its own, as Winetricks is in Flathub's
    Wine; ``branch`` is the branch to install where Flathub publishes several; and ``icon`` names the app's own
    icon inside the Flatpak, where it is not the one Flatpak exports. An ``x11`` app is given X11 for every
    start from Steam, even where Flatpak would give it only Wayland (see :func:`flatpak.x11_options`); its
    ``env`` chooses X11 for its toolkit. ``settings`` are
    NonSteamApps' TV set-up in the app's own folder, for an app without data per account: written when
    missing and put back by every install. ``libraries`` gives the app's sandbox
    every Steam library folder, such as one on an SD card, for an app that works on Steam's games.
    ``callbacks`` are the link schemes through which a browser hands a sign-in back to the app; in Game Mode
    such an app's links open in Helium, in front of it, and the callbacks come back to it (see :mod:`links`).
    A ``qt_window`` app's first window is given the screen's size in Game Mode with ``-qwindowgeometry``:
    gamescope sizes only full-screen windows to the screen and ignores requests to maximise. In Game Mode,
    the windows of ``fullscreen_class`` (their ``WM_CLASS``) are asked to be full screen instead (see
    :mod:`x11`), and a ``hide_menu_bar`` app runs with NonSteamApps standing in for the desktop's global
    menu, which its sandbox may then talk to, so that Electron draws no menu bar in its window (see
    :mod:`appmenu`). ``userstyles`` are style
    sheets from NonSteamApps' ``share/userstyles``, copied at every start into the ``userstyles`` folder of
    the data folder the app runs with, where VacuumTube loads them (see :func:`place_userstyles`). ``games`` are
    folders in the home folder for an app's games, created at every start and opened to its sandbox, read-only,
    for that run; Eden's game list gets one while no folder added to it exists (see :func:`add_game_folder`), or,
    ``games_listed``, each wherever it is missing, as Lichii's gets the Switch and Switch 2 libraries it shares
    with Eden and Eden-NX2.
    A ``console_mode`` app emulates a console that runs docked or handheld, which each start chooses
    (see :func:`set_console_mode`). An app with a ``desktop`` entry is added to Desktop Mode's applications menu
    and its taskbar at install, for use outside Game Mode. ``graphics`` are an emulator's graphics settings for
    SteamOS's hardware, written into its settings file at every start (see :func:`write_eden_settings`), so that
    a fallback the emulator saved after one failed start does not stay. An emulator with ``keys_from`` takes
    the decryption keys installed in that app at every start, where its own are missing or older (see
    :func:`copy_keys`), and one with ``firmware_from`` the firmware installed there, while it has none of its
    own (see :func:`share_firmware`).
    """

    id: str
    name: str
    client: str
    summary: str
    flatpak: str = ""
    browser: Optional[Browser] = None
    system: Optional[SystemApp] = None
    release: Optional[Release] = None
    args: Tuple[str, ...] = ()
    profile: Optional[Profile] = None
    controller: str = ""
    logo_position: str = "BottomLeft:42:58"
    tv_scale: Optional[TvScale] = None
    sandbox_off_when: Tuple[str, ...] = ()
    notice: str = ""
    ports: Tuple[str, ...] = ()
    env: Tuple[Tuple[str, str], ...] = ()
    game_mode_env: Tuple[Tuple[str, str], ...] = ()
    x11: bool = False
    settings: Tuple[Settings, ...] = ()
    libraries: bool = False
    callbacks: Tuple[str, ...] = ()
    qt_window: bool = False
    fullscreen_class: str = ""
    hide_menu_bar: bool = False
    userstyles: Tuple[str, ...] = ()
    games: Tuple[str, ...] = ()
    games_listed: bool = False
    console_mode: bool = False
    graphics: Tuple[Tuple[str, str, str], ...] = ()
    keys_from: str = ""
    firmware_from: str = ""
    desktop: Optional[DesktopEntry] = None
    from_source: bool = False
    appimage: bool = False
    command: str = ""
    branch: str = ""
    icon: str = ""

    @property
    def profiles_name(self) -> str:
        """The folder of NonSteamApps' profiles that holds the app's data: the one its Helium profiles are shared in, or its own."""
        return self.browser.profile if self.browser and self.browser.profile else self.id

    @property
    def ref(self) -> str:
        """What ``flatpak install`` and ``flatpak uninstall`` are given: the app's ID, on its ``branch`` where it has one."""
        return f"{self.flatpak}//{self.branch}" if self.branch else self.flatpak

    def home(self, user_home: Path) -> Path:
        """The app's own folder, which Flatpak keeps in ``~/.var/app``."""
        return Path(user_home) / ".var" / "app" / self.flatpak

    def arguments(self, user_home: Path, account: Optional[int]) -> List[str]:
        if self.profile and account:
            return self.profile.wrap(self.home(user_home), account, self.args)
        return list(self.args)

    def run_options(self, user_home: Path, account: Optional[int]) -> List[str]:
        """Options for ``flatpak run`` itself, before the app ID."""
        if self.profile and account:
            return self.profile.run_options(self.home(user_home), account)
        return [f"--command={self.command}"] if self.command else []


EDEN_SHARED_LINKS = (
    ("user/keys", EDEN_KEYS),
    ("user/nand/system/Contents/registered", "nand/system/Contents/registered"),
    ("user/nand/user/Contents/registered", "nand/user/Contents/registered"),
    ("user/load", "load"),
    ("user/shader", "shader"),
)
EDEN_CARRIED = (("UI", "Paths\\gamedirs\\"), ("UI", "Paths\\external_content_dirs\\"))
EDEN_PROFILE = PortableProfile(
    "data/eden-steam-{account}",
    "",
    shared="data/eden",
    settings=(EDEN_SETTINGS,),
    shared_settings=(EDEN_SHARED_SETTINGS,),
    shared_links=EDEN_SHARED_LINKS,
    carried=EDEN_CARRIED,
)
LICHII_PROFILE = PortableProfile(
    "{account}",
    "",
    shared="shared/user",
    settings=(IniSettings("user/config/qt-config.ini", LICHII_TV, new=EDEN_CONTROLS),),
    shared_settings=(IniSettings("shared/user/config/qt-config.ini", LICHII_TV, new=EDEN_CONTROLS),),
    shared_links=EDEN_SHARED_LINKS,
    carried=EDEN_CARRIED,
)

APPS: Tuple[App, ...] = (
    App(
        id="youtube",
        name="YouTube",
        client="VacuumTube",
        flatpak="rocks.shy.VacuumTube",
        summary="YouTube's TV interface with ad blocking, SponsorBlock, DeArrow and dislike counts",
        args=("--fullscreen",),
        profile=FolderProfile(
            "config/VacuumTube-steam-{account}",
            "--portable={folder}",
            shared="config/VacuumTube",
            settings=(VACUUMTUBE_SETTINGS,),
            changes=(("2.11.0", VACUUMTUBE_TV), ("2.21.0", VACUUMTUBE_SEGMENTS), ("2.22.0", VACUUMTUBE_STYLES)),
        ),
        controller=YOUTUBE.title,
        userstyles=("nonsteamapps-steamos.css",),
        tv_scale=TvScale(
            argument="--force-device-scale-factor={factor}",
            layout=1080,
            requires=JsonSettings("config.json", (("unlock_resolution", True),)),
        ),
        sandbox_off_when=("SteamGamepadUI",),
    ),
    App(
        id="element",
        name="Element",
        client="Element Desktop",
        flatpak="im.riot.Riot",
        summary="Secure chat on Matrix, set up for a TV and a controller",
        args=("--password-store=basic", "--storage-mode=allow-plaintext", "--enable-spatial-navigation"),
        controller=ELEMENT.title,
        profile=FolderProfile(
            "config/Element-steam-{account}",
            "--profile=steam-{account}",
            settings=(ELEMENT_SETTINGS,),
            changes=(("2.34.0", ELEMENT_CONSOLE),),
        ),
        logo_position="BottomLeft:44:56",
        tv_scale=CHROMIUM_SCALE,
        callbacks=("io.element.desktop", "element"),
        fullscreen_class="element",
        hide_menu_bar=True,
    ),
    App(
        id="signal",
        name="Signal",
        client="Signal Desktop",
        flatpak="org.signal.Signal",
        summary="Private messages and calls, linked to Signal on your phone, set up for a TV and a controller",
        args=("--enable-spatial-navigation",),
        controller=SIGNAL.title,
        profile=ScriptProfile(
            "config/Signal-steam-{account}",
            "XDG_CONFIG_HOME={folder}",
            defaults=(("Signal/config.json", "{}\n"),),
            command="signal-desktop",
            fixed=("SIGNAL_PASSWORD_STORE=basic",),
        ),
        logo_position="BottomLeft:44:56",
        tv_scale=CHROMIUM_SCALE,
        fullscreen_class="signal",
        hide_menu_bar=True,
        notice="Signal keeps its database key unencrypted on disk, as Flathub's Signal does by default; see the README",
    ),
    App(
        id="bitwarden",
        name="Bitwarden",
        client="Bitwarden",
        flatpak="com.bitwarden.desktop",
        summary="Your Bitwarden password vault, set up for a TV and a controller",
        args=("--enable-spatial-navigation",),
        profile=EnvProfile(
            "config/Bitwarden-steam-{account}",
            "BITWARDEN_APPDATA_DIR={folder}",
            shared="config/Bitwarden",
            settings=(BITWARDEN_SETTINGS,),
        ),
        controller=BITWARDEN.title,
        logo_position="BottomLeft:44:56",
        tv_scale=CHROMIUM_SCALE,
        env=(("ACCESS_TOKEN_LOCATION", "DISK"),),
        game_mode_env=(("DISPLAY_MODE", "X11"),),
        callbacks=("bitwarden",),
        fullscreen_class="bitwarden",
        hide_menu_bar=True,
        notice="Bitwarden keeps its login tokens unencrypted on disk, so that it works without a keyring; see the README",
    ),
    App(
        id="jellyfin",
        name="Jellyfin",
        client="Jellyfin Desktop",
        flatpak="org.jellyfin.JellyfinDesktop",
        summary="Your Jellyfin media server's films, shows and music, in its TV layout",
        args=("--tv", "--fullscreen"),
        profile=JellyfinProfile(),
        controller=JELLYFIN.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(argument="--scale-factor={factor}"),
    ),
    App(
        id="localsend",
        name="LocalSend",
        client="LocalSend",
        flatpak="org.localsend.localsend_app",
        summary="Send files to and from nearby phones and computers over your own network",
        controller=LOCALSEND.title,
        logo_position="BottomLeft:44:56",
        ports=("53317/tcp", "53317/udp"),
        tv_scale=TvScale(variable="GDK_SCALE", whole=True),
        settings=(LOCALSEND_SETTINGS,),
    ),
    App(
        id="prism",
        name="Prism Launcher",
        client="Prism Launcher",
        flatpak="org.prismlauncher.PrismLauncher",
        summary="Minecraft: Java Edition, with instances, mods and modpacks, set up for a TV and a controller",
        profile=FolderProfile(
            "data/PrismLauncher-steam-{account}",
            "--dir={folder}",
            shared="data/PrismLauncher",
            settings=(PRISM_SETTINGS,),
            links=("assets", "libraries", "java"),
        ),
        controller=MINECRAFT.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        game_mode_env=(("QT_QPA_PLATFORM", "xcb"),),
        qt_window=True,
        notice="Prism Launcher asks for a language and the Microsoft account that owns Minecraft on its first start, once for each Steam account",
    ),
    App(
        id="eden",
        name="Eden",
        client="Eden",
        flatpak="dev.eden_emu.eden",
        summary="Nintendo Switch games you own, through the Eden emulator, set up for a TV and a controller",
        args=("-f",),
        profile=EDEN_PROFILE,
        controller=EMULATOR.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        env=(("QT_QPA_PLATFORM", "xcb"),),
        x11=True,
        qt_window=True,
        games=("Games/Switch",),
        console_mode=True,
        graphics=EDEN_GRAPHICS,
        notice="Eden plays only games you own, with the keys and firmware from your own Switch; install them once, from Eden in Desktop Mode",
    ),
    App(
        id="edennx2",
        name="Eden-NX2",
        client="Eden-NX2",
        flatpak=nx2.APP_ID,
        from_source=True,
        summary="Switch 2 games you own, through Eden-NX2's early Switch 2 support, built here from its official source and set up for a TV and a controller",
        args=("-f",),
        profile=EDEN_PROFILE,
        controller=EMULATOR.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        env=(("QT_QPA_PLATFORM", "xcb"),),
        x11=True,
        qt_window=True,
        games=("Games/Switch2",),
        console_mode=True,
        graphics=NX2_GRAPHICS,
        keys_from="eden",
        notice="Eden-NX2 is early work, and few Switch 2 games start: copy each one you own, dumped as a folder holding its exefs and romfs, "
               "into ~/Games/Switch2. It is built here, so nonsteamapps update builds its newest source, which can take an hour",
    ),
    App(
        id="lichii",
        name="Lichii",
        client="Lichii",
        appimage=True,
        summary="Switch and Switch 2 games you own, through the Lichii emulator, which builds on Eden, set up for a TV and a controller",
        args=("-f",),
        profile=LICHII_PROFILE,
        controller=EMULATOR.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        env=(("QT_QPA_PLATFORM", "xcb"),),
        qt_window=True,
        games=("Games/Switch", "Games/Switch2"),
        games_listed=True,
        console_mode=True,
        graphics=LICHII_GRAPHICS,
        keys_from="eden",
        firmware_from="eden",
        notice="Lichii is early work and plays only games you own: Switch games in ~/Games/Switch, which Eden reads too, and Switch 2 games "
               "in ~/Games/Switch2, dumped as Eden-NX2 reads them or as .nup packages, which only Lichii reads. "
               "It takes the keys and firmware installed in Eden, and updates with `nonsteamapps update`, not every week",
    ),
    App(
        id="kytyps5",
        name="KytyPS5",
        client="KytyPS5",
        summary="PlayStation 5 games you own, run natively through the KytyPS5 translation layer, which is early work: many games do not run yet",
        release=Release(settings=(KYTY_SETTINGS,), changes=(("2.23.0", KYTY_TV), ("2.25.0", KYTY_GAMES))),
        controller=EMULATOR.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        game_mode_env=(("QT_QPA_PLATFORM", "xcb"), ("SDL_VIDEO_DRIVER", "x11")),
        fullscreen_class="nonsteamapps-kytyps5",
        notice="KytyPS5 plays only games you own, copied from your own console; it updates with `nonsteamapps update`, not every week",
    ),
    App(
        id="protonup",
        name="ProtonUp-Qt",
        client="ProtonUp-Qt",
        flatpak="net.davidotek.pupgui2",
        summary="Install and update GE-Proton and other compatibility tools for Steam, set up for a TV and a controller",
        controller=TOOLS.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
        env=(("PUPGUI2_DISABLE_GAMEPAD", "1"),),
        game_mode_env=(("QT_QPA_PLATFORM", "xcb"),),
        qt_window=True,
        settings=(IniSettings("config/pupgui/config.ini", (("pupgui2", "theme", "steam"),)),),
        libraries=True,
        notice="Steam lists the compatibility tools ProtonUp-Qt installs once Steam restarts; choose one in a game's Properties ▸ Compatibility",
    ),
    App(
        id="protontricks",
        name="Protontricks",
        client="Protontricks",
        flatpak="com.github.Matoking.protontricks",
        summary="Install Windows components and fixes into a Proton game's prefix, set up for a TV and a controller",
        args=("--no-term", "--gui"),
        controller=TOOLS.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="GDK_SCALE", whole=True, text="GDK_DPI_SCALE"),
        game_mode_env=(("GDK_BACKEND", "x11"),),
        libraries=True,
        notice="Protontricks lists the Proton games started at least once; pick a game, then what to install into its prefix",
    ),
    App(
        id="winetricks",
        name="Winetricks",
        client="Winetricks",
        flatpak="org.winehq.Wine",
        branch="stable",
        command="winetricks",
        icon="winetricks",
        summary="Install Windows components, fonts and fixes into Wine prefixes, with Flathub's Wine, set up for a TV and a controller",
        controller=TOOLS.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="GDK_SCALE", whole=True, text="GDK_DPI_SCALE"),
        game_mode_env=(("GDK_BACKEND", "x11"),),
        notice="Winetricks works on the Wine prefixes of Flathub's Wine, in ~/.var/app/org.winehq.Wine/data; "
               "for Steam games and other Proton games, use Protontricks",
    ),
    App(
        id="files",
        name="Files",
        client="Dolphin",
        summary="Browse and open your files with SteamOS's file manager, set up for a TV and a controller",
        system=SystemApp(
            command="dolphin",
            settings=(
                IniSettings("dolphinrc", (
                    ("General", "RememberOpenedTabs", "false"),
                    ("General", "ConfirmClosingMultipleTabs", "false"),
                    ("General", "BrowseThroughArchives", "true"),
                    ("MainWindow", "MenuBar", "Disabled"),
                    ("IconsMode", "PreviewSize", "96"),
                    ("PlacesPanel", "IconSize", "32"),
                )),
                IniSettings("kdeglobals", (("KDE", "SingleClick", "true"),)),
            ),
            shared=("user-dirs.dirs", "user-dirs.locale"),
            game_mode=(("QT_QPA_PLATFORM", "xcb"), ("QT_QPA_PLATFORMTHEME", "kde")),
        ),
        args=("--new-window",),
        qt_window=True,
        controller=FILES.title,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
    ),
    App(
        id="helium",
        name="Helium",
        client="Helium",
        summary="A private, ad-blocking web browser, set up for a TV and a controller",
        browser=Browser(),
        controller=BROWSER.title,
        desktop=DesktopEntry(generic="Web Browser", categories=("Network", "WebBrowser"), own="helium.desktop", icon="product_logo_256.png"),
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="primevideo",
        name="Prime Video",
        client="Helium",
        summary="Prime Video's films and series, full screen in Helium",
        browser=Browser(url="https://www.primevideo.com/", kiosk=True),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="hbomax",
        name="HBO Max",
        client="Helium",
        summary="HBO Max's series and films, full screen in Helium",
        browser=Browser(url="https://www.hbomax.com/", kiosk=True),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="netflix",
        name="Netflix",
        client="Helium",
        summary="Netflix's series and films, full screen in Helium",
        browser=Browser(url="https://www.netflix.com/", kiosk=True),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="disneyplus",
        name="Disney+",
        client="Helium",
        summary="Disney+'s films and series, full screen in Helium",
        browser=Browser(url="https://www.disneyplus.com/", kiosk=True),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="protondb",
        name="ProtonDB",
        client="Helium",
        summary="Player reports on how well games run with Proton, full screen in Helium",
        browser=Browser(
            url="https://www.protondb.com/",
            kiosk=True,
            account_url="https://www.protondb.com/dashboard/{steam_id}?nonsteamapps=library",
            extensions=("protondb",),
        ),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="steamdb",
        name="SteamDB",
        client="Helium",
        summary="Steam's prices, sales, player counts and update history, full screen in Helium",
        browser=Browser(
            url="https://steamdb.info/",
            kiosk=True,
            account_url="https://steamdb.info/#nonsteamapps={steam_id}",
            extensions=("steamdb",),
            manifest="https://steamdb.info/steamdb.webmanifest",
        ),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="protonmail",
        name="Proton Mail",
        client="Helium",
        summary="Proton's end-to-end encrypted email, full screen in Helium",
        browser=Browser(url="https://mail.proton.me/", kiosk=True, profile="proton"),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="protoncalendar",
        name="Proton Calendar",
        client="Helium",
        summary="Proton's end-to-end encrypted calendar, full screen in Helium",
        browser=Browser(url="https://calendar.proton.me/", kiosk=True, profile="proton"),
        controller=BROWSER.title,
        logo_position="BottomLeft:44:56",
    ),
)


def sharing_profiles(app: App) -> Tuple[App, ...]:
    """The other apps that share ``app``'s Helium profiles."""
    if not (app.browser and app.browser.profile):
        return ()
    return tuple(other for other in APPS if other is not app and other.browser and other.browser.profile == app.browser.profile)


def by_id(app_id: str) -> App:
    for app in APPS:
        if app.id == app_id.strip().lower():
            return app
    raise KeyError(app_id)


def ids() -> List[str]:
    return [app.id for app in APPS]
