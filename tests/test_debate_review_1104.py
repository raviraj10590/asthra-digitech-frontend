"""Customer-vs-bot debate, 2026-11-04 (owner: "brain upgrade aagbeku").

A Groq model played six hard customers against the live composer
(~/Projects/Tools/brain-stress/debate.py). What it found, each a message from that run:

  "call ಬೇಡ" + price/delivery/install questions -> "ನಾವು call ಮಾಡಲ್ಲ" six times, never the price
  "50% ಮುಂಚಿತ ಪಾವತಿ" / "24/7" / "3 motors"    -> "50 units" / "24 units" / "3 units"
  "ಬೆಲೆ ₹70,000 … ₹50,000 … ನಾನು ₹45,000 ಕೊಟ್ಟರೆ" -> owner told "offered ₹70,000"
  the bargain block and "ಸರಿ, ಅದೇ ಊರು 👍" sent again word for word every turn
  "ಆನ್‌ಲೈನ್ ಸ್ಕ್ಯಾಮ್ ಅಲ್ಲವೆ?"                        -> no trust facts
  "100kVA ಅಥವಾ 63kVA ಸಾಕಾ? … ಬೆಲೆ ಹೋಲಿಸಿ"         -> size switched to 100, no comparison
  "kVA ಅಂದ್ರೆ ಏನು? … ಸಬ್ಸಿಡಿ, ಲೋನ್"               -> "ಇದನ್ನ ನಮ್ಮ engineer ಹತ್ರ ಕೇಳಿ ಹೇಳ್ತೀವಿ"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

DL = (b.AWAITING_DELIVERY,)


def turn(text, known, awaiting=DL):
    f = b.parse_followup(text, awaiting, known=known)
    return f, b.compose_followup_reply(f, known)


class DoNotCallStillAnswers(unittest.TestCase):
    K = {"capacity_kva": 25, "name": "Shobha", "location": "Tumakuru", "delivery_location": "Tumakuru"}
    MSG = "ಹೌದು Tumakuru, 25kVA 1 ದಿನಕ್ಕೆ ಬೇಕು. ಬೆಲೆ, ಡೆಲಿವರಿ ಟೈಮ್, ಇನ್‌ಸ್ಟಾಲ್ ವೆಚ್ಚ ಎಷ್ಟು? Call ಬೇಡ, WhatsApp ನಲ್ಲಿ ಮಾತ್ರ."

    def test_the_price_is_given_with_the_promise(self):
        f, r = turn(self.MSG, self.K)
        self.assertTrue(f["no_call"])
        self.assertIn("call ಮಾಡಲ್ಲ", r)
        self.assertIn("₹85,000", r)
        self.assertIn("installation", r)
        self.assertIn(b._DELIVERY_TIME_KN[:20], r)
        self.assertNotIn(b.CALLBACK_QUESTION, r)

    def test_said_once_not_every_turn(self):
        known = dict(self.K, no_call=True)
        f, r = turn("price 25kVA ಎಷ್ಟು? call ಮಾಡಬೇಡಿ", known, ())
        self.assertNotIn("call ಮಾಡಲ್ಲ", r)
        self.assertIn("₹85,000", r)

    def test_a_bare_refusal_still_gets_the_short_answer(self):
        f, r = turn("call beda", self.K, (b.AWAITING_CALLBACK,))
        self.assertIn("call ಮಾಡಲ್ಲ", r)

    def test_a_bargain_without_calls_promises_no_call(self):
        known = dict(self.K, no_call=True)
        f, r = turn("45000 ge kodi", known, ())
        self.assertTrue(f["asked_discount"])
        self.assertNotIn("call ಮಾಡಿ", r)
        self.assertIn("WhatsApp", r)


class NotACount(unittest.TestCase):
    def test_percent_hours_and_motors(self):
        K = {"capacity_kva": 63, "location": "Hassan"}
        for t in ("50% ಮುಂಚಿತ ಪಾವತಿ ಎನಗೆ?", "2nd shift power supply ಗಾಗಿ, 24/7.",
                  "3 motors 10 HP ಕ್ಕೆ ಸಾಕಾ?", "3 ಮೋಟಾರ್ ಇದೆ"):
            self.assertIsNone(b.parse_followup(t, DL, known=K)["quantity"], t)

    def test_real_counts_still_read(self):
        for t, n in (("2 units beku", 2), ("3 ಯುನಿಟ್", 3), ("5 transformer", 5)):
            self.assertEqual(b.parse_followup(t, (), known={})["quantity"], n, t)


class OurFactoryIsNotTheirs(unittest.TestCase):
    def test_asking_about_our_factory(self):
        f = b.parse_followup("ಫ್ಯಾಕ್ಟರಿ Kadaba ಅಲ್ಲಿ ಇದ್ದೇ? ನಿಜವಾದ ವಿಳಾಸ ಬೇಕು", DL, known={"capacity_kva": 63})
        self.assertIsNone(f["application"])

    def test_their_factory_still_read(self):
        self.assertEqual(b.parse_followup("namma factory ge beku", (), known={})["application"], "INDUSTRY")


class TheirOfferIsTheLowestFigure(unittest.TestCase):
    def test_the_debate_message(self):
        t = "ಬೆಲೆ ₹70,000 ಆಗಿದೆ. ಮತ್ತೊಂದು ಕಂಪನಿ ₹50,000 ಕೊಡ್ತಿದೆ. ನಾನು ₹45,000 ಕೊಟ್ಟರೆ ಏನಾದರೂ ಮಾಡ್ತೀರಾ?"
        self.assertEqual(b.offered_amount(t), 45000)

    def test_one_figure_unchanged(self):
        self.assertEqual(b.offered_amount("60000 ge kodi"), 60000)


class NoWordForWordRepeat(unittest.TestCase):
    K = {"capacity_kva": 25, "name": "Mahesh", "location": "Kadur", "delivery_location": "Kadur"}

    def test_second_bargain_is_short(self):
        first = b.compose_followup_reply(b.parse_followup("45000 ge kodi", (), known=self.K), self.K)
        known = dict(self.K, asked_discount=True, delivery_same=True)
        f = b.parse_followup("55000 ge kodi sir", (), known=known)
        again = b.compose_followup_reply(f, known)
        self.assertIn("quality", first)
        self.assertNotIn("quality ಮೇಲೆ depend", again)
        self.assertIn("sales", again)
        self.assertNotIn("₹", again)

    def test_same_place_acknowledged_once(self):
        known = dict(self.K, delivery_same=True)
        r = b.compose_followup_reply(b.parse_followup("ಹೌದು Kadur, rate eshtu", DL, known=known), known)
        self.assertNotIn("ಅದೇ ಊರು", r)

    def test_details_card_carries_the_price_once(self):
        K = {"capacity_kva": 25, "location": "Chitradurga"}
        r = turn("25 kVA ಬೆಲೆ ಎಷ್ಟು? ವಿವರ ಕೊಡಿ", K, ())[1]
        self.assertEqual(r.count("₹85,000"), 1)


class TrustQuestions(unittest.TestCase):
    def test_scam_gets_the_facts(self):
        K = {"capacity_kva": 63, "location": "Hassan"}
        f, r = turn("ಆನ್‍ಲೈನ್ ಸ್ಕ್ಯಾಮ್ ಅಲ್ಲವೆ? 50% ಮುಂಚಿತ ಪಾವತಿ ಎನಗೆ?", K)
        self.assertIn("Kadaba", r)
        self.assertIn("50%", r)
        self.assertIn("MESCOM", r)


class ComparingSizes(unittest.TestCase):
    K = {"capacity_kva": 250, "name": "Naveen", "location": "Mysuru"}
    MSG = "3 motors 10 HP ಕ್ಕೆ 100kVA ಅಥವಾ 63kVA ಸಾಕಾ? 250kVA ಬೆಲೆ, 100kVA ಬೆಲೆ, 63kVA ಬೆಲೆ ಹೋಲಿಸಿ ಕೊಡಿ."

    def test_every_size_priced_and_none_chosen_for_them(self):
        f, r = turn(self.MSG, self.K)
        self.assertIsNone(f["capacity_kva"])
        for p in ("₹1,90,000", "₹2,50,000", "₹4,95,000"):
            self.assertIn(p, r)
        self.assertIn("engineer", r)
        self.assertEqual(b.merged_state(self.K, f)["capacity_kva"], 250)


class PlainQuestions(unittest.TestCase):
    K = {"capacity_kva": 25, "location": "Chitradurga"}

    def test_kva_meaning_and_subsidy(self):
        f, r = turn("ಅಯ್ಯೋ 25 kVA ಅಂದ್ರೆ ಏನು ಅರ್ಥ, ನನಗೆ ಗೊತ್ತಿಲ್ಲ. ಸರ್ಕಾರದ ಸಬ್ಸಿಡಿ, ಲೋನ್ ಬಗ್ಗೆ ಹೇಳಿ.", self.K)
        self.assertIn("HP", r)
        self.assertIn("ಸಬ್ಸಿಡಿ", r)
        self.assertNotIn("ಇದನ್ನ ನಮ್ಮ engineer ಹತ್ರ ಕೇಳಿ", r)
        self.assertIsNone(b.reply_violates_evidence(b.answer_question_kn(b.QUESTION_KVA_SUBSIDY)))

    def test_subsidy_alone(self):
        self.assertEqual(b.customer_question("subsidy sigutta?"), b.QUESTION_SUBSIDY)
        self.assertEqual(b.customer_question("kva andre enu"), b.QUESTION_KVA)


class SecondRun(unittest.TestCase):
    """The same debate run again after the fixes (2026-11-04) — what it still found."""

    def test_bargain_question_gets_no_ask_the_engineer_line(self):
        K = {"capacity_kva": 25, "name": "Mahesh", "location": "Kadur"}
        f, r = turn("ಹೌದು, Kadur, Chikkamagaluru. 25kVA 45k ರೂ.ಗೆ ಕೊಡುವಿರಾ? 💰", K)
        self.assertTrue(f["asked_discount"])
        self.assertNotIn("ಇದನ್ನ ನಮ್ಮ engineer ಹತ್ರ ಕೇಳಿ", r)

    def test_real_company_and_advance(self):
        K = {"capacity_kva": 63, "location": "Hassan"}
        f, r = turn("ಹೌದು, ಹೌದು. ನಿಮ್ಮ ಫ್ಯಾಕ್ಟರಿ ಎಲ್ಲಿ ಇದೆ? ಇದೊಂದು ನಿಜವಾದ ಕಂಪನಿ ಅಲ್ವಾ? ನಾನು 50% ಮುಂಚಿತ ಪಾವತಿ ಮಾಡಬೇಕೆ? 🤔", K)
        self.assertIsNone(f["quantity"])
        self.assertIsNone(f["application"])
        self.assertIn("50%", r)
        self.assertIn("MESCOM", r)

    def test_the_address_ends_with_its_sentence(self):
        t = ("ಹೌದು, Hubballi, Bagalkot ಜಿಲ್ಲೆ. 100 kVA ಗಾಗಿ GST ಸಹಿತ ಬೆಲೆ, ಡೆಲಿವರಿ ದಿನಗಳು, ಕಾಪರ್ ಅಥವಾ "
             "ಅಲ್ಯೂಮಿನಿಯಂ winding, ಟೆಸ್ಟ್ ಪ್ರಮಾಣಪತ್ರ, ಕ್ರೆಡಿಟ್ ಷರತ್ತುಗಳು ತಿಳಿಸಿ. ಧನ್ಯವಾದಗಳು.")
        dl = b.parse_followup(t, DL, known={"capacity_kva": 100, "location": "Hubballi"})["delivery_location"]
        self.assertIn("Bagalkot", dl)
        self.assertNotIn("ಡೆಲಿವರಿ", dl)

    def test_a_full_address_is_still_verbatim(self):
        t = "ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು,ಚಿತ್ರದುರ್ಗ ಜಿಲ್ಲೆ"
        self.assertEqual(b.parse_followup(t, DL, known={})["delivery_location"], t)

    def test_loan_said_another_way(self):
        self.assertEqual(b.customer_question("ಸರ್ಕಾರದ ಸಹಾಯ, ಸಾಲ ಮಾಹಿತಿ ಕೊಡ್ತೀರಾ?"), b.QUESTION_SUBSIDY)

    def test_three_by_ten_hp_and_a_smaller_size(self):
        K = {"capacity_kva": 250, "name": "Naveen", "location": "Mysuru"}
        f, r = turn("250kVA ಗಿಂತ ಸ್ವಲ್ಪ ಕಡಿಮೆ ಬೇಕು. 3 x 10 HP ಮೋಟರ್‌ಗಳಿಗೆ 100kVA ಅಥವಾ 63kVA ಸಾಕಾ? "
                    "250kVA, 100kVA, 63kVA ಬೆಲೆಗಳನ್ನು ಹೋಲಿಸಿ ಕೊಡಿ.", K)
        self.assertIsNone(f["quantity"])
        self.assertFalse(f["asked_discount"])
        self.assertIn("₹1,90,000", r)

    def test_delivery_time_without_a_call(self):
        K = {"capacity_kva": 25, "name": "Shobha", "location": "Tumakuru", "no_call": True}
        r = turn("ಡೆಲಿವರಿ ಎಷ್ಟು ದಿನ? ಕರೆ ಬೇಡ", K, ())[1]
        self.assertIn("1 ತಿಂಗಳೊಳಗೆ", r)

    def test_no_call_with_a_question_still_awaits_the_next_answer(self):
        K = {"capacity_kva": 25, "name": "Shobha", "location": "Tumakuru"}
        f = b.parse_followup("ಬೆಲೆ ತಿಳಿಸಿ. ಕರೆ ಬೇಡ", DL, known=K)
        self.assertNotEqual(b.awaiting_after(f, K), ())
        self.assertEqual(b.awaiting_after(b.parse_followup("call beda", DL, known=K), K), ())

    def test_third_run_factory_where_and_is_it_real(self):
        K = {"capacity_kva": 63, "location": "Hassan"}
        f, r = turn("ನಿನ್ನ ಕಂಪನಿ ನಿಜವೇ? ಫ್ಯಾಕ್ಟರಿ ಎಲ್ಲಿ ಇದೆ? 50% advance ಕೊಡಬೇಕೆಂದರೆ?", K)
        self.assertIsNone(f["application"])
        self.assertTrue(f["asks_info"])
        self.assertIn("Kadaba", r)


class OwnerAnswers1104(unittest.TestCase):
    """Owner, 2026-11-04: "winding alluminiumn. Ht load sanction aadre 160 KVa saha supply madbahudu"."""
    K = {"capacity_kva": 100, "name": "Kiran", "location": "Hubballi", "delivery_same": True}

    def test_winding(self):
        f, r = turn("winding copper aa aluminium aa?", self.K, ())
        self.assertEqual(f["customer_question"], b.QUESTION_WINDING)
        self.assertIn("aluminium winding", r)
        self.assertFalse(b.should_ask_model(f, self.K))

    def test_160_on_an_ht_sanction_without_a_price(self):
        f, r = turn("160 kva sigutta?", self.K, ())
        self.assertIn("HT load sanction", r)
        self.assertNotIn("ಇದನ್ನ ನಮ್ಮ engineer ಹತ್ರ ಕೇಳಿ", r)
        self.assertNotIn(160, b.PRICE_LIST)
        self.assertEqual(b.sku_status(160), b.VERIFY)
        r2 = turn("160 kva rate eshtu", self.K, ())[1]
        self.assertIn("ಅದರ ದರ ನಮ್ಮ engineer ತಿಳಿಸ್ತಾರೆ", r2)

    def test_160_only_when_asked(self):
        self.assertNotIn("160", b._range_line_kn())
        self.assertNotIn("160", b.info_card_kn({"capacity_kva": 100}))
        self.assertEqual(b.customer_question("ಯಾವ ಯಾವ kVA ಮಾಡ್ತೀರಾ?"), b.QUESTION_RANGE)


class OwnerAnswers1104b(unittest.TestCase):
    """Owner, 2026-11-04: test certificate yes; 50% advance must, rest at delivery; delivery
    within one month of the advance."""
    K = {"capacity_kva": 100, "name": "Kiran", "location": "Hubballi", "delivery_same": True}

    def test_the_factory_buyers_four_questions(self):
        f, r = turn("ಡೆಲಿವರಿ ಎಷ್ಟು ದಿನಗಳು? ವಿಂಡಿಂಗ್ ಕಾಪರ್ ಇದೆಯಾ ಅಥವಾ ಅಲ್ಯೂಮಿನಿಯಂ? ಟೆಸ್ಟ್ ಸರ್ಟಿಫಿಕೇಟ್ ಬೇಕು. "
                    "ಕ್ರೆಡಿಟ್ ಟರ್ಮ್ಸ್ 30 ದಿನಗಳಾ?", self.K, ())
        self.assertIn("1 ತಿಂಗಳೊಳಗೆ", r)
        self.assertIn("aluminium winding", r)
        self.assertIn("test certificate", r)
        self.assertIn("50% advance", r)
        self.assertIsNone(f["quantity"])

    def test_payment_is_firm(self):
        self.assertIn("ಕಡ್ಡಾಯ", b.TERM_LINES["payment"])

    def test_the_card_still_has_no_delivery_line(self):
        self.assertNotIn("ತಿಂಗಳೊಳಗೆ", b.info_card_kn({"capacity_kva": 25}))


if __name__ == "__main__":
    unittest.main()
