"""A progress bar on the terminal's last line, beneath the messages printed while it is shown.

The bar counts the steps of a long command, such as an install, and fills as they are done, along with what is
reported of the step under way: the bytes of a download, the parts of a Flatpak install or the steps of a build.
To print a message, the bar is cleared, the message printed and the bar drawn again under it (see :mod:`ui`). It is
drawn only on a terminal, so the output that goes to a file or a pipe is the same with or without it.
"""

from __future__ import annotations

import os
from typing import TextIO

WIDTH = 30
"""The most columns the bar itself takes; the rest of the line says which step is under way."""

_CLEAR = "\r\033[2K"
_EIGHTHS = " ▏▎▍▌▋▊▉"


def wanted(stream: TextIO) -> bool:
    """Whether ``stream`` is a terminal that can draw the bar."""
    try:
        return stream.isatty() and os.environ.get("TERM", "dumb") != "dumb"
    except (AttributeError, ValueError):
        return False


def columns(stream: TextIO) -> int:
    """The width of the terminal ``stream`` writes to, or 80 when it cannot be read."""
    try:
        return os.get_terminal_size(stream.fileno()).columns
    except (AttributeError, ValueError, OSError):
        return 80


class Bar:
    """A bar of ``total`` steps on ``stream``: :meth:`step` starts each one and :meth:`update` says how far it has got.

    On a terminal 100 columns wide, the line reads, for example,
    ``███████████▏░░░░░░░░░░░  48%  5 of 9 · YouTube · part 2 of 4, 45%, 2.3 MB/s``. It is drawn only when it
    changes, and not at all while it is hidden (see :meth:`hide`).
    """

    def __init__(self, stream: TextIO, total: int, colour: bool = False) -> None:
        self.stream = stream
        self.total = max(total, 1)
        self.colour = colour
        self.index = 0
        self.fraction = 0.0
        self.label = ""
        self.detail = ""
        self.hidden = 0
        self.shown = ""

    def step(self, label: str) -> None:
        """Count the step under way as done and start the next one, called ``label``."""
        self.index += 1
        self.total = max(self.total, self.index)
        self.fraction, self.label, self.detail = 0.0, label, ""
        self.draw()

    def update(self, fraction: float, detail: str = "") -> None:
        """Say how far the step under way has got, from 0 to 1, and what it is doing."""
        self.fraction = min(max(fraction, 0.0), 1.0)
        self.detail = detail
        self.draw()

    def skip(self, count: int) -> None:
        """Leave out ``count`` of the steps still to come."""
        self.total = max(self.total - count, self.index, 1)
        self.draw()

    def done(self) -> float:
        """How much of the whole is done, from 0 to 1."""
        return min((self.index - 1 + self.fraction) / self.total, 1.0) if self.index else 0.0

    def line(self, width: int) -> str:
        """The bar as it fits in ``width`` columns, leaving the last one free so the terminal does not wrap it.

        The bar takes a quarter of the line, up to :data:`WIDTH` columns, and none on a terminal too narrow for 8;
        the words after it are cut short to fit.
        """
        done = self.done()
        percent = f"{int(done * 100):3d}%"
        words = " · ".join(part for part in (f"{self.index} of {self.total}", self.label, self.detail) if part)
        room = max(width - 1, len(percent))
        size = min(WIDTH, (room - len(percent) - 3) // 4)
        size = size if size >= 8 else 0
        left = room - (size + 1 if size else 0) - len(percent) - 2
        if len(words) > left:
            words = words[:left - 1] + "…" if left > 1 else ""
        bar = self._bar(size, done) + " " if size else ""
        return f"{bar}{percent}  {words}".rstrip()

    def _bar(self, size: int, done: float) -> str:
        full, eighths = divmod(int(size * 8 * done), 8)
        filled = "█" * full + (_EIGHTHS[eighths] if eighths and full < size else "")
        empty = "░" * (size - len(filled))
        if self.colour:
            return f"\033[34m{filled}\033[0m\033[2m{empty}\033[0m"
        return filled + empty

    def draw(self) -> None:
        """Draw the bar again, if it has changed, unless it is hidden or no step has started."""
        if self.hidden or not self.index:
            return
        line = self.line(columns(self.stream))
        if line != self.shown:
            self.stream.write(_CLEAR + line)
            self.stream.flush()
            self.shown = line

    def clear(self) -> None:
        """Take the bar off the terminal, leaving the cursor at the start of its empty line."""
        if self.shown:
            self.stream.write(_CLEAR)
            self.stream.flush()
            self.shown = ""

    def hide(self) -> None:
        """Clear the bar and keep it off until :meth:`show` is called as often as this was."""
        self.hidden += 1
        self.clear()

    def show(self) -> None:
        """Undo one :meth:`hide`, and draw the bar once none is left."""
        self.hidden = max(self.hidden - 1, 0)
        self.draw()
