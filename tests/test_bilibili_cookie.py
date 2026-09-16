"""Logged-in crawling for the CLI/MCP path, which was anonymous-only.

Bilibili only attaches reply_control.location to a request that carries a
session, so without a cookie every crawl returns empty IP locations and the
region chart cannot have data. These tests pin the wiring end to end over
loopback HTTP, and pin that a cookie is treated as the credential it is.
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bilibili_crawler.api import bilibili_api
from bilibili_crawler.api.bilibili_api import BilibiliAPI
from bilibili_crawler.crawler.comment_crawler import CommentCrawler
from bilibili_crawler.service import credentials as creds
from bilibili_crawler.service.agent_service import AgentService
from bilibili_crawler.service.diagnostics import diagnose
from bilibili_crawler.service.run_store import RunStore

SESSDATA = "cookie-canary-sessdata-0123456789"
COOKIE = f"SESSDATA={SESSDATA}; bili_jct=cookie-canary-jct-0123456789; buvid3=not-a-secret"


class Handler(BaseHTTPRequestHandler):
    """Stands in for api.bilibili.com, echoing what the session actually sent."""

    seen_cookies: list[str] = []

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's contract
        self.seen_cookies.append(self.headers.get("Cookie") or "")
        # Only a request carrying a session gets a location, exactly like the
        # real endpoint. A fake that always returned one would let an
        # unauthenticated crawl pass this test.
        authenticated = "SESSDATA=" in (self.headers.get("Cookie") or "")
        control = {"location": "IP属地：上海"} if authenticated else {}
        body = json.dumps(
            {
                "code": 0,
                "data": {
                    "replies": [
                        {
                            "rpid": 1,
                            "rcount": 0,
                            "content": {"message": "一条评论"},
                            "member": {"uname": "某人"},
                            "reply_control": control,
                        }
                    ],
                    "cursor": {"is_end": True, "next": 0},
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class CookieResolutionTests(unittest.TestCase):
    def setUp(self):
        # Only the cookie is cleared: wiping the whole environment takes
        # HOME/USERPROFILE with it, and the profile lookup needs those.
        self.env = patch.dict(os.environ, {})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(creds.ENV_COOKIE, None)

    def test_explicit_value_wins_over_the_environment(self):
        os.environ[creds.ENV_COOKIE] = "SESSDATA=from-env-value-0123456789"
        self.assertEqual(creds.resolve_bilibili_cookie("SESSDATA=explicit-value-0123456789"),
                         "SESSDATA=explicit-value-0123456789")

    def test_environment_is_used_when_no_flag_is_given(self):
        os.environ[creds.ENV_COOKIE] = COOKIE
        self.assertEqual(creds.resolve_bilibili_cookie(), COOKIE)

    def test_missing_cookie_resolves_to_empty_rather_than_failing(self):
        self.assertEqual(creds.resolve_bilibili_cookie(), "")

    def test_session_values_are_scrubbed_but_device_ids_are_not(self):
        creds.resolve_bilibili_cookie(COOKIE)
        scrubbed = creds.scrub(f"upstream said {SESSDATA} was rejected")
        self.assertNotIn(SESSDATA, scrubbed)
        self.assertIn(creds.REDACTED, scrubbed)
        # buvid3 is device fingerprinting, not a session; scrubbing it would
        # blank harmless substrings out of unrelated text.
        self.assertIn("not-a-secret", creds.scrub("buvid3=not-a-secret"))

    def test_status_reports_presence_without_revealing_values(self):
        status = creds.cookie_status(COOKIE)
        self.assertTrue(status["configured"])
        self.assertTrue(status["has_sessdata"])
        self.assertNotIn(SESSDATA, json.dumps(status, ensure_ascii=False))

    def test_a_cookie_without_sessdata_is_not_a_login(self):
        status = creds.cookie_status("buvid3=abc; bili_jct=def")
        self.assertTrue(status["configured"])
        self.assertFalse(status["has_sessdata"])

    def test_doctor_reports_login_state_without_the_cookie(self):
        os.environ[creds.ENV_COOKIE] = COOKIE
        payload = diagnose()
        self.assertTrue(payload["bilibili_login"]["configured"])
        self.assertTrue(payload["bilibili_login"]["has_sessdata"])
        self.assertNotIn(SESSDATA, json.dumps(payload, ensure_ascii=False))

    def test_doctor_says_why_the_region_chart_will_be_empty(self):
        payload = diagnose()
        self.assertFalse(payload["bilibili_login"]["configured"])
        self.assertIn("匿名", payload["bilibili_login"]["note"])


class ServiceWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"BILIBILI_AGENT_RUNS_DIR": self.temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_the_services_own_api_carries_the_cookie(self):
        service = AgentService(store=RunStore(), cookie=COOKIE)
        self.assertEqual(service._api.session.headers.get("Cookie"), COOKIE)

    def test_an_injected_api_is_never_given_a_cookie(self):
        # The desktop drives QR login on the object it injects. Writing a
        # header here would replace the session the user just logged into.
        injected = BilibiliAPI()
        injected.set_cookie("SESSDATA=desktop-session-value-0123456789")
        with patch.dict(os.environ, {creds.ENV_COOKIE: COOKIE}):
            service = AgentService(store=RunStore(), api=injected)
        self.assertEqual(injected.session.headers.get("Cookie"),
                         "SESSDATA=desktop-session-value-0123456789")
        self.assertTrue(service._api_is_foreign)

    def test_a_cookieless_service_owns_an_anonymous_session(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(creds.ENV_COOKIE, None)
            service = AgentService(store=RunStore())
        self.assertFalse(service._api_is_foreign)
        self.assertEqual(service._cookie, "")
        self.assertIsNone(service._api.session.headers.get("Cookie"))


class LiveLoopbackTests(unittest.TestCase):
    """A real HTTP round trip: the header has to survive the whole stack."""

    def setUp(self):
        # A default RunStore() resolves the checkout's own analysis-runs and
        # probes it for writability. No run is written here, but #53 made
        # keeping the tests out of that directory the rule, not a detail.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        runs = patch.dict(os.environ, {"BILIBILI_AGENT_RUNS_DIR": self.temp.name})
        runs.start()
        self.addCleanup(runs.stop)

        Handler.seen_cookies = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        base = f"http://127.0.0.1:{self.server.server_port}"
        for name in ("COMMENT_API_URL", "COMMENT_WBI_API_URL", "REPLY_API_URL"):
            patcher = patch.object(bilibili_api, name, f"{base}/{name}")
            patcher.start()
            self.addCleanup(patcher.stop)
        # The adaptive delay would add a second per request for no benefit here.
        sleep = patch.object(BilibiliAPI, "_adaptive_sleep", lambda *a, **k: None)
        sleep.start()
        self.addCleanup(sleep.stop)

    def crawl(self, api):
        crawler = CommentCrawler(progress_callback=lambda _message: None, api=api)
        with patch.object(CommentCrawler, "resolve_target", lambda self, target: _Target()):
            return crawler.crawl_comments("BV1xx411c7mD", include_replies=False, max_pages=1)

    def test_an_anonymous_crawl_gets_no_ip_location(self):
        comments = self.crawl(BilibiliAPI())
        self.assertEqual([c["ip_location"] for c in comments], [""])
        self.assertNotIn("SESSDATA=", Handler.seen_cookies[0])

    def test_a_cookie_reaches_bilibili_and_yields_ip_location(self):
        api = BilibiliAPI()
        api.set_cookie(COOKIE)
        comments = self.crawl(api)

        self.assertTrue(Handler.seen_cookies)
        self.assertIn(f"SESSDATA={SESSDATA}", Handler.seen_cookies[0])
        # The prefix Bilibili puts on the value is stripped on the way in.
        self.assertEqual([c["ip_location"] for c in comments], ["上海"])

    def test_the_service_path_is_wired_the_same_way(self):
        service = AgentService(store=RunStore(Path(self.temp.name)), cookie=COOKIE)
        comments = self.crawl(service._api)
        self.assertEqual([c["ip_location"] for c in comments], ["上海"])


class _Target:
    """What resolve_target returns for a video, without a metadata request."""

    content_type = 1
    oid = 12345
    bvid = "BV1xx411c7mD"
    uid = None
    raw_input = "BV1xx411c7mD"


if __name__ == "__main__":
    unittest.main()
