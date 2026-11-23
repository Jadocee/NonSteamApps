"""Make the installer's Python package importable from the tests, on a Steam Machine whatever device runs them.

``NONSTEAMAPPS_DMI`` points NonSteamApps at the DMI tables in ``fakes/dmi`` (see :mod:`nonsteamapps.device`), read once,
as on a device, and taken by the processes the tests start; :func:`on_device` makes another device the one the
tests run on.
"""

import contextlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "src" / "lib"
DMI = ROOT / "tests" / "fakes" / "dmi"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
os.environ["NONSTEAMAPPS_DMI"] = str(DMI / "steam-machine")

from nonsteamapps import device  # noqa: E402

device.current.cache_clear()
device.current()


@contextlib.contextmanager
def on_device(name):
    """Run the block as on the device whose tables are ``fakes/dmi/<name>``, for this process and those it starts."""
    before = os.environ["NONSTEAMAPPS_DMI"]
    os.environ["NONSTEAMAPPS_DMI"] = str(DMI / name)
    device.current.cache_clear()
    try:
        yield device.current()
    finally:
        os.environ["NONSTEAMAPPS_DMI"] = before
        device.current.cache_clear()
        device.current()
