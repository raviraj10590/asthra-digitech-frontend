"""Bairavi Bot Knowledge (owner 2026-11-05, "2 maadu"): what the owner writes on the CRM page
reaches the Bairavi model, and the evidence guard accepts exactly those facts — nothing more."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

ROWS = [{"topic": "160 kVA", "body": "160 kVA on an HT load sanction: ₹3,20,000 + GST."},
        {"topic": "Delivery", "body": "Delivery within 30 days of the advance."}]
FACTS = b.owner_knowledge_text(ROWS)


class Guard(unittest.TestCase):
    def test_owner_price_and_time_pass(self):
        t = "160 kVA ದರ ₹3,20,000 + GST. Advance ಕೊಟ್ಟ 30 ದಿನದಲ್ಲಿ ಡೆಲಿವರಿ."
        self.assertIsNotNone(b.reply_violates_evidence(t, "160 rate?"))         # without the page
        self.assertIsNone(b.reply_violates_evidence(t, "160 rate?", FACTS))     # with it

    def test_a_figure_the_owner_did_not_write_still_fails(self):
        self.assertEqual(b.reply_violates_evidence("160 kVA ₹2,90,000 ಮಾತ್ರ.", "rate?", FACTS), "a price")
        self.assertEqual(b.reply_violates_evidence("15 ದಿನದಲ್ಲಿ ಡೆಲಿವರಿ.", "delivery?", FACTS),
                         "a delivery time")

    def test_no_rows_no_change(self):
        self.assertEqual(b.owner_knowledge_text([]), "")
        self.assertEqual(b.owner_knowledge_text([{"topic": " ", "body": "x"}]), "")


class Brief(unittest.TestCase):
    def test_rows_reach_the_brief(self):
        brief = b.model_brief_kn({}, knowledge=ROWS)
        self.assertIn("₹3,20,000", brief)
        self.assertIn("ಇದೇ ಅಂತಿಮ", brief)
        self.assertNotIn("Bot Knowledge", b.model_brief_kn({}))


class Webhook(unittest.TestCase):
    def test_the_model_path_reads_bairavi_rows(self):
        import webhook as w
        seen = {}

        def ai(messages, fallback, **_):
            seen["system"] = messages[0]["content"]
            return "160 kVA ದರ ₹3,20,000 + GST — HT load sanction ಇದ್ದರೆ."
        f = {"customer_question": b.QUESTION_UNANSWERED}
        with mock.patch.object(w, "fetch_knowledge", return_value=ROWS) as fk, \
             mock.patch.object(b, "should_ask_model", return_value=True), \
             mock.patch.object(b, "outstanding", return_value=[]), \
             mock.patch.object(w, "_generate_ai_reply", side_effect=ai):
            reply = w.bairavi_model_reply("919999999999", "160 kva rate enu?", [], f, {})
        fk.assert_called_with("bairavi")
        self.assertIn("₹3,20,000", seen["system"])
        self.assertIn("₹3,20,000", reply)


if __name__ == "__main__":
    unittest.main()
