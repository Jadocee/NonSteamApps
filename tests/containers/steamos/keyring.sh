#!/usr/bin/env bash
# Checks what the README says about keyrings on SteamOS, with SteamOS's own KWallet and Valve's set-up of it, in the
# SteamOS image: that nothing starts a Secret Service on demand, as in Game Mode, and that the wallet SteamOS gives
# every device opens without a password, as does a copy of it. A SteamOS release that changes this fails here, and
# the README's "Protecting your data" should then be reviewed.
set -Eeuo pipefail
WORK=$(mktemp -d)
SECRET=nonsteamapps-keyring-check
failed=0
pids=()
trap 'kill "${pids[@]}" 2>/dev/null; rm -rf "$WORK"' EXIT

in_home() {
    local dir=$1
    shift
    env HOME="$dir/home" XDG_DATA_HOME="$dir/home/.local/share" XDG_CONFIG_HOME="$dir/home/.config" \
        XDG_RUNTIME_DIR="$dir/run" DBUS_SESSION_BUS_ADDRESS="unix:path=$dir/bus" QT_QPA_PLATFORM=offscreen "$@"
}

start_home() {
    local dir=$1
    mkdir -p "$dir/home/.local/share/kwalletd" "$dir/home/.config" "$dir/run"
    chmod 700 "$dir/run"
    pids+=("$(dbus-daemon --session --fork --address="unix:path=$dir/bus" --print-pid)")
}

start_kwallet() {
    local dir=$1
    in_home "$dir" ksecretd >"$dir/ksecretd.log" 2>&1 &
    pids+=("$!")
    for _ in $(seq 50); do
        bus_call "$dir" NameHasOwner org.freedesktop.secrets | grep -q true && return 0
        sleep 0.2
    done
    echo "    ksecretd did not take the Secret Service's name" >&2
    return 1
}

bus_call() {
    local dir=$1 method=$2
    shift 2
    in_home "$dir" gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method "org.freedesktop.DBus.$method" "$@"
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

# shellcheck disable=SC2317,SC2329 # run through check
not_activatable() {
    ! bus_call "$1" ListActivatableNames | grep -q "'org.freedesktop.secrets'"
}

# shellcheck disable=SC2317,SC2329 # run through check
reads_back() {
    [ "$(in_home "$1" timeout 20 secret-tool lookup service nonsteamapps account keyring-check)" = "$SECRET" ]
}

first=$WORK/first
second=$WORK/second
start_home "$first"
echo "==> SteamOS ${STEAMOS_RELEASE:-?}: $(pacman -Q kwallet steamdeck-kde-presets | tr '\n' ' ')"
check "nothing starts a Secret Service on demand, as in Game Mode" not_activatable "$first"

in_home "$first" steamos-setup-kwallet
start_kwallet "$first"
printf %s "$SECRET" | in_home "$first" timeout 20 secret-tool store --label=NonSteamApps service nonsteamapps account keyring-check
check "KWallet opens the wallet SteamOS gives every device without a password" reads_back "$first"
in_home "$first" gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets \
    --method org.freedesktop.Secret.Service.Lock "['/org/freedesktop/secrets/aliases/default']" >/dev/null
check "and opens it again after it is locked, without a password" reads_back "$first"

start_home "$second"
cp "$first/home/.local/share/kwalletd/"kdewallet* "$second/home/.local/share/kwalletd/"
in_home "$second" kwriteconfig6 --file kwalletrc --group Wallet --key "First Use" false
start_kwallet "$second"
check "a copy of the wallet's files, in another home, gives up the secret without a password" reads_back "$second"
exit "$failed"
