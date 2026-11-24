"""Chromium's DevTools protocol over the pipe that ``--remote-debugging-pipe`` opens.

Chromium reads the protocol's messages on its file descriptor 3 and writes its own on 4, each a JSON object ending
in a NUL. Only the program that holds the other ends of the pipe can use it, unlike a debugging port, which any
program on the machine could reach, and Chromium closes once that program closes them.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import IO, List, Mapping, Optional, Sequence, Tuple

SWITCH = "--remote-debugging-pipe"
MAX_BUFFER = 1 << 22


def _high_fd(fd: int) -> int:
    """A copy of ``fd`` numbered 10 or more, clear of 3 and 4, which the browser's pipe takes."""
    return fcntl.fcntl(fd, fcntl.F_DUPFD, 10)


def spawn(program: Path, arguments: Sequence[str], environment: Optional[Mapping[str, str]] = None,
          output: Optional[IO] = None) -> Tuple[subprocess.Popen, int, int]:
    """Start ``program`` with ``arguments``, which include :data:`SWITCH`, in a session of its own, with the pipe on its file
    descriptors 3 and 4; return the process, the end to read its messages from and the end to send commands to.

    Raises :class:`OSError` when it cannot start.
    """
    to_browser, from_browser = os.pipe(), os.pipe()
    child: List[int] = []
    try:
        child.append(_high_fd(to_browser[0]))
        child.append(_high_fd(from_browser[1]))
        script = f'exec "$@" 3<&{child[0]} 4>&{child[1]} {child[0]}<&- {child[1]}>&-'
        process = subprocess.Popen(
            [shutil.which("bash") or "/bin/bash", "-c", script, "bash", str(program), *arguments], pass_fds=tuple(child),
            stdin=subprocess.DEVNULL, stdout=output, stderr=output, env=environment, start_new_session=True,
        )
    except OSError:
        for fd in (to_browser[1], from_browser[0]):
            os.close(fd)
        raise
    finally:
        for fd in (to_browser[0], from_browser[1], *child):
            os.close(fd)
    return process, from_browser[0], to_browser[1]


def command(number: int, method: str, params: Optional[dict] = None, session: Optional[str] = None) -> bytes:
    """Command ``number``, ``method`` with ``params``, for the page ``session`` drives or else the browser, as the pipe carries it."""
    message: dict = {"id": number, "method": method, "params": params or {}}
    if session:
        message["sessionId"] = session
    return json.dumps(message).encode("utf-8") + b"\0"


def messages(buffer: bytes) -> Tuple[List[object], bytes]:
    """The messages complete in ``buffer``, leaving out any that is not JSON, and what follows the last of them.

    What follows is dropped once it grows past :data:`MAX_BUFFER` without ending.
    """
    *complete, rest = buffer.split(b"\0")
    found: List[object] = []
    for raw in complete:
        try:
            found.append(json.loads(raw.decode("utf-8")))
        except ValueError:
            continue
    return found, rest if len(rest) <= MAX_BUFFER else b""
