"""Review of 2026-10-05 evening chats (owner: "ivattu brain bot answer madirodu
svalpa wrong ide"). Each test is a real message that went wrong live."""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                             # noqa: E402

D = (b.AWAITING_DELIVERY,)


def read(text, awaiting=(), known=None):
    return b.parse_followup(text, awaiting, known=known or {})


class GstAnswered(unittest.TestCase):
    """...5514: 'Gst estu aguthe sir' got 'the engineer will tell you' about the
    WRONG size; the owner had to answer (25 kVA with GST ~ 1,12,000)."""

    def test_the_question_is_read(self):
        for t in ("Gst estu aguthe sir", "GST yeshtu", "gst included?", "tax estu"):
            self.assertEqual(read(t)["customer_question"], b.QUESTION_GST, t)

    def test_the_answer_uses_the_size_they_asked_about(self):
        known = {"capacity_kva": 25, "name": "Bharath Patel"}
        f = read("Gst estu aguthe sir", (), known)
        reply = b.compose_followup_reply(f, known, None, None)
        self.assertIn("GST *18%*", reply)
        self.assertIn("₹1,12,100", reply)
        self.assertNotIn("63", reply)

    def test_totals_are_computed(self):
        self.assertEqual(b.with_gst(95_000), 112_100)
        self.assertEqual(b.with_gst(200_000), 236_000)


class RefusalsAreRefusals(unittest.TestCase):
    K = {"capacity_kva": 100, "location": "channagiri", "name": "Umesh Mudegowd"}

    def test_beda_bidi_is_not_a_place(self):
        """...6244: stored as the delivery place 'Beda bidi'."""
        f = read("Beda bidi", D, self.K)
        self.assertIsNone(f["delivery_location"])
        self.assertTrue(f["declined"])

    def test_a_price_refusal_gets_value_and_a_person_no_questions(self):
        """...6244: 'Dara jasti beda' was answered with 'ಎಷ್ಟು units ಬೇಕು?'."""
        f = read("Dara jasti beda", (), self.K)
        self.assertTrue(f["declined"])
        self.assertTrue(f["asked_discount"])
        reply = b.compose_followup_reply(f, self.K, None, None)
        self.assertIn("sales ತಂಡ", reply)
        self.assertNotIn("units", reply)
        self.assertNotIn("1️⃣", reply)
        self.assertEqual(b.awaiting_after(f, self.K), ())

    def test_ok_after_a_refusal_is_not_answered_with_the_call_menu(self):
        f = read("OK sir", (), self.K)
        self.assertTrue(b.is_silent_ack(f, ()))

    def test_a_thing_not_wanted_is_not_a_refusal(self):
        self.assertFalse(read("kamba beda", (), self.K)["declined"])
