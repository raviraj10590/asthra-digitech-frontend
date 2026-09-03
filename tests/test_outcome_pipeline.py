"""PROCEED opens exactly one 2I observation window — proved through the
REAL pipeline wiring, not by calling the producer directly.

WHY THIS FILE EXISTS
--------------------
The shared Base fixture stubs party.resolve_or_create with the STRING
"subj-fixed". That is fine for tests that never persist, but bic_outcome_records
.subject is a uuid column, so a pipeline test that let the real producer run
watched PostgreSQL reject the row (22P02) and the producer fail safe. The
outcome write then looked absent when it had merely been rejected by a fixture
value that production never produces.

The fix is the smallest possible override: give the resolver a DETERMINISTIC
VALID UUID and let everything else — expect_customer_reply, outcomes.expect,
the row construction — run for real. The producer is NOT mocked; only the
store underneath it is, exactly as every other persistence test here does it.

NON-VACUOUS BY CONSTRUCTION
---------------------------
  · the real bic.outcome_producers.expect_customer_reply runs
  · the real bic.outcomes.expect builds and inserts the row
  · the fake store records table + row, so the assertions read what the
    production code actually wrote
  · a counter proves the producer was entered exactly once, so "zero rows"
    can never be mistaken for "never called"

Offline: no network, no AI, no database.
"""

import io
import os
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                               # noqa: E402
from bic import claims as cl                                      # noqa: E402
from bic import outcome_producers as op                           # noqa: E402
from bic import outcomes as oc                                    # noqa: E402
from tests.test_brain_decision_loop import (Base, clarify_packet,  # noqa: E402
                                            proceed_packet, refuse_packet)

# A deterministic, SCHEMA-VALID party id. The point of the fixture fix: the
# uuid column will accept this, so the row that production would write is the
# row this test inspects.
PARTY_UUID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


class FakeOutcomeStore:
    """Records what the real producer writes. Raises on any unexpected table,
    so a stray write cannot pass unnoticed."""

    def __init__(self):
        self.rows, self.tables = [], []

    def insert(self, table, row, timeout=None):
        self.tables.append(table)
        if table == oc.TABLE:
            # Mirror the column contract that bit us: subject must be a uuid.
            uuid.UUID(str(row["subject"]))
            self.rows.append(dict(row))
        elif table == oc.RETRACTIONS_TABLE:
            self.rows.append(dict(row))
        else:
            raise AssertionError(f"unexpected table {table}")


class Pipeline(Base):

    def drive(self, packet):
        self.store = FakeOutcomeStore()
        self.producer_calls = []
        self.claim_writes = []
        real = op.expect_customer_reply

        def counting(sender, decision_ref, tenant_id=None, goal_ref=None):
            # Counts, then runs the REAL producer. Not a replacement for it.
            self.producer_calls.append(
                {"sender": sender, "decision_ref": decision_ref,
                 "tenant_id": tenant_id, "goal_ref": goal_ref})
            return real(sender, decision_ref, tenant_id=tenant_id,
                        goal_ref=goal_ref)

        s = self.stack.enter_context
        s(mock.patch.object(w.bic_party, "resolve_or_create",
                            lambda *a, **k: PARTY_UUID))
        s(mock.patch.object(oc, "insert", self.store.insert))
        s(mock.patch.object(w.bic_outcome_producers, "expect_customer_reply",
                            counting))
        s(mock.patch.object(cl, "insert",
                            lambda t, r, **k: self.claim_writes.append(t)))
        s(mock.patch.object(w, "extract_lead_info", lambda h: {}))
        s(self.with_packet(packet))
        with redirect_stdout(io.StringIO()):
            self.run_pipeline(long_history=True)

    def outcome_rows(self):
        return [r for r in self.store.rows if r.get("outcome_kind")]


# ── PROCEED ────────────────────────────────────────────────────────────

class Proceed(Pipeline):

    def setUp(self):
        super().setUp()
        self.drive(proceed_packet())

    def test_the_producer_is_entered_exactly_once(self):
        self.assertEqual(len(self.producer_calls), 1)

    def test_exactly_one_outcome_row_is_written(self):
        self.assertEqual(len(self.outcome_rows()), 1)

    def test_the_row_goes_to_the_outcome_records_table(self):
        self.assertEqual(self.store.tables, [oc.TABLE])

    def test_the_row_carries_a_valid_tenant(self):
        uuid.UUID(str(self.outcome_rows()[0]["tenant_id"]))

    def test_the_row_carries_a_valid_decision_ref(self):
        ref = self.outcome_rows()[0]["decision_ref"]
        self.assertTrue(ref)
        uuid.UUID(str(ref))

    def test_the_row_carries_a_valid_party_uuid_subject(self):
        self.assertEqual(self.outcome_rows()[0]["subject"], PARTY_UUID)
        uuid.UUID(str(self.outcome_rows()[0]["subject"]))

    def test_the_window_is_the_declared_24h(self):
        row = self.outcome_rows()[0]
        self.assertEqual(row["window_seconds"], op.CUSTOMER_REPLY_WINDOW_SECONDS)
        self.assertEqual(row["window_seconds"], 86400)

    def test_the_row_opens_in_EXPECTED_with_nothing_observed(self):
        row = self.outcome_rows()[0]
        self.assertEqual(row["lifecycle"], oc.EXPECTED)
        self.assertIsNone(row["observed_state"])
        self.assertIsNone(row["observed_at"])

    def test_it_is_the_customer_reply_kind(self):
        self.assertEqual(self.outcome_rows()[0]["outcome_kind"],
                         op.CUSTOMER_REPLY_KIND)

    def test_no_duplicate_row_and_no_extra_expectation(self):
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(len(self.producer_calls), 1)

    def test_no_claim_is_written(self):
        self.assertEqual(self.claim_writes, [])


# ── CLARIFY ────────────────────────────────────────────────────────────

class Clarify(Pipeline):

    def setUp(self):
        super().setUp()
        self.drive(clarify_packet())

    def test_the_producer_is_never_entered(self):
        self.assertEqual(self.producer_calls, [])

    def test_no_outcome_row_exists(self):
        self.assertEqual(self.outcome_rows(), [])

    def test_nothing_at_all_is_written(self):
        self.assertEqual(self.store.rows, [])
        self.assertEqual(self.store.tables, [])

    def test_no_claim_is_written(self):
        self.assertEqual(self.claim_writes, [])


# ── REFUSE ─────────────────────────────────────────────────────────────

class Refuse(Pipeline):

    def setUp(self):
        super().setUp()
        self.drive(refuse_packet())

    def test_the_producer_is_never_entered(self):
        self.assertEqual(self.producer_calls, [])

    def test_no_outcome_row_exists(self):
        self.assertEqual(self.outcome_rows(), [])

    def test_no_claim_is_written(self):
        self.assertEqual(self.claim_writes, [])


# ── the fixture defect this file was written to close ──────────────────

class FixtureContract(Pipeline):

    def test_the_shared_base_fixture_still_returns_a_non_uuid(self):
        """Documents WHY the override is needed, and fails loudly the day
        Base changes — at which point this override can go."""
        super().setUp()
        self.assertEqual(
            w.bic_party.resolve_or_create(None, None, None), "subj-fixed")
        with self.assertRaises(ValueError):
            uuid.UUID("subj-fixed")

    def test_a_non_uuid_subject_would_be_rejected_by_the_store(self):
        """The fake store enforces the same column contract PostgreSQL does,
        so this test cannot pass on a value production would reject."""
        store = FakeOutcomeStore()
        with self.assertRaises(ValueError):
            store.insert(oc.TABLE, {"subject": "subj-fixed",
                                    "outcome_kind": "customer_reply"})
