"""Steam artwork for each app, made on this machine with the app's own icon.

NonSteamApps ships artwork of its own for every app (``artwork/<app>``), drawn from the template in
``share/artwork`` in the style of Steam's library: the app's icon and name on a dark ground tinted with the app's
colours. On the device it draws the same artwork again around the app's own icon, which it takes from the app
itself, as a desktop does: the icon a Flatpak exports, the one SteamOS's icon theme gives Dolphin, the one in
Helium's release, the one KytyPS5's or Lichii's project keeps with the build installed, or, for a site that runs in
Helium, the icon the site names. So no app's own icon is in NonSteamApps' repository.

NonSteamApps' own Helium draws it, headless, driven through the DevTools protocol on a pipe (:class:`Browser`).
Artwork is made again only when the icon or the template changes; an app whose icon cannot be had, or is too small,
keeps the shipped artwork.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import http.client
import json
import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import net
from .fsutil import atomic_write_bytes, atomic_write_json

VERSION = 1
SLOTS: Tuple[Tuple[str, str, int, int], ...] = (
    ("capsule", "capsule.png", 600, 900),
    ("wide", "wide.png", 920, 430),
    ("hero", "hero.jpg", 3840, 1240),
    ("logo", "logo.png", 1280, 400),
    ("icon", "icon.png", 256, 256),
)
TEMPLATE = "card.html"
RECORD = "made.json"
MIN_SIZE = 128
MIN_ART = 256
MAX_ICON = 8 << 20
COLOURS: Dict[str, Tuple[str, str]] = {
    "youtube": ("#ff0033", "#ff6a3d"),
    "element": ("#0dbd8b", "#368bd6"),
    "signal": ("#3a76f0", "#7aa7ff"),
    "bitwarden": ("#175ddc", "#5f9bff"),
    "jellyfin": ("#aa5cc3", "#00a4dc"),
    "localsend": ("#1aa39a", "#5fd4b4"),
    "prism": ("#6d5ad8", "#e0a83c"),
    "eden": ("#e3889a", "#7a3e8f"),
    "edennx2": ("#e3889a", "#e0313f"),
    "lichii": ("#ff3d6e", "#8fd15a"),
    "kytyps5": ("#3d7fe6", "#1c47b0"),
    "protonup": ("#7e4de0", "#2fb5ff"),
    "protontricks": ("#a3243b", "#e2a03a"),
    "winetricks": ("#c1121f", "#9aa3ad"),
    "files": ("#3daee9", "#1d99f3"),
    "helium": ("#4aa3ff", "#b6d8ff"),
    "primevideo": ("#00a8e1", "#1a6cff"),
    "hbomax": ("#002be7", "#7a3cff"),
    "netflix": ("#e50914", "#7a0a0f"),
    "disneyplus": ("#0063e5", "#00d5ff"),
    "protondb": ("#e0313f", "#ff8a5c"),
    "steamdb": ("#2a475e", "#66c0f4"),
    "protonmail": ("#6d4aff", "#c9b9ff"),
    "protoncalendar": ("#6d4aff", "#a58bff"),
}
SITE_ICONS = r"""
(async (extra) => {
  const found = [];
  const add = (href, sizes, type, kind) => {
    try { found.push({url: new URL(href, document.baseURI).href, sizes: sizes || "", type: type || "", kind}); } catch (error) {}
  };
  for (const link of document.querySelectorAll("link[rel][href]")) {
    const rel = link.rel.toLowerCase().split(/\s+/);
    if (rel.includes("icon") || rel.includes("apple-touch-icon") || rel.includes("apple-touch-icon-precomposed")) {
      add(link.getAttribute("href"), link.getAttribute("sizes"), link.getAttribute("type"), rel.includes("icon") ? "icon" : "touch");
    }
  }
  const manifests = new Set();
  const named = document.querySelector('link[rel~="manifest"][href]');
  if (named) {
    manifests.add(named.href);
  }
  for (const href of extra) {
    try { manifests.add(new URL(href, document.baseURI).href); } catch (error) {}
  }
  for (const href of manifests) {
    try {
      const response = await fetch(href, {credentials: "omit"});
      const data = await response.json();
      for (const icon of data.icons || []) {
        const purpose = String(icon.purpose || "any");
        if (/\bany\b/.test(purpose) || !/maskable|monochrome/.test(purpose)) {
          found.push({url: new URL(icon.src, response.url).href, sizes: icon.sizes || "", type: icon.type || "", kind: "manifest"});
        }
      }
    } catch (error) {}
  }
  add("/apple-touch-icon.png", "180x180", "image/png", "guess");
  return found;
})
"""
CARD_READY = """
new Promise((resolve) => {
  const check = () => window.cardReady ? resolve(window.cardReady) : setTimeout(check, 20);
  check();
})
"""


class ArtworkError(RuntimeError):
    """An app's own icon could not be had, or its artwork could not be drawn."""


class BrowserError(ArtworkError):
    """The headless browser could not be started, or did not answer as Chromium does."""


@dataclass(frozen=True)
class Source:
    """Where an app's own icon comes from: a ``file`` on this machine, a ``url`` of its project's, or the ``site`` it opens.

    A site names its icons itself, in its page and its web app manifest. ``manifest`` is a web app manifest that a
    site publishes without naming it in the page it opens on, as SteamDB's home page does not; its icons count too.
    """

    kind: str
    location: str
    manifest: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.location}" + (f" {self.manifest}" if self.manifest else "")


def site_icons(manifests: Sequence[str] = ()) -> str:
    """The script that lists the icons a loaded page names, reading the ``manifests`` beside the one the page names."""
    return f"{SITE_ICONS.strip()}({json.dumps(list(manifests))})"


def _size_of(folder: str) -> int:
    match = re.match(r"(\d+)x(\d+)(?:@(\d+))?\Z", folder)
    return int(match.group(1)) * int(match.group(3) or 1) if match else 0


def flatpak_icon(app_id: str, installations: Sequence[Path], name: str = "") -> Optional[Path]:
    """The icon a Flatpak installation exports for ``app_id``: its scalable one, or else its largest of at least :data:`MIN_SIZE` pixels.

    With ``name``, the icon of that name among the app's current files comes first, as Winetricks' does in
    Flathub's Wine, which exports Wine's.
    """
    own = _hicolor_icon([Path(folder) / "app" / app_id / "current" / "active" / "files" for folder in installations], name) if name else None
    return own or _hicolor_icon([Path(folder) / "exports" for folder in installations], app_id)


def _hicolor_icon(roots: Sequence[Path], name: str) -> Optional[Path]:
    best: Tuple[int, Optional[Path]] = (0, None)
    for root in roots:
        icons = root / "share" / "icons" / "hicolor"
        scalable = icons / "scalable" / "apps" / f"{name}.svg"
        if scalable.is_file():
            return scalable
        if not icons.is_dir():
            continue
        for folder in icons.iterdir():
            size, candidate = _size_of(folder.name), folder / "apps" / f"{name}.png"
            if size > best[0] and candidate.is_file():
                best = (size, candidate)
    return best[1] if best[0] >= MIN_SIZE else None


def theme_icon(name: str, themes: Sequence[Path]) -> Optional[Path]:
    """The icon ``name`` in the first of the icon ``themes`` that has it: a scalable one, or else its largest."""
    for theme in themes:
        if not Path(theme).is_dir():
            continue
        found = [path for path in Path(theme).rglob(f"{name}.*") if path.suffix in (".svg", ".png") and path.is_file()]
        vector = sorted(path for path in found if path.suffix == ".svg")
        if vector:
            return max(vector, key=lambda path: (path.parent.parent.name == "scalable", _size_of(path.parent.name) or _size_of(path.parent.parent.name), str(path)))
        raster = sorted(found, key=lambda path: (_size_of(path.parent.parent.name) or _size_of(path.parent.name), str(path)))
        if raster:
            return raster[-1]
    return None


def desktop_icon(command: str, folders: Sequence[Path], themes: Sequence[Path]) -> Optional[Path]:
    """The icon of the applications menu entry that starts ``command``, from the icon ``themes``."""
    for folder in folders:
        if not Path(folder).is_dir():
            continue
        for entry in sorted(Path(folder).glob("*.desktop")):
            try:
                lines = entry.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith(("#", "[")))
            program = values.get("Exec", "").split(" ", 1)[0].strip('"')
            if Path(program).name == command and values.get("Icon"):
                icon = values["Icon"]
                return Path(icon) if os.path.isabs(icon) and Path(icon).is_file() else theme_icon(icon, themes)
    return None


def _high_fd(fd: int) -> int:
    """A copy of ``fd`` numbered 10 or more, clear of 3 and 4, which the browser's pipe takes."""
    return fcntl.fcntl(fd, fcntl.F_DUPFD, 10)


class Browser:
    """A headless Chromium, such as NonSteamApps' Helium, driven through the DevTools protocol on the pipe ``--remote-debugging-pipe`` opens.

    Chromium reads the protocol's messages on its file descriptor 3 and writes its own on 4, each ending in a NUL.
    It loads no extension, unless ``extensions`` names unpacked ones, as the tests of NonSteamApps' own do; Google's
    branded Chrome then needs ``DisableLoadExtensionCommandLineSwitch`` turned off to honour ``--load-extension``.
    """

    def __init__(self, program: Path, timeout: float = 45.0, environment: Optional[Dict[str, str]] = None,
                 extensions: Sequence[Path] = ()) -> None:
        self.program = Path(program)
        self.timeout = timeout
        self.environment = environment
        self.extensions = tuple(str(folder) for folder in extensions)
        self.process: Optional[subprocess.Popen] = None
        self.profile: Optional[str] = None
        self._reader = self._writer = -1
        self._buffer = b""
        self._events: List[dict] = []
        self._last = 0

    def start(self) -> None:
        self.profile = tempfile.mkdtemp(prefix="nonsteamapps-artwork.")
        to_browser, from_browser = os.pipe(), os.pipe()
        self._writer, self._reader = to_browser[1], from_browser[0]
        try:
            read_end, write_end = _high_fd(to_browser[0]), _high_fd(from_browser[1])
        finally:
            os.close(to_browser[0])
            os.close(from_browser[1])
        arguments = [
            "--headless", "--remote-debugging-pipe", f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
            *([f"--load-extension={','.join(self.extensions)}", "--disable-features=DisableLoadExtensionCommandLineSwitch"]
              if self.extensions else ["--disable-extensions"]), "--disable-sync", "--disable-background-networking", "--hide-scrollbars", "--mute-audio",
            "--force-device-scale-factor=1", "--allow-file-access-from-files", *(["--no-sandbox"] if os.geteuid() == 0 else []), "about:blank",
        ]
        script = f'exec "$@" 3<&{read_end} 4>&{write_end} {read_end}<&- {write_end}>&-'
        self._log = Path(self.profile) / "browser.log"
        try:
            with open(self._log, "wb") as log:
                self.process = subprocess.Popen(
                    [shutil.which("bash") or "/bin/bash", "-c", script, "bash", str(self.program), *arguments], pass_fds=(read_end, write_end),
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=self.environment, start_new_session=True,
                )
        except OSError as exc:
            self.close()
            raise BrowserError(f"could not start {self.program.name}: {exc}") from exc
        finally:
            os.close(read_end)
            os.close(write_end)
        try:
            self.call("Browser.getVersion")
        except BrowserError as exc:
            said = self._said()
            self.close()
            raise BrowserError(f"{exc}" + (f" ({said})" if said else "")) from exc

    def _said(self) -> str:
        """The last thing the browser wrote to its log."""
        try:
            lines = [line.strip() for line in self._log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        except (OSError, AttributeError):
            return ""
        return lines[-1][:200] if lines else ""

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self.call("Browser.close", timeout=5)
            except ArtworkError:
                pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for fd in (self._reader, self._writer):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._reader = self._writer = -1
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None

    def __enter__(self) -> "Browser":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _message(self, deadline: float) -> dict:
        while b"\0" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserError("the browser did not answer in time")
            ready, _, _ = select.select([self._reader], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(self._reader, 1 << 16)
            if not chunk:
                raise BrowserError("the browser closed its DevTools pipe")
            self._buffer += chunk
        raw, _, self._buffer = self._buffer.partition(b"\0")
        try:
            message = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise BrowserError("the browser sent something that is not a DevTools message") from exc
        if not isinstance(message, dict):
            raise BrowserError("the browser sent something that is not a DevTools message")
        return message

    def call(self, method: str, params: Optional[dict] = None, session: Optional[str] = None, timeout: Optional[float] = None) -> dict:
        """Send one DevTools command and return its result, keeping the events that arrive meanwhile."""
        if self._writer < 0:
            raise BrowserError("the browser is not running")
        self._last += 1
        message: dict = {"id": self._last, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            os.write(self._writer, json.dumps(message).encode("utf-8") + b"\0")
        except OSError as exc:
            raise BrowserError(f"could not reach the browser: {exc}") from exc
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            reply = self._message(deadline)
            if reply.get("id") == self._last:
                if "error" in reply:
                    raise BrowserError(f"{method} failed: {reply['error'].get('message', reply['error'])}")
                return reply.get("result") or {}
            if "method" in reply:
                self._events.append(reply)

    def wait_for(self, event: str, session: str, timeout: Optional[float] = None) -> Optional[dict]:
        """The next ``event`` for ``session``, or ``None`` once ``timeout`` passes without one."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            for index, message in enumerate(self._events):
                if message.get("method") == event and message.get("sessionId") == session:
                    del self._events[index]
                    return message
            try:
                message = self._message(deadline)
            except BrowserError:
                if time.monotonic() >= deadline:
                    return None
                raise
            if "method" in message:
                self._events.append(message)

    def page(self) -> str:
        """Open a page and return the session that drives it."""
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Page.enable", session=session)
        return session

    def load(self, session: str, url: str, width: int, height: int, transparent: bool = True, timeout: Optional[float] = None) -> bool:
        """Show ``url`` at ``width`` by ``height`` pixels; return whether it finished loading in time."""
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session)
        background = {"color": {"r": 0, "g": 0, "b": 0, "a": 0}} if transparent else {}
        self.call("Emulation.setDefaultBackgroundColorOverride", background, session)
        self._events = [event for event in self._events if event.get("sessionId") != session]
        self.call("Page.navigate", {"url": url}, session)
        return self.wait_for("Page.loadEventFired", session, timeout) is not None

    def evaluate(self, session: str, expression: str, timeout: Optional[float] = None) -> object:
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, session, timeout)
        if "exceptionDetails" in result:
            raise BrowserError(f"the page's script failed: {result['exceptionDetails'].get('text', '')}")
        return (result.get("result") or {}).get("value")

    def screenshot(self, session: str, width: int, height: int, jpeg: bool = False) -> bytes:
        params: dict = {"format": "jpeg", "quality": 92} if jpeg else {"format": "png"}
        params["clip"] = {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}
        data = self.call("Page.captureScreenshot", params, session).get("data", "")
        try:
            return base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise BrowserError("the browser's screenshot was not base64") from exc


def fetch(url: str) -> bytes:
    """Download an icon of at most :data:`MAX_ICON` bytes over HTTPS."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ArtworkError(f"{url} is not an https address")
    try:
        with urllib.request.urlopen(net.request(url), timeout=net.TIMEOUT) as response:
            data = response.read(MAX_ICON + 1)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise ArtworkError(f"could not download {url}: {exc}") from exc
    if len(data) > MAX_ICON:
        raise ArtworkError(f"{url} is larger than an icon")
    return data


def _suffix(name: str, data: bytes) -> str:
    """The file type of an icon, from its content: a picture's own signature, or SVG's markup; ``""`` for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\0\0\1\0"):
        return ".ico"
    head = data[:4096].lstrip().lower()
    named = Path(urllib.parse.urlsplit(name).path).suffix.lower() == ".svg"
    if b"<svg" in head and (head.startswith((b"<svg", b"<?xml", b"<!doctype svg")) or (named and head.startswith(b"<!--"))):
        return ".svg"
    return ""


def _declared(candidate: dict) -> int:
    sizes = str(candidate.get("sizes") or "").lower()
    if "any" in sizes or str(candidate.get("type") or "").endswith("svg") or urllib.parse.urlsplit(str(candidate.get("url"))).path.endswith(".svg"):
        return 1 << 20
    found = [int(width) for width, height in re.findall(r"(\d+)x(\d+)", sizes)]
    return max(found) if found else (180 if candidate.get("kind") == "touch" else 0)


def rank(candidates: Sequence[object]) -> List[str]:
    """The icons a site names, best first: vector ones, then the largest; each address once."""
    seen, ranked = set(), []
    usable = [candidate for candidate in candidates if isinstance(candidate, dict) and str(candidate.get("url", "")).startswith("https://")]
    for candidate in sorted(usable, key=lambda candidate: (-_declared(candidate), candidate.get("kind") == "guess")):
        url = str(candidate["url"])
        if url not in seen:
            seen.add(url)
            ranked.append(url)
    return ranked


def card_url(template: Path, slot: str, name: str, colours: Tuple[str, str], icon: Path, art: Optional[Path] = None) -> str:
    """The template's address for one slot: drawn around ``icon``, or showing ``art``, the project's own artwork for it."""
    values = {"slot": slot, "name": name, "a": colours[0], "b": colours[1], "icon": Path(icon).resolve().as_uri()}
    if art is not None:
        values["art"] = Path(art).resolve().as_uri()
    return f"{Path(template).resolve().as_uri()}?{urllib.parse.urlencode(values)}"


class Studio:
    """Makes each app's artwork with its own icon, one folder per app in ``folder``, with the template in ``share``.

    ``browser`` makes the :class:`Browser` that draws it, started only once something must be drawn, and ``download``
    fetches icons from the web.
    """

    def __init__(self, folder: Path, share: Path, browser: Callable[[], Browser], download: Optional[Callable[[str], bytes]] = None) -> None:
        self.folder = Path(folder)
        self.template = Path(share) / TEMPLATE
        self._browser_factory = browser
        self._browser: Optional[Browser] = None
        self._session = ""
        self.download = download

    def __enter__(self) -> "Studio":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None

    def _page(self) -> Tuple[Browser, str]:
        if self._browser is None:
            browser = self._browser_factory()
            browser.start()
            self._browser = browser
            self._session = browser.page()
        return self._browser, self._session

    def files(self, app_id: str) -> Dict[str, Path]:
        """The artwork made for ``app_id`` with its own icon, by slot, or nothing while any of it is missing or out of date."""
        folder = self.folder / app_id
        try:
            record = json.loads((folder / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        found = {slot: folder / name for slot, name, _, _ in SLOTS}
        if not isinstance(record, dict) or record.get("version") != VERSION or not all(path.is_file() for path in found.values()):
            return {}
        return found

    def _record(self, app_id: str) -> dict:
        try:
            record = json.loads((self.folder / app_id / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return record if isinstance(record, dict) else {}

    def origin(self, app_id: str) -> str:
        """Where the icon of the artwork made for ``app_id`` came from, and which slots its project's own artwork fills, as
        people read it, or ``""`` if none was made."""
        if not self.files(app_id):
            return ""
        record = self._record(app_id)
        kind, _, location = str(record.get("source", "")).partition(":")
        icon = f"the icon {urllib.parse.urlsplit(location).netloc} names" if kind == "site" else location
        official = sorted(record.get("official") or {}) if isinstance(record.get("official"), dict) else []
        return icon + (f"; its project's own library artwork for the {', '.join(official)}" if official else "")

    def forget(self, app_id: str) -> None:
        shutil.rmtree(self.folder / app_id, ignore_errors=True)

    def _measure(self, icon: Path) -> dict:
        browser, session = self._page()
        browser.load(session, card_url(self.template, "icon", "", ("#000000", "#000000"), icon), 256, 256)
        ready = browser.evaluate(session, CARD_READY)
        return ready if isinstance(ready, dict) else {}

    def _usable(self, icon: Path) -> Optional[str]:
        """Why the icon ``icon`` cannot be used, or ``None`` if it can."""
        ready = self._measure(icon)
        if not ready.get("ok"):
            return "it is not an image Helium can show"
        if icon.suffix != ".svg" and min(int(ready.get("width") or 0), int(ready.get("height") or 0)) < MIN_SIZE:
            return f"it is smaller than {MIN_SIZE} pixels"
        return None

    def _site_icons(self, url: str, manifests: Sequence[str] = ()) -> List[str]:
        browser, session = self._page()
        browser.load(session, url, 1280, 720, transparent=False, timeout=25)
        try:
            found = browser.evaluate(session, site_icons(manifests), timeout=20)
        except BrowserError:
            found = []
        browser.load(session, "about:blank", 256, 256)
        return rank(found if isinstance(found, list) else [])

    def _fetch(self, app_id: str, source: Source) -> Tuple[Path, str]:
        """Put the icon ``source`` names in the app's folder, as ``original`` with its file type; return it and its SHA-256."""
        folder = self.folder / app_id
        folder.mkdir(parents=True, exist_ok=True)
        if source.kind == "file":
            candidates = [source.location]
        elif source.kind == "url":
            candidates = [source.location]
        else:
            candidates = self._site_icons(source.location, [source.manifest] if source.manifest else [])
            if not candidates:
                raise ArtworkError(f"{urllib.parse.urlsplit(source.location).netloc} names no icon")
        reasons = []
        for candidate in candidates:
            try:
                data = Path(candidate).read_bytes() if source.kind == "file" else (self.download or fetch)(candidate)
            except (OSError, ArtworkError) as exc:
                reasons.append(str(exc))
                continue
            suffix = _suffix(candidate, data)
            if not suffix:
                reasons.append(f"{candidate} is not an icon")
                continue
            for stale in folder.glob("original.*"):
                stale.unlink()
            icon = folder / f"original{suffix}"
            atomic_write_bytes(icon, data)
            reason = self._usable(icon)
            if reason is None:
                return icon, hashlib.sha256(data).hexdigest()
            reasons.append(f"{Path(candidate).name if source.kind == 'file' else candidate}: {reason}")
            icon.unlink()
        raise ArtworkError("; ".join(reasons[:3]) or "no icon was found")

    def _official(self, app_id: str, official: Dict[str, str], record: dict, refresh: bool) -> Dict[str, Tuple[Path, str, str]]:
        """The library artwork ``app_id``'s project publishes, by slot, as ``(file, SHA-256, address)``: kept from before where the
        address is the same, otherwise downloaded and checked. A slot whose artwork cannot be had, or is smaller than
        :data:`MIN_ART` pixels, is left out, and gets NonSteamApps' design.
        """
        known = record.get("official") if isinstance(record.get("official"), dict) else {}
        found: Dict[str, Tuple[Path, str, str]] = {}
        for slot, url in sorted(official.items()):
            entry = known.get(slot) if isinstance(known.get(slot), dict) else {}
            kept = self.folder / app_id / str(entry.get("file", ""))
            if not refresh and entry.get("url") == url and entry.get("file") and kept.is_file():
                found[slot] = (kept, str(entry.get("sha256", "")), url)
                continue
            try:
                data = (self.download or fetch)(url)
            except ArtworkError:
                continue
            suffix = _suffix(url, data)
            if not suffix:
                continue
            art = self.folder / app_id / f"official-{slot}{suffix}"
            for stale in (self.folder / app_id).glob(f"official-{slot}.*"):
                stale.unlink()
            atomic_write_bytes(art, data)
            ready = self._measure(art)
            if not ready.get("ok") or min(int(ready.get("width") or 0), int(ready.get("height") or 0)) < MIN_ART:
                art.unlink()
                continue
            found[slot] = (art, hashlib.sha256(data).hexdigest(), url)
        return found

    def make(self, app_id: str, name: str, source: Source, refresh: bool = False, official: Optional[Dict[str, str]] = None) -> str:
        """Draw ``app_id``'s artwork around the icon ``source`` names, unless it is already up to date; return what happened.

        ``official`` maps slots to the addresses of library artwork that the app's project publishes itself, which
        those slots use in place of NonSteamApps' design. Returns ``"made"`` or ``"kept"``; raises :class:`ArtworkError`
        when the icon cannot be had or drawn, keeping artwork made before. A ``site`` or ``url`` icon, and the
        project's artwork, are downloaded again only with ``refresh``, or once their address changes.
        """
        official = dict(official or {})
        record = self._record(app_id)
        complete = bool(self.files(app_id))
        known = record.get("official") if isinstance(record.get("official"), dict) else {}
        same_art = official == {slot: entry.get("url") for slot, entry in known.items() if isinstance(entry, dict)}
        if complete and same_art and record.get("source") == source.key and source.kind != "file" and not refresh:
            return "kept"
        if complete and same_art and source.kind == "file" and record.get("source") == source.key:
            try:
                digest = hashlib.sha256(Path(source.location).read_bytes()).hexdigest()
            except OSError as exc:
                raise ArtworkError(f"could not read {source.location}: {exc}") from exc
            if digest == record.get("icon"):
                return "kept"
        icon, digest = self._fetch(app_id, source)
        art = self._official(app_id, official, record, refresh)
        drawn_art = {slot: entry.get("sha256") for slot, entry in known.items() if isinstance(entry, dict)}
        entries = {slot: {"url": url, "sha256": sha, "file": path.name} for slot, (path, sha, url) in art.items()}
        updated = {"version": VERSION, "source": source.key, "icon": digest, "file": icon.name, "official": entries}
        if complete and digest == record.get("icon") and {slot: sha for slot, (_, sha, _) in art.items()} == drawn_art:
            if updated != record:
                atomic_write_json(self.folder / app_id / RECORD, updated)
            return "kept"
        colours = COLOURS.get(app_id, ("#1a9fff", "#66c0f4"))
        browser, session = self._page()
        drawn = {}
        for slot, file, width, height in SLOTS:
            jpeg = file.endswith(".jpg")
            piece = art.get(slot, (None, "", ""))[0]
            browser.load(session, card_url(self.template, slot, name, colours, icon, piece), width, height, transparent=not jpeg)
            ready = browser.evaluate(session, CARD_READY)
            if not isinstance(ready, dict) or not ready.get("ok"):
                raise ArtworkError(f"Helium could not draw {app_id}'s {slot}")
            drawn[file] = browser.screenshot(session, width, height, jpeg)
        for file, data in drawn.items():
            atomic_write_bytes(self.folder / app_id / file, data)
        atomic_write_json(self.folder / app_id / RECORD, updated)
        return "made"
