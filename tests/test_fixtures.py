import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("fixtures", Path(__file__).resolve().parents[1] / "services/fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fixtures.DATABASE = Path(self.tmp.name) / "test.sqlite"
        env = patch.dict(os.environ, {"CIAB_FIXTURE_TOKEN": "local-fixture-token"})
        env.start()
        self.addCleanup(env.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), fixtures.Server)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, data=None, token="local-fixture-token"):
        req = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)

    def test_authentication_failures_and_recovery_are_observable(self):
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request("/mail", token="wrong")
        self.assertEqual(failure.exception.code, 401)
        self.request("/reset", {})
        self.assertEqual(len(self.request("/mail")), 1)
        self.request("/fault", {"service": "mailbox", "status": 503})
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request("/mail")
        self.assertEqual(failure.exception.code, 503)
        self.request("/fault", {"service": "mailbox", "status": 0})
        self.assertEqual(len(self.request("/mail")), 1)

    def test_messages_retain_identity_order_and_duplicates_for_delivery_tests(self):
        message = {"ts": "123.000001", "text": "operator instruction", "channel": "C_TEST", "thread": "122.000001"}
        self.request("/messages", message)
        self.request("/messages", message)
        rows = self.request("/messages")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ts"], rows[1]["ts"])
        self.assertEqual(rows[0]["thread"], message["thread"])
        self.request("/fault", {"service": "slack", "status": 429})
        with self.assertRaises(urllib.error.HTTPError):
            self.request("/messages")
        self.assertEqual(len(self.request("/state")["messages"]), 2)

    def test_cloud_fixtures_use_caller_owned_state(self):
        self.request("/cloud", {"account": "123456789012", "pods": {
            "example": {"live": {"id": "example", "status": "RUNNING"}}}})
        self.assertEqual(self.request("/v2/pods/example")["id"], "example")
        req = urllib.request.Request(self.base, data=b"Action=GetCallerIdentity&Version=2011-06-15",
                                     headers={"Authorization": "AWS4-HMAC-SHA256 Credential=CIABLOCAL/local"})
        with urllib.request.urlopen(req, timeout=2) as response:
            self.assertIn(b"<Account>123456789012</Account>", response.read())
        self.request("/fault", {"service": "runpod", "status": 503})
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request("/v2/pods/example")
        self.assertEqual(failure.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
