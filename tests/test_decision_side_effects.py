"""Which downstream actions each Brain verdict is allowed to take.

THE CONTRACT THIS FILE ENFORCES
-------------------------------
IDD-3A §2.2 lists the runtime transitions:

    ASSESSING → CLARIFY-terminal      Missing evidence a human can supply
    ASSESSING → PLANNING              **PROCEED**
    PLANNING  → … → EXECUTING

Only PROCEED reaches PLANNING, and only PLANNING reaches EXECUTING. So a
CLARIFY turn may be RECORDED and RESPONDED to, and may not EXECUTE business
actions. 2H §4.2 says the same thing from the evidence side: CLARIFY means a
required slot is missing, so treating that turn as a qualified lead
contradicts the verdict that produced it.

    PROCEED  → record · alert the owner · run workflows · roll memory
    CLARIFY  → record the customer's own words ONLY (lead upsert + memory);
               NO owner alert, NO workflows
    REFUSE   → nothing downstream at all
    LEGACY   → unchanged; it has no verdict, so it keeps pre-Brain behaviour

WHY CLARIFY STILL WRITES THE LEAD
---------------------------------
upsert_lead and update_memory write down what the CUSTOMER said, not a
conclusion the Brain drew. Suppressing them would lose a real enquiry
whenever someone asks an incomplete question and never answers ours — and
"early drop-offs are exactly the leads we must not lose" is this pipeline's
own stated reason for extracting on short chats. Alerting the owner and
firing meeting/callback/quote workflows are different: those ACT on an
enquiry we just declared insufficient.

NON-VACUOUS BY CONSTRUCTION
---------------------------
extract_lead_info returns a REAL lead here. A fixture returning {} makes
`if lead:` unreachable and every assertion below pass without the code ever
running — a defect this suite has actually shipped before.

Offline: no network, no AI, no database.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                               # noqa: E402
from tests.test_brain_decision_loop import (Base, Delivery,        # noqa: E402
                                            clarify_packet, proceed_packet,
                                            refuse_packet)

A_LEAD = {"name": "Ravi", "service_needed": "social media",
          "city": "Bengaluru", "summary": "wants instagram help"}


class SideEffects(Base):
    """Drives the real pipeline and counts what actually fired."""

    def fire(self, packet=None, *, legacy=False, lead=A_LEAD,
             extract_raises=False, channel=None):
        ev = {"extract": 0, "upsert": 0, "owner_alert": 0, "workflow": 0,
              "memory": 0, "expect_outcome": 0, "history": None}
        # Readable by the caller even if the pipeline raises mid-turn.
        self.attempted_effects = ev
        s = self.stack.enter_context

        def _extract(history):
            ev["extract"] += 1
            ev["history"] = list(history)
            if extract_raises:
                raise RuntimeError("analyst model unavailable")
            return lead

        s(mock.patch.object(w, "extract_lead_info", _extract))
        for name, key in (("upsert_lead", "upsert"),
                          ("maybe_alert_lead", "owner_alert"),
                          ("run_workflows", "workflow"),
                          ("update_memory", "memory")):
            s(mock.patch.object(w, name,
                                (lambda k: lambda *a, **kw:
                                 ev.__setitem__(k, ev[k] + 1))(key)))
        s(mock.patch.object(w.bic_outcome_producers, "expect_customer_reply",
                            lambda *a, **k: ev.__setitem__(
                                "expect_outcome", ev["expect_outcome"] + 1)))
        if channel is not None:
            seq = list(channel)
            self.attempts = []

            def _send(to, t, **k):
                self.attempts.append((to, t))
                item = seq[min(len(self.attempts), len(seq)) - 1]
                if isinstance(item, BaseException):
                    raise item
                return item
            s(mock.patch.object(w, "send_text", _send))
        if legacy:
            s(mock.patch.object(w.bic_decide, "admit_goal", lambda t: None))
        else:
            s(self.with_packet(packet or proceed_packet()))
        with redirect_stdout(io.StringIO()):
            self.run_pipeline(long_history=True)
        return ev


# ── STEP 7 · PROCEED keeps the full approved flow ──────────────────────

class Proceed(SideEffects):

    def test_proceed_runs_the_whole_business_flow(self):
        ev = self.fire(proceed_packet())
        self.assertEqual((ev["extract"], ev["upsert"], ev["owner_alert"],
                          ev["workflow"], ev["memory"]), (1, 1, 1, 1, 1))

    def test_proceed_opens_exactly_one_outcome_window(self):
        self.assertEqual(self.fire(proceed_packet())["expect_outcome"], 1)

    def test_proceed_extractor_never_sees_a_brain_question(self):
        ev = self.fire(proceed_packet())
        self.assertEqual(ev["history"][-1]["content"], "LLM PROPOSAL TEXT")


# ── STEP 6 · REFUSE regression — must stay at zero ─────────────────────

class Refuse(SideEffects):

    def test_refuse_executes_nothing_downstream(self):
        ev = self.fire(refuse_packet())
        self.assertEqual((ev["extract"], ev["upsert"], ev["owner_alert"],
                          ev["workflow"], ev["memory"]), (0, 0, 0, 0, 0))

    def test_refuse_opens_no_outcome_window(self):
        self.assertEqual(self.fire(refuse_packet())["expect_outcome"], 0)

    def test_refuse_never_even_calls_the_analyst_model(self):
        """The guard returns BEFORE extraction, so no second model runs."""
        self.assertIsNone(self.fire(refuse_packet())["history"])


# ── STEPS 3-5 · the CLARIFY boundary ───────────────────────────────────

class Clarify(SideEffects):

    def test_clarify_does_not_alert_the_owner(self):
        """It would present an enquiry we just called evidence-insufficient
        as a qualified lead."""
        self.assertEqual(self.fire(clarify_packet())["owner_alert"], 0)

    def test_clarify_does_not_run_business_workflows(self):
        """meeting / callback / quote must not fire off a turn that asked a
        question because a required slot was missing."""
        self.assertEqual(self.fire(clarify_packet())["workflow"], 0)

    def test_clarify_still_records_what_the_customer_said(self):
        ev = self.fire(clarify_packet())
        self.assertEqual(ev["upsert"], 1)
        self.assertEqual(ev["memory"], 1)

    def test_clarify_opens_no_outcome_window(self):
        """2I registers only on PROCEED — the Brain path carries
        _pending_expectation only for that verdict."""
        self.assertEqual(self.fire(clarify_packet())["expect_outcome"], 0)

    def test_the_extractor_sees_our_own_question_on_a_clarify_turn(self):
        """Pins WHY the owner alert and workflows are suppressed: the last
        assistant turn in the mined transcript is the Brain's question."""
        ev = self.fire(clarify_packet())
        last = ev["history"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertNotEqual(last["content"], "LLM PROPOSAL TEXT")

    def test_a_clarify_lead_is_not_lost(self):
        """The whole reason recording survives: a customer who drops off
        after our question is still captured."""
        self.assertEqual(self.fire(clarify_packet())["upsert"], 1)

    def test_an_analyst_failure_reaches_no_suppressed_action(self):
        """extract_lead_info is UNGUARDED here and propagates — pre-existing
        behaviour, identical in the deployed f209d22, and contained by the
        caller's try/except which marks the webhook event FAILED. Asserted as
        it actually is, not as it would be convenient: the reply has already
        been sent, and none of the suppressed actions ran."""
        ev = {}
        with self.assertRaises(RuntimeError):
            ev = self.fire(clarify_packet(), extract_raises=True)
        # `fire` raised, so read the counters it mutated in place.
        self.assertEqual(self.attempted_effects["owner_alert"], 0)
        self.assertEqual(self.attempted_effects["workflow"], 0)
        self.assertEqual(self.attempted_effects["upsert"], 0)

    def test_clarify_with_no_lead_found_does_nothing(self):
        ev = self.fire(clarify_packet(), lead={})
        self.assertEqual((ev["upsert"], ev["owner_alert"], ev["workflow"]),
                         (0, 0, 0))


# ── STEP 8 · exactly when a 2I expectation is created ──────────────────

class OutcomeExpectationScope(SideEffects):
    """2I's producer declares its scope as 'the AI-generated reply in
    run_client_pipeline's normal-turn branch'. That covers BOTH the Brain and
    legacy replies, and excludes menu echoes, off-topic redirects, brochure
    sends and the new-contact welcome. This table is that contract."""

    def test_brain_proceed_creates_one(self):
        self.assertEqual(self.fire(proceed_packet())["expect_outcome"], 1)

    def test_brain_clarify_creates_none(self):
        self.assertEqual(self.fire(clarify_packet())["expect_outcome"], 0)

    def test_brain_refuse_creates_none(self):
        self.assertEqual(self.fire(refuse_packet())["expect_outcome"], 0)

    def test_a_legacy_turn_creates_one(self):
        """Deliberate and contractual, not accidental: a legacy AI reply is
        an eligible action under the producer's declared scope."""
        self.assertEqual(self.fire(legacy=True)["expect_outcome"], 1)

    def test_no_turn_creates_two(self):
        for label, kw in (("proceed", {"packet": proceed_packet()}),
                          ("clarify", {"packet": clarify_packet()}),
                          ("refuse", {"packet": refuse_packet()}),
                          ("legacy", {"legacy": True})):
            with self.subTest(label=label):
                self.assertLessEqual(self.fire(**kw)["expect_outcome"], 1)

    def test_procedural_turns_create_none(self):
        """The producer excludes procedural branches by design. Only texts
        that genuinely take an early-return branch belong here: an unmatched
        question is NOT off-topic and correctly falls through to a legacy AI
        reply, which IS an eligible action."""
        for text in ("menu", "services", "hi"):
            with self.subTest(text=text):
                ev = {"n": 0}
                with mock.patch.object(w.bic_outcome_producers,
                                       "expect_customer_reply",
                                       lambda *a, **k: ev.__setitem__("n", 1)), \
                     redirect_stdout(io.StringIO()):
                    self.run_pipeline(text=text, long_history=True)
                self.assertEqual(ev["n"], 0)


# ── STEP 9 · adversarial ───────────────────────────────────────────────

class Adversarial(SideEffects):

    def test_legacy_behaviour_is_completely_unchanged(self):
        ev = self.fire(legacy=True)
        self.assertEqual((ev["extract"], ev["upsert"], ev["owner_alert"],
                          ev["workflow"], ev["memory"]), (1, 1, 1, 1, 1))

    def test_a_brain_exception_falls_back_to_legacy_not_to_clarify_rules(self):
        """A crash inside the Brain must not silently apply the CLARIFY
        suppression to a legacy turn."""
        with mock.patch.object(w, "_bic_decide_and_record",
                               side_effect=RuntimeError("boom")):
            ev = self.fire(legacy=False)
        self.assertEqual((ev["owner_alert"], ev["workflow"]), (1, 1))

    def test_provider_retry_still_ends_in_one_set_of_effects(self):
        """A 429 then success is ONE delivered turn, not two."""
        from tests.test_brain_decision_loop import Resp
        ev = self.fire(proceed_packet(), channel=[Resp(False, 429), Delivery()])
        self.assertEqual(len(self.attempts), 2)
        self.assertEqual((ev["upsert"], ev["owner_alert"], ev["workflow"]),
                         (1, 1, 1))
        self.assertEqual(ev["expect_outcome"], 1)

    def test_an_undelivered_turn_executes_nothing_downstream(self):
        """Nothing reached the customer, so there is no conversation to mine."""
        ev = self.fire(proceed_packet(), channel=[TimeoutError("gw")])
        self.assertEqual((ev["extract"], ev["upsert"], ev["owner_alert"],
                          ev["workflow"], ev["memory"]), (0, 0, 0, 0, 0))
        self.assertEqual(ev["expect_outcome"], 0)

    def test_clarify_cannot_reach_workflows_by_any_lead_shape(self):
        for shape in ({"name": "X"}, {"service_needed": "ads"},
                      dict(A_LEAD, budget="5L"), {"summary": "meeting please"}):
            with self.subTest(shape=shape):
                self.assertEqual(
                    self.fire(clarify_packet(), lead=shape)["workflow"], 0)

    def test_no_verdict_bypasses_decide(self):
        """Every Brain turn's verdict comes from decide(); the downstream
        gate reads that verdict and nothing else."""
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("_clarifying = (decide_result is not None", src)
        self.assertIn("decide_result[\"outcome\"] == bic_decide.CLARIFY", src)
