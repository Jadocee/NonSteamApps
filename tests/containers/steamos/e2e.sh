#!/usr/bin/env bash
# A real install on SteamOS's own packages, in the SteamOS image: install.sh installs LocalSend from Flathub with
# SteamOS's flatpak, into a throwaway home with stand-in Steam accounts; LocalSend then starts in its sandbox, and
# NonSteamApps removes it again. The container has no D-Bus, so a private bus stands in for the session and system
# buses: flatpak asks the system bus about parental controls before it installs an app, and skips the check when no
# service there answers. It needs the internet, and about 2 GB for LocalSend and its runtime, which go with the
# container.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)
WORK=$(mktemp -d)
HOME_DIR="$WORK/home"
APP=org.localsend.localsend_app
BUS="unix:path=$WORK/bus"
failed=0
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$HOME_DIR" "$WORK/bin" "$WORK/runtime"
chmod 700 "$WORK/runtime"
for fake in steam systemctl; do
    ln -s "$ROOT/tests/fakes/$fake" "$WORK/bin/$fake"
done
python3 -I - "$ROOT/tests" "$HOME_DIR" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import _fakes
_fakes.make_steam(Path(sys.argv[2]))
PY

run() {
    env -i HOME="$HOME_DIR" PATH="$WORK/bin:/usr/local/bin:/usr/bin" USER="$(id -un)" LANG=C.UTF-8 NO_COLOR=1 \
        XDG_RUNTIME_DIR="$WORK/runtime" DBUS_SESSION_BUS_ADDRESS="$BUS" DBUS_SYSTEM_BUS_ADDRESS="$BUS" \
        ${HTTPS_PROXY:+HTTPS_PROXY="$HTTPS_PROXY"} "$@"
}

bus=$(run dbus-daemon --session --fork --address="$BUS" --print-pid)
trap 'rm -rf "$WORK"; kill "$bus"' EXIT

check() {
    local message=$1
    shift
    if "$@"; then
        echo "    ok: $message"
    else
        echo "    FAIL $message"
        failed=1
    fi
}

# shellcheck disable=SC2317,SC2329 # run through check
installed() {
    run flatpak list --user --app --columns=application | grep -qx "$APP"
}

# shellcheck disable=SC2317,SC2329 # run through check
uninstalled() {
    ! installed
}

# shellcheck disable=SC2317,SC2329 # run through check
no_runtimes() {
    [ -z "$(run flatpak list --user --runtime --columns=application)" ]
}

# shellcheck disable=SC2317,SC2329 # run through check
shortcuts() {
    python3 -I - "$ROOT/src/lib" "$HOME_DIR/.local/share/Steam/userdata" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from nonsteamapps import vdf
for config in sorted(Path(sys.argv[2]).glob("*/config")):
    entries = vdf.loads_binary((config / "shortcuts.vdf").read_bytes()).get("shortcuts").values()
    if "LocalSend" not in [entry.get("AppName") for entry in entries]:
        sys.exit(f"no LocalSend shortcut in {config}")
PY
}

echo "==> install.sh localsend, with $(flatpak --version)"
run "$ROOT/install.sh" --yes --no-auto-update localsend
check "LocalSend was installed from Flathub" installed
check "both Steam accounts got its shortcut" shortcuts
check "LocalSend starts in its sandbox" run flatpak run --command=true "$APP"
echo "==> nonsteamapps remove localsend"
run "$HOME_DIR/.local/share/nonsteamapps/bin/nonsteamapps" remove localsend --yes
check "LocalSend was uninstalled" uninstalled
check "its runtime went with it" no_runtimes
exit "$failed"
