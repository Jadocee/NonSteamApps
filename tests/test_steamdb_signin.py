import base64
import unittest
import urllib.parse
from pathlib import Path

import _paths
from nonsteamapps import artwork
from test_artwork import chromium

EXTENSION = Path(_paths.ROOT) / "src" / "share" / "extensions" / "steamdb"
ACCOUNT = "76561197960265839"
OTHER = "76561197960265840"
STEAMDB = "https://steamdb.info/"
SIGNED_OUT = ('<!doctype html><title>SteamDB</title><header><div class="header-user hide-small">'
              '<a class="header-login" href="/login/?page=faq" rel="nofollow"><span>Sign in</span></a></div></header>')
SIGNED_IN = '<!doctype html><title>SteamDB</title><header><div class="header-user hide-small"><a href="/user/">Account</a></div></header>'


def openid(realm: str = STEAMDB, return_to: str = STEAMDB + "login/?page=faq") -> str:
    """Steam's OpenID page as SteamDB's sign-in sends the browser to it."""
    return "https://steamcommunity.com/openid/login?" + urllib.parse.urlencode({
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    })


def confirmation(steam_id: str) -> str:
    """Steam's page asking a signed-in account to confirm a sign-in, with what Steam's pages say about who is signed in."""
    return ('<!doctype html><title>Steam Community :: Sign In</title>'
            f'<div id="application_config" data-userinfo=\'{{"logged_in":true,"steamid":"{steam_id}"}}\'></div>'
            f'<script>g_steamID = "{steam_id}";</script>'
            '<form id="openidForm" name="loginForm" action="https://steamcommunity.com/openid/login" method="POST">'
            '<input type="hidden" name="action" value="steam_openid_login"><input type="submit" id="imageLogin" value="Sign In"></form>')


class Sites:
    """Stand-ins for SteamDB and Steam, served to one tab through DevTools' Fetch domain, with a record of the pages asked for."""

    def __init__(self, browser: artwork.Browser) -> None:
        self.browser = browser
        self.session = browser.page()
        self.requests = []
        self.steamdb = SIGNED_OUT
        self.steam_account = ACCOUNT
        self.sign_in = openid()
        patterns = [{"urlPattern": "https://steamdb.info/*"}, {"urlPattern": "https://steamcommunity.com/*"}]
        browser.call("Fetch.enable", {"patterns": patterns}, self.session)

    def _answer(self, method: str, url: str):
        parts = urllib.parse.urlsplit(url)
        if parts.netloc == "steamcommunity.com":
            if method == "POST":
                claimed = "https://steamcommunity.com/openid/id/" + self.steam_account
                return 302, STEAMDB + "login/?" + urllib.parse.urlencode({"page": "faq", "openid.mode": "id_res", "openid.claimed_id": claimed})
            return 200, confirmation(self.steam_account)
        if parts.path == "/login/":
            if "openid.mode=id_res" in parts.query:
                self.steamdb = SIGNED_IN
                return 302, STEAMDB
            return 302, self.sign_in
        if parts.path.startswith("/signout"):
            self.steamdb = SIGNED_OUT
            return 200, "<!doctype html><title>Signed out</title>"
        return 200, self.steamdb

    def _serve(self, quiet: float = 2.0) -> None:
        while True:
            event = self.browser.wait_for("Fetch.requestPaused", self.session, timeout=quiet)
            if event is None:
                return
            params = event["params"]
            request = params["request"]
            reply = {"requestId": params["requestId"]}
            if params.get("resourceType") != "Document":
                reply.update(responseCode=404)
            else:
                self.requests.append((request["method"], request["url"]))
                status, content = self._answer(request["method"], request["url"])
                if status == 302:
                    reply.update(responseCode=302, responseHeaders=[{"name": "Location", "value": content}])
                else:
                    reply.update(responseCode=200, responseHeaders=[{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                                 body=base64.b64encode(content.encode("utf-8")).decode("ascii"))
            self.browser.call("Fetch.fulfillRequest", reply, self.session)

    def visit(self, url: str) -> str:
        """Open ``url``, serve every page the tab then asks for, and return the address it settles on."""
        self.browser.evaluate(self.session, f"location.href = {url!r}; true")
        self._serve()
        return self.browser.evaluate(self.session, "location.href")

    def asked(self, method: str, prefix: str) -> int:
        return sum(1 for made, url in self.requests if made == method and url.startswith(prefix))

    def made(self, method: str, url: str) -> int:
        return self.requests.count((method, url))


class SteamDbSignInTests(unittest.TestCase):
    """SteamDB's sign-in extension in a real Chromium, against stand-ins for SteamDB and Steam; skipped where none starts."""

    def setUp(self):
        program = chromium()
        if program is None:
            self.skipTest("no Chromium on this machine")
        self.browser = artwork.Browser(program, timeout=30, extensions=[EXTENSION])
        try:
            self.browser.start()
        except artwork.BrowserError as exc:
            self.skipTest(f"Chromium did not start here: {exc}")
        self.addCleanup(self.browser.close)

    def started(self, signed_in: bool) -> Sites:
        """A tab where Steam started SteamDB for ACCOUNT, as its link does, signed in or not."""
        sites = Sites(self.browser)
        sites.steamdb = SIGNED_IN if signed_in else SIGNED_OUT
        self.assertEqual(sites.visit(f"{STEAMDB}#nonsteamapps={ACCOUNT}"), STEAMDB)
        return sites

    def test_the_account_is_taken_from_the_address_which_is_then_cleaned_and_nothing_signs_in_before_the_first_time(self):
        sites = self.started(signed_in=False)
        self.assertEqual(sites.asked("GET", STEAMDB + "login/"), 0)

    def test_once_signed_in_it_signs_in_again_through_steam_for_its_own_account(self):
        self.started(signed_in=True)
        later = Sites(self.browser)
        self.assertEqual(later.visit(STEAMDB), STEAMDB)
        self.assertEqual(later.made("GET", STEAMDB + "login/?page=faq"), 1)
        self.assertEqual(later.asked("POST", "https://steamcommunity.com/openid/login"), 1)
        self.assertEqual(later.asked("GET", STEAMDB + "login/?page=faq&openid.mode=id_res"), 1)
        self.assertEqual(later.steamdb, SIGNED_IN)

    def test_steam_is_confirmed_for_steamdb_alone_and_only_for_the_account_that_started_it(self):
        self.started(signed_in=False)
        for realm, return_to, account in (("https://example.org/", "https://example.org/return", ACCOUNT),
                                          (STEAMDB, "https://example.org/return", ACCOUNT),
                                          (STEAMDB, STEAMDB + "login/?page=faq", OTHER)):
            with self.subTest(realm=realm, return_to=return_to, account=account):
                sites = Sites(self.browser)
                sites.steam_account = account
                self.assertTrue(sites.visit(openid(realm, return_to)).startswith("https://steamcommunity.com/openid/login?"))
                self.assertEqual(sites.asked("POST", "https://steamcommunity.com/"), 0)
        sites = Sites(self.browser)
        self.assertEqual(sites.visit(openid()), STEAMDB)
        self.assertEqual(sites.asked("POST", "https://steamcommunity.com/openid/login"), 1)

    def test_after_signing_out_on_steamdb_it_stays_signed_out(self):
        sites = self.started(signed_in=True)
        sites.visit(STEAMDB + "signout/")
        later = Sites(self.browser)
        self.assertEqual(later.visit(STEAMDB), STEAMDB)
        self.assertEqual(later.asked("GET", STEAMDB + "login/"), 0)

    def test_a_sign_in_that_fails_is_not_tried_again_until_the_next_start(self):
        self.started(signed_in=True)
        later = Sites(self.browser)
        later.sign_in = STEAMDB
        self.assertEqual(later.visit(STEAMDB), STEAMDB)
        self.assertEqual(later.asked("GET", STEAMDB + "login/"), 1)
        self.assertEqual(later.asked("POST", "https://steamcommunity.com/"), 0)


if __name__ == "__main__":
    unittest.main()
