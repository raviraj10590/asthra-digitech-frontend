"""Replay of 14 days of Bairavi follow-ups, 2026-10-03 (second review).

239 customer messages replayed through the code then live; 41 still went to
the model. Each test below is one of those real messages, now answered from
the owner's facts. After this change the same replay sends 27 (11%).
"""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                    # noqa: E402
import interpretation as I                             # noqa: E402

CHOSEN = {"capacity_kva": 63, "name": "Ravi", "location": "Tikota",
          "application": "AGRICULTURE", "callback": "evening"}
NOT_CHOSEN = {"capacity_kva": 63, "name": "Ravi", "location": "Tikota",
              "application": "AGRICULTURE"}


def turn(text, known, awaiting=()):
    f = b.parse_followup(text, awaiting, known)
    f["call_hour"] = 12
    return f, b.compose_followup_reply(f, known, None, None)


class WhenWillYouCall(unittest.TestCase):
    """The largest group: "when?" after the call was promised."""
    LIVE = ("Yavag", "ಯಾವಾಗ", "Time", "Yastu ಗಂಟೆಗೆ", "Coll yavag madtare nimma enginiyar")

    def test_with_a_call_time_chosen_the_time_is_restated(self):
        for t in self.LIVE:
            with self.subTest(t=t):
                f, reply = turn(t, CHOSEN)
                self.assertFalse(b.should_ask_model(f, CHOSEN))
                self.assertIn("*ಇಂದು ಸಂಜೆ*", reply)
                self.assertFalse(reply.startswith("ಧನ್ಯವಾದಗಳು."), reply[:40])

    def test_without_one_the_times_are_offered_and_awaited(self):
        for t in self.LIVE:
            with self.subTest(t=t):
                f, reply = turn(t, NOT_CHOSEN)
                self.assertFalse(b.should_ask_model(f, NOT_CHOSEN))
                self.assertIn(b.CALLBACK_QUESTION, reply)
                self.assertEqual(b.awaiting_after(f, NOT_CHOSEN), (b.AWAITING_CALLBACK,))
        # ...and the "1" that follows is the time, not one unit.
        nxt = b.parse_followup("1", (b.AWAITING_CALLBACK,), NOT_CHOSEN)
        self.assertEqual((nxt["callback"], nxt["quantity"]), (b.CALLBACK_NOW, None))

    def test_call_hours_still_apply(self):
        f = b.parse_followup("Yavag", (), dict(CHOSEN, callback="now"))
        f["call_hour"] = 22
        self.assertIn("ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9", b.compose_followup_reply(f, dict(CHOSEN, callback="now"), None, None))

    def test_a_when_about_delivery_is_still_a_delivery_question(self):
        for t in ("Yavaga barate", "Estu Dinake kalstira", "when will it be delivered"):
            with self.subTest(t=t):
                f, reply = turn(t, CHOSEN)
                self.assertEqual(f["customer_question"], b.QUESTION_DELIVERY_TIME)
                self.assertFalse(f["asks_call"])
                self.assertIn("ಡೆಲಿವರಿ ಸಮಯ", reply)

    def test_a_place_is_not_a_question(self):
        self.assertFalse(b.asks_call_time("Kadaba"))
        self.assertFalse(b.asks_call_time("estu"))


class WordsAsTyped(unittest.TestCase):
    def test_coll_me_is_a_call_request(self):
        f, reply = turn("Coll me", NOT_CHOSEN)
        self.assertEqual(f["callback"], b.CALLBACK_NOW)

    def test_dar_heli_is_a_price_question(self):
        f, reply = turn("Dar heli", NOT_CHOSEN)
        self.assertTrue(f["asked_price"])
        self.assertIn("₹2,00,000 + GST", reply)

    def test_farming_is_agriculture(self):
        self.assertEqual(b.parse_followup("Farming", (b.AWAITING_PURPOSE,), {})["application"],
                         "AGRICULTURE")

    def test_oj_is_an_ok(self):
        self.assertTrue(b.parse_followup("Oj", (), {})["is_ack"])


class YouToldUsNothing(unittest.TestCase):
    LIVE = ("ನೀವು ನಮಗೆ ಯಾವ ಮಾಹಿತಿನು ಸಹ ಕೊಡಲಿಲ್ಲ.. ಯಾಕೆ ?", "ಅರ್ಥ ಆಗಲಿಲ್ಲ")
    KNOWN = {"capacity_kva": 25, "name": "Ravi", "location": "Tikota"}

    def test_answered_with_the_owner_facts_card(self):
        for t in self.LIVE:
            with self.subTest(t=t):
                f, reply = turn(t, self.KNOWN, (b.AWAITING_DELIVERY,))
                self.assertFalse(b.should_ask_model(f, self.KNOWN))
                self.assertTrue(reply.startswith("📋"), reply[:40])
                for fact in ("₹95,000 + GST", "1 ವರ್ಷ warranty", "50% advance", "MESCOM approved"):
                    self.assertIn(fact, reply)

    def test_never_stored_as_the_delivery_place(self):
        for t in self.LIVE + ("ಬೇಕಾದ ದಾಖಲೆಗಳು ವಿವರವನ್ನು ನೀಡಿ",):
            with self.subTest(t=t):
                f, _ = turn(t, self.KNOWN, (b.AWAITING_DELIVERY,))
                self.assertIsNone(f["delivery_location"])

    def test_a_document_question_is_not_answered_with_prices(self):
        """No document list has been stated by the owner."""
        f, _ = turn("ಬೇಕಾದ ದಾಖಲೆಗಳು ವಿವರವನ್ನು ನೀಡಿ", self.KNOWN)
        self.assertFalse(f["asks_info"])

    def test_without_a_known_rating_the_range_is_given_not_a_price(self):
        card = b.info_card_kn({})
        self.assertNotIn("₹", card)
        self.assertIn("25 kVA / 63 kVA / 100 kVA / 250 kVA", card)

    def test_the_card_carries_only_stated_facts(self):
        """Delivery time stays a call, never a number of days."""
        card = b.info_card_kn({"capacity_kva": 100})
        self.assertIsNone(b._REPLY_LEADTIME_RE.search(card))
        self.assertIn("₹2,95,000 + GST", card)


class TheShadowContract(unittest.TestCase):
    def test_new_signals_are_brain_owned_and_versioned(self):
        self.assertEqual(I.VALIDATOR_VERSION, "v3")
        # Whatever an interpreter proposes, these come from the deterministic reader.
        self.assertTrue(I.state_view(I.validate(I.empty(), "ಅರ್ಥ ಆಗಲಿಲ್ಲ"))["asks_info"])
        self.assertTrue(I.state_view(I.validate(I.empty(), "ಕರೆ ಮಾಡಿಲ್ಲ"))["call_missed"])
        self.assertFalse(I.state_view(I.validate(I.empty(), "Kadaba"))["asks_info"])


if __name__ == "__main__":
    unittest.main()
