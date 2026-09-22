"""A measurement is not a count.

THE DEFECT, from production on 2026-09-22. Two real customers had a figure
they never offered as a quantity recorded as the quantity:

    "Hiladahalli. Ranibennur. Agriculture purpus. 25 kv. 15 hp"
        -> quantity 15.  "15 hp" is the rating of the pump the transformer
           will feed. One transformer was wanted.

    "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"
        -> quantity 5.   "5 ಕೀ ಮೀ" is how far the village is from Chelur.
           The customer was describing WHERE, and was recorded as ordering
           five transformers.

Quantity is the figure a quotation is multiplied by, which makes this the
most expensive misread this module can make.

WHY THE FIX IS NARROW. The obvious fix — require the unit word — was tried
first and rejected: it broke 16 existing tests, and inspecting them showed
why. A customer asked "how many?" answers "2", and that bare 2 is a real
order. Requiring "units" discards genuine quantities to catch invented ones.

So the figure is rejected only when the text immediately after it names a
unit that cannot be a count. "15 hp" is a rating; "15 units" is still
fifteen; "100kv 2" is still two.
"""
import unittest
import bairavi as b


class AMeasurementIsNotACount(unittest.TestCase):
    """The two production messages, verbatim."""

    def test_a_motor_rating_is_not_a_quantity(self):
        self.assertIsNone(b.parse_followup(
            "Hiladahalli. Ranibennur. Agriculture purpus. \n25 kv. 15 hp"
        )["quantity"])

    def test_a_distance_in_kannada_is_not_a_quantity(self):
        self.assertIsNone(b.parse_followup(
            "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"
        )["quantity"])

    def test_land_area_is_not_a_quantity(self):
        """An agricultural enquiry states acreage. It is not an order size."""
        self.assertIsNone(b.parse_followup("5 acre land, 25 kva")["quantity"])
        self.assertIsNone(b.parse_followup("2 ಎಕರೆ")["quantity"])

    def test_electrical_units_are_not_a_quantity(self):
        for text in ("25 kva", "100 kv", "63 kw", "440 volt", "3 phase"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text)["quantity"])

    def test_the_unit_may_be_separated_by_punctuation(self):
        """"25 kv." and "25-kv" are the same statement as "25 kv"."""
        for text in ("15 . hp", "15- hp", "15.hp"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text)["quantity"])


class AGenuineQuantityStillReads(unittest.TestCase):
    """The fix must not be paid for with lost orders."""

    def test_a_bare_number_is_still_a_quantity(self):
        self.assertEqual(b.parse_followup("100kv 2")["quantity"], 2)
        self.assertEqual(b.parse_followup("1")["quantity"], 1)

    def test_an_explicit_unit_word_is_still_a_quantity(self):
        for text, want in (("3 units", 3), ("5 nos", 5), ("4 pcs", 4),
                           ("2 pieces", 2), ("250kv 3 units", 3)):
            with self.subTest(text=text):
                self.assertEqual(b.parse_followup(text)["quantity"], want)

    def test_a_rating_and_a_count_in_one_message(self):
        """The rating is skipped and the count is still found after it."""
        self.assertEqual(b.parse_followup("10 hp pump, 2 units")["quantity"], 2)

    def test_the_count_may_precede_the_rating(self):
        self.assertEqual(b.parse_followup("2 units for 10 hp pump")["quantity"], 2)

    def test_the_unit_must_FOLLOW_the_figure_immediately(self):
        """The measurement is looked for at the START of what follows, not
        anywhere in it.

        Widening `startswith` to a substring test throws away real
        quantities: here the "hp" belongs to the pump three words later, and
        a substring test would reject the 2 and then reject the 10 as well,
        leaving no quantity at all. This case is what pins the distinction --
        an earlier one stopped pinning it once a stated unit word became
        authoritative.
        """
        self.assertEqual(
            b.parse_followup("2 transformers for 10 hp pump")["quantity"], 2)
        self.assertEqual(b.parse_followup("2, 10 hp pump")["quantity"], 2)


class TheKannadaUnitWordsNowActuallyMatch(unittest.TestCase):
    """A latent bug the measurement table exposed.

    Python's \\b is a \\w/non-\\w transition, and the Kannada virama U+0CCD --
    the final character of "ಯುನಿಟ್" -- is a combining mark, which is not \\w.
    The old pattern ended in \\b, so neither Kannada unit word could ever
    match. It went unnoticed because the suffix was optional and the bare
    number matched instead.
    """

    def test_the_kannada_unit_word_matches(self):
        self.assertEqual(b.parse_followup("2 ಯುನಿಟ್")["quantity"], 2)

    def test_the_kannada_plural_matches(self):
        """Kannada inflects; the stem is matched permissively on purpose."""
        self.assertEqual(b.parse_followup("2 ಯುನಿಟ್ಗಳು")["quantity"], 2)

    def test_naga_is_read_as_a_unit_word(self):
        self.assertEqual(b.parse_followup("5 ನಗ")["quantity"], 5)

    def test_naga_must_be_a_whole_word_in_the_pattern(self):
        """"ನಗ" is a prefix of "ನಗರ" (city), which appears in real addresses,
        so the alternative carries a lookahead.

        ASSERTED ON THE PATTERN, not on a parse. A first attempt asserted
        that "ಬೆಂಗಳೂರು ನಗರ" yields no quantity -- which is true, but true
        for the wrong reason: there is no digit in it, so the regex never
        reaches the lookahead, and the assertion also held with the
        lookahead removed. The parse cannot distinguish the two, because the
        unit word is optional and a bare figure matches either way; only the
        pattern can.
        """
        self.assertIn(r"ನಗ(?![\u0C80-\u0CFF])", b._QTY_RE.pattern)

    def test_the_kannada_vocabulary_is_present_in_the_pattern(self):
        """ASSERTED ON THE PATTERN, and it has to be.

        Removing "ಯುನಿಟ್" from the alternation is an EQUIVALENT MUTANT: with
        the unit word optional, the bare figure matches instead, and the
        measurement test then reads the text after the figure -- which is
        "ಯುನಿಟ್" itself, never a measurement. So every input gives the same
        answer with the alternative present or absent, and no parse can tell
        them apart. Proven by mutation, not assumed.

        The vocabulary is still pinned, because it stops being decorative
        the moment the unit word becomes mandatory or the measurement table
        grows a Kannada entry that could follow a figure.
        """
        self.assertIn("ಯುನಿಟ್", b._QTY_RE.pattern)

    def test_the_regex_carries_a_named_group(self):
        """Guards the alternation shape the lookaheads depend on."""
        self.assertIn("n", b._QTY_RE.groupindex)


class AnExplicitUnitWordWins(unittest.TestCase):
    """A defect found by mutation testing, in the fix itself.

    The measurement test originally ran on every match. So when the customer
    named the unit themselves and a measurement happened to follow it, the
    match consumed the unit word and the test then read the measurement
    AFTER it -- discarding a quantity the customer had stated out loud.
    """

    def test_a_stated_kannada_unit_survives_a_following_measurement(self):
        self.assertEqual(b.parse_followup("2 ಯುನಿಟ್ ಕೀ ಮೀ")["quantity"], 2)
        self.assertEqual(b.parse_followup("15 ಯುನಿಟ್ hp")["quantity"], 15)

    def test_a_stated_english_unit_survives_a_following_measurement(self):
        self.assertEqual(b.parse_followup("2 units 10 hp")["quantity"], 2)
        self.assertEqual(b.parse_followup("3 nos 440 volt")["quantity"], 3)

    def test_a_bare_figure_gets_no_such_protection(self):
        """The asymmetry is the whole point: the guard exists for figures the
        customer never offered as a count."""
        self.assertIsNone(b.parse_followup("2 hp")["quantity"])
        self.assertIsNone(b.parse_followup("2 ಕೀ ಮೀ")["quantity"])


class TheTableIsVocabularyNotGeography(unittest.TestCase):
    """AC-04 and the standing constraint: no place names are introduced."""

    def test_every_entry_is_a_unit_of_measurement(self):
        self.assertTrue(all(isinstance(u, str) and u for u in b._MEASUREMENT_UNIT))

    def test_the_two_units_from_production_are_present(self):
        self.assertIn("hp", b._MEASUREMENT_UNIT)
        self.assertIn("ಕೀ ಮೀ", b._MEASUREMENT_UNIT)

    def test_the_capacity_units_are_present(self):
        """They replace the ad-hoc five-character span test for "kv"."""
        self.assertIn("kv", b._MEASUREMENT_UNIT)
        self.assertIn("kva", b._MEASUREMENT_UNIT)

    def test_the_span_hack_is_gone(self):
        """The measurement table is the single place this rule lives."""
        import inspect
        src = inspect.getsource(b.parse_followup)
        self.assertIn("_MEASUREMENT_UNIT", src)
        self.assertNotIn('"kv" in span', src)


class QuantityStaysTheOwnersDefault(unittest.TestCase):
    """The 2026-09-17 ruling is untouched: unstated quantity is ONE, and the
    parse still reports None so the owner alert can say it was assumed."""

    def test_a_missing_quantity_is_still_none_not_one(self):
        self.assertIsNone(b.parse_followup("agriculture")["quantity"])

    def test_the_default_is_unchanged(self):
        self.assertEqual(b.DEFAULT_QUANTITY, 1)

    def test_a_rejected_measurement_falls_back_to_the_default(self):
        """The recoverable outcome. A blank quantity becomes one unit and a
        human confirms; an invented fifteen goes out in a quotation."""
        parsed = b.parse_followup("15 hp")
        self.assertIsNone(parsed["quantity"])
        qty, assumed = b.effective_quantity(parsed)
        self.assertEqual(qty, b.DEFAULT_QUANTITY)
        # The flag is the point: the owner alert must say the one was
        # assumed, not stated, so a salesperson confirms before quoting.
        self.assertTrue(assumed)

    def test_a_real_quantity_is_not_reported_as_assumed(self):
        qty, assumed = b.effective_quantity(b.parse_followup("2 units"))
        self.assertEqual(qty, 2)
        self.assertFalse(assumed)


if __name__ == "__main__":
    unittest.main()
