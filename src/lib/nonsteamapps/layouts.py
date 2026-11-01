"""Controller layouts NonSteamApps makes itself, for apps that none of Valve's layouts suits.

The Files layout is Valve's Web Browser layout for the Steam Deck, read from Steam's own templates folder,
with three changes for a file manager: A presses only Enter, Y only goes forward (Valve's also types S,
which jumps to a file), and the left stick moves the selection like the D-pad instead of scrolling. It is
written for every controller type Valve ships a Gamepad layout for, keeping only the inputs that
controller has, into ``controller_base/templates``, where Steam lists layouts, and then assigned like
Valve's own (see :mod:`controllers`).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Dict, List, Optional

from . import controllers, vdf
from .fsutil import atomic_write_bytes

BASE = "controller_neptune_webbrowser.vdf"
FILES_TITLE = "Files (NonSteamApps)"
FILES_DESCRIPTION = "D-pad or left stick to move, A to open, B to go back, X for the keyboard, Start to close"
PREFIX = "nonsteamapps_"
REVISION = "1"
_ALWAYS_ON = "always_on_action"


def _find(pairs: vdf.Pairs, key: str):
    return next((value for name, value in pairs if name == key), None)


def _mappings(layout: vdf.Pairs) -> vdf.Pairs:
    mappings = _find(layout, "controller_mappings")
    if not isinstance(mappings, list):
        raise vdf.VdfError("not a controller layout")
    return mappings


def _active_groups(mappings: vdf.Pairs) -> Dict[str, vdf.Pairs]:
    """Map each input source the layout uses (``button_diamond``, ``dpad``…) to its group."""
    groups = {_find(group, "id"): group for name, group in mappings if name == "group" and isinstance(group, list)}
    preset = _find(mappings, "preset") or []
    found: Dict[str, vdf.Pairs] = {}
    for group_id, source in _find(preset, "group_source_bindings") or []:
        name, _, state = str(source).partition(" ")
        if state == "active" and group_id in groups:
            found.setdefault(name, groups[group_id])
    return found


def _inputs(group: vdf.Pairs) -> List[str]:
    return [name for name, _ in _find(group, "inputs") or []]


def _bind(group: vdf.Pairs, button: str, bindings: List[str]) -> None:
    for name, value in _find(group, "inputs") or []:
        if name == button:
            activator = _find(_find(value, "activators") or [], "Full_Press") or []
            pairs = _find(activator, "bindings")
            if isinstance(pairs, list):
                pairs[:] = [("binding", binding) for binding in bindings]


def _group(source: str, base: Dict[str, vdf.Pairs], target: vdf.Pairs, same_controller: bool) -> Optional[vdf.Pairs]:
    if source == "joystick" and "dpad" in base and "joystick" in base:
        group = [(name, value) for name, value in copy.deepcopy(base["joystick"]) if name != "inputs"]
        group.insert(2, ("inputs", copy.deepcopy(_find(base["dpad"], "inputs"))))
        return group
    if source not in base:
        return None
    group = copy.deepcopy(base[source])
    if source == "button_diamond":
        _bind(group, "button_a", ["key_press RETURN, Open"])
        _bind(group, "button_y", ["mouse_button FORWARD, ▶️"])
    elif source == "switch":
        keep = set(_inputs(target)) | ({_ALWAYS_ON} if same_controller else set())
        inputs = _find(group, "inputs") or []
        inputs[:] = [(name, value) for name, value in inputs if name in keep]
    return group


def files_layout(base: vdf.Pairs, target: vdf.Pairs) -> Optional[vdf.Pairs]:
    """The Files layout for the controller of Valve's Gamepad layout ``target``, from the Web Browser layout ``base``."""
    base_mappings, target_mappings = _mappings(base), _mappings(target)
    kind = str(_find(target_mappings, "controller_type") or "")
    if not kind.startswith("controller_"):
        return None
    same_controller = kind == _find(base_mappings, "controller_type")
    base_groups = _active_groups(base_mappings)
    body: vdf.Pairs = []
    sources: vdf.Pairs = []
    for source, target_group in _active_groups(target_mappings).items():
        group = _group(source, base_groups, target_group, same_controller)
        if group is None:
            continue
        group_id = str(len(sources))
        body.append(("group", [("id", group_id), *[(name, value) for name, value in group if name != "id"]]))
        sources.append((group_id, f"{source} active"))
    if not sources:
        return None
    settings = _find(base_mappings if same_controller else target_mappings, "settings") or []
    header: vdf.Pairs = [
        ("version", "3"),
        ("revision", REVISION),
        ("title", FILES_TITLE),
        ("description", FILES_DESCRIPTION),
        ("controller_type", kind),
        ("major_revision", "0"),
        ("minor_revision", "0"),
        ("Timestamp", "0"),
    ]
    preset: vdf.Pairs = [("id", "0"), ("name", "Default"), ("group_source_bindings", sources)]
    return [("controller_mappings", [*header, *body, ("preset", preset), ("settings", copy.deepcopy(settings))])]


def _read(path: Path) -> vdf.Pairs:
    return vdf.loads_pairs(path.read_text(encoding="utf-8", errors="replace"))


def install(root: Path) -> List[str]:
    """Write the Files layout for each controller type with a Valve Gamepad layout; return the files that were missing or out of date."""
    directory = controllers.templates_dir(root)
    try:
        base = _read(directory / BASE)
    except (OSError, vdf.VdfError):
        return []
    written = []
    for kind, name in sorted(controllers.find_templates(root, "Gamepad").items()):
        if kind.startswith("controller_mobile"):
            continue
        try:
            layout = files_layout(base, _read(directory / name))
        except (OSError, vdf.VdfError):
            continue
        if layout is None:
            continue
        path = directory / f"{kind}_{PREFIX}files.vdf"
        text = vdf.dumps_pairs(layout)
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != text:
            atomic_write_bytes(path, text.encode("utf-8"))
            written.append(path.name)
    return written


def remove(root: Path) -> List[str]:
    """Delete the layouts :func:`install` wrote; return their names."""
    removed = []
    for path in sorted(controllers.templates_dir(root).glob(f"controller_*_{PREFIX}*.vdf")):
        path.unlink()
        removed.append(path.name)
    return removed
