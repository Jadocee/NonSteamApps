"""The device's processes, as ``/proc`` shows them: each one's parent, command line and program."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Mapping

PROC = Path("/proc")


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
    """Whether ``pid`` is ``ancestor`` or one of the processes under it, by ``tree``, each process's parent."""
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = tree.get(pid, 0)
    return False
