"""Replies to the price message sent to every lead on 2026-10-12."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bairavi as b                                             # noqa: E402

K = {"capacity_kva": 25, "location": "haveri, adur, HANGAL", "name": "Test"}


def turn(text, awaiting=(), known=K):
    f = b.parse_followup(text, awaiting, known)
    return f, b.compose_followup_reply(f, known)


class ThumbsUpInAnyColour(unittest.TestCase):
    """...9594 answered "deliver to Hangal?" with 👍🏿 and was asked again."""

    def test_skin_tones_confirm_the_place(self):
        for t in ("👍🏿", "👍🏻", "👍🏽", "👍"):
            f, reply = turn(t, (b.AWAITING_DELIVERY,))
            self.assertTrue(f["delivery_same"], t)
            self.assertIn("ಇದೇ ಸ್ಥಳಕ್ಕೆ", reply)


class AnotherSizeAsksItsPrice(unittest.TestCase):
    """...9594 got the 25 kVA price and wrote "65kva"; no price came back."""

    def test_a_listed_size_gets_its_own_price(self):
        f, reply = turn("63kva")
        self.assertEqual(f["capacity_kva"], 63)
        self.assertIn("₹1,90,000 + GST", reply)
        self.assertIn("₹2,50,000 + GST", turn("100 kva transformer")[1])

    def test_65_is_our_63(self):
        """Owner 2026-10-12: "65 kva andru 65 andru 63 kva anta arta madkibeku"."""
        for t in ("65kva", "65 KVA", "65 kv", "65"):
            f, reply = turn(t)
            self.assertEqual((f["capacity_kva"], f["quantity"]), (63, None), t)
            self.assertIn("*63 kVA 5 Star* — *₹1,90,000 + GST*", reply)
        self.assertEqual(b.capacity_kva("65 kva"), 63)
        self.assertEqual(turn("65", (), {"location": "Hangal"})[0]["capacity_kva"], 63)   # no size on record
        self.assertEqual(turn("65", (b.AWAITING_QUANTITY,))[0]["quantity"], 65)          # a count when a count was asked

    def test_only_65_no_other_rounding(self):
        self.assertEqual([b.capacity_kva(t) for t in ("60 kva", "64 kva", "75 kva", "100 kva")], [60, 64, 75, 100])

    def test_an_unlisted_size_gets_the_whole_list(self):
        _, reply = turn("75kva")
        for price in ("₹85,000", "₹1,90,000", "₹2,50,000", "₹4,95,000"):
            self.assertIn(price, reply)

    def test_the_size_already_held_is_not_news(self):
        f, reply = turn("25kva")
        self.assertFalse(f["asked_price"])

    def test_a_bare_catalogue_number_is_a_size_not_a_count(self):
        f, reply = turn("100")
        self.assertEqual((f["capacity_kva"], f["quantity"]), (100, None))
        self.assertIn("₹2,50,000 + GST", reply)

    def test_but_a_count_when_a_count_was_asked(self):
        self.assertEqual(turn("100", (b.AWAITING_QUANTITY,))[0]["quantity"], 100)
        self.assertEqual(turn("3")[0]["quantity"], 3)
        self.assertEqual(turn("100 units")[0]["quantity"], 100)


class TheCannedOpenerIsAGreeting(unittest.TestCase):
    """...9370 sent WhatsApp's prefilled "Hello from Asthra DigiTech! How can
    we empower your brand's digital journey toda"."""

    def test_read_as_hello(self):
        f, reply = turn("Hello from Asthra DigiTech! How can we empower your brand’s digital journey toda")
        self.assertFalse(b.should_ask_model(f, K))
        self.assertIn("ನಮಸ್ಕಾರ", reply)


class BedaAsPeopleTypeIt(unittest.TestCase):
    """...0983 answered the price message with "ನಮಗೆಬೆಡಾ"; it was stored as
    the delivery place and the next question was asked."""

    def test_spellings_of_no(self):
        for t in ("ನಮಗೆಬೆಡಾ", "ನಮಗೆ ಬೇಡ", "ಬೆಡ", "ಬೇಡಾ ಸರ್", "namage beda", "nange bedaa", "ಬ್ಯಾಡ"):
            f, reply = turn(t, (b.AWAITING_DELIVERY,))
            self.assertTrue(f["declined"], t)
            self.assertIsNone(f["delivery_location"], t)
            self.assertNotIn("ಉದ್ದೇಶ", reply)
            self.assertEqual(b.awaiting_after(f, K), ())

    def test_places_and_things_not_wanted_are_not_a_refusal(self):
        for t in ("ಬೇಡರಹಳ್ಳಿ", "Bedarahalli", "kamba beda", "installation beda", "beda andre yake"):
            self.assertFalse(turn(t, (b.AWAITING_DELIVERY,))[0]["declined"], t)
