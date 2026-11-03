"""Controller layouts NonSteamApps makes itself, for apps that none of Valve's layouts suits.

Each layout starts from one of Valve's layouts for the Steam Deck, read from Steam's own templates folder,
and changes only what its app needs. It is written for every controller type Valve ships a Gamepad layout
for, keeping only the inputs that controller has, into ``controller_base/templates``, where Steam lists
layouts, and then assigned like Valve's own (see :mod:`controllers`).

- **Browser**, for the Helium apps, is Web Browser with one addition: holding Menu quits (Ctrl+Shift+W,
  which closes the window with all its tabs), while a short press still closes the tab.
- **Files** starts from Web Browser. A presses only Enter (Valve's also presses Space, which toggles
  Dolphin's selection mode), Y only goes forward (Valve's also types S, which jumps to a file), the
  left stick moves the selection like the D-pad instead of scrolling, and holding Menu quits (Ctrl+Q).
- **Minecraft** starts from Keyboard (WASD) and Mouse, whose buttons already match Minecraft's keys. X drops
  the held item (Q), Menu pauses (Escape) and View shows the players (Tab), the stick clicks sprint
  (Ctrl) and sneak (Shift), and the bumpers step left and right along the hotbar.
- **LocalSend** starts from Web Browser and uses LocalSend's own keys: the D-pad moves between controls as
  before, A selects (Enter; Valve's also presses Space, so a button would be pressed twice), B goes back
  (Escape; LocalSend ignores the mouse's Back button), Y pastes (Ctrl+V, which sends what was copied), the
  bumpers step to the previous and next control (Shift+Tab and Tab), and holding Menu quits (Ctrl+Q).
- **Tools**, for ProtonUp-Qt and Protontricks, starts from Web Browser. Their windows are lists, check boxes
  and buttons, so the D-pad moves up and down a list and left and right between controls (Shift+Tab and Tab),
  A selects or ticks (Space), Y confirms (Enter) and B cancels (Escape). Valve's A presses both Enter and
  Space, which would tick a box and close its dialog at once.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from . import controllers, vdf
from .fsutil import atomic_write_bytes

PREFIX = "nonsteamapps_"
_ALWAYS_ON = "always_on_action"

Change = Callable[[str, vdf.Pairs, Dict[str, vdf.Pairs]], vdf.Pairs]


def _find(pairs: vdf.Pairs, key: str):
    return next((value for name, value in pairs if name == key), None)


def _bind(group: vdf.Pairs, button: str, bindings: List[str]) -> None:
    for name, value in _find(group, "inputs") or []:
        if name == button:
            activator = _find(_find(value, "activators") or [], "Full_Press") or []
            pairs = _find(activator, "bindings")
            if isinstance(pairs, list):
                pairs[:] = [("binding", binding) for binding in bindings]


def _set(pairs: vdf.Pairs, key: str, value: str) -> None:
    pairs[:] = [(name, current) for name, current in pairs if name != key] + [(key, value)]


def _hold(group: vdf.Pairs, button: str, bindings: List[str]) -> None:
    """Give ``button`` a long press; its short press then waits for the release, so holding sends only ``bindings``."""
    for name, value in _find(group, "inputs") or []:
        activators = _find(value, "activators") if name == button else None
        if not isinstance(activators, list):
            continue
        full = _find(activators, "Full_Press")
        if isinstance(full, list):
            settings = _find(full, "settings")
            if not isinstance(settings, list):
                settings = []
                full.append(("settings", settings))
            _set(settings, "interruptable", "1")
        activators[:] = [(kind, activator) for kind, activator in activators if kind != "Long_Press"]
        activators.append(("Long_Press", [("bindings", [("binding", binding) for binding in bindings])]))


def _browser(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "switch":
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press LEFT_SHIFT", "key_press W"])
    return group


def _files(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "joystick" and "dpad" in base:
        group = [(name, value) for name, value in group if name != "inputs"]
        group.insert(2, ("inputs", copy.deepcopy(_find(base["dpad"], "inputs"))))
    elif source == "button_diamond":
        _bind(group, "button_a", ["key_press RETURN, Open"])
        _bind(group, "button_y", ["mouse_button FORWARD, ▶️"])
    elif source == "switch":
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press Q"])
    return group


def _minecraft(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "button_diamond":
        _bind(group, "button_x", ["key_press Q, Drop"])
    elif source == "switch":
        _bind(group, "button_menu", ["key_press ESCAPE, Pause"])
        _bind(group, "button_escape", ["key_press TAB, Players"])
        _bind(group, "left_bumper", ["mouse_wheel SCROLL_UP"])
        _bind(group, "right_bumper", ["mouse_wheel SCROLL_DOWN"])
    elif source == "joystick":
        _bind(group, "click", ["key_press LEFT_CONTROL, Sprint"])
    elif source == "right_joystick":
        _bind(group, "click", ["key_press LEFT_SHIFT, Sneak"])
    return group


def _localsend(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "button_diamond":
        _bind(group, "button_a", ["key_press RETURN, Select"])
        _bind(group, "button_b", ["key_press ESCAPE, Back"])
        _bind(group, "button_y", ["key_press LEFT_CONTROL, Paste", "key_press V"])
    elif source == "switch":
        _bind(group, "left_bumper", ["key_press LEFT_SHIFT", "key_press TAB, Previous"])
        _bind(group, "right_bumper", ["key_press TAB, Next"])
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press Q"])
    return group


def _tools(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "dpad":
        _bind(group, "dpad_west", ["key_press LEFT_SHIFT", "key_press TAB, Previous"])
        _bind(group, "dpad_east", ["key_press TAB, Next"])
    elif source == "button_diamond":
        _bind(group, "button_a", ["key_press SPACE, Select"])
        _bind(group, "button_b", ["key_press ESCAPE, Cancel"])
        _bind(group, "button_y", ["key_press RETURN, OK"])
    return group


@dataclass(frozen=True)
class Layout:
    """A layout made from Valve's ``base`` layout for the Deck, with ``change`` applied to each group it keeps."""

    slug: str
    title: str
    description: str
    base: str
    change: Change
    revision: str = "1"

    def file_name(self, kind: str) -> str:
        return f"{kind}_{PREFIX}{self.slug}.vdf"


BROWSER = Layout(
    slug="browser",
    title="Browser (NonSteamApps)",
    description="Steam's Web Browser layout: trackpads or right stick to point, R2 to click, B to go back, X for the keyboard, Start to close the tab, hold Start to quit",
    base="controller_neptune_webbrowser.vdf",
    change=_browser,
)
FILES = Layout(
    slug="files",
    title="Files (NonSteamApps)",
    description="D-pad or left stick to move, A to open, B to go back, X for the keyboard, Start to close the tab, hold Start to quit",
    base="controller_neptune_webbrowser.vdf",
    change=_files,
    revision="2",
)
MINECRAFT = Layout(
    slug="minecraft",
    title="Minecraft (NonSteamApps)",
    description="Left stick to move, right stick to look, A to jump, B for the inventory, X to drop, triggers to use and attack, Start to pause",
    base="controller_neptune_wasd.vdf",
    change=_minecraft,
)
LOCALSEND = Layout(
    slug="localsend",
    title="LocalSend (NonSteamApps)",
    description="D-pad to move, A to select, B to go back, Y to paste, bumpers for the previous and next control, X for the keyboard, hold Start to quit",
    base="controller_neptune_webbrowser.vdf",
    change=_localsend,
)
TOOLS = Layout(
    slug="tools",
    title="Tools (NonSteamApps)",
    description="D-pad up and down to move in a list, left and right to go between controls, A to select, Y for OK, B to cancel, X for the keyboard",
    base="controller_neptune_webbrowser.vdf",
    change=_tools,
)
LAYOUTS = (BROWSER, FILES, LOCALSEND, MINECRAFT, TOOLS)


def used_by(titles: Iterable[str]) -> List[Layout]:
    """The layouts named in ``titles``, the controller layouts apps ask for."""
    wanted = set(titles)
    return [layout for layout in LAYOUTS if layout.title in wanted]


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


def build(layout: Layout, base: vdf.Pairs, target: vdf.Pairs) -> Optional[vdf.Pairs]:
    """``layout`` for the controller of Valve's Gamepad layout ``target``, from Valve's ``base`` layout."""
    base_mappings, target_mappings = _mappings(base), _mappings(target)
    kind = str(_find(target_mappings, "controller_type") or "")
    if not kind.startswith("controller_"):
        return None
    same_controller = kind == _find(base_mappings, "controller_type")
    base_groups = _active_groups(base_mappings)
    body: vdf.Pairs = []
    sources: vdf.Pairs = []
    for source, target_group in _active_groups(target_mappings).items():
        if source not in base_groups:
            continue
        group = copy.deepcopy(base_groups[source])
        if source == "switch":
            keep = set(_inputs(target_group)) | ({_ALWAYS_ON} if same_controller else set())
            inputs = _find(group, "inputs") or []
            inputs[:] = [(name, value) for name, value in inputs if name in keep]
        group = layout.change(source, group, base_groups)
        group_id = str(len(sources))
        body.append(("group", [("id", group_id), *[(name, value) for name, value in group if name != "id"]]))
        sources.append((group_id, f"{source} active"))
    if not sources:
        return None
    settings = _find(base_mappings if same_controller else target_mappings, "settings") or []
    header: vdf.Pairs = [
        ("version", "3"),
        ("revision", layout.revision),
        ("title", layout.title),
        ("description", layout.description),
        ("controller_type", kind),
        ("major_revision", "0"),
        ("minor_revision", "0"),
        ("Timestamp", "0"),
    ]
    preset: vdf.Pairs = [("id", "0"), ("name", "Default"), ("group_source_bindings", sources)]
    return [("controller_mappings", [*header, *body, ("preset", preset), ("settings", copy.deepcopy(settings))])]


def _read(path: Path) -> vdf.Pairs:
    return vdf.loads_pairs(path.read_text(encoding="utf-8", errors="replace"))


def install(root: Path, layout: Layout) -> List[str]:
    """Write ``layout`` for each controller type with a Valve Gamepad layout; return the files that were missing or out of date."""
    directory = controllers.templates_dir(root)
    try:
        base = _read(directory / layout.base)
    except (OSError, vdf.VdfError):
        return []
    written = []
    for kind, name in sorted(controllers.find_templates(root, "Gamepad").items()):
        if kind.startswith("controller_mobile"):
            continue
        try:
            built = build(layout, base, _read(directory / name))
        except (OSError, vdf.VdfError):
            continue
        if built is None:
            continue
        path = directory / layout.file_name(kind)
        text = vdf.dumps_pairs(built)
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != text:
            atomic_write_bytes(path, text.encode("utf-8"))
            written.append(path.name)
    return written


def remove(root: Path, layout: Layout) -> List[str]:
    """Delete the files :func:`install` wrote for ``layout``; return their names."""
    removed = []
    for path in sorted(controllers.templates_dir(root).glob(layout.file_name("controller_*"))):
        path.unlink()
        removed.append(path.name)
    return removed
