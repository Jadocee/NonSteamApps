"""Keep NonSteamApps' shortcuts together in a collection in each Steam account's library.

Steam keeps collections in ``userdata/<account>/config/cloudstorage``, in the namespace file that
``cloud-storage-namespaces.json`` marks as current, and merges them with Steam Cloud's copy
("union-collections"). Entries are written as Steam ROM Manager writes its own, while Steam is
closed. Only NonSteamApps' collections are changed; an account whose file does not exist yet is left
alone.

Steam Cloud gives every device of the account the same collections, while each device's shortcuts have
app IDs of their own (see :func:`device.tag`), so each device keeps its apps in a collection of its own,
with an ID of its own (see :func:`collection_id`). Before 2.52.0, every device shared one, ``SHARED_ID``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

from . import steam
from .fsutil import atomic_write_json

SHARED_ID = "nonsteamapps"


def collection_id(tag: str) -> str:
    """The ID of the collection of the device with the tag ``tag``."""
    return f"{SHARED_ID}-{tag}"


def _key(ident: str) -> str:
    return f"user-collections.{ident}"


def storage_file(root: Path, account: int) -> Optional[Path]:
    """The account's current collections file, if Steam has written one."""
    directory = steam.config_dir(root, account) / "cloudstorage"
    namespace = 1
    try:
        versions = json.loads((directory / "cloud-storage-namespaces.json").read_text(encoding="utf-8"))
        newest = max(versions, key=lambda entry: int(entry[1]))
        if int(newest[1]) > 0:
            namespace = int(newest[0])
    except (OSError, ValueError, TypeError, IndexError, KeyError):
        pass
    path = directory / f"cloud-storage-namespace-{namespace}.json"
    return path if path.is_file() else None


def _load(path: Path) -> Optional[list]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _find(entries: list, ident: str) -> Optional[list]:
    for item in entries:
        if isinstance(item, list) and len(item) == 2 and item[0] == _key(ident) and isinstance(item[1], dict):
            return item
    return None


def _value(item: Optional[list]) -> Optional[dict]:
    if item is None or item[1].get("is_deleted"):
        return None
    try:
        value = json.loads(item[1].get("value") or "")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def members(path: Path, ident: str) -> List[int]:
    value = _value(_find(_load(path) or [], ident))
    return list(value.get("added", [])) if value else []


def _write(path: Path, entries: list, ident: str, item: Optional[list], value: Optional[dict]) -> None:
    stamp = int(time.time())
    if value is None:
        item[1].update(is_deleted=True, timestamp=stamp)
    else:
        record = {
            "key": _key(ident),
            "timestamp": stamp,
            "value": json.dumps(value, separators=(",", ":")),
            "version": str(stamp),
            "conflictResolutionMethod": "custom",
            "strMethodId": "union-collections",
        }
        if item is None:
            entries.append([_key(ident), record])
        else:
            item[1] = record
    atomic_write_json(path, entries, compact=True)


def update(path: Path, ident: str, name: str, add: Iterable[int] = (), remove: Iterable[int] = ()) -> bool:
    """Put apps into the collection ``ident``, called ``name``, and take others out; delete it once it is empty.

    Returns whether the file changed. Apps taken out are listed as removed, so that merging with
    Steam Cloud's copy does not bring them back.
    """
    entries = _load(path)
    if entries is None:
        return False
    item = _find(entries, ident)
    current = _value(item)
    added = list(current.get("added", [])) if current else []
    removed = list(current.get("removed", [])) if current else []
    for appid in add:
        if appid not in added:
            added.append(appid)
        if appid in removed:
            removed.remove(appid)
    for appid in remove:
        if appid in added:
            added.remove(appid)
            removed.append(appid)
    if not added:
        if current is None:
            return False
        _write(path, entries, ident, item, None)
        return True
    value = {"id": ident, "name": name, "added": added, "removed": removed}
    if value == current:
        return False
    _write(path, entries, ident, item, value)
    return True


def delete(path: Path, ident: str) -> bool:
    entries = _load(path)
    item = _find(entries or [], ident)
    if _value(item) is None:
        return False
    _write(path, entries, ident, item, None)
    return True
