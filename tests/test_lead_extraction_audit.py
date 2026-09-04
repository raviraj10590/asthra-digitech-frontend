"""Durable observability for the AI lead-extraction path.

THE UNKNOWN THIS ANSWERS
------------------------
Nothing could say whether extract_lead_info is reached in production. It is
not a registered tool, so it writes no audit row; its only trace is a print
that survives ~1 hour. Production shows 17 upsert_lead executions, all
attributable to menu taps, which IMPLIES the AI path has never produced a
lead — but an inference drawn from an absence is not an observation. These
events make it one.

WHAT IS RECORDED, AND WHAT IS NOT
---------------------------------
Recorded: outcome, provider, model, latency, field NAMES, field count,
exception TYPE, and OpenAI token usage (the tokens_in/tokens_out columns
have existed since migration 20260802000003 and nothing has ever written
them — so the first real answer to "what is extraction costing?" needs no
migration).

Never recorded: the prompt, the provider response, the conversation, any
lead VALUE, or the phone. extract_lead_info is not even given a phone —
adding a parameter to carry one would change the call contract, so the
event deliberately has no sender marker and correlates to the adjacent
lead_upsert row by timestamp instead.

Offline: fake providers only. No network, no OpenAI, no Gemini.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

# A conversation carrying PII in the message TEXT, so any leak of the
# transcript into the audit row is detectable.
HISTORY = [
    {"role": "user", "content": "Hi, I am Ravi Kumar from Acme Traders"},
    {"role": "assistant", "content": "How can we help?"},
    {"role": "user", "content": "Need Digital Ads, budget 50000, in Bengaluru"},
    {"role": "assistant", "content": "Noted."},
]
LEAD = {"name": "Ravi Kumar", "company": "Acme Traders",
        "budget": "50000", "city": "Bengaluru"}
PII = ("Ravi Kumar", "Acme Traders", "50000", "Bengaluru",
       "sales analyst", "Need Digital Ads")   # last two: prompt + transcript


class _Msg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _Usage:
    def __init__(self, pt, ct):
        self.prompt_tokens, self.completion_tokens = pt, ct


class _Resp:
    def __init__(self, content, usage=True):
        self.choices = [_Msg(content)]
        if usage:
            self.usage = _Usage(1234, 56)


def run(openai_content=None, openai_exc=None,
        gemini_content=None, gemini_exc=None,
        history=None, audit_raises=None, usage=True):
    """Drive the REAL extract_lead_info. Returns (result, audits, stdout)."""
    audits = []

    def fake_db_insert(table, row, timeout=None):
        audits.append({"table": table, "row": row})
        if audit_raises is not None:
            raise audit_raises

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    if openai_exc is not None:
                        raise openai_exc
                    return _Resp(openai_content, usage=usage)

    def fake_gemini(msgs):
        if gemini_exc is not None:
            raise gemini_exc
        return gemini_content

    buf = io.StringIO()
    with mock.patch.object(w, "get_openai", lambda: _Client), \
         mock.patch.object(w, "generate_reply_gemini", fake_gemini), \
         mock.patch.object(w, "BIC_AVAILABLE", True), \
         mock.patch.object(w.bic_config, "is_configured", lambda: True), \
         mock.patch.object(w.bic_db, "insert", fake_db_insert), \
         redirect_stdout(buf):
        result = w.extract_lead_info(HISTORY if history is None else history)
    return result, [a["row"] for a in audits], buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# 1 · every outcome is recorded, and distinctly
# ══════════════════════════════════════════════════════════════════════════

class OutcomesAreRecorded(unittest.TestCase):

    def only(self, rows):
        self.assertEqual(len(rows), 1, "expected exactly one audit row")
        return rows[0]

    def test_attempt_and_success_are_recorded(self):
        result, rows, _ = run(openai_content=json.dumps(LEAD))
        row = self.only(rows)
        self.assertEqual(result, LEAD)
        self.assertEqual(row["tool"], w.LEAD_EXTRACTION_EVENT)
        self.assertEqual(row["args_redacted"]["outcome"], w.EXTRACTION_SUCCESS)
        self.assertTrue(row["ok"])

    def test_empty_result_is_recorded_as_empty_not_success(self):
        """"The model answered and found nothing" is the single most likely
        production state, and it must not read as a failure or a success."""
        result, rows, _ = run(openai_content="{}")
        row = self.only(rows)
        self.assertEqual(result, {})
        self.assertEqual(row["args_redacted"]["outcome"], w.EXTRACTION_EMPTY)
        self.assertFalse(row["ok"])

    def test_no_json_object_at_all_is_empty(self):
        """No `{...}` match returns {} WITHOUT trying Gemini — existing
        control flow, pinned so instrumentation cannot have altered it."""
        result, rows, _ = run(openai_content="sorry, nothing here")
        row = self.only(rows)
        self.assertEqual(result, {})
        self.assertEqual(row["args_redacted"]["outcome"], w.EXTRACTION_EMPTY)
        self.assertEqual(row["args_redacted"]["provider"], "openai")

    def test_parse_failure_is_distinct_from_provider_failure(self):
        """Malformed JSON means the provider ANSWERED and we could not read
        it — a different remedy from the call failing."""
        # Must MATCH the `\{.*\}` regex yet fail json.loads — an unclosed
        # brace finds no match at all and is correctly reported EMPTY.
        _, rows, _ = run(openai_content='{"name": broken}', gemini_content=None)
        self.assertEqual(rows[0]["args_redacted"]["outcome"],
                         w.EXTRACTION_PARSE_FAILED)
        self.assertIn("Error", rows[0]["error"] or "")

    def test_provider_failure_is_recorded(self):
        _, rows, _ = run(openai_exc=RuntimeError("quota exhausted"),
                         gemini_content=None)
        self.assertEqual(rows[0]["args_redacted"]["outcome"],
                         w.EXTRACTION_PROVIDER_FAILED)
        self.assertEqual(rows[0]["error"], "RuntimeError")

    def test_short_history_records_a_skip_and_calls_no_provider(self):
        result, rows, _ = run(history=[{"role": "user", "content": "hi"}])
        row = self.only(rows)
        self.assertEqual(result, {})
        self.assertEqual(row["args_redacted"]["outcome"], w.EXTRACTION_SKIPPED)
        self.assertIsNone(row["args_redacted"]["provider"])

    def test_field_names_and_count_are_recorded(self):
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        a = rows[0]["args_redacted"]
        self.assertEqual(a["fields"], ["budget", "city", "company", "name"])
        self.assertEqual(a["field_count"], 4)

    def test_latency_and_model_are_recorded(self):
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        self.assertEqual(rows[0]["args_redacted"]["model"], "gpt-4o-mini")
        self.assertEqual(rows[0]["args_redacted"]["provider"], "openai")
        self.assertIsInstance(rows[0]["latency_ms"], int)
        self.assertGreaterEqual(rows[0]["latency_ms"], 0)


class TokenTelemetry(unittest.TestCase):
    """tokens_in/tokens_out have existed since migration 20260802000003 and
    nothing has ever written them. No migration is required."""

    def test_openai_token_usage_is_recorded(self):
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        self.assertEqual(rows[0]["tokens_in"], 1234)
        self.assertEqual(rows[0]["tokens_out"], 56)

    def test_a_response_without_usage_does_not_break_extraction(self):
        """A stub client or older SDK may carry no `usage`. Observability
        must never be the thing that breaks the path it observes."""
        result, rows, _ = run(openai_content=json.dumps(LEAD), usage=False)
        self.assertEqual(result, LEAD)
        self.assertIsNone(rows[0]["tokens_in"])
        self.assertIsNone(rows[0]["tokens_out"])

    def test_gemini_records_no_token_usage(self):
        """generate_reply_gemini returns a bare string — no usage exists, and
        inventing a number would be worse than a null."""
        _, rows, _ = run(openai_exc=RuntimeError("down"),
                         gemini_content=json.dumps(LEAD))
        gem = [r for r in rows if r["args_redacted"]["provider"] == "gemini"][0]
        self.assertIsNone(gem["tokens_in"])
        self.assertIsNone(gem["tokens_out"])


# ══════════════════════════════════════════════════════════════════════════
# 2 · the fallback chain, unchanged
# ══════════════════════════════════════════════════════════════════════════

class FallbackBehaviourUnchanged(unittest.TestCase):

    def test_openai_failure_falls_back_to_gemini_and_both_are_recorded(self):
        result, rows, out = run(openai_exc=RuntimeError("down"),
                                gemini_content=json.dumps(LEAD))
        self.assertEqual(result, LEAD)
        self.assertEqual([r["args_redacted"]["provider"] for r in rows],
                         ["openai", "gemini"])
        self.assertEqual(rows[1]["args_redacted"]["outcome"],
                         w.EXTRACTION_SUCCESS)
        self.assertIn("Gemini fallback", out)

    def test_gemini_failure_after_openai_failure_returns_empty(self):
        result, rows, _ = run(openai_exc=RuntimeError("a"),
                              gemini_exc=RuntimeError("b"))
        self.assertEqual(result, {})
        self.assertEqual([r["args_redacted"]["outcome"] for r in rows],
                         [w.EXTRACTION_PROVIDER_FAILED,
                          w.EXTRACTION_PROVIDER_FAILED])

    def test_gemini_answering_without_json_records_empty(self):
        result, rows, _ = run(openai_exc=RuntimeError("a"),
                              gemini_content="no json here")
        self.assertEqual(result, {})
        self.assertEqual(rows[1]["args_redacted"]["outcome"],
                         w.EXTRACTION_EMPTY)

    def test_a_successful_openai_call_never_reaches_gemini(self):
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        self.assertEqual([r["args_redacted"]["provider"] for r in rows],
                         ["openai"])

    def test_an_empty_openai_result_does_not_trigger_the_fallback(self):
        """Existing control flow: `if match else {}` returns immediately."""
        _, rows, _ = run(openai_content="{}", gemini_content=json.dumps(LEAD))
        self.assertEqual([r["args_redacted"]["provider"] for r in rows],
                         ["openai"])


# ══════════════════════════════════════════════════════════════════════════
# 3 · PII — prompt, response, transcript and values all excluded
# ══════════════════════════════════════════════════════════════════════════

class NoPiiIsStored(unittest.TestCase):

    def assertClean(self, rows):
        blob = str(rows)
        for secret in PII:
            self.assertNotIn(secret, blob, secret)

    def test_success_row_stores_no_values_prompt_or_transcript(self):
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        self.assertClean(rows)

    def test_failure_row_stores_no_values_prompt_or_transcript(self):
        _, rows, _ = run(openai_exc=RuntimeError("Ravi Kumar rejected"),
                         gemini_exc=RuntimeError("Acme Traders"))
        self.assertClean(rows)

    def test_parse_failure_stores_no_provider_response(self):
        _, rows, _ = run(openai_content='{"name": "Ravi Kumar", broken}')
        self.assertClean(rows)

    def test_no_sender_marker_is_stored(self):
        """extract_lead_info is never given a phone; the event records none
        and correlates to lead_upsert by timestamp instead."""
        _, rows, _ = run(openai_content=json.dumps(LEAD))
        self.assertIsNone(rows[0]["source_ref"])

    def test_only_the_exception_type_is_stored_never_its_message(self):
        _, rows, _ = run(openai_exc=RuntimeError("customer 919999000444"),
                         gemini_content=None)
        self.assertEqual(rows[0]["error"], "RuntimeError")
        self.assertNotIn("919999000444", str(rows))


# ══════════════════════════════════════════════════════════════════════════
# 4 · best-effort, and the registry left alone
# ══════════════════════════════════════════════════════════════════════════

class BestEffortAndUnregistered(unittest.TestCase):

    def test_an_audit_failure_does_not_break_extraction(self):
        result, _, out = run(openai_content=json.dumps(LEAD),
                             audit_raises=RuntimeError("store down"))
        self.assertEqual(result, LEAD)
        self.assertIn("LEAD_EXTRACTION_AUDIT_FAILED", out)

    def test_an_audit_failure_logs_the_type_only(self):
        _, _, out = run(openai_content=json.dumps(LEAD),
                        audit_raises=RuntimeError("Ravi Kumar"))
        self.assertIn("RuntimeError", out)
        self.assertNotIn("Ravi Kumar", out)

    def test_nothing_is_recorded_when_bic_is_unavailable(self):
        audits = []
        with mock.patch.object(w, "get_openai",
                               lambda: (_ for _ in ()).throw(RuntimeError("x"))), \
             mock.patch.object(w, "generate_reply_gemini", lambda m: None), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             mock.patch.object(w.bic_db, "insert",
                               lambda t, r, timeout=None: audits.append(r)), \
             redirect_stdout(io.StringIO()):
            w.extract_lead_info(HISTORY)
        self.assertEqual(audits, [])

    def test_the_event_is_not_a_registered_tool(self):
        mig = os.path.join(os.path.dirname(__file__), "..", "supabase",
                           "migrations")
        for name in os.listdir(mig):
            with open(os.path.join(mig, name)) as fh:
                sql = "\n".join(l for l in fh if not l.strip().startswith("--"))
            self.assertNotIn(f"'{w.LEAD_EXTRACTION_EVENT}'", sql, name)

    def test_no_migration_is_needed_for_token_columns(self):
        """The columns this writes must already exist."""
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260802000003_bic_observability.sql")
        with open(path) as fh:
            sql = fh.read()
        for col in ("tokens_in", "tokens_out", "latency_ms", "args_redacted"):
            self.assertIn(col, sql, col)


class ProviderContractUnchanged(unittest.TestCase):
    """The instrumentation must not have touched prompt, model or params."""

    def test_the_call_parameters_are_unchanged(self):
        seen = {}

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        seen.update(kw)
                        return _Resp("{}")
        with mock.patch.object(w, "get_openai", lambda: _Client), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             redirect_stdout(io.StringIO()):
            w.extract_lead_info(HISTORY)
        self.assertEqual(seen["model"], "gpt-4o-mini")
        self.assertEqual(seen["max_tokens"], 380)
        self.assertEqual(seen["temperature"], 0)
        self.assertEqual(seen["messages"][0]["content"],
                         w.EXTRACTION_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
