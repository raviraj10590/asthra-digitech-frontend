"""Evening review, 2026-09-24 (lead ...4459, after 898268c went live).

  form location "thota" (farm)            -> read as a PLACE; purpose never inferred
  "1) ತೋಟ / 2) agriculture / 3) 25kVA"      -> delivery address "1) ತೋಟ"
  "kk"                                     -> would be a delivery address
  "K" with every question answered         -> a "message received" receipt
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

A = (b.AWAITING_DELIVERY,)
KNOWN = {"location": "Sira", "capacity_kva": 25}


def read(text, awaiting=A, known=KNOWN):
    return b.parse_followup(text, awaiting, known=known)


class FarmWords(unittest.TestCase):
    def test_form_location_thota_is_a_purpose(self):
        self.assertEqual(b._form_location("thota"), (None, "AGRICULTURE"))

    def test_farm_words_read_as_agriculture_not_an_address(self):
        for t in ("ತೋಟ", "thota", "ನಮ್ಮ ತೋಟಕ್ಕೆ", "ಹೊಲ", "gadde", "ಜಮೀನು", "farm"):
            r = read(t)
            self.assertEqual(r["application"], "AGRICULTURE", t)
            self.assertIsNone(r["delivery_location"], t)

    def test_place_names_containing_thota_are_still_places(self):
        r = read("Thotadahalli")
        self.assertIsNone(r["application"])
        self.assertEqual(r["delivery_location"], "Thotadahalli")


class NumberedAnswers(unittest.TestCase):
    def test_the_real_message(self):
        r = read("1) ತೋಟ \n2) agriculture \n3) 25kVA")
        self.assertEqual(r["application"], "AGRICULTURE")
        self.assertEqual(r["capacity_kva"], 25)
        self.assertIsNone(r["delivery_location"])

    def test_a_numbered_place_keeps_the_place_and_drops_the_number(self):
        self.assertEqual(read("1) Hosahalli\n2) agriculture")["delivery_location"], "Hosahalli")
        self.assertEqual(read("1. Sulekere village")["delivery_location"], "Sulekere village")

    def test_unnumbered_addresses_are_unchanged(self):
        self.assertEqual(read("Sulekere village, Turuvekere taluk")["delivery_location"],
                         "Sulekere village, Turuvekere taluk")


class OkSpellings(unittest.TestCase):
    def test_kk_is_never_an_address(self):
        for t in ("kk", "okk", "okey", "ಓಕೆ"):
            self.assertIsNone(read(t)["delivery_location"], t)

    def test_kk_to_same_place_is_yes(self):
        self.assertTrue(read("kk")["delivery_same"])


class SilentAck(unittest.TestCase):
    def test_k_with_nothing_pending_gets_no_reply(self):
        self.assertTrue(b.is_silent_ack(read("K", ()), ()))

    def test_k_to_a_pending_question_is_an_answer(self):
        r = read("K", A)
        self.assertFalse(b.is_silent_ack(r, A))
        self.assertTrue(r["delivery_same"])

    def test_anything_readable_is_answered(self):
        for t in ("25 kva rate?", "agriculture", "2 units"):
            self.assertFalse(b.is_silent_ack(read(t, ()), ()), t)

    def test_a_question_is_answered(self):
        self.assertFalse(b.is_silent_ack(read("mescom approval ide?", ()), ()))


class WebhookStaysSilent(unittest.TestCase):
    def test_the_branch_returns_before_sending(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")).read()
        i = src.index("if bairavi.is_silent_ack(followup, _awaiting):")
        j = src.index("send_text_checked(sender, _reply)")
        self.assertLess(i, j)
        self.assertIn("return", src[i:i + 400])

    def test_silence_uses_the_untimed_reader(self):
        """A stale or missing timestamp must never turn an answer into silence."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")).read()
        self.assertIn('_awaiting = bairavi.awaiting_from_history(ctx["history"])', src)


if __name__ == "__main__":
    unittest.main()
