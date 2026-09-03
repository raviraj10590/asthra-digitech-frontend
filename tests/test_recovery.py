"""Stage ⑮ execution recovery — I13 made enforceable.

    I13 — "Non-idempotent actions are never auto-retried."
    Criterion 15 — "Non-idempotent write fails ambiguously →
                    ESCALATED, NEVER AUTO-RETRIED."

A WhatsApp send is not idempotent. The sharpest tests below are the ones
proving that an AMBIGUOUS failure escalates instead of retrying — §9.1 names
I13 as one of the four invariants that will come under pressure, and the
pressure is exactly "it probably didn't go through, just retry it".

Offline: no network, no AI, no database.
"""

import ast
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import decision                                        # noqa: E402
from bic import observe as ob                                   # noqa: E402
from bic import recovery as rec                                 # noqa: E402

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "recovery.py")


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


def obs(result):
    return ob.execution(result)


# ── the channel answered and refused: retry cannot duplicate ────────────

class ChannelRefused(unittest.TestCase):

    def test_rate_limit_is_safe_to_retry(self):
        r = rec.classify(obs(Resp(False, 429)))
        self.assertEqual(r["recovery"], rec.SAFE_TO_RETRY)
        self.assertTrue(r["may_retry"])

    def test_server_error_is_safe_to_retry(self):
        self.assertEqual(rec.classify(obs(Resp(False, 503)))["recovery"],
                         rec.SAFE_TO_RETRY)

    def test_malformed_request_is_terminal_not_retried(self):
        """A byte-identical retry fails identically."""
        r = rec.classify(obs(Resp(False, 400)))
        self.assertEqual(r["recovery"], rec.TERMINAL_FAILURE)
        self.assertFalse(r["may_retry"])

    def test_bad_credentials_are_terminal_not_retried(self):
        for status in (401, 403):
            with self.subTest(status=status):
                self.assertEqual(rec.classify(obs(Resp(False, status)))["recovery"],
                                 rec.TERMINAL_FAILURE)


# ── the channel never answered: ambiguous, so never retried ─────────────

class AmbiguousDelivery(unittest.TestCase):

    def test_timeout_escalates_and_is_never_auto_retried(self):
        """I13 / criterion 15. The request may have reached the channel and
        the reply been lost — retrying is the one move that double-sends."""
        r = rec.classify(obs(TimeoutError("gateway")))
        self.assertEqual(r["recovery"], rec.HUMAN_REVIEW)
        self.assertFalse(r["may_retry"])
        self.assertTrue(r["needs_human"])

    def test_connection_error_escalates_rather_than_retrying(self):
        """Note the contrast with HTTP 429: both classify as CONNECTION, but
        only the answered one proves no delivery."""
        r = rec.classify(obs(ConnectionError("reset")))
        self.assertEqual(r["recovery"], rec.HUMAN_REVIEW)
        self.assertFalse(r["may_retry"])

    def test_unreadable_result_escalates(self):
        self.assertEqual(rec.classify(obs(None))["recovery"], rec.HUMAN_REVIEW)

    def test_the_same_failure_class_splits_on_whether_the_channel_answered(self):
        answered = obs(Resp(False, 429))
        silent = obs(ConnectionError("x"))
        self.assertEqual(answered["failure_class"], silent["failure_class"])
        self.assertNotEqual(rec.classify(answered)["recovery"],
                            rec.classify(silent)["recovery"])


# ── success / nothing attempted ─────────────────────────────────────────

class NoRecoveryNeeded(unittest.TestCase):

    def test_delivered_needs_no_recovery(self):
        r = rec.classify(obs(Resp(True, 200)))
        self.assertEqual(r["recovery"], rec.NONE)
        self.assertFalse(r["needs_human"])

    def test_not_attempted_is_not_a_failure(self):
        r = rec.classify(ob.not_attempted())
        self.assertEqual(r["recovery"], rec.NOT_APPLICABLE)
        self.assertFalse(r["may_retry"])


# ── bounded attempts ────────────────────────────────────────────────────

class BoundedAttempts(unittest.TestCase):

    def test_max_attempts_is_small_and_declared(self):
        self.assertEqual(rec.MAX_ATTEMPTS, 2)

    def test_budget_exhaustion_escalates_rather_than_giving_up(self):
        """§6.2 T4 — 'acknowledge, queue, notify a human. Never silence.'"""
        r = rec.classify(obs(Resp(False, 429)), attempt=rec.MAX_ATTEMPTS)
        self.assertEqual(r["recovery"], rec.HUMAN_REVIEW)
        self.assertTrue(r["needs_human"])

    def test_retry_is_permitted_only_below_the_bound(self):
        self.assertTrue(rec.should_retry(obs(Resp(False, 429)), attempt=1))
        self.assertFalse(rec.should_retry(obs(Resp(False, 429)), attempt=2))
        self.assertFalse(rec.should_retry(obs(Resp(False, 429)), attempt=9))

    def test_invalid_attempt_is_refused(self):
        for bad in (0, -1, "1", None):
            with self.subTest(bad=bad):
                with self.assertRaises(rec.RecoveryError):
                    rec.classify(obs(Resp(False, 429)), attempt=bad)

    def test_a_missing_observation_is_refused_not_guessed(self):
        with self.assertRaises(rec.RecoveryError):
            rec.classify(None)


# ── determinism and boundaries ──────────────────────────────────────────

class Boundaries(unittest.TestCase):

    def test_classification_is_deterministic(self):
        o = obs(Resp(False, 429))
        self.assertEqual([rec.classify(o)["recovery"] for _ in range(5)],
                         [rec.SAFE_TO_RETRY] * 5)

    def test_decisions_are_a_closed_set(self):
        for result in (Resp(True, 200), Resp(False, 400), Resp(False, 429),
                       Resp(False, 401), TimeoutError("x"), None):
            with self.subTest(result=result):
                self.assertIn(rec.classify(obs(result))["recovery"],
                              rec.DECISIONS)

    def test_reuses_the_existing_failure_vocabulary(self):
        """Asserted on the RUNTIME constant, not the source: code_only()
        blanks string literals, so a literal assertion there can never fail
        honestly."""
        for cls in rec._RETRYABLE_WHEN_ANSWERED:
            self.assertIn(cls, decision.FAILURE_CLASSES)
        for status in (400, 401, 429):
            self.assertIn(obs(Resp(False, status))["failure_class"],
                          decision.FAILURE_CLASSES)

    def test_writes_nothing_anywhere(self):
        """Recovery decides; it does not store. No queue, no table, no claim."""
        code = code_only(MODULE)
        for banned in ("insert(", "select(", "db.", "bic_claims", "outcomes",
                       "redis", "celery"):
            self.assertNotIn(banned, code)

    def test_no_model_or_network(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "llm", "requests", "http", "sleep"):
            self.assertNotIn(banned, code)

    def test_no_pii_vocabulary(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "sender",
                       "message_body"):
            self.assertNotIn(banned, code)

    def test_describe_is_bounded(self):
        d = rec.describe(rec.classify(obs(Resp(False, 429))))
        self.assertEqual(set(d),
                         {"recovery", "attempt", "max_attempts", "needs_human"})
