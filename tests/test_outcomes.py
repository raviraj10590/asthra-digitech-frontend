"""IDD-2I Outcome Intelligence — observation, not evaluation.

THE ONE RULE EVERYTHING ELSE SERVES (§0.2)
------------------------------------------
    "Record what happened. Derive whether it was good."

Record SUCCESS and you bake in a 2026 definition of success; when the yardstick
changes in 2028, every historical outcome silently means something different.
So the sharpest tests below are the ones asserting what is NOT stored — no
success column, no verdict column, no evaluation write path.

THE OTHER FAILURE THIS GUARDS
-----------------------------
I2: "Quotation sent, HTTP 200" is an execution result; "quotation accepted on
day 12" is an outcome. Train on the first and every metric stays green while
the models learn nothing about whether you win work. Several tests assert that
execution telemetry cannot become an outcome.

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

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from unittest import mock                                        # noqa: E402
from bic import outcomes as oc                                   # noqa: E402
from bic.db import DbError                                       # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
SUBJECT = "805d1c4e-0000-4000-8000-000000000001"
OTHER_SUBJECT = "d542ac32-0000-4000-8000-000000000002"
DECISION = "dec-11111111-1111-4111-8111-111111111111"
OTHER_DECISION = "dec-22222222-2222-4222-8222-222222222222"

MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                   "20260816000017_bic_outcome_records.sql")


def code_only(path) -> str:
    """Source with docstrings, comments and string literals blanked.

    Negative assertions MUST read this, never the raw file. bic/outcomes.py
    documents at length why it never writes to bic_claims and why lessons are
    excluded — and a raw grep finds those words inside the very explanation of
    why they are forbidden. This project has been bitten by that repeatedly;
    reading prose is not testing behaviour.
    """
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "outcomes.py")


def ts(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


BASE = ts("2026-08-21T06:00:00")


class FakeOutcomeDb:
    """In-memory store enforcing the append-only trigger, like Postgres."""

    def __init__(self):
        self.records, self.retractions = [], []

    def insert(self, table, row, timeout=None):
        if table == oc.TABLE:
            self.records.append(dict(row))
        elif table == oc.RETRACTIONS_TABLE:
            self.retractions.append(dict(row))
        else:
            raise AssertionError(f"unexpected table {table}")

    def update(self, table, params, patch, timeout=None):
        raise AssertionError(f"{table} is append-only: UPDATE rejected")

    def delete(self, table, params, timeout=None):
        raise AssertionError(f"{table} is append-only: DELETE rejected")

    def select(self, table, params, timeout=None):
        rows = self.records if table == oc.TABLE else self.retractions
        out = []
        for row in rows:
            keep = True
            for key, val in params.items():
                if key in ("order", "limit", "select"):
                    continue
                val = str(val)
                if val.startswith("eq.") and str(row.get(key)) != val[3:]:
                    keep = False
                elif val.startswith("in.") and str(row.get(key)) not in \
                        val[4:-1].split(","):
                    keep = False
            if keep:
                out.append(dict(row))
        out.sort(key=lambda r: r.get("recorded_at") or "")
        return out


class Base(unittest.TestCase):

    def setUp(self):
        self.db = FakeOutcomeDb()
        self._p = [mock.patch.object(oc, "insert", self.db.insert),
                   mock.patch.object(oc, "select", self.db.select)]
        for p in self._p:
            p.start()
        self.clock = BASE

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def expect(self, *, decision=DECISION, kind="customer_reply",
               window=86400, at=None, **kw):
        return oc.expect(TENANT, kw.pop("subject", SUBJECT), decision,
                         outcome_kind=kind, window_seconds=window,
                         at=at or self.clock, **kw)


# ── 1-3 · creation and the expectation model ───────────────────────────────

class Creation(Base):

    def test_expectation_is_created_at_decision_time(self):
        """I6 — an outcome that only exists once something is observed can
        never record TIMED_OUT, because nothing is watching."""
        rec = self.expect()
        self.assertEqual(rec["lifecycle"], oc.EXPECTED)
        self.assertIsNone(rec["observed_state"])
        self.assertIsNone(rec["observation_status"])

    def test_window_is_declared_per_decision(self):
        """I12 — observation windows are declared, never assumed."""
        rec = self.expect(window=3600)
        self.assertEqual(rec["window_seconds"], 3600)
        self.assertEqual(oc._parse(rec["window_closes_at"]),
                         self.clock + timedelta(seconds=3600))

    def test_a_window_is_mandatory(self):
        for bad in (0, -1, None, "a day"):
            with self.assertRaises(oc.OutcomeError):
                oc.expect(TENANT, SUBJECT, DECISION,
                          outcome_kind="k", window_seconds=bad)

    def test_attribution_is_mandatory(self):
        with self.assertRaises(oc.OutcomeError):
            oc.expect(TENANT, SUBJECT, "", outcome_kind="k",
                      window_seconds=60)

    def test_carries_2h_references_not_the_packet(self):
        rec = self.expect(goal_ref="social_media_enquiry", risk_tier=1,
                          sufficiency_verdict="PROCEED",
                          evidence_refs=["claim-a", "claim-b"])
        self.assertEqual(rec["goal_ref"], "social_media_enquiry")
        self.assertEqual(rec["risk_tier"], 1)
        self.assertEqual(rec["evidence_refs"], ["claim-a", "claim-b"])
        # §4.1 — the packet stays reachable through the decision; a copy here
        # would drift from the original.
        for packet_field in ("evidence", "boundaries", "epistemic", "question"):
            self.assertNotIn(packet_field, rec)

    def test_expected_state_must_be_an_observed_state(self):
        with self.assertRaises(oc.OutcomeError):
            self.expect(expected_state="SUCCESS")


# ── 4, 11-12 · observed states and statuses ────────────────────────────────

class ObservedStates(Base):

    def test_six_observed_states(self):
        self.assertEqual(len(oc.OBSERVED_STATES), 6)
        self.assertEqual(sorted(oc.OBSERVED_STATES),
                         ["CANCELLED", "DECLINED", "EXPIRED", "NO_RESPONSE",
                          "RESOLVED", "SUPERSEDED"])

    def test_five_observation_statuses(self):
        self.assertEqual(len(oc.OBSERVATION_STATUSES), 5)

    def test_success_and_failure_are_not_observed_states(self):
        """§2.1 — they are evaluations, and storing them is the mistake this
        design exists to prevent."""
        for evaluation in ("SUCCESS", "FAILURE", "PARTIAL", "NEUTRAL"):
            self.assertNotIn(evaluation, oc.OBSERVED_STATES)
            with self.assertRaises(oc.OutcomeError):
                oc.observe(TENANT, self.expect(), evaluation, oc.OBSERVED)

    def test_state_and_status_are_orthogonal(self):
        rec = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.REPORTED)
        self.assertEqual(rec["observed_state"], oc.RESOLVED)
        self.assertEqual(rec["observation_status"], oc.REPORTED)

    def test_timed_out_is_data_not_a_gap(self):
        """I7 — we watched and nothing came. Distinct from never watching."""
        rec = oc.time_out(TENANT, self.expect(),
                          at=self.clock + timedelta(days=2))
        self.assertEqual(rec["observed_state"], oc.NO_RESPONSE)
        self.assertEqual(rec["observation_status"], oc.TIMED_OUT)

    def test_timed_out_differs_from_unobservable(self):
        self.assertNotEqual(oc.TIMED_OUT, oc.UNOBSERVABLE)
        self.assertGreater(oc.STATUS_CONFIDENCE_CAP[oc.TIMED_OUT],
                           oc.STATUS_CONFIDENCE_CAP[oc.UNOBSERVABLE])

    def test_reported_is_capped_at_tier_five(self):
        """I11 / Article II.6 — a party telling us is worth 0.50, however
        emphatically they tell us."""
        self.assertEqual(oc.STATUS_CONFIDENCE_CAP[oc.REPORTED], 0.50)

    def test_declined_is_distinct_from_no_response(self):
        """Losing by silence is not the same as losing to a competitor."""
        self.assertNotEqual(oc.DECLINED, oc.NO_RESPONSE)

    def test_an_observation_needs_both_halves(self):
        with self.assertRaises(oc.OutcomeError):
            oc.observe(TENANT, self.expect(), oc.RESOLVED, "GUESSED")


# ── 2, 9-10, 24 · append-only, revision, retraction ────────────────────────

class AppendOnly(Base):

    def test_observation_appends_and_never_edits(self):
        """I3."""
        exp = self.expect()
        obs = oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED)
        self.assertEqual(len(self.db.records), 2)
        self.assertNotEqual(obs["outcome_id"], exp["outcome_id"])
        self.assertEqual(obs["revises"], exp["outcome_id"])

    def test_the_original_stays_readable_forever(self):
        exp = self.expect()
        oc.observe(TENANT, exp, oc.DECLINED, oc.OBSERVED)
        first = self.db.records[0]
        self.assertEqual(first["lifecycle"], oc.EXPECTED)
        self.assertIsNone(first["observed_state"])

    def test_module_has_no_update_path(self):
        tree = ast.parse(pathlib.Path(MODULE).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "db":
                imported |= {a.name for a in node.names}
        self.assertNotIn("update", imported)
        self.assertNotIn("delete", imported)

    def test_revision_appends_a_linked_record(self):
        exp = self.expect()
        obs = oc.observe(TENANT, exp, oc.NO_RESPONSE, oc.TIMED_OUT)
        rev = oc.revise(TENANT, obs, oc.RESOLVED, oc.OBSERVED,
                        observed_at=self.clock + timedelta(days=40),
                        reason="payment cleared late")
        self.assertEqual(rev["revises"], obs["outcome_id"])
        self.assertEqual(len(self.db.records), 3)
        self.assertEqual(self.db.records[1]["observed_state"], oc.NO_RESPONSE)

    def test_retraction_is_its_own_record(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        oc.retract(TENANT, obs["outcome_id"], "misattributed", "raviraj")
        self.assertEqual(len(self.db.retractions), 1)
        self.assertEqual(len(self.db.records), 2)   # nothing deleted

    def test_retraction_needs_a_reason_and_an_author(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        for reason, who in (("", "raviraj"), ("x", "")):
            with self.assertRaises(oc.OutcomeError):
                oc.retract(TENANT, obs["outcome_id"], reason, who)

    def test_retirement_is_not_deletion(self):
        """§3.5 — 'we used to believe this, and stopped' is knowledge."""
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        ret = oc.retire(TENANT, obs, reason="market changed")
        self.assertEqual(ret["lifecycle"], oc.RETIRED)
        self.assertEqual(len(self.db.records), 3)

    def test_retirement_needs_a_reason(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        with self.assertRaises(oc.OutcomeError):
            oc.retire(TENANT, obs, reason="")


# ── 5, 15 · attribution ────────────────────────────────────────────────────

class Attribution(Base):

    def test_exactly_one_attribution_edge(self):
        """I4."""
        rec = self.expect()
        self.assertEqual(rec["decision_ref"], DECISION)

    def test_no_shortcut_edges_to_customer_or_project(self):
        """2B §4.3 — two paths to the same fact will diverge."""
        rec = self.expect()
        for shortcut in ("customer_id", "project_id", "party_id", "lead_id",
                         "invoice_id"):
            self.assertNotIn(shortcut, rec)

    def test_the_question_is_answerable(self):
        exp = self.expect()
        oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED)
        rows = oc.history(TENANT, DECISION)
        self.assertTrue(rows)
        self.assertEqual({r["decision_ref"] for r in rows}, {DECISION})

    def test_contributing_factors_are_not_attribution(self):
        """§4.2 — zero or many, associative, never justify an action alone."""
        obs = oc.observe(TENANT, self.expect(), oc.EXPIRED, oc.INFERRED,
                         contributing_factors=["supplier delay", "festival week"])
        self.assertEqual(len(obs["contributing_factors"]), 2)
        self.assertEqual(obs["decision_ref"], DECISION)   # still exactly one

    def test_no_temporal_or_fuzzy_attribution(self):
        code = code_only(MODULE).lower()
        for smell in ("fuzzy", "similar", "nearest", "guess", "best_match",
                      "infer_decision", "probable"):
            self.assertNotIn(smell, code)

    def test_multi_decision_outcomes_get_their_own_records(self):
        """§4.4 — splitting one outcome across decisions would need invented
        weights."""
        a = self.expect(decision=DECISION)
        b = self.expect(decision=OTHER_DECISION)
        oc.observe(TENANT, a, oc.SUPERSEDED, oc.OBSERVED)
        oc.observe(TENANT, b, oc.RESOLVED, oc.OBSERVED)
        self.assertEqual(len(oc.history(TENANT, DECISION)), 2)
        self.assertEqual(len(oc.history(TENANT, OTHER_DECISION)), 2)


# ── 6 · asynchronous observation ───────────────────────────────────────────

class Asynchronous(Base):

    def test_outcome_may_arrive_long_after_the_action(self):
        exp = self.expect(window=86400)
        obs = oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED,
                         observed_at=self.clock + timedelta(days=12))
        self.assertEqual(obs["elapsed_seconds"], 12 * 86400)
        self.assertTrue(obs["late_beyond_window"])

    def test_delay_is_an_attribute_not_a_state(self):
        """§2.6 — a payment 40 days late that ARRIVES is RESOLVED with a large
        variance. Delay describes the path; state describes the destination."""
        obs = oc.observe(TENANT, self.expect(window=86400), oc.RESOLVED,
                         oc.OBSERVED,
                         observed_at=self.clock + timedelta(days=40))
        self.assertEqual(obs["observed_state"], oc.RESOLVED)
        self.assertEqual(obs["variance_vs_expected"], 40.0)
        self.assertNotIn("DELAYED", oc.OBSERVED_STATES)

    def test_no_outcome_is_required_during_the_original_turn(self):
        rec = self.expect()
        self.assertEqual(rec["lifecycle"], oc.EXPECTED)
        self.assertEqual(len(self.db.records), 1)

    def test_window_closure_is_derived_not_stored(self):
        self.expect(window=3600)
        later = self.clock + timedelta(hours=2)
        view = oc.current(TENANT, DECISION, now=later)
        self.assertEqual(view["customer_reply"]["lifecycle"], oc.CLOSED)

    def test_open_window_stays_expected(self):
        self.expect(window=86400)
        view = oc.current(TENANT, DECISION,
                          now=self.clock + timedelta(hours=1))
        self.assertEqual(view["customer_reply"]["lifecycle"], oc.EXPECTED)

    def test_due_for_timeout_reports_but_does_not_act(self):
        self.expect(window=3600)
        due = oc.due_for_timeout(TENANT, now=self.clock + timedelta(hours=2))
        self.assertEqual(len(due), 1)
        # Reporting only: writing NO_RESPONSE is an observation, made
        # deliberately, never as a side effect of a query.
        self.assertEqual(len(self.db.records), 1)


# ── 7-8 · provisional vs confirmed ─────────────────────────────────────────

class Provisional(Base):

    def test_expected_is_provisional(self):
        self.expect()
        view = oc.current(TENANT, DECISION, now=self.clock)
        r = oc.learning_readiness(view["customer_reply"]["record"],
                                  view["customer_reply"]["lifecycle"])
        self.assertTrue(r["provisional"])
        self.assertFalse(r["ready"])

    def test_observed_but_unconfirmed_is_provisional(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        r = oc.learning_readiness(obs, oc.L_OBSERVED)
        self.assertTrue(r["provisional"])
        self.assertFalse(r["ready"])
        self.assertIn("status_confirmed_or_closed", r["blocked_by"])

    def test_confirmation_makes_it_eligible(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED,
                         observed_at=self.clock)
        con = oc.confirm(TENANT, obs, corroborated_by="crm_invoice")
        ev = oc.evaluate(con, YARDSTICK)
        r = oc.learning_readiness(con, oc.CONFIRMED, evaluation=ev)
        self.assertFalse(r["provisional"])
        self.assertTrue(r["ready"], r["blocked_by"])

    def test_confirming_nothing_is_refused(self):
        with self.assertRaises(oc.OutcomeError):
            oc.confirm(TENANT, self.expect())

    def test_confirmation_appends(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        con = oc.confirm(TENANT, obs)
        self.assertEqual(con["revises"], obs["outcome_id"])
        self.assertEqual(len(self.db.records), 3)


# ── 14 · the readiness gate ────────────────────────────────────────────────

YARDSTICK = oc.yardstick("asthra_default", "2026.1", {
    oc.RESOLVED: oc.SUCCESS, oc.DECLINED: oc.FAILURE,
    oc.NO_RESPONSE: oc.FAILURE, oc.EXPIRED: oc.FAILURE,
    oc.CANCELLED: oc.NEUTRAL, oc.SUPERSEDED: oc.NEUTRAL})


class ReadinessGate(Base):

    def _confirmed(self, **kw):
        obs = oc.observe(TENANT, self.expect(**kw), oc.RESOLVED, oc.OBSERVED,
                         observed_at=kw.get("observed_at"))
        return oc.confirm(TENANT, obs)

    def test_all_six_conditions_reported(self):
        con = self._confirmed()
        r = oc.learning_readiness(con, oc.CONFIRMED,
                                  evaluation=oc.evaluate(con, YARDSTICK))
        self.assertEqual(sorted(r["checks"]), [
            "evaluation_with_yardstick", "no_unresolved_conflict",
            "not_late_unreliable", "not_retired", "single_attribution",
            "status_confirmed_or_closed"])

    def test_provisional_is_excluded_from_learning(self):
        """§3.3 — a lesson built on unconfirmed signal will be revised the
        moment reality arrives, having already influenced decisions."""
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        self.assertFalse(oc.learning_readiness(
            obs, oc.L_OBSERVED, evaluation=oc.evaluate(obs, YARDSTICK))["ready"])

    def test_unresolved_conflict_blocks(self):
        con = self._confirmed()
        r = oc.learning_readiness(con, oc.CONFIRMED,
                                  evaluation=oc.evaluate(con, YARDSTICK),
                                  conflicts=[{"sources": ["crm", "whatsapp"]}])
        self.assertFalse(r["ready"])
        self.assertIn("no_unresolved_conflict", r["blocked_by"])

    def test_missing_evaluation_blocks(self):
        con = self._confirmed()
        r = oc.learning_readiness(con, oc.CONFIRMED)
        self.assertFalse(r["ready"])
        self.assertIn("evaluation_with_yardstick", r["blocked_by"])

    def test_retired_blocks(self):
        con = self._confirmed()
        r = oc.learning_readiness(con, oc.RETIRED,
                                  evaluation=oc.evaluate(con, YARDSTICK))
        self.assertFalse(r["ready"])
        self.assertIn("not_retired", r["blocked_by"])

    def test_late_unreliable_blocks(self):
        """§6.1 — time delay degrades evidential value."""
        obs = oc.observe(TENANT, self.expect(window=3600), oc.RESOLVED,
                         oc.OBSERVED, observed_at=self.clock + timedelta(days=1))
        con = oc.confirm(TENANT, obs)
        r = oc.learning_readiness(con, oc.CONFIRMED,
                                  evaluation=oc.evaluate(con, YARDSTICK))
        self.assertFalse(r["ready"])
        self.assertIn("not_late_unreliable", r["blocked_by"])

    def test_the_gate_explains_itself(self):
        """A gate that says only 'no' gets worked around."""
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        self.assertTrue(oc.learning_readiness(obs, oc.L_OBSERVED)["blocked_by"])


# ── 13 · evaluation is derived, never stored ───────────────────────────────

class EvaluationIsDerived(Base):

    def test_evaluate_writes_nothing(self):
        """I1 — the enforcement is that there is no write path."""
        con = oc.confirm(TENANT, oc.observe(TENANT, self.expect(),
                                            oc.RESOLVED, oc.OBSERVED))
        before = len(self.db.records)
        ev = oc.evaluate(con, YARDSTICK)
        self.assertEqual(len(self.db.records), before)
        self.assertTrue(ev["derived"])
        self.assertFalse(ev["stored"])

    def test_no_success_column_is_ever_written(self):
        oc.confirm(TENANT, oc.observe(TENANT, self.expect(), oc.RESOLVED,
                                      oc.OBSERVED))
        for row in self.db.records:
            for banned in ("success", "verdict", "score", "evaluation",
                           "is_good", "rating"):
                self.assertNotIn(banned, row)

    def test_the_same_outcome_re_judges_under_a_new_yardstick(self):
        """§2.4 — change the target and history is re-judged, not rewritten."""
        con = oc.confirm(TENANT, oc.observe(TENANT, self.expect(),
                                            oc.NO_RESPONSE, oc.TIMED_OUT))
        strict = oc.yardstick("asthra", "2026.1", {oc.NO_RESPONSE: oc.FAILURE})
        lenient = oc.yardstick("asthra", "2027.1", {oc.NO_RESPONSE: oc.NEUTRAL})
        self.assertEqual(oc.evaluate(con, strict)["verdict"], oc.FAILURE)
        self.assertEqual(oc.evaluate(con, lenient)["verdict"], oc.NEUTRAL)
        # And the stored observation never changed.
        self.assertEqual(con["observed_state"], oc.NO_RESPONSE)

    def test_evaluation_names_its_yardstick_and_version(self):
        con = oc.confirm(TENANT, oc.observe(TENANT, self.expect(),
                                            oc.RESOLVED, oc.OBSERVED))
        ev = oc.evaluate(con, YARDSTICK)
        self.assertEqual(ev["yardstick_ref"], "asthra_default")
        self.assertEqual(ev["yardstick_version"], "2026.1")

    def test_evaluation_carries_the_confidence_ceiling(self):
        con = oc.confirm(TENANT, oc.observe(TENANT, self.expect(),
                                            oc.RESOLVED, oc.REPORTED))
        self.assertEqual(oc.evaluate(con, YARDSTICK)["confidence_cap"], 0.50)

    def test_a_yardstick_must_be_versioned(self):
        with self.assertRaises(oc.OutcomeError):
            oc.yardstick("x", "", {oc.RESOLVED: oc.SUCCESS})

    def test_a_yardstick_maps_observed_states_only(self):
        with self.assertRaises(oc.OutcomeError):
            oc.yardstick("x", "1", {"SUCCESS": oc.SUCCESS})


# ── 16-18 · isolation, PII, claim boundary ─────────────────────────────────

class Boundaries(Base):

    def test_tenant_isolation(self):
        self.expect()
        self.assertEqual(oc.history(OTHER_TENANT, DECISION), [])

    def test_no_cross_tenant_existence_disclosure(self):
        self.expect()
        view = oc.current(OTHER_TENANT, DECISION, now=self.clock)
        self.assertEqual(view, {})
        self.assertNotIn(SUBJECT, repr(view))

    def test_never_writes_to_the_claims_table(self):
        """Step 2 — outcomes must never become knowledge."""
        oc.confirm(TENANT, oc.observe(TENANT, self.expect(), oc.RESOLVED,
                                      oc.OBSERVED))
        code = code_only(MODULE)
        for banned in ("bic_claims", "assert_claim", "predicate_ns"):
            self.assertNotIn(banned, code)
        # The only tables this module can name are its own.
        self.assertEqual({oc.TABLE, oc.RETRACTIONS_TABLE},
                         {"bic_outcome_records", "bic_outcome_retractions"})
        for row in self.db.records:
            self.assertNotIn("predicate_ns", row)

    def test_no_pii_in_a_record(self):
        rec = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED,
                         observed_by="crm:invoice_settled")
        blob = repr(rec)
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob))
        self.assertNotIn("wamid", blob)

    def test_module_carries_no_pii_fields(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "message_body", "source_ref"):
            self.assertNotIn(banned, code)

    def test_no_ai_and_no_provider(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "deepseek", "llm", "completion",
                       "embed", "reinforce", "fine_tune"):
            self.assertNotIn(banned, code)
        # No lesson GENERATION here — 2I establishes reliable evidence first
        # (Step 16). `learning_readiness` is a GATE, not a generator: it
        # decides what may feed learning and deliberately does no learning,
        # so a blanket ban on names beginning "learn" would forbid the very
        # function §7.1 requires.
        names = {n.name for n in ast.walk(ast.parse(
            pathlib.Path(MODULE).read_text())) if isinstance(n, ast.FunctionDef)}
        for generator in ("generate_lesson", "propose_lesson", "adapt_policy",
                          "train", "fit", "update_weights", "reinforce"):
            self.assertNotIn(generator, names)
        self.assertIn("learning_readiness", names)   # the gate must exist

    def test_no_vertical_vocabulary(self):
        """Step 12 — no real_estate_outcome.py, and no vertical words here."""
        code = code_only(MODULE).lower()
        for word in ("transformer", "kva", "realestate", "voltage",
                     "brochure"):
            self.assertNotIn(word, code)


# ── 19-21 · real business-event fixtures, ordering, multiple outcomes ──────

class RealBusinessEvents(Base):
    """Fixtures shaped like events the system ALREADY observes today.

    Deliberately excluded: quotation accepted/declined and lead conversion.
    No authoritative source for those exists, and inventing one would be the
    fabricated conversion data Step 11 forbids.
    """

    def test_customer_replied_after_an_outbound_action(self):
        exp = self.expect(kind="customer_reply", window=86400,
                          goal_ref="social_media_enquiry", risk_tier=1,
                          sufficiency_verdict="PROCEED")
        obs = oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED,
                         observed_at=self.clock + timedelta(minutes=7),
                         observed_by="whatsapp:inbound_message")
        self.assertEqual(obs["observed_state"], oc.RESOLVED)
        self.assertEqual(obs["elapsed_seconds"], 420)

    def test_customer_never_replied(self):
        """The most common outcome in a small business (§2.2)."""
        exp = self.expect(kind="customer_reply", window=86400)
        obs = oc.time_out(TENANT, exp, at=self.clock + timedelta(days=1, hours=1))
        self.assertEqual(obs["observed_state"], oc.NO_RESPONSE)
        self.assertEqual(obs["observation_status"], oc.TIMED_OUT)

    def test_owner_took_over_the_conversation(self):
        """chat_pause is a real, recorded OWNER act on a customer."""
        exp = self.expect(kind="owner_engagement", window=86400)
        obs = oc.observe(TENANT, exp, oc.SUPERSEDED, oc.OBSERVED,
                         observed_by="tool:chat_pause")
        self.assertEqual(obs["observed_state"], oc.SUPERSEDED)

    def test_multiple_outcome_kinds_for_one_decision(self):
        self.expect(kind="customer_reply")
        self.expect(kind="owner_engagement")
        view = oc.current(TENANT, DECISION, now=self.clock)
        self.assertEqual(sorted(view), ["customer_reply", "owner_engagement"])

    def test_chain_ordering_is_stable_for_replay(self):
        exp = self.expect()
        obs = oc.observe(TENANT, exp, oc.NO_RESPONSE, oc.TIMED_OUT)
        rev = oc.revise(TENANT, obs, oc.RESOLVED, oc.OBSERVED,
                        observed_at=self.clock + timedelta(days=30))
        ids = [r["outcome_id"] for r in oc.history(TENANT, DECISION)]
        self.assertEqual(ids, [exp["outcome_id"], obs["outcome_id"],
                               rev["outcome_id"]])

    def test_current_reports_the_chain_and_what_it_superseded(self):
        exp = self.expect()
        obs = oc.observe(TENANT, exp, oc.NO_RESPONSE, oc.TIMED_OUT)
        oc.revise(TENANT, obs, oc.RESOLVED, oc.OBSERVED)
        view = oc.current(TENANT, DECISION, now=self.clock)["customer_reply"]
        self.assertEqual(view["chain_length"], 3)
        self.assertIn(obs["outcome_id"], view["superseded_ids"])

    def test_retracted_outcome_is_derived_not_hidden(self):
        obs = oc.observe(TENANT, self.expect(), oc.RESOLVED, oc.OBSERVED)
        oc.retract(TENANT, obs["outcome_id"], "misattributed", "raviraj")
        view = oc.current(TENANT, DECISION, now=self.clock)["customer_reply"]
        self.assertEqual(view["lifecycle"], oc.RETRACTED)


# ── 22-23 · trace safety and idempotency ───────────────────────────────────

class TraceAndIdempotency(Base):

    def test_trace_references_are_opaque(self):
        rec = self.expect(evidence_refs=["claim-aaaa", "claim-bbbb"])
        for ref in rec["evidence_refs"]:
            self.assertNotIn("@", ref)
            self.assertIsNone(re.search(r"\b91\d{10}\b", ref))

    def test_each_record_gets_a_fresh_id(self):
        exp = self.expect()
        obs = oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED)
        con = oc.confirm(TENANT, obs)
        self.assertEqual(len({exp["outcome_id"], obs["outcome_id"],
                              con["outcome_id"]}), 3)

    def test_repeated_expectations_do_not_collapse(self):
        """Two windows for the same decision+kind are two real windows; the
        IDD does not make expect() idempotent, and silently merging them
        would lose one."""
        a = self.expect(kind="customer_reply")
        b = self.expect(kind="customer_reply")
        self.assertNotEqual(a["outcome_id"], b["outcome_id"])

    def test_a_store_failure_surfaces(self):
        with mock.patch.object(oc, "insert", side_effect=DbError("down")):
            with self.assertRaises(DbError):
                self.expect()


# ── Migration ──────────────────────────────────────────────────────────────

class Migration(unittest.TestCase):

    def setUp(self):
        with open(MIG) as fh:
            self.raw = fh.read()
        out, i, ins = [], 0, False
        while i < len(self.raw):
            c = self.raw[i]
            if ins:
                if c == "'":
                    if i + 1 < len(self.raw) and self.raw[i + 1] == "'":
                        i += 2
                        continue
                    ins = False
                i += 1
                continue
            if c == "'":
                ins = True
                i += 1
                continue
            if self.raw[i:i + 2] == "--":
                while i < len(self.raw) and self.raw[i] != "\n":
                    i += 1
                continue
            out.append(c)
            i += 1
        self.code = "".join(out)

    def test_creates_only_outcome_tables(self):
        self.assertEqual(re.findall(r"create table if not exists (\w+)",
                                    self.code),
                         ["bic_outcome_records", "bic_outcome_retractions"])

    def test_never_touches_claims_or_party(self):
        for table in ("bic_claims", "bic_parties", "bic_party_identifiers",
                      "bic_decision_records", "bic_webhook_events",
                      "bic_tool_defs"):
            self.assertNotIn(table, self.code)

    def test_no_success_or_verdict_column(self):
        """I1, enforced by the schema rather than by discipline."""
        self.assertIsNone(re.search(
            r"\b(success|verdict|score|is_good|rating)\b\s+"
            r"(text|boolean|numeric|integer)", self.code, re.I))

    def test_append_only_triggers_on_both_tables(self):
        self.assertEqual(len(re.findall(r"create trigger", self.code)), 2)
        self.assertEqual(self.code.count("bic_reject_mutation()"), 2)

    def test_no_destructive_sql(self):
        self.assertIsNone(re.search(r"(?im)^\s*(delete|truncate)\b", self.code))

    def test_six_states_and_five_statuses_in_the_check_constraints(self):
        for state in oc.OBSERVED_STATES:
            self.assertIn(f"'{state}'", self.raw)
        for status in oc.OBSERVATION_STATUSES:
            self.assertIn(f"'{status}'", self.raw)

    def test_rls_enabled(self):
        self.assertEqual(len(re.findall(r"enable row level security",
                                        self.code)), 2)

    def test_no_shortcut_edge_columns(self):
        for shortcut in ("customer_id", "project_id", "party_id", "invoice_id"):
            self.assertNotIn(shortcut, self.code)

    def test_no_phone_literal(self):
        self.assertIsNone(re.search(r"\b\d{10,15}\b", self.raw))


if __name__ == "__main__":
    unittest.main(verbosity=2)
