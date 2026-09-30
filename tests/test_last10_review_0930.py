"""Last-10 review, 2026-09-30 (lead ...5711, real replies read from the CRM).

  "Idi" answering "is this the place?"   -> stored as the ADDRESS "Idi"
  "Ivag cl madtiya" after choosing "now"  -> never told "yes, now"
  "Nimdu tc yav company du"               -> "ಧನ್ಯವಾದಗಳು."
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

D = (b.AWAITING_DELIVERY,)
K = {"location": "thirthahalli", "delivery_same": True, "capacity_kva": 25,
     "application": "AGRICULTURE", "callback": "now", "name": "Sudarshan Gowda"}


class IdiMeansYes(unittest.TestCase):
    def test_the_real_answer(self):
        for t in ("Idi", "ide", "ಇದೆ", "ಇದಿ", "houdu idi", "ಅದೇ"):
            f = b.parse_followup(t, D, known={"location": "thirthahalli"})
            self.assertIsNone(f["delivery_location"], t)
            self.assertTrue(f["delivery_same"], t)

    def test_a_real_place_is_still_a_place(self):
        f = b.parse_followup("Idikki", D, known={"location": "thirthahalli"})
        self.assertEqual(f["delivery_location"], "Idikki")


class WillYouCallNow(unittest.TestCase):
    def test_the_real_message(self):
        f = b.parse_followup("Ivag cl madtiya", (), known=K)
        self.assertTrue(f["asks_call"])
        self.assertFalse(b.should_ask_model(f, K))
        self.assertEqual(b.compose_followup_reply(f, K),
                         "ಹೌದು Sudarshan Gowda ಅವರೇ, ನಮ್ಮ engineer *ಈಗಲೇ* ನಿಮಗೆ ಕರೆ ಮಾಡುತ್ತಾರೆ 🙏")
        alert = b.compose_followup_alert("9", f, "Ivag cl madtiya", K)
        self.assertTrue(alert.startswith("⏰📞 *WAITING FOR YOUR CALL*"))
        self.assertIn("(chose: NOW)", alert)

    def test_the_chosen_time_is_the_one_confirmed(self):
        k = dict(K, callback="evening")
        f = b.parse_followup("yavaga call madtira", (), known=k)
        self.assertIn("*ಇಂದು ಸಂಜೆ*", b.compose_followup_reply(f, k))

    def test_no_time_chosen_yet_is_not_confirmed(self):
        k = dict(K, callback=None)
        f = b.parse_followup("call madtira", (), known=k)
        reply = b.compose_followup_reply(f, k)
        self.assertNotIn("ಹೌದು", reply)
        self.assertNotIn("WAITING FOR YOUR CALL", b.compose_followup_alert("9", f, "x", k))

    def test_a_call_question_is_never_the_place(self):
        """Found by the contract corpus: asked while the bot waited for the place."""
        for t in ("yavaga call madtira", "Ivag cl madtiya", "ph madi sir"):
            self.assertIsNone(b.parse_followup(t, D, known={})["delivery_location"], t)

    def test_words_that_are_not_a_call(self):
        for t in ("call", "clear", "close", "Kamba yalla bantha", "1"):
            self.assertFalse(b.asks_about_call(t), t)
        for t in ("please call me now", "ph madi sir", "ಯಾವಾಗ ಕರೆ ಮಾಡುತ್ತೀರಿ"):
            self.assertTrue(b.asks_about_call(t), t)


class WhichCompany(unittest.TestCase):
    def test_answered_with_who_makes_it(self):
        for t in ("Nimdu tc yav company du", "which company transformer", "ಯಾವ ಕಂಪನಿ"):
            self.assertEqual(b.customer_question(t), b.QUESTION_WHO, t)
            self.assertIn("ತಯಾರಕರು", b.answer_question_kn(b.QUESTION_WHO, K))


if __name__ == "__main__":
    unittest.main()
