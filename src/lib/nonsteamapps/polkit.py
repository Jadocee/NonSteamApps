"""A polkit action an app needs that SteamOS does not ship, as Bitwarden's, with which its desktop app asks for the
account's password before it unlocks: its "Unlock with system authentication" on Linux, which its browser
extension then unlocks through.

Bitwarden checks with polkit that its action, ``com.bitwarden.Bitwarden.unlock``, exists; from its Flatpak it
cannot add it, as it would write it into ``/usr/share/polkit-1/actions``, which SteamOS keeps read-only. polkit
126 and later also read actions from ``/etc/polkit-1/actions``, which SteamOS keeps through its updates: SteamOS
3.9 has polkit 127 and SteamOS 3.10 polkit 128. Writing there takes ``sudo``, as opening LocalSend's port does
(see :mod:`firewall`). ``NONSTEAMAPPS_POLKIT_ROOT`` names another folder to find both under, as the tests and the
sandbox do.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import List, Optional, Sequence

SYSTEM = Path("usr/share/polkit-1/actions")
LOCAL = Path("etc/polkit-1/actions")
VARIABLE = "NONSTEAMAPPS_POLKIT_ROOT"
LOCAL_SINCE = 126


class PolkitError(RuntimeError):
    """A change that failed, with the ``commands`` that make it by hand."""

    def __init__(self, reason: str, commands: Sequence[str]) -> None:
        super().__init__(reason)
        self.commands = list(commands)


def action_id(policy: Path) -> str:
    """The ID of the action that the policy file ``policy`` defines."""
    found = ElementTree.parse(str(policy)).getroot().find("action")
    if found is None or not found.get("id"):
        raise ValueError(f"{policy} defines no action")
    return str(found.get("id"))


class Polkit:
    """The policy file ``policy``, NonSteamApps' copy, installed into the folder polkit reads local actions from."""

    def __init__(self, policy: Path, sudo: str = "sudo", pkaction: str = "pkaction") -> None:
        self.policy = Path(policy)
        self.sudo = sudo
        self.pkaction = pkaction
        root = Path(os.environ.get(VARIABLE) or "/")
        self.system = root / SYSTEM
        self.folder = root / LOCAL

    @property
    def path(self) -> Path:
        return self.folder / self.policy.name

    def present(self) -> bool:
        """Whether the action is installed, by the system's own packages or into the local folder."""
        return (self.system / self.policy.name).is_file() or self.path.is_file()

    def version(self) -> Optional[int]:
        """polkit's version, as ``pkaction --version`` gives it, or ``None`` where that cannot be told."""
        program = shutil.which(self.pkaction)
        if not program:
            return None
        try:
            output = subprocess.run([program, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
                                    check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = re.search(r"(\d+)(?:\.\d+)*\s*$", output.strip())
        return int(match.group(1)) if match else None

    def reads_local(self) -> Optional[bool]:
        """Whether this polkit reads actions from the local folder, as polkit 126 and later do; ``None`` where its version is not known."""
        version = self.version()
        return None if version is None else version >= LOCAL_SINCE

    def _run(self, command: List[str]) -> None:
        """Run ``command`` through ``sudo``, which asks for the password on the terminal; raise :class:`PolkitError` with the
        command to run by hand when it fails."""
        manual = ["sudo " + " ".join(command)]
        try:
            result = subprocess.run([self.sudo, *command], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise PolkitError(str(exc), manual) from exc
        if result.returncode != 0:
            said = result.stderr.strip().splitlines()
            raise PolkitError(said[-1] if said else f"exit status {result.returncode}", manual)

    def install(self) -> None:
        """Copy the policy into the local folder."""
        self._run(["install", "-D", "-m", "644", str(self.policy), str(self.path)])

    def remove(self, path: Optional[Path] = None) -> None:
        """Remove the policy from the local folder, or from ``path``, where it was installed."""
        self._run(["rm", "-f", str(path or self.path)])
