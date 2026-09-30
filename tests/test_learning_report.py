"""The weekly learning report and `promote` (2026-10-01)."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import learning_report as L  # noqa: E402

SECRET = "test-only-secret"
REF = "msg:5f3c9a2e-0000-4000-8000-000000000001"
WAMID = "wamid.TEST1"
NOW = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)


def row(**k):
    base = {"turn_key": L.turn_key(SECRET, REF), "created_at": "2026-10-04T10:00:00+00:00",
            "status": "ok", "awaiting": ["purpose"], "conflict_fields": [], "diffs": None, "rejected": []}
    base.update(k)
    return base


class TheKey(unittest.TestCase):
    def test_same_as_the_live_webhook(self):
        from unittest import mock
        import webhook as w
        with mock.patch.dict(os.environ, {"SHADOW_TURN_KEY": SECRET}):
            self.assertEqual(w.shadow_turn_key(REF), L.turn_key(SECRET, REF))


class Lessons(unittest.TestCase):
    def test_a_disagreement_is_joined_to_the_customers_words(self):
        items = L.lessons([row(diffs={"application": {"parser": None, "shadow": "AGRICULTURE"}})],
                          [(REF, WAMID)], {WAMID: "Krasige.bekku. call 9876543210"}, SECRET)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Krasige.bekku. call [number]")
        self.assertEqual(items[0]["id"], L.turn_key(SECRET, REF)[:8])

    def test_agreement_is_not_a_lesson(self):
        self.assertEqual(L.lessons([row()], [(REF, WAMID)], {WAMID: "ok"}, SECRET), [])

    def test_refusals_and_invalid_are_lessons(self):
        self.assertEqual(len(L.lessons([row(rejected=[["delivery_place", "not_a_place"]])], [], {}, SECRET)), 1)
        self.assertEqual(len(L.lessons([row(status="invalid")], [], {}, SECRET)), 1)

    def test_wrong_secret_finds_no_words(self):
        items = L.lessons([row(conflict_fields=["quantity"])], [(REF, WAMID)], {WAMID: "32 ಕಹಬ"}, "other")
        self.assertIsNone(items[0]["text"])

    def test_render(self):
        items = L.lessons([row(diffs={"application": {"parser": None, "shadow": "AGRICULTURE"}},
                               rejected=[["delivery_place", "not_a_place"]])],
                          [(REF, WAMID)], {WAMID: "Krasige.bekku."}, SECRET)
        md = L.render(items, [{"name": "Rohit", "phone": "919742662829", "note": "🤖 Bot check: x"}], NOW)
        self.assertIn("1 message(s) where the AI read something different", md)
        self.assertIn("'Krasige.bekku.'", md)
        self.assertIn("**application**: rules = `None` · AI = `AGRICULTURE`", md)
        self.assertIn("refused by the validator (not_a_place)", md)
        self.assertIn("**Rohit** (…2829): 🤖 Bot check: x", md)


class Promote(unittest.TestCase):
    ITEM = {"id": "abcd1234", "text": "Krasige.bekku.", "awaiting": ["purpose"]}

    def test_expectations_are_typed(self):
        self.assertEqual(L.parse_expectations(["application=AGRICULTURE", "quantity=2",
                                               "delivery_same=true", "delivery_location=none"]),
                         {"application": "AGRICULTURE", "quantity": 2, "delivery_same": True,
                          "delivery_location": None})
        with self.assertRaises(ValueError):
            L.parse_expectations(["price=95000"])
        with self.assertRaises(ValueError):
            L.parse_expectations(["application"])

    def test_add_case(self):
        bank = L.add_case([], self.ITEM, {"application": "AGRICULTURE"}, NOW)
        self.assertEqual(bank[0], {"id": "abcd1234", "text": "Krasige.bekku.", "awaiting": ["purpose"],
                                   "expect": {"application": "AGRICULTURE"}, "added": "2026-10-05"})
        with self.assertRaises(ValueError):
            L.add_case(bank, self.ITEM, {"application": "AGRICULTURE"}, NOW)       # no duplicates
        with self.assertRaises(ValueError):
            L.add_case([], dict(self.ITEM, text=None), {"application": "X"}, NOW)  # needs words

    def test_the_database_is_only_read(self):
        with self.assertRaises(ValueError):
            L._sql("x", "delete from public.clients")
        with self.assertRaises(ValueError):
            L._sql("x", "select 1; update t set a = 1")


if __name__ == "__main__":
    unittest.main()
