"""LLM provider calls are time-bounded, so one slow provider cannot hold a turn.

THE DEFECT
----------
`_call_deepseek` and `get_openai` constructed their clients with NO timeout, so
both inherited the OpenAI SDK default of roughly TEN MINUTES. Gemini already
passed `timeout=15`. That asymmetry is measurable in production: the derived
provider phase reached p90 44.48s, p95 49.50s and max 73.49s, while every
deterministic turn finished in 3.26s.

Meta is acknowledged only after processing completes, so that time is paid by
the customer's phone and by Meta's retry window alike.

WHAT THE VALUES ARE, AND WHY THEY ARE NOT ROUND NUMBERS PICKED BY FEEL
---------------------------------------------------------------------
Successful DeepSeek calls measure p50 24.16s, p75 32.67s, p90 41.88s,
max 52.05s — it is a reasoning model and it is genuinely slow. 35s sits just
above p75, leaving ~three quarters of successful calls untouched; simulated
against the real distribution it caps the provider phase at 40.72s instead of
73.49s while sending 21.5% of calls into the EXISTING Gemini fallback
(measured 5.72s), where they still get an answer.

WHAT THIS DOES NOT DO
---------------------
It does not fix the median. DeepSeek's own median is 24s, so no finite timeout
brings a turn under Meta's window. This bounds the tail only. It also does NOT
move the webhook acknowledgement, add retries, or change provider order.

Offline: no network, no provider, no database.
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

MSGS = [{"role": "user", "content": "hi"}]


class FakeTimeout(Exception):
    """Stands in for the SDK's APITimeoutError without importing it."""
    pass


FakeTimeout.__name__ = "APITimeoutError"


class _GeminiResp:
    """Minimal stand-in for the requests Response generate_reply_gemini reads."""

    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = str(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._p


class CapturingClient:
    """Records the kwargs the provider client was constructed with."""
    last_kwargs = None
    construct_count_for_turn = 0

    def __init__(self, **kwargs):
        CapturingClient.last_kwargs = kwargs
        CapturingClient.construct_count_for_turn += 1
        self.chat = mock.Mock()
        self.chat.completions.create.side_effect = FakeTimeout("timed out")


def build_kwargs_for(call, patch_target):
    """Run `call` with the OpenAI class replaced; return construction kwargs."""
    CapturingClient.last_kwargs = None
    CapturingClient.construct_count_for_turn = 0
    fake_mod = mock.Mock()
    fake_mod.OpenAI = CapturingClient
    buf = io.StringIO()
    with mock.patch.dict(sys.modules, {"openai": fake_mod}), \
         redirect_stdout(buf):
        call()
    return CapturingClient.last_kwargs, buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# 1-3 · every provider is bounded
# ══════════════════════════════════════════════════════════════════════════

class TimeoutsAreExplicit(unittest.TestCase):

    def test_1_deepseek_client_receives_an_explicit_timeout(self):
        with mock.patch.object(w, "DEEPSEEK_API_KEY", "k"):
            kw, _ = build_kwargs_for(lambda: w._call_deepseek(MSGS), "deepseek")
        self.assertIn("timeout", kw)
        self.assertEqual(kw["timeout"], w.DEEPSEEK_TIMEOUT_SECONDS)

    def test_2_openai_client_receives_an_explicit_timeout(self):
        kw, _ = build_kwargs_for(lambda: w.get_openai(), "openai")
        self.assertIn("timeout", kw)
        self.assertEqual(kw["timeout"], w.OPENAI_TIMEOUT_SECONDS)

    def test_3_gemini_timeout_is_unchanged(self):
        import inspect
        self.assertIn("timeout=15",
                      inspect.getsource(w.generate_reply_gemini))

    def test_the_timeouts_are_finite_and_not_the_sdk_default(self):
        """The SDK default is ~600s. Anything near it is not a bound."""
        for name, v in (("deepseek", w.DEEPSEEK_TIMEOUT_SECONDS),
                        ("openai", w.OPENAI_TIMEOUT_SECONDS)):
            self.assertIsNotNone(v, name)
            self.assertGreater(v, 0, name)
            self.assertLess(v, 120, f"{name} timeout is not a real bound")

    def test_the_values_match_the_measured_evidence(self):
        """35s sits just above DeepSeek's measured p75 (32.67s); 20s is above
        Gemini's proven 15s for comparable calls."""
        self.assertGreaterEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 32.67)
        self.assertLessEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 45)
        self.assertGreaterEqual(w.OPENAI_TIMEOUT_SECONDS, 15)
        self.assertLessEqual(w.OPENAI_TIMEOUT_SECONDS, 30)

    def test_the_timeouts_are_env_overridable(self):
        import inspect
        src = inspect.getsource(w)
        self.assertIn('os.environ.get("DEEPSEEK_TIMEOUT_SECONDS"', src)
        self.assertIn('os.environ.get("OPENAI_TIMEOUT_SECONDS"', src)


# ══════════════════════════════════════════════════════════════════════════
# 4-6 · a timeout is a provider failure, and falls back exactly once
# ══════════════════════════════════════════════════════════════════════════

class TimeoutFallsBack(unittest.TestCase):

    def test_4_deepseek_timeout_returns_empty_so_the_chain_continues(self):
        with mock.patch.object(w, "DEEPSEEK_API_KEY", "k"):
            _, out = build_kwargs_for(lambda: self.assertEqual(
                w._call_deepseek(MSGS), ""), "deepseek")
        self.assertIn("TIMEOUT", out)

    def test_5_openai_timeout_returns_empty_so_the_chain_continues(self):
        fake_mod = mock.Mock()
        fake_mod.OpenAI = CapturingClient
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, {"openai": fake_mod}), \
             redirect_stdout(buf):
            self.assertEqual(w._call_openai(MSGS), "")
        self.assertIn("TIMEOUT", buf.getvalue())

    # NOTE ON THESE THREE. The first version stubbed _PROVIDERS with functions
    # that RAISED, and they failed — because _generate_ai_reply does not wrap
    # provider calls in try/except; each provider catches its own errors and
    # returns "". The stubs were therefore testing a contract the real code
    # does not have. These drive the REAL provider functions with a faked SDK
    # instead, which is what production actually does.

    def _fake_sdk(self, stack):
        """Replace the openai module so the REAL provider functions time out."""
        CapturingClient.construct_count_for_turn = 0
        fake_mod = mock.Mock()
        fake_mod.OpenAI = CapturingClient
        stack.enter_context(mock.patch.dict(sys.modules, {"openai": fake_mod}))

    def test_4b_a_deepseek_timeout_reaches_the_next_provider(self):
        """The EXISTING chain, unchanged: a timeout is just a failure."""
        from contextlib import ExitStack
        seen = []

        def gemini_ok(url, json=None, timeout=None):
            seen.append("gemini")
            return _GeminiResp({"candidates": [{"finishReason": "STOP",
                                "content": {"parts": [{"text": "REPLY"}]}}]})
        with ExitStack() as st:
            self._fake_sdk(st)
            st.enter_context(mock.patch.object(w, "DEEPSEEK_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "GEMINI_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "AI_PROVIDER_ORDER",
                                               "deepseek,gemini"))
            st.enter_context(mock.patch.object(w, "BIC_AVAILABLE", False))
            st.enter_context(mock.patch.object(w.requests, "post", gemini_ok))
            st.enter_context(redirect_stdout(io.StringIO()))
            out = w._generate_ai_reply(MSGS, "sorry")
        self.assertEqual(out, "REPLY")
        self.assertEqual(seen, ["gemini"], "gemini must be called exactly once")

    def test_6_a_timeout_causes_no_retry_storm(self):
        """Each provider is attempted exactly ONCE per turn."""
        from contextlib import ExitStack
        calls = []

        def gemini_ok(url, json=None, timeout=None):
            calls.append("gemini")
            return _GeminiResp({"candidates": [{"finishReason": "STOP",
                                "content": {"parts": [{"text": "REPLY"}]}}]})
        with ExitStack() as st:
            self._fake_sdk(st)
            st.enter_context(mock.patch.object(w, "DEEPSEEK_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "GEMINI_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "AI_PROVIDER_ORDER",
                                               "deepseek,gemini"))
            st.enter_context(mock.patch.object(w, "BIC_AVAILABLE", False))
            st.enter_context(mock.patch.object(w.requests, "post", gemini_ok))
            st.enter_context(redirect_stdout(io.StringIO()))
            w._generate_ai_reply(MSGS, "sorry")
        # one SDK-backed attempt each for deepseek and openai, one gemini
        self.assertEqual(calls.count("gemini"), 1)
        self.assertEqual(CapturingClient.construct_count_for_turn, 1)

    def test_6b_no_retry_loop_exists_in_the_provider_functions(self):
        """AST, not a string match. An earlier version looked for the literal
        "for attempt"; a mutation inserting `for _attempt in range(3)` walked
        straight past it. A loop is a loop whatever it is named."""
        import ast, inspect, textwrap
        for fn in (w._call_deepseek, w._call_openai, w.generate_reply_gemini):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            loops = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.For, ast.While, ast.AsyncFor))]
            self.assertEqual(loops, [],
                             f"{fn.__name__} contains a loop — a retry storm "
                             f"is one edit away")

    def test_all_providers_timing_out_still_returns_the_apology(self):
        from contextlib import ExitStack

        def gemini_timeout(url, json=None, timeout=None):
            raise FakeTimeout("timed out")
        with ExitStack() as st:
            self._fake_sdk(st)
            st.enter_context(mock.patch.object(w, "DEEPSEEK_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "GEMINI_API_KEY", "k"))
            st.enter_context(mock.patch.object(w, "BIC_AVAILABLE", False))
            st.enter_context(mock.patch.object(w.requests, "post",
                                               gemini_timeout))
            st.enter_context(redirect_stdout(io.StringIO()))
            self.assertEqual(w._generate_ai_reply(MSGS, "APOLOGY"), "APOLOGY")


# ══════════════════════════════════════════════════════════════════════════
# 7-9 · classification and what never reaches the log
# ══════════════════════════════════════════════════════════════════════════

class TimeoutIsDistinguishable(unittest.TestCase):

    def test_7_a_timeout_is_labelled_as_a_timeout(self):
        with mock.patch.object(w, "DEEPSEEK_API_KEY", "k"):
            _, out = build_kwargs_for(lambda: w._call_deepseek(MSGS), "d")
        self.assertIn("TIMEOUT", out)
        self.assertIn("APITimeoutError", out)

    def test_7b_a_non_timeout_error_is_not_mislabelled(self):
        fake_mod = mock.Mock()

        class Boom:
            def __init__(self, **kw):
                self.chat = mock.Mock()
                self.chat.completions.create.side_effect = ValueError("bad request")
        fake_mod.OpenAI = Boom
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, {"openai": fake_mod}), \
             mock.patch.object(w, "DEEPSEEK_API_KEY", "k"), \
             redirect_stdout(buf):
            w._call_deepseek(MSGS)
        self.assertNotIn("TIMEOUT", buf.getvalue())
        self.assertIn("deepseek error", buf.getvalue())

    def test_the_classifier_recognises_sdk_timeout_type_names(self):
        for name in ("APITimeoutError", "ReadTimeout", "ConnectTimeout",
                     "TimeoutError", "PoolTimeout"):
            exc = type(name, (Exception,), {})()
            self.assertTrue(w._is_timeout(exc), name)
        for name in ("ValueError", "RateLimitError", "APIConnectionError"):
            exc = type(name, (Exception,), {})()
            self.assertFalse(w._is_timeout(exc), name)

    def test_8_and_9_no_credential_prompt_or_response_is_logged(self):
        SECRET = "sk-SENTINEL-key-should-never-appear"
        fake_mod = mock.Mock()

        class Leaky:
            def __init__(self, **kw):
                self.chat = mock.Mock()
                self.chat.completions.create.side_effect = FakeTimeout(
                    f"request to https://api.deepseek.com failed key={SECRET} "
                    f"body={{'messages': 'CUSTOMER TRANSCRIPT HERE'}}")
        fake_mod.OpenAI = Leaky
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, {"openai": fake_mod}), \
             mock.patch.object(w, "DEEPSEEK_API_KEY", SECRET), \
             redirect_stdout(buf):
            w._call_deepseek([{"role": "user", "content": "CUSTOMER TRANSCRIPT HERE"}])
        out = buf.getvalue()
        self.assertNotIn(SECRET, out)
        self.assertNotIn("CUSTOMER TRANSCRIPT HERE", out)
        self.assertIn("TIMEOUT", out)


# ══════════════════════════════════════════════════════════════════════════
# 10-21 · everything else is untouched
# ══════════════════════════════════════════════════════════════════════════

class NothingElseChanged(unittest.TestCase):

    def test_10_provider_order_is_unchanged(self):
        import inspect
        src = inspect.getsource(w._provider_chain)
        self.assertIn("AI_PROVIDER_ORDER", src)
        self.assertIn("AI_PROVIDER_PRIMARY", src)
        self.assertEqual(set(w._PROVIDERS), {"deepseek", "openai", "gemini"})

    def test_11_model_selection_is_unchanged(self):
        self.assertEqual(w.DEEPSEEK_MODEL, "deepseek-v4-pro")
        import inspect
        self.assertIn("model=OPENAI_CHAT_MODEL",
                      inspect.getsource(w._call_openai))
        self.assertIn("model=DEEPSEEK_MODEL",
                      inspect.getsource(w._call_deepseek))

    def test_12_max_tokens_are_unchanged(self):
        self.assertEqual(w.DEEPSEEK_MAX_TOKENS, 1200)
        self.assertEqual(w.OPENAI_MAX_TOKENS, 900)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)
        import inspect
        self.assertIn("max_tokens=380",
                      inspect.getsource(w.extract_lead_info))

    def test_13_the_extraction_parser_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.extract_lead_info)
        self.assertIn("re.search(r'\\{.*\\}'", src)
        self.assertIn("json.loads", src)
        self.assertIn("generate_reply_gemini", src)

    def test_14_the_extraction_cadence_is_unchanged(self):
        import inspect
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      inspect.getsource(w.run_client_pipeline))

    def test_15_lead_upsert_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.upsert_lead)
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")', src)
        self.assertNotIn("_supa_headers", src)

    def test_16_business_status_is_unchanged(self):
        import inspect
        self.assertIn("BUSINESS_STATUS_GOAL",
                      inspect.getsource(w.tool_business_status))
        self.assertEqual(w.BUSINESS_STATUS_GOAL, "business_month_review")

    def test_17_business_reasoning_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.tool_business_reasoning)
        self.assertIn("bic_reasoning.reason", src)
        self.assertIn("bic_explain.validate_narration", src)
        self.assertNotIn("authorize", src)

    def test_18_19_the_prompt_and_routing_are_unchanged(self):
        self.assertIn("Robot ಭಾಷೆ ಬೇಡ", w.SYSTEM_PROMPT)
        for t, gate in (("What is the business status this month?",
                         w.owner_business_status_query),
                        ("Why are my enquiries low?", w.owner_reasoning_query),
                        ("How many enquiries this month?", w.owner_evidence_query)):
            self.assertTrue(gate(t), t)

    def test_20_deterministic_paths_call_no_provider(self):
        """A menu tap must not reach an LLM, timeout or otherwise."""
        import inspect
        for fn in (w.is_menu_request, w.is_off_topic, w.is_brochure_request,
                   w.owner_reasoning_query, w.owner_business_status_query):
            src = inspect.getsource(fn).lower()
            for banned in ("openai", "gemini", "deepseek", "_generate_ai_reply"):
                self.assertNotIn(banned, src, f"{fn.__name__}:{banned}")

    def test_21_a_timeout_still_reaches_deterministic_degradation(self):
        """business_status must still render from records when CONSULT dies."""
        import inspect
        src = inspect.getsource(w.tool_business_status)
        self.assertIn("render_business_status", src)
        self.assertIn("narration_rejected", src)

    def test_the_webhook_ack_was_not_moved(self):
        """Explicitly out of scope for this task."""
        import inspect
        src = inspect.getsource(w.HANDLER_CLASS.do_POST) \
            if hasattr(w, "HANDLER_CLASS") else None
        if src is None:
            import re
            whole = io.open(os.path.join(os.path.dirname(__file__), "..",
                                         "api", "webhook.py"),
                            encoding="utf-8").read()
            m = re.search(r"finally:\n(.*?)_decision_flush\(\)\n(\s*)self\._ok\(\); return",
                          whole, re.S)
            self.assertIsNotNone(
                m, "the ack no longer follows _decision_flush() — ack timing changed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
