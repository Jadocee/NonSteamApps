"""Let go of a TV remote's key that the TV leaves pressed, while an app runs.

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
"""

from __future__ import annotations

import os
import select
import struct
import sys
import time
from typing import Callable, FrozenSet, Mapping, Optional, Tuple

from . import appmenu
from .x11 import running

SERVICE = "com.steampowered.CecDaemon1"
DAEMON_PATH = "/com/steampowered/CecDaemon1/Daemon"
CONFIG = "com.steampowered.CecDaemon1.Config1"
DEVICE = "com.steampowered.CecDaemon1.CecDevice1"
PROPERTIES = "org.freedesktop.DBus.Properties"
MATCH = f"type='signal',sender='{SERVICE}',interface='{DEVICE}'"
TIMEOUT = 2.0
UNREADABLE = (struct.error, ValueError, IndexError)


class Reader:
    """Reads D-Bus values from a message body, aligned from its start."""

    def __init__(self, data: bytes, order: str = "<") -> None:
        self.data, self.order, self.offset = data, order, 0

    def align(self, size: int) -> None:
        self.offset += -self.offset % size

    def _unpack(self, kind: str, size: int) -> int:
        self.align(size)
        (value,) = struct.unpack_from(self.order + kind, self.data, self.offset)
        self.offset += size
        return value

    def byte(self) -> int:
        return self._unpack("B", 1)

    def uint16(self) -> int:
        return self._unpack("H", 2)

    def uint32(self) -> int:
        return self._unpack("I", 4)

    def uint64(self) -> int:
        return self._unpack("Q", 8)

    def byte_array(self) -> bytes:
        length = self.uint32()
        if self.offset + length > len(self.data):
            raise struct.error("a byte array runs past the message")
        value = self.data[self.offset:self.offset + length]
        self.offset += length
        return bytes(value)

    def signature(self) -> str:
        length = self.byte()
        value = self.data[self.offset:self.offset + length].decode("ascii", "replace")
        self.offset += length + 1
        return value


def _variant(message: appmenu.Message, signature: str) -> Optional[Reader]:
    """A reader at the value of a reply to ``Get``, a variant, where that value has ``signature``."""
    reader = Reader(message.body, message.order)
    return reader if reader.signature() == signature else None


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
    reader = Reader(message.body, message.order)
    initiator, destination = reader.byte(), reader.byte()
    received = reader.uint64()
    return f"  CEC {received / 1e9:.3f} {initiator:x}>{destination:x}: {reader.byte_array().hex(' ')}"


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


def _handle(message: appmenu.Message, follower: Follower, now: float, log: Callable[[str], None]) -> None:
    if message.kind != appmenu.SIGNAL or message.fields.get(appmenu.INTERFACE) != DEVICE:
        return
    member = message.fields.get(appmenu.MEMBER)
    try:
        line = describe(message)
        button = Reader(message.body, message.order).byte_array() if member == "UserControlPressed" else None
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
           clock: Callable[[], float] = time.monotonic) -> Tuple[bool, int]:
    """Follow ``cecd``'s key signals while ``alive()``, and have it reload when a key it presses stays pressed for ``timeout``.

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
        ready()
        while alive():
            if connection.pending or select.select([connection.socket], [], [], interval)[0]:
                for message in connection.messages():
                    _handle(message, follower, clock(), log)
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


def watch(pid: int, timeout: float = TIMEOUT) -> int:
    """Start a helper process that follows the TV remote's keys while ``pid`` runs; return its ID, or 0 when it cannot start.

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
        follow(lambda: running(pid), timeout=timeout)
    finally:
        os._exit(0)
