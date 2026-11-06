"""The TV's remote: keep the daemons that read it over HDMI-CEC from typing more than the remote means.

Current SteamOS reads the remote with Valve's ``cecd``, which presses a key of its virtual keyboard on each
``<User Control Pressed>`` from the TV and lets it go on ``<User Control Released>``. It waits for that release
however long it takes, where the kernel's own CEC input lets a key go 550 milliseconds after its last press.
TVs send the commands of their own menus, such as Home's "device root menu", and then show that menu without
sending the release, so the key stays down and repeats for whatever reads the keyboard. NonSteamApps gives
``cecd`` its own key mappings without those menus, in ``cecd/config.d`` under ``$XDG_CONFIG_HOME``, where
SteamOS Manager keeps its settings for ``cecd`` too, and asks the running ``cecd`` to read them again. A record of
what was written lets a file the user has since changed or removed stay as they left it, until the next install.

SteamOS before SteamOS Manager 26.2 started KDE's Plasma Remote Controllers instead. Out of the box it also opens
every joystick, Steam Input's virtual gamepads among them, and types their buttons and left stick as Enter, Ctrl,
Shift and the arrow keys: its SDL backend (``EnableJoystick``) does since 2025, its evdev backend (``EnableEvdev``)
did before. Steam Input already gives every app its controller, so NonSteamApps turns both backends off in
``plasma-remotecontrollersrc``, which leaves the remote's own backend (``EnableCEC``) on, and restarts the service if
it runs. What the file held before is kept in NonSteamApps' state, for an uninstall to put back.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .apps import IniSettings, ini_entries
from .fsutil import atomic_write_bytes, atomic_write_json

FILE = "plasma-remotecontrollersrc"
GROUP = "General"
BACKENDS = ("EnableJoystick", "EnableEvdev")
UNIT = "plasma-remotecontrollers.service"
UNIT_DIRS = (Path("/usr/lib/systemd/user"), Path("/etc/systemd/user"), Path("/usr/local/lib/systemd/user"))
RECORD = "remote-controllers.json"
CECD_UNIT = "cecd.service"
CECD_FRAGMENT = Path("cecd") / "config.d" / "50-nonsteamapps.toml"
CECD_RECORD = "cecd-mappings.json"
CECD_MAPPINGS = (
    ("select", 28), ("up", 103), ("down", 108), ("left", 105), ("right", 106), ("right-up", 614),
    ("right-down", 615), ("left-up", 616), ("left-down", 617), ("back", 1), ("number-entry-mode", 413),
    ("11", 620), ("12", 621), ("0", 11), ("1", 2), ("2", 3), ("3", 4), ("4", 5), ("5", 6), ("6", 7), ("7", 8),
    ("8", 9), ("9", 10), ("dot", 52), ("enter", 28), ("clear", 355), ("next-favorite", 624), ("channel-up", 402),
    ("channel-down", 403), ("previous-channel", 412), ("sound-select", 213), ("page-up", 104),
    ("page-down", 109), ("power", 116), ("volume-up", 115), ("volume-down", 114), ("mute", 113), ("play", 200),
    ("stop", 166), ("pause", 201), ("record", 167), ("rewind", 168), ("fast-forward", 208), ("eject", 161),
    ("skip-forward", 163), ("skip-backward", 165), ("stop-record", 625), ("pause-record", 626), ("angle", 371),
    ("audio-description", 622), ("3d-mode", 623), ("restore-volume-function", 628),
    ("power-toggle-function", 116), ("power-off-function", 142), ("power-on-function", 143), ("f1", 401),
    ("f2", 398), ("f3", 399), ("f4", 400), ("f5", 63),
)
CECD_LEFT_OUT = (
    "device-root-menu", "device-setup-menu", "contents-menu", "favorite-menu", "media-top-menu",
    "media-context-sensitive-menu", "display-information", "help", "electronic-program-guide",
    "initial-configuration", "internet", "video-on-demand", "timer-programming", "data",
)


def present(unit_dirs: Optional[Sequence[Path]] = None) -> bool:
    """Whether Plasma Remote Controllers is installed as a user service, as on SteamOS."""
    return any((Path(folder) / UNIT).is_file() for folder in (UNIT_DIRS if unit_dirs is None else unit_dirs))


def cecd_present(unit_dirs: Optional[Sequence[Path]] = None) -> bool:
    """Whether Valve's ``cecd`` is installed as a user service, as on SteamOS with SteamOS Manager 26.2 or newer."""
    return any((Path(folder) / CECD_UNIT).is_file() for folder in (UNIT_DIRS if unit_dirs is None else unit_dirs))


def cecd_fragment() -> str:
    """The configuration fragment of ``cecd`` key mappings that leaves out the commands of the TV's own menus."""
    lines = ["# NonSteamApps: cecd's own key mappings, without the TV's menus, whose keys TVs leave pressed", "[mappings]"]
    lines += [f'"{name}" = {code}' for name, code in CECD_MAPPINGS]
    return "\n".join(lines) + "\n"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _recorded(record: Path) -> Optional[str]:
    try:
        kept = json.loads(Path(record).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return kept.get("sha256") if isinstance(kept, dict) and isinstance(kept.get("sha256"), str) else None


def leave_out_tv_menus(config_home: Path, record: Path, force: bool) -> bool:
    """Write :func:`cecd_fragment` into ``cecd``'s user configuration; return whether the file changed.

    Without ``force``, as at an update, a fragment the user changed or removed after NonSteamApps wrote it stays as
    it is; an install, with ``force``, writes it again. ``record`` keeps the SHA-256 of what was written.
    """
    target = Path(config_home) / CECD_FRAGMENT
    text = cecd_fragment()
    try:
        current: Optional[str] = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = None
    except (OSError, UnicodeDecodeError):
        return False
    written = _recorded(record)
    if current == text:
        if written != _digest(text):
            atomic_write_json(record, {"sha256": _digest(text)})
        return False
    if not force and written is not None and (current is None or _digest(current) != written):
        return False
    if not force and written is None and current is not None:
        return False
    atomic_write_bytes(target, text.encode("utf-8"))
    atomic_write_json(record, {"sha256": _digest(text)})
    return True


def restore_cecd(config_home: Path, record: Path) -> bool:
    """Remove the fragment :func:`leave_out_tv_menus` wrote, where it is unchanged; return whether it was removed."""
    target = Path(config_home) / CECD_FRAGMENT
    written = _recorded(record)
    Path(record).unlink(missing_ok=True)
    try:
        current = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if _digest(current) not in (written, _digest(cecd_fragment())):
        return False
    target.unlink(missing_ok=True)
    return True


def reload_cecd() -> bool:
    """Have a running ``cecd`` read its configuration again, as SteamOS Manager does; return whether ``systemctl`` succeeded."""
    return _systemctl("try-reload-or-restart", CECD_UNIT)


def remote_only(settings: Path, record: Path, force: bool) -> List[str]:
    """Turn the controller backends off in ``settings``; return those turned off.

    Without ``force``, as at an update, a backend the file names already stays as it is, so that a choice made
    since stays; an install, with ``force``, turns it off again. ``record`` keeps the value each replaced, the
    last one the user chose, or none where the file did not name it.
    """
    current = dict(ini_entries(settings, GROUP, "Enable"))
    wanted = [key for key in BACKENDS if current.get(key, "").strip().lower() != "false" and (force or key not in current)]
    if not wanted:
        return []
    kept = _load(record)
    kept.update((key, current.get(key)) for key in wanted)
    if not IniSettings(Path(settings).name, tuple((GROUP, key, "false") for key in wanted)).apply(Path(settings).parent):
        return []
    atomic_write_json(record, kept)
    return wanted


def restore(settings: Path, record: Path) -> bool:
    """Put back the values :func:`remote_only` replaced, where they are still NonSteamApps'; return whether the file changed."""
    kept = _load(record)
    if not kept:
        return False
    try:
        lines = Path(settings).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = None
    except (OSError, UnicodeDecodeError):
        return False
    changed = False
    if lines is not None:
        for key, value in kept.items():
            changed = _put_back(lines, key, value) or changed
        if changed:
            atomic_write_bytes(Path(settings), ("\n".join(lines) + "\n").encode("utf-8"))
    Path(record).unlink(missing_ok=True)
    return changed


def restart() -> bool:
    """Restart the service where it runs, so that it reads its settings again; return whether ``systemctl`` succeeded."""
    return _systemctl("try-restart", UNIT)


def _systemctl(action: str, unit: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", action, unit], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False).returncode == 0
    except OSError:
        return False


def _put_back(lines: List[str], key: str, value: Optional[str]) -> bool:
    """Set ``key`` in ``[General]`` back to ``value``, or remove it for ``None``, where it still reads ``false``."""
    group = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            group = stripped[1:-1]
            continue
        name, separator, current = stripped.partition("=")
        if group == GROUP and separator and name.strip() == key and current.strip().lower() == "false":
            if value is None:
                del lines[index]
            else:
                lines[index] = f"{key}={value}"
            return True
    return False


def _load(record: Path) -> Dict[str, Optional[str]]:
    try:
        kept = json.loads(Path(record).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(kept, dict):
        return {}
    return {str(key): (value if isinstance(value, str) else None) for key, value in kept.items() if key in BACKENDS}
