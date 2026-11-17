"""Install, update, remove and run apps from Flathub with the ``flatpak`` command."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import ui

REMOTE = "flathub"
REMOTE_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"

_COUNTS = re.compile(r"(\d+)\s*/\s*(\d+)")
_PERCENT = re.compile(r"(\d{1,3})\s?%|%\s?(\d{1,3})")
_DURATION = re.compile(r"\d+(?::\d\d)+")


def x11_options() -> List[str]:
    """``flatpak run`` options that give an app X11 even where Flatpak finds a Wayland display.

    An app that falls back to X11 (``fallback-x11``) gets X11 only where there is no Wayland display, and
    Flatpak 1.14 and 1.16 ignore ``--socket=x11`` while that fallback is set, so it is turned off as well.
    """
    return ["--socket=x11", "--nosocket=fallback-x11"]


class FlatpakError(RuntimeError):
    """A ``flatpak`` command failed."""


class Progress:
    """Reads the progress that ``flatpak install`` prints without ``--noninteractive`` when its output is not a terminal.

    As each operation of the install starts, such as a runtime or the app, Flatpak prints a line like
    ``Installing 2/4…``, and then, as it goes on, that line again with a bar, a percentage and the speed after it
    (as Flatpak 1.14 to 1.18 do). Only that shape is relied on, not the words, which are in the user's language.
    """

    def __init__(self) -> None:
        self.previous = ""
        self.heading = ""
        self.operation = 0
        self.operations = 0

    def read(self, line: str) -> Optional[Tuple[float, str]]:
        """How far the whole install has got, from 0 to 1, and what it is doing, when ``line`` says so."""
        line = line.rstrip("\r\n")
        if not (self.heading and line.startswith(self.heading + " ")):
            if not (self.previous and line.startswith(self.previous + " ")):
                self.previous = line
                return None
            self._start(self.previous)
        found = _PERCENT.search(line, len(self.heading) + 1)
        if not found:
            return None
        percent = min(int(found.group(1) or found.group(2)), 100)
        operations = max(self.operations, self.operation)
        words = [f"part {self.operation} of {operations}"] if operations > 1 else []
        words.append(f"{percent}%")
        speed = " ".join(word for word in line[found.end():].split() if not _DURATION.fullmatch(word))
        if speed:
            words.append(speed)
        return min((self.operation - 1 + percent / 100) / operations, 1.0), ", ".join(words)

    def _start(self, heading: str) -> None:
        self.heading = heading
        counts = _COUNTS.search(heading)
        if counts:
            self.operation, self.operations = int(counts.group(1)), int(counts.group(2))
        else:
            self.operation += 1


@dataclass(frozen=True)
class Installed:
    version: str
    installation: str


class Flatpak:
    """Thin wrapper around the ``flatpak`` command; apps NonSteamApps installs go into the user installation."""

    def __init__(self, command: str = "flatpak") -> None:
        self.command = command

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def _call(self, *args: str, quiet: bool = False) -> None:
        stream = subprocess.DEVNULL if quiet else None
        try:
            result = subprocess.run([self.command, *args], stdin=subprocess.DEVNULL, stdout=stream, check=False)
        except OSError as exc:
            raise FlatpakError(f"could not run {self.command}: {exc}") from exc
        if result.returncode != 0:
            raise FlatpakError(f"'flatpak {' '.join(args)}' failed with exit status {result.returncode}")

    def _follow(self, *args: str) -> None:
        """Run ``flatpak args`` with its progress on the progress bar, and print what it says on stderr above the bar."""
        reader = Progress()
        with tempfile.TemporaryFile() as said:
            try:
                process = subprocess.Popen([self.command, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=said,
                                           env={**os.environ, "FLATPAK_FANCY_OUTPUT": "0"}, encoding="utf-8", errors="replace")
            except OSError as exc:
                raise FlatpakError(f"could not run {self.command}: {exc}") from exc
            with process:
                for line in process.stdout:
                    found = reader.read(line)
                    if found:
                        ui.advance(*found)
            said.seek(0)
            for line in said.read().decode("utf-8", "replace").splitlines():
                if line.strip():
                    ui.info(line.strip())
        if process.returncode != 0:
            raise FlatpakError(f"'flatpak {' '.join(args)}' failed with exit status {process.returncode}")

    def installed(self) -> Dict[str, Installed]:
        """Map installed app IDs to their version and installation, preferring the user installation."""
        try:
            output = subprocess.run(
                [self.command, "list", "--app", "--columns=application,version,installation"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return {}
        apps: Dict[str, Installed] = {}
        for line in output.splitlines():
            fields = [field.strip() for field in line.split("\t")]
            if len(fields) < 3:
                fields = line.split()
            if len(fields) < 2 or "." not in fields[0]:
                continue
            app_id, version, installation = fields[0], (fields[1] if len(fields) > 2 else ""), fields[-1]
            if app_id not in apps or installation == "user":
                apps[app_id] = Installed(version, installation)
        return apps

    def installation(self, app_id: str) -> Optional[str]:
        found = self.installed().get(app_id)
        return found.installation if found else None

    def install(self, app_id: str) -> None:
        """Install ``app_id`` from Flathub into the user installation.

        While a progress bar is shown (see :func:`ui.progress`), Flatpak's progress goes to it (see :class:`Progress`):
        ``--noninteractive`` would print none, so it is left out, and ``-y`` answers Flatpak's questions as it does.
        """
        following = ui.progressing()
        run = self._follow if following else self._call
        run("remote-add", "--user", "--if-not-exists", REMOTE, REMOTE_URL)
        run("install", "--user", *(() if following else ("--noninteractive",)), "-y", REMOTE, app_id)

    def update(self, app_ids: Sequence[str], quiet: bool = False) -> None:
        if app_ids:
            self._call("update", "--user", "--noninteractive", "-y", *app_ids, quiet=quiet)

    def uninstall(self, app_id: str) -> None:
        self._call("uninstall", "--user", "--noninteractive", "-y", app_id)

    def remove_unused(self) -> None:
        self._call("uninstall", "--user", "--unused", "--noninteractive", "-y", quiet=True)

    def run_args(self, app_id: str, args: Sequence[str] = (), options: Sequence[str] = ()) -> List[str]:
        return [self.command, "run", *options, app_id, *args]

    def run_quietly(self, app_id: str, args: Sequence[str]) -> int:
        """Run the app to completion with ``args`` (for its own maintenance options) and return its status."""
        try:
            return subprocess.run(
                self.run_args(app_id, args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=False,
            ).returncode
        except (OSError, subprocess.TimeoutExpired):
            return -1
