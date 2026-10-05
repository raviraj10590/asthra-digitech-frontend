"""The owner's own test chat, 2026-09-25 00:35–00:39 ("answer is some not good").

  "Hii namaste"                   -> got the call-back close, not a hello
  "Nijanna"                       -> model reply in Latin-letter Kannada, "Neenu"
  "Ayitu delivery Yavaga kodtira" -> the question ignored, purpose asked instead
  "Krushi" / "Krusshi"            -> not read; purpose asked twice more
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

K = {"location": "Sira", "capacity_kva": 25, "name": "RAVI", "delivery_same": True}


def reply(text, awaiting=(), known=K):
    f = b.parse_followup(text, awaiting, known=known)
    return f, b.compose_followup_reply(f, known)


class Greetings(unittest.TestCase):
    def test_a_greeting_is_greeted_with_the_open_question(self):
        f, r = reply("Hii namaste", (b.AWAITING_PURPOSE,))
        self.assertTrue(r.startswith("ನಮಸ್ಕಾರ Ravi ಅವರೇ"), r)
        self.assertIn("*ಉದ್ದೇಶಕ್ಕೆ* ಬೇಕು?", r)
        self.assertNotIn(b.CALLBACK_QUESTION, r)

    def test_nothing_open_offers_help(self):
        known = {**K, "application": "AGRICULTURE", "callback": "now"}
        _, r = reply("hi sir", (), known)
        self.assertIn("ಹೇಗೆ ಸಹಾಯ", r)

    def test_a_greeting_is_never_silent_and_never_the_model(self):
        f, _ = reply("Hii namaste")
        self.assertFalse(b.is_silent_ack(f, ()))
        self.assertFalse(b.should_ask_model(f, K))

    def test_places_are_not_greetings(self):
        for t in ("Hirekerur", "Hiriyur", "sir"):
            self.assertFalse(b.parse_followup(t)["is_greeting"], t)


class DeliveryTime(unittest.TestCase):
    def test_answered_with_the_owners_ruling(self):
        f, r = reply("Ayitu delivery Yavaga kodtira", (b.AWAITING_PURPOSE,))
        self.assertEqual(f["customer_question"], b.QUESTION_DELIVERY_TIME)
        self.assertIn(b._DELIVERY_TIME_KN, r)
        self.assertFalse(b.should_ask_model(f, K))
        for banned in ("ದಿನ", "days", "week", "ವಾರ"):
            self.assertNotIn(banned, b._DELIVERY_TIME_KN)

    def test_other_ways_to_ask(self):
        for t in ("delivery yaavaga?", "ಡೆಲಿವರಿ ಯಾವಾಗ", "when will you deliver", "estu dina alli ready"):
            self.assertEqual(b.customer_question(t), b.QUESTION_DELIVERY_TIME, t)

    def test_when_to_call_is_not_a_delivery_question(self):
        self.assertNotEqual(b.customer_question("yavaga call madtira"), b.QUESTION_DELIVERY_TIME)


class KrushiInEnglishLetters(unittest.TestCase):
    def test_read_as_agriculture(self):
        for t in ("Krushi", "Krusshi", "krishi", "vyavasaya", "raitha"):
            self.assertEqual(b.parse_followup(t)["application"], "AGRICULTURE", t)

    def test_not_inside_other_words(self):
        self.assertIsNone(b.parse_followup("Krishnapura")["application"])


class TheModelSpeaksProfessionally(unittest.TestCase):
    def test_the_real_reply_is_refused(self):
        real = ("Namaste 🙏 25 kVA namme standard range nalli ide. Neenu urgent anta "
                "helidri, adakke engineer jothe point madidivi. Svalpa samaya kodi.")
        self.assertIsNotNone(b.reply_violates_evidence(real))

    def test_latin_kannada_is_refused_even_when_polite(self):
        self.assertEqual(b.reply_violates_evidence(
            "Namma engineer nimage khachitavagi tilisuttare, svalpa samaya kodi."),
            "Kannada in English letters")

    def test_a_proper_kannada_reply_passes(self):
        self.assertIsNone(b.reply_violates_evidence(
            "ನಮಸ್ಕಾರ 🙏 ಈ ವಿಷಯವನ್ನು ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ."))

    def test_an_english_reply_to_an_english_customer_passes(self):
        self.assertIsNone(b.reply_violates_evidence(
            "Thank you. Our engineer will confirm this for you on a call."))

    def test_the_brief_demands_script_and_respect(self):
        brief = b.model_brief_kn()
        self.assertIn("ಕನ್ನಡ ಲಿಪಿಯಲ್ಲೇ", brief)
        self.assertIn("'ನೀನು' ಎಂದಿಗೂ ಬೇಡ", brief)


if __name__ == "__main__":
    unittest.main()
