"""One reply, once (api/webhook.py claim_reply) and "details" during a takeover."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import bairavi as b                                             # noqa: E402
import webhook as w                                             # noqa: E402


class Resp:
    def __init__(self, ok=True, data=None):
        self.ok, self._data = ok, data

    def json(self):
        return self._data


class FakeDb:
    """Assigns ids in insert order, like Postgres."""

    def __init__(self):
        self.rows, self.next_id = [], 101

    def post(self, url, headers=None, json=None, timeout=None):
        row = dict(json[0], id=self.next_id)
        self.next_id += 1
        self.rows.append(row)
        return Resp(True, [row])

    def get(self, url, headers=None, params=None, timeout=None):
        want = params["content"][3:]
        return Resp(True, sorted(({"id": r["id"]} for r in self.rows if r["content"] == want), key=lambda r: r["id"]))


class ClaimReply(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.patches = [mock.patch.object(w, "REPLY_CLAIM_WINDOW_S", 20),
                        mock.patch.object(w.requests, "post", self.db.post),
                        mock.patch.object(w.requests, "get", self.db.get)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_the_first_turn_sends_the_second_stays_quiet(self):
        """...9703 (2026-10-12) got the same greeting twice in one second."""
        self.assertTrue(w.claim_reply("919999999999", "ನಮಸ್ಕಾರ Santhosh ಅವರೇ 🙏"))
        self.assertFalse(w.claim_reply("919999999999", "ನಮಸ್ಕಾರ Santhosh ಅವರೇ 🙏"))

    def test_both_inserted_before_either_reads_still_only_one_sends(self):
        first = self.db.post("u", json=[{"phone": "p", "role": "system",
                                         "content": w.REPLY_CLAIM + __import__("hashlib").sha1("hi".encode()).hexdigest()[:16]}])
        self.assertFalse(w.claim_reply("p", "hi"))            # the later row yields to the earlier one
        self.assertEqual(first.json()[0]["id"], 101)

    def test_a_different_reply_is_not_a_duplicate(self):
        self.assertTrue(w.claim_reply("p", "price is ₹85,000 + GST"))
        self.assertTrue(w.claim_reply("p", "where should we deliver?"))

    def test_only_a_hash_is_stored_never_the_reply(self):
        w.claim_reply("p", "ನಮಸ್ಕಾರ Santhosh")
        self.assertTrue(self.db.rows[0]["content"].startswith(w.REPLY_CLAIM))
        self.assertNotIn("Santhosh", self.db.rows[0]["content"])
        self.assertEqual(self.db.rows[0]["role"], "system")

    def test_it_fails_open(self):
        with mock.patch.object(w.requests, "post", side_effect=RuntimeError("down")):
            self.assertTrue(w.claim_reply("p", "hi"))
        with mock.patch.object(w.requests, "post", return_value=Resp(False)):
            self.assertTrue(w.claim_reply("p", "hi"))
        with mock.patch.object(w, "REPLY_CLAIM_WINDOW_S", 0):
            self.assertTrue(w.claim_reply("p", "hi"))


class DetailsWhileTheOwnerIsTalking(unittest.TestCase):
    """...5389 (2026-10-12): staff wrote "25 kva barutte"; "ditels heli" got no answer."""
    K = {"capacity_kva": 63, "location": "thirthalli", "name": "Madhan"}

    def decide(self, text, owner=("25 kva barutte",)):
        return b.takeover_decision(b.parse_followup(text, (), self.K), text, owner, self.K)

    def test_details_gets_the_card(self):
        for t in ("ditels heli", "details heli", "full details kalisi", "ಮಾಹಿತಿ ಕೊಡಿ"):
            act, reply = self.decide(t)
            self.assertEqual(act, "answer", t)
            self.assertTrue(reply.startswith("📋"), t)
            self.assertIn("+ GST", reply)

    def test_the_card_is_for_the_size_they_now_hold(self):
        f = b.parse_followup("25 kva details heli", (), self.K)
        act, reply = b.takeover_decision(f, "25 kva details heli", ("25 kva barutte",), self.K)
        self.assertIn("*25 kVA 4 Star* — *₹85,000 + GST*", reply)

    def test_everything_else_is_still_the_owners(self):
        self.assertEqual(self.decide("hu k sir")[0], "silent")
        self.assertEqual(self.decide("price kadime madi")[0], "silent")
        self.assertEqual(self.decide("document details kalisi")[0], "silent")
