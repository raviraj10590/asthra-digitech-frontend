"""Brain Operating Loop v1 — the full reasoning pass, stage by stage.

WHAT THIS SLICE ADDS OVER REASONING CORE v1
-------------------------------------------
v1 produced situation → diagnosis → priority → recommendation. This adds the
stages that make the loop usable for an actual decision:

    temporal shape   POINT_IN_TIME / MOVEMENT / PERSISTENCE / RECURRENCE
    hypotheses       candidate explanations, permanently labelled as such
    decision plan    the question, the option, and what would reverse it
    counterfactual   what evidence would change each conclusion
    evidence quality provenance x freshness x confidence, deterministic
    contradiction    lowers confidence numerically, not just in prose

THE BOUNDARY EVERY TEST HERE DEFENDS
------------------------------------
One reading is a fact and never a direction. A movement is arithmetic and
never a cause. A hypothesis is a candidate and never a finding. An ACT
recommendation requires a SUPPORTED diagnosis, and on this evidence base none
is reachable — so the honest output is measurement and investigation.

Deterministic: bic.reasoning performs no I/O and calls no model, so these
tests need no provider fakes at all.

Offline: no network, no provider, no database.
"""

import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402
from bic import context as cx, goals as gl                     # noqa: E402
from bic import reasoning as r                                 # noqa: E402

BIZ = gl.NEW_ENQUIRIES
CONV = gl.CONVERSION_RATE
PIPE = gl.PIPELINE_VALUE
ATTR = gl.CHANNEL_ATTRIBUTION
CAP = gl.CAPACITY
TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
ORG = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"


def executable_only(fn):
    """Source with comments and STRINGS removed — these functions' own prose
    names what they must not touch, so a raw scan matches the explanation."""
    import inspect, tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(fn)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def fact(value="16", predicate=BIZ, label="New enquiries per month",
         conf=0.70, verdict="FRESH", claim_id="claim-now", tier=3,
         unit="count"):
    return {"predicate": predicate, "label": label, "value": value,
            "unit": unit, "confidence": conf,
            "provenance": {"tier": tier, "cap": 0.70},
            "valid_from": "2026-09-01T00:00:00+00:00",
            "observed_at": "2026-09-05T04:00:00+00:00",
            "freshness": {"verdict": verdict}, "claim_id": claim_id}


def gap(slot="conversion_rate", predicate=CONV, cls=cx.UNKNOWABLE):
    return {"slot": slot, "predicate": predicate, "class": cls, "why": "x"}


ALL_GAPS = [gap("conversion_rate", CONV), gap("pipeline_value", PIPE),
            gap("attribution", ATTR), gap("capacity", CAP)]


def packet(facts=(), gaps=(), conflicts=(), scope=cx.BUSINESS, tenant=TENANT):
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
                      "sufficiency": {"verdict": cx.PROCEED, "reason": "r",
                                      "risk_tier": 2, "gaps": list(gaps)}},
    }


def prior(value, claim_id, ns="biz.pipeline",
          concept="new_enquiries_per_month", version=1, unit=None):
    row = {"claim_id": claim_id, "value": value, "predicate_ns": ns,
           "predicate_concept": concept, "semantic_version": version}
    if unit is not None:
        row["unit"] = unit
    return row


# ══════════════════════════════════════════════════════════════════════════
# 1-6 · TEMPORAL REASONING
# ══════════════════════════════════════════════════════════════════════════

class TemporalReasoning(unittest.TestCase):

    def test_1_one_fact_is_point_in_time_only(self):
        out = r.reason(packet([fact()]))
        obs = out["evidence"][0]
        self.assertEqual(obs["temporal"], r.POINT_IN_TIME)
        self.assertEqual(obs["situation_class"], r.OBSERVED)
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["situation"]["stable_signals"], [],
                         "one reading must not be reported as stable")

    def test_2_two_comparable_points_make_a_movement(self):
        out = r.reason(packet([fact("16")]),
                       history={BIZ: [prior("14", "c1")]})
        t = out["situation"]["changes"][0]
        self.assertEqual(t["temporal"], r.MOVEMENT)
        self.assertEqual(t["pattern"], r.INCREASE)
        self.assertEqual(t["epistemic"], r.DERIVED)

    def test_3_three_monotonic_points_are_persistence(self):
        out = r.reason(packet([fact("16")]),
                       history={BIZ: [prior("14", "c1"), prior("9", "c2")]})
        self.assertEqual(out["situation"]["changes"][0]["temporal"],
                         r.PERSISTENCE)
        self.assertTrue(out["situation"]["recurrences"])

    def test_3b_three_alternating_points_are_recurrence(self):
        out = r.reason(packet([fact("16")]),
                       history={BIZ: [prior("14", "c1"), prior("20", "c2")]})
        self.assertEqual(out["situation"]["changes"][0]["temporal"],
                         r.RECURRENCE_T)

    def test_4_a_stale_reading_never_forms_a_trend(self):
        out = r.reason(packet([fact(verdict="STALE")]),
                       history={BIZ: [prior("14", "c1")]})
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["evidence"][0]["epistemic"], r.FACT)

    def test_5_a_semantic_version_change_breaks_the_trend(self):
        out = r.reason(packet([fact("16")]),
                       history={BIZ: [prior("14", "c1", version=2)]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_6_incompatible_units_cannot_be_compared(self):
        out = r.reason(packet([fact("16", unit="count")]),
                       history={BIZ: [prior("14", "c1", unit="percent")]})
        self.assertEqual(out["situation"]["changes"], [],
                         "a count must not be compared with a percentage")

    def test_matching_units_still_compare(self):
        out = r.reason(packet([fact("16", unit="count")]),
                       history={BIZ: [prior("14", "c1", unit="count")]})
        self.assertTrue(out["situation"]["changes"])

    def test_a_movement_never_carries_a_cause(self):
        out = r.reason(packet([fact("16")]),
                       history={BIZ: [prior("14", "c1")]})
        for p in out["patterns"]:
            self.assertIsNone(p.get("cause"), p.get("pattern"))


# ══════════════════════════════════════════════════════════════════════════
# 7-8 · CONTRADICTION
# ══════════════════════════════════════════════════════════════════════════

class Contradiction(unittest.TestCase):

    CONFLICT = [{"predicate": BIZ, "competing_values": ["16", "22"]}]

    def test_7_a_contradiction_is_detected_and_unresolved(self):
        out = r.reason(packet([fact()], conflicts=self.CONFLICT))
        c = out["contradictions"][0]
        self.assertEqual(c["epistemic"], r.CONTRADICTED)
        self.assertEqual(c["situation_class"], r.CONTRADICTED)
        self.assertIn("no value has been selected", c["note"])
        self.assertIn("resolved_by", c)

    def test_8_a_contradiction_reduces_confidence(self):
        clean = r.reason(packet([fact(conf=0.8)]))["confidence"]
        dirty = r.reason(packet([fact(conf=0.8)],
                                conflicts=self.CONFLICT))["confidence"]
        self.assertIsNotNone(clean)
        self.assertLess(dirty, clean,
                        "evidence that disagrees with itself must cost "
                        "confidence, not merely add a caveat")
        self.assertAlmostEqual(dirty, clean * r.CONTRADICTION_CONFIDENCE_FACTOR,
                               places=4)

    def test_the_engine_never_picks_the_convenient_value(self):
        out = r.reason(packet([fact()], conflicts=self.CONFLICT))
        blob = str(out["contradictions"])
        self.assertNotIn("22", blob.replace("competing", ""))
        self.assertTrue(out["epistemic"]["contradicted"])

    def test_a_contradiction_produces_an_unresolved_diagnosis(self):
        out = r.reason(packet([fact()], conflicts=self.CONFLICT))
        d = [x for x in out["diagnoses"] if x["epistemic"] == r.CONTRADICTED]
        self.assertTrue(d)
        self.assertEqual(d[0]["state"], r.UNRESOLVED)


# ══════════════════════════════════════════════════════════════════════════
# 9-11 · DIAGNOSIS AND HYPOTHESES
# ══════════════════════════════════════════════════════════════════════════

class DiagnosisAndHypotheses(unittest.TestCase):

    def moved(self):
        return r.reason(packet([fact("16")], gaps=ALL_GAPS),
                        history={BIZ: [prior("14", "c1")]})

    def test_9_the_cause_stays_unresolved(self):
        d = self.moved()["diagnoses"][0]
        self.assertEqual(d["state"], r.UNRESOLVED)
        self.assertIn("cause is not", d["why_unresolved"])

    def test_10_every_hypothesis_is_labelled_a_hypothesis(self):
        hyp = self.moved()["hypotheses"]
        self.assertTrue(hyp)
        for h in hyp:
            self.assertEqual(h["epistemic"], r.HYPOTHESIS)
            self.assertIsNone(h["confidence"],
                              "a hypothesis has no confidence to report")
            self.assertEqual(h["supporting_evidence"], [])

    def test_10b_hypotheses_name_what_would_settle_them(self):
        for h in self.moved()["hypotheses"]:
            if h["testable"]:
                self.assertTrue(h["refutable_by"])
            else:
                self.assertIn("no registered predicate", h["note"])

    def test_10c_the_catalogue_matches_the_existing_vocabulary(self):
        """Not invented: exactly the explanations the diagnosis text already
        enumerated — channel, campaign, market, follow-up, measurement."""
        ids = {h[0] for h in r.HYPOTHESES}
        self.assertEqual(ids, {"channel_shift", "campaign_effect",
                               "market_effect", "measurement_artifact",
                               "followup_effect", "capacity_constraint"})

    def test_10d_no_hypotheses_when_nothing_moved(self):
        """Explaining a business that has not moved is narrating noise."""
        self.assertEqual(r.reason(packet([fact()]))["hypotheses"], [])

    def test_11_no_supported_diagnosis_is_reachable_on_this_evidence(self):
        out = self.moved()
        self.assertNotIn(r.SUPPORTED, [d["state"] for d in out["diagnoses"]])

    def test_11b_no_causal_language_appears_anywhere(self):
        blob = str(self.moved()).lower()
        for banned in ("caused by", "because of the ads", "due to marketing",
                       "marketing improved", "ads drove"):
            self.assertNotIn(banned, blob)

    def test_no_promotion_path_from_hypothesis_to_fact_exists(self):
        """STRUCTURAL: nothing in the module assigns FACT to a hypothesis."""
        src = executable_only(r.hypotheses)
        self.assertIn("HYPOTHESIS", src)
        self.assertNotIn("FACT", src)


# ══════════════════════════════════════════════════════════════════════════
# 12-20 · PRIORITIES AND RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════

class PrioritiesAndRecommendations(unittest.TestCase):

    def full(self):
        return r.reason(packet([fact("16")], gaps=ALL_GAPS),
                        history={BIZ: [prior("14", "c1")]},
                        question="What should I focus on?")

    def test_12_no_unsupported_ACT_recommendation_is_produced(self):
        self.assertEqual([x for x in self.full()["recommendations"]
                          if x["kind"] == r.ACT], [])

    def test_13_and_14_measure_and_investigate_are_produced(self):
        kinds = {x["kind"] for x in self.full()["recommendations"]}
        self.assertIn(r.MEASURE, kinds)
        self.assertIn(r.INVESTIGATE, kinds)

    def test_15_to_18_every_missing_metric_is_recognised(self):
        gaps = {u["predicate"] for u in self.full()["gaps"]}
        for predicate in (CONV, PIPE, ATTR, CAP):
            self.assertIn(predicate, gaps)

    def test_15b_missing_metrics_are_never_treated_as_zero(self):
        for u in self.full()["gaps"]:
            self.assertNotIn("value", u)
            self.assertEqual(u["epistemic"], r.UNKNOWN)

    def test_19_priority_uses_evidence_quality(self):
        inv = [p for p in self.full()["priorities"]
               if p["kind"] == r.INVESTIGATE][0]
        self.assertIn("evidence_quality", inv)
        self.assertIn("magnitude", inv)

    def test_19b_lower_provenance_lowers_the_priority_score(self):
        good = r.reason(packet([fact("16", tier=0)]),
                        history={BIZ: [prior("14", "c1")]})["priorities"]
        poor = r.reason(packet([fact("16", tier=5)]),
                        history={BIZ: [prior("14", "c1")]})["priorities"]
        g = [p for p in good if p["kind"] == r.INVESTIGATE][0]["score"]
        p_ = [p for p in poor if p["kind"] == r.INVESTIGATE][0]["score"]
        self.assertGreater(g, p_)

    def test_20_priority_uses_uncertainty_and_information_value(self):
        meas = [p for p in self.full()["priorities"]
                if p["kind"] == r.MEASURE][0]
        self.assertEqual(meas["uncertainty"], "high")
        self.assertIn("information_value", meas)
        self.assertIn("unblocks", meas)

    def test_20b_an_unmeasurable_metric_outranks_a_small_movement(self):
        top = self.full()["priorities"][0]
        self.assertEqual(top["kind"], r.MEASURE)

    def test_21_one_metric_does_not_become_overall_business_health(self):
        blob = str(self.full()).lower()
        for banned in ("business is healthy", "business is doing well",
                       "overall health", "business is growing",
                       "performing well"):
            self.assertNotIn(banned, blob)

    def test_no_priority_invents_money(self):
        blob = str(self.full()["priorities"]).lower()
        for banned in ("₹", "revenue", "rupee", "profit", "roi", "worth"):
            self.assertNotIn(banned, blob)


# ══════════════════════════════════════════════════════════════════════════
# 22-25 · DECISION PLAN, COUNTERFACTUAL, REFS, SCOPE
# ══════════════════════════════════════════════════════════════════════════

class DecisionPlanAndCounterfactual(unittest.TestCase):

    def full(self):
        return r.reason(packet([fact("16")], gaps=ALL_GAPS),
                        history={BIZ: [prior("14", "c1")]},
                        question="What should I do next?")

    def test_22_the_decision_plan_carries_a_reversal_condition(self):
        plan = self.full()["decision_plan"]
        self.assertTrue(plan["reversal_condition"])
        self.assertTrue(plan["decision_question"])
        self.assertTrue(plan["recommended_option"])
        self.assertTrue(plan["next_evidence_needed"])

    def test_22b_the_plan_authorises_nothing(self):
        plan = self.full()["decision_plan"]
        self.assertTrue(plan["advisory"])
        self.assertFalse(plan["action_required"])
        self.assertFalse(plan["authorised"])

    def test_22c_the_plan_echoes_the_owner_question(self):
        self.assertEqual(self.full()["decision_plan"]["decision_question"],
                         "What should I do next?")

    def test_22d_no_plan_without_a_recommendation(self):
        self.assertIsNone(r.reason(packet([fact()]))["decision_plan"])

    def test_23_every_conclusion_says_what_would_change_it(self):
        out = self.full()
        for d in out["diagnoses"]:
            self.assertTrue(d["counterfactual"]["would_change_if"])
        for rec in out["recommendations"]:
            self.assertTrue(rec["counterfactual"]["would_change_if"])

    def test_23b_the_counterfactual_names_the_missing_evidence(self):
        cf = self.full()["recommendations"][0]["counterfactual"]
        self.assertTrue(any(CONV in x for x in cf["would_change_if"]))

    def test_24_evidence_references_survive_every_stage(self):
        out = self.full()
        self.assertEqual(out["evidence"][0]["evidence_ref"], "claim-now")
        self.assertIn("claim-now",
                      out["situation"]["changes"][0]["evidence_refs"])
        self.assertIn("c1", out["situation"]["changes"][0]["evidence_refs"])

    def test_25_business_scope_is_enforced(self):
        with self.assertRaises(r.ReasoningError):
            r.reason(packet([fact()], scope=cx.PARTY))
        with self.assertRaises(r.ReasoningError):
            r.reason(packet([fact()], scope=None))

    def test_26_the_engine_cannot_reach_another_tenant(self):
        """STRUCTURAL: reason() has no store access, so cross-tenant reads are
        impossible rather than merely prevented."""
        import inspect
        src = inspect.getsource(r)
        for banned in ("select(", "insert(", "requests.", "db.", "http"):
            self.assertNotIn(banned, src, banned)

    def test_the_state_carries_every_declared_field(self):
        out = self.full()
        for key in ("question", "goal", "scope", "evidence", "epistemic",
                    "situation", "patterns", "diagnoses", "hypotheses",
                    "priorities", "recommendations", "decision_plan",
                    "confidence", "gaps", "contradictions", "as_of"):
            self.assertIn(key, out, key)


# ══════════════════════════════════════════════════════════════════════════
# 27-33 · WHAT MAY REACH THE MODEL, AND WHAT MAY NOT
# ══════════════════════════════════════════════════════════════════════════

class ConsultIsConstrained(unittest.TestCase):

    def brief(self):
        out = r.reason(packet([fact("16")], gaps=ALL_GAPS),
                       history={BIZ: [prior("14", "c1")]}, question="why?")
        return str(w._reasoning_brief(out, "why?"))

    def test_27_28_29_30_no_memory_crm_transcript_or_pii(self):
        blob = self.brief()
        for secret in ("claim-now", "c1", ORG, TENANT, "919", "918"):
            self.assertNotIn(secret, blob, secret)

    def test_27b_structurally_cannot_inject(self):
        import inspect
        self.assertEqual(list(inspect.signature(w._reasoning_brief).parameters),
                         ["result", "question"])
        src = executable_only(w._reasoning_brief)
        for banned in ("fetch_owner_memory", "recall_from_archive",
                       "owner_business_snapshot", "whatsapp_messages",
                       "leads", "clients", "crm"):
            self.assertNotIn(banned, src, banned)

    def test_hypotheses_reach_the_model_labelled_as_candidates(self):
        blob = self.brief()
        self.assertIn("HYPOTHESES (CANDIDATES ONLY", blob)
        self.assertIn("never state these as fact", blob)

    def test_the_brief_teaches_the_epistemic_language(self):
        blob = self.brief()
        for phrase in ("the evidence shows", "based on these observations",
                       "a possible explanation is",
                       "we cannot currently determine",
                       "the available evidence conflicts"):
            self.assertIn(phrase, blob)
        self.assertIn("Never write", blob)

    def test_the_brief_forbids_causal_and_spending_claims(self):
        blob = self.brief()
        self.assertIn("Do not assert a CAUSE", blob)
        self.assertIn("CAUSE NOT ESTABLISHED", blob)
        self.assertIn("increase", blob.lower())

    def test_31_32_33_no_authorize_execute_or_commitment(self):
        import inspect
        src = executable_only(w.tool_business_reasoning)
        for banned in ("authorize", "commitment", "insert", "assert_claim",
                       "upsert_lead"):
            self.assertNotIn(banned, src, banned)


# ══════════════════════════════════════════════════════════════════════════
# 34-40 · NOTHING ELSE MOVED
# ══════════════════════════════════════════════════════════════════════════

class ExistingBehaviourUnchanged(unittest.TestCase):

    def test_34_business_status_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.tool_business_status)
        self.assertIn("BUSINESS_STATUS_GOAL", src)
        self.assertNotIn("bic_reasoning", src)

    def test_35_business_reasoning_still_uses_the_same_entry_point(self):
        import inspect
        src = inspect.getsource(w.tool_business_reasoning)
        self.assertIn("bic_reasoning.reason", src)
        self.assertIn("bic_explain.validate_narration", src)
        self.assertIn("bic_decide.decide", src)

    def test_35b_focus_recommendation_is_still_blocked(self):
        g = gl.lookup("business_focus_recommendation")
        self.assertEqual(len(g["required_slots"]), 5)
        self.assertNotIn("business_focus_recommendation",
                         inspect_source(w.tool_business_reasoning))

    def test_36_the_client_path_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      src)
        self.assertNotIn("bic_reasoning", src)

    def test_37_owner_direct_tools_are_unchanged(self):
        for t, gate in (("How many enquiries this month?",
                         w.owner_evidence_query),
                        ("What is the business status this month?",
                         w.owner_business_status_query),
                        ("Show my clients", w.owner_lookup_tool)):
            self.assertTrue(gate(t), t)
            self.assertFalse(w.owner_reasoning_query(t), t)

    def test_38_no_second_classifier(self):
        import inspect
        src = inspect.getsource(w.owner_reasoning_query)
        for banned in ("openai", "gemini", "deepseek", "chat.completions"):
            self.assertNotIn(banned, src)
        self.assertIn("_REASONING_MARKERS", src)

    def test_39_40_no_second_context_or_decision_engine(self):
        import inspect
        src = inspect.getsource(r)
        for banned in ("def assemble", "def decide", "def authorize",
                       "def validate_narration"):
            self.assertNotIn(banned, src, banned)

    def test_the_reasoning_core_calls_no_model(self):
        import inspect
        src = inspect.getsource(r).lower()
        for banned in ("openai", "gemini", "deepseek", "chat.completions",
                       "_call_openai", "generate_reply"):
            self.assertNotIn(banned, src, banned)

    def test_provider_and_lead_config_untouched(self):
        self.assertEqual(w.DEEPSEEK_MAX_TOKENS, 1200)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)
        self.assertEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 35)
        import inspect
        self.assertIn("max_tokens=380", inspect.getsource(w.extract_lead_info))
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")',
                      inspect.getsource(w.upsert_lead))

    def test_lead_rows_are_never_treated_as_conversion_evidence(self):
        """§19: only a registered predicate may license a conclusion."""
        import inspect
        src = inspect.getsource(r).lower()
        for banned in ("leads", "crm", "clients"):
            self.assertNotIn(f'"{banned}"', src, banned)


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


# ══════════════════════════════════════════════════════════════════════════
# performance (§23)
# ══════════════════════════════════════════════════════════════════════════

class Performance(unittest.TestCase):

    def test_the_reasoning_pass_is_fast_and_does_no_io(self):
        pk = packet([fact("16")], gaps=ALL_GAPS)
        hist = {BIZ: [prior("14", "c1"), prior("9", "c2")]}
        t0 = time.perf_counter()
        for _ in range(200):
            r.reason(pk, history=hist, question="q")
        ms = (time.perf_counter() - t0) * 1000 / 200
        self.assertLess(ms, 20.0, f"reasoning pass took {ms:.2f}ms")

    def test_history_is_consumed_not_refetched(self):
        """Injected, so the loop adds no database round trip of its own."""
        import inspect
        self.assertIn("history", inspect.signature(r.reason).parameters)


if __name__ == "__main__":
    unittest.main(verbosity=2)
