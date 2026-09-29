"""Last-10 review, 2026-09-29, replayed through the live code.

  location "Jagadish", name "Jagadish R"   -> "deliver to Jagadish?"
  "Ur from"                                -> "ಧನ್ಯವಾದಗಳು."
  "25 kva price sir" (25 already known)    -> "ಧನ್ಯವಾದಗಳು — 25 kVA ಗಮನಿಸಿದ್ದೇವೆ" + price
  name in Kannada script                   -> not greeted by name at all
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {loc}\n"
        "Full name: {name}\nPhone number: +910000000000\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ")


class TheWholeNameIsNotAPlace(unittest.TestCase):
    def test_the_real_form(self):
        p = b.parse(FORM.format(loc="Jagadish", name="Jagadish R"))
        self.assertIsNone(p["location"])
        self.assertIn("ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು", b.compose_reply(p))

    def test_one_word_of_a_longer_name_is_still_a_place(self):
        for loc, name in (("Shivakumar", "Shivakumar S Ambi"), ("Ambi", "Shivakumar Ambi"),
                          ("Sira", "Ravi Kumar")):
            self.assertEqual(b.parse(FORM.format(loc=loc, name=name))["location"], loc)

    def test_rule(self):
        self.assertTrue(b._is_the_name("Jagadish", "Jagadish R"))
        self.assertTrue(b._is_the_name("ravi kumar", "Ravi Kumar"))
        self.assertFalse(b._is_the_name("Jagadish", "Jagadish Kumar"))


class WhereAreYouFrom(unittest.TestCase):
    K = {"location": "Kadur", "capacity_kva": 25, "application": "AGRICULTURE", "callback": "tomorrow"}

    def test_answered_with_where_we_are(self):
        for t in ("Ur from", "where are you from", "you from which place", "ನೀವು ಎಲ್ಲಿಂದ",
                  "ನೀವು ಎಲ್ಲಿಯವರು", "neevu ellinavru"):
            self.assertEqual(b.customer_question(t), b.QUESTION_WHO, t)
            reply = b.compose_followup_reply(b.parse_followup(t, (), known=self.K), self.K)
            self.assertIn("Kadaba", reply, t)


class RepeatedSizeIsNotThanked(unittest.TestCase):
    def test_the_real_message(self):
        k = {"capacity_kva": 25, "location": "Kadur", "delivery_location": "Kadur"}
        f = b.parse_followup("25 kva price sir", (b.AWAITING_PURPOSE,), known=k)
        reply = b.compose_followup_reply(f, k)
        self.assertNotIn("*25 kVA* ಗಮನಿಸಿದ್ದೇವೆ", reply)
        self.assertIn("₹95,000 + GST", reply)

    def test_a_new_size_is_still_thanked(self):
        k = {"capacity_kva": 25}
        reply = b.compose_followup_reply(b.parse_followup("63 kva", (), known=k), k)
        self.assertIn("63 kVA", reply.split("\n")[0])


class Names(unittest.TestCase):
    def test_invisible_joiners_do_not_become_part_of_the_name(self):
        self.assertEqual(b.display_name("‌ravi‌ kumar"), "Ravi Kumar")

    def test_kannada_names_survive(self):
        self.assertEqual(b.display_name("ಶಿವ ಕುಮಾರ್"), "ಶಿವ ಕುಮಾರ್")
        self.assertEqual(b.display_name("ಮಂಜುನಾಥ ೨೦೨೪"), "ಮಂಜುನಾಥ")

    def test_existing_behaviour(self):
        self.assertEqual(b.display_name("PUNITH SINCHANA 2024"), "Punith Sinchana")
        self.assertEqual(b.display_name("Laxman F Soppadla"), "Laxman Soppadla")
        self.assertEqual(b.display_name(""), "")


if __name__ == "__main__":
    unittest.main()
