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


class TheProductIsNotAPlace(unittest.TestCase):
    """...8890 (2026-10-06): the form's place field said "tc" and the bot
    asked "ಡೆಲಿವರಿ ಸ್ಥಳ: tc — ಇದು ಸರಿಯೇ?"."""

    def test_product_words_are_not_places(self):
        for word in ("tc", "TC", "T.C", "t c", "ಟಿಸಿ", "transformer", "current", "ವಿದ್ಯುತ್"):
            self.assertFalse(b._is_place_like(word), word)

    def test_places_that_contain_them_still_read(self):
        for place in ("Kadaba TC road", "tarikere", "channagiri", "Chikkaballapura"):
            self.assertTrue(b._is_place_like(place), place)


class PurposeInThePlaceField(unittest.TestCase):
    """...9608 (2026-10-06): "Agriculture farming 7 hp pump Electric" in the
    place field was confirmed back as "ಡೆಲಿವರಿ ಸ್ಥಳ: 7 hp Electric"."""

    def test_rating_and_equipment_are_not_the_place(self):
        self.assertEqual(b._form_location("Agriculture farming 7 hp pump Electric"), (None, "AGRICULTURE"))
        self.assertEqual(b._form_location("agriculture 10hp motor Hosur"), ("Hosur", "AGRICULTURE"))
        self.assertEqual(b._form_location("Bore well Hosur"), ("Hosur", "AGRICULTURE"))

    def test_real_places_unchanged(self):
        self.assertEqual(b._form_location("Agriculture Kanakagiri"), ("Kanakagiri", "AGRICULTURE"))
        self.assertEqual(b._form_location("Almel-586202"), ("Almel-586202", None))


class MenuDigitAfterTheMenu(unittest.TestCase):
    """...5389 (2026-10-06) chose "1" (call now), then sent "3"; the bot said
    "3 units ಗಮನಿಸಿದ್ದೇವೆ" though 3 is also ನಾಳೆ on that menu."""
    K = {"capacity_kva": 63, "location": "thirthalli", "application": "AGRICULTURE",
         "delivery_same": True, "callback": b.CALLBACK_NOW}

    def test_bare_3_asks_units_or_call_time(self):
        f = read("3", (), self.K)
        self.assertIsNone(f["quantity"])
        reply = b.compose_followup_reply(f, self.K)
        self.assertIn("3 units", reply)
        self.assertIn("ನಾಳೆ", reply)
        self.assertEqual(b.awaiting_after(f, self.K), (b.AWAITING_CALLBACK, b.AWAITING_QUANTITY))

    def test_the_answers_to_that_question(self):
        A = (b.AWAITING_CALLBACK, b.AWAITING_QUANTITY)
        self.assertEqual(read("ನಾಳೆ", A, self.K)["callback"], b.CALLBACK_TOMORROW)
        self.assertEqual(read("3 units", A, self.K)["quantity"], 3)

    def test_still_a_quantity_without_a_call_time_or_with_a_unit_word(self):
        self.assertEqual(read("3", (), {"capacity_kva": 63})["quantity"], 3)
        self.assertEqual(read("3 units", (), self.K)["quantity"], 3)
        self.assertEqual(read("3", (b.AWAITING_QUANTITY,), self.K)["quantity"], 3)
