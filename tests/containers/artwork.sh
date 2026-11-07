#!/usr/bin/env bash
# Draws every app's artwork with tools/render-artwork.py and the image's Chromium, in a copy of the repository, and
# checks that each app got its five images. The repository itself is left as it is.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir "$WORK/repo"
tar --exclude=.git -C "$ROOT" -cf - . | tar -C "$WORK/repo" -xf -
find "$WORK/repo/assets/artwork" -type f -delete
CHROMIUM=${CHROMIUM:-$(command -v chromium)} python3 "$WORK/repo/tools/render-artwork.py"

python3 -I - "$WORK/repo" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src" / "lib"))
from nonsteamapps import apps
wanted = ["capsule.png", "hero.jpg", "icon.png", "logo.png", "wide.png"]
missing = [f"{app.id}/{name}" for app in apps.APPS for name in wanted if not (root / "assets" / "artwork" / app.id / name).is_file()]
if missing:
    sys.exit("not drawn: " + ", ".join(missing))
print(f"drew {len(apps.APPS)} apps' artwork, {len(wanted)} images each")
PY
