"""Morning call briefing (2026-09-30)."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import call_briefing as cb  # noqa: E402

NOW = datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc)   # 09:00 IST, 1 Oct
FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: {kva}\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {place}\n"
        "Full name: {name}\nನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: {when}")
NOW_FORM, LATER_FORM = "A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ", "C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ"


def lead(phone, name, created, stage="Lead", contacted=None, notes=None):
    return {"phone": phone, "name": name, "created_at": created, "pipeline_stage": stage,
            "last_contacted_at": contacted, "notes": notes}


def form(phone, at, kva="A. 25 kVA", place="Sira", name="X", when=LATER_FORM):
    return {"phone": phone, "direction": "inbound", "created_at": at,
            "body": FORM.format(kva=kva, place=place, name=name, when=when)}


def bot(phone, at, body):
    return {"phone": phone, "direction": "outbound", "created_at": at, "body": body}


NOW_OK = "ಸರಿ X ಅವರೇ. ನಮ್ಮ engineer *ಈಗಲೇ* ನಿಮಗೆ ಕರೆ ಮಾಡಿ, ಡೆಲಿವರಿ ಸಮಯ..."
TOMORROW_OK = "ಸರಿ X ಅವರೇ. ನಮ್ಮ engineer *ನಾಳೆ* ನಿಮಗೆ ಕರೆ ಮಾಡಿ..."
OFFER = "ನಿಮಗೆ ಯಾವಾಗ ಕರೆ ಮಾಡುವುದು ಅನುಕೂಲ? 1️⃣ ಈಗಲೇ / 2️⃣ ಇಂದು ಸಂಜೆ / 3️⃣ ನಾಳೆ"


class Build(unittest.TestCase):
    def setUp(self):
        self.clients = [
            lead("919000000001", "Asked Now", "2026-09-30T14:00:00+00:00"),
            lead("919000000002", "Needs Now", "2026-09-30T10:00:00+00:00"),
            lead("919000000003", "Tomorrow Promise", "2026-09-30T08:00:00+00:00"),
            lead("919000000004", "Just Browsing", "2026-09-29 05:00:00.5+00"),
            lead("919000000005", "Already Called", "2026-09-30T06:00:00+00:00", "Interested",
                 "2026-09-30T12:00:00+00:00",
                 "Service: x\n📞 28 Sep 11:00 call: Contacted — earlier call\n"
                 "🔥 30 Sep 17:30 call: Interested — 5 called interested"),
            lead("918884448141", "Whatsapp Lead", "2026-09-30T07:00:00+00:00"),   # owner test number
            lead("919000000006", "Too Old", "2026-09-01T07:00:00+00:00"),
        ]
        self.msgs = [
            form("919000000001", "2026-09-30T14:00:00+00:00", place="TQ Ramdurga  Dist Belgaum  Toranagatti"),
            bot("919000000001", "2026-09-30T14:02:00+00:00", OFFER),
            bot("919000000001", "2026-09-30T14:03:00+00:00", NOW_OK),
            form("919000000002", "2026-09-30T10:00:00+00:00", kva="B. 63 kVA", when=NOW_FORM),
            form("919000000003", "2026-09-30T08:00:00+00:00"),
            bot("919000000003", "2026-09-30T08:05:00+00:00", TOMORROW_OK),
            form("919000000004", "2026-09-29T05:00:00+00:00", place="Kadur"),
            bot("919000000004", "2026-09-29T05:01:00+00:00", OFFER),
        ]
        self.text = cb.build(self.clients, self.msgs, NOW)

    def test_sections_and_order(self):
        t = self.text
        self.assertTrue(t.startswith("📞 *Today's call plan* — 01 Oct"))
        self.assertLess(t.index("🔥 *Call first* (2)"), t.index("📅 *Promised a call* (1)"))
        self.assertLess(t.index("Asked Now"), t.index("Needs Now"))          # newest first
        self.assertIn("asked: call NOW (yesterday 7:33 pm)", t)
        self.assertIn("63 kVA · Sira · needs it NOW", t)
        self.assertIn("Toranagatti, Ramdurga, Belgaum", t)                  # tidy place
        self.assertIn("Tomorrow Promise · 25 kVA · Sira · asked: tomorrow", t)
        self.assertIn("🕒 *Also not called yet*: 1", t)
        self.assertIn("Just Browsing · 25 kVA · Kadur", t)
        self.assertIn("wa.me/919000000001 · …0001", t)

    def test_marked_old_and_owner_leads_are_not_listed(self):
        for name in ("Already Called", "Whatsapp Lead", "Too Old"):
            self.assertNotIn(name, self.text)

    def test_yesterday(self):
        # Exactly yesterday's calls: the 28 Sep "Contacted" line is not counted.
        self.assertIn("📊 *Yesterday*: 🆕 4 new leads — 1 Interested\n", self.text)

    def test_the_offer_alone_is_not_a_choice(self):
        self.assertNotIn("Just Browsing · 25 kVA · Kadur · asked", self.text)

    def test_nothing_to_say(self):
        self.assertEqual(cb.build([], [], NOW), "")

    def test_everyone_marked(self):
        t = cb.build([self.clients[4]], [], NOW)
        self.assertIn("✅ Everyone from the last 14 days has been marked.", t)
        self.assertIn("1 Interested", t)

    def test_owner_numbers_from_the_environment(self):
        t = cb.build([lead("919876500001", "Staff Test", "2026-09-30T14:00:00+00:00")],
                     [], NOW, owner_phones=["919876500001"])
        self.assertEqual(t, "")


class Timestamps(unittest.TestCase):
    def test_every_shape(self):
        want = datetime(2026, 9, 17, 16, 7, 54, 542797, tzinfo=timezone.utc)
        for s in ("2026-09-17 16:07:54.542797+00", "2026-09-17T16:07:54.542797+00:00",
                  "2026-09-17T16:07:54.542797Z", "2026-09-17T21:37:54.542797+05:30"):
            self.assertEqual(cb._ts(s), want, s)
        self.assertEqual(cb._ts("2026-09-17T16:07:54.5+00:00").microsecond, 500000)
        self.assertEqual(cb._ts("2026-09-17T16:07:54").tzinfo, timezone.utc)


class TheNineOClockRun(unittest.TestCase):
    def run_handler(self, crm_fails=False):
        import digest as d
        sent = []

        class R:
            def __init__(self, data): self._d, self.ok, self.status_code, self.text = data, True, 200, ""
            def json(self): return self._d
            def raise_for_status(self):
                if crm_fails: raise RuntimeError("crm down")

        def get(url, params=None, **k):
            if "crm.example" in url:
                if "clients" in url:
                    return R([lead("919100005711", "Asked Now", "2026-09-30T14:00:00+00:00"),
                              # an OWNER_PHONE number (tests/conftest.py) — never listed
                              lead("910000000002", "Owner Phone", "2026-09-30T14:00:00+00:00")])
                return R([bot("919100005711", "2026-09-30T14:03:00+00:00", NOW_OK)])
            return R([])

        with mock.patch.object(d, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(d, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(d, "CRM_OWNER_USER_ID", "o"), \
             mock.patch.object(d.requests, "get", get), \
             mock.patch.object(d.requests, "post", lambda *a, **k: R({})), \
             mock.patch.object(d.requests, "patch", lambda *a, **k: R({})), \
             mock.patch.object(d, "send_to_owner", lambda text: sent.append(text) or True):
            h = d.handler.__new__(d.handler)
            h.headers = {"User-Agent": "vercel-cron/1.0"}
            h.path = "/api/digest"
            h.send_response = lambda *a: None
            h.send_header = lambda *a: None
            h.end_headers = lambda: None
            h.wfile = type("W", (), {"write": lambda self, b: None})()
            h.do_GET()
        return sent

    def test_digest_then_briefing(self):
        sent = self.run_handler()
        self.assertEqual(len(sent), 2)
        self.assertIn("Daily Bot Report", sent[0])
        self.assertIn("Today's call plan", sent[1])
        self.assertIn("Asked Now", sent[1])
        self.assertNotIn("Owner Phone", sent[1])

    def test_a_crm_failure_never_costs_the_digest(self):
        sent = self.run_handler(crm_fails=True)
        self.assertEqual(len(sent), 1)
        self.assertIn("Daily Bot Report", sent[0])


if __name__ == "__main__":
    unittest.main()


class NaraRouterExtras(unittest.TestCase):
    def test_summary_under_the_lead_and_bot_check_count(self):
        c = lead("919000005555", "Summ Arized", "2026-09-30T14:00:00+00:00",
                 notes="Service: x\n🧠 AI 01 Oct 08:15 — 63 kVA x2, Gokak; asked about poles")
        t = cb.build([c], [form("919000005555", "2026-09-30T14:00:00+00:00")], NOW, bot_checks=2)
        self.assertIn("1. Summ Arized · 25 kVA · Sira\n   🧠 63 kVA x2, Gokak; asked about poles\n   wa.me/", t)
        self.assertIn("🤖 *Bot check*: 2 chats flagged for a look — CRM → Follow-ups", t)

    def test_bot_checks_alone_still_send(self):
        self.assertIn("🤖 *Bot check*: 1 chat flagged", cb.build([], [], NOW, bot_checks=1))
