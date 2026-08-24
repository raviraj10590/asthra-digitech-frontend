"""The first real Brain decision loop, wired into run_client_pipeline.

Integration-level: drives the REAL run_client_pipeline (not a reimplementation
of it), with bic.context.assemble/bic.identity.resolve/bic.party and the DB
write mocked so each scenario is deterministic and offline. bic.decide's own
adjudication logic is exercised for real — only its inputs are controlled.

Offline: no network, no AI provider, no database.
"""

import os
import sys
import unittest
from contextlib import ExitStack
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                               # noqa: E402
from bic import context as cx                                     # noqa: E402
from bic import decision as bic_decision                          # noqa: E402
from bic import policy                                            # noqa: E402
from bic.db import DbError                                        # noqa: E402

CLIENT = "919555555555"
TENANT = w.bic_config.DEFAULT_TENANT_ID
CTX = {"history": [{"role": "user", "content": "prior"}],
      "paused": False, "vip_alerted": False, "lead_alerted": False,
      "recent_sys": [], "last_user": {}}


def proceed_packet():
    return {
        "tenant_id": TENANT, "goal_ref": "social_media_enquiry",
        "principal": {"risk_tier_ceiling": 1},
        "epistemic": {"sufficiency": {"verdict": cx.PROCEED,
                                      "reason": "ok", "gaps": []}},
    }


def clarify_packet():
    return {
        "tenant_id": TENANT, "goal_ref": "social_media_enquiry",
        "principal": {"risk_tier_ceiling": 1},
        "epistemic": {"sufficiency": {
            "verdict": cx.CLARIFY, "reason": "missing: service_interest",
            "gaps": [{"slot": "service_interest", "class": cx.OBTAINABLE_BY_ASKING,
                     "why": "no fact on record"}]}},
    }


def refuse_packet():
    return {
        "tenant_id": TENANT, "goal_ref": "social_media_enquiry",
        "principal": {"risk_tier_ceiling": 1},
        "epistemic": {"sufficiency": {"verdict": cx.REFUSE,
                                      "reason": "unresolved conflict", "gaps": []}},
    }


class Base(unittest.TestCase):
    """Drives run_client_pipeline for real, with everything around it
    stubbed for determinism and to stay offline."""

    def setUp(self):
        self.sent = []
        self.saved = []
        self.inserted = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # A clean decision-record turn per test — mirrors _decision_open(),
        # and guarantees no state leaks between tests (the exact failure
        # mode already known to affect this suite when order isn't reset).
        bic_decision.close_turn()
        self.addCleanup(bic_decision.close_turn)
        bic_decision.open_turn()
        bic_decision.mark_route("client")
        bic_decision.mark_identity("CLIENT")

        p = self.stack.enter_context
        p(mock.patch.object(w, "BIC_AVAILABLE", True))
        p(mock.patch.object(w, "send_text",
                            lambda to, t, **k: self.sent.append((to, t))))
        p(mock.patch.object(w, "save_messages",
                            lambda items: self.saved.append(list(items))))
        p(mock.patch.object(w, "save_message", lambda *a, **k: None))
        p(mock.patch.object(w, "fetch_memory", lambda s: {}))
        p(mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None))
        p(mock.patch.object(w, "after_hours_note", lambda: ""))
        p(mock.patch.object(w, "extract_lead_info", lambda h: {}))
        p(mock.patch.object(w, "generate_reply",
                            lambda *a, **k: "LLM PROPOSAL TEXT"))
        p(mock.patch.object(w.bic_identity, "resolve",
                            lambda sender, channel="whatsapp", **k:
                            policy.Principal(sender, "CLIENT", TENANT)))
        p(mock.patch.object(w.bic_party, "resolve_or_create",
                            lambda tenant, channel, sender, **k: "subj-fixed"))
        p(mock.patch.object(w.bic_db, "insert",
                            lambda table, row, **k: self.inserted.append((table, row))))
        self.producers = mock.Mock()
        p(mock.patch.object(w, "bic_outcome_producers", self.producers))

    def with_packet(self, packet):
        return mock.patch.object(w.bic_context, "assemble", lambda *a, **k: packet)

    # A message that DOES admit the one supported goal. Uses the service
    # vocabulary the bot's own menu already uses for this row.
    ADMITTING_TEXT = "I need help with instagram and social media marketing"

    def run_pipeline(self, text=None):
        w.run_client_pipeline(CLIENT, text if text is not None else self.ADMITTING_TEXT,
                              dict(CTX), message_id="wamid.T1")


# ── 1, 7, 13 · the Brain path runs and produces a normal response ─────────

class NormalPath(Base):

    def test_normal_message_enters_the_brain_path_and_responds(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))

    def test_llm_proposal_is_generated_and_used_on_proceed(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertIn("LLM PROPOSAL TEXT", self.sent[0][1])

    def test_clarify_response_still_reaches_the_customer(self):
        with self.with_packet(clarify_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("service_interest", self.sent[0][1])
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])

    def test_refuse_response_still_reaches_the_customer(self):
        with self.with_packet(refuse_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])


# ── 9 · DECIDE overrides an unsafe (denied) proposal ────────────────────

class DecideOverridesProposal(Base):

    def test_authorization_denial_downgrades_proceed_to_refuse(self):
        pkt = proceed_packet()
        pkt["goal_ref"] = "a_mismatched_goal"  # forces authorize() to deny
        with self.with_packet(pkt):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])


# ── 11, 12 · record before respond ──────────────────────────────────────

class RecordBeforeRespond(Base):

    def test_record_write_happens_before_send_text(self):
        order = []
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert",
            lambda table, row, **k: order.append("insert")))
        self.stack.enter_context(mock.patch.object(
            w, "send_text", lambda to, t, **k: order.append("send")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(order, ["insert", "send"])

    def test_record_failure_prevents_the_response(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", side_effect=DbError("store down")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved, [])

    def test_record_failure_does_not_crash_the_turn(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", side_effect=DbError("store down")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()  # must not raise out of the test


# ── 2 · goal handling / fallback ────────────────────────────────────────

class FallbackToLegacy(Base):

    def test_brain_infrastructure_error_falls_back_to_legacy_reply(self):
        """An unexpected error in context assembly must not brick the
        customer's reply — the legacy AI path still answers."""
        self.stack.enter_context(mock.patch.object(
            w.bic_context, "assemble", side_effect=RuntimeError("boom")))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))

    def test_bic_unavailable_falls_back_to_legacy_reply(self):
        self.stack.enter_context(mock.patch.object(w, "BIC_AVAILABLE", False))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))


# ── 15, 16 · tenant isolation carried through the wiring ────────────────

class TenantAndSecurity(Base):

    def test_foreign_tenant_packet_is_refused_not_executed(self):
        pkt = proceed_packet()
        pkt["tenant_id"] = "99999999-9999-4999-8999-999999999999"
        with self.with_packet(pkt):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])

    def test_party_identity_is_resolved_for_the_subject(self):
        seen = []
        self.stack.enter_context(mock.patch.object(
            w.bic_party, "resolve_or_create",
            lambda tenant, channel, sender, **k: seen.append((tenant, channel)) or "subj-fixed"))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(seen, [(TENANT, w.bic_party.WHATSAPP)])

    def test_no_identifier_reaches_the_decision_record(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        blob = repr(self.inserted)
        self.assertNotIn(CLIENT, blob)
        self.assertNotIn("wamid", blob)


# ── 1-2 · admission gates which turns enter the Brain slice ─────────────

class GoalAdmission(Base):

    def test_supported_request_enters_the_brain_slice(self):
        with self.with_packet(clarify_packet()):
            self.run_pipeline("can you manage our instagram?")
        # A CLARIFY reply proves the Brain decided it, not the legacy path.
        self.assertIn("service_interest", self.sent[0][1])

    def test_unsupported_request_keeps_legacy_behaviour(self):
        called = []
        self.stack.enter_context(mock.patch.object(
            w.bic_context, "assemble",
            lambda *a, **k: called.append(1) or proceed_packet()))
        self.run_pipeline("what are your prices?")
        self.assertEqual(called, [], "context must not be assembled for an "
                                     "unsupported request")
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))

    def test_unsupported_request_still_uses_the_legacy_outcome_producer(self):
        """The 2I producer wiring on the legacy path must survive untouched."""
        self.run_pipeline("what are your prices?")
        self.assertTrue(self.producers.expect_customer_reply.called)


# ── 26, 41-42 · REGISTER EXPECTATION before respond ─────────────────────

class RegisterExpectation(Base):

    def test_expectation_registered_on_proceed(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertTrue(self.producers.expect_customer_reply.called)
        kwargs = self.producers.expect_customer_reply.call_args.kwargs
        self.assertEqual(kwargs["goal_ref"], "social_media_enquiry")

    def test_expectation_registered_before_send(self):
        order = []
        self.producers.expect_customer_reply.side_effect = \
            lambda *a, **k: order.append("expect")
        self.stack.enter_context(mock.patch.object(
            w, "send_text", lambda to, t, **k: order.append("send")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(order, ["expect", "send"])

    def test_no_expectation_when_the_action_did_not_go_out(self):
        with self.with_packet(refuse_packet()):
            self.run_pipeline()
        self.assertFalse(self.producers.expect_customer_reply.called)

    def test_expectation_failure_does_not_block_the_reply(self):
        """Migration 17 is deliberately unapplied, so the outcome table does
        not exist in production. A fatal expectation write would silence
        every supported customer until it ships."""
        self.producers.expect_customer_reply.side_effect = DbError("no table")
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))

    def test_expectation_is_attributed_to_the_recorded_decision(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        decision_ref = self.producers.expect_customer_reply.call_args.args[1]
        recorded_turn_ids = [row.get("turn_id") for _, row in self.inserted]
        self.assertIn(decision_ref, recorded_turn_ids)


# ── 30 · execution surface stays exactly one reply ──────────────────────

class ExecutionSurface(Base):

    def test_exactly_one_send_per_turn(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)

    def test_no_crm_or_external_side_effects_added(self):
        crm = []
        self.stack.enter_context(mock.patch.object(
            w, "log_reply_to_crm", lambda *a, **k: crm.append(1)))
        self.stack.enter_context(mock.patch.object(
            w, "sync_lead_to_crm", lambda *a, **k: crm.append(1)))
        self.stack.enter_context(mock.patch.object(
            w, "upsert_lead", lambda *a, **k: crm.append(1)))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(crm, [])

    def test_only_the_decision_table_is_written(self):
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual({t for t, _ in self.inserted},
                         {w.bic_decision.TABLE})


# ── 17 · CONSULT failure must never become silent action ────────────────

class ConsultFailure(Base):

    def test_empty_llm_proposal_refuses_rather_than_acting(self):
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply", lambda *a, **k: ""))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        # A deterministic refusal, never an empty or invented message.
        self.assertTrue(self.sent[0][1].strip())
        self.assertFalse(self.producers.expect_customer_reply.called,
                         "no expectation for an action that never went out")

    def test_llm_exception_does_not_send_a_fabricated_reply(self):
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply", side_effect=RuntimeError("provider down")))
        try:
            self.run_pipeline()
        except RuntimeError:
            pass  # propagates to do_POST, which marks the delivery FAILED
        self.assertEqual(self.sent, [])


# ── 37 · webhook dedupe is untouched by this slice ──────────────────────

class DedupeUnchanged(unittest.TestCase):

    def test_slice_does_not_touch_the_dedupe_or_lifecycle_call_sites(self):
        """Structural: the Brain slice lives inside run_client_pipeline, which
        do_POST only reaches AFTER claim/dedupe. Asserted from source so a
        later edit that moved it would fail here."""
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn("is_duplicate_webhook", src)
        self.assertIn("_decision_open", src)
        self.assertIn("finally", src)
        self.assertIn("_decision_flush", src)
        # The Brain entry point must NOT appear in do_POST — it is reached
        # only through run_client_pipeline, downstream of dedupe.
        self.assertNotIn("_bic_decide_and_record", src)

    def test_brain_entry_is_downstream_of_dedupe_in_the_pipeline(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertEqual(src.count("_bic_decide_and_record("), 1)
