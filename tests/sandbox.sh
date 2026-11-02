#!/usr/bin/env bash
# End-to-end check of the shipped scripts in a throwaway home: install.sh with a
# fake flatpak, a running fake firewall, a stand-in Helium release and two Steam
# accounts, launches through the links Steam runs, and uninstall.sh. Needs bash,
# python3 and xz.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
WORK=$(mktemp -d)
HOME_DIR="$WORK/home"
STEAM="$HOME_DIR/.local/share/Steam"
PROGRAM="$HOME_DIR/.local/share/nonsteamapps"
failed=0
trap 'rm -rf "$WORK"' EXIT

run() {
    env -i HOME="$HOME_DIR" PATH="$WORK/bin:$PATH" USER=deck LANG=C.UTF-8 NO_COLOR=1 NONSTEAMAPPS_ALLOW_ROOT=1 \
        FAKE_FLATPAK_STATE="$WORK/flatpak.json" FAKE_FLATPAK_LOG="$WORK/flatpak.log" FAKE_HELIUM_LOG="$WORK/helium.log" \
        FAKE_FIREWALL_STATE="$WORK/firewall.json" FAKE_HELIUM_ENV_LOG="$WORK/helium-env.log" FAKE_DOLPHIN_LOG="$WORK/dolphin.log" "$@"
}

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

shortcut_names() {
    python3 -I - "$ROOT/src/lib" "$STEAM/userdata/$1/config/shortcuts.vdf" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nonsteamapps import vdf
path = Path(sys.argv[2])
entries = vdf.loads_binary(path.read_bytes()).get("shortcuts").values() if path.exists() else []
print(" ".join(sorted(entry.get("AppName") for entry in entries)))
EOF
}

collection_size() {
    python3 -I - "$ROOT/src/lib" "$STEAM" "$1" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nonsteamapps import collection
print(len(collection.members(collection.storage_file(Path(sys.argv[2]), int(sys.argv[3])))))
EOF
}

mkdir -p "$WORK/bin" "$STEAM/userdata/111/config" "$STEAM/userdata/222/config" "$STEAM/config"
for account in 111 222; do
    mkdir -p "$STEAM/userdata/$account/config/cloudstorage"
    echo '[[1,"798"]]' >"$STEAM/userdata/$account/config/cloudstorage/cloud-storage-namespaces.json"
    echo '[]' >"$STEAM/userdata/$account/config/cloudstorage/cloud-storage-namespace-1.json"
done
ln -s "$ROOT/tests/fakes/flatpak" "$WORK/bin/flatpak"
ln -s "$ROOT/tests/fakes/firewall-cmd" "$WORK/bin/firewall-cmd"
ln -s "$ROOT/tests/fakes/sudo" "$WORK/bin/sudo"
ln -s "$ROOT/tests/fakes/dolphin" "$WORK/bin/dolphin"
echo '{"running": true, "default": "public", "active": ["public"], "runtime": {}, "permanent": {}}' >"$WORK/firewall.json"
printf '%s\n' '"users"' '{' \
    '  "76561197960265839" { "AccountName" "alpha" "PersonaName" "Alpha" "MostRecent" "1" }' \
    '  "76561197960265950" { "AccountName" "beta" "PersonaName" "Beta" "MostRecent" "0" }' \
    '}' >"$STEAM/config/loginusers.vdf"

HELIUM_ARCHIVE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_helium_archive(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$WORK")
TEMPLATES=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.add_controller_templates(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$STEAM")
YOUTUBE_ID=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; from nonsteamapps import steam; print(steam.shortcut_appid(steam.quote(sys.argv[2]), "YouTube"))' "$ROOT/src/lib" "$PROGRAM/apps/youtube")
printf '%s\n' '"InstallConfigStore"' '{' '"Software"' '{' '"Valve"' '{' '"Steam"' '{' '"CompatToolMapping"' '{' \
    "\"$YOUTUBE_ID\" { \"name\" \"proton_experimental\" \"config\" \"\" \"priority\" \"250\" }" \
    '"1245620" { "name" "proton_9" "config" "" "priority" "250" }' '}' '}' '}' '}' '}' >"$STEAM/config/config.vdf"

echo "==> install.sh"
run "$ROOT/install.sh" --yes --no-auto-update --helium-archive "$HELIUM_ARCHIVE" --skip-verify >"$WORK/install.log" 2>&1 || {
    cat "$WORK/install.log"
    exit 1
}
everything="Disney+ Element Files HBO Max Helium Jellyfin LocalSend Netflix Prime Video Prism Launcher Proton Calendar ProtonDB Signal YouTube"
check "every app has a link to the launcher" test "$(find "$PROGRAM/apps" -type l | wc -l)" -eq 14
check "both accounts list every app" test "$(shortcut_names 111)|$(shortcut_names 222)" == "$everything|$everything"
check "the artwork was copied" test "$(find "$STEAM/userdata/222/config/grid" -name '*_hero.jpg' | wc -l)" -eq 14
check "Helium was unpacked and made current" test -x "$PROGRAM/helium/current/helium-wrapper"
check "both accounts have every app in the NonSteamApps collection" test "$(collection_size 111) $(collection_size 222)" == "14 14"
check "YouTube no longer forces Proton, and another game still does" test "$(grep -c "\"$YOUTUBE_ID\"" "$STEAM/config/config.vdf") $(grep -c '"proton_9"' "$STEAM/config/config.vdf")" == "0 1"
check "Files got its own controller layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_files.vdf' | wc -l)" -eq 2
check "Prism Launcher got the Minecraft layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_minecraft.vdf' | wc -l)" -eq 2
check "LocalSend's port was opened in the firewall" grep -qF '"permanent": {"public": ["53317/tcp", "53317/udp"]}' "$WORK/firewall.json"

echo "==> launch through the link Steam runs"
: >"$WORK/flatpak.log"
run "$PROGRAM/apps/jellyfin" --steam-account 222 --verbose >/dev/null
run "$PROGRAM/apps/youtube" --steam-account 222
check "Jellyfin's profile for the account was created first" grep -qF '["run", "org.jellyfin.JellyfinDesktop", "--create-profile", "steam-222"]' "$WORK/flatpak.log"
check "Jellyfin started with that profile" grep -qF '"--tv", "--fullscreen", "--profile=steam-222"]' "$WORK/flatpak.log"
check "VacuumTube started with the account's folder" grep -qF "\"--portable=$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222\"]" "$WORK/flatpak.log"
check "VacuumTube's new folder hides the Shorts and Podcasts tabs" grep -qF '"podcasts"' "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json"
check "VacuumTube's folder records the settings change" grep -qF '"2.11.0"' "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/nonsteamapps.json"
check "the launch was logged" grep -q 'starting YouTube (VacuumTube) for Steam account 222' "$HOME_DIR/.local/state/nonsteamapps/youtube.log"
run "$PROGRAM/apps/element" --steam-account 222
check "Element's new profile quits when its window closes" grep -qF '"minimizeToTray": false' "$HOME_DIR/.var/app/im.riot.Riot/config/Element-steam-222/electron-config.json"
run "$PROGRAM/apps/signal" --steam-account 222
check "Signal started its own script with the account's folder" grep -qF "[\"run\", \"--command=env\", \"org.signal.Signal\", \"XDG_CONFIG_HOME=$HOME_DIR/.var/app/org.signal.Signal/config/Signal-steam-222\", \"SIGNAL_PASSWORD_STORE=basic\", \"signal-desktop\"]" "$WORK/flatpak.log"
run env LD_PRELOAD="$STEAM/ubuntu12_64/gameoverlayrenderer.so" LD_LIBRARY_PATH="$STEAM/ubuntu12_32/steam-runtime/lib" \
    SYSTEM_LD_LIBRARY_PATH= "$PROGRAM/apps/primevideo" --steam-account 222 2>/dev/null
check "Helium started without Steam's overlay library" grep -qxF "<unset>" "$WORK/helium-env.log"
check "Prime Video started full screen in its own Helium profile" grep -qF "[\"--user-data-dir=$PROGRAM/profiles/primevideo/222\"" "$WORK/helium.log"
check "Prime Video opened its site in a kiosk" grep -qE '"--kiosk".*"https://www.primevideo.com/"\]$' "$WORK/helium.log"
check "the profile shares Helium's Widevine folder" test "$(readlink -f "$PROGRAM/profiles/primevideo/222/WidevineCdm")" == "$(readlink -f "$PROGRAM/helium/WidevineCdm")"
PRISM="$HOME_DIR/.var/app/org.prismlauncher.PrismLauncher/data"
run "$PROGRAM/apps/prism" --steam-account 222
check "Prism Launcher started with the account's folder" grep -qF "[\"run\", \"org.prismlauncher.PrismLauncher\", \"--dir=$PRISM/PrismLauncher-steam-222\"]" "$WORK/flatpak.log"
check "Prism Launcher starts dark and quits after the game" grep -qxF "QuitAfterGameStop=true" "$PRISM/PrismLauncher-steam-222/prismlauncher.cfg"
check "Prism Launcher shares Minecraft's downloads" test "$(readlink "$PRISM/PrismLauncher-steam-222/assets")" == "../PrismLauncher/assets"
run "$PROGRAM/apps/files" --steam-account 222
check "Files started the system's Dolphin in a new window" grep -qxF "args: --new-window" "$WORK/dolphin.log"
check "Dolphin read its TV profile, over the desktop's settings" grep -qxF "XDG_CONFIG_HOME=$PROGRAM/profiles/files/shared/config" "$WORK/dolphin.log"
check "the TV profile starts without the menu bar" grep -qxF "MenuBar=Disabled" "$PROGRAM/profiles/files/shared/config/dolphinrc"

echo "==> uninstall.sh"
run "$ROOT/uninstall.sh" --yes >"$WORK/uninstall.log" 2>&1 || {
    cat "$WORK/uninstall.log"
    exit 1
}
check "only the app profiles remain" test "$(ls "$PROGRAM")" == "profiles"
check "the shortcuts are gone" test -z "$(shortcut_names 111)$(shortcut_names 222)"
check "the apps it installed were uninstalled" grep -q '"apps": {}' "$WORK/flatpak.json"
check "the collection was removed" test "$(collection_size 111) $(collection_size 222)" == "0 0"
check "LocalSend's port was closed again" grep -qF '"permanent": {"public": []}' "$WORK/firewall.json"
check "NonSteamApps' controller layouts were removed" test -z "$(find "$TEMPLATES" -name '*_nonsteamapps_*')"

if ((failed)); then
    echo "==> Sandbox test FAILED"
    exit 1
fi
echo "==> Sandbox test passed"
