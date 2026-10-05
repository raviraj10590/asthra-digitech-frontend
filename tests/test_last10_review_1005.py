"""Last-10 review, 2026-10-05 — each test is a real message that went wrong.

Replayed against the code that was live (99bcb8c) before writing a fix; only
what still failed there is covered. The owner's three complaints:
  * the CRM did not pick up a new WhatsApp lead (...3980, an ad referral whose
    text carried no transformer word);
  * "some lines show a star mark between words" (*ಉದ್ದೇಶ*ಕ್ಕೆ, 48 sends in
    a week);
  * the last ten conversations, read for anything the bot misunderstood.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                             # noqa: E402
import webhook as w                                             # noqa: E402
from conversation import Conversation                           # noqa: E402

D = (b.AWAITING_DELIVERY,)
P = (b.AWAITING_PURPOSE,)


def read(text, awaiting=(), known=None):
    return b.parse_followup(text, awaiting, known=known or {})


class AnAdThatSaysWhatTheMessageDoesNot(unittest.TestCase):
    """...3980: 'Hello! I filled out your form…' with no form fields, from the
    ad 'Bairavi Transformers — ಉಚಿತ ಕೊಟೇಶನ್'. Routed as Asthra; no lead."""

    INTRO = "Hello! I filled out your form and would like to know more about your business."
    AD = {"source_type": "ad", "headline": "Bairavi Transformers — ಉಚಿತ ಕೊಟೇಶನ್",
          "body": "⚡ Bairavi Trans Solutions, ದಕ್ಷಿಣ ಕನ್ನಡ ಜಿಲ್ಲೆ, ಕಡಬ"}

    def test_the_ad_makes_it_a_transformer_enquiry(self):
        self.assertFalse(b.looks_like_transformer_enquiry(self.INTRO))
        text = b.with_ad_context(self.INTRO, self.AD)
        self.assertTrue(b.looks_like_transformer_enquiry(text))
        self.assertTrue(text.endswith("[Ad: Bairavi Transformers — ಉಚಿತ ಕೊಟೇಶನ್]"))

    def test_the_conversation_gets_the_bairavi_opening_not_the_menu(self):
        t = Conversation().send(b.with_ad_context(self.INTRO, self.AD))
        self.assertFalse(t["menu"])
        self.assertIn("Bairavi", t.reply)

    def test_untouched_when_the_text_already_says_it_or_the_ad_is_not_bairavi(self):
        form = self.INTRO + "\nCapacity: 63 kVA transformer"
        self.assertEqual(b.with_ad_context(form, self.AD), form)
        self.assertEqual(b.with_ad_context("Hi", {"headline": "Websites that sell"}), "Hi")
        self.assertEqual(b.with_ad_context("Hi", None), "Hi")


class StarsWhatsAppWillRender(unittest.TestCase):
    def test_a_glued_case_ending_moves_inside(self):
        self.assertEqual(b.whatsapp_format("ಯಾವ *ಉದ್ದೇಶ*ಕ್ಕೆ ಬೇಕು?"), "ಯಾವ *ಉದ್ದೇಶಕ್ಕೆ* ಬೇಕು?")

    def test_separate_spans_stay_separate(self):
        s = "Transformer *ಡೆಲಿವರಿ* ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು? *63 kVA*."
        self.assertEqual(b.whatsapp_format(s), s)

    def test_model_markdown(self):
        self.assertEqual(b.whatsapp_format("ನಾವು **Asthra DigiTech**\n## Plans\n* one"),
                         "ನಾವು *Asthra DigiTech*\nPlans\n* one")

    def test_the_two_composed_lines_are_fixed_at_source(self):
        self.assertNotIn("*ಉದ್ದೇಶ*ಕ್ಕೆ", b.question_for("purpose", {}))
        for line in (b.question_for("purpose", {}), b.question_for("delivery", {})):
            self.assertEqual(b.whatsapp_format(line), line)

    def test_send_text_formats_every_message(self):
        sent = {}
        with mock.patch.object(w, "_wa_post", lambda p: sent.update(p) or None), \
             mock.patch.object(w, "get_role", lambda to: ("CLIENT", None)), \
             mock.patch.object(w, "log_reply_to_crm", lambda *a, **k: None), \
             redirect_stdout(io.StringIO()):
            w.send_text("919000000000", "ಯಾವ *ಉದ್ದೇಶ*ಕ್ಕೆ ಬೇಕು?")
        self.assertEqual(sent["text"]["body"], "ಯಾವ *ಉದ್ದೇಶಕ್ಕೆ* ಬೇಕು?")


class ThisSamePlaceIsNotAPlace(unittest.TestCase):
    def test_the_real_answer(self):
        """...3294: stored as the delivery place, then the CRM city."""
        f = read("ಇಲ್ಲ ಇದೇ ಸ್ಥಳವಿದೇ", D, {"location": "Kotyal", "capacity_kva": 63})
        self.assertIsNone(f["delivery_location"])
        self.assertTrue(f["delivery_same"])

    def test_variants(self):
        for t in ("ಇದೇ ಸ್ಥಳ", "ಅದೇ ಊರು", "same place", "ide uru"):
            with self.subTest(t=t):
                f = read(t, D, {"location": "Kotyal"})
                self.assertIsNone(f["delivery_location"])
                self.assertTrue(f["delivery_same"])


class AnAddressInTwoMessages(unittest.TestCase):
    """...2096: 'ಊರು. ಬೀಸನಕೊಪ್ಪಾ' then 'ತಾಲೂಕ. ಮೂಡಲಗಿ'."""

    def test_the_village_label_is_not_part_of_the_name(self):
        self.assertEqual(read("ಊರು. ಬೀಸನಕೊಪ್ಪಾ", D)["delivery_location"], "ಬೀಸನಕೊಪ್ಪಾ")

    def test_a_place_called_uru_is_still_read(self):
        for t in ("ಊರು", "Ura"):
            self.assertEqual(read(t, D)["delivery_location"], t)

    def test_the_taluk_is_added_to_the_village(self):
        f = read("ತಾಲೂಕ. ಮೂಡಲಗಿ", P, {"location": "ಬೀಸನಕೊಪ್ಪಾ"})
        self.assertEqual(f["delivery_location"], "ಬೀಸನಕೊಪ್ಪಾ, ತಾಲೂಕ. ಮೂಡಲಗಿ")
        f = read("taluk mudalagi", P, {"location": "Beesanakoppa"})
        self.assertEqual(f["delivery_location"], "Beesanakoppa, taluk mudalagi")

    def test_not_appended_twice(self):
        f = read("Tq Tikota", P, {"location": "Kotyal, Tq Tikota"})
        self.assertNotIn("Tq Tikota, Tq Tikota", f["delivery_location"] or "")


class TwoSizesAreNotACount(unittest.TestCase):
    K = {"capacity_kva": 63, "location": "Kotyal", "name": "Shivachandramulage"}

    def test_exchange_and_cost(self):
        """'take back my 25, give a 63 — what will it cost?' was '25 units'."""
        f = read("25 ತೆಗೆದುಕೊಂಡು 63 ಕೊಡಲೂ ಯಷ್ಟು ಖರ್ಚಾಗಬಹುದು", (), self.K)
        self.assertIsNone(f["quantity"])
        self.assertTrue(f["asked_price"])
        self.assertEqual(f["customer_question"], b.QUESTION_SIZE_CHANGE)
        reply = b.compose_followup_reply(f, self.K, None, None)
        self.assertIn("₹2,00,000", reply)                  # the 63 kVA price
        self.assertIn("engineer", reply)                   # exchange: a person, no promise
        self.assertNotIn("units", reply)

    def test_units_said_for_kva(self):
        f = read("25units sakagutill 63 units ಬೇಕಾಗಿದೆ", (), self.K)
        self.assertIsNone(f["quantity"])
        self.assertEqual(f["customer_question"], b.QUESTION_SIZE_CHANGE)

    def test_a_real_count_and_a_choice_are_unchanged(self):
        self.assertEqual(read("2 units", (), self.K)["quantity"], 2)
        f = read("25kva or 63kva agriculture purpose", (), {})
        self.assertIsNone(f["customer_question"])


class WhenIsNotYesOrNo(unittest.TestCase):
    K = {"capacity_kva": 63, "name": "Shivachandramulage", "callback": "now", "location": "Kotyal"}

    def test_when_is_answered_without_yes(self):
        for t in ("ಯಾವಾಗ", "Yastu ಗಂಟೆಗೆ", "Time", "Coll yavag madtare nimma enginiyar"):
            with self.subTest(t=t):
                f = read(t, (), self.K)
                reply = b.compose_followup_reply(f, self.K, None, None)
                self.assertFalse(reply.startswith("ಹೌದು"), reply)
                self.assertIn("*ಈಗಲೇ*", reply)
                self.assertIn("ಮತ್ತೊಮ್ಮೆ ತಿಳಿಸಿದ್ದೇವೆ", reply)

    def test_will_you_call_now_still_gets_yes(self):
        f = read("Ivag cl madtiya", (), self.K)
        self.assertTrue(b.compose_followup_reply(f, self.K, None, None).startswith("ಹೌದು"))


class WhyAreYouAsking(unittest.TestCase):
    def test_why_gets_the_reason_then_the_question(self):
        """...0033: 'Yake sir' got the same question again."""
        k = {"location": "nadi sinur", "capacity_kva": 63, "last_asked": "delivery"}
        f = read("Yake sir", D, k)
        self.assertEqual(f["customer_question"], b.QUESTION_WHY)
        reply = b.compose_followup_reply(f, k, None, None)
        self.assertTrue(reply.startswith("ಡೆಲಿವರಿ ಸ್ಥಳ ತಿಳಿದರೆ"), reply)
        self.assertIn("nadi sinur", reply)

    def test_a_long_message_with_why_is_not_this(self):
        f = read("why is the 63 kva so costly compared to others", (), {})
        self.assertNotEqual(f["customer_question"], b.QUESTION_WHY)


if __name__ == "__main__":
    unittest.main()
