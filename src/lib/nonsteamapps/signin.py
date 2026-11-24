"""Hand a sign-in back to an app that asks for the address of the web page it ends on, as chiaki-ng's PSN sign-in does.

chiaki-ng signs in to PSN in the web browser. The sign-in ends on Sony's page
``https://remoteplay.dl.playstation.net/remoteplay/redirect``, with a code in its address, which chiaki-ng then
asks for as "Redirect URL from Web Browser": it reads the address from the clipboard ("Click to Paste URL") and
exchanges the code for its PSN sign-in ("Setup"). In Game Mode, where NonSteamApps opens an app's links in Helium
in front of the app (see :mod:`links`), the Helium window of such a sign-in runs with a DevTools pipe that only
the launcher holds (see :mod:`devtools`). Through it, :class:`Watch` learns the address of each page the window
shows. Once one is the sign-in's end, with a code, the launcher puts that address on the clipboard and closes the
window, which shows the app again, ready for the paste. The launcher holds the clipboard until another program
takes it or the app exits (see :class:`x11.Selection`). In Game Mode, gamescope takes it at once: it copies the
text of each new clipboard on its X servers and then holds it on all of them, so the address stays until
something else is copied.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Callable, Optional, Tuple

from . import devtools
from .browser import return_addresses

DISCOVER = "Target.setDiscoverTargets"
CLOSE = "Browser.close"
PAGE_EVENTS = ("Target.targetCreated", "Target.targetInfoChanged")


def _page(url: str) -> Tuple[str, str, str]:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower(), parts.path


def starts(url: str, ends: str) -> bool:
    """Whether the page at ``url`` is a sign-in that returns to the page ``ends``, as its ``redirect_uri`` says."""
    return bool(ends) and any(_page(address) == _page(ends) for address in return_addresses(url))


def reached(url: str, ends: str) -> bool:
    """Whether ``url`` is the page ``ends`` with the code a sign-in gives in its query, as chiaki-ng reads it."""
    if not ends or _page(url) != _page(ends):
        return False
    return any(key == "code" and value for key, value in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def _address(message: object) -> Optional[str]:
    """The address of the page that a DevTools event says a tab now shows, where it says so."""
    if not isinstance(message, dict) or message.get("method") not in PAGE_EVENTS:
        return None
    params = message.get("params")
    info = params.get("targetInfo") if isinstance(params, dict) else None
    if not isinstance(info, dict) or info.get("type") != "page":
        return None
    url = info.get("url")
    return url if isinstance(url, str) else None


class Watch:
    """Follow the pages of a Helium window that :func:`devtools.spawn` started, until one is ``ends`` with a code.

    ``ended`` is then given its address, and returns whether to close the window, as it does once the address is
    on the clipboard. Wait for the window's messages on :meth:`fileno`; :meth:`handle` reads them and returns
    whether the window is still open. Closing the pipe, as :meth:`close` does, also closes Helium.
    """

    def __init__(self, reader: int, writer: int, ends: str, ended: Callable[[str], bool]) -> None:
        self.reader, self.writer, self.ends, self.ended = reader, writer, ends, ended
        self._buffer = b""
        self._sent = 0
        self._send(DISCOVER, {"discover": True})

    def fileno(self) -> int:
        return self.reader

    def _send(self, method: str, params: Optional[dict] = None) -> None:
        self._sent += 1
        try:
            os.write(self.writer, devtools.command(self._sent, method, params))
        except OSError:
            pass

    def handle(self) -> bool:
        try:
            chunk = os.read(self.reader, 1 << 16)
        except (BlockingIOError, InterruptedError):
            return True
        except OSError:
            chunk = b""
        if not chunk:
            return False
        found, self._buffer = devtools.messages(self._buffer + chunk)
        for message in found:
            url = _address(message)
            if url is not None and reached(url, self.ends):
                self.ends = ""
                if self.ended(url):
                    self._send(CLOSE)
        return True

    def close(self) -> None:
        for fd in (self.reader, self.writer):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.reader = self.writer = -1
