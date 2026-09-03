"""IDD-2H — Business Context Packet & Sufficiency Gate.

THE QUESTION UNDER TEST
-----------------------
"Do I have enough trustworthy information to complete this business task?"

Not "what do we know" — 2G answers that. Sufficiency is a property of the
(evidence, action) PAIR (§4.4): the same fact can be sufficient for a summary
and insufficient for a payment. Several tests below assert exactly that, by
running IDENTICAL evidence through a tier-1 and a tier-4 goal.

WHAT THESE TESTS MOSTLY GUARD
-----------------------------
Not that the packet is well-formed — that is easy. The failure that matters is
a gate that says PROCEED when it should not: a stale fact quietly filling a
slot, a contested value counting as settled, a budget trimming the evidence a
question needed. Each of those produces a confident answer built on nothing,
which is worse than a refusal.

The three vertical goals (real estate, transformer, social media) are TEST
FIXTURES ONLY. They exist to prove the requirement mechanism is generic —
acceptance criterion 32, "count packet-structure changes when adding a
vertical: exactly zero". No vertical vocabulary appears in bic/context.py.

Offline: no network, no AI, no database.
"""

import ast
import copy
import inspect
import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import context as cx, policy                              # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
SUBJECT = "805d1c4e-0000-4000-8000-000000000001"
PARTIAL = "d542ac32-0000-4000-8000-000000000002"

INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"
SEGMENT = "core.party.engagement_segment@1"
SOCIAL = "Social Media ನಿರ್ವಹಣೆ"

DESCRIPTOR = {"code": "knowledge.describe", "min_role": "STAFF",
              "customer_safe": False, "risk_tier": 1, "active": True}


def owner():
    return policy.Principal("910000000001", "OWNER", TENANT)


def client():
    return policy.Principal("919999000777", "CLIENT", TENANT)


# ── Real production claim shapes, as describe returns them ─────────────────

def fact(predicate, value, tier, cap, conf, volatility, verdict, ref,
         observed, asserted="whatsapp:menu_selection"):
    return {"predicate": predicate, "label": predicate, "value": value,
            "unit": None, "cardinality": "single", "semantic_version": 1,
            "status": "ACTIVE", "confidence": conf,
            "provenance": {"tier": tier, "cap": cap, "source": "whatsapp",
                           "source_kind": "wa_msg", "asserted_by": asserted},
            "valid_from": observed, "valid_until": None,
            "observed_at": observed,
            "freshness": {"verdict": verdict, "volatility_class": volatility,
                          "bound_seconds": None, "age_seconds": 172800,
                          "observed_at": observed},
            "claim_id": ref}


F_FIRST_SEEN = fact(FIRST_SEEN, "2026-08-18T16:07:48.492062+00:00", 1, 0.90,
                    0.90, "static", "PERMANENT",
                    "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                    "2026-08-18T16:07:48.997941+00:00",
                    asserted="whatsapp:first_contact")
F_INTEREST = fact(INTEREST, "Design & Branding", 5, 0.50, 0.50, "slow",
                  "FRESH", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
                  "2026-08-18T16:08:15.536992+00:00")


def envelope(values, *, state="KNOWN", conflicts=(), absent=(), unavailable=(),
             degradation=(), subject=SUBJECT):
    return {
        "capability": "knowledge.describe", "state": state, "reason": None,
        "entity": subject, "subject": subject,
        "identity": {"kind": "PERSON", "resolution_state": "PROVISIONAL"},
        "values": list(values), "conflicts": list(conflicts),
        "coverage": {"requested": None,
                     "consulted": [INTEREST, FIRST_SEEN],
                     "known": [v["predicate"] for v in values],
                     "absent": list(absent), "unavailable": list(unavailable),
                     "unregistered": []},
        "freshness": {"verdict": "FRESH", "stale_predicates": [],
                      "oldest_observed_at": "2026-08-18T16:07:48.997941+00:00"},
        "confidence": {"value_confidence": 0.50, "provenance_ceiling": 0.50,
                       "coverage_ratio": 1.0, "identity_state": "PROVISIONAL"},
        "degraded": bool(degradation), "degradation": list(degradation),
        "trace_ref": None, "asked_at": None, "evaluated_at": None,
        "as_of": None, "as_known_at": None,
    }


def describer(env):
    """A stand-in knowledge.describe. Injected, never imported."""
    def _d(tenant_id, subject, predicates=None, as_of=None):
        if tenant_id != TENANT:
            # Tenant isolation: a foreign tenant sees an unknown entity,
            # never a denial that would confirm the subject exists.
            return envelope([], state="UNKNOWN", absent=predicates or [])
        return env
    return _d


def boom(exc=RuntimeError("store down")):
    def _d(*a, **k):
        raise exc
    return _d


# ── The three vertical goals — FIXTURES ONLY ───────────────────────────────

GOAL_SOCIAL = cx.goal(
    "social_media_enquiry", 1,
    [cx.slot("service_interest", INTEREST, cx.OBTAINABLE_BY_ASKING),
     cx.slot("first_contact", FIRST_SEEN, cx.OBTAINABLE_BY_RETRIEVAL)],
    "Answer a social-media marketing enquiry")

GOAL_REALESTATE = cx.goal(
    "realestate_enquiry", 2,
    [cx.slot("service_interest", INTEREST, cx.OBTAINABLE_BY_ASKING),
     cx.slot("budget", "realestate.enquiry.budget@1", cx.OBTAINABLE_BY_ASKING),
     cx.slot("locality", "realestate.enquiry.locality@1",
             cx.OBTAINABLE_BY_ASKING)],
    "Qualify a real-estate enquiry")

GOAL_TRANSFORMER = cx.goal(
    "transformer_quotation", 4,
    [cx.slot("kva", "mfg.transformer.kva_rating@1", cx.OBTAINABLE_BY_ASKING),
     cx.slot("quantity", "mfg.transformer.quantity@1", cx.OBTAINABLE_BY_ASKING),
     cx.slot("voltage", "mfg.transformer.voltage@1", cx.OBTAINABLE_BY_ASKING),
     cx.slot("delivery_location", "mfg.transformer.delivery_location@1",
             cx.OBTAINABLE_BY_ASKING)],
    "Prepare a transformer quotation")


def code_only(obj) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


class Base(unittest.TestCase):
    def build(self, env=None, goal_def=None, principal=None, **kw):
        return cx.assemble(
            kw.pop("tenant", TENANT), kw.pop("request", "hello"),
            principal or owner(), goal_def or GOAL_SOCIAL,
            kw.pop("subject", SUBJECT),
            describe=describer(env if env is not None
                               else envelope([F_INTEREST, F_FIRST_SEEN])),
            **kw)


# ── 1-2 · sufficient and insufficient ──────────────────────────────────────

class Sufficiency(Base):

    def test_all_slots_filled_proceeds(self):
        p = self.build()
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)
        self.assertEqual(p["epistemic"]["missing"], [])

    def test_all_four_conditions_reported(self):
        s = self.build()["epistemic"]["sufficiency"]
        self.assertEqual(sorted(s["conditions"]),
                         ["confidence", "conflicts", "coverage", "freshness"])
        self.assertTrue(all(s["conditions"].values()))

    def test_missing_slot_does_not_proceed(self):
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN]))
        self.assertNotEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    def test_a_gap_names_the_slot(self):
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN]))
        gaps = p["epistemic"]["sufficiency"]["gaps"]
        self.assertEqual([g["slot"] for g in gaps], ["first_contact"])

    def test_refusal_is_actionable(self):
        """§4.5 — a bare 'I don't know' is a different failure."""
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN]))
        s = p["epistemic"]["sufficiency"]
        self.assertTrue(s["reason"])
        self.assertTrue(all(g["why"] for g in s["gaps"]))


# ── 3-4 · degraded, missing requirement classes ────────────────────────────

class DegradedAndMissing(Base):

    def test_degradation_is_carried(self):
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN],
                                degradation=[{"reason": "stale_value",
                                              "predicate": INTEREST}]))
        self.assertTrue(p["epistemic"]["degradation"])

    def test_obtainable_by_asking_yields_clarify(self):
        g = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        p = self.build(envelope([], state="UNKNOWN", absent=[INTEREST]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.CLARIFY)

    def test_obtainable_by_retrieval_yields_retrieve(self):
        g = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_RETRIEVAL)])
        p = self.build(envelope([], state="UNKNOWN", absent=[INTEREST]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.RETRIEVE)

    def test_unknowable_yields_refuse(self):
        g = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.UNKNOWABLE)])
        p = self.build(envelope([], state="UNKNOWN", absent=[INTEREST]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)

    def test_refused_is_distinguishable_from_never_asked(self):
        """Criterion 15 — 'the customer refused to state their budget' is
        commercially significant; 'we never asked' is a process gap."""
        refused = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.REFUSED)])
        never = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        env = envelope([], state="UNKNOWN", absent=[INTEREST])
        a = self.build(env, refused)["epistemic"]["missing"][0]
        b = self.build(env, never)["epistemic"]["missing"][0]
        self.assertEqual(a["class"], cx.REFUSED)
        self.assertEqual(b["class"], cx.OBTAINABLE_BY_ASKING)
        self.assertNotEqual(a["verdict_if_alone"], b["verdict_if_alone"])

    def test_all_five_missing_classes_exist(self):
        self.assertEqual(len(cx.MISSING_CLASSES), 5)

    def test_the_most_severe_gap_decides(self):
        """Answering the easiest gap first would promise a resolution the
        hardest gap cannot deliver."""
        g = cx.goal("g", 1, [
            cx.slot("askable", INTEREST, cx.OBTAINABLE_BY_ASKING),
            cx.slot("unknowable", FIRST_SEEN, cx.UNKNOWABLE)])
        p = self.build(envelope([], state="UNKNOWN",
                                absent=[INTEREST, FIRST_SEEN]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)


# ── 5, 23 · stale evidence ─────────────────────────────────────────────────

class StaleEvidence(Base):

    def _stale(self):
        f = copy.deepcopy(F_INTEREST)
        f["freshness"]["verdict"] = "STALE"
        return f

    def test_tier1_accepts_stale_but_records_it(self):
        p = self.build(envelope([self._stale(), F_FIRST_SEEN]))
        s = p["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], cx.PROCEED)
        self.assertTrue(s["accepts_stale_evidence"])

    def test_tier4_does_not_accept_stale(self):
        g = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        p = self.build(envelope([self._stale()]), g)
        self.assertNotEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    def test_stale_evidence_does_not_silently_fill_a_high_tier_slot(self):
        g = cx.goal("g", 3, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        p = self.build(envelope([self._stale()]), g)
        gap = p["epistemic"]["missing"][0]
        self.assertIn("STALE", gap["why"])
        self.assertEqual(gap["class"], cx.OBTAINABLE_BY_RETRIEVAL)

    def test_the_same_fact_yields_different_verdicts_by_tier(self):
        """Criterion 17 — sufficiency is a property of the (evidence, action)
        pair, never of the evidence alone."""
        env = envelope([self._stale()])
        low = cx.goal("g", 1, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        high = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        self.assertNotEqual(
            self.build(env, low)["epistemic"]["sufficiency"]["verdict"],
            self.build(env, high)["epistemic"]["sufficiency"]["verdict"])


# ── 6, 24 · conflicts ──────────────────────────────────────────────────────

class Conflicts(Base):

    def _conflicted(self, tier=3):
        other = copy.deepcopy(F_INTEREST)
        other["value"] = "Digital Ads"
        other["claim_id"] = "cccccccc-3333-4333-8333-cccccccccccc"
        env = envelope([F_INTEREST, other], conflicts=[
            {"predicate": INTEREST, "values": ["Design & Branding", "Digital Ads"],
             "cardinality": "single", "resolved": False}])
        g = cx.goal("g", tier, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        return self.build(env, g)

    def test_conflict_is_never_hidden(self):
        p = self._conflicted()
        self.assertEqual(len(p["epistemic"]["conflicts"]), 1)
        self.assertEqual(p["epistemic"]["conflicts"][0]["winner"], "UNRESOLVED")

    def test_conflict_carries_business_consequence(self):
        """§6.2 — that field converts a data-quality note into a decision
        input."""
        c = self._conflicted()["epistemic"]["conflicts"][0]
        self.assertTrue(c["business_consequence"])
        self.assertIn("claims_in_tension", c)

    def test_high_severity_blocks_rather_than_lowering_confidence(self):
        p = self._conflicted(tier=3)
        s = p["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], cx.REFUSE)
        self.assertIn(INTEREST, s["blocking_conflicts"])

    def test_severity_comes_from_the_decision_not_the_facts(self):
        """§6.3 — a discrepancy is HIGH for a state change and LOW for a
        greeting. Same conflict, different severity."""
        self.assertEqual(self._conflicted(tier=1)["epistemic"]["conflicts"][0]["severity"], cx.LOW)
        self.assertEqual(self._conflicted(tier=2)["epistemic"]["conflicts"][0]["severity"], cx.MEDIUM)
        self.assertEqual(self._conflicted(tier=4)["epistemic"]["conflicts"][0]["severity"], cx.HIGH)

    def test_a_contested_fact_never_silently_satisfies_a_requirement(self):
        p = self._conflicted(tier=1)
        gap = p["epistemic"]["missing"][0]
        self.assertIn("contested", gap["why"])


# ── 7-8 · provenance and confidence preserved ──────────────────────────────

class Preservation(Base):

    def test_every_fact_carries_provenance(self):
        """I7."""
        for f in self.build()["evidence"]["facts"]:
            self.assertIsNotNone(f["provenance"]["tier"])
            self.assertIsNotNone(f["provenance"]["asserted_by"])

    def test_tiers_and_caps_survive_assembly(self):
        by = {f["predicate"]: f for f in self.build()["evidence"]["facts"]}
        self.assertEqual(by[FIRST_SEEN]["provenance"]["tier"], 1)
        self.assertEqual(by[FIRST_SEEN]["provenance"]["cap"], 0.90)
        self.assertEqual(by[INTEREST]["provenance"]["tier"], 5)
        self.assertEqual(by[INTEREST]["provenance"]["cap"], 0.50)

    def test_confidences_survive_assembly(self):
        by = {f["predicate"]: f for f in self.build()["evidence"]["facts"]}
        self.assertEqual(by[FIRST_SEEN]["confidence"], 0.90)
        self.assertEqual(by[INTEREST]["confidence"], 0.50)

    def test_freshness_survives_per_fact(self):
        by = {f["predicate"]: f for f in self.build()["evidence"]["facts"]}
        self.assertEqual(by[FIRST_SEEN]["freshness"]["verdict"], "PERMANENT")
        self.assertEqual(by[FIRST_SEEN]["freshness"]["volatility_class"], "static")
        self.assertEqual(by[INTEREST]["freshness"]["verdict"], "FRESH")

    def test_no_packet_level_confidence_scalar(self):
        """C2 / structural criterion 3."""
        p = self.build()
        self.assertNotIn("confidence", p)
        self.assertNotIn("confidence", p["epistemic"])
        s = p["epistemic"]["sufficiency"]
        self.assertNotIn("confidence_score", s)
        self.assertIsInstance(s["weakest_fact"], dict)

    def test_the_weak_dimension_is_named(self):
        w = self.build()["epistemic"]["sufficiency"]["weakest_fact"]
        self.assertEqual(w["predicate"], INTEREST)
        self.assertEqual(w["confidence"], 0.50)


# ── 9 · tenant isolation ───────────────────────────────────────────────────

class TenantIsolation(Base):

    def test_foreign_tenant_gets_no_evidence(self):
        p = self.build(tenant=OTHER_TENANT)
        self.assertEqual(p["evidence"]["facts"], [])

    def test_foreign_tenant_sees_unknown_not_denied(self):
        """A denial would confirm the subject exists in another tenant."""
        p = self.build(tenant=OTHER_TENANT)
        self.assertEqual(p["assembly_state"], cx.A_UNKNOWN)

    def test_no_cross_tenant_value_leak(self):
        blob = repr(self.build(tenant=OTHER_TENANT))
        self.assertNotIn("Design & Branding", blob)
        self.assertNotIn(SOCIAL, blob)

    def test_visibility_scope_is_the_tenant(self):
        self.assertEqual(self.build()["principal"]["visibility_scope"], TENANT)


# ── 10-12 · UNKNOWN / DENIED / UNAVAILABLE stay distinct ───────────────────

class DistinctStates(Base):

    def test_unknown(self):
        p = self.build(envelope([], state="UNKNOWN", absent=[INTEREST, FIRST_SEEN]))
        self.assertEqual(p["assembly_state"], cx.A_UNKNOWN)

    def test_denied_is_not_planned_not_filtered(self):
        """Criterion 10 / §3.2 — restricted capabilities are NOT called."""
        called = []

        def spy(*a, **k):
            called.append(a)
            return envelope([F_INTEREST, F_FIRST_SEEN])

        p = cx.assemble(TENANT, "hi", client(), GOAL_SOCIAL, SUBJECT,
                        describe=spy, descriptor=DESCRIPTOR)
        self.assertEqual(p["assembly_state"], cx.A_DENIED)
        self.assertEqual(called, [], "retrieval ran despite denial")
        self.assertEqual(p["evidence"]["facts"], [])

    def test_unavailable(self):
        p = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                        describe=boom())
        self.assertEqual(p["assembly_state"], cx.A_UNAVAILABLE)

    def test_unavailable_reports_the_type_only(self):
        p = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                        describe=boom(RuntimeError("boom 919999000222")))
        self.assertNotIn("919999000222", repr(p))

    def test_the_states_are_all_different(self):
        unknown = self.build(envelope([], state="UNKNOWN"))["assembly_state"]
        denied = cx.assemble(TENANT, "hi", client(), GOAL_SOCIAL, SUBJECT,
                             describe=describer(envelope([])),
                             descriptor=DESCRIPTOR)["assembly_state"]
        unavailable = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                                  describe=boom())["assembly_state"]
        ok = self.build()["assembly_state"]
        self.assertEqual(len({unknown, denied, unavailable, ok}), 4)

    def test_assembly_state_is_separate_from_the_verdict(self):
        """An outage and an insufficiency are different situations."""
        p = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                        describe=boom())
        self.assertEqual(p["assembly_state"], cx.A_UNAVAILABLE)
        self.assertIn(p["epistemic"]["sufficiency"]["verdict"], cx.VERDICTS)


# ── ESCALATE ───────────────────────────────────────────────────────────────

class Escalation(Base):

    def test_sufficient_but_above_the_ceiling_escalates(self):
        """Criterion 16 — ESCALATE, not refuse."""
        g = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        f = copy.deepcopy(F_INTEREST)
        f["confidence"] = 0.99
        f["provenance"]["tier"] = 0
        f["provenance"]["cap"] = 1.0
        staff = policy.Principal("910000000002", "STAFF", TENANT)
        p = self.build(envelope([f]), g, principal=staff)
        s = p["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], cx.ESCALATE)
        self.assertEqual(s["principal_tier_ceiling"], 3)

    def test_owner_ceiling_permits_tier_four(self):
        g = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        f = copy.deepcopy(F_INTEREST)
        f["confidence"] = 0.99
        p = self.build(envelope([f]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    def test_all_five_verdicts_exist(self):
        self.assertEqual(len(cx.VERDICTS), 5)


# ── 13-14, 19 · determinism, no LLM, no storage ────────────────────────────

class Boundaries(unittest.TestCase):

    def _src(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "context.py")) as fh:
            return fh.read()

    def test_no_direct_storage_access(self):
        """I4 — no storage concepts in a packet, and none in the plane."""
        tree = ast.parse(self._src())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        for banned in ("db", "claims", "party", "registry", "requests",
                       "knowledge", "supabase", "psycopg2"):
            self.assertNotIn(banned, modules)
        for banned in ("select(", "insert(", "update(", "rest/v1", "SELECT "):
            self.assertNotIn(banned, self._src())

    def test_assembly_makes_no_ai_calls(self):
        """I11 / criterion 26 — enforced by there being nothing that could."""
        src = self._src().lower()
        for provider in ("openai", "gemini", "groq", "openrouter", "deepseek",
                         "anthropic", "llm", "completion", "embed"):
            self.assertNotIn(provider, src)

    def test_no_vertical_vocabulary_in_the_engine(self):
        """Criterion 32 — adding a vertical must change zero packet structure."""
        src = self._src().lower()
        for word in ("transformer", "kva", "realestate", "real estate",
                     "voltage", "locality", "social media", "brochure"):
            self.assertNotIn(word, src)

    def test_result_is_deterministic(self):
        env = envelope([F_INTEREST, F_FIRST_SEEN])
        verdicts, gaps = set(), set()
        for _ in range(10):
            p = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                            describe=describer(env))
            verdicts.add(p["epistemic"]["sufficiency"]["verdict"])
            gaps.add(len(p["epistemic"]["missing"]))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(len(gaps), 1)

    def test_no_fuzzy_matching_or_ai_subject_selection(self):
        src = code_only(cx).lower()
        for smell in ("fuzzy", "similar", "levenshtein", "guess", "best_match",
                      "score(", "classify"):
            self.assertNotIn(smell, src)

    def test_identity_must_be_resolved_before_assembly(self):
        """I12 — a packet without a subject has no visibility scope."""
        with self.assertRaises(cx.ContextError):
            cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, None)

    def test_packet_is_immutable(self):
        """I2 / criterion 19."""
        p = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                        describe=describer(envelope([F_INTEREST])))
        for attempt in (lambda: p.__setitem__("tenant_id", "x"),
                        lambda: p.pop("evidence"),
                        lambda: p.update({"a": 1}),
                        lambda: p.clear()):
            with self.assertRaises(cx.ContextError):
                attempt()


# ── 15-18 · real fixtures and the three vertical goals ─────────────────────

class RealProductionFixtures(Base):

    def test_context_contains_first_seen_at(self):
        preds = [f["predicate"] for f in self.build()["evidence"]["facts"]]
        self.assertIn(FIRST_SEEN, preds)

    def test_context_contains_declared_service_interest(self):
        preds = [f["predicate"] for f in self.build()["evidence"]["facts"]]
        self.assertIn(INTEREST, preds)

    def test_partial_context_names_the_gap(self):
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN]),
                       subject=PARTIAL)
        self.assertEqual(len(p["evidence"]["facts"]), 1)
        self.assertIn(FIRST_SEEN, p["epistemic"]["coverage"]["absent"])
        self.assertEqual([g["slot"] for g in
                          p["epistemic"]["sufficiency"]["gaps"]],
                         ["first_contact"])

    def test_social_media_goal_proceeds_on_real_evidence(self):
        p = self.build(goal_def=GOAL_SOCIAL)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    def test_realestate_goal_needs_more_than_the_same_evidence(self):
        """Same party, same claims — a different goal needs different facts.

        Note the service_interest slot is ALSO unmet here, and not because the
        fact is absent: it is a tier-5 customer self-declaration capped at
        0.50 (Article II.6), and the tier-2 floor is 0.60. Provenance is a
        ceiling, so this fact cannot satisfy a tier-2 requirement no matter
        how recent it is. See ProvenanceCeiling below.
        """
        p = self.build(envelope([F_INTEREST], absent=[FIRST_SEEN]),
                       GOAL_REALESTATE)
        s = p["epistemic"]["sufficiency"]
        self.assertNotEqual(s["verdict"], cx.PROCEED)
        self.assertEqual(sorted(g["slot"] for g in s["gaps"]),
                         ["budget", "locality", "service_interest"])
        # The two genuinely-absent slots are askable; the third is a floor miss.
        by = {g["slot"]: g["class"] for g in s["gaps"]}
        self.assertEqual(by["budget"], cx.OBTAINABLE_BY_ASKING)
        self.assertEqual(by["service_interest"], cx.OBTAINABLE_BY_RETRIEVAL)

    def test_realestate_clarifies_once_the_floor_is_met(self):
        strong = copy.deepcopy(F_INTEREST)
        strong["confidence"], strong["provenance"]["tier"] = 0.80, 2
        strong["provenance"]["cap"] = 0.80
        p = self.build(envelope([strong], absent=[FIRST_SEEN]), GOAL_REALESTATE)
        s = p["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], cx.CLARIFY)
        self.assertEqual(sorted(g["slot"] for g in s["gaps"]),
                         ["budget", "locality"])

    def test_transformer_goal_refuses_with_the_missing_slot_named(self):
        """The brief's worked example: KVA + quantity + voltage known,
        delivery location missing → INSUFFICIENT."""
        # Tier-0 provenance (cap 1.00) so these clear the tier-4 floor of
        # 0.95 — otherwise the gap would be "everything", which is true but
        # not the example being demonstrated.
        known = [
            fact("mfg.transformer.kva_rating@1", "500", 0, 1.00, 0.98,
                 "static", "PERMANENT", "d1", "2026-08-18T10:00:00+00:00"),
            fact("mfg.transformer.quantity@1", "3", 0, 1.00, 0.98,
                 "static", "PERMANENT", "d2", "2026-08-18T10:00:00+00:00"),
            fact("mfg.transformer.voltage@1", "11kV", 0, 1.00, 0.98,
                 "static", "PERMANENT", "d3", "2026-08-18T10:00:00+00:00"),
        ]
        p = self.build(envelope(known,
                                absent=["mfg.transformer.delivery_location@1"]),
                       GOAL_TRANSFORMER)
        s = p["epistemic"]["sufficiency"]
        self.assertNotEqual(s["verdict"], cx.PROCEED)
        self.assertEqual([g["slot"] for g in s["gaps"]], ["delivery_location"])
        self.assertEqual(len(p["evidence"]["facts"]), 3)

    def test_adding_a_vertical_changes_no_packet_structure(self):
        """Criterion 32, stated as an assertion."""
        a = self.build(goal_def=GOAL_SOCIAL)
        b = self.build(goal_def=GOAL_TRANSFORMER)
        self.assertEqual(sorted(a.keys()), sorted(b.keys()))
        self.assertEqual(sorted(a["epistemic"].keys()),
                         sorted(b["epistemic"].keys()))


# ── 20-22 · traceability, subject consistency, budget ──────────────────────

class TraceabilityAndBudget(Base):

    def test_evidence_refs_are_carried(self):
        p = self.build()
        self.assertEqual(len(p["epistemic"]["evidence_refs"]), 2)

    def test_three_independent_versions(self):
        """§8.3 / structural criterion 7."""
        p = self.build()
        self.assertEqual(p["packet_schema_version"], cx.PACKET_SCHEMA_VERSION)
        self.assertEqual(p["assembly_version"], cx.ASSEMBLY_VERSION)
        self.assertIn("policy_version", p)

    def test_subject_is_consistent_across_the_packet(self):
        p = self.build()
        self.assertEqual(p["question"]["goal"], GOAL_SOCIAL["goal_id"])
        self.assertEqual(p["goal_ref"], GOAL_SOCIAL["goal_id"])

    def test_digest_is_stable_for_identical_content(self):
        env = envelope([F_INTEREST])
        a = cx.assemble(TENANT, "hi", owner(), GOAL_SOCIAL, SUBJECT,
                        describe=describer(env))
        b = dict(a)
        self.assertEqual(cx.digest(b), cx.digest(dict(a)))

    def test_budget_prunes_evidence_only(self):
        """C3 / I10 / criterion 11 — conflict retained, evidence pruned."""
        other = copy.deepcopy(F_INTEREST)
        other["value"] = "Digital Ads"
        other["claim_id"] = "zzz"
        env = envelope([F_INTEREST, F_FIRST_SEEN, other], conflicts=[
            {"predicate": INTEREST, "values": ["a", "b"], "resolved": False}])
        g = cx.goal("g", 1, [cx.slot("s", SEGMENT, cx.OBTAINABLE_BY_ASKING,
                                     optional=True)])
        p = self.build(env, g, evidence_budget=1)
        self.assertEqual(len(p["evidence"]["facts"]), 1)
        self.assertEqual(len(p["epistemic"]["conflicts"]), 1)
        self.assertTrue(p["epistemic"]["pruning_trace"])

    def test_boundaries_are_never_pruned(self):
        p = self.build(evidence_budget=0,
                       policies=[{"id": "p1", "text": "no discount over 20%"}],
                       constraints=[{"id": "c1", "text": "capacity"}])
        self.assertEqual(p["evidence"]["facts"], [])
        self.assertEqual(len(p["boundaries"]["policies"]), 1)
        self.assertEqual(len(p["boundaries"]["constraints"]), 1)

    def test_pruning_a_required_slot_refuses_rather_than_truncating(self):
        """§5.4 / criterion 12."""
        p = self.build(evidence_budget=0)
        s = p["epistemic"]["sufficiency"]
        self.assertEqual(s["verdict"], cx.REFUSE)
        self.assertIn("pruned", s["reason"])

    def test_pruning_trace_explains_the_exclusion(self):
        """§7.1 / criterion 23."""
        p = self.build(evidence_budget=1)
        self.assertTrue(all(t["reason"] for t in p["epistemic"]["pruning_trace"]))

    def test_policies_are_not_evidence(self):
        """C1 / structural criterion 2 — structurally separate."""
        p = self.build(policies=[{"id": "p1", "text": "advisory"}])
        self.assertIn("policies", p["boundaries"])
        self.assertNotIn("policies", p["evidence"])
        for f in p["evidence"]["facts"]:
            self.assertNotIn("policy", f["predicate"])


# ── Structure and PII ──────────────────────────────────────────────────────

class StructureAndPii(Base):

    def test_six_sections_present(self):
        p = self.build()
        for section in ("question", "principal", "evidence", "boundaries",
                        "epistemic"):
            self.assertIn(section, p)
        self.assertIn("packet_id", p)

    def test_epistemic_state_is_first_class(self):
        """Structural criterion 4 — absence must not look like a field nobody
        needed."""
        ep = self.build()["epistemic"]
        for key in ("conflicts", "missing", "freshness", "coverage",
                    "degradation", "sufficiency", "evidence_refs"):
            self.assertIn(key, ep)

    def test_no_storage_concepts_in_the_packet(self):
        """Criterion 9."""
        blob = repr(self.build())
        for smell in ("bic_claims", "bic_parties", "rest/v1", "SELECT",
                      "table", "cursor", "row_count"):
            self.assertNotIn(smell, blob)

    def test_no_phone_email_wamid_or_source_ref(self):
        blob = repr(self.build())
        self.assertNotIn("source_ref", blob)
        self.assertNotIn("wamid", blob)
        import re
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob))

    def test_only_the_source_scheme_is_carried(self):
        for f in self.build()["evidence"]["facts"]:
            self.assertEqual(f["provenance"]["source_kind"], "wa_msg")

    def test_no_prompt_or_model_output_in_the_packet(self):
        blob = repr(self.build()).lower()
        for smell in ("system_prompt", "you are", "assistant:", "temperature"):
            self.assertNotIn(smell, blob)


class ProvenanceCeiling(Base):
    """Article II.6 meeting IDD-2H §4.4, and the consequence is structural.

    A customer self-declaration is provenance tier 5, capped at 0.50. The
    tier-2 confidence floor is 0.60. So a fact the CUSTOMER told us can never,
    by itself, satisfy a tier-2-or-higher requirement — however fresh, however
    recently confirmed. That is provenance behaving as a ceiling rather than a
    hint, and it means anything above "answer a question" needs corroboration
    from a better-sourced fact.
    """

    def _at(self, tier):
        g = cx.goal("g", tier, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        return self.build(envelope([F_INTEREST]), g)["epistemic"]["sufficiency"]

    def test_customer_declaration_satisfies_tier_one(self):
        self.assertEqual(self._at(1)["verdict"], cx.PROCEED)

    def test_customer_declaration_cannot_satisfy_tier_two(self):
        s = self._at(2)
        self.assertNotEqual(s["verdict"], cx.PROCEED)
        self.assertIn("below the tier-2 floor", s["gaps"][0]["why"])

    def test_it_fails_on_the_floor_not_on_absence(self):
        s = self._at(3)
        self.assertEqual(s["gaps"][0]["class"], cx.OBTAINABLE_BY_RETRIEVAL)
        self.assertNotIn("no fact on record", s["gaps"][0]["why"])

    def test_a_tier_one_provenance_fact_clears_every_floor(self):
        strong = copy.deepcopy(F_FIRST_SEEN)
        strong["predicate"] = INTEREST
        strong["confidence"] = 0.90
        g = cx.goal("g", 3, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        p = self.build(envelope([strong]), g)
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)


class ThresholdsAreGoverned(unittest.TestCase):
    """§4.6 — thresholds drift downward every time they block work, and
    within a year nothing is gated. They are pinned here so a change is
    visible in review rather than silent."""

    def test_confidence_floors_match_the_idd_table(self):
        self.assertEqual(cx.RISK_CONFIDENCE_FLOOR,
                         {1: 0.50, 2: 0.60, 3: 0.80, 4: 0.95})

    def test_tier_four_requires_human_approval(self):
        self.assertTrue(cx.RISK_REQUIRES_APPROVAL[4])
        self.assertFalse(cx.RISK_REQUIRES_APPROVAL[1])

    def test_high_tiers_reject_stale_evidence(self):
        self.assertEqual(cx.RISK_ACCEPTS_STALE,
                         {1: True, 2: True, 3: False, 4: False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
