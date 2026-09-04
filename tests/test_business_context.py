"""BUSINESS-scoped 2H context — the Brain asking about Asthra, not a customer.

WHAT THIS SLICE IS
------------------
2H context assembly has always been PARTY-scoped: `subject` is an opaque
knowledge_id and the packet never said what KIND of thing it referred to.
That works for "why is this customer's engagement low?" and is wrong for
"what should I focus on this month?" — which is about the business itself.
Forcing the second into the first means inventing a fake party for Asthra.

THE MINIMUM EXTENSION, AND WHAT IT DELIBERATELY IS NOT
-------------------------------------------------------
Added: a declared `scope` on the goal and on the packet, and enforcement
that a predicate may only be retrieved for a subject kind the 2A registry
says it applies to. NOT added: OWNER DECIDE, planning, autonomy, or any
recommendation. assemble_business_context() assembles and assesses; it
answers nothing.

WHY THE COMPATIBILITY RULE IS THE REGISTRY'S OWN
-------------------------------------------------
2A already records `applies_to` per concept and knowledge._concepts_for
already honours it — but ONLY when it consults the whole vocabulary. When
the caller names predicates explicitly, which is every call assembly makes,
applies_to is not checked at all. So today a business goal naming a
PERSON-only predicate would retrieve it silently. These tests pin the fix.

Offline: no network, no AI, no database. The end-to-end classes drive the
REAL bic.context / bic.knowledge / bic.claims / bic.registry stack against
an in-memory store, so this proves the actual read path, not a mock of it.
"""

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bic import claims as c, context as cx, goals as gl        # noqa: E402
from bic import knowledge, party as p, policy, registry as r   # noqa: E402
from bic import pipeline_evidence as pe                        # noqa: E402
from tests.test_claims import ClaimsDb                         # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
ORG_A = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"
ORG_B = "6d8d3067-0c9d-41c9-8e88-29ff8644783b"
PERSON = "805d1c4e-0000-4000-8000-000000000001"

BIZ = gl.NEW_ENQUIRIES
INTEREST = gl.INTEREST


def owner(tenant=TENANT):
    return policy.Principal("910000000001", "OWNER", tenant)


# ══════════════════════════════════════════════════════════════════════════
# 1 · The contract, in isolation
# ══════════════════════════════════════════════════════════════════════════

class ScopeContract(unittest.TestCase):

    def test_scope_vocabulary_is_closed(self):
        self.assertEqual(cx.SCOPES, ("PARTY", "BUSINESS"))

    def test_goal_defaults_to_party_so_existing_goals_are_unchanged(self):
        g = cx.goal("g", 1, [cx.slot("s", INTEREST)])
        self.assertEqual(g["scope"], cx.PARTY)

    def test_every_pre_existing_goal_is_party_scoped(self):
        """The regression that matters most: adding BUSINESS must not have
        silently re-scoped a customer goal."""
        for gid in ("social_media_enquiry", "real_estate_enquiry",
                    "transformer_quotation"):
            self.assertEqual(gl.lookup(gid)["scope"], cx.PARTY, gid)

    def test_the_business_goal_declares_business_scope(self):
        self.assertEqual(gl.lookup("business_month_review")["scope"],
                         cx.BUSINESS)

    def test_an_unknown_scope_is_rejected_at_goal_definition(self):
        with self.assertRaises(cx.ContextError):
            cx.goal("g", 1, [], scope="TENANT")

    def test_packet_declares_its_scope(self):
        """A stored, replayed packet must say whose context it was — an
        opaque subject id alone cannot distinguish a customer from the
        business, and the two support different decisions."""
        g = cx.goal("g", 1, [cx.slot("s", INTEREST)])
        pk = cx.assemble(TENANT, "hi", owner(), g, PERSON)
        self.assertEqual(pk["scope"], cx.PARTY)

    def test_business_scope_without_the_resolver_raises(self):
        """Failing loudly beats silently skipping the check — a skipped
        check is exactly how a party predicate becomes business-scoped."""
        g = gl.lookup("business_month_review")
        with self.assertRaises(cx.ContextError):
            cx.assemble(TENANT, "hi", owner(), g, ORG_A)


# ══════════════════════════════════════════════════════════════════════════
# 2 · Evidence selection — the applies_to rule
# ══════════════════════════════════════════════════════════════════════════

def applies(mapping):
    """A stand-in registry.applies_to_ref. Injected, never imported."""
    return lambda ref: mapping.get(ref)


class EvidenceSelection(unittest.TestCase):

    BIZ_ONLY = {BIZ: ["ORGANIZATION"], INTEREST: ["PERSON", "ORGANIZATION"]}

    def build(self, slots, mapping=None, scope=cx.BUSINESS, describe=None):
        g = cx.goal("g", 2, slots, scope=scope)
        return cx.assemble(TENANT, "hi", owner(), g, ORG_A,
                           describe=describe,
                           applies_to=applies(mapping or self.BIZ_ONLY))

    def test_a_business_predicate_is_planned(self):
        pk = self.build([cx.slot("n", BIZ, cx.OBTAINABLE_BY_RETRIEVAL)])
        self.assertIn(BIZ, pk["epistemic"]["coverage"]["planned"])
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [])

    def test_a_person_only_predicate_is_excluded_from_business_scope(self):
        """The core rule: a party-scoped predicate must NOT silently become
        business-scoped."""
        person_only = {BIZ: ["ORGANIZATION"], INTEREST: ["PERSON"]}
        pk = self.build([cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                        mapping=person_only)
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [INTEREST])
        self.assertNotIn(INTEREST, pk["epistemic"]["coverage"]["planned"])

    def test_an_excluded_predicate_is_never_requested_not_merely_discarded(self):
        """§3.2's rule for authority applied to scope: filtering AFTER
        retrieval means the data was fetched, and a filter is one bug away
        from being bypassed."""
        asked = []

        def spy(tenant_id, subject, predicates=None, as_of=None):
            asked.append(list(predicates or []))
            return None
        person_only = {BIZ: ["ORGANIZATION"], INTEREST: ["PERSON"]}
        self.build([cx.slot("n", BIZ, cx.OBTAINABLE_BY_RETRIEVAL),
                    cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                   mapping=person_only, describe=spy)
        self.assertEqual(asked, [[BIZ]])

    def test_a_predicate_applying_to_both_kinds_is_allowed(self):
        """applies_to ['PERSON','ORGANIZATION'] genuinely covers the business
        org party — this must not over-reject."""
        pk = self.build([cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [])

    def test_an_empty_applies_to_means_anything(self):
        """Matches knowledge._concepts_for's own reading, rather than
        inventing a stricter rule in a second place."""
        pk = self.build([cx.slot("x", "z.z.z@1", cx.OBTAINABLE_BY_RETRIEVAL)],
                        mapping={"z.z.z@1": []})
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [])

    def test_party_scope_does_not_filter(self):
        """A PARTY subject may be a PERSON or an ORGANIZATION and assembly
        cannot know which without a lookup it must not perform. Filtering on
        a guess would reject legitimate organization-counterparty goals."""
        person_only = {INTEREST: ["PERSON"]}
        pk = self.build([cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                        mapping=person_only, scope=cx.PARTY)
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [])

    def test_out_of_scope_produces_unknowable_not_a_question(self):
        """Asking the owner for a customer's declared interest when the
        question was about the business is a nonsense question, so the gate
        must not classify this OBTAINABLE_BY_ASKING."""
        person_only = {INTEREST: ["PERSON"]}
        pk = self.build([cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                        mapping=person_only)
        gap = [m for m in pk["epistemic"]["missing"]
               if m["predicate"] == INTEREST][0]
        self.assertEqual(gap["class"], cx.UNKNOWABLE)
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)

    def test_exclusion_is_recorded_as_degradation(self):
        person_only = {INTEREST: ["PERSON"]}
        pk = self.build([cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                        mapping=person_only)
        reasons = {d["reason"] for d in pk["epistemic"]["degradation"]}
        self.assertIn("out_of_scope", reasons)


# ══════════════════════════════════════════════════════════════════════════
# 3 · End to end against the REAL knowledge/claims/registry stack
# ══════════════════════════════════════════════════════════════════════════

class RealStack(unittest.TestCase):
    """Same in-memory Harness pattern test_first_seen_at.py established."""

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for k, v in params.items():
                    if k in ("order", "limit"):
                        continue
                    v = str(v)
                    if v == "is.null" and row.get(k) is not None:
                        keep = False
                    elif v.startswith("eq.") and str(row.get(k)) != v[3:]:
                        keep = False
                if keep:
                    out.append(dict(row))
            return out

        self._p = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
        ]
        for x in self._p:
            x.start()

        r.register("biz.pipeline", "new_enquiries_per_month", 1, "QUANTITATIVE",
                   {"type": "number", "min": 0},
                   "New enquiries per month (Brain-known)", unit="count",
                   cardinality="single", volatility_class="fast",
                   applies_to=["ORGANIZATION"])
        r.activate("biz.pipeline", "new_enquiries_per_month", 1, "raviraj")
        # applies_to PERSON only — deliberately narrower than production,
        # where it is ['PERSON','ORGANIZATION']. This fixture exists to prove
        # the EXCLUSION path works against the real registry; production's
        # wider value is asserted separately in ProductionRegistryShape below.
        r.register("core.party", "declared_service_interest", 1, "CLASSIFYING",
                   {"type": "enum", "values": ["Website / App"]},
                   "Declared service interest",
                   cardinality="single", volatility_class="slow",
                   applies_to=["PERSON"])
        r.activate("core.party", "declared_service_interest", 1, "raviraj")

        for tenant, org in ((TENANT, ORG_A), (OTHER_TENANT, ORG_B)):
            self.parties.append({"tenant_id": tenant, "knowledge_id": org,
                                 "kind": "ORGANIZATION",
                                 "resolution_state": "PROVISIONAL",
                                 "merged_into": None})
            self.identifiers.append({"tenant_id": tenant, "party_id": org,
                                     "channel": pe.SELF_CHANNEL,
                                     "identifier_value": tenant,
                                     "identifier_class": "CONTACT",
                                     "valid_until": None})

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def claim(self, value, when, tenant=TENANT, subject=ORG_A,
              predicate=BIZ, until=None):
        c.assert_claim(tenant, subject, predicate, value,
                       source=pe.SOURCE, provenance_tier=pe.PROVENANCE_TIER,
                       asserted_by=pe.ASSERTED_BY, valid_from=when,
                       valid_until=until or when + timedelta(days=20),
                       observed_at=when)

    def build(self, tenant=TENANT, subject=ORG_A, as_of=None, goal_def=None):
        return cx.assemble(
            tenant, "what should I focus on this month?", owner(tenant),
            goal_def or gl.lookup("business_month_review"), subject,
            describe=knowledge.describe, applies_to=r.applies_to_ref,
            as_of=as_of)

    # ── assembly ───────────────────────────────────────────────────────
    def test_business_context_assembles_with_real_evidence(self):
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1))
        pk = self.build()
        self.assertEqual(pk["scope"], cx.BUSINESS)
        self.assertEqual(pk["subject"], ORG_A)
        fact = [f for f in pk["evidence"]["facts"] if f["predicate"] == BIZ][0]
        # bic_claims.value is text — the store round-trips 9 as "9". Asserted
        # as the store actually returns it rather than as the int that was
        # written, so this test describes the real contract a renderer sees.
        self.assertEqual(str(fact["value"]), "9")
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    def test_the_value_is_read_not_hardcoded(self):
        """Guards against an implementation that assumes today's figure."""
        now = datetime.now(timezone.utc)
        self.claim(41, now - timedelta(hours=1))
        pk = self.build()
        fact = [f for f in pk["evidence"]["facts"] if f["predicate"] == BIZ][0]
        self.assertEqual(str(fact["value"]), "41")

    # ── freshness ──────────────────────────────────────────────────────
    def test_a_stale_business_claim_stays_stale(self):
        now = datetime.now(timezone.utc)
        self.claim(7, now - timedelta(hours=30), until=now + timedelta(days=5))
        pk = self.build()
        fact = [f for f in pk["evidence"]["facts"] if f["predicate"] == BIZ][0]
        self.assertEqual(fact["freshness"]["verdict"], "STALE")

    def test_provenance_and_confidence_survive_assembly(self):
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1))
        pk = self.build()
        fact = [f for f in pk["evidence"]["facts"] if f["predicate"] == BIZ][0]
        self.assertEqual(fact["provenance"]["tier"], 3)
        self.assertEqual(fact["confidence"], 0.70)

    # ── conflict ───────────────────────────────────────────────────────
    def test_conflicting_business_claims_are_not_collapsed(self):
        """Two live values on a `single` predicate is a contradiction the
        gate must surface, never average or pick between."""
        now = datetime.now(timezone.utc)
        same = now - timedelta(hours=1)
        self.claim(9, same)
        self.claim(3, same)          # identical valid_from → neither supersedes
        pk = self.build()
        self.assertTrue(pk["epistemic"]["conflicts"])
        self.assertNotEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.PROCEED)

    # ── absence ────────────────────────────────────────────────────────
    def test_missing_business_evidence_produces_structured_insufficiency(self):
        pk = self.build()
        self.assertEqual(pk["evidence"]["facts"], [])
        gap = [m for m in pk["epistemic"]["missing"]
               if m["predicate"] == BIZ][0]
        self.assertEqual(gap["class"], cx.OBTAINABLE_BY_RETRIEVAL)
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.RETRIEVE)

    # ── tenant isolation ───────────────────────────────────────────────
    def test_tenant_a_never_sees_tenant_b_business_evidence(self):
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1), tenant=TENANT, subject=ORG_A)
        self.claim(77, now - timedelta(hours=1),
                   tenant=OTHER_TENANT, subject=ORG_B)
        a = self.build(tenant=TENANT, subject=ORG_A)
        values = [str(f["value"]) for f in a["evidence"]["facts"]]
        self.assertEqual(values, ["9"])
        self.assertNotIn("77", values)

    def test_tenant_b_sees_only_its_own(self):
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1), tenant=TENANT, subject=ORG_A)
        self.claim(77, now - timedelta(hours=1),
                   tenant=OTHER_TENANT, subject=ORG_B)
        b = self.build(tenant=OTHER_TENANT, subject=ORG_B)
        self.assertEqual([str(f["value"]) for f in b["evidence"]["facts"]],
                         ["77"])

    def test_a_tenants_own_subject_yields_nothing_under_another_tenant(self):
        """Cross-tenant read with the RIGHT subject but the WRONG tenant must
        return nothing rather than leaking the claim."""
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1), tenant=TENANT, subject=ORG_A)
        pk = self.build(tenant=OTHER_TENANT, subject=ORG_A)
        self.assertEqual(pk["evidence"]["facts"], [])

    def test_claims_are_tenant_filtered_even_for_an_identical_subject_id(self):
        """The claims-layer tenant filter, exercised DIRECTLY.

        The three tests above pass through party resolution: a foreign
        tenant's subject fails party lookup and describe returns UNKNOWN
        before claims are ever read. That is real defence, but it means they
        do NOT prove the tenant predicate on the claims query — verified by
        mutation: deleting `tenant_id` from both claim reads left all three
        green. This binds the SAME knowledge_id under both tenants so party
        lookup succeeds either way and only the claims filter can separate
        them.
        """
        shared = "7f7f7f7f-8888-4888-8888-999999999999"
        for tenant in (TENANT, OTHER_TENANT):
            self.parties.append({"tenant_id": tenant, "knowledge_id": shared,
                                 "kind": "ORGANIZATION",
                                 "resolution_state": "PROVISIONAL",
                                 "merged_into": None})
        now = datetime.now(timezone.utc)
        self.claim(11, now - timedelta(hours=1), tenant=TENANT, subject=shared)
        self.claim(22, now - timedelta(hours=1),
                   tenant=OTHER_TENANT, subject=shared)

        a = self.build(tenant=TENANT, subject=shared)
        b = self.build(tenant=OTHER_TENANT, subject=shared)
        self.assertEqual([str(f["value"]) for f in a["evidence"]["facts"]], ["11"])
        self.assertEqual([str(f["value"]) for f in b["evidence"]["facts"]], ["22"])

    def test_business_subject_resolution_is_tenant_scoped(self):
        self.assertEqual(pe.find_business_subject(TENANT), ORG_A)
        self.assertEqual(pe.find_business_subject(OTHER_TENANT), ORG_B)

    def test_find_business_subject_never_creates_a_party(self):
        """A question must not have identity side effects."""
        before = len(self.parties)
        self.assertIsNone(pe.find_business_subject(
            "11111111-2222-4333-8444-555555555555"))
        self.assertEqual(len(self.parties), before)

    # ── party evidence must not leak in ─────────────────────────────────
    def test_a_person_only_predicate_cannot_enter_business_context(self):
        """Against the REAL registry: declared_service_interest is
        applies_to ['PERSON'] here, so it is excluded and reported."""
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1))
        g = cx.goal("mixed", 2,
                    [cx.slot("n", BIZ, cx.OBTAINABLE_BY_RETRIEVAL),
                     cx.slot("i", INTEREST, cx.OBTAINABLE_BY_ASKING)],
                    scope=cx.BUSINESS)
        pk = self.build(goal_def=g)
        self.assertEqual(pk["epistemic"]["coverage"]["out_of_scope"], [INTEREST])
        self.assertNotIn(INTEREST,
                         [f["predicate"] for f in pk["evidence"]["facts"]])


# ══════════════════════════════════════════════════════════════════════════
# 4 · Scope is goal DATA, never inferred from the message text
# ══════════════════════════════════════════════════════════════════════════

class ScopeIsNotInferredFromText(unittest.TestCase):
    """Phase 9/10: no bare keyword routing, no second classifier.

    Scope comes from the named goal. That is the same protection goals.py
    already documents for goal selection itself — "inferring it from free
    text would let a customer's phrasing lower the evidence bar".
    """

    def test_the_same_text_cannot_change_scope(self):
        g = gl.lookup("business_month_review")
        for text in ("what should I focus on this month?",
                     "why is Ravi's engagement low?",
                     "how is this customer doing?"):
            pk = cx.assemble(TENANT, text, owner(), g, ORG_A,
                             applies_to=lambda ref: ["ORGANIZATION"])
            self.assertEqual(pk["scope"], cx.BUSINESS, text)

    def test_a_party_goal_stays_party_whatever_the_text(self):
        g = gl.lookup("social_media_enquiry")
        pk = cx.assemble(TENANT, "what should I focus on this month?",
                         owner(), g, PERSON)
        self.assertEqual(pk["scope"], cx.PARTY)

    def test_scope_determination_structurally_cannot_see_the_message(self):
        """STRUCTURAL, not a string scan.

        A substring scan for words like "text" is what a previous version of
        this test did, and it matched the identifier ContextError — the same
        false-positive class this repo has hit before. The real guarantee is
        stronger and exact: _out_of_scope's signature does not include the
        request, so no amount of future editing inside it can route on
        message content without changing the signature first.
        """
        import inspect
        params = list(inspect.signature(cx._out_of_scope).parameters)
        self.assertEqual(params, ["goal_def", "applies_to"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
# 5 · The production registry actually permits this
# ══════════════════════════════════════════════════════════════════════════

class ProductionRegistryShape(unittest.TestCase):
    """The migration that registered the predicate must keep it BUSINESS
    compatible. A future 2A edit narrowing applies_to would silently make
    the business goal unsatisfiable, and this is what would catch it."""

    def _sql(self, name):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", name)
        with open(path) as fh:
            return "\n".join(l for l in fh if not l.strip().startswith("--"))

    def test_the_business_predicate_applies_to_organization(self):
        sql = self._sql("20260827000020_bic_seed_new_enquiries_per_month.sql")
        self.assertIn("array['ORGANIZATION']::text[]", sql)

    def test_the_business_goal_names_the_registered_predicate(self):
        self.assertEqual(gl.NEW_ENQUIRIES,
                         "biz.pipeline.new_enquiries_per_month@1")
        slots = gl.lookup("business_month_review")["required_slots"]
        self.assertEqual([s["predicate"] for s in slots], [gl.NEW_ENQUIRIES])

    def test_the_business_goal_tier_is_satisfiable_by_its_own_evidence(self):
        """Tier 3 would demand confidence 0.80, above the 0.70 cap a tier-3
        derived fact can ever carry (2C §6) — the goal could never be
        satisfied however healthy the pipeline. Tier 2's floor is 0.60."""
        tier = gl.lookup("business_month_review")["risk_tier"]
        self.assertLessEqual(cx.RISK_CONFIDENCE_FLOOR[tier],
                             c.TIER_CAPS[pe.PROVENANCE_TIER])


# ══════════════════════════════════════════════════════════════════════════
# 6 · OWNER integration — assembles and assesses, decides NOTHING
# ══════════════════════════════════════════════════════════════════════════

class OwnerIntegration(unittest.TestCase):

    def setUp(self):
        import webhook as w
        self.w = w

    def test_it_returns_a_structured_reason_when_no_business_subject(self):
        """Genuine absence of evidence, reported as such — never resolved
        into a freshly minted party by asking a question."""
        with mock.patch.object(self.w, "BIC_AVAILABLE", True), \
             mock.patch.object(self.w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(self.w.bic_pipeline_evidence,
                               "find_business_subject", lambda t: None):
            packet, reason = self.w.assemble_business_context("focus?")
        self.assertIsNone(packet)
        self.assertEqual(reason, "no_business_subject")

    def test_an_unknown_goal_is_refused_not_defaulted(self):
        with mock.patch.object(self.w, "BIC_AVAILABLE", True), \
             mock.patch.object(self.w.bic_config, "is_configured", lambda: True):
            packet, reason = self.w.assemble_business_context(
                "focus?", goal_id="no_such_goal")
        self.assertIsNone(packet)
        self.assertEqual(reason, "unknown_goal")

    def test_a_store_failure_reports_the_type_only(self):
        """A DbError body can echo an identifier."""
        def boom(_t):
            raise RuntimeError("phone 910000000001 not found")
        with mock.patch.object(self.w, "BIC_AVAILABLE", True), \
             mock.patch.object(self.w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(self.w.bic_pipeline_evidence,
                               "find_business_subject", boom):
            packet, reason = self.w.assemble_business_context("focus?")
        self.assertIsNone(packet)
        self.assertNotIn("910000000001", reason)
        self.assertIn("RuntimeError", reason)

    def test_it_makes_no_model_call_and_no_recommendation(self):
        """STRUCTURAL: the function must not be able to reach a provider or
        emit advice. "What should I focus on" is answerable only by a DECIDE
        stage that does not exist yet."""
        import inspect
        src = inspect.getsource(self.w.assemble_business_context)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        code = code.split('"""')[-1]
        for banned in ("generate_owner_reply", "openai", "OpenAI", "deepseek",
                       "gemini", "recommend"):
            self.assertNotIn(banned, code)

    def test_it_uses_the_registry_resolver_not_a_second_rule(self):
        import inspect
        src = inspect.getsource(self.w.assemble_business_context)
        self.assertIn("applies_to=bic_registry.applies_to_ref", src)


# ══════════════════════════════════════════════════════════════════════════
# 7 · business_focus_recommendation — declares its evidence, recommends NOTHING
# ══════════════════════════════════════════════════════════════════════════

class FocusRecommendationGoal(unittest.TestCase):
    """The goal exists to say what a recommendation NEEDS, and to report
    honestly that the Brain does not have it. It must never produce advice.
    """

    GOAL = "business_focus_recommendation"

    def goal(self):
        return gl.lookup(self.GOAL)

    def test_the_goal_exists(self):
        self.assertIsNotNone(self.goal())

    def test_it_is_business_scoped(self):
        self.assertEqual(self.goal()["scope"], cx.BUSINESS)

    def test_risk_tier_is_two(self):
        self.assertEqual(self.goal()["risk_tier"], 2)

    def test_tier_is_satisfiable_by_derived_evidence(self):
        """Tier 3 would demand 0.80, above the 0.70 cap a tier-3 derived fact
        can ever carry (2C §6) — the goal could never be satisfied however
        complete the evidence became."""
        self.assertLessEqual(cx.RISK_CONFIDENCE_FLOOR[self.goal()["risk_tier"]],
                             c.TIER_CAPS[pe.PROVENANCE_TIER])

    def test_all_four_required_slots_are_declared(self):
        names = {s["name"] for s in self.goal()["required_slots"]}
        for required in ("conversion_rate", "pipeline_value",
                         "channel_attribution", "capacity"):
            self.assertIn(required, names)

    def test_the_known_enquiry_metric_is_also_declared(self):
        """Without it the packet would carry no evidence at all and the
        report would read as "we know nothing", which is false."""
        preds = [s["predicate"] for s in self.goal()["required_slots"]]
        self.assertIn(gl.NEW_ENQUIRIES, preds)

    def test_the_four_predicates_are_deliberately_unregistered(self):
        """Naming a predicate does not create it — 2A registration is a
        separate, deliberate act that freezes a meaning forever. This pins
        that none of the four was smuggled into a migration.

        PRECISE, not a substring scan: it looks only inside `insert into
        bic_concepts` statements and requires the namespace and concept to
        appear as an adjacent registered pair. A bare scan for the concept
        name matched the word "value" inside unrelated tool-registry prose —
        the same false-positive class this repo has hit before, which is also
        why PIPELINE_VALUE is `open_value` rather than the generic `value`.
        """
        mig = os.path.join(os.path.dirname(__file__), "..", "supabase",
                           "migrations")
        registered = set()
        for name in sorted(os.listdir(mig)):
            with open(os.path.join(mig, name)) as fh:
                sql = "\n".join(l for l in fh
                                 if not l.strip().startswith("--"))
            if "insert into bic_concepts" not in sql.lower():
                continue
            for ns, concept in re.findall(
                    r"'([a-z][a-z0-9_.]*)',\s*\n\s*'([a-z][a-z0-9_]*)',", sql):
                registered.add(f"{ns}.{concept}")

        # The control: the one predicate that IS registered must be found,
        # otherwise this test would pass by finding nothing at all.
        self.assertIn("biz.pipeline.new_enquiries_per_month", registered)
        for ref in (gl.CONVERSION_RATE, gl.PIPELINE_VALUE,
                    gl.CHANNEL_ATTRIBUTION, gl.CAPACITY):
            self.assertNotIn(ref.split("@")[0], registered, ref)

    def test_the_description_states_what_it_requires(self):
        self.assertIn("Requires", self.goal()["description"])


class FocusRecommendationIsInsufficient(RealStack):
    """Drives the REAL stack. Inherits RealStack's registry/claims wiring,
    where only new_enquiries is registered — exactly production's state."""

    def focus_packet(self, tenant=TENANT, subject=ORG_A):
        return self.build(tenant=tenant, subject=subject,
                          goal_def=gl.lookup("business_focus_recommendation"))

    def with_enquiries(self, value=9):
        self.claim(value, datetime.now(timezone.utc) - timedelta(hours=1))

    def test_the_known_metric_is_present_as_evidence(self):
        self.with_enquiries()
        pk = self.focus_packet()
        self.assertEqual([str(f["value"]) for f in pk["evidence"]["facts"]],
                         ["9"])

    def test_the_missing_evidence_is_visible_and_named(self):
        self.with_enquiries()
        pk = self.focus_packet()
        gaps = {g["slot"] for g in pk["epistemic"]["sufficiency"]["gaps"]}
        self.assertEqual(gaps, {"conversion_rate", "pipeline_value",
                                "channel_attribution", "capacity"})

    def test_the_result_is_insufficient(self):
        self.with_enquiries()
        pk = self.focus_packet()
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)

    def test_the_enquiry_metric_alone_never_yields_proceed(self):
        """THE PRODUCT RULE. business_month_review PROCEEDs on this same
        evidence because its action is "assemble what we know"; sufficiency
        is a property of the (evidence, ACTION) pair, so the same fact must
        NOT proceed for a recommendation."""
        self.with_enquiries()
        review = self.build(goal_def=gl.lookup("business_month_review"))
        focus = self.focus_packet()
        self.assertEqual(review["epistemic"]["sufficiency"]["verdict"],
                         cx.PROCEED)
        self.assertEqual(focus["epistemic"]["sufficiency"]["verdict"],
                         cx.REFUSE)

    def test_the_packet_carries_no_recommendation_field(self):
        """STRUCTURAL, and deliberately so.

        A word-scan version of this test stripped "recommendation" from the
        blob first (to avoid matching the goal id business_focus_recommendation)
        and was thereby blind to an injected {"recommendation": "focus on
        Digital Ads"} — verified by mutation. Asserting the exact 2H key set
        instead catches ANY added field, whatever it is called.
        """
        self.with_enquiries()
        self.assertEqual(sorted(self.focus_packet().keys()), [
            "as_of", "assembled_at", "assembly_state", "assembly_version",
            "boundaries", "epistemic", "evidence", "goal_ref", "packet_id",
            "packet_schema_version", "policy_version", "principal",
            "question", "scope", "subject", "tenant_id", "turn_ref"])

    def test_no_advice_language_reaches_the_evidence_or_verdict(self):
        """The goal id legitimately contains "recommendation"; the EVIDENCE
        and the SUFFICIENCY REASON must not contain advice at all."""
        self.with_enquiries()
        pk = self.focus_packet()
        blob = (str(pk["evidence"]) + str(pk["epistemic"]["sufficiency"]["reason"])).lower()
        for word in ("recommend", "focus on", "priorit", "advice", "suggest",
                     "you should"):
            self.assertNotIn(word, blob)

    def test_no_value_is_fabricated_for_a_missing_slot(self):
        self.with_enquiries()
        pk = self.focus_packet()
        preds = {f["predicate"] for f in pk["evidence"]["facts"]}
        for ref in (gl.CONVERSION_RATE, gl.PIPELINE_VALUE,
                    gl.CHANNEL_ATTRIBUTION, gl.CAPACITY):
            self.assertNotIn(ref, preds)

    # ── RETRIEVE vs UNKNOWABLE, preserved per-gap ───────────────────────
    def test_unregistered_evidence_is_unknowable_not_retrievable(self):
        """"We haven't measured it yet" and "there is no such measurement"
        are different answers, and only the second is UNKNOWABLE."""
        self.with_enquiries()
        for g_ in self.focus_packet()["epistemic"]["sufficiency"]["gaps"]:
            self.assertEqual(g_["class"], cx.UNKNOWABLE, g_["slot"])
            self.assertIn("not registered", g_["why"])

    def test_a_registered_but_unmeasured_slot_is_retrievable_not_unknowable(self):
        """The distinction the OWNER adapter will later surface: once a
        predicate IS registered, its absence becomes obtainable."""
        pk = self.build(goal_def=gl.lookup("business_month_review"))
        gap = [g_ for g_ in pk["epistemic"]["sufficiency"]["gaps"]
               if g_["slot"] == "new_enquiries"][0]
        self.assertEqual(gap["class"], cx.OBTAINABLE_BY_RETRIEVAL)
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.RETRIEVE)

    def test_both_classes_are_distinguishable_in_one_packet(self):
        """REFUSE outranks RETRIEVE in the aggregate, but the per-gap classes
        must both survive so the adapter can word them differently."""
        pk = self.focus_packet()          # no enquiry claim written
        classes = {g_["slot"]: g_["class"]
                   for g_ in pk["epistemic"]["sufficiency"]["gaps"]}
        self.assertEqual(classes["new_enquiries"], cx.OBTAINABLE_BY_RETRIEVAL)
        self.assertEqual(classes["conversion_rate"], cx.UNKNOWABLE)
        self.assertEqual(pk["epistemic"]["sufficiency"]["verdict"], cx.REFUSE)

    # ── tenant isolation ────────────────────────────────────────────────
    def test_recommendation_evidence_is_tenant_isolated(self):
        """Same subject id under both tenants, so party lookup succeeds
        either way and only the claims tenant filter can separate them."""
        shared = "7f7f7f7f-8888-4888-8888-999999999999"
        for tenant in (TENANT, OTHER_TENANT):
            self.parties.append({"tenant_id": tenant, "knowledge_id": shared,
                                 "kind": "ORGANIZATION",
                                 "resolution_state": "PROVISIONAL",
                                 "merged_into": None})
        now = datetime.now(timezone.utc)
        self.claim(11, now - timedelta(hours=1), tenant=TENANT, subject=shared)
        self.claim(22, now - timedelta(hours=1),
                   tenant=OTHER_TENANT, subject=shared)
        a = self.focus_packet(tenant=TENANT, subject=shared)
        b = self.focus_packet(tenant=OTHER_TENANT, subject=shared)
        self.assertEqual([str(f["value"]) for f in a["evidence"]["facts"]], ["11"])
        self.assertEqual([str(f["value"]) for f in b["evidence"]["facts"]], ["22"])


class FocusRecommendationMakesNoModelCall(unittest.TestCase):
    """Phase 7: zero LLM calls, even for "what should I focus on this month?"
    """

    def test_assemble_business_context_reaches_no_provider(self):
        import webhook as w
        import inspect
        src = inspect.getsource(w.assemble_business_context)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#")).split('"""')[-1]
        for banned in ("generate_owner_reply", "openai", "OpenAI", "deepseek",
                       "gemini", "call_ai", "chat.completions"):
            self.assertNotIn(banned, code)

    def test_the_context_engine_imports_no_provider(self):
        """2H I11: "Assembly makes no AI calls" — enforced by there being
        nothing there that could make one."""
        import inspect
        src = inspect.getsource(cx)
        for banned in ("import openai", "import requests", "chat.completions"):
            self.assertNotIn(banned, src)

    def test_the_whole_focus_path_is_offline(self):
        """Belt and braces: assembling the focus packet with a describe that
        records every call proves no second retrieval sneaks in."""
        calls = []

        def spy(tenant_id, subject, predicates=None, as_of=None):
            calls.append(list(predicates or []))
            return None
        cx.assemble(TENANT, "what should I focus on this month?", owner(),
                    gl.lookup("business_focus_recommendation"), ORG_A,
                    describe=spy, applies_to=lambda ref: None)
        self.assertEqual(len(calls), 1)
