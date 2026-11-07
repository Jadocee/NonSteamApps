"""Open an app's web links in Helium, in front of the app, while Game Mode runs it.

In Game Mode, SteamOS opens links in Steam's own browser, which cannot hand a sign-in's callback back to an app
such as Element or Bitwarden. For an app with sign-in ``callbacks``, the launcher therefore stays alive as the
app's parent and puts NonSteamApps' ``xdg-open`` first on the app's ``PATH``. That script passes web links and
callbacks through a pipe in the app's runtime folder, which Flatpak shares with the sandbox at the same path.
The launcher opens a web link in a Helium window of its own, which Game Mode shows over the app because Steam
started both, and hands a callback to the running app by starting the app again with it, as a desktop would.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

MAX_URL = 8192
WEB_SCHEMES = ("http", "https")
WAIT_SECONDS = 10.0


def channel_dir(flatpak_id: str, environ: Mapping[str, str]) -> Path:
    """Where the pipe goes: the app's runtime folder, which Flatpak shares with its sandbox."""
    runtime = environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "app" / flatpak_id / "nonsteamapps"


def open_channel(directory: Path) -> Tuple[Path, int]:
    """Make the pipe and hold it open for reading and writing, so a writer never waits while the launcher runs."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"open-{os.getpid()}"
    path.unlink(missing_ok=True)
    os.mkfifo(path, 0o600)
    return path, os.open(path, os.O_RDWR | os.O_NONBLOCK)


def kind(url: str, schemes: Sequence[str]) -> Optional[str]:
    """``web`` for a web link, ``callback`` for a link in one of the app's ``schemes``, and ``None`` for anything else."""
    if not url or len(url) > MAX_URL or any(ord(character) < 32 or ord(character) == 127 for character in url):
        return None
    scheme, separator, rest = url.partition(":")
    if not separator:
        return None
    if scheme.lower() in WEB_SCHEMES:
        return "web" if rest.startswith("//") and len(rest) > 2 else None
    return "callback" if scheme.lower() in {name.lower() for name in schemes} else None


def sandbox_options(scripts: Path, pipe: Path, schemes: Sequence[str]) -> List[str]:
    """``flatpak run`` options that put NonSteamApps' ``xdg-open`` first on the app's ``PATH``."""
    return [
        f"--filesystem={scripts}:ro",
        f"--env=PATH={scripts}:/app/bin:/usr/bin",
        f"--env=NONSTEAMAPPS_OPEN={pipe}",
        f"--env=NONSTEAMAPPS_SCHEMES={' '.join(schemes)}",
    ]


def browser_environment(environ: Mapping[str, str], scripts: Path, pipe: Path, schemes: Sequence[str]) -> Dict[str, str]:
    """The Helium window's environment, in which the app's callbacks also reach NonSteamApps' ``xdg-open``.

    Without a session bus, Chromium cannot ask the desktop portal, which in Game Mode would give the callback to
    Steam's browser, and runs ``xdg-open`` from ``PATH`` instead.
    """
    environment = dict(environ)
    environment.update(
        PATH=f"{scripts}:{environ.get('PATH') or '/usr/bin:/bin'}",
        NONSTEAMAPPS_OPEN=str(pipe),
        NONSTEAMAPPS_SCHEMES=" ".join(schemes),
        DBUS_SESSION_BUS_ADDRESS="unix:path=/dev/null",
    )
    return environment


def serve(child: subprocess.Popen, fd: int, schemes: Sequence[str], open_web: Callable[[str], None], deliver: Callable[[str], None]) -> int:
    """Pass each link from the pipe on until the app exits; return the app's exit status."""
    pending = b""
    while child.poll() is None:
        try:
            ready, _, _ = select.select([fd], [], [], 0.25)
            chunk = os.read(fd, 65536) if ready else b""
        except (InterruptedError, BlockingIOError):
            continue
        *lines, pending = (pending + chunk).split(b"\n")
        pending = pending[-MAX_URL:]
        for line in lines:
            url = line.decode("utf-8", "replace").strip()
            found = kind(url, schemes)
            if found == "web":
                open_web(url)
            elif found == "callback":
                deliver(url)
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


def stop(processes: Sequence[subprocess.Popen]) -> None:
    """End each process that still runs, with the processes it started, and wait for each to end (see :func:`reap`)."""
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    reap(processes)


def reap(processes: Sequence[subprocess.Popen], timeout: float = WAIT_SECONDS) -> None:
    """Wait up to ``timeout`` seconds in all for the processes to end, so that none is left a zombie; leave any still running."""
    deadline = time.monotonic() + timeout
    for process in processes:
        try:
            process.wait(max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
