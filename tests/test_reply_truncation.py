"""Replies must not be cut off mid-sentence, and truncation must never be silent.

THE DEFECT
----------
Measured in production across 104 customer-facing replies: 18 (17%) ended
mid-word. One real example, in full:

    ಸರಿಯಾಯಿತು ರಾಜಶೇಖರ್ ಅವರೇ. ನಿಮ್ಮ ಲೇ

Two causes, both here:

1. A 400-token ceiling. Kannada script costs several tokens per character, so
   400 tokens is roughly 150-250 Kannada characters — and the median healthy
   reply is ~160. Replies were not ending, they were hitting the ceiling.
   DeepSeek already had 1200 and was unaffected; the damage only surfaced when
   DeepSeek stopped answering on 2026-09-03 and everything fell through to
   OpenAI (429ing) and then Gemini.

2. Silence. OpenAI and DeepSeek both check finish_reason and log a warning.
   The Gemini path ignored it and returned the partial text as if complete, so
   the fallback provider shipped half-sentences with nothing in the logs.

Offline: no network, no provider.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402


class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = str(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._p


def gemini(payload, status=200, max_tokens=None):
    """Drive the REAL generate_reply_gemini. Returns (text, stdout)."""
    buf = io.StringIO()
    with mock.patch.object(w, "GEMINI_API_KEY", "test-key"), \
         mock.patch.object(w.requests, "post",
                           lambda *a, **k: FakeResp(payload, status)), \
         redirect_stdout(buf):
        out = w.generate_reply_gemini([{"role": "user", "content": "hi"}],
                                      max_tokens)
    return out, buf.getvalue()


def candidate(text="ಸರಿ", finish="STOP"):
    return {"candidates": [{"finishReason": finish,
                            "content": {"parts": [{"text": text}]}}]}


# ══════════════════════════════════════════════════════════════════════════
# 1 · the token ceiling that caused the cut-offs
# ══════════════════════════════════════════════════════════════════════════

class TokenBudget(unittest.TestCase):

    def test_the_budgets_are_large_enough_for_kannada(self):
        """400 cut one reply in six off mid-word in production."""
        self.assertGreaterEqual(w.GEMINI_MAX_TOKENS, 900)
        self.assertGreaterEqual(w.OPENAI_MAX_TOKENS, 900)

    def test_gemini_is_not_starved_relative_to_deepseek(self):
        """The whole defect was the fallback having a smaller ceiling than the
        primary, so a provider outage silently degraded reply quality."""
        self.assertGreaterEqual(w.GEMINI_MAX_TOKENS,
                                w.DEEPSEEK_MAX_TOKENS * 0.7)

    def test_the_budgets_are_still_env_overridable(self):
        import inspect
        src = inspect.getsource(w)
        self.assertIn('os.environ.get("GEMINI_MAX_TOKENS"', src)
        self.assertIn('os.environ.get("OPENAI_MAX_TOKENS"', src)

    def test_an_explicit_budget_still_wins(self):
        """extract_lead_info passes 380 deliberately; the default must not
        override a caller that asked for a specific size."""
        seen = {}

        def fake_post(url, json=None, timeout=None):
            seen["max"] = json["generationConfig"]["maxOutputTokens"]
            return FakeResp(candidate())
        with mock.patch.object(w, "GEMINI_API_KEY", "k"), \
             mock.patch.object(w.requests, "post", fake_post), \
             redirect_stdout(io.StringIO()):
            w.generate_reply_gemini([{"role": "user", "content": "x"}], 380)
        self.assertEqual(seen["max"], 380)

    def test_the_default_is_used_when_no_budget_is_passed(self):
        seen = {}

        def fake_post(url, json=None, timeout=None):
            seen["max"] = json["generationConfig"]["maxOutputTokens"]
            return FakeResp(candidate())
        with mock.patch.object(w, "GEMINI_API_KEY", "k"), \
             mock.patch.object(w.requests, "post", fake_post), \
             redirect_stdout(io.StringIO()):
            w.generate_reply_gemini([{"role": "user", "content": "x"}])
        self.assertEqual(seen["max"], w.GEMINI_MAX_TOKENS)


# ══════════════════════════════════════════════════════════════════════════
# 2 · truncation is no longer silent
# ══════════════════════════════════════════════════════════════════════════

class GeminiTruncationIsReported(unittest.TestCase):

    def test_a_truncated_reply_logs_a_warning(self):
        out, log = gemini(candidate("ಸರಿಯಾಯಿತು ರಾಜಶೇಖರ್ ಅವರೇ. ನಿಮ್ಮ ಲೇ",
                                    finish="MAX_TOKENS"))
        self.assertIn("gemini TRUNCATED", log)
        self.assertIn("max_tokens=", log)

    def test_the_warning_matches_the_other_providers(self):
        """Same signal, same wording, so one grep finds all three."""
        import inspect
        for fn in (w._call_openai, w._call_deepseek, w.generate_reply_gemini):
            self.assertIn("TRUNCATED", inspect.getsource(fn), fn.__name__)

    def test_a_complete_reply_logs_nothing(self):
        out, log = gemini(candidate("ಸರಿ, ಖಂಡಿತ ಮಾಡುತ್ತೇವೆ.", finish="STOP"))
        self.assertNotIn("TRUNCATED", log)
        self.assertEqual(out, "ಸರಿ, ಖಂಡಿತ ಮಾಡುತ್ತೇವೆ.")

    def test_the_partial_text_is_still_returned(self):
        """Half an answer beats the apology text — but it is now logged."""
        out, _ = gemini(candidate("ನಿಮ್ಮ ಲೇ", finish="MAX_TOKENS"))
        self.assertEqual(out, "ನಿಮ್ಮ ಲೇ")

    def test_the_reported_budget_is_the_one_actually_used(self):
        _, log = gemini(candidate("x", finish="MAX_TOKENS"), max_tokens=380)
        self.assertIn("max_tokens=380", log)


# ══════════════════════════════════════════════════════════════════════════
# 3 · the malformed-response crash this also removes
# ══════════════════════════════════════════════════════════════════════════

class MalformedResponsesDoNotCrash(unittest.TestCase):

    def test_max_tokens_with_no_parts_returns_empty_not_an_exception(self):
        """Gemini can finish on MAX_TOKENS with no `parts` at all. The old
        chained subscript raised KeyError, which the caller then reported as a
        content failure rather than a provider one."""
        out, log = gemini({"candidates": [{"finishReason": "MAX_TOKENS",
                                           "content": {}}]})
        self.assertEqual(out, "")
        self.assertIn("TRUNCATED", log)
        self.assertIn("no text", log)

    def test_no_candidates_returns_empty(self):
        out, _ = gemini({"candidates": []})
        self.assertEqual(out, "")

    def test_missing_candidates_key_returns_empty(self):
        out, _ = gemini({})
        self.assertEqual(out, "")

    def test_a_safety_block_returns_empty_and_says_why(self):
        out, log = gemini({"candidates": [{"finishReason": "SAFETY",
                                           "content": {"parts": []}}]})
        self.assertEqual(out, "")
        self.assertIn("SAFETY", log)

    def test_multi_part_replies_are_joined(self):
        out, _ = gemini({"candidates": [{"finishReason": "STOP", "content":
                        {"parts": [{"text": "ಒಂದು "}, {"text": "ಎರಡು"}]}}]})
        self.assertEqual(out, "ಒಂದು ಎರಡು")

    def test_an_http_error_still_returns_empty(self):
        out, log = gemini({"error": "quota"}, status=429)
        self.assertEqual(out, "")
        self.assertIn("gemini fallback 429", log)

    def test_a_missing_api_key_still_short_circuits(self):
        buf = io.StringIO()
        with mock.patch.object(w, "GEMINI_API_KEY", ""), redirect_stdout(buf):
            self.assertEqual(w.generate_reply_gemini([{"role": "user",
                                                       "content": "x"}]), "")
        self.assertIn("GEMINI_API_KEY not set", buf.getvalue())


# ══════════════════════════════════════════════════════════════════════════
# 4 · nothing else about replying changed
# ══════════════════════════════════════════════════════════════════════════

class UnrelatedBehaviourUnchanged(unittest.TestCase):

    def test_no_secret_reaches_the_logs(self):
        with mock.patch.object(w, "GEMINI_API_KEY", "SECRET-KEY-SENTINEL"):
            _, log = gemini(candidate("x", finish="MAX_TOKENS"))
        self.assertNotIn("SECRET-KEY-SENTINEL", log)

    def test_the_system_prompt_is_untouched(self):
        self.assertIn("Robot ಭಾಷೆ ಬೇಡ", w.SYSTEM_PROMPT)
        self.assertIn("3-5 ಸಾಲು max", w.SYSTEM_PROMPT)

    def test_the_provider_chain_is_untouched(self):
        import inspect
        src = inspect.getsource(w._provider_chain)
        self.assertIn("AI_PROVIDER_ORDER", src)
        self.assertIn("AI_PROVIDER_PRIMARY", src)

    def test_extraction_still_asks_for_its_own_budget(self):
        import inspect
        self.assertIn("max_tokens=380", inspect.getsource(w.extract_lead_info))

    def test_the_extraction_guard_is_unchanged(self):
        import inspect
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      inspect.getsource(w.run_client_pipeline))

    def test_the_service_role_lead_write_is_unchanged(self):
        import inspect
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")',
                      inspect.getsource(w.upsert_lead))


if __name__ == "__main__":
    unittest.main(verbosity=2)
