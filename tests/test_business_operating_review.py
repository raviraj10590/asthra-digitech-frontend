"""Business Operating Review — the scorecard goal that makes gaps visible.

WHAT PRODUCTION PROVED, AND WHAT THIS FIXES
-------------------------------------------
A real OWNER asked "What should I do next?". The loop ran correctly — 7.7s,
ok=True, no fabrication — and returned 274 characters saying enquiries are 20
and no action was taken. Correct, safe, and nearly useless.

The cause was the goal, not the engine. `business_month_review` requires ONE
predicate. It was satisfied, so sufficiency reached PROCEED with an empty gap
list — and every stage after SITUATION is fed by gaps or changes, of which
there were neither.

`business_operating_review` declares the five dimensions the business is
actually judged by, reusing the SAME predicate references
business_focus_recommendation already declared. Four are unregistered. That
does not make them measurable and is not meant to: it makes them VISIBLE, so
the loop can name what is missing, why it blocks a conclusion, and what would
close it.

THE SECOND FIX: THE RENDERER LIED
---------------------------------
With `changes` empty it printed "none — a single reading is not a trend".
Production hit that branch with TEN comparable readings sitting flat at 20.
Claiming we lack data while holding plenty is the most misleading thing this
renderer could say.

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
from bic import context as cx, goals as gl                     # noqa: E402
from bic import reasoning as r                                 # noqa: E402

REVIEW = "business_operating_review"
FOCUS = "business_focus_recommendation"
BIZ, CONV = gl.NEW_ENQUIRIES, gl.CONVERSION_RATE
PIPE, ATTR, CAP = gl.PIPELINE_VALUE, gl.CHANNEL_ATTRIBUTION, gl.CAPACITY
TENANT = "00000000-0000-0000-0000-000000000001"
ORG = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"

# The real production series: ten readings, currently flat at 20.
REAL_SERIES = ["20", "20", "16", "14", "9", "3", "0", "7", "7", "7"]


def executable_only(fn):
    import inspect, tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(fn)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def fact(value="20", predicate=BIZ, label="New enquiries per month",
         conf=0.70, verdict="FRESH", claim_id="claim-now", tier=3, unit="count"):
    return {"predicate": predicate, "label": label, "value": value,
            "unit": unit, "confidence": conf,
            "provenance": {"tier": tier, "cap": 0.70},
            "valid_from": "2026-09-01T00:00:00+00:00",
            "observed_at": "2026-09-07T04:22:40+00:00",
            "freshness": {"verdict": verdict}, "claim_id": claim_id}


def scorecard_gaps(cls=cx.UNKNOWABLE):
    """The four dimensions the review declares and cannot get."""
    return [{"slot": s["name"], "predicate": s["predicate"],
             "class": cls, "why": "x"}
            for s in gl.lookup(REVIEW)["required_slots"][1:]]


def packet(facts=(), gaps=(), conflicts=(), scope=cx.BUSINESS,
           verdict=cx.REFUSE, tenant=TENANT, goal=REVIEW):
    return {
        "packet_id": "p1", "tenant_id": tenant, "subject": ORG, "scope": scope,
        "goal_ref": goal, "assembly_state": "OK",
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


def prior(value, cid, ns="biz.pipeline", concept="new_enquiries_per_month",
          version=1, unit=None):
    row = {"claim_id": cid, "value": value, "predicate_ns": ns,
           "predicate_concept": concept, "semantic_version": version}
    if unit is not None:
        row["unit"] = unit
    return row


def real_history():
    return [prior(v, f"c{i}") for i, v in enumerate(REAL_SERIES[1:], start=1)]


def full(question="What should I do next?"):
    return r.reason(packet([fact()], gaps=scorecard_gaps()),
                    history={BIZ: real_history()}, question=question)


# ══════════════════════════════════════════════════════════════════════════
# 1-12 · the goal and the scorecard
# ══════════════════════════════════════════════════════════════════════════

class TheGoal(unittest.TestCase):

    def test_1_the_operating_review_goal_exists(self):
        self.assertIn(REVIEW, gl.known_ids())

    def test_2_it_is_business_scoped_and_tier_2(self):
        g = gl.lookup(REVIEW)
        self.assertEqual(g["scope"], cx.BUSINESS)
        self.assertEqual(g["risk_tier"], 2)

    def test_3_all_five_scorecard_dimensions_are_declared(self):
        names = [s["name"] for s in gl.lookup(REVIEW)["required_slots"]]
        self.assertEqual(names, ["new_enquiries", "conversion_rate",
                                 "pipeline_value", "channel_attribution",
                                 "capacity"])

    def test_3b_it_invents_no_predicate(self):
        """Same references business_focus_recommendation already declared —
        one definition of the scorecard, not two that can drift."""
        mine = [s["predicate"] for s in gl.lookup(REVIEW)["required_slots"]]
        theirs = [s["predicate"] for s in gl.lookup(FOCUS)["required_slots"]]
        self.assertEqual(mine, theirs)

    def test_12_the_recommendation_goal_is_untouched(self):
        g = gl.lookup(FOCUS)
        self.assertEqual(len(g["required_slots"]), 5)
        self.assertEqual(g["scope"], cx.BUSINESS)
        self.assertNotEqual(w.REASONING_GOAL, FOCUS)

    def test_the_loop_reasons_over_the_review_goal(self):
        self.assertEqual(w.REASONING_GOAL, REVIEW)


class MeasuredUnknownUnknowable(unittest.TestCase):

    def test_the_three_classes_are_distinct_literal_values(self):
        """Pinned as LITERALS, not via the constants. Every other test here
        compares against r.EV_*, so redefining EV_UNKNOWABLE = "MEASURED"
        would satisfy all of them while telling the owner — and the model,
        which reads the class in the brief — that an undefined metric is
        measured. The word itself is part of the contract."""
        self.assertEqual(r.EV_MEASURED, "MEASURED")
        self.assertEqual(r.EV_UNKNOWN, "UNKNOWN")
        self.assertEqual(r.EV_UNKNOWABLE, "UNKNOWABLE")
        self.assertEqual(len(set(r.EVIDENCE_CLASSES)), 3)
        self.assertEqual(set(r.EVIDENCE_CLASSES),
                         {"MEASURED", "UNKNOWN", "UNKNOWABLE"})

    def test_an_undefined_metric_is_never_labelled_measured_anywhere(self):
        out = full()
        for u in out["gaps"]:
            self.assertEqual(u["evidence_class"], "UNKNOWABLE")
        self.assertIn("[UNKNOWABLE]", str(w._reasoning_brief(out, "q")))
        self.assertNotIn("[MEASURED]", str(w._reasoning_brief(out, "q")))

    def test_4_new_enquiries_is_measured(self):
        out = full()
        o = out["evidence"][0]
        self.assertEqual(o["evidence_class"], r.EV_MEASURED)
        self.assertEqual(o["epistemic"], r.FACT)

    def test_5_to_8_the_four_dimensions_are_unknowable(self):
        gaps = {u["predicate"]: u for u in full()["gaps"]}
        for predicate in (CONV, PIPE, ATTR, CAP):
            self.assertIn(predicate, gaps)
            self.assertEqual(gaps[predicate]["evidence_class"],
                             r.EV_UNKNOWABLE, predicate)
            self.assertFalse(gaps[predicate]["measurable"], predicate)

    def test_a_registered_but_unavailable_metric_is_UNKNOWN_not_UNKNOWABLE(self):
        """The distinction that decides who does what: a collection gap needs
        the path fixed; a missing definition needs the business to define it."""
        out = r.reason(packet([fact()],
                              gaps=scorecard_gaps(cx.OBTAINABLE_BY_RETRIEVAL)),
                       history={BIZ: real_history()})
        for u in out["gaps"]:
            self.assertEqual(u["evidence_class"], r.EV_UNKNOWN)
            self.assertTrue(u["measurable"])
            self.assertIn("collection path", u["closed_by"])

    def test_an_unknowable_metric_says_it_needs_defining(self):
        for u in full()["gaps"]:
            self.assertIn("defining and capturing", u["closed_by"])

    def test_9_unknown_metrics_are_never_treated_as_zero(self):
        for u in full()["gaps"]:
            self.assertNotIn("value", u)
            self.assertNotIn("numeric", u)

    def test_10_unknown_metrics_are_never_treated_as_measured(self):
        measured = {o["predicate"] for o in full()["evidence"]}
        for predicate in (CONV, PIPE, ATTR, CAP):
            self.assertNotIn(predicate, measured)

    def test_11_the_review_surfaces_the_gaps(self):
        """The whole point: business_month_review produced none."""
        self.assertEqual(len(full()["gaps"]), 4)


# ══════════════════════════════════════════════════════════════════════════
# 13-21 · temporal + comparability, on the real series
# ══════════════════════════════════════════════════════════════════════════

class TemporalOnRealData(unittest.TestCase):

    def test_13_one_observation_is_point_in_time(self):
        out = r.reason(packet([fact()], gaps=scorecard_gaps()))
        self.assertEqual(out["evidence"][0]["temporal"], r.POINT_IN_TIME)
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["situation"]["stable_signals"], [])

    def test_14_two_equal_observations_are_stable_not_a_change(self):
        out = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                       history={BIZ: [prior("20", "c1")]})
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(len(out["situation"]["stable_signals"]), 1)
        self.assertEqual(out["situation"]["stable_signals"][0]["pattern"], r.FLAT)

    def test_15_two_different_observations_are_a_movement(self):
        out = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                       history={BIZ: [prior("14", "c1")]})
        t = out["situation"]["changes"][0]
        self.assertEqual(t["pattern"], r.INCREASE)
        self.assertEqual(t["temporal"], r.MOVEMENT)

    def test_16_the_real_ten_point_series_is_recognised(self):
        out = full()
        self.assertEqual(out["evidence"][0]["temporal"], r.RECURRENCE_T)
        self.assertEqual(len(out["situation"]["stable_signals"]), 1)
        self.assertGreaterEqual(
            out["situation"]["stable_signals"][0]["observations"], 3)

    def test_17_a_stale_reading_never_trends(self):
        out = r.reason(packet([fact(verdict="STALE")], gaps=scorecard_gaps()),
                       history={BIZ: real_history()})
        self.assertEqual(out["situation"]["changes"], [])
        self.assertEqual(out["situation"]["stable_signals"], [])

    def test_18_a_semantic_version_change_breaks_comparability(self):
        out = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                       history={BIZ: [prior("14", "c1", version=2)]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_19_a_unit_mismatch_breaks_comparability(self):
        out = r.reason(packet([fact("20", unit="count")], gaps=scorecard_gaps()),
                       history={BIZ: [prior("14", "c1", unit="percent")]})
        self.assertEqual(out["situation"]["changes"], [])

    def test_20_21_a_contradiction_is_kept_and_costs_confidence(self):
        conflict = [{"predicate": BIZ, "competing_values": ["20", "31"]}]
        clean = r.reason(packet([fact(conf=0.8)], gaps=scorecard_gaps()))
        dirty = r.reason(packet([fact(conf=0.8)], gaps=scorecard_gaps(),
                                conflicts=conflict))
        self.assertEqual(dirty["contradictions"][0]["epistemic"],
                         r.CONTRADICTED)
        self.assertLess(dirty["confidence"], clean["confidence"])


# ══════════════════════════════════════════════════════════════════════════
# 22-32 · diagnosis, priorities, recommendations, plan, counterfactual
# ══════════════════════════════════════════════════════════════════════════

class ReviewOutput(unittest.TestCase):

    def test_22_overall_performance_is_UNRESOLVED_not_supported(self):
        d = [x for x in full()["diagnoses"]
             if x["about"] == "overall business performance"]
        self.assertTrue(d, "the review must say it cannot judge the business")
        self.assertEqual(d[0]["state"], r.UNRESOLVED)
        self.assertEqual(d[0]["epistemic"], r.UNKNOWN)

    def test_22b_it_says_what_is_measurable_and_what_is_not(self):
        d = [x for x in full()["diagnoses"]
             if x["about"] == "overall business performance"][0]
        self.assertIn("is measurable", d["why_unresolved"])
        self.assertEqual(len(d["missing_evidence"]), 4)

    def test_22c_it_never_claims_the_business_is_doing_well_or_badly(self):
        blob = str(full()).lower()
        for banned in ("business is poor", "business is healthy",
                       "performing well", "performing poorly",
                       "business is growing", "marketing is the cause",
                       "sales conversion is"):
            self.assertNotIn(banned, blob)

    def test_23_hypotheses_stay_labelled_when_present(self):
        moved = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                         history={BIZ: [prior("14", "c1")]})
        self.assertTrue(moved["hypotheses"])
        for h in moved["hypotheses"]:
            self.assertEqual(h["epistemic"], r.HYPOTHESIS)
            self.assertIsNone(h["confidence"])

    def test_24_no_causal_certainty_anywhere(self):
        blob = str(full()).lower()
        for banned in ("caused by", "because of", "due to", "led to",
                       "drove the"):
            self.assertNotIn(banned, blob)

    def test_25_26_measure_and_investigate_are_produced(self):
        out = full()
        kinds = [x["kind"] for x in out["recommendations"]]
        self.assertIn(r.MEASURE, kinds)
        moved = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                         history={BIZ: [prior("14", "c1")]})
        self.assertIn(r.INVESTIGATE, [x["kind"] for x in moved["recommendations"]])

    def test_27_no_ACT_recommendation_is_possible(self):
        for out in (full(),
                    r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                             history={BIZ: [prior("14", "c1")]})):
            self.assertEqual([x for x in out["recommendations"]
                              if x["kind"] == r.ACT], [])

    def test_the_priority_names_the_bottleneck_not_just_the_gap(self):
        p = [x for x in full()["priorities"] if x["kind"] == r.MEASURE][0]
        self.assertIn("commercial outcome", p["reason"])
        self.assertIn("closed_by", p)

    def test_28_29_the_decision_plan_is_about_evidence_and_can_be_reversed(self):
        plan = full()["decision_plan"]
        self.assertIsNotNone(plan)
        self.assertEqual(plan["option_kind"], r.MEASURE)
        self.assertTrue(plan["reversal_condition"])
        self.assertEqual(len(plan["next_evidence_needed"]), 4)
        self.assertTrue(plan["advisory"])
        self.assertFalse(plan["action_required"])
        self.assertFalse(plan["authorised"])

    def test_30_counterfactuals_exist_on_diagnoses_and_recommendations(self):
        out = full()
        for d in out["diagnoses"]:
            self.assertTrue(d["counterfactual"]["would_change_if"])
        for rec in out["recommendations"]:
            self.assertTrue(rec["counterfactual"]["would_change_if"])

    def test_31_evidence_refs_survive(self):
        out = full()
        self.assertEqual(out["evidence"][0]["evidence_ref"], "claim-now")
        self.assertIn("claim-now",
                      out["situation"]["stable_signals"][0]["evidence_refs"])

    def test_32_business_scope_is_enforced(self):
        with self.assertRaises(r.ReasoningError):
            r.reason(packet([fact()], scope=cx.PARTY))

    def test_44_to_47_no_fabricated_metric_carries_a_number(self):
        import re
        blob = re.sub(r"[a-z_.]+@\d+", "<ref>", str(full()))
        for name in ("conversion", "capacit", "attribut", "revenue",
                     "pipeline value"):
            for m in re.finditer(name, blob, re.I):
                self.assertNotRegex(blob[m.end():m.end() + 40],
                                    r"^[^a-zA-Z]{0,8}\d", name)


# ══════════════════════════════════════════════════════════════════════════
# 43 · the renderer bug
# ══════════════════════════════════════════════════════════════════════════

class RendererTellsTheTruth(unittest.TestCase):

    def render(self, out):
        with redirect_stdout(io.StringIO()):
            return w.render_business_reasoning(out, None, "REFUSE")

    def test_43_flat_multi_point_data_is_not_called_a_single_reading(self):
        """THE BUG. Production had ten readings and was told it had one."""
        txt = self.render(full())
        self.assertNotIn("single reading", txt)
        self.assertIn("comparable readings, no movement", txt)
        self.assertIn("stable at", txt)

    def test_43b_a_genuine_single_reading_says_so_correctly(self):
        txt = self.render(r.reason(packet([fact()], gaps=scorecard_gaps())))
        self.assertIn("no comparable earlier reading exists yet", txt)
        self.assertNotIn("single reading is not a trend", txt)

    def test_43c_no_evidence_at_all_says_that_instead(self):
        txt = self.render(r.reason(packet([], gaps=scorecard_gaps())))
        self.assertIn("nothing is currently measured", txt)

    def test_a_movement_still_renders_as_a_movement(self):
        out = r.reason(packet([fact("20")], gaps=scorecard_gaps()),
                       history={BIZ: [prior("14", "c1")]})
        txt = self.render(out)
        self.assertIn("movement between two comparable readings", txt)
        self.assertIn("Cause NOT established", txt)

    def test_the_three_gap_classes_render_separately(self):
        txt = self.render(full())
        self.assertIn("NOT YET MEASURABLE", txt)
        self.assertNotIn("MEASURED BUT UNAVAILABLE", txt)
        avail = self.render(r.reason(
            packet([fact()], gaps=scorecard_gaps(cx.OBTAINABLE_BY_RETRIEVAL)),
            history={BIZ: real_history()}))
        self.assertIn("MEASURED BUT UNAVAILABLE", avail)

    def test_the_reply_is_substantive_now(self):
        """274 characters was the production output. This must beat it."""
        txt = self.render(full())
        self.assertGreater(len(txt), 800)
        for section in ("📌 OBSERVED", "🔍 DIAGNOSIS", "🎯 PRIORITIES",
                        "✅ RECOMMENDED NEXT", "🧭 DECISION PLAN",
                        "🔄 WHAT WOULD CHANGE THIS",
                        "No action has been taken or authorised"):
            self.assertIn(section, txt, section)


# ══════════════════════════════════════════════════════════════════════════
# 33-42 · routing, CONSULT, safety, and what must not move
# ══════════════════════════════════════════════════════════════════════════

class RoutingAndSafety(unittest.TestCase):

    def test_33_the_review_questions_route_to_reasoning(self):
        for t in ("What is happening in my business?",
                  "What is the current business situation?",
                  "Give me a business review.",
                  "What should I focus on?",
                  "What should I do next?",
                  "Why are my enquiries low?"):
            self.assertTrue(w.owner_reasoning_query(t), t)

    def test_34_owner_direct_tools_still_win_their_questions(self):
        for t, gate in (("How many enquiries this month?",
                         w.owner_evidence_query),
                        ("What is the business status this month?",
                         w.owner_business_status_query),
                        ("Show my clients", w.owner_lookup_tool)):
            self.assertTrue(gate(t), t)
            self.assertFalse(w.owner_reasoning_query(t), t)

    def test_the_gates_remain_mutually_exclusive(self):
        cases = {"What is the business status this month?": ("status",),
                 "How many enquiries this month?": ("count",),
                 "Give me a business review.": ("reason",),
                 "Show my clients": ("lookup",),
                 "Why is my phone slow?": ()}
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

    def test_35_the_client_path_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      src)

    def test_36_37_38_the_consult_brief_stays_packet_only(self):
        import inspect
        self.assertEqual(list(inspect.signature(w._reasoning_brief).parameters),
                         ["result", "question"])
        src = executable_only(w._reasoning_brief)
        for banned in ("fetch_owner_memory", "recall_from_archive",
                       "owner_business_snapshot", "whatsapp_messages",
                       "leads", "clients", "crm"):
            self.assertNotIn(banned, src, banned)
        blob = str(w._reasoning_brief(full(), "why?"))
        for secret in ("claim-now", "c1", ORG, TENANT, "919"):
            self.assertNotIn(secret, blob, secret)

    def test_the_brief_carries_the_evidence_class(self):
        blob = str(w._reasoning_brief(full(), "why?"))
        self.assertIn(f"[{r.EV_UNKNOWABLE}]", blob)

    def test_the_brief_does_not_repeat_the_single_reading_lie(self):
        """The renderer's bug lived here too — and this copy is worse, because
        the MODEL reads it and would hedge about data it actually has."""
        blob = str(w._reasoning_brief(full(), "why?"))
        self.assertNotIn("a single reading is not a trend", blob)
        self.assertIn("STABLE at", blob)
        self.assertIn("comparable readings", blob)

    def test_the_brief_still_says_so_when_there_is_one_reading(self):
        blob = str(w._reasoning_brief(
            r.reason(packet([fact()], gaps=scorecard_gaps())), "why?"))
        self.assertIn("no comparable earlier reading exists yet", blob)

    def test_the_brief_says_so_when_nothing_is_measured(self):
        blob = str(w._reasoning_brief(
            r.reason(packet([], gaps=scorecard_gaps())), "why?"))
        self.assertIn("nothing is measured", blob)

    def test_39_40_41_no_authorize_execute_or_commitment(self):
        src = executable_only(w.tool_business_reasoning)
        for banned in ("authorize", "commitment", "insert", "assert_claim",
                       "upsert_lead"):
            self.assertNotIn(banned, src, banned)

    def test_42_the_narration_validator_is_still_invoked(self):
        import inspect
        self.assertIn("bic_explain.validate_narration",
                      inspect.getsource(w.tool_business_reasoning))

    def test_provider_and_lead_config_untouched(self):
        import inspect
        self.assertEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 35)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)
        self.assertIn("max_tokens=380", inspect.getsource(w.extract_lead_info))
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")',
                      inspect.getsource(w.upsert_lead))

    def test_no_internal_note_regression(self):
        import inspect
        self.assertEqual(
            inspect.getsource(w).count("log_reply_to_crm(sender"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
