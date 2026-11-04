"""Last-10 review, 2026-11-04 (owner: "ella tappu sari maadu").

  ...8314 "ಕರೆ madabedi"                    -> asked the call time again
  ...2521 "99727 15155 ಕರೆ ಮಾಡಿ ವಿಷಯ ತಿಳಿಸಿ" -> asked the call time again
  ...0765 Kannada name in the place field  -> "ನಿಮ್ಮ ಊರು ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ ಅಲ್ವಾ?"
  ...7601 "Naliy"                           -> asked the call time again
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

CB = (b.AWAITING_CALLBACK,)
K = {"capacity_kva": 25, "name": "Parshu SG", "application": "AGRICULTURE", "delivery_location": "Hanagal"}


class DoNotCall(unittest.TestCase):
    def test_the_live_message(self):
        f = b.parse_followup("ಕರೆ madabedi", CB, known=K)
        self.assertTrue(f["no_call"])
        self.assertIsNone(f["callback"])
        r = b.compose_followup_reply(f, K)
        self.assertIn("call ಮಾಡಲ್ಲ", r)
        self.assertNotIn(b.CALLBACK_QUESTION, r)
        self.assertEqual(b.awaiting_after(f, K), ())
        self.assertIn("DO NOT CALL", b.compose_followup_alert("918197288314", f, "ಕರೆ madabedi", K))

    def test_other_ways(self):
        for t in ("call beda", "call madbedi", "ಕರೆ ಮಾಡಬೇಡಿ", "don't call", "please dont call me",
                  "only whatsapp", "phone beda sir"):
            self.assertTrue(b.refuses_call(t), t)
        for t in ("call madi", "ಕರೆ ಮಾಡಿ", "nale call madi", "ಕರೆ ಮಾಡಿಲ್ಲ", "beda", "price beda"):
            self.assertFalse(b.refuses_call(t), t)

    def test_never_asked_again_later_in_the_chat(self):
        known = dict(K, no_call=True)
        f = b.parse_followup("price eshtu", (), known=known)
        self.assertNotIn(b.CALLBACK_QUESTION, b.compose_followup_reply(f, known))
        self.assertNotIn(b.AWAITING_CALLBACK, b.awaiting_after(f, known))

    def test_a_later_call_request_still_wins(self):
        known = dict(K, no_call=True)
        f = b.parse_followup("call madi", (), known=known)
        self.assertEqual(f["callback"], b.CALLBACK_NOW)


class CallMeInsideALongerMessage(unittest.TestCase):
    def test_the_live_message(self):
        self.assertEqual(b.callback_request("99727 15155 ಕರೆ ಮಾಡಿ ವಿಷಯ ತಿಳಿಸಿ", CB), b.CALLBACK_NOW)

    def test_later_and_complaints_are_not_now(self):
        self.assertEqual(b.callback_request("nale call madi", CB), b.CALLBACK_TOMORROW)
        self.assertIsNone(b.callback_request("ಕರೆ ಮಾಡಿಲ್ಲ", CB))
        self.assertIsNone(b.callback_request("ಕರೆ madabedi", CB))


class TyposOfTomorrow(unittest.TestCase):
    def test_naliy(self):
        for t in ("Naliy", "nali", "naley", "ನಾಳೇ"):
            self.assertEqual(b.callback_request(t, CB), b.CALLBACK_TOMORROW, t)

    def test_only_when_the_call_time_was_asked(self):
        self.assertIsNone(b.callback_request("nali", ()))


class TheNameInTheOtherScript(unittest.TestCase):
    FORM = ("Hello! I filled in your form and would like to know more about your business.\n\n"
            "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
            "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ\n"
            "Full name: Suresh Lamani\nPhone number: +919964430765\n"
            "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ")

    def test_the_form_place_is_dropped(self):
        p = b.parse(self.FORM)
        self.assertIsNone(p["location"])
        self.assertNotIn("ಸುರೇಶ್", b.compose_reply(p))

    def test_places_are_still_places(self):
        self.assertFalse(b._is_the_name("ಹುಲಿಕೇರಿ ತಾಂಡ", "Suresh Lamani"))
        self.assertFalse(b._is_the_name("Ravi Nagar Hubli", "Ravi Kumar"))
        self.assertFalse(b._is_the_name("ಹಾಸನ", "Hassan Ali"))

    def test_the_name_line_leaves_the_address(self):
        k = {"capacity_kva": 25, "name": "Suresh Lamani"}
        f = b.parse_followup("ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ\nಹುಲಿಕೇರಿ ತಾಂಡ\nತಾಲೂಕು ಸವದತಿ\nಜಿಲ್ಲಾ ಬೆಳಗಾವ",
                             (b.AWAITING_DELIVERY,), known=k)
        self.assertNotIn("ಸುರೇಶ್", f["delivery_location"])
        self.assertIn("ಸವದತಿ", f["delivery_location"])


if __name__ == "__main__":
    unittest.main()
