"""The shared language module: what Karnataka customers mean, with no client in it.

Every case here is a real message (live chat or stress test). A new client's bot inherits
all of them on day one — they are the reason it does not start its stress testing from zero.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kannada_understanding as ku  # noqa: E402


class NoClientInside(unittest.TestCase):
    def test_the_module_knows_no_business(self):
        src = open(ku.__file__, encoding="utf-8").read().split('"""', 2)[2]
        for word in ("Bairavi", "Asthra", "transformer", "kVA", "PRICE_LIST", "9,999", "85,000 +"):
            self.assertNotIn(word, _code_only(src), word)


def _code_only(src):
    """The module's code without comments and docstrings (examples may name a live chat)."""
    out = []
    in_doc = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""'):
            if s.count('"""') == 1:
                in_doc = not in_doc
            continue
        if in_doc or s.startswith("#"):
            continue
        out.append(line.split("  #")[0])
    return "\n".join(out)


class Amounts(unittest.TestCase):
    def test_offers(self):
        for t, n in (("25000₹nane kodayhni", 25000), ("₹70,000 ge kodi", 70000), ("70000 aagutta", 70000),
                     ("Rs 1,50,000 final", 150000), ("80000/- ge kodi", 80000), ("25000 kodtini", 25000)):
            self.assertEqual(ku.offered_amount(t), n, t)

    def test_not_offers(self):
        for t in ("99727 15155 ಕರೆ ಮಾಡಿ", "+91 98765 43210", "Rs 5000 advance kodtini", "85000 + gst aa?",
                  "2026 ge beku", "Pin code:581102", "10 units beku", "rate eshtu", "Hassan"):
            self.assertIsNone(ku.offered_amount(t), t)

    def test_a_list_price_said_back_is_not_an_offer(self):
        self.assertEqual(ku.offered_amount("85,000 alva"), 85000)
        self.assertIsNone(ku.offered_amount("85,000 alva", list_prices=[85000]))
        self.assertIsNone(ku.offered_amount("100300 aa?", list_prices=[85000]))   # with 18% GST

    def test_indian_grouping(self):
        self.assertEqual((ku.inr(999), ku.inr(85000), ku.inr(250000), ku.inr(1000000)),
                         ("999", "85,000", "2,50,000", "10,00,000"))


class Names(unittest.TestCase):
    def test_the_same_name_in_two_scripts(self):
        self.assertTrue(ku.is_the_name("ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ", "Suresh Lamani"))
        self.assertTrue(ku.is_the_name("Shivakumar sadashiva ambi", "shivakumar s ambi"))

    def test_places_are_not_names(self):
        for place, name in (("ಹುಲಿಕೇರಿ ತಾಂಡ", "Suresh Lamani"), ("Ravi Nagar Hubli", "Ravi Kumar"),
                            ("ಹಾಸನ", "Hassan Ali"), ("Shivakumar", "Shivakumar Patil H")):
            self.assertFalse(ku.is_the_name(place, name), place)


class Calls(unittest.TestCase):
    def test_do_not_call(self):
        for t in ("ಕರೆ madabedi", "call beda", "ಕರೆ ಮಾಡಬೇಡಿ", "don't call", "only whatsapp", "phone beda sir"):
            self.assertTrue(ku.refuses_call(t), t)
        for t in ("call madi", "ಕರೆ ಮಾಡಿ", "ಕರೆ ಮಾಡಿಲ್ಲ", "beda", "price beda"):
            self.assertFalse(ku.refuses_call(t), t)

    def test_call_me(self):
        for t in ("99727 15155 ಕರೆ ಮಾಡಿ ವಿಷಯ ತಿಳಿಸಿ", "call madi", "phone maadi", "call me sir"):
            self.assertTrue(ku.CALL_ME_RE.search(t.lower()), t)
        self.assertFalse(ku.CALL_ME_RE.search("ಕರೆ ಮಾಡಿಲ್ಲ"))

    def test_kannada_digits(self):
        self.assertEqual("೩ units".translate(ku.KANNADA_DIGITS), "3 units")


class Paying(unittest.TestCase):
    def test_will_pay(self):
        for t in ("Kk I will pay", "advance kodtini", "gpay number kodi", "payment details kalisi", "ಪೇಮೆಂಟ್ ಮಾಡ್ತೀನಿ"):
            self.assertTrue(ku.said_will_pay(t), t)

    def test_not_paying(self):
        for t in ("I will not pay now", "pay later maadtini", "payment hege maadodu?", "advance kodalla"):
            self.assertFalse(ku.said_will_pay(t), t)


class Words(unittest.TestCase):
    def test_whole_english_words_and_kannada_stems(self):
        self.assertFalse(ku.mentions("yavaga barate", ("rate",)))
        self.assertTrue(ku.mentions("rates eshtu", ("rate",)))
        self.assertTrue(ku.mentions("ದರವು ಎಷ್ಟು", ("ದರ",)))
        self.assertFalse(ku.mentions("ಆದರೆ ಬೇಕು", ("ದರ",)))


if __name__ == "__main__":
    unittest.main()
