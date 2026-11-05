"""Keep NonSteamApps' apps out of the status Steam shows friends.

While a non-Steam game runs, Steam tells friends the account is "In non-Steam game", with the game's name,
and Steam cannot mark a non-Steam game private: its Mark as Private is turned off for shortcuts. So while an
app started from Steam runs, NonSteamApps makes the account invisible with Steam's own
``steam://friends/status/invisible``, and once the last of its apps has closed, it sets back the status it
replaced, Online or Away. Friends see the account offline meanwhile, and chat still works. An account whose
chosen status, ``PersonaStateDesired`` in its ``localconfig.vdf``, is already Invisible or Offline is left
as it is.

The apps that run are kept in ``presence.json`` in NonSteamApps' state folder, with the status to set back,
so that the status returns only after the last of them, whichever closes first. An app that ended without a
word, as when its processes were killed, no longer counts at the next start. The status set back stays there
for a minute, for an app started in that time, before Steam may have saved it to ``localconfig.vdf``.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from . import steamclient, vdf

SETTING = "INVISIBLE_WHILE_RUNNING"
OFFLINE, ONLINE, AWAY, INVISIBLE = 0, 1, 3, 7
HIDDEN = (OFFLINE, INVISIBLE)
URL = "steam://friends/status/{}"
STATE_FILE = "presence.json"
POLL = 0.5
TIMEOUT = 20
RECENT = 60


def applies(value: Optional[str], app_id: str) -> bool:
    """Whether the setting's ``value`` covers ``app_id``: ``all``, the default, ``off``, or a list of app IDs."""
    text = (value if value is not None else "all").strip().lower()
    if text in ("all", "1", "on", "yes", "true"):
        return True
    if text in ("", "off", "0", "no", "none", "false"):
        return False
    return app_id.lower() in text.replace(",", " ").split()


def desired_state(localconfig: Path) -> Optional[int]:
    """The status the account last chose, kept in its ``localconfig.vdf``, or ``None`` when that does not say."""
    try:
        root = vdf.loads_text(Path(localconfig).read_text(encoding="utf-8", errors="replace"))
    except (OSError, vdf.VdfError):
        return None
    store = root.get("UserLocalConfigStore")
    friends = store.get("friends") if isinstance(store, vdf.KeyValues) else None
    value = friends.get("PersonaStateDesired") if isinstance(friends, vdf.KeyValues) else None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def status_name(state: Optional[int]) -> str:
    """The ``steam://friends/status`` command that sets ``state`` back: away for Away, otherwise online."""
    return "away" if state == AWAY else "online"


def started(pid: int) -> Optional[str]:
    """When process ``pid`` started, in clock ticks since boot, or ``None`` once it has ended."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        fields = text[text.rindex(")") + 2:].split()
    except (OSError, ValueError):
        return None
    return None if len(fields) < 20 or fields[0] in ("Z", "X") else fields[19]


class Presence:
    """The account's status while NonSteamApps' apps run, recorded in ``state``'s ``presence.json``.

    ``localconfig`` is the account's ``localconfig.vdf``, and ``steam`` the command that reaches the running
    client, by default :func:`steamclient.command`'s.
    """

    def __init__(self, state: Path, localconfig: Optional[Path], steam: Optional[str] = None) -> None:
        self.file = Path(state) / STATE_FILE
        self.localconfig = localconfig
        self.steam = steam

    def hide(self, pid: int) -> Tuple[bool, Optional[str]]:
        """Count ``pid`` among the apps that run; return whether its start makes the account invisible, and what to log.

        The first app to start while the account is visible makes it invisible, through :meth:`watch`; the
        others find it so.
        """
        with self._locked():
            record = self._load()
            running = self._running(record)
            invisible, message = False, None
            if not record.get("changed"):
                if time.time() - float(record.get("restored", 0)) < RECENT:
                    previous = record.get("previous")
                else:
                    previous = desired_state(self.localconfig) if self.localconfig else None
                if previous in HIDDEN:
                    message = "the Steam account is already invisible or offline, so friends cannot see the app"
                elif not (self.steam or steamclient.command()):
                    message = "the steam command was not found, so friends see the app"
                else:
                    invisible = True
                    message = "making the Steam account invisible, so friends do not see the app; its status comes back when the apps close"
                record = {"previous": previous, "changed": invisible}
            begun = started(pid)
            record["apps"] = running + ([{"pid": pid, "start": begun}] if begun else [])
            self._save(record)
            return invisible, message

    def release(self, pid: int) -> Optional[str]:
        """Stop counting ``pid`` and, once no app runs, set back the status that :meth:`hide` replaced; return what was done."""
        with self._locked():
            record = self._load()
            running = [app for app in self._running(record) if app["pid"] != pid]
            if running:
                record["apps"] = running
                self._save(record)
                return None
            if not record.get("changed"):
                self.file.unlink(missing_ok=True)
                return None
            name = status_name(record.get("previous"))
            sent = self.send(name)
            self._save({"previous": record.get("previous"), "changed": False, "restored": time.time()})
            return f"set the Steam account back to {name}" if sent else f"could not set the Steam account back to {name}"

    def watch(self, pid: int, invisible: bool) -> int:
        """Start a process that makes the account invisible when asked, then calls :meth:`release` once ``pid`` has ended.

        It also ends when Steam stops the app, which signals every process the app started. The app starts
        meanwhile, without waiting for Steam. Returns the process's ID.
        """
        child = os.fork()
        if child:
            return child
        try:
            stopping: List[int] = []
            for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(number, lambda received, frame: stopping.append(received))
            begun = started(pid)
            if invisible and not self.send("invisible"):
                print("  could not reach Steam to make the account invisible; friends see the app", flush=True)
            while begun and not stopping and started(pid) == begun:
                time.sleep(POLL)
            message = self.release(pid)
            if message:
                print(f"  {message}", flush=True)
        finally:
            os._exit(0)

    def send(self, name: str) -> bool:
        """Set the account's status with ``steam://friends/status/<name>``, sent only to a Steam that runs."""
        steam = self.steam or steamclient.command()
        if not steam:
            return False
        try:
            return subprocess.run([steam, "-ifrunning", URL.format(name)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=TIMEOUT, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _running(record: dict) -> List[dict]:
        return [app for app in record.get("apps", []) if isinstance(app, dict) and started(int(app.get("pid", 0))) == app.get("start")]

    def _load(self) -> dict:
        try:
            record = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return record if isinstance(record, dict) else {}

    def _save(self, record: dict) -> None:
        partial = self.file.with_name(self.file.name + ".new")
        partial.write_text(json.dumps(record) + "\n", encoding="utf-8")
        os.replace(partial, self.file)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file.with_name(self.file.name + ".lock"), "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
