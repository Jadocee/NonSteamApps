import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fakes
import _paths
from nonsteamapps import account

NOW = datetime.datetime(2026, 11, 26, 10, 0, 0)
HEADER = "deck:\nWhen                Type  Source                                           Valid\n"


def report(*minutes_ago, valid="V"):
    lines = [f"{(NOW - datetime.timedelta(minutes=ago)):%Y-%m-%d %H:%M:%S} TTY   /dev/pts/0                                           {valid}"
             for ago in minutes_ago]
    return HEADER + "".join(f"{line}\n" for line in lines)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = Path(self.tmp.name) / "faillock.conf"

    def test_pams_defaults_hold_without_the_file_or_with_its_settings_commented_out(self):
        self.assertEqual(account.faillock_settings(self.conf), {"deny": 3, "fail_interval": 900, "unlock_time": 600})
        self.conf.write_text("# deny = 5\n# unlock_time = 60\n")
        self.assertEqual(account.faillock_settings(self.conf), account.DEFAULTS)

    def test_the_files_settings_win_and_never_means_until_reset(self):
        self.conf.write_text("deny = 5\nfail_interval=60 # a minute\nunlock_time = never\naudit\nsilent = yes\n")
        self.assertEqual(account.faillock_settings(self.conf), {"deny": 5, "fail_interval": 60, "unlock_time": 0})


class LockoutTests(unittest.TestCase):
    def test_only_valid_failures_count(self):
        self.assertEqual(account.failures(report(5, 1, 3)), sorted(NOW - datetime.timedelta(minutes=ago) for ago in (5, 1, 3)))
        self.assertEqual(account.failures(report(5, 1, 3, valid="I")), [])
        self.assertEqual(account.failures("deck:\n"), [])

    def test_three_wrong_passwords_lock_the_account_for_ten_minutes_after_the_last(self):
        self.assertEqual(account.lockout(report(3, 2, 1), NOW, account.DEFAULTS), 540)
        self.assertEqual(account.lockout(report(12, 11, 10), NOW, account.DEFAULTS), 0)
        self.assertEqual(account.lockout(report(2, 1), NOW, account.DEFAULTS), 0)

    def test_failures_further_apart_than_the_interval_lock_nothing(self):
        self.assertEqual(account.lockout(report(40, 20, 1), NOW, account.DEFAULTS), 0)
        self.assertEqual(account.lockout(report(40, 2, 1, 0), NOW, account.DEFAULTS), 600)

    def test_a_lockout_without_an_unlock_time_lasts_until_reset_and_no_deny_locks_nothing(self):
        self.assertIsNone(account.lockout(report(300, 299, 298), NOW, {**account.DEFAULTS, "unlock_time": 0}))
        self.assertEqual(account.lockout(report(3, 2, 1), NOW, {**account.DEFAULTS, "deny": 0}), 0)

    def test_sudos_refusals_are_told_from_the_commands_own_failures(self):
        for error in ("sudo: a password is required", "sudo: 3 incorrect password attempts", "sudo: Authentication failure"):
            self.assertTrue(account.refused(error), error)
        for error in ("firewall-cmd: INVALID_ZONE: home", "install: cannot create regular file: Read-only file system"):
            self.assertFalse(account.refused(error), error)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.record = self.home / "faillock"
        self.account = _fakes.fake_account(self.home)
        patcher = mock.patch.dict(os.environ, {"FAKE_FAILLOCK_RECORD": str(self.record)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self, state):
        return mock.patch.dict(os.environ, {"FAKE_PASSWD_STATE": state})

    def failed(self, *minutes_ago):
        now = datetime.datetime.now().replace(microsecond=0)
        self.record.write_text("".join(f"{(now - datetime.timedelta(minutes=ago)):%Y-%m-%d %H:%M:%S} TTY   /dev/pts/0   V\n"
                                       for ago in minutes_ago))

    def test_passwd_tells_a_password_none_and_a_locked_one_apart(self):
        for state in ("P", "NP", "L"):
            with self.state(state):
                self.assertEqual(self.account.password(), state)
        self.assertEqual(account.Account("deck", passwd=str(self.home / "missing")).password(), "")
        self.assertEqual(account.Account("someone", passwd=str(_paths.ROOT / "tests" / "fakes" / "passwd")).password(), "P")

    def test_a_set_or_empty_password_blocks_nothing(self):
        for state in ("P", "NP", ""):
            with self.state(state):
                self.assertEqual(self.account.blocker(), "")
        self.assertEqual(self.account.status(), "deck has a password")
        with self.state("NP"):
            self.assertEqual(self.account.status(), "deck has no password, so sudo runs without one")

    def test_a_locked_password_blocks_sudo_before_it_asks(self):
        with self.state("L"):
            self.assertEqual(self.account.blocker(),
                             "your account, deck, has a locked password, which sudo takes no answer for: set one with passwd in Konsole")
            self.assertEqual(self.account.status(), "deck has a locked password; set one with passwd for sudo")

    def test_a_lockout_blocks_sudo_until_it_ends(self):
        self.failed(3, 2, 1)
        self.assertEqual(self.account.blocker(),
                         "after 3 wrong passwords, SteamOS refuses your account's password, even the right one, for 9 more minutes")
        self.assertEqual(self.account.advice(),
                         "After 3 wrong passwords, SteamOS refuses your account's password, even the right one, for 9 more minutes; then run "
                         "the installer again.")
        self.assertIn("deck has a password; after 3 wrong passwords", self.account.status())
        self.failed(9.5, 9.2, 9)
        self.assertIn("for 1 more minute", self.account.blocker())
        self.failed(12, 11, 10.5)
        self.assertEqual(self.account.blocker(), "")

    def test_a_lockout_until_reset_says_how_to_reset_it(self):
        (self.home / "faillock.conf").write_text("deny = 4\nfail_interval = 86400\nunlock_time = never\n")
        self.failed(300, 200, 100, 50)
        self.assertEqual(self.account.blocker(), "after 4 wrong passwords, SteamOS refuses your account's password, even the right one, until "
                                                 "the failures are reset with: sudo faillock --user deck --reset")

    def test_the_advice_names_the_account_and_its_password(self):
        self.assertEqual(self.account.advice(), "sudo asks for the password of your account, deck, the one set with passwd in Konsole, not "
                                                "your Steam password; after 3 wrong ones, SteamOS refuses even the right one for 10 minutes.")


if __name__ == "__main__":
    unittest.main()
