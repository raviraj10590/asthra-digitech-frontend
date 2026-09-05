"""Internal notes must never enter the customer's message stream.

THE PRODUCTION LEAK THIS CLOSES
-------------------------------
A real customer received this, verbatim:

    🤖 Internal lead note (not sent to customer) — 🌤 WARM 60/100: <name>, a
    real estate agent in <city>, is interested in using Meta Ads for his
    business. | Next: Follow up with <name> to understand his specific
    marketing objectives...

The parenthetical was a comment to ourselves. The mechanism said otherwise:
log_reply_to_crm's only action is an INSERT with direction="outbound",
status="sent" — a claim that this text was sent to the customer, written into
the customer's own conversation.

THREE CALLERS DID THIS, not one:
  1. the lead note above          — name, city, trade, our internal next step
  2. the quotation task           — echoed the customer's stated BUDGET back
  3. the follow-up task           — internal scheduling

All three are removed. Nothing is lost: each was immediately preceded by a
notify_owner() carrying the same material more completely.

WHY NOT RE-LABEL INSTEAD. The CRM's schema is not readable from this process
(its credentials are write-only here), so any other `direction` value would be
a guess — and because the write is fire-and-forget, a value the CRM rejects
fails SILENTLY and would look exactly like a fix.

Offline: no HTTP, no provider, no database.
"""

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

WEBHOOK_SRC = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")
PHONE = "919999000444"

# The lead the production leak was built from, reconstructed with synthetic
# values. Every field here is one that appeared in the message a customer saw.
LEAD = {"name": "Test Person", "company": "Test Realty", "city": "Testville",
        "service_needed": "Meta Ads", "budget": "50000", "lead_score": 60,
        "summary": "a real estate agent interested in Meta Ads",
        "next_action": "Follow up to understand marketing objectives",
        "buying_intent": 60, "urgency": 40}

PII = ("Test Person", "Test Realty", "Testville", "50000")


def run_alert(lead=None, already=False):
    """Drive the REAL maybe_alert_lead. Returns (crm_writes, owner_alerts)."""
    crm, owner = [], []
    with mock.patch.object(w, "log_reply_to_crm",
                           lambda phone, body: crm.append(body)), \
         mock.patch.object(w, "notify_owner", lambda msg, **k: owner.append(msg)), \
         redirect_stdout(io.StringIO()):
        w.maybe_alert_lead(PHONE, LEAD if lead is None else lead, already)
    return crm, owner


def run_workflows(actions):
    """Drive the REAL run_workflows. Returns (crm_writes, owner_alerts)."""
    crm, owner = [], []
    lead = dict(LEAD); lead["actions"] = actions
    ctx = {"recent_sys": [], "history": [], "paused": False,
           "vip_alerted": False, "lead_alerted": False, "last_user": {}}
    with mock.patch.object(w, "log_reply_to_crm",
                           lambda phone, body: crm.append(body)), \
         mock.patch.object(w, "notify_owner", lambda msg, **k: owner.append(msg)), \
         mock.patch.object(w, "save_message", lambda *a, **k: None), \
         mock.patch.object(w, "send_text", lambda *a, **k: None), \
         mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
         mock.patch.object(w, "upsert_lead", lambda *a, **k: None), \
         redirect_stdout(io.StringIO()):
        w.run_workflows(PHONE, lead, ctx)
    return crm, owner


# ══════════════════════════════════════════════════════════════════════════
# 1 · the exact leak, pinned
# ══════════════════════════════════════════════════════════════════════════

class TheReportedLeak(unittest.TestCase):

    def test_no_internal_lead_note_is_written_to_the_customer_stream(self):
        """THE REGRESSION. A real customer received this text."""
        crm, _ = run_alert()
        self.assertEqual(crm, [], f"internal note leaked to CRM: {crm}")

    def test_the_phrase_itself_is_gone_from_the_codebase(self):
        src = io.open(WEBHOOK_SRC, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        self.assertNotIn('f"🤖 Internal lead note', code)

    def test_no_lead_pii_can_reach_the_crm_from_the_alert_path(self):
        crm, _ = run_alert()
        blob = " ".join(crm)
        for secret in PII:
            self.assertNotIn(secret, blob, secret)

    def test_the_owner_still_receives_the_full_alert(self):
        """Removing the note must not cost the owner information."""
        _, owner = run_alert()
        self.assertEqual(len(owner), 1)
        blob = owner[0]
        self.assertIn("Test Person", blob)
        self.assertIn(LEAD["summary"], blob)
        self.assertIn(LEAD["next_action"], blob)

    def test_an_already_alerted_lead_still_writes_nothing(self):
        crm, _ = run_alert(already=True)
        self.assertEqual(crm, [])


# ══════════════════════════════════════════════════════════════════════════
# 2 · the two the owner had not seen yet
# ══════════════════════════════════════════════════════════════════════════

class TheOtherTwoLeaks(unittest.TestCase):

    def test_the_quotation_task_no_longer_echoes_the_budget_back(self):
        """This one returned the customer's own stated budget to them."""
        crm, owner = run_workflows({"quotation_requested": True})
        self.assertEqual(crm, [])
        self.assertTrue(any("QUOTATION" in o for o in owner))
        self.assertNotIn("50000", " ".join(crm))

    def test_the_followup_task_is_not_written_to_the_customer(self):
        crm, owner = run_workflows({"followup_date": "2026-10-01"})
        self.assertEqual(crm, [])
        self.assertTrue(any("FOLLOW-UP" in o for o in owner))

    def test_the_owner_still_gets_both_notifications(self):
        _, owner = run_workflows({"quotation_requested": True,
                                  "followup_date": "2026-10-01"})
        joined = " ".join(owner)
        self.assertIn("QUOTATION", joined)
        self.assertIn("FOLLOW-UP", joined)
        self.assertIn("50000", joined, "the owner should still see the budget")

    def test_no_workflow_writes_anything_to_the_crm_stream(self):
        for actions in ({"meeting_requested": True, "meeting_time": "Mon"},
                        {"callback_requested": True},
                        {"quotation_requested": True},
                        {"followup_date": "2026-10-01"},
                        {"unhappy": True, "unhappy_reason": "late"}):
            crm, _ = run_workflows(actions)
            self.assertEqual(crm, [], f"{actions} leaked {crm}")


# ══════════════════════════════════════════════════════════════════════════
# 3 · the contract, so it cannot regress
# ══════════════════════════════════════════════════════════════════════════

class OnlySendTextMayMirror(unittest.TestCase):

    def call_sites(self):
        src = io.open(WEBHOOK_SRC, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        return [m for m in re.findall(r"log_reply_to_crm\([^)]*\)", code)
                if not m.startswith("log_reply_to_crm(phone: str")]

    def test_there_is_exactly_one_caller(self):
        """It writes direction=outbound/status=sent, so its only honest
        caller is the function that actually sent the message."""
        self.assertEqual(len(self.call_sites()), 1, self.call_sites())

    def test_that_caller_is_send_text(self):
        import inspect
        self.assertIn("log_reply_to_crm(to, message)",
                      inspect.getsource(w.send_text))

    def test_the_mirror_still_records_a_genuine_reply(self):
        """The legitimate path must keep working."""
        sent = []
        with mock.patch.object(w, "_wa_post", lambda p: {"ok": True}), \
             mock.patch.object(w, "log_reply_to_crm",
                               lambda phone, body: sent.append(body)), \
             mock.patch.object(w, "save_message", lambda *a, **k: None), \
             redirect_stdout(io.StringIO()):
            w.send_text(PHONE, "ನಮಸ್ಕಾರ 🙏")
        self.assertEqual(sent, ["ನಮಸ್ಕಾರ 🙏"])

    def test_the_write_still_claims_outbound_sent(self):
        """Unchanged — which is exactly why nothing unsent may pass through."""
        import inspect
        src = inspect.getsource(w.log_reply_to_crm)
        self.assertIn('"direction": "outbound"', src)
        self.assertIn('"status": "sent"', src)

    def test_the_contract_is_written_down(self):
        import inspect
        doc = (w.log_reply_to_crm.__doc__ or "")
        self.assertIn("ONE LEGITIMATE CALLER", doc)


# ══════════════════════════════════════════════════════════════════════════
# 4 · nothing else moved
# ══════════════════════════════════════════════════════════════════════════

class UnrelatedBehaviourUnchanged(unittest.TestCase):

    def test_notify_owner_is_untouched(self):
        import inspect
        self.assertTrue(callable(w.notify_owner))
        src = inspect.getsource(w.maybe_alert_lead)
        self.assertIn("notify_owner", src)

    def test_the_extraction_cadence_is_unchanged(self):
        import inspect
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      inspect.getsource(w.run_client_pipeline))

    def test_lead_upsert_and_crm_sync_are_unchanged(self):
        import inspect
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")',
                      inspect.getsource(w.upsert_lead))
        self.assertTrue(callable(w.sync_lead_to_crm))

    def test_provider_config_is_unchanged(self):
        self.assertEqual(w.DEEPSEEK_MAX_TOKENS, 1200)
        self.assertEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 35)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)

    def test_business_reasoning_is_unchanged(self):
        import inspect
        self.assertIn("bic_reasoning.reason",
                      inspect.getsource(w.tool_business_reasoning))


if __name__ == "__main__":
    unittest.main(verbosity=2)
