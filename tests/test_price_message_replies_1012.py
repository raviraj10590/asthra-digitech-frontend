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


class QuestionsAfterThePrice(unittest.TestCase):
    """More replies to the price message, 2026-10-12 evening."""
    K63 = {"capacity_kva": 63, "location": "thirthalli", "name": "Madhan", "application": "AGRICULTURE",
           "delivery_same": True, "callback": b.CALLBACK_NOW}

    def test_location_asks_where_we_are(self):
        """...8578: "Location" got the call-time menu."""
        for t in ("Location", "location?", "address sir", "nimma location elli", "address kalisi"):
            f, reply = turn(t, (), self.K63)
            self.assertEqual(f["customer_question"], b.QUESTION_WHO, t)
            self.assertIn("Kadaba, ದಕ್ಷಿಣ ಕನ್ನಡ", reply)

    def test_their_own_location_is_still_theirs(self):
        f, _ = turn("location hubli", (b.AWAITING_DELIVERY,), {"capacity_kva": 25})
        self.assertIsNone(f["customer_question"])
        self.assertIn("hubli", f["delivery_location"])

    def test_is_there_a_smaller_one_gets_sizes_and_prices(self):
        """...5389: "63kva githa kadme ellva sir" was told the engineer would call."""
        f, reply = turn("63kva githa kadme ellva sir", (), self.K63)
        self.assertEqual(f["customer_question"], b.QUESTION_RANGE)
        for line in ("25 kVA 4 Star* — *₹85,000 + GST", "100 kVA 5 Star* — *₹2,50,000 + GST"):
            self.assertIn(line, reply)

    def test_details_as_typed(self):
        """...5389: "ditels heli" got no answer."""
        _, reply = turn("ditels heli", (), self.K63)
        self.assertTrue(reply.startswith("📋"))
        self.assertIn("₹1,90,000 + GST", reply)

    def test_a_discount_request_is_not_a_size_question(self):
        f, reply = turn("price kadime madi", (), self.K63)
        self.assertNotEqual(f["customer_question"], b.QUESTION_RANGE)
        self.assertIn("sales ತಂಡ", reply)


class NotEveryMessageIsAnEnquiry(unittest.TestCase):
    """2026-10-13, the day after the price message."""
    CHAIN = ("ಪ್ರಧಾನಿ ಮೋದಿ: ದಸರಾ ಸಂದರ್ಭದಲ್ಲಿ ಎಲ್ಲಾ ಭಾರತೀಯ ನಾಗರಿಕರಿಗೆ ₹10,000 ಮೊತ್ತದ ನಗದು ನೆರವು\n"
             "ಈ ವರ್ಷದ ದಸರಾ ಆಚರಣೆಯ ಭಾಗವಾಗಿ, ಪ್ರಧಾನಿ ಮೋದಿ ಅವರು ಎಲ್ಲಾ ಭಾರತೀಯ ನಾಗರಿಕರಿಗೆ ₹10,000 ಮೊತ್ತದ "
             "ನಗದು ನೆರವು ನೀಡಲು ಅನುಮೋದಿಸಿದ್ದಾರೆ.\nಪಡೆಯುವ ವಿಧಾನ: ಕೆಳಗಿನ ಲಿಂಕ್ ಮೇಲೆ ಕ್ಲಿಕ್ ಮಾಡಿ https://example-gift.xyz/abc")

    def test_a_forwarded_chain_message_is_not_ten_units(self):
        """...5212 forwarded this and got "10 units ಗಮನಿಸಿದ್ದೇವೆ" and a price."""
        for awaiting in ((), (b.AWAITING_DELIVERY,), (b.AWAITING_QUANTITY,)):
            f = b.parse_followup(self.CHAIN, awaiting, K)
            self.assertIsNone(f["quantity"])
            self.assertIsNone(f["delivery_location"])
            self.assertTrue(b.is_silent_ack(f, awaiting))

    def test_a_long_real_enquiry_with_a_link_is_still_read(self):
        text = "nanna site location https://maps.app.goo.gl/xyz 63 kva transformer beku " + "hubli hattira " * 20
        f = b.parse_followup(text, (), K)
        self.assertFalse(f.get("forwarded"))
        self.assertEqual(f["capacity_kva"], 63)

    def test_money_is_not_a_count(self):
        for t in ("budget ₹10,000 ide", "Rs 5000 advance kodtini", "2,00,000 alva"):
            self.assertIsNone(turn(t)[0]["quantity"], t)
        self.assertEqual(turn("10 units beku")[0]["quantity"], 10)

    def test_a_reaction_gets_no_reply(self):
        """...7377 reacted 🙏 twice and was sent the generic receipt four times."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py"), encoding="utf-8").read()
        branch = src[src.index('elif msg_type == "reaction":'):]
        branch = branch[:branch.index("else:")]
        self.assertIn("self._ok(); return", branch)
        for forbidden in ("send_text(", "notify_owner("):
            self.assertNotIn(forbidden, branch)


class LastTwentyOfOctober24(unittest.TestCase):
    """Review of the last 20 customer messages, 2026-10-24."""

    def test_a_budget_is_not_a_count(self):
        """...9365 wrote "May be 45 k range" and was told "45 units ಗಮನಿಸಿದ್ದೇವೆ"."""
        for t in ("May be 45 k range", "45k", "45 thousand", "budget 50k", "2 lakh", "1.5 lakh ge kodi"):
            f, reply = turn(t)
            self.assertIsNone(f["quantity"], t)
            self.assertTrue(f["asked_discount"], t)
            self.assertNotIn("units", reply)

    def test_our_sizes_with_a_k_are_still_sizes(self):
        for t, kva in (("63k", 63), ("100 k", 100), ("250k", 250)):
            f, _ = turn(t)
            self.assertFalse(f.get("asked_discount"), t)
            self.assertEqual((f["capacity_kva"], f["quantity"]), (kva, None), t)

    def test_counts_are_still_counts(self):
        self.assertEqual(turn("10 units beku")[0]["quantity"], 10)
        self.assertEqual(turn("2 beku")[0]["quantity"], 2)

    def test_yes_it_is_from_a_voice_note(self):
        """...3316's voice note came through as "ಸರಿ / ದೆ"; the place question was asked again."""
        for t in ("ಸರಿ\nದೆ", "ಸರಿ ದೆ", "ಸರಿ ಅದೆ", "ok ide", "ಸರಿ ಇದೆ"):
            f, reply = turn(t, (b.AWAITING_DELIVERY,))
            self.assertTrue(f["delivery_same"], t)
            self.assertIsNone(f["delivery_location"], t)

    def test_a_place_starting_with_the_same_letters_is_still_a_place(self):
        f, _ = turn("ಸರಿ ದೆಹಲಿ", (b.AWAITING_DELIVERY,))
        self.assertFalse(f["delivery_same"])


class LastTwentyCustomers1024(unittest.TestCase):
    """Analysis of the last 20 customers, 19–24 Oct 2026 (owner: "maadu")."""
    K = {"capacity_kva": 63, "location": "tarikere", "name": "Nagaraj Koppala", "delivery_same": True,
         "application": "AGRICULTURE"}

    def test_purpose_as_typed(self):
        for t in ("ಕೃಷೀ", "CRUSHY", "Crushy", "Ip", "ip set", "ಐಪಿ ಸೆಟ್"):
            self.assertEqual(b._application_of(t.lower()), "AGRICULTURE", t)
        for t in ("stone crusher", "ಕೃಷ್ಣಾಪುರ", "krishna", "tip top"):
            self.assertIsNone(b._application_of(t.lower()), t)

    def test_a_star_rating_is_not_a_count(self):
        """...9786: "4 star" after the 63 kVA price → "4 units ಗಮನಿಸಿದ್ದೇವೆ"."""
        f, reply = turn("4 star", (), self.K)
        self.assertIsNone(f["quantity"])
        self.assertIn("*25 kVA 4 Star* — *₹85,000 + GST*", reply)
        self.assertIn("*63 kVA 5 Star* — *₹1,90,000 + GST*", reply)

    def test_a_load_is_not_a_count(self):
        """...4779: "Namige 5hp 6 motor run agutta" → "6 units ಗಮನಿಸಿದ್ದೇವೆ"."""
        f, reply = turn("Namige 5hp 6 motor run agutta", (), self.K)
        self.assertIsNone(f["quantity"])
        self.assertIn("engineer", reply)
        self.assertNotIn("units* ಗಮನಿಸ", reply)

    def test_the_engineers_number(self):
        """Owner 2026-10-24: "engineer number share maadu 7349259369" (...4233 said
        "ನಾನೇ ಕಾಲ್ ಮಾಡುತ್ತೇನೆ ಓಕೆ ಬಾಯ್" and got the call menu again)."""
        for t in ("ನಾನೇ ಕಾಲ್ ಮಾಡುತ್ತೇನೆ ಓಕೆ ಬಾಯ್", "engineer number kodi", "nimma number", "I will call you",
                  "number kalisi"):
            f, reply = turn(t, (), self.K)
            self.assertIn("73492 59369", reply, t)
            self.assertNotIn("1️⃣", reply, t)
            self.assertEqual(b.awaiting_after(f, self.K), (), t)

    def test_the_number_is_not_given_where_nobody_asked(self):
        form = ("Hello! I filled out your form and would like to know more about your business.\n\n"
                "Full name: X Y\nPhone number: +919999999999\nನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA")
        for t in (form, "call me", "nanna number 9999999999", "10 units beku"):
            self.assertFalse(turn(t, (), self.K)[0].get("wants_number"), t[:30])

    def test_while_the_owner_is_talking_the_number_is_given_too(self):
        f = b.parse_followup("engineer number kodi", (), self.K)
        act, reply = b.takeover_decision(f, "engineer number kodi", ("ok",), self.K)
        self.assertEqual(act, "answer")
        self.assertIn("73492 59369", reply)


class SolarIsTransformerBusiness(unittest.TestCase):
    """Owner 2026-10-24: "solar sha transformer releted irodu" (...3608's
    "ಮನೆಗೆ ಸೋಲಾರ್ ಕರೆಂಟ್ ಲೈಟಿಗೆ ಬೇಕು" went to Asthra: "digital marketing only")."""

    def test_solar_is_a_bairavi_enquiry(self):
        for t in ("ಮನೆಗೆ ಸೋಲಾರ್ ಕರೆಂಟ್ ಲೈಟಿಗೆ ಬೇಕು.", "solar", "1 MW solar plant", "ಸೋಲಾರ್ ಬಗ್ಗೆ heli"):
            self.assertTrue(b.looks_like_transformer_enquiry(t), t)

    def test_the_opening_reply_says_what_we_make_for_solar(self):
        reply = b.compose_reply(b.parse("ಮನೆಗೆ ಸೋಲಾರ್ ಕರೆಂಟ್ ಲೈಟಿಗೆ ಬೇಕು."))
        self.assertIn(b.SOLAR_LINE_KN, reply)
        self.assertEqual(reply.count(b.SOLAR_LINE_KN), 1)
        for claim in ("panel", "ಪ್ಯಾನೆಲ್", "inverter", "installation ನಮ್ಮಿಂದ"):
            self.assertNotIn(claim, reply)

    def test_no_solar_line_without_solar(self):
        self.assertNotIn(b.SOLAR_LINE_KN, b.compose_reply(b.parse("63 kva beku")))
