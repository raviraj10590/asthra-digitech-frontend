"""Business Reasoning Core v1 — reasoning across evidence, not retrieving one.

WHAT THIS SLICE IS
------------------
`business_status` answers "what is the number?". This answers "what is going
on, why might it be, what matters, what next" — in stages, with every object
carrying the epistemic weight it actually has:

    evidence -> situation -> patterns -> diagnosis -> priorities
             -> recommendations -> rationale

THE BOUNDARY THE WHOLE SUITE DEFENDS
------------------------------------
An observation is not a diagnosis, and a diagnosis is not a cause.
"Enquiries are 14"            FACT
"Enquiries fell from 20"      DERIVED — needs a second comparable reading
"Marketing is underperforming" needs marketing evidence, which does not exist
"The ads caused it"            needs causal evidence, which nothing produces

Most tests here exist to prove the engine REFUSES to climb that ladder
without the evidence each rung requires.

DETERMINISTIC. bic.reasoning calls no model and performs no I/O. The tests
therefore need no fakes for the reasoning itself — only for the packet.

Offline: no network, no provider, no database.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402
from bic import context as cx, decide as dcd, goals as gl      # noqa: E402
from bic import reasoning as r                                 # noqa: E402

BIZ = "biz.pipeline.new_enquiries_per_month@1"
OTHER = "biz.pipeline.open_value@1"
TENANT = "00000000-0000-0000-0000-000000000001"
ORG = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"


def executable_only(fn):
    """Function source with comments and STRINGS (incl. docstrings) removed.

    Needed because these functions' own prose names the things they must not
    touch, in order to explain that they do not touch them. Scanning raw
    source would match the explanation.
    """
    import inspect, tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(fn)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def fact(value="14", predicate=BIZ, label="New enquiries per month",
         conf=0.70, verdict="FRESH", claim_id="claim-aaa", tier=3, unit="count"):
    return {"predicate": predicate, "label": label, "value": value,
            "unit": unit, "confidence": conf,
            "provenance": {"tier": tier, "cap": 0.70},
            "valid_from": "2026-09-01T00:00:00+00:00",
            "observed_at": "2026-09-05T04:00:00+00:00",
            "freshness": {"verdict": verdict}, "claim_id": claim_id}


def gap(slot="conversion_rate", predicate="biz.pipeline.conversion_rate@1",
        cls=cx.UNKNOWABLE):
    return {"slot": slot, "predicate": predicate, "class": cls, "why": "x"}


def packet(facts=(), gaps=(), conflicts=(), verdict=cx.PROCEED,
           scope=cx.BUSINESS, tenant=TENANT):
    return {
        "packet_id": "p1", "tenant_id": tenant, "subject": ORG, "scope": scope,
        "goal_ref": "business_month_review", "assembly_state": "OK",
        "question": {"request": "q", "risk_tier": 2},
        "principal": {"principal_ref": "prn", "role": "OWNER",
                      "risk_tier_ceiling": 4},
        "evidence": {"facts": list(facts), "relationships": [], "timeline": [],
                     "organizational_intelligence": {}},
        "boundaries": {},
        "epistemic": {"conflicts": list(conflicts), "missing": [],
                      "coverage": {"planned": [BIZ], "retrieved": [],
                                   "absent": [], "unavailable": [],
                                   "unregistered": [], "out_of_scope": []},
                      "degradation": [],
                      "sufficiency": {"verdict": verdict, "reason": "r",
                                      "risk_tier": 2, "gaps": list(gaps)}},
    }


def prior(value="20", claim_id="claim-old", ns="biz.pipeline",
          concept="new_enquiries_per_month", version=1):
    return {"claim_id": claim_id, "value": value, "predicate_ns": ns,
            "predicate_concept": concept, "semantic_version": version}


# ══════════════════════════════════════════════════════════════════════════
# A-F · evidence composition and the epistemic model
# ══════════════════════════════════════════════════════════════════════════

class EvidenceComposition(unittest.TestCase):

    def test_A_single_fact_is_observed_as_a_fact(self):
        out = r.reason(packet([fact()]))
        obs = out["situation"]["observations"]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["epistemic"], r.FACT)
        self.assertEqual(obs[0]["value"], "14")

    def test_B_multiple_compatible_facts_are_all_composed(self):
        """Generic, not a hardcoded new_enquiries pathway."""
        out = r.reason(packet([fact(), fact(predicate=OTHER, label="Open value",
                                            value="5", claim_id="claim-bbb")]))
        self.assertEqual(len(out["situation"]["observations"]), 2)
        self.assertEqual({o["predicate"] for o in out["situation"]["observations"]},
                         {BIZ, OTHER})

    def test_C_conflicting_facts_become_CONTRADICTED_not_a_value(self):
        out = r.reason(packet([fact()], conflicts=[
            {"predicate": BIZ, "competing_values": ["14", "19"]}]))
        c = out["situation"]["contradictions"]
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["epistemic"], r.CONTRADICTED)
        self.assertIn("no value has been selected", c[0]["note"])

    def test_D_missing_evidence_is_carried_as_UNKNOWN(self):
        out = r.reason(packet([fact()], gaps=[gap()]))
        u = out["situation"]["unknowns"]
        self.assertEqual(len(u), 1)
        self.assertEqual(u[0]["epistemic"], r.UNKNOWN)

    def test_E_unregistered_metric_is_unknown_and_not_measurable(self):
        out = r.reason(packet([fact()], gaps=[gap(cls=cx.UNKNOWABLE)]))
        u = out["situation"]["unknowns"][0]
        self.assertFalse(u["measurable"])
        self.assertIn("nothing records it yet", u["why"])

    def test_E2_registered_but_unavailable_is_unknown_but_measurable(self):
        out = r.reason(packet([fact()],
                              gaps=[gap(cls=cx.OBTAINABLE_BY_RETRIEVAL)]))
        u = out["situation"]["unknowns"][0]
        self.assertTrue(u["measurable"])
        self.assertIn("not currently available", u["why"])

    def test_F_stale_evidence_is_still_a_fact_but_never_trends(self):
        """A stale reading was true when observed; comparing it to a current
        one measures the clock as much as the business."""
        out = r.reason(packet([fact(verdict="STALE")]),
                       history={BIZ: [prior()]})
        self.assertEqual(out["situation"]["observations"][0]["epistemic"], r.FACT)
        self.assertEqual(out["situation"]["changes"], [])

    def test_confidence_is_the_weakest_leg_not_the_average(self):
        out = r.reason(packet([fact(conf=0.9), fact(conf=0.5, predicate=OTHER,
                                                    claim_id="claim-bbb")]))
        self.assertEqual(out["situation"]["confidence"], 0.5)

    def test_confidence_is_none_not_zero_when_nothing_is_known(self):
        """0.0 would read as 'we are certain it is nothing'."""
        self.assertIsNone(r.reason(packet([]))["situation"]["confidence"])


# ══════════════════════════════════════════════════════════════════════════
# G-H · trends: the single-point rule
# ══════════════════════════════════════════════════════════════════════════

class TrendRules(unittest.TestCase):

    def test_G_a_single_point_is_never_a_trend(self):
        """THE CORE RULE. One measurement is a FACT; a line through one point
        is a decision about what you wanted to see."""
        out = r.reason(packet([fact()]))            # no history at all
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["situation"]["stable_signals"], [])

    def test_H_two_comparable_observations_make_a_derived_trend(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        t = out["situation"]["changes"][0]
        self.assertEqual(t["pattern"], r.DECREASE)
        self.assertEqual(t["epistemic"], r.DERIVED)
        self.assertEqual((t["from_value"], t["to_value"]), ("20", "14"))

    def test_an_increase_is_detected(self):
        out = r.reason(packet([fact("30")]), history={BIZ: [prior("20")]})
        self.assertEqual(out["situation"]["changes"][0]["pattern"], r.INCREASE)

    def test_a_small_move_is_flat_not_a_change(self):
        out = r.reason(packet([fact("20.5")]), history={BIZ: [prior("20")]})
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["situation"]["stable_signals"][0]["pattern"], r.FLAT)

    def test_a_trend_never_carries_a_cause(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        self.assertIsNone(out["situation"]["changes"][0]["cause"])

    def test_a_semantic_version_change_is_not_comparable(self):
        """Comparing across a redefinition trends the DEFINITION and reports
        it as a business movement."""
        out = r.reason(packet([fact("14")]),
                       history={BIZ: [prior("20", version=2)]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_a_different_predicate_is_not_comparable(self):
        out = r.reason(packet([fact("14")]),
                       history={BIZ: [prior("20", concept="something_else")]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_non_numeric_values_do_not_trend(self):
        out = r.reason(packet([fact("many")]), history={BIZ: [prior("20")]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_the_current_claim_is_not_compared_with_itself(self):
        out = r.reason(packet([fact("14", claim_id="same")]),
                       history={BIZ: [prior("14", claim_id="same")]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_min_trend_observations_is_two(self):
        self.assertEqual(r.MIN_TREND_OBSERVATIONS, 2)


# ══════════════════════════════════════════════════════════════════════════
# I-L · diagnosis
# ══════════════════════════════════════════════════════════════════════════

class DiagnosisRules(unittest.TestCase):

    def test_I_a_fact_is_not_a_diagnosis(self):
        """A single fact produces observations and NO diagnosis — there is
        nothing yet to explain."""
        out = r.reason(packet([fact()]))
        self.assertEqual(out["diagnoses"], [])
        self.assertTrue(out["situation"]["observations"])

    def test_J_a_movement_does_not_become_a_cause(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        d = out["diagnoses"][0]
        self.assertEqual(d["state"], r.UNRESOLVED)
        self.assertIn("cause is not", d["why_unresolved"])

    def test_J2_divergence_is_correlation_never_causation(self):
        out = r.reason(packet([fact("14"), fact("30", predicate=OTHER,
                                                label="Open value",
                                                claim_id="claim-bbb")]),
                       history={BIZ: [prior("20")],
                                OTHER: [prior("10", concept="open_value")]})
        div = [a for a in out["situation"]["anomalies"]
               if a["pattern"] == r.DIVERGENCE]
        self.assertTrue(div)
        self.assertEqual(div[0]["epistemic"], r.CORRELATION)
        self.assertIsNone(div[0]["cause"])
        self.assertIn("no causal link", div[0]["note"])

    def test_K_an_unproven_explanation_is_labelled_HYPOTHESIS(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        self.assertEqual(out["diagnoses"][0]["epistemic"], r.HYPOTHESIS)

    def test_L_no_diagnosis_is_ever_SUPPORTED_without_explanatory_evidence(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        self.assertNotIn(r.SUPPORTED, [d["state"] for d in out["diagnoses"]])

    def test_a_diagnosis_names_what_would_resolve_it(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        d = out["diagnoses"][0]
        self.assertIn("biz.pipeline.conversion_rate@1", d["missing_evidence"])

    def test_a_diagnosis_carries_supporting_evidence_refs(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        self.assertIn("claim-aaa", out["diagnoses"][0]["supporting_evidence"])

    def test_a_contradiction_produces_its_own_unresolved_diagnosis(self):
        out = r.reason(packet([fact()], conflicts=[
            {"predicate": BIZ, "competing_values": ["14", "19"]}]))
        d = [x for x in out["diagnoses"] if x["epistemic"] == r.CONTRADICTED]
        self.assertTrue(d)
        self.assertEqual(d[0]["state"], r.UNRESOLVED)


# ══════════════════════════════════════════════════════════════════════════
# M-N · prioritisation
# ══════════════════════════════════════════════════════════════════════════

class PriorityRules(unittest.TestCase):

    def test_M_priorities_are_evidence_backed(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        self.assertTrue(out["priorities"])
        for p in out["priorities"]:
            self.assertIn(p["epistemic"], r.EPISTEMIC)
            self.assertTrue(p["reason"])

    def test_N_an_unmeasurable_metric_outranks_a_small_movement(self):
        """You cannot manage what you have not defined."""
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        self.assertEqual(out["priorities"][0]["kind"], r.MEASURE)

    def test_priorities_carry_uncertainty(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]))
        for p in out["priorities"]:
            self.assertIn(p["uncertainty"], ("high", "medium", "low"))

    def test_no_priority_invents_money_or_impact(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        blob = str(out["priorities"]).lower()
        for banned in ("₹", "revenue", "rupee", "profit", "roi", "worth"):
            self.assertNotIn(banned, blob, banned)

    def test_a_contradiction_is_a_high_priority(self):
        out = r.reason(packet([fact()], conflicts=[
            {"predicate": BIZ, "competing_values": ["14", "19"]}]))
        self.assertTrue([p for p in out["priorities"]
                         if p["epistemic"] == r.CONTRADICTED])


# ══════════════════════════════════════════════════════════════════════════
# O-V · recommendations, and the fabrication ban
# ══════════════════════════════════════════════════════════════════════════

class RecommendationRules(unittest.TestCase):

    def test_O_recommendations_derive_from_priorities_not_raw_evidence(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        kinds = {x["kind"] for x in out["recommendations"]}
        self.assertTrue(kinds <= set(r.RECOMMENDATION_KINDS))
        for rec in out["recommendations"]:
            self.assertTrue(rec["reason"])
            self.assertTrue(rec["expected_objective"])
            self.assertTrue(rec["would_change_if"])

    def test_P_an_ACT_recommendation_requires_a_supported_diagnosis(self):
        """No SUPPORTED diagnosis is reachable from current evidence, so no
        ACT recommendation may be produced."""
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        self.assertEqual([x for x in out["recommendations"]
                          if x["kind"] == r.ACT], [])

    def test_P2_an_act_priority_is_dropped_without_a_supported_diagnosis(self):
        acted = r.recommend(
            [{"priority": "Increase ad budget", "kind": r.ACT, "score": 0.9,
              "epistemic": r.FACT, "reason": "x", "evidence_refs": [],
              "uncertainty": "low", "about": "ads"}], [])
        self.assertEqual(acted, [])

    def test_Q_a_measurement_recommendation_is_allowed_and_preferred(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]))
        m = [x for x in out["recommendations"] if x["kind"] == r.MEASURE]
        self.assertTrue(m)
        self.assertIn("measurable", m[0]["expected_objective"])

    def test_recommendations_are_advisory_and_require_no_action(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]))
        for rec in out["recommendations"]:
            self.assertTrue(rec["advisory"])
            self.assertFalse(rec["action_required"])
        self.assertTrue(out["advisory"])
        self.assertFalse(out["action_required"])

    def test_R_to_V_no_fabricated_metric_appears_anywhere(self):
        """Conversion, pipeline value, capacity, attribution, revenue —
        nameable as UNKNOWN, never assertable as measured."""
        out = r.reason(packet([fact("14")], gaps=[
            gap("conversion_rate", "biz.pipeline.conversion_rate@1"),
            gap("pipeline_value", "biz.pipeline.open_value@1"),
            gap("capacity", "biz.capacity.available@1"),
            gap("attribution", "biz.channel.attribution@1")]),
            history={BIZ: [prior("20")]})
        import re
        blob = str(out["recommendations"]) + str(out["diagnoses"])
        # Predicate REFS legitimately end in "@<semantic version>"; that digit
        # is a schema version, not a business quantity. Strip refs first so the
        # scan tests for fabrication rather than for the naming convention.
        blob = re.sub(r"[a-z_.]+@\d+", "<ref>", blob)
        for name in ("conversion", "capacit", "attribut", "revenue", "value"):
            for m in re.finditer(name, blob, re.I):
                tail = blob[m.end():m.end() + 40]
                self.assertNotRegex(tail, r"^[^a-zA-Z]{0,6}\d",
                                    f"{name} appears with a number")

    def test_the_rationale_explains_rather_than_repeats(self):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        rat = out["rationale"]
        self.assertIn("limiting_factor", rat)
        self.assertTrue(rat["no_action_authorised"])
        self.assertNotIn(out["recommendations"][0]["recommendation"],
                         rat["limiting_factor"])


# ══════════════════════════════════════════════════════════════════════════
# W-Y · scope, refs, tenancy
# ══════════════════════════════════════════════════════════════════════════

class ScopeAndProvenance(unittest.TestCase):

    def test_W_evidence_refs_are_preserved_through_the_chain(self):
        out = r.reason(packet([fact("14")]), history={BIZ: [prior("20")]})
        self.assertEqual(out["situation"]["observations"][0]["evidence_ref"],
                         "claim-aaa")
        self.assertIn("claim-aaa", out["situation"]["changes"][0]["evidence_refs"])

    def test_X_a_party_scoped_packet_is_refused(self):
        """Reasoning about a customer's context as though it were the business
        is the one confusion 2H's scope field exists to prevent."""
        with self.assertRaises(r.ReasoningError):
            r.reason(packet([fact()], scope=cx.PARTY))

    def test_X2_business_scope_is_required_explicitly(self):
        with self.assertRaises(r.ReasoningError):
            r.reason(packet([fact()], scope=None))

    def test_Y_the_engine_reasons_only_over_the_packet_it_is_given(self):
        """Tenant isolation is structural: reason() has no store access, so it
        cannot reach another tenant's evidence even in principle."""
        import inspect
        src = inspect.getsource(r)
        for banned in ("select(", "insert(", "requests.", "http", "db."):
            self.assertNotIn(banned, src, banned)


# ══════════════════════════════════════════════════════════════════════════
# Z-AB · what the model may see
# ══════════════════════════════════════════════════════════════════════════

class ConsultBriefIsPacketOnly(unittest.TestCase):

    def brief(self, **kw):
        out = r.reason(packet([fact("14")], gaps=[gap()]),
                       history={BIZ: [prior("20")]})
        return str(w._reasoning_brief(out, "why?"))

    def test_Z_no_pii_reaches_the_model(self):
        blob = self.brief()
        for secret in ("claim-aaa", "claim-old", ORG, TENANT, "919"):
            self.assertNotIn(secret, blob, secret)

    def test_AA_and_AB_no_owner_memory_archive_or_crm_snapshot(self):
        import inspect
        params = list(inspect.signature(w._reasoning_brief).parameters)
        self.assertEqual(params, ["result", "question"])
        # CODE ONLY. The docstring says "no CRM or leads snapshot", so a raw
        # source scan would match the explanation instead of an actual leak —
        # the self-referential trap this codebase has hit before.
        src = executable_only(w._reasoning_brief)
        for banned in ("fetch_owner_memory", "recall_from_archive",
                       "owner_business_snapshot", "whatsapp_messages",
                       "leads", "clients"):
            self.assertNotIn(banned, src, banned)

    def test_the_brief_forbids_asserting_a_cause(self):
        blob = self.brief()
        self.assertIn("CAUSE NOT ESTABLISHED", blob)
        self.assertIn("Do not assert a CAUSE", blob)

    def test_the_brief_forbids_the_unmeasured_metrics_by_name(self):
        blob = self.brief().lower()
        for banned in ("revenue", "conversion", "pipeline value", "capacity",
                       "attribution"):
            self.assertIn(banned, blob)
        self.assertIn("do not recommend spending changes", blob)

    def test_the_brief_states_that_one_reading_is_not_a_trend(self):
        out = r.reason(packet([fact("14")]))
        self.assertIn("not a trend", str(w._reasoning_brief(out, "q")))


# ══════════════════════════════════════════════════════════════════════════
# AC-AJ · everything that must not have changed
# ══════════════════════════════════════════════════════════════════════════

class ExistingBehaviourUnchanged(unittest.TestCase):

    def test_AC_business_status_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.tool_business_status)
        self.assertIn("BUSINESS_STATUS_GOAL", src)
        self.assertNotIn("bic_reasoning", src)
        self.assertEqual(w.BUSINESS_STATUS_GOAL, "business_month_review")

    def test_AD_focus_recommendation_still_requires_its_five_slots(self):
        """NOT activated and NOT weakened (§17)."""
        g = gl.lookup("business_focus_recommendation")
        self.assertEqual(len(g["required_slots"]), 5)
        self.assertEqual(g["scope"], cx.BUSINESS)

    def test_AD2_the_reasoning_tool_never_reaches_that_goal(self):
        import inspect
        self.assertNotIn("business_focus_recommendation",
                         inspect.getsource(w.tool_business_reasoning))
        self.assertEqual(w.REASONING_GOAL, "business_month_review")

    def test_AE_the_client_path_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      src)
        self.assertNotIn("bic_reasoning", src)

    def test_AF_existing_owner_direct_tools_are_unchanged(self):
        for text, gate in (("How many enquiries this month?",
                            w.owner_evidence_query),
                           ("What is the business status this month?",
                            w.owner_business_status_query)):
            self.assertTrue(gate(text))
            self.assertFalse(w.owner_reasoning_query(text), text)

    def test_AG_no_authorize_is_called(self):
        import inspect
        self.assertNotIn("authorize",
                         inspect.getsource(w.tool_business_reasoning))

    def test_AH_no_execute_no_commitment_no_mutation(self):
        import inspect
        src = inspect.getsource(w.tool_business_reasoning)
        for banned in ("commitment", "insert(", "assert_claim", "send_text",
                       "upsert_lead", "requests.post"):
            self.assertNotIn(banned, src, banned)

    def _drive(self, narration):
        """Drive the REAL tool_business_reasoning with an injected narrator."""
        pk = packet([fact("14")], gaps=[gap()])
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", TENANT), \
             mock.patch.object(w, "assemble_business_context",
                               lambda *a, **k: (pk, None)), \
             mock.patch.object(w.bic_claims, "history",
                               lambda *a, **k: [prior("20")]), \
             redirect_stdout(io.StringIO()):
            return w.tool_business_reasoning(
                "910000000001", question="why?",
                narrator=lambda res, q: narration)

    def test_AI_narration_validation_is_still_enforced(self):
        """BEHAVIOURAL, not a source grep. A grep passes even when the call is
        deleted and replaced with `rejected = None` — which a mutation proved,
        so this drives the real path instead."""
        out = self._drive("Revenue reached 250000 this month.")
        self.assertIn("Narration refused", out)
        self.assertNotIn("250000", out)

    def test_AI2_a_valid_narration_is_included(self):
        out = self._drive("Enquiries are 14 this month.")
        self.assertIn("Enquiries are 14", out)
        self.assertNotIn("Narration refused", out)

    def test_AI3_a_narrator_failure_degrades_to_the_deterministic_output(self):
        pk = packet([fact("14")], gaps=[gap()])

        def boom(res, q):
            raise RuntimeError("provider down")
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", TENANT), \
             mock.patch.object(w, "assemble_business_context",
                               lambda *a, **k: (pk, None)), \
             mock.patch.object(w.bic_claims, "history", lambda *a, **k: []), \
             redirect_stdout(io.StringIO()):
            out = w.tool_business_reasoning("910000000001", question="why?",
                                            narrator=boom)
        self.assertIn("14", out)
        self.assertIn("Advisory only", out)

    def test_AI4_the_reply_never_exposes_internal_ids(self):
        out = self._drive("Enquiries are 14 this month.")
        for secret in ("claim-aaa", "claim-old", ORG, TENANT):
            self.assertNotIn(secret, out, secret)

    def test_AI5_the_reply_states_no_action_was_authorised(self):
        self.assertIn("No action has been taken or authorised",
                      self._drive(None))

    def test_AJ_decide_is_reused_and_no_second_engine_exists(self):
        import inspect
        self.assertIn("bic_decide.decide",
                      inspect.getsource(w.tool_business_reasoning))
        src = inspect.getsource(r)
        for banned in ("def decide", "def authorize", "OUTCOMES"):
            self.assertNotIn(banned, src, banned)

    def test_the_reasoning_core_calls_no_model(self):
        import inspect
        src = inspect.getsource(r)
        for banned in ("openai", "gemini", "deepseek", "chat.completions",
                       "_call_openai", "generate_reply"):
            self.assertNotIn(banned, src.lower(), banned)


# ══════════════════════════════════════════════════════════════════════════
# routing + the registry row
# ══════════════════════════════════════════════════════════════════════════

class Routing(unittest.TestCase):

    def test_the_four_owner_questions_route_to_reasoning(self):
        for t in ("What is happening in my business?",
                  "Why are my enquiries low?",
                  "What should I focus on this month?",
                  "What should I do next?"):
            self.assertTrue(w.owner_reasoning_query(t), t)

    def test_the_gates_remain_mutually_exclusive(self):
        cases = {
            "What is the business status this month?": ("status",),
            "How many enquiries this month?": ("count",),
            "Why are my enquiries low?": ("reason",),
            "What is happening in my business?": ("reason",),
            "Show my clients": ("lookup",),
            "Why is my phone slow?": (),
        }
        for text, expected in cases.items():
            got = []
            if w.owner_reasoning_query(text):
                got.append("reason")
            if w.owner_business_status_query(text):
                got.append("status")
            if w.owner_evidence_query(text):
                got.append("count")
            if w.owner_lookup_tool(text):
                got.append("lookup")
            self.assertEqual(tuple(got), expected, text)

    def test_no_second_classifier_was_introduced(self):
        import inspect
        src = inspect.getsource(w.owner_reasoning_query)
        for banned in ("openai", "gemini", "chat.completions", "generate_reply"):
            self.assertNotIn(banned, src)
        self.assertIn("_REASONING_MARKERS", src)

    def test_the_tool_is_owner_only_and_not_customer_safe(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260905000024_bic_business_reasoning_tool.sql")
        with open(path) as fh:
            sql = fh.read()
        self.assertIn("'business_reasoning'", sql)
        self.assertRegex(sql, r"'OWNER',\s*1,\s*false,\s*false")
        code = "\n".join(l for l in sql.splitlines()
                         if not l.strip().startswith("--"))
        for banned in ("create table", "alter table", "drop "):
            self.assertNotIn(banned, code.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
