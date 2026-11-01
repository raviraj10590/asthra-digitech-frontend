"""Bairavi follow-ups from the 2026-10-29 review of the last 20 chats.

Each case is a live message, verbatim:

- "Hu sari" (yes, OK) answering "is <place> right?" was stored as the
  delivery place (...5094, 2026-10-29).
- "Ritaru karidisabahuda" (can farmers buy it?) answering the same question
  was stored as the delivery place, and the question was never answered
  (...2302, 2026-10-27).
- "ಭದ್ರಾವತಿ ತಾಲೂಕಿನ ಅನವೇರಿ ಗ್ರಾಮ ತೋಟ ಕೆ ಬೇಕು" (Anaveri village, Bhadravati
  taluk — for the farm) read the purpose and dropped the address, so the
  next reply asked where to deliver (...7215, 2026-10-28).
- "10" answering "what time today?" was a call time on record, and the model
  replaced its confirmation with a MESCOM paragraph (...2302, 2026-10-27).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)


class YesIsNotAPlace(unittest.TestCase):
    def test_hu_sari_confirms_the_form_place(self):
        r = b.parse_followup("Hu sari", DELIVERY, {"location": "Shivamogga district"})
        self.assertIsNone(r["delivery_location"])
        self.assertTrue(r["delivery_same"])

    def test_the_other_spellings(self):
        for t in ("Hu", "Huu", "Hu sari", "ಹೂ", "ಹೂಂ ಸರಿ", "Hum ok"):
            with self.subTest(t=t):
                r = b.parse_followup(t, DELIVERY, {"location": "Kadur"})
                self.assertIsNone(r["delivery_location"])


class AQuestionIsNotAPlace(unittest.TestCase):
    def test_can_farmers_buy(self):
        r = b.parse_followup("Ritaru karidisabahuda", DELIVERY, {"location": "Shikaripura"})
        self.assertIsNone(r["delivery_location"])

    def test_bahuda_in_kannada_letters(self):
        r = b.parse_followup("ರೈತರು ಖರೀದಿಸಬಹುದಾ", DELIVERY, {"location": "Shikaripura"})
        self.assertIsNone(r["delivery_location"])

    def test_a_bahu_place_is_still_a_place(self):
        # A village name that merely contains the letters must still read.
        r = b.parse_followup("Bahudapura", DELIVERY, {})
        self.assertEqual(r["delivery_location"], "Bahudapura")


class TheAddressBeforeThePurpose(unittest.TestCase):
    def test_live_message(self):
        r = b.parse_followup("ಭದ್ರಾವತಿ ತಾಲೂಕಿನ ಅನವೇರಿ ಗ್ರಾಮ ತೋಟ ಕೆ ಬೇಕು", DELIVERY, {})
        self.assertEqual(r["delivery_location"], "ಭದ್ರಾವತಿ ತಾಲೂಕಿನ ಅನವೇರಿ ಗ್ರಾಮ")
        self.assertEqual(r["application"], "AGRICULTURE")


class AChosenCallTimeIsConfirmedNotParaphrased(unittest.TestCase):
    def test_no_model_for_a_call_time(self):
        r = b.parse_followup("10", (b.AWAITING_CALL_TIME,), {"capacity_kva": 63})
        self.assertEqual(r["call_time"]["hour"], 10)
        self.assertFalse(b.should_ask_model(r, {"capacity_kva": 63}))


if __name__ == "__main__":
    unittest.main()
