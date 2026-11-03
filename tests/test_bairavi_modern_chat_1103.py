"""Bairavi follow-ups from the 2026-11-03 "modern chat" fake-customer round.

Owner: "namma brain modern jagattinalli conversation maadalu 100% efficient aagbeku". Groq
(openai/gpt-oss-120b) wrote 318 replies in today's chat styles; 258 passed on the live Brain
(a66f3d5). Messages below are verbatim from that batch
(~/Projects/Tools/brain-stress/nara_msgs_modern.json).

- Pings, a person asked for, payment, media and bargaining answering "deliver where?" were stored
  as the PLACE: "hi bro", "please connect to owner", "UPI code haaki", "video link kudko",
  "3k discount kodri", "👍 done".
- Clock times in modern formats at the 1/2/3 question were read as UNITS: "5:30 ge call maadi",
  "17:00 alli", "after 4 please", "half past 3 call", "12 noon call maadi".
- The place inside an English sentence was not read: "sir i want it at belgaum".
- "complete pricing for the 25 kVA" got the engineer hand-off.
- "bot aagiddiya" got only the place question again.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
CALLBACK = (b.AWAITING_CALLBACK,)
KNOWN = {"location": "Kadur", "capacity_kva": 25}


def at_delivery(t):
    return b.parse_followup(t, DELIVERY, KNOWN)


class NotAPlace(unittest.TestCase):
    def test_pings_people_payment_media_bargain(self):
        for t in ("hi bro", "hey there", "anyone there", "hello everyone", "please connect to owner",
                  "talk to actual person", "human manager", "real ga speak maadi", "engineer ivra",
                  "bot aagiddiya", "UPI code haaki.", "brochure bekku, pdf haaki", "video link kudko please",
                  "test cert copy haak", "location GPS coordinates haaku", "address exact kodu",
                  "discount thara, otherwise no deal", "illa, 3k discount kodri",
                  "ithu too high, 1.05lakh try maadi", "👍 done", "👍 gotit", "2 days nalli delivery"):
            with self.subTest(t=t):
                self.assertIsNone(at_delivery(t)["delivery_location"])

    def test_real_places_still_read(self):
        for t, place in (("Hosanagar", "Hosanagar"), ("Kotebottu", "Kotebottu"), ("Gadag distic sir", "Gadag"),
                         ("Holalkere taluk, Chitradurga", "Holalkere")):
            with self.subTest(t=t):
                self.assertIn(place, at_delivery(t)["delivery_location"] or "")


class PlaceInsideASentence(unittest.TestCase):
    def test_english_and_kannada_order(self):
        for t, place in (("sir i want it at belgaum please confirm availability", "belgaum"),
                         ("sir we need at shivamogga please arrange", "shivamogga"),
                         ("good morning sir idhu transformer delivery beku then just send to bagalkot", "bagalkot"),
                         ("sir i need at hosanagar", "hosanagar"),
                         ("hello sir haan nanna transformer delivery nodbeku andre please chennagiri alli "
                          "ship maadi", "chennagiri")):
            with self.subTest(t=t):
                self.assertEqual(at_delivery(t)["delivery_location"], place)

    def test_not_a_place_after_the_verb(self):
        for t in ("i want it at the earliest", "send to my site", "deliver to same place"):
            with self.subTest(t=t):
                self.assertIsNone(at_delivery(t)["delivery_location"])


class ModernClockTimes(unittest.TestCase):
    def test_read_at_the_menu_question(self):
        for t, hour in (("5:30 ge call maadi", 17), ("17:00 alli", 17), ("after 4 please", 16),
                        ("half past 3 call", 15), ("12 noon call maadi", 12), ("13:00 call", 13),
                        ("3.30 ge", 15), ("now illa, after 5", 17)):
            with self.subTest(t=t):
                got = b.parse_followup(t, CALLBACK, KNOWN)
                self.assertIsNotNone(got["call_time"])
                self.assertEqual(got["call_time"]["hour"], hour)
                self.assertIsNone(got["quantity"])

    def test_minutes_kept(self):
        self.assertEqual(b.parse_call_time("5:30 ge call maadi")["label_kn"], "ಸಂಜೆ 5:30 ಗಂಟೆಗೆ")
        self.assertEqual(b.parse_call_time("half past 3 call")["label_kn"], "ಮಧ್ಯಾಹ್ನ 3:30 ಗಂಟೆಗೆ")

    def test_not_a_clock(self):
        for t in ("after 2 days call", "1.05 lakh", "2 units", "2"):
            with self.subTest(t=t):
                self.assertIsNone(b.parse_followup(t, CALLBACK, KNOWN)["call_time"])
        self.assertIsNone(b.parse_followup("after 2 days call", CALLBACK, KNOWN)["quantity"])


class PersonBotPaymentMedia(unittest.TestCase):
    def test_asking_for_a_person_is_a_call_now(self):
        for t in ("please connect to owner", "talk to actual person", "human manager", "owner jote matadbeku"):
            with self.subTest(t=t):
                self.assertEqual(b.callback_request(t), b.CALLBACK_NOW)
        self.assertIsNone(b.callback_request("talk to owner later"))

    def test_bot_question_answered(self):
        for t in ("bot aagiddiya", "is this a bot?", "are you a robot"):
            with self.subTest(t=t):
                self.assertTrue(b.asks_bot(t))
        for t in ("Kotebottu", "bottle", "both ok"):
            with self.subTest(t=t):
                self.assertFalse(b.asks_bot(t))

    def test_payment_and_media(self):
        self.assertIn("payment", b.asked_terms("UPI code haaki"))
        self.assertIn("payment", b.asked_terms("GPay number kodi"))
        self.assertTrue(b.asks_photo("video link kudko please"))
        self.assertTrue(b.asks_photo("brochure pdf haaki"))
        self.assertTrue(b.asks_documents("test cert copy haak"))

    def test_pricing_is_a_price_ask(self):
        self.assertTrue(at_delivery("Could you provide the complete pricing for the 25 kVA transformer?")["asked_price"])


if __name__ == "__main__":
    unittest.main()


class SecondFreshBatch(unittest.TestCase):
    """A second, unseen modern batch (nara_msgs_modern_1103b.json): 271/309 before these."""

    def test_kannada_order_place(self):
        for t, place in (("hello sir haan nanage belgaum nalli delivery maadbeku please", "belgaum"),
                         ("sir hello idu belgaum ge delivery aagbe", "belgaum"),
                         ("namaskara sir nimminda yen kelasa nodbeku belgaum alli delivery aagbeku", "belgaum")):
            with self.subTest(t=t):
                self.assertEqual(at_delivery(t)["delivery_location"], place)

    def test_not_places(self):
        for t in ("bank loan approve aagidre delivery maadi", "factory address kooda send madri",
                  "idre maadi, illandre nenu beda", "cheap company idhe, neenu yen heli",
                  "brochure beku, email ge send madi", "nanna transformer delivery nodbeku",
                  "koneya delivery date yelli?", "2 days nalli delivery"):
            with self.subTest(t=t):
                self.assertIsNone(at_delivery(t)["delivery_location"])

    def test_shipping_is_transport_and_size_after_how_much_is_price(self):
        self.assertIn("transport", b.asked_terms("kudur ge shipping charge yen?"))
        self.assertTrue(at_delivery("yestu? 25kva")["asked_price"])
        self.assertFalse(at_delivery("yestu?")["asked_price"])     # "how many?" too — deliberately not a price
