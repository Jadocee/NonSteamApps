import json
import os
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from nonsteamapps import apps, devtools, signin

ENDS = apps.PSN_SIGN_IN_ENDS
LOGIN = ("https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize?service_entity=urn:service-entity:psn&response_type=code"
         f"&client_id=c&redirect_uri={ENDS}&scope=psn:clientapp referenceDataService:countryConfig.read&request_locale=en_US&duid=d&")


class AddressTests(unittest.TestCase):
    def test_psns_sign_in_starts_where_it_names_the_redirect_page_as_its_return(self):
        self.assertTrue(signin.starts(LOGIN, ENDS))
        self.assertFalse(signin.starts(LOGIN.replace("remoteplay.dl.playstation.net", "remoteplay.example.org"), ENDS))
        self.assertFalse(signin.starts("https://www.playstation.com/", ENDS))
        self.assertFalse(signin.starts(LOGIN, ""))

    def test_the_sign_in_ends_on_the_redirect_page_with_a_code_in_its_query(self):
        self.assertTrue(signin.reached(f"{ENDS}?code=v3.abc&cid=1", ENDS))
        for url in (ENDS, f"{ENDS}?error=access_denied", f"{ENDS}?code=", f"{ENDS}#code=x", f"{ENDS}/other?code=x",
                    "http://remoteplay.dl.playstation.net/remoteplay/redirect?code=x",
                    "https://remoteplay.dl.playstation.net.example.org/remoteplay/redirect?code=x"):
            with self.subTest(url):
                self.assertFalse(signin.reached(url, ENDS))
        self.assertFalse(signin.reached(f"{ENDS}?code=x", ""))


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.from_browser, self.to_browser = os.pipe(), os.pipe()
        self.ended, self.keep = [], True
        self.watch = signin.Watch(self.from_browser[0], self.to_browser[1], ENDS, self.on_end)
        self.addCleanup(self.watch.close)
        self.addCleanup(self.close, [self.from_browser[1], self.to_browser[0]])

    def close(self, fds):
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass

    def on_end(self, url):
        self.ended.append(url)
        return self.keep

    def sent(self):
        found, rest = devtools.messages(os.read(self.to_browser[0], 1 << 16))
        self.assertEqual(rest, b"")
        return [(message["id"], message["method"], message["params"]) for message in found]

    def say(self, *messages, raw=b""):
        os.write(self.from_browser[1], raw + b"".join(json.dumps(message).encode("utf-8") + b"\0" for message in messages))
        return self.watch.handle()

    @staticmethod
    def page(url, method="Target.targetInfoChanged", kind="page"):
        return {"method": method, "params": {"targetInfo": {"targetId": "t", "type": kind, "url": url}}}

    def test_once_a_page_reaches_the_end_with_a_code_its_address_is_handed_on_and_the_window_closed(self):
        self.assertEqual(self.watch.fileno(), self.from_browser[0])
        self.assertEqual(self.sent(), [(1, "Target.setDiscoverTargets", {"discover": True})])
        self.assertTrue(self.say({"id": 1, "result": {}}, self.page(LOGIN, "Target.targetCreated"), self.page(f"{ENDS}?code=c", kind="iframe"),
                                 self.page(f"{ENDS}?error=e"), {"method": "Target.targetInfoChanged", "params": []}, raw=b"not json\0"))
        self.assertEqual(self.ended, [])
        self.assertTrue(self.say(raw=json.dumps(self.page(f"{ENDS}?code=c&cid=1")).encode()[:20]))
        self.assertTrue(self.say(self.page(f"{ENDS}?code=d"), raw=json.dumps(self.page(f"{ENDS}?code=c&cid=1")).encode()[20:] + b"\0"))
        self.assertEqual(self.ended, [f"{ENDS}?code=c&cid=1"])
        self.assertEqual(self.sent(), [(2, "Browser.close", {})])
        self.close([self.from_browser[1]])
        self.assertFalse(self.watch.handle())

    def test_a_window_whose_address_could_not_be_handed_on_stays_open(self):
        self.keep = False
        self.sent()
        self.assertTrue(self.say(self.page(f"{ENDS}?code=c")))
        self.assertTrue(self.say(self.page(f"{ENDS}?code=d")))
        self.assertEqual(self.ended, [f"{ENDS}?code=c"])
        os.set_blocking(self.to_browser[0], False)
        with self.assertRaises(BlockingIOError):
            os.read(self.to_browser[0], 1)

    def test_closing_the_watch_closes_its_pipe(self):
        self.watch.close()
        self.assertEqual(os.read(self.to_browser[0], 1 << 16).count(b"\0"), 1)
        self.assertEqual(os.read(self.to_browser[0], 1), b"")
        self.watch.close()


class DevToolsTests(unittest.TestCase):
    def test_commands_and_messages_end_in_a_nul(self):
        self.assertEqual(json.loads(devtools.command(3, "Page.enable", session="s")[:-1]), {"id": 3, "method": "Page.enable", "params": {}, "sessionId": "s"})
        self.assertEqual(devtools.messages(b'{"id":1}\0[]\0{\0{"method"'), ([{"id": 1}, []], b'{"method"'))
        self.assertEqual(devtools.messages(b"x" * (devtools.MAX_BUFFER + 1)), ([], b""))

    def test_a_program_started_with_the_pipe_reads_it_on_3_and_writes_on_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "browser"
            program.write_text(
                "#!/usr/bin/env python3\nimport os, sys\n"
                "data = b''\n"
                "while not data.endswith(b'\\0'):\n"
                "    chunk = os.read(3, 1)\n"
                "    if not chunk:\n        break\n"
                "    data += chunk\n"
                "os.write(4, data[:-1].upper() + b'\\0' + ' '.join(sys.argv[1:]).encode() + b'\\0')\n"
            )
            program.chmod(0o755)
            process, reader, writer = devtools.spawn(program, [devtools.SWITCH, "about:blank"])
            try:
                os.write(writer, b'{"id":1}\0')
                answer = b""
                while answer.count(b"\0") < 2:
                    chunk = os.read(reader, 1 << 16)
                    if not chunk:
                        break
                    answer += chunk
                self.assertEqual(answer, b'{"ID":1}\0--remote-debugging-pipe about:blank\0')
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                os.close(reader)
                os.close(writer)


if __name__ == "__main__":
    unittest.main()
