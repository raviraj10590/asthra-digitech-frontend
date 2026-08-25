"""Goal lifecycle — an admitted intention that knows when it is finished.

The tests that matter most are the ones proving a goal CANNOT be completed by
assertion: not by a model, not by a customer saying "done", and not by the
mere fact that some message was sent. Completion is derived from the declared
condition being satisfied, or it does not happen.

Offline: no network, no AI, no database.
"""

import ast
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import goal_lifecycle as gl                            # noqa: E402
from bic import goals                                            # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
SUBJECT = "805d1c4e-0000-4000-8000-000000000001"
DECISION = "dec-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic",
                      "goal_lifecycle.py")
SOCIAL = "social_media_enquiry"


def code_only(path) -> str:
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


def admitted(**kw):
    return gl.admit(goals.lookup(SOCIAL), tenant_id=kw.pop("tenant_id", TENANT),
                    subject=kw.pop("subject", SUBJECT),
                    decision_ref=kw.pop("decision_ref", DECISION), **kw)


DELIVERED = {"response_delivered": True}


# ── 1 · definition vs instance ──────────────────────────────────────────

class DefinitionVsInstance(unittest.TestCase):

    def test_definition_is_reusable_data_and_carries_no_subject(self):
        d = goals.lookup(SOCIAL)
        for per_turn in ("subject", "tenant_id", "lifecycle", "admitted_at",
                         "decision_ref", "owner"):
            self.assertNotIn(per_turn, d)

    def test_instance_carries_the_per_turn_state(self):
        i = admitted()
        for field in ("goal_id", "subject", "tenant_id", "lifecycle",
                      "completion", "owner", "admitted_at", "decision_ref"):
            self.assertIn(field, i)

    def test_instance_does_not_copy_goal_definition_data(self):
        """Goal data lives in bic/goals.py and is not duplicated per turn."""
        i = admitted()
        self.assertNotIn("required_slots", i)
        self.assertNotIn("risk_tier", i)

    def test_goal_data_is_declared_in_the_registry_not_the_mechanism(self):
        code = code_only(MODULE)
        self.assertNotIn(SOCIAL, code)


# ── 2-4 · admission ─────────────────────────────────────────────────────

class Admission(unittest.TestCase):

    def test_admission_creates_an_admitted_instance(self):
        self.assertEqual(admitted()["lifecycle"], gl.ADMITTED)

    def test_a_goal_without_a_completion_condition_is_not_admissible(self):
        """§1.4 — 'A goal with no defined completion condition may not be
        admitted.' Without it the goal never ends."""
        with self.assertRaises(gl.GoalError):
            gl.admit({"goal_id": "x"}, tenant_id=TENANT, subject=SUBJECT)

    def test_the_inactive_goals_remain_inadmissible(self):
        """transformer/real-estate declare no completion condition, so the
        admission gate is a second lock on them."""
        for gid in ("transformer_quotation", "real_estate_enquiry"):
            with self.subTest(gid=gid):
                with self.assertRaises(gl.GoalError):
                    gl.admit(goals.lookup(gid), tenant_id=TENANT,
                             subject=SUBJECT)

    def test_subject_and_tenant_are_required(self):
        for kw in ({"subject": ""}, {"tenant_id": ""}):
            with self.subTest(kw=kw):
                with self.assertRaises(gl.GoalError):
                    admitted(**kw)

    def test_tenant_and_subject_are_carried_consistently(self):
        i = admitted()
        self.assertEqual(i["tenant_id"], TENANT)
        self.assertEqual(i["subject"], SUBJECT)
        self.assertNotEqual(i["tenant_id"], OTHER_TENANT)

    def test_owner_is_never_null(self):
        """§1.5 — 'never null, even when the work is autonomous.'"""
        self.assertTrue(admitted()["owner"])

    def test_social_enquiry_is_ephemeral(self):
        """§1.2 — 'answer a question' is one turn, working memory. That is
        why this slice needs no table and no migration."""
        self.assertEqual(admitted()["goal_type"], gl.EPHEMERAL)


# ── 5-11 · lifecycle states and completion ──────────────────────────────

class Lifecycle(unittest.TestCase):

    def test_states_are_the_idd_names(self):
        """§1.3 uses ADMITTED/ACTIVE/BLOCKED — not OPEN, and not REFUSED."""
        for s in ("PROPOSED", "ADMITTED", "REJECTED", "PLANNED", "ACTIVE",
                  "BLOCKED", "COMPLETED", "ABANDONED", "EXPIRED",
                  "SUPERSEDED"):
            self.assertIn(s, gl.STATES)
        self.assertNotIn("OPEN", gl.STATES)
        self.assertNotIn("REFUSED", gl.STATES)

    def test_admitted_to_active(self):
        self.assertEqual(gl.activate(admitted())["lifecycle"], gl.ACTIVE)

    def test_blocked_carries_a_bounded_reason(self):
        b = gl.block(admitted(), gl.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertEqual(b["lifecycle"], gl.BLOCKED)
        self.assertIn(b["blocker"], gl.BLOCKERS)

    def test_unknown_blocker_is_refused(self):
        with self.assertRaises(gl.GoalError):
            gl.block(admitted(), "because the customer seemed unsure")

    def test_completion_path_active_then_delivered(self):
        done = gl.complete(gl.activate(admitted()), DELIVERED)
        self.assertEqual(done["lifecycle"], gl.COMPLETED)

    def test_completion_condition_not_satisfied_leaves_it_alone(self):
        active = gl.activate(admitted())
        with self.assertRaises(gl.GoalError):
            gl.complete(active, {"response_delivered": False})
        self.assertEqual(active["lifecycle"], gl.ACTIVE)

    def test_a_blocked_goal_cannot_be_completed_by_sending_something(self):
        """AUDIT REGRESSION. Completion first checked only 'was a message
        sent', so a CLARIFY or REFUSE reply completed a BLOCKED goal while
        it still carried its blocker."""
        blocked = gl.block(admitted(), gl.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertFalse(gl.is_complete(blocked, DELIVERED))
        with self.assertRaises(gl.GoalError):
            gl.complete(blocked, DELIVERED)

    def test_an_admitted_but_undecided_goal_cannot_complete(self):
        self.assertFalse(gl.is_complete(admitted(), DELIVERED))


# ── 12 · PROCEED is not COMPLETED ───────────────────────────────────────

class ProceedIsNotCompletion(unittest.TestCase):

    def test_active_means_permitted_to_act_not_finished(self):
        a = gl.activate(admitted())
        self.assertEqual(a["lifecycle"], gl.ACTIVE)
        self.assertNotEqual(a["lifecycle"], gl.COMPLETED)
        self.assertFalse(gl.is_complete(a, {}))


# ── 13-14 · nobody may assert completion ────────────────────────────────

class CompletionCannotBeAsserted(unittest.TestCase):

    def test_a_model_claiming_completion_changes_nothing(self):
        active = gl.activate(admitted())
        for claim in ({"llm_says_done": True}, {"completed": True},
                      {"verdict": "COMPLETED"}, {"customer_said": "done"}):
            with self.subTest(claim=claim):
                self.assertFalse(gl.is_complete(active, claim))
                with self.assertRaises(gl.GoalError):
                    gl.complete(active, claim)

    def test_a_customer_saying_done_does_not_complete_a_blocked_goal(self):
        blocked = gl.block(admitted(), gl.BLOCKED_INSUFFICIENT_EVIDENCE)
        with self.assertRaises(gl.GoalError):
            gl.complete(blocked, {"response_delivered": True,
                                  "customer_said": "done"})

    def test_missing_evidence_keeps_it_blocked(self):
        blocked = gl.block(admitted(), gl.BLOCKED_INSUFFICIENT_EVIDENCE)
        self.assertEqual(blocked["lifecycle"], gl.BLOCKED)
        self.assertEqual(blocked["blocker"], gl.BLOCKED_INSUFFICIENT_EVIDENCE)


# ── 10 · reopening is not defined by the IDD ────────────────────────────

class NoReopening(unittest.TestCase):

    def test_terminal_states_have_no_arrow_back(self):
        """§1.3's diagram has no transition out of a terminal state, so
        reopening is not invented here."""
        done = gl.complete(gl.activate(admitted()), DELIVERED)
        for fn in (gl.activate, lambda i: gl.block(i, gl.BLOCKERS[0])):
            with self.subTest(fn=fn):
                with self.assertRaises(gl.GoalError):
                    fn(done)

    def test_history_stays_traceable(self):
        done = gl.complete(gl.activate(admitted()), DELIVERED)
        self.assertEqual([h["state"] for h in done["history"]],
                         [gl.ADMITTED, gl.ACTIVE, gl.COMPLETED])

    def test_transitions_do_not_mutate_the_prior_instance(self):
        a = admitted()
        gl.activate(a)
        self.assertEqual(a["lifecycle"], gl.ADMITTED)


# ── 24 · determinism ────────────────────────────────────────────────────

class Determinism(unittest.TestCase):

    def test_same_inputs_give_the_same_lifecycle(self):
        results = [gl.complete(gl.activate(admitted()), DELIVERED)["lifecycle"]
                   for _ in range(5)]
        self.assertEqual(results, [gl.COMPLETED] * 5)

    def test_is_complete_is_a_pure_function(self):
        a = gl.activate(admitted())
        self.assertEqual([gl.is_complete(a, DELIVERED) for _ in range(5)],
                         [True] * 5)


# ── 18, 23 · boundaries ─────────────────────────────────────────────────

class Boundaries(unittest.TestCase):

    def test_no_pii_in_an_instance(self):
        blob = repr(admitted())
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob))
        self.assertNotIn("wamid", blob)

    def test_describe_carries_no_subject_or_tenant(self):
        d = gl.describe(admitted())
        self.assertNotIn("subject", d)
        self.assertNotIn("tenant_id", d)

    def test_no_pii_vocabulary_in_the_module(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "message_body"):
            self.assertNotIn(banned, code)

    def test_no_model_storage_or_network(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "llm", "requests", "http",
                       "insert(", "select("):
            self.assertNotIn(banned, code)

    def test_lifecycle_never_writes_an_outcome_record(self):
        """§7 — a goal state change is not an Outcome. 2I observes what the
        WORLD did, asynchronously; this observes what WE did, in-turn."""
        code = code_only(MODULE)
        for banned in ("outcomes", "bic_outcome_records", "expect_customer_reply"):
            self.assertNotIn(banned, code)

    def test_lifecycle_creates_no_second_authorization_path(self):
        code = code_only(MODULE).lower()
        for banned in ("may_invoke", "principal", "policy", "role"):
            self.assertNotIn(banned, code)

    def test_completion_conditions_are_a_closed_set(self):
        self.assertEqual(gl.COMPLETION_CONDITIONS, (gl.RESPONSE_DELIVERED,))
