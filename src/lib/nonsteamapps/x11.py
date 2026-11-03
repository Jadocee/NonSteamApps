"""Ask for an app's windows to be full screen, which gamescope needs before it gives a window the whole screen.

In Game Mode, gamescope gives a window that Steam started the screen's size only when the window is full screen.
Any other window keeps the size it asked for, and is scaled to fit with black bars; gamescope ignores requests to
maximise. Chromium makes a window one pixel smaller than the screen size it is given, but a full-screen request
from another program makes it fill the screen while it keeps its tabs and address bar. This sends that request,
as a desktop's window list would, to the windows of one ``WM_CLASS``, through libX11 with ctypes.
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set, Tuple

IS_VIEWABLE = 2
CLIENT_MESSAGE = 33
SUBSTRUCTURE_NOTIFY = 1 << 19
SUBSTRUCTURE_REDIRECT = 1 << 20
ADD = 1
FROM_APPLICATION = 1

Window = Tuple[int, str, str, bool]


class ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class Event(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xclient", ClientMessage), ("pad", ctypes.c_long * 24)]


class ClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class Attributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int), ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


ErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_ignore_errors = ErrorHandler(lambda display, error: 0)


def library() -> Optional[ctypes.CDLL]:
    """libX11 with the functions used here, or ``None`` where it cannot be loaded."""
    try:
        lib = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None
    signatures = {
        "XOpenDisplay": (ctypes.c_void_p, [ctypes.c_char_p]),
        "XCloseDisplay": (ctypes.c_int, [ctypes.c_void_p]),
        "XDefaultRootWindow": (ctypes.c_ulong, [ctypes.c_void_p]),
        "XInternAtom": (ctypes.c_ulong, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]),
        "XQueryTree": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                      ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint)]),
        "XGetClassHint": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ClassHint)]),
        "XGetWindowAttributes": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Attributes)]),
        "XSendEvent": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(Event)]),
        "XSync": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int]),
        "XFree": (ctypes.c_int, [ctypes.c_void_p]),
        "XSetErrorHandler": (ctypes.c_void_p, [ErrorHandler]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
    return lib


class Display:
    """A connection to an X server, by default the one in ``DISPLAY``; use it in a ``with`` block."""

    def __init__(self, lib: ctypes.CDLL, name: Optional[str] = None) -> None:
        self.lib = lib
        lib.XSetErrorHandler(_ignore_errors)
        self.handle = lib.XOpenDisplay(name.encode() if name else None)
        if not self.handle:
            raise OSError(f"cannot open the X display {name or os.environ.get('DISPLAY', '')!r}")
        self.root = lib.XDefaultRootWindow(self.handle)

    def __enter__(self) -> "Display":
        return self

    def __exit__(self, *exc) -> None:
        self.lib.XCloseDisplay(self.handle)

    def _text(self, pointer: Optional[int]) -> str:
        if not pointer:
            return ""
        text = ctypes.string_at(pointer).decode("utf-8", "replace")
        self.lib.XFree(pointer)
        return text

    def windows(self) -> List[Window]:
        """The root's child windows: their ID, ``WM_CLASS`` name and class, and whether they are shown and managed."""
        root, parent = ctypes.c_ulong(), ctypes.c_ulong()
        children, count = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not self.lib.XQueryTree(self.handle, self.root, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count)):
            return []
        ids = [children[index] for index in range(count.value)]
        if children:
            self.lib.XFree(children)
        found = []
        for window in ids:
            hint, attributes = ClassHint(), Attributes()
            if not self.lib.XGetClassHint(self.handle, window, ctypes.byref(hint)):
                continue
            name, kind = self._text(hint.res_name), self._text(hint.res_class)
            shown = bool(self.lib.XGetWindowAttributes(self.handle, window, ctypes.byref(attributes)))
            found.append((window, name, kind, shown and attributes.map_state == IS_VIEWABLE and not attributes.override_redirect))
        return found

    def fullscreen(self, window: int) -> None:
        """Ask the window manager to make ``window`` full screen (an EWMH ``_NET_WM_STATE`` request)."""
        event = Event()
        message = event.xclient
        message.type, message.window, message.format = CLIENT_MESSAGE, window, 32
        message.message_type = self.lib.XInternAtom(self.handle, b"_NET_WM_STATE", 0)
        message.data[0] = ADD
        message.data[1] = self.lib.XInternAtom(self.handle, b"_NET_WM_STATE_FULLSCREEN", 0)
        message.data[3] = FROM_APPLICATION
        self.lib.XSendEvent(self.handle, self.root, 0, SUBSTRUCTURE_NOTIFY | SUBSTRUCTURE_REDIRECT, ctypes.byref(event))
        self.lib.XSync(self.handle, 0)


def matching(windows: Iterable[Window], wm_class: str, done: Set[int]) -> List[int]:
    """The shown windows of ``wm_class`` (as ``WM_CLASS`` name or class) not yet made full screen."""
    return [window for window, name, kind, shown in windows if shown and wm_class in (name, kind) and window not in done]


def running(pid: int) -> bool:
    """Whether the process ``pid`` exists and has not exited."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
    except OSError:
        return False
    return bool(state) and state[0] not in ("Z", "X")


def keep_fullscreen(wm_class: str, alive: Callable[[], bool], interval: float = 0.25, display: Optional[str] = None) -> int:
    """Make each new window of ``wm_class`` full screen while ``alive()``; return how many were."""
    lib = library()
    if lib is None:
        return 0
    done: Set[int] = set()
    try:
        with Display(lib, display) as connection:
            while alive():
                for window in matching(connection.windows(), wm_class, done):
                    connection.fullscreen(window)
                    done.add(window)
                time.sleep(interval)
    except OSError:
        pass
    return len(done)


def watch(wm_class: str, pid: int) -> None:
    """Start a helper process that makes the windows of ``wm_class`` full screen while ``pid`` runs.

    The launcher calls it with its own ID just before it becomes the app, and for a browser it starts.
    """
    if os.fork():
        return
    try:
        keep_fullscreen(wm_class, lambda: running(pid))
    finally:
        os._exit(0)
