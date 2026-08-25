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
from bic import goal_lifecycle as gl                              # noqa: E402
from bic import observe as ob                                     # noqa: E402
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


class Delivery:
    """A successful channel result, shaped like the WhatsApp API response."""
    ok = True
    status_code = 200
    text = "{}"


class Rejected:
    """A channel REJECTION — the shape Meta returns for a bad send. The API
    call completes, so nothing raises; only the status says it failed."""
    ok = False
    status_code = 400
    text = '{"error":{"message":"Unsupported post request"}}'


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
        # A channel result, because that is what the real send_text returns.
        # Returning None here would model a send that told us NOTHING, which
        # stage 12 correctly reads as UNKNOWN rather than success — the mock
        # would be quietly asserting a delivery it never observed.
        p(mock.patch.object(w, "send_text",
                            lambda to, t, **k: (self.sent.append((to, t)),
                                                Delivery())[1]))
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

    # The post-reply lead/workflow block is gated on `len(history) >= 4`
    # (history = ctx history + this turn's 2 messages). The default CTX has
    # ONE entry, so that block is unreachable with it — a fixture that made
    # "no downstream side effects" assertions pass vacuously. Tests about
    # downstream execution must pass long_history=True.
    LONG_HISTORY = [{"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                    {"role": "user", "content": "c"}]

    def run_pipeline(self, text=None, long_history=False):
        ctx = dict(CTX)
        if long_history:
            ctx["history"] = list(self.LONG_HISTORY)
        w.run_client_pipeline(CLIENT, text if text is not None else self.ADMITTING_TEXT,
                              ctx, message_id="wamid.T1")

    def _wire_downstream(self):
        """Capture the post-reply business block. NOTE: an earlier version of
        this fixture left extract_lead_info returning {} from Base, so the
        `if lead:` body never ran and the assertions below passed
        vacuously — the block was in fact firing on every Brain turn."""
        ev = {"extract": 0, "lead": 0, "owner": 0, "workflow": 0, "memory": 0}
        s = self.stack.enter_context

        def bump(key):
            def _f(*a, **k):
                ev[key] += 1
            return _f

        s(mock.patch.object(w, "extract_lead_info",
                            lambda h: (ev.__setitem__("extract", ev["extract"] + 1),
                                       {"name": "X", "service_needed": "social"})[1]))
        s(mock.patch.object(w, "upsert_lead", bump("lead")))
        s(mock.patch.object(w, "maybe_alert_lead", bump("owner")))
        s(mock.patch.object(w, "run_workflows", bump("workflow")))
        s(mock.patch.object(w, "update_memory", bump("memory")))
        s(mock.patch.object(w, "notify_owner", bump("owner")))
        return ev



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

    def test_no_open_turn_withholds_the_response(self):
        """AUDIT REGRESSION (3A I10). 'Cannot record' previously fell through
        the record block and the caller SENT the decision anyway — a Brain
        response with no Decision Record at all."""
        bic_decision.close_turn()
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved, [])
        self.assertEqual(self.inserted, [])


# ── 2 · goal handling / fallback ────────────────────────────────────────

class FallbackToLegacy(Base):

    def test_bic_unavailable_falls_back_to_legacy_reply(self):
        self.stack.enter_context(mock.patch.object(w, "BIC_AVAILABLE", False))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0], (CLIENT, "LLM PROPOSAL TEXT"))


# ── AUDIT REGRESSION · I5 — no unadjudicated reply after admission ──────

class AdmittedGoalNeverFallsBackToRawLlm(Base):
    """3A I5 ("the LLM proposes; the state machine decides") and §6.3 rule 1
    ("a degraded answer that looks normal is worse than a refusal").

    An earlier revision let any post-admission error reach the caller's
    generic handler, which answered with the raw provider output."""

    def test_context_failure_refuses_rather_than_answering(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_context, "assemble", side_effect=RuntimeError("boom")))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])

    def test_decide_failure_refuses_rather_than_answering(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_decide, "decide", side_effect=RuntimeError("decide crashed")))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("LLM PROPOSAL TEXT", self.sent[0][1])

    def test_the_refusal_is_still_recorded_before_it_is_sent(self):
        order = []
        self.stack.enter_context(mock.patch.object(
            w.bic_decide, "decide", side_effect=RuntimeError("decide crashed")))
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", lambda t, r, **k: order.append("insert")))
        self.stack.enter_context(mock.patch.object(
            w, "send_text", lambda to, t, **k: order.append("send")))
        self.run_pipeline()
        self.assertEqual(order, ["insert", "send"])

    def test_failure_after_admission_consults_the_provider_only_once(self):
        """The old fallback re-invoked the provider on the legacy path,
        doubling cost and latency on every Brain-path error."""
        calls = []
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply",
            lambda *a, **k: calls.append(1) or "LLM PROPOSAL TEXT"))
        self.stack.enter_context(mock.patch.object(
            w.bic_decide, "decide", side_effect=RuntimeError("decide crashed")))
        self.run_pipeline()
        self.assertEqual(len(calls), 1)

    def test_provider_failure_degrades_loudly_instead_of_silently(self):
        """§6.3 / T4 'never silence': a provider outage on an admitted goal
        now yields a recorded deterministic refusal, not nothing."""
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply", side_effect=RuntimeError("provider down")))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0][1].strip())
        self.assertEqual(len(self.inserted), 1)

    def test_no_expectation_is_registered_for_a_failed_turn(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_decide, "decide", side_effect=RuntimeError("decide crashed")))
        self.run_pipeline()
        self.assertFalse(self.producers.expect_customer_reply.called)


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

    def test_a_refused_turn_executes_nothing_downstream(self):
        """AUDIT REGRESSION. A REFUSE still ran a SECOND model over the
        transcript, wrote a lead, alerted the owner and fired workflows —
        mining the canned refusal for business facts (§6.3 rule 2) and
        making a refusal look like a qualified lead."""
        ev = self._wire_downstream()
        with self.with_packet(refuse_packet()):
            self.run_pipeline(long_history=True)
        self.assertEqual(len(self.sent), 1, "the refusal itself is still sent")
        self.assertEqual(ev, {"extract": 0, "lead": 0, "owner": 0,
                              "workflow": 0, "memory": 0})

    def test_proceed_keeps_the_existing_downstream_behaviour(self):
        """The fix must be surgical — PROCEED is a genuine conversational
        turn and must not lose lead capture."""
        ev = self._wire_downstream()
        with self.with_packet(proceed_packet()):
            self.run_pipeline(long_history=True)
        self.assertEqual(ev["extract"], 1)
        self.assertEqual(ev["lead"], 1)

    def test_clarify_keeps_the_existing_downstream_behaviour(self):
        ev = self._wire_downstream()
        with self.with_packet(clarify_packet()):
            self.run_pipeline(long_history=True)
        self.assertEqual(ev["extract"], 1)

    def test_no_crm_mirror_or_lead_sync_added_by_the_brain_path(self):
        crm = []
        self.stack.enter_context(mock.patch.object(
            w, "log_reply_to_crm", lambda *a, **k: crm.append(1)))
        self.stack.enter_context(mock.patch.object(
            w, "sync_lead_to_crm", lambda *a, **k: crm.append(1)))
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
        """A provider outage must never produce an invented answer. Since
        the audit fix it degrades LOUDLY (§6.3 rule 1, T4 'never silence'):
        a deterministic refusal, recorded — not the silence it used to be,
        and never model output."""
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply", side_effect=RuntimeError("provider down")))
        self.run_pipeline()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][1], w.bic_decide.REFUSAL_TEXT)
        self.assertEqual(len(self.inserted), 1, "the refusal is recorded")


# ── Phase 10 · the loop's states, made explicit ─────────────────────────

class StateTransitions(Base):
    """One assertion per reachable state of the first Brain loop.

    Deliberately NOT a state-machine framework (3A §2 is not implemented and
    is out of scope here) — these observe the states from OUTSIDE, through
    effects the contract makes observable: whether a decision was recorded,
    whether an expectation was registered, what reached the customer, and
    whether downstream execution ran.
    """

    def observe(self, packet=None, text=None, **patches):
        """Run one turn and report the externally observable state."""
        ev = {"extract": 0}
        self.stack.enter_context(mock.patch.object(
            w, "extract_lead_info",
            lambda h: (ev.__setitem__("extract", ev["extract"] + 1), {})[1]))
        for target, kw in patches.items():
            self.stack.enter_context(mock.patch.object(w, target, **kw))
        ctx = mock.patch.object(w.bic_context, "assemble",
                                lambda *a, **k: packet) if packet else None
        if ctx:
            self.stack.enter_context(ctx)
        self.run_pipeline(text, long_history=True)
        return {
            "sent": [t for _, t in self.sent],
            "recorded": len(self.inserted),
            "expected": self.producers.expect_customer_reply.called,
            "executed_downstream": ev["extract"] > 0,
        }

    # ── success path ────────────────────────────────────────────────
    def test_admitted_context_sufficient_consulted_decided_recorded_responded(self):
        st = self.observe(proceed_packet())
        self.assertEqual(st["sent"], ["LLM PROPOSAL TEXT"])   # RESPONDED
        self.assertEqual(st["recorded"], 1)                    # RECORDED
        self.assertTrue(st["expected"])                        # EXPECTED
        self.assertTrue(st["executed_downstream"])             # EXECUTED

    # ── failure states ──────────────────────────────────────────────
    def test_state_unsupported(self):
        st = self.observe(text="what are your prices?")
        self.assertEqual(st["sent"], ["LLM PROPOSAL TEXT"])  # legacy, unchanged
        self.assertFalse(st["expected"] is False and st["recorded"] > 0,
                         "legacy path must not write a brain decision record")

    def test_state_clarify(self):
        st = self.observe(clarify_packet())
        self.assertIn("service_interest", st["sent"][0])
        self.assertEqual(st["recorded"], 1)
        self.assertFalse(st["expected"], "no action went out to await a reply to")

    def test_state_refused(self):
        st = self.observe(refuse_packet())
        self.assertEqual(st["sent"], [w.bic_decide.REFUSAL_TEXT])
        self.assertEqual(st["recorded"], 1)
        self.assertFalse(st["expected"])
        self.assertFalse(st["executed_downstream"])

    def test_state_unauthorized(self):
        pkt = proceed_packet()
        pkt["goal_ref"] = "a_mismatched_goal"
        st = self.observe(pkt)
        self.assertEqual(st["sent"], [w.bic_decide.REFUSAL_TEXT])
        self.assertEqual(st["recorded"], 1)
        self.assertFalse(st["expected"])

    def test_state_unavailable_context(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_context, "assemble", side_effect=RuntimeError("store down")))
        self.run_pipeline()
        self.assertEqual([t for _, t in self.sent], [w.bic_decide.REFUSAL_TEXT])
        self.assertEqual(len(self.inserted), 1)

    def test_state_record_failed(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", side_effect=DbError("store down")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(self.sent, [])          # nothing responded
        self.assertFalse(self.producers.expect_customer_reply.called)

    def test_state_no_open_record(self):
        bic_decision.close_turn()
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
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


# ── Goal lifecycle through the real pipeline (Steps 9 & 13) ─────────────

class GoalLifecycleIntegration(Base):
    """Proves the lifecycle from OUTSIDE, via the GOAL_STATE trace the
    pipeline emits after the response is actually delivered."""

    def goal_state(self, packet=None, text=None, **patches):
        import io
        import json as _json
        from contextlib import redirect_stdout
        for target, kw in patches.items():
            self.stack.enter_context(mock.patch.object(w, target, **kw))
        if packet is not None:
            self.stack.enter_context(self.with_packet(packet))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.run_pipeline(text)
        lines = [l for l in buf.getvalue().splitlines()
                 if l.startswith("GOAL_STATE ")]
        return _json.loads(lines[0][len("GOAL_STATE "):]) if lines else None

    # ── the three real paths ────────────────────────────────────────
    def test_open_to_completed_on_a_delivered_answer(self):
        st = self.goal_state(proceed_packet())
        self.assertEqual(st["lifecycle"], gl.COMPLETED)
        self.assertIsNone(st["blocker"])

    def test_open_to_blocked_on_missing_evidence(self):
        st = self.goal_state(clarify_packet())
        self.assertEqual(st["lifecycle"], gl.BLOCKED)
        self.assertEqual(st["blocker"], gl.BLOCKED_INSUFFICIENT_EVIDENCE)

    def test_open_to_blocked_when_refused(self):
        st = self.goal_state(refuse_packet())
        self.assertEqual(st["lifecycle"], gl.BLOCKED)

    def test_open_to_blocked_when_not_authorized(self):
        pkt = proceed_packet()
        pkt["goal_ref"] = "a_mismatched_goal"
        st = self.goal_state(pkt)
        self.assertEqual(st["lifecycle"], gl.BLOCKED)
        self.assertEqual(st["blocker"], gl.BLOCKED_NOT_AUTHORIZED)

    def test_infrastructure_failure_blocks_rather_than_completes(self):
        self.stack.enter_context(mock.patch.object(
            w.bic_context, "assemble", side_effect=RuntimeError("down")))
        st = self.goal_state()
        self.assertEqual(st["lifecycle"], gl.BLOCKED)
        self.assertEqual(st["blocker"], gl.BLOCKED_UNAVAILABLE)

    # ── adversarial ─────────────────────────────────────────────────
    def test_unsupported_request_creates_no_goal_at_all(self):
        self.assertIsNone(self.goal_state(text="what are your prices?"))

    def test_customer_saying_done_does_not_complete_a_blocked_goal(self):
        st = self.goal_state(clarify_packet(),
                             text="instagram - done, all sorted")
        self.assertEqual(st["lifecycle"], gl.BLOCKED)

    def test_customer_saying_yes_without_evidence_stays_blocked(self):
        st = self.goal_state(clarify_packet(), text="yes please, instagram")
        self.assertNotEqual(st["lifecycle"], gl.COMPLETED)

    def test_a_model_proposal_claiming_completion_changes_nothing(self):
        self.stack.enter_context(mock.patch.object(
            w, "generate_reply",
            lambda *a, **k: "Your goal is COMPLETED and closed."))
        st = self.goal_state(clarify_packet())
        self.assertEqual(st["lifecycle"], gl.BLOCKED)

    def test_goal_state_trace_carries_no_pii(self):
        import re as _re
        st = self.goal_state(proceed_packet())
        blob = repr(st)
        self.assertNotIn(CLIENT, blob)
        self.assertIsNone(_re.search(r"\b91\d{10}\b", blob))
        self.assertNotIn("wamid", blob)

    def test_record_before_respond_still_holds_with_a_goal(self):
        order = []
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", lambda t, r, **k: order.append("insert")))
        self.stack.enter_context(mock.patch.object(
            w, "send_text", lambda to, t, **k: order.append("send")))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(order, ["insert", "send"])


# ── Stage 12 OBSERVE through the real pipeline ──────────────────────────

class ExecutionObservation(Base):
    """Observes stage 12 from OUTSIDE, via the EXECUTION_OBSERVED trace the
    pipeline emits after it actually executes."""

    def observe_run(self, packet=None, channel=None, text=None):
        import io
        import json as _json
        from contextlib import redirect_stdout
        self.downstream = self._wire_downstream()
        if channel is not None:
            self.stack.enter_context(mock.patch.object(
                w, "send_text",
                lambda to, t, **k: (self.sent.append((to, t)), channel)[1]
                if not isinstance(channel, BaseException) else
                (_ for _ in ()).throw(channel)))
        if packet is not None:
            self.stack.enter_context(self.with_packet(packet))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.run_pipeline(text, long_history=True)
        lines = buf.getvalue().splitlines()

        def grab(prefix):
            hit = [l for l in lines if l.startswith(prefix)]
            return _json.loads(hit[0][len(prefix):]) if hit else None

        return (grab("EXECUTION_OBSERVED "), grab("GOAL_STATE "))

    # ── success / failure ───────────────────────────────────────────
    def test_successful_delivery_is_observed(self):
        obs, goal = self.observe_run(proceed_packet())
        self.assertEqual(obs["state"], ob.SUCCEEDED)
        self.assertEqual(goal["lifecycle"], gl.COMPLETED)

    def test_channel_rejection_is_observed_and_blocks_completion(self):
        """AUDIT REGRESSION: a hardcoded delivery meant HTTP 400 still
        reported the enquiry answered and the goal COMPLETED."""
        obs, goal = self.observe_run(proceed_packet(), channel=Rejected())
        self.assertEqual(obs["state"], ob.FAILED)
        self.assertEqual(obs["failure_class"], "VALUE")
        self.assertNotEqual(goal["lifecycle"], gl.COMPLETED)

    def test_send_exception_is_observed_rather_than_lost(self):
        obs, goal = self.observe_run(proceed_packet(),
                                     channel=TimeoutError("gateway"))
        self.assertEqual(obs["state"], ob.FAILED)
        self.assertEqual(obs["failure_class"], "TIMEOUT")
        self.assertNotEqual(goal["lifecycle"], gl.COMPLETED)

    # ── adversarial: an undelivered turn drives nothing ─────────────
    def test_failed_delivery_runs_no_downstream_business_action(self):
        self.observe_run(proceed_packet(), channel=Rejected())
        self.assertEqual(self.downstream,
                         {"extract": 0, "lead": 0, "owner": 0,
                          "workflow": 0, "memory": 0})

    def test_successful_delivery_keeps_downstream_behaviour(self):
        self.observe_run(proceed_packet())
        self.assertEqual(self.downstream["extract"], 1)

    def test_refusal_runs_no_downstream_business_action(self):
        self.observe_run(refuse_packet())
        self.assertEqual(self.downstream,
                         {"extract": 0, "lead": 0, "owner": 0,
                          "workflow": 0, "memory": 0})

    def test_clarify_does_not_complete_the_goal_even_when_delivered(self):
        obs, goal = self.observe_run(clarify_packet())
        self.assertEqual(obs["state"], ob.SUCCEEDED)
        self.assertEqual(goal["lifecycle"], gl.BLOCKED)

    def test_authorization_denial_does_not_complete_the_goal(self):
        pkt = proceed_packet()
        pkt["goal_ref"] = "a_mismatched_goal"
        obs, goal = self.observe_run(pkt)
        self.assertEqual(goal["lifecycle"], gl.BLOCKED)
        self.assertEqual(goal["blocker"], gl.BLOCKED_NOT_AUTHORIZED)

    # ── traces stay bounded ─────────────────────────────────────────
    def test_observation_trace_carries_no_pii(self):
        import re as _re
        obs, _ = self.observe_run(proceed_packet())
        blob = repr(obs)
        self.assertNotIn(CLIENT, blob)
        self.assertIsNone(_re.search(r"\b91\d{10}\b", blob))
        self.assertNotIn("wamid", blob)

    def test_record_before_respond_survives_the_observation_stage(self):
        order = []
        self.stack.enter_context(mock.patch.object(
            w.bic_db, "insert", lambda t, r, **k: order.append("insert")))
        self.stack.enter_context(mock.patch.object(
            w, "send_text",
            lambda to, t, **k: (order.append("send"), Delivery())[1]))
        with self.with_packet(proceed_packet()):
            self.run_pipeline()
        self.assertEqual(order, ["insert", "send"])
