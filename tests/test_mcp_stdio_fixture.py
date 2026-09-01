"""Check the test-only network guard without making any network calls."""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_stdio" / "sitecustomize.py"


class StdioNetworkGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("stdio_fixture", FIXTURE)
        self.fixture = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BILIBILI_TEST_MCP_STDIO": "0"}):
            spec.loader.exec_module(self.fixture)

    def test_only_literal_loopback_addresses_pass_all_network_entrypoints(self):
        for host in ("127.0.0.1", "::1", "example.invalid", "203.0.113.1", "0.0.0.0", None):
            events = [
                ("socket.getaddrinfo", (host, 80, 0, 0, 0)),
                ("socket.gethostbyname", (host,)), ("socket.gethostbyaddr", (host,)),
                ("socket.getnameinfo", ((host, 80), 0)),
                *((event, (object(), (host, 80))) for event in
                  ("socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg")),
            ]
            for event, args in events:
                with self.subTest(host=host, event=event):
                    if host in {"127.0.0.1", "::1"} and event not in {"socket.gethostbyaddr", "socket.getnameinfo"}:
                        self.fixture.guard_network(event, args)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "only permits loopback"):
                            self.fixture.guard_network(event, args)

    def test_installed_hook_rejects_synthetic_dns_and_udp_events_before_io(self):
        # Install in a disposable interpreter: audit hooks cannot be removed.
        # sys.audit exercises dispatch without ever asking the OS to resolve or
        # send; all external addresses here are documentation-only examples.
        code = """
import runpy, sys
guard = runpy.run_path(sys.argv[1])["guard_network"]
sys.addaudithook(guard)
for event, args in (
    ("socket.getaddrinfo", ("example.invalid", 80, 0, 0, 0)),
    ("socket.sendto", (None, ("203.0.113.1", 80))),
):
    try:
        sys.audit(event, *args)
    except RuntimeError as exc:
        assert str(exc) == "stdio test only permits loopback network"
    else:
        raise AssertionError("external network event was accepted")
"""
        child = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(FIXTURE)],
                               env={**os.environ, "BILIBILI_TEST_MCP_STDIO": "0"},
                               capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
