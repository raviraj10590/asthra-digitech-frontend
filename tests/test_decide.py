"""bic/decide.py — the first real Brain decision loop (IDD-3A stage ⑨).

Unit tests only, against REAL packets from the real bic.context engine and
the REAL registered goal (bic.goals.lookup("social_media_enquiry")) — not a
locally re-declared copy. This module is pure: no db, no network, no AI
provider. Offline by construction.
"""

import ast
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import context as cx                                    # noqa: E402
from bic import decide                                            # noqa: E402
from bic import goals                                             # noqa: E402
from bic import policy                                            # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
SUBJECT = "805d1c4e-0000-4000-8000-000000000001"

INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"

GOAL = goals.lookup("social_media_enquiry")

DECIDE_MODULE = os.path.join(os.path.dirname(__file__), "..", "bic", "decide.py")


def code_only(path) -> str:
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


def client():
    return policy.Principal("919999000777", "CLIENT", TENANT)


def owner():
    return policy.Principal("910000000001", "OWNER", TENANT)


def fact(predicate, value, tier, cap, conf, volatility, verdict, ref, observed):
    return {"predicate": predicate, "label": predicate, "value": value,
            "unit": None, "cardinality": "single", "semantic_version": 1,
            "status": "ACTIVE", "confidence": conf,
            "provenance": {"tier": tier, "cap": cap, "source": "whatsapp",
                           "source_kind": "wa_msg",
                           "asserted_by": "whatsapp:first_contact"},
            "valid_from": observed, "valid_until": None, "observed_at": observed,
            "freshness": {"verdict": verdict, "volatility_class": volatility,
                          "bound_seconds": None, "age_seconds": 100,
                          "observed_at": observed},
            "claim_id": ref}


F_FIRST_SEEN = fact(FIRST_SEEN, "2026-08-18T16:07:48+00:00", 1, 0.90, 0.90,
                    "static", "FRESH", "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                    "2026-08-18T16:07:48+00:00")
F_INTEREST = fact(INTEREST, "Design & Branding", 5, 0.50, 0.50, "slow", "FRESH",
                  "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
                  "2026-08-18T16:08:15+00:00")


def envelope(values, *, state="KNOWN", absent=()):
    return {
        "capability": "knowledge.describe", "state": state, "reason": None,
        "entity": SUBJECT, "subject": SUBJECT,
        "identity": {"kind": "PERSON", "resolution_state": "PROVISIONAL"},
        "values": list(values), "conflicts": [],
        "coverage": {"requested": None, "consulted": [INTEREST, FIRST_SEEN],
                     "known": [v["predicate"] for v in values],
                     "absent": list(absent), "unavailable": [], "unregistered": []},
        "freshness": {"verdict": "FRESH", "stale_predicates": [],
                      "oldest_observed_at": "2026-08-18T16:07:48+00:00"},
        "confidence": {"value_confidence": 0.50, "provenance_ceiling": 0.50,
                       "coverage_ratio": 1.0, "identity_state": "PROVISIONAL"},
        "degraded": False, "degradation": [], "trace_ref": None,
        "asked_at": None, "evaluated_at": None, "as_of": None, "as_known_at": None,
    }


def describer(env):
    def _d(tenant_id, subject, predicates=None, as_of=None):
        return env
    return _d


def packet(env=None, goal_def=None, principal=None, subject=SUBJECT, tenant=TENANT):
    return cx.assemble(tenant, "hello", principal or client(), goal_def or GOAL,
                       subject,
                       describe=describer(env if env is not None else
                                         envelope([F_INTEREST, F_FIRST_SEEN])))


# ── 2. GOAL ──────────────────────────────────────────────────────────────

class GoalRecognition(unittest.TestCase):

    def test_the_real_goal_is_recognized(self):
        g = decide.recognize_goal()
        self.assertIsNotNone(g)
        self.assertEqual(g["goal_id"], "social_media_enquiry")

    def test_unknown_goal_returns_none_never_a_guess(self):
        self.assertIsNone(decide.recognize_goal("not_a_real_goal"))

    def test_admits_the_supported_goal_on_real_service_vocabulary(self):
        for text in ("I want social media management",
                     "do you handle instagram?",
                     "facebook page ads please",
                     "ಸೋಶಿಯಲ್ ಮೀಡಿಯಾ ಬೇಕು"):
            with self.subTest(text=text):
                g = decide.admit_goal(text)
                self.assertIsNotNone(g, text)
                self.assertEqual(g["goal_id"], "social_media_enquiry")

    def test_unsupported_request_is_not_admitted(self):
        """UNSUPPORTED is not a refusal — it means this slice doesn't cover
        the request and the caller keeps its existing behaviour."""
        for text in ("what is your price?", "hello", "I need a website",
                     "", "   "):
            with self.subTest(text=text):
                self.assertIsNone(decide.admit_goal(text))

    def test_markers_match_on_word_boundaries_not_substrings(self):
        """AUDIT REGRESSION. A bare `in` test made "insta" match "install",
        "instant" and "instantly", admitting the goal for messages that are
        not enquiries — breaking "activates only where the goal is reliably
        identified" by accident."""
        for text in ("please install the app", "I need it instantly",
                     "instant reply needed", "is this instant?",
                     "constant contact"):
            with self.subTest(text=text):
                self.assertIsNone(decide.admit_goal(text), text)

    def test_the_colloquial_abbreviation_still_admits(self):
        """The boundary fix must not cost the real short form."""
        self.assertIsNotNone(decide.admit_goal("do you do insta?"))
        self.assertIsNotNone(decide.admit_goal("insta and fb please"
                                               .replace("fb", "facebook")))

    def test_high_risk_goals_are_unreachable_from_text(self):
        """A customer's wording must never select transformer/real-estate —
        their predicates are unregistered and their tiers are 4 and 2."""
        for text in ("transformer quotation 500 kva urgent",
                     "real estate plot budget 50 lakh in whitefield"):
            with self.subTest(text=text):
                self.assertIsNone(decide.admit_goal(text))

    def test_admitted_goal_is_the_lowest_risk_tier(self):
        """Tier 1 is what makes a false-positive admission safe: it can only
        ever admit the least demanding goal, never escalate a turn."""
        self.assertEqual(decide.admit_goal("instagram")["risk_tier"], 1)

    def test_admission_is_deterministic(self):
        text = "social media help"
        self.assertEqual([decide.admit_goal(text)["goal_id"] for _ in range(5)],
                         ["social_media_enquiry"] * 5)

    def test_admission_uses_no_model(self):
        code = code_only(DECIDE_MODULE).lower()
        for banned in ("generate_reply", "openai", "gemini", "classify"):
            self.assertNotIn(banned, code)

    def test_no_new_predicates_or_verticals_were_added(self):
        """No new VERTICAL. The decide slice must not grow industry
        vocabulary — no second transformer/real-estate goal, no new predicate.

        `business_month_review` is not a vertical: it is BUSINESS-scoped
        (about Asthra itself, not a counterparty) and reuses the already
        registered biz.pipeline predicate. DECIDE never reaches it — the
        assertion below in test_decide_is_party_scoped proves decide's own
        goal is still PARTY-scoped.
        """
        self.assertEqual(sorted(goals.known_ids()),
                         ["business_focus_recommendation",
                          "business_month_review", "real_estate_enquiry",
                          "social_media_enquiry", "transformer_quotation"])
        for gid in ("real_estate_enquiry", "social_media_enquiry",
                    "transformer_quotation"):
            self.assertEqual(goals.lookup(gid)["scope"], cx.PARTY)


# ── 3. CONTEXT ───────────────────────────────────────────────────────────

class ContextIntegration(unittest.TestCase):

    def test_assemble_context_delegates_to_the_real_engine(self):
        p = decide.assemble_context(TENANT, "hello", client(), GOAL, SUBJECT,
                                    describe=describer(envelope([F_INTEREST, F_FIRST_SEEN])))
        self.assertEqual(p["goal_ref"], "social_media_enquiry")
        self.assertEqual(p["tenant_id"], TENANT)
        self.assertIn("sufficiency", p["epistemic"])

    def test_packet_carries_the_correct_subject(self):
        p = packet()
        self.assertEqual(p["subject"], SUBJECT)

    def test_packet_carries_provenance_confidence_and_freshness(self):
        p = packet()
        facts = p["evidence"]["facts"]
        self.assertTrue(facts)
        for f in facts:
            self.assertIn("tier", f["provenance"])
            self.assertIsNotNone(f["confidence"])
            self.assertIsNotNone(f["freshness"]["verdict"])

    def test_packet_carries_boundaries_and_epistemic_state(self):
        p = packet()
        for section in ("boundaries", "epistemic", "evidence", "question",
                        "principal"):
            self.assertIn(section, p)
        for key in ("conflicts", "missing", "coverage", "sufficiency"):
            self.assertIn(key, p["epistemic"])

    def test_packet_leaks_no_pii(self):
        """The packet is stored, replayed and explained — a raw identifier
        here would outlive the turn in all three."""
        blob = repr(packet(principal=client()))
        self.assertNotIn("919555555555", blob)
        self.assertNotIn("919999000777", blob)   # the client's own sender_id
        self.assertIsNone(re.search(r"\b91\d{10}\b", blob))
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", blob))
        self.assertNotIn("wamid", blob)

    def test_does_not_duplicate_the_context_engine(self):
        """decide.py must not reimplement sufficiency logic — it can only
        read what bic.context already computed."""
        code = code_only(DECIDE_MODULE)
        for banned in ("RISK_CONFIDENCE_FLOOR", "_detect_missing", "_assess"):
            self.assertNotIn(banned, code)


# ── 4-6. SUFFICIENCY → DECIDE outcomes ──────────────────────────────────

class DecideOutcomes(unittest.TestCase):

    def test_proceed_sends_the_llm_proposal(self):
        p = packet()  # both slots filled — PROCEED
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)
        r = decide.decide(GOAL, p, "here is a real, useful reply")
        self.assertEqual(r["outcome"], decide.PROCEED)
        self.assertEqual(r["text"], "here is a real, useful reply")

    def test_clarify_when_a_fact_is_missing(self):
        # service_interest is OBTAINABLE_BY_ASKING — its absence is CLARIFY.
        p = packet(envelope([F_FIRST_SEEN], absent=[INTEREST]))
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.CLARIFY)
        r = decide.decide(GOAL, p, "anything the model said")
        self.assertEqual(r["outcome"], decide.CLARIFY)
        self.assertIn("service_interest", r["text"])

    def test_retrieve_maps_to_refuse_not_a_guess(self):
        """first_contact is OBTAINABLE_BY_RETRIEVAL — the SYSTEM should have
        fetched it, not the customer. No automated retrieval is wired in
        this slice, so the documented, conservative choice is REFUSE rather
        than asking the customer for something that isn't theirs to supply."""
        p = packet(envelope([F_INTEREST], absent=[FIRST_SEEN]))
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.RETRIEVE)
        r = decide.decide(GOAL, p, "anything the model said")
        self.assertEqual(r["outcome"], decide.REFUSE)

    def test_refuse_when_authorization_is_denied_at_context_assembly(self):
        """A denied context assembly (principal lacks authority) surfaces as
        REFUSE at the sufficiency layer already — decide() must honour it."""
        p = cx.assemble(TENANT, "hello", client(), GOAL, SUBJECT,
                        describe=describer(envelope([F_INTEREST, F_FIRST_SEEN])),
                        descriptor={"code": "knowledge.describe",
                                   "min_role": "OWNER", "customer_safe": False,
                                   "risk_tier": 1, "active": True})
        self.assertEqual(p["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)
        r = decide.decide(GOAL, p, "anything the model said")
        self.assertEqual(r["outcome"], decide.REFUSE)
        self.assertEqual(r["text"], decide.REFUSAL_TEXT)


# ── 8-9, 14. LLM proposal cannot bypass or determine DECIDE ─────────────

class ProposalCannotBypassDecide(unittest.TestCase):

    def test_clarify_ignores_the_llm_proposal_text_entirely(self):
        """Even if the LLM's proposal reads as a confident, complete answer,
        a CLARIFY verdict must still ask for the missing fact — proving the
        proposal never determines the outcome."""
        p = packet(envelope([F_FIRST_SEEN], absent=[INTEREST]))
        confident_but_wrong = "Yes, absolutely, I can confirm that for you!"
        r = decide.decide(GOAL, p, confident_but_wrong)
        self.assertEqual(r["outcome"], decide.CLARIFY)
        self.assertNotIn(confident_but_wrong, r["text"])

    def test_refuse_ignores_the_llm_proposal_text_entirely(self):
        p = cx.assemble(TENANT, "hello", client(), GOAL, SUBJECT,
                        describe=describer(envelope([F_INTEREST, F_FIRST_SEEN])),
                        descriptor={"code": "knowledge.describe",
                                   "min_role": "OWNER", "customer_safe": False,
                                   "risk_tier": 1, "active": True})
        confident_but_wrong = "Sure! Here is exactly what you asked for."
        r = decide.decide(GOAL, p, confident_but_wrong)
        self.assertEqual(r["outcome"], decide.REFUSE)
        self.assertNotIn(confident_but_wrong, r["text"])

    def test_proceed_with_no_proposal_refuses_rather_than_inventing_one(self):
        p = packet()
        r = decide.decide(GOAL, p, "")
        self.assertEqual(r["outcome"], decide.REFUSE)

    def test_clarify_names_only_the_missing_slot_never_a_fabricated_value(self):
        """No hallucinated missing fact: the CLARIFY text must name the SLOT,
        and must not contain any of the (unrelated) values from other real
        facts, which would look like an invented answer."""
        p = packet(envelope([F_FIRST_SEEN], absent=[INTEREST]))
        r = decide.decide(GOAL, p, "irrelevant")
        self.assertNotIn("2026-08-18", r["text"])           # a real fact VALUE
        self.assertIn("service_interest", r["text"])         # the slot NAME


# ── 10, 16. AUTHORIZE ────────────────────────────────────────────────────

class Authorization(unittest.TestCase):

    def test_client_role_is_authorized_for_its_own_tier_1_goal(self):
        p = packet(principal=client())
        r = decide.authorize(client(), p, GOAL, TENANT)
        self.assertTrue(r["allowed"])

    def test_owner_role_is_not_a_customer_facing_principal(self):
        p = packet(principal=owner())
        r = decide.authorize(owner(), p, GOAL, TENANT)
        self.assertFalse(r["allowed"])

    def test_tenant_mismatch_denied(self):
        p = packet()
        r = decide.authorize(client(), p, GOAL, OTHER_TENANT)
        self.assertFalse(r["allowed"])
        self.assertIn("tenant", r["reason"])

    def test_goal_mismatch_denied(self):
        p = packet()
        other_goal = dict(GOAL, goal_id="a_different_goal")
        r = decide.authorize(client(), p, other_goal, TENANT)
        self.assertFalse(r["allowed"])
        self.assertIn("goal", r["reason"])


# ── 15. Security / PII ───────────────────────────────────────────────────

class SecurityAndBoundaries(unittest.TestCase):

    def test_no_pii_vocabulary_in_decide_module(self):
        code = code_only(DECIDE_MODULE).lower()
        for banned in ("phone", "email", "wamid", "sender", "message_body"):
            self.assertNotIn(banned, code)

    def test_no_ai_or_provider_dependency(self):
        code = code_only(DECIDE_MODULE).lower()
        for banned in ("openai", "gemini", "deepseek", "requests", "http"):
            self.assertNotIn(banned, code)

    def test_never_touches_claims_party_or_storage(self):
        code = code_only(DECIDE_MODULE)
        for banned in ("bic_claims", "insert(", "select(", "db.", "party."):
            self.assertNotIn(banned, code)
