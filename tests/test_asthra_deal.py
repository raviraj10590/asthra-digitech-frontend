"""The Asthra deal (owner, 2026-11-02): chat each customer until the advance.

- The varadi: the model's hidden requirement summary goes to the owner, never
  to the customer.
- #price / #advance parse, and the price message never mentions GST.
- Follow-ups on days 1, 2, 4, 7, 10, 14, 17 after the customer's last
  message; stopped by a reply, "beda", a pause, #advance; daytime only.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import asthra_deal as d  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
# 11:00 IST — inside the daytime window.
NOW = datetime(2026, 11, 20, 11, 0, tzinfo=IST).astimezone(timezone.utc)


def row(role, content, ago):
    return {"role": role, "content": content, "created_at": (NOW - ago).isoformat()}


def chat(silent_for, *extra):
    """Newest first: extra rows, the customer's last message, a lead sign."""
    return list(extra) + [row("user", "website beku", silent_for),
                          row("system", "LEAD_ALERTED", silent_for + timedelta(minutes=1))]


class TheVaradi(unittest.TestCase):
    def test_the_summary_is_cut_from_the_customer_text(self):
        text, summary = d.split_quote_marker(
            "ಧನ್ಯವಾದಗಳು sir 🙏 quotation ಬೇಗ ಕಳಿಸುತ್ತೇವೆ.\n"
            "[[QUOTE_READY]] Service: App | Kelasa: Android | Budget: 1L")
        self.assertNotIn("QUOTE", text)
        self.assertNotIn("Budget", text)
        self.assertEqual(summary, "Service: App | Kelasa: Android | Budget: 1L")

    def test_no_marker_is_untouched(self):
        self.assertEqual(d.split_quote_marker("hello"), ("hello", None))

    def test_report_names_the_command(self):
        r = d.quote_report("919876544521", "Service: App | Budget: 1L")
        self.assertIn("#price 4521", r)
        self.assertIn("Budget: 1L", r)


class OwnerCommands(unittest.TestCase):
    def test_price(self):
        self.assertEqual(d.parse_price("#price 4521 75000 tingaLige"), ("4521", 75000, "tingaLige"))
        self.assertEqual(d.parse_price("#price 4521 ₹1,50,000"), ("4521", 150000, ""))
        self.assertEqual(d.parse_price("#Price 4521 75k"), ("4521", 75000, ""))
        self.assertEqual(d.parse_price("#price 4521 1.5 lakh one time"), ("4521", 150000, "one time"))

    def test_price_needs_digits_and_amount(self):
        for t in ("#price", "#price 4521", "#price 45 1000", "#price abcd 1000"):
            with self.subTest(t=t):
                self.assertIsNone(d.parse_price(t))

    def test_advance(self):
        self.assertEqual(d.parse_advance("#advance 4521"), "4521")
        self.assertIsNone(d.parse_advance("#advance"))

    def test_price_message_never_says_gst(self):
        m = d.price_message(75000, "tingaLige")
        self.assertIn("₹75,000", m)
        self.assertNotIn("GST", m.upper())
        self.assertIn("advance", m)

    def test_rupees(self):
        self.assertEqual(d.rupees(3000), "₹3,000")
        self.assertEqual(d.rupees(150000), "₹1,50,000")
        self.assertEqual(d.rupees(500), "₹500")


class FollowUps(unittest.TestCase):
    def test_too_soon(self):
        self.assertEqual(d.decide(chat(timedelta(hours=5)), NOW), (d.NOT_DUE, None))

    def test_day_one_at_20_hours(self):
        self.assertEqual(d.decide(chat(timedelta(hours=21)), NOW), (d.SEND, 1))

    def test_day_one_goes_inside_the_window(self):
        self.assertTrue(d.window_open(chat(timedelta(hours=21)), NOW))
        self.assertFalse(d.window_open(chat(timedelta(days=2)), NOW))

    def test_each_day_once(self):
        rows = chat(timedelta(days=2, hours=1),
                    row("assistant", "x\n" + d.marker(1), timedelta(days=1)))
        self.assertEqual(d.decide(rows, NOW), (d.SEND, 2))
        rows.insert(0, row("assistant", "x\n" + d.marker(2), timedelta(minutes=30)))
        self.assertEqual(d.decide(rows, NOW), (d.NOT_DUE, None))

    def test_a_missed_day_is_skipped_not_doubled(self):
        rows = chat(timedelta(days=8), row("assistant", d.marker(2), timedelta(days=6)))
        self.assertEqual(d.decide(rows, NOW), (d.SEND, 7))

    def test_after_day_17_it_stops(self):
        rows = chat(timedelta(days=30), row("assistant", d.marker(17), timedelta(days=13)))
        self.assertEqual(d.decide(rows, NOW), (d.FINISHED, None))

    def test_a_reply_restarts_the_clock(self):
        rows = [row("user", "ok sir", timedelta(hours=2)),
                row("assistant", d.marker(4), timedelta(days=1))] + chat(timedelta(days=5))
        self.assertEqual(d.decide(rows, NOW), (d.NOT_DUE, None))

    def test_advance_ends_it(self):
        rows = chat(timedelta(days=3), row("system", d.ADVANCE_PAID, timedelta(days=1)))
        self.assertEqual(d.decide(rows, NOW)[0], d.DEAL_DONE)

    def test_beda_ends_it(self):
        rows = [row("user", "beda sir", timedelta(days=3))] + chat(timedelta(days=4))
        self.assertEqual(d.decide(rows, NOW)[0], d.DECLINED)

    def test_a_paused_chat_is_left_alone(self):
        rows = chat(timedelta(days=3), row("system", "BOT_PAUSED", timedelta(hours=3)))
        self.assertEqual(d.decide(rows, NOW)[0], d.CHAT_PAUSED)

    def test_bairavi_chats_are_not_asthra(self):
        rows = chat(timedelta(days=3), row("assistant", "[Bairavi transformer reply] x", timedelta(days=4)))
        self.assertEqual(d.decide(rows, NOW)[0], d.BAIRAVI)

    def test_night_waits(self):
        night = datetime(2026, 11, 20, 22, 30, tzinfo=IST).astimezone(timezone.utc)
        rows = [{"role": "user", "content": "hi", "created_at": (night - timedelta(days=3)).isoformat()}]
        self.assertEqual(d.decide(rows, night)[0], d.OUTSIDE_DAYTIME)


class ThePrompt(unittest.TestCase):
    def test_owner_prices_are_in_the_prompt(self):
        import webhook as w
        for must in ("₹3,000", "₹30,000", "20%", "₹5,000", "[[QUOTE_READY]]", "official quotation"):
            with self.subTest(must=must):
                self.assertIn(must, w.SYSTEM_PROMPT)
        self.assertNotIn("ಎಂದಿಗೂ fixed price ಕೊಡಬೇಡಿ", w.SYSTEM_PROMPT)

    def test_generate_reply_hides_the_summary_and_reports_it(self):
        import webhook as w
        with mock.patch.object(w, "_generate_ai_reply",
                               return_value="ಧನ್ಯವಾದ 🙏\n[[QUOTE_READY]] Service: App"), \
             mock.patch.object(w, "report_quote_request") as rep:
            out = w.generate_reply("919876544521", "app beku", history=[])
        self.assertEqual(out, "ಧನ್ಯವಾದ 🙏")
        rep.assert_called_once_with("919876544521", "Service: App")


if __name__ == "__main__":
    unittest.main()
