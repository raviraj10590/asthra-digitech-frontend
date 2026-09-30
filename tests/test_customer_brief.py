"""The owner asks the Brain about one customer (2026-10-01)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import customer_brief as c  # noqa: E402

FORM = ("Hello! I filled in your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: thirthahalli\nFull name: Sudarshan Gowda\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: B.  1 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ")
LEAD = {"id": "c1", "name": "Sudarshan Gowda", "phone": "918431945711", "pipeline_stage": "Interested",
        "last_contacted_at": "2026-09-30T10:00:00+00:00",
        "notes": "Service: x\n🔥 30 Sep 15:30 call: Interested — 5711 called interested\n"
                 "🧠 AI 01 Oct 08:15 — 25 kVA agriculture; asked about poles"}
MSGS = [{"direction": "inbound", "body": FORM, "created_at": "2026-09-29T08:37:00+00:00"},
        {"direction": "outbound", "body": "ನಮಸ್ಕಾರ", "created_at": "2026-09-29T08:37:01+00:00"},
        {"direction": "inbound", "body": "Kamba yalla bantha", "created_at": "2026-09-29T08:38:00+00:00"},
        {"direction": "outbound", "body": "ಹೌದು, ನಮ್ಮ engineer *ಈಗಲೇ* ನಿಮಗೆ ಕರೆ ಮಾಡುತ್ತಾರೆ 🙏",
         "created_at": "2026-09-29T08:39:00+00:00"}]


class Query(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(c.query_of("5711"), ("phone", "5711"))
        self.assertEqual(c.query_of("5711 enu helidru?"), ("phone", "5711"))
        self.assertEqual(c.query_of("#who Sudarshan Gowda"), ("name", "Sudarshan Gowda"))
        self.assertEqual(c.query_of("#WHO 918431945711"), ("phone", "918431945711"))
        for t in ("hello", "#leads", "how many leads today", "25 kva"):
            self.assertIsNone(c.query_of(t), t)


class Build(unittest.TestCase):
    def test_the_brief(self):
        t = c.build(LEAD, list(reversed(MSGS)), [{"note": "🤖 Bot check: x", "due_date": "2026-10-01",
                                                  "is_done": False}])
        self.assertTrue(t.startswith("👤 *Sudarshan Gowda* · …5711"))
        self.assertIn("📋 25 kVA · thirthahalli · within 1 month", t)
        self.assertIn("📌 Stage: *Interested* · last contact 30 Sep 3:30 pm", t)
        self.assertIn("🧠 25 kVA agriculture; asked about poles", t)
        self.assertIn("📞 🔥 30 Sep 15:30 call: Interested — 5711 called interested", t)
        self.assertIn("⏰ 2026-10-01: 🤖 Bot check: x", t)
        self.assertIn("👤 29 Sep 2:08 pm — Kamba yalla bantha", t)
        self.assertNotIn("filled in your form", t)                    # the form is summarised, not dumped
        self.assertLess(t.index("ನಮಸ್ಕಾರ"), t.index("Kamba yalla bantha"))  # oldest first
        self.assertIn("wa.me/918431945711 · mark a call: *5711 called interested*", t)

    def test_a_new_lead(self):
        t = c.build(dict(LEAD, pipeline_stage="Lead", last_contacted_at=None, notes=""), [], [])
        self.assertIn("📌 Stage: *New Lead* · not called yet", t)
        self.assertNotIn("💬", t)
        self.assertNotIn("🧠", t)

    def test_none_or_many(self):
        self.assertIn("No lead in the CRM named Ravi", c.choose_reply(("name", "Ravi"), []))
        many = c.choose_reply(("phone", "11"), [LEAD, dict(LEAD, phone="919000005711")])
        self.assertIn("2 leads match 11", many)
        self.assertEqual(c.choose_reply(("phone", "5711"), [LEAD]), "")


class FromTheOwnersPhone(unittest.TestCase):
    def ask(self, text, rows):
        import webhook as w
        gets = []

        class R:
            def __init__(self, d): self._d, self.ok = d, True
            def json(self): return self._d
            def raise_for_status(self): pass

        def get(url, params=None, **k):
            gets.append((url.rsplit("/", 1)[-1], params))
            if url.endswith("/clients"):
                return R(rows)
            if url.endswith("/whatsapp_messages"):
                return R(list(reversed(MSGS)))
            return R([])
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "o"), \
             mock.patch.object(w.requests, "get", get), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None), \
             mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "generate_owner_reply", lambda *a, **k: "<AI>"):
            return w.handle_owner_text("918861369951", "OWNER", "Owner", text, {}), gets

    def test_digits(self):
        out, gets = self.ask("5711", [LEAD])
        self.assertTrue(out.startswith("👤 *Sudarshan Gowda*"))
        self.assertEqual(gets[0][1]["phone"], "like.*5711")

    def test_by_name(self):
        out, gets = self.ask("#who Sudarshan", [LEAD])
        self.assertTrue(out.startswith("👤 *Sudarshan Gowda*"))
        self.assertEqual(gets[0][1]["name"], "ilike.*Sudarshan*")

    def test_a_call_outcome_is_still_a_call_outcome(self):
        import webhook as w
        with mock.patch.object(w, "tool_call_outcome", lambda *a, **k: "✅ marked"), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None), \
             mock.patch.object(w, "_bic_enabled", lambda: False):
            self.assertEqual(w.handle_owner_text("9", "OWNER", "O", "5711 called interested", {}), "✅ marked")

    def test_digits_with_no_lead_fall_through_to_the_assistant(self):
        out, _ = self.ask("2026 sales report", [])
        self.assertNotIn("No lead", out)

    def test_who_with_no_lead_says_so(self):
        out, _ = self.ask("#who Nobody", [])
        self.assertIn("No lead in the CRM named Nobody", out)

    def test_the_like_match_is_rechecked(self):
        out, _ = self.ask("5711", [dict(LEAD, phone="915711000000")])
        self.assertNotIn("Sudarshan", out)


if __name__ == "__main__":
    unittest.main()
