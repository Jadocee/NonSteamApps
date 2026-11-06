"""The TV's remote: keep Plasma Remote Controllers to it, so that it does not also type the controllers' presses.

Where Steam lets the TV's remote control the device over HDMI-CEC, SteamOS Manager starts KDE's Plasma Remote
Controllers, which turns the remote's buttons into presses of a virtual keyboard. Out of the box it also opens every
joystick, Steam Input's virtual gamepads among them, and types their buttons and left stick as Enter, Ctrl, Shift and
the arrow keys: its SDL backend (``EnableJoystick``) does since 2025, its evdev backend (``EnableEvdev``) did before.
While a game or app runs, its controller's presses then arrive twice, the second time as keys for whatever holds the
keyboard. Steam Input already gives every app its controller, so NonSteamApps turns both backends off in
``plasma-remotecontrollersrc``, which leaves the remote's own backend (``EnableCEC``) on, and restarts the service if
it runs. What the file held before is kept in NonSteamApps' state, for an uninstall to put back.
"""

from __future__ import annotations

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


def present(unit_dirs: Optional[Sequence[Path]] = None) -> bool:
    """Whether Plasma Remote Controllers is installed as a user service, as on SteamOS."""
    return any((Path(folder) / UNIT).is_file() for folder in (UNIT_DIRS if unit_dirs is None else unit_dirs))


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
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "try-restart", UNIT], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
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
