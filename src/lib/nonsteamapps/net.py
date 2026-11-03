"""Downloads for Helium's releases and NonSteamApps' own updates, sent with NonSteamApps' user agent."""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path

TIMEOUT = 30


def request(url: str, accept: str = "") -> urllib.request.Request:
    headers = {"User-Agent": "nonsteamapps"}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def fetch_text(url: str, accept: str = "") -> str:
    with urllib.request.urlopen(request(url, accept), timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def final_url(url: str) -> str:
    """Where ``url`` leads after its redirects."""
    with urllib.request.urlopen(request(url), timeout=TIMEOUT) as response:
        return response.geturl()


def download(url: str, target: Path) -> None:
    """Save ``url`` as ``target``, which never holds part of a download."""
    target = Path(target)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request(url), timeout=TIMEOUT) as response, open(partial, "wb") as output:
            shutil.copyfileobj(response, output, 1 << 20)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
