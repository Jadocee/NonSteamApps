"""Update NonSteamApps itself from where it was installed, leaving the apps and settings as they are.

When ``install.sh`` starts an install it names its source: the archive it downloaded, or the folder it ran
from. ``nonsteamapps update`` fetches that source again and runs its ``install.sh`` to copy only the program
into place, so the new version lays out its own files, then hands over to the new launcher to update the apps.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

from . import net
from .config import Paths
from .fsutil import atomic_write_json

SOURCE_VARIABLE = "NONSTEAMAPPS_SOURCE"
COPY_ONLY_VARIABLE = "NONSTEAMAPPS_COPY_ONLY"
UPDATED_FROM_VARIABLE = "NONSTEAMAPPS_UPDATED_FROM"
DEFAULT_SOURCE = "https://github.com/Jadocee/NonSteamApps/archive/main.tar.gz"
RENAMED_SOURCE = "https://github.com/jadocee/steamos-yt/archive/main.tar.gz"


class UpdateError(RuntimeError):
    """NonSteamApps could not be fetched or copied into place."""


def remember(paths: Paths, environ: Mapping[str, str]) -> None:
    """Keep the source ``install.sh`` names, for later updates."""
    source = environ.get(SOURCE_VARIABLE, "").strip()
    if source:
        atomic_write_json(paths.source, {"source": source})


def source(paths: Paths) -> str:
    """The recorded source, or NonSteamApps' GitHub archive when there is none or the recorded folder is gone.

    An archive recorded under the repository's former name, ``steamos-yt``, is read as the archive under its own.
    """
    try:
        value = json.loads(paths.source.read_text(encoding="utf-8")).get("source")
    except (OSError, ValueError, AttributeError):
        value = None
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_SOURCE
    if os.path.isabs(value) and not (Path(value) / "install.sh").is_file():
        return DEFAULT_SOURCE
    if value.strip().lower() == RENAMED_SOURCE:
        return DEFAULT_SOURCE
    return value


def fetch(source: str, work: Path) -> Path:
    """A folder holding the source's project: a local copy as it is, or the archive downloaded and unpacked in ``work``."""
    if os.path.isabs(source):
        return Path(source)
    archive = Path(work) / "nonsteamapps.tar.gz"
    try:
        net.download(source, archive)
    except (OSError, ValueError) as exc:
        raise UpdateError(f"could not download {source}: {exc}") from exc
    tree = Path(work) / "source"
    tree.mkdir()
    result = subprocess.run(
        ["tar", "-xzf", str(archive), "-C", str(tree), "--strip-components=1", "--no-same-owner"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not (tree / "install.sh").is_file():
        raise UpdateError(f"{source} is not a NonSteamApps archive{': ' + result.stderr.strip() if result.stderr.strip() else ''}")
    return tree


def copy(tree: Path, program: Path, environ: Mapping[str, str]) -> None:
    """Copy the program in ``tree`` over ``program`` with the tree's own ``install.sh``."""
    env = {key: value for key, value in environ.items() if key != SOURCE_VARIABLE}
    env.update({COPY_ONLY_VARIABLE: "1", "NONSTEAMAPPS_HOME": str(program)})
    result = subprocess.run(
        ["bash", str(Path(tree) / "install.sh")],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        raise UpdateError(lines[-1] if lines else f"its install.sh failed with status {result.returncode}")
