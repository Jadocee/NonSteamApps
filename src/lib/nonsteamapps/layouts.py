"""Controller layouts NonSteamApps makes itself, for apps that none of Valve's layouts suits.

Each layout starts from one of Valve's layouts for the Steam Deck, read from Steam's own templates folder,
and changes only what its app needs. It is written for every controller type Valve ships a Gamepad layout
for, keeping only the inputs that controller has, into ``controller_base/templates``, where Steam lists
layouts, and then assigned like Valve's own (see :mod:`controllers`).

- **Browser**, for the Helium apps, is Web Browser with long presses added. Holding Menu quits: it sends
  Ctrl+Shift+W, which closes the window with all its tabs, together with Ctrl+Shift+Q, Helium's Exit, which
  a full-screen page cannot intercept (see :mod:`browser`). Holding L1 or R1 goes to the previous or next tab
  (Ctrl+Page Up and Ctrl+Page Down). Short presses still close the tab and go back and forward.
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
- **Emulator**, for KytyPS5, Eden and Eden-NX2, starts from Gamepad with Mouse Trackpad, whose right trackpad moves
  the pointer but whose press, on a soft press like Valve's mouse layouts, is the right stick's click. It presses
  the left mouse button instead; the rest is a
  gamepad for the game. Holding View shifts the right stick and the face buttons into Web Browser's for every
  controller, for the emulators' own windows: the stick points (its click clicks), A clicks, B is Escape,
  Y is Enter and X the on-screen keyboard. Valve does not let a mode shift change triggers or bumpers.
- **Tools**, for ProtonUp-Qt and Protontricks, starts from Web Browser. Their windows are lists, check boxes
  and buttons, so the D-pad moves up and down a list and left and right between controls (Shift+Tab and Tab),
  A selects or ticks (Space), Y confirms (Enter) and B cancels (Escape). Valve's A presses both Enter and
  Space, which would tick a box and close its dialog at once.
- **Bitwarden** starts from Web Browser, for Bitwarden's web interface, in which the arrow keys move between
  controls by where they are on screen (Chromium's spatial navigation, see :mod:`apps`): the D-pad, and the left
  stick instead of scrolling, send them. A presses Enter, which opens a link, presses a button or sends a form
  (Space would not open the links of its sidebar), B is Escape and Y is Space, which ticks a box. Valve's A also
  presses Space, which would press a button twice. Bitwarden's shortcuts stand in for what its menu bar holds,
  which Game Mode hides (see :mod:`appmenu`): Menu opens the settings (Ctrl+,), View locks the vault (Ctrl+L),
  L1 searches it (Ctrl+F), R1 opens the password generator (Ctrl+G), and holding Menu quits (Ctrl+Q).
- **Jellyfin** starts from Web Browser and sends Jellyfin Desktop's keys, as its Flatpak cannot reach a
  controller itself: the D-pad and the left stick move (arrow keys), A selects (Enter), B goes back
  (Escape) and, held, home (H), Y searches (Ctrl+F), the bumpers rewind and fast forward (Page Up and Page
  Down), Menu plays or pauses (Space), held, quits (Ctrl+Q), and View goes home. B's short press waits for
  its release, as Jellyfin quits when Escape is held for half a second; Valve's Menu, Ctrl+W, would quit at once.
- **YouTube** is Gamepad, which VacuumTube reads as a controller, with View held to reload YouTube: Ctrl+R,
  the Reload of the menu Electron gives an app that sets none, which VacuumTube keeps hidden. Reloading the
  home screen brings fresh recommendations. A short press is still Select, VacuumTube's volume down.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import controllers, vdf
from .fsutil import atomic_write_bytes

PREFIX = "nonsteamapps_"
_ALWAYS_ON = "always_on_action"

Change = Callable[[str, vdf.Pairs, Dict[str, vdf.Pairs]], vdf.Pairs]


def _find(pairs: vdf.Pairs, key: str):
    return next((value for name, value in pairs if name == key), None)


def _press(value: vdf.Pairs) -> vdf.Pairs:
    """The activator of an input's press: its full press, or else the one Valve gives it, such as a trackpad's soft press."""
    activators = _find(value, "activators") or []
    full = _find(activators, "Full_Press")
    if isinstance(full, list):
        return full
    return next((activator for _, activator in activators if isinstance(activator, list)), [])


def _bind(group: vdf.Pairs, button: str, bindings: List[str]) -> None:
    for name, value in _find(group, "inputs") or []:
        if name == button:
            pairs = _find(_press(value), "bindings")
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
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press LEFT_SHIFT", "key_press W", "key_press Q"])
        _hold(group, "left_bumper", ["key_press LEFT_CONTROL, Previous tab", "key_press PAGE_UP"])
        _hold(group, "right_bumper", ["key_press LEFT_CONTROL, Next tab", "key_press PAGE_DOWN"])
    return group


def _stick_as_dpad(group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    """The left stick's group with the D-pad's inputs, so that the stick moves the selection as the D-pad does."""
    group = [(name, value) for name, value in group if name != "inputs"]
    group.insert(2, ("inputs", copy.deepcopy(_find(base["dpad"], "inputs"))))
    return group


def _files(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "joystick" and "dpad" in base:
        group = _stick_as_dpad(group, base)
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


def _jellyfin(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "joystick" and "dpad" in base:
        group = _stick_as_dpad(group, base)
    elif source == "button_diamond":
        _bind(group, "button_a", ["key_press RETURN, Select"])
        _bind(group, "button_b", ["key_press ESCAPE, Back"])
        _hold(group, "button_b", ["key_press H, Home"])
        _bind(group, "button_y", ["key_press LEFT_CONTROL, Search", "key_press F"])
    elif source == "switch":
        _bind(group, "button_menu", ["key_press SPACE, Play or pause"])
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press Q"])
        _bind(group, "button_escape", ["key_press H, Home"])
        _bind(group, "left_bumper", ["key_press PAGE_UP, Rewind"])
        _bind(group, "right_bumper", ["key_press PAGE_DOWN, Fast forward"])
    return group


def _emulator(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "right_trackpad":
        _bind(group, "click", ["mouse_button LEFT"])
    return group


def _windows(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "button_diamond":
        _bind(group, "button_a", ["mouse_button LEFT, Click"])
        _bind(group, "button_b", ["key_press ESCAPE, Back"])
        _bind(group, "button_y", ["key_press RETURN, OK"])
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


def _youtube(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "switch":
        _hold(group, "button_escape", ["key_press LEFT_CONTROL, Reload", "key_press R"])
    return group


def _bitwarden(source: str, group: vdf.Pairs, base: Dict[str, vdf.Pairs]) -> vdf.Pairs:
    if source == "joystick" and "dpad" in base:
        group = _stick_as_dpad(group, base)
    elif source == "button_diamond":
        _bind(group, "button_a", ["key_press RETURN, Select"])
        _bind(group, "button_b", ["key_press ESCAPE, Back"])
        _bind(group, "button_y", ["key_press SPACE, Tick"])
    elif source == "switch":
        _bind(group, "button_menu", ["key_press LEFT_CONTROL, Settings", "key_press COMMA"])
        _hold(group, "button_menu", ["key_press LEFT_CONTROL, Quit", "key_press Q"])
        _bind(group, "button_escape", ["key_press LEFT_CONTROL, Lock", "key_press L"])
        _bind(group, "left_bumper", ["key_press LEFT_CONTROL, Search", "key_press F"])
        _bind(group, "right_bumper", ["key_press LEFT_CONTROL, Generator", "key_press G"])
    return group


@dataclass(frozen=True)
class Shift:
    """While ``button`` of the switches is held, ``sources`` take their groups from Valve's layout ``template``, changed by ``change``."""

    button: str
    template: str
    sources: Tuple[str, ...]
    change: Change


@dataclass(frozen=True)
class Layout:
    """A layout made from Valve's ``base`` layout for the Deck, with ``change`` applied to each group it keeps.

    ``replaces`` are the slugs it had in earlier versions, whose files go when it is written or removed. ``shift``
    is a mode shift, built from another of Valve's layouts on the device.
    """

    slug: str
    title: str
    description: str
    base: str
    change: Change
    revision: str = "1"
    replaces: Tuple[str, ...] = ()
    shift: Optional[Shift] = None

    def file_name(self, kind: str, slug: str = "") -> str:
        return f"{kind}_{PREFIX}{slug or self.slug}.vdf"

    def retired(self, directory: Path) -> List[Path]:
        """The files written under the slugs in ``replaces``."""
        return sorted(path for slug in self.replaces for path in Path(directory).glob(self.file_name("controller_*", slug)))


BROWSER = Layout(
    slug="browser",
    title="Browser (NonSteamApps)",
    description="Steam's Web Browser layout: trackpads or right stick to point, R2 to click, B to go back, X for the keyboard, Start to close the tab, hold Start to quit, hold L1 or R1 to change tabs",
    base="controller_neptune_webbrowser.vdf",
    change=_browser,
    revision="2",
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
EMULATOR = Layout(
    slug="emulator",
    title="Emulator (NonSteamApps)",
    description="Steam's Gamepad layout for games; hold View for the emulator's own windows: right stick to point, A to click, B for Escape, Y for Enter, X for the keyboard",
    base="controller_neptune_gamepad+mouse.vdf",
    change=_emulator,
    revision="3",
    replaces=("kytyps5",),
    shift=Shift("button_escape", "controller_neptune_webbrowser.vdf", ("right_joystick", "button_diamond"), _windows),
)
JELLYFIN = Layout(
    slug="jellyfin",
    title="Jellyfin (NonSteamApps)",
    description="D-pad or left stick to move, A to select, B to go back (hold for home), Y to search, L1 and R1 to rewind and fast forward, Start to play or pause, hold Start to quit, View for home, X for the keyboard",
    base="controller_neptune_webbrowser.vdf",
    change=_jellyfin,
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
BITWARDEN = Layout(
    slug="bitwarden",
    title="Bitwarden (NonSteamApps)",
    description="D-pad or left stick to move, A to select, B to go back, Y to tick, X for the keyboard, Start for settings, View to lock, L1 to search, R1 for the generator, hold Start to quit",
    base="controller_neptune_webbrowser.vdf",
    change=_bitwarden,
    revision="2",
)
YOUTUBE = Layout(
    slug="youtube",
    title="YouTube (NonSteamApps)",
    description="Steam's Gamepad layout, which VacuumTube reads as a controller, with View held to reload YouTube and refresh its home screen",
    base="controller_neptune_gamepad_joystick.vdf",
    change=_youtube,
)
LAYOUTS = (BITWARDEN, BROWSER, EMULATOR, FILES, JELLYFIN, LOCALSEND, MINECRAFT, TOOLS, YOUTUBE)


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


def _add(group: vdf.Pairs, button: str, bindings: List[str]) -> bool:
    for name, value in _find(group, "inputs") or []:
        if name == button:
            pairs = _find(_press(value), "bindings")
            if isinstance(pairs, list):
                pairs.extend(("binding", binding) for binding in bindings)
                return True
    return False


def _add_shift(shift: Shift, template: vdf.Pairs, targets: Dict[str, vdf.Pairs], body: vdf.Pairs, sources: vdf.Pairs) -> None:
    """Add ``shift``'s groups as mode shifts, and bind them to its button; leave the layout as it is when it has no such button."""
    switch_id = next((group_id for group_id, binding in sources if binding == "switch active"), None)
    switch = next((group for name, group in body if _find(group, "id") == switch_id), None)
    if switch is None or shift.button not in _inputs(switch):
        return
    groups = _active_groups(_mappings(template))
    bindings = []
    for source in shift.sources:
        if source not in targets or source not in groups:
            continue
        group = shift.change(source, copy.deepcopy(groups[source]), groups)
        group_id = str(len(sources))
        body.append(("group", [("id", group_id), *[(name, value) for name, value in group if name != "id"]]))
        sources.append((group_id, f"{source} active modeshift"))
        bindings.append(f"mode_shift {source} {group_id}")
    if bindings:
        _add(switch, shift.button, bindings)


def build(layout: Layout, base: vdf.Pairs, target: vdf.Pairs, shift: Optional[vdf.Pairs] = None) -> Optional[vdf.Pairs]:
    """``layout`` for the controller of Valve's Gamepad layout ``target``, from Valve's ``base`` layout, and ``shift``, the
    layout its mode shift comes from."""
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
    if layout.shift and shift is not None:
        _add_shift(layout.shift, shift, _active_groups(target_mappings), body, sources)
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
    try:
        shift = _read(directory / layout.shift.template) if layout.shift else None
    except (OSError, vdf.VdfError):
        shift = None
    written = []
    for kind, name in sorted(controllers.find_templates(root, "Gamepad").items()):
        if kind.startswith("controller_mobile"):
            continue
        try:
            built = build(layout, base, _read(directory / name), shift)
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
    for path in layout.retired(directory):
        path.unlink()
    return written


def remove(root: Path, layout: Layout) -> List[str]:
    """Delete the files :func:`install` wrote for ``layout``; return their names."""
    directory = controllers.templates_dir(root)
    removed = []
    for path in [*sorted(directory.glob(layout.file_name("controller_*"))), *layout.retired(directory)]:
        path.unlink()
        removed.append(path.name)
    return removed
