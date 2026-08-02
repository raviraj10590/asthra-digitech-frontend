"""Slice 1C — Decision Replay Mode tests (ADR 0004). Offline."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bic import replay  # noqa: E402


class TestRecorder(unittest.TestCase):
    def test_records_without_executing(self):
        r = replay.Recorder()
        send = r.stub("send_text")
        result = send("919000000001", "hello")
        self.assertIsNone(result)
        self.assertEqual(len(r.ops), 1)
        self.assertEqual(r.ops[0].operation, "send_text")
        self.assertEqual(r.ops[0].mode, "REPLAY")

    def test_stub_accepts_any_signature(self):
        """Recorders replace arbitrary callables; they must never raise on shape."""
        r = replay.Recorder()
        s = r.stub("crm_sync_lead")
        s("91900", {"service": "web"})
        s(phone="91900", data={"x": 1})
        s()
        self.assertEqual(len(r.ops), 3)

    def test_stub_returns_benign_default(self):
        """The surrounding flow must continue normally after a stubbed call."""
        r = replay.Recorder()
        self.assertEqual(r.stub("leads_today", return_value=[])(), [])

    def test_recorded_op_key_is_stable(self):
        r = replay.Recorder()
        r.record("crm_sync_lead", phone="91900", service="web")
        r2 = replay.Recorder()
        r2.record("crm_sync_lead", service="web", phone="91900")   # different order
        self.assertEqual(r.keys(), r2.keys())

    def test_as_dicts_matches_documented_shape(self):
        r = replay.Recorder()
        r.record("crm_sync_lead", phone="91900")
        self.assertEqual(r.as_dicts(),
                         [{"tool": "crm_sync_lead",
                           "arguments": {"phone": "91900"},
                           "mode": "REPLAY"}])


class TestFingerprint(unittest.TestCase):
    def test_same_input_same_fingerprint(self):
        a = [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]
        self.assertEqual(replay.fingerprint(a), replay.fingerprint(list(a)))

    def test_different_input_different_fingerprint(self):
        a = [{"role": "user", "content": "hi"}]
        b = [{"role": "user", "content": "hello"}]
        self.assertNotEqual(replay.fingerprint(a), replay.fingerprint(b))

    def test_handles_unserialisable_input(self):
        class Weird:
            pass
        self.assertIsInstance(replay.fingerprint([Weird()]), str)

    def test_kannada_text_is_stable(self):
        a = [{"content": "ನಮಸ್ಕಾರ 🙏"}]
        self.assertEqual(replay.fingerprint(a), replay.fingerprint(a))


class TestCompare(unittest.TestCase):
    def _d(self, **kw):
        base = dict(route="client", role="CLIENT", tools=[], intended_ops=[])
        base.update(kw)
        return replay.Decision(**base)

    def test_identical_decisions_have_no_diffs(self):
        self.assertEqual(replay.compare(self._d(), self._d()), [])

    def test_route_difference_detected(self):
        diffs = replay.compare(self._d(route="client"), self._d(route="owner"))
        self.assertTrue(any("route" in d for d in diffs))

    def test_tool_difference_detected(self):
        diffs = replay.compare(self._d(tools=["send_brochure"]), self._d(tools=[]))
        self.assertTrue(any("tools" in d for d in diffs))

    def test_tool_order_does_not_matter(self):
        """Ordering is not a behaviour difference — avoid false positives."""
        self.assertEqual(
            replay.compare(self._d(tools=["a", "b"]), self._d(tools=["b", "a"])), [])

    def test_prompt_fingerprint_difference_detected(self):
        diffs = replay.compare(self._d(prompt_fingerprint="aaa"),
                               self._d(prompt_fingerprint="bbb"))
        self.assertTrue(any("prompt_fingerprint" in d for d in diffs))

    def test_decision_excludes_generated_text(self):
        """ADR 0004: LLM output must never be a comparison field."""
        fields = replay.Decision(route="client", role="CLIENT").to_dict()
        for banned in ("reply", "text", "reply_text", "output"):
            self.assertNotIn(banned, fields)


class TestAIStub(unittest.TestCase):
    def test_stub_returns_sentinel_and_makes_no_call(self):
        stub = replay.stub_ai_reply()
        self.assertEqual(stub([{"role": "user", "content": "hi"}]),
                         "<REPLAY_STUBBED_AI>")
        self.assertEqual(stub(), "<REPLAY_STUBBED_AI>")


class TestNoSideEffectSurface(unittest.TestCase):
    def test_replay_module_cannot_perform_io(self):
        """Structural guarantee: this module has no way to send or write."""
        src = open(replay.__file__).read()
        for forbidden in ("requests", "import webhook", "from webhook",
                          "supabase", "send_text("):
            self.assertNotIn(forbidden, src,
                             f"replay module must not be able to perform I/O: {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
