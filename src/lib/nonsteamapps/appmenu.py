"""Stand in for a desktop's global menu, so that an Electron app draws no menu bar in its window.

On X11, Electron moves an app's menu into the desktop's global menu, and draws no menu bar in the window,
when a program owns ``com.canonical.AppMenu.Registrar`` on the session bus and libdbusmenu loads. Its
keyboard shortcuts keep working. Bitwarden has no setting that hides its menu bar, and shows it again
whenever its window is shown; Signal shows its bar unless told otherwise, and Element's hidden bar opens on
a lone Alt release, which Element's own Alt shortcuts can leave unpaired. So in Game Mode NonSteamApps owns
that name while one of them runs. It answers the two calls an app makes, ``RegisterWindow`` and
``UnregisterWindow``, and shows nothing.

This speaks just enough of the D-Bus wire protocol, with the standard library, to own the name.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import urllib.parse
from typing import Callable, Dict, List, Mapping, NamedTuple, Optional

from .x11 import running

REGISTRAR = "com.canonical.AppMenu.Registrar"
BUS = "org.freedesktop.DBus"
BUS_PATH = "/org/freedesktop/DBus"
METHOD_CALL, METHOD_RETURN, ERROR, SIGNAL = 1, 2, 3, 4
NO_REPLY_EXPECTED = 1
DO_NOT_QUEUE = 4
PRIMARY_OWNER = 1
PATH, INTERFACE, MEMBER, ERROR_NAME, REPLY_SERIAL, DESTINATION, SENDER, SIGNATURE = range(1, 9)
FIELD_TYPES = {PATH: "o", INTERFACE: "s", MEMBER: "s", ERROR_NAME: "s", REPLY_SERIAL: "u", DESTINATION: "s", SENDER: "s", SIGNATURE: "g"}
ANSWERED = ("RegisterWindow", "UnregisterWindow")
MAX_MESSAGE = 1 << 20


class Message(NamedTuple):
    kind: int
    flags: int
    serial: int
    fields: Dict[int, object]
    body: bytes
    order: str


class Writer:
    """Marshals D-Bus values, little-endian, aligned from the start of what it writes."""

    def __init__(self) -> None:
        self.data = bytearray()

    def pad(self, size: int) -> None:
        self.data += bytes(-len(self.data) % size)

    def byte(self, value: int) -> "Writer":
        self.data.append(value)
        return self

    def uint32(self, value: int) -> "Writer":
        self.pad(4)
        self.data += struct.pack("<I", value)
        return self

    def string(self, value: str) -> "Writer":
        encoded = value.encode()
        self.uint32(len(encoded))
        self.data += encoded + b"\0"
        return self

    def signature(self, value: str) -> "Writer":
        encoded = value.encode()
        self.byte(len(encoded))
        self.data += encoded + b"\0"
        return self

    def value(self, kind: str, value) -> "Writer":
        if kind == "u":
            return self.uint32(value)
        if kind == "g":
            return self.signature(value)
        return self.string(value)


def encode(kind: int, serial: int, fields: Mapping[int, object], body: bytes = b"", flags: int = 0) -> bytes:
    """A message whose ``body`` was marshalled from an 8-byte boundary, as a :class:`Writer` does."""
    writer = Writer()
    writer.data += bytes((ord("l"), kind, flags, 1))
    writer.uint32(len(body)).uint32(serial).uint32(0)
    for code, value in fields.items():
        writer.pad(8)
        writer.byte(code).signature(FIELD_TYPES[code]).value(FIELD_TYPES[code], value)
    struct.pack_into("<I", writer.data, 12, len(writer.data) - 16)
    writer.pad(8)
    return bytes(writer.data) + body


def decode(data: bytes) -> Optional[Message]:
    """The first whole message in ``data``, or ``None`` while it is still arriving; its length is :func:`size`."""
    total = size(data)
    if total is None or len(data) < total:
        return None
    order = "<" if data[0] == ord("l") else ">"
    _, serial, fields_length = struct.unpack_from(order + "III", data, 4)
    end = 16 + fields_length
    fields: Dict[int, object] = {}
    offset = 16
    while offset < end:
        offset += -offset % 8
        code, length = data[offset], data[offset + 1]
        kind = data[offset + 2:offset + 2 + length].decode("ascii", "replace")
        offset += length + 3
        if kind in ("s", "o"):
            offset += -offset % 4
            (length,) = struct.unpack_from(order + "I", data, offset)
            value: object = data[offset + 4:offset + 4 + length].decode("utf-8", "replace")
            offset += length + 5
        elif kind == "u":
            offset += -offset % 4
            (value,) = struct.unpack_from(order + "I", data, offset)
            offset += 4
        elif kind == "g":
            length = data[offset]
            value = data[offset + 1:offset + 1 + length].decode("ascii", "replace")
            offset += length + 2
        else:
            break
        fields[code] = value
    return Message(data[1], data[2], serial, fields, bytes(data[end + (-end % 8):total]), order)


def size(data: bytes) -> Optional[int]:
    """The length of the message at the start of ``data``, once its fixed header has arrived."""
    if len(data) < 16:
        return None
    if data[0] not in (ord("l"), ord("B")):
        raise ValueError("not a D-Bus message")
    order = "<" if data[0] == ord("l") else ">"
    body_length, _, fields_length = struct.unpack_from(order + "III", data, 4)
    end = 16 + fields_length
    total = end + (-end % 8) + body_length
    if total > MAX_MESSAGE:
        raise ValueError("a D-Bus message too large for a stand-in")
    return total


def uint32(message: Message) -> int:
    """The first value of a reply whose body starts with a ``u``."""
    return struct.unpack_from(message.order + "I", message.body)[0]


def session_bus(environ: Mapping[str, str]) -> Optional[str]:
    """The session bus's socket: a path, or an abstract name that starts with a NUL."""
    for entry in environ.get("DBUS_SESSION_BUS_ADDRESS", "").split(";"):
        transport, _, parameters = entry.partition(":")
        if transport != "unix":
            continue
        options = dict(part.partition("=")[::2] for part in parameters.split(","))
        if options.get("path"):
            return urllib.parse.unquote(options["path"])
        if options.get("abstract"):
            return "\0" + urllib.parse.unquote(options["abstract"])
    runtime = environ.get("XDG_RUNTIME_DIR")
    return os.path.join(runtime, "bus") if runtime else None


class Connection:
    """An authenticated connection to a bus, through which messages are sent and read."""

    def __init__(self, address: str, timeout: float = 2.0) -> None:
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.serial = 0
        self.buffer = b""
        try:
            self.socket.connect(address)
            self._authenticate()
        except BaseException:
            self.socket.close()
            raise

    def _authenticate(self) -> None:
        self.socket.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        line = b""
        while not line.endswith(b"\r\n") and len(line) < 512:
            chunk = self.socket.recv(1)
            if not chunk:
                break
            line += chunk
        if not line.startswith(b"OK "):
            raise OSError(f"the session bus refused to authenticate: {line.strip()!r}")
        self.socket.sendall(b"BEGIN\r\n")

    def close(self) -> None:
        self.socket.close()

    def send(self, kind: int, fields: Mapping[int, object], body: bytes = b"", flags: int = 0) -> int:
        self.serial += 1
        self.socket.sendall(encode(kind, self.serial, fields, body, flags))
        return self.serial

    def messages(self) -> List[Message]:
        """Read from the bus once, waiting up to the timeout, and return the whole messages that have arrived."""
        chunk = self.socket.recv(65536)
        if not chunk:
            raise EOFError("the session bus closed the connection")
        self.buffer += chunk
        found = []
        while True:
            message = decode(self.buffer)
            if message is None:
                return found
            self.buffer = self.buffer[size(self.buffer):]
            found.append(message)

    def call(self, destination: str, path: str, interface: str, member: str, signature: str = "", body: bytes = b"") -> Message:
        """Call a method and wait for its reply; an error reply raises :class:`OSError`."""
        fields = {PATH: path, INTERFACE: interface, MEMBER: member, DESTINATION: destination}
        if signature:
            fields[SIGNATURE] = signature
        serial = self.send(METHOD_CALL, fields, body)
        while True:
            for message in self.messages():
                if message.fields.get(REPLY_SERIAL) == serial:
                    if message.kind == ERROR:
                        raise OSError(f"{member} failed: {message.fields.get(ERROR_NAME)}")
                    return message

    def bus(self, member: str, signature: str = "", body: bytes = b"") -> Message:
        return self.call(BUS, BUS_PATH, BUS, member, signature, body)


def answer(connection: Connection, message: Message) -> None:
    """Reply to a call to the stand-in: an empty reply to the calls apps make, and an error to anything else."""
    if message.kind != METHOD_CALL or message.flags & NO_REPLY_EXPECTED or SENDER not in message.fields:
        return
    fields: Dict[int, object] = {REPLY_SERIAL: message.serial, DESTINATION: message.fields[SENDER]}
    if message.fields.get(MEMBER) in ANSWERED:
        connection.send(METHOD_RETURN, fields)
        return
    fields.update({ERROR_NAME: "org.freedesktop.DBus.Error.UnknownMethod", SIGNATURE: "s"})
    connection.send(ERROR, fields, bytes(Writer().string("NonSteamApps only stands in for the global menu").data))


def stand_in(alive: Callable[[], bool], ready: Callable[[], None] = lambda: None, environ: Mapping[str, str] = os.environ,
             interval: float = 0.25) -> bool:
    """Own the registrar's name while ``alive()``; return ``False`` at once when there is no bus or another program owns it."""
    address = session_bus(environ)
    if not address:
        return False
    try:
        connection = Connection(address)
    except (OSError, ValueError):
        return False
    try:
        connection.bus("Hello")
        if uint32(connection.bus("RequestName", "su", bytes(Writer().string(REGISTRAR).uint32(DO_NOT_QUEUE).data))) != PRIMARY_OWNER:
            return False
        ready()
        while alive():
            if select.select([connection.socket], [], [], interval)[0]:
                for message in connection.messages():
                    answer(connection, message)
        return True
    except (OSError, EOFError, ValueError, struct.error):
        return False
    finally:
        connection.close()


def watch(pid: int, timeout: float = 2.0) -> bool:
    """Start a helper process that stands in for the global menu while ``pid`` runs; return whether it does.

    The launcher calls it with its own ID just before it becomes the app. It waits until the helper owns
    the name, because Electron looks for the global menu only when the app sets its menu, as it starts.
    """
    reader, writer = os.pipe()
    if os.fork():
        os.close(writer)
        try:
            ready = select.select([reader], [], [], timeout)[0] and os.read(reader, 1) == b"1"
        finally:
            os.close(reader)
        return bool(ready)
    os.close(reader)
    try:
        stand_in(lambda: running(pid), lambda: os.write(writer, b"1"))
    finally:
        os._exit(0)
