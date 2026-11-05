"""The screen an app starts on, and the interface scale that suits a TV in Game Mode."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional, Tuple

TV_HEIGHT = 720
TV_SIZED = 1000
_SCREEN = re.compile(r"current (\d+) x (\d+)")


def screen_size() -> Optional[Tuple[int, int]]:
    """The width and height of the screen apps start on, as xrandr reports it; in Game Mode, the resolution Steam runs the app at."""
    if not os.environ.get("DISPLAY") or not shutil.which("xrandr"):
        return None
    try:
        output = subprocess.run(
            ["xrandr", "--current"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _SCREEN.search(output)
    return (int(match.group(1)), int(match.group(2))) if match else None


def screen_height() -> Optional[int]:
    size = screen_size()
    return size[1] if size else None


def tv_sized(height: Optional[int]) -> bool:
    """Whether a screen ``height`` pixels tall is a TV's size, 1000 pixels or more, as at 1080p and above."""
    return bool(height and height >= TV_SIZED)


def window_size(factor: Optional[float]) -> Optional[Tuple[int, int]]:
    """The window size that fills the screen exactly, in the units of an app scaled by ``factor``."""
    size = screen_size()
    if not size:
        return None
    return round(size[0] / (factor or 1)), round(size[1] / (factor or 1))


def scale(setting: str, game_mode: bool, height: Optional[int] = None, layout: int = TV_HEIGHT) -> Optional[float]:
    """The interface scale: a number from the settings, or in Game Mode one that fits a layout ``layout`` pixels tall to the screen."""
    value = (setting or "auto").strip().lower()
    if value != "auto":
        try:
            number = float(value)
        except ValueError:
            return None
        return min(max(number, 0.5), 4.0) if number != 1 else None
    if not game_mode:
        return None
    height = screen_height() if height is None else height
    if not tv_sized(height):
        return None
    factor = round(height / layout * 4) / 4
    return factor if factor > 1 else None
