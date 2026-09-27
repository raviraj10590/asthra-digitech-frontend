"""Last-10 CRM review, 2026-09-26. Four live misreadings, from real messages.

  "Yavaga barate"  (when will it come?)   -> answered with the PRICE: "rate" in "barate"
  "ರೇಟ್"           (rate, Kannada script)  -> not a price question; the model said it could not say
  "೩"              (3, Kannada digit)      -> offered call-back 1/2/3, recorded as 3 UNITS
  place typed below the form's last answer -> lost; the bot asked "which place?"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

K = {"location": "Sira", "capacity_kva": 25, "application": "AGRICULTURE",
     "delivery_same": True}


def read(text, awaiting=(), known=K):
    return b.parse_followup(text, awaiting, known=known)


class PriceWordsAreWholeWords(unittest.TestCase):
    def test_barate_is_not_a_price_question(self):
        f = read("Yavaga barate")
        self.assertFalse(f["asked_price"])
        self.assertIsNone(f["commercial_intent"])
        self.assertNotIn("₹", b.compose_followup_reply(f, K))

    def test_other_words_containing_price_words(self):
        for t in ("barate", "karate", "accurate", "separate", "pricey", "costume"):
            self.assertFalse(read(t)["asked_price"], t)

    def test_real_price_questions_still_count(self):
        for t in ("rate?", "Rate", "rates eshtu", "25 kva rate enu", "price list", "price?",
                  "prices", "cost", "how much", "amount", "kitna", "rate-list", "ದರ ಎಷ್ಟು"):
            self.assertTrue(read(t)["asked_price"], t)

    def test_quotation_words_too(self):
        for t in ("quotation beku", "quote", "quotes please", "ಕೋಟೇಶನ್"):
            self.assertEqual(read(t)["commercial_intent"], b.QUOTATION_REQUEST, t)

    def test_a_place_containing_rate_is_no_longer_rejected(self):
        """Side effect, and a correct one: the place filter used the same
        substring test, so "Karate club road" could not be an address."""
        self.assertEqual(read("Karate club road", (b.AWAITING_DELIVERY,))["delivery_location"],
                         "Karate club road")


class RateInKannadaLetters(unittest.TestCase):
    def test_is_a_price_question_answered_with_the_price(self):
        for t in ("ರೇಟ್", "ರೇಟ್ ಎಷ್ಟು", "ರೇಟು", "ಪ್ರೈಸ್"):
            f = read(t)
            self.assertTrue(f["asked_price"], t)
            self.assertEqual(f["commercial_intent"], b.PRICE_REQUEST, t)
            self.assertFalse(b.should_ask_model(f, K), t)          # not the model
            self.assertIn("₹95,000 + GST", b.compose_followup_reply(f, K), t)


class KannadaDigitsInTheCallBackChoice(unittest.TestCase):
    def test_kannada_digits_are_the_choice(self):
        for t, slot in (("೧", "now"), ("೨", "evening"), ("೩", "tomorrow")):
            f = read(t, (b.AWAITING_CALLBACK,))
            self.assertEqual(f["callback"], slot, t)
            self.assertIsNone(f["quantity"], t)

    def test_still_a_quantity_when_asked_how_many(self):
        self.assertEqual(read("೩", (b.AWAITING_QUANTITY,), {})["quantity"], 3)

    def test_the_real_sequence(self):
        """Offered 1/2/3, the customer typed "೩": call tomorrow, no quantity."""
        history = [{"role": "assistant", "content": b.flow_marker((b.AWAITING_CALLBACK,))},
                   {"role": "user", "content": "೩"}]
        state = b.established_from_history(history)
        self.assertEqual(state["callback"], "tomorrow")
        self.assertIsNone(state["quantity"])


FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {loc}\n"
        "Full name: Test Person\nPhone number: +910000000000\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: E. ಮಾಹಿತಿ ಮತ್ತು ದರಪಟ್ಟಿಗಾಗಿ\n{tail}")


class APlaceWrittenBelowTheForm(unittest.TestCase):
    def test_the_real_form(self):
        p = b.parse(FORM.format(loc="", tail="ಮುದಿಗೆರೆ ಅಜ್ಜಂಪ"))
        self.assertEqual(p["location"], "ಮುದಿಗೆರೆ ಅಜ್ಜಂಪ")
        reply = b.compose_reply(p)
        self.assertIn("ಡೆಲಿವರಿ ಸ್ಥಳ: *ಮುದಿಗೆರೆ ಅಜ್ಜಂಪ* — ಇದು ಸರಿಯೇ?", reply)          # confirm, not "which place?"

    def test_non_places_below_the_form_are_ignored(self):
        for tail in ("", "thanks", "please call me", "ತಕ್ಷಣ", "ok"):
            self.assertIsNone(b.parse(FORM.format(loc="", tail=tail))["location"], tail)

    def test_the_forms_own_answer_wins(self):
        self.assertEqual(b.parse(FORM.format(loc="Sira", tail="ಮುದಿಗೆರೆ"))["location"], "Sira")

    def test_the_greeting_line_is_never_a_place(self):
        self.assertIsNone(b.parse(FORM.format(loc="", tail=""))["location"])

    def test_only_forms(self):
        """A chat message is not a form; nothing changes for follow-ups."""
        self.assertIsNone(b.parse("hello\nಮುದಿಗೆರೆ ಅಜ್ಜಂಪ")["location"])


if __name__ == "__main__":
    unittest.main()
