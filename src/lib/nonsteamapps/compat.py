"""Keep NonSteamApps' shortcuts free of Steam Play compatibility tools.

Every app NonSteamApps adds is a native Linux program started by its launcher, so the best Steam Play
setting is none: Proton would run the launcher as a Windows program, and the Steam Linux Runtime's
container hides Flatpak and SteamOS's own apps. Steam keeps a tool forced on a shortcut in the
install's ``config/config.vdf``, under ``CompatToolMapping`` and the shortcut's 32-bit app ID; a
shortcut with no entry, or one naming no tool, runs natively. Like Steam ROM Manager, NonSteamApps
removes the entry to undo a forced tool, edits the file only while Steam is closed, and keeps a backup.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable, Optional

from . import vdf
from .fsutil import atomic_write_bytes

MAPPING_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")
BACKUP_SUFFIX = ".nonsteamapps.bak"


def config_file(root: Path) -> Path:
    return Path(root) / "config" / "config.vdf"


def _child(pairs: vdf.Pairs, key: str) -> Optional[vdf.Pairs]:
    return next((value for name, value in pairs if name.lower() == key.lower() and isinstance(value, list)), None)


def _mapping(data: vdf.Pairs) -> Optional[vdf.Pairs]:
    node: Optional[vdf.Pairs] = data
    for key in MAPPING_PATH:
        node = _child(node, key) if node is not None else None
    return node


def _tool(entry) -> str:
    if not isinstance(entry, list):
        return ""
    return next((str(value) for name, value in entry if name.lower() == "name" and isinstance(value, str)), "")


def _load(root: Path) -> Optional[vdf.Pairs]:
    try:
        return vdf.loads_pairs(config_file(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, vdf.VdfError):
        return None


def forced(root: Path, appids: Iterable[int]) -> Dict[int, str]:
    """The tools forced on these shortcuts, by app ID."""
    wanted = {str(appid): appid for appid in appids}
    mapping = _mapping(_load(root) or [])
    return {wanted[key]: _tool(entry) for key, entry in mapping or [] if key in wanted and _tool(entry)}


def clear(root: Path, appids: Iterable[int], everything: bool = False) -> Dict[int, str]:
    """Undo the tools forced on these shortcuts, or with ``everything`` drop their entries too; return what was forced.

    Call it only while Steam is closed, which rewrites the file when it exits.
    """
    wanted = {str(appid): appid for appid in appids}
    data = _load(root)
    mapping = _mapping(data or [])
    if not mapping:
        return {}
    found = {wanted[key]: _tool(entry) for key, entry in mapping if key in wanted and _tool(entry)}
    kept = [(key, entry) for key, entry in mapping if key not in wanted or not (everything or _tool(entry))]
    if len(kept) == len(mapping):
        return found
    mapping[:] = kept
    path = config_file(root)
    shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
    atomic_write_bytes(path, vdf.dumps_pairs(data).encode("utf-8"))
    return found
