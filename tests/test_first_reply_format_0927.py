"""First-reply format, owner-approved 2026-09-27 (lead ...5839).

  address shown exactly as typed ("TQ Ramdurga  Dist Belgaum  Toranagatti")
  "ತಕ್ಷಣ" on the form not acknowledged
  "distribution transformer" in English inside Kannada
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: {when}\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {loc}\n"
        "Full name: Test Person\nPhone number: +910000000000")
NOW = "A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ"
LATER = "C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ"
REAL_LOC = "TQ Ramdurga  Dist Belgaum  Toranagatti"


class TheRealLead(unittest.TestCase):
    def setUp(self):
        self.p = b.parse(FORM.format(when=NOW, loc=REAL_LOC))
        self.r = b.compose_reply(self.p)

    def test_address_is_tidy(self):
        self.assertIn("ಡೆಲಿವರಿ ಸ್ಥಳ: *Toranagatti, Ramdurga, Belgaum* — ಇದು ಸರಿಯೇ?", self.r)
        self.assertNotIn("  ", self.r)

    def test_stored_place_is_untouched(self):
        self.assertEqual(self.p["location"], REAL_LOC)

    def test_urgency_acknowledged_without_a_date(self):
        self.assertIn("*ತಕ್ಷಣ* ಬೇಕು ಎಂದು ಗಮನಿಸಿದ್ದೇವೆ — ಆದ್ಯತೆ ಮೇಲೆ ಮುಂದುವರಿಸುತ್ತೇವೆ", self.r)
        for w in ("ದಿನ", "ವಾರ", "day", "week", "₹"):
            self.assertNotIn(w, self.r)

    def test_no_english_distribution(self):
        self.assertNotIn("distribution", self.r)


class NotUrgent(unittest.TestCase):
    def test_no_priority_promise(self):
        r = b.compose_reply(b.parse(FORM.format(when=LATER, loc="Sira")))
        self.assertNotIn("ಆದ್ಯತೆ", r)
        self.assertIn("*63 kVA* ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ವಿಚಾರಣೆ ನಮಗೆ ತಲುಪಿದೆ", r)
        self.assertIn("ಡೆಲಿವರಿ ಸ್ಥಳ: *Sira* — ಇದು ಸರಿಯೇ?", r)


class PlaceDisplay(unittest.TestCase):
    def test_reordered_only_when_both_labels_are_clear(self):
        for typed, shown in (
            (REAL_LOC, "Toranagatti, Ramdurga, Belgaum"),
            ("Toranagatti Tq Ramdurga Dist Belgaum", "Toranagatti, Ramdurga, Belgaum"),
            ("Hosur, Taluk Sira, District Tumkur", "Hosur, Sira, Tumkur"),
            ("TQ Sira Dist Tumkur", "Sira, Tumkur"),
        ):
            self.assertEqual(b.place_display(typed), shown, typed)

    def test_otherwise_as_typed_minus_extra_spaces(self):
        for typed, shown in (
            ("Sira", "Sira"),
            ("Mudigere  Ajjampura", "Mudigere Ajjampura"),
            ("Ramdurga Dist Belgaum", "Ramdurga Dist Belgaum"),     # one label only
            ("Toranagatti TQ", "Toranagatti TQ"),                    # label at the end
            ("TQ Dist Belgaum", "TQ Dist Belgaum"),                  # label then label
            ("TQ Dist Belgaum Dist Gokak", "TQ Dist Belgaum Dist Gokak"),  # label as a value
            ("TQ A TQ B Dist C", "TQ A TQ B Dist C"),                # repeated label
            ("ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು", "ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು"),
            ("", ""),
        ):
            self.assertEqual(b.place_display(typed), shown, typed)

    def test_the_answer_yes_still_confirms(self):
        for t in ("ಹೌದು", "ಸರಿ", "yes", "ok"):
            f = b.parse_followup(t, (b.AWAITING_DELIVERY,), known={"location": REAL_LOC})
            self.assertTrue(f["delivery_same"], t)


if __name__ == "__main__":
    unittest.main()
