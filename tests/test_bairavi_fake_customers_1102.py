"""Bairavi follow-ups from the 2026-11-02 fake-customer test.

A free model (OrcaRouter tencent/hy3-free) wrote two batches of 250 messy customer replies for
four points of a lead's conversation; 51 and then 29 were handled wrongly. Each message
below is verbatim from that batch (~/Projects/Tools/brain-stress/nara_msgs_1102a.json, _1102b.json).

- A question or a refusal answering "where to deliver?" was stored as the
  delivery place: "subsidy ideya sir", "ಎಮ್ಐ ಮಾಡ್ತೀರಾ", "transformer bekagilla".
- A yes around the form's place kept the yes: "ok kadur ge", "yes kadur".
- Misspelt price asks got no price: "raet kudivo", "prise tell me", "beli yenu".
- A clock time with "kke"/"ge" at the 1/2/3 question was read as units:
  "evning 6 kke call" -> 6 units, menu again.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
PURPOSE = (b.AWAITING_PURPOSE,)
CALLBACK = (b.AWAITING_CALLBACK,)
KNOWN = {"location": "Kadur", "capacity_kva": 25}


class AQuestionOrARefusalIsNotAPlace(unittest.TestCase):
    def test_questions(self):
        for t in ("subsidy ideya sir", "ಸಬ್ಸಿಡಿ ಕೊಡ್ತೀರಾ", "ಎಮ್ಐ ಮಾಡ್ತೀರಾ", "warrenty years hegidhe",
                  "mescom la sanction agtha", "fitting charga separate aa", "guarnty motor ge",
                  "mescom liaison idya", "subdy direct accnt ge"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"])

    def test_refusals(self):
        for t in ("ಇಲ್ಲ ಈಗ ಬೇಕಿಲ್ಲ", "transformer bekagilla", "already use madthidini transformer",
                  "keli bidi later", "second hand dalli kotta", "no delivery needed",
                  "already installed maadi", "kadur alli nan transformer idhe",
                  # second batch
                  "beda sadhu", "dasara taruvaya matadthini", "kadur ge bardilla eega",
                  "illeri bartini month end ge", "free fittin aidra"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"])

    def test_not_needed_is_a_decline(self):
        for t in ("transformer bekagilla", "ಇಲ್ಲ ಈಗ ಬೇಕಿಲ್ಲ", "already installed"):
            with self.subTest(t=t):
                self.assertTrue(b.is_decline(t))

    def test_real_places_still_read(self):
        for t in ("Emmiganur", "Hosanagara", "Anna Nagar", "Illkal"):
            with self.subTest(t=t):
                self.assertEqual(b.parse_followup(t, DELIVERY, {})["delivery_location"], t)


class AYesAroundThePlace(unittest.TestCase):
    def test_the_yes_and_the_ending_go(self):
        for t in ("ok kadur ge", "yes kadur", "ok aythu kadur ge", "deliver madthini kadur",
                  "kadur bidu", "deliver to kadur only", "ok ok kadur ge", "ok kadur ge thagi",
                  "hau kadur ge", "ಸರಿ ಕದೂರ್\u200cಗೆ ಬಿಡಿ".replace("ಕದೂರ್\u200cಗೆ ಬಿಡಿ", "kadur ge bidi")):
            with self.subTest(t=t):
                self.assertEqual(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"].lower(), "kadur")

    def test_the_joined_kannada_ending_goes(self):
        r = b.parse_followup("ಸರಿ ಕದೂರ್\u200cಗೆ ಬಿಡಿ", DELIVERY, KNOWN)
        self.assertEqual(r["delivery_location"], "ಕದೂರ್")

    def test_pointing_at_the_form(self):
        for t in ("ok deliver there", "ok form address alli", "yes ade town", "sari adey place",
                  "delivr thre pls", "yeah go ahead", "fine send it"):
            with self.subTest(t=t):
                r = b.parse_followup(t, DELIVERY, KNOWN)
                self.assertIsNone(r["delivery_location"])
                self.assertTrue(r["delivery_same"])


class MisspeltPriceAsks(unittest.TestCase):
    def test_price(self):
        for t in ("raet kudivo", "prise tell me", "beli yenu", "yestu paisa kitti",
                  "transformer ಕಿಟ್ಟಿ ಯೆಸ್ಟು", "yestu rupayi", "hw much for 3 phase"):
            with self.subTest(t=t):
                self.assertTrue(b.parse_followup(t, PURPOSE, KNOWN)["asked_price"])


class AClockTimeWithAnEnding(unittest.TestCase):
    def test_read_as_a_time_not_units(self):
        for t, hour in (("evning 6 kke call", 18), ("aftrnoon 3 ge engineer call", 15),
                        ("belgil 8 ge", 9), ("ಮಾರ್ನಿಂಗ್ 7 kke call madi", 9), ("tomorow 11 kke", 11),
                        ("ratri 9 call mado", 20), ("11 baje engineer call madi", 11), ("ಮಧ್ಯಾನ್ಹ 3 baje", 15)):
            with self.subTest(t=t):
                r = b.parse_followup(t, CALLBACK, KNOWN)
                self.assertEqual(r["call_time"]["hour"], hour)
                self.assertIsNone(r["quantity"])

    def test_hour_word_spelt_yeradu(self):
        r = b.parse_followup("yeradu gante barli", (b.AWAITING_CALL_TIME,), KNOWN)
        self.assertEqual(r["call_time"]["hour"], 14)

    def test_a_bare_digit_is_still_the_menu(self):
        self.assertIsNone(b.parse_followup("2", CALLBACK, KNOWN)["call_time"])


if __name__ == "__main__":
    unittest.main()
