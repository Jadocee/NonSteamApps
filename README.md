# NonSteamApps

Living-room apps for SteamOS, added to the Steam library with original artwork. They come from Flathub, run in NonSteamApps' own copy of the Helium browser, or, for Files, are part of SteamOS, and each is set up for a TV and a controller. Each Steam account gets its own sign-ins. The apps work in Game Mode and Desktop Mode, and NonSteamApps keeps them up to date.

| In Steam | App | Source | Good to know |
| --- | --- | --- | --- |
| **YouTube** | [VacuumTube](https://github.com/shy1132/VacuumTube) | `rocks.shy.VacuumTube` | YouTube's TV interface, with controller support, ad blocking and casting from the YouTube phone app. NonSteamApps turns on SponsorBlock, DeArrow, dislike counts, the remaining-time display and HDR, hides Shorts and the Shorts and Podcasts tabs, stops the "Continue watching?" prompt, and starts it full screen without window decorations. |
| **Element** | [Element Desktop](https://element.io) | `im.riot.Riot` | Matrix chat. A desktop interface: use the touchscreen, the trackpads or a keyboard. In Game Mode, its sign-in page and links open in Helium in front of it, and the sign-in returns to Element. |
| **Signal** | [Signal Desktop](https://signal.org/download/) | `org.signal.Signal` | Private messages and calls, linked to Signal on your phone. A desktop interface, like Element. Flathub's package is an unofficial repackaging of Signal's own release. |
| **Bitwarden** | [Bitwarden](https://bitwarden.com/download/) | `com.bitwarden.desktop` | Your password vault, with one for each Steam account. Scaled for the TV, with the Tools controller layout; closing its window quits it, and in Game Mode its SSO and Duo sign-ins return to it from Helium. |
| **Jellyfin** | [Jellyfin Desktop](https://github.com/jellyfin/jellyfin-desktop) | `org.jellyfin.JellyfinDesktop` | Your Jellyfin server in its TV layout, with controller support. It plays more formats without the server converting them. |
| **LocalSend** | [LocalSend](https://localsend.org) | `org.localsend.localsend_app` | Send files to and from nearby phones and computers over your own network, with no account and no internet needed. Received files go to `~/Downloads`. It starts dark, in its OLED colours. |
| **Prism Launcher** | [Prism Launcher](https://prismlauncher.org) | `org.prismlauncher.PrismLauncher` | Minecraft: Java Edition, with instances, mods and modpacks. Scaled for the TV and dark, it steps aside while you play and quits when you leave Minecraft, and a Minecraft controller layout plays the game. |
| **ProtonUp-Qt** | [ProtonUp-Qt](https://github.com/DavidoTek/ProtonUp-Qt) | `net.davidotek.pupgui2` | Installs and updates GE-Proton and other compatibility tools for your Steam games. It starts in its dark Steam Deck theme, scaled for the TV, with a controller layout of NonSteamApps' own, and reaches every Steam library, an SD card's included. |
| **Protontricks** | [Protontricks](https://github.com/Matoking/protontricks) | `com.github.Matoking.protontricks` | Winetricks for Proton games: installs Windows components, runtimes and fonts into a game's prefix. It starts at its game picker, scaled for the TV, with the same controller layout as ProtonUp-Qt and every Steam library within reach. |
| **Files** | [Dolphin](https://apps.kde.org/dolphin/) | Part of SteamOS | Your files, SD card and USB drives in SteamOS's own file manager, started with a TV profile: scaled for the TV, one press to open, no menu bar, a fresh start at your home folder, and a controller layout of its own. |
| **Helium** | [Helium](https://helium.computer) | Signed Helium release | A private web browser with uBlock Origin built in, set up for a TV and a controller. |
| **Prime Video** | Prime Video in Helium | Helium, full screen | Amazon's streaming service, full screen with no browser interface. |
| **HBO Max** | HBO Max in Helium | Helium, full screen | Warner Bros. Discovery's streaming service, full screen with no browser interface. |
| **Netflix** | Netflix in Helium | Helium, full screen | Netflix's streaming service, full screen with no browser interface. |
| **Disney+** | Disney+ in Helium | Helium, full screen | Disney's streaming service, full screen with no browser interface. |
| **ProtonDB** | ProtonDB in Helium | Helium, full screen | Player reports on how well games run with Proton, full screen with no browser interface. |
| **Proton Calendar** | Proton Calendar in Helium | Helium, full screen | Proton's end-to-end encrypted calendar, full screen with no browser interface. Sign in with your Proton account. |

## Features

- **No root, nothing lost on updates.** Apps install into your user Flatpak installation, which SteamOS updates leave alone. An app you already installed, for example through Discover, is used as it is and never uninstalled. The one step that needs your password is opening LocalSend's port when SteamOS's firewall is on, and NonSteamApps asks first.
- **Every Steam account.** Each account on the device gets a shortcut, with artwork for the library, the capsule, the hero banner, the logo and the icon. The Steam overlay is off. The apps sit together in a **NonSteamApps** collection in the library.
- **Native, never Proton.** Every app is a native Linux app, so the best Steam Play setting for each is none. Proton is for Windows programs, and the Steam Linux Runtime's container hides Flatpak and SteamOS's own apps, so either would stop an app starting. Installing removes a compatibility tool forced on an app under **Properties → Compatibility**.
- **Separate sign-ins.** Each Steam account has its own data in every app except LocalSend, ProtonUp-Qt, Protontricks and Files, which have no sign-in, so their settings are shared (see [Several Steam accounts](#several-steam-accounts)).
- **Console-ready browser apps.** Helium, the streaming apps, ProtonDB and Proton Calendar open without first-run pages, prompts or a "Restore pages?" bubble after Steam closes them. The arrow keys move between links and buttons, the interface is dark, and in Game Mode pages are scaled for the TV (see [Helium apps](#helium-apps)).
- **Private by default.** Helium blocks ads and trackers with its built-in uBlock Origin. NonSteamApps' Helium profiles also send Global Privacy Control and keep no crash reports (see [Privacy, security and ad blocking](#privacy-security-and-ad-blocking)).
- **Sign-ins in Game Mode.** In Game Mode, Steam's own browser opens apps' links, and it cannot hand a sign-in back to an app. Element's and Bitwarden's sign-in pages and links therefore open in Helium, in front of the app, and the sign-in returns to the app.
- **Controller layouts.** YouTube gets Steam's Gamepad controller layout, and Element and Signal get its Web Browser layout. The Helium apps, Files, LocalSend, Prism Launcher, ProtonUp-Qt, Protontricks and Bitwarden get layouts of NonSteamApps' own: Browser, Files, LocalSend, Minecraft and Tools. In the Helium apps, Files and LocalSend, holding **Menu** quits. A layout you pick yourself stays until you run the installer again.
- **Install, or update.** Running the installer installs every app and sets each up afresh; `nonsteamapps update` brings NonSteamApps and your apps up to date and keeps everything as you set it (see [Install again, or update](#install-again-or-update)). A weekly timer updates the apps NonSteamApps installed, Helium included.
- **Replaces SteamOS YT.** On a device with this project's earlier YouTube kiosk, its YouTube shortcut moves to VacuumTube and keeps its place in the library (see [Moving from SteamOS YT](#moving-from-steamos-yt)).

## Requirements

- SteamOS 3, or another Linux system with Steam and Flatpak
- Python 3.8 or newer, `flatpak`, `tar` and `xz`, `gpg` to check Helium's signature, and `curl` to download the installer; all are included with SteamOS
- An internet connection. The first install of each app also downloads its Flatpak runtime or Helium, which takes a while.

## Install

In Desktop Mode, open Konsole and run:

```bash
curl -fsSL https://raw.githubusercontent.com/jadocee/steamos-yt/main/install.sh | bash
```

This installs every app in the table above. To choose, name them:

```bash
curl -fsSL https://raw.githubusercontent.com/jadocee/steamos-yt/main/install.sh | bash -s -- youtube jellyfin
```

From a clone, run `./install.sh [APP...]`. Steam must be closed while its library is changed, so the installer offers to close Steam and starts it again afterwards. It cannot do that from Game Mode.

| Option | Effect |
| --- | --- |
| `--steam-user all\|auto\|ID` | Steam accounts that get shortcuts: all (default), the most recent sign-in, or one account |
| `--no-steam` | Leave the Steam library alone |
| `--no-restart-steam` | Leave Steam closed afterwards |
| `--no-auto-update` | Do not install the weekly update timer |
| `--helium-archive FILE` | Install Helium from a downloaded release archive, with its `.asc` signature beside it |
| `--skip-verify` | Install Helium without checking its signature (not recommended) |
| `-y`, `--yes` / `-q`, `--quiet` | Answer yes to questions / print only warnings and errors |

### Install again, or update

Run the installer again to install every app afresh, or `nonsteamapps update` to bring what you have up to date as it is:

| | Installer (`nonsteamapps install`) | `nonsteamapps update` |
| --- | --- | --- |
| Apps | Every app, or the ones you name; an app you removed comes back | Only the apps you have |
| NonSteamApps itself | The installer's version | The latest, from where you installed it: GitHub, or your clone |
| Steam shortcuts | Name, launch options and icon set back to NonSteamApps' | Kept as you changed them; only shortcuts already there are refreshed |
| Artwork | NonSteamApps' | NonSteamApps' own is renewed; artwork you chose stays |
| Controller layouts | NonSteamApps' layout, over one you picked | Yours stays; NonSteamApps' is given where none is set |
| Each app's TV settings | Put back, for example VacuumTube's hidden tabs, Prism Launcher's dark theme and Files' profile | Kept as you changed them |
| Steam Play tool, collection | A forced tool is removed; the apps join the collection | Left as they are |
| Sign-ins, app data and `nonsteamapps.conf` | Kept | Kept |

Without app names, the installer asks first. Steam is closed only while its library changes; `update` leaves it running when no shortcut needs to change.

## Using the apps

Open them from the **NonSteamApps** collection or **Library → Non-Steam**, in Game Mode or in the Steam client in Desktop Mode. To quit, use the app's own exit, or press the Steam button and choose **Exit game**. In the Helium apps, Files and LocalSend, holding **Menu** for a moment quits too.

- **YouTube:** controllers work out of the box, with Steam's Gamepad layout. Press `Ctrl+O`, or open YouTube's settings, for VacuumTube's settings: ad blocking, SponsorBlock categories, DeArrow, dislikes, hiding Shorts, codec filters and more. Each Steam account's VacuumTube starts set up for a TV: full screen without window decorations, no "Continue watching?" prompt, no Shorts, no Shorts or Podcasts tab in the side menu, the time left shown while playing, and HDR allowed. Folders made before version 2.11.0 get the window and tab settings once, on their next start; after that, changes you make in VacuumTube's settings stay. On a TV in Game Mode, VacuumTube is scaled to the 1080p layout YouTube's TV apps are made for (1.25× at 1440p, 2× at 4K), so its settings menu is a readable size. While it is scaled, **Unlock Resolution** stays on: VacuumTube limits videos to the screen size it sees, which the scale reduces, so a 4K TV would otherwise get 1080p. HDR needs an HDR TV, Steam's HDR setting turned on, and VacuumTube running on Wayland; if colours look washed out on a screen without HDR, turn off **Wayland HDR** in VacuumTube's settings. To cast from a phone, choose the device in the YouTube app on the same network. In Game Mode, VacuumTube turns Chromium's sandbox off; `GAME_MODE_SANDBOX=1` keeps it on (see [Configuration](#configuration)).
- **Element:** Element has no controller navigation, so it gets Steam's Web Browser controller layout, in which the trackpads work as a mouse. Use those or the touchscreen; **Steam + X** opens the on-screen keyboard. To pick another layout, use the controller icon on its library page. On a TV in Game Mode, Element is scaled like the Helium apps (`TV_SCALE`). Closing its window quits it: each Steam account's Element starts with minimising to the tray turned off, because Game Mode has no tray to bring it back from.
  - **Signing in, in Game Mode:** matrix.org signs you in on its own website. NonSteamApps opens that page in Helium in front of Element and lets it hand the sign-in back, so once you have signed in, Helium closes and Element carries on. Links you open in Element also open in Helium; **Menu** closes them. This needs the Helium app installed. In Desktop Mode, Element uses your usual browser.
- **Signal:** on its first start, link it to Signal on your phone: in the phone app, open **Settings → Linked devices** and scan the code on screen. Each Steam account links its own Signal. As with Element, it has Steam's Web Browser controller layout and the TV scale, and closing its window quits it. See [How Signal keeps its data](#how-signal-keeps-its-data).
- **Jellyfin:** starts in its TV layout. Add your server and sign in once for each Steam account. On a TV in Game Mode, it is scaled like the Helium apps (`TV_SCALE`).
- **Bitwarden:** sign in with your email address and master password; each Steam account keeps its own vault. **X** shows the on-screen keyboard.
  - **Controls (Tools layout):** the D-pad moves up and down a list and left and right between controls, **A** selects, **Y** is OK, **B** cancels, and **R2** clicks where the right stick or right trackpad points.
  - **Quitting:** closing its window quits it, so Steam sees it end. Bitwarden normally keeps running in the tray, which Game Mode does not have.
  - **Unlocking:** set a PIN under **Settings → Security → Unlock with PIN** to unlock with the controller. Biometric unlock needs a polkit rule in a system folder that SteamOS keeps read-only, and the **Never** lock timeout needs a keyring.
  - **Sign-in tokens:** they are kept unencrypted in the account's Bitwarden folder (`ACCESS_TOKEN_LOCATION=DISK`), so a keyring that is missing in one mode cannot sign you out. Your vault stays encrypted with your master password.
  - **SSO and Duo:** in Game Mode, these open their pages in Helium in front of Bitwarden and return to it, as Element's sign-in does.
- **LocalSend:** devices on the same network find each other while LocalSend is open on both. It starts dark, in its OLED colours; running the installer again puts them back. LocalSend listens on port 53317 (TCP and UDP). When SteamOS's firewall (firewalld) is running, the installer offers to open that port, both now and permanently, in every firewall zone in use. `sudo` then asks for your password. Removing LocalSend closes the port again, unless you keep the app with `--keep-app`.
  - **Receiving:** accept a transfer and the files land in `~/Downloads`.
  - **Sending:** you pick files through the system file chooser. If it does not open in Game Mode, send from Desktop Mode.
  - **Controls (LocalSend layout):** the D-pad moves between buttons and settings, **A** selects, **B** goes back, **L1** and **R1** step to the previous and next control, **Y** pastes (outside a text box, LocalSend then offers to send what you copied), **X** shows the on-screen keyboard, and holding **Menu** quits LocalSend. The trackpads and right stick still move the pointer, with **R2** to click, and the touchscreen works too.
  - **On a TV:** in Game Mode, LocalSend is scaled ×2 on a 1440p TV and ×3 on a 4K one. Its toolkit only scales by whole numbers, so it is not scaled at 1080p.
- **Prism Launcher:** on its first start, choose a language and sign in with the Microsoft account that owns Minecraft. Each Steam account does this once, because each has its own instances, worlds and sign-in. Minecraft's downloads (assets, libraries and Java) are kept once and shared. Instances made in Prism Launcher from the applications menu stay in its own data: to play one from Steam, copy its folder from `~/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher/instances` into the account's `instances` folder (see [Several Steam accounts](#several-steam-accounts)).
  - **Console flow:** pick an instance and choose **Launch**. Prism Launcher closes when Minecraft opens, and quits when you leave Minecraft, which takes you back to Steam. If Minecraft crashes, Prism Launcher stays open with its log.
  - **On a TV:** the launcher is dark and, in Game Mode, scaled for the TV (`TV_SCALE`) and as large as the screen. Minecraft's own **GUI Scale** setting (Options → Video Settings) sizes the game's menus; **Auto** picks the largest that fits.
  - **Controls (Minecraft layout):** the left stick moves and its click sprints, the right stick looks and its click sneaks, **A** jumps, **B** opens and closes the inventory, **X** drops the held item, **Y** swaps hands, **R2** attacks or breaks, **L2** uses or places, the bumpers move along the hotbar, **Menu** pauses and **View** shows the players. In menus, the right stick or right trackpad moves the pointer and **R2** clicks. Minecraft's sneak can hold or toggle: choose **Toggle** under Options → Controls if holding a stick click is awkward.
  - **Native controller menus:** a mod such as Controlify gives Minecraft its own controller support. Add it to an instance in Prism Launcher, then pick Steam's **Gamepad** layout for Prism Launcher in Steam.
- **ProtonUp-Qt:** choose **Add version**, pick a tool such as GE-Proton and a version, and install it for Steam. Steam lists a new tool once it restarts: then choose it for a game under **⚙ → Properties → Compatibility**. Choose tools there rather than in ProtonUp-Qt's game list, whose changes Steam overwrites while it runs, as it always does in Game Mode.
  - **On a TV:** it starts in its dark Steam Deck theme and, in Game Mode, is scaled for the TV (`TV_SCALE`): its window is small, so 1.5× at 1080p and 3× at 4K.
  - **Controls (Tools layout):** the D-pad moves up and down a list and left and right between controls, **A** selects, **Y** is OK, **B** cancels, **X** shows the on-screen keyboard, and **R2** clicks where the right stick or right trackpad points. ProtonUp-Qt's own gamepad support is off when Steam starts it, so a press does not count twice.
  - **Libraries:** it reaches every Steam library, an SD card's included, so its game list shows all your games.
- **Protontricks:** pick a game, then what to do with its Proton prefix, such as installing a Windows component or font, or running `winecfg`. A game appears once it has been started at least once. Like ProtonUp-Qt, it reaches every Steam library and has the Tools layout: in Winetricks' lists, **A** ticks an item and **Y** confirms.
  - **On a TV:** in Game Mode, its windows' text is 1.5× at 1080p, and the whole window 3× at 4K, as GTK scales windows by whole numbers only.
  - **If Wine hangs:** add `--no-bwrap` to its **Launch Options** after `--steam-account <ID>`. Running the installer again removes it.
- **Files:** SteamOS's Dolphin, started with a TV profile that is kept apart from Desktop Mode's Dolphin. A single press opens a file or folder, the menu bar is hidden (the ☰ button holds the menu), and Files starts at your home folder each time. Thumbnails and the Places panel's icons are larger, zip files and other archives open like folders, and quitting with several tabs open does not ask first. In Game Mode it is scaled for the TV (`TV_SCALE`), opens as large as the screen, and is drawn in KDE's own style. Desktop Mode's settings, bookmarks, file associations and trash still apply. What you change in Files stays in its profile, as do the settings of apps you open from it.
  - **Controls (Files layout):** the D-pad or left stick moves the selection, **A** opens, **B** or **L1** goes back, **Y** or **R1** goes forward, **X** shows the on-screen keyboard to rename or search, **R2** clicks and **L2** opens the menu for the item under the pointer, which the right stick or right trackpad moves. **View** cancels, **Menu** closes the tab (closing the last one quits Files), and holding **Menu** quits Files at once.
  - **The layout:** NonSteamApps makes it from Steam's Web Browser layout, for each controller type Steam has a Gamepad layout for, and saves it in Steam's `controller_base/templates` folder. If a Steam update removes it, the weekly update or `nonsteamapps steam add files` puts it back.
- **Helium, Prime Video, HBO Max, Netflix, Disney+, ProtonDB and Proton Calendar:** see [Helium apps](#helium-apps).

### On a TV: use its full resolution

In Game Mode, Steam decides the resolution each app runs at. On an external display, its default is usually lower than the TV's own. With the Steam Deck connected to the TV, select an app in your library, then **⚙ → Properties → Shortcut → Maximum Game Resolution → Native**. The setting only appears while an external display is connected. Set it for each app, and for each Steam account. [docs/plans/steam-native-resolution.md](docs/plans/steam-native-resolution.md) describes how automating this is planned.

Game Mode shows a window that is not full screen at its own size, scaled to fit, with black bars, and ignores a request to maximise it. So NonSteamApps opens Files, Prism Launcher, ProtonUp-Qt and the Helium browser as large as the screen, and asks for the Helium browser's windows to be full screen; the browser keeps its tabs and address bar. The site apps already run full screen. A resolution that is not 16:9, such as the Steam Deck's own 1280 × 800, still leaves bars on a 16:9 TV, which **Native** avoids.

## Several Steam accounts

Each Steam account's shortcut starts the app with `--steam-account <ID>`. NonSteamApps then points the app at that account's own data:

| App | Data for a Steam account |
| --- | --- |
| YouTube | `~/.var/app/rocks.shy.VacuumTube/config/VacuumTube-steam-<ID>` |
| Element | `~/.var/app/im.riot.Riot/config/Element-steam-<ID>` |
| Signal | `~/.var/app/org.signal.Signal/config/Signal-steam-<ID>` |
| Bitwarden | `~/.var/app/com.bitwarden.desktop/config/Bitwarden-steam-<ID>`, through `BITWARDEN_APPDATA_DIR` |
| Jellyfin | A Jellyfin Desktop profile named `steam-<ID>`, created on first launch |
| LocalSend | Shared by every account: it has no sign-in, and received files go to `~/Downloads` |
| Prism Launcher | `~/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher-steam-<ID>`, with Minecraft's assets, libraries and Java linked from Prism Launcher's own `data/PrismLauncher` |
| ProtonUp-Qt | Shared by every account: it installs compatibility tools for the whole Steam installation |
| Protontricks | Shared by every account: it changes each game's own Proton prefix |
| Files | Shared by every account: a TV profile in `~/.local/share/nonsteamapps/profiles/files/shared`, over Desktop Mode's Dolphin settings |
| Helium, Prime Video, HBO Max, Netflix, Disney+, ProtonDB, Proton Calendar | A Helium profile in `~/.local/share/nonsteamapps/profiles/<app>/<ID>` |

Started from the applications menu, VacuumTube, Element and Signal use their usual data instead, and Jellyfin uses its default profile. To give every account the same data, set `PROFILE_PER_STEAM_ACCOUNT=0` in `~/.config/nonsteamapps/nonsteamapps.conf`.

## Helium apps

Helium publishes no Flatpak, so NonSteamApps installs its signed release itself. It checks the signature against Helium's public key, keeps the installed version and the one before it in `~/.local/share/nonsteamapps/helium`, and updates it with the other apps. The apps run as follows:

- **Helium** opens as a full browser: maximised in Desktop Mode, and in Game Mode as large as the screen, with its tabs and address bar.
- **Prime Video**, **HBO Max**, **Netflix**, **Disney+**, **ProtonDB** and **Proton Calendar** each open their site full screen (kiosk mode), with no address bar or tabs. To leave, hold **Menu**, or press the Steam button and choose **Exit game**.

Each app has its own Helium profile for each Steam account, so signing in to one never signs you in to another. Before every start, NonSteamApps sets up that profile for a console:

- **No interruptions:** onboarding and welcome pages are marked as seen, and the last session is recorded as closed cleanly. Steam ends apps by signalling them, which would otherwise bring up "Restore pages?".
- **Fewer prompts:** sites cannot ask to send notifications, so Proton Calendar's reminders do not pop up; see them on your phone or computer instead. The full-screen apps also turn off translation, password and address saving, and permission prompts.
- **Navigation:** the arrow keys move between links and buttons, as on a TV (Chromium's spatial navigation).
- **Dark:** Helium's interface is dark, and so are sites that offer a dark theme. In the Helium app, **Settings → Appearance → Mode** switches back to light.
- **Scale:** in Game Mode, pages are scaled so a TV shows a 720p-sized layout (1.5× at 1080p, 3× at 4K). Set `TV_SCALE` to choose a fixed scale.
- **Video:** decoding uses the graphics chip (VA-API), and video plays without waiting for a click.
- **Controllers:** the apps get NonSteamApps' Browser controller layout, which is Steam's Web Browser layout with one addition: holding **Menu** quits the app, whatever tabs are open. The trackpads work as a mouse and scroll wheel, and **Steam + X** opens the on-screen keyboard. On the Steam Deck, **L1** and **R1** go back and forward, and a short press of **Menu** closes a tab. In ProtonDB, links to the Steam store and other sites open in a new tab, so **Menu** brings you back to ProtonDB; Proton Calendar's links to Proton's other apps work the same way. Change the layout under the controller icon on the app's library page.

### Streaming apps: what to expect

- **Widevine:** all four services need Widevine copy protection. Helium downloads it through Helium's services the first time a profile asks for it, and every profile then shares that download. If the first video does not play, close the app and open it again.
- **Picture quality:** on Linux, Widevine runs without hardware protection (level L3), and the services limit browsers like this: Prime Video to standard definition, Netflix to 720p. Disney+ plays, but may limit quality too. HBO Max does not officially support Linux, so it may limit quality, or stop playing altogether. NonSteamApps cannot lift these limits.
- **Helium's services:** they are on by default, because they deliver Widevine and keep the ad blocker's filter lists current. Set `HELIUM_SERVICES=0` to keep Helium from contacting them; the streaming apps then cannot play.

### Privacy, security and ad blocking

Helium does most of the work, and NonSteamApps keeps its defaults:

- **Ads and trackers:** uBlock Origin is built in. Helium's services keep its filter lists current.
- **Tracking:** third-party cookies are blocked, and WebRTC does not reveal local network addresses. Fingerprinting scripts get slightly randomised answers. Link-auditing pings, page preloading and running in the background are off.
- **Connections:** Helium tries HTTPS first, and warns before it opens a public site over an insecure connection.
- **Updates:** NonSteamApps installs Helium only with a valid signature from Helium's key, updates it every week, and keeps the version before for `nonsteamapps rollback`.

Each new profile also:

- sends [Global Privacy Control](https://globalprivacycontrol.org), which asks sites not to sell or share your data; some laws, such as California's, require sites to honour it;
- keeps crash reports off, so no upload question appears after a crash.

NonSteamApps sets these only when it creates a profile, so a change you make in Helium's settings stays.

Left out on purpose:

| Not added | Why |
| --- | --- |
| Extra extensions, such as ones claiming 1080p on Netflix | Each is more code from another source with access to your sign-ins, to vet and keep updated. The 1080p ones also rely on tricks that the services break without notice. |
| Strict HTTPS-only mode | Helium already prefers HTTPS. Strict mode adds full-page warnings that are awkward to get past with a controller. |
| A fixed secure-DNS provider | Helium already uses DNS over HTTPS when your network's DNS provider supports it. A fixed provider would see every site you visit, and can break home networks that name local devices or filter content. |
| JavaScript without its optimiser | It removes a common route for exploits, but makes the streaming sites' heavy interfaces noticeably slower. |
| Locking the streaming apps to their own sites | Sign-in, payment and playback span many domains that change without notice, so a lock would break them. |
| Changing uBlock Origin's filter lists | Doing it for you would need a system-wide browser policy, which needs root. You can add lists, such as cookie-notice filters, in uBlock Origin's own settings in the Helium app. |

**Ads in ad-supported plans.** uBlock Origin removes ads and trackers from web pages. The ads in the streaming services' ad-supported plans, however, come from the services themselves, alongside the video, so a blocker either cannot remove them or breaks playback; only an ad-free plan does.

## How Element keeps your sign-in

Element normally protects its stored session secrets with the system keyring. Game Mode has no keyring, and a profile protected by KWallet in Desktop Mode cannot be opened in Game Mode. Steam therefore starts Element with `--password-store=basic --storage-mode=allow-plaintext`.

The session secrets stay in the profile folder, encrypted with a fixed key rather than a password: hidden from casual view, but not protected from software running as your user. In exchange, the same profile works in both modes and Element never stops at a prompt a controller cannot answer.

To limit the risk:

- set up Element's **Secure Backup** with a recovery key;
- if the device is lost, sign it out from another device under **Settings → Sessions**.

Element started from the applications menu keeps using the keyring.

## How Signal keeps its data

Flathub's Signal keeps the key to its message database in plain text by default (`SIGNAL_PASSWORD_STORE=basic`), because of database-corruption bugs with the encrypted keyrings. Game Mode has no keyring anyway, so each Steam account's Signal always uses this store, and the same profile opens in both modes.

On a first start with this store, Flathub's Signal asks for confirmation, with **No**, which quits, preselected. That is easy to answer wrongly with a controller. NonSteamApps skips the question by creating the account's settings file before the first start, and shows the same note after installing instead.

The key can therefore be read by anyone who can read your files. If the device is lost, unlink it from your phone under **Settings → Linked devices**.

Signal started from the applications menu keeps Flathub's own defaults, including the question.

## Configuration

`~/.config/nonsteamapps/nonsteamapps.conf` holds five settings:

| Setting | Default | Effect |
| --- | --- | --- |
| `PROFILE_PER_STEAM_ACCOUNT` | `1` | Separate data for each Steam account (see [Several Steam accounts](#several-steam-accounts)) |
| `STEAM_COLLECTION` | `NonSteamApps` | Name of the Steam collection that holds the apps in each account; leave empty for no collection |
| `HELIUM_SERVICES` | `1` | Let Helium use its services, which deliver Widevine for the streaming apps and keep the ad blocker's filter lists current |
| `TV_SCALE` | `auto` | Scale of the Helium apps, YouTube, Element, Signal, Bitwarden, Jellyfin, LocalSend, Prism Launcher, ProtonUp-Qt, Protontricks and Files: `auto` sizes them for a TV in Game Mode, a number such as `1.5` sets the scale, and `1` turns it off. Replaces `HELIUM_SCALE`, which is still read |
| `GAME_MODE_SANDBOX` | `0` | `1` keeps Chromium's sandbox on for YouTube in Game Mode. Not yet confirmed on a Steam Deck: if YouTube then does not start, set it back to `0` |

Anything you add to a shortcut's **Launch Options** in Steam after `--steam-account <ID>` is passed to the app, for example `--debug-gpu` for VacuumTube. `nonsteamapps update` keeps it; running the installer again sets the options back.

## Commands

The installer places the `nonsteamapps` command in `~/.local/share/nonsteamapps/bin/`:

```text
nonsteamapps install [APP...]        install every app, or those named, and set them up afresh
nonsteamapps remove APP... [--purge] [--keep-app]
                                     remove apps from Steam and uninstall those NonSteamApps installed;
                                     --purge also deletes their data for every Steam account
nonsteamapps list                    every app, and whether it is installed
nonsteamapps update [--apps-only]    update NonSteamApps and your apps, keeping them as they are;
                                     --apps-only updates only the apps and Helium, as the weekly timer does
nonsteamapps rollback                switch Helium back to the version installed before
nonsteamapps steam add|remove|status [APP...] [--user all|auto|ID]
nonsteamapps doctor                  diagnostics, including each app's last launch log
nonsteamapps uninstall [--purge] [--keep-apps]
nonsteamapps launch APP [--steam-account ID] [--verbose] [-- ARGS]
                                     what Steam runs
```

`./uninstall.sh [--purge]` in this repository does the same as `nonsteamapps uninstall`. Without `--purge`, sign-ins and settings are kept.

## Moving from SteamOS YT

Installing NonSteamApps on a device with SteamOS YT, the Helium-based YouTube kiosk this project used to be, does the following:

- **Shortcut:** the existing YouTube shortcut now starts VacuumTube. It keeps its Steam app ID, so its play time, collections, controller layout and resolution setting carry over.
- **Shared sign-in:** if SteamOS YT was set to share one sign-in between Steam accounts, that choice carries over.
- **Clean-up:** after asking, the installer removes SteamOS YT: Helium, its profiles, its settings, its update timer and its menu entry.
- **Signing in again:** Helium's sign-ins cannot move to VacuumTube, so sign in to YouTube once for each Steam account.

## How it works

1. `install.sh` copies the program to `~/.local/share/nonsteamapps`, notes where it came from and runs `nonsteamapps install`. Without app names, that installs every app and puts back NonSteamApps' set-up in the data each already has.
2. Each Flathub app is installed with `flatpak install --user`, unless it is already installed. The Helium apps share one signed Helium release, unpacked in `~/.local/share/nonsteamapps/helium`. Files uses the Dolphin SteamOS includes, which NonSteamApps never installs or removes.
3. Each app gets a link in `~/.local/share/nonsteamapps/apps/`, for example `apps/youtube`, pointing at the launcher. Steam's shortcut runs that link with `--steam-account <ID>`. Steam derives the shortcut's app ID from the link and the name, and NonSteamApps writes the shortcut to each account's `shortcuts.vdf`, with the artwork in the account's `grid` folder. It also adds the app to its collection in the account's collections file (`config/cloudstorage`), which Steam syncs through Steam Cloud. It writes that file the way Steam ROM Manager does, and leaves your other collections alone. Steam is closed while these files change, then started again in a systemd unit of its own, named as Plasma names the apps it starts (`app-steam-<random>.scope`). KDE's screen-sharing prompts then identify it as Steam, not Konsole.
4. When an app starts, the launcher works out the Steam account: the shortcut's, otherwise the most recent sign-in. It then:
   - removes what Steam adds to a game's environment: its overlay library, which stops Helium starting in Game Mode, the Steam Runtime's library paths, and any Proton prefix (`STEAM_COMPAT_DATA_PATH`), which Protontricks would otherwise change whatever game is picked;
   - prepares that account's data (for a Helium app, its profile: preferences, a clean last exit and the shared Widevine folder);
   - logs to `~/.local/state/nonsteamapps/<app>.log`;
   - for Element and Bitwarden in Game Mode, stays as the app's parent, with its own `xdg-open` first on the app's `PATH`. That script sends web links and sign-in callbacks through a pipe in the app's runtime folder, which Flatpak shares with the sandbox. NonSteamApps opens a web link in Helium, which Game Mode shows in front of the app because Steam started both, and starts the app again with a callback, which then reaches the running app;
   - otherwise replaces itself with `flatpak run <app> …` (for Signal, `flatpak run --command=env …`, so that Signal's own launch script sees the account's folder; for ProtonUp-Qt and Protontricks, with `--filesystem` for each folder in Steam's `libraryfolders.vdf`, for that run only), with Helium and its console flags, or with Dolphin and its TV profile: its own `XDG_CONFIG_HOME` and `XDG_STATE_HOME`, with Desktop Mode's settings underneath through `XDG_CONFIG_DIRS`.
5. For apps with a controller layout, NonSteamApps finds the layout in Steam's `controller_base/templates` and records it for the shortcut in `steamapps/common/Steam Controller Configs/<ID>/config`, where Steam keeps the layout a user picks. An install puts NonSteamApps' layout back over one you chose, and an update keeps yours. An install also removes any Steam Play tool forced on its shortcuts from `config/config.vdf` (`CompatToolMapping`), as Steam ROM Manager does, and keeps a backup. The Browser, Files, Minecraft and Tools layouts are NonSteamApps' own: each is made from one of Valve's layouts on the device, written into that folder first, one file per controller type, and removed with the last app that uses it.
6. If firewalld is running, LocalSend's port is opened with `sudo firewall-cmd`, and NonSteamApps records what it opened so that it can close it again.
7. `nonsteamapps update` fetches NonSteamApps again from where the installer came from, runs that version's `install.sh` to copy only the program, and hands over to the new version. That version updates the apps and Helium, then refreshes the shortcuts already there. NonSteamApps notes a fingerprint of each artwork file it puts in Steam's `grid` folders (`~/.local/state/nonsteamapps/artwork.json`), so it renews its own artwork and leaves artwork you chose. Steam is closed only if a shortcut must change.
8. A weekly systemd user timer runs `nonsteamapps update --apps-only`, which updates the apps and Helium but neither NonSteamApps itself nor the Steam library. Discover updates any other Flatpaks.

## Troubleshooting

- **"Steam is running in Game Mode":** switch to Desktop Mode and run the command again.
- **An app does not start:** `nonsteamapps doctor` shows each app's last launch log, and whether a Steam Play tool such as Proton is forced on it; `nonsteamapps launch youtube --verbose` runs it in the terminal.
- **An app stopped starting after you chose Proton or another compatibility tool for it:** run `nonsteamapps steam add <app>`, or untick **Force the use of a specific Steam Play compatibility tool** in its Properties. NonSteamApps' apps run natively.
- **A Helium app stays on Steam's loading screen in Game Mode and cannot be exited** (versions 2.2.0 to 2.8.0): run the installer again to update. Those versions let Steam's overlay library into Helium, which then never starts.
- **After installing, a window asks to share the screen with Konsole** (before version 2.10.1): decline it, then restart Steam from the application menu or run the installer again to update. The installer started Steam again from Konsole, and KDE treats a program started from Konsole as part of Konsole, so Steam's request to capture the screen was shown as Konsole's.
- **In Game Mode, Element's or Bitwarden's sign-in opens in Steam's browser and never comes back:** install Helium with `nonsteamapps install helium`. NonSteamApps opens sign-in pages in it, and the app's log (`nonsteamapps doctor`) says when it is missing.
- **Helium asks whether to open a link with xdg-open after you sign in:** choose **Open**. NonSteamApps allows the sign-in page's own site in advance, but a sign-in that ends on another site, such as your organisation's, asks once.
- **A new Steam account has no shortcuts:** run `nonsteamapps steam add`.
- **Files, Prism Launcher, ProtonUp-Qt or Protontricks has Steam's default controls:** run `nonsteamapps steam add files prism protonup protontricks`. It writes NonSteamApps' layouts again, for example after a Steam update removed them.
- **A tool installed with ProtonUp-Qt is missing from a game's Compatibility list:** restart Steam, which reads its tools when it starts.
- **Protontricks does not list a game:** start the game once from Steam, then open Protontricks again.
- **An account has no NonSteamApps collection:** Steam creates an account's collections file the first time it opens the library. Open Steam with that account once, close it, then run `nonsteamapps steam add`.
- **A Helium update misbehaves:** `nonsteamapps rollback` switches back to the previous version.
- **A streaming app shows a playback error the first time:** close the app and open it again, once Widevine has downloaded. `nonsteamapps doctor` shows whether it has.
- **The picture looks soft on a TV:** see [On a TV](#on-a-tv-use-its-full-resolution).
- **YouTube does not start in Game Mode after setting `GAME_MODE_SANDBOX=1`:** set it back to `0`.
- **Phones and computers cannot see the device in LocalSend:** `nonsteamapps doctor` shows whether the firewall lets port 53317 in. If it does not, run the installer again. If opening the port failed because your account has no password, set one first with `passwd`. Also check that your router does not isolate devices from each other, which guest networks often do.
- **The screen dims, or the device sleeps, during a video:** Game Mode ignores the requests that video apps send to keep the screen on. In Steam's settings, under Display and Power, lengthen or turn off the dimming and sleep timers. Alternatively, use a Decky Loader plugin that pauses them while something plays.
- **Casting from the YouTube app does not find the device:** with the firewall on, casting may be blocked. VacuumTube answers on UDP port 1900 and a TCP port it picks at random each time, so NonSteamApps cannot open a fixed port for it.

## Development

```bash
python3 -m unittest discover -s tests          # apps, Flatpak, Helium (with real signatures), Steam, layouts, migration and command-line flows
shellcheck -x -P SCRIPTDIR install.sh uninstall.sh src/bin/nonsteamapps tests/sandbox.sh tests/fakes/sudo tests/fakes/dolphin src/share/sandbox/xdg-open
tests/sandbox.sh                               # install.sh, launches through the links Steam runs, uninstall.sh
node tools/render-artwork.js [APP...]          # render assets/src/<app> into assets/artwork/<app>
```

| Path | Purpose |
| --- | --- |
| `install.sh`, `uninstall.sh` | Entry points (work from a clone or through `curl … \| bash`) |
| `src/bin/nonsteamapps` | Launcher: runs the command-line interface, or starts an app when called through its link |
| `src/lib/nonsteamapps/` | Python standard-library package: `apps.py` (the apps), `flatpak.py`, `helium.py` (the signed Helium release), `browser.py` (console profiles and flags), `display.py` (TV scale), `controllers.py` (Steam layouts), `layouts.py` (NonSteamApps' own layouts), `collection.py` (the Steam collection), `compat.py` (Steam Play tools), `steam.py` and `vdf.py` (shortcuts and artwork), `steamclient.py`, `firewall.py` (LocalSend's port), `legacy.py` (SteamOS YT), `selfupdate.py` and `net.py` (updating NonSteamApps itself), `links.py` (sign-ins in Game Mode), `x11.py` (full-screen windows in Game Mode), `cli.py` |
| `src/share/` | Default settings, the update timer and Helium's public signing key (fingerprint `BE67 7C19 89D3 5EAB 2C5F 26C9 3516 01AD 01D6 378E`) |
| `assets/src/<app>`, `assets/artwork/<app>` | SVG sources and rendered Steam artwork |
| `tests/fakes/` | Stand-ins for `flatpak`, `firewall-cmd` and `sudo`, used by the tests; `tests/_fakes.py` also builds a stand-in Helium release |

To add an app:

1. Add an `App` to `apps.py` with its Flathub ID, arguments and per-account data.
2. Draw its artwork in `assets/src/<app>` and render it.
3. Extend the tests.

## Roadmap

- [ADR 0001](docs/decisions/0001-multi-app-steam-integration.md): why NonSteamApps installs upstream clients from Flathub and owns only the Steam integration.
- [Maximum Game Resolution plan](docs/plans/steam-native-resolution.md): set **Native** for every app and account automatically.
- Steam Input layouts for each app, for example a mouse-and-keyboard layout for Element.

## Acknowledgements

- [VacuumTube](https://github.com/shy1132/VacuumTube) by shy1132 and contributors, which brings YouTube's TV interface to the desktop.
- [Element](https://github.com/element-hq/element-web), and the maintainers of its [Flathub package](https://github.com/flathub/im.riot.Riot).
- [Signal Desktop](https://github.com/signalapp/Signal-Desktop) by Signal Messenger, and the maintainers of its unofficial [Flathub package](https://github.com/flathub/org.signal.Signal).
- [Bitwarden](https://github.com/bitwarden/clients) by Bitwarden and contributors.
- [Jellyfin Desktop](https://github.com/jellyfin/jellyfin-desktop) by the Jellyfin project.
- [LocalSend](https://github.com/localsend/localsend) by Tien Do Nam and contributors.
- [Helium](https://github.com/imputnet/helium) by imput, built on ungoogled-chromium.
- [ProtonDB](https://www.protondb.com), where players report how well games run with Proton.
- [Prism Launcher](https://github.com/PrismLauncher/PrismLauncher) by its contributors, and the maintainers of its [Flathub package](https://github.com/flathub/org.prismlauncher.PrismLauncher).
- [ProtonUp-Qt](https://github.com/DavidoTek/ProtonUp-Qt) by DavidoTek and contributors.
- [Protontricks](https://github.com/Matoking/protontricks) by Matoking and contributors, built on [Winetricks](https://github.com/Winetricks/winetricks).
- [Dolphin](https://apps.kde.org/dolphin/) by KDE, as SteamOS ships it.
- [Steam ROM Manager](https://github.com/SteamGridDB/steam-rom-manager): reference for Steam's shortcut, artwork and controller conventions.

NonSteamApps is not affiliated with Valve, Google, Element, the Matrix.org Foundation, Signal Messenger, Bitwarden, the Jellyfin project, LocalSend, imput, ProtonDB, Proton AG, KDE, the Prism Launcher project, the ProtonUp-Qt project, the Protontricks project, the Winetricks project, Mojang Studios, Microsoft, Amazon, Warner Bros. Discovery, Netflix or The Walt Disney Company. YouTube is a trademark of Google LLC; Steam and SteamOS are trademarks of Valve Corporation; Minecraft is a trademark of Mojang Synergies AB; other names belong to their owners. The artwork in this repository is original.
