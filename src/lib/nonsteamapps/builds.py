"""Builds that NonSteamApps downloads itself from a project's GitHub releases, as it does for KytyPS5 and Lichii.

Neither project publishes a Flatpak or signs its builds, so a download is installed only once its size and SHA-256
match what GitHub's API records for the file. Each build is kept in a folder named after its release's tag,
``current`` points at the active one, and the one before it stays, for :meth:`Builds.rollback`. A subclass says
which releases and files are the project's builds and how a build is laid out once installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Type

from . import net, ui

KEEP = 2
BUILD_RECORD = ".nonsteamapps.json"
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")


@dataclass(frozen=True)
class Build:
    """A release's build for this machine, as GitHub's API describes it."""

    tag: str
    url: str
    size: int
    sha256: str
    published: str = ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_asset(release: dict, name: str, repo: str, error: Type[Exception]) -> Optional[Build]:
    """The file ``name`` among ``release``'s, or ``None`` if it has none.

    Raises ``error`` unless the file is one of ``repo``'s own downloads and GitHub records its size and SHA-256.
    """
    asset = next((item for item in release.get("assets") or [] if isinstance(item, dict) and item.get("name") == name), None)
    if asset is None:
        return None
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith(f"https://github.com/{repo}/releases/download/"):
        raise error(f"{name} is not among {repo}'s own releases, so it was not installed")
    digest = _DIGEST.match(str(asset.get("digest") or ""))
    if not digest:
        raise error(f"GitHub records no SHA-256 for {name}, so it was not installed")
    size = asset.get("size")
    if not isinstance(size, int) or size <= 0:
        raise error(f"GitHub records no size for {name}, so it was not installed")
    return Build(str(release.get("tag_name") or ""), url, size, digest.group(1), str(release.get("published_at") or ""))


class Builds:
    """A project's builds installed under ``root``, from its GitHub repository ``repo``.

    ``label`` names the project in messages and ``error`` is its exception. A complete build holds the executable
    ``programs``; ``running`` are the files a process started from the build can be running, which :meth:`prune`
    keeps the build for.
    """

    label = ""
    error: Type[Exception] = RuntimeError
    programs: Tuple[str, ...] = ()
    running: Tuple[str, ...] = ()
    icon = ""

    def __init__(self, root: Path, repo: str) -> None:
        self.root = Path(root)
        self.repo = repo

    def valid(self, tag: str) -> bool:
        """Whether ``tag`` is how the project tags a release with a build."""
        raise NotImplementedError

    def describe(self, tag: str) -> str:
        """A build's tag as people read it."""
        return tag

    def order(self, tag: str) -> Tuple:
        """How a build sorts among the others, after its release's publication time; the newest sorts last."""
        return (tag,)

    def newest(self, releases: Sequence[object]) -> Build:
        """The newest of ``releases`` (GitHub's list, newest first) with a build for this machine."""
        raise NotImplementedError

    def asset(self, tag: str) -> str:
        """The name of the file that holds release ``tag``'s build."""
        raise NotImplementedError

    def archive_tag(self, name: str) -> Optional[str]:
        """The tag of the release a downloaded file named ``name`` comes from, or ``None`` if none is named so."""
        return None

    def archive_build(self, archive: Path, verify: bool) -> Build:
        """The build a downloaded file is: its release, as GitHub records it, or unchecked only what the file itself says."""
        tag = self.archive_tag(archive.name)
        if not tag:
            raise self.error(f"{archive.name} is not named like a {self.label} Linux build")
        return self.build(tag) if verify else Build(tag, "", archive.stat().st_size, "")

    def place(self, archive: Path, folder: Path) -> None:
        """Lay the build in ``archive`` out in the empty ``folder``, raising ``error`` for one that is not laid out as expected."""
        raise NotImplementedError

    def released(self, tag: str) -> bool:
        """Whether ``tag`` names one of the project's releases, rather than a build installed from a file unchecked."""
        return self.valid(tag)

    def icon_url(self, tag: Optional[str] = None) -> Optional[str]:
        """Where the project keeps ``icon``, its app's icon, at the release ``tag``, the active build's by default."""
        tag = tag or self.current()
        return f"https://raw.githubusercontent.com/{self.repo}/{tag}/{self.icon}" if self.icon and tag and self.released(tag) else None

    def check_machine(self) -> None:
        machine = platform.machine().lower()
        if machine not in ("x86_64", "amd64"):
            raise self.error(f"{self.label} runs only on x86-64 processors, not {machine}")

    @property
    def downloads(self) -> Path:
        return self.root / ".downloads"

    def _complete(self, tag: str) -> bool:
        return self.valid(tag) and all(os.access(self.root / tag / name, os.X_OK) for name in self.programs)

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
        return sorted(found, key=lambda tag: (self._published(tag), *self.order(tag)), reverse=True)

    def releases(self) -> List[object]:
        try:
            data = json.loads(net.fetch_text(f"https://api.github.com/repos/{self.repo}/releases?per_page=30", "application/vnd.github+json"))
        except (OSError, ValueError) as exc:
            raise self.error(f"could not read {self.label}'s releases from GitHub: {exc}") from exc
        if not isinstance(data, list):
            raise self.error(f"GitHub's answer about {self.label}'s releases was not a list")
        return data

    def latest(self) -> Build:
        return self.newest(self.releases())

    def build(self, tag: str) -> Build:
        """The release ``tag``'s build, as GitHub records it."""
        for release in self.releases():
            if isinstance(release, dict) and release.get("tag_name") == tag:
                return self.newest([release])
        raise self.error(f"{tag} is not among {self.label}'s recent releases on GitHub")

    def download(self, build: Build) -> Path:
        self.downloads.mkdir(parents=True, exist_ok=True)
        archive = self.downloads / self.asset(build.tag)
        ui.info(f"Downloading {archive.name} ({build.size / 1048576:.0f} MB)")
        try:
            net.download(build.url, archive)
        except OSError as exc:
            raise self.error(f"could not download {archive.name}: {exc}") from exc
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
            self.place(archive, staging)
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
        """Whether a running process was started from one of the build's ``running`` files, through any of its links."""
        programs = set()
        for name in self.running:
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
        self.check_machine()
        if archive is not None:
            archive = Path(archive).resolve()
            build = self.archive_build(archive, verify)
        else:
            build = build or self.latest()
            if self._complete(build.tag):
                self.activate(build.tag)
                return build.tag
            archive = self.download(build)
        if build.sha256 and self.verify(archive, build):
            ui.ok(f"Checked {self.label} {self.describe(build.tag)} against the SHA-256 GitHub records for it")
        elif verify:
            raise self.error(
                f"{self.label} {self.describe(build.tag)} does not match the size and SHA-256 GitHub records for it, so it was not installed"
            )
        else:
            ui.warn(f"installing {self.label} {self.describe(build.tag)} without checking it against GitHub (--skip-verify)")
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
            raise self.error(f"no other {self.label} build is installed to switch back to")
        self.activate(others[0])
        return others[0]

    def remove(self) -> None:
        if self.root.is_dir():
            shutil.rmtree(self.root)
