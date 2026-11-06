"""NonSteamApps' own copy of Lichii, an emulator for Nintendo Switch and Switch 2 games that builds on Eden.

Lichii publishes no Flatpak and signs nothing: each change to its source publishes a GitHub prerelease, tagged
``build-N``, whose Linux builds include self-contained AppImages. NonSteamApps installs the newest release that has
one, after checking the download's size and SHA-256 against what GitHub's API records for the file (see
:mod:`builds`), keeps the build before it for :meth:`Runtime.rollback`, and runs the AppImage as it is. Of the two
x86-64 AppImages it takes the one built with profile-guided optimisation, as Lichii's release notes recommend.
Lichii's project also publishes its icon and artwork for Steam's library (``dist/branding``), which NonSteamApps
takes, at the release installed, for the app's Steam artwork (see :mod:`artwork`).

Lichii keeps Eden's data layout and settings: started in a folder that holds a ``user`` folder, it keeps everything
there, as Eden does. Each Steam account runs it from a folder of its own, laid out as Eden's (see
:class:`apps.PortableProfile`), and so does the shared one, so that Lichii never reads or writes the data of an Eden
installed outside Flatpak, which it would otherwise share.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Sequence, Tuple

from . import builds
from .builds import Build

REPO = "zortos293/Lichii"
ASSET = "lichii-linux-x86_64-pgo.AppImage"
PROGRAM = "lichii.AppImage"
ICON = "dist/branding/lichii_icon.png"
LIBRARY = (
    ("capsule", "dist/branding/lichii_vertical_grid.png"),
    ("wide", "dist/branding/lichii_square_grid.png"),
    ("logo", "dist/branding/lichii_logo.png"),
)
_TAG = re.compile(r"(?:build-([1-9][0-9]*)|local-([0-9a-f]{12}))\Z")
_APPIMAGE = (b"\x7fELF", b"AI\x02")


class LichiiError(RuntimeError):
    """Lichii could not be found, downloaded, checked or installed."""


def valid_tag(text: str) -> bool:
    return bool(_TAG.match(text or ""))


def describe(tag: str) -> str:
    """A build's tag as people read it: its build number, or the start of the SHA-256 of a build installed from a file unchecked."""
    match = _TAG.match(tag or "")
    if not match:
        return tag
    return f"build {match.group(1)}" if match.group(1) else f"local build {match.group(2)}"


def newest_build(releases: Sequence[object], repo: str = REPO) -> Build:
    """The newest of ``releases`` (GitHub's list, newest first) with Lichii's x86-64 AppImage, which must carry a SHA-256.

    Lichii publishes every build as a prerelease, so prereleases count; drafts do not.
    """
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "")
        if not tag.startswith("build-") or not valid_tag(tag):
            continue
        build = builds.checked_asset(release, ASSET, repo, LichiiError)
        if build is not None:
            return build
    raise LichiiError(f"none of {repo}'s recent releases has {ASSET}")


def is_appimage(path: Path) -> bool:
    """Whether ``path`` starts as a type 2 AppImage does: an ELF program carrying the AppImage mark."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(11)
    except OSError:
        return False
    return head[:4] == _APPIMAGE[0] and head[8:11] == _APPIMAGE[1]


class Runtime(builds.Builds):
    """Lichii builds installed under ``root``, each an AppImage in a folder named after its release's tag."""

    label = "Lichii"
    error = LichiiError
    programs = (PROGRAM,)
    running = (PROGRAM,)
    icon = ICON
    library = LIBRARY

    def __init__(self, root: Path, repo: str = REPO) -> None:
        super().__init__(root, repo)

    @property
    def program(self) -> Path:
        """The active build's AppImage, through ``current``."""
        return self.root / "current" / PROGRAM

    def valid(self, tag: str) -> bool:
        return valid_tag(tag)

    def released(self, tag: str) -> bool:
        match = _TAG.match(tag or "")
        return bool(match and match.group(1))

    def describe(self, tag: str) -> str:
        return describe(tag)

    def order(self, tag: str) -> Tuple:
        match = _TAG.match(tag)
        return (int(match.group(1) or 0), tag)

    def newest(self, releases: Sequence[object]) -> Build:
        return newest_build(releases, self.repo)

    def asset(self, tag: str) -> str:
        return ASSET

    def archive_build(self, archive: Path, verify: bool) -> Build:
        """The release whose AppImage ``archive`` is, found by its SHA-256 among the recent ones; unchecked, a build named after it."""
        if not is_appimage(archive):
            raise LichiiError(f"{archive.name} is not an AppImage")
        digest = builds.sha256(archive)
        if not verify:
            return Build(f"local-{digest[:12]}", "", archive.stat().st_size, "")
        for release in self.releases():
            if not isinstance(release, dict) or not valid_tag(str(release.get("tag_name") or "")):
                continue
            try:
                build = newest_build([release], self.repo)
            except LichiiError:
                continue
            if build.sha256 == digest:
                return build
        raise LichiiError(f"{archive.name} is not the {ASSET} of any of Lichii's recent releases, so it was not installed")

    def place(self, archive: Path, folder: Path) -> None:
        if not is_appimage(archive):
            raise LichiiError(f"{Path(archive).name} is not an AppImage")
        target = Path(folder) / PROGRAM
        shutil.copyfile(archive, target)
        os.chmod(target, 0o755)
