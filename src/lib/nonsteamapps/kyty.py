"""NonSteamApps' own copy of KytyPS5, a translation layer that runs PlayStation 5 games on Linux.

KytyPS5 publishes no Flatpak and signs nothing: each change to its main branch publishes a GitHub release
whose Linux build is a tarball. NonSteamApps installs the newest release that has one, after checking the
download's size and SHA-256 against what GitHub's API records for the file. It unpacks each build beside
the others, points ``current`` at the active one and keeps two, for :meth:`Runtime.rollback`.

KytyPS5's launcher starts the emulator in the emulator's own folder, where saves, trophies and caches are
kept, and keeps its settings in ``Kyty.ini`` in the folder it is started in. Each Steam account therefore
gets a folder of its own (:meth:`Runtime.prepare_home`), in which the build's programs are hard links, so
that KytyPS5 takes that folder as its own, and everything else is a symbolic link into the build. Saves and
settings stay there when the build changes. KytyPS5's own updater is left out of that folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from . import net, ui

REPO = "KytyPS5/KytyPS5"
KEEP = 2
LAUNCHER = "kyty_launcher"
EMULATOR = "kyty_emulator"
UPDATER = "kyty_updater"
SETTINGS_FILE = "Kyty.ini"
BUILD_RECORD = ".nonsteamapps.json"
LINK_RECORD = ".nonsteamapps-links.json"
_TAG = re.compile(r"KytyPS5-(\d{4}-\d{2}-\d{2})-([0-9a-f]{7,40})\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
_ARCHIVE = re.compile(r"(KytyPS5-\d{4}-\d{2}-\d{2}-[0-9a-f]{7,40})-Linux-x86_64\.tar\.gz\Z")


class KytyError(RuntimeError):
    """KytyPS5 could not be found, downloaded, checked or installed."""


@dataclass(frozen=True)
class Build:
    """A KytyPS5 release's Linux build, as GitHub's API describes it."""

    tag: str
    url: str
    size: int
    sha256: str
    published: str = ""


def valid_tag(text: str) -> bool:
    return bool(_TAG.match(text or ""))


def describe(tag: str) -> str:
    """A build's tag as people read it: its date and commit."""
    match = _TAG.match(tag or "")
    return f"{match.group(1)} ({match.group(2)[:7]})" if match else tag


def asset_name(tag: str) -> str:
    return f"{tag}-Linux-x86_64.tar.gz"


def check_machine() -> None:
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise KytyError(f"KytyPS5 runs only on x86-64 processors, not {machine}")


def newest_build(releases: Sequence[object], repo: str = REPO) -> Build:
    """The newest of ``releases`` (GitHub's list, newest first) with a Linux build, which must carry a SHA-256."""
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        if not valid_tag(tag):
            continue
        asset = next((item for item in release.get("assets") or [] if isinstance(item, dict) and item.get("name") == asset_name(tag)), None)
        if asset is None:
            continue
        url = str(asset.get("browser_download_url") or "")
        if not url.startswith(f"https://github.com/{repo}/releases/download/"):
            raise KytyError(f"{asset_name(tag)} is not among {repo}'s own releases, so it was not installed")
        digest = _DIGEST.match(str(asset.get("digest") or ""))
        if not digest:
            raise KytyError(f"GitHub records no SHA-256 for {asset_name(tag)}, so it was not installed")
        size = asset.get("size")
        if not isinstance(size, int) or size <= 0:
            raise KytyError(f"GitHub records no size for {asset_name(tag)}, so it was not installed")
        return Build(tag, url, size, digest.group(1), str(release.get("published_at") or ""))
    raise KytyError(f"none of {repo}'s recent releases has a Linux build")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_tree(root: Path) -> None:
    """Refuse an unpacked build that holds anything but files, folders and links that stay inside it."""
    top = os.path.realpath(root)
    for folder, directories, files in os.walk(root):
        for name in directories + files:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                target = os.readlink(path)
                resolved = os.path.normpath(os.path.join(os.path.realpath(folder), target))
                if os.path.isabs(target) or os.path.commonpath([top, resolved]) != top:
                    raise KytyError(f"the build links outside itself ({os.path.relpath(path, root)} -> {target})")
            elif not (os.path.isdir(path) or os.path.isfile(path)):
                raise KytyError(f"the build holds something that is neither a file nor a folder ({os.path.relpath(path, root)})")


def _linkable(name: str) -> bool:
    return not name.startswith((".", "_")) and name not in (SETTINGS_FILE, UPDATER)


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _replace(target: Path, make) -> None:
    temporary = target.with_name(f".{target.name}.new")
    if os.path.lexists(temporary):
        temporary.unlink()
    make(temporary)
    os.replace(temporary, target)


def _hardlink(source: Path, temporary: Path) -> None:
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)


class Runtime:
    """KytyPS5 builds installed under ``root``."""

    def __init__(self, root: Path, repo: str = REPO) -> None:
        self.root = Path(root)
        self.repo = repo

    @property
    def downloads(self) -> Path:
        return self.root / ".downloads"

    def _complete(self, tag: str) -> bool:
        return valid_tag(tag) and all(os.access(self.root / tag / name, os.X_OK) for name in (LAUNCHER, EMULATOR))

    def _published(self, tag: str) -> str:
        try:
            return str(json.loads((self.root / tag / BUILD_RECORD).read_text(encoding="utf-8")).get("published", ""))
        except (OSError, ValueError, AttributeError):
            return ""

    def current(self) -> Optional[str]:
        try:
            target = os.readlink(self.root / "current")
        except OSError:
            return None
        return target if self._complete(target) else None

    def versions(self) -> List[str]:
        """Installed builds, newest first."""
        if not self.root.is_dir():
            return []
        found = [path.name for path in self.root.iterdir() if self._complete(path.name)]
        return sorted(found, key=lambda tag: (self._published(tag), _TAG.match(tag).group(1), tag), reverse=True)

    def releases(self) -> List[object]:
        try:
            data = json.loads(net.fetch_text(f"https://api.github.com/repos/{self.repo}/releases?per_page=30", "application/vnd.github+json"))
        except (OSError, ValueError) as exc:
            raise KytyError(f"could not read KytyPS5's releases from GitHub: {exc}") from exc
        if not isinstance(data, list):
            raise KytyError("GitHub's answer about KytyPS5's releases was not a list")
        return data

    def latest(self) -> Build:
        return newest_build(self.releases(), self.repo)

    def build(self, tag: str) -> Build:
        """The release ``tag``'s Linux build, as GitHub records it."""
        for release in self.releases():
            if isinstance(release, dict) and release.get("tag_name") == tag:
                return newest_build([release], self.repo)
        raise KytyError(f"{tag} is not among KytyPS5's recent releases on GitHub")

    def download(self, build: Build) -> Path:
        self.downloads.mkdir(parents=True, exist_ok=True)
        archive = self.downloads / asset_name(build.tag)
        ui.info(f"Downloading {archive.name} ({build.size / 1048576:.0f} MB)")
        try:
            net.download(build.url, archive)
        except OSError as exc:
            raise KytyError(f"could not download {archive.name}: {exc}") from exc
        return archive

    @staticmethod
    def verify(archive: Path, build: Build) -> bool:
        """Whether ``archive`` has the size and SHA-256 that GitHub records for ``build``."""
        return Path(archive).stat().st_size == build.size and sha256(archive) == build.sha256

    def unpack(self, archive: Path, build: Build) -> None:
        if self._complete(build.tag):
            return
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".unpack.", dir=str(self.root)))
        try:
            result = subprocess.run(
                ["tar", "-xzf", str(archive), "-C", str(staging), "--no-same-owner"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise KytyError(f"could not unpack {Path(archive).name}: {result.stderr.strip()}")
            check_tree(staging)
            if not all(os.access(staging / name, os.X_OK) and not (staging / name).is_symlink() for name in (LAUNCHER, EMULATOR)):
                raise KytyError(f"unexpected KytyPS5 archive layout in {Path(archive).name}")
            record = {"tag": build.tag, "published": build.published, "sha256": build.sha256}
            (staging / BUILD_RECORD).write_text(json.dumps(record), encoding="utf-8")
            target = self.root / build.tag
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def activate(self, tag: str) -> None:
        link = self.root / ".current.new"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(tag)
        os.replace(link, self.root / "current")

    def in_use(self, tag: str) -> bool:
        """Whether a running process was started from one of the build's programs, through any of its links."""
        programs = set()
        for name in (LAUNCHER, EMULATOR, UPDATER):
            try:
                found = os.stat(self.root / tag / name)
            except OSError:
                continue
            programs.add((found.st_dev, found.st_ino))
        for exe in Path("/proc").glob("[0-9]*/exe"):
            try:
                found = os.stat(exe)
            except OSError:
                continue
            if (found.st_dev, found.st_ino) in programs:
                return True
        return False

    def prune(self) -> List[str]:
        """Delete all but the active build and the newest other one, unless still running."""
        current = self.current()
        keep = [current] if current else []
        for tag in self.versions():
            if len(keep) >= KEEP:
                break
            if tag not in keep:
                keep.append(tag)
        removed = []
        for tag in self.versions():
            if tag not in keep and not self.in_use(tag):
                shutil.rmtree(self.root / tag)
                removed.append(tag)
        return removed

    def install(self, archive: Optional[Path] = None, verify: bool = True, build: Optional[Build] = None) -> str:
        """Install the newest build, ``build``, or the build in ``archive``; return its tag."""
        check_machine()
        if archive is not None:
            archive = Path(archive).resolve()
            match = _ARCHIVE.match(archive.name)
            if not match:
                raise KytyError(f"{archive.name} is not named like a KytyPS5 Linux build")
            build = Build(match.group(1), "", archive.stat().st_size, "") if not verify else self.build(match.group(1))
        else:
            build = build or self.latest()
            if self._complete(build.tag):
                self.activate(build.tag)
                return build.tag
            archive = self.download(build)
        if build.sha256 and self.verify(archive, build):
            ui.ok(f"Checked KytyPS5 {describe(build.tag)} against the SHA-256 GitHub records for it")
        elif verify:
            raise KytyError(
                f"KytyPS5 {describe(build.tag)} does not match the size and SHA-256 GitHub records for it, so it was not installed"
            )
        else:
            ui.warn(f"installing KytyPS5 {describe(build.tag)} without checking it against GitHub (--skip-verify)")
        self.unpack(archive, build)
        self.activate(build.tag)
        self.prune()
        shutil.rmtree(self.downloads, ignore_errors=True)
        return build.tag

    def update(self) -> Optional[str]:
        """Install and switch to the newest build, unless it is already the active one; return its tag."""
        build = self.latest()
        if self.current() == build.tag:
            return None
        return self.install(build=build)

    def rollback(self) -> str:
        current = self.current()
        others = [tag for tag in self.versions() if tag != current]
        if not others:
            raise KytyError("no other KytyPS5 build is installed to switch back to")
        self.activate(others[0])
        return others[0]

    def remove(self) -> None:
        if self.root.is_dir():
            shutil.rmtree(self.root)

    def prepare_home(self, home: Path) -> Path:
        """Point the folder ``home`` at the active build, keeping KytyPS5's data in it; return its launcher.

        The build's programs are linked in hard, everything else symbolically. A name that NonSteamApps did not
        link before, and that is not a link, is the user's and stays.
        """
        tag = self.current()
        if not tag:
            raise KytyError("KytyPS5 is not installed")
        build = self.root / tag
        home = Path(home)
        home.mkdir(parents=True, exist_ok=True)
        record = home / LINK_RECORD
        try:
            linked = {str(name) for name in json.loads(record.read_text(encoding="utf-8"))}
        except (OSError, ValueError, TypeError):
            linked = set()
        names = sorted(entry.name for entry in build.iterdir() if _linkable(entry.name))
        for name in sorted(linked - set(names)):
            stale = home / name
            if stale.is_symlink() or stale.is_file():
                stale.unlink()
        for name in names:
            source, target = build / name, home / name
            if os.path.lexists(target) and not target.is_symlink() and (name not in linked or target.is_dir()):
                continue
            if source.is_file() and not source.is_symlink() and os.access(source, os.X_OK):
                if not target.is_symlink() and _same_file(source, target):
                    continue
                _replace(target, lambda temporary, source=source: _hardlink(source, temporary))
            elif not (target.is_symlink() and os.readlink(target) == str(source)):
                _replace(target, lambda temporary, source=source: temporary.symlink_to(source))
        record.write_text(json.dumps(names), encoding="utf-8")
        return home / LAUNCHER


def unlink_home(home: Path) -> List[str]:
    """Remove the links :meth:`Runtime.prepare_home` made in ``home``, keeping KytyPS5's data; return their names."""
    home = Path(home)
    record = home / LINK_RECORD
    try:
        linked = [str(name) for name in json.loads(record.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []
    removed = []
    for name in linked:
        target = home / name
        if _linkable(name) and (target.is_symlink() or target.is_file()):
            target.unlink()
            removed.append(name)
    record.unlink()
    return removed
