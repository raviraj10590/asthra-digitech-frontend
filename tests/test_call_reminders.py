"""Call reminders (call_reminders.py + api/call_reminders_sync.py).

Data that motivated it (14 days to 2026-10-03): 27 customers chose a call
time; 19 were never marked as called. Offline: Brain, CRM and WhatsApp are
faked; transcripts are in the shape Brain stores them.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import requests                                        # noqa: E402
import bairavi as b                                    # noqa: E402
import call_reminders as cr                            # noqa: E402
import call_reminders_sync as sync                     # noqa: E402
import webhook as w                                    # noqa: E402
from conversation import lead_form                     # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
CUST = "919480001234"
OWNER = "919999000001"
BRAIN, CRM = "https://brain.test", "https://crm.test"


def ist(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=IST)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def chat(chosen_at, slot_answer="1", phone=CUST, extra=()):
    """A real-shaped Bairavi transcript: form, opening marker, the call-time
    offer, the customer's choice."""
    t0 = chosen_at - timedelta(minutes=10)
    rows = [
        {"phone": phone, "role": "user", "content": lead_form(name="Muttu", location="Hosakeri"),
         "created_at": iso(t0)},
        {"phone": phone, "role": "assistant", "content": b.flow_marker((b.AWAITING_CALLBACK,)),
         "created_at": iso(t0 + timedelta(minutes=1))},
        {"phone": phone, "role": "user", "content": slot_answer, "created_at": iso(chosen_at)},
        {"phone": phone, "role": "assistant", "content": b.flow_marker(()),
         "created_at": iso(chosen_at + timedelta(seconds=5))},
    ]
    for when, role, content in extra:
        rows.append({"phone": phone, "role": role, "content": content, "created_at": iso(when)})
    return rows


class Resp:
    def __init__(self, body, status=200):
        self._b, self.status_code, self.ok = body, status, 200 <= status < 300

    def json(self):
        return self._b

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


# ── Pure rules ──────────────────────────────────────────────────────────────

class APromise(unittest.TestCase):
    def test_the_choice_after_the_offer(self):
        for answer, slot in (("1", "now"), ("2", "evening"), ("3", "tomorrow"), ("ನಾಳೆ", "tomorrow")):
            with self.subTest(answer=answer):
                p = cr.promise(chat(ist(3, 11), answer))
                self.assertEqual((p["slot"], p["chosen_at"]), (slot, iso(ist(3, 11))))

    def test_a_call_request_without_an_offer(self):
        rows = chat(ist(3, 11), "ok")
        rows.append({"phone": CUST, "role": "user", "content": "Coll me", "created_at": iso(ist(3, 12))})
        self.assertEqual(cr.promise(rows)["slot"], "now")

    def test_the_latest_choice_wins(self):
        rows = chat(ist(3, 11), "1", extra=[
            (ist(3, 11, 5), "assistant", b.flow_marker((b.AWAITING_CALLBACK,))),
            (ist(3, 11, 6), "user", "3")])
        p = cr.promise(rows)
        self.assertEqual((p["slot"], p["chosen_at"]), ("tomorrow", iso(ist(3, 11, 6))))

    def test_a_decline_and_a_complaint_afterwards_are_seen(self):
        rows = chat(ist(3, 11), "1", extra=[(ist(3, 14), "user", "ಕರೆ ಮಾಡಿಲ್ಲ")])
        self.assertTrue(cr.promise(rows)["complained_after"])
        rows = chat(ist(3, 11), "1", extra=[(ist(3, 14), "user", "STOP")])
        self.assertTrue(cr.promise(rows)["declined_after"])

    def test_not_a_bairavi_chat_no_promise(self):
        self.assertIsNone(cr.promise([{"role": "user", "content": "call me", "created_at": iso(ist(3, 11))}]))

    def test_no_choice_no_promise(self):
        self.assertIsNone(cr.promise(chat(ist(3, 11), "Agriculture")[:2]))


class DueTimes(unittest.TestCase):
    def test_owner_call_hours(self):
        cases = [("now", ist(3, 10, 30), ist(3, 11, 30)),
                 ("now", ist(3, 8, 30), ist(3, 10)),        # before 9 am
                 ("now", ist(3, 22), ist(4, 10)),           # after 9 pm
                 ("evening", ist(3, 11, 30), ist(3, 20)),
                 ("evening", ist(3, 20, 30), ist(3, 21, 30)),
                 ("evening", ist(3, 21, 30), ist(4, 20)),
                 ("tomorrow", ist(3, 11, 30), ist(4, 12))]
        for slot, chosen, due in cases:
            with self.subTest(slot=slot, chosen=chosen.strftime("%H:%M")):
                self.assertEqual(cr.due_at(slot, chosen), due)


class Handled(unittest.TestCase):
    CHOSEN = iso(ist(3, 11))

    def test_a_call_logged_after_the_promise(self):
        self.assertTrue(cr.handled(self.CHOSEN, {"last_contacted_at": iso(ist(3, 15)), "pipeline_stage": "Lead"}))

    def test_a_call_from_before_the_promise_does_not_count(self):
        self.assertFalse(cr.handled(self.CHOSEN, {"last_contacted_at": iso(ist(2, 15)), "pipeline_stage": "Lead"}))

    def test_a_lead_moved_on_in_the_pipeline(self):
        self.assertTrue(cr.handled(self.CHOSEN, {"pipeline_stage": "Contacted"}))

    def test_a_manual_message_after_the_promise(self):
        self.assertTrue(cr.handled(self.CHOSEN, {}, [iso(ist(3, 13))]))
        self.assertFalse(cr.handled(self.CHOSEN, {}, [iso(ist(3, 9))]))


# ── The job ─────────────────────────────────────────────────────────────────

class World(unittest.TestCase):
    NOW = ist(3, 14)       # 2 pm IST, inside call hours

    def setUp(self):
        self.brain = chat(ist(3, 11), "1")            # "now" at 11 am -> due 12 pm
        self.clients = [{"phone": CUST, "name": "Muttu S S", "pipeline_stage": "Lead",
                         "last_contacted_at": None, "user_id": "owner"}]
        self.outbound = []
        self.alerts, self.saved = [], []
        self.delivered = 1
        self.fail = None
        self.calls = []

        def get(url, headers=None, params=None, timeout=None):
            params = dict(params or {})
            self.calls.append(url)
            if self.fail and self.fail in url:
                return Resp({}, 503)
            offset, limit = int(params.get("offset", 0)), int(params.get("limit", 1000))
            if url == f"{BRAIN}/rest/v1/whatsapp_messages":
                rows = self.brain
            elif url == f"{CRM}/rest/v1/clients":
                wanted = params["phone"][len("in.("):-1].split(",")
                rows = [c for c in self.clients if c["phone"] in wanted]
            elif url == f"{CRM}/rest/v1/whatsapp_messages":
                rows = self.outbound
            else:
                raise requests.ConnectionError("blocked")
            return Resp(rows[offset:offset + limit])

        def save_messages(items):
            self.saved.extend(items)
            self.brain.extend({"phone": p, "role": r, "content": c,
                               "created_at": iso(self.NOW)} for p, r, c in items)
            return w.SAVE_OK

        self._p = [
            mock.patch.object(requests, "get", get),
            mock.patch.object(w, "SUPABASE_URL", BRAIN),
            mock.patch.object(w, "CRM_SUPABASE_URL", CRM),
            mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"),
            mock.patch.object(w, "staff_and_owner_numbers", lambda: [OWNER]),
            mock.patch.object(w, "notify_owner", lambda m, **k: (self.alerts.append(m), self.delivered)[1]),
            mock.patch.object(w, "save_messages", save_messages),
            mock.patch.dict(os.environ, {"CALL_REMINDERS": "on"}),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def run_job(self, now=None):
        with redirect_stdout(io.StringIO()) as out:
            res = sync.run(now or self.NOW)
        self.log = out.getvalue()
        return res


class Reminding(World):
    def test_an_overdue_promise_is_sent_to_the_owner_once(self):
        res = self.run_job()
        self.assertEqual(res["reminded"], 1)
        msg = self.alerts[0]
        self.assertIn("Customers waiting for your call — 1", msg)
        for must in ("Muttu S S", "25 kVA", "Hosakeri", "asked *now*", f"wa.me/{CUST}",
                     "1234 called interested"):
            self.assertIn(must, msg)
        self.assertEqual(self.saved, [(CUST, "system", cr.marker(iso(ist(3, 11)), "2026-10-03"))])

    def test_not_twice_the_same_day(self):
        self.run_job()
        res = self.run_job(ist(3, 18))
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(res.get("reminded_today"), 1)

    def test_again_the_next_day_while_still_not_called(self):
        self.run_job()
        self.run_job(ist(4, 10))
        self.assertEqual(len(self.alerts), 2)
        self.assertIn("day 2", self.alerts[1])

    def test_a_logged_call_ends_it(self):
        self.clients[0]["last_contacted_at"] = iso(ist(3, 12, 30))
        res = self.run_job()
        self.assertEqual(self.alerts, [])
        self.assertEqual(res.get("handled"), 1)

    def test_a_manual_message_from_the_crm_ends_it_but_the_bots_own_do_not(self):
        self.outbound = [{"phone": CUST, "created_at": iso(ist(3, 11, 1)),
                          "metadata": {"source": "asthra_ai_bot"}}]
        self.run_job()
        self.assertEqual(len(self.alerts), 1, "the bot's reply is not the owner calling")
        self.alerts.clear()
        self.outbound.append({"phone": CUST, "created_at": iso(ist(3, 13)), "metadata": None})
        self.run_job(ist(4, 10))
        self.assertEqual(self.alerts, [])

    def test_not_before_it_is_due(self):
        res = self.run_job(ist(3, 11, 30))
        self.assertEqual(self.alerts, [])
        self.assertEqual(res.get("not_due_yet"), 1)

    def test_never_outside_call_hours_and_reads_nothing(self):
        res = self.run_job(ist(3, 22))
        self.assertEqual((res, self.alerts, self.calls), ({"skipped": "outside_call_hours"}, [], []))

    def test_a_complaint_is_flagged(self):
        self.brain.append({"phone": CUST, "role": "user", "content": "ಕರೆ ಮಾಡಿಲ್ಲ",
                           "created_at": iso(ist(3, 13))})
        self.run_job()
        self.assertIn("complained", self.alerts[0])

    def test_a_decline_is_not_chased(self):
        self.brain.append({"phone": CUST, "role": "user", "content": "no thanks",
                           "created_at": iso(ist(3, 13))})
        res = self.run_job()
        self.assertEqual(self.alerts, [])
        self.assertEqual(res.get("declined"), 1)

    def test_a_week_old_promise_is_dropped(self):
        self.brain = chat(ist(3, 11) - timedelta(days=8), "1")
        res = self.run_job()
        self.assertEqual(self.alerts, [])
        self.assertEqual(res.get("too_old"), 1)

    def test_staff_numbers_are_never_listed(self):
        self.brain = chat(ist(3, 11), "1", phone=OWNER)
        self.run_job()
        self.assertEqual(self.alerts, [])

    def test_a_failed_alert_is_retried_next_run(self):
        self.delivered = 0
        res = self.run_job()
        self.assertEqual((res.get("notify_failed"), self.saved), (1, []))
        self.delivered = 1
        self.run_job(ist(3, 15))
        self.assertEqual(len(self.alerts), 2)

    def test_crm_down_sends_nothing(self):
        self.fail = CRM
        res = self.run_job()
        self.assertEqual((res.get("error"), self.alerts), ("crm_read_failed", []))

    def test_many_waiting_fit_one_message(self):
        self.brain = []
        for i in range(cr.MAX_LINES + 4):
            phone = f"9194800{i:05d}"
            self.brain += chat(ist(3, 10) + timedelta(minutes=i), "1", phone=phone)
            self.clients.append({"phone": phone, "name": f"C{i}", "pipeline_stage": "Lead",
                                 "last_contacted_at": None, "user_id": "owner"})
        self.run_job()
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("…and 4 more", self.alerts[0])
        self.assertEqual(len(self.saved), cr.MAX_LINES + 4, "every listed promise is recorded")

    def test_newest_first_and_addresses_on_one_line(self):
        older = chat(ist(3, 9), "1", phone="919480009999")
        self.brain = older + self.brain
        self.clients.append({"phone": "919480009999", "name": "Old\nLead", "pipeline_stage": "Lead",
                             "last_contacted_at": None, "user_id": "owner"})
        with mock.patch.object(b, "established_from_history",
                               lambda h: {"capacity_kva": 25,
                                          "location": "Baleathiguppe \nPandavapura \nMandya"}):
            self.run_job()
        msg = self.alerts[0]
        self.assertLess(msg.index("Muttu S S"), msg.index("Old Lead"), "the 11 am promise before 9 am")
        self.assertIn("Baleathiguppe Pandavapura Mandya", msg)

    def test_reads_past_one_page(self):
        filler = [{"phone": f"9100000{i:05d}", "role": "user", "content": "hi",
                   "created_at": iso(ist(3, 9))} for i in range(sync.PAGE + 50)]
        self.brain = filler + self.brain
        self.run_job()
        self.assertEqual(len(self.alerts), 1, "the promise sat on page 2")

    def test_off_switch(self):
        with mock.patch.dict(os.environ, {"CALL_REMINDERS": "off"}):
            self.assertEqual(self.run_job(), {"mode": "off"})
        self.assertEqual(self.alerts, [])

    def test_logs_carry_no_names_or_phones(self):
        self.run_job()
        for leak in ("Muttu", CUST, "Hosakeri"):
            self.assertNotIn(leak, self.log)


class TheEndpoint(unittest.TestCase):
    def test_a_failing_reminder_job_never_fails_the_sweep(self):
        import recovery
        import redrive
        tok = "s" * 48
        h = recovery.handler.__new__(recovery.handler)
        h.headers = {"Authorization": f"Bearer {tok}"}
        h.path, h.rfile, h.wfile = "/api/recovery", io.BytesIO(b""), io.BytesIO()
        sent = {}
        h.send_response = lambda c, *a: sent.setdefault("code", c)
        h.send_header = lambda *a: None
        h.end_headers = lambda: None
        with mock.patch.dict(os.environ, {"CRON_SECRET": tok}), \
             mock.patch.object(redrive, "run", lambda: {}), \
             mock.patch.object(recovery, "meta_leads", lambda now=None: {"mode": "off"}), \
             mock.patch.object(sync, "run", mock.Mock(side_effect=RuntimeError("x 919480001234"))), \
             mock.patch.object(recovery, "publish_health", lambda c: "ok"), \
             redirect_stdout(io.StringIO()) as out:
            h.do_POST()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(sent["code"], 200)
        self.assertEqual(body["call_reminders"], {"error": "call_reminders_failed"})
        self.assertNotIn("919480001234", out.getvalue())


if __name__ == "__main__":
    unittest.main()


class TheirOwnTimeIsWhenItIsDue(unittest.TestCase):
    """Option B (2026-10-04): a time the customer named sets when the call is due."""

    def test_due_at_their_hour(self):
        import call_reminders as cr
        from datetime import datetime
        said_at_night = datetime(2026, 10, 4, 22, 30, tzinfo=cr.IST)
        due = cr.due_at("now", said_at_night, time_hour=17, time_at=said_at_night)
        self.assertEqual((due.day, due.hour), (5, 17))                 # tomorrow 5 pm
        said_morning = datetime(2026, 10, 5, 8, 0, tzinfo=cr.IST)
        due = cr.due_at("now", said_morning, time_hour=11, time_at=said_morning)
        self.assertEqual((due.day, due.hour), (5, 11))                 # today 11 am

    def test_promise_reads_the_answer(self):
        import bairavi as b
        import call_reminders as cr
        hist = [
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_CALLBACK,)), "created_at": "2026-10-04T16:00:00+00:00"},
            {"role": "user", "content": "1", "created_at": "2026-10-04T16:30:00+00:00"},
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_CALL_TIME,)), "created_at": "2026-10-04T16:30:01+00:00"},
            {"role": "user", "content": "11", "created_at": "2026-10-04T16:31:00+00:00"},
        ]
        with mock.patch.object(b, "in_transformer_flow", lambda rows: True):
            p = cr.promise(hist)
        self.assertEqual((p["slot"], p["time_hour"], p["time_label"]), ("now", 11, "11 AM"))
