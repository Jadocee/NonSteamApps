"""Which device NonSteamApps runs on: a Steam Machine, a Steam Deck or another PC.

They are told apart as SteamOS Manager tells them apart, by what the firmware's DMI tables call the maker and the
board: with ``Valve`` as the maker, the Steam Machine's board is ``Fremont``, and the Steam Deck's ``Jupiter``, the
LCD model, or ``Galileo``, the OLED one. Any other machine is a PC, which NonSteamApps treats as it treats the Steam
Machine. On a Steam Deck:

- the apps stay open while it sleeps, as a handheld's apps usually do, unless ``CLOSE_BEFORE_SLEEP`` names them
  (see :mod:`sleepwatch`);
- an app that needs more than a Steam Deck has, as Eden-NX2 does, is not offered by the installer (see
  :attr:`apps.App.needs`);
- KytyPS5 keeps its own 1280×720, which runs faster there than the 1080p it gets on a TV (see :class:`apps.KytyGlobal`);
- Helium is scaled for its screen in Game Mode (see :func:`display.scale`), with Spacious controls and overlay
  scrollbars for its touchscreen (see :mod:`browser`), and so are the other apps laid out for a desktop's
  screen, such as Element, VLC, Files and the emulators' windows (see :attr:`apps.TvScale.handheld`).

chiaki-ng streams in HDR on a device whose screen can show it (see :attr:`Device.hdr`).
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from pathlib import Path

DMI = Path("/sys/class/dmi/id")
VARIABLE = "NONSTEAMAPPS_DMI"
VALVE = "Valve"
STEAM_MACHINE = "Steam Machine"
STEAM_DECK = "Steam Deck"
BOARDS = {"Fremont": STEAM_MACHINE, "Jupiter": STEAM_DECK, "Galileo": STEAM_DECK}
HDR_BOARDS = ("Fremont", "Galileo")


@dataclass(frozen=True)
class Device:
    """The device, by the ``board`` its firmware names, where Valve makes it; empty for any other PC."""

    board: str = ""

    @property
    def name(self) -> str:
        return BOARDS.get(self.board, "PC")

    @property
    def steam_deck(self) -> bool:
        return self.name == STEAM_DECK

    @property
    def hdr(self) -> bool:
        """Whether the device can show HDR: the Steam Deck OLED on its own screen, and the Steam Machine on a TV that can.

        A screen that cannot still shows an HDR stream, which the app then maps to its range.
        """
        return self.board in HDR_BOARDS


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def detect(dmi: Path = DMI) -> Device:
    """The device, as the DMI tables in the folder ``dmi`` describe it."""
    if _read(Path(dmi) / "sys_vendor") != VALVE:
        return Device()
    for name in ("board_name", "product_name"):
        found = _read(Path(dmi) / name)
        if found in BOARDS:
            return Device(found)
    return Device()


@functools.lru_cache(maxsize=None)
def current() -> Device:
    """This device, read once; ``NONSTEAMAPPS_DMI`` names another folder of DMI tables to read, as the tests do."""
    return detect(Path(os.environ.get(VARIABLE) or DMI))
