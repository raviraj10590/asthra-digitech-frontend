"""Last-10 review 2026-10-01 (real replies from the CRM) + the owner's selling points.

  "ಸರಿ ಇದೆ" (yes, right)              -> stored as the delivery ADDRESS      (...1709)
  "25" after the price               -> AI: "we can't share price here"     (...1709)
  "ಲೊಕೇಶನ್ all ಓವರ್ ಕರ್ನಾಟಕ ನ"         -> "engineer will tell"                (...1709)
  "Installation charge yestaguthe"   -> stored as the delivery ADDRESS      (...4585)
  "ಹಣ" (money)                       -> "engineer will tell about money"    (...4599)
  "Krish"                            -> not read; English AI paragraph      (...1945)
  Owner: "premium transformer, new company, five star, best grade aluminium
  winding, lower losses"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

D, P = (b.AWAITING_DELIVERY,), (b.AWAITING_PURPOSE,)


class YesWordsTogether(unittest.TestCase):
    def test_the_real_reply(self):
        for t in ("ಸರಿ ಇದೆ", "ಹೌದು ಸರಿ", "sari idi", "ok sir", "yes correct"):
            f = b.parse_followup(t, D, known={"location": "N G koppalu"})
            self.assertIsNone(f["delivery_location"], t)
            self.assertTrue(f["delivery_same"], t)

    def test_an_ack_when_nothing_is_asked(self):
        self.assertTrue(b.parse_followup("ಸರಿ ಇದೆ", (), known={})["is_ack"])

    def test_a_place_with_a_yes_word_is_still_a_place(self):
        self.assertEqual(b.parse_followup("Sira", D, known={})["delivery_location"], "Sira")
        self.assertFalse(b._all_affirmation_words("ಸರಿ Sira"))


class AQuestionIsNotAnAddress(unittest.TestCase):
    def test_the_real_message(self):
        for t in ("Installation charge yestaguthe", "transport eshtu", "rate enu",
                  "delivery hege", "ಎಷ್ಟು ದಿನ"):
            self.assertIsNone(b.parse_followup(t, D, known={})["delivery_location"], t)

    def test_places_still_read(self):
        for t in ("Yavagal", "Hosaholli", "Enumala halli", "Kadaba"):
            self.assertEqual(b.parse_followup(t, D, known={})["delivery_location"], t, t)


class MoneyIsPrice(unittest.TestCase):
    def test_hana(self):
        k = {"capacity_kva": 25}
        for t in ("ಹಣ", "ಹಣ ಎಷ್ಟು", "duddu yestu", "ದುಡ್ಡು"):
            f = b.parse_followup(t, (), known=k)
            self.assertTrue(f["asked_price"], t)
            self.assertIn("₹95,000 + GST", b.compose_followup_reply(f, k), t)


class DeliveryArea(unittest.TestCase):
    def test_all_over_karnataka(self):
        for t in ("ಲೊಕೇಶನ್ all ಓವರ್ ಕರ್ನಾಟಕ ನ", "do you deliver all over karnataka",
                  "ಇಡೀ ಕರ್ನಾಟಕ ಡೆಲಿವರಿ ಇದೆಯಾ"):
            self.assertEqual(b.customer_question(t), b.QUESTION_DELIVERY_AREA, t)


class Krish(unittest.TestCase):
    def test_typo(self):
        self.assertEqual(b.parse_followup("Krish", P, known={})["application"], "AGRICULTURE")
        for place in ("Krishnarajpet", "Krishnagiri"):
            self.assertNotEqual(b.parse_followup(place, P, known={})["application"], "AGRICULTURE", place)


class TheModelMayNotRefuseThePrice(unittest.TestCase):
    def test_the_real_reply_is_refused(self):
        r = "ನಮಸ್ಕಾರ ಗುರುಮೂರ್ತಿ ಅವರೆ. ದರದ ವಿವರಗಳನ್ನು ಇಲ್ಲಿ ಹಂಚಿಕೊಳ್ಳಲು ಸಾಧ್ಯವಿಲ್ಲ — ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ."
        self.assertEqual(b.reply_violates_evidence(r, "25"), "refuses to share a price")
        for r in ("I'm unable to discuss figures here.", "We cannot share the price."):
            self.assertEqual(b.reply_violates_evidence(r, "x"), "refuses to share a price", r)

    def test_the_brief_says_so(self):
        brief = b.model_brief_kn()
        self.assertIn("'ದರ ಹೇಳಲು ಸಾಧ್ಯವಿಲ್ಲ' ಎಂದು ಎಂದಿಗೂ ಹೇಳಬೇಡಿ", brief)


class EnglishToLatinKannadaWriters(unittest.TestCase):
    EN = "Thank you, Kiran. Bairavi Trans Solutions manufactures oil-immersed 3-phase distribution transformers at Kadaba."

    def test_refused(self):
        for t in ("Krish", "Sari", "25 kva beku"):
            self.assertEqual(b.reply_violates_evidence(self.EN, t), "not in Kannada", t)

    def test_english_writers_still_allowed(self):
        self.assertIsNone(b.reply_violates_evidence(self.EN, "where is your factory located"))


class SellingPoints(unittest.TestCase):
    def test_the_value_line_follows_the_price_list_rating(self):
        self.assertIn("*4 Star* premium transformer", b.value_line_kn(25))
        self.assertIn("*5 Star* premium transformer", b.value_line_kn(63))
        self.assertIn("*Star-rated* premium transformer", b.value_line_kn(None))
        for kva in (25, 63, None):
            line = b.value_line_kn(kva)
            self.assertIn("best-grade aluminium winding", line)
            self.assertIn("lower losses", line)
            for w in ("years", "ವರ್ಷ", "since", "%", "₹"):          # a new company; no figures
                self.assertNotIn(w, line)

    def test_after_the_price(self):
        k = {"capacity_kva": 63}
        reply = b.compose_followup_reply(b.parse_followup("rate eshtu", (), known=k), k)
        self.assertIn("₹2,00,000 + GST", reply)
        self.assertIn("*5 Star* premium transformer", reply)

    def test_on_a_price_objection(self):
        k = {"capacity_kva": 25}
        reply = b.compose_followup_reply(b.parse_followup("Too cost", (), known=k), k)
        self.assertLess(reply.index("premium transformer"), reply.index("sales ತಂಡ"))
        self.assertNotIn("₹", reply)

    def test_who_are_you(self):
        self.assertIn("premium transformer", b.answer_question_kn(b.QUESTION_WHO, {"capacity_kva": 25}))

    def test_the_model_knows_them_but_claims_no_years(self):
        brief = b.model_brief_kn()
        self.assertIn("best-grade aluminium winding", brief)
        self.assertIn("ವರ್ಷಗಳ ಅನುಭವ ಎಂದು ಹೇಳಬೇಡಿ", brief)


if __name__ == "__main__":
    unittest.main()


class NoLoneThanks(unittest.TestCase):
    def test_a_waiting_customer_is_told_when(self):
        k = {"capacity_kva": 25, "location": "x", "delivery_same": True,
             "application": "AGRICULTURE", "callback": "now"}
        self.assertEqual(b.compose_followup_reply(b.parse_followup("25", (), known=k), k),
                         "ಧನ್ಯವಾದಗಳು 🙏 ನಮ್ಮ engineer *ಈಗಲೇ* ನಿಮಗೆ ಕರೆ ಮಾಡುತ್ತಾರೆ.")

    def test_installation_amount_is_the_engineers(self):
        k = {"capacity_kva": 25}
        reply = b.compose_followup_reply(b.parse_followup("Installation charge yestaguthe", (), known=k), k)
        self.assertIn("ಅದರ ಮೊತ್ತವನ್ನು ನಮ್ಮ engineer ಕರೆಯಲ್ಲಿ ತಿಳಿಸುತ್ತಾರೆ", reply)
        self.assertNotIn("₹", reply)
