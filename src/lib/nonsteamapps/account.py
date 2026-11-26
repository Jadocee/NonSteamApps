"""The account NonSteamApps runs in, whose password ``sudo`` asks for, and what keeps that password from working.

SteamOS names its user account ``deck`` on every device, a Steam Machine as much as a Steam Deck, so sudo's
prompt, ``[sudo] password for deck:``, names the account, not the device. ``passwd -S`` tells the account itself
whether it has a password (``P``), none (``NP``), with which sudo runs without asking, or a locked one (``L``),
with which sudo asks and takes no answer.

SteamOS's PAM (``pam_faillock``) refuses the account, even its right password, for ``unlock_time`` seconds once
``deny`` wrong ones have come within ``fail_interval`` seconds of each other: 600, 3 and 900 unless
``/etc/security/faillock.conf`` says otherwise. sudo then says only "Sorry, try again". ``faillock`` shows the
account its own failures. Neither needs root.
"""

from __future__ import annotations

import datetime
import math
import os
import pwd
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

CONF = Path("/etc/security/faillock.conf")
DEFAULTS = {"deny": 3, "fail_interval": 900, "unlock_time": 600}
_FAILURE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s.*\s([VI])\s*$")
_REFUSED = ("incorrect password", "password is required", "authentication failure")


def name() -> str:
    """The name of the account NonSteamApps runs in."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get("USER", "")


def faillock_settings(conf: Path = CONF) -> Dict[str, int]:
    """``deny``, ``fail_interval`` and ``unlock_time`` as ``conf`` sets them, PAM's defaults otherwise; ``unlock_time``
    is 0 where the lockout lasts until it is reset (``never``)."""
    settings = dict(DEFAULTS)
    try:
        lines = Path(conf).read_text(encoding="utf-8").splitlines()
    except OSError:
        return settings
    for line in lines:
        key, separator, value = line.split("#", 1)[0].partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in settings:
            continue
        if value.isdigit():
            settings[key] = int(value)
        elif key == "unlock_time" and value == "never":
            settings[key] = 0
    return settings


def failures(report: str) -> List[datetime.datetime]:
    """The times of the valid failures that ``faillock --user`` reports, in its own local time, oldest first."""
    found = []
    for line in report.splitlines():
        match = _FAILURE.match(line.strip())
        if match and match.group(2) == "V":
            found.append(datetime.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    return sorted(found)


def lockout(report: str, now: datetime.datetime, settings: Dict[str, int]) -> Optional[int]:
    """The seconds left at ``now`` of the lockout that ``report`` shows: 0 for none, ``None`` for one that lasts until reset."""
    times = failures(report)
    deny = settings["deny"]
    if deny <= 0 or len(times) < deny:
        return 0
    last = times[-1]
    if len([time for time in times if (last - time).total_seconds() <= settings["fail_interval"]]) < deny:
        return 0
    if settings["unlock_time"] <= 0:
        return None
    return max(0, math.ceil(settings["unlock_time"] - (now - last).total_seconds()))


def refused(error: str) -> bool:
    """Whether sudo's ``error`` says it took no password, rather than that the command it ran failed."""
    return any(words in error.lower() for words in _REFUSED)


def _minutes(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"{minutes} more minute{'s' if minutes > 1 else ''}"


@dataclass(frozen=True)
class Account:
    """The account ``user``, as ``passwd`` and ``faillock`` report it, with ``conf``'s lockout settings."""

    user: str
    passwd: str = "passwd"
    faillock: str = "faillock"
    conf: Path = CONF

    def _output(self, command: List[str]) -> str:
        try:
            return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def password(self) -> str:
        """``P`` for a password, ``NP`` for none and ``L`` for a locked one, as ``passwd -S`` reports it; ``""`` where it cannot tell."""
        fields = self._output([self.passwd, "-S", self.user]).split()
        return fields[1] if len(fields) > 1 and fields[0] == self.user else ""

    def locked_for(self, now: Optional[datetime.datetime] = None) -> Optional[int]:
        """The seconds SteamOS still refuses the account's password, even the right one: 0 for none, ``None`` until reset."""
        report = self._output([self.faillock, "--user", self.user])
        return lockout(report, now or datetime.datetime.now(), faillock_settings(self.conf))

    def _lockout(self, seconds: Optional[int]) -> str:
        deny = faillock_settings(self.conf)["deny"]
        if seconds is None:
            return (f"after {deny} wrong passwords, SteamOS refuses your account's password, even the right one, until the "
                    f"failures are reset with: sudo faillock --user {self.user} --reset")
        return f"after {deny} wrong passwords, SteamOS refuses your account's password, even the right one, for {_minutes(seconds)}"

    def blocker(self) -> str:
        """Why sudo cannot run now, before it is asked, or ``""``: a locked password, or a lockout after wrong ones."""
        if self.password() == "L":
            return (f"your account, {self.user}, has a locked password, which sudo takes no answer for: set one with passwd in "
                    f"Konsole")
        seconds = self.locked_for()
        return self._lockout(seconds) if seconds != 0 else ""

    def advice(self) -> str:
        """What to do after sudo took no password."""
        seconds = self.locked_for()
        if seconds != 0:
            lockout_text = self._lockout(seconds)
            return f"{lockout_text[0].upper()}{lockout_text[1:]}; then run the installer again."
        settings = faillock_settings(self.conf)
        return (f"sudo asks for the password of your account, {self.user}, the one set with passwd in Konsole, not your Steam "
                f"password; after {settings['deny']} wrong ones, SteamOS refuses even the right one for "
                f"{max(1, math.ceil(settings['unlock_time'] / 60))} minutes.")

    def status(self) -> str:
        """The account and whether sudo can take its password, as ``nonsteamapps doctor`` shows them."""
        state = {"P": "has a password", "NP": "has no password, so sudo runs without one",
                 "L": "has a locked password; set one with passwd for sudo"}.get(self.password(), "its password could not be checked")
        seconds = self.locked_for()
        lock = f"; {self._lockout(seconds)}" if seconds != 0 else ""
        return f"{self.user} {state}{lock}"
