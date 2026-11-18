"""Follow the TV's HDMI-CEC messages while an app runs: let go of a remote key the TV leaves pressed, and pause the
app when the TV switches away from the Steam Machine or turns off.

Valve's ``cecd`` holds a key of its virtual keyboard down from each ``<User Control Pressed>`` until the TV's
``<User Control Released>`` or its next press, however long that takes (see :mod:`remote`). A TV repeats the press
while a button is held, and Linux's own CEC input lets a key go 550 milliseconds after the last press. A TV that opens
its own Home or Assistant can leave a press without its release; Steam then repeats the key, with its navigation
sound, until something resets it. So while an app runs in Game Mode, a helper follows ``cecd``'s
``UserControlPressed`` and ``UserControlReleased`` signals on the session bus. When a key stays pressed for
:data:`TIMEOUT`, well past those 550 milliseconds, with neither a repeat nor a release, and ``cecd`` presses a key of
its keyboard for it, the helper has ``cecd`` reload, which makes its keyboard again, so that the held key is let go.
It never starts a ``cecd`` that is not running. It also writes each message ``cecd`` receives to the app's log, with
the time the kernel received it, for what the TV sends to be seen.

``cecd`` signals each message it receives with ``ReceivedMessage``. When one shows that the TV no longer shows the
Steam Machine, because the TV switched to another input or to its own apps, another device took over, or the TV is
turning off (see :func:`departure`), the helper pauses the app's own media players (see :mod:`mpris`), as
``PAUSE_WHEN_TV_SWITCHES`` says (see :func:`pauses`). Nothing resumes by itself. ``cecd`` keeps an ``Active``
property of its own, but it takes a route through an AV receiver for one elsewhere and signals only its changes, so
the helper judges each message itself, against the Steam Machine's physical address.
"""

from __future__ import annotations

import os
import select
import sys
import time
from typing import Callable, FrozenSet, Mapping, Optional, Tuple

from . import appmenu, config, mpris
from .apps import App
from .x11 import running

SERVICE = "com.steampowered.CecDaemon1"
DAEMON_PATH = "/com/steampowered/CecDaemon1/Daemon"
CONFIG = "com.steampowered.CecDaemon1.Config1"
DEVICE = "com.steampowered.CecDaemon1.CecDevice1"
PROPERTIES = "org.freedesktop.DBus.Properties"
MATCH = f"type='signal',sender='{SERVICE}',interface='{DEVICE}'"
TIMEOUT = 2.0
UNREADABLE = appmenu.UNREADABLE
SETTING = "PAUSE_WHEN_TV_SWITCHES"
STANDBY, ROUTING_CHANGE, ROUTING_INFORMATION, ACTIVE_SOURCE, SET_STREAM_PATH = 0x36, 0x80, 0x81, 0x82, 0x86
ROUTING = frozenset({ROUTING_CHANGE, ROUTING_INFORMATION, ACTIVE_SOURCE, SET_STREAM_PATH})
TV, AUDIO_SYSTEM = 0, 5
NO_ADDRESS = 0xFFFF


def pauses(value: Optional[str], app: App) -> bool:
    """Whether ``PAUSE_WHEN_TV_SWITCHES``'s ``value`` pauses ``app`` when the TV switches away: ``default``, as when
    unset, pauses the apps that play video or music (see :attr:`App.plays_media`); otherwise ``all``, ``off`` or a
    list of app IDs."""
    return config.covers(value, app.id, default=app.plays_media)


def _variant(message: appmenu.Message, signature: str) -> Optional[appmenu.Reader]:
    """A reader at the value of a reply to ``Get``, a variant, where that value has ``signature``."""
    return appmenu.Reader.of(message).variant(signature)


def mapped_buttons(message: appmenu.Message) -> Optional[FrozenSet[bytes]]:
    """The UI commands ``cecd`` maps to keys, from the reply to a ``Get`` of its ``Mappings`` (``a(ayq)``)."""
    reader = _variant(message, "a(ayq)")
    if reader is None:
        return None
    length = reader.uint32()
    reader.align(8)
    end = reader.offset + length
    found = set()
    while reader.offset < end:
        reader.align(8)
        found.add(reader.byte_array())
        reader.uint16()
    return frozenset(found)


def switched_on(message: appmenu.Message) -> Optional[bool]:
    """A ``b`` property, such as ``Uinput``, whether ``cecd`` has a keyboard, from the reply to a ``Get`` of it."""
    reader = _variant(message, "b")
    return None if reader is None else bool(reader.uint32())


def describe(message: appmenu.Message) -> Optional[str]:
    """A line for the log about a message ``cecd`` received, timed in seconds as the kernel times it, or ``None`` for another signal."""
    if message.fields.get(appmenu.MEMBER) != "ReceivedMessage":
        return None
    reader = appmenu.Reader.of(message)
    initiator, destination = reader.byte(), reader.byte()
    received = reader.uint64()
    return f"  CEC {received / 1e9:.3f} {initiator:x}>{destination:x}: {reader.byte_array().hex(' ')}"


def address_text(address: int) -> str:
    """A physical address as CEC writes it, such as ``2.0.0.0``: the first number is the TV's HDMI input."""
    return ".".join(format((address >> shift) & 0xF, "x") for shift in (12, 8, 4, 0))


def _steps(address: int) -> Tuple[int, ...]:
    return tuple((address >> shift) & 0xF for shift in (12, 8, 4, 0))


def leads_to(route: int, address: int) -> bool:
    """Whether a route to physical address ``route`` shows the device at ``address``: it ends there, or at a switch on
    the way, such as an AV receiver, which passes the picture on. A route to the TV itself, ``0.0.0.0``, shows the
    TV's own apps."""
    if NO_ADDRESS in (route, address) or route == 0:
        return False
    if route == address:
        return True
    steps = _steps(route)
    depth = max(index for index, step in enumerate(steps) if step) + 1
    return steps[:depth] == _steps(address)[:depth]


def _who(initiator: int) -> str:
    return {TV: "the TV", AUDIO_SYSTEM: "the audio system"}.get(initiator, f"device {initiator:x}")


def _place(route: int) -> str:
    return "its own apps" if route == 0 else address_text(route)


def departure(initiator: int, data: bytes, address: Optional[int]) -> Optional[str]:
    """Why a message ``cecd`` received means the TV no longer shows the device at physical ``address``, or ``None``.

    ``data`` is the message, its opcode first, sent by logical address ``initiator``. ``<Standby>`` always counts. The
    others need ``address``, and count when they take the picture elsewhere: another device's ``<Active Source>``, a
    ``<Set Stream Path>`` or the TV's ``<Routing Change>`` to a route that does not lead to the device, a switch's
    ``<Routing Change>`` away from it, and a switch's ``<Routing Information>`` for a route on the device's own HDMI
    input that leads elsewhere.
    """
    if not data:
        return None
    opcode, operands = data[0], data[1:]
    if opcode == STANDBY:
        return "the TV is turning off" if initiator == TV else f"{_who(initiator)} asked for standby"
    if address is None or opcode not in ROUTING or len(operands) < (4 if opcode == ROUTING_CHANGE else 2):
        return None
    route = operands[0] << 8 | operands[1]
    if opcode == ACTIVE_SOURCE:
        if route == address:
            return None
        return "the TV switched to its own apps" if route == 0 else f"the device at {address_text(route)} took over the TV"
    if opcode == SET_STREAM_PATH:
        return None if leads_to(route, address) else f"the TV switched to {_place(route)}"
    if opcode == ROUTING_CHANGE:
        new = operands[2] << 8 | operands[3]
        if leads_to(new, address) or (initiator != TV and not leads_to(route, address)):
            return None
        return f"{_who(initiator)} switched to {_place(new)}"
    if leads_to(route, address) or _steps(route)[0] != _steps(address)[0]:
        return None
    return f"{_who(initiator)} switched to {_place(route)}"


class Follower:
    """The key the TV holds: refreshed by each press, cleared by a release, and due once it is held :data:`TIMEOUT`."""

    def __init__(self, timeout: float = TIMEOUT) -> None:
        self.timeout = timeout
        self.held: Optional[bytes] = None
        self.since = 0.0

    def press(self, button: bytes, now: float) -> None:
        self.held, self.since = button, now

    def release(self) -> None:
        self.held = None

    def due(self, now: float) -> Optional[bytes]:
        """The key held for the timeout, once: it is not due again until it is pressed again."""
        if self.held is None or now - self.since < self.timeout:
            return None
        held, self.held = self.held, None
        return held


def _print(line: str) -> None:
    print(line, flush=True)


def _get(connection: appmenu.Connection, name: str) -> appmenu.Message:
    body = bytes(appmenu.Writer().string(CONFIG).string(name).data)
    return connection.call(SERVICE, DAEMON_PATH, PROPERTIES, "Get", "ss", body, appmenu.NO_AUTO_START)


def _presses_key(connection: appmenu.Connection, button: bytes) -> Optional[bool]:
    """Whether ``cecd`` presses a key of its keyboard for ``button``, or ``None`` when it cannot tell."""
    try:
        keyboard = switched_on(_get(connection, "Uinput"))
        mapped = mapped_buttons(_get(connection, "Mappings"))
    except (OSError, *UNREADABLE):
        return None
    if keyboard is False:
        return False
    return None if mapped is None else button in mapped


def _physical_address(connection: appmenu.Connection, path: object) -> Optional[int]:
    """The physical address of ``cecd``'s device at ``path``, :data:`NO_ADDRESS` while it has none, or ``None`` when
    ``cecd`` does not say."""
    if not isinstance(path, str):
        return None
    body = bytes(appmenu.Writer().string(DEVICE).string("PhysicalAddress").data)
    try:
        reader = _variant(connection.call(SERVICE, path, PROPERTIES, "Get", "ss", body, appmenu.NO_AUTO_START), "q")
        return None if reader is None else reader.uint16()
    except (OSError, *UNREADABLE):
        return None


def _departure(connection: appmenu.Connection, message: appmenu.Message) -> Optional[str]:
    """Why a ``ReceivedMessage`` signal means the TV no longer shows the Steam Machine, if it does; ``cecd`` is asked
    for the device's address only for a message that needs it."""
    if message.kind != appmenu.SIGNAL or message.fields.get(appmenu.INTERFACE) != DEVICE \
            or message.fields.get(appmenu.MEMBER) != "ReceivedMessage":
        return None
    try:
        reader = appmenu.Reader.of(message)
        initiator = reader.byte()
        reader.byte()
        reader.uint64()
        data = reader.byte_array()
    except UNREADABLE:
        return None
    address = _physical_address(connection, message.fields.get(appmenu.PATH)) if data[:1] and data[0] in ROUTING else None
    return departure(initiator, data, address)


def _handle(message: appmenu.Message, follower: Follower, now: float, log: Callable[[str], None]) -> None:
    if message.kind != appmenu.SIGNAL or message.fields.get(appmenu.INTERFACE) != DEVICE:
        return
    member = message.fields.get(appmenu.MEMBER)
    try:
        line = describe(message)
        button = appmenu.Reader.of(message).byte_array() if member == "UserControlPressed" else None
    except UNREADABLE:
        return
    if line:
        log(line)
    if button is not None:
        follower.press(button, now)
    elif member == "UserControlReleased":
        follower.release()


def follow(alive: Callable[[], bool], ready: Callable[[], None] = lambda: None, environ: Mapping[str, str] = os.environ,
           log: Callable[[str], None] = _print, timeout: float = TIMEOUT, interval: float = 0.25,
           clock: Callable[[], float] = time.monotonic, players: Optional[mpris.Players] = None) -> Tuple[bool, int]:
    """Follow ``cecd``'s signals while ``alive()``, and have it reload when a key it presses stays pressed for ``timeout``.

    With ``players``, the app's, also pause them when a message shows that the TV no longer shows the Steam Machine.
    ``ready()`` is called once the signals are followed. Returns whether they were followed until ``alive()`` turned
    false, and how many times ``cecd`` was made to let a key go.
    """
    address = appmenu.session_bus(environ)
    if not address:
        log("  cannot follow the TV remote's keys: there is no session bus")
        return False, 0
    try:
        connection = appmenu.Connection(address)
    except (OSError, ValueError) as exc:
        log(f"  cannot follow the TV remote's keys: {exc}")
        return False, 0
    follower, freed = Follower(timeout), 0
    try:
        connection.bus("Hello")
        connection.bus("AddMatch", "s", bytes(appmenu.Writer().string(MATCH).data))
        log("  following the TV remote's keys, to let go of one the TV leaves pressed")
        if players is not None:
            log(f"  following the TV's input, to pause {players.client} when the TV switches away or turns off")
        ready()
        while alive():
            if connection.pending or select.select([connection.socket], [], [], interval)[0]:
                for message in connection.messages():
                    _handle(message, follower, clock(), log)
                    if players is not None:
                        reason = _departure(connection, message)
                        if reason:
                            players.pause(connection, reason, log)
            held = follower.due(clock())
            if held is None:
                continue
            if _presses_key(connection, held) is False:
                log(f"  the TV left {held.hex(' ')} pressed, for which cecd presses no key")
                continue
            log(f"  the TV left {held.hex(' ')} pressed without letting go; cecd reloads to let its key go")
            try:
                connection.call(SERVICE, DAEMON_PATH, CONFIG, "Reload", flags=appmenu.NO_AUTO_START)
                freed += 1
            except OSError as exc:
                log(f"  cecd could not reload: {exc}")
        return True, freed
    except (OSError, EOFError, *UNREADABLE) as exc:
        log(f"  stopped following the TV remote's keys: {exc}")
        return False, freed
    finally:
        connection.close()


def watch(pid: int, timeout: float = TIMEOUT, pausing: Optional[str] = None) -> int:
    """Start a helper process that follows ``cecd``'s signals while ``pid`` runs; return its ID, or 0 when it cannot start.

    With ``pausing``, the app's name, the helper also pauses the app's players when the TV switches away or turns off.
    Its lines go where the launcher's output goes: the app's log.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        child = os.fork()
    except OSError:
        return 0
    if child:
        return child
    try:
        follow(lambda: running(pid), timeout=timeout, players=mpris.Players(pid, pausing) if pausing else None)
    finally:
        os._exit(0)
