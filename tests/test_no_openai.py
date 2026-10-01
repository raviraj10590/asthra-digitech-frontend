"""OpenAI is out of every live path (owner, 2026-10-01: "remove open ai from
system because we not recharge this api presently")."""
import ast
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import webhook as w  # noqa: E402

DORMANT = {"get_openai", "_call_openai"}      # definitions kept, never called


class NoLivePathCallsOpenAI(unittest.TestCase):
    def test_a_stale_openai_setting_cannot_break_the_chain(self):
        from unittest import mock
        with mock.patch.object(w, "AI_PROVIDER_ORDER", ""), \
             mock.patch.object(w, "AI_PROVIDER_PRIMARY", "openai"), \
             mock.patch.object(w, "AI_PROVIDERS_ALLOWED", {"openai", "deepseek", "gemini"}):
            self.assertEqual([n for n, _ in w._provider_chain()][0], "deepseek")
        with mock.patch.object(w, "AI_PROVIDER_ORDER", "openai,deepseek"), \
             mock.patch.object(w, "AI_PROVIDERS_ALLOWED", {"openai", "deepseek"}):
            self.assertEqual([n for n, _ in w._provider_chain()], ["deepseek"])

    def test_not_a_provider(self):
        self.assertNotIn("openai", w._PROVIDERS)
        self.assertEqual([n for n, _ in w._provider_chain()], ["deepseek"])

    def test_nothing_calls_the_dormant_functions(self):
        for path in ("api/webhook.py", "api/digest.py", "api/evaluate.py", "api/nudge.py",
                     "api/lead.py", "bairavi.py", "interpretation.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            tree = ast.parse(src)
            inside_dormant = set()
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and fn.name in DORMANT:
                    inside_dormant |= {id(n) for n in ast.walk(fn)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and id(node) not in inside_dormant:
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    self.assertNotIn(name, DORMANT, f"{path}: calls {name}()")

    def test_no_openai_model_or_key_in_live_calls(self):
        src = open(os.path.join(ROOT, "api", "webhook.py"), encoding="utf-8").read()
        self.assertNotIn('model="gpt-4o-mini"', src)
        self.assertNotIn("whisper-1", src)
        self.assertNotIn("audio.speech.create", src)
        ev = open(os.path.join(ROOT, "api", "evaluate.py"), encoding="utf-8").read()
        self.assertNotIn("OPENAI_API_KEY", ev)


if __name__ == "__main__":
    unittest.main()
