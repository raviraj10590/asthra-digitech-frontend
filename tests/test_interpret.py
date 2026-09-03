"""Stage ③ INTERPRET — deterministic interpretation, no model.

The sharpest tests here are the NEGATIVE ones: a word appearing in a message
is not the same as a customer asking for that service. "install Instagram"
and "I don't need social media" both contain a marker and neither is an
enquiry. Admitting them would put a turn through a goal whose evidence bar
was chosen for a different question.

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

from bic import decide                                          # noqa: E402
from bic import goals                                           # noqa: E402
from bic import interpret as I                                  # noqa: E402

MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "interpret.py")


def code_only(path) -> str:
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


class Base(unittest.TestCase):

    def assertClear(self, text):
        r = I.interpret(text)
        self.assertEqual(r["interpretation_state"], I.CLEAR, f"{text!r} -> {r}")
        return r

    def assertNotAdmitted(self, text):
        r = I.interpret(text)
        self.assertNotEqual(r["interpretation_state"], I.CLEAR, f"{text!r} -> {r}")
        self.assertIsNone(r["goal_candidate"])
        self.assertIsNone(decide.admit_goal(text))
        return r


# ── 1-7 · genuine intent is recognised ──────────────────────────────────

class GenuineIntent(Base):

    def test_clear_social_media_request(self):
        r = self.assertClear("Do you provide social media?")
        self.assertEqual(r["intent"], "social_media_enquiry")
        self.assertEqual(r["goal_candidate"], "social_media_enquiry")

    def test_instagram(self):
        self.assertClear("I need instagram marketing")

    def test_facebook(self):
        self.assertClear("facebook page please")

    def test_youtube(self):
        self.assertClear("youtube channel management")

    def test_linkedin(self):
        self.assertClear("linkedin help")

    def test_social_media_phrase(self):
        self.assertClear("social media")

    def test_kannada_intent(self):
        self.assertClear("ಸೋಶಿಯಲ್ ಮೀಡಿಯಾ ಬೇಕು")
        self.assertClear("ಇನ್ಸ್ಟಾಗ್ರಾಂ ನಿರ್ವಹಣೆ")

    def test_mixed_kannada_english(self):
        self.assertClear("ನನಗೆ instagram ನಿರ್ವಹಣೆ ಬೇಕು")


# ── 8-11 · substring false positives ────────────────────────────────────

class FalsePositives(Base):

    def test_install_installation_instant_instantly(self):
        for text in ("install", "installation", "instant", "instantly",
                     "please install the app", "I need it instantly",
                     "constant contact"):
            with self.subTest(text=text):
                self.assertNotAdmitted(text)

    def test_incidental_app_support_is_not_a_service_enquiry(self):
        """'install Instagram' is a phone-support question."""
        for text in ("install Instagram", "Instagram app install",
                     "how to download instagram", "my instagram was hacked",
                     "forgot my facebook password"):
            with self.subTest(text=text):
                r = self.assertNotAdmitted(text)
                self.assertEqual(r["ambiguity"], I.INCIDENTAL)


# ── 12 · ambiguity ──────────────────────────────────────────────────────

class Ambiguity(Base):

    def test_multi_intent_is_ambiguous(self):
        for text in ("I want a website and instagram",
                     "instagram and election campaign",
                     "logo design and social media"):
            with self.subTest(text=text):
                r = self.assertNotAdmitted(text)
                self.assertEqual(r["ambiguity"], I.MULTI_INTENT)

    def test_negation_is_not_an_enquiry(self):
        for text in ("I don't need social media", "no need for instagram",
                     "not interested in facebook", "we already have instagram"):
            with self.subTest(text=text):
                r = self.assertNotAdmitted(text)
                self.assertEqual(r["ambiguity"], I.NEGATED)

    def test_ambiguity_kind_is_from_the_bounded_set(self):
        for text in ("I want a website and instagram", "install instagram",
                     "I don't need instagram"):
            with self.subTest(text=text):
                kind = I.interpret(text)["ambiguity"]
                self.assertIn(kind, I.AMBIGUITY_KINDS)


# ── 13 · unsupported ────────────────────────────────────────────────────

class Unsupported(Base):

    def test_unrelated_requests(self):
        for text in ("what are your prices?", "hello", "", "   ", None,
                     "I need a website", "transformer quotation 500 kva"):
            with self.subTest(text=text):
                r = I.interpret(text)
                self.assertEqual(r["interpretation_state"], I.UNSUPPORTED)
                self.assertIsNone(decide.admit_goal(text))

    def test_high_risk_goals_remain_unreachable_from_text(self):
        for text in ("transformer quotation 500kva urgent",
                     "real estate plot budget 50 lakh"):
            with self.subTest(text=text):
                self.assertIsNone(decide.admit_goal(text))


# ── 14-16 · slots ───────────────────────────────────────────────────────

class Slots(Base):

    def test_slot_names_come_only_from_the_registered_goal(self):
        r = self.assertClear("instagram please")
        registered = {s["name"] for s in
                      goals.lookup("social_media_enquiry")["required_slots"]}
        self.assertEqual(set(r["slots"]), registered)

    def test_service_interest_is_observed_from_the_message(self):
        r = self.assertClear("instagram please")
        self.assertTrue(r["slots"]["service_interest"]["observed"])

    def test_first_contact_is_unknowable_from_text_and_marked_missing(self):
        """A retrieval fact about OUR records. Never guessed."""
        r = self.assertClear("instagram please")
        self.assertFalse(r["slots"]["first_contact"]["observed"])

    def test_observed_slots_are_never_marked_verified(self):
        """Interpretation is not evidence — 2H fills slots from records."""
        r = self.assertClear("instagram please")
        for slot in r["slots"].values():
            self.assertFalse(slot["verified"])

    def test_no_slot_value_is_invented(self):
        r = self.assertClear("instagram please")
        self.assertNotIn("value", r["slots"]["first_contact"])

    def test_unsupported_input_yields_no_slots(self):
        self.assertEqual(I.interpret("hello")["slots"], {})


# ── 17-18 · determinism ─────────────────────────────────────────────────

class Determinism(Base):

    def test_repeated_input_gives_an_identical_interpretation(self):
        for text in ("instagram marketing", "install instagram", "hello"):
            with self.subTest(text=text):
                results = [I.interpret(text) for _ in range(5)]
                self.assertEqual(results, [results[0]] * 5)

    def test_case_and_punctuation_do_not_change_admission(self):
        for text in ("INSTAGRAM!!!", "instagram???", "  Instagram  ",
                     "SOCIAL MEDIA"):
            with self.subTest(text=text):
                self.assertClear(text)

    def test_whitespace_variants_interpret_identically(self):
        base = I.interpret("social media")["interpretation_state"]
        for text in ("social  media", "social\nmedia", " social media "):
            with self.subTest(text=text):
                self.assertEqual(I.interpret(text)["interpretation_state"], base)


# ── 19-21 · boundaries ──────────────────────────────────────────────────

class Boundaries(Base):

    def test_no_model_or_provider_in_interpret(self):
        code = code_only(MODULE).lower()
        for banned in ("openai", "gemini", "deepseek", "llm", "completion",
                       "generate_reply", "classify", "embed", "requests"):
            self.assertNotIn(banned, code)

    def test_no_storage_or_network_access(self):
        code = code_only(MODULE)
        for banned in ("insert(", "select(", "db.", "http", "urllib"):
            self.assertNotIn(banned, code)

    def test_no_pii_vocabulary(self):
        code = code_only(MODULE).lower()
        for banned in ("phone", "email", "wamid", "source_ref", "sender",
                       "message_body", "tenant"):
            self.assertNotIn(banned, code)

    def test_interpretation_carries_no_pii_and_no_raw_message(self):
        blob = repr(I.interpret("my number is 919999000444, want instagram"))
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertNotIn("my number is", blob)

    def test_evidence_is_bounded_vocabulary_not_echoed_text(self):
        r = self.assertClear("please help with instagram growth")
        for marker in r["evidence"]:
            self.assertIn(marker, I._SOCIAL_MARKERS)

    def test_confidence_is_capped_at_tier_five(self):
        """2C / Article II.6 — a customer self-declaration is worth 0.50."""
        self.assertEqual(I.CONFIDENCE_CAP, 0.50)
        for text in ("instagram", "social media", "hello", "install instagram"):
            with self.subTest(text=text):
                self.assertLessEqual(I.interpret(text)["confidence"], 0.50)

    def test_only_the_registered_goal_can_ever_be_proposed(self):
        self.assertEqual(I.GOAL_SOCIAL, "social_media_enquiry")
        self.assertIsNotNone(goals.lookup(I.GOAL_SOCIAL))


# ── goal-registry integration ───────────────────────────────────────────

class GoalIntegration(Base):

    def test_admission_delegates_to_the_goal_registry(self):
        g = decide.admit_goal("instagram please")
        self.assertIs(g, goals.lookup("social_media_enquiry"))

    def test_decide_does_not_redefine_goal_data(self):
        code = code_only(os.path.join(os.path.dirname(__file__), "..",
                                      "bic", "decide.py"))
        self.assertNotIn("required_slots", code)

    def test_only_clear_interpretations_admit(self):
        for text in ("I want a website and instagram", "install instagram",
                     "I don't need instagram", "hello"):
            with self.subTest(text=text):
                self.assertIsNone(decide.admit_goal(text))
        self.assertIsNotNone(decide.admit_goal("instagram"))
