# ADR 0001: Become a Steam integration installer for several apps

- **Status:** accepted, 30 October 2026; amended the same day with the owner's answers (see [Amendment](#amendment-30-october-2026)), which supersede the points they name
- **Covers:** how apps are delivered, the shared Steam integration layer and YouTube's engine
- **Related:** [Maximum Game Resolution plan](../plans/steam-native-resolution.md)

## Context

SteamOS YT installs one app, YouTube's TV interface in a Helium kiosk. It integrates it with Steam: a shortcut for every account, artwork, a launch option that identifies the Steam account, separate sign-ins per account and the overlay switched off. Much of the code, however, serves YouTube itself rather than Steam: the Cobalt identity, ad removal, SponsorBlock, DeArrow, Return YouTube Dislike and the site lock.

The goal is now an installation script that handles Steam integration for several apps, starting with YouTube, Element (Matrix) and Jellyfin. SteamOS shapes the answer in three ways:

- The root filesystem is read-only. Valve warns that anything installed outside Flatpak, for example with pacman, may be wiped by the next update [1].
- Game Mode is a Gamescope session, not a desktop. There is one fullscreen app at a time, controllers go through Steam Input, and desktop services such as a keyring cannot be assumed.
- Several Steam accounts can share a device, and each should keep its own sign-ins.

## Decision drivers

1. Maintain the integration, not the apps.
2. Survive SteamOS updates without root access.
3. Offer the best TV and controller experience each app has.
4. Keep data separate per Steam account.
5. Keep sandboxing and get browser-engine security fixes promptly.
6. Stay testable without a Steam Deck.

## What the candidate apps offer

| | YouTube: VacuumTube 2.0.1 [2] | Element Desktop 1.12 [3] | Jellyfin Desktop 2.0 [4] |
| --- | --- | --- | --- |
| Engine | Electron 44 | Electron | Qt 6 WebEngine with libmpv |
| Flathub | `rocks.shy.VacuumTube`, the install its author recommends | `im.riot.Riot`, a community repackaging of Element's own tarball | `org.jellyfin.JellyfinDesktop`, linked from the project's README |
| Other Linux builds | AppImage, deb, tarball | deb, tarball | nightly AppImage |
| TV and controller | YouTube's TV interface; controller and touch support; casting from the YouTube phone app (DIAL) | Desktop interface; touch, or Steam Input acting as mouse and keyboard | TV layout, chosen automatically when the Flatpak runs on SteamOS; SDL controller input |
| Per-account switch | `--portable <dir>` | `--profile <name>` or `--profile-dir <dir>` | `--profile <name>` |
| Game Mode behaviour | Detects Game Mode, forces fullscreen and adds `--no-sandbox` | Keeps secrets in a keyring. Without one, it asks to fall back to `basic_text`, which encrypts with a fixed key | Plays more formats without server transcoding, which is the reason to prefer it to the web client |
| Updates under Flatpak | Flathub; its own updater stands down | Flathub | Flathub; last release December 2025 |

## Options considered

1. **Helium for everything.** One engine, and the site lock and per-account profiles already exist. However, YouTube's TV quirks would remain ours to chase. Jellyfin's web client also leaves more transcoding to the server, and Element's web client cannot search encrypted rooms.
2. **Upstream clients from Flathub, with Helium for web-only apps.** Chosen.
3. **Our own Electron wrappers.** Full control, but every wrapper bundles a Chromium we would have to patch, and it repeats work that upstreams already do. Rejected.
4. **Self-managed AppImages or tarballs for every app.** Works without Flatpak, but makes us responsible for updates, signature checks and rollback for each app. Used only where no Flatpak exists, as with Helium today.
5. **A Decky Loader plugin instead of an installer.** It gets live access to Steam's client API, for collections and resolution, without restarting Steam. However, it depends on a third-party loader that Steam updates can break. It may become an optional companion later; it is not the core.
6. **Building on an existing integrator.** Steam ROM Manager [6] is a desktop app that adds emulated games and other launchers' libraries to Steam. NonSteamLaunchers [5] installs game launchers and browser kiosk shortcuts, YouTube's TV interface among them. Neither separates sign-ins per Steam account or carries per-app Game Mode fixes. We follow their file conventions and never touch entries they own.

## Decision

1. **Scope.** The project becomes a Steam integration installer for living-room apps on SteamOS. YouTube is the first app, not the product.
2. **Shape.** The project has a core, one declarative recipe per app, and interchangeable install backends:
   - The **core** owns everything to do with Steam: shortcuts for every account, artwork, launch options carrying the Steam account, the overlay, Steam Input, Maximum Game Resolution, updates, `doctor` and uninstall.
   - A **recipe** says what to install and how to launch it, including the app's per-account switch and its Game Mode fixes.
   - There are three **backends**:
     - `flatpak` is the default: Flathub, installed per user, with no root access needed;
     - `webapp` is today's Helium kiosk, generalised;
     - `archive` covers signed upstream archives, only where no Flatpak exists.
3. **Choosing a client.** Prefer the upstream-maintained client on Flathub when it does something a browser kiosk cannot: wider codec support, platform features or a maintained TV interface. Otherwise, use `webapp`. Never install with pacman, and never write our own Electron wrapper.
4. **Electron.** The toolkit is not the criterion; upstream maintenance and capability are. An Electron app is acceptable when it is the upstream's own client (Element) or a maintained, purpose-built one (VacuumTube). Each recipe documents the app's security trade-offs.
5. **YouTube.** VacuumTube becomes the default YouTube engine. Today's Helium engine stays as an opt-in `youtube-helium` recipe for one minor release after the switch. After that, its YouTube-specific code is removed unless hardware testing shows a gap that matters. Helium stays as the `webapp` engine.
6. **Stable identity.** The YouTube shortcut keeps its executable path and name when the engine changes. Steam derives the app ID from these two, and play time, artwork, controller layout and resolution are all stored against that ID.
7. **Accounts.** Every recipe keeps data per Steam account through the app's own switch. Today's rule still applies: the first launch inherits any existing shared data.

## Why VacuumTube for YouTube

| | Helium and companion extension (today) | VacuumTube |
| --- | --- | --- |
| Who tracks changes to YouTube's TV interface | This project alone | An active upstream with outside contributors (2.0.1, October 2026) |
| Ads, SponsorBlock, DeArrow, dislike counts | Yes | Yes |
| Further features | None | Casting from the phone app, hiding Shorts, a codec filter, uncapped resolution, settings inside YouTube's interface, userstyles, touch |
| Separate sign-ins per Steam account | Built in | `--portable <dir>`, passed by our launcher |
| Site lock | Yes | No. Sign-in uses a code entered on a phone or computer, so the app has little reason to leave YouTube |
| Sandboxing | Chromium sandbox on; extension code in isolated worlds | Context isolation and the renderer sandbox off; the Chromium sandbox also off in Game Mode. The Flatpak sandbox still confines it: no home-folder access, but all devices and the network |
| Browser-engine security fixes | Helium follows Chromium releases | Arrive when VacuumTube ships a release with a newer Electron |
| Updates | Our signed-update timer | Flathub |

VacuumTube wins on what matters most for this project: it moves the most fragile, fastest-changing work upstream and adds features we would never build. What it gives up is defence in depth. The opt-in `youtube-helium` recipe keeps that available during the overlap. Making the sandbox work in Game Mode is a good first upstream contribution.

## Recipes

Recipes are TOML files, read with `tomllib`. This raises the Python baseline from 3.8 to 3.11, so check the version shipped with SteamOS stable first; if it is older, use JSON with the same fields. `{account}` is the Steam account ID, and `{app_home}` is the app's own folder (for a Flatpak, `~/.var/app/<id>`).

```toml
id = "youtube"
name = "YouTube"

[install]
backend = "flatpak"
app = "rocks.shy.VacuumTube"

[launch]
args = ["--fullscreen"]
account_args = ["--portable={app_home}/config/VacuumTube-steam-{account}"]

[steam]
overlay = false
input = "gamepad"
resolution = "native"
artwork = "artwork/youtube"
```

The other two recipes differ only in their fields:

| Recipe | `install` | `launch.args` | `launch.account_args` | `steam.input` |
| --- | --- | --- | --- | --- |
| `jellyfin` | `flatpak`, `org.jellyfin.JellyfinDesktop` | `--tv`, `--fullscreen` | `--profile=steam-{account}` | `gamepad` |
| `element` | `flatpak`, `im.riot.Riot` | `--password-store=basic` | `--profile=steam-{account}` | `mouse` |
| `youtube-helium` | `webapp`, `https://www.youtube.com/tv`, with today's site list and extension | today's flags | today's profiles | `gamepad` |

Steam runs the core's launcher, never the app directly: `<launcher> launch <recipe> --steam-account <id>`. The launcher picks the account's data folder, lets the first launch inherit shared data, applies the recipe's fixes, and then replaces itself with the app, for example `flatpak run rocks.shy.VacuumTube …`.

`steam.input` becomes `UseSteamControllerConfig` in `localconfig.vdf`, and, when a template is named, an entry in `configset_controller_<type>.vdf`, as Steam ROM Manager writes them [6]. The template file names still need to be confirmed on a Deck.

## Consequences

- **Gains.** The YouTube-specific extension modules, Cobalt identity and their smoke tests stop being ours, which is most of the code that breaks when YouTube changes. New apps cost a recipe rather than a fork. Updates come from Flathub, and Flatpak can roll back with `flatpak update --commit=<commit>`.
- **Costs.** We inherit each upstream's bugs, release pace and security posture. Element arrives through a community Flatpak. Switching YouTube's engine means signing in again once per account. Flatpak runtimes use disk space: Electron, Qt WebEngine and Freedesktop bases.
- **Testing.** Helium smoke tests remain for `webapp`. Unit tests drive a fake `flatpak` command to check arguments, per-account folders and data inheritance. Each app gets a short Game Mode checklist on real hardware: controller, exit, sleep and resume, sign-in persistence, keyring and resolution.

## Migration

Superseded by the amendment: phases 1–3, 5 and 6 shipped together as NonSteamApps 2.0.0, and phase 4 remains.

| Phase | Work | Done when |
| --- | --- | --- |
| 1. Core | Recipe loader; today's YouTube moves into a `youtube-helium` recipe; `install`, `remove` and `list` per app | No visible change; every existing test and the smoke test pass |
| 2. Flatpak | Per-user Flathub remote; install, update, remove and rollback; launch with per-account folders and data inheritance | Fake-`flatpak` tests pass; `doctor` reports each app's version |
| 3. Apps | Opt-in `youtube` (VacuumTube), `jellyfin` and `element` recipes, with artwork | Each passes its Game Mode checklist on a Steam Deck |
| 4. Steam settings | Steam Input per recipe; Maximum Game Resolution per [the plan](../plans/steam-native-resolution.md) | Settings appear for every account and are removed on uninstall |
| 5. Switch | `youtube` becomes the default; existing installs keep the same shortcut and sign in again | No regression from the checklist; users told in the README and install summary |
| 6. Clean-up | Remove the YouTube-specific Helium code one minor release later; decide the project's name | Only the `webapp` engine remains in Helium |

## Amendment (30 October 2026)

The owner answered the open questions. Where these answers differ from the text above, they take precedence.

1. **Name.** The project is **NonSteamApps**: the command is `nonsteamapps`, and it installs into `~/.local/share/nonsteamapps`. The GitHub repository keeps its address until it is renamed. No shim stays at SteamOS YT's old path. Instead, the installer takes over the old YouTube shortcut in place and keeps its app ID, which meets the aim of decision 6 without leaving old files behind.
2. **YouTube.** VacuumTube replaces the Helium engine straight away, with no `youtube-helium` overlap. Helium, the companion extension and the `webapp` and `archive` backends are removed. A `webapp` backend can return, from history, if a web-only app ever needs it. This supersedes decision 5 and the backends listed in decision 2.
3. **Apps.** Element and Jellyfin come next after VacuumTube. All three ship together.
4. **Element's sign-in (decided here).** Steam starts Element with `--password-store=basic --storage-mode=allow-plaintext`. With this:
   - its secrets use Electron's `basic_text` store, which encrypts with a fixed key;
   - the same profile opens in Game Mode, which has no keyring, and in Desktop Mode;
   - no consent prompt appears that a controller cannot answer.

   The cost is protection against other software running as the user. The README recommends Secure Backup and signing out lost devices. VacuumTube needs no such flag, because it keeps cookies unencrypted. Jellyfin Desktop needs none either, because its source uses no keyring at all.
5. **Artwork.** Each app ships original artwork, drawn in one family: a TV-screen emblem with an app-specific glyph and colour.
6. **Recipes.** The recipes are entries in `apps.py` rather than TOML files. This keeps the Python 3.8 baseline and needs no parser. Each entry includes the app's per-account data handling:
   - VacuumTube: `--portable` with a folder per account, created with SponsorBlock, DeArrow and dislike counts turned on, as SteamOS YT had them;
   - Element: `--profile`;
   - Jellyfin: a named profile, created before `--profile` selects it.

7. **LocalSend (added at the owner's request).** It comes from Flathub as `org.localsend.localsend_app`. It has no sign-in, so it has no per-account data: every Steam account shares its settings, and received files go to `~/Downloads`, the one folder its Flatpak may write.

8. **Helium returns as an engine (owner request).** The owner asked for Helium as a console-ready browser, and for Prime Video and HBO Max as apps running in it.
   - **Delivery:** the `archive` backend comes back for Helium alone, because Helium refuses to ship a Flatpak. Like SteamOS YT, it downloads the release from GitHub, checks it against the bundled public key with `gpgv`, keeps two versions and can roll back.
   - **Profiles:** each Helium app keeps one profile per Steam account. Before every start, NonSteamApps marks onboarding as done and the last exit as clean. It also links the profile's `WidevineCdm` to one shared folder, so Widevine downloads once.
   - **Console flags:** the apps start with spatial navigation (`--enable-spatial-navigation`, checked on Helium 0.20 to move focus with the arrow keys), and scale for the TV in Game Mode. The streaming apps also run as a kiosk.
   - **DRM:** Helium fetches Widevine through Helium's services, which are therefore on by default (`HELIUM_SERVICES`). On Linux, Widevine runs at L3, so Prime Video plays in standard definition, and HBO Max has no official Linux support.
9. **Controller layouts (part of phase 4).** Apps without controller navigation are given Valve's Web Browser layout: Element, LocalSend and the Helium apps. NonSteamApps finds the layout by its English title in `controller_base/templates` and records it in Steam's per-account `configset_<controller>.vdf`, in the format Steam ROM Manager uses. It marks those entries as its own and never touches a layout the user picked.

10. **Netflix, Disney+ and a privacy review (owner request).** Netflix and Disney+ run as Helium kiosk apps, like Prime Video and HBO Max. On Linux, Netflix limits Widevine L3 to 720p [7]; Disney+ plays, but may limit quality too [8]. A review of Helium for privacy, security, TV use and ad blocking keeps Helium's own defaults: uBlock Origin, third-party cookie blocking, WebRTC limited to the public interface, fingerprinting noise and balanced HTTPS-First mode [9]. It adds three settings, each checked on Helium 0.20.1.1:
    - new profiles send Global Privacy Control (`Sec-GPC: 1` and `navigator.globalPrivacyControl`);
    - new profiles keep crash reports off (`helium.crash_reporting.mode` set to −1 in Local State), so no upload question follows a crash;
    - every Helium app starts with `--force-dark-mode`. Helium's interface turns dark and sites see `prefers-color-scheme: dark`, while Helium's own Mode setting still takes precedence.

    The first two are written only into a new profile. Chromium drops a value that equals its default, so a later write could not tell a user's choice from no choice. Left out, with the reasons in the README: extra extensions (including Netflix 1080p unlockers), strict HTTPS-only mode, a fixed DNS-over-HTTPS provider, JavaScript without its optimiser, a site lock for the kiosk apps and changes to uBlock Origin's lists. No browser setting removes the ads that the services deliver in their ad-supported plans.

11. **Electron flags (owner request).** VacuumTube and Element are the Electron apps; Jellyfin Desktop (Qt WebEngine, playing through mpv) and LocalSend (Flutter) take no Electron flags. Both apps' Flathub wrappers already choose X11 or Wayland and add Wayland's input-method switches. That matters more since SteamOS 3.8 made Wayland the Desktop Mode default [12].
    - **VacuumTube: no flags added.** It already turns on hardware video decoding (`AcceleratedVideoDecodeLinuxGL` and its zero-copy variant). A scale factor would shrink YouTube's viewport and with it the video quality on offer. Spatial navigation would compete with YouTube TV's own focus handling. Forcing a display platform would override a wrapper that already chooses correctly. GPU blocklist and GPU-sandbox switches are unneeded on the Deck's AMD graphics and weaken security.
    - **VacuumTube's sandbox.** It adds `--no-sandbox` whenever `SteamOS=1` and `SteamGamepadUI=1` are set. Electron apps hang in Game Mode when Steam's overlay library is preloaded into Chromium's zygote [10, 11]. Inside the Flatpak, that library is out of reach, because the app cannot see the home folder, and NonSteamApps' shortcuts have the overlay off. With `GAME_MODE_SANDBOX=1`, the launcher therefore hides `SteamGamepadUI` from VacuumTube, so the sandbox stays on. Fullscreen does not change, because NonSteamApps passes `--fullscreen`. The setting stays opt-in until it is confirmed on a Steam Deck.
    - **Element: one flag.** In Game Mode on a screen 1000 pixels tall or more, it starts with `--force-device-scale-factor`, by the Helium apps' rule. The setting becomes `TV_SCALE`, and `HELIUM_SCALE` is still read. Element has no TV layout, so at Native resolution on a 4K TV its text is too small to read. Its sandbox stays on. Spatial navigation is left off, because Element's own arrow-key handling in lists and the composer would conflict with it.
    - **Element's tray.** Element minimises to the tray by default, and Electron creates the tray icon even in Game Mode, where nothing shows it. Closing the window then hides Element, and Steam still counts it as running. New per-account profiles therefore start with `minimizeToTray` off. Those profiles are only started through Steam, and Element's own profile is left alone.

12. **Signal (owner request).** Signal Desktop comes from Flathub as `org.signal.Signal`, an unofficial repackaging of Signal's own release [13]. Its launch script defaults to the plaintext key store and asks for confirmation on a first start. It decides whether to ask from `$XDG_CONFIG_HOME/Signal/config.json`. Signal keeps its data in `$XDG_CONFIG_HOME/Signal` and has no switch for another folder [14].
    - **Per-account data:** `flatpak run --env` cannot change `XDG_CONFIG_HOME`, because Flatpak applies `--env` first and then sets the XDG directories itself [15]. Each account's Signal therefore starts through `env` inside the sandbox, as `flatpak run --command=env org.signal.Signal XDG_CONFIG_HOME=<folder> SIGNAL_PASSWORD_STORE=basic signal-desktop`. Signal's own script still runs, so its sandboxing and defaults stay in place, and its question is keyed to the account's folder.
    - **Key store:** always `basic` for these profiles. A profile then opens the same way in Game Mode, which has no keyring, and in Desktop Mode, as decided for Element in item 4. Signal refuses a database whose key store has changed [14].
    - **First-start question:** the script preselects quitting, which a controller can trigger by accident. NonSteamApps creates the account's `Signal/config.json` as an empty settings object, which Signal fills on its first start, so the question is skipped. The same notice appears after installing and in the README.
    - **Console fit:** the Web Browser controller layout and the TV scale, as for Element. Signal leaves its tray off by default on Linux, so closing the window quits it.

13. **VacuumTube on a TV, and a gamepad layout (owner request, for the Steam Machine).**
    - **New per-account folders** also start with the "Continue watching?" prompt blocked, Shorts hidden, the remaining-time display on and Wayland HDR on. The remaining-time display needs VacuumTube's extended features, which are switched on with it. Wayland HDR only stops VacuumTube switching off Chromium's Wayland colour management, so it applies only where VacuumTube runs on Wayland. VacuumTube warns that it can wash out colours on some screens without HDR; each account can turn it off in VacuumTube's settings.
    - **Layout:** the YouTube shortcut gets Valve's Gamepad layout. Where Valve ships two files with one title for a controller, as for Xbox controllers, the plain joystick file is chosen.
    - **Bug fix:** reading Valve's current templates [16] showed that most of them begin with a UTF-8 byte-order mark. The text VDF reader took the mark for a stray token and skipped those files, among them the Deck's Gamepad layouts. The reader now ignores the mark. The Web Browser template has no mark, which is why it already worked.
    - **The new Steam Controller** has no template of its own in Steam's files yet, so it keeps Steam's default layout. When Valve adds one titled "Gamepad", the next install or repair picks it up.

14. **LocalSend's port (owner request).** LocalSend needs incoming TCP and UDP on port 53317 [17]. SteamOS ships firewalld [18]; when it is running, the installer offers to open the port. It does this permanently and for the current boot, in every zone in use, through `sudo firewall-cmd`. This is the one step that needs the user's password, so NonSteamApps asks before running it. If `sudo` fails, for example because the account has no password, NonSteamApps prints the exact commands instead. The record notes what NonSteamApps opened, so that removing LocalSend or uninstalling closes it again, unless the app is kept. `doctor` reports the port. Re-running the installer opens the port if it is still closed. YouTube casting is left alone: VacuumTube answers on UDP 1900 and a TCP port it picks at random, so no fixed rule fits it.

15. **ProtonDB (owner request).** ProtonDB runs full screen in Helium, like the streaming apps, with its own profile for each Steam account. It needs no Widevine. Its links to the Steam store, SteamDB and other sites open in new tabs, which a kiosk does not show. Valve's Web Browser layout maps the Deck's Menu button to Ctrl+W, which closes such a tab and returns to ProtonDB, and L1 and R1 go back and forward [16]. A full browser window was not needed for this.

16. **Launch environment (bug fix).** SteamOS YT's launcher removed Steam's `LD_PRELOAD` and the Steam Runtime's paths before starting Helium. When Helium returned in item 8, the new launcher did not, and the Helium apps then hung in Game Mode: Steam's loading screen stayed up, and Exit game had no effect. Steam preloads its overlay library into every game it starts, and with it loaded Chromium's sandboxed zygote crashes [11]. Shortcuts with the overlay off still get it. The Flatpak apps were spared, because the library is outside their sandbox. Before every launch, NonSteamApps now removes the overlay library from `LD_PRELOAD`, keeping any other preloaded library. It also restores `LD_LIBRARY_PATH` and `PATH` from Steam's `SYSTEM_LD_LIBRARY_PATH` and `SYSTEM_PATH`. The Helium sandbox stays on.

17. **A collection for the apps (owner request).** Each Steam account gets a library collection, named by `STEAM_COLLECTION` (default "NonSteamApps"), that holds every app NonSteamApps adds.
    - **Storage:** Steam keeps collections in `userdata/<account>/config/cloudstorage`, in the namespace file that `cloud-storage-namespaces.json` marks as current. It merges them with Steam Cloud's copy by union ("union-collections"). NonSteamApps writes its own entry, `user-collections.nonsteamapps`, in the same shape as Steam ROM Manager [19], while Steam is closed, and leaves every other entry alone.
    - **Removal:** apps taken out are listed under `removed`, so that the merge does not bring them back. The collection is marked deleted once it is empty, which uninstalling causes.
    - **Accounts not set up yet:** an account whose collections file does not exist yet is reported and skipped, because creating that file could conflict with Steam's own.

18. **Launch settings, and staying with Flatpak (owner request).** A review of environment variables and launch options for each app led to the following.
    - **Jellyfin** takes the TV scale through its own `--scale-factor` option, which sets `QT_SCALE_FACTOR`.
    - **LocalSend** takes it through `GDK_SCALE`, passed with `flatpak run --env`. GTK only scales by whole numbers, so the scale is rounded down and left out below 2. `apps.TvScale` describes how each app takes its scale.
    - **Screen dimming during videos** cannot be fixed with a launch setting: Game Mode ignores the requests apps send to keep the screen on [20]. The README points to Steam's dimming and sleep timers.
    - **File picker in Game Mode:** the 2022 `XDG_CURRENT_DESKTOP=KDE` workaround is left for a test on a device first.
    - **pacman instead of Flatpak:** the owner asked whether installing with pacman would avoid most issues. It would not, because almost every issue so far comes from Game Mode, Steam or SteamOS, which treat pacman-installed apps the same way. It would also add new problems:
      - every SteamOS update removes the apps;
      - root and a writable system are needed for every install;
      - the system partition is about 5 GB [21];
      - SteamOS's frozen repositories would let Signal expire;
      - VacuumTube, LocalSend and Helium are only in the AUR;
      - Flatpak's isolation, which kept Steam's overlay library out of the Electron apps, would be lost.

      Flathub therefore stays the source, as decided above.

19. **Restarting Steam (bug fix, owner report).** After the installer restarted Steam, KDE asked to share the screen with Konsole. xdg-desktop-portal identifies an unsandboxed app by the systemd unit it runs in, `app-<ID>-<random>.scope` [22][23], and a program started from a terminal stays in the terminal's unit. Steam, started again by the installer, ran in Konsole's unit, and its screen-capture request named Konsole [24]. The installer now starts Steam with `systemd-run --user --scope --unit=app-steam-<random>.scope --slice=app.slice`, as Plasma names the apps it starts, so the portal identifies it as Steam. When `systemd-run --user --scope true` fails, there is no user service manager to ask, and Steam is started directly, as before.

20. **VacuumTube's window, side menu and settings size (owner request).**
    - **Settings:** every VacuumTube data folder, new or existing, gets `fullscreen`, `no_window_decorations` and `disabled_tabs` (the Shorts and Podcasts tabs) once [25]. The change is recorded in the folder's `nonsteamapps.json`, so later choices in VacuumTube's settings stay. A `config.json` that is not valid JSON is left for VacuumTube, which replaces it, and is changed on a later start. VacuumTube already started full screen, because NonSteamApps passes `--fullscreen`. Its setting showed off because VacuumTube only sets it in a config file it creates itself, and NonSteamApps had created that file first.
    - **Settings menu size:** VacuumTube draws its settings menu at a fixed 1100 × 760 pixels, with 15-pixel text, which is a quarter of a 4K screen. Scaling only the menu with CSS was tested in Chromium and rejected. VacuumTube's scrolling compares on-screen positions with layout sizes, which CSS `zoom` and `scale` both pull apart, so the focused row would scroll out of view. VacuumTube is therefore scaled as a whole, with `--force-device-scale-factor`. The scale fits the 1080p layout YouTube's TV apps use (1.25× at 1440p, 2× at 4K, none at 1080p), and YouTube's interface fills the screen either way.
    - **Video resolution:** VacuumTube offers videos up to the screen size it sees, which the scale reduces: to 1080p at 4K [25]. That was why item 11 left VacuumTube unscaled. While it is scaled, NonSteamApps keeps VacuumTube's Unlock Resolution on, so a 4K TV still gets 4K. Only 8K videos may now stream above the screen's resolution.

21. **Files (owner request).** SteamOS includes KDE's Dolphin, so Files is the first app NonSteamApps neither installs nor removes. `App.system` names its command, and the installer only checks that it is there.
    - **TV profile:** Files gets its own `XDG_CONFIG_HOME` and `XDG_STATE_HOME`, in `profiles/files/shared`. Desktop Mode's config folder comes first in `XDG_CONFIG_DIRS`, so KDE reads the profile, then the desktop's settings underneath, and writes only to the profile. This was checked with KDE's own `kreadconfig5` and `kwriteconfig5`. The profile starts with `RememberOpenedTabs=false` (a fresh start at home), the menu bar hidden, and single-click opening. Bookmarks, trash and file associations live outside the config folder, or are read through the layering, so they stay shared. Apps opened from Files inherit the profile.
    - **Start:** `dolphin --new-window`, because a plain start hands its folders to any Dolphin already running, without the profile, and exits [26]. In Game Mode, Dolphin runs on X11 (`QT_QPA_PLATFORM=xcb`), as the Helium apps do. `QT_QPA_PLATFORMTHEME=kde` keeps KDE's style, colours and icons where `XDG_CURRENT_DESKTOP` is `gamescope`, and `QT_SCALE_FACTOR` carries the TV scale. gamescope resizes any resizable window Steam started to fill the screen, so no window size is needed [27].
    - **Controller layout:** none of Valve's layouts suits a file manager.
      - Web Browser's A sends Enter and Space together, and Space toggles Dolphin's selection mode, so every press would also toggle selection mode. Its Y also types S, which jumps to a file [26].
      - Keyboard (WASD) and Mouse sends Space on A. Mouse Only has no arrow keys.
      - Dolphin's shortcuts cannot be changed for the profile alone: KDE reads a `[Shortcuts]` group only for apps without an XML GUI file, and Dolphin has one, which lives in the shared data folder [28].
      - NonSteamApps therefore writes its first layout of its own, "Files (NonSteamApps)". It is Valve's Web Browser layout for the Deck, read from the device, with A sending only Enter, Y only going forward, and the left stick moving the selection. It is written for every controller type Valve ships a Gamepad layout for, keeping only that controller's inputs; Valve has a Web Browser layout only for the Deck. The files go into `controller_base/templates`, where RetroDECK and EmuDeck's community guide also add layouts [29, 30], and are assigned like Valve's. `nonsteamapps update` writes them again if a Steam update removes them, and they are deleted once no account has Files.
    - **Needs a device:** whether Steam lists and applies the layouts, and Dolphin's look and scale in Game Mode.

22. **Prism Launcher (owner request).** Prism Launcher plays Minecraft: Java Edition, and comes from Flathub as `org.prismlauncher.PrismLauncher`.
    - **Data:** each Steam account gets its own data folder through Prism's `--dir`, so each has its own instances, worlds and Microsoft sign-in [31]. Minecraft's downloads are large and checked by hash, so each account's `assets`, `libraries` and `java` folders are links to Prism's own data folder, and they are downloaded once. `FolderProfile.links` makes these links, relative so that they work the same inside the sandbox.
    - **Settings for a new folder** (`prismlauncher.cfg`, an INI file Prism reads with QSettings):
      - the dark theme, with icons drawn for it. A valid theme also skips the first-run wizard's theme page;
      - `CloseAfterLaunch`: the launcher closes when Minecraft opens;
      - `QuitAfterGameStop`: the launcher quits when Minecraft exits, back to Steam. Prism adds this step after a successful game run only, so a crash leaves it open with the log;
      - `LaunchMaximized`.

      Flathub builds Prism with its Java downloader [32], and a new folder has automatic Java on, so the wizard asks only for a language and the Microsoft sign-in, which no setting can skip. Prism's migration from PolyMC or MultiMC is offered only when no settings file exists, so it is not offered here [31].
    - **TV:** the TV scale through `QT_SCALE_FACTOR`, passed with `flatpak run --env`. Minecraft's own GUI Scale sizes the game.
    - **Controller:** Minecraft: Java Edition has no controller support of its own, so it is played through the keyboard and mouse. Valve's Keyboard (WASD) and Mouse layout already matches Minecraft's default keys: W, A, S and D to move, Space to jump, E for the inventory, F to swap hands, the mouse buttons to attack and use, and the wheel for the hotbar. Valve ships it for the Deck only, so `layouts` generalises to more than one layout of NonSteamApps' own, and a "Minecraft (NonSteamApps)" layout is made from it for every controller type, as for Files (item 21). The changes from Valve's layout are:
      - X drops the held item (Q), where Valve's presses R, which Minecraft does not use;
      - Menu pauses (Escape) and View shows the player list (Tab), Valve's the other way round;
      - the left stick click sprints (Ctrl) and the right stick click sneaks (Shift), where Valve's left click sneaks and right click is a mouse click;
      - the left bumper steps left along the hotbar and the right bumper right.

      A controller mod such as Controlify gives native controller menus; the README explains how to use it with Steam's Gamepad layout.
    - **Needs a device:** whether Steam lists and applies the layout, the launcher's look and scale, and the launch and quit flow in Game Mode.

23. **Proton Calendar, and Mullvad VPN (owner request).**
    - **Proton Calendar** runs full screen in Helium, like ProtonDB, at `https://calendar.proton.me/`, with Steam's Web Browser layout and a Helium profile for each Steam account. Links to Proton's other apps open in new tabs, which Menu (Ctrl+W) closes. NonSteamApps' Helium profiles refuse notification requests, so its reminders do not pop up.
    - **Mullvad VPN cannot come from Flathub.** Flathub has Mullvad Browser (`net.mullvad.MullvadBrowser`) but no Mullvad VPN app, because the app depends on a system daemon, which Flatpak cannot run [33]. Mullvad publishes it as `.deb` and `.rpm` packages only. The ways open on SteamOS are:
      - WireGuard through SteamOS's own NetworkManager, with Mullvad's configuration files;
      - Mullvad's own app, installed outside the read-only system with its daemon as a system service;
      - pacman, which item 18 ruled out.

      The owner chose to skip Mullvad VPN.

24. **Steam Play settings (owner request).** The owner asked for the best Steam Play compatibility tool for each app: none, Proton Experimental or another. For every app it is none.
    - **Why:** every app is a native Linux program, started by NonSteamApps' launcher. That covers the Flathub apps, Helium and its sites, SteamOS's Dolphin, and Prism Launcher, whose Minecraft is Java. Proton, in any version, runs the launcher as a Windows program, which fails. The Steam Linux Runtime runs it in a container that hides Flatpak, the user's Helium and SteamOS's own apps. Each would stop the app starting.
    - **How Steam stores it:** a tool forced on a non-Steam shortcut is kept in the install's `config/config.vdf`, under `InstallConfigStore/Software/Valve/Steam/CompatToolMapping` and the shortcut's 32-bit app ID. A shortcut without an entry, or with one that names no tool, runs natively [34]. Guides apply Proton to non-Steam games through this per-shortcut setting [35].
    - **What NonSteamApps does:** `compat` removes any forced tool from NonSteamApps' shortcuts, as Steam ROM Manager's "none" does. It runs on `steam add`, so on every install and repair, while Steam is closed, and says which app it reset. It keeps a backup, and writes nothing when nothing needs to change; the file round-trips byte for byte. Removing an app drops its entries once no account has its shortcut, because Steam never prunes them. `doctor` reports a forced tool.

25. **New apps on a repeat install (bug fix, owner report; replaced by item 26 in 2.16.0).** After updating, the owner did not see Proton Calendar or Prism Launcher. Run again without app names, the installer repaired only the apps already installed, so apps added in later versions never reached an existing install: Files, Prism Launcher and Proton Calendar.
    - **Fix:** the record now keeps `offered`, the apps that existed at each install, whether the user took them or not. A repeat install without names finds the apps never offered, asks once whether to add them (`--yes` accepts), and prints the command to add them later if declined. An app the user removed stays offered, so it does not come back.
    - **Older records:** a record from before has no `offered` list, so each app it does not manage counts as new, once.

26. **Install and update (owner decision).** The owner set the rule: running install installs and overwrites everything, and running update keeps the existing state. Asked where the line falls, the owner chose that install also puts back each app's TV settings, and that only a manual update fetches NonSteamApps itself.
    - **Install:** without names, every app, so an app added in a later version, or one the user removed, is installed; item 25's offer and its `offered` list are gone. Each shortcut's name, launch options, icon and artwork, and its controller layout, become NonSteamApps' again. The apps join the collection, and a forced Steam Play tool is cleared. Each app's TV settings are put back into the data it already has: the settings files of VacuumTube, Element, Prism Launcher and ProtonUp-Qt, Files' Dolphin profile, and the first-run preferences of the Helium profiles. Settings files are merged, so only NonSteamApps' keys change. Sign-ins, app data and `nonsteamapps.conf` are kept. It asks first, because it can bring a removed app back and undo the user's changes.
    - **Update:** keeps which apps are installed and how they are set up. `nonsteamapps update` first updates NonSteamApps itself. The installer records its source, the archive it downloaded or the clone it ran from; update fetches that again, runs its `install.sh` with `NONSTEAMAPPS_COPY_ONLY=1` to copy only the program, so the new version lays out its own files, and hands over to the new launcher. The new version updates the apps and Helium, then refreshes only the shortcuts already there. A name, launch options, icon, overlay choice, artwork or controller layout the user changed stays, and NonSteamApps' own artwork is renewed. To tell its artwork from the user's, NonSteamApps records a SHA-256 of each file it writes into `grid`, as `install_defaults` does for `nonsteamapps.conf`. Steam is closed only when a shortcut must change; the collection and Steam Play tools are left as they are.
    - **Weekly timer:** it runs `update --apps-only`, so no new NonSteamApps code runs unattended and Steam is never closed under the user. Without a terminal, the question to close Steam now counts as no unless `--yes` is given, so even an older timer cannot close Steam.

27. **ProtonUp-Qt and Protontricks (owner request).**
    - **ProtonUp-Qt** (`net.davidotek.pupgui2`, Qt 6 through PySide6 [36][37]) installs compatibility tools such as GE-Proton into Steam's `compatibilitytools.d`. It has no flags of its own. NonSteamApps sets its Steam Deck theme (`[pupgui2] theme=steam` in its `config.ini`), and scales it with `QT_SCALE_FACTOR` [41]: its window is 440×360, so 1.5× at 1080p and 3× at 4K. In Game Mode it uses X11 (`QT_QPA_PLATFORM=xcb`), as gamescope runs apps on Xwayland. Its own gamepad support reads `/dev/input` directly and sends Tab, Space and Enter. With Steam Input sending keys too, a press would act twice, so `PUPGUI2_DISABLE_GAMEPAD=1` turns it off and the Tools layout drives it. Steam lists a new tool once it restarts, and Steam overwrites the per-game choices made in ProtonUp-Qt's game list while it runs, so the README points to a game's Properties.
    - **Protontricks** (`com.github.Matoking.protontricks` [38][39]) starts with `--no-term --gui`: its game picker, then Winetricks for the chosen game. `--no-term` shows errors in a dialog, as there is no terminal. Its Flatpak bundles YAD, which is GTK 3: `GDK_SCALE` takes whole numbers only, so at 1080p `GDK_DPI_SCALE` scales the text 1.5×, and at 4K the window is scaled 3× [40]. It has no controller support, hence the Tools layout. The launcher also drops `STEAM_COMPAT_DATA_PATH`, with which Protontricks would change that prefix whatever game is picked.
    - **Steam libraries:** both Flatpaks reach only Steam's default folders, so a library on an SD card stays hidden until the user runs `flatpak override` [39]. Each start therefore passes `--filesystem` for every folder in Steam's `libraryfolders.vdf`, for that run only, and nothing in the user's Flatpak settings changes.
    - **Tools layout:** made from Web Browser. The D-pad moves up and down a list and steps between controls with Shift+Tab and Tab. A presses Space (select, tick), Y presses Enter (OK) and B presses Escape (cancel). Valve's A presses Enter and Space together, which in a checklist would tick an item and close its dialog.
    - **Steam Play:** both are native Linux apps that manage Proton for games, so, like every app, their shortcuts run with no tool (item 24).

Still open: Maximum Game Resolution (the rest of migration phase 4).

## Sources

1. [Steam Support: Steam Deck Desktop FAQ](https://help.steampowered.com/faqs/view/671A-4453-E8D2-323C)
2. VacuumTube: [repository and README](https://github.com/shy1132/VacuumTube); `src/index.js` for Game Mode detection, `--no-sandbox` and window preferences; [Flathub manifest](https://github.com/flathub/rocks.shy.VacuumTube) for permissions; [GamingOnLinux on VacuumTube for Steam Deck](https://www.gamingonlinux.com/2025/06/vacuumtube-is-the-best-way-to-watch-youtube-on-steam-deck-steamos/)
3. Element Desktop, now in [element-web under `apps/desktop`](https://github.com/element-hq/element-web): `src/args.ts` for `--profile`, `--profile-dir` and `--storage-mode`, and `src/store.ts` for the keyring fallback; [Flathub `im.riot.Riot`](https://github.com/flathub/im.riot.Riot)
4. [Jellyfin Desktop](https://github.com/jellyfin/jellyfin-desktop): `src/main.cpp` for its options and `src/system/SystemComponent.cpp` for SteamOS detection; [Flathub](https://flathub.org/apps/org.jellyfin.JellyfinDesktop); [AlternativeTo on the 2.0 release](https://alternativeto.net/news/2025/12/jellyfin-desktop-2-0-launches-with-rebranding-qt-6-upgrade-and-fresh-features)
5. [NonSteamLaunchers](https://github.com/moraroy/NonSteamLaunchers-On-Steam-Deck)
6. [Steam ROM Manager](https://github.com/SteamGridDB/steam-rom-manager), `src/lib/controller-manager.ts`
7. [Linux Uprising: how to stream Netflix videos at 1080p](https://www.linuxuprising.com/2018/07/how-to-stream-netflix-videos-at-1080p.html), on the 720p limit for browsers with software Widevine
8. [Phoronix: Disney+ not working on Linux](https://www.phoronix.com/news/Disney-Plus-Not-On-Linux), and [Slashdot: Linux users can now use Disney+ after a DRM fix](https://linux.slashdot.org/story/19/12/08/169213/linux-users-can-now-use-disney-after-drm-fix)
9. [Helium](https://github.com/imputnet/helium) patches: `patches/helium/core/prefer-https-by-default.patch`, `patches/helium/core/crash-reporting-prefs.patch` and `patches/helium/core/noise/`
10. [Steam Community: an Electron app hangs in Game Mode without `--no-sandbox`](https://steamcommunity.com/app/1675200/discussions/1/4826187053916237100)
11. [anthrodeck pull request 11: Steam's overlay, preloaded into Chromium's zygote, stops Electron starting](https://github.com/keaton4422/anthrodeck/pull/11)
12. [SteamOS 3.8 release coverage: Wayland by default in Desktop Mode](https://www.inkl.com/news/valves-latest-steamos-is-out-with-initial-support-for-upcoming-steam-machine-hardware)
13. [Flathub `org.signal.Signal`](https://github.com/flathub/org.signal.Signal): `signal-desktop.sh` and the README
14. [Signal Desktop](https://github.com/signalapp/Signal-Desktop): `app/user_config.main.ts` for the data folder, `app/main.main.ts` for `getSQLKey` and key-store changes, and `ts/types/Settings.std.ts` for the tray default
15. [Flatpak](https://github.com/flatpak/flatpak): `common/flatpak-run.c`, which applies `--env` first, and `common/flatpak-context.c` (`flatpak_context_apply_env_appid`)
16. [SteamTracking](https://github.com/SteamDatabase/SteamTracking): `ClientExtracted/controller_base/templates`, the Steam client's controller layouts, as of 29 October 2026
17. [LocalSend README](https://github.com/localsend/localsend#setup), "Setup": incoming TCP and UDP on 53317, and the `firewall-cmd` commands
18. [Steam Community: "Please include a firewall"](https://steamcommunity.com/app/1675200/discussions/2/3416557114749187579/), on firewalld arriving with SteamOS 3.5
19. [Steam ROM Manager](https://github.com/SteamGridDB/steam-rom-manager): `src/lib/category-manager.ts`, which writes collections to Steam's cloud storage file
20. [decky-insomnia](https://zff.dev/kartikynwa/decky-insomnia), on Game Mode ignoring apps' requests to keep the screen on
21. [Robert Kirkman's SteamOS pacman guide](https://gist.github.com/robertkirkman/753922262259486ec417e5ff8b5b924b), on the 5 GB system partition and SteamOS's repositories
22. [xdg-desktop-portal 1.20.3](https://github.com/flatpak/xdg-desktop-portal/blob/1.20.3/src/xdp-app-info-host.c): `src/xdp-app-info-host.c`, which reads an unsandboxed app's ID from its systemd unit's name
23. [systemd: Desktop Environments](https://systemd.io/DESKTOP_ENVIRONMENTS/), on how desktops name the units of the apps they start
24. [KDE bug 500891](https://bugs.kde.org/show_bug.cgi?id=500891): the screen-sharing dialog names Konsole for an app started from Konsole
25. [VacuumTube](https://github.com/shy1132/VacuumTube) 2.0.1: `src/config.js` and `src/index.js` for its settings, `src/preload/modules/guide-tabs.js`, `src/preload/modules/h5vcc/index.js` for the resolution limit, and `src/preload/modules/settings/` for the settings menu's size and scrolling
26. [Dolphin](https://invent.kde.org/system/dolphin): `src/main.cpp` for `--new-window`, `src/dolphinmainwindow.cpp` for Space toggling selection mode, `src/dolphintabwidget.cpp` for the last tab closing Dolphin, and `src/kitemviews/kitemlistcontroller.cpp` for type-ahead search
27. [gamescope](https://github.com/ValveSoftware/gamescope): `src/steamcompmgr.cpp`, which sizes windows to the screen unless their minimum and maximum sizes match
28. [KXmlGui](https://invent.kde.org/frameworks/kxmlgui): `src/kxmlguifactory.cpp`, which reads the `[Shortcuts]` group only for clients without an XML file, and `src/kxmlguiversionhandler.cpp`
29. [RetroDECK: Steam Input](https://retrodeck.readthedocs.io/en/latest/wiki_development/general/steam-input/), on installing its layouts into `controller_base/templates`
30. [EmuDeck: community creations](https://emudeck.github.io/community-creations/steamos/community-creations), whose guide adds layouts to the same folder
31. [Prism Launcher](https://github.com/PrismLauncher/PrismLauncher): `launcher/Application.cpp` for `--dir`, its settings, the first-run wizard and data migration; `launcher/launch/LaunchTask.cpp` and `launcher/minecraft/MinecraftInstance.cpp` for quitting after the game
32. [Flathub `org.prismlauncher.PrismLauncher`](https://github.com/flathub/org.prismlauncher.PrismLauncher): the manifest, which turns on the Java downloader
33. [Flathub forum: Mullvad VPN](https://discourse.flathub.org/t/vpn-mullvad-vpn/2594), on why the app cannot be packaged; Flathub's repositories on GitHub have `net.mullvad.MullvadBrowser` and no Mullvad VPN app
34. [Steam ROM Manager](https://github.com/SteamGridDB/steam-rom-manager): `src/lib/compat-tool-manager.ts` and `src/lib/helpers/steam/list-compat-tools.ts`, which force or clear a shortcut's tool in `config.vdf`
35. [Evetech: how to add a non-Steam game and run it with Proton](https://evezone.evetech.co.za/build-lab/how-to-add-a-non-steam-game-to-steam-and-run-it-with-proton), on forcing a tool per shortcut
36. [ProtonUp-Qt](https://github.com/DavidoTek/ProtonUp-Qt/tree/v2.16.0) 2.16.0: `pupgui2/pupgui2.py` for `PUPGUI2_DISABLE_GAMEPAD` and Qt's own arguments, `pupgui2/util.py` and `pupgui2/constants.py` for `config.ini` and its themes, `pupgui2/gamepadinputworker.py` for its gamepad keys, and its metainfo for gamepad support since 2.4.0
37. [Flathub `net.davidotek.pupgui2`](https://github.com/flathub/net.davidotek.pupgui2): the manifest, with KDE's runtime, PySide6 and its permissions
38. [Protontricks](https://github.com/Matoking/protontricks/tree/1.15.0) 1.15.0: `src/protontricks/cli/main.py` and `cli/util.py` for `--gui` and `--no-term`, `gui.py` for YAD or Zenity and its check of library permissions, and `util.py` for `STEAM_COMPAT_DATA_PATH`
39. [Flathub `com.github.Matoking.protontricks`](https://github.com/flathub/com.github.Matoking.protontricks): the manifest, which builds YAD and grants only Steam's default folders, and its README on `flatpak override` for other libraries
40. [GTK 3](https://github.com/GNOME/gtk/tree/gtk-3-24): `gdk/x11/gdkscreen-x11.c`, where `GDK_SCALE` takes a whole number, and `gdk/x11/xsettings-client.c` for `GDK_DPI_SCALE`
41. [Qt 6](https://github.com/qt/qtbase/tree/6.10): `src/gui/kernel/qhighdpiscaling.cpp` for `QT_SCALE_FACTOR`, and `src/gui/kernel/qguiapplication.cpp` for how the platform is chosen
