"""Stage ⑮ escalation → 2B Commitment.

The sharpest tests here are the ones proving the Brain records NOTHING when
no deadline policy exists. 2B makes due_on part of a Commitment's identity and
part of its purpose — "are we about to miss it?" — so a fabricated deadline
would author the SLA the business is later judged against, inside the one
store built to keep that judgement honest.

The second family proves the LLM cannot reach any of it (I5), and the third
that a Commitment is not an Outcome and not a Claim (2I boundary).

Offline: no network, no AI, no database.
"""

import ast
import os
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import commitment as cm                                  # noqa: E402
from bic import escalation as esc                                 # noqa: E402
from bic import goal_lifecycle as gl                              # noqa: E402
from bic import observe as ob                                     # noqa: E402
from bic import recovery as rec                                   # noqa: E402
from bic.db import DbError                                        # noqa: E402

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "escalation.py")

TENANT = "tenant-fixed"
PARTY = "party-abc"
DECISION = "decision-xyz"
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=4)


def code_only(path) -> str:
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


class Resp:
    def __init__(self, ok, status_code):
        self.ok, self.status_code, self.text = ok, status_code, "{}"


def human_review():
    """A real HUMAN_REVIEW result, built by the real classifier."""
    r = rec.classify(ob.execution(TimeoutError("gateway")))
    assert r["recovery"] == rec.HUMAN_REVIEW
    return r


def kwargs(**over):
    base = dict(tenant_id=TENANT, party=PARTY, decision_ref=DECISION,
                owner=esc.resolve_owner(), now=NOW)
    base.update(over)
    return base


# ══════════════════════════════════════════════════════════════════════
# THE DUE_ON POLICY BOUNDARY — the point of this slice
# ══════════════════════════════════════════════════════════════════════

class DueOnPolicy(unittest.TestCase):
    """The approved ruling (2026-08-25): due_on = escalation + 4 hours,
    continuous clock, no criticality variation, exact timestamp."""

    def test_the_deadline_is_exactly_four_hours(self):
        due = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=NOW)
        self.assertEqual(due - NOW, timedelta(hours=4))

    def test_the_window_is_declared_once_and_is_four_hours(self):
        self.assertEqual(esc._SLA[esc.DELIVER_PENDING_REPLY],
                         timedelta(hours=4))

    def test_it_is_measured_from_the_supplied_instant(self):
        for moment in (NOW, NOW + timedelta(days=3), NOW - timedelta(days=90)):
            with self.subTest(moment=moment):
                self.assertEqual(
                    esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=moment),
                    moment + timedelta(hours=4))

    def test_it_is_deterministic(self):
        a = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=NOW)
        b = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=NOW)
        self.assertEqual(a, b)

    def test_the_result_is_timezone_aware_utc(self):
        due = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=NOW)
        self.assertIsNotNone(due.tzinfo)
        self.assertEqual(due.utcoffset(), timedelta(0))

    def test_a_naive_instant_is_read_as_utc_not_local_time(self):
        naive = datetime(2026, 8, 25, 9, 0)
        self.assertEqual(esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=naive),
                         NOW + timedelta(hours=4))

    def test_the_timestamp_is_exact_and_never_rounded(self):
        odd = datetime(2026, 8, 25, 9, 17, 43, 123456, tzinfo=timezone.utc)
        due = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=odd)
        self.assertEqual(due, odd + timedelta(hours=4))
        self.assertEqual(due.microsecond, 123456)
        self.assertEqual((due.minute, due.second), (17, 43))

    def test_an_unruled_obligation_still_records_nothing(self):
        """The refusal mechanism survives the ruling — it is now scoped to
        obligations the owner has not ruled on, rather than removed."""
        with mock.patch.dict(esc._SLA, {}, clear=True):
            self.assertIsNone(esc.due_on_policy(esc.DELIVER_PENDING_REPLY,
                                                now=NOW))
            r = esc.escalate(human_review(), **kwargs())
        self.assertEqual(r["escalation"], esc.POLICY_REQUIRED)
        self.assertFalse(r["recorded"])

    def test_an_unruled_obligation_still_needs_a_human(self):
        """Not recording must never look like nothing happened (§6.2 T4)."""
        with mock.patch.dict(esc._SLA, {}, clear=True):
            r = esc.escalate(human_review(), **kwargs())
        self.assertTrue(r["needs_human"])
        self.assertEqual(r["recovery"], rec.HUMAN_REVIEW)

    def test_an_unknown_obligation_is_refused_not_defaulted(self):
        with self.assertRaises(esc.EscalationError):
            esc.due_on_policy("SOMETHING_NOBODY_RULED_ON")

    # ── the ruling says NO calendars. These guard that it stays true ──

    def test_no_business_hour_or_holiday_calendar_exists(self):
        code = code_only(MODULE).lower()
        for banned in ("holiday", "business_hour", "businesshour", "weekend",
                       "workday", "business_day", "calendar"):
            self.assertNotIn(banned, code)

    def test_no_criticality_tiers_exist(self):
        """The ruling: no criticality variation, and criticality is never
        inferred. The SLA table is keyed by obligation alone."""
        for window in esc._SLA.values():
            self.assertIsInstance(window, timedelta)
        self.assertNotIn("criticality", code_only(MODULE).lower())

    def test_criticality_is_left_unset_on_the_commitment(self):
        with mock.patch.object(cm, "save", lambda c: c):
            esc.escalate(human_review(), **kwargs())
        built = []
        with mock.patch.object(cm, "save", lambda c: built.append(c) or c):
            esc.escalate(human_review(), **kwargs())
        self.assertIsNone(built[0]["criticality"])

    def test_the_policy_reads_no_customer_signal(self):
        """It takes an obligation and an instant. There is no argument
        through which customer type, text, role or campaign could reach it."""
        sig = __import__("inspect").signature(esc.due_on_policy)
        self.assertEqual(list(sig.parameters), ["obligation", "now"])

    # ── an explicitly supplied deadline still overrides ──

    def test_an_explicitly_supplied_deadline_is_honoured(self):
        with mock.patch.object(cm, "save", lambda c: c):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        self.assertEqual(r["escalation"], esc.RECORDED)

    def test_a_past_deadline_is_not_a_valid_policy(self):
        r = esc.escalate(human_review(), **kwargs(due_on=NOW - timedelta(days=1)))
        self.assertEqual(r["escalation"], esc.POLICY_REQUIRED)

    def test_an_unparseable_deadline_is_not_a_valid_policy(self):
        r = esc.escalate(human_review(), **kwargs(due_on="whenever"))
        self.assertEqual(r["escalation"], esc.POLICY_REQUIRED)


class ClockRunsContinuously(unittest.TestCase):
    """Overnight, weekend and holiday boundaries. The ruling pauses for
    none of them, so each of these must land exactly 4 hours later —
    these tests exist to FAIL the day someone adds a calendar."""

    def assert_plain_four_hours(self, moment):
        self.assertEqual(esc.due_on_policy(esc.DELIVER_PENDING_REPLY,
                                           now=moment),
                         moment + timedelta(hours=4))

    def test_overnight_does_not_pause(self):
        # 23:30 Mon → 03:30 Tue, straight through the night.
        late = datetime(2026, 8, 24, 23, 30, tzinfo=timezone.utc)
        self.assert_plain_four_hours(late)
        self.assertEqual(esc.due_on_policy(esc.DELIVER_PENDING_REPLY,
                                           now=late).day, 25)

    def test_end_of_business_day_does_not_defer_to_morning(self):
        self.assert_plain_four_hours(
            datetime(2026, 8, 24, 17, 30, tzinfo=timezone.utc))

    def test_saturday_does_not_pause(self):
        sat = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(sat.weekday(), 5)
        self.assert_plain_four_hours(sat)

    def test_friday_night_does_not_skip_the_weekend(self):
        fri = datetime(2026, 8, 28, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(fri.weekday(), 4)
        due = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=fri)
        self.assertEqual(due, fri + timedelta(hours=4))
        self.assertEqual(due.weekday(), 5, "lands on Saturday, not Monday")

    def test_sunday_does_not_pause(self):
        sun = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(sun.weekday(), 6)
        self.assert_plain_four_hours(sun)

    def test_a_public_holiday_does_not_pause(self):
        # Indian Independence Day — a real holiday for this business.
        self.assert_plain_four_hours(
            datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc))

    def test_new_year_midnight_does_not_pause(self):
        eve = datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)
        due = esc.due_on_policy(esc.DELIVER_PENDING_REPLY, now=eve)
        self.assertEqual(due, datetime(2027, 1, 1, 3, 0, tzinfo=timezone.utc))


class OverdueBoundary(unittest.TestCase):
    """`is_overdue` is 2B's, not this module's — but the digest reports off
    it, so the 4-hour edge is pinned here."""

    def setUp(self):
        with mock.patch.object(cm, "save", lambda c: c):
            self.result = esc.escalate(human_review(), **kwargs())
        self.c = {"lifecycle": cm.MADE,
                  "due_on": esc.due_on_policy(esc.DELIVER_PENDING_REPLY,
                                              now=NOW).isoformat()}

    def test_just_before_four_hours_is_not_overdue(self):
        self.assertFalse(cm.is_overdue(
            self.c, now=NOW + timedelta(hours=4) - timedelta(seconds=1)))

    def test_exactly_four_hours_is_not_yet_overdue(self):
        """Strictly past the deadline. At the instant it falls due the
        business is on time, not late."""
        self.assertFalse(cm.is_overdue(self.c, now=NOW + timedelta(hours=4)))

    def test_just_after_four_hours_is_overdue(self):
        self.assertTrue(cm.is_overdue(
            self.c, now=NOW + timedelta(hours=4) + timedelta(seconds=1)))

    def test_it_is_not_overdue_an_hour_in(self):
        self.assertFalse(cm.is_overdue(self.c, now=NOW + timedelta(hours=1)))

    def test_a_closed_commitment_is_never_overdue(self):
        for state in cm.TERMINALS:
            with self.subTest(state=state):
                self.assertFalse(cm.is_overdue(
                    dict(self.c, lifecycle=state), now=NOW + timedelta(days=9)))


# ══════════════════════════════════════════════════════════════════════
# WHEN A COMMITMENT MAY BE CREATED AT ALL
# ══════════════════════════════════════════════════════════════════════

class OnlyOutstandingWork(unittest.TestCase):

    def _esc(self, result):
        return esc.escalate(result, **kwargs(due_on=LATER))

    def test_delivered_owes_nothing(self):
        r = self._esc(rec.classify(ob.execution(Resp(True, 200))))
        self.assertEqual(r["escalation"], esc.NOT_APPLICABLE)

    def test_safe_to_retry_owes_nothing_yet(self):
        """Still in flight. A commitment here would record a debt for work
        the very next line of the loop may complete."""
        r = self._esc(rec.classify(ob.execution(Resp(False, 429))))
        self.assertEqual(r["recovery"], rec.SAFE_TO_RETRY)
        self.assertEqual(r["escalation"], esc.NOT_APPLICABLE)

    def test_terminal_failure_owes_nothing(self):
        r = self._esc(rec.classify(ob.execution(Resp(False, 400))))
        self.assertEqual(r["escalation"], esc.NOT_APPLICABLE)

    def test_nothing_attempted_owes_nothing(self):
        r = self._esc(rec.classify(ob.not_attempted()))
        self.assertEqual(r["escalation"], esc.NOT_APPLICABLE)

    def test_only_human_review_creates_an_obligation(self):
        self.assertEqual(list(esc._OBLIGATION_FOR), [rec.HUMAN_REVIEW])

    def test_obligation_for_is_total_and_deterministic(self):
        for result in (Resp(True, 200), Resp(False, 400), Resp(False, 429),
                       TimeoutError("x"), None):
            o = ob.execution(result)
            a = esc.obligation_for(rec.classify(o))
            b = esc.obligation_for(rec.classify(o))
            self.assertEqual(a, b)
            self.assertIn(a, (None,) + esc.OBLIGATIONS)


# ══════════════════════════════════════════════════════════════════════
# OWNER, PARTY, ATTRIBUTION
# ══════════════════════════════════════════════════════════════════════

class RequiredReferences(unittest.TestCase):

    def test_no_owner_records_nothing(self):
        r = esc.escalate(human_review(), **kwargs(owner=None, due_on=LATER))
        self.assertEqual(r["escalation"], esc.OWNER_UNRESOLVED)
        self.assertFalse(r["recorded"])

    def test_owner_reuses_the_existing_convention(self):
        """Not a second owner system: the same constant the goal lifecycle
        already uses for autonomous work."""
        self.assertEqual(esc.resolve_owner(), gl.AUTONOMOUS_OWNER)

    def test_owner_is_not_a_phone_number(self):
        self.assertFalse(any(ch.isdigit() for ch in esc.resolve_owner()))

    def test_missing_party_records_nothing(self):
        r = esc.escalate(human_review(), **kwargs(party=None, due_on=LATER))
        self.assertEqual(r["escalation"], esc.ATTRIBUTION_MISSING)

    def test_missing_decision_ref_records_nothing(self):
        """§7 — the obligation must name the decision that created it."""
        r = esc.escalate(human_review(), **kwargs(decision_ref=None, due_on=LATER))
        self.assertEqual(r["escalation"], esc.ATTRIBUTION_MISSING)

    def test_missing_tenant_records_nothing(self):
        r = esc.escalate(human_review(), **kwargs(tenant_id=None, due_on=LATER))
        self.assertEqual(r["escalation"], esc.ATTRIBUTION_MISSING)


class WhatGetsWritten(unittest.TestCase):

    def setUp(self):
        self.built = []
        self.stack = mock.patch.object(cm, "save", lambda c: self.built.append(c) or c)
        self.stack.start()
        self.addCleanup(self.stack.stop)
        self.result = esc.escalate(human_review(), **kwargs(due_on=LATER,
                                                            goal_ref="goal-1"))

    def test_it_records_exactly_one_commitment(self):
        self.assertEqual(self.result["escalation"], esc.RECORDED)
        self.assertEqual(len(self.built), 1)

    def test_decision_ref_is_preserved(self):
        self.assertEqual(self.built[0]["decision_ref"], DECISION)

    def test_party_is_preserved(self):
        self.assertEqual(self.built[0]["party"], PARTY)

    def test_subject_is_absent_because_the_promise_has_no_distinct_object(self):
        """What is owed is a reply to the party, not a thing with its own
        identity. NULLS NOT DISTINCT makes the absence a VALUE, which is what
        gives one open obligation per party per deadline."""
        self.assertIsNone(self.built[0]["subject"])

    def test_goal_ref_is_preserved(self):
        self.assertEqual(self.built[0]["goal_ref"], "goal-1")

    def test_the_obligation_is_deterministic_and_from_a_closed_set(self):
        self.assertEqual(self.built[0]["obligation"], esc.DELIVER_PENDING_REPLY)
        self.assertIn(self.built[0]["obligation"], esc.OBLIGATIONS)

    def test_it_starts_in_2b_made(self):
        self.assertEqual(self.built[0]["lifecycle"], cm.MADE)

    def test_the_obligation_is_an_identifier_not_a_sentence(self):
        o = self.built[0]["obligation"]
        self.assertNotIn(" ", o)
        self.assertEqual(o, o.upper())


# ══════════════════════════════════════════════════════════════════════
# IDEMPOTENCY — through the database identity, not a new dedupe table
# ══════════════════════════════════════════════════════════════════════

from tests.test_commitment import FakeStore                       # noqa: E402


class Idempotency(unittest.TestCase):

    def setUp(self):
        self.store = FakeStore()
        for target, fn in (("insert", self.store.insert),
                           ("select", self.store.select)):
            p = mock.patch.object(cm, target, fn)
            p.start()
            self.addCleanup(p.stop)

    def run_once(self):
        return esc.escalate(human_review(), **kwargs(due_on=LATER))

    def test_repeated_recovery_creates_exactly_one_commitment(self):
        first, second = self.run_once(), self.run_once()
        self.assertEqual(first["escalation"], esc.RECORDED)
        self.assertEqual(second["escalation"], esc.ALREADY_RECORDED)
        self.assertEqual(len(self.store.rows), 1)

    def test_the_second_call_reports_the_stored_commitment(self):
        """Not the freshly built one — that id was never persisted."""
        first, second = self.run_once(), self.run_once()
        self.assertEqual(second["commitment_id"], first["commitment_id"])

    def test_a_duplicate_still_counts_as_recorded(self):
        self.run_once()
        self.assertTrue(self.run_once()["recorded"])

    def test_many_repeats_still_create_one(self):
        for _ in range(5):
            self.run_once()
        self.assertEqual(len(self.store.rows), 1)

    def test_a_different_party_is_a_different_obligation(self):
        self.run_once()
        esc.escalate(human_review(), **kwargs(party="party-other", due_on=LATER))
        self.assertEqual(len(self.store.rows), 2)

    def test_no_dedupe_table_was_invented(self):
        """Dedupe is the migration's unique index, not a second store. The
        FakeStore raises on any table it does not know, so a new one would
        fail here rather than pass silently."""
        self.run_once()
        self.run_once()
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(len(self.store.transitions), 0,
                         "creation is not a transition")
        # Asserted on the AST, not the raw text: the module legitimately
        # discusses the SLA "table" in prose, and a comment must not be able
        # to trip or satisfy a structural rule.
        tree = ast.parse(pathlib.Path(MODULE).read_text())
        names = [t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)]
        self.assertEqual([n for n in names if n.endswith("TABLE")], [],
                         "escalation names no table of its own")


class StoreFailures(unittest.TestCase):

    def test_store_unavailable_is_reported_not_raised(self):
        with mock.patch.object(cm, "insert", side_effect=DbError("down")):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        self.assertEqual(r["escalation"], esc.PERSISTENCE_FAILED)
        self.assertFalse(r["recorded"])

    def test_a_failed_store_still_needs_a_human(self):
        with mock.patch.object(cm, "insert", side_effect=DbError("down")):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        self.assertTrue(r["needs_human"])

    def test_a_rejection_that_is_not_a_duplicate_is_not_reported_as_recorded(self):
        with mock.patch.object(cm, "save",
                               side_effect=cm.CommitmentError("bad row")), \
             mock.patch.object(cm, "find", lambda *a, **k: None):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        self.assertEqual(r["escalation"], esc.PERSISTENCE_FAILED)

    def test_a_failed_readback_never_claims_a_duplicate(self):
        with mock.patch.object(cm, "save",
                               side_effect=cm.CommitmentError("dupe")), \
             mock.patch.object(cm, "find", side_effect=DbError("down")):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        self.assertEqual(r["escalation"], esc.PERSISTENCE_FAILED)


# ══════════════════════════════════════════════════════════════════════
# BOUNDARIES — 2I, claims, the LLM, PII
# ══════════════════════════════════════════════════════════════════════

class Boundaries(unittest.TestCase):

    def setUp(self):
        self.code = code_only(MODULE)
        self.raw = pathlib.Path(MODULE).read_text()

    def test_creating_a_commitment_is_not_an_outcome(self):
        """2I is what the WORLD did, asynchronously. This is what WE owe."""
        for banned in ("outcomes", "outcome_records", "outcome_producers",
                       "expect_customer_reply"):
            self.assertNotIn(banned, self.code)

    def test_creating_a_commitment_is_not_a_claim(self):
        for banned in ("claims", "bic_claims", "assert_claim"):
            self.assertNotIn(banned, self.code)

    def test_it_asserts_no_knowledge_and_opens_no_window(self):
        self.assertNotIn("knowledge", self.code)
        self.assertNotIn("window", self.code)

    def test_no_model_and_no_network(self):
        low = self.code.lower()
        for banned in ("openai", "gemini", "llm", "requests", "http", "sleep",
                       "proposal", "prompt"):
            self.assertNotIn(banned, low)

    def test_escalate_accepts_no_free_text(self):
        """I5 made structural: there is no argument through which generated
        text could reach the obligation, the owner or the deadline."""
        sig = __import__("inspect").signature(esc.escalate)
        for forbidden in ("text", "reply", "proposal", "message", "obligation"):
            self.assertNotIn(forbidden, sig.parameters)

    def test_the_llm_cannot_choose_the_lifecycle(self):
        """Every commitment starts in 2B's `made`; no argument sets it."""
        sig = __import__("inspect").signature(esc.escalate)
        self.assertNotIn("lifecycle", sig.parameters)
        self.assertNotIn("state", sig.parameters)

    def test_nothing_here_can_claim_a_commitment_met(self):
        for banned in ("record_transition", "meet(", "MET", "start(",
                       "waive", "renegotiate"):
            self.assertNotIn(banned, self.code)

    def test_it_never_bypasses_the_rpc_with_a_direct_update(self):
        self.assertNotIn("update", self.code.lower())

    def test_no_pii_vocabulary(self):
        low = self.code.lower()
        for banned in ("phone", "email", "wamid", "source_ref", "sender",
                       "message_body", "lead_id", "customer_id", "packet_id"):
            self.assertNotIn(banned, low)

    def test_describe_carries_no_identifiers(self):
        with mock.patch.object(cm, "save", lambda c: c):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        d = esc.describe(r)
        self.assertNotIn("commitment_id", d)
        blob = repr(d)
        for leak in (PARTY, DECISION, TENANT):
            self.assertNotIn(leak, blob)

    def test_the_owner_note_leaks_no_identifiers(self):
        with mock.patch.object(cm, "save", lambda c: c):
            r = esc.escalate(human_review(), **kwargs(due_on=LATER))
        note = esc.owner_note(r)
        for leak in (PARTY, DECISION, TENANT, r["commitment_id"]):
            self.assertNotIn(leak, note)

    def test_every_result_state_has_a_deterministic_owner_note(self):
        for state in esc.RESULTS:
            self.assertIn(state, esc._NOTES)

    def test_unrecorded_states_tell_the_owner_it_is_not_tracked(self):
        """The alert is the only thing between the customer and silence when
        nothing was written, so it must not read like a success."""
        for state in esc.UNRECORDED:
            self.assertIn("NOT recorded", esc._NOTES[state])

    def test_tenant_isolation_is_required_not_defaulted(self):
        self.assertNotIn("DEFAULT_TENANT_ID", self.raw)


# ══════════════════════════════════════════════════════════════════════
# THROUGH THE REAL WEBHOOK PIPELINE
# ══════════════════════════════════════════════════════════════════════
# Everything above tests the module. These drive run_client_pipeline for
# real, because the question that matters is whether the WIRING creates a
# commitment on the right turns and no commitment on every other one.

import io                                                         # noqa: E402
import json as _json                                              # noqa: E402
from contextlib import redirect_stdout                            # noqa: E402

# `webhook`, NOT `api.webhook`. tests/test_brain_decision_loop.py imports it
# through the api/ path entry, and importing it the other way would create a
# SECOND module object: Base's patches would land on one and these on the
# other, so every "creates nothing" assertion below would pass without the
# escalation path ever running.
import webhook as w                                               # noqa: E402
from tests.test_brain_decision_loop import (Base, Delivery,        # noqa: E402
                                            Rejected, clarify_packet,
                                            proceed_packet, refuse_packet)

class PipelineBase(Base):

    def drive(self, channel_seq, packet=None, at=None):
        """`at` pins the escalation instant. The SLA is live, so the deadline
        is derived from it exactly as production would — this only removes
        clock jitter, it does not substitute a different policy."""
        self.store = FakeStore()
        self.alerts = []
        seq = list(channel_seq)
        self.attempts = []

        def _send(to, t, **k):
            self.attempts.append((to, t))
            i = min(len(self.attempts), len(seq)) - 1
            item = seq[i]
            if isinstance(item, BaseException):
                raise item
            return item

        s = self.stack.enter_context
        s(mock.patch.object(w, "send_text", _send))
        s(mock.patch.object(w, "notify_owner",
                            lambda m, *a, **k: self.alerts.append(m)))
        s(mock.patch.object(cm, "insert", self.store.insert))
        s(mock.patch.object(cm, "select", self.store.select))
        if at is not None:
            s(mock.patch.object(esc, "_now", lambda: at))
        s(self.with_packet(packet or proceed_packet()))

        buf = io.StringIO()
        with redirect_stdout(buf):
            self.run_pipeline(long_history=True)
        lines = buf.getvalue().splitlines()

        def grab(prefix):
            hit = [l for l in lines if l.startswith(prefix)]
            return _json.loads(hit[-1][len(prefix):]) if hit else None

        return {"recovery": grab("EXECUTION_RECOVERY "),
                "escalation": grab("EXECUTION_ESCALATION "),
                "goal": grab("GOAL_STATE "),
                "rows": self.store.rows,
                "alerts": self.alerts}


class AmbiguousDeliveryCreatesTheObligation(PipelineBase):

    def test_ambiguous_delivery_creates_exactly_one_commitment(self):
        """The live path, with no policy patched in: the approved SLA now
        applies of its own accord."""
        r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["recovery"]["recovery"], rec.HUMAN_REVIEW)
        self.assertEqual(r["escalation"]["escalation"], esc.RECORDED)
        self.assertEqual(len(r["rows"]), 1)

    def test_the_live_deadline_is_four_hours_after_the_failure(self):
        before = datetime.now(timezone.utc)
        r = self.drive([TimeoutError("gw")])
        after = datetime.now(timezone.utc)
        due = datetime.fromisoformat(r["rows"][0]["due_on"])
        # Bracketed by the real clock rather than compared to a fixed
        # instant, so this stays honest without becoming drift-sensitive.
        self.assertGreaterEqual(due, before + timedelta(hours=4))
        self.assertLessEqual(due, after + timedelta(hours=4))

    def test_the_commitment_is_not_created_already_overdue(self):
        r = self.drive([TimeoutError("gw")])
        self.assertFalse(cm.is_overdue(r["rows"][0]))

    def test_an_unruled_obligation_creates_nothing_through_the_pipeline(self):
        with mock.patch.dict(esc._SLA, {}, clear=True):
            r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["escalation"]["escalation"], esc.POLICY_REQUIRED)
        self.assertEqual(len(r["rows"]), 0)

    def test_the_created_commitment_carries_the_real_decision_ref(self):
        r = self.drive([TimeoutError("gw")])
        row = r["rows"][0]
        self.assertTrue(row["decision_ref"], "must name the deciding turn")
        self.assertEqual(row["obligation"], esc.DELIVER_PENDING_REPLY)
        self.assertEqual(row["lifecycle"], cm.MADE)

    def test_the_party_is_the_opaque_knowledge_id_not_the_phone(self):
        r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["rows"][0]["party"], "subj-fixed")
        self.assertNotIn("919555555555", repr(r["rows"][0]))

    def _rerun(self, store, at):
        """Drive the pipeline again against the SAME store.

        A FRESH DECISION TURN IS MANDATORY. _bic_decide_and_record closes the
        turn after writing the record, so a second run without this hits the
        record-before-respond gate, returns early, and never reaches the
        escalation at all — which made these assertions pass while proving
        nothing.
        """
        w.bic_decision.close_turn()
        w.bic_decision.open_turn()
        w.bic_decision.mark_route("client")
        w.bic_decision.mark_identity("CLIENT")
        with mock.patch.object(cm, "insert", store.insert), \
             mock.patch.object(cm, "select", store.select), \
             mock.patch.object(esc, "_now", lambda: at), \
             mock.patch.object(w, "send_text",
                               lambda *a, **k: (_ for _ in ()).throw(
                                   TimeoutError("gw"))), \
             mock.patch.object(w, "notify_owner", lambda *a, **k: None), \
             self.with_packet(proceed_packet()), \
             redirect_stdout(io.StringIO()):
            self.run_pipeline(long_history=True)

    def test_a_repeated_recovery_at_the_same_instant_creates_one(self):
        """Same customer, same escalation instant, therefore same due_on —
        migration 18's unique index collapses them, with no dedupe table."""
        first = self.drive([TimeoutError("gw")], at=NOW)
        self._rerun(self.store, NOW)
        self.assertEqual(len(first["rows"]), 1)
        self.assertEqual(len(self.store.rows), 1)

    def test_many_repeats_at_the_same_instant_still_create_one(self):
        self.drive([TimeoutError("gw")], at=NOW)
        for _ in range(4):
            self._rerun(self.store, NOW)
        self.assertEqual(len(self.store.rows), 1)

    def test_two_distinct_failures_are_two_distinct_obligations(self):
        """A CONSEQUENCE OF THE RULING, PINNED DELIBERATELY.

        The policy sets an exact timestamp (item 9) and 2B keys identity on
        due_on (item 10), so two failures an hour apart are two promises with
        two deadlines — not one. That is the correct reading: the customer is
        owed a reply to each, and collapsing them would silently drop one.

        A genuine DUPLICATE delivery never reaches here — stage ① claims the
        wamid and returns before the Brain path runs."""
        self.drive([TimeoutError("gw")], at=NOW)
        self._rerun(self.store, NOW + timedelta(hours=1))
        self.assertEqual(len(self.store.rows), 2)
        due = sorted(r["due_on"] for r in self.store.rows)
        self.assertNotEqual(due[0], due[1])


class NoObligationOnEveryOtherTurn(PipelineBase):

    def test_successful_delivery_creates_nothing(self):
        r = self.drive([Delivery()])
        self.assertEqual(len(r["rows"]), 0)
        self.assertIsNone(r["escalation"])

    def test_safe_retry_that_succeeds_creates_nothing(self):
        r = self.drive([Resp(False, 429), Delivery()])
        self.assertEqual(len(self.attempts), 2)
        self.assertEqual(len(r["rows"]), 0)

    def test_terminal_channel_refusal_creates_nothing(self):
        r = self.drive([Rejected()])
        self.assertEqual(r["recovery"]["recovery"], rec.TERMINAL_FAILURE)
        self.assertEqual(len(r["rows"]), 0)

    def test_refuse_creates_nothing_even_when_delivery_is_ambiguous(self):
        """We never promised anything, so we owe nothing. Recording here
        would put a debt in the ledger the business does not hold."""
        r = self.drive([TimeoutError("gw")], packet=refuse_packet())
        self.assertEqual(r["recovery"]["recovery"], rec.HUMAN_REVIEW)
        self.assertEqual(len(r["rows"]), 0)

    def test_clarify_creates_nothing_even_when_delivery_is_ambiguous(self):
        r = self.drive([TimeoutError("gw")], packet=clarify_packet())
        self.assertEqual(r["recovery"]["recovery"], rec.HUMAN_REVIEW)
        self.assertEqual(len(r["rows"]), 0)

    def test_exhausted_retry_budget_still_escalates_to_a_commitment(self):
        r = self.drive([Resp(False, 429), Resp(False, 429)])
        self.assertEqual(r["recovery"]["recovery"], rec.HUMAN_REVIEW)
        self.assertEqual(len(r["rows"]), 1)


class GoalAndOwnerInteraction(PipelineBase):

    def test_the_goal_is_never_completed_by_creating_a_commitment(self):
        r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["escalation"]["escalation"], esc.RECORDED)
        self.assertNotEqual(r["goal"]["lifecycle"], gl.COMPLETED)

    def test_the_goal_is_blocked_not_abandoned(self):
        """BLOCKED is a goal that still exists and is waiting (3B §1.3), and
        UNAVAILABLE is an existing blocker — no new state was invented."""
        r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["goal"]["lifecycle"], gl.BLOCKED)
        self.assertEqual(r["goal"]["blocker"], gl.BLOCKED_UNAVAILABLE)
        self.assertIn(r["goal"]["blocker"], gl.BLOCKERS)

    def test_a_delivered_turn_still_completes_its_goal(self):
        """The blocking path must not have broken the ordinary one."""
        r = self.drive([Delivery()])
        self.assertEqual(r["goal"]["lifecycle"], gl.COMPLETED)

    def test_the_owner_is_notified_exactly_once(self):
        r = self.drive([TimeoutError("gw")])
        self.assertEqual(len(r["alerts"]), 1)

    def test_the_alert_says_it_was_recorded(self):
        r = self.drive([TimeoutError("gw")])
        self.assertIn("open commitment", r["alerts"][0])

    def test_the_alert_says_loudly_when_nothing_was_recorded(self):
        """§6.3 degrade loudly — the owner must not read a silent failure as
        a handled one. Reached now only for an obligation nobody has ruled
        on, which is the case the refusal was narrowed to."""
        with mock.patch.dict(esc._SLA, {}, clear=True):
            r = self.drive([TimeoutError("gw")])
        self.assertIn("NOT recorded", r["alerts"][0])

    def test_the_alert_leaks_no_internal_identifiers(self):
        r = self.drive([TimeoutError("gw")])
        alert = r["alerts"][0]
        self.assertNotIn(r["rows"][0]["commitment_id"], alert)
        self.assertNotIn(r["rows"][0]["decision_ref"], alert)
        self.assertNotIn("subj-fixed", alert)
        self.assertNotIn("wamid", alert)

    def test_a_store_failure_never_breaks_the_turn(self):
        """An undelivered reply must not also become a 500."""
        with mock.patch.object(cm, "save", side_effect=DbError("down")):
            r = self.drive([TimeoutError("gw")])
        self.assertEqual(r["escalation"]["escalation"], esc.PERSISTENCE_FAILED)
        self.assertEqual(len(r["alerts"]), 1)


class NotAnOutcomeThroughThePipeline(PipelineBase):

    def test_no_outcome_record_is_written_when_a_commitment_is_created(self):
        """2I opens a window only when a reply actually reached the customer.
        An undelivered turn must not register an expectation, or 2I would
        later close it as 'we asked and nothing came back'."""
        calls = []
        with mock.patch.object(w.bic_outcome_producers, "expect_customer_reply",
                               lambda *a, **k: calls.append(a)):
            r = self.drive([TimeoutError("gw")])
        self.assertEqual(len(r["rows"]), 1)
        self.assertEqual(calls, [], "a commitment is not an outcome")

    def test_no_claim_is_written_when_a_commitment_is_created(self):
        tables = []
        with mock.patch.object(w.bic_db, "insert",
                               lambda table, row, **k: tables.append(table)):
            self.drive([TimeoutError("gw")])
        self.assertNotIn("bic_claims", tables)


# ══════════════════════════════════════════════════════════════════════
# DIGEST REPORTING FOLLOWS THE SAME POLICY
# ══════════════════════════════════════════════════════════════════════
# api/digest.py reports through commitment.overdue(). These pin that the
# report's notion of "late" is the SLA's notion of "late" — one policy, not
# two that drift apart.

class DigestOverdueFollowsTheSla(unittest.TestCase):

    def setUp(self):
        self.store = FakeStore()
        for target, fn in (("insert", self.store.insert),
                           ("select", self.store.select)):
            p = mock.patch.object(cm, target, fn)
            p.start()
            self.addCleanup(p.stop)
        r = esc.escalate(human_review(), **kwargs())
        self.assertEqual(r["escalation"], esc.RECORDED)

    def due(self, **delta):
        return cm.overdue(TENANT, now=NOW + timedelta(**delta))

    def test_nothing_is_reported_immediately(self):
        self.assertEqual(self.due(seconds=1), [])

    def test_nothing_is_reported_just_before_four_hours(self):
        self.assertEqual(self.due(hours=3, minutes=59, seconds=59), [])

    def test_nothing_is_reported_at_exactly_four_hours(self):
        self.assertEqual(self.due(hours=4), [])

    def test_it_is_reported_just_after_four_hours(self):
        self.assertEqual(len(self.due(hours=4, seconds=1)), 1)

    def test_it_stays_reported_the_next_day(self):
        self.assertEqual(len(self.due(days=1)), 1)

    def test_an_overnight_failure_is_reported_four_hours_later_not_at_9am(self):
        """The clock does not pause, so a 23:30 failure is late at 03:30 —
        the digest reports it, it does not wait for business hours."""
        store = FakeStore()
        with mock.patch.object(cm, "insert", store.insert), \
             mock.patch.object(cm, "select", store.select):
            night = datetime(2026, 8, 24, 23, 30, tzinfo=timezone.utc)
            esc.escalate(human_review(), **kwargs(now=night, party="p-night"))
            at_0331 = datetime(2026, 8, 25, 3, 31, tzinfo=timezone.utc)
            self.assertEqual(len(cm.overdue(TENANT, now=at_0331)), 1)

    def test_a_weekend_failure_is_reported_four_hours_later_not_on_monday(self):
        store = FakeStore()
        with mock.patch.object(cm, "insert", store.insert), \
             mock.patch.object(cm, "select", store.select):
            sat = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
            esc.escalate(human_review(), **kwargs(now=sat, party="p-sat"))
            still_sat = datetime(2026, 8, 29, 18, 1, tzinfo=timezone.utc)
            rows = cm.overdue(TENANT, now=still_sat)
            self.assertEqual(len(rows), 1)
            self.assertEqual(still_sat.weekday(), 5)

    def test_the_digest_never_transitions_anything_to_missed(self):
        """"missed" is a business judgement with a reason and an actor. A
        clock tick is neither, so the report is strictly read-only."""
        self.due(days=3)
        self.assertEqual(len(self.store.transitions), 0)
        self.assertEqual(self.store.rows[0]["lifecycle"], cm.MADE)

    def test_the_digest_block_is_read_only_in_source(self):
        """CODE lines only — the block's comments discuss `missed` at length,
        and prose must not be able to trip a structural rule."""
        src = pathlib.Path(os.path.join(os.path.dirname(__file__), "..",
                                        "api", "digest.py")).read_text()
        block = src[src.index("what have we promised"):]
        code = "\n".join(l for l in block.splitlines()
                         if not l.strip().startswith("#"))
        for banned in ("record_transition", "miss(", "MISSED", "insert(",
                       "update(", "rpc("):
            self.assertNotIn(banned, code)
        self.assertIn("overdue(", code, "the block must still do the read")
