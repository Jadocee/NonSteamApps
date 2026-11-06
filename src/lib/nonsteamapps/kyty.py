"""NonSteamApps' own copy of KytyPS5, a translation layer that runs PlayStation 5 games on Linux.

KytyPS5 publishes no Flatpak and signs nothing: each change to its main branch publishes a GitHub release
whose Linux build is a tarball. NonSteamApps installs the newest release that has one, after checking the
download's size and SHA-256 against what GitHub's API records for the file (see :mod:`builds`). It unpacks
each build beside the others, points ``current`` at the active one and keeps two, for :meth:`Runtime.rollback`.

KytyPS5's launcher starts the emulator in the emulator's own folder, where saves, trophies and caches are
kept, and keeps its settings in ``Kyty.ini`` in the folder it is started in. Each Steam account therefore
gets a folder of its own (:meth:`Runtime.prepare_home`), in which the build's programs are hard links, so
that KytyPS5 takes that folder as its own, and everything else is a symbolic link into the build. Saves and
settings stay there when the build changes. KytyPS5's own updater is left out of that folder.

Games are shared by every account, their saves and settings are not: a game's downloaded content and the
shader caches built from it live once, in a ``games`` folder beside the accounts' folders
(:func:`share_game_data`), and an account that starts KytyPS5 for the first time gets the game folders that
another account set up (:func:`game_folders`).
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import builds
from .builds import Build

REPO = "KytyPS5/KytyPS5"
LAUNCHER = "kyty_launcher"
EMULATOR = "kyty_emulator"
UPDATER = "kyty_updater"
SETTINGS_FILE = "Kyty.ini"
ICON = "src/launcher/icons/kyty.svg"
LINK_RECORD = ".nonsteamapps-links.json"
GAMES = "games"
DEFAULT_GAMES = Path("Games") / "PS5"
SHARED_DATA = ("_DownloadData", "_PipelineCache")
_TAG = re.compile(r"KytyPS5-(\d{4}-\d{2}-\d{2})-([0-9a-f]{7,40})\Z")
_ARCHIVE = re.compile(r"(KytyPS5-\d{4}-\d{2}-\d{2}-[0-9a-f]{7,40})-Linux-x86_64\.tar\.gz\Z")


class KytyError(RuntimeError):
    """KytyPS5 could not be found, downloaded, checked or installed."""


def valid_tag(text: str) -> bool:
    return bool(_TAG.match(text or ""))


def describe(tag: str) -> str:
    """A build's tag as people read it: its date and commit."""
    match = _TAG.match(tag or "")
    return f"{match.group(1)} ({match.group(2)[:7]})" if match else tag


def asset_name(tag: str) -> str:
    return f"{tag}-Linux-x86_64.tar.gz"


def newest_build(releases: Sequence[object], repo: str = REPO) -> Build:
    """The newest of ``releases`` (GitHub's list, newest first) with a Linux build, which must carry a SHA-256."""
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        if not valid_tag(tag):
            continue
        build = builds.checked_asset(release, asset_name(tag), repo, KytyError)
        if build is not None:
            return build
    raise KytyError(f"none of {repo}'s recent releases has a Linux build")


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


class Runtime(builds.Builds):
    """KytyPS5 builds installed under ``root``."""

    label = "KytyPS5"
    error = KytyError
    programs = (LAUNCHER, EMULATOR)
    running = (LAUNCHER, EMULATOR, UPDATER)
    icon = ICON

    def __init__(self, root: Path, repo: str = REPO) -> None:
        super().__init__(root, repo)

    def valid(self, tag: str) -> bool:
        return valid_tag(tag)

    def describe(self, tag: str) -> str:
        return describe(tag)

    def order(self, tag: str) -> Tuple:
        return (_TAG.match(tag).group(1), tag)

    def newest(self, releases: Sequence[object]) -> Build:
        return newest_build(releases, self.repo)

    def asset(self, tag: str) -> str:
        return asset_name(tag)

    def archive_tag(self, name: str) -> Optional[str]:
        match = _ARCHIVE.match(name)
        return match.group(1) if match else None

    def place(self, archive: Path, folder: Path) -> None:
        result = subprocess.run(
            ["tar", "-xzf", str(archive), "-C", str(folder), "--no-same-owner"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise KytyError(f"could not unpack {Path(archive).name}: {result.stderr.strip()}")
        check_tree(folder)
        if not all(os.access(folder / name, os.X_OK) and not (folder / name).is_symlink() for name in (LAUNCHER, EMULATOR)):
            raise KytyError(f"unexpected KytyPS5 archive layout in {Path(archive).name}")

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


def share_game_data(home: Path, games: Path) -> List[str]:
    """Make ``home``'s folders for game content links into ``games``; return the ones that had to stay as they were.

    What such a folder already holds is moved into ``games`` first, without replacing anything there; a folder
    left with anything in it stays, and so does a link the user made.
    """
    home, games = Path(home), Path(games)
    home.mkdir(parents=True, exist_ok=True)
    kept = []
    for name in SHARED_DATA:
        shared, link = games / name, home / name
        shared.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            continue
        if link.is_dir():
            for entry in sorted(link.iterdir()):
                if not os.path.lexists(shared / entry.name):
                    entry.rename(shared / entry.name)
            try:
                link.rmdir()
            except OSError:
                kept.append(name)
                continue
        elif os.path.lexists(link):
            kept.append(name)
            continue
        link.symlink_to(os.path.relpath(shared, home))
    return kept


def listed_game_folders(settings_file: Path) -> List[str]:
    """The game folders a ``Kyty.ini`` lists, as KytyPS5 reads them: ``game_dirs``, or else the older ``game_dir``."""
    for key in ("game_dirs", "game_dir"):
        value = game_folders([settings_file], keys=(key,))
        if value:
            return [folder.strip() for folder in next(csv.reader([value], skipinitialspace=True)) if folder.strip()]
    return []


def game_folders_value(folders: Sequence[str]) -> str:
    """``folders`` as QSettings writes a list in an INI file, with a folder that holds a comma in quotes."""
    return ", ".join('"' + folder.replace('"', '\\"') + '"' if "," in folder or '"' in folder else folder for folder in folders)


def game_folders(settings_files: Sequence[Path], keys: Sequence[str] = ("game_dirs",)) -> Optional[str]:
    """The game folders that the most recently saved of these ``Kyty.ini`` files lists under ``keys``, as KytyPS5 wrote them.

    ``game_dir`` is the single folder older launchers kept, which KytyPS5 still reads when ``game_dirs`` is empty.
    """
    found = []
    for path in settings_files:
        try:
            stamp, lines = Path(path).stat().st_mtime, Path(path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        group = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                group = stripped[1:-1]
                continue
            key, separator, value = stripped.partition("=")
            if group == "Launcher" and separator and key.strip() in keys and value.strip():
                found.append((stamp, value.strip()))
    return max(found)[1] if found else None
