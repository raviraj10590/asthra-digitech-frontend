"""The owner's own chat with his assistant, 2026-10-05 — three fixes.

(a) a burst of short messages got one reply each, answering stale ones;
(b) the assistant did not know Bairavi's price list or terms;
(c) call notes typed with a NAME ("Shashi nanjappa", "VINAY … 15 days later")
    were only acknowledged, never saved to the CRM.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                             # noqa: E402
import call_log as c                                            # noqa: E402
import webhook as w                                             # noqa: E402

OWNER = "910000000001"
LEADS = [{"id": "L1", "name": "Shashi Nanjappa", "phone": "918496969822"},
         {"id": "L2", "name": "Vinay Vini Vinay Vini", "phone": "919000008852"},
         {"id": "L3", "name": "Vinay Kumar", "phone": "919000001111"},
         {"id": "L4", "name": "Bharath Patel", "phone": "919000005514"}]


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class BairaviFactsForTheOwner(unittest.TestCase):
    def test_every_price_and_term_is_there(self):
        f = b.owner_facts_en()
        for s in ("25 kVA 4 Star ₹95,000", "63 kVA 5 Star ₹2,00,000",
                  "100 kVA 5 Star ₹2,95,000", "250 kVA 5 Star ₹4,95,000",
                  "Transport INCLUDED", "Installation NOT", "1 year", "50% advance",
                  "MESCOM approved", "does NOT make generators", "Repair up to 2500 kVA"):
            self.assertIn(s, f)

    def test_the_owner_prompt_carries_them(self):
        seen = {}

        def fake_ai(messages, apology, max_tokens=None):
            seen["m"] = messages
            return '{"reply": "ok", "memory": ""}'
        with mock.patch.object(w, "fetch_owner_memory", return_value=""), \
             mock.patch.object(w, "recall_from_archive", return_value=""), \
             mock.patch.object(w, "owner_business_snapshot", return_value=""), \
             mock.patch.object(w, "_generate_ai_reply", fake_ai), \
             mock.patch.object(w, "update_owner_memory"), \
             redirect_stdout(io.StringIO()):
            w.generate_owner_reply(OWNER, "OWNER", "Raviraj", "quotation for Bharath", [])
        self.assertTrue(any("₹2,95,000" in m["content"] for m in seen["m"]
                            if m["role"] == "system"))


class CallNotesByName(unittest.TestCase):
    def test_followup_days(self):
        for text, days in (("customer interested after one month", 30),
                           ("he told call me 15 days letter", 15),
                           ("call after 2 weeks", 14), ("next week", 7),
                           ("ondu thingalu nantara", 30), ("Call done", None),
                           ("25kva 4 star", None)):
            with self.subTest(text=text):
                self.assertEqual(c.followup_days(text), days)

    def test_the_real_notes(self):
        self.assertEqual(c.outcome_of("This is done customer interested after one month"),
                         (c.INTERESTED, 30))
        self.assertEqual(c.outcome_of("I got call from VINAY kumar MK he told call me 15 days letter"),
                         (c.CONTACTED, 15))
        self.assertEqual(c.outcome_of("Bharath want catalog and quotations")[0], c.NEGOTIATION)
        self.assertIsNone(c.outcome_of("Shashi nanjappa"))

    def test_names(self):
        self.assertEqual([r["id"] for r in c.name_matches("Shashi nanjappa", LEADS)], ["L1"])
        self.assertEqual([r["id"] for r in c.name_matches(
            "I got call from VINAY kumar MK he told call me 15 days letter", LEADS)], ["L3"])
        self.assertEqual(len(c.name_matches("I talk with VINAY Bharath omkar Murty", LEADS)), 3)

    def test_a_request_is_not_a_note(self):
        for t in ("draft a quotation for Bharath", "Bharath quotation ready maadu",
                  "what did Shashi say?"):
            self.assertTrue(c.is_request(t), t)
        self.assertFalse(c.is_request("Bharath want catalog and quotations"))

    def test_a_note_without_a_name_waits_for_the_name(self):
        history = [{"role": "user", "content": "Call done", "created_at": ago(23)},
                   {"role": "assistant", "content": "Which contact was it?", "created_at": ago(23)},
                   {"role": "user", "content": "This is done customer interested after one month",
                    "created_at": ago(22)},
                   {"role": "assistant", "content": "Tell me who it was.", "created_at": ago(22)}]
        stage, days, words = c.pending_note(history, datetime.now(timezone.utc))
        self.assertEqual((stage, days), (c.INTERESTED, 30))
        self.assertIn("Call done", words)

    def test_an_old_or_saved_note_does_not_wait(self):
        old = [{"role": "user", "content": "call done", "created_at": ago(90)}]
        self.assertIsNone(c.pending_note(old, datetime.now(timezone.utc)))
        saved = [{"role": "user", "content": "call done", "created_at": ago(5)},
                 {"role": "assistant", "content": "✅ X (…1234) → *Contacted*", "created_at": ago(5)}]
        self.assertIsNone(c.pending_note(saved, datetime.now(timezone.utc)))


class SavedToTheCrm(unittest.TestCase):
    def _note(self, text, history=None):
        calls = {}

        def fake_run_tool(sender, code, _fallback=None, **args):
            calls.update(code=code, **args)
            return "SAVED"
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "u"), \
             mock.patch.object(w, "_crm_owner_leads", return_value=LEADS), \
             mock.patch.object(w, "run_tool", fake_run_tool):
            out = w.named_call_note(OWNER, text, history or [])
        return out, calls

    def test_a_named_note_with_a_followup(self):
        out, calls = self._note("I got call from VINAY kumar MK he told call me 15 days letter")
        self.assertEqual(out, "SAVED")
        self.assertEqual((calls["lead_id"], calls["stage"], calls["days"]), ("L3", c.CONTACTED, 15))

    def test_the_name_completes_the_waiting_note(self):
        history = [{"role": "user", "content": "This is done customer interested after one month",
                    "created_at": ago(20)}]
        out, calls = self._note("Shashi nanjappa", history)
        self.assertEqual((calls["lead_id"], calls["stage"], calls["days"]), ("L1", c.INTERESTED, 30))

    def test_several_matches_are_never_written(self):
        out, calls = self._note("I talk with VINAY Bharath omkar Murty")
        self.assertIn("not saved", out)
        self.assertEqual(calls, {})

    def test_not_a_note_goes_to_the_assistant(self):
        for t in ("draft a quotation for Bharath", "Call done", "Shashi nanjappa"):
            self.assertIsNone(self._note(t)[0], t)

    def test_the_tool_adds_the_crm_followup(self):
        posted, patched = {}, {}

        class R:
            ok = True

            def __init__(self, data=None):
                self._d = data

            def json(self):
                return self._d

            def raise_for_status(self):
                return None
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "u"), \
             mock.patch.object(w.requests, "get", lambda *a, **k: R([dict(LEADS[0], notes="")])), \
             mock.patch.object(w.requests, "patch", lambda url, **k: patched.update(k["json"]) or R()), \
             mock.patch.object(w.requests, "post", lambda url, **k: posted.update(url=url, **k["json"]) or R()), \
             redirect_stdout(io.StringIO()):
            out = w.tool_call_outcome(OWNER, stage=c.INTERESTED, words="interested after one month",
                                      lead_id="L1", days=30)
        self.assertEqual(patched["pipeline_stage"], c.INTERESTED)
        self.assertTrue(posted["url"].endswith("/follow_ups"))
        self.assertEqual(posted["client_id"], "L1")
        self.assertIn("Follow-up added", out)
        due = (datetime.now(timezone(timedelta(hours=5, minutes=30))).date() + timedelta(days=30))
        self.assertEqual(posted["due_date"], due.isoformat())


class OneReplyPerBurst(unittest.TestCase):
    def _burst(self, text, rows):
        saved = []
        with mock.patch.object(w, "OWNER_BURST_SECONDS", 0.01), \
             mock.patch.object(w, "save_message", lambda *a: saved.append(a)), \
             mock.patch.object(w.time, "sleep"), \
             mock.patch.object(w, "fetch_context", return_value={"history": rows}), \
             redirect_stdout(io.StringIO()):
            w._TURN_EXTRAS.clear()
            return w.owner_burst(OWNER, text, []), saved

    def test_the_newest_message_answers_the_whole_burst(self):
        rows = [{"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "Transformer"}, {"role": "user", "content": "25kva"},
                {"role": "user", "content": "4 star"}, {"role": "user", "content": "95k plus gst"}]
        (text, history), saved = self._burst("95k plus gst", rows)
        self.assertEqual(text, "Transformer\n25kva\n4 star\n95k plus gst")
        self.assertEqual(history, rows[:1])
        self.assertEqual(saved, [(OWNER, "user", "95k plus gst")])

    def test_an_older_message_stays_quiet(self):
        rows = [{"role": "user", "content": "Transformer"}, {"role": "user", "content": "25kva"}]
        self.assertIsNone(self._burst("Transformer", rows)[0])

    def test_a_command_answered_meanwhile_does_not_silence_it(self):
        rows = [{"role": "user", "content": "draft Bharath quotation"},
                {"role": "user", "content": "#today"}, {"role": "assistant", "content": "Today: …"}]
        (text, _), _ = self._burst("draft Bharath quotation", rows)
        self.assertEqual(text, "draft Bharath quotation")

    def test_the_owner_message_is_not_saved_twice(self):
        saved = []
        w._TURN_EXTRAS.clear()
        w._TURN_EXTRAS["owner_user_saved"] = True
        with mock.patch.object(w, "save_messages", lambda items: saved.extend(items)), \
             mock.patch.object(w, "send_text"):
            w._save_owner_turn(OWNER, "hi", "reply")
            w._save_owner_turn(OWNER, "hi", "")
        w._TURN_EXTRAS.clear()
        self.assertEqual(saved, [(OWNER, "assistant", "reply")])


if __name__ == "__main__":
    unittest.main()


class NoDirectManufacturerClaim(unittest.TestCase):
    """Owner, 2026-10-05: Bairavi also sells through distributors and electrical
    contractors, so "direct manufacturer — no middleman" must never be said."""

    def test_the_customer_info_card(self):
        for kva in (25, 63, 100, 250, None):
            card = b.info_card_kn({"capacity_kva": kva})
            self.assertNotIn("ಮಧ್ಯವರ್ತಿ", card)
            self.assertNotIn("ನೇರ ತಯಾರಕ", card)

    def test_the_owner_assistant_is_told(self):
        f = b.owner_facts_en()
        self.assertIn("distributors and electrical contractors", f)
        self.assertIn("No dry-type", f)
