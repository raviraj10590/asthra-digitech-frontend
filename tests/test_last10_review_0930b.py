"""Last-10 review, 2026-09-30 evening (real replies read from the CRM).

  "ಧನ್ಯವಾದಗಳು ಸಿಸ್ಟಮ್"             -> sent to the model, which volunteered a reply
  "Too cost"                      -> the same price again, then "cannot discuss figures"
  "No thanx"                      -> an English model reply
  "Krasige.bekku." / "...niru.hasalu.bekku" -> purpose not read, asked again
  "32 ಕಹಬ" (32 poles)             -> recorded as 32 transformers
  form place "Agriculture Kanakagiri" -> "which place?"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

K = {"location": "Kanakagiri", "delivery_same": True, "capacity_kva": 25,
     "application": "AGRICULTURE", "callback": "tomorrow", "name": "Rohit K"}
P = (b.AWAITING_PURPOSE,)


class ThanksIsAnAcknowledgement(unittest.TestCase):
    def test_real_and_common(self):
        for t in ("ಧನ್ಯವಾದಗಳು ಸಿಸ್ಟಮ್", "thank you sir", "Thanks for info", "tq sir",
                  "ಧನ್ಯವಾದಗಳು ಸರ್ 🙏", "thanku"):
            f = b.parse_followup(t, (), known=K)
            self.assertTrue(f["is_ack"], t)
            self.assertFalse(b.should_ask_model(f, K), t)

    def test_thanks_is_never_the_delivery_place(self):
        for t in ("thank you sir", "ಧನ್ಯವಾದಗಳು ಸಿಸ್ಟಮ್"):
            f = b.parse_followup(t, (b.AWAITING_DELIVERY,), known={})
            self.assertIsNone(f["delivery_location"], t)

    def test_thanks_with_news_is_not_only_thanks(self):
        f = b.parse_followup("thank you, 2 units", (), known=K)
        self.assertFalse(f["is_ack"])
        self.assertEqual(f["quantity"], 2)
        self.assertFalse(b._is_thanks("thanks but price jasti ide sir ok"))


class PriceObjection(unittest.TestCase):
    def test_too_cost(self):
        for t in ("Too cost", "too costly", "very expensive", "rate jasti", "price too high",
                  "ತುಂಬಾ ದುಬಾರಿ", "rate heavy ide"):
            f = b.parse_followup(t, (), known=K)
            self.assertTrue(f["asked_discount"], t)
            reply = b.compose_followup_reply(f, K)
            self.assertIn("sales ತಂಡ", reply, t)
            self.assertNotIn("₹", reply, t)

    def test_not_an_objection(self):
        for t in ("jasti units beku", "too", "high school road", "cost", "heavy load"):
            self.assertFalse(b.asked_discount(t), t)


class NoThanks(unittest.TestCase):
    def test_the_real_message(self):
        f = b.parse_followup("No thanx", (), known=K)
        self.assertTrue(f["declined"])
        self.assertFalse(b.should_ask_model(f, K))
        reply = b.compose_followup_reply(f, K)
        self.assertTrue(reply.startswith("ಸರಿ Rohit ಅವರೇ 🙏"))
        self.assertNotIn("?", reply)
        alert = b.compose_followup_alert("9", f, "No thanx", K)
        self.assertTrue(alert.startswith("❌ *NOT INTERESTED*"))

    def test_other_declines_and_non_declines(self):
        for t in ("not interested", "ಬೇಡ", "beda sir", "no need"):
            self.assertTrue(b.is_decline(t), t)
        for t in ("no", "beda anta helilla", "ok", "need 2"):
            self.assertFalse(b.is_decline(t), t)


class PurposeInLatinKannada(unittest.TestCase):
    def test_real_messages(self):
        for t in ("Krasige.bekku.", "Beligalige.niru.hasalu.bekku", "krushige beku",
                  "krishige", "raitharige", "ನೀರು ಹಾಯಿಸಲು"):
            self.assertEqual(b.parse_followup(t, P, known={})["application"], "AGRICULTURE", t)

    def test_places_are_not_farms(self):
        for t in ("Kanakagiri", "Krishnarajpet", "Raichur"):
            self.assertNotEqual(b.parse_followup(t, P, known={})["application"], "AGRICULTURE", t)


class PolesAreNotTransformers(unittest.TestCase):
    def test_the_real_message(self):
        for t in ("32 ಕಹಬ", "32 ಕಂಬ", "10 kamba", "5 acre", "3 poles"):
            self.assertIsNone(b.parse_followup(t, (), known={"capacity_kva": 63})["quantity"], t)

    def test_counts_still_count(self):
        for t, n in (("2 units", 2), ("2 beku", 2), ("3 tc", 3)):
            self.assertEqual(b.parse_followup(t, (), known={"capacity_kva": 63})["quantity"], n, t)


FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {}\nFull name: Rohit K\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA")


class PurposeAndPlaceInOneAnswer(unittest.TestCase):
    def test_the_real_form(self):
        p = b.parse(FORM.format("Agriculture Kanakagiri"))
        self.assertEqual((p["location"], p["application"]), ("Kanakagiri", "AGRICULTURE"))
        self.assertIn("*Kanakagiri* — ಇದು ಸರಿಯೇ?", b.compose_reply(p))

    def test_unchanged_cases(self):
        self.assertEqual(b.parse(FORM.format("Kanakagiri"))["location"], "Kanakagiri")
        self.assertIsNone(b.parse(FORM.format("agriculture"))["location"])
        self.assertIsNone(b.parse(FORM.format("thota"))["location"])


if __name__ == "__main__":
    unittest.main()
