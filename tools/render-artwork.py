#!/usr/bin/env python3
"""Draw the artwork NonSteamApps ships, assets/artwork/<app>, around each app's icon in assets/src/<app>/icon.svg.

It draws with the template and code NonSteamApps draws with on a device, around an app's own icon
(src/share/artwork and nonsteamapps.artwork), in a headless Chromium: $CHROMIUM, else Chromium or Google
Chrome on PATH, else the one Playwright keeps.

Usage: tools/render-artwork.py [APP...]
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "lib"))

from nonsteamapps import apps, artwork  # noqa: E402


def chromium() -> Path:
    """The Chromium to draw with."""
    candidates = [os.environ.get("CHROMIUM", "")]
    candidates += [shutil.which(name) or "" for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")]
    candidates += sorted(str(path) for path in Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    candidates.append("/opt/pw-browsers/chromium")
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return Path(candidate)
    raise SystemExit("no Chromium found; set CHROMIUM to one")


def main(names) -> int:
    try:
        chosen = [apps.by_id(name) for name in names] or list(apps.APPS)
    except KeyError as exc:
        raise SystemExit(f"unknown app {exc}; choose from: {', '.join(apps.ids())}") from None
    program = chromium()
    with tempfile.TemporaryDirectory(prefix="nonsteamapps-render.") as work:
        with artwork.Studio(Path(work), ROOT / "src" / "share" / "artwork", lambda: artwork.Browser(program, timeout=120)) as studio:
            for app in chosen:
                icon = ROOT / "assets" / "src" / app.id / "icon.svg"
                studio.make(app.id, app.name, artwork.Source("file", str(icon)))
                target = ROOT / "assets" / "artwork" / app.id
                target.mkdir(parents=True, exist_ok=True)
                for path in studio.files(app.id).values():
                    shutil.copyfile(path, target / path.name)
                print(f"drew assets/artwork/{app.id} around assets/src/{app.id}/icon.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
