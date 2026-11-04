"""Owner 2026-11-04: fix the invented ₹11,498 total, and make the Asthra bot persuade like a
sales expert — honestly. These pin the prompt rules; the stress test checks the model."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test")

import webhook as w  # noqa: E402

P = w.SYSTEM_PROMPT


class Totals(unittest.TestCase):
    def test_the_bot_payment_now_is_the_setup_only(self):
        self.assertIn("starts from the 2ND month", P)
        self.assertIn("ಈಗ ₹9,999, 2ನೇ ತಿಂಗಳಿನಿಂದ ₹1,499", P)
        self.assertIn("never ₹11,498", P)

    def test_page_setup_is_in_the_first_month_only_without_a_page(self):
        self.assertIn("₹2,000 page setup ONLY if they have no page", P)
        self.assertIn("ಮೊದಲ ತಿಂಗಳು ₹8,000, ನಂತರ ₹6,000", P)

    def test_a_sent_quotation_is_final(self):
        self.assertIn("quotation ನಲ್ಲಿರುವ amount ಸರಿ sir", P)


class HonestPersuasion(unittest.TestCase):
    def test_the_techniques_are_there(self):
        for part in ("THEIR GOAL FIRST", "PRICE WITH ITS WHY", "SMALL FIRST STEP", "TWO EASY CHOICES",
                     "BEFORE ASKING THE ADVANCE"):
            self.assertIn(part, P)

    def test_the_lines_it_must_not_cross(self):
        self.assertIn("fake urgency or scarcity", P)
        self.assertIn("invented results", P)
        self.assertIn("Never offer a discount or a lower price yourself", P)
        self.assertIn("never bring up the ₹5,000 minimum yourself", P)

    def test_respectful_address(self):
        self.assertIn("never ಅಣ್ಣಾ", P)


if __name__ == "__main__":
    unittest.main()
