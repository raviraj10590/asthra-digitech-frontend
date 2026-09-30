"""THE LESSON BANK — every confirmed lesson, enforced forever.

tests/data/learned_cases.json grows through `ops/learning_report.py promote`
(the weekly learning loop: shadow mode finds where the AI and the rules read
a real message differently; a person confirms the right reading; it lands
here). A change that makes the Brain misread any of these messages again
fails the suite.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402

BANK = os.path.join(os.path.dirname(__file__), "data", "learned_cases.json")
CASES = json.load(open(BANK, encoding="utf-8"))


class TheLessonBank(unittest.TestCase):
    def test_every_lesson(self):
        for case in CASES:
            f = b.parse_followup(case["text"], tuple(case["awaiting"]), known=case.get("known") or {})
            for field, want in case["expect"].items():
                with self.subTest(lesson=case["id"], text=case["text"], field=field):
                    self.assertEqual(f[field], want)

    def test_the_bank_is_well_formed(self):
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)), "duplicate lesson id")
        for c in CASES:
            self.assertTrue(c["text"].strip(), c["id"])
            self.assertNotRegex(c["text"], r"\d{10}", "a phone number reached the bank")
            self.assertTrue(set(c["awaiting"]) <= {"delivery", "purpose", "callback", "quantity", "capacity"})
            self.assertTrue(c["expect"], c["id"])


if __name__ == "__main__":
    unittest.main()
