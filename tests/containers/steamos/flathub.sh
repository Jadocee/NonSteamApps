#!/usr/bin/env bash
# Checks that Flathub still publishes every Flatpak NonSteamApps installs, under the ID and branch it installs, with
# SteamOS's own flatpak: the apps, and the SDK and runtime Eden-NX2 builds with. It needs the internet, and installs
# nothing.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.."

flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
mapfile -t refs < <(python3 -I - src/lib <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from nonsteamapps import apps, nx2
for app in apps.APPS:
    if app.flatpak and not app.from_source:
        print(app.ref)
for ref in (nx2.SDK, nx2.RUNTIME):
    print(f"{ref}//{nx2.RUNTIME_VERSION}")
PY
)
failed=0
for ref in "${refs[@]}"; do
    if flatpak remote-info --user flathub "$ref" >/dev/null 2>&1; then
        echo "    ok: $ref"
    else
        echo "    FAIL $ref is not on Flathub"
        failed=1
    fi
done
exit "$failed"
