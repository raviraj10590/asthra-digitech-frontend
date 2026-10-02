"""Last-20-leads review, 2026-10-03 — each test is a real message that went wrong.

Replayed against the code that was live (a04c3bd) before writing a fix: every
case below failed there, and only those that still failed are covered. The
1 Oct fixes already handled "ಸರಿ ಇದೆ", "Installation charge yestaguthe",
"Krish" and "ಹಣ".
"""
import json
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                             # noqa: E402
from conversation import Conversation, lead_form                # noqa: E402

AWAIT_PLACE = (b.AWAITING_DELIVERY,)


def place(text, known=None):
    f = b.parse_followup(text, AWAIT_PLACE, known or {"location": "melkote", "capacity_kva": 25})
    return f["delivery_location"], f["delivery_same"]


class YesIsNotAPlace(unittest.TestCase):
    def test_sare_confirms_the_place(self):
        """...3188: 'Sare' was recorded as the delivery place 'Sare'."""
        self.assertEqual(place("Sare"), (None, True))

    def test_a_form_option_letter_is_not_a_place(self):
        """...3900: 'A' was recorded as the delivery place 'A'."""
        for letter in ("A", "B", "c", "D."):
            with self.subTest(letter=letter):
                self.assertIsNone(place(letter)[0])

    def test_real_short_places_still_read(self):
        for name in ("Ura", "ಊರು", "Kadaba", "Doddabaragi", "Hosakeri"):
            with self.subTest(name=name):
                self.assertEqual(place(name)[0], name)


class WordsAsCustomersTypeThem(unittest.TestCase):
    def test_kruShi_is_agriculture(self):
        """...3350: 'ಕ್ರುಷಿ' twice, unread both times."""
        for t in ("ಕ್ರುಷಿ", "ಕ್ರಷಿ"):
            with self.subTest(t=t):
                self.assertEqual(b.parse_followup(t, (), {})["application"], "AGRICULTURE")

    def test_cast_and_amuont_ask_the_price(self):
        """...3900: 'Cast', then 'Amuont' — both went to the model."""
        for t in ("Cast", "Amuont", "amout"):
            with self.subTest(t=t):
                f = b.parse_followup(t, (), {"capacity_kva": 25})
                self.assertTrue(f["asked_price"])
                self.assertFalse(b.should_ask_model(f, {"capacity_kva": 25}))

    def test_cast_is_a_whole_word(self):
        self.assertFalse(b.parse_followup("broadcast", (), {})["asked_price"])


class APriceObjection(unittest.TestCase):
    """...5879: 'It's very High' straight after the quote got an English
    paragraph promising 'our system' would send a rate list."""

    def setUp(self):
        self.known = {"capacity_kva": 100, "name": "Manju Patil", "location": "badami"}
        self.f = b.parse_followup("It's very High", (), self.known)

    def test_is_read_as_negotiation_and_answered_by_the_composer(self):
        self.assertTrue(self.f["asked_discount"])
        self.assertFalse(b.should_ask_model(self.f, self.known))

    def test_the_answer_is_value_and_a_person_never_a_discount(self):
        reply = b.compose_followup_reply(self.f, self.known, None, None)
        self.assertIn("5 Star", reply)
        self.assertIn("sales ತಂಡ", reply)
        self.assertIsNone(b.reply_violates_evidence(reply.replace("5 Star", "")))
        alert = b.compose_followup_alert("919000000000", self.f, "It's very High", self.known)
        self.assertIn("PRICE NEGOTIATION", alert)


class TheCallThatNeverCame(unittest.TestCase):
    """...3188: 'ಕರೆ ಮಾಡಿಲ್ಲ' two hours after 'engineer will call now' was
    answered 'ಹೌದು' (YES) and the same promise again."""

    def setUp(self):
        self.known = {"capacity_kva": 25, "name": "Gkkumar Gkkumar", "callback": "now",
                      "location": "melkote", "application": "AGRICULTURE"}

    def test_detected_in_both_scripts(self):
        for t in ("ಕರೆ ಮಾಡಿಲ್ಲ", "call madilla sir", "No call yet", "nobody called me"):
            with self.subTest(t=t):
                self.assertTrue(b.parse_followup(t, (), self.known)["call_missed"])

    def test_asking_for_a_call_is_not_a_complaint(self):
        for t in ("call me", "ಕರೆ ಮಾಡಿ", "when will you call"):
            with self.subTest(t=t):
                self.assertFalse(b.parse_followup(t, (), self.known)["call_missed"])

    def test_answered_with_an_apology_not_yes(self):
        f = b.parse_followup("ಕರೆ ಮಾಡಿಲ್ಲ", (), self.known)
        reply = b.compose_followup_reply(f, self.known, None, None)
        self.assertTrue(reply.startswith("ಕ್ಷಮಿಸಿ"), reply)
        self.assertNotIn("ಹೌದು", reply)
        self.assertNotIn("ಈಗಲೇ", reply, "no new time promise")
        self.assertFalse(b.should_ask_model(f, self.known))

    def test_the_owner_alert_leads_with_it(self):
        f = b.parse_followup("ಕರೆ ಮಾಡಿಲ್ಲ", (), self.known)
        alert = b.compose_followup_alert("919000000000", f, "ಕರೆ ಮಾಡಿಲ್ಲ", self.known)
        self.assertTrue(alert.startswith("📵🔥 *CALL MISSED*"), alert[:80])
        self.assertNotIn("WAITING FOR YOUR CALL", alert)

    def test_through_a_conversation(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("ಕರೆ ಮಾಡಿಲ್ಲ")
        self.assertTrue(t.reply.startswith("ಕ್ಷಮಿಸಿ"), t.reply)
        self.assertTrue(any(m.startswith("📵🔥") for m in t["owner"]))


# The AI replies that actually went out (abridged from the CRM, phone numbers
# removed), each paired with what the customer had written.
LIVE_REPLIES = [
    ("It's very High", "Thank you, Manju Patil. We understand your concern about pricing — "
     "the detailed rate list for your requirement will be shared with you by our system, so "
     "please refer to it there.", "promises a document nobody sends"),
    ("ಸ್ವಲ್ಪ ಸಮಯ ವಾಗಲಿ", "ನಮಸ್ಕಾರ, ದಯಾನಂದ್ ಅವರೆ! ನಾವು ಕಡಬದಲ್ಲಿ oil-immersed 3-phase distribution "
     "transformer ತಯಾರಕರು. ದರಪಟ್ಟಿಯನ್ನು ನಮ್ಮ ವ್ಯವಸ್ಥೆ ಕಳುಹಿಸುತ್ತದೆ.", "promises a document nobody sends"),
    ("Cast", "ನಮಸ್ಕಾರ ರಘುಕ್ ಅವರೇ, ಬೈರವಿ ಟ್ರಾನ್ಸ್ ಸೊಲ್ಯೂಷನ್ಸ್‌ಗೆ ಸ್ವಾಗತ.", "welcomes the customer again"),
    ("ಕ್ರುಷಿ", "ನಮಸ್ಕಾರ ಚಿದಾನಂದ ಅವರೆ, ನಿಮ್ಮ ವಿಚಾರಣೆಗೆ ಧನ್ಯವಾದ. ನಾವು ಕಡಬದಲ್ಲಿ oil-immersed 3-phase "
     "distribution transformer ತಯಾರಿಸುತ್ತೇವೆ ಮತ್ತು MESCOM ಅನುಮೋದನೆ ಹೊಂದಿದ್ದೇವೆ.", "re-introduces the company"),
]


class TheGuard(unittest.TestCase):
    def test_the_live_replies_are_now_refused(self):
        for customer, reply, reason in LIVE_REPLIES:
            with self.subTest(customer=customer):
                self.assertEqual(b.reply_violates_evidence(reply, customer), reason)

    def test_an_introduction_is_fine_when_asked_for(self):
        for q in ("who are you", "what do you make", "ನೀವು ಯಾರು"):
            with self.subTest(q=q):
                self.assertIsNone(b.reply_violates_evidence(
                    "ನಾವು ಕಡಬದಲ್ಲಿ oil-immersed transformer ತಯಾರಕರು.", q))

    def test_an_ordinary_engineer_handoff_still_passes(self):
        self.assertIsNone(b.reply_violates_evidence(
            "ಡೆಲಿವರಿ ವ್ಯಾಪ್ತಿಯ ಬಗ್ಗೆ ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.", "Bellikhandi"))

    def test_a_refused_reply_falls_back_to_the_composed_one(self):
        reply, reason = b.compose_model_reply(LIVE_REPLIES[0][1], {}, {}, customer_text="It's very High")
        self.assertIsNone(reply)
        self.assertEqual(reason, "promises a document nobody sends")


if __name__ == "__main__":
    unittest.main()
