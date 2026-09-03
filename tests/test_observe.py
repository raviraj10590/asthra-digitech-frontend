"""Stage ⑫ OBSERVE — what actually happened when we executed.

The sharpest tests are the ones proving an execution observation can never be
read as a business result, and that "we could not tell" never counts as
success. The Brain previously handed its goal a hardcoded delivery, so a
WhatsApp rejection still reported the enquiry answered.

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

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import decision                                        # noqa: E402
from bic import goal_lifecycle as gl                            # noqa: E402
from bic import goals                                           # noqa: E402
from bic import observe as ob                                   # noqa: E402

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "observe.py")


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


# ── execution success / failure ─────────────────────────────────────────

class ExecutionResult(unittest.TestCase):

    def test_channel_answer_is_recorded_as_delivery_certainty(self):
        """A status code proves the channel processed the request; an
        exception or an unreadable result proves nothing either way."""
        self.assertTrue(ob.execution(Resp(True, 200))["channel_responded"])
        self.assertTrue(ob.execution(Resp(False, 429))["channel_responded"])
        self.assertFalse(ob.execution(TimeoutError("x"))["channel_responded"])
        self.assertFalse(ob.execution(None)["channel_responded"])

    def test_success(self):
        o = ob.execution(Resp(True, 200))
        self.assertEqual(o["state"], ob.SUCCEEDED)
        self.assertTrue(o["delivered"])
        self.assertTrue(o["attempted"])
        self.assertFalse(o["degraded"])
        self.assertIsNone(o["failure_class"])

    def test_channel_rejection_is_a_failure_not_a_success(self):
        o = ob.execution(Resp(False, 400))
        self.assertEqual(o["state"], ob.FAILED)
        self.assertFalse(o["delivered"])

    def test_failure_classes_are_the_existing_bounded_vocabulary(self):
        for status in (400, 401, 403, 408, 429, 500, 504):
            with self.subTest(status=status):
                o = ob.execution(Resp(False, status))
                self.assertIn(o["failure_class"], decision.FAILURE_CLASSES)

    def test_permission_timeout_and_connection_are_distinguished(self):
        self.assertEqual(ob.execution(Resp(False, 401))["failure_class"],
                         "PERMISSION")
        self.assertEqual(ob.execution(Resp(False, 408))["failure_class"],
                         "TIMEOUT")
        self.assertEqual(ob.execution(Resp(False, 429))["failure_class"],
                         "CONNECTION")

    def test_an_exception_is_an_observation_not_a_crash(self):
        o = ob.execution(TimeoutError("upstream timed out"))
        self.assertEqual(o["state"], ob.FAILED)
        self.assertEqual(o["failure_class"], "TIMEOUT")
        self.assertFalse(o["delivered"])

    def test_provider_connection_failure_is_classified(self):
        self.assertEqual(ob.execution(ConnectionError("x"))["failure_class"],
                         "CONNECTION")

    def test_unreadable_result_is_degraded_and_never_delivered(self):
        """§1.2 — 'record raw; mark degraded'. Not knowing is not success."""
        o = ob.execution(None)
        self.assertEqual(o["state"], ob.UNKNOWN)
        self.assertTrue(o["degraded"])
        self.assertFalse(o["delivered"])

    def test_not_attempted_is_distinct_from_a_failed_attempt(self):
        o = ob.not_attempted()
        self.assertFalse(o["attempted"])
        self.assertFalse(o["delivered"])
        self.assertFalse(o["degraded"])

    def test_unknown_action_is_refused(self):
        with self.assertRaises(ob.ObserveError):
            ob.execution(Resp(True, 200), action="SEND_INVOICE")


# ── timestamps and traceability ─────────────────────────────────────────

class Traceability(unittest.TestCase):

    def test_observation_is_timestamped(self):
        self.assertTrue(ob.execution(Resp(True, 200))["observed_at"])

    def test_timestamp_is_deterministic_when_supplied(self):
        from datetime import datetime, timezone
        at = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
        a = ob.execution(Resp(True, 200), at=at)
        b = ob.execution(Resp(True, 200), at=at)
        self.assertEqual(a["observed_at"], b["observed_at"])

    def test_action_vocabulary_is_closed(self):
        self.assertEqual(ob.ACTIONS, (ob.RESPONSE_DELIVERY,))

    def test_describe_is_bounded(self):
        d = ob.describe(ob.execution(Resp(False, 400)))
        self.assertEqual(set(d), {"action", "state", "attempted",
                                  "channel_responded", "degraded",
                                  "failure_class"})


# ── the delivered() gate ────────────────────────────────────────────────

class DeliveredGate(unittest.TestCase):

    def test_only_succeeded_counts_as_delivered(self):
        self.assertTrue(ob.delivered(ob.execution(Resp(True, 200))))
        for result in (Resp(False, 400), None, TimeoutError("t")):
            with self.subTest(result=result):
                self.assertFalse(ob.delivered(ob.execution(result)))

    def test_a_missing_observation_is_never_delivered(self):
        self.assertFalse(ob.delivered(None))
        self.assertFalse(ob.delivered({}))

    def test_not_attempted_is_never_delivered(self):
        self.assertFalse(ob.delivered(ob.not_attempted()))


# ── goal lifecycle interaction ──────────────────────────────────────────

class GoalInteraction(unittest.TestCase):

    def _active(self):
        return gl.activate(gl.admit(goals.lookup("social_media_enquiry"),
                                    tenant_id="t", subject="s"))

    def test_a_delivered_execution_completes_an_active_goal(self):
        o = ob.execution(Resp(True, 200))
        done = gl.complete(self._active(), {"response_delivered": ob.delivered(o)})
        self.assertEqual(done["lifecycle"], gl.COMPLETED)

    def test_a_failed_execution_does_not_complete_the_goal(self):
        """AUDIT REGRESSION. A hardcoded delivery meant a rejected send still
        reported the enquiry answered and the goal COMPLETED."""
        active = self._active()
        o = ob.execution(Resp(False, 400))
        with self.assertRaises(gl.GoalError):
            gl.complete(active, {"response_delivered": ob.delivered(o)})
        self.assertEqual(active["lifecycle"], gl.ACTIVE)

    def test_a_degraded_execution_does_not_complete_the_goal(self):
        active = self._active()
        with self.assertRaises(gl.GoalError):
            gl.complete(active, {"response_delivered":
                                 ob.delivered(ob.execution(None))})


# ── 2I boundary ─────────────────────────────────────────────────────────

class OutcomeBoundary(unittest.TestCase):

    def test_execution_observation_is_never_a_business_outcome(self):
        """IDD-2I I2 — 'Quotation sent, HTTP 200' is an execution result."""
        o = ob.execution(Resp(True, 200))
        for banned in ("SUCCESS", "RESOLVED", "verdict", "outcome_kind",
                       "business_success"):
            self.assertNotIn(banned, o)

    def test_module_writes_no_outcome_and_no_claim(self):
        code = code_only(MODULE)
        for banned in ("outcomes", "bic_outcome_records", "bic_claims",
                       "assert_claim", "expect_customer_reply", "insert("):
            self.assertNotIn(banned, code)

    def test_module_reuses_the_existing_failure_vocabulary(self):
        """A second taxonomy for the same idea would drift."""
        for status in (400, 401, 429, 500):
            self.assertIn(ob.execution(Resp(False, status))["failure_class"],
                          decision.FAILURE_CLASSES)


# ── idempotency ─────────────────────────────────────────────────────────

class Idempotency(unittest.TestCase):

    def test_observation_is_pure_and_repeatable(self):
        r = Resp(False, 400)
        from datetime import datetime, timezone
        at = datetime(2026, 8, 25, tzinfo=timezone.utc)
        self.assertEqual([ob.execution(r, at=at) for _ in range(5)],
                         [ob.execution(r, at=at)] * 5)

    def test_observing_creates_no_stored_state(self):
        """Nothing accumulates, so a duplicate delivery cannot duplicate an
        observation — there is no store to duplicate into."""
        code = code_only(MODULE)
        for banned in ("global ", "_cache", "append(", "insert("):
            self.assertNotIn(banned, code)


# ── security ────────────────────────────────────────────────────────────

class Boundaries(unittest.TestCase):

    def test_no_model_storage_or_network(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "llm", "requests", "http", "urllib",
                       "select("):
            self.assertNotIn(banned, code)

    def test_no_pii_vocabulary(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "message_body",
                       "sender", "tenant"):
            self.assertNotIn(banned, code)

    def test_a_failure_never_carries_the_exception_text(self):
        """An exception body can echo an identifier or a response payload."""
        blob = repr(ob.execution(
            ValueError("failed for 919999000444 with token sk-abc123")))
        self.assertNotIn("919999000444", blob)
        self.assertNotIn("sk-abc123", blob)
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))

    def test_a_response_body_never_reaches_the_observation(self):
        r = Resp(False, 400)
        r.text = '{"error":"bad number 919999000444"}'
        self.assertNotIn("919999000444", repr(ob.execution(r)))
