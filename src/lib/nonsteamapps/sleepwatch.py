"""Close an app before the Steam Machine sleeps or shuts down, while it runs in Game Mode.

Whatever puts the Steam Machine to sleep, Steam's menu, a short press of the power button, Steam's idle timer or the
TV turning off with Steam's HDMI-CEC setting, asks logind, which freezes the apps as they are: they carry on when the
device wakes, and a video app goes on playing. So while an app runs, a helper holds a logind delay lock for sleep
and shutdown, which any user may take, and follows logind's ``PrepareForSleep`` and ``PrepareForShutdown`` on the
system bus. When either says the device is about to sleep or shut down, the helper asks the app to quit with
SIGTERM, as a desktop's logout does, waits up to :data:`GRACE` seconds for it to save and close, and then lets the
lock go, so that logind goes on. logind waits for a delay lock for at most ``InhibitDelayMaxSec``, 5 seconds unless
SteamOS sets another.

SIGTERM goes to the app's own main process (see :func:`target`): bubblewrap, which runs each Flatpak, passes no
signal on, and neither does the shell of a start script. Chromium and Electron, like most programs, quit gracefully
on SIGTERM, and VacuumTube saves its settings as it quits. Which apps close is ``CLOSE_BEFORE_SLEEP``'s to say (see
:func:`applies`).
"""

from __future__ import annotations

import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from . import appmenu, config
from .apps import App
from .x11 import running

SETTING = "CLOSE_BEFORE_SLEEP"
LOGIN = "org.freedesktop.login1"
LOGIN_PATH = "/org/freedesktop/login1"
MANAGER = "org.freedesktop.login1.Manager"
MATCH = f"type='signal',sender='{LOGIN}',interface='{MANAGER}',path='{LOGIN_PATH}'"
ANNOUNCEMENTS = {"PrepareForSleep": "sleeps", "PrepareForShutdown": "shuts down"}
GRACE = 4.0
INTERVAL = 0.25
WRAPPERS = frozenset({"bwrap", "sh", "bash", "dash", "zypak-helper"})
PROC = Path("/proc")


def applies(value: Optional[str], app: App) -> bool:
    """Whether ``CLOSE_BEFORE_SLEEP``'s ``value`` closes ``app`` first: ``default``, as when unset, leaves it to each
    app (see :attr:`App.stays_open_in_sleep`); otherwise ``all``, ``off`` or a list of app IDs."""
    return config.covers(value, app.id, default=not app.stays_open_in_sleep)


def parents(proc: Path = PROC) -> Dict[int, int]:
    """Each process's parent, from ``/proc``."""
    found: Dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rpartition(")")[2].split()
        except OSError:
            continue
        if len(fields) > 1 and fields[1].isdigit():
            found[int(entry.name)] = int(fields[1])
    return found


def command_line(pid: int, proc: Path = PROC) -> List[str]:
    try:
        return (proc / str(pid) / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")[:-1]
    except OSError:
        return []


def program(pid: int, proc: Path = PROC) -> str:
    """The program ``pid`` runs, by the name it was started with, which for a script is its interpreter."""
    argv = command_line(pid, proc)
    if argv:
        return os.path.basename(argv[0])
    try:
        return (proc / str(pid) / "comm").read_text().strip()
    except OSError:
        return ""


def descends(pid: int, ancestor: int, tree: Mapping[int, int]) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = tree.get(pid, 0)
    return False


def sandbox(app_id: str, pid: int, tree: Mapping[int, int], flatpak: str = "flatpak") -> Optional[int]:
    """The first process in the sandbox of ``app_id``'s Flatpak that ``pid`` started, from ``flatpak ps``."""
    try:
        output = subprocess.run([flatpak, "ps", "--columns=pid,child-pid,application"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].isdigit() and fields[1].isdigit() and fields[2] == app_id \
                and descends(int(fields[0]), pid, tree):
            return int(fields[1])
    return None


def main_process(start: int, tree: Mapping[int, int], name: Callable[[int], str], skipped: Callable[[int], bool]) -> Optional[int]:
    """The process nearest ``start``, ``start`` included, whose program is not one of :data:`WRAPPERS`.

    A process ``skipped``, such as one of NonSteamApps' helpers, is passed over with its own processes.
    """
    children: Dict[int, List[int]] = {}
    for child, parent in sorted(tree.items()):
        children.setdefault(parent, []).append(child)
    queue = [start]
    while queue:
        current = queue.pop(0)
        if skipped(current):
            continue
        if name(current) not in WRAPPERS:
            return current
        queue.extend(children.get(current, []))
    return None


def target(pid: int, app_id: str, launcher: List[str], flatpak: str = "flatpak", proc: Path = PROC) -> Optional[int]:
    """The process to ask to quit: for a Flatpak, its main one in the sandbox ``pid`` started; otherwise the one ``pid``
    became, or the first under it. NonSteamApps' own processes share the launcher's command line, ``launcher``."""
    tree = parents(proc)
    start = sandbox(app_id, pid, tree, flatpak) if app_id else pid
    if start is None:
        return None
    return main_process(start, tree, lambda each: program(each, proc), lambda each: command_line(each, proc) == launcher)


def _lock(connection: appmenu.Connection, client: str) -> int:
    """A logind delay lock for sleep and shutdown, as the file descriptor that holds it."""
    body = appmenu.Writer().string("sleep:shutdown").string("NonSteamApps").string(f"Closes {client} first").string("delay").data
    reply = connection.call(LOGIN, LOGIN_PATH, MANAGER, "Inhibit", "ssss", bytes(body))
    fds = connection.take_fds()
    index = appmenu.uint32(reply)
    if index >= len(fds):
        for fd in fds:
            os.close(fd)
        raise OSError("logind sent no lock")
    lock = fds.pop(index)
    for fd in fds:
        os.close(fd)
    return lock


def announcement(message: appmenu.Message) -> Optional[str]:
    """What logind's signal says the device is about to do, ``sleeps`` or ``shuts down``, or ``None``."""
    member = message.fields.get(appmenu.MEMBER)
    if message.kind != appmenu.SIGNAL or message.fields.get(appmenu.INTERFACE) != MANAGER or member not in ANNOUNCEMENTS:
        return None
    try:
        return ANNOUNCEMENTS[member] if appmenu.uint32(message) else None
    except struct.error:
        return None


def close(pid: int, quitting: Optional[int], client: str, grace: float = GRACE, log: Callable[[str], None] = print) -> bool:
    """Ask ``quitting`` to quit and wait up to ``grace`` seconds for the app, ``pid``, to end; return whether it did."""
    if quitting is None:
        log(f"  {client} could not be found to close")
        return False
    try:
        os.kill(quitting, signal.SIGTERM)
    except OSError as exc:
        log(f"  could not close {client}: {exc}")
        return False
    deadline = time.monotonic() + grace
    while running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if running(pid):
        log(f"  {client} did not close within {grace:g} seconds")
        return False
    log(f"  closed {client}")
    return True


def follow(pid: int, app_id: str, client: str, launcher: List[str], environ: Mapping[str, str] = os.environ,
           grace: float = GRACE, flatpak: str = "flatpak", log: Callable[[str], None] = print, proc: Path = PROC) -> bool:
    """While ``pid`` runs, hold the lock and close the app when logind announces sleep or shutdown; return whether it did.

    ``app_id`` is the app's Flatpak, or empty for one that is not.
    """
    try:
        connection = appmenu.Connection(appmenu.system_bus(environ), unix_fds=True)
    except OSError as exc:
        log(f"  cannot close {client} before sleep: {exc}")
        return False
    lock = -1
    try:
        connection.bus("Hello")
        connection.bus("AddMatch", "s", bytes(appmenu.Writer().string(MATCH).data))
        lock = _lock(connection, client)
        connection.socket.settimeout(None)
        while running(pid):
            if not connection.pending and not select.select([connection.socket], [], [], INTERVAL)[0]:
                continue
            for message in connection.messages():
                about = announcement(message)
                if about:
                    log(f"  closing {client}: the Steam Machine {about}")
                    return close(pid, target(pid, app_id, launcher, flatpak, proc), client, grace, log)
        return False
    except (OSError, EOFError) as exc:
        log(f"  cannot close {client} before sleep: {exc}")
        return False
    finally:
        if lock >= 0:
            os.close(lock)
        connection.close()


def watch(pid: int, app: App, flatpak: str = "flatpak") -> int:
    """Start a helper process that closes ``app`` first whenever the device sleeps or shuts down while ``pid`` runs.

    Returns the helper's ID, or 0 when it cannot start. Its lines go to the app's log.
    """
    launcher = command_line(pid)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        child = os.fork()
    except OSError:
        return 0
    if child:
        return child
    try:
        follow(pid, app.flatpak, app.client, launcher, flatpak=flatpak, log=lambda line: print(line, flush=True))
    finally:
        os._exit(0)
