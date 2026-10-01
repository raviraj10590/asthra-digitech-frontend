"""Brain Health snapshot (brain_health.py + api/health_snapshot.py).

The snapshot is the ONLY Brain data the CRM's Brain Health page sees, so the
tests pin two things: the numbers are right, and nothing identifying a
customer can get into it. Offline.
"""
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import requests                                    # noqa: E402
import brain_health as bh                          # noqa: E402
import health_snapshot as hs                       # noqa: E402

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)


def at(**kw):
    return (NOW - timedelta(**kw)).isoformat()


EVENTS = [
    {"state": "COMPLETED", "failure_class": None, "created_at": at(minutes=60),
     "completed_at": at(minutes=59, seconds=55), "updated_at": at(minutes=59)},
    {"state": "COMPLETED", "failure_class": None, "created_at": at(minutes=50),
     "completed_at": at(minutes=49, seconds=25), "updated_at": at(minutes=49)},
    {"state": "FAILED", "failure_class": "VALUE", "created_at": at(minutes=40),
     "completed_at": at(minutes=39, seconds=50), "updated_at": at(minutes=39)},
    {"state": "PROCESSING", "failure_class": None, "created_at": at(minutes=30),
     "completed_at": None, "updated_at": at(minutes=30)},          # stuck
    {"state": "PROCESSING", "failure_class": None, "created_at": at(minutes=2),
     "completed_at": None, "updated_at": at(minutes=2)},           # still running
]
HEALTH = ("at=2026-10-01T04:22:48+00:00 probe=OK token=OK days_left=45 "
          "quiet_daytime_hours=1 silence_alarm=False ads=ADS_OK")
RECOVERY = ["RECOVERY::wamid.HBgMOTE5OTk5::attempt=1::prev=FAILED::reason=failed:VALUE",
            "RECOVERY::wamid.HBgMOTE5OTk5::final=HUMAN_REVIEW",
            "RECOVERY::wamid.OTHER::final=RECONCILED_REPLY_EXISTS"]


def sample(**over):
    kw = dict(now=NOW, events_24h=EVENTS, last_event_at=at(minutes=2), accepted_total=3,
              recovery_contents=RECOVERY, health_value=HEALTH,
              sweep={"REDRIVEN": 1}, commit="33f48e1abcdef", source="recovery")
    kw.update(over)
    return bh.build(**kw)


class Numbers(unittest.TestCase):
    def test_events(self):
        e = sample()["events"]
        self.assertEqual(e["total"], 5)
        self.assertEqual(e["by_state"], {"COMPLETED": 2, "FAILED": 1, "PROCESSING": 2})
        self.assertEqual(e["failed_by_class"], {"VALUE": 1})
        self.assertEqual(e["stuck_processing"], 1, "only the one past 600 s")
        self.assertEqual(e["duration_s"], {"p50": 10.0, "p90": 35.0, "max": 35.0})
        self.assertEqual(e["accepted_unresolved"], 3)

    def test_recovery_and_sweep(self):
        r = sample()["recovery"]
        self.assertEqual(r["attempts_7d"], 1)
        self.assertEqual(r["final_7d"], {"HUMAN_REVIEW": 1, "RECONCILED_REPLY_EXISTS": 1})
        self.assertEqual(r["last_sweep"], {"REDRIVEN": 1})

    def test_health_check_is_parsed_into_known_fields_only(self):
        h = sample(health_value=HEALTH + " token_value=SECRET")["health_check"]
        self.assertEqual(h["days_left"], 45)
        self.assertIs(h["silence_alarm"], False)
        self.assertEqual(h["probe"], "OK")
        self.assertNotIn("token_value", h)

    def test_the_shadow_table_is_not_part_of_health(self):
        """It has no production reader by design; this must not become one."""
        self.assertNotIn("shadow", sample())
        src = open(os.path.join(ROOT, "api", "health_snapshot.py")).read()
        self.assertNotIn("bairavi_shadow_interpretations", src)

    def test_empty_world(self):
        s = sample(events_24h=[], recovery_contents=[], health_value=None,
                   sweep={}, commit="", last_event_at=None)
        self.assertEqual(s["events"]["total"], 0)
        self.assertEqual(s["events"]["duration_s"], {"p50": None, "p90": None, "max": None})
        self.assertEqual(s["health_check"], {})
        self.assertIsNone(s["deployment"]["commit"])

    def test_postgres_timestamp_shapes(self):
        for v in ("2026-08-20 02:49:21.62012+00", "2026-08-20T02:49:21Z"):
            self.assertIsNotNone(bh._ts(v), v)


class NothingIdentifying(unittest.TestCase):
    def test_no_phone_wamid_or_text_survives(self):
        text = json.dumps(sample())
        self.assertNotIn("wamid", text.lower())
        self.assertNotIn("HBgM", text)
        self.assertIsNone(re.search(r"\d{9,}", text), "no phone-length digit run")

    def test_the_collector_reads_only_named_columns(self):
        calls = []

        def get(url, headers=None, params=None, timeout=None):
            calls.append((url, dict(params)))
            r = mock.Mock(ok=True)
            r.raise_for_status = lambda: None
            r.json = lambda: []
            return r
        with mock.patch.object(requests, "get", get), \
             mock.patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": "test-key"}):
            hs.collect({}, now=NOW)
        for url, params in calls:
            self.assertIn("select", params, url)
            self.assertNotIn("*", params["select"], url)
        settings = [p for u, p in calls if u.endswith("/app_settings")]
        self.assertEqual(settings, [{"key": "eq.bot_health_last_check", "select": "value", "limit": "1"}])
        self.assertTrue(all(c[0].startswith(hs.SUPABASE_URL) for c in calls))


class Publishing(unittest.TestCase):
    def test_writes_one_owner_row_to_the_crm(self):
        sent = []

        def post(url, headers=None, json=None, timeout=None):
            sent.append((url, headers, json))
            return mock.Mock(ok=True, status_code=201)
        env = {"CRM_SUPABASE_URL": "https://crm.test", "CRM_SUPABASE_SERVICE_KEY": "crm-key",
               "CRM_OWNER_USER_ID": "owner-uid"}
        with mock.patch.object(requests, "post", post), mock.patch.dict(os.environ, env):
            self.assertTrue(hs.publish(sample()))
        url, headers, body = sent[0]
        self.assertEqual(url, "https://crm.test/rest/v1/brain_health_snapshots")
        self.assertEqual(body["user_id"], "owner-uid")
        self.assertEqual(body["source"], "recovery")
        self.assertEqual(body["snapshot"]["schema"], 1)

    def test_not_configured_is_a_skip_not_a_crash(self):
        with mock.patch.dict(os.environ, {"CRM_SUPABASE_URL": ""}):
            self.assertFalse(hs.publish(sample()))

    def test_run_never_raises_and_logs_no_detail(self):
        import io
        from contextlib import redirect_stdout
        def boom(*a, **k):
            raise RuntimeError("relation app_settings 919999000888")
        with mock.patch.object(hs, "collect", boom), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hs.run({}), "failed")
        self.assertNotIn("919999000888", out.getvalue())
        self.assertIn("type=RuntimeError", out.getvalue())

    def test_a_crm_rejection_logs_status_only(self):
        import io
        from contextlib import redirect_stdout
        resp = mock.Mock(ok=False, status_code=401, text="body echoing secrets")
        env = {"CRM_SUPABASE_URL": "https://crm.test", "CRM_SUPABASE_SERVICE_KEY": "crm-key",
               "CRM_OWNER_USER_ID": "owner-uid"}
        with mock.patch.object(requests, "post", lambda *a, **k: resp), \
             mock.patch.dict(os.environ, env), redirect_stdout(io.StringIO()) as out:
            self.assertFalse(hs.publish(sample()))
        self.assertIn("status=401", out.getvalue())
        self.assertNotIn("body echoing", out.getvalue())
        self.assertNotIn("crm-key", out.getvalue())


if __name__ == "__main__":
    unittest.main()
