"""The daily digest keeps business evidence fresh.

    biz.pipeline.new_enquiries_per_month@1 is volatility `fast` (24h). A value
    nobody recomputes goes STALE within a day and 2H stops accepting it, so
    the fact is only useful if something refreshes it. That something is the
    EXISTING daily cron — Vercel Hobby caps at 2 and both are in use, so this
    rides the digest as a fourth best-effort block rather than a third cron.

THE TWO PROPERTIES THAT MATTER
------------------------------
1. A failure must never fabricate a zero. record() returns None when the store
   refuses; if the digest turned that into a recorded 0 it would read as "no
   enquiries this month" — the precise falsehood this predicate exists to
   avoid. test_a_failure_records_no_value pins it.

2. Running daily must SUPERSEDE, not accumulate. valid_from is the measurement
   instant, so today's reading replaces yesterday's. If it conflicted instead,
   the fact would go `contested` and 2H would return CLARIFY forever.

Deterministic clocks only — no test here depends on wall-clock time.

Offline: no network, no AI, no real database.
"""

import io
import os
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import digest as dg                                               # noqa: E402
from bic import claims as c                                       # noqa: E402
from bic import context as ctx                                    # noqa: E402
from bic import knowledge, party as pt, policy                    # noqa: E402
from bic import pipeline_evidence as pe                           # noqa: E402
from bic import registry as r                                     # noqa: E402
from tests.test_pipeline_evidence import Store, T, OTHER_T        # noqa: E402


class Base(unittest.TestCase):
    """Real producer, real claims/registry logic, fake store and fake clock."""

    def setUp(self):
        self.db = Store()
        self._p = [mock.patch.object(m, fn, getattr(self.db, fn))
                   for m in (c, pt, r) for fn in ("select", "insert", "update")
                   if hasattr(m, fn)]
        for p in self._p:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self._p)])
        r.register("core.party", "first_seen_at", 1, "TEMPORAL",
                   {"type": "timestamp"}, "First seen at",
                   volatility_class="static")
        r.activate("core.party", "first_seen_at", 1, "test")
        r.register("biz.pipeline", "new_enquiries_per_month", 1, "QUANTITATIVE",
                   {"type": "number", "min": 0}, "New enquiries per month",
                   unit="count", volatility_class="fast",
                   applies_to=["ORGANIZATION"])
        r.activate("biz.pipeline", "new_enquiries_per_month", 1, "test")

    def seen(self, when, tenant=T):
        p = pt.resolve_or_create(tenant, pt.WHATSAPP, f"p-{uuid.uuid4()}")
        c.assert_claim(tenant, p, pe.SOURCE_PREDICATE, when.isoformat(),
                       source="whatsapp", provenance_tier=1, asserted_by="test",
                       valid_from=when, observed_at=when)
        return p

    def run_digest_block(self, at, tenant=T):
        """Execute ONLY the pipeline-evidence block of the daily digest, with
        a frozen clock. The rest of do_GET makes network calls."""
        out = {"claim": None, "log": ""}
        buf = io.StringIO()
        with mock.patch.object(pe, "_now", lambda: at), redirect_stdout(buf):
            out["claim"] = dg.bic_pipeline_evidence.record(tenant)
        out["log"] = buf.getvalue()
        return out


# ── the integration itself ─────────────────────────────────────────────

class Wiring(unittest.TestCase):

    def test_the_digest_imports_the_producer(self):
        self.assertTrue(hasattr(dg, "bic_pipeline_evidence"))
        self.assertIs(dg.bic_pipeline_evidence, pe)

    def test_the_digest_calls_record_exactly_once_per_run(self):
        import inspect
        src = inspect.getsource(dg.handler.do_GET)
        self.assertEqual(src.count("bic_pipeline_evidence.record("), 1)

    def test_it_is_guarded_by_BIC_AVAILABLE(self):
        import inspect
        src = inspect.getsource(dg.handler.do_GET)
        block = src[src.index("bic pipeline evidence"):]
        self.assertIn("if BIC_AVAILABLE:", src[:src.index("bic_pipeline_evidence.record(")])
        self.assertIn("except Exception", block)

    def test_no_new_scheduler_was_added(self):
        import json, pathlib
        crons = json.loads(pathlib.Path(
            os.path.join(os.path.dirname(__file__), "..", "vercel.json")
        ).read_text()).get("crons", [])
        self.assertEqual(len(crons), 2)
        self.assertEqual(crons[0]["schedule"], "30 3 * * *")

    def test_it_uses_the_default_tenant_like_every_other_digest_block(self):
        import inspect
        src = inspect.getsource(dg.handler.do_GET)
        seg = src[src.index("bic_pipeline_evidence.record("):]
        self.assertIn("bic_config.DEFAULT_TENANT_ID", seg[:200])


# ── freshness across a scheduled run ───────────────────────────────────

class Freshness(Base):

    DAY1 = datetime(2026, 8, 10, 3, 30, tzinfo=timezone.utc)   # 09:00 IST

    def test_recording_today_is_FRESH(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY1)
        env = knowledge.describe(T, pe.business_subject(T), [pe.PREDICATE],
                                 as_of=self.DAY1 + timedelta(hours=1))
        v = {x["predicate"]: x for x in env["values"]}[pe.PREDICATE]
        self.assertEqual(v["freshness"]["verdict"], "FRESH")

    def test_it_goes_STALE_past_the_fast_bound(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY1)
        env = knowledge.describe(T, pe.business_subject(T), [pe.PREDICATE],
                                 as_of=self.DAY1 + timedelta(hours=30))
        v = {x["predicate"]: x for x in env["values"]}[pe.PREDICATE]
        self.assertEqual(v["freshness"]["verdict"], "STALE")

    def test_the_next_scheduled_run_restores_FRESH(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY1)
        day2 = self.DAY1 + timedelta(days=1)
        self.run_digest_block(day2)
        env = knowledge.describe(T, pe.business_subject(T), [pe.PREDICATE],
                                 as_of=day2 + timedelta(hours=1))
        v = {x["predicate"]: x for x in env["values"]}[pe.PREDICATE]
        self.assertEqual(v["freshness"]["verdict"], "FRESH")

    def test_daily_runs_never_conflict(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        for d in range(5):
            self.run_digest_block(self.DAY1 + timedelta(days=d))
        cur = c.current(T, pe.business_subject(T), pe.PREDICATE,
                        as_of=self.DAY1 + timedelta(days=5))
        self.assertFalse(cur["conflict"])
        self.assertEqual(len(cur["claims"]), 1)

    def test_the_value_tracks_new_parties_across_days(self):
        self.seen(datetime(2026, 8, 2, tzinfo=timezone.utc))
        r1 = self.run_digest_block(self.DAY1)["claim"]
        self.assertEqual(str(r1["value"]), "1")
        self.seen(datetime(2026, 8, 11, tzinfo=timezone.utc))
        r2 = self.run_digest_block(self.DAY1 + timedelta(days=2))["claim"]
        self.assertEqual(str(r2["value"]), "2")


# ── failure semantics ──────────────────────────────────────────────────

class Failure(Base):

    DAY = datetime(2026, 8, 10, 3, 30, tzinfo=timezone.utc)

    def test_a_failure_records_no_value(self):
        """THE ONE THAT MATTERS. A false zero reads as 'no enquiries'."""
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        from bic.db import DbError
        with mock.patch.object(c, "assert_claim", side_effect=DbError("down")):
            res = self.run_digest_block(self.DAY)
        self.assertIsNone(res["claim"])
        rows = [x for x in self.db.rows
                if x.get("predicate_concept") == "new_enquiries_per_month"]
        self.assertEqual(rows, [], "a failed run must write nothing at all")

    def test_a_failure_leaves_the_previous_measurement_standing(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        good = self.run_digest_block(self.DAY)["claim"]
        from bic.db import DbError
        with mock.patch.object(c, "assert_claim", side_effect=DbError("down")):
            self.run_digest_block(self.DAY + timedelta(days=1))
        cur = c.current(T, pe.business_subject(T), pe.PREDICATE,
                        as_of=self.DAY + timedelta(days=1, hours=1))
        self.assertEqual(len(cur["claims"]), 1)
        self.assertEqual(cur["claims"][0]["claim_id"], good["claim_id"])

    def test_a_failure_does_not_raise_out_of_the_producer(self):
        from bic.db import DbError
        with mock.patch.object(c, "assert_claim", side_effect=DbError("down")):
            self.assertIsNone(pe.record(T, observed_at=self.DAY, at=self.DAY))

    def test_zero_parties_records_an_honest_zero(self):
        """Distinguishes 'measured zero' from 'failed to measure'."""
        res = self.run_digest_block(self.DAY)
        self.assertIsNotNone(res["claim"])
        self.assertEqual(str(res["claim"]["value"]), "0")


# ── boundaries ─────────────────────────────────────────────────────────

class Boundaries(Base):

    def test_a_run_on_the_1st_measures_the_new_month(self):
        self.seen(datetime(2026, 8, 20, tzinfo=timezone.utc))          # August
        sept1 = datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc)       # 09:00 IST
        claim = self.run_digest_block(sept1)["claim"]
        self.assertEqual(str(claim["value"]), "0", "August must not leak in")

    def test_a_run_on_the_last_day_still_measures_that_month(self):
        self.seen(datetime(2026, 8, 20, tzinfo=timezone.utc))
        aug31 = datetime(2026, 8, 31, 3, 30, tzinfo=timezone.utc)
        claim = self.run_digest_block(aug31)["claim"]
        self.assertEqual(str(claim["value"]), "1")

    def test_year_rollover(self):
        self.seen(datetime(2026, 12, 20, tzinfo=timezone.utc))
        jan1 = datetime(2027, 1, 1, 3, 30, tzinfo=timezone.utc)
        self.assertEqual(str(self.run_digest_block(jan1)["claim"]["value"]), "0")

    def test_leap_february(self):
        self.seen(datetime(2028, 2, 29, tzinfo=timezone.utc))
        feb29 = datetime(2028, 2, 29, 6, 0, tzinfo=timezone.utc)
        self.assertEqual(str(self.run_digest_block(feb29)["claim"]["value"]), "1")

    def test_the_producer_never_uses_machine_local_time(self):
        import inspect
        src = inspect.getsource(pe)
        self.assertNotIn("astimezone()", src)
        self.assertNotIn("datetime.now()", src)
        self.assertIn("timezone(timedelta(hours=5, minutes=30))", src)

    def test_tenant_isolation_across_a_scheduled_run(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc), tenant=T)
        self.seen(datetime(2026, 8, 6, tzinfo=timezone.utc), tenant=OTHER_T)
        self.seen(datetime(2026, 8, 7, tzinfo=timezone.utc), tenant=OTHER_T)
        day = datetime(2026, 8, 10, 3, 30, tzinfo=timezone.utc)
        a = self.run_digest_block(day, tenant=T)["claim"]
        b = self.run_digest_block(day, tenant=OTHER_T)["claim"]
        self.assertEqual(str(a["value"]), "1")
        self.assertEqual(str(b["value"]), "2")


# ── idempotency ────────────────────────────────────────────────────────

class Idempotency(Base):

    DAY = datetime(2026, 8, 10, 3, 30, tzinfo=timezone.utc)

    def test_two_runs_at_the_same_instant_do_not_corrupt_state(self):
        """Same measurement instant: identical valid_from, so this is the
        exact shape that used to produce a permanent conflict."""
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY)
        self.run_digest_block(self.DAY)
        cur = c.current(T, pe.business_subject(T), pe.PREDICATE,
                        as_of=self.DAY + timedelta(hours=1))
        self.assertEqual(len(cur["claims"]), 1,
                         "a same-instant re-run must not leave two live claims")
        self.assertFalse(cur["conflict"])

    def test_repeated_runs_are_deterministic(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        vals = [str(self.run_digest_block(self.DAY + timedelta(hours=i))["claim"]["value"])
                for i in range(1, 4)]
        self.assertEqual(vals, ["1", "1", "1"])

    def test_the_business_party_is_never_duplicated(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        for d in range(3):
            self.run_digest_block(self.DAY + timedelta(days=d))
        orgs = [p for p in self.db.parties if p["kind"] == pt.ORGANIZATION]
        self.assertEqual(len(orgs), 1)


# ── downstream boundaries ──────────────────────────────────────────────

class DownstreamBoundary(Base):

    DAY = datetime(2026, 8, 10, 3, 30, tzinfo=timezone.utc)

    def test_it_writes_no_commitment_or_outcome(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY)
        tables = {row.get("_table") for row in []}
        for row in self.db.rows:
            self.assertEqual(row.get("predicate_ns") in ("core.party", "biz.pipeline"),
                             True)
        self.assertEqual(len(self.db.parties), 2)   # one probe + the org

    def test_it_writes_only_the_intended_predicate(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY)
        written = {f"{x['predicate_ns']}.{x['predicate_concept']}"
                   for x in self.db.rows}
        self.assertEqual(written,
                         {"core.party.first_seen_at",
                          "biz.pipeline.new_enquiries_per_month"})

    def test_the_refreshed_fact_is_consumable_by_2H(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY)
        g = ctx.goal("probe", 2,
                     [ctx.slot("n", pe.PREDICATE, ctx.OBTAINABLE_BY_RETRIEVAL)],
                     "probe")
        p_ = policy.Principal("910000000001", "OWNER", T)
        pk = ctx.assemble(T, "probe", p_, g, pe.business_subject(T),
                          describe=knowledge.describe,
                          as_of=self.DAY + timedelta(hours=1))
        s = pk["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], "PROCEED")
        fact = [f for f in pk["evidence"]["facts"]
                if f["predicate"] == pe.PREDICATE][0]
        self.assertEqual(fact["provenance"]["tier"], 3)
        self.assertEqual(fact["freshness"]["verdict"], "FRESH")

    def test_a_stale_fact_still_reaches_2H_with_its_verdict(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.run_digest_block(self.DAY)
        g = ctx.goal("probe", 2,
                     [ctx.slot("n", pe.PREDICATE, ctx.OBTAINABLE_BY_RETRIEVAL)],
                     "probe")
        p_ = policy.Principal("910000000001", "OWNER", T)
        pk = ctx.assemble(T, "probe", p_, g, pe.business_subject(T),
                          describe=knowledge.describe,
                          as_of=self.DAY + timedelta(hours=30))
        fact = [f for f in pk["evidence"]["facts"]
                if f["predicate"] == pe.PREDICATE][0]
        self.assertEqual(fact["freshness"]["verdict"], "STALE")

    def test_digest_block_logs_no_pii(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        log = self.run_digest_block(self.DAY)["log"]
        for banned in ("910000000001", "919555555555", "@", "wamid"):
            self.assertNotIn(banned, log)

    def test_the_digest_block_calls_no_model_and_no_crm(self):
        import inspect
        src = inspect.getsource(dg.handler.do_GET)
        seg = src[src.index("bic pipeline evidence"):]
        for banned in ("deepseek", "openai", "gemini", "CRM_", "clients"):
            self.assertNotIn(banned, seg)
