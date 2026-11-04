"""Owner, 2026-11-04 ("sari madu"), after the 45-message chat with …3602
(SM Events and Planner): the bot saw only ten turns, so it called an events
business "photography", re-asked what it had been told, and when the customer
said "Kk I will pay" nobody was told.

- Every message the customer wrote rides along as a block the model must not
  re-ask from or contradict.
- "I will pay" alerts the owner once and the reply asks no question.
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
SAID = ["Hello! I filled out your form…\nFull name: manjunath K\nCity: banglore",
        "Events management", "Wedding decrtion birthday party", "New page", "Ss", "Kk",
        "Sm events and planner", "Hebbal \nBanglore only"]


class CustomerSaidBlock(unittest.TestCase):
    def test_their_words_are_listed_and_bare_acks_dropped(self):
        block = d.customer_said_block(SAID)
        for s in ("Events management", "New page", "Sm events and planner", "Hebbal Banglore only"):
            self.assertIn(s, block)
        self.assertNotIn("• Ss", block)
        self.assertNotIn("• Kk", block)
        self.assertIn("never ask again", block)
        self.assertIn("never call it something they did not say", block)

    def test_nothing_said_is_no_block(self):
        self.assertEqual(d.customer_said_block(["Kk", "Ss", ""]), "")

    def test_over_the_cap_the_oldest_go_but_the_form_stays(self):
        many = ["FORM name budget"] + [f"message {i} " + "x" * 200 for i in range(60)]
        block = d.customer_said_block(many)
        self.assertLessEqual(len(block), d.CUSTOMER_SAID_CHARS + 600)
        self.assertIn("FORM name budget", block)
        self.assertIn("message 59", block)
        self.assertNotIn("message 0 ", block)


class SaidWillPay(unittest.TestCase):
    def test_agreeing_to_pay(self):
        for t in ("Kk I will pay", "I will pay", "advance kodtini", "payment details kalisi",
                  "gpay number kodi", "ನಾನು ಪೇ ಮಾಡ್ತೀನಿ", "send account details"):
            self.assertTrue(d.said_will_pay(t), t)

    def test_not_agreeing(self):
        for t in ("I will not pay", "pay later", "upi accept maadteera?", "Ss",
                  "ನಾನು ಮಾಡುತ್ತೇನೆ", "ಎಷ್ಟು ಮೊತ್ತ?", "photos kodtini", "advance beda"):
            self.assertFalse(d.said_will_pay(t), t)

    def test_the_owner_alert(self):
        r = d.pay_intent_report(PHONE, "Kk I will pay", "₹5,000 ad budget + ₹1,000 = ₹6,000")
        self.assertIn("wa.me/917338463602", r)
        self.assertIn("Kk I will pay", r)
        self.assertIn("₹6,000", r)
        self.assertIn("#advance 3602", r)

    def test_last_offer_is_the_newest_rupee_line(self):
        hist = [{"role": "assistant", "content": "₹10,000 ad ಗೆ ₹2,000"},
                {"role": "user", "content": "ಎಷ್ಟು ಮೊತ್ತ?"},
                {"role": "assistant", "content": "₹5,000 + ₹1,000 = ಒಟ್ಟು ₹6,000 sir.\n\nstart ಮಾಡೋಣವಾ?"}]
        self.assertEqual(d.last_offer(hist), "₹5,000 + ₹1,000 = ಒಟ್ಟು ₹6,000 sir.")
        self.assertEqual(d.last_offer([]), "")


class GenerateReply(unittest.TestCase):
    def run_reply(self, text, said=(), pending=False, history=()):
        sent = {}

        def ai(messages, fallback, **_):
            sent["messages"] = messages
            return "ಸರಿ sir 🙏"
        with mock.patch.object(w, "fetch_customer_said", return_value=(list(said), pending)), \
             mock.patch.object(w, "_generate_ai_reply", side_effect=ai), \
             mock.patch.object(w, "report_pay_intent") as rep:
            w.generate_reply(PHONE, text, history=list(history))
        system = "\n".join(m["content"] for m in sent["messages"] if m["role"] == "system")
        return system, rep, sent["messages"]

    def test_their_words_reach_the_model(self):
        system, rep, _ = self.run_reply("Banglore full", said=SAID)
        self.assertIn("Sm events and planner", system)
        rep.assert_not_called()

    def test_i_will_pay_alerts_the_owner_and_asks_nothing(self):
        hist = [{"role": "assistant", "content": "ಒಟ್ಟು ₹6,000 sir."}]
        system, rep, _ = self.run_reply("Kk I will pay", said=SAID, history=hist)
        self.assertIn("PAYMENT AGREED", system)
        rep.assert_called_once_with(PHONE, "Kk I will pay", "ಒಟ್ಟು ₹6,000 sir.")

    def test_a_second_i_will_pay_does_not_alert_again(self):
        system, rep, _ = self.run_reply("I will pay", said=SAID, pending=True)
        self.assertIn("PAYMENT AGREED", system)
        rep.assert_not_called()

    def test_after_agreeing_the_bot_does_not_push(self):
        system, rep, _ = self.run_reply("Banglore full", said=SAID, pending=True)
        self.assertIn("PAYMENT PENDING", system)
        rep.assert_not_called()

    def test_twenty_turns_of_history_not_ten(self):
        hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"}
                for i in range(20)]
        _, _, messages = self.run_reply("hi", history=hist)
        self.assertIn("t0", [m["content"] for m in messages])


class FetchCustomerSaid(unittest.TestCase):
    def fetch(self, rows, current=""):
        resp = mock.Mock(ok=True)
        resp.json.return_value = rows
        with mock.patch.object(w.requests, "get", return_value=resp), \
             mock.patch.object(w, "ai_seconds_left", return_value=60):
            return w.fetch_customer_said(PHONE, current)

    def test_oldest_first_and_the_current_message_not_twice(self):
        rows = [{"role": "user", "content": "Banglore full"},     # newest first
                {"role": "user", "content": "Events management"}]
        self.assertEqual(self.fetch(rows, "Banglore full"), (["Events management"], False))
        self.assertEqual(self.fetch(rows, "other"), (["Events management", "Banglore full"], False))

    def test_the_pay_marker_means_pending(self):
        rows = [{"role": "system", "content": d.PAY_INTENT}, {"role": "user", "content": "x"}]
        self.assertEqual(self.fetch(rows), (["x"], True))

    def test_a_failed_read_changes_nothing(self):
        with mock.patch.object(w.requests, "get", side_effect=OSError("down")), \
             mock.patch.object(w, "ai_seconds_left", return_value=60):
            self.assertEqual(w.fetch_customer_said(PHONE), ([], False))

    def test_a_short_deadline_skips_the_read(self):
        with mock.patch.object(w.requests, "get") as get, \
             mock.patch.object(w, "ai_seconds_left", return_value=2):
            self.assertEqual(w.fetch_customer_said(PHONE), ([], False))
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
