"""Last-10 review, 2026-09-24. Four real answers the bot misread.

  ...6665  "Agreeculture"            -> stored as the DELIVERY address, purpose asked again
  ...6665  "25" (25 kVA already known, purpose awaited) -> "25 units"
  ...2655  "Agriculture / Single unit" -> delivery address "Single unit"
  ...1424  "1. near 3km. / 2. Agriculture. / 3. 25kv" -> "1 unit" from the list number
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

KNOWN = {"location": "bhalki", "capacity_kva": 25}


def read(text, awaiting=(), known=KNOWN):
    return b.parse_followup(text, awaiting, known=known)


class MisspeltPurpose(unittest.TestCase):
    def test_agreeculture_is_agriculture_not_an_address(self):
        r = read("Agreeculture", (b.AWAITING_DELIVERY,))
        self.assertEqual(r["application"], "AGRICULTURE")
        self.assertIsNone(r["delivery_location"])

    def test_other_by_ear_spellings(self):
        for t in ("agricalcher", "agriculcher", "irigation", "industrail", "constraction", "comercial"):
            self.assertIsNotNone(read(t)["application"], t)

    def test_place_names_do_not_become_a_purpose(self):
        for t in ("Kallambella", "Hosahalli", "Chitradurga", "Channagiri", "Turuvekere", "Karejavanahalli"):
            self.assertIsNone(read(t, (b.AWAITING_DELIVERY,))["application"], t)

    def test_short_words_are_never_fuzzed(self):
        self.assertIsNone(b._application_of("indus"))

    def test_edit_distance(self):
        self.assertEqual(b._edit_distance("agreeculture", "agriculture", 2), 2)
        self.assertEqual(b._edit_distance("kitten", "sitting", 5), 3)
        self.assertGreater(b._edit_distance("abc", "abcdefgh", 2), 2)


class RepeatedCapacity(unittest.TestCase):
    def test_bare_kva_again_is_not_a_quantity(self):
        self.assertIsNone(read("25", (b.AWAITING_PURPOSE,))["quantity"])

    def test_with_a_unit_word_it_still_counts(self):
        self.assertEqual(read("25 units", (b.AWAITING_PURPOSE,))["quantity"], 25)

    def test_a_different_figure_still_counts(self):
        self.assertEqual(read("3", (b.AWAITING_QUANTITY,))["quantity"], 3)

    def test_without_a_known_capacity_nothing_changes(self):
        self.assertEqual(read("25", (b.AWAITING_QUANTITY,), known={})["quantity"], 25)


class WordQuantity(unittest.TestCase):
    def test_single_unit_is_one_not_an_address(self):
        r = read("Agriculture \nSingle unit", (b.AWAITING_DELIVERY,))
        self.assertEqual(r["quantity"], 1)
        self.assertEqual(r["application"], "AGRICULTURE")
        self.assertIsNone(r["delivery_location"])

    def test_number_words_with_a_unit(self):
        for t, n in (("one unit", 1), ("ondu tc", 1), ("ಒಂದು ಟಿಸಿ", 1), ("two transformers", 2), ("ಎರಡು ಯುನಿಟ್", 2)):
            self.assertEqual(read(t, known={})["quantity"], n, t)

    def test_one_alone_is_not_a_count(self):
        self.assertIsNone(read("one more doubt", known={})["quantity"])

    def test_single_inside_a_word_is_not_a_count(self):
        self.assertIsNone(read("singlephase", known={})["quantity"])


class NumberedList(unittest.TestCase):
    def test_list_numbers_are_not_quantities(self):
        r = read("1. near 3km.\n2. Agriculture.\n3. 25kv", (b.AWAITING_DELIVERY,))
        self.assertIsNone(r["quantity"])
        self.assertEqual(r["application"], "AGRICULTURE")
        self.assertEqual(r["capacity_kva"], 25)

    def test_paren_marker(self):
        self.assertIsNone(read("1) agriculture", known={})["quantity"])

    def test_a_real_count_on_a_list_line_still_counts(self):
        self.assertEqual(read("1. 2 units\n2. agriculture", known={})["quantity"], 2)

    def test_a_count_mid_sentence_still_counts(self):
        self.assertEqual(read("need 2 units", known={})["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
