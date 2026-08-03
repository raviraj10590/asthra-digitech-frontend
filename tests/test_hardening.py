"""Regression locks for the Phase 1C hardening tasks.

Each class corresponds to an audit finding. Offline: no network, no database.
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import config, db, tools                  # noqa: E402


class M1_RegistryNegativeCache(unittest.TestCase):
    """A failed registry read must back off, not be retried on every invoke.

    Without this, one `#status` during a Supabase outage makes two doomed
    reads at 5 s each, plus identity, two audit writes and the replay write —
    enough to exceed the function limit, which costs the 200 to Meta, which
    triggers a retry, which repeats the whole thing.
    """

    def setUp(self):
        self._cache = dict(tools._REGISTRY_CACHE)
        self._exp = tools._REGISTRY_EXPIRES

    def tearDown(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE.update(self._cache)
        tools._REGISTRY_EXPIRES = self._exp

    def _force_outage(self):
        return mock.patch.object(
            db, "select", mock.Mock(side_effect=db.DbError("supabase down")))

    def test_repeated_loads_hit_the_database_only_once(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_EXPIRES = 0.0
        with self._force_outage() as sel:
            for _ in range(10):
                tools._load_registry()
        self.assertEqual(sel.call_count, 1,
                         f"registry hit a dead DB {sel.call_count} times; "
                         "the negative cache is not working")

    def test_backoff_is_shorter_than_the_success_ttl(self):
        """It is a circuit breaker, not a cache. A long back-off would keep
        serving an empty registry — denying everything — after recovery."""
        self.assertLess(config.REGISTRY_FAILURE_BACKOFF, config.REGISTRY_CACHE_TTL)
        self.assertGreater(config.REGISTRY_FAILURE_BACKOFF, 0)

    def test_behaviour_is_unchanged_empty_registry_still_denies(self):
        """The back-off must not alter what the registry ANSWERS, only how
        often it asks."""
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_EXPIRES = 0.0
        with self._force_outage():
            defs = tools._load_registry()
        self.assertEqual(defs, {}, "empty registry must stay empty ⇒ deny-all")

    def test_stale_cache_is_still_served_during_an_outage(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE["leads_today"] = {"code": "leads_today",
                                                "min_role": "STAFF",
                                                "active": True}
        tools._REGISTRY_EXPIRES = 0.0
        with self._force_outage():
            defs = tools._load_registry()
        self.assertIn("leads_today", defs,
                      "a blip must not lose a registry we already had")

    def test_recovery_after_backoff_expires(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_EXPIRES = 0.0
        with self._force_outage():
            tools._load_registry()
        # Simulate the back-off window elapsing.
        tools._REGISTRY_EXPIRES = time.time() - 1
        with mock.patch.object(db, "select",
                               mock.Mock(return_value=[{"code": "x", "active": True}])) as ok:
            defs = tools._load_registry()
        self.assertEqual(ok.call_count, 1, "must retry once the back-off lapses")
        self.assertIn("x", defs)


class M3_RetentionIsWired(unittest.TestCase):
    """bic_rollup_tool_invocations existed since Slice 1A and was never called,
    so the audit table grew without bound."""

    def _digest_source(self):
        path = os.path.join(os.path.dirname(__file__), "..", "api", "digest.py")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_rollup_is_invoked_by_the_existing_cron(self):
        """Assert on the RPC URL, not on any mention of the name.

        The first version of this test matched the string anywhere in the file
        and therefore passed when the CALL was removed but a comment naming it
        remained — the mutation run caught it. Matching prose is not matching
        behaviour.
        """
        self.assertIn("rpc/bic_rollup_tool_invocations", self._digest_source(),
                      "audit-table retention is still unwired")

    def test_replay_prune_is_still_invoked(self):
        self.assertIn("rpc/bic_prune_replay_records", self._digest_source())

    def test_no_new_cron_was_added(self):
        """Vercel Hobby caps at 2 crons and both are in use. Retention rides
        the existing digest job."""
        import json
        path = os.path.join(os.path.dirname(__file__), "..", "vercel.json")
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertLessEqual(len(cfg.get("crons", [])), 2,
                             "exceeded the Hobby cron limit")

    def test_retention_failure_cannot_break_the_digest(self):
        """Housekeeping must never take down the daily report."""
        src = self._digest_source()
        rollup_at = src.index("bic_rollup_tool_invocations")
        after = src[rollup_at:rollup_at + 900]
        self.assertIn("except Exception", after,
                      "rollup failure is not contained")


class Task4_FunctionTimeout(unittest.TestCase):
    """An explicit ceiling, rather than inheriting the platform default."""

    def _cfg(self):
        import json
        path = os.path.join(os.path.dirname(__file__), "..", "vercel.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_webhook_declares_a_max_duration(self):
        cfg = self._cfg()
        build = next(b for b in cfg["builds"] if b["src"] == "api/webhook.py")
        self.assertIn("maxDuration", build.get("config", {}),
                      "webhook inherits an unchosen platform default")

    def test_max_duration_exceeds_the_slowest_measured_tool(self):
        """#aitest measured 7,347 ms in production on 2026-08-03. The ceiling
        must clear that plus audit round trips, with headroom."""
        cfg = self._cfg()
        build = next(b for b in cfg["builds"] if b["src"] == "api/webhook.py")
        self.assertGreaterEqual(build["config"]["maxDuration"], 15)

    def test_max_duration_is_not_unbounded(self):
        """A wedged function should die well inside Meta's patience, not run
        for a minute holding resources."""
        cfg = self._cfg()
        build = next(b for b in cfg["builds"] if b["src"] == "api/webhook.py")
        self.assertLessEqual(build["config"]["maxDuration"], 60)

    def test_functions_and_builds_do_not_coexist(self):
        """Vercel rejects a config containing both."""
        cfg = self._cfg()
        self.assertNotIn("functions", cfg,
                         "`functions` cannot be used alongside `builds`")


if __name__ == "__main__":
    unittest.main(verbosity=2)
