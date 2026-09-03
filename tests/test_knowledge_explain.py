"""knowledge.explain — justification over already-retrieved evidence (2G §7).

WHAT THESE TESTS ARE ACTUALLY GUARDING
--------------------------------------
Not "does it produce nice prose". The danger in an explanation layer is the
opposite of the danger in a retrieval layer: retrieval fails loudly, but a
fluent explanation of facts that were never retrieved fails silently and is
believed. §7.4 names it — "a plausible fiction fitted to the answer,
convincing, unfalsifiable, and worse than silence."

So the bulk of this file tests what the capability CANNOT do: reach storage,
alter evidence, invent a number, mint an identifier, inflate a tier cap into
certainty, or quietly pick a winner from conflicting claims.

The production fixtures are the same five real claims validated against the
live database, reduced to describe envelopes.

Offline: no network, no AI, no database. The narrator is always a stub.
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import explain as x, policy                                # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
P_FULL = "805d1c4e"
P_PART = "d542ac32"
INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"
SEGMENT = "core.party.engagement_segment@1"
SOCIAL = "Social Media ನಿರ್ವಹಣೆ"

DESCRIPTOR = {"code": "knowledge.explain", "min_role": "STAFF",
              "customer_safe": False, "risk_tier": 1, "active": True}


def value(predicate, val, tier, cap, conf, volatility, verdict,
          claim_id, observed, valid_from=None, asserted="whatsapp:menu_selection"):
    return {
        "predicate": predicate, "label": predicate, "value": val,
        "unit": None, "cardinality": "single", "semantic_version": 1,
        "status": "ACTIVE", "confidence": conf,
        "provenance": {"tier": tier, "cap": cap, "source": "whatsapp",
                       "source_kind": "wa_msg", "asserted_by": asserted},
        "valid_from": valid_from or observed, "valid_until": None,
        "observed_at": observed,
        "freshness": {"verdict": verdict, "volatility_class": volatility,
                      "bound_seconds": None if volatility == "static" else 15552000,
                      "age_seconds": 172800, "observed_at": observed},
        "claim_id": claim_id,
    }


# ── The real production party with two facts (805d1c4e) ────────────────────
FULL = {
    "capability": "knowledge.describe", "state": "KNOWN", "reason": None,
    "entity": P_FULL, "subject": P_FULL,
    "identity": {"kind": "PERSON", "resolution_state": "PROVISIONAL"},
    "values": [
        value(FIRST_SEEN, "2026-08-18T16:07:48.492062+00:00", 1, 0.90, 0.90,
              "static", "PERMANENT", "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
              "2026-08-18T16:07:48.997941+00:00",
              valid_from="2026-08-18T16:07:48.492062+00:00",
              asserted="whatsapp:first_contact"),
        value(INTEREST, "Design & Branding", 5, 0.50, 0.50, "slow", "FRESH",
              "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
              "2026-08-18T16:08:15.536992+00:00"),
    ],
    "conflicts": [],
    "coverage": {"requested": None,
                 "consulted": [INTEREST, SEGMENT, FIRST_SEEN],
                 "known": [INTEREST, FIRST_SEEN], "absent": [SEGMENT],
                 "unavailable": [], "unregistered": []},
    "freshness": {"verdict": "FRESH", "stale_predicates": [],
                  "oldest_observed_at": "2026-08-18T16:07:48.997941+00:00"},
    "confidence": {"value_confidence": 0.50, "provenance_ceiling": 0.50,
                   "coverage_ratio": 0.6667, "identity_state": "PROVISIONAL"},
    "degraded": False, "degradation": [], "trace_ref": None,
    "asked_at": "2026-08-20T00:00:00+00:00",
    "evaluated_at": "2026-08-20T00:00:00+00:00",
    "as_of": None, "as_known_at": None,
}

# ── The real partial-knowledge party (d542ac32) ────────────────────────────
PARTIAL = {
    "capability": "knowledge.describe", "state": "KNOWN", "reason": None,
    "entity": P_PART, "subject": P_PART,
    "identity": {"kind": "PERSON", "resolution_state": "PROVISIONAL"},
    "values": [value(INTEREST, SOCIAL, 5, 0.50, 0.50, "slow", "FRESH",
                     "cccccccc-3333-4333-8333-cccccccccccc",
                     "2026-08-18T11:07:50.829544+00:00")],
    "conflicts": [],
    "coverage": {"requested": None,
                 "consulted": [INTEREST, SEGMENT, FIRST_SEEN],
                 "known": [INTEREST], "absent": [SEGMENT, FIRST_SEEN],
                 "unavailable": [], "unregistered": []},
    "freshness": {"verdict": "FRESH", "stale_predicates": [],
                  "oldest_observed_at": "2026-08-18T11:07:50.829544+00:00"},
    "confidence": {"value_confidence": 0.50, "provenance_ceiling": 0.50,
                   "coverage_ratio": 0.3333, "identity_state": "PROVISIONAL"},
    "degraded": False, "degradation": [], "trace_ref": None,
    "asked_at": "2026-08-20T00:00:00+00:00",
    "evaluated_at": "2026-08-20T00:00:00+00:00",
    "as_of": None, "as_known_at": None,
}

# ── Constructed OFFLINE: a conflict production does not have ───────────────
CONFLICT = copy.deepcopy(PARTIAL)
CONFLICT["values"] = [
    value(INTEREST, SOCIAL, 5, 0.50, 0.50, "slow", "FRESH",
          "dddddddd-4444-4444-8444-dddddddddddd",
          "2026-08-18T11:07:50.829544+00:00"),
    value(INTEREST, "Digital Ads", 5, 0.50, 0.50, "slow", "FRESH",
          "eeeeeeee-5555-4555-8555-eeeeeeeeeeee",
          "2026-08-18T11:07:50.829544+00:00"),
]
CONFLICT["conflicts"] = [{
    "predicate": INTEREST, "values": ["Digital Ads", SOCIAL],
    "cardinality": "single",
    "reason": "multiple_active_values_on_single_cardinality",
    "resolved": False}]
CONFLICT["degraded"] = True
CONFLICT["degradation"] = [{"reason": "conflict_present", "predicate": INTEREST}]

UNKNOWN_ENV = {
    "capability": "knowledge.describe", "state": "UNKNOWN",
    "reason": "no_claims_found", "entity": P_PART, "subject": P_PART,
    "identity": {"kind": "PERSON", "resolution_state": "PROVISIONAL"},
    "values": [], "conflicts": [],
    "coverage": {"requested": None, "consulted": [INTEREST, FIRST_SEEN],
                 "known": [], "absent": [INTEREST, FIRST_SEEN],
                 "unavailable": [], "unregistered": []},
    "freshness": {"verdict": None, "stale_predicates": [],
                  "oldest_observed_at": None},
    "confidence": {"value_confidence": None, "provenance_ceiling": None,
                   "coverage_ratio": 0.0, "identity_state": "PROVISIONAL"},
    "degraded": False, "degradation": [], "trace_ref": None,
    "asked_at": None, "evaluated_at": None, "as_of": None, "as_known_at": None,
}

UNAVAILABLE_ENV = dict(UNKNOWN_ENV, state="UNAVAILABLE",
                       reason="store_unavailable",
                       coverage=dict(UNKNOWN_ENV["coverage"],
                                     absent=[], unavailable=[INTEREST, FIRST_SEEN]))


# ── Deterministic stub narrators (never a live model) ──────────────────────

def faithful(brief):
    return ("We hold 2 facts about this party. The service interest is "
            "Design & Branding, self-declared at tier 5 with confidence 0.5. "
            "First contact was recorded by our own transport at tier 1.")


def invents_number(brief):
    return "The party has 7 open projects worth 250000 rupees."


def invents_claim_id(brief):
    return "See evidence ffffffff-9999-4999-8999-ffffffffffff for details."


def inflates_confidence(brief):
    return "We are certain the party wants Design & Branding."


def leaks_phone(brief):
    return "The party contacted us from 919999000222 about branding."


def leaks_wamid(brief):
    return "Recorded in message wamid.HBgMOTE5OTk5MDAwMjIy."


def empty(brief):
    return "   "


def explodes(brief):
    raise RuntimeError("provider down: prompt was 'secret internal text'")


class Base(unittest.TestCase):
    def explain(self, envelope=FULL, **kwargs):
        return x.explain(copy.deepcopy(envelope), **kwargs)


# ── 1. Known explanation ───────────────────────────────────────────────────

class KnownExplanation(Base):

    def test_state_and_shape(self):
        out = self.explain()
        self.assertEqual(out["capability"], "knowledge.explain")
        self.assertEqual(out["kind"], "EXPLAIN")
        self.assertEqual(out["state"], "KNOWN")
        for field in ("explanation", "questions", "evidence", "conflicts",
                      "coverage", "freshness", "confidence", "degraded",
                      "trace_ref", "evidence_digest"):
            self.assertIn(field, out)

    def test_the_four_questions_are_all_answered(self):
        q = self.explain()["questions"]
        self.assertEqual(sorted(q), ["what_confidence", "why_not_another",
                                     "why_this_information", "why_this_source"])

    def test_explanation_is_grounded_in_exactly_the_supplied_facts(self):
        out = self.explain()
        joined = " ".join(out["explanation"])
        self.assertIn("Design & Branding", joined)
        self.assertIn(FIRST_SEEN, joined)
        self.assertEqual(len(out["questions"]["why_this_source"]), 2)

    def test_evidence_is_carried_not_replaced_by_prose(self):
        """§3.2 still applies: an explanation adds a layer, it does not
        substitute for the structured result."""
        out = self.explain()
        self.assertEqual(len(out["evidence"]), 2)
        self.assertEqual(out["evidence"], FULL["values"])

    def test_capabilities_called_is_reported(self):
        q = self.explain()["questions"]["why_this_information"]
        self.assertEqual(q["capabilities_called"], ["knowledge.describe"])
        self.assertEqual(q["consulted"], [INTEREST, SEGMENT, FIRST_SEEN])

    def test_nothing_is_ever_reported_as_pruned(self):
        """§3.5 — unresolved conflicts cannot be budget-dropped."""
        self.assertEqual(
            self.explain()["questions"]["why_this_information"]["pruned"], [])


# ── 2. Partial knowledge ───────────────────────────────────────────────────

class PartialKnowledge(Base):

    def test_explains_only_what_is_known(self):
        out = self.explain(PARTIAL)
        self.assertEqual(len(out["evidence"]), 1)
        self.assertEqual(len(out["questions"]["why_this_source"]), 1)

    def test_missing_coverage_is_named_explicitly(self):
        out = self.explain(PARTIAL)
        joined = " ".join(out["explanation"])
        self.assertIn(FIRST_SEEN, joined)
        self.assertIn(SEGMENT, joined)
        self.assertIn("absence of record", joined)

    def test_absence_is_not_turned_into_a_statement_about_the_party(self):
        joined = " ".join(self.explain(PARTIAL)["explanation"]).lower()
        for invented in ("not interested", "no interest in", "does not want",
                         "never contacted", "is not a customer"):
            self.assertNotIn(invented, joined)

    def test_invents_nothing(self):
        out = self.explain(PARTIAL)
        self.assertEqual([v["value"] for v in out["evidence"]], [SOCIAL])


# ── 3-5. UNKNOWN / DENIED / UNAVAILABLE are three different answers ────────

class DistinctStates(Base):

    def test_unknown_explains_insufficient_knowledge(self):
        out = self.explain(UNKNOWN_ENV)
        joined = " ".join(out["explanation"])
        self.assertEqual(out["state"], "UNKNOWN")
        self.assertIn("no current knowledge", joined)
        self.assertIn("not a refusal", joined)
        self.assertIn("Nothing is inferred from the absence", joined)

    def test_unavailable_explains_an_incomplete_request(self):
        out = self.explain(UNAVAILABLE_ENV)
        joined = " ".join(out["explanation"])
        self.assertEqual(out["state"], "UNAVAILABLE")
        self.assertIn("could not be reached", joined)
        self.assertIn("NOT an absence of knowledge", joined)

    def test_denied_explains_authorization(self):
        out = self.explain(FULL,
                           principal=policy.Principal("1", "CLIENT", TENANT),
                           descriptor=DESCRIPTOR)
        joined = " ".join(out["explanation"])
        self.assertEqual(out["state"], "DENIED")
        self.assertIn("not authorized", joined)
        self.assertIn("not an absence of knowledge", joined)

    def test_the_three_explanations_are_all_different(self):
        texts = {
            " ".join(self.explain(UNKNOWN_ENV)["explanation"]),
            " ".join(self.explain(UNAVAILABLE_ENV)["explanation"]),
            " ".join(self.explain(
                FULL, principal=policy.Principal("1", "CLIENT", TENANT),
                descriptor=DESCRIPTOR)["explanation"]),
        }
        self.assertEqual(len(texts), 3)

    def test_none_of_them_invents_an_explanation(self):
        for env in (UNKNOWN_ENV, UNAVAILABLE_ENV):
            out = self.explain(env)
            self.assertEqual(out["evidence"], [])
            self.assertEqual(out["questions"]["why_this_source"], [])


# ── 6-8. Provenance / confidence / freshness preserved exactly ─────────────

class Preservation(Base):

    def test_provenance_is_preserved_per_fact(self):
        chains = {c["predicate"]: c
                  for c in self.explain()["questions"]["why_this_source"]}
        self.assertEqual(chains[FIRST_SEEN]["tier"], 1)
        self.assertEqual(chains[FIRST_SEEN]["tier_cap"], 0.90)
        self.assertEqual(chains[FIRST_SEEN]["asserted_by"], "whatsapp:first_contact")
        self.assertEqual(chains[INTEREST]["tier"], 5)
        self.assertEqual(chains[INTEREST]["tier_cap"], 0.50)

    def test_confidence_is_preserved_and_never_recomputed(self):
        out = self.explain()
        self.assertEqual(out["confidence"]["vector"], FULL["confidence"])
        self.assertEqual([v["confidence"] for v in out["evidence"]],
                         [0.90, 0.50])

    def test_confidence_is_a_vector_with_the_dominating_dimension_named(self):
        """§7.3: EXPLAIN returns the vector AND names the dominating dimension."""
        conf = self.explain()["confidence"]
        self.assertIsInstance(conf["vector"], dict)
        self.assertIsNotNone(conf["dominating_dimension"])
        self.assertTrue(conf["dominating_because"])

    def test_identity_dominates_while_it_is_unresolved(self):
        conf = self.explain()["confidence"]
        self.assertEqual(conf["dominating_dimension"], "identity_state")
        self.assertIn("PROVISIONAL", conf["dominating_because"])

    def test_weakest_numeric_dimension_dominates_once_identity_resolves(self):
        env = copy.deepcopy(FULL)
        env["confidence"]["identity_state"] = "RESOLVED"
        env["confidence"]["coverage_ratio"] = 0.20
        conf = x.explain(env)["confidence"]
        self.assertEqual(conf["dominating_dimension"], "coverage_ratio")

    def test_projected_scalar_is_the_minimum_never_an_average(self):
        env = copy.deepcopy(FULL)
        env["confidence"]["identity_state"] = "RESOLVED"
        conf = x.explain(env)["confidence"]
        self.assertEqual(conf["projected_scalar"], 0.50)
        self.assertIn("minimum", conf["projection_rule"])

    def test_tier_caps_applied_are_reported_per_fact(self):
        caps = {c["predicate"]: c
                for c in self.explain()["confidence"]["tier_caps_applied"]}
        self.assertTrue(caps[INTEREST]["at_cap"])
        self.assertEqual(caps[INTEREST]["cap"], 0.50)

    def test_freshness_is_preserved_per_fact(self):
        chains = {c["predicate"]: c
                  for c in self.explain()["questions"]["why_this_source"]}
        self.assertEqual(chains[FIRST_SEEN]["freshness_verdict"], "PERMANENT")
        self.assertEqual(chains[FIRST_SEEN]["volatility_class"], "static")
        self.assertEqual(chains[INTEREST]["freshness_verdict"], "FRESH")
        self.assertEqual(chains[INTEREST]["volatility_class"], "slow")

    def test_freshness_block_is_carried_verbatim(self):
        self.assertEqual(self.explain()["freshness"], FULL["freshness"])


# ── 9. Conflict narration ──────────────────────────────────────────────────

class Conflicts(Base):

    def test_explanation_states_that_evidence_conflicts(self):
        joined = " ".join(self.explain(CONFLICT)["explanation"])
        self.assertIn("EVIDENCE CONFLICTS", joined)
        self.assertIn("No value has been selected", joined)

    def test_both_competing_values_are_named(self):
        joined = " ".join(self.explain(CONFLICT)["explanation"])
        self.assertIn(SOCIAL, joined)
        self.assertIn("Digital Ads", joined)

    def test_no_silent_selection(self):
        out = self.explain(CONFLICT)
        competing = out["questions"]["why_not_another"][0]
        self.assertFalse(competing["resolved"])
        self.assertEqual(len(out["evidence"]), 2)

    def test_the_missing_rung_is_declared_not_fabricated(self):
        """§7.2 asks for the rung that settled it. Nothing settled it."""
        out = self.explain(CONFLICT)
        self.assertIsNone(out["questions"]["why_not_another"][0]["outranked_at_rung"])
        self.assertIn(x.DEG_LADDER_NOT_IMPLEMENTED,
                      {d["reason"] for d in out["degradation"]})

    def test_the_ladder_is_not_implemented_here(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "bic",
                                "explain.py")).read()
        names = {n.name for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef)}
        for banned in ("resolve_conflict", "pick", "adjudicate", "rank",
                       "winner", "best_claim", "choose"):
            self.assertNotIn(banned, names)


# ── 10-13. The model cannot introduce anything ─────────────────────────────

class ModelCannotInventFacts(Base):

    def test_a_faithful_narration_is_accepted(self):
        out = self.explain(narrator=faithful)
        self.assertIsNotNone(out["narration"])
        self.assertEqual(out["narration_source"], "model")
        self.assertIsNone(out["narration_rejected"])

    def test_an_invented_number_is_rejected(self):
        out = self.explain(narrator=invents_number)
        self.assertIsNone(out["narration"])
        self.assertEqual(out["narration_rejected"], x.REJ_UNSUPPORTED_NUMBER)

    def test_an_invented_claim_id_is_rejected(self):
        out = self.explain(narrator=invents_claim_id)
        self.assertEqual(out["narration_rejected"], x.REJ_UNSUPPORTED_IDENTIFIER)

    def test_confidence_inflating_language_is_rejected(self):
        """tier 1 / 0.90 must not become 'certain'. No IDD clause permits it."""
        out = self.explain(narrator=inflates_confidence)
        self.assertEqual(out["narration_rejected"], x.REJ_CERTAINTY_LANGUAGE)

    def test_a_rejected_narration_still_returns_the_explanation(self):
        out = self.explain(narrator=invents_number)
        self.assertTrue(out["explanation"])
        self.assertEqual(out["state"], "KNOWN")
        self.assertEqual(len(out["evidence"]), 2)

    def test_a_rejection_is_recorded_not_hidden(self):
        out = self.explain(narrator=invents_number)
        self.assertTrue(out["degraded"])
        self.assertIn(x.DEG_NARRATION_REJECTED,
                      {d["reason"] for d in out["degradation"]})

    def test_a_narrator_failure_degrades_without_leaking_the_prompt(self):
        out = self.explain(narrator=explodes)
        self.assertIn(x.DEG_NARRATION_UNAVAILABLE,
                      {d["reason"] for d in out["degradation"]})
        self.assertNotIn("secret internal text", repr(out))

    def test_an_empty_narration_is_rejected(self):
        self.assertEqual(self.explain(narrator=empty)["narration_rejected"],
                         x.REJ_EMPTY)

    def test_narration_cannot_change_the_structured_evidence(self):
        """Step 20: altering model wording cannot alter the evidence."""
        base = self.explain()
        for narrator in (faithful, invents_number, inflates_confidence,
                         invents_claim_id, empty, explodes):
            out = self.explain(narrator=narrator)
            self.assertEqual(out["evidence"], base["evidence"])
            self.assertEqual(out["evidence_digest"], base["evidence_digest"])
            self.assertEqual(out["confidence"]["vector"],
                             base["confidence"]["vector"])
            self.assertEqual(out["questions"]["why_this_source"],
                             base["questions"]["why_this_source"])

    def test_no_new_claim_ids_can_appear(self):
        for narrator in (faithful, invents_claim_id):
            out = self.explain(narrator=narrator)
            self.assertEqual({v["claim_id"] for v in out["evidence"]},
                             {"aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                              "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"})

    def test_no_new_provenance_tier_can_appear(self):
        out = self.explain(narrator=faithful)
        self.assertEqual({v["provenance"]["tier"] for v in out["evidence"]},
                         {1, 5})

    def test_the_validator_allows_only_evidence_numbers(self):
        out = self.explain()
        allowed = x.allowed_tokens(out)
        self.assertIn("0.5", allowed)
        self.assertIn("5", allowed)
        self.assertNotIn("250000", allowed)


# ── 14. Traceability ───────────────────────────────────────────────────────

class Traceability(Base):

    def test_trace_ref_is_carried_never_minted(self):
        self.assertIsNone(self.explain()["trace_ref"])
        env = dict(copy.deepcopy(FULL), trace_ref="turn-123")
        self.assertEqual(x.explain(env)["trace_ref"], "turn-123")

    def test_every_fact_carries_an_evidence_ref(self):
        for chain in self.explain()["questions"]["why_this_source"]:
            self.assertTrue(chain["evidence_ref"])

    def test_the_evidence_digest_detects_tampering(self):
        out = self.explain()
        self.assertEqual(out["evidence_digest"], x._digest(out["evidence"]))
        tampered = copy.deepcopy(out["evidence"])
        tampered[0]["confidence"] = 0.99
        self.assertNotEqual(out["evidence_digest"], x._digest(tampered))

    def test_the_explained_retrieval_is_identified(self):
        self.assertEqual(self.explain()["explains"]["capability"],
                         "knowledge.describe")


# ── 15. PII ────────────────────────────────────────────────────────────────

class NoPii(Base):

    def test_no_raw_source_ref_reaches_the_explanation(self):
        blob = repr(self.explain())
        self.assertNotIn("source_ref", blob)
        self.assertNotIn("wamid", blob)

    def test_only_the_source_scheme_is_shown(self):
        chain = self.explain()["questions"]["why_this_source"][0]
        self.assertEqual(chain["source_kind"], "wa_msg")

    def test_a_narration_leaking_a_phone_is_rejected(self):
        out = self.explain(narrator=leaks_phone)
        self.assertEqual(out["narration_rejected"], x.REJ_PII)
        self.assertNotIn("919999000222", repr(out))

    def test_a_narration_leaking_a_wamid_is_rejected(self):
        out = self.explain(narrator=leaks_wamid)
        self.assertIn(out["narration_rejected"], (x.REJ_PII,
                                                  x.REJ_UNSUPPORTED_NUMBER))
        self.assertIsNone(out["narration"])

    def test_the_brief_given_to_the_model_carries_no_pii(self):
        out = self.explain()
        brief = x.build_brief(out)
        self.assertNotIn("wamid", brief)
        self.assertNotIn("source_ref", brief)
        for pattern in x._PII_RES:
            self.assertIsNone(pattern.search(brief), brief)


# ── 16-19. Structural boundaries ───────────────────────────────────────────

class Boundaries(unittest.TestCase):

    def _source(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "explain.py")) as fh:
            return fh.read()

    def test_no_direct_database_access(self):
        tree = ast.parse(self._source())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        for banned in ("db", "claims", "party", "registry", "requests",
                       "knowledge", "supabase"):
            self.assertNotIn(banned, modules)

    def test_the_module_cannot_retrieve_anything(self):
        src = self._source()
        for banned in ("select(", "insert(", "update(", "rest/v1",
                       "describe(", "current(", "as_known_at("):
            self.assertNotIn(banned, src)

    def test_no_model_provider_is_imported(self):
        """The narrator is injected. This module never chooses a provider,
        so it cannot call one behind the caller's back — and costs nothing
        to test."""
        src = self._source().lower()
        for provider in ("openai", "gemini", "groq", "openrouter", "deepseek",
                         "anthropic", "requests"):
            self.assertNotIn(provider, src)

    def test_no_vector_or_rag_infrastructure(self):
        src = self._source().lower()
        for banned in ("embed", "pgvector", "faiss", "cosine", "vector store"):
            self.assertNotIn(banned, src)

    def test_the_model_is_never_called_without_a_narrator(self):
        calls = []
        x.explain(copy.deepcopy(FULL))
        self.assertEqual(calls, [])
        out = x.explain(copy.deepcopy(FULL),
                        narrator=lambda b: calls.append(b) or "ok")
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(out["narration"])

    def test_the_model_is_called_only_after_the_evidence_is_fixed(self):
        """Pipeline order: describe -> evidence -> explain -> narration."""
        seen = {}

        def narrator(brief):
            seen["digest_at_call_time"] = brief
            return "Two facts are on record."

        out = x.explain(copy.deepcopy(FULL), narrator=narrator)
        self.assertIn("digest_at_call_time", seen)
        # The brief the model saw was built from the finished explanation.
        self.assertEqual(seen["digest_at_call_time"],
                         "\n".join(out["explanation"]))

    def test_it_refuses_an_envelope_it_did_not_come_from(self):
        with self.assertRaises(x.ExplainError):
            x.explain({"capability": "knowledge.find", "state": "KNOWN"})

    def test_it_refuses_a_non_envelope(self):
        for bad in (None, "text", 42, []):
            with self.assertRaises(x.ExplainError):
                x.explain(bad)


class Authorization(Base):

    def test_it_uses_the_existing_policy_gate(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "explain.py")) as fh:
            src = fh.read()
        self.assertIn("may_invoke", src)
        for smell in ('"min_role"', '"customer_safe"', '"OWNER"', '"STAFF"'):
            self.assertNotIn(smell, src)

    def test_staff_and_owner_are_allowed(self):
        for role in ("OWNER", "STAFF"):
            out = self.explain(principal=policy.Principal("1", role, TENANT),
                               descriptor=DESCRIPTOR)
            self.assertEqual(out["state"], "KNOWN")

    def test_client_is_denied(self):
        out = self.explain(principal=policy.Principal("1", "CLIENT", TENANT),
                           descriptor=DESCRIPTOR)
        self.assertEqual(out["state"], "DENIED")

    def test_a_principal_without_a_descriptor_fails_closed(self):
        self.assertEqual(
            self.explain(principal=policy.Principal("1", "OWNER", TENANT))["state"],
            "DENIED")

    def test_an_inactive_descriptor_denies(self):
        self.assertEqual(
            self.explain(principal=policy.Principal("1", "OWNER", TENANT),
                         descriptor=dict(DESCRIPTOR, active=False))["state"],
            "DENIED")

    def test_a_denied_explanation_carries_no_evidence(self):
        out = self.explain(principal=policy.Principal("1", "CLIENT", TENANT),
                           descriptor=DESCRIPTOR)
        self.assertEqual(out["evidence"], [])
        self.assertEqual(out["questions"]["why_this_source"], [])
        self.assertNotIn("Design & Branding", repr(out))


# ── 20. The caller's envelope is never mutated ─────────────────────────────

class Immutability(Base):

    def test_the_input_envelope_is_not_mutated(self):
        original = copy.deepcopy(FULL)
        x.explain(FULL, narrator=faithful)
        self.assertEqual(FULL, original)

    def test_mutating_the_output_cannot_reach_the_input(self):
        env = copy.deepcopy(FULL)
        out = x.explain(env)
        out["evidence"][0]["confidence"] = 0.99
        self.assertEqual(env["values"][0]["confidence"], 0.90)

    def test_evidence_is_json_identical_to_the_describe_values(self):
        out = self.explain()
        self.assertEqual(json.dumps(out["evidence"], sort_keys=True),
                         json.dumps(FULL["values"], sort_keys=True))


# ── 21. #interest is untouched ─────────────────────────────────────────────

class InterestUnchanged(unittest.TestCase):

    def test_the_tool_does_not_use_explain(self):
        import inspect
        import webhook as w
        src = inspect.getsource(w.tool_service_interest)
        self.assertNotIn("explain", src)
        self.assertIn("bic_knowledge.describe", src)

    def test_the_renderer_does_not_use_explain(self):
        import inspect
        import webhook as w
        self.assertNotIn("explain", inspect.getsource(w.render_knowledge))


# ── 22. The registry row ───────────────────────────────────────────────────

class MigrationRow(unittest.TestCase):

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260816000015_bic_knowledge_explain.sql")
        with open(path) as fh:
            self.sql = fh.read()
        # Comment-stripped, string-stripped SQL. Matching DDL as a
        # SUBSTRING finds "drop" inside "prose dropped" and reports a
        # destructive migration that does not exist — a test that reads
        # English is not a test of SQL. Trailing comments count too: a
        # line-start-only strip leaves "false,  -- note" in the stream.
        out, i, in_str = [], 0, False
        body = self.sql
        while i < len(body):
            ch = body[i]
            if in_str:
                if ch == "'":
                    if i + 1 < len(body) and body[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
                i += 1
                continue
            if ch == "'":
                in_str = True
                i += 1
                continue
            if ch == "-" and body[i:i + 2] == "--":
                while i < len(body) and body[i] != "\n":
                    i += 1
                continue
            out.append(ch)
            i += 1
        self.code = "".join(out)

    def test_it_registers_the_capability_as_explain_kind(self):
        self.assertIn("'knowledge.explain'", self.sql)
        self.assertIn("'EXPLAIN'", self.sql)

    def test_it_is_active_now_that_a_caller_dispatches_it(self):
        """#why is the dispatch, so SHADOW/inactive would now be false.

        Status is a claim about EXPOSURE, not code quality: one owner-only
        command is LIMITED, never GENERAL.
        """
        self.assertNotIn("'SHADOW'", self.sql)
        self.assertRegex(self.sql, r"true,[^\n]*\n\s*'LIMITED'")

    def test_the_command_row_is_owner_only_through_the_existing_gate(self):
        self.assertIn("'knowledge_why'", self.sql)
        self.assertIn("'OWNER'", self.sql)
        self.assertRegex(self.sql, r"'OWNER', 1, false, false")

    def test_the_command_declares_no_binding(self):
        """§8.2 bindings fix parameters on ONE capability; #why composes two,
        so claiming a binding would describe the wrong relationship.

        Checked against the comment-stripped SQL: the migration EXPLAINS in
        prose why it sets no binds_to, and a raw-text search finds that
        explanation and reports the opposite of the truth.
        """
        self.assertNotIn("binds_to", self.code)

    def test_no_phone_number_is_hardcoded_for_authorization(self):
        import re
        self.assertIsNone(re.search(r"\b\d{10,15}\b", self.sql))

    def test_it_declares_all_four_required_capability_fields(self):
        for field in ("freshness", "provenance_tiers", "degradation",
                      "explainability"):
            self.assertIn(field, self.sql)

    def test_degradation_is_not_unspecified(self):
        self.assertNotIn("'unspecified'", self.sql)

    def test_it_creates_and_drops_nothing(self):
        import re
        self.assertIsNone(re.search(
            r"(?im)^\s*(create|drop|alter|delete|truncate|grant|revoke)\b",
            self.code))
        # Two INSERTs: the capability descriptor and the #why command row.
        self.assertEqual(len(re.findall(r"(?im)^\s*insert\s+into", self.code)), 2)

    def test_it_touches_no_fact_table(self):
        lowered = self.sql.lower()
        for table in ("bic_claims", "bic_parties", "bic_party_identifiers",
                      "bic_decision_records", "bic_facts", "bic_concepts"):
            self.assertNotIn(table, lowered)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class OpaqueIdentifiersDoNotAuthoriseTheirDigits(Base):
    """Regression: a claim_id's hex digits must not become allowed numbers.

    Found when a `#why` test failed only on the runs where a randomly
    generated claim_id happened to contain a bare "7" — which silently
    licensed a narration asserting "There are 7 open projects", an invented
    business fact admitted on the strength of a random hex digit. The
    flakiness was the symptom; the hole was real.
    """

    def _with_claim_id(self, claim_id):
        env = copy.deepcopy(FULL)
        env["values"][0]["claim_id"] = claim_id
        return x.explain(env)

    def test_uuid_digits_are_not_allowed_tokens(self):
        out = self._with_claim_id("6bcbb44f-7f67-48db-855b-6eae46d448d8")
        allowed = x.allowed_tokens(out)
        self.assertIn("6bcbb44f-7f67-48db-855b-6eae46d448d8", allowed)
        for fragment in ("7", "44", "67", "855", "448"):
            self.assertNotIn(fragment, allowed,
                             f"uuid fragment {fragment!r} leaked into the "
                             f"allowed set")

    def test_a_narration_cannot_borrow_a_number_from_a_uuid(self):
        out = self._with_claim_id("6bcbb44f-7f67-48db-855b-6eae46d448d8")
        self.assertEqual(x.validate_narration("There are 7 open projects.", out),
                         x.REJ_UNSUPPORTED_NUMBER)

    def test_the_whole_claim_id_may_still_be_quoted(self):
        out = self._with_claim_id("6bcbb44f-7f67-48db-855b-6eae46d448d8")
        self.assertIsNone(x.validate_narration(
            "Evidence 6bcbb44f-7f67-48db-855b-6eae46d448d8 supports this.", out))

    def test_timestamp_components_are_still_allowed(self):
        """A timestamp's parts are meaningful; a uuid's are not."""
        out = self.explain()
        allowed = x.allowed_tokens(out)
        for part in ("2026", "08", "18"):
            self.assertIn(part, allowed)

    def test_knowledge_ids_are_opaque_too(self):
        env = copy.deepcopy(FULL)
        env["subject"] = "9f9f9f9f-9999-4999-8999-9f9f9f9f9f9f"
        out = x.explain(env)
        self.assertNotIn("9999", x.allowed_tokens(out))
