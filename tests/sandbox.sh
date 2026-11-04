#!/usr/bin/env bash
# End-to-end check of the shipped scripts in a throwaway home: install.sh with a
# fake flatpak, a running fake firewall, stand-in Helium and KytyPS5 releases and two Steam
# accounts, launches through the links Steam runs, an update that keeps what the
# user changed, an install that puts it back, and uninstall.sh. Needs bash,
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
        FAKE_FIREWALL_STATE="$WORK/firewall.json" FAKE_HELIUM_ENV_LOG="$WORK/helium-env.log" FAKE_DOLPHIN_LOG="$WORK/dolphin.log" \
        FAKE_KYTY_LOG="$WORK/kyty.log" "$@"
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

rename_shortcut() {
    python3 -I - "$ROOT/src/lib" "$STEAM/userdata/$1/config/shortcuts.vdf" "$2" "$3" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from nonsteamapps import steam
shortcuts = steam.ShortcutsFile.load(sys.argv[2])
for entry in shortcuts.entries():
    if entry.get("AppName") == sys.argv[3]:
        entry.set("AppName", sys.argv[4])
shortcuts.save(backup=False)
EOF
}

shortcut_named() {
    python3 -I - "$ROOT/src/lib" "$STEAM/userdata/$1/config/shortcuts.vdf" "$2" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from nonsteamapps import steam
sys.exit(0 if sys.argv[3] in [entry.get("AppName") for entry in steam.ShortcutsFile.load(sys.argv[2]).entries()] else 1)
EOF
}

json_value() {
    python3 -I -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))[sys.argv[2]]))' "$1" "$2"
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

mkdir -p "$WORK/bin" "$WORK/sdcard" "$STEAM/userdata/111/config" "$STEAM/userdata/222/config" "$STEAM/config" "$STEAM/steamapps"
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
printf '%s\n' '"libraryfolders"' '{' "\"0\" { \"path\" \"$STEAM\" }" "\"1\" { \"path\" \"$WORK/sdcard\" }" '}' >"$STEAM/steamapps/libraryfolders.vdf"

HELIUM_ARCHIVE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_helium_archive(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$WORK")
KYTY_ARCHIVE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_kyty_archive(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$WORK")
TEMPLATES=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.add_controller_templates(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$STEAM")
YOUTUBE_ID=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; from nonsteamapps import steam; print(steam.shortcut_appid(steam.quote(sys.argv[2]), "YouTube"))' "$ROOT/src/lib" "$PROGRAM/apps/youtube")
printf '%s\n' '"InstallConfigStore"' '{' '"Software"' '{' '"Valve"' '{' '"Steam"' '{' '"CompatToolMapping"' '{' \
    "\"$YOUTUBE_ID\" { \"name\" \"proton_experimental\" \"config\" \"\" \"priority\" \"250\" }" \
    '"1245620" { "name" "proton_9" "config" "" "priority" "250" }' '}' '}' '}' '}' '}' >"$STEAM/config/config.vdf"

echo "==> install.sh"
run "$ROOT/install.sh" --yes --no-auto-update --helium-archive "$HELIUM_ARCHIVE" --kytyps5-archive "$KYTY_ARCHIVE" --skip-verify >"$WORK/install.log" 2>&1 || {
    cat "$WORK/install.log"
    exit 1
}
everything="Bitwarden Disney+ Eden Element Files HBO Max Helium Jellyfin KytyPS5 LocalSend Netflix Prime Video Prism Launcher Proton Calendar ProtonDB ProtonUp-Qt Protontricks Signal YouTube"
check "every app has a link to the launcher" test "$(find "$PROGRAM/apps" -type l | wc -l)" -eq 19
check "both accounts list every app" test "$(shortcut_names 111)|$(shortcut_names 222)" == "$everything|$everything"
check "the artwork was copied" test "$(find "$STEAM/userdata/222/config/grid" -name '*_hero.jpg' | wc -l)" -eq 19
check "Helium was unpacked and made current" test -x "$PROGRAM/helium/current/helium-wrapper"
check "KytyPS5 was unpacked and made current" test -x "$PROGRAM/kytyps5/current/kyty_launcher"
check "both accounts have every app in the NonSteamApps collection" test "$(collection_size 111) $(collection_size 222)" == "19 19"
check "YouTube no longer forces Proton, and another game still does" test "$(grep -c "\"$YOUTUBE_ID\"" "$STEAM/config/config.vdf") $(grep -c '"proton_9"' "$STEAM/config/config.vdf")" == "0 1"
check "Files got its own controller layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_files.vdf' | wc -l)" -eq 2
check "Prism Launcher got the Minecraft layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_minecraft.vdf' | wc -l)" -eq 2
check "YouTube got its own layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_youtube.vdf' | wc -l)" -eq 2
check "ProtonUp-Qt and Protontricks got the Tools layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_tools.vdf' | wc -l)" -eq 2
check "The emulators got their own layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_emulator.vdf' | wc -l)" -eq 2
check "Holding View shifts the emulators' layout into launcher controls" grep -q "mode_shift right_joystick" "$TEMPLATES/controller_xboxone_nonsteamapps_emulator.vdf"
check "LocalSend's port was opened in the firewall" grep -qF '"permanent": {"public": ["53317/tcp", "53317/udp"]}' "$WORK/firewall.json"

echo "==> launch through the link Steam runs"
: >"$WORK/flatpak.log"
run "$PROGRAM/apps/jellyfin" --steam-account 222 --verbose >/dev/null
run "$PROGRAM/apps/youtube" --steam-account 222
check "Jellyfin's profile for the account was created first" grep -qF '["run", "org.jellyfin.JellyfinDesktop", "--create-profile", "steam-222"]' "$WORK/flatpak.log"
check "Jellyfin started with that profile" grep -qF '"--tv", "--fullscreen", "--profile=steam-222"]' "$WORK/flatpak.log"
check "VacuumTube started with the account's folder" grep -qF "\"--portable=$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222\"]" "$WORK/flatpak.log"
check "VacuumTube's new folder hides the Shorts and Podcasts tabs" grep -qF '"podcasts"' "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json"
check "VacuumTube's folder records the settings changes" test "$(json_value "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/nonsteamapps.json" changes)" == '["2.11.0", "2.21.0", "2.22.0"]'
check "VacuumTube got the SteamOS theme, with its userstyles on" test -f "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/userstyles/nonsteamapps-steamos.css" -a "$(json_value "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json" userstyles)" == true
check "VacuumTube skips self-promotion and end cards" test "$(json_value "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json" sponsorblock_skip_selfpromo) $(json_value "$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json" sponsorblock_skip_outro)" == "true true"
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
EDEN="$HOME_DIR/.var/app/dev.eden_emu.eden/data"
run "$PROGRAM/apps/eden" --steam-account 222
check "Eden started full screen, portable and on X11, in the account's folder, with its games folder" grep -qF "[\"run\", \"--cwd=$EDEN/eden-steam-222\", \"--filesystem=$HOME_DIR/Games/Switch:ro\", \"--socket=x11\", \"--nosocket=fallback-x11\", \"--env=QT_QPA_PLATFORM=xcb\", \"dev.eden_emu.eden\", \"-f\"]" "$WORK/flatpak.log"
check "Eden lists ~/Games/Switch among its game folders" grep -qxF "Paths\\gamedirs\\4\\path=$HOME_DIR/Games/Switch" "$EDEN/eden-steam-222/user/config/qt-config.ini"
check "Eden starts dark, with Steam's controller mapped" grep -qxF 'player_0_button_a="engine:sdl,port:0,guid:03000000de280000ff11000001000000,button:1"' "$EDEN/eden-steam-222/user/config/qt-config.ini"
check "Eden shares the keys, firmware and installed games" test "$(readlink "$EDEN/eden-steam-222/user/keys")" == "../../eden/keys" -a -d "$EDEN/eden/nand/user/Contents/registered"
run "$PROGRAM/apps/files" --steam-account 222
check "Files started the system's Dolphin in a new window" grep -qxF "args: --new-window" "$WORK/dolphin.log"
check "Dolphin read its TV profile, over the desktop's settings" grep -qxF "XDG_CONFIG_HOME=$PROGRAM/profiles/files/shared/config" "$WORK/dolphin.log"
check "the TV profile starts without the menu bar" grep -qxF "MenuBar=Disabled" "$PROGRAM/profiles/files/shared/config/dolphinrc"
run "$PROGRAM/apps/bitwarden" --steam-account 222
BITWARDEN="$HOME_DIR/.var/app/com.bitwarden.desktop/config/Bitwarden-steam-222"
check "Bitwarden started with the account's folder and its tokens on disk" grep -qF "[\"run\", \"--env=BITWARDEN_APPDATA_DIR=$BITWARDEN\", \"--env=ACCESS_TOKEN_LOCATION=DISK\", \"com.bitwarden.desktop\"]" "$WORK/flatpak.log"
check "Bitwarden quits when its window closes" test "$(json_value "$BITWARDEN/data.json" global_desktopSettings_runInBackground)" == "false"
run "$PROGRAM/apps/localsend" --steam-account 222
check "LocalSend starts dark, in its OLED colours" test "$(json_value "$HOME_DIR/.var/app/org.localsend.localsend_app/data/org.localsend.localsend_app/shared_preferences.json" flutter.ls_color)" == '"oled"'
run "$PROGRAM/apps/protonup" --steam-account 222
check "ProtonUp-Qt started without its own gamepad input and with every Steam library" grep -qF "[\"run\", \"--env=PUPGUI2_DISABLE_GAMEPAD=1\", \"--filesystem=$STEAM\", \"--filesystem=$WORK/sdcard\", \"net.davidotek.pupgui2\"]" "$WORK/flatpak.log"
check "ProtonUp-Qt starts in the Steam Deck theme" grep -qxF "theme=steam" "$HOME_DIR/.var/app/net.davidotek.pupgui2/config/pupgui/config.ini"
run "$PROGRAM/apps/protontricks" --steam-account 222
check "Protontricks opened its game picker with the SD card's library" grep -qF "\"--filesystem=$WORK/sdcard\", \"com.github.Matoking.protontricks\", \"--no-term\", \"--gui\"]" "$WORK/flatpak.log"

KYTY_HOME="$PROGRAM/profiles/kytyps5/222"
run env FAKE_KYTY_PLAY=/games/PPSA00000 timeout 30 "$PROGRAM/apps/kytyps5" --steam-account 222
check "KytyPS5's launcher started in the account's folder" grep -qF "\"cwd\": \"$KYTY_HOME\", \"folder\": \"$KYTY_HOME\"" "$WORK/kyty.log"
check "KytyPS5's own updater is off" grep -qxF "check_updates_on_startup=false" "$KYTY_HOME/Kyty.ini"
check "KytyPS5 started with a games folder, so it asks for none" grep -qxF "game_dirs=$HOME_DIR/Games/PS5" "$KYTY_HOME/Kyty.ini"
check "KytyPS5's launcher starts dark, with its games in a grid" test "$(grep -cxE 'theme=1|grid_view=true' "$KYTY_HOME/Kyty.ini")" -eq 2
check "the game ran through NonSteamApps' stand-in terminal, which waited for no key" grep -qF '{"emulator": ["--game", "/games/PPSA00000"]' "$WORK/kyty.log"
check "the game's save stayed in the account's folder" test -d "$KYTY_HOME/_SaveData/PPSA00000"
check "the game's downloaded content went to the folder every account shares" test -d "$PROGRAM/profiles/kytyps5/games/_DownloadData/PPSA00000" -a -L "$KYTY_HOME/_DownloadData"

VACUUMTUBE="$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json"
echo "==> update keeps what the user changed"
rename_shortcut 222 YouTube "My Tube"
python3 -I -c 'import json, sys; data = json.load(open(sys.argv[1])); data["disabled_tabs"] = []; json.dump(data, open(sys.argv[1], "w"))' "$VACUUMTUBE"
run env HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 "$PROGRAM/bin/nonsteamapps" update --yes >"$WORK/update.log" 2>&1 || {
    cat "$WORK/update.log"
    exit 1
}
check "update copied NonSteamApps from the clone it was installed from, then handed over" grep -qE "NonSteamApps [0-9.]+ is up to date" "$WORK/update.log"
check "update added no app" test "$(find "$PROGRAM/apps" -type l | wc -l)" -eq 19
check "update kept the renamed shortcut" shortcut_named 222 "My Tube"
check "update kept VacuumTube's tabs as the user set them" test "$(json_value "$VACUUMTUBE" disabled_tabs)" == "[]"

echo "==> installing again puts NonSteamApps' set-up back"
run "$ROOT/install.sh" --yes --no-auto-update --helium-archive "$HELIUM_ARCHIVE" --kytyps5-archive "$KYTY_ARCHIVE" --skip-verify >"$WORK/reinstall.log" 2>&1 || {
    cat "$WORK/reinstall.log"
    exit 1
}
check "the shortcut is called YouTube again" test "$(shortcut_names 222)" == "$everything"
check "VacuumTube hides the Shorts and Podcasts tabs again" test "$(json_value "$VACUUMTUBE" disabled_tabs)" == '["shorts", "podcasts"]'

echo "==> uninstall.sh"
run "$ROOT/uninstall.sh" --yes >"$WORK/uninstall.log" 2>&1 || {
    cat "$WORK/uninstall.log"
    exit 1
}
check "only the app profiles remain" test "$(ls "$PROGRAM")" == "profiles"
check "KytyPS5's save stayed, without its programs" test -d "$KYTY_HOME/_SaveData/PPSA00000" -a ! -e "$KYTY_HOME/kyty_launcher"
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
