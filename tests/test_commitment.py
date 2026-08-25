"""IDD-2B Commitment — any promise with a party, obligation and deadline.

The sharpest tests are the negative ones: a promise with no owner, a promise
already overdue when made, a terminal state quietly reopening, and `met`
reached without ever being worked on. 2B's diagram permits none of them, and
each is a way a business loses track of what it owes.

Offline: no network, no AI, no database.
"""

import ast
import os
import pathlib
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import commitment as cm                                # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
PARTY = "805d1c4e-0000-4000-8000-000000000001"     # opaque 2B knowledge_id
OWNER = "9f2a1b3c-0000-4000-8000-00000000000a"     # an AGENT knowledge_id
DECISION = "dec-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

NOW = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
DUE = NOW + timedelta(days=7)

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "commitment.py")


def code_only(path) -> str:
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


def made(**kw):
    kw.setdefault("tenant_id", TENANT)
    kw.setdefault("party", PARTY)
    kw.setdefault("obligation", "resolve_undelivered_reply")
    kw.setdefault("due_on", DUE)
    kw.setdefault("owner", OWNER)
    kw.setdefault("decision_ref", DECISION)
    kw.setdefault("at", NOW)
    return cm.make(**kw)


# ── 1-7 · creation and required fields ──────────────────────────────────

class Creation(unittest.TestCase):

    def test_create_starts_in_made(self):
        self.assertEqual(made()["lifecycle"], cm.MADE)

    def test_party_obligation_due_on_and_owner_are_required(self):
        """2B Required: party, obligation, due_on, owner."""
        for field in ("party", "obligation", "due_on", "owner"):
            with self.subTest(field=field):
                with self.assertRaises(cm.CommitmentError):
                    made(**{field: None})

    def test_owner_is_never_null(self):
        """'Every Commitment has an accountable owner (an AGENT). Never null.'"""
        with self.assertRaises(cm.CommitmentError):
            made(owner="")
        self.assertTrue(made()["owner"])

    def test_tenant_is_required(self):
        with self.assertRaises(cm.CommitmentError):
            made(tenant_id="")

    def test_a_promise_cannot_be_made_already_overdue(self):
        with self.assertRaises(cm.CommitmentError):
            made(due_on=NOW - timedelta(days=1))

    def test_unparseable_deadline_is_refused_not_defaulted(self):
        with self.assertRaises(cm.CommitmentError):
            made(due_on="whenever")

    def test_optional_fields_are_exactly_2bs(self):
        c = made(penalty="p", source="s", criticality="high")
        for f in ("penalty", "source", "criticality"):
            self.assertEqual(c[f], {"penalty": "p", "source": "s",
                                    "criticality": "high"}[f])

    def test_no_speculative_fields(self):
        c = made()
        self.assertEqual(set(c), {
            "commitment_id", "tenant_id", "subject", "party", "due_on",
            "obligation", "owner", "lifecycle", "decision_ref", "goal_ref",
            "penalty", "source", "criticality", "approver", "superseded_by",
            "created_at", "history"})

    def test_each_commitment_gets_a_fresh_id(self):
        self.assertNotEqual(made()["commitment_id"], made()["commitment_id"])


# ── 8-13 · the 2B lifecycle ─────────────────────────────────────────────

class Lifecycle(unittest.TestCase):

    def test_states_are_exactly_2bs(self):
        self.assertEqual(set(cm.STATES),
                         {"made", "in_progress", "met", "missed", "waived",
                          "renegotiated"})

    def test_lifecycle_is_not_the_goal_vocabulary(self):
        """A goal is what we are trying to do; a commitment is what we owe."""
        for goal_state in ("ADMITTED", "ACTIVE", "BLOCKED", "COMPLETED",
                           "ABANDONED", "EXPIRED"):
            self.assertNotIn(goal_state, cm.STATES)

    def test_made_to_in_progress_to_met(self):
        c = cm.meet(cm.start(made()))
        self.assertEqual(c["lifecycle"], cm.MET)

    def test_missed_from_made(self):
        self.assertEqual(cm.miss(made(), reason="never actioned")["lifecycle"],
                         cm.MISSED)

    def test_missed_from_in_progress(self):
        c = cm.miss(cm.start(made()), reason="deadline passed")
        self.assertEqual(c["lifecycle"], cm.MISSED)

    def test_missed_requires_a_reason(self):
        with self.assertRaises(cm.CommitmentError):
            cm.miss(made(), reason="")

    def test_waived_requires_an_approver(self):
        """2B's diagram annotates waived '(requires approver)'."""
        with self.assertRaises(cm.CommitmentError):
            cm.waive(made(), approver="", reason="customer withdrew")
        c = cm.waive(made(), approver=OWNER, reason="customer withdrew")
        self.assertEqual(c["lifecycle"], cm.WAIVED)
        self.assertEqual(c["approver"], OWNER)

    def test_renegotiation_closes_the_old_and_returns_a_successor(self):
        """'renegotiated → made (new commitment, old one closed)'."""
        old, new = cm.renegotiate(made(), due_on=DUE + timedelta(days=7),
                                  reason="customer asked for more time", at=NOW)
        self.assertEqual(old["lifecycle"], cm.RENEGOTIATED)
        self.assertEqual(new["lifecycle"], cm.MADE)
        self.assertNotEqual(old["commitment_id"], new["commitment_id"])

    def test_renegotiation_names_its_successor(self):
        """2B for Document: 'superseded requires naming the successor.'"""
        old, new = cm.renegotiate(made(), due_on=DUE + timedelta(days=1),
                                  reason="slipped", at=NOW)
        self.assertEqual(old["superseded_by"], new["commitment_id"])

    def test_renegotiation_carries_the_original_attribution(self):
        _, new = cm.renegotiate(made(), due_on=DUE + timedelta(days=1),
                                reason="slipped", at=NOW)
        self.assertEqual(new["decision_ref"], DECISION)
        self.assertEqual(new["party"], PARTY)


# ── 14-15 · illegal and terminal transitions ────────────────────────────

class IllegalTransitions(unittest.TestCase):

    def test_met_is_unreachable_without_being_worked_on(self):
        """The diagram routes met only through in_progress."""
        with self.assertRaises(cm.CommitmentError):
            cm.meet(made())

    def test_renegotiate_is_not_available_once_in_progress(self):
        with self.assertRaises(cm.CommitmentError):
            cm.renegotiate(cm.start(made()), due_on=DUE, reason="x", at=NOW)

    def test_waive_is_available_from_made_and_from_in_progress(self):
        """OWNER RULING: work already started can still be forgiven. Refusing
        it would force a real waiver to be recorded as a miss, corrupting the
        signal 2B calls out as the reliability signal."""
        self.assertEqual(
            cm.waive(made(), approver=OWNER, reason="r")["lifecycle"], cm.WAIVED)
        self.assertEqual(
            cm.waive(cm.start(made()), approver=OWNER, reason="r")["lifecycle"],
            cm.WAIVED)

    def test_no_backwards_transition(self):
        with self.assertRaises(cm.CommitmentError):
            cm.start(cm.start(made()))

    def test_terminal_states_never_reopen(self):
        terminals = [
            cm.meet(cm.start(made())),
            cm.miss(made(), reason="r"),
            cm.waive(made(), approver=OWNER, reason="r"),
            cm.renegotiate(made(), due_on=DUE, reason="r", at=NOW)[0],
        ]
        for c in terminals:
            with self.subTest(state=c["lifecycle"]):
                for fn in (cm.start, cm.meet):
                    with self.assertRaises(cm.CommitmentError):
                        fn(c)
                with self.assertRaises(cm.CommitmentError):
                    cm.miss(c, reason="r")

    def test_missed_is_never_deleted_or_rewritten(self):
        """'missed is recorded, never deleted. Missed commitments are the
        reliability signal.'"""
        missed = cm.miss(made(), reason="never actioned")
        with self.assertRaises(cm.CommitmentError):
            cm.meet(missed)
        self.assertEqual(missed["lifecycle"], cm.MISSED)
        code = code_only(MODULE).lower()
        self.assertNotIn("delete", code)


# ── 16 · history ────────────────────────────────────────────────────────

class History(unittest.TestCase):

    def test_history_records_every_transition(self):
        c = cm.meet(cm.start(made()))
        self.assertEqual([h["state"] for h in c["history"]],
                         [cm.MADE, cm.IN_PROGRESS, cm.MET])

    def test_transitions_do_not_mutate_the_prior_record(self):
        c = made()
        cm.start(c)
        self.assertEqual(c["lifecycle"], cm.MADE)

    def test_every_transition_carries_a_reason_and_a_time(self):
        c = cm.miss(made(), reason="deadline passed")
        for h in c["history"]:
            self.assertTrue(h["reason"])
            self.assertTrue(h["at"])


# ── 17-19 · attribution and relationships ───────────────────────────────

class Attribution(unittest.TestCase):

    def test_single_decision_attribution(self):
        self.assertEqual(made()["decision_ref"], DECISION)

    def test_goal_reference_is_carried_when_supplied(self):
        self.assertEqual(made(goal_ref="social_media_enquiry")["goal_ref"],
                         "social_media_enquiry")

    def test_no_shortcut_attribution_edges(self):
        c = made()
        for shortcut in ("customer_id", "lead_id", "project_id", "phone",
                         "wamid", "invoice_id"):
            self.assertNotIn(shortcut, c)

    def test_tenant_is_carried_and_distinct(self):
        self.assertEqual(made()["tenant_id"], TENANT)
        self.assertNotEqual(made()["tenant_id"], OTHER_TENANT)


# ── deadlines ───────────────────────────────────────────────────────────

class Deadlines(unittest.TestCase):

    def test_overdue_detection_is_deterministic(self):
        c = made()
        self.assertFalse(cm.is_overdue(c, now=DUE - timedelta(hours=1)))
        self.assertTrue(cm.is_overdue(c, now=DUE + timedelta(hours=1)))

    def test_a_terminal_commitment_is_never_overdue(self):
        for c in (cm.meet(cm.start(made())), cm.miss(made(), reason="r"),
                  cm.waive(made(), approver=OWNER, reason="r")):
            with self.subTest(state=c["lifecycle"]):
                self.assertFalse(cm.is_overdue(c, now=DUE + timedelta(days=99)))

    def test_overdue_detection_never_transitions_on_its_own(self):
        """'missed' is a business judgement with a reason, not a clock tick."""
        c = made()
        cm.is_overdue(c, now=DUE + timedelta(days=1))
        self.assertEqual(c["lifecycle"], cm.MADE)

    def test_renegotiation_is_how_a_deadline_moves(self):
        old, new = cm.renegotiate(made(), due_on=DUE + timedelta(days=30),
                                  reason="agreed extension", at=NOW)
        self.assertNotEqual(old["due_on"], new["due_on"])
        self.assertEqual(old["lifecycle"], cm.RENEGOTIATED)


# ── 20-23 · boundaries ──────────────────────────────────────────────────

class Boundaries(unittest.TestCase):

    def test_never_writes_a_claim_or_an_outcome(self):
        code = code_only(MODULE)
        for banned in ("bic_claims", "assert_claim", "outcomes",
                       "bic_outcome_records"):
            self.assertNotIn(banned, code)

    def test_a_missed_commitment_is_not_an_outcome_record(self):
        """What WE failed to do is not what the WORLD did."""
        c = cm.miss(made(), reason="r")
        for banned in ("observed_state", "observation_status", "outcome_kind",
                       "verdict"):
            self.assertNotIn(banned, c)

    def test_no_model_or_network(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "llm", "requests", "http", "urllib"):
            self.assertNotIn(banned, code)

    def test_no_pii_vocabulary(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "message_body",
                       "display_name"):
            self.assertNotIn(banned, code)

    def test_no_pii_in_a_record(self):
        blob = repr(made())
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob))
        self.assertNotIn("wamid", blob)

    def test_describe_carries_no_party_owner_or_subject(self):
        d = cm.describe(made())
        for identifying in ("party", "owner", "subject", "tenant_id"):
            self.assertNotIn(identifying, d)


# ── 15 · adversarial ────────────────────────────────────────────────────

class Adversarial(unittest.TestCase):

    def test_a_model_claiming_done_cannot_meet_a_commitment(self):
        """Completion is a transition, not an assertion. There is no argument
        by which text reaches this module."""
        c = made()
        with self.assertRaises(cm.CommitmentError):
            cm.meet(c)          # still `made` — no in_progress, no met
        self.assertEqual(c["lifecycle"], cm.MADE)

    def test_a_customer_saying_done_cannot_meet_a_commitment(self):
        started = cm.start(made())
        self.assertEqual(cm.meet(started)["lifecycle"], cm.MET)
        # ...but only because the CALLER transitioned it; no free text path.
        code = code_only(MODULE).lower()
        for banned in ("text", "said", "claim", "assert"):
            self.assertNotIn(f"if {banned}", code)

    def test_a_waiver_without_an_approver_is_refused(self):
        with self.assertRaises(cm.CommitmentError):
            cm.waive(made(), approver=None, reason="r")

    def test_renegotiating_a_terminal_commitment_is_refused(self):
        met = cm.meet(cm.start(made()))
        with self.assertRaises(cm.CommitmentError):
            cm.renegotiate(met, due_on=DUE, reason="r", at=NOW)

    def test_two_commitments_for_the_same_decision_are_distinct_records(self):
        """Deduplication is a STORE concern (a unique index on the identifying
        assertions). The object itself never silently merges two promises."""
        a, b = made(), made()
        self.assertNotEqual(a["commitment_id"], b["commitment_id"])

    def test_state_evaluation_is_deterministic(self):
        c = made()
        self.assertEqual([cm.is_overdue(c, now=DUE + timedelta(days=1))
                          for _ in range(5)], [True] * 5)


# ── Migration safety (asserted against the SQL, like test_outcomes.py) ──

MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                   "20260816000018_bic_commitments.sql")


class Migration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MIG) as fh:
            cls.raw = fh.read()
        # Strip comments and string literals so prose cannot satisfy — or
        # trip — an assertion about the SQL itself.
        out, i, ins = [], 0, False
        raw = cls.raw
        while i < len(raw):
            c = raw[i]
            if ins:
                if c == "'":
                    if i + 1 < len(raw) and raw[i + 1] == "'":
                        i += 2
                        continue
                    ins = False
                i += 1
                continue
            if c == "'":
                ins = True
                i += 1
                continue
            if raw[i:i + 2] == "--":
                while i < len(raw) and raw[i] != "\n":
                    i += 1
                continue
            out.append(c)
            i += 1
        cls.code = "".join(out)

    def test_creates_only_the_two_commitment_tables(self):
        self.assertEqual(
            re.findall(r"create table if not exists (\w+)", self.code),
            ["bic_commitments", "bic_commitment_transitions"])

    def test_touches_no_other_bic_table(self):
        for table in ("bic_claims", "bic_outcome_records", "bic_decision_records",
                      "bic_webhook_events", "bic_party_identifiers",
                      "bic_replay_records", "bic_tool_defs"):
            self.assertNotIn(table, self.code)

    def test_party_is_the_only_foreign_key_outside_the_module(self):
        refs = set(re.findall(r"references (\w+)", self.code))
        self.assertEqual(refs, {"bic_parties", "bic_commitments"})

    def test_no_destructive_sql(self):
        self.assertIsNone(re.search(r"(?im)^\s*(delete|truncate|drop table)\b",
                                    self.code))

    def test_rls_enabled_on_both_tables(self):
        self.assertEqual(len(re.findall(r"enable row level security",
                                        self.code)), 2)

    def test_lifecycle_check_carries_exactly_the_six_states(self):
        for state in cm.STATES:
            self.assertIn(f"'{state}'", self.raw)
        for foreign in ("COMPLETED", "ADMITTED", "BLOCKED", "ACTIVE"):
            self.assertNotIn(f"'{foreign}'", self.raw)

    def test_identity_index_is_unique_and_nulls_not_distinct(self):
        """OWNER RULING: two subject-less promises to the same party with the
        same deadline are ONE commitment."""
        self.assertIn("nulls not distinct", self.code)
        self.assertRegex(self.code, r"create unique index[^;]+bic_commitments"
                                    r"[^;]+tenant_id, subject, party, due_on")

    def test_owner_is_not_nullable(self):
        self.assertRegex(self.code, r"owner\s+text not null")

    def test_history_is_append_only(self):
        self.assertIn("bic_reject_mutation", self.code)
        self.assertIn("before update or delete on bic_commitment_transitions",
                      self.code)

    def test_commitments_are_never_deleted(self):
        """2B criterion 16: missed recorded and retained; not deleted."""
        self.assertIn("before delete on bic_commitments", self.code)

    def test_the_promise_itself_is_frozen_after_insert(self):
        for frozen in ("obligation", "due_on", "owner", "party", "decision_ref"):
            self.assertIn(f"new.{frozen}", self.code)

    def test_waiver_requires_an_actor_at_the_database(self):
        """Structure asserted on `code` (literals are blanked there) and the
        literal on `raw` — asserting a quoted value against the blanked text
        can never fail honestly."""
        self.assertIn("bic_commitment_waiver_needs_an_actor", self.code)
        self.assertIn("actor is not null", self.code)
        self.assertIn("to_state <> 'waived'", self.raw)

    def test_no_pii_columns(self):
        for banned in ("phone", "email", "wamid", "source_ref", "message",
                       "display_name", "legal_name"):
            self.assertNotIn(banned, self.code)

    def test_no_phone_literal_anywhere(self):
        self.assertIsNone(re.search(r"\b\d{10,15}\b", self.raw))

    def test_tenant_isolation_on_both_tables(self):
        self.assertEqual(len(re.findall(r"tenant_id\s+uuid not null",
                                        self.code)), 2)
