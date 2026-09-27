"""Review of lead ...3450, 2026-09-27 (the first on 6f0c1d4 in production).

  location field = the customer's own name  -> "deliver to <his name>?"
  "🙏🏻", "🙏"                                -> sent to the model
  "Ok 👍" answering "deliver to X?"          -> stored as the ADDRESS "Ok 👍"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {loc}\n"
        "Full name: ‌‌‌‌ shivakumar s ambi\nPhone number: +910000000000")
D = (b.AWAITING_DELIVERY,)


class TheNameIsNotAPlace(unittest.TestCase):
    def test_the_real_form(self):
        p = b.parse(FORM.format(loc="Shivakumar sadashiva ambi"))
        self.assertIsNone(p["location"])
        reply = b.compose_reply(p)
        self.assertIn("ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು", reply)             # asks, instead of confirming his name
        self.assertNotIn("sadashiva", reply.lower().split("ಸಂಪರ್ಕಿಸಿದ್ದಕ್ಕೆ")[1])

    def test_places_sharing_a_name_word_are_kept(self):
        for loc in ("Ambi nagar", "Shivakumar nagar", "Sira", "Shivakumar"):
            self.assertEqual(b.parse(FORM.format(loc=loc))["location"], loc, loc)

    def test_invisible_characters_do_not_hide_the_name(self):
        self.assertEqual(b._name_words("‌‌ shivakumar s ambi"), {"shivakumar", "ambi"})

    def test_rule(self):
        self.assertTrue(b._is_the_name("Ravi Kumar", "ravi kumar"))
        self.assertFalse(b._is_the_name("Ravi Nagar Hubli", "Ravi Kumar"))     # one shared word
        self.assertFalse(b._is_the_name("", "Ravi Kumar"))

    def test_an_invisible_character_inside_a_word_does_not_split_it(self):
        self.assertEqual(b._name_words("shiva‌kumar"), {"shivakumar"})
        self.assertTrue(b._is_the_name("Shivakumar sadashiva ambi", "shiva‌kumar s ambi"))


class EmojiAreNotWords(unittest.TestCase):
    K = {"location": "Sira", "capacity_kva": 25, "application": "AGRICULTURE", "callback": "now"}

    def test_emoji_only_is_an_acknowledgement(self):
        for t in ("🙏🏻", "🙏", "👌🏼", "👍👍", "🙏🙏"):
            f = b.parse_followup(t, (), known=self.K)
            self.assertTrue(f["is_ack"], t)
            self.assertFalse(b.should_ask_model(f, self.K), t)
            self.assertTrue(b.is_silent_ack(f, ()), t)

    def test_emoji_around_a_word_do_not_hide_it(self):
        self.assertTrue(b.parse_followup("Ok 👍", (), known=self.K)["is_ack"])

    def test_ok_with_emoji_to_same_place_is_yes_not_an_address(self):
        for t in ("Ok 👍", "kk 👍", "yes sir 🙏", "👍"):
            f = b.parse_followup(t, D, known={"location": "Sira"})
            self.assertIsNone(f["delivery_location"], t)
            self.assertTrue(f["delivery_same"], t)

    def test_real_answers_with_emoji_still_read(self):
        f = b.parse_followup("25 kva 🙏", (), known={})
        self.assertEqual(f["capacity_kva"], 25)
        self.assertFalse(f["is_ack"])
        self.assertEqual(b.parse_followup("Hirekerur", D, known={})["delivery_location"], "Hirekerur")

    def test_a_question_mark_alone_is_still_answered(self):
        f = b.parse_followup("?", (), known=self.K)
        self.assertFalse(b.is_silent_ack(f, ()))


class KannadaSurvivesTheEmojiCleanUp(unittest.TestCase):
    """Found by the existing suite: stripping non-\\w characters broke
    "ಸರಿ" (vowel signs and the virama are not \\w)."""

    def test_kannada_acknowledgements_with_and_without_emoji(self):
        for t in ("ಸರಿ", "ಆಯ್ತು", "ಸರಿ 🙏", "ಆಯ್ತು 👍", "ಹೌದು"):
            f = b.parse_followup(t, D, known={"location": "Sira"})
            self.assertTrue(f["is_ack"] or f["delivery_same"], t)
            self.assertIsNone(f["delivery_location"], t)


if __name__ == "__main__":
    unittest.main()
