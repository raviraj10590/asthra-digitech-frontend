"""Owner, 2026-11-04: "namma sales li customerge starting nalle bot tara reply madodanu bidbeku
simpla aagi manushyar tra reply maadbeku ondonde messages".

The replies read like a person on WhatsApp: no numbered menu, no option list, no thank-you
receipt ("ಧನ್ಯವಾದಗಳು — … ಗಮನಿಸಿದ್ದೇವೆ"), and a reply in parts goes out as short separate
messages. The call promise keeps its parsed shape (CRM call board, call_briefing).
Plus the parse misses the 2026-11-04 stress test found.
"""
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.dirname(__file__))
import bairavi as b  # noqa: E402
import webhook as w  # noqa: E402
from conversation import Conversation, lead_form  # noqa: E402
import fake_send  # noqa: E402

KNOWN = {"capacity_kva": 25, "name": "Ravi", "location": "Kadur"}
DELIVERY, PURPOSE, CALLBACK = (b.AWAITING_DELIVERY,), (b.AWAITING_PURPOSE,), (b.AWAITING_CALLBACK,)


def reply(text, awaiting=(), known=KNOWN):
    return b.compose_followup_reply(b.parse_followup(text, awaiting, known), known)


class NoBotShapes(unittest.TestCase):
    def test_no_menu_and_no_option_list_in_the_questions(self):
        for field in (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE, b.AWAITING_CAPACITY,
                      b.AWAITING_QUANTITY, b.AWAITING_CALLBACK):
            q = b.question_for(field, KNOWN)
            self.assertNotIn("⃣", q, field)
            self.assertNotIn(" / ", q, field)
            self.assertEqual(q.count("?"), 1, q)

    def test_an_answer_is_acknowledged_like_a_person(self):
        r = reply("krushi", PURPOSE)
        self.assertTrue(r.startswith("ಸರಿ"), r)
        self.assertNotIn("ಗಮನಿಸಿದ್ದೇವೆ", r)
        self.assertNotIn("ಧನ್ಯವಾದಗಳು", r)

    def test_ok_is_not_put_in_front_of_a_real_answer(self):
        r = reply("who are you?", DELIVERY)
        self.assertFalse(r.startswith(b.ACK_KN), r)

    def test_the_opening_says_hello_not_a_receipt(self):
        r = b.compose_reply(b.parse(lead_form(location="Kadur", name="Ravi Kumar")))
        self.assertTrue(r.startswith("ನಮಸ್ಕಾರ Ravi Kumar 🙏 Bairavi Trans Solutions"), r)
        self.assertNotIn("ವಿಚಾರಣೆ ನಮಗೆ ತಲುಪಿದೆ", r)
        self.assertNotIn("ಸಂಪರ್ಕಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು", r)

    def test_the_bot_never_claims_to_be_a_person(self):
        self.assertIn("WhatsApp ಸಹಾಯಕ", b.BOT_KN)
        self.assertIn("bot/AI ಅಂತ ಯಾರಾದರೂ ಕೇಳಿದರೆ ಸುಳ್ಳು ಹೇಳಬೇಡಿ", w.SYSTEM_PROMPT)

    def test_the_call_promise_keeps_the_shape_the_crm_reads(self):
        k = dict(KNOWN, callback=None)
        r = reply("15 ge phone maadri", CALLBACK, k)
        self.assertIn("ನಮ್ಮ engineer *ಮಧ್ಯಾಹ್ನ 3 ಗಂಟೆಗೆ* ನಿಮಗೆ ಕರೆ ಮಾಡುತ್ತಾರೆ", r)


class Bubbles(unittest.TestCase):
    def test_one_message_per_paragraph(self):
        self.assertEqual(b.bubbles("ಸರಿ 👍\n\nಡೆಲಿವರಿ ಯಾವ ಊರಿಗೆ ಬೇಕು?"),
                         ["ಸರಿ 👍", "ಡೆಲಿವರಿ ಯಾವ ಊರಿಗೆ ಬೇಕು?"])

    def test_lines_of_one_paragraph_stay_together(self):
        self.assertEqual(b.bubbles("ದರ:\n*25 kVA* — ₹85,000"), ["ದರ:\n*25 kVA* — ₹85,000"])

    def test_never_more_than_three(self):
        parts = b.bubbles("a\n\nb\n\nc\n\nd\n\ne")
        self.assertEqual(len(parts), b.MAX_BUBBLES)
        self.assertEqual(parts[-1], "c\n\nd\n\ne")

    def test_the_opening_goes_out_as_short_messages(self):
        t = Conversation().send(lead_form(location="Kadur", name="Ravi Kumar"))
        self.assertGreater(len(t["sent"]), 1)
        self.assertTrue(all(s.strip() for s in t["sent"]))

    def test_a_later_message_that_fails_does_not_make_the_reply_undelivered(self):
        calls = []

        def send(to, text):
            calls.append(text)
            return w.classify_delivery(fake_send.Accepted() if len(calls) == 1 else fake_send.Rejected())
        with unittest.mock.patch.object(w, "send_text_checked", send):
            result = w.send_bubbles_checked("910000000000", "one\n\ntwo\n\nthree")
        self.assertEqual(result["verdict"], w.DELIVERY_ACCEPTED)
        self.assertEqual(calls, ["one", "two"])          # stops at the failure

    def test_a_first_message_that_fails_is_undelivered(self):
        with unittest.mock.patch.object(w, "send_text_checked",
                                        lambda to, text: w.classify_delivery(fake_send.Rejected())):
            self.assertNotEqual(w.send_bubbles_checked("910000000000", "one\n\ntwo")["verdict"],
                                w.DELIVERY_ACCEPTED)


class StressTestFindings1104(unittest.TestCase):
    def test_a_time_with_ge_call_is_never_units(self):
        for t in ("30 ge call maadi please", "15 ge phone maadri", "6 ge call maadi"):
            self.assertIsNone(b.parse_followup(t, CALLBACK, KNOWN)["quantity"], t)
        self.assertEqual(b.parse_followup("15 ge phone maadri", CALLBACK, KNOWN)["call_time"]["hour"], 15)
        self.assertEqual(b.parse_followup("2 units beku", (), KNOWN)["quantity"], 2)

    def test_hour_typos_are_times(self):
        for t, h in (("12 ಗಂತೆಗೆ", 12), ("11 ಗಂತೆಗೆ", 11), ("12 midday", 12)):
            f = b.parse_followup(t, CALLBACK, KNOWN)
            self.assertIsNone(f["quantity"], t)
            self.assertEqual(f["call_time"]["hour"], h, t)

    def test_what_does_it_cost_in_kanglish(self):
        self.assertTrue(b.parse_followup("bhai, 25kva ge yen charge?", DELIVERY, KNOWN)["asked_price"])
        self.assertTrue(b.parse_followup("yenu charge?", PURPOSE, KNOWN)["asked_price"])
        self.assertEqual(b.asked_terms("kudur alli delivery ge extra yen?"), ("transport",))

    def test_the_place_without_its_filler(self):
        for t in ("kadur ok", "yep kadur", "kadur delivery"):
            self.assertEqual(b.parse_followup(t, DELIVERY, KNOWN)["delivery_location"], "kadur", t)
        self.assertEqual(b.parse_followup("hey boss belgaum delivery maadi", DELIVERY, KNOWN)
                         ["delivery_location"], "belgaum")

    def test_not_now_is_a_decline_not_a_place(self):
        for t in ("can't right now", "can't buy now"):
            f = b.parse_followup(t, DELIVERY, KNOWN)
            self.assertIsNone(f["delivery_location"], t)
            self.assertTrue(f["declined"], t)


if __name__ == "__main__":
    unittest.main()
