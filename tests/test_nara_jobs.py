"""NaraRouter morning jobs: lead summaries + bot health check (2026-10-01)."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))

import nara_jobs as n  # noqa: E402
import call_briefing as cb  # noqa: E402

NOW = datetime(2026, 10, 1, 2, 45, tzinfo=timezone.utc)      # 08:15 IST


def m(direction, body, at):
    return {"direction": direction, "body": body, "created_at": at, "phone": "919000005711"}


class Summaries(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(n.parse_summary("thinking...\nsum=63 kVA x2, Gokak; asked about poles"),
                         "63 kVA x2, Gokak; asked about poles")
        self.assertEqual(n.parse_summary("sum=Needs 1 unit agriculture delivery not stated kVA not stated"),
                         "Needs 1 unit agriculture")
        for bad in ("", "no answer", "sum=<max 20 English words>", "sum=price ₹95,000 agreed",
                    "sum=call 9876543210", "sum=" + "x" * 201):
            self.assertIsNone(n.parse_summary(bad), bad)

    def test_one_summary_line_replaced_not_piled_up(self):
        notes = "Service: transformer\n🧠 AI 30 Sep 08:15 — old\n🔥 30 Sep 19:52 call: Interested — ok"
        out = n.with_summary(notes, n.summary_line("new", NOW))
        self.assertEqual(out, "Service: transformer\n🔥 30 Sep 19:52 call: Interested — ok\n"
                              "🧠 AI 01 Oct 08:15 — new")

    def test_stale_only_when_the_customer_wrote_after_it(self):
        notes = "🧠 AI 30 Sep 20:00 — x"
        self.assertFalse(n.summary_is_stale(notes, datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc), NOW))
        self.assertTrue(n.summary_is_stale(notes, datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc), NOW))
        self.assertTrue(n.summary_is_stale("", NOW, NOW))

    def test_year_turn(self):
        jan = datetime(2027, 1, 1, 3, 0, tzinfo=timezone.utc)
        self.assertFalse(n.summary_is_stale("🧠 AI 31 Dec 20:00 — x",
                                            datetime(2026, 12, 31, 10, 0, tzinfo=timezone.utc), jan))
        # made 31 Dec 2026, the customer wrote on 1 Jan 2027: stale
        self.assertTrue(n.summary_is_stale("🧠 AI 31 Dec 20:00 — x",
                                           datetime(2027, 1, 1, 2, 0, tzinfo=timezone.utc), jan))

    def test_transcript_carries_no_phone_numbers(self):
        t = n.transcript([m("inbound", "call me on 98765 43210 or +919876543210", "2026-09-30T10:00:00Z"),
                          m("outbound", "ಸರಿ", "2026-09-30T10:00:05Z")])
        self.assertEqual(t, "CUSTOMER: call me on [number] or [number]\nBOT: ಸರಿ")

    def test_the_briefing_shows_it(self):
        self.assertEqual(cb.ai_summary("x\n🧠 AI 01 Oct 08:15 — 63 kVA x2, Gokak"), "63 kVA x2, Gokak")
        self.assertIsNone(cb.ai_summary("no summary"))


class DeterministicChecks(unittest.TestCase):
    def test_english_to_kannada(self):
        msgs = [m("inbound", "ಅಲ್ಲಿ ಒಂದು ಹಳ್ಳಿ", "2026-09-30T10:00:00Z"),
                m("outbound", "We are a manufacturer of oil-immersed 3-phase distribution transformers.",
                  "2026-09-30T10:00:04Z")]
        self.assertIn("English reply to a customer writing Kannada", n.deterministic_issues(msgs))

    def test_english_to_english_is_fine(self):
        msgs = [m("inbound", "where is your factory", "2026-09-30T10:00:00Z"),
                m("outbound", "We are a manufacturer of oil-immersed 3-phase distribution transformers.",
                  "2026-09-30T10:00:04Z")]
        self.assertEqual(n.deterministic_issues(msgs), [])

    def test_repeated_message(self):
        q = "Transformer *ಡೆಲಿವರಿ* ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು? (ಊರು, ತಾಲ್ಲೂಕು)"
        msgs = [m("outbound", q, f"2026-09-30T10:0{i}:00Z") for i in range(3)]
        self.assertIn("the same bot message was sent 3+ times", n.deterministic_issues(msgs))
        self.assertEqual(n.deterministic_issues(msgs[:2]), [])

    def test_unanswered(self):
        msgs = [m("inbound", "Nimdu tc yav company du", "2026-09-30T10:00:00Z")]
        self.assertEqual(n.deterministic_issues(msgs), ["no reply to “Nimdu tc yav company du”"])
        # the CRM stores the reply up to a few seconds BEFORE the message
        self.assertEqual(n.deterministic_issues(msgs + [m("outbound", "ನಾವು ತಯಾರಕರು", "2026-09-30T09:59:58Z")]), [])

    def test_thanks_and_declines_are_owed_no_reply(self):
        for t in ("Thanks sir", "ಧನ್ಯವಾದಗಳು ಸಿಸ್ಟಮ್", "No thanx", "🙏🙏"):
            self.assertEqual(n.deterministic_issues([m("inbound", t, "2026-09-30T10:00:00Z")]), [], t)


class Verdicts(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(n.parse_verdict("...\nverdict=OK"), (True, None))
        self.assertEqual(n.parse_verdict("verdict=ISSUE; reason=repeats delivery question"),
                         (False, "repeats delivery question"))
        self.assertEqual(n.parse_verdict("verdict=ISSUE"), (False, "possible mistake (no reason given)"))
        self.assertIsNone(n.parse_verdict("I think it is fine"))

    def test_note(self):
        self.assertEqual(n.bot_check_note(["no reply to “x”"], "ignored poles question"),
                         "🤖 Bot check: no reply to “x”; AI: ignored poles question")


CLIENT = {"id": "c1", "name": "Sudarshan", "phone": "919000005711", "notes": "Service: x",
          "business_id": "b1", "user_id": "u1", "created_at": "2026-09-29T08:00:00+00:00"}
OWNER = dict(CLIENT, id="c2", phone="918884448141")
MSGS = [m("inbound", "Hello! I filled out your form and would like to know more about your business.\n\n"
                     "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: Sira\nFull name: X", "2026-09-30T08:00:00+00:00"),
        m("outbound", "ನಮಸ್ಕಾರ", "2026-09-30T08:00:01+00:00"),
        m("inbound", "Kamba yalla bantha", "2026-09-30T08:01:00+00:00"),
        m("outbound", "ಸರಿ", "2026-09-30T08:01:05+00:00"),
        m("inbound", "Nimdu tc yav company du", "2026-09-30T08:02:00+00:00")]


class TheRun(unittest.TestCase):
    def go(self, dry=False, model=lambda system: "sum=25 kVA, Sira; asked about poles"):
        sql = []

        def fake_sql(query):
            sql.append(query)
            if "from public.clients" in query:
                return [CLIENT, OWNER]
            if "from public.whatsapp_messages" in query:
                return MSGS + [dict(x, phone=OWNER["phone"]) for x in MSGS]
            return []

        def fake_call(key, system, text, job, activity):
            activity.append({"created_at": "2026-10-01T02:45:00+00:00", "provider": "nararouter",
                             "key_label": "k", "job": job, "model": "m", "outcome": "ok", "http_status": 200,
                             "latency_ms": 1, "input_chars": 1, "output_chars": 1, "est_tokens": 1})
            self.assertNotIn("919000005711", text)
            return model(system) if job == "lead_summary" else "verdict=ISSUE; reason=ignored poles question"

        with mock.patch.object(n, "_sql", fake_sql), mock.patch.object(n, "call_model", fake_call), \
             mock.patch.object(n, "nara_key", lambda: "k"), \
             mock.patch.object(n, "datetime", wraps=datetime) as dt:
            dt.now.side_effect = lambda tz=None: NOW if tz is None else NOW.astimezone(tz)
            stats = n.run(dry, 0, "owner@example.com")
        return stats, sql

    def test_writes(self):
        stats, sql = self.go()
        self.assertEqual(stats["summaries"], 1)
        self.assertEqual(stats["flagged"], 1)
        upd = [s for s in sql if s.startswith("update public.clients")]
        self.assertEqual(len(upd), 1)
        self.assertIn("🧠 AI 01 Oct 08:15 — 25 kVA, Sira; asked about poles", upd[0])
        self.assertIn("where id = 'c1'", upd[0])
        fu = [s for s in sql if s.startswith("insert into public.follow_ups")]
        self.assertEqual(len(fu), 1)
        self.assertIn("🤖 Bot check: no reply to “Nimdu tc yav company du”; AI: ignored poles question", fu[0])
        self.assertIn("'2026-10-01'::date", fu[0])
        self.assertIn("where not exists", fu[0])            # once per lead per day
        self.assertIn("'b1'", fu[0])                        # business kept, so RLS lets the owner see it
        self.assertTrue(any(s.startswith("insert into public.api_key_activity") for s in sql))
        self.assertFalse(any("c2" in s for s in upd + fu))  # the owner's own number is never a lead

    def test_dry_run_writes_nothing(self):
        stats, sql = self.go(dry=True)
        self.assertEqual(stats["summaries"], 1)
        self.assertFalse(any(s.startswith(("update", "insert")) for s in sql))

    def test_a_bad_summary_is_not_written(self):
        stats, sql = self.go(model=lambda s: "I could not decide")
        self.assertEqual(stats["summary_failed"], 1)
        self.assertFalse(any(s.startswith("update public.clients") for s in sql))

    def test_quotes_cannot_break_the_sql(self):
        self.assertEqual(n.q("it's"), "'it''s'")
        self.assertEqual(n.q(None), "NULL")


if __name__ == "__main__":
    unittest.main()
