"""Desktop Mode: an app's entry in the applications menu, and its launcher on Plasma's taskbar.

The entry is a desktop file in ``~/.local/share/applications`` named after the app's window class, so that
Plasma counts the app's windows as that launcher's. Plasma keeps a task manager's pinned launchers in the
``launchers`` key of the applet's settings, and shows its own defaults while that key is missing. A running
Plasma writes its settings file over any change made to it, so a running Plasma is changed through its
scripting interface on the session bus (``org.kde.PlasmaShell.evaluateScript``); one that is not running, as
in Game Mode, through the file it reads when it next starts.
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from . import appmenu
from .apps import set_ini
from .fsutil import atomic_write_bytes

PLASMA = "org.kde.plasmashell"
LAYOUT = "plasma-org.kde.plasma.desktop-appletsrc"
TASK_MANAGERS = ("org.kde.plasma.taskmanager", "org.kde.plasma.icontasks")
DEFAULT_LAUNCHERS = (
    "applications:systemsettings.desktop",
    "applications:org.kde.discover.desktop",
    "preferred://filemanager",
    "preferred://browser",
)
_APPLET = re.compile(r"Containments\]\[\d+\]\[Applets\]\[\d+")


def entry_text(name: str, comment: str, command: Path, icon: Path, wm_class: str, generic: str = "", categories: Tuple[str, ...] = ()) -> str:
    """A desktop file that runs ``command`` with the files or links it is given."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        *([f"GenericName={generic}"] if generic else []),
        f"Comment={comment}",
        f'Exec="{command}" %U',
        f"Icon={icon}",
        "Terminal=false",
        *([f"Categories={';'.join(categories)};"] if categories else []),
        f"StartupWMClass={wm_class}",
        "StartupNotify=true",
    ]
    return "\n".join(lines) + "\n"


def write_entry(path: Path, text: str) -> bool:
    """Write the desktop file at ``path``; return whether it changed."""
    try:
        if Path(path).read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(Path(path), text.encode("utf-8"))
    return True


def launcher(entry: Path) -> str:
    """How Plasma's taskbar names the launcher of the desktop file ``entry``."""
    return f"applications:{Path(entry).name}"


def pin(name: str, layout: Path, environ: Mapping[str, str] = os.environ) -> Optional[bool]:
    """Add the launcher ``name`` to every taskbar; whether one changed, or ``None`` when none could be."""
    return _change(name, True, layout, environ)


def unpin(name: str, layout: Path, environ: Mapping[str, str] = os.environ) -> Optional[bool]:
    """Take the launcher ``name`` off every taskbar; whether one changed, or ``None`` when none could be."""
    return _change(name, False, layout, environ)


def _change(name: str, add: bool, layout: Path, environ: Mapping[str, str]) -> Optional[bool]:
    reached, changed = _through_plasma(name, add, environ)
    if reached:
        return changed
    if plasma_running():
        return None
    return _through_layout(name, add, Path(layout))


def script(name: str, add: bool) -> str:
    """Plasma's script that adds the launcher to, or takes it off, each task manager, and prints how many changed."""
    return (
        f"var entry = {json.dumps(name)}, add = {json.dumps(add)}, defaults = {json.dumps(list(DEFAULT_LAUNCHERS))};\n"
        f"var types = {json.dumps(list(TASK_MANAGERS))}, changed = 0;\n"
        "panels().forEach(function (panel) {\n"
        "  types.forEach(function (type) {\n"
        "    panel.widgets(type).forEach(function (widget) {\n"
        "      widget.currentConfigGroup = [\"General\"];\n"
        "      var launchers = widget.readConfig(\"launchers\", defaults);\n"
        "      launchers = typeof launchers === \"string\" ? (launchers ? launchers.split(\",\") : []) : Array.prototype.slice.call(launchers);\n"
        "      if ((launchers.indexOf(entry) >= 0) === add) return;\n"
        "      launchers = add ? launchers.concat([entry]) : launchers.filter(function (item) { return item !== entry; });\n"
        "      widget.writeConfig(\"launchers\", launchers);\n"
        "      widget.reloadConfig();\n"
        "      changed += 1;\n"
        "    });\n"
        "  });\n"
        "});\n"
        "print(changed);\n"
    )


def _through_plasma(name: str, add: bool, environ: Mapping[str, str]) -> Tuple[bool, Optional[bool]]:
    """Run :func:`script` in a running Plasma: whether Plasma was reached, and whether a taskbar changed."""
    address = appmenu.session_bus(environ)
    if not address:
        return False, None
    try:
        connection = appmenu.Connection(address, timeout=10.0)
    except (OSError, ValueError):
        return False, None
    try:
        connection.bus("Hello")
        if not appmenu.uint32(connection.bus("NameHasOwner", "s", bytes(appmenu.Writer().string(PLASMA).data))):
            return False, None
        body = bytes(appmenu.Writer().string(script(name, add)).data)
        reply = connection.call(PLASMA, "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript", "s", body)
        printed = _string(reply).strip()
        return True, printed.isdigit() and int(printed) > 0
    except (OSError, EOFError, ValueError, struct.error):
        return True, None
    finally:
        connection.close()


def _string(message: appmenu.Message) -> str:
    length = struct.unpack_from(message.order + "I", message.body)[0]
    return message.body[4:4 + length].decode("utf-8", "replace")


def plasma_running(proc: Path = Path("/proc")) -> bool:
    """Whether a Plasma shell runs for this user, which would write its settings over a change to the file."""
    uid = os.getuid()
    try:
        entries = list(Path(proc).iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == uid and (entry / "comm").read_text(encoding="utf-8").strip() == "plasmashell":
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _groups(lines: List[str]) -> Dict[str, Dict[str, str]]:
    groups: Dict[str, Dict[str, str]] = {}
    current: Optional[Dict[str, str]] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = groups.setdefault(stripped[1:-1], {})
        elif current is not None and "=" in stripped:
            key, _, value = stripped.partition("=")
            current[key.strip()] = value.strip()
    return groups


def split_list(value: str) -> List[str]:
    """A KConfig list: items between commas, where ``\\,`` is a comma and ``\\\\`` a backslash."""
    items, current, escaped = [], "", False
    for character in value:
        if escaped:
            current += character
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ",":
            items.append(current)
            current = ""
        else:
            current += character
    if current or items:
        items.append(current)
    return items


def join_list(items: List[str]) -> str:
    return ",".join(item.replace("\\", "\\\\").replace(",", "\\,") for item in items)


def _through_layout(name: str, add: bool, layout: Path) -> Optional[bool]:
    """Change the task managers in Plasma's layout file, for Plasma to read when it next starts."""
    try:
        lines = layout.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    groups = _groups(lines)
    applets = [group for group, values in groups.items() if _APPLET.fullmatch(group) and values.get("plugin") in TASK_MANAGERS]
    if not applets:
        return None
    changed = False
    for applet in applets:
        settings = f"{applet}][Configuration][General"
        stored = groups.get(settings, {}).get("launchers")
        launchers = split_list(stored) if stored is not None else list(DEFAULT_LAUNCHERS)
        if (name in launchers) == add:
            continue
        launchers = [*launchers, name] if add else [item for item in launchers if item != name]
        changed = set_ini(lines, settings, "launchers", join_list(launchers)) or changed
    if changed:
        atomic_write_bytes(layout, ("\n".join(lines) + "\n").encode("utf-8"))
    return changed
