"""The ``nonsteamapps`` command. Steam starts each app through ``nonsteamapps launch <app>``."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import (
    __version__, appmenu, apps, browser, collection, compat, config, controllers, desktop, display, kyty, layouts, legacy, links, nx2,
    presence, selfupdate, steam, steamclient, timer, ui, x11,
)
from .apps import App
from .config import Paths, Record
from .firewall import Firewall, FirewallError
from .flatpak import Flatpak, FlatpakError, Installed, x11_options
from .helium import HeliumError, Runtime

EXIT_ERROR = 1
EXIT_INTERRUPTED = 130
PER_ACCOUNT = "PROFILE_PER_STEAM_ACCOUNT"
HELIUM_SERVICES = "HELIUM_SERVICES"
TV_SCALE = "TV_SCALE"
HELIUM_SCALE = "HELIUM_SCALE"
GAME_MODE_SANDBOX = "GAME_MODE_SANDBOX"
EDEN_CONSOLE_MODE = "EDEN_CONSOLE_MODE"
COLLECTION = "STEAM_COLLECTION"
DEFAULT_COLLECTION = "NonSteamApps"
RESOLUTION_HINT = "⚙ ▸ Properties ▸ Shortcut ▸ Maximum Game Resolution ▸ Native"


def _refuse_root() -> None:
    if os.getuid() == 0 and os.environ.get("NONSTEAMAPPS_ALLOW_ROOT") != "1":
        raise ui.Abort("run nonsteamapps as your normal user (for example 'deck'), not as root")


def _choose(names: Sequence[str]) -> List[App]:
    chosen: List[App] = []
    for name in names:
        try:
            app = apps.by_id(name)
        except KeyError:
            raise ui.Abort(f"unknown app {name!r}; choose from: {', '.join(apps.ids())}") from None
        if app not in chosen:
            chosen.append(app)
    return chosen


def _managed(record: Record) -> List[App]:
    return [app for app in apps.APPS if app.id in record.apps]


def _names(chosen: Sequence[App]) -> str:
    names = [app.name for app in chosen]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _listing(chosen: Sequence[App]) -> str:
    names = [f"{app.name} ({app.client})" if app.name != app.client else app.name for app in chosen]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _runtime(paths: Paths) -> Runtime:
    return Runtime(paths.helium, paths.helium_key)


def _kyty(paths: Paths) -> kyty.Runtime:
    return kyty.Runtime(paths.kyty)


def _nx2(paths: Paths, flatpak: Flatpak) -> nx2.Builder:
    return nx2.Builder(paths.nx2, flatpak.command)


def _firewall() -> Firewall:
    return Firewall()


def _describe_ports(ports: Sequence[str]) -> str:
    protocols: Dict[str, List[str]] = {}
    for port in ports:
        number, _, protocol = port.partition("/")
        protocols.setdefault(number, []).append(protocol.upper())
    return ", ".join(f"{number} ({' and '.join(names)})" for number, names in protocols.items())


def _open_ports(record: Record, chosen: Sequence[App]) -> None:
    """Let other devices reach the apps that need it, when SteamOS's firewall is running."""
    wanted = [app for app in chosen if app.ports]
    wall = _firewall()
    if not wanted or not wall.running():
        return
    for app in wanted:
        closed = wall.closed(app.ports)
        if not closed:
            continue
        ports = _describe_ports(app.ports)
        if not ui.confirm(f"Open port {ports} in the firewall, so other devices can reach {app.client}? sudo asks for your password", default=True):
            ui.info(f"{app.client} cannot be reached while the firewall blocks port {ports}; to open it, run the installer again")
            continue
        try:
            wall.change("add", closed)
        except FirewallError as error:
            ui.warn(f"Could not open port {ports} for {app.client} ({error}). If your account has no password, set one with passwd and run the installer again, or run:")
            for command in error.commands:
                ui.info(f"  {command}")
            continue
        opened = record.opened_ports(app.id)
        for zone, found in closed.items():
            opened[zone] = sorted(set(opened.get(zone, [])) | set(found))
        record.set_opened_ports(app.id, opened)
        ui.ok(f"Opened port {ports} in the firewall for {app.client}")


def _close_ports(record: Record, chosen: Sequence[App]) -> None:
    """Close the firewall ports NonSteamApps opened for these apps."""
    for app in chosen:
        opened = record.opened_ports(app.id)
        if not opened:
            continue
        ports = _describe_ports(sorted({port for found in opened.values() for port in found}))
        try:
            _firewall().change("remove", opened)
        except FirewallError as error:
            ui.warn(f"Could not close port {ports}, which NonSteamApps opened for {app.client} ({error}); to close it, run:")
            for command in error.commands:
                ui.info(f"  {command}")
        else:
            ui.ok(f"Closed port {ports}, which NonSteamApps opened for {app.client}")
        record.set_opened_ports(app.id, {})


def _firewall_status(record: Record) -> str:
    wall = _firewall()
    if not wall.running():
        return "not running"
    found = []
    for app in apps.APPS:
        if app.ports and app.id in record.apps:
            closed = wall.closed(app.ports)
            state = "open" if not closed else f"closed in {', '.join(closed)}; run the installer again to open it"
            found.append(f"{app.client}'s port {_describe_ports(app.ports)} {state}")
    return "; ".join(["firewalld running", *found])


def _steam_root() -> Optional[Path]:
    try:
        return steam.find_steam_root()
    except steam.SteamError:
        return None


def _is_steamos() -> bool:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return any(line.startswith(("id=", "id_like=")) and "steamos" in line for line in text.splitlines())


def _account_label(account: int, names: Dict[int, str]) -> str:
    name = names.get(account)
    return f"Steam account {name} ({account})" if name else f"Steam account {account}"


def _report(result: steam.ShortcutResult, verb: str, names: Dict[int, str]) -> str:
    return f"{_account_label(result.account, names)}: {verb} \"{result.name}\" (app ID {result.appid})"


def _spec(paths: Paths, app: App) -> steam.ShortcutSpec:
    return steam.ShortcutSpec(
        name=app.name,
        exe=str(paths.app_link(app.id)),
        start_dir=str(paths.program),
        launch_options=f"--steam-account {steam.ACCOUNT_PLACEHOLDER}",
        overlay=False,
        legacy_exes=app.legacy_exes,
    )


def _link(paths: Paths, app: App) -> None:
    """Point ``apps/<id>`` at the launcher; Steam runs that link, and the launcher reads the app from its name."""
    link = paths.app_link(app.id)
    link.parent.mkdir(parents=True, exist_ok=True)
    target = os.path.relpath(paths.launcher, link.parent)
    if link.is_symlink() and os.readlink(link) == target:
        return
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


def _collection_name(paths: Paths) -> str:
    """The collection the apps go in; empty for none."""
    return config.read_settings(paths.settings).get(COLLECTION, DEFAULT_COLLECTION).strip()


Work = Tuple[App, steam.ShortcutSpec, Dict[str, Path], steam.LogoPosition]


def _library_changes(root: Path, accounts: Sequence[int], work: Sequence[Work], found: Dict[str, Dict[str, str]], record: steam.ArtworkRecord) -> bool:
    """Whether refreshing the shortcuts already there, keeping what the user changed, would change Steam's own files."""
    for app, spec, artwork, logo in work:
        for result in steam.add_shortcut(root, accounts, spec, artwork, logo, overwrite=False, record=record, create=False, dry_run=True):
            if result.changed or (app.controller and controllers.pending(root, result.account, result.name, found[app.controller])):
                return True
    return False


def steam_add(paths: Paths, chosen: Sequence[App], user: str = "all", restart: bool = True, overwrite: bool = True) -> None:
    """Add the apps to the Steam library of each account ``user`` selects.

    With ``overwrite``, as install and ``steam add`` do, each shortcut, its artwork and its controller layout
    become NonSteamApps' again, the apps join the collection and no Steam Play tool stays forced. Without it, as
    update does, only shortcuts already there are refreshed and what the user changed stays; Steam is closed only
    when its own files must change.
    """
    root = _steam_root()
    if root is None:
        ui.warn(f"Steam was not found; sign in to Steam once, then run: {paths.launcher} steam add")
        return
    accounts = steam.select_accounts(root, user)
    if not accounts:
        ui.warn(f"no Steam account was found; sign in to Steam once, then run: {paths.launcher} steam add")
        return
    names = steam.account_names(root)
    record = steam.ArtworkRecord(paths.artwork_record)
    for layout in layouts.used_by(app.controller for app in chosen):
        layouts.install(root, layout)
    found_layouts = {title: controllers.find_templates(root, title) for title in dict.fromkeys(app.controller for app in chosen if app.controller)}
    work: List[Work] = [
        (app, _spec(paths, app), steam.collect_artwork(paths.artwork(app.id)), steam.LogoPosition.parse(app.logo_position)) for app in chosen
    ]
    if not overwrite and not _library_changes(root, accounts, work, found_layouts, record):
        for app, spec, artwork, logo in work:
            steam.add_shortcut(root, accounts, spec, artwork, logo, overwrite=False, record=record, create=False, save=False)
        record.save()
        ui.ok("The Steam library is up to date")
        return
    ui.log(f"Adding {_listing(chosen)} to your Steam library" if overwrite else f"Refreshing {_listing(chosen)} in your Steam library")
    added: Dict[int, List[int]] = {}
    owners: Dict[int, App] = {}
    native: Dict[int, str] = {}
    waiting: List[str] = []
    name = _collection_name(paths)
    with steamclient.closed(f"{paths.launcher} {'steam add' if overwrite else 'update'}", restart):
        for app, spec, artwork, logo in work:
            for result in steam.add_shortcut(root, accounts, spec, artwork, logo, overwrite=overwrite, record=record, create=overwrite):
                if overwrite or result.changed:
                    ui.ok(_report(result, "added" if result.created else "updated", names))
                added.setdefault(result.account, []).append(result.appid)
                owners[result.appid] = app
                if app.controller:
                    controllers.assign(root, result.account, result.name, found_layouts[app.controller], force=overwrite)
        if overwrite:
            for account, appids in added.items():
                path = collection.storage_file(root, account)
                if path is None:
                    waiting.append(names.get(account, str(account)))
                elif name:
                    collection.update(path, name, add=appids)
                else:
                    collection.delete(path)
            native = compat.clear(root, owners)
    record.save()
    if not overwrite:
        return
    for appid, tool in sorted(native.items()):
        ui.ok(f"{owners[appid].name} no longer forces the Steam Play tool {tool}: like every NonSteamApps app, it runs natively")
    if name and len(waiting) < len(added):
        ui.ok(f'Put {_listing(chosen)} in the "{name}" collection')
    if name and waiting:
        ui.info(f"Steam has not set up collections for {', '.join(waiting)} yet; open Steam with that account once, then run: {paths.launcher} steam add")
    for title, found in found_layouts.items():
        if found:
            ui.ok(f"Gave {_listing([app for app in chosen if app.controller == title])} the {title} controller layout")
        else:
            ui.info(f"The {title} controller layout was not found; pick a layout for these apps in Steam")


def steam_remove(paths: Paths, chosen: Sequence[App], user: str = "all", restart: bool = True) -> None:
    root = _steam_root()
    if root is None:
        return
    accounts = steam.select_accounts(root, user)
    present = [app for app in chosen if steam.shortcut_status(root, accounts, str(paths.app_link(app.id)))]
    if not present:
        return
    names = steam.account_names(root)
    name = _collection_name(paths) or DEFAULT_COLLECTION
    removed: Dict[str, List[int]] = {}
    with steamclient.closed(f"{paths.launcher} steam remove", restart):
        for app in present:
            for result in steam.remove_shortcut(root, accounts, str(paths.app_link(app.id))):
                ui.ok(_report(result, "removed", names))
                removed.setdefault(app.id, []).append(result.appid)
                path = collection.storage_file(root, result.account)
                if path is not None:
                    collection.update(path, name, remove=[result.appid])
                if app.controller:
                    controllers.release(root, result.account, result.name)
        gone = [app for app in present if not steam.shortcut_status(root, steam.account_ids(root), str(paths.app_link(app.id)))]
        compat.clear(root, [appid for app in gone for appid in removed.get(app.id, [])], everything=True)
        for layout in layouts.used_by(app.controller for app in present):
            users = [app for app in apps.APPS if app.controller == layout.title]
            if not any(steam.shortcut_status(root, steam.account_ids(root), str(paths.app_link(app.id))) for app in users):
                layouts.remove(root, layout)


def _install_helium(paths: Paths, archive: Optional[str], verify: bool) -> None:
    runtime = _runtime(paths)
    current = runtime.current()
    if current and not archive:
        ui.ok(f"Helium {current} is installed")
        return
    ui.log("Installing Helium" + (f" from {archive}" if archive else " from GitHub"))
    version = runtime.install(Path(archive) if archive else None, verify=verify)
    ui.ok(f"Installed Helium {version}")


def _install_kyty(paths: Paths, archive: Optional[str], verify: bool) -> None:
    runtime = _kyty(paths)
    current = runtime.current()
    if current and not archive:
        ui.ok(f"KytyPS5 {kyty.describe(current)} is installed; {paths.launcher} update installs a newer build")
        return
    ui.log("Installing KytyPS5" + (f" from {archive}" if archive else " from its GitHub releases"))
    tag = runtime.install(Path(archive) if archive else None, verify=verify)
    ui.ok(f"Installed KytyPS5 {kyty.describe(tag)}")


def _install_nx2(paths: Paths, flatpak: Flatpak, commit: Optional[str]) -> None:
    builder = _nx2(paths, flatpak)
    current = builder.current()
    if current and (not commit or commit == current.commit):
        ui.ok(f"Eden-NX2 {nx2.describe(current)} is installed; {paths.launcher} update builds its newest source")
        return
    ui.log("Building Eden-NX2 from its source, " + (f"commit {commit}" if commit else f"the {nx2.BRANCH} branch") + f" of {nx2.REPOSITORY}")
    build = builder.build(commit or builder.latest())
    ui.ok(f"Installed Eden-NX2 {nx2.describe(build)}")


def _install_app(paths: Paths, flatpak: Flatpak, record: Record, app: App, found: Optional[Installed]) -> None:
    if app.system:
        command = shutil.which(app.system.command)
        if command:
            ui.ok(f"{app.client} is part of the system ({command})")
        else:
            ui.warn(f"{app.client} ({app.system.command}) was not found; SteamOS includes it, other systems install it from their own packages")
        record.add(app.id, installed_flatpak=False)
    elif app.browser or app.release:
        record.add(app.id, installed_flatpak=False)
    elif app.from_source:
        record.add(app.id, installed_flatpak=True)
    elif found:
        version = f" {found.version}" if found.version else ""
        ui.ok(f"{app.client}{version} is already installed ({found.installation} installation)")
        record.add(app.id, installed_flatpak=False)
    else:
        ui.log(f"Installing {app.client} from Flathub ({app.flatpak})")
        flatpak.install(app.flatpak)
        record.add(app.id, installed_flatpak=True)
        ui.ok(f"Installed {app.client}")
    _link(paths, app)


def _reset(paths: Paths, app: App, separate: bool) -> int:
    """Put NonSteamApps' TV settings back in the app's existing data, keeping sign-ins; return the data folders changed."""
    if app.browser:
        return sum(browser.reset(folder, app.browser.kiosk) for folder in sorted((paths.profiles / app.id).glob("*")) if folder.is_dir())
    if app.system:
        return int(app.system.reset(paths.profile(app.id, None)))
    if app.release:
        homes = sorted(folder for folder in (paths.profiles / app.id).glob("*") if folder.is_dir() and folder.name != kyty.GAMES)
        return sum(any([wanted.apply(home) for wanted in app.release.settings]) for home in homes)
    home = app.home(paths.home)
    count = len(app.profile.reset(home, shared=not separate)) if app.profile else 0
    if app.settings and home.is_dir() and any([wanted.apply(home) for wanted in app.settings]):
        count += 1
    return count


def _purge(paths: Paths, app: App) -> None:
    if app.browser or app.system or app.release:
        folders = [paths.profiles / app.id] if (paths.profiles / app.id).is_dir() else []
    else:
        folders = app.profile.existing(app.home(paths.home)) if app.profile else []
        if app.callbacks and (paths.profiles / app.id).is_dir():
            folders.append(paths.profiles / app.id)
    for folder in folders:
        shutil.rmtree(folder)
    if folders:
        ui.ok(f"Deleted {app.name}'s data for each Steam account ({len(folders)} folder{'s' if len(folders) > 1 else ''})")


def _uninstall_flatpaks(flatpak: Flatpak, record: Record, chosen: Sequence[App]) -> None:
    installed = flatpak.installed() if flatpak.available() else {}
    removed = False
    for app in chosen:
        found = installed.get(app.flatpak)
        if found is None:
            continue
        if record.owns_flatpak(app.id) and found.installation == "user":
            ui.log(f"Uninstalling {app.client}")
            flatpak.uninstall(app.flatpak)
            removed = True
        else:
            ui.info(f"{app.client} stays installed: it was installed before NonSteamApps")
    if removed:
        flatpak.remove_unused()


def _summary(paths: Paths, managed: Sequence[App], separate: bool) -> None:
    ui.log("Done")
    width = max([len("Sign-ins:")] + [len(app.name) + 1 for app in managed]) + 1
    for app in managed:
        client = f" ({app.client})" if app.client != app.name else ""
        ui.info(f"{app.name + ':':<{width}}Steam ▸ Library ▸ Non-Steam ▸ {app.name}{client}")
    ui.info(f"{'Sign-ins:':<{width}}{'separate for each Steam account' if separate else 'shared by all Steam accounts'}")
    for app in managed:
        if app.notice:
            ui.info(f"{'Note:':<{width}}{app.notice}")
    ui.info(f"{'TV:':<{width}}for an app's full resolution, open it in Game Mode: {RESOLUTION_HINT}")
    ui.info(f"{'Settings:':<{width}}{paths.settings}")


def cmd_install(args, paths: Paths, flatpak: Flatpak) -> int:
    _refuse_root()
    if not _is_steamos():
        ui.warn("this does not look like SteamOS; continuing anyway")
    record = Record.load(paths.record)
    old = legacy.Legacy.detect()
    chosen = _choose(args.apps)
    if not chosen:
        chosen = list(apps.APPS)
        question = f"Install {_listing(chosen)}?"
        if not any(app.from_source and app.id in record.apps for app in chosen):
            question += " Eden-NX2 is built here from its source, which can take an hour."
        if record.managed():
            question += " The apps already installed get NonSteamApps' set-up back; their sign-ins and data are kept."
        if not ui.confirm(question, default=True):
            raise ui.Abort(f"nothing installed; pick apps with: {paths.launcher} install APP..., or update the apps you have with: {paths.launcher} update")
    youtube = apps.by_id("youtube")
    if old.present() and youtube not in chosen:
        chosen.insert(0, youtube)
        ui.info("SteamOS YT is installed, so its YouTube shortcut moves to VacuumTube")
    if any(app.flatpak for app in chosen) and not flatpak.available():
        raise ui.Abort(f"flatpak is not installed; NonSteamApps installs {_listing([a for a in chosen if a.flatpak])} from Flathub")

    ui.log(f"Installing NonSteamApps {__version__} into {paths.program}")
    paths.state.mkdir(parents=True, exist_ok=True)
    selfupdate.remember(paths, os.environ)
    fresh = not paths.settings.exists()
    message = config.install_defaults(paths.program / "share" / "config" / config.SETTINGS_FILE, paths.settings)
    if message:
        ui.info(message)
    if fresh and old.separate_profiles() is False:
        config.set_setting(paths.settings, PER_ACCOUNT, "0")
        ui.info("Kept SteamOS YT's choice of one sign-in shared by all Steam accounts")
    separate = config.enabled(config.read_settings(paths.settings).get(PER_ACCOUNT), default=True)

    if any(app.browser for app in chosen):
        _install_helium(paths, args.helium_archive, not args.skip_verify)
    if any(app.release for app in chosen):
        try:
            _install_kyty(paths, args.kytyps5_archive, not args.skip_verify)
        except (kyty.KytyError, OSError) as exc:
            if all(app.release for app in chosen):
                raise ui.Abort(f"KytyPS5 was not installed: {exc}") from exc
            ui.warn(f"KytyPS5 was not installed, so it is left out: {exc}")
            chosen = [app for app in chosen if not app.release]
    if any(app.from_source for app in chosen):
        try:
            _install_nx2(paths, flatpak, args.eden_nx2_commit)
        except (nx2.NX2Error, OSError) as exc:
            if all(app.from_source for app in chosen):
                raise ui.Abort(f"Eden-NX2 was not installed: {exc}") from exc
            ui.warn(f"Eden-NX2 was not installed, so it is left out: {exc}")
            chosen = [app for app in chosen if not app.from_source]
    installed = flatpak.installed() if any(app.flatpak for app in chosen) else {}
    for app in chosen:
        _install_app(paths, flatpak, record, app, installed.get(app.flatpak))
        record.save()
        reset = _reset(paths, app, separate)
        if reset:
            ui.ok(f"Put back {app.name}'s TV settings ({reset} data folder{'s' if reset > 1 else ''}); sign-ins are kept")
        if app.desktop:
            _add_to_desktop(paths, app)
    _open_ports(record, chosen)
    record.save()

    if args.auto_update:
        timer.install(paths)
    else:
        timer.remove(paths)
    managed = _managed(record)
    if args.steam:
        steam_add(paths, chosen, args.steam_user, args.restart_steam)
        if old.present():
            if ui.confirm("Remove SteamOS YT, including its Helium browser and its YouTube sign-ins?", default=True):
                for path in old.remove():
                    ui.ok(f"Removed {path}")
            else:
                ui.info(f"Kept SteamOS YT's files; Steam now starts VacuumTube for YouTube. Remove them later with: {paths.launcher} install youtube")
    elif old.present():
        ui.info("Kept SteamOS YT, because its Steam shortcut was not moved to VacuumTube (--no-steam)")
    _summary(paths, managed, separate)
    return 0


def cmd_remove(args, paths: Paths, flatpak: Flatpak) -> int:
    _refuse_root()
    chosen = _choose(args.apps)
    record = Record.load(paths.record)
    question = f"Remove {_listing(chosen)} from Steam"
    question += f" and delete {'its' if len(chosen) == 1 else 'their'} data for every Steam account?" if args.purge else "? Sign-ins are kept."
    if not ui.confirm(question, default=not args.purge):
        raise ui.Abort("cancelled")
    steam_remove(paths, chosen, "all", args.restart_steam)
    for app in chosen:
        paths.app_link(app.id).unlink(missing_ok=True)
        _remove_from_desktop(paths, app)
        if args.purge:
            _purge(paths, app)
    if not args.keep_app:
        _close_ports(record, chosen)
        _uninstall_flatpaks(flatpak, record, chosen)
    for app in chosen:
        record.discard(app.id)
    record.save()
    if not args.keep_app and not any(app.browser for app in _managed(record)) and paths.helium.exists():
        _runtime(paths).remove()
        ui.ok("Removed Helium, which no other app uses")
    if not args.keep_app and not any(app.release for app in _managed(record)) and paths.kyty.exists():
        _unlink_kyty_homes(paths)
        _kyty(paths).remove()
        kept = (paths.profiles / "kytyps5").is_dir()
        ui.ok("Removed KytyPS5's builds" + (f"; each Steam account's saves and settings stay in {paths.profiles / 'kytyps5'}" if kept else ""))
    if not args.keep_app and not any(app.from_source for app in _managed(record)) and paths.nx2.exists():
        _nx2(paths, flatpak).remove()
        ui.ok("Removed Eden-NX2's source, builds and build caches")
    ui.ok(f"Removed {_listing(chosen)}")
    return 0


def _add_to_desktop(paths: Paths, app: App) -> None:
    """Add the app to Desktop Mode's applications menu and pin it to Plasma's taskbar (see :mod:`desktop`)."""
    entry = paths.desktop_entry(app.id)
    text = desktop.entry_text(app.name, app.summary, paths.app_link(app.id), paths.artwork(app.id) / "icon.png", entry.stem,
                              app.desktop.generic, app.desktop.categories)
    try:
        desktop.write_entry(entry, text)
    except OSError as exc:
        ui.warn(f"could not add {app.name} to Desktop Mode's applications menu: {exc}")
        return
    pinned = desktop.pin(desktop.launcher(entry), paths.plasma_layout)
    if pinned is None:
        ui.info(f"Added {app.name} to Desktop Mode's applications menu; Plasma's taskbar could not be changed, so pin it from the menu")
    else:
        ui.ok(f"Added {app.name} to Desktop Mode's applications menu and taskbar")


def _remove_from_desktop(paths: Paths, app: App) -> None:
    """Take the app off Plasma's taskbar and out of Desktop Mode's applications menu, where NonSteamApps put it."""
    entry = paths.desktop_entry(app.id)
    if not entry.exists():
        return
    if desktop.unpin(desktop.launcher(entry), paths.plasma_layout):
        ui.ok(f"Took {app.name} off Desktop Mode's taskbar")
    entry.unlink(missing_ok=True)


def _unlink_kyty_homes(paths: Paths) -> None:
    """Remove the links to KytyPS5's programs from each account's folder, which keeps only KytyPS5's data."""
    for home in sorted((paths.profiles / "kytyps5").glob("*")):
        if home.is_dir() and home.name != kyty.GAMES:
            kyty.unlink_home(home)


def _parse_launch(argv: Sequence[str]) -> Tuple[str, str, bool, List[str]]:
    if not argv or argv[0].startswith("-"):
        raise ui.Abort(f"launch needs an app: {', '.join(apps.ids())}")
    app_id, rest = argv[0], list(argv[1:])
    account, verbose, extra = "", False, []
    while rest:
        argument = rest.pop(0)
        if argument == "--":
            extra += rest
            break
        if argument == "--verbose":
            verbose = True
        elif argument == "--steam-account":
            account = rest.pop(0) if rest else ""
        elif argument.startswith("--steam-account="):
            account = argument.split("=", 1)[1]
        else:
            extra.append(argument)
    return app_id, account, verbose, extra


def _redirect(log: Path) -> None:
    previous = log.with_name(log.name + ".1")
    if log.exists():
        os.replace(log, previous)
    sys.stdout.flush()
    sys.stderr.flush()
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(descriptor, 1)
    os.dup2(descriptor, 2)
    os.close(descriptor)


def _scale_setting(settings: Dict[str, str]) -> str:
    return settings.get(TV_SCALE) or settings.get(HELIUM_SCALE) or "auto"


def cmd_launch(argv: Sequence[str], paths: Paths, flatpak: Flatpak) -> int:
    app_id, hint, verbose, extra = _parse_launch(argv)
    app = _choose([app_id])[0]
    settings = config.read_settings(paths.settings)
    account = None
    if config.enabled(settings.get(PER_ACCOUNT), default=True):
        account = steam.launch_account(_steam_root(), hint)
    paths.state.mkdir(parents=True, exist_ok=True)
    if not verbose:
        _redirect(paths.log(app.id))
    print(f"nonsteamapps {__version__}: starting {_listing([app])} for {f'Steam account {account}' if account else 'all accounts'}")
    if steamclient.leave_steam_environment(os.environ):
        print("  without Steam's overlay library and Steam Runtime paths")
    _hide_from_friends(paths, app, settings, hint)
    if app.browser:
        return _launch_helium(paths, app, account, extra)
    if app.system:
        return _launch_system(paths, app, extra)
    if app.release:
        return _launch_kyty(paths, app, account, extra)
    if account and app.profile:
        ready = app.profile.prepare(app.home(paths.home), account, lambda options: flatpak.run_quietly(app.flatpak, options))
        if not ready:
            print(f"warning: could not create {app.client}'s data for Steam account {account}; using its shared data")
            account = None
    if not account and app.profile:
        app.profile.prepare_shared(app.home(paths.home))
    for wanted in app.settings:
        if not wanted.target(app.home(paths.home)).exists():
            wanted.apply(app.home(paths.home))
    _place_userstyles(paths, app, account)
    games = _games_folder(paths, app, account)
    game_mode = steamclient.in_game_mode()
    _console_mode(paths, app, account, settings, game_mode)
    factor = display.scale(_scale_setting(settings), game_mode, layout=app.tv_scale.layout) if app.tv_scale else None
    scale, scale_options = app.tv_scale.apply(factor) if app.tv_scale and factor else ([], [])
    required = app.tv_scale.requires if app.tv_scale and factor else None
    folder = app.profile.data_folder(app.home(paths.home), account) if required and app.profile else None
    if folder and required.apply(folder):
        print(f"  set {', '.join(key for key, _ in required.values)} in {required.file}, which the TV scale needs")
    options = [*app.run_options(paths.home, account), *games, *scale_options, *_environment(app, game_mode), *_libraries(app)]
    channel = _link_channel(paths, app, game_mode)
    if channel:
        options += links.sandbox_options(paths.program / "share" / "sandbox", channel[0], app.callbacks)
    command = flatpak.run_args(app.flatpak, [*app.arguments(paths.home, account), *scale, *_qt_window(app, game_mode, factor), *extra], options)
    hidden = [variable for variable in app.sandbox_off_when if variable in os.environ]
    if hidden and config.enabled(settings.get(GAME_MODE_SANDBOX)):
        for variable in hidden:
            del os.environ[variable]
        print(f"  keeping {app.client}'s sandbox on: hid {', '.join(hidden)} ({GAME_MODE_SANDBOX}=1)")
    print("  " + " ".join(command), flush=True)
    if game_mode:
        _tidy_window(app)
    if channel:
        return _serve_links(paths, app, account, command, settings, game_mode, channel)
    os.execvp(command[0], command)
    return EXIT_ERROR


def _hide_from_friends(paths: Paths, app: App, settings: Dict[str, str], hint: Optional[str]) -> None:
    """Keep an app that Steam started out of the status friends see, as ``INVISIBLE_WHILE_RUNNING`` says (see :mod:`presence`).

    Steam's shortcuts pass ``--steam-account``; an app started from elsewhere, such as the applications menu,
    is not one Steam shows, so the status stays as it is.
    """
    if not hint or not presence.applies(settings.get(presence.SETTING), app.id):
        return
    root = _steam_root()
    account = steam.launch_account(root, hint) if root else None
    localconfig = steam.config_dir(root, account) / "localconfig.vdf" if root and account else None
    keeper = presence.Presence(paths.state, localconfig)
    invisible, message = keeper.hide(os.getpid())
    if message:
        print(f"  {message}", flush=True)
    keeper.watch(os.getpid(), invisible)


def _games_folder(paths: Paths, app: App, account: Optional[int]) -> List[str]:
    """Create the app's games folder, add it to the game list when the user has none there, and open it to the sandbox for this run."""
    if not app.games:
        return []
    games = paths.home / app.games
    try:
        games.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"  {app.client} starts without {games}: {exc}")
        return []
    settings = app.profile.settings_file(app.home(paths.home), account) if isinstance(app.profile, apps.PortableProfile) else None
    if settings and apps.add_game_folder(settings, games):
        print(f"  added {games} to {app.client}'s game list: copy your games there", flush=True)
    return [f"--filesystem={games}:ro"]


def _console_mode(paths: Paths, app: App, account: Optional[int], settings: Dict[str, str], game_mode: bool) -> None:
    """Run the emulated console docked or handheld, as ``EDEN_CONSOLE_MODE`` says.

    With ``auto``, it runs docked in Game Mode when Steam runs it at a TV's size, and handheld below that, as on a
    Steam Deck's screen; outside Game Mode, the emulator keeps its own choice.
    """
    if not app.console_mode or not isinstance(app.profile, apps.PortableProfile):
        return
    choice = (settings.get(EDEN_CONSOLE_MODE) or "auto").strip().lower()
    if choice == "auto":
        height = display.screen_height() if game_mode else None
        if not height:
            return
        docked, reason = display.tv_sized(height), f"Steam runs it {height} pixels tall"
    elif choice in ("docked", "handheld"):
        docked, reason = choice == "docked", f"{EDEN_CONSOLE_MODE}={choice}"
    else:
        return
    settings_file = app.profile.settings_file(app.home(paths.home), account)
    if settings_file and apps.set_console_mode(settings_file, docked):
        print(f"  {app.client} runs {'docked' if docked else 'handheld'}: {reason}", flush=True)


def _place_userstyles(paths: Paths, app: App, account: Optional[int]) -> None:
    folder = app.profile.data_folder(app.home(paths.home), account) if app.userstyles and app.profile else None
    if not folder:
        return
    try:
        written = apps.place_userstyles(paths.userstyles, folder, app.userstyles)
    except OSError as exc:
        print(f"  could not add NonSteamApps' styles to {app.client}: {exc}")
        return
    if written:
        print(f"  added {', '.join(written)} to {app.client}'s userstyles", flush=True)


def _tidy_window(app: App) -> None:
    """In Game Mode, before the app starts: ask for its windows to be full screen, and hide an Electron app's menu bar."""
    if app.fullscreen_class:
        x11.watch(app.fullscreen_class, os.getpid())
    if app.hide_menu_bar:
        if appmenu.watch(os.getpid()):
            print(f"  hiding {app.client}'s menu bar: NonSteamApps stands in for the desktop's global menu", flush=True)
        else:
            print(f"  {app.client} keeps its menu bar: the session bus is out of reach, or another program owns the global menu", flush=True)


def _qt_window(app: App, game_mode: bool, factor: Optional[float]) -> List[str]:
    """Give a Qt app's first window the screen's size in Game Mode, where it would otherwise keep its own and get black bars."""
    size = display.window_size(factor) if app.qt_window and game_mode else None
    return ["-qwindowgeometry", f"{size[0]}x{size[1]}+0+0"] if size else []


def _link_channel(paths: Paths, app: App, game_mode: bool) -> Optional[Tuple[Path, int]]:
    """In Game Mode, the pipe through which an app with sign-in callbacks passes its links to Helium."""
    if not (app.callbacks and game_mode):
        return None
    if not _runtime(paths).current():
        print(f"  Helium is not installed, so {app.client}'s links open in Steam's browser, from which a sign-in cannot return")
        return None
    try:
        return links.open_channel(links.channel_dir(app.flatpak, os.environ))
    except OSError as exc:
        print(f"  {app.client}'s links open in Steam's browser: {exc}")
        return None


def _serve_links(paths: Paths, app: App, account: Optional[int], command: List[str], settings: Dict[str, str], game_mode: bool,
                 channel: Tuple[Path, int]) -> int:
    """Run the app as a child, open its links in Helium in front of it, and hand its sign-ins back to it (see :mod:`links`)."""
    pipe, fd = channel
    runtime = _runtime(paths)
    profile = paths.profile(app.id, account)
    services = config.enabled(settings.get(HELIUM_SERVICES), default=True)
    factor = display.scale(_scale_setting(settings), game_mode)
    environment = links.browser_environment(os.environ, paths.program / "share" / "sandbox", pipe, app.callbacks)
    browsers: List[subprocess.Popen] = []

    def open_web(url: str) -> None:
        browser.prepare(profile, services, False, runtime.widevine)
        signing_in = browser.allow_callbacks(profile, url, app.callbacks)
        print(f"  opening {'the sign-in page at ' if signing_in else ''}{urllib.parse.urlsplit(url).netloc} in Helium", flush=True)
        name = f"nonsteamapps-{app.id}"
        argv = [str(runtime.executable), *browser.flags(profile, url, False, game_mode, factor, name, display.window_size(factor), [paths.focus_extension])]
        browsers.append(subprocess.Popen(argv, env=environment, start_new_session=True))
        x11.watch(name, browsers[-1].pid)

    def deliver(url: str) -> None:
        print(f"  handing the sign-in back to {app.client}", flush=True)
        subprocess.Popen([*command, url])
        links.stop(browsers)

    child = subprocess.Popen(command)
    previous = signal.signal(signal.SIGTERM, lambda *_: child.terminate())
    try:
        return links.serve(child, fd, app.callbacks, open_web, deliver)
    finally:
        signal.signal(signal.SIGTERM, previous)
        links.stop(browsers)
        os.close(fd)
        pipe.unlink(missing_ok=True)


def _environment(app: App, game_mode: bool) -> List[str]:
    """``flatpak run`` options for the display and the variables the app is started with from Steam."""
    display_options = x11_options() if app.x11 else []
    return [*display_options, *(f"--env={name}={value}" for name, value in (*app.env, *(app.game_mode_env if game_mode else ())))]


def _libraries(app: App) -> List[str]:
    """``flatpak run`` options that let the app's sandbox reach every Steam library folder."""
    root = _steam_root() if app.libraries else None
    folders = steam.library_folders(root) if root else []
    return [f"--filesystem={folder}" for folder in folders if folder.is_dir() and ":" not in str(folder)]


def _launch_helium(paths: Paths, app: App, account: Optional[int], extra: Sequence[str]) -> int:
    runtime = _runtime(paths)
    if not runtime.current():
        raise ui.Abort(f"Helium is not installed; run: {paths.launcher} install {app.id}")
    settings = config.read_settings(paths.settings)
    game_mode = steamclient.in_game_mode()
    profile = paths.profile(app.id, account)
    browser.prepare(profile, config.enabled(settings.get(HELIUM_SERVICES), default=True), app.browser.kiosk, runtime.widevine)
    factor = display.scale(_scale_setting(settings), game_mode)
    name = f"nonsteamapps-{app.id}"
    window = display.window_size(factor) if game_mode and not app.browser.kiosk else None
    url = app.browser.start_url(account)
    extensions = [paths.focus_extension, *(paths.extension(folder) for folder in app.browser.extensions)]
    command = [str(runtime.executable), *browser.flags(profile, url, app.browser.kiosk, game_mode, factor, name, window, extensions), *extra]
    print(f"  Helium {runtime.current()}: " + " ".join(command), flush=True)
    if window:
        x11.watch(name, os.getpid())
    os.execv(command[0], command)
    return EXIT_ERROR


def _launch_kyty(paths: Paths, app: App, account: Optional[int], extra: Sequence[str]) -> int:
    """Start KytyPS5's launcher in the account's folder, which holds its settings and saves (see :mod:`kyty`).

    The launcher runs a game through the program in ``$TERMINAL``; NonSteamApps' own runs it without a window.
    """
    runtime = _kyty(paths)
    if not runtime.current():
        raise ui.Abort(f"KytyPS5 is not installed; run: {paths.launcher} install {app.id}")
    settings = config.read_settings(paths.settings)
    home = paths.profile(app.id, account)
    fresh = not (home / kyty.SETTINGS_FILE).exists()
    launcher = runtime.prepare_home(home)
    for name in kyty.share_game_data(home, paths.profiles / app.id / kyty.GAMES):
        print(f"  {home / name} stays as it is: it holds what the shared folder already has")
    for wanted in app.release.settings:
        if not wanted.target(home).exists():
            wanted.apply(home)
    apps.apply_changes(home, app.release.changes)
    if fresh:
        others = [path for path in sorted((paths.profiles / app.id).glob(f"*/{kyty.SETTINGS_FILE}")) if path.parent != home]
        folders = kyty.game_folders(others)
        if folders:
            apps.IniSettings(kyty.SETTINGS_FILE, (("Launcher", "game_dirs", folders),)).apply(home)
            print(f"  starting with the game folders another account set up: {folders}")
    listed = kyty.listed_game_folders(home / kyty.SETTINGS_FILE)
    if not any(Path(folder).is_dir() for folder in listed):
        games = paths.home / kyty.DEFAULT_GAMES
        games.mkdir(parents=True, exist_ok=True)
        folders = listed if str(games) in listed else [*listed, str(games)]
        apps.IniSettings(kyty.SETTINGS_FILE, (("Launcher", "game_dirs", kyty.game_folders_value(folders)),)).apply(home)
        reason = "none of the game folders KytyPS5 lists exists" if listed else "KytyPS5 lists no game folder"
        print(f"  {reason}, so it has {games}: copy your games there, or add folders in its global settings")
    game_mode = steamclient.in_game_mode()
    factor = display.scale(_scale_setting(settings), game_mode, layout=app.tv_scale.layout) if app.tv_scale else None
    variables = {"TERMINAL": str(paths.program / "share" / "kytyps5" / "terminal")}
    if factor:
        variables.update(app.tv_scale.variables(factor))
    if game_mode:
        variables.update(app.game_mode_env)
        variables.update(RESOURCE_NAME=app.fullscreen_class, SDL_APP_ID=app.fullscreen_class)
    os.environ.update(variables)
    os.chdir(home)
    argv = [str(launcher), *extra]
    print(f"  KytyPS5 {kyty.describe(runtime.current() or '')} in {home}: "
          + " ".join([*(f"{name}={value}" for name, value in variables.items()), *argv]), flush=True)
    if game_mode:
        _tidy_window(app)
    os.execv(argv[0], argv)
    return EXIT_ERROR


def _launch_system(paths: Paths, app: App, extra: Sequence[str]) -> int:
    command = shutil.which(app.system.command)
    if not command:
        raise ui.Abort(f"{app.client} ({app.system.command}) is not installed; SteamOS includes it")
    settings = config.read_settings(paths.settings)
    game_mode = steamclient.in_game_mode()
    profile = paths.profile(app.id, None)
    desktop = config.xdg_dir(os.environ, "XDG_CONFIG_HOME", paths.home, ".config")
    if desktop == profile / "config":
        desktop = paths.home / ".config"
    app.system.prepare(profile, desktop)
    variables = app.system.environment(profile, desktop, os.environ, game_mode)
    factor = display.scale(_scale_setting(settings), game_mode, layout=app.tv_scale.layout) if app.tv_scale else None
    scale = app.tv_scale.apply(factor)[0] if factor else []
    if factor:
        variables.update(app.tv_scale.variables(factor))
    os.environ.update(variables)
    argv = [command, *app.args, *scale, *_qt_window(app, game_mode, factor), *extra]
    print("  " + " ".join([*(f"{name}={value}" for name, value in variables.items()), *argv]), flush=True)
    os.execv(command, argv)
    return EXIT_ERROR


def _update_program(args, paths: Paths) -> None:
    """Replace NonSteamApps with the latest version from where it was installed, which then updates the apps.

    Returns only in the version that has just replaced the one before, or when no new version can be had.
    """
    previous = os.environ.pop(selfupdate.UPDATED_FROM_VARIABLE, None)
    if previous is not None:
        ui.ok(f"Updated NonSteamApps from {previous} to {__version__}" if previous != __version__ else f"NonSteamApps {__version__} is up to date")
        return
    source = selfupdate.source(paths)
    ui.log(f"Updating NonSteamApps from {source}")
    try:
        with tempfile.TemporaryDirectory(prefix="nonsteamapps-update.") as work:
            selfupdate.copy(selfupdate.fetch(source, Path(work)), paths.program, os.environ)
    except (selfupdate.UpdateError, OSError) as exc:
        ui.warn(f"could not update NonSteamApps ({exc}); the apps are updated by NonSteamApps {__version__}")
        return
    os.environ[selfupdate.UPDATED_FROM_VARIABLE] = __version__
    argv = [str(paths.launcher), "update", *(["--yes"] if args.yes else []), *(["--quiet"] if args.quiet else [])]
    if not args.restart_steam:
        argv.append("--no-restart-steam")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(str(paths.launcher), argv)


def _update_apps(paths: Paths, flatpak: Flatpak, record: Record, managed: Sequence[App], manual: bool = True) -> None:
    own_layouts = layouts.used_by(app.controller for app in managed)
    root = _steam_root() if own_layouts else None
    for layout in own_layouts if root else []:
        if layouts.install(root, layout):
            ui.ok(f"Refreshed the {layout.title} controller layout")
    if any(app.browser for app in managed):
        try:
            version = _runtime(paths).update()
        except (HeliumError, OSError) as exc:
            ui.warn(f"could not update Helium: {exc}")
        else:
            ui.ok(f"Updated Helium to {version}" if version else "Helium is up to date")
    if manual and any(app.release for app in managed):
        try:
            tag = _kyty(paths).update()
        except (kyty.KytyError, OSError) as exc:
            ui.warn(f"could not update KytyPS5: {exc}")
        else:
            ui.ok(f"Updated KytyPS5 to {kyty.describe(tag)}" if tag else "KytyPS5 is up to date")
    if manual and any(app.from_source for app in managed):
        try:
            build = _nx2(paths, flatpak).update()
        except (nx2.NX2Error, OSError) as exc:
            ui.warn(f"could not update Eden-NX2, so the build installed stays: {exc}")
        else:
            ui.ok(f"Updated Eden-NX2 to {nx2.describe(build)}" if build else "Eden-NX2 is up to date")
    installed = flatpak.installed() if any(app.flatpak for app in managed) else {}
    ours = [
        app for app in managed
        if app.flatpak and not app.from_source and record.owns_flatpak(app.id) and getattr(installed.get(app.flatpak), "installation", "") == "user"
    ]
    if ours:
        ui.log(f"Updating {_listing(ours)}")
        flatpak.update([app.flatpak for app in ours], quiet=ui.quiet)
        ui.ok("Apps are up to date")
    elif not any(app.browser or app.release or app.from_source for app in managed):
        ui.info("NonSteamApps installed no apps to update; Discover updates the rest")


def cmd_update(args, paths: Paths, flatpak: Flatpak) -> int:
    """Update NonSteamApps, unless ``--apps-only``, then the apps, keeping which apps are installed and how they are set up."""
    if not args.apps_only:
        _update_program(args, paths)
    record = Record.load(paths.record)
    managed = _managed(record)
    _update_apps(paths, flatpak, record, managed, manual=not args.apps_only)
    if args.apps_only or not managed:
        return 0
    message = config.install_defaults(paths.program / "share" / "config" / config.SETTINGS_FILE, paths.settings)
    if message:
        ui.info(message)
    timer.refresh(paths)
    for app in managed:
        _link(paths, app)
    try:
        steam_add(paths, managed, "all", args.restart_steam, overwrite=False)
    except ui.Abort as exc:
        ui.warn(f"left the Steam library as it was: {exc}")
    return 0


def cmd_rollback(args, paths: Paths, flatpak: Flatpak) -> int:
    if args.app == "kytyps5":
        tag = _kyty(paths).rollback()
        ui.ok(f"Switched KytyPS5 back to {kyty.describe(tag)}")
        return 0
    if args.app == "edennx2":
        build = _nx2(paths, flatpak).rollback()
        ui.ok(f"Switched Eden-NX2 back to {nx2.describe(build)}; {paths.launcher} update switches to its newest source again")
        return 0
    version = _runtime(paths).rollback()
    ui.ok(f"Switched Helium back to {version}")
    return 0


def cmd_steam(args, paths: Paths, flatpak: Flatpak) -> int:
    _refuse_root()
    chosen = _choose(args.apps) or _managed(Record.load(paths.record))
    if not chosen:
        raise ui.Abort(f"no apps are installed; install some with: {paths.launcher} install")
    if args.action == "add":
        steam_add(paths, chosen, args.user or "all", args.restart_steam)
    elif args.action == "remove":
        steam_remove(paths, chosen, args.user or "all", args.restart_steam)
    else:
        root = _steam_root()
        if root is None:
            raise ui.Abort("Steam was not found")
        accounts = steam.select_accounts(root, args.user or "all")
        names = steam.account_names(root)
        for app in chosen:
            results = steam.shortcut_status(root, accounts, str(paths.app_link(app.id)))
            for result in results:
                print(_report(result, "present", names))
            if not results:
                print(f"{app.name}: not in the Steam library (add it with: {paths.launcher} steam add {app.id})")
    return 0


def _describe(app: App, record: Record, found: Optional[Installed], helium: Optional[str] = None, build: Optional[str] = None,
              built: Optional[nx2.Build] = None) -> str:
    if app.release:
        return f"KytyPS5 {kyty.describe(build)}" if build else "not installed"
    if app.from_source:
        return f"{app.client} {nx2.describe(built)}, built here from its source ({found.installation} installation)" if found else "not installed"
    if app.system:
        command = shutil.which(app.system.command)
        return f"{app.client} from the system ({command})" if command else f"not found ({app.system.command})"
    if app.browser:
        return f"in Helium {helium}" if helium else "not installed"
    if found is None:
        return "not installed"
    version = f" {found.version}" if found.version else ""
    origin = ", installed by NonSteamApps" if record.owns_flatpak(app.id) else ""
    return f"{app.client}{version} ({found.installation} installation{origin})"


def cmd_list(args, paths: Paths, flatpak: Flatpak) -> int:
    record = Record.load(paths.record)
    installed = flatpak.installed() if flatpak.available() else {}
    helium = _runtime(paths).current()
    build = _kyty(paths).current()
    built = _nx2(paths, flatpak).current() if nx2.APP_ID in installed else None
    for app in apps.APPS:
        managed = app.id in record.apps
        status = _describe(app, record, installed.get(app.flatpak), helium if managed else None, build if managed else None, built)
        managed = "in use" if app.id in record.apps else "available"
        print(f"{app.id:<10}{managed:<11}{status}")
        print(f"{'':<21}{app.summary}")
    return 0


def _size(path: Path) -> str:
    """The size of what is only in ``path``: links, hard ones included, are not counted."""
    total = sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file() and not entry.is_symlink() and entry.stat().st_nlink == 1)
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            return f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
        total /= 1024
    return ""


def _helium_status(paths: Paths, settings: Dict[str, str]) -> str:
    runtime = _runtime(paths)
    current = runtime.current()
    if not current:
        return "not installed"
    others = [version for version in runtime.versions() if version != current]
    services = "on" if config.enabled(settings.get(HELIUM_SERVICES), default=True) else "off"
    widevine = "downloaded" if any(runtime.widevine.glob("*/manifest.json")) else "not downloaded yet"
    return (f"{current}" + (f" (also {', '.join(others)})" if others else "")
            + f"; services {services}; Widevine {widevine}")


def _kyty_status(paths: Paths) -> str:
    runtime = _kyty(paths)
    current = runtime.current()
    if not current:
        return "not installed"
    others = [kyty.describe(tag) for tag in runtime.versions() if tag != current]
    return kyty.describe(current) + (f" (also {', '.join(others)})" if others else "") + f"; newer builds with: {paths.launcher} update"


def _nx2_status(paths: Paths, flatpak: Flatpak) -> str:
    builder = _nx2(paths, flatpak)
    current = builder.current()
    if not current:
        return "not installed" + (f"; the last build's log is {builder.log}" if builder.log.is_file() else "")
    others = [nx2.describe(build) for build in builder.builds() if build.flatpak != current.flatpak]
    return (nx2.describe(current) + (f" (also {', '.join(others)})" if others else "")
            + f"; build log {builder.log}; its newest source with: {paths.launcher} update")


def cmd_doctor(args, paths: Paths, flatpak: Flatpak) -> int:
    try:
        release = dict(
            line.split("=", 1) for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines() if "=" in line
        ).get("PRETTY_NAME", "unknown").strip('"')
    except OSError:
        release = "unknown"
    settings = config.read_settings(paths.settings)
    separate = config.enabled(settings.get(PER_ACCOUNT), default=True)
    print(ui.bold(f"NonSteamApps {__version__}"))
    rows = [
        ("System", f"{release} ({platform.machine()}, kernel {platform.release()})"),
        ("Session", "Game Mode (gamescope)" if steamclient.in_game_mode() else f"{os.environ.get('XDG_SESSION_TYPE', 'unknown')} desktop"),
        ("Program", str(paths.program)),
        ("Settings", f"{paths.settings} (sign-ins {'separate for each Steam account' if separate else 'shared'})"),
        ("Python", platform.python_version()),
        ("Flatpak", "available" if flatpak.available() else "not installed"),
        ("Helium", _helium_status(paths, settings)),
        ("KytyPS5", _kyty_status(paths)),
        ("Eden-NX2", _nx2_status(paths, flatpak)),
        ("Firewall", _firewall_status(Record.load(paths.record))),
        ("TV scale", f"{_scale_setting(settings)} (Helium apps, {_names([app for app in apps.APPS if app.tv_scale])})"),
        ("Updates", timer.status(paths)),
    ]
    root = _steam_root()
    rows.append(("Steam", f"{root} ({'running' if steamclient.running() else 'not running'})" if root else "not found"))
    for label, value in rows:
        print(f"  {label:<10} {value}")
    record = Record.load(paths.record)
    installed = flatpak.installed() if flatpak.available() else {}
    accounts = steam.account_ids(root) if root else []
    names = steam.account_names(root) if root else {}
    print(ui.bold("Apps"))
    helium = _runtime(paths).current()
    build = _kyty(paths).current()
    built = _nx2(paths, flatpak).current() if nx2.APP_ID in installed else None
    for app in apps.APPS:
        if app.id not in record.apps and (not app.flatpak or app.flatpak not in installed):
            continue
        print(f"  {app.id:<10} {_describe(app, record, installed.get(app.flatpak), helium, build, built)}")
        if root:
            results = steam.shortcut_status(root, accounts, str(paths.app_link(app.id)))
            for result in results:
                print(f"  {'':<10} {_report(result, 'in the library as', names)}")
            for tool in sorted(set(compat.forced(root, [result.appid for result in results]).values())):
                print(f"  {'':<10} forced to the Steam Play tool {tool}, so it may not start; run: {paths.launcher} steam add {app.id}")
        if app.browser or app.system or app.release:
            folders = sorted(path for path in (paths.profiles / app.id).glob("*") if path.is_dir())
        else:
            folders = app.profile.existing(app.home(paths.home)) if app.profile else []
        for folder in folders:
            print(f"  {'':<10} data: {folder} ({_size(folder)})")
        log = paths.log(app.id)
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"  {'':<10} last launch log ({log}):")
            for line in lines[-8:]:
                print(f"  {'':<12} {line}")
    return 0


def cmd_uninstall(args, paths: Paths, flatpak: Flatpak) -> int:
    _refuse_root()
    if not (paths.program / "lib" / config.NAME / "__init__.py").is_file():
        raise ui.Abort(f"refusing to remove unexpected directory {paths.program}")
    record = Record.load(paths.record)
    managed = _managed(record)
    question = "Remove NonSteamApps and its Steam shortcuts"
    if managed and not args.keep_apps:
        question += f", and uninstall {_listing(managed)}"
    question += ", deleting every app's sign-ins and your settings?" if args.purge else "? Sign-ins and settings are kept."
    if not ui.confirm(question, default=not args.purge):
        raise ui.Abort("cancelled")
    ui.log("Removing NonSteamApps")
    steam_remove(paths, managed, "all", args.restart_steam)
    for app in apps.APPS:
        _remove_from_desktop(paths, app)
    if args.purge:
        for app in managed:
            _purge(paths, app)
    if not args.keep_apps:
        _close_ports(record, managed)
        _uninstall_flatpaks(flatpak, record, managed)
    if paths.nx2.exists():
        _nx2(paths, flatpak).remove()
    timer.remove(paths)
    shutil.rmtree(paths.state, ignore_errors=True)
    _unlink_kyty_homes(paths)
    if args.purge:
        shutil.rmtree(paths.config, ignore_errors=True)
        shutil.rmtree(paths.program)
        ui.ok("Removed NonSteamApps")
        return 0
    for child in paths.program.iterdir():
        if child == paths.profiles:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    kept = f", {paths.profiles}" if paths.profiles.exists() else ""
    if not any(paths.program.iterdir()):
        paths.program.rmdir()
    ui.ok(f"Removed NonSteamApps; sign-ins stay in ~/.var/app{kept} and settings in {paths.config}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=config.NAME,
        description="Install apps from Flathub, or in NonSteamApps' own Helium, and add them to the Steam library "
                    "with separate sign-ins per Steam account.",
        epilog=f"Apps: {', '.join(apps.ids())}. Steam starts each one with: {config.NAME} launch APP [--steam-account ID] [-- ARGS]",
    )
    parser.add_argument("--version", action="version", version=f"{config.NAME} {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.required = True

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("-y", "--yes", action="store_true", help="answer yes to every question")
        sub.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors")

    def restart(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--no-restart-steam", dest="restart_steam", action="store_false",
                         help="leave Steam closed after changing its library")

    sub = commands.add_parser("install", help="install apps, or set them up again, and add them to Steam (default: every app)")
    sub.add_argument("apps", nargs="*", metavar="APP")
    sub.add_argument("--steam-user", default="all", help="Steam accounts that get shortcuts: all (default), auto or an account ID")
    sub.add_argument("--no-steam", dest="steam", action="store_false", help="do not change the Steam library")
    sub.add_argument("--no-auto-update", dest="auto_update", action="store_false", help="do not install the weekly update timer")
    sub.add_argument("--helium-archive", metavar="FILE", help="install Helium from a release archive (its .asc signature beside it)")
    sub.add_argument("--kytyps5-archive", metavar="FILE",
                     help="install KytyPS5 from a Linux build archive, named as its releases name them (KytyPS5-DATE-COMMIT-Linux-x86_64.tar.gz)")
    sub.add_argument("--eden-nx2-commit", metavar="COMMIT",
                     help="build Eden-NX2 from this commit of its source, all 40 characters, rather than its branch's newest")
    sub.add_argument("--skip-verify", action="store_true",
                     help="install Helium without checking its signature, or KytyPS5 without checking it against GitHub (not recommended)")
    restart(sub)
    common(sub)
    sub.set_defaults(func=cmd_install)

    sub = commands.add_parser("remove", help="remove apps from Steam and uninstall the ones NonSteamApps installed")
    sub.add_argument("apps", nargs="+", metavar="APP")
    sub.add_argument("--purge", action="store_true", help="also delete the apps' data for every Steam account")
    sub.add_argument("--keep-app", action="store_true", help="only remove the Steam shortcut; keep the app installed")
    restart(sub)
    common(sub)
    sub.set_defaults(func=cmd_remove)

    sub = commands.add_parser("list", help="show every app and whether it is installed")
    sub.set_defaults(func=cmd_list)

    sub = commands.add_parser("update", help="update NonSteamApps and the apps it installed, keeping your apps and their settings")
    sub.add_argument("--apps-only", action="store_true",
                     help="update only the apps and Helium, as the weekly timer does; KytyPS5 and Eden-NX2 stay as they are")
    restart(sub)
    common(sub)
    sub.set_defaults(func=cmd_update)

    sub = commands.add_parser("rollback", help="switch Helium, KytyPS5 or Eden-NX2 back to the version installed before")
    sub.add_argument("app", nargs="?", choices=("helium", "kytyps5", "edennx2"), default="helium")
    common(sub)
    sub.set_defaults(func=cmd_rollback)

    sub = commands.add_parser("steam", help="add, remove or show Steam shortcuts (default: every app in use)")
    sub.add_argument("action", choices=("add", "remove", "status"))
    sub.add_argument("apps", nargs="*", metavar="APP")
    sub.add_argument("--user", help="all (default), auto (the most recent sign-in) or an account ID")
    restart(sub)
    common(sub)
    sub.set_defaults(func=cmd_steam)

    sub = commands.add_parser("doctor", help="show diagnostics for troubleshooting")
    sub.set_defaults(func=cmd_doctor)

    sub = commands.add_parser("uninstall", help="remove NonSteamApps, its shortcuts and the apps it installed")
    sub.add_argument("--purge", action="store_true", help="also delete every app's data and your settings")
    sub.add_argument("--keep-apps", action="store_true", help="keep the apps installed")
    restart(sub)
    common(sub)
    sub.set_defaults(func=cmd_uninstall)

    sub = commands.add_parser("launch", help="start an app (what Steam runs)")
    sub.add_argument("app", metavar="APP")
    return parser


def main(argv: Optional[Sequence[str]] = None, paths: Optional[Paths] = None, flatpak: Optional[Flatpak] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = paths or Paths.detect()
    flatpak = flatpak or Flatpak()
    try:
        if argv and argv[0] == "launch":
            return cmd_launch(argv[1:], paths, flatpak)
        args = build_parser().parse_args(argv)
        ui.quiet = getattr(args, "quiet", False)
        ui.assume_yes = getattr(args, "yes", False)
        return args.func(args, paths, flatpak)
    except ui.Abort as exc:
        ui.error(str(exc))
    except (steam.SteamError, FlatpakError, HeliumError, kyty.KytyError, nx2.NX2Error, OSError) as exc:
        ui.error(str(exc))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    return EXIT_ERROR
