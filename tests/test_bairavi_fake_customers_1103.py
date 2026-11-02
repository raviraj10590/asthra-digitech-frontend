"""Bairavi follow-ups from the 2026-11-03 Groq fake-customer test.

Groq (openai/gpt-oss-120b) wrote 243 messy customer replies for four points of a lead's
conversation; 32 were handled wrongly on the live Brain (1fd4b12). Each message below is
verbatim from that batch (~/Projects/Tools/brain-stress/nara_msgs_1103_groq.json).

- An English clock time ("six pm", "ten am", "seven o'clock") at "what time shall we call?"
  was answered "the engineer will call you *now*".
- "ಸಾಯಂಕಾಲ 4 call maadi" at the 1/2/3 question was read as 4 units.
- A refusal or a postponement answering "where to deliver?" was stored as the place:
  "not interested, sorry" -> "sorry", "maybe later, after harvest" -> "after harvest".
- A request about the order was stored as the place: "stock availability confirm maadi".
- "kaasu yestu?", "ಅದಕ್ಕೆ ಎಷ್ಟು? again", "₹?? quick reply" got no price.
- "Kadur nalli", "Kadur thik aagide" kept the words after the place.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
PURPOSE = (b.AWAITING_PURPOSE,)
CALLBACK = (b.AWAITING_CALLBACK,)
CALL_TIME = (b.AWAITING_CALL_TIME,)
KNOWN = {"location": "Kadur", "capacity_kva": 25}


class EnglishClockTimes(unittest.TestCase):
    def test_hour_words_are_read(self):
        for t, hour in (("six pm", 18), ("ten am", 10), ("four pm", 16), ("nine pm", 20),
                        ("seven o'clock", 19), ("seven o'clock call maadi", 19), ("eleven gante call maadi", 11)):
            with self.subTest(t=t):
                got = b.parse_call_time(t)
                self.assertIsNotNone(got)
                self.assertEqual(got["hour"], hour)

    def test_at_the_menu_question_too(self):
        for t in ("seven o'clock call maadi", "eleven gante call maadi"):
            with self.subTest(t=t):
                out = b.parse_followup(t, CALLBACK, KNOWN)
                self.assertIsNotNone(out["call_time"])
                self.assertIsNone(out["quantity"])

    def test_number_words_without_a_clock_are_not_times(self):
        self.assertFalse(b.names_a_clock_time("one transformer beku"))
        self.assertFalse(b.names_a_clock_time("two units"))


class SaayankaalaIsEvening(unittest.TestCase):
    def test_not_four_units(self):
        out = b.parse_followup("ಸಾಯಂಕಾಲ 4 call maadi", CALLBACK, KNOWN)
        self.assertIsNone(out["quantity"])
        self.assertEqual(out["call_time"]["hour"], 16)


class ARefusalIsNotAPlace(unittest.TestCase):
    REFUSALS = ("not interested, sorry", "not now, busy", "no thanks, i have my own",
                "maybe later, after harvest", "later, need to see specs", "later, after monsoon")

    def test_no_place_and_a_decline(self):
        for t in self.REFUSALS:
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"])
                self.assertTrue(b.is_decline(t))

    def test_a_later_call_is_not_a_no(self):
        for t in ("not now, call in the evening", "not today, naale call maadi", "later call maadi"):
            with self.subTest(t=t):
                self.assertFalse(b.is_decline(t))

    def test_deliver_later_is_not_a_no(self):
        self.assertFalse(b.is_decline("deliver later next month"))


class ARequestIsNotAPlace(unittest.TestCase):
    def test_requests(self):
        for t in ("stock availability confirm maadi", "kinda shipping address confirm maadi",
                  "order quantity increase madbeku"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"])

    def test_real_places_still_read(self):
        for t in ("Emmiganur", "Hosanagara", "Illkal", "Doddaballapura"):
            with self.subTest(t=t):
                self.assertEqual(b.parse_followup(t, DELIVERY, {})["delivery_location"], t)


class PriceAsks(unittest.TestCase):
    def test_asked_price(self):
        for t in ("kaasu yestu?", "ಅದಕ್ಕೆ ಎಷ್ಟು? again", "₹?? quick reply", "₹?? ask", "idakke eshtu"):
            with self.subTest(t=t):
                self.assertTrue(b.parse_followup(t, PURPOSE, KNOWN)["asked_price"])


class ThePlaceWithoutTheWordsAfterIt(unittest.TestCase):
    def test_suffixes_go(self):
        for t in ("Kadur nalli", "Kadur thik aagide"):
            with self.subTest(t=t):
                out = b.parse_followup(t, DELIVERY, KNOWN)
                self.assertIn((out["delivery_location"] or "").lower(), ("kadur", ""))


if __name__ == "__main__":
    unittest.main()
