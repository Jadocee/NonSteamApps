"""Terminal output and prompts shared by the commands.

While a long command shows a progress bar (see :func:`progress`), the messages are printed above it.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Iterator, Optional

from .progress import Bar, wanted

quiet = False
assume_yes = False

MEGABYTE = 1 << 20

_COLOUR = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
_bar: Optional[Bar] = None


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


class Abort(RuntimeError):
    """A failure to report as ``error: <message>`` before exiting."""


def _say(text: str) -> None:
    with paused():
        print(text, file=sys.stderr)


def log(message: str) -> None:
    if not quiet:
        _say(f"{_paint('34', '==>')} {_paint('1', message)}")


def info(message: str) -> None:
    if not quiet:
        _say(f"    {message}")


def ok(message: str) -> None:
    if not quiet:
        _say(f"{_paint('32', ' ✓')}  {message}")


def warn(message: str) -> None:
    _say(f"{_paint('33', 'warning:')} {message}")


def error(message: str) -> None:
    _say(f"{_paint('31', 'error:')} {message}")


def bold(text: str) -> str:
    return _paint("1", text)


def confirm(question: str, default: bool = False, unattended: Optional[bool] = None) -> bool:
    """Ask a yes/no question on the terminal; without one, return ``unattended``, or else ``default``."""
    if assume_yes:
        return True
    try:
        with paused(), open("/dev/tty", "w", encoding="utf-8") as output, open("/dev/tty", encoding="utf-8") as answers:
            output.write(f"{_paint('33', '?')} {question} {'[Y/n]' if default else '[y/N]'} ")
            output.flush()
            reply = answers.readline().strip().lower()
    except OSError:
        return default if unattended is None else unattended
    return default if not reply else reply in ("y", "yes")


@contextlib.contextmanager
def progress(total: int) -> Iterator[None]:
    """Show a progress bar of ``total`` steps beneath the messages while the block runs, when stderr is a terminal.

    :func:`step` starts each step and :func:`advance` says how far it has got. Without a bar, as when the output
    goes to a file or ``quiet`` is set, they do nothing, and the output is what it would be without them.
    """
    global _bar
    if quiet or _bar is not None or not wanted(sys.stderr):
        yield
        return
    _bar = Bar(sys.stderr, total, colour=_COLOUR)
    try:
        yield
    finally:
        _bar.clear()
        _bar = None


def progressing() -> bool:
    """Whether a progress bar is shown, so that a program's own progress can go to it instead of the terminal."""
    return _bar is not None


def step(label: str) -> None:
    """Start the next step of the progress bar, called ``label``."""
    if _bar is not None:
        _bar.step(label)


def advance(fraction: float, detail: str = "") -> None:
    """Say how far the progress bar's step under way has got, from 0 to 1, and what it is doing."""
    if _bar is not None:
        _bar.update(fraction, detail)


def downloaded(received: int, size: int) -> None:
    """Show a download's progress on the progress bar: ``received`` bytes of ``size``, which is 0 when unknown."""
    if _bar is not None:
        got = f"{received / MEGABYTE:.0f}"
        _bar.update(received / size if size else 0.0, f"{got} of {size / MEGABYTE:.0f} MB" if size else f"{got} MB")


def skip(count: int) -> None:
    """Leave ``count`` of the progress bar's steps still to come out."""
    if _bar is not None:
        _bar.skip(count)


@contextlib.contextmanager
def paused() -> Iterator[None]:
    """Keep the progress bar off the terminal while the block uses it, such as a program asking for a password."""
    bar = _bar
    if bar is None:
        yield
        return
    bar.hide()
    try:
        yield
    finally:
        bar.show()
