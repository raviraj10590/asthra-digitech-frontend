"""Regression locks for the raw-JSON leak (deferred defect D3).

WHAT HAPPENED
-------------
Between 2026-07-29 and 2026-08-03, 58 assistant messages were sent to the owner
beginning with ```json. Every one of the 24 fenced samples inspected had NO
closing brace.

Root cause: the OWNER turn asks for one JSON object containing a reply AND a
memory note of up to 400 words across six sections. In Kannada — roughly one
token per one-to-two characters — that note alone is 1,500-2,500 tokens. The
budgets were openai 400 and deepseek 1200, so truncation was GUARANTEED.

Three symptoms, one bug:
  1. the JSON never closed, so _parse_json_block returned {}
  2. `reply = parsed.get("reply") or raw` then sent the raw fragment to a human
  3. `parsed.get("memory")` was None, so memory silently stopped advancing —
     which is what the owner had actually been complaining about

Offline: no network, no AI, no database.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                    # noqa: E402

OWNER = "918861369951"

# A verbatim shape from production (truncated mid-word, no closing brace).
TRUNCATED = '```json\n{\n  "reply": "OWNER, ನಿಮ್ಮ ಮಾ'
COMPLETE = '```json\n{"reply": "Done, OWNER.", "memory": "PEOPLE\\n- Ravi"}'


class Salvage(unittest.TestCase):
    """The reply text survives inside a broken envelope. Recover it."""

    def test_recovers_reply_from_truncated_json(self):
        self.assertEqual(w._salvage_reply(TRUNCATED), "OWNER, ನಿಮ್ಮ ಮಾ")

    def test_recovers_reply_from_complete_json(self):
        self.assertEqual(w._salvage_reply(COMPLETE), "Done, OWNER.")

    def test_handles_escaped_quotes(self):
        raw = '{"reply": "He said \\"yes\\" today", "memory": "x"}'
        self.assertEqual(w._salvage_reply(raw), 'He said "yes" today')

    def test_handles_escaped_newlines(self):
        raw = '{"reply": "line one\\nline two"'
        self.assertEqual(w._salvage_reply(raw), "line one\nline two")

    def test_returns_empty_when_nothing_recoverable(self):
        for junk in ("", "not json at all", "{}", '{"memory": "no reply here"}'):
            self.assertEqual(w._salvage_reply(junk), "", f"on {junk!r}")


class MachineOutputGuard(unittest.TestCase):
    """A human must never receive machine-formatted text."""

    def test_detects_fenced_and_bare_json(self):
        for t in (TRUNCATED, COMPLETE, '{"reply": "x"}', '  ```json\n{'):
            self.assertTrue(w._looks_like_machine_output(t), f"missed {t[:30]!r}")

    def test_does_not_fire_on_prose(self):
        for t in ("Hello there", "The JSON file is ready",
                  "ನಮಸ್ಕಾರ", "Sure — I'll send it.", ""):
            self.assertFalse(w._looks_like_machine_output(t), f"false positive {t!r}")


class OwnerReplyNeverLeaksJson(unittest.TestCase):
    """THE regression lock. Each test would have caught the production defect."""

    def _run(self, raw_from_model):
        saved = {}
        with mock.patch.object(w, "_generate_ai_reply", lambda *a, **k: raw_from_model), \
             mock.patch.object(w, "fetch_owner_memory", lambda s: "prior note"), \
             mock.patch.object(w, "recall_from_archive", lambda *a, **k: ""), \
             mock.patch.object(w, "owner_business_snapshot", lambda: ""), \
             mock.patch.object(w, "update_owner_memory",
                               lambda s, m: saved.update(memory=m)):
            reply = w.generate_owner_reply(OWNER, "OWNER", "Ravi", "hi", [])
        return reply, saved

    def test_truncated_envelope_does_not_reach_the_user(self):
        reply, _ = self._run(TRUNCATED)
        self.assertNotIn("```", reply, "fenced JSON reached the owner")
        self.assertNotIn('"reply"', reply, "raw JSON key reached the owner")
        self.assertFalse(reply.lstrip().startswith("{"))

    def test_truncated_envelope_still_delivers_the_content(self):
        """Salvage, not just suppression — the owner gets what was written."""
        reply, _ = self._run(TRUNCATED)
        self.assertEqual(reply, "OWNER, ನಿಮ್ಮ ಮಾ")

    def test_complete_envelope_parses_normally(self):
        reply, saved = self._run(COMPLETE)
        self.assertEqual(reply, "Done, OWNER.")
        self.assertIn("PEOPLE", saved.get("memory", ""))

    def test_unrecoverable_machine_output_yields_clean_fallback(self):
        reply, _ = self._run('```json\n{\n  "memo')
        self.assertFalse(w._looks_like_machine_output(reply))
        self.assertIn("⚠️", reply)

    def test_plain_prose_still_passes_through(self):
        """A provider ignoring the JSON instruction must not be suppressed."""
        reply, _ = self._run("Sure — I'll send that now.")
        self.assertEqual(reply, "Sure — I'll send that now.")

    def test_empty_model_output_yields_fallback(self):
        reply, _ = self._run("")
        self.assertIn("⚠️", reply)

    def test_no_production_leak_shape_survives(self):
        """Every shape observed in production, asserted at once."""
        for raw in (TRUNCATED,
                    '```json\n{\n  "reply": "OWNER,',
                    '{\n  "reply": "partial',
                    '```json\n{'):
            reply, _ = self._run(raw)
            self.assertFalse(reply.lstrip().startswith(("```", "{", '"reply"')),
                             f"leaked on {raw[:24]!r}")


class TokenBudget(unittest.TestCase):
    """The root cause: the owner envelope did not fit in the budget."""

    def test_owner_turn_has_its_own_budget(self):
        self.assertTrue(hasattr(w, "OWNER_TURN_MAX_TOKENS"))

    def test_owner_budget_exceeds_both_provider_defaults(self):
        """400 and 1200 could not hold a reply plus a 400-word Kannada note."""
        self.assertGreater(w.OWNER_TURN_MAX_TOKENS, w.OPENAI_MAX_TOKENS)
        self.assertGreater(w.OWNER_TURN_MAX_TOKENS, w.DEEPSEEK_MAX_TOKENS)
        self.assertGreaterEqual(w.OWNER_TURN_MAX_TOKENS, 2500)

    def test_owner_path_requests_the_larger_budget(self):
        seen = {}
        with mock.patch.object(w, "_generate_ai_reply",
                               lambda m, a, max_tokens=None: seen.update(mt=max_tokens) or COMPLETE), \
             mock.patch.object(w, "fetch_owner_memory", lambda s: ""), \
             mock.patch.object(w, "recall_from_archive", lambda *a, **k: ""), \
             mock.patch.object(w, "owner_business_snapshot", lambda: ""), \
             mock.patch.object(w, "update_owner_memory", lambda s, m: None):
            w.generate_owner_reply(OWNER, "OWNER", "Ravi", "hi", [])
        self.assertEqual(seen.get("mt"), w.OWNER_TURN_MAX_TOKENS)

    def test_providers_accept_a_per_call_budget(self):
        import inspect
        for fn in (w._call_openai, w._call_deepseek, w.generate_reply_gemini):
            self.assertIn("max_tokens", inspect.signature(fn).parameters,
                          f"{fn.__name__} cannot honour a per-call budget")

    def test_gemini_payload_honours_the_budget(self):
        payload = w._to_gemini_payload([{"role": "user", "content": "hi"}], 3000)
        self.assertEqual(
            payload.get("generationConfig", {}).get("maxOutputTokens"), 3000)

    def test_gemini_defaults_to_its_own_cap_when_unset(self):
        payload = w._to_gemini_payload([{"role": "user", "content": "hi"}])
        self.assertEqual(
            payload["generationConfig"]["maxOutputTokens"], w.GEMINI_MAX_TOKENS)

    def test_all_three_providers_were_capped_below_the_envelope(self):
        """The root cause was not one provider — it was ALL of them.
        openai 400, gemini 400, deepseek 1200; the envelope needs ~2500."""
        for cap in (w.OPENAI_MAX_TOKENS, w.GEMINI_MAX_TOKENS, w.DEEPSEEK_MAX_TOKENS):
            self.assertLess(cap, w.OWNER_TURN_MAX_TOKENS)


class MemoryFailureIsLoud(unittest.TestCase):
    """The silent third symptom: memory stopped advancing on 2026-07-29 and
    nothing said so."""

    def test_unparseable_envelope_logs_the_memory_failure(self):
        import io, contextlib
        buf = io.StringIO()
        with mock.patch.object(w, "_generate_ai_reply", lambda *a, **k: TRUNCATED), \
             mock.patch.object(w, "fetch_owner_memory", lambda s: "prior"), \
             mock.patch.object(w, "recall_from_archive", lambda *a, **k: ""), \
             mock.patch.object(w, "owner_business_snapshot", lambda: ""), \
             mock.patch.object(w, "update_owner_memory", lambda s, m: None), \
             contextlib.redirect_stdout(buf):
            w.generate_owner_reply(OWNER, "OWNER", "Ravi", "hi", [])
        out = buf.getvalue()
        self.assertIn("memory did NOT advance", out)

    def test_memory_advances_on_a_good_envelope(self):
        saved = {}
        with mock.patch.object(w, "_generate_ai_reply", lambda *a, **k: COMPLETE), \
             mock.patch.object(w, "fetch_owner_memory", lambda s: "old"), \
             mock.patch.object(w, "recall_from_archive", lambda *a, **k: ""), \
             mock.patch.object(w, "owner_business_snapshot", lambda: ""), \
             mock.patch.object(w, "update_owner_memory",
                               lambda s, m: saved.update(m=m)):
            w.generate_owner_reply(OWNER, "OWNER", "Ravi", "hi", [])
        self.assertIn("PEOPLE", saved.get("m", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
