"""Step 0 — no model call may outlive the Vercel function (2026-09-25).

vercel.json: maxDuration 30s. The chain tried DeepSeek (35s) -> OpenAI (20s)
-> Gemini (15s) in sequence, so a slow turn could wait 70s and be killed
before any fallback ran. Every POST now starts a clock; each provider waits at
most what is left before FUNCTION_BUDGET - POST_AI_RESERVE; a provider with
under MIN_PROVIDER_SECONDS left is skipped and the caller's fallback runs.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
MSGS = [{"role": "user", "content": "hi"}]


class Clock:
    """A controllable monotonic clock."""
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def reset_clocks():
    w._TURN_CLOCK["deadline"] = None
    w._CHAIN_DEADLINE["t"] = None


class TheBudgetFitsTheFunction(unittest.TestCase):
    def test_budget_matches_vercel_max_duration(self):
        cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
        webhook_build = next(b for b in cfg["builds"] if b["src"] == "api/webhook.py")
        self.assertEqual(webhook_build["config"]["maxDuration"], w.FUNCTION_BUDGET_SECONDS)

    def test_the_reserve_leaves_room_for_the_fallback(self):
        self.assertGreaterEqual(w.POST_AI_RESERVE_SECONDS, 5)
        self.assertLess(w.FUNCTION_BUDGET_SECONDS - w.POST_AI_RESERVE_SECONDS,
                        w.FUNCTION_BUDGET_SECONDS)

    def test_without_a_turn_clock_one_chain_still_fits(self):
        self.assertLessEqual(w.DEFAULT_AI_CHAIN_SECONDS + w.POST_AI_RESERVE_SECONDS,
                             w.FUNCTION_BUDGET_SECONDS)

    def test_the_future_interpretation_call_fits_before_a_useful_chain(self):
        """Step 2 is not built; its budget is designed now. The interpretation
        call plus at least one real provider attempt must fit in the model window."""
        window = w.FUNCTION_BUDGET_SECONDS - w.POST_AI_RESERVE_SECONDS
        self.assertLessEqual(w.INTERPRET_TIMEOUT_SECONDS + 2 * w.MIN_PROVIDER_SECONDS + 10, window)

    def test_maxduration_was_not_raised_to_hide_it(self):
        self.assertEqual(w.FUNCTION_BUDGET_SECONDS, 30.0)


class ProvidersAreBoundedByTheDeadline(unittest.TestCase):
    def setUp(self):
        reset_clocks()

    def tearDown(self):
        reset_clocks()

    def test_caps_apply_when_time_is_plentiful(self):
        clock = Clock()
        with mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()
            self.assertEqual(w._bounded(15), 15.0)

    def test_a_cap_is_shortened_to_what_is_left(self):
        clock = Clock()
        with mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()                 # deadline = +24s
            clock.t += 20                        # 4s left
            self.assertAlmostEqual(w._bounded(w.DEEPSEEK_TIMEOUT_SECONDS), 4.0)
            self.assertAlmostEqual(w._bounded(w.OPENAI_TIMEOUT_SECONDS), 4.0)

    def test_deepseek_never_waits_past_the_deadline(self):
        """The 35s cap is longer than the whole function; bounded it is not."""
        clock = Clock()
        with mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()
            self.assertLessEqual(w._bounded(w.DEEPSEEK_TIMEOUT_SECONDS),
                                 w.FUNCTION_BUDGET_SECONDS - w.POST_AI_RESERVE_SECONDS)

    def test_the_real_providers_pass_the_bounded_timeout(self):
        captured = {}

        class FakeClient:
            def __init__(self, **kw):
                self.chat = mock.Mock()
                self.chat.completions.create.side_effect = (
                    lambda **k: captured.update(k) or (_ for _ in ()).throw(RuntimeError("x")))

        fake_mod = mock.Mock(OpenAI=FakeClient)
        clock = Clock()
        with mock.patch.dict(sys.modules, {"openai": fake_mod}), \
             mock.patch.object(w, "DEEPSEEK_API_KEY", "k"), \
             mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()
            clock.t += 21                        # 3s left
            w._call_deepseek(MSGS)
        self.assertAlmostEqual(captured["timeout"], 3.0)

    def test_gemini_passes_the_bounded_timeout(self):
        captured = {}

        def fake_post(*a, **k):
            captured.update(k)
            raise RuntimeError("x")

        clock = Clock()
        with mock.patch.object(w, "GEMINI_API_KEY", "k"), \
             mock.patch.object(w.requests, "post", fake_post), \
             mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()
            clock.t += 22                        # 2s left
            w.generate_reply_gemini(MSGS)
        self.assertAlmostEqual(captured["timeout"], 2.0)


class TheChainStopsSoTheFallbackRuns(unittest.TestCase):
    def setUp(self):
        reset_clocks()

    def tearDown(self):
        reset_clocks()

    def _chain(self, clock, spend):
        """Providers that each consume `spend` seconds and fail."""
        called = []

        def make(name):
            def provider(messages, max_tokens=None):
                called.append(name)
                clock.t += spend
                return ""
            return provider
        return [(n, make(n)) for n in ("deepseek", "openai", "gemini")], called

    def test_slow_failures_stop_before_the_deadline(self):
        clock = Clock()
        chain, called = self._chain(clock, spend=11)
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.start_turn_clock()
            out = w._generate_ai_reply(MSGS, "APOLOGY")
        # 24s window: deepseek (11) + openai (11) = 22s, 2s left -> gemini still
        # allowed at exactly MIN; add one more second of spend and it is not.
        self.assertEqual(out, "APOLOGY")
        self.assertLessEqual(clock.t - 1000, w.FUNCTION_BUDGET_SECONDS - w.POST_AI_RESERVE_SECONDS + 11)

    def test_a_provider_is_skipped_when_under_the_minimum(self):
        clock = Clock()
        chain, called = self._chain(clock, spend=12)
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.start_turn_clock()                 # 24s window
            out = w._generate_ai_reply(MSGS, "APOLOGY")
        self.assertEqual(called, ["deepseek", "openai"])   # 0s left: gemini skipped
        self.assertEqual(out, "APOLOGY")                   # the existing fallback

    def test_a_late_turn_skips_every_provider(self):
        clock = Clock()
        chain, called = self._chain(clock, spend=1)
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.start_turn_clock()
            clock.t += 23                        # 1s left, below MIN
            out = w._generate_ai_reply(MSGS, "APOLOGY")
        self.assertEqual(called, [])
        self.assertEqual(out, "APOLOGY")

    def test_a_fast_success_is_untouched(self):
        clock = Clock()
        chain = [("deepseek", lambda m, t=None: "hello")]
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.start_turn_clock()
            self.assertEqual(w._generate_ai_reply(MSGS, "APOLOGY"), "hello")

    def test_bairavi_falls_back_to_the_composed_reply_when_out_of_time(self):
        """"" from the model path means the composer's reply is sent."""
        clock = Clock()
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: [("deepseek", lambda m, t=None: "x")]), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.start_turn_clock()
            clock.t += 23
            followup = w.bairavi.parse_followup("what is the impedance?")
            self.assertEqual(w.bairavi_model_reply("919000000000", "what is the impedance?",
                                                   [], followup, {}), "")


class TheClockResetsPerRequest(unittest.TestCase):
    def tearDown(self):
        reset_clocks()

    def test_a_reused_instance_does_not_inherit_an_old_deadline(self):
        clock = Clock()
        with mock.patch.object(w.time, "monotonic", clock):
            w.start_turn_clock()
            clock.t += 500                       # a warm instance, much later
            w.start_turn_clock()
            self.assertGreater(w.ai_seconds_left(), 20)

    def test_do_post_starts_the_clock(self):
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        self.assertLess(src.index("start_turn_clock()"), src.index("self.rfile.read"))

    def test_without_a_clock_a_chain_gets_its_own_bounded_window(self):
        reset_clocks()
        clock = Clock()
        seen = []
        chain = [("deepseek", lambda m, t=None: seen.append(w.ai_seconds_left()) or "")]
        with mock.patch.object(w.time, "monotonic", clock), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w._generate_ai_reply(MSGS, "")
        self.assertAlmostEqual(seen[0], w.DEFAULT_AI_CHAIN_SECONDS)
        self.assertIsNone(w._CHAIN_DEADLINE["t"])          # cleaned up after


if __name__ == "__main__":
    unittest.main()
