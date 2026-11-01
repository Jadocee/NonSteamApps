"""The apps NonSteamApps can install, and how each keeps separate data per Steam account."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .display import TV_HEIGHT
from .fsutil import atomic_write_json
from .layouts import FILES_TITLE

RunApp = Callable[[Sequence[str]], int]
_STEAM_PROFILE = re.compile(r"steam-\d+\Z")
VACUUMTUBE_DEFAULTS = {
    "sponsorblock": True,
    "dearrow": True,
    "dislikes": True,
    "block_continue_watching": True,
    "hide_shorts": True,
    "features_enabled": True,
    "remaining_time_feature": True,
    "wayland_hdr": True,
}
ELEMENT_DEFAULTS = {"minimizeToTray": False}
CHANGES_FILE = "nonsteamapps.json"


@dataclass(frozen=True)
class JsonSettings:
    """Values for one of an app's JSON settings files, at ``file`` in its data folder."""

    file: str
    values: Tuple[Tuple[str, object], ...]

    def apply(self, folder: Path) -> Optional[bool]:
        """Write the values into the file, keeping its other settings; return whether it changed.

        Returns ``None``, and leaves the file alone, when it does not hold a JSON object: the app replaces such a file itself.
        """
        path = Path(folder) / self.file
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        wanted = {key: list(value) if isinstance(value, tuple) else value for key, value in self.values}
        if all(key in data and data[key] == value for key, value in wanted.items()):
            return False
        data.update(wanted)
        atomic_write_json(path, data)
        return True


@dataclass(frozen=True)
class FolderProfile:
    """Per-account data in a folder chosen with one command-line argument.

    ``defaults`` are files written into a data folder that does not have them yet,
    including the app's own ``shared`` folder used when accounts share data. ``changes``
    are settings changed once in every data folder, new or existing, each under its own
    name. The names done are kept in the folder's ``nonsteamapps.json``, so a setting the
    user changes afterwards stays as they set it.
    """

    folder: str
    argument: str
    shared: str = ""
    defaults: Tuple[Tuple[str, str], ...] = ()
    changes: Tuple[Tuple[str, JsonSettings], ...] = ()

    def path(self, app_home: Path, account: int) -> Path:
        return Path(app_home) / self.folder.format(account=account)

    def data_folder(self, app_home: Path, account: Optional[int]) -> Optional[Path]:
        """The folder an account's data is in, or without one the shared folder."""
        if account:
            return self.path(app_home, account)
        return Path(app_home) / self.shared if self.shared else None

    def arguments(self, app_home: Path, account: int) -> List[str]:
        return [self.argument.format(folder=self.path(app_home, account), account=account)]

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*args, *self.arguments(app_home, account)]

    def run_options(self) -> List[str]:
        return []

    def _seed(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in self.defaults:
            target = folder / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        self._change(folder)

    def _change(self, folder: Path) -> None:
        if not self.changes:
            return
        record = folder / CHANGES_FILE
        try:
            done = list(json.loads(record.read_text(encoding="utf-8"))["changes"])
        except (OSError, ValueError, TypeError, KeyError):
            done = []
        pending = [(name, settings) for name, settings in self.changes if name not in done]
        applied = [name for name, settings in pending if settings.apply(folder) is not None]
        if applied:
            atomic_write_json(record, {"changes": done + applied})

    def prepare(self, app_home: Path, account: int, run_app: RunApp) -> bool:
        self._seed(self.path(app_home, account))
        return True

    def prepare_shared(self, app_home: Path) -> None:
        if self.shared and (self.defaults or self.changes):
            self._seed(Path(app_home) / self.shared)

    def existing(self, app_home: Path) -> List[Path]:
        pattern = re.compile(re.escape(Path(self.folder).name).replace(r"\{account\}", r"\d+") + r"\Z")
        parent = self.path(app_home, 0).parent
        if not parent.is_dir():
            return []
        return sorted(path for path in parent.iterdir() if path.is_dir() and pattern.match(path.name))


@dataclass(frozen=True)
class ScriptProfile(FolderProfile):
    """A folder handed to the app's own launch script in an environment variable (``argument`` is ``VAR={folder}``).

    ``flatpak run --env`` cannot set the XDG directories, because Flatpak sets them afterwards, so the
    script (``command``) starts through ``env`` inside the sandbox, after any ``fixed`` assignments.
    """

    command: str = ""
    fixed: Tuple[str, ...] = ()

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*self.arguments(app_home, account), *self.fixed, self.command, *args]

    def run_options(self) -> List[str]:
        return ["--command=env"]


@dataclass(frozen=True)
class JellyfinProfile:
    """Jellyfin Desktop's named profiles, which must exist before ``--profile`` can select one."""

    data: str = "data/jellyfin-desktop"
    cache: str = "cache/jellyfin-desktop"

    @staticmethod
    def name(account: int) -> str:
        return f"steam-{account}"

    def arguments(self, app_home: Path, account: int) -> List[str]:
        return [f"--profile={self.name(account)}"]

    def data_folder(self, app_home: Path, account: Optional[int]) -> Optional[Path]:
        return None

    def wrap(self, app_home: Path, account: int, args: Sequence[str]) -> List[str]:
        return [*args, *self.arguments(app_home, account)]

    def run_options(self) -> List[str]:
        return []

    def prepare_shared(self, app_home: Path) -> None:
        return None

    def profiles(self, app_home: Path) -> Dict[str, Path]:
        """Map profile names to their folders, as Jellyfin Desktop records them."""
        found: Dict[str, Path] = {}
        directory = Path(app_home) / self.data / "profiles"
        if not directory.is_dir():
            return found
        for folder in sorted(directory.iterdir()):
            try:
                name = json.loads((folder / "profile.json").read_text(encoding="utf-8")).get("name")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(name, str):
                found.setdefault(name, folder)
        return found

    def prepare(self, app_home: Path, account: int, run_app: RunApp) -> bool:
        name = self.name(account)
        if name in self.profiles(app_home):
            return True
        run_app(["--create-profile", name])
        return name in self.profiles(app_home)

    def existing(self, app_home: Path) -> List[Path]:
        folders = []
        for name, folder in self.profiles(app_home).items():
            if _STEAM_PROFILE.match(name):
                folders.append(folder)
                cache = Path(app_home) / self.cache / "profiles" / folder.name
                if cache.is_dir():
                    folders.append(cache)
        return folders


Profile = Union[FolderProfile, ScriptProfile, JellyfinProfile]
WEB_BROWSER = "Web Browser"
GAMEPAD = "Gamepad"


@dataclass(frozen=True)
class SystemApp:
    """An app SteamOS includes (``command``), started from Steam with a TV profile of its own.

    The profile gives the app its own ``XDG_CONFIG_HOME`` and ``XDG_STATE_HOME``. The desktop's settings stay
    readable underneath, through ``XDG_CONFIG_DIRS``, so the app keeps its look and file associations, but
    what it saves stays in the profile, as it does for the apps it opens. ``defaults`` are written into the
    profile's config folder when missing, ``shared`` files there are links to the desktop's own, and
    ``game_mode`` variables are set only in Game Mode.
    """

    command: str
    defaults: Tuple[Tuple[str, str], ...] = ()
    shared: Tuple[str, ...] = ()
    game_mode: Tuple[Tuple[str, str], ...] = ()

    def prepare(self, profile: Path, desktop_config: Path) -> None:
        config = Path(profile) / "config"
        for name, content in self.defaults:
            target = config / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        for name in self.shared:
            link, source = config / name, Path(desktop_config) / name
            if source.is_file() and not link.exists() and not link.is_symlink():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source)
        (Path(profile) / "state").mkdir(parents=True, exist_ok=True)

    def environment(self, profile: Path, desktop_config: Path, environ: Mapping[str, str], game_mode: bool) -> Dict[str, str]:
        """The variables that start the app with its profile, layered over the desktop's settings."""
        variables = {
            "XDG_CONFIG_HOME": str(Path(profile) / "config"),
            "XDG_CONFIG_DIRS": ":".join([str(desktop_config), environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"]),
            "XDG_STATE_HOME": str(Path(profile) / "state"),
        }
        if game_mode:
            variables.update(self.game_mode)
        return variables


@dataclass(frozen=True)
class Browser:
    """An app that runs in NonSteamApps' own Helium: the browser itself, or one site full screen (kiosk)."""

    url: str = ""
    kiosk: bool = False


@dataclass(frozen=True)
class TvScale:
    """How an app takes its TV scale: a command-line ``argument`` with ``{factor}`` in it, or an environment ``variable``.

    A ``whole`` scale is rounded down, and dropped below 2, for toolkits that only scale by whole numbers.
    ``layout`` is the screen height the app's layout is made for, which the automatic scale fits a TV to.
    ``requires`` are settings the app needs while it is scaled, set before each scaled start.
    """

    argument: str = ""
    variable: str = ""
    whole: bool = False
    layout: int = TV_HEIGHT
    requires: Optional[JsonSettings] = None

    def _text(self, factor: float) -> Optional[str]:
        value = float(int(factor)) if self.whole else factor
        return None if self.whole and value < 2 else f"{value:g}"

    def apply(self, factor: float) -> Tuple[List[str], List[str]]:
        """Return the app's arguments and ``flatpak run`` options for this scale."""
        text = self._text(factor)
        if text is None:
            return [], []
        arguments = [self.argument.format(factor=text)] if self.argument else []
        return arguments, [f"--env={name}={value}" for name, value in self.variables(factor).items()]

    def variables(self, factor: float) -> Dict[str, str]:
        """The environment variable this scale sets, for an app started without Flatpak."""
        text = self._text(factor)
        return {self.variable: text} if self.variable and text else {}


CHROMIUM_SCALE = TvScale(argument="--force-device-scale-factor={factor}")
VACUUMTUBE_TV = JsonSettings(
    "config.json",
    (("fullscreen", True), ("no_window_decorations", True), ("disabled_tabs", ("shorts", "podcasts"))),
)


@dataclass(frozen=True)
class App:
    """An app NonSteamApps adds to Steam: from Flathub (``flatpak``), in its own Helium (``browser``), or one SteamOS includes (``system``).

    ``controller`` names the controller layout to give the shortcut, one of Valve's or one of
    :mod:`layouts`. ``tv_scale`` says how a Flathub or system app is scaled for a TV in Game Mode, as the
    Helium apps always are. ``sandbox_off_when`` names
    environment variables that make the app turn Chromium's sandbox off; the launcher hides them when
    the user chooses to keep the sandbox. ``notice`` is shown after installing. ``ports`` are opened in
    the firewall, when one is running, so other devices can reach the app.
    """

    id: str
    name: str
    client: str
    summary: str
    flatpak: str = ""
    browser: Optional[Browser] = None
    system: Optional[SystemApp] = None
    args: Tuple[str, ...] = ()
    profile: Optional[Profile] = None
    controller: str = ""
    logo_position: str = "BottomLeft:42:58"
    legacy_exes: Tuple[str, ...] = ()
    tv_scale: Optional[TvScale] = None
    sandbox_off_when: Tuple[str, ...] = ()
    notice: str = ""
    ports: Tuple[str, ...] = ()

    def home(self, user_home: Path) -> Path:
        """The app's own folder, which Flatpak keeps in ``~/.var/app``."""
        return Path(user_home) / ".var" / "app" / self.flatpak

    def arguments(self, user_home: Path, account: Optional[int]) -> List[str]:
        if self.profile and account:
            return self.profile.wrap(self.home(user_home), account, self.args)
        return list(self.args)

    def run_options(self, account: Optional[int]) -> List[str]:
        """Options for ``flatpak run`` itself, before the app ID."""
        return self.profile.run_options() if self.profile and account else []


APPS: Tuple[App, ...] = (
    App(
        id="youtube",
        name="YouTube",
        client="VacuumTube",
        flatpak="rocks.shy.VacuumTube",
        summary="YouTube's TV interface with ad blocking, SponsorBlock, DeArrow and dislike counts",
        args=("--fullscreen",),
        profile=FolderProfile(
            "config/VacuumTube-steam-{account}",
            "--portable={folder}",
            shared="config/VacuumTube",
            defaults=(("config.json", json.dumps(VACUUMTUBE_DEFAULTS, indent=4) + "\n"),),
            changes=(("2.11.0", VACUUMTUBE_TV),),
        ),
        controller=GAMEPAD,
        legacy_exes=("~/.local/share/steamos-yt/bin/steamos-yt",),
        tv_scale=TvScale(
            argument="--force-device-scale-factor={factor}",
            layout=1080,
            requires=JsonSettings("config.json", (("unlock_resolution", True),)),
        ),
        sandbox_off_when=("SteamGamepadUI",),
    ),
    App(
        id="element",
        name="Element",
        client="Element Desktop",
        flatpak="im.riot.Riot",
        summary="Secure chat on Matrix",
        args=("--password-store=basic", "--storage-mode=allow-plaintext"),
        controller=WEB_BROWSER,
        profile=FolderProfile(
            "config/Element-steam-{account}",
            "--profile=steam-{account}",
            defaults=(("electron-config.json", json.dumps(ELEMENT_DEFAULTS, indent=4) + "\n"),),
        ),
        logo_position="BottomLeft:44:56",
        tv_scale=CHROMIUM_SCALE,
    ),
    App(
        id="signal",
        name="Signal",
        client="Signal Desktop",
        flatpak="org.signal.Signal",
        summary="Private messages and calls, linked to Signal on your phone",
        controller=WEB_BROWSER,
        profile=ScriptProfile(
            "config/Signal-steam-{account}",
            "XDG_CONFIG_HOME={folder}",
            defaults=(("Signal/config.json", "{}\n"),),
            command="signal-desktop",
            fixed=("SIGNAL_PASSWORD_STORE=basic",),
        ),
        logo_position="BottomLeft:44:56",
        tv_scale=CHROMIUM_SCALE,
        notice="Signal keeps its database key unencrypted on disk, as Flathub's Signal does by default; see the README",
    ),
    App(
        id="jellyfin",
        name="Jellyfin",
        client="Jellyfin Desktop",
        flatpak="org.jellyfin.JellyfinDesktop",
        summary="Your Jellyfin media server's films, shows and music, in its TV layout",
        args=("--tv", "--fullscreen"),
        profile=JellyfinProfile(),
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(argument="--scale-factor={factor}"),
    ),
    App(
        id="localsend",
        name="LocalSend",
        client="LocalSend",
        flatpak="org.localsend.localsend_app",
        summary="Send files to and from nearby phones and computers over your own network",
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
        ports=("53317/tcp", "53317/udp"),
        tv_scale=TvScale(variable="GDK_SCALE", whole=True),
    ),
    App(
        id="files",
        name="Files",
        client="Dolphin",
        summary="Browse and open your files with SteamOS's file manager, set up for a TV and a controller",
        system=SystemApp(
            command="dolphin",
            defaults=(
                ("dolphinrc", "[General]\nRememberOpenedTabs=false\n\n[MainWindow]\nMenuBar=Disabled\n"),
                ("kdeglobals", "[KDE]\nSingleClick=true\n"),
            ),
            shared=("user-dirs.dirs", "user-dirs.locale"),
            game_mode=(("QT_QPA_PLATFORM", "xcb"), ("QT_QPA_PLATFORMTHEME", "kde")),
        ),
        args=("--new-window",),
        controller=FILES_TITLE,
        logo_position="BottomLeft:44:56",
        tv_scale=TvScale(variable="QT_SCALE_FACTOR"),
    ),
    App(
        id="helium",
        name="Helium",
        client="Helium",
        summary="A private, ad-blocking web browser, set up for a TV and a controller",
        browser=Browser(),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="primevideo",
        name="Prime Video",
        client="Helium",
        summary="Prime Video's films and series, full screen in Helium",
        browser=Browser(url="https://www.primevideo.com/", kiosk=True),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="hbomax",
        name="HBO Max",
        client="Helium",
        summary="HBO Max's series and films, full screen in Helium",
        browser=Browser(url="https://www.hbomax.com/", kiosk=True),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="netflix",
        name="Netflix",
        client="Helium",
        summary="Netflix's series and films, full screen in Helium",
        browser=Browser(url="https://www.netflix.com/", kiosk=True),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="disneyplus",
        name="Disney+",
        client="Helium",
        summary="Disney+'s films and series, full screen in Helium",
        browser=Browser(url="https://www.disneyplus.com/", kiosk=True),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
    App(
        id="protondb",
        name="ProtonDB",
        client="Helium",
        summary="Player reports on how well games run with Proton, full screen in Helium",
        browser=Browser(url="https://www.protondb.com/", kiosk=True),
        controller=WEB_BROWSER,
        logo_position="BottomLeft:44:56",
    ),
)


def by_id(app_id: str) -> App:
    for app in APPS:
        if app.id == app_id.strip().lower():
            return app
    raise KeyError(app_id)


def ids() -> List[str]:
    return [app.id for app in APPS]
