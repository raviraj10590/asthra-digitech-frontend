"""When the owner is talking to a customer (owner, 2026-10-04): the bot answers
only what is needed and not already answered; otherwise it stays quiet."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b      # noqa: E402

K = {"capacity_kva": 63, "name": "Ravi"}


def decide(text, owner_said):
    f = b.parse_followup(text, (), K)
    return b.takeover_decision(f, text, [owner_said], K)


class Decision(unittest.TestCase):
    def test_quiet_for_acks_and_conversation(self):
        for text in ("Ok", "ಸರಿ sir", "👍", "Thanks", "5 ge bartini", "nale site ge banni"):
            with self.subTest(text=text):
                self.assertEqual(decide(text, "ನಾಳೆ ಬನ್ನಿ")[0], "silent")

    def test_quiet_for_what_is_the_owners(self):
        for text in ("discount kodi", "call yavaga madtira?", "call bandilla"):
            with self.subTest(text=text):
                self.assertEqual(decide(text, "₹2,00,000"), ("silent", "for the owner"))

    def test_answers_only_the_unanswered_question(self):
        act, reply = decide("warranty eshtu varsha?", "ನಾಳೆ call ಮಾಡ್ತೀನಿ")
        self.assertEqual(act, "answer")
        self.assertIn("1 ವರ್ಷ warranty", reply)
        self.assertNotIn("ಯಾವ", reply)                      # no qualification question added

    def test_quiet_when_the_owner_already_answered(self):
        self.assertEqual(decide("warranty eshtu varsha?", "1 year warranty ide"),
                         ("silent", "the owner already answered it"))
        self.assertEqual(decide("price eshtu?", "63 kVA ₹2,00,000 + GST")[0], "silent")
        self.assertEqual(decide("MESCOM approval ide na?", "MESCOM approval ide sir")[0], "silent")

    def test_price_and_approval_answers_come_from_the_owners_tables(self):
        act, reply = decide("price eshtu?", "engineer call madtare")
        self.assertEqual(act, "answer")
        self.assertIn(b.price_line(63), reply)
        act, reply = decide("MESCOM approval ide na?", "site ge bartini")
        self.assertIn("MESCOM", reply)


class ThroughTheWebhook(unittest.TestCase):
    def run_turn(self, text, owner_said):
        import webhook as w
        hist = [{"role": "user", "content": "Hello! I filled out your form\nFull name: Ravi\nkVA: 63"},
                {"role": "assistant", "content": b.flow_marker(())}]
        sent, alerts = [], []
        with mock.patch.object(w, "human_replies", lambda s: [owner_said]), \
             mock.patch.object(b, "in_transformer_flow", lambda h: True), \
             mock.patch.object(w, "send_text_checked", lambda to, t: sent.append(t) or {"verdict": w.DELIVERY_ACCEPTED}), \
             mock.patch.object(w, "notify_owner", lambda m: alerts.append(m)), \
             mock.patch.object(w, "save_messages", lambda rows: True), \
             mock.patch.object(w, "upsert_lead", lambda *a, **k: None), \
             mock.patch.object(w, "warn_if_transcript_lost", lambda *a, **k: None), \
             mock.patch.object(w, "shadow_interpret", lambda *a, **k: None), \
             mock.patch.object(w, "bairavi_model_reply", lambda *a, **k: "MODEL"):
            w.run_client_pipeline("919000000001", text, {"history": hist, "last_user": {}, "paused": False, "vip_alerted": True}, "wamid.x")
        return sent, alerts

    def test_quiet_turn_sends_nothing_and_tells_the_owner(self):
        sent, alerts = self.run_turn("5 ge bartini", "ನಾಳೆ ಬನ್ನಿ")
        self.assertEqual(sent, [])
        self.assertEqual(len(alerts), 1)
        self.assertIn("the bot stayed quiet", alerts[0])

    def test_needed_answer_only(self):
        sent, alerts = self.run_turn("warranty eshtu varsha?", "ನಾಳೆ call ಮಾಡ್ತೀನಿ")
        self.assertEqual(len(sent), 1)
        self.assertIn("1 ವರ್ಷ warranty", sent[0])
        self.assertNotIn("MODEL", sent[0])
        self.assertTrue(any("answered only their question" in a for a in alerts), alerts)


if __name__ == "__main__":
    unittest.main()
