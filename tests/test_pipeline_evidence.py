"""The first BUSINESS-level evidence predicate.

    biz.pipeline.new_enquiries_per_month@1
    "Distinct parties known to the Brain whose first_seen_at falls inside one
     calendar month, measured in IST."

THE TWO TESTS THAT MATTER MOST
------------------------------
1. The IST boundary. A calendar month in Bengaluru starts 5.5 hours before it
   starts in UTC, so every enquiry between 18:30Z and midnight sits in the
   NEXT month if the arithmetic is done in the wrong zone. Half-open windows
   are pinned at both edges.

2. Supersession. The producer originally set valid_from to the month START,
   which reads well and is wrong: claims.current() buckets a `single`
   predicate by predicate and keeps the LATEST valid_from, so identical
   valid_from values meant nothing superseded, two live claims survived, and
   the fact went permanently `contested` — CLARIFY, and a metric no decision
   could use. That defect is pinned by test_recomputation_supersedes.

Offline: no network, no AI, no real database.
"""

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import claims as c                                       # noqa: E402
from bic import party as pt                                       # noqa: E402
from bic import pipeline_evidence as pe                           # noqa: E402
from bic import registry as r                                     # noqa: E402

T = "00000000-0000-0000-0000-000000000001"
OTHER_T = "00000000-0000-0000-0000-0000000000ff"
IST = pe.IST


class Store:
    """In-memory stand-in for bic_claims + bic_parties. Enforces what the
    real schema enforces that this producer depends on."""

    def __init__(self):
        self.rows, self.parties, self.identifiers, self.concepts = [], [], [], []

    def insert(self, table, row, timeout=None):
        if table == c.TABLE:
            self.rows.append(dict(row))
        elif table == pt.PARTIES_TABLE:
            self.parties.append(dict(row))
        elif table == pt.IDENTIFIERS_TABLE:
            key = (row["tenant_id"], row["channel"], row["identifier_value"])
            if any((i["tenant_id"], i["channel"], i["identifier_value"]) == key
                   for i in self.identifiers):
                from bic.db import DbError
                raise DbError("duplicate key value violates unique constraint (23505)")
            self.identifiers.append(dict(row))
        elif table == r.TABLE:
            self.concepts.append(dict(row))
        else:
            raise AssertionError(f"unexpected table {table}")

    def update(self, table, params, patch, timeout=None):
        src = {r.TABLE: self.concepts, pt.PARTIES_TABLE: self.parties}[table]
        for row in src:
            if all(str(row.get(k)) == str(v)[3:] for k, v in params.items()
                   if str(v).startswith("eq.")):
                row.update(patch)

    def select(self, table, params, timeout=None):
        src = {c.TABLE: self.rows, pt.PARTIES_TABLE: self.parties,
               pt.IDENTIFIERS_TABLE: self.identifiers,
               r.TABLE: self.concepts}.get(table)
        if src is None:
            if table == c.RETRACTIONS_TABLE:
                return []
            raise AssertionError(f"unexpected table {table}")
        out = []
        for row in src:
            keep = True
            for k, v in params.items():
                if k in ("order", "limit", "select"):
                    continue
                v = str(v)
                got = str(row.get(k))
                if v.startswith("eq.") and got != v[3:]:
                    keep = False
                elif v.startswith("gte.") and not got >= v[4:]:
                    keep = False
                elif v.startswith("lt.") and not got < v[3:]:
                    keep = False
                elif v.startswith("in."):
                    if got not in v[3:].strip("()").split(","):
                        keep = False
                elif v == "is.null" and row.get(k) is not None:
                    keep = False
            if keep:
                out.append(dict(row))
        order = params.get("order")
        if order:
            field, _, direction = order.split(",")[0].partition(".")
            out.sort(key=lambda x: str(x.get(field) or ""),
                     reverse=direction == "desc")
        return out


class Base(unittest.TestCase):

    def setUp(self):
        self.db = Store()
        self._p = [mock.patch.object(m, fn, getattr(self.db, fn))
                   for m in (c, pt, r) for fn in ("select", "insert", "update")
                   if hasattr(m, fn)]
        for p in self._p:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self._p)])
        # Register the two predicates this producer needs, exactly as the
        # migrations register them.
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
        """A party whose first contact was `when` (world time)."""
        p = pt.resolve_or_create(tenant, pt.WHATSAPP, f"p-{uuid.uuid4()}")
        c.assert_claim(tenant, p, pe.SOURCE_PREDICATE, when.isoformat(),
                       source="whatsapp", provenance_tier=1, asserted_by="test",
                       valid_from=when, observed_at=when)
        return p


# ── the window ─────────────────────────────────────────────────────────

class MonthWindow(Base):

    def test_august_window_is_midnight_IST_not_UTC(self):
        start, end = pe.month_window(datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertEqual(start, datetime(2026, 7, 31, 18, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 8, 31, 18, 30, tzinfo=timezone.utc))

    def test_it_is_half_open(self):
        start, end = pe.month_window(datetime(2026, 8, 15, tzinfo=timezone.utc))
        nxt_start, _ = pe.month_window(end)
        self.assertEqual(end, nxt_start,
                         "consecutive months must partition time exactly")

    def test_year_rollover(self):
        start, end = pe.month_window(datetime(2026, 12, 20, tzinfo=timezone.utc))
        self.assertEqual(start, datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc))

    def test_leap_february(self):
        start, end = pe.month_window(datetime(2028, 2, 10, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(days=29))

    def test_non_leap_february(self):
        start, end = pe.month_window(datetime(2027, 2, 10, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(days=28))

    def test_an_instant_late_on_the_31st_IST_is_still_that_month(self):
        """23:00 IST on 31 Aug is 17:30Z — same month. The UTC-naive bug would
        put it in September only after 18:30Z, which is why this is pinned."""
        late = datetime(2026, 8, 31, 23, 0, tzinfo=IST)
        start, end = pe.month_window(late)
        self.assertEqual(end, datetime(2026, 8, 31, 18, 30, tzinfo=timezone.utc))
        self.assertLess(late.astimezone(timezone.utc), end)

    def test_naive_input_is_read_as_utc_not_local(self):
        a = pe.month_window(datetime(2026, 8, 15))
        b = pe.month_window(datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertEqual(a, b)


# ── the count ──────────────────────────────────────────────────────────

class Counting(Base):

    AUG = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    def test_zero_known_parties(self):
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 0)

    def test_one_party(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 1)

    def test_multiple_parties(self):
        for d in (2, 9, 17, 28):
            self.seen(datetime(2026, 8, d, tzinfo=timezone.utc))
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 4)

    def test_exact_window_start_is_included(self):
        start, _ = pe.month_window(self.AUG)
        self.seen(start)
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 1)

    def test_one_second_before_the_window_is_excluded(self):
        start, _ = pe.month_window(self.AUG)
        self.seen(start - timedelta(seconds=1))
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 0)

    def test_exact_window_end_is_excluded(self):
        _, end = pe.month_window(self.AUG)
        self.seen(end)
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 0)

    def test_one_second_before_the_end_is_included(self):
        _, end = pe.month_window(self.AUG)
        self.seen(end - timedelta(seconds=1))
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 1)

    def test_a_party_seen_twice_counts_once(self):
        p = self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        when = datetime(2026, 8, 9, tzinfo=timezone.utc)
        c.assert_claim(T, p, pe.SOURCE_PREDICATE, when.isoformat(),
                       source="whatsapp", provenance_tier=1, asserted_by="test",
                       valid_from=when, observed_at=when)
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 1)

    def test_same_party_in_a_different_month_is_not_counted_here(self):
        self.seen(datetime(2026, 7, 10, tzinfo=timezone.utc))
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 0)

    def test_tenant_isolation(self):
        self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc), tenant=OTHER_T)
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 0)
        self.assertEqual(pe.count_new_enquiries(OTHER_T, at=self.AUG)["value"], 1)

    def test_it_counts_parties_not_claims(self):
        p = self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        for d in (6, 7, 8):
            when = datetime(2026, 8, d, tzinfo=timezone.utc)
            c.assert_claim(T, p, pe.SOURCE_PREDICATE, when.isoformat(),
                           source="whatsapp", provenance_tier=1,
                           asserted_by="test", valid_from=when, observed_at=when)
        self.assertEqual(len(self.db.rows), 4)
        self.assertEqual(pe.count_new_enquiries(T, at=self.AUG)["value"], 1)

    def test_it_is_deterministic(self):
        for d in (2, 9, 17):
            self.seen(datetime(2026, 8, d, tzinfo=timezone.utc))
        a = pe.count_new_enquiries(T, at=self.AUG)["value"]
        b = pe.count_new_enquiries(T, at=self.AUG)["value"]
        self.assertEqual(a, b)


# ── the claim it writes ────────────────────────────────────────────────

class Recording(Base):

    AUG = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        super().setUp()
        for d in (2, 9, 12):
            self.seen(datetime(2026, 8, d, tzinfo=timezone.utc))
        self.row = pe.record(T, at=self.AUG, observed_at=self.AUG)

    def test_it_writes_the_count(self):
        self.assertEqual(str(self.row["value"]), "3")

    def test_provenance_is_tier_three_derivation(self):
        self.assertEqual(self.row["provenance_tier"], 3)

    def test_confidence_is_capped_at_the_tier(self):
        self.assertEqual(float(self.row["confidence"]), 0.70)

    def test_valid_until_pins_the_month(self):
        _, end = pe.month_window(self.AUG)
        self.assertEqual(self.row["valid_until"], end.isoformat())

    def test_valid_from_is_the_measurement_instant(self):
        """NOT the month start — that is what broke supersession."""
        self.assertEqual(self.row["valid_from"], self.AUG.isoformat())

    def test_the_subject_is_an_organization_party(self):
        subj = pe.business_subject(T)
        self.assertEqual(pt.lookup(T, subj)["kind"], pt.ORGANIZATION)

    def test_the_business_party_is_stable(self):
        self.assertEqual(pe.business_subject(T), pe.business_subject(T))

    def test_recomputation_supersedes_rather_than_conflicts(self):
        """THE REGRESSION. Identical valid_from left two live claims on a
        `single` predicate, which claims.current() reports as contested."""
        self.seen(datetime(2026, 8, 20, tzinfo=timezone.utc))
        later = self.AUG + timedelta(days=6)
        pe.record(T, at=later, observed_at=later)
        cur = c.current(T, pe.business_subject(T), pe.PREDICATE,
                        as_of=later + timedelta(hours=1))
        self.assertFalse(cur["conflict"], "recomputation must supersede")
        self.assertEqual(len(cur["claims"]), 1)
        self.assertEqual(str(cur["claims"][0]["value"]), "4")

    def test_backfilling_a_closed_month_is_refused(self):
        with self.assertRaises(pe.PipelineEvidenceError):
            pe.record(T, at=self.AUG,
                      observed_at=datetime(2026, 9, 10, tzinfo=timezone.utc))

    def test_a_store_failure_returns_none_rather_than_raising(self):
        """A LATER instant, deliberately: setUp already recorded at self.AUG,
        and the same-instant guard would return that existing claim before
        assert_claim is ever reached — which would make this pass without
        exercising the failure path at all."""
        from bic.db import DbError
        later = self.AUG + timedelta(days=1)
        with mock.patch.object(c, "assert_claim", side_effect=DbError("down")):
            self.assertIsNone(pe.record(T, at=later, observed_at=later))

    def test_a_same_instant_rerun_is_an_idempotent_no_op(self):
        """Two runs sharing a measurement instant must not leave two live
        claims — supersession is keyed on valid_from, so neither would win."""
        again = pe.record(T, at=self.AUG, observed_at=self.AUG)
        self.assertEqual(again["claim_id"], self.row["claim_id"])
        cur = c.current(T, pe.business_subject(T), pe.PREDICATE,
                        as_of=self.AUG + timedelta(hours=1))
        self.assertEqual(len(cur["claims"]), 1)
        self.assertFalse(cur["conflict"])


# ── boundaries ─────────────────────────────────────────────────────────

def executable_python(module):
    """Module source with comments and STRINGS (incl. docstrings) removed.

    Required here: this module's prose EXPLAINS why the `leads` table was
    rejected and states that it touches no phone or wamid. Scanning raw text
    would match the explanation and report the very thing it promises.
    """
    import io, inspect, tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(module)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


class Boundaries(Base):

    def test_the_producer_never_reads_leads_or_crm(self):
        code = executable_python(pe).lower()
        for banned in ("leads", "clients", "crm", "whatsapp_messages"):
            self.assertNotIn(banned, code)

    def test_no_model_and_no_direct_network(self):
        code = executable_python(pe).lower()
        for banned in ("openai", "gemini", "deepseek", "llm", "requests",
                       "prompt", "http"):
            self.assertNotIn(banned, code)

    def test_no_pii_vocabulary(self):
        code = executable_python(pe).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "sender"):
            self.assertNotIn(banned, code)

    def test_the_claim_carries_no_subject_list(self):
        """The audit list is returned for inspection, never persisted."""
        for d in (2, 9):
            self.seen(datetime(2026, 8, d, tzinfo=timezone.utc))
        at = datetime(2026, 8, 15, tzinfo=timezone.utc)
        row = pe.record(T, at=at, observed_at=at)
        self.assertNotIn("subjects", row)
        self.assertNotIn("subjects", str(row))

    def test_it_derives_only_from_first_seen_at(self):
        self.assertEqual(pe.SOURCE_PREDICATE, "core.party.first_seen_at@1")

    def test_the_predicate_is_versioned(self):
        self.assertTrue(pe.PREDICATE.endswith("@1"))

    def test_retracted_source_claims_are_not_counted(self):
        p = self.seen(datetime(2026, 8, 5, tzinfo=timezone.utc))
        claim_id = self.db.rows[-1]["claim_id"]
        with mock.patch.object(c, "_retracted_ids",
                               lambda tenant, ids: {claim_id}):
            at = datetime(2026, 8, 15, tzinfo=timezone.utc)
            self.assertEqual(pe.count_new_enquiries(T, at=at)["value"], 0)
