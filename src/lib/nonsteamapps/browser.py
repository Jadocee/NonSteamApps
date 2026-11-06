"""Console set-up for the apps that run in Helium.

Each app keeps one Helium profile per Steam account. Before every start, the
profile is told it closed cleanly (Steam ends apps by signalling them) and that
first-run pages are done. Arrow keys move between links and buttons (spatial
navigation), with a clear outline around the one they reach, Helium and sites
that offer a dark theme start dark (Helium's Mode setting can still choose
light), and in Game Mode the interface scales with the screen, so a TV reads
like a TV app. Ctrl+Shift+Q runs Helium's Exit, which no page can intercept,
not even in a full-screen app, for the controller's long press on Menu.

Helium already blocks ads (uBlock Origin), third-party cookies and WebRTC's
local addresses, adds fingerprinting noise and keeps background mode, link
auditing and preloading off; new profiles also send Global Privacy Control
and do not keep crash reports to offer for upload.
"""

from __future__ import annotations

import copy
import json
import os
import urllib.parse
from pathlib import Path
from typing import List, MutableMapping, Optional, Sequence, Tuple

from .fsutil import atomic_write_bytes, atomic_write_json

BLOCK = 2
SCHEMA_VERSION = 1
CRASH_REPORTS_OFF = -1
LOCAL_STATE = {"helium": {"crash_reporting": {"mode": CRASH_REPORTS_OFF}}}
FEATURES = "AcceleratedVideoDecodeLinuxGL,AcceleratedVideoDecodeLinuxZeroCopyGL"
EXIT_COMMAND = "34031"
EXIT_SHORTCUT = "Control+Shift+KeyQ"
BROWSER_BINARIES = ("helium", "chrome", "chromium")
STEAM_INPUT_METHOD = "Steam"
SIMPLE_INPUT_METHOD = "simple"


def single_keystrokes(environ: MutableMapping[str, str]) -> bool:
    """Have Helium take each key of Steam's on-screen keyboard once; return whether ``environ`` changed.

    Steam's Game Mode starts games with ``GTK_IM_MODULE=Steam``, its own GTK input method, which can deliver the same
    text twice to a Chromium-based program that, like Helium, runs on SteamOS itself and can load it; an app in a
    Flatpak cannot. Helium then gets GTK's simple input method instead. Another input method, such as one chosen
    for Desktop Mode, stays.
    """
    if environ.get("GTK_IM_MODULE", "").strip().lower() != STEAM_INPUT_METHOD.lower():
        return False
    environ["GTK_IM_MODULE"] = SIMPLE_INPUT_METHOD
    return True


def deep_merge(base: dict, overlay: dict) -> dict:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def first_run_preferences(kiosk: bool) -> dict:
    """Written once, into a new profile: Global Privacy Control, no notification requests, and for full-screen apps no other prompts."""
    preferences: dict = {
        "helium": {"global_privacy_control": True},
        "browser": {"has_seen_welcome_page": True},
        "profile": {"default_content_setting_values": {"notifications": BLOCK}},
    }
    if kiosk:
        deep_merge(preferences, {
            "translate": {"enabled": False},
            "credentials_enable_service": False,
            "credentials_enable_autosignin": False,
            "autofill": {"profile_enabled": False, "credit_card_enabled": False},
            "profile": {"password_manager_enabled": False, "default_content_setting_values": {"geolocation": BLOCK}},
        })
    return preferences


def launch_preferences(services: bool) -> dict:
    """Applied before every start: onboarding done, the services choice, and a clean last exit."""
    helium: dict = {"completed_onboarding": True, "services": {"enabled": services}}
    if services:
        helium["services"]["user_consented"] = True
    return {
        "helium": helium,
        "browser": {"has_seen_welcome_page": True},
        "profile": {"exit_type": "Normal", "exited_cleanly": True},
    }


def add_exit_shortcut(preferences: dict) -> None:
    """Add Ctrl+Shift+Q to Helium's own shortcuts for Exit (Chromium's ``IDC_EXIT``), keeping any the user added."""
    deep_merge(preferences, {"helium": {"browser": {"custom_accelerators": {}}}})
    commands = preferences["helium"]["browser"]["custom_accelerators"]
    entry = commands.get(EXIT_COMMAND) if isinstance(commands.get(EXIT_COMMAND), dict) else {}

    def others(name: str) -> List[str]:
        keys = entry.get(name)
        return [key for key in keys if isinstance(key, str) and key != EXIT_SHORTCUT] if isinstance(keys, list) else []

    removed = others("removed")
    commands[EXIT_COMMAND] = {"added": [*others("added"), EXIT_SHORTCUT], **({"removed": removed} if removed else {})}


def _load(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_preferences(profile: Path, services: bool, kiosk: bool) -> Path:
    path = Path(profile) / "Default" / "Preferences"
    fresh = not path.exists()
    data = _load(path)
    if data is None:
        atomic_write_bytes(path.with_name("Preferences.corrupt"), path.read_bytes())
        data, fresh = {}, True
    if fresh:
        deep_merge(data, first_run_preferences(kiosk))
    deep_merge(data, launch_preferences(services))
    add_exit_shortcut(data)
    if services:
        settings = data["helium"]["services"]
        if not isinstance(settings.get("schema_version"), int) or settings["schema_version"] < SCHEMA_VERSION:
            settings["schema_version"] = SCHEMA_VERSION
    atomic_write_json(path, data, compact=True)
    return path


def write_local_state(profile: Path) -> Path:
    """Start a new profile with crash reports off, so no upload question follows a crash; later starts keep the user's choice."""
    path = Path(profile) / "Local State"
    if not path.exists():
        atomic_write_json(path, LOCAL_STATE, compact=True)
    return path


def reset(profile: Path, kiosk: bool) -> bool:
    """Put a new profile's settings back into an existing one, as an install does; return whether it changed.

    A missing or damaged file is left for Helium, which writes a new one.
    """
    changed = False
    for path, wanted in ((Path(profile) / "Default" / "Preferences", first_run_preferences(kiosk)), (Path(profile) / "Local State", LOCAL_STATE)):
        data = _load(path) if path.is_file() else None
        if not data:
            continue
        merged = deep_merge(copy.deepcopy(data), wanted)
        if merged != data:
            atomic_write_json(path, merged, compact=True)
            changed = True
    return changed


def allow_callbacks(profile: Path, url: str, schemes: Sequence[str]) -> List[str]:
    """Let the sign-in page at ``url`` open the app's callback without asking, when it names one of ``schemes`` as its return address.

    Chromium asks before a page opens a link that only another app handles, unless the page's origin may open
    that kind of link, as ticking "Always allow" records. Returns the schemes allowed.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        return []
    returns = [
        value
        for query in (parts.query, parts.fragment.partition("?")[2])
        for key, value in urllib.parse.parse_qsl(query)
        if key.lower() in ("redirect_uri", "redirecturi", "redirecturl")
    ]
    allowed = [scheme for scheme in schemes if any(value.lower().startswith(f"{scheme.lower()}:") for value in returns)]
    path = Path(profile) / "Default" / "Preferences"
    data = _load(path) if allowed else None
    if data is None:
        return []
    origin = f"https://{parts.netloc}"
    deep_merge(data, {"protocol_handler": {"allowed_origin_protocol_pairs": {origin: {scheme: True for scheme in allowed}}}})
    atomic_write_json(path, data, compact=True)
    return allowed


def clear_stale_lock(profile: Path) -> bool:
    """Remove a lock left by a Helium that is no longer running, which would block the next start."""
    lock = Path(profile) / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    pid = target.rsplit("-", 1)[-1]
    if pid.isdecimal():
        try:
            exe = os.path.basename(os.readlink(f"/proc/{pid}/exe")).replace(" (deleted)", "")
        except OSError:
            exe = ""
        if exe in BROWSER_BINARIES:
            return False
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = Path(profile) / name
        if path.is_symlink() or path.exists():
            path.unlink()
    return True


def link_widevine(profile: Path, shared: Path) -> None:
    """Point the profile's Widevine folder at one shared by every profile, so one download serves them all."""
    Path(shared).mkdir(parents=True, exist_ok=True)
    link = Path(profile) / "WidevineCdm"
    if link.is_symlink() and not link.exists():
        link.unlink()
    if not link.exists():
        link.symlink_to(shared, target_is_directory=True)


def prepare(profile: Path, services: bool, kiosk: bool, widevine: Path) -> None:
    Path(profile).mkdir(parents=True, exist_ok=True)
    write_preferences(profile, services, kiosk)
    write_local_state(profile)
    clear_stale_lock(profile)
    link_widevine(profile, widevine)


def flags(profile: Path, url: str, kiosk: bool, game_mode: bool, factor: Optional[float], name: str, window: Optional[Tuple[int, int]] = None,
          extensions: Sequence[Path] = ()) -> List[str]:
    """Helium's arguments. ``window`` is the size, in device-independent pixels, that a browser window takes instead of
    being maximised: gamescope ignores maximising. ``extensions`` are folders of NonSteamApps' extensions, such as the
    focus outline, each loaded when present.
    """
    arguments = [
        f"--user-data-dir={profile}",
        f"--class={name}",
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--hide-crash-restore-bubble",
        "--noerrdialogs",
        "--hide-fullscreen-exit-ui",
        "--enable-spatial-navigation",
        "--force-dark-mode",
        f"--enable-features={FEATURES}",
        "--ozone-platform=x11" if game_mode else "--ozone-platform-hint=auto",
    ]
    if factor:
        arguments.append(f"--force-device-scale-factor={factor:g}")
    present = [str(folder) for folder in extensions if (Path(folder) / "manifest.json").is_file()]
    if present:
        arguments.append(f"--load-extension={','.join(present)}")
    if kiosk:
        arguments += [
            "--kiosk",
            "--autoplay-policy=no-user-gesture-required",
            "--deny-permission-prompts",
            "--disable-pinch",
            "--overscroll-history-navigation=0",
        ]
    elif window:
        arguments += ["--window-position=0,0", f"--window-size={window[0]},{window[1]}"]
    else:
        arguments.append("--start-maximized")
    return arguments + ([url] if url else [])
