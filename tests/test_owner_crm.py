"""Owner CRM views on WhatsApp — phase 1, read-only (2026-10-04)."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import owner_crm  # noqa: E402
from api import webhook as w  # noqa: E402

NOW = datetime(2026, 10, 5, 3, 30, tzinfo=timezone.utc)        # 09:00 IST
TODAY = "2026-10-05"
OWNER = w.OWNER_PHONES[0] if w.OWNER_PHONES else "919900000000"


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


class Commands(unittest.TestCase):
    def test_command_words(self):
        self.assertEqual(owner_crm.command("#today"), "today")
        self.assertEqual(owner_crm.command("#followups"), "followups")
        self.assertEqual(owner_crm.command("#due"), "due")
        self.assertEqual(owner_crm.command("#week please"), "week")
        self.assertIsNone(owner_crm.command("#calls"))
        self.assertIsNone(owner_crm.command("today"))

    def test_routing_uses_the_registry(self):
        calls = []
        with mock.patch.object(w, "run_tool", lambda s, name, **k: calls.append((name, k.get("view"))) or "ok"):
            for text in ("#today", "#chats", "#pipeline", "#week", "#followups", "#due", "#calls"):
                w.handle_owner_text(OWNER, "OWNER", "Owner", text, {"history": [], "last_user": {}})
        self.assertEqual(calls, [("crm_owner_view", "today"), ("crm_owner_view", "chats"),
                                 ("crm_owner_view", "pipeline"), ("crm_owner_view", "week"),
                                 ("crm_owner_view", "followups"), ("crm_money_due", None),
                                 ("crm_calls_to_make", None)])


class Timestamps(unittest.TestCase):
    def test_postgres_shapes_python39_cannot_read(self):
        """Found by the real-data preview 2026-10-04: '+00' and 5-digit fractions."""
        for raw in ("2026-09-29T12:33:12.51124+00", "2026-09-29 12:33:12.51124+00",
                    "2026-09-29T12:33:12+00:00", "2026-09-29T12:33:12.5Z"):
            self.assertEqual(owner_crm._ts(raw).astimezone(timezone.utc).hour, 12, raw)
        convos = [{"phone": "919000000001", "last_body": "rate?", "last_direction": "inbound",
                   "last_created_at": (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.51124+00"),
                   "contact_name": ""}]
        self.assertEqual(len(owner_crm.waiting_chats(convos, NOW)), 1)


class Followups(unittest.TestCase):
    ROWS = [{"id": 1, "client_id": "a", "note": "call back about 63 kVA", "due_date": "2026-10-03", "is_done": False},
            {"id": 2, "client_id": "b", "note": "send quotation", "due_date": TODAY, "is_done": False},
            {"id": 3, "client_id": "c", "note": "later", "due_date": "2026-10-09", "is_done": False},
            {"id": 4, "client_id": "a", "note": "done one", "due_date": "2026-10-01", "is_done": True}]
    CLIENTS = {"a": {"name": "Ravi", "phone": "919000000001"}, "b": {"name": "Manju", "phone": "919000000002"}}

    def test_due_and_overdue_only_oldest_first(self):
        t = owner_crm.followups_text(self.ROWS, self.CLIENTS, TODAY)
        self.assertIn("Follow-ups due* — 2 (1 overdue)", t)
        self.assertLess(t.index("Ravi"), t.index("Manju"))
        self.assertNotIn("later", t)
        self.assertNotIn("done one", t)
        self.assertIn("⚠️", t.split("\n")[1])                    # the overdue one is marked

    def test_nothing_due(self):
        self.assertIn("nothing due", owner_crm.followups_text([], {}, TODAY))


class Chats(unittest.TestCase):
    def convo(self, phone, body, minutes, direction="inbound"):
        return {"phone": phone, "contact_name": "", "last_body": body, "last_direction": direction,
                "last_created_at": ago(minutes)}

    def test_waiting_means_customer_wrote_last_and_is_owed_an_answer(self):
        convos = [self.convo("919000000001", "63 kva rate eshtu?", 60),
                  self.convo("919000000002", "ok", 60),                       # an acknowledgement
                  self.convo("919000000003", "price please", 3),              # under 10 minutes
                  self.convo("919000000004", "hello?", 60 * 24 * 9),          # over 7 days
                  self.convo("919000000005", "we replied", 60, "outbound"),
                  self.convo(OWNER, "test from owner", 60)]                   # staff number
        waiting = owner_crm.waiting_chats(convos, NOW, [OWNER])
        self.assertEqual([c["phone"] for c in waiting], ["919000000001"])
        text = owner_crm.chats_text(convos, {"9000000001": "Ravi"}, NOW, [OWNER])
        self.assertIn("Ravi", text)
        self.assertIn("wa.me/919000000001", text)


class ReplyStampedEarly(unittest.TestCase):
    def test_bot_reply_saved_a_second_before_counts_as_answered(self):
        c = {"phone": "919000000001", "last_body": "Hello! I filled in your form", "last_direction": "inbound",
             "last_created_at": ago(60), "contact_name": ""}
        replied_just_before = NOW - timedelta(minutes=60, seconds=2)
        replied_long_before = NOW - timedelta(days=2)
        self.assertEqual(owner_crm.waiting_chats([c], NOW, last_reply={"9000000001": replied_just_before}), [])
        self.assertEqual(len(owner_crm.waiting_chats([c], NOW, last_reply={"9000000001": replied_long_before})), 1)


class BotChecksApart(unittest.TestCase):
    def test_bot_checks_counted_separately(self):
        rows = Followups.ROWS + [{"id": 9, "client_id": "a", "note": "🤖 Bot check: no reply",
                                  "due_date": TODAY, "is_done": False}]
        t = owner_crm.followups_text(rows, Followups.CLIENTS, TODAY)
        self.assertIn("— 2 (1 overdue) · plus 1 🤖 bot check", t)
        self.assertNotIn("no reply", t)


class Money(unittest.TestCase):
    def test_indian_grouping_and_total(self):
        self.assertEqual(owner_crm.money(295000), "2,95,000")
        self.assertEqual(owner_crm.money(12345678), "1,23,45,678")
        t = owner_crm.due_text([{"client_name": "Sri Ram", "invoice_number": "BT-7", "balance_due": 95000,
                                 "due_date": "2026-10-01"},
                                {"client_name": "Paid", "invoice_number": "BT-8", "balance_due": 0}], TODAY)
        self.assertIn("₹95,000 on 1 invoice", t)
        self.assertIn("overdue", t)
        self.assertNotIn("Paid", t)


class Today(unittest.TestCase):
    def test_one_message_with_all_three(self):
        t = owner_crm.today_text(Followups.ROWS, Followups.CLIENTS,
                                 [{"phone": "919000000001", "last_body": "rate?", "last_direction": "inbound",
                                   "last_created_at": ago(30), "contact_name": ""}],
                                 {}, [{"name": "New One", "phone": "919000000009"}], NOW)
        self.assertIn("Follow-ups due: *2*", t)
        self.assertIn("Chats waiting for you: *1*", t)
        self.assertIn("New leads (24 h): *1*", t)
        self.assertIn("5 Oct", t)


class ToolFailures(unittest.TestCase):
    def test_crm_down_is_said_not_shown_as_empty(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://x"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "u"), \
             mock.patch.object(w.requests, "get", side_effect=TimeoutError("slow")):
            self.assertEqual(w.tool_owner_view(OWNER, view="today"), "⚠️ Could not reach the CRM.")
            self.assertEqual(w.tool_money_due(OWNER), "⚠️ Could not reach the CRM.")

    def test_reads_only(self):
        """Phase 1 never writes: no POST/PATCH/DELETE from these tools."""
        import inspect
        src = inspect.getsource(w._owner_view_data) + inspect.getsource(w.tool_money_due) + \
            inspect.getsource(w._crm_rows) + inspect.getsource(w._crm_count)
        for verb in ("requests.post", "requests.patch", "requests.delete", "requests.put"):
            self.assertNotIn(verb, src)
        self.assertNotIn("nara_", src)                            # owner rule: no NaraRouter tables


if __name__ == "__main__":
    unittest.main()
