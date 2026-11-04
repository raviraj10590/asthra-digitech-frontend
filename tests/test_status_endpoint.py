"""GET /api/status — the two facts the owner's Uptime Kuma watches (2026-11-05)."""
import io
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import status  # noqa: E402

NOW = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)


class Arithmetic(unittest.TestCase):
    def test_days_left(self):
        self.assertEqual(status.days_left(NOW.timestamp() + 9 * 86400 + 100, NOW), 9)
        self.assertEqual(status.days_left(NOW.timestamp() - 10, NOW), -1)
        self.assertIsNone(status.days_left(0, NOW))         # permanent system-user token
        self.assertIsNone(status.days_left(None, NOW))

    def test_minutes_since(self):
        self.assertEqual(status.minutes_since("2026-11-05T05:53:30+00:00", NOW), 6)
        self.assertIsNone(status.minutes_since(None, NOW))
        self.assertIsNone(status.minutes_since("not a time", NOW))


def call(path):
    h = status.handler.__new__(status.handler)
    h.path, h.wfile, h.requestline, h.request_version = path, io.BytesIO(), "GET", "HTTP/1.1"
    h.send_response = lambda code: setattr(h, "code", code)
    h.send_header = lambda *a: None
    h.end_headers = lambda: None
    h.do_GET()
    return h.code, json.loads(h.wfile.getvalue())


class Endpoint(unittest.TestCase):
    def test_recovery_only_never_calls_meta(self):
        with mock.patch.object(status, "recovery_status", lambda: {"minutes_ago": 4}), \
             mock.patch.object(status, "whatsapp_status", side_effect=AssertionError("Meta called")):
            code, out = call("/api/status?only=recovery")
        self.assertEqual((code, out), (200, {"recovery": {"minutes_ago": 4}}))

    def test_both_and_nothing_secret(self):
        with mock.patch.object(status, "recovery_status", lambda: {"minutes_ago": 2}), \
             mock.patch.object(status, "whatsapp_status",
                               lambda: {"ok": True, "state": "OK", "days_left": 10}):
            code, out = call("/api/status")
        self.assertEqual(out["whatsapp"], {"ok": True, "state": "OK", "days_left": 10})
        self.assertEqual(set(out), {"recovery", "whatsapp"})

    def test_a_failing_probe_reads_as_not_ok(self):
        with mock.patch.object(status, "recovery_status", lambda: {"minutes_ago": 2}), \
             mock.patch.object(status, "whatsapp_status", side_effect=RuntimeError("x")):
            out = call("/api/status")[1]
        self.assertFalse(out["whatsapp"]["ok"])


if __name__ == "__main__":
    unittest.main()
