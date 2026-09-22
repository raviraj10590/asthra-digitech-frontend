"""Record the address the customer gave, in full, and never lose the district.

THE OWNER'S RULING, 2026-09-22, after reading that day's conversations:
"grahakara vilasa dakshalisu mukhyavagi jille missagabrdu full adress kotre
full dakshalisu" -- record the customer's address; above all the district
must not be missed; if they give a full address, record it in full.

WHAT PRODUCTION DID INSTEAD. Four real answers that day:

    "ತುಮಕೂರು .ಜಿಲ್ಲೆ . ಗುಬ್ಬಿ ..ತಾಲ್ಲೂಕು... ಚೇಳೂರು ಹೋಬಳಿ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"
        113 characters. District, taluk, hobli, village. Rejected on length.
        The customer had already given it once; the bot asked a fifth time.

    "Kadaba near tumkur / Agriculture use / 1 unit"
        Rejected: it carries a purpose and a quantity too, so the whole
        message was discarded -- address included.

    "Houdu"   (ಹೌದು, in Latin letters)   -> stored AS the delivery address
    "ಸೇಮ್"     ("same", in Kannada)       -> stored AS the delivery address

The last two are the same bug twice: each word was already recognised, but
only in the other script.
"""
import unittest
import bairavi as b

ASKED = (b.AWAITING_DELIVERY,)


def delivery(text):
    return b.parse_followup(text, awaiting=ASKED)["delivery_location"]


def same(text):
    return b.parse_followup(text, awaiting=ASKED)["delivery_same"]


class AFullAddressIsRecordedInFull(unittest.TestCase):

    def test_the_production_kannada_address_is_verbatim(self):
        text = ("ತುಮಕೂರು .ಜಿಲ್ಲೆ .              ಗುಬ್ಬಿ ..ತಾಲ್ಲೂಕು..."
                "                              ಚೇಳೂರು ಹೋಬಳಿ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ")
        got = delivery(text)
        self.assertEqual(got, text.strip())

    def test_the_district_is_never_lost(self):
        """The owner named this explicitly, so it is asserted explicitly."""
        for text in ("ತುಮಕೂರು ಜಿಲ್ಲೆ, ಗುಬ್ಬಿ ತಾಲ್ಲೂಕು, ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ",
                     "Tumkur district Gubbi taluk Chelur hobli"):
            with self.subTest(text=text):
                got = delivery(text)
                self.assertIsNotNone(got)
                self.assertTrue("ಜಿಲ್ಲೆ" in got or "district" in got)

    def test_a_relative_address_survives(self):
        """"5 km from Chelur, Kulumegudlu village" is how the place is
        actually described. The distance is not a quantity and the "ಇಂದ" is
        not an origin statement."""
        text = "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"
        self.assertEqual(delivery(text), text)

    def test_length_alone_never_rejects(self):
        for text in ("Hubli Dharwad Bijapur Bidar Gadag",
                     "Gandhinagar Ahmedabad Gandhinagar Ahmedabad"):
            with self.subTest(text=text):
                self.assertEqual(delivery(text), text)


class AMixedMessageKeepsTheAddressPart(unittest.TestCase):
    """A customer answers several questions at once. The other extractors
    own the other fields; discarding the whole message loses the address."""

    def test_address_purpose_and_quantity_in_one_message(self):
        self.assertEqual(
            delivery("Kadaba near tumkur \nAgriculture use\n1 unit"),
            "Kadaba near tumkur")

    def test_address_and_purpose_in_one_message(self):
        self.assertEqual(delivery("Kadur (T) Turuvanahalli \nAgriculture"),
                         "Kadur (T) Turuvanahalli")

    def test_the_other_fields_are_still_read_from_the_same_message(self):
        """Keeping the address must not cost the purpose or the quantity."""
        parsed = b.parse_followup("Kadaba near tumkur \nAgriculture use\n1 unit",
                                  awaiting=ASKED)
        self.assertEqual(parsed["delivery_location"], "Kadaba near tumkur")
        self.assertEqual(parsed["application"], "AGRICULTURE")
        self.assertEqual(parsed["quantity"], 1)

    def test_a_motor_rating_is_not_kept_as_part_of_the_address(self):
        """"15 hp" passes every other filter -- correctly not a quantity, and
        it does contain a letter -- so it leaked into the address until a
        bare measurement was excluded outright."""
        self.assertEqual(
            delivery("Hiladahalli. Ranibennur. Agriculture purpus. \n25 kv. 15 hp"),
            "Hiladahalli, Ranibennur")

    def test_a_numbered_street_is_still_a_place(self):
        """The measurement exclusion must not eat house and street numbers.

        The first version of this test only checked that "Vidyanagar"
        survived, which a mutation rejecting EVERY segment that starts with a
        figure also satisfied -- the second segment carried it. So the
        address that begins with a figure and has nothing after it to fall
        back on is the one that pins the rule.
        """
        self.assertIn("Vidyanagar", delivery("2nd cross, Vidyanagar"))
        self.assertEqual(delivery("1st main road Rajajinagar"),
                         "1st main road Rajajinagar")

    def test_a_standalone_house_number_is_a_KNOWN_LIMITATION(self):
        """Documented, not asserted as desirable.

        A readable quantity anywhere in the text disqualifies it as a place,
        so an address whose figure stands alone is rejected and the question
        is asked again. Narrowing the rule to "the text is nothing but a
        figure" was tried and reverted -- it made "೧ beku" ("I want 1") read
        as the delivery address, which is the AC-07 confidently-wrong field
        this module exists to avoid.

        The trade is deliberate: a re-ask costs one message, a wrong address
        costs a delivery. This test exists so the limitation is visible and
        the next person does not rediscover it as a surprise.
        """
        self.assertIsNone(delivery("12 Hosur Road"))
        self.assertIsNone(delivery("No.5 Gandhi Road"))

    def test_a_full_stop_inside_a_token_does_not_split_it(self):
        """A full stop separates only when whitespace or the end follows it.

        Customers write "Gubbi Tq.Chelur" -- the real 2026-09-22 form answer
        was "Tumkur ..Gubbi.Tq. Chelur". Splitting on every full stop tears
        that into pieces and rejoins them with commas, rewriting an address
        the owner's ruling says to record as given.
        """
        self.assertEqual(delivery("Gubbi Tq.Chelur, Agriculture use"),
                         "Gubbi Tq.Chelur")

    def test_a_stated_unit_word_may_be_glued_to_the_figure(self):
        """The glued-figure rule applies only when NO unit word was stated.
        "3units" is three units; the absence of a space is a typing habit,
        not a change of meaning."""
        self.assertEqual(b._read_quantity("3units"), 3)
        self.assertEqual(b._read_quantity("5nos"), 5)

    def test_a_glued_figure_is_not_a_quantity_so_ordinals_survive(self):
        """The half of the house-number problem that IS solved: a figure
        written without a space before a word is an ordinal or a house
        number, never a count."""
        self.assertIsNone(b._read_quantity("1st main road"))
        self.assertIsNone(b._read_quantity("2nd cross"))
        self.assertEqual(b._read_quantity("2 units"), 2)


class AConfirmationIsNotAnAddress(unittest.TestCase):
    """Both spellings of both words, in both scripts."""

    def test_houdu_in_latin_letters(self):
        self.assertIsNone(delivery("Houdu"))
        self.assertTrue(same("Houdu"))

    def test_same_in_kannada_letters(self):
        self.assertIsNone(delivery("ಸೇಮ್"))
        self.assertTrue(same("ಸೇಮ್"))

    def test_the_spellings_that_already_worked_still_work(self):
        for word in ("same", "ಹೌದು", "ಅದೇ", "same place"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word))
                self.assertTrue(same(word))


class ASiteTypeIsNotASite(unittest.TestCase):

    def test_layout_alone_is_not_an_address(self):
        """A real answer on 2026-09-22, recorded as the delivery address."""
        self.assertIsNone(delivery("layout"))

    def test_the_other_site_types_are_not_addresses(self):
        for word in ("site", "plot", "farm", "land", "village",
                     "ಜಮೀನು", "ಗ್ರಾಮ", "ಹಳ್ಳಿ"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_a_site_type_INSIDE_a_place_name_still_reads(self):
        """The comparison is exact for exactly this reason."""
        for text in ("Vidyaranyapura layout", "Kulumegudlu ಗ್ರಾಮ",
                     "Sahakar Nagar layout"):
            with self.subTest(text=text):
                self.assertEqual(delivery(text), text)


class PositionDecidesALocativeWord(unittest.TestCase):
    """"from" and "near" build addresses and also introduce origins. Which
    one it is depends on where the word sits."""

    def test_a_leading_locative_is_an_origin(self):
        for text in ("from Gujarat", "near tumkur", "ಇಂದ ಚೇಳೂರು"):
            with self.subTest(text=text):
                self.assertIsNone(delivery(text), text)

    def test_an_internal_locative_is_part_of_the_address(self):
        for text in ("Kadaba near tumkur", "Chelur inda 5 km Kulumegudlu"):
            with self.subTest(text=text):
                self.assertIsNotNone(delivery(text), text)

    def test_a_pronoun_origin_statement_is_still_rejected(self):
        for text in ("I am from Gujarat", "we are from Gujarat",
                     "ನಾನು ಗುಜರಾತ್", "my place is Gujarat"):
            with self.subTest(text=text):
                self.assertIsNone(delivery(text), text)


class TheReviewBlockerStaysClosed(unittest.TestCase):
    """The length caps are gone, so every one of these must be rejected by
    the semantic filters alone. This is the set that shipped as d201cdc; if
    removing the caps reopened any of it, that is a regression."""

    def test_none_of_these_is_ever_an_address(self):
        for word in ("ತಕ್ಷಣ", "urgent", "immediate", "soon", "asap", "later",
                     "call me", "call back", "ಕರೆ ಮಾಡಿ", "call", "send",
                     "ಕಳಿಸಿ", "sir", "madam", "anna", "hello", "hi",
                     "idk", "dunno", "ಗೊತ್ತಿಲ್ಲ", "not sure", "You mad",
                     "ok", "ಸರಿ", "thanks", "no", "yes", "123", "👍", "",
                     "Gujarat price?", "Gujarat?"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), repr(word))

    def test_a_long_sentence_mentioning_a_place_is_still_not_an_address(self):
        self.assertIsNone(delivery(
            "our line is far from the town so we need a TC in Gujarat"))


class StillNoGeography(unittest.TestCase):
    """AC-04 and the standing constraint: no gazetteer, no transliteration,
    no canonical form. Every rejection is another field's answer or a
    linguistic category."""

    def test_no_place_name_was_added_to_any_table(self):
        tables = (b._NOT_A_PLACE_EXACT + b._NOT_A_PLACE_PHRASE
                  + b._NOT_A_BARE_ANSWER + b._LOCATIVE_PREFIX
                  + b._ACKNOWLEDGEMENTS + b._SAME_PLACE)
        for place in ("tumkur", "bengaluru", "bangalore", "mysore", "mysuru",
                      "gubbi", "chelur", "kadaba", "karnataka", "gujarat",
                      "ತುಮಕೂರು", "ಬೆಂಗಳೂರು", "ಕರ್ನಾಟಕ"):
            with self.subTest(place=place):
                self.assertNotIn(place, tables)

    def test_the_answer_is_never_rewritten(self):
        """Mysuru stays Mysuru and Mysore stays Mysore."""
        for text in ("Mysuru", "Mysore", "Bengaluru", "Bangalore"):
            with self.subTest(text=text):
                self.assertEqual(delivery(text), text)

    def test_no_network_call_and_no_constituencies_table(self):
        import inspect
        src = inspect.getsource(b._is_place_like) + inspect.getsource(
            b._bare_delivery_answer)
        for forbidden in ("constituenc", "requests", "httpx", "urlopen",
                          "supabase"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
