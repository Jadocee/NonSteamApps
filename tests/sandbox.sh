#!/usr/bin/env bash
# End-to-end check of the shipped scripts in a throwaway home: install.sh with a
# fake flatpak, which also stands in for Eden-NX2's build, a running fake firewall, a
# stand-in systemctl that reaches no real service,
# stand-in Helium, KytyPS5 and Lichii releases and two Steam accounts, launches through the
# links Steam runs, an update that keeps what the
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
        FAKE_KYTY_LOG="$WORK/kyty.log" FAKE_LICHII_LOG="$WORK/lichii.log" FAKE_STEAM_LOG="$WORK/steam.log" FAKE_SYSTEMCTL_LOG="$WORK/systemctl.log" \
        FAKE_FLATPAK_ICONS=1 FAKE_DEVTOOLS_LOG="$WORK/devtools.log" HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 "$@"
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

grid_file() {
    python3 -I - "$ROOT/src/lib" "$STEAM/userdata/$1/config" "$2" "$3" <<'EOF'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from nonsteamapps import steam
config, name, suffix = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
entry = next(entry for entry in steam.ShortcutsFile.load(config / "shortcuts.vdf").entries() if entry.get("AppName") == name)
print(config / "grid" / f"{steam.to_unsigned32(entry.get('appid'))}{suffix}")
EOF
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

status_back() {
    local _
    for _ in $(seq 100); do
        if grep -qF '"steam://friends/status/invisible"' "$WORK/steam.log" 2>/dev/null &&
            [ "$(tail -n 1 "$WORK/steam.log")" = '["-ifrunning", "steam://friends/status/online"]' ]; then
            return 0
        fi
        sleep 0.1
    done
    return 1
}

mkdir -p "$WORK/bin" "$WORK/sdcard" "$STEAM/userdata/111/config" "$STEAM/userdata/222/config" "$STEAM/config" "$STEAM/steamapps"
for account in 111 222; do
    mkdir -p "$STEAM/userdata/$account/config/cloudstorage"
    echo '[[1,"798"]]' >"$STEAM/userdata/$account/config/cloudstorage/cloud-storage-namespaces.json"
    echo '[]' >"$STEAM/userdata/$account/config/cloudstorage/cloud-storage-namespace-1.json"
done
ln -s "$ROOT/tests/fakes/flatpak" "$WORK/bin/flatpak"
ln -s "$ROOT/tests/fakes/steam" "$WORK/bin/steam"
ln -s "$ROOT/tests/fakes/firewall-cmd" "$WORK/bin/firewall-cmd"
ln -s "$ROOT/tests/fakes/sudo" "$WORK/bin/sudo"
ln -s "$ROOT/tests/fakes/dolphin" "$WORK/bin/dolphin"
ln -s "$ROOT/tests/fakes/systemctl" "$WORK/bin/systemctl"
echo '{"running": true, "default": "public", "active": ["public"], "runtime": {}, "permanent": {}}' >"$WORK/firewall.json"
printf '%s\n' '"users"' '{' \
    '  "76561197960265839" { "AccountName" "alpha" "PersonaName" "Alpha" "MostRecent" "1" }' \
    '  "76561197960265950" { "AccountName" "beta" "PersonaName" "Beta" "MostRecent" "0" }' \
    '}' >"$STEAM/config/loginusers.vdf"
printf '%s\n' '"libraryfolders"' '{' "\"0\" { \"path\" \"$STEAM\" }" "\"1\" { \"path\" \"$WORK/sdcard\" }" '}' >"$STEAM/steamapps/libraryfolders.vdf"

HELIUM_ARCHIVE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_helium_archive(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$WORK")
KYTY_ARCHIVE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_kyty_archive(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$WORK")
LICHII_APPIMAGE=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.make_lichii_appimage(pathlib.Path(sys.argv[2]) / "lichii"))' "$ROOT/tests" "$WORK")
NX2_COMMIT=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes; print(_fakes.NX2_COMMIT)' "$ROOT/tests")
NX2_ID=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; from nonsteamapps import nx2; print(nx2.APP_ID)' "$ROOT/src/lib")
TEMPLATES=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; import _fakes, pathlib; print(_fakes.add_controller_templates(pathlib.Path(sys.argv[2])))' "$ROOT/tests" "$STEAM")
YOUTUBE_ID=$(python3 -c 'import sys; sys.path[:0] = [sys.argv[1]]; from nonsteamapps import steam; print(steam.shortcut_appid(steam.quote(sys.argv[2]), "YouTube"))' "$ROOT/src/lib" "$PROGRAM/apps/youtube")
printf '%s\n' '"InstallConfigStore"' '{' '"Software"' '{' '"Valve"' '{' '"Steam"' '{' '"CompatToolMapping"' '{' \
    "\"$YOUTUBE_ID\" { \"name\" \"proton_experimental\" \"config\" \"\" \"priority\" \"250\" }" \
    '"1245620" { "name" "proton_9" "config" "" "priority" "250" }' '}' '}' '}' '}' '}' >"$STEAM/config/config.vdf"

LAYOUT="$HOME_DIR/.config/plasma-org.kde.plasma.desktop-appletsrc"
mkdir -p "$HOME_DIR/.config"
printf '%s\n' '[Containments][1]' 'plugin=org.kde.panel' '' '[Containments][1][Applets][2]' 'plugin=org.kde.plasma.icontasks' >"$LAYOUT"
PLASMA_HERE=0
if pgrep -u "$(id -u)" -x plasmashell >/dev/null 2>&1; then
    PLASMA_HERE=1
fi

echo "==> install.sh"
run "$ROOT/install.sh" --yes --no-auto-update --helium-archive "$HELIUM_ARCHIVE" --kytyps5-archive "$KYTY_ARCHIVE" --lichii-archive "$LICHII_APPIMAGE" \
    --eden-nx2-commit "$NX2_COMMIT" --skip-verify >"$WORK/install.log" 2>&1 || {
    cat "$WORK/install.log"
    exit 1
}
everything="Bitwarden Disney+ Eden Eden-NX2 Element Files HBO Max Helium Jellyfin KytyPS5 Lichii LocalSend Netflix Prime Video Prism Launcher Proton Calendar Proton Mail ProtonDB ProtonUp-Qt Protontricks Signal Winetricks YouTube"
check "every app has a link to the launcher" test "$(find "$PROGRAM/apps" -type l | wc -l)" -eq 23
check "both accounts list every app" test "$(shortcut_names 111)|$(shortcut_names 222)" == "$everything|$everything"
check "the artwork was copied" test "$(find "$STEAM/userdata/222/config/grid" -name '*_hero.jpg' | wc -l)" -eq 23
check "Helium was unpacked and made current" test -x "$PROGRAM/helium/current/helium-wrapper"
check "KytyPS5 was unpacked and made current" test -x "$PROGRAM/kytyps5/current/kyty_launcher"
check "Lichii's AppImage was installed and made current" test -x "$PROGRAM/lichii/current/lichii.AppImage"
check "YouTube's capsule was drawn around VacuumTube's own icon" test "$(head -c 17 "$(grid_file 222 YouTube p.png)")" == "fake png capsule "
check "Helium's hero was drawn around the icon in Helium's release" test "$(head -c 15 "$(grid_file 222 Helium _hero.jpg)")" == "fake jpeg hero "
check "a site that names no icon keeps NonSteamApps' artwork" cmp -s "$(grid_file 222 Netflix p.png)" "$PROGRAM/artwork/netflix/capsule.png"
check "Eden-NX2 was built from its source in the SDK" grep -qF "\"git\", \"-C\", \"/run/nonsteamapps/source\", \"fetch\", \"-q\", \"--depth\", \"1\", \"https://git.eden-emu.dev/Takoroka/eden-nx2.git\", \"$NX2_COMMIT\"]" "$WORK/flatpak.log"
check "Eden-NX2 was installed from NonSteamApps' own repository" grep -qF "[\"install\", \"--user\", \"--noninteractive\", \"-y\", \"nonsteamapps\", \"$NX2_ID\"]" "$WORK/flatpak.log"
check "Winetricks came with Flathub's Wine, from its stable branch" grep -qF '["install", "--user", "--noninteractive", "-y", "flathub", "org.winehq.Wine//stable"]' "$WORK/flatpak.log"
check "Eden-NX2's build files and staging folder were cleared, its caches kept" test ! -e "$PROGRAM/eden-nx2/build" -a ! -e "$PROGRAM/eden-nx2/app" -a -d "$PROGRAM/eden-nx2/cpm"
check "both accounts have every app in the NonSteamApps collection" test "$(collection_size 111) $(collection_size 222)" == "23 23"
check "YouTube no longer forces Proton, and another game still does" test "$(grep -c "\"$YOUTUBE_ID\"" "$STEAM/config/config.vdf") $(grep -c '"proton_9"' "$STEAM/config/config.vdf")" == "0 1"
check "Files got its own controller layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_files.vdf' | wc -l)" -eq 2
check "Prism Launcher got the Minecraft layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_minecraft.vdf' | wc -l)" -eq 2
check "YouTube got its own layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_youtube.vdf' | wc -l)" -eq 2
check "Jellyfin got its own layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_jellyfin.vdf' | wc -l)" -eq 2
check "Helium joined the applications menu, starting Helium itself" grep -qxF "Exec=\"$PROGRAM/helium/current/helium-wrapper\" --class=nonsteamapps-helium %U" "$HOME_DIR/.local/share/applications/nonsteamapps-helium.desktop"
check "Helium's entry has Helium's own icon" grep -qxF "Icon=$PROGRAM/helium/current/product_logo_256.png" "$HOME_DIR/.local/share/applications/nonsteamapps-helium.desktop"
if [ "$PLASMA_HERE" = 0 ]; then
    check "Helium joined the taskbar, after Plasma's own launchers" grep -qxF "launchers=applications:systemsettings.desktop,applications:org.kde.discover.desktop,preferred://filemanager,preferred://browser,applications:nonsteamapps-helium.desktop" "$LAYOUT"
fi
check "ProtonUp-Qt, Protontricks and Winetricks got the Tools layout for each controller" test "$(find "$TEMPLATES" -name '*_nonsteamapps_tools.vdf' | wc -l)" -eq 2
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
check "Element's new profile quits when its window closes, without asking, and hides its menu bar" \
    test "$(grep -cE '"(minimizeToTray|warnBeforeExit)": false|"autoHideMenuBar": true' "$HOME_DIR/.var/app/im.riot.Riot/config/Element-steam-222/electron-config.json")" -eq 3
check "Element moves with the arrow keys by what is on screen" grep -qF '"--storage-mode=allow-plaintext", "--enable-spatial-navigation", "--profile=steam-222"' "$WORK/flatpak.log"
run "$PROGRAM/apps/signal" --steam-account 222
check "Signal started its own script with the account's folder and spatial navigation" grep -qF "[\"run\", \"--command=env\", \"org.signal.Signal\", \"XDG_CONFIG_HOME=$HOME_DIR/.var/app/org.signal.Signal/config/Signal-steam-222\", \"SIGNAL_PASSWORD_STORE=basic\", \"signal-desktop\", \"--enable-spatial-navigation\"]" "$WORK/flatpak.log"
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
check "Eden runs on Vulkan, on the first graphics chip" grep -qxF "backend=1" "$EDEN/eden-steam-222/user/config/qt-config.ini"
printf 'header_key = 00\n' > "$EDEN/eden/keys/prod.keys"
NX2="$HOME_DIR/.var/app/$NX2_ID/data"
run "$PROGRAM/apps/edennx2" --steam-account 222
check "Eden-NX2 started as Eden does, from its own Flatpak, with its own games folder" grep -qF "[\"run\", \"--cwd=$NX2/eden-steam-222\", \"--filesystem=$HOME_DIR/Games/Switch2:ro\", \"--socket=x11\", \"--nosocket=fallback-x11\", \"--env=QT_QPA_PLATFORM=xcb\", \"$NX2_ID\", \"-f\"]" "$WORK/flatpak.log"
check "Eden-NX2 lists ~/Games/Switch2 among its game folders" grep -qxF "Paths\\gamedirs\\4\\path=$HOME_DIR/Games/Switch2" "$NX2/eden-steam-222/user/config/qt-config.ini"
check "Eden-NX2 took the keys installed in Eden, so it does not ask for them" cmp -s "$EDEN/eden/keys/prod.keys" "$NX2/eden-steam-222/user/keys/prod.keys"
check "Eden-NX2 runs on Vulkan" grep -qxF "backend=1" "$NX2/eden-steam-222/user/config/qt-config.ini"
check "Eden-NX2 keeps ASTC textures as BC3, decoded on the graphics chip" grep -qxF "astc_recompression=2" "$NX2/eden-steam-222/user/config/qt-config.ini"
run "$PROGRAM/apps/files" --steam-account 222
check "Files started the system's Dolphin in a new window" grep -qxF "args: --new-window" "$WORK/dolphin.log"
check "Dolphin read its TV profile, over the desktop's settings" grep -qxF "XDG_CONFIG_HOME=$PROGRAM/profiles/files/shared/config" "$WORK/dolphin.log"
check "the TV profile starts without the menu bar" grep -qxF "MenuBar=Disabled" "$PROGRAM/profiles/files/shared/config/dolphinrc"
run "$PROGRAM/apps/bitwarden" --steam-account 222
BITWARDEN="$HOME_DIR/.var/app/com.bitwarden.desktop/config/Bitwarden-steam-222"
check "Bitwarden started with the account's folder, its tokens on disk and spatial navigation" grep -qF "[\"run\", \"--env=BITWARDEN_APPDATA_DIR=$BITWARDEN\", \"--env=ACCESS_TOKEN_LOCATION=DISK\", \"com.bitwarden.desktop\", \"--enable-spatial-navigation\"]" "$WORK/flatpak.log"
check "Bitwarden quits when its window closes" test "$(json_value "$BITWARDEN/data.json" global_desktopSettings_runInBackground)" == "false"
run "$PROGRAM/apps/localsend" --steam-account 222
check "LocalSend starts dark, in its OLED colours" test "$(json_value "$HOME_DIR/.var/app/org.localsend.localsend_app/data/org.localsend.localsend_app/shared_preferences.json" flutter.ls_color)" == '"oled"'
run "$PROGRAM/apps/protonup" --steam-account 222
check "ProtonUp-Qt started without its own gamepad input and with every Steam library" grep -qF "[\"run\", \"--env=PUPGUI2_DISABLE_GAMEPAD=1\", \"--filesystem=$STEAM\", \"--filesystem=$WORK/sdcard\", \"net.davidotek.pupgui2\"]" "$WORK/flatpak.log"
check "ProtonUp-Qt starts in the Steam Deck theme" grep -qxF "theme=steam" "$HOME_DIR/.var/app/net.davidotek.pupgui2/config/pupgui/config.ini"
run "$PROGRAM/apps/protontricks" --steam-account 222
check "Protontricks opened its game picker with the SD card's library" grep -qF "\"--filesystem=$WORK/sdcard\", \"com.github.Matoking.protontricks\", \"--no-term\", \"--gui\"]" "$WORK/flatpak.log"
run "$PROGRAM/apps/winetricks" --steam-account 222
check "Winetricks opened its menu in Flathub's Wine" grep -qF '["run", "--command=winetricks", "org.winehq.Wine"]' "$WORK/flatpak.log"

KYTY_HOME="$PROGRAM/profiles/kytyps5/222"
run env FAKE_KYTY_PLAY=/games/PPSA00000 timeout 30 "$PROGRAM/apps/kytyps5" --steam-account 222
check "KytyPS5's launcher started in the account's folder" grep -qF "\"cwd\": \"$KYTY_HOME\", \"folder\": \"$KYTY_HOME\"" "$WORK/kyty.log"
check "KytyPS5's own updater is off" grep -qxF "check_updates_on_startup=false" "$KYTY_HOME/Kyty.ini"
check "KytyPS5 started with a games folder, so it asks for none" grep -qxF "game_dirs=$HOME_DIR/Games/PS5" "$KYTY_HOME/Kyty.ini"
check "KytyPS5's launcher starts dark, with its games in a grid" test "$(grep -cxE 'theme=1|grid_view=true' "$KYTY_HOME/Kyty.ini")" -eq 2
check "KytyPS5 maps View to the touchpad for Steam's gamepad" grep -qF '"Pad:TouchPad=Touchpad", "Pad:TouchPadRight=Back"' "$KYTY_HOME/Kyty.ini"
check "KytyPS5's games render at 1080p" grep -qxF "screen_resolution=1920x1080" "$KYTY_HOME/Kyty.ini"
check "the game ran through NonSteamApps' stand-in terminal, which waited for no key" grep -qF '{"emulator": ["--game", "/games/PPSA00000"]' "$WORK/kyty.log"
check "the game's save stayed in the account's folder" test -d "$KYTY_HOME/_SaveData/PPSA00000"
check "the game's downloaded content went to the folder every account shares" test -d "$PROGRAM/profiles/kytyps5/games/_DownloadData/PPSA00000" -a -L "$KYTY_HOME/_DownloadData"
LICHII_HOME="$PROGRAM/profiles/lichii/222"
mkdir -p "$HOME_DIR/.var/app/dev.eden_emu.eden/data/eden/keys"
echo "header_key = 00" >"$HOME_DIR/.var/app/dev.eden_emu.eden/data/eden/keys/prod.keys"
EDEN_FIRMWARE="$HOME_DIR/.var/app/dev.eden_emu.eden/data/eden/nand/system/Contents/registered"
mkdir -p "$EDEN_FIRMWARE"
echo "firmware" >"$EDEN_FIRMWARE/0123456789abcdef0123456789abcdef.nca"
run "$PROGRAM/apps/lichii" --steam-account 222
check "Lichii's AppImage started full screen, in the account's folder, on X11" grep -qF "{\"argv\": [\"-f\"], \"cwd\": \"$LICHII_HOME\", \"portable\": true, \"env\": {\"QT_QPA_PLATFORM\": \"xcb\"" "$WORK/lichii.log"
check "Lichii's own update check is off" grep -qxF "check_for_updates=false" "$LICHII_HOME/user/config/qt-config.ini"
check "Lichii runs on Vulkan, with ASTC textures kept as BC3" test "$(grep -cxE 'backend=1|astc_recompression=2' "$LICHII_HOME/user/config/qt-config.ini")" -eq 2
check "Lichii lists ~/Games/Switch, which Eden reads, and ~/Games/Switch2, which Eden-NX2 reads" test "$(grep -cxF -e "Paths\\gamedirs\\4\\path=$HOME_DIR/Games/Switch" -e "Paths\\gamedirs\\5\\path=$HOME_DIR/Games/Switch2" "$LICHII_HOME/user/config/qt-config.ini")" -eq 2
check "Lichii took the keys installed in Eden" grep -qxF "header_key = 00" "$LICHII_HOME/user/keys/prod.keys"
check "Lichii took the firmware installed in Eden, as a hard link" test "$LICHII_HOME/user/nand/system/Contents/registered/0123456789abcdef0123456789abcdef.nca" -ef "$EDEN_FIRMWARE/0123456789abcdef0123456789abcdef.nca"
check "the account was invisible to friends while the apps ran, and online once they had closed" status_back

VACUUMTUBE="$HOME_DIR/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-222/config.json"
echo "==> update keeps what the user changed"
rename_shortcut 222 YouTube "My Tube"
python3 -I -c 'import json, sys; data = json.load(open(sys.argv[1])); data["disabled_tabs"] = []; json.dump(data, open(sys.argv[1], "w"))' "$VACUUMTUBE"
run env HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 "$PROGRAM/bin/nonsteamapps" update --yes >"$WORK/update.log" 2>&1 || {
    cat "$WORK/update.log"
    exit 1
}
check "update copied NonSteamApps from the clone it was installed from, then handed over" grep -qE "NonSteamApps [0-9.]+ is up to date" "$WORK/update.log"
check "update added no app" test "$(find "$PROGRAM/apps" -type l | wc -l)" -eq 23
check "update kept the Eden-NX2 build it could not compare with its branch" grep -qF "could not update Eden-NX2, so the build installed stays" "$WORK/update.log"
check "update kept the renamed shortcut" shortcut_named 222 "My Tube"
check "update kept VacuumTube's tabs as the user set them" test "$(json_value "$VACUUMTUBE" disabled_tabs)" == "[]"

echo "==> installing again puts NonSteamApps' set-up back"
run "$ROOT/install.sh" --yes --no-auto-update --helium-archive "$HELIUM_ARCHIVE" --kytyps5-archive "$KYTY_ARCHIVE" --lichii-archive "$LICHII_APPIMAGE" \
    --eden-nx2-commit "$NX2_COMMIT" --skip-verify >"$WORK/reinstall.log" 2>&1 || {
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
check "Lichii's settings stayed, without its AppImages" test -f "$LICHII_HOME/user/config/qt-config.ini" -a ! -e "$PROGRAM/lichii"
check "the shortcuts are gone" test -z "$(shortcut_names 111)$(shortcut_names 222)"
check "the apps it installed were uninstalled" grep -q '"apps": {}' "$WORK/flatpak.json"
check "Eden-NX2's repository was forgotten" grep -qF '["remote-delete", "--user", "--force", "nonsteamapps"]' "$WORK/flatpak.log"
check "Helium left the applications menu" test ! -e "$HOME_DIR/.local/share/applications/nonsteamapps-helium.desktop"
if [ "$PLASMA_HERE" = 0 ]; then
    check "Helium left the taskbar" test "$(grep -c nonsteamapps-helium "$LAYOUT")" -eq 0
fi
check "the collection was removed" test "$(collection_size 111) $(collection_size 222)" == "0 0"
check "LocalSend's port was closed again" grep -qF '"permanent": {"public": []}' "$WORK/firewall.json"
check "NonSteamApps' controller layouts were removed" test -z "$(find "$TEMPLATES" -name '*_nonsteamapps_*')"

if ((failed)); then
    echo "==> Sandbox test FAILED"
    exit 1
fi
echo "==> Sandbox test passed"
