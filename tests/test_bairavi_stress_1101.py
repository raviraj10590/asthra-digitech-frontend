"""Bairavi follow-ups from the 2026-11-01 stress test (last 40 live chats + probes).

Live messages, verbatim, unless marked as a probe:

- "ಇದೆ ಸ್ಥಳ ಅಮೌಂಟ್ ಎಷ್ಟು" (same place — how much?) got no price and the
  place question again (...1191, 2026-10-30).
- "Formland" (farmland) answering "where?" was stored as the place, and the
  real address in the next message was ignored (...9663, 2026-10-31).
- "Gadag distic sir" / "Shivamogga only" were stored with the courtesy word.
- "ಒಂದು ಗಂಟೆಗೆ ಫೋನ್ ಮಾಡಿ ಸರ್" (call at one o'clock) answering the 1/2/3
  question re-asked the menu (...6541, 2026-10-31); "4 gantege call madi"
  (probe) was read as 4 units.
- Form place answers "Details required", "Bkbb", "ಹೊಲದಲ್ಲಿ" and the
  customer's own name were offered back as the delivery place.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402
from conversation import lead_form  # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
CALLBACK = (b.AWAITING_CALLBACK,)
KNOWN = {"location": "S Bidare Kadur taluk", "capacity_kva": 25}


class SamePlaceAndPrice(unittest.TestCase):
    def test_same_place_how_much(self):
        r = b.parse_followup("ಇದೆ ಸ್ಥಳ ಅಮೌಂಟ್ ಎಷ್ಟು", DELIVERY, KNOWN)
        self.assertTrue(r["asked_price"])
        self.assertTrue(r["delivery_same"])
        self.assertIsNone(r["delivery_location"])

    def test_ide_sthala_is_a_pointer(self):
        r = b.parse_followup("ಇದೆ ಸ್ಥಳ", DELIVERY, KNOWN)
        self.assertIsNone(r["delivery_location"])
        self.assertTrue(r["delivery_same"])

    def test_typed_yes(self):
        for t in ("Ys", "Yess", "Ya"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"])


class NotAPlace(unittest.TestCase):
    def test_farm_words(self):
        for t in ("Formland", "Farmland", "ಹೊಲದಲ್ಲಿ", "ತೋಟಕ್ಕೆ"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, DELIVERY, {})["delivery_location"])

    def test_courtesy_word_is_dropped(self):
        self.assertEqual(b.parse_followup("Gadag distic sir", DELIVERY, {})["delivery_location"],
                         "Gadag distic")
        self.assertEqual(b.parse_followup("Shivamogga only", DELIVERY, {})["delivery_location"],
                         "Shivamogga")

    def test_a_place_named_with_sir_inside_is_kept(self):
        self.assertEqual(b.parse_followup("Sirsi", DELIVERY, {})["delivery_location"], "Sirsi")


class TheFormsPlaceAnswer(unittest.TestCase):
    def check(self, loc, name, want):
        self.assertEqual(b.parse(lead_form(location=loc, name=name))["location"], want)

    def test_details_required(self):
        self.check("Details required", "Narendra Kshatriya", None)

    def test_keyboard_noise(self):
        self.check("Bkbb", "Parsrama Jangawad", None)

    def test_in_the_field(self):
        self.check("ಹೊಲದಲ್ಲಿ", "Halesh", None)

    def test_kannada_name_with_other_initials(self):
        self.check("ರವಿಕುಮಾರ್. ಜಿ. ಎಮ್", "ರವಿಕುಮಾರ್ ಜಿ. ಎಂ", None)

    def test_a_real_place_stays(self):
        self.check("Kadur", "Ravi Kumar", "Kadur")
        self.check("ಬೇಗೂರು", "Yoge Sha", "ಬೇಗೂರು")


class AClockTimeAtTheMenu(unittest.TestCase):
    def test_kannada_hour_word(self):
        r = b.parse_followup("ಒಂದು ಗಂಟೆಗೆ ಫೋನ್ ಮಾಡಿ ಸರ್", CALLBACK, KNOWN)
        self.assertEqual(r["call_time"]["hour"], 13)

    def test_a_figure_with_gante_is_a_time_not_units(self):
        r = b.parse_followup("4 gantege call madi", CALLBACK, KNOWN)
        self.assertEqual(r["call_time"]["hour"], 16)
        self.assertIsNone(r["quantity"])

    def test_part_of_day_and_figure(self):
        self.assertEqual(b.parse_followup("evening 5", CALLBACK, KNOWN)["call_time"]["hour"], 17)

    def test_a_bare_digit_is_still_the_menu(self):
        r = b.parse_followup("2", CALLBACK, KNOWN)
        self.assertIsNone(r["call_time"])

    def test_a_chosen_time_closes_the_menu(self):
        r = b.parse_followup("4 gantege call madi", CALLBACK, KNOWN)
        self.assertTrue(b.call_settled(r, KNOWN))
        self.assertNotIn(b.AWAITING_CALLBACK, b.awaiting_after(r, KNOWN))


if __name__ == "__main__":
    unittest.main()
