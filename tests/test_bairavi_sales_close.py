"""Sales close, owner's ruling 2026-09-24.

Prices first (the owner's list, + GST), terms answered, and a call-back
choice once qualification is complete, which goes to the owner as a call task.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402
import nudge  # noqa: E402
from _price_policy import OWNER_PRICES, assert_only_owner_prices  # noqa: E402

FORM = ("Hello! I filled out your form\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: {cap}\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: Sira\nFull name: Test")
# The form's "price list / info" answer — the customer ASKED for the price.
PRICE_ASKED = "\nನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: E. ಮಾಹಿತಿ ಮತ್ತು ದರಪಟ್ಟಿಗಾಗಿ"
NEEDED_SOON = "\nನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: B.  1 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ"
DONE = {"location": "Sira", "capacity_kva": 25, "application": "AGRICULTURE", "delivery_same": True}


class ThePriceList(unittest.TestCase):
    def test_exactly_the_owners_figures(self):
        self.assertEqual(b.PRICE_LIST, {25: (95_000, 4), 63: (200_000, 5),
                                        100: (295_000, 5), 250: (495_000, 5)})

    def test_indian_grouping(self):
        self.assertEqual([b.inr(x) for x in (950, 95_000, 200_000, 295_000, 495_000)],
                         ["950", "95,000", "2,00,000", "2,95,000", "4,95,000"])
        self.assertEqual(OWNER_PRICES, {"95,000", "2,00,000", "2,95,000", "4,95,000"})

    def test_each_capacity_gets_its_own_price_and_star(self):
        for cap, line in (("A. 25 kVA", "*25 kVA 4 Star* — *₹95,000 + GST*"),
                          ("B. 63 kVA", "*63 kVA 5 Star* — *₹2,00,000 + GST*"),
                          ("C. 100 kVA", "*100 kVA 5 Star* — *₹2,95,000 + GST*"),
                          ("D. 250 kVA", "*250 kVA 5 Star* — *₹4,95,000 + GST*")):
            r = b.compose_reply(b.parse(FORM.format(cap=cap) + PRICE_ASKED))
            self.assertIn(line, r, cap)
            self.assertEqual(r.count("₹"), 1, cap)
            assert_only_owner_prices(self, r)

    def test_an_uncatalogued_capacity_sees_the_whole_list_not_a_guess(self):
        r = b.compose_reply(b.parse(FORM.format(cap="D.500 kVA") + PRICE_ASKED))
        self.assertEqual(r.count("₹"), 4)
        assert_only_owner_prices(self, r)

    def test_the_terms_are_exactly_what_the_owner_said(self):
        r = b.price_block_kn(25) + "\n".join(b.TERM_LINES.values()) + b.CLOSING_VALUE
        for must in ("Transport ಸೇರಿದೆ", "installation ಪ್ರತ್ಯೇಕ", "1 ವರ್ಷ warranty",
                     "service ಲಭ್ಯ", "50% advance", "MESCOM approved",
                     "ಡೆಲಿವರಿ ಸಮಯ — ನಮ್ಮ ತಂಡ call ನಲ್ಲಿ"):
            self.assertIn(must, r)

    def test_nothing_the_owner_did_not_state(self):
        r = b.price_block_kn(None) + b.price_block_kn(25)
        for banned in ("18%", "days", "weeks", "discount", "GESCOM approved",
                       "BESCOM approved", "installation free", "valid till"):
            self.assertNotIn(banned, r)

    def test_the_opening_reply_is_short(self):
        """Owner, 2026-09-25: "in one message dont tell everything"."""
        r = b.compose_reply(b.parse(FORM.format(cap="A. 25 kVA") + NEEDED_SOON))
        self.assertLessEqual(len([l for l in r.splitlines() if l.strip()]), 4, r)
        self.assertEqual(r.count("?"), 1)

    def test_no_price_unless_they_asked(self):
        """Owner, 2026-09-25: "dont tell price directly, if they ask price
        then only tell them price"."""
        for tail in ("", NEEDED_SOON, "\nನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ"):
            r = b.compose_reply(b.parse(FORM.format(cap="B. 63 kVA") + tail))
            self.assertNotIn("₹", r, tail)
        done_reply = b.compose_followup_reply(b.parse_followup("agriculture", (), DONE), DONE)
        self.assertNotIn("₹", done_reply)
        self.assertIn("₹", b.compose_reply(b.parse(FORM.format(cap="B. 63 kVA") + PRICE_ASKED)))

    def test_the_customer_is_addressed_by_name(self):
        r = b.compose_reply(b.parse(FORM.format(cap="A. 25 kVA").replace("Test", "PUNITH SINCHANA 2024")))
        self.assertTrue(r.startswith("ನಮಸ್ಕಾರ Punith Sinchana ಅವರೇ"), r)
        self.assertEqual(b.display_name("  "), "")


class PriceAndTermsQuestions(unittest.TestCase):
    def test_a_price_question_gets_the_price_for_their_capacity(self):
        r = b.compose_followup_reply(b.parse_followup("rate?", (), DONE), DONE)
        self.assertIn("₹95,000 + GST", r)
        self.assertEqual(r.count("₹"), 1)

    def test_without_a_capacity_the_whole_list(self):
        r = b.compose_followup_reply(b.parse_followup("price list?", (), {}), {})
        self.assertEqual(r.count("₹"), 4)

    def test_payment_and_warranty_questions_are_answered(self):
        for q, must in (("payment hege?", "50% advance"), ("warranty ide?", "1 ವರ್ಷ warranty"),
                        ("transport charge?", "Transport ದರದಲ್ಲೇ ಸೇರಿದೆ"), ("ಅಡ್ವಾನ್ಸ್ ಎಷ್ಟು", "50% advance")):
            r = b.compose_followup_reply(b.parse_followup(q, (), DONE), DONE)
            self.assertIn(must, r, q)
            self.assertNotIn("₹", r, q)          # a terms question is not a price question
            self.assertFalse(b.unanswered_question(b.parse_followup(q, (), DONE)), q)


class CallBack(unittest.TestCase):
    def test_offered_once_qualification_is_complete(self):
        f = b.parse_followup("ok", (b.AWAITING_DELIVERY,), DONE)
        r = b.compose_followup_reply(f, DONE)
        self.assertIn(b.CALLBACK_QUESTION, r)
        self.assertEqual(b.awaiting_after(f, DONE), (b.AWAITING_CALLBACK,))

    def test_not_offered_while_questions_remain(self):
        known = {"location": "Sira", "capacity_kva": 25}
        f = b.parse_followup("agriculture", (b.AWAITING_PURPOSE,), known)
        self.assertNotIn(b.CALLBACK_QUESTION, b.compose_followup_reply(f, known))
        self.assertNotIn(b.AWAITING_CALLBACK, b.awaiting_after(f, known))

    def test_the_three_choices(self):
        for text, slot in (("1", "now"), ("2", "evening"), ("3", "tomorrow"),
                           ("ಈಗಲೇ", "now"), ("sanje", "evening"), ("ನಾಳೆ ಬೆಳಿಗ್ಗೆ", "tomorrow"),
                           ("2️⃣", "evening")):
            f = b.parse_followup(text, (b.AWAITING_CALLBACK,), DONE)
            self.assertEqual(f["callback"], slot, text)
            self.assertIsNone(f["quantity"], text)

    def test_a_bare_number_is_a_quantity_when_no_choice_was_offered(self):
        f = b.parse_followup("2", (b.AWAITING_QUANTITY,), {})
        self.assertIsNone(f["callback"])
        self.assertEqual(f["quantity"], 2)

    def test_call_as_a_word_means_now(self):
        for t in ("CALL", "call me", "ಕಾಲ್ ಮಾಡಿ", "phone madi"):
            self.assertEqual(b.parse_followup(t, (), {})["callback"], "now", t)

    def test_a_sentence_mentioning_call_is_not_a_booking(self):
        self.assertIsNone(b.parse_followup("I will call you later about price", (), {})["callback"])

    def test_the_customer_is_told_when_and_not_asked_again(self):
        f = b.parse_followup("2", (b.AWAITING_CALLBACK,), DONE)
        r = b.compose_followup_reply(f, DONE)
        self.assertIn("ಇಂದು ಸಂಜೆ", r)
        self.assertNotIn(b.CALLBACK_QUESTION, r)
        self.assertEqual(b.awaiting_after(f, b.merged_state(DONE, f)), ())

    def test_the_owner_gets_a_call_task_first(self):
        f = b.parse_followup("1", (b.AWAITING_CALLBACK,), DONE)
        alert = b.compose_followup_alert("919000000000", f, "1", DONE)
        self.assertTrue(alert.startswith("🔥📞 *CALL NOW*"))

    def test_a_booking_is_remembered_across_turns(self):
        history = [
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_CALLBACK,))},
            {"role": "user", "content": "3"},
        ]
        self.assertEqual(b.established_from_history(history).get("callback"), "tomorrow")

    def test_the_reminder_asks_the_call_question_cleanly(self):
        text = nudge.compose((b.AWAITING_CALLBACK,), b.question_for, DONE)
        self.assertIn(b.CALLBACK_QUESTION, text)
        self.assertNotIn("1️⃣ 📞", text)


class TheClosingIsSaidOnce(unittest.TestCase):
    """Owner, 2026-09-25: "in one message dont tell everything"."""

    def test_after_the_offer_only_a_one_line_reminder(self):
        f = b.parse_followup("warranty?", (b.AWAITING_CALLBACK,), DONE)
        r = b.compose_followup_reply(f, DONE)
        self.assertIn("1 ವರ್ಷ warranty", r)
        self.assertIn(b.CALLBACK_REMINDER, r)
        self.assertNotIn(b.CLOSING_VALUE, r)
        self.assertNotIn(b.QUANTITY_NOTE, r)
        self.assertNotIn(b.CALLBACK_QUESTION, r)

    def test_the_reminder_options_still_parse(self):
        self.assertEqual(b.parse_followup("2", (b.AWAITING_CALLBACK,), DONE)["callback"], "evening")


class NoRepeatedCourtesy(unittest.TestCase):
    def test_thanks_is_said_once_per_message(self):
        f = b.parse_followup("agriculture", (b.AWAITING_PURPOSE,), {**DONE, "application": None})
        r = b.compose_followup_reply(f, {**DONE, "application": None})
        self.assertEqual(r.count("ಧನ್ಯವಾದಗಳು"), 1, r)


if __name__ == "__main__":
    unittest.main()
