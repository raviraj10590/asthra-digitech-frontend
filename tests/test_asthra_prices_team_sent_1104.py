"""Owner, 2026-11-04 ("eradannu sari madu"):
1. The day's prices are the bot's prices: page setup ₹2,000, creatives
   separate, social media slabs ₹30k–₹2L, AI bot ₹9,999 + ₹1,499/month.
2. What a person sends from the CRM inbox (the two SM Events quotation PDFs)
   reaches the reply prompt, so the bot stops promising what was sent.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import asthra_deal as d  # noqa: E402
import webhook as w  # noqa: E402

PHONE = "917338463602"
TEAM_ROWS = [  # oldest first, as the CRM inbox wrote them on 2026-11-04
    {"created_at": "2026-11-04T08:01:40+00:00", "message_type": "media",
     "body": "SM-Events-Booking-Bot-Quotation.pdf",
     "metadata": {"action": "media", "original_type": "document",
                  "file_name": "SM-Events-Booking-Bot-Quotation.pdf"}},
    {"created_at": "2026-11-04T08:14:01+00:00", "message_type": "media",
     "body": "SM-Events-Meta-Ads-Quotation.pdf",
     "metadata": {"action": "media", "original_type": "document",
                  "file_name": "SM-Events-Meta-Ads-Quotation.pdf"}},
]


class ThePrices(unittest.TestCase):
    def test_the_days_prices_are_in_the_prompt(self):
        for must in ("₹2,000 one time", "creative charge ಪ್ರತ್ಯೇಕ", "₹60,000", "₹1,00,000",
                     "₹2,00,000", "₹9,999 ರಿಂದ", "₹1,499 ತಿಂಗಳಿಗೆ", "X)"):
            self.assertIn(must, w.SYSTEM_PROMPT, must)

    def test_the_bot_is_no_longer_an_unpriced_service(self):
        other = w.SYSTEM_PROMPT[w.SYSTEM_PROMPT.index("EVERY OTHER service"):][:120]
        self.assertNotIn("chatbot", other)

    def test_still_no_gst_and_no_creative_price(self):
        self.assertIn("NEVER mention GST", w.SYSTEM_PROMPT)
        self.assertIn("never name a creative price", w.SYSTEM_PROMPT)


class TeamSentBlock(unittest.TestCase):
    def test_the_quotations_are_listed_in_ist(self):
        block = d.team_sent_block(TEAM_ROWS)
        self.assertIn("04 Nov 01:31 PM — document: SM-Events-Booking-Bot-Quotation.pdf", block)
        self.assertIn("04 Nov 01:44 PM — document: SM-Events-Meta-Ads-Quotation.pdf", block)
        self.assertIn("Never promise to send something already listed", block)
        self.assertIn("never quote amounts or terms from a document", block)

    def test_a_typed_message_is_its_text(self):
        row = {"created_at": "2026-11-04T09:00:00+00:00", "message_type": "text",
               "body": "Sir payment details:\nUPI ...", "metadata": {"action": "text"}}
        self.assertIn("Sir payment details: UPI ...", d.team_sent_block([row]))

    def test_bot_rows_are_not_team_rows(self):
        bot = {"created_at": "2026-11-04T06:01:36+00:00", "message_type": "text", "body": "ಸರಿ sir",
               "metadata": {"source": "asthra_ai_bot"}}
        self.assertEqual(d.team_sent_block([bot]), "")
        self.assertEqual(d.team_sent_block([]), "")


class FetchTeamSent(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.multiple(w, CRM_SUPABASE_URL="https://crm.example",
                                       CRM_SUPABASE_SERVICE_KEY="k")
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_oldest_first_from_the_crm_with_the_right_filter(self):
        resp = mock.Mock(ok=True)
        resp.json.return_value = list(reversed(TEAM_ROWS))      # newest first
        with mock.patch.object(w.requests, "get", return_value=resp) as get, \
             mock.patch.object(w, "ai_seconds_left", return_value=60):
            rows = w.fetch_team_sent(PHONE)
        self.assertEqual(rows, TEAM_ROWS)
        url, params = get.call_args[0][0], get.call_args[1]["params"]
        self.assertTrue(url.startswith("https://crm.example/rest/v1/whatsapp_messages"))
        self.assertEqual(params["metadata->>action"], "in.(text,media,template)")
        self.assertEqual(params["direction"], "eq.outbound")
        self.assertIn(PHONE, params["or"])

    def test_no_crm_config_no_read(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", ""), \
             mock.patch.object(w.requests, "get") as get:
            self.assertEqual(w.fetch_team_sent(PHONE), [])
            get.assert_not_called()

    def test_a_failed_read_changes_nothing(self):
        with mock.patch.object(w.requests, "get", side_effect=OSError("down")), \
             mock.patch.object(w, "ai_seconds_left", return_value=60):
            self.assertEqual(w.fetch_team_sent(PHONE), [])

    def test_the_block_reaches_the_model(self):
        seen = {}

        def ai(messages, fallback, **_):
            seen["system"] = "\n".join(m["content"] for m in messages if m["role"] == "system")
            return "ಸರಿ sir"
        with mock.patch.object(w, "fetch_customer_said", return_value=([], False)), \
             mock.patch.object(w, "fetch_team_sent", return_value=TEAM_ROWS), \
             mock.patch.object(w, "_generate_ai_reply", side_effect=ai):
            w.generate_reply(PHONE, "quotation kalisi", history=[])
        self.assertIn("SM-Events-Meta-Ads-Quotation.pdf", seen["system"])


if __name__ == "__main__":
    unittest.main()
