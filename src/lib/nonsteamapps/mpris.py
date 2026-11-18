"""Pause the media players an app publishes on the session bus.

An app that plays video or music, such as VacuumTube, Jellyfin, VLC or Helium, publishes an MPRIS player on the
session bus while it runs: a name under ``org.mpris.MediaPlayer2.``, through which a desktop's media keys pause it.
The bus knows the process behind each name: the app's own, or for a Flatpak the ``xdg-dbus-proxy`` that
``flatpak run`` starts beside the app. Either runs under the process the launcher became, so an app's players are
those whose process descends from the launcher's, and another program's player is never touched. A player is asked
to pause only while it says it plays, so a second reason to pause changes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from . import appmenu
from .proctree import PROC, descends, parents

PREFIX = "org.mpris.MediaPlayer2."
OBJECT = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPERTIES = "org.freedesktop.DBus.Properties"


def status(connection: appmenu.Connection, name: str) -> Optional[str]:
    """What player ``name`` says it does, ``Playing``, ``Paused`` or ``Stopped``, or ``None`` when it does not say."""
    body = bytes(appmenu.Writer().string(PLAYER).string("PlaybackStatus").data)
    try:
        reply = connection.call(name, OBJECT, PROPERTIES, "Get", "ss", body, appmenu.NO_AUTO_START)
        reader = appmenu.Reader.of(reply).variant("s")
        return None if reader is None else reader.string()
    except (OSError, *appmenu.UNREADABLE):
        return None


class Players:
    """The media players of the app that process ``pid`` became, called ``client``, which :meth:`pause` pauses."""

    def __init__(self, pid: int, client: str, proc: Path = PROC) -> None:
        self.pid, self.client, self.proc = pid, client, proc

    def names(self, connection: appmenu.Connection) -> List[str]:
        """The bus names of the app's players, those whose process descends from the launcher's."""
        listed = appmenu.Reader.of(connection.bus("ListNames")).strings()
        tree = parents(self.proc)
        found = []
        for name in sorted(name for name in listed if name.startswith(PREFIX)):
            try:
                owner = appmenu.uint32(connection.bus("GetConnectionUnixProcessID", "s", bytes(appmenu.Writer().string(name).data)))
            except (OSError, *appmenu.UNREADABLE):
                continue
            if descends(owner, self.pid, tree):
                found.append(name)
        return found

    def pause(self, connection: appmenu.Connection, reason: str, log: Callable[[str], None]) -> int:
        """Pause each of the app's players that plays, writing ``reason`` and what was done to the log; return how many
        were paused."""
        try:
            names = self.names(connection)
        except (OSError, *appmenu.UNREADABLE) as exc:
            log(f"  {reason}; could not find {self.client}'s players: {exc}")
            return 0
        paused, failure = 0, ""
        for name in names:
            if status(connection, name) not in (None, "Playing"):
                continue
            try:
                connection.call(name, OBJECT, PLAYER, "Pause", flags=appmenu.NO_AUTO_START)
                paused += 1
            except OSError as exc:
                failure = failure or str(exc)
        if paused:
            log(f"  {reason}; paused {self.client}")
        elif failure:
            log(f"  {reason}; could not pause {self.client}: {failure}")
        else:
            log(f"  {reason}; {self.client} was not playing")
        return paused
