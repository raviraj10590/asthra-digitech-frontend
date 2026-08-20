"""knowledge.describe — the first executable 2G capability.

WHY THESE FIXTURES ARE THE REAL ONES
------------------------------------
Every claim below mirrors a claim that exists in production today: the same
predicates, the same values, the same provenance tiers, the same confidences,
the same observed_at/valid_from gap, and the same partial-knowledge party that
has a declared interest but no first_seen_at. Testing a capability against
invented facts proves it can describe facts nobody has; testing it against
these proves it can describe the ones we actually hold.

The knowledge_ids are SYNTHETIC. They are meaningless uuids by design (2B V3),
so copying the production ones would add nothing except a real identifier in a
test file.

WHAT THIS FILE IS REALLY CHECKING
---------------------------------
Not "does it return the rows". bic/claims.py already has 38 tests for that.
The question here is whether the four states stay distinguishable under every
failure, because the single most damaging thing a knowledge capability can do
is answer "nothing on file" when the truth is "not allowed", "couldn't reach
the store", or "the identity is contested".

Offline: no network, no AI, no database.
"""

import ast
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import claims as c, knowledge as k, party as p, policy    # noqa: E402
from bic import registry as r                                      # noqa: E402
from bic.db import DbError                                         # noqa: E402
from tests.test_claims import ClaimsDb                             # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"

# Synthetic stand-ins for the three production parties.
FULL = "11111111-1111-4111-8111-111111111111"     # interest + first_seen_at
PARTIAL = "22222222-2222-4222-8222-222222222222"  # interest only
ABSENT = "33333333-3333-4333-8333-333333333333"   # a party with no claims
NOBODY = "44444444-4444-4444-8444-444444444444"   # no party at all

INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"

# The exact values on record in production.
SOCIAL = "Social Media ನಿರ್ವಹಣೆ"
DESIGN = "Design & Branding"

# In production, first_seen_at's observed_at trails its valid_from by ~0.5s —
# the transport records the moment, then the writer commits it. The GAP is
# reproduced; the calendar date is not. A fixture pinned to 2026-08-18 passes
# today and fails in a month, long after the change that would explain it.
FIRST_SEEN_LAG = timedelta(milliseconds=506)

SERVICES = [SOCIAL, "Website / App", "Election Campaign", "AI Chatbot",
            "Digital Ads", "Govt Schemes", DESIGN]


def now():
    return datetime.now(timezone.utc)


class Harness(unittest.TestCase):
    """party + claims + registry on one in-memory store."""

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for key, val in params.items():
                    if key in ("order", "limit"):
                        continue
                    val = str(val)
                    if val == "is.null" and row.get(key) is not None:
                        keep = False
                    elif val.startswith("eq.") and str(row.get(key)) != val[3:]:
                        keep = False
                if keep:
                    out.append(dict(row))
            return out

        self._patches = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
        ]
        for patch in self._patches:
            patch.start()

        # The vocabulary, registered as DATA exactly as the seed migrations do.
        r.register("core.party", "declared_service_interest", 1, "CLASSIFYING",
                   {"type": "enum", "values": SERVICES},
                   "Declared service interest", cardinality="single",
                   volatility_class="slow",
                   applies_to=["PERSON", "ORGANIZATION"])
        r.activate("core.party", "declared_service_interest", 1, "raviraj")
        r.register("core.party", "first_seen_at", 1, "TEMPORAL",
                   {"type": "timestamp"}, "First seen at",
                   cardinality="single", volatility_class="static",
                   applies_to=["PERSON", "ORGANIZATION"])
        r.activate("core.party", "first_seen_at", 1, "raviraj")

        for kid in (FULL, PARTIAL, ABSENT):
            self.parties.append({"knowledge_id": kid, "tenant_id": TENANT,
                                 "kind": p.PERSON,
                                 "resolution_state": p.PROVISIONAL,
                                 "merged_into": None})

        # The production claims, reproduced. Anchored in the recent past so
        # that observed_at is never ahead of the clock — a fixture that
        # commits a fact "half a second from now" is invisible to every
        # as-known-at read, which is a test artefact, not a behaviour.
        self.anchor = now() - timedelta(hours=2)
        self.first_seen_value = self.anchor.isoformat()
        c.assert_claim(TENANT, FULL, FIRST_SEEN, self.first_seen_value,
                       source="whatsapp", provenance_tier=1,
                       asserted_by="whatsapp:first_contact", confidence=0.90,
                       source_ref="wa_msg:wamid.TEST",
                       valid_from=self.anchor,
                       observed_at=self.anchor + FIRST_SEEN_LAG)
        self.interest(FULL, SOCIAL, observed=self.anchor + timedelta(seconds=1))
        self.interest(PARTIAL, DESIGN, observed=self.anchor + timedelta(seconds=1))

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()

    def interest(self, subject, value, observed=None, valid_from=None):
        observed = observed or now()
        return c.assert_claim(
            TENANT, subject, INTEREST, value, source="whatsapp",
            provenance_tier=5, asserted_by="whatsapp:menu_selection",
            confidence=0.50, source_ref="wa_msg:wamid.TEST",
            valid_from=valid_from or observed, observed_at=observed)

    def describe(self, entity=FULL, **kwargs):
        return k.describe(TENANT, entity, **kwargs)


# ── The envelope contract (2G §3.2) ────────────────────────────────────────

class EnvelopeContract(Harness):

    def test_envelope_carries_every_declared_field(self):
        env = self.describe()
        for field in ("state", "values", "conflicts", "coverage", "freshness",
                      "confidence", "degraded", "degradation", "trace_ref",
                      "subject", "identity", "evaluated_at"):
            self.assertIn(field, env, f"{field} missing from the envelope")

    def test_a_bare_value_is_never_returned(self):
        """§3.2: a capability never returns a naked value."""
        env = self.describe(predicates=[INTEREST])
        value = env["values"][0]
        for field in ("provenance", "confidence", "observed_at", "freshness",
                      "predicate", "semantic_version"):
            self.assertIn(field, value)

    def test_state_is_one_of_the_four(self):
        self.assertIn(self.describe()["state"], k.STATES)
        self.assertEqual(len(set(k.STATES)), 4)

    def test_known_when_claims_exist(self):
        self.assertEqual(self.describe()["state"], k.KNOWN)


# ── The real production claims ─────────────────────────────────────────────

class RealClaims(Harness):

    def test_full_party_returns_both_predicates(self):
        env = self.describe(FULL)
        self.assertEqual({v["predicate"] for v in env["values"]},
                         {INTEREST, FIRST_SEEN})

    def test_partial_party_reports_the_missing_predicate_as_absent(self):
        """The production party that has an interest but no first_seen_at."""
        env = self.describe(PARTIAL)
        self.assertEqual(env["state"], k.KNOWN)
        self.assertEqual([v["predicate"] for v in env["values"]], [INTEREST])
        self.assertIn(FIRST_SEEN, env["coverage"]["absent"])
        self.assertNotIn(FIRST_SEEN, env["coverage"]["known"])

    def test_values_carry_the_production_provenance(self):
        env = self.describe(FULL, predicates=[INTEREST])
        prov = env["values"][0]["provenance"]
        self.assertEqual(prov["tier"], 5)
        self.assertEqual(prov["cap"], 0.50)
        self.assertEqual(prov["asserted_by"], "whatsapp:menu_selection")

    def test_confidence_never_exceeds_the_tier_cap(self):
        for value in self.describe(FULL)["values"]:
            self.assertLessEqual(value["confidence"], value["provenance"]["cap"])

    def test_tier_one_fact_outranks_the_tier_five_one(self):
        """first_seen_at is our own transport; the interest is self-declared."""
        by_ref = {v["predicate"]: v for v in self.describe(FULL)["values"]}
        self.assertEqual(by_ref[FIRST_SEEN]["confidence"], 0.90)
        self.assertEqual(by_ref[INTEREST]["confidence"], 0.50)

    def test_semantic_version_is_carried_from_the_claim(self):
        self.assertEqual(self.describe(FULL, predicates=[INTEREST])
                         ["values"][0]["semantic_version"], 1)

    def test_status_is_derived_not_stored(self):
        self.assertEqual(self.describe(FULL, predicates=[INTEREST])
                         ["values"][0]["status"], c.ST_ACTIVE)


# ── Freshness (2G §3.3) ────────────────────────────────────────────────────

class Freshness(Harness):

    def test_static_predicate_is_permanent_not_stale(self):
        env = self.describe(FULL, predicates=[FIRST_SEEN])
        self.assertEqual(env["values"][0]["freshness"]["verdict"], k.PERMANENT)

    def test_static_predicate_stays_permanent_after_ten_years(self):
        """A fact that cannot change must never be reported as suspect
        merely because time passed."""
        env = self.describe(FULL, predicates=[FIRST_SEEN],
                            as_known_at=now() + timedelta(days=3650))
        self.assertEqual(env["values"][0]["freshness"]["verdict"], k.PERMANENT)

    def test_slow_predicate_is_fresh_inside_the_bound(self):
        env = self.describe(FULL, predicates=[INTEREST])
        self.assertEqual(env["values"][0]["freshness"]["verdict"], k.FRESH)

    def test_slow_predicate_goes_stale_past_the_bound(self):
        env = self.describe(FULL, predicates=[INTEREST],
                            as_known_at=now() + timedelta(days=181))
        self.assertEqual(env["values"][0]["freshness"]["verdict"], k.STALE)

    def test_a_stale_value_is_returned_not_dropped(self):
        env = self.describe(FULL, predicates=[INTEREST],
                            as_known_at=now() + timedelta(days=181))
        self.assertEqual(env["state"], k.KNOWN)
        self.assertEqual(env["values"][0]["value"], SOCIAL)

    def test_a_stale_value_degrades_the_answer_by_name(self):
        env = self.describe(FULL, predicates=[INTEREST],
                            as_known_at=now() + timedelta(days=181))
        self.assertTrue(env["degraded"])
        self.assertIn(k.DEG_STALE_VALUE,
                      {d["reason"] for d in env["degradation"]})

    def test_bound_is_reported_with_the_verdict(self):
        env = self.describe(FULL, predicates=[INTEREST])
        fresh = env["values"][0]["freshness"]
        self.assertEqual(fresh["volatility_class"], "slow")
        self.assertEqual(fresh["bound_seconds"],
                         int(k.STALENESS_BOUNDS["slow"].total_seconds()))

    def test_overall_freshness_takes_the_worst_verdict(self):
        """One permanent fact must not hide one stale fact."""
        env = self.describe(FULL, as_known_at=now() + timedelta(days=181))
        self.assertEqual(env["freshness"]["verdict"], k.STALE)
        self.assertEqual(env["freshness"]["stale_predicates"], [INTEREST])

    def test_freshness_is_measured_from_observed_at_not_valid_from(self):
        """A fact backdated a year but learned today is fresh knowledge."""
        self.interest(ABSENT, "Digital Ads",
                      observed=now(), valid_from=now() - timedelta(days=400))
        env = self.describe(ABSENT, predicates=[INTEREST])
        self.assertEqual(env["values"][0]["freshness"]["verdict"], k.FRESH)

    def test_every_registry_volatility_class_has_a_bound(self):
        self.assertEqual(set(k.STALENESS_BOUNDS), set(r.VOLATILITY_CLASSES))


# ── Conflicts (2G §3.4, §3.5) ──────────────────────────────────────────────

class Conflicts(Harness):

    def _conflicted(self):
        stamp = now()
        self.interest(ABSENT, SOCIAL, observed=stamp, valid_from=stamp)
        self.interest(ABSENT, DESIGN, observed=stamp, valid_from=stamp)
        return self.describe(ABSENT, predicates=[INTEREST])

    def test_both_conflicting_values_are_returned(self):
        env = self._conflicted()
        self.assertEqual({v["value"] for v in env["values"]}, {SOCIAL, DESIGN})

    def test_the_conflict_is_named_and_marked_unresolved(self):
        env = self._conflicted()
        self.assertEqual(len(env["conflicts"]), 1)
        conflict = env["conflicts"][0]
        self.assertEqual(sorted(conflict["values"]), sorted([DESIGN, SOCIAL]))
        self.assertFalse(conflict["resolved"])

    def test_a_conflict_degrades_the_answer_by_name(self):
        env = self._conflicted()
        self.assertTrue(env["degraded"])
        self.assertIn(k.DEG_CONFLICT_PRESENT,
                      {d["reason"] for d in env["degradation"]})

    def test_no_resolution_ladder_is_implemented_here(self):
        """§3.4 puts the ladder above this capability. A `pick`/`resolve`
        helper appearing in this module would mean it moved."""
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "knowledge.py")) as fh:
            src = fh.read()
        names = {n.name for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef)}
        for banned in ("resolve_conflict", "pick", "adjudicate", "winner",
                       "best_claim"):
            self.assertNotIn(banned, names)


# ── Coverage: absent vs unregistered vs unavailable ────────────────────────

class Coverage(Harness):

    def test_absent_is_not_unregistered(self):
        env = self.describe(ABSENT, predicates=[INTEREST])
        self.assertIn(INTEREST, env["coverage"]["absent"])
        self.assertEqual(env["coverage"]["unregistered"], [])
        self.assertEqual(env["state"], k.UNKNOWN)

    def test_unregistered_is_not_absent(self):
        """'we hold no such fact' and 'there is no such kind of fact' are
        different answers."""
        env = self.describe(FULL, predicates=["core.party.nonexistent@1"])
        self.assertEqual(env["coverage"]["unregistered"],
                         ["core.party.nonexistent@1"])
        self.assertEqual(env["coverage"]["absent"], [])
        self.assertIn(k.DEG_PREDICATE_UNREGISTERED,
                      {d["reason"] for d in env["degradation"]})

    def test_a_malformed_reference_is_unregistered_not_a_crash(self):
        env = self.describe(FULL, predicates=["not a ref"])
        self.assertEqual(env["coverage"]["unregistered"], ["not a ref"])

    def test_omitting_predicates_consults_the_whole_live_vocabulary(self):
        env = self.describe(FULL)
        self.assertEqual(sorted(env["coverage"]["consulted"]),
                         sorted([INTEREST, FIRST_SEEN]))
        self.assertIsNone(env["coverage"]["requested"])

    def test_applies_to_filters_by_party_kind(self):
        r.register("core.org", "gst_number", 1, "IDENTIFYING",
                   {"type": "text"}, "GST number", applies_to=["ORGANIZATION"])
        r.activate("core.org", "gst_number", 1, "raviraj")
        env = self.describe(FULL)
        self.assertNotIn("core.org.gst_number@1", env["coverage"]["consulted"])

    def test_draft_predicates_are_never_consulted(self):
        r.register("core.party", "draft_thing", 1, "DESCRIPTIVE",
                   {"type": "text"}, "Draft thing")
        env = self.describe(FULL)
        self.assertNotIn("core.party.draft_thing@1", env["coverage"]["consulted"])


# ── Degradation (2G §6.1) ──────────────────────────────────────────────────

class Degradation(Harness):

    def test_one_unreadable_predicate_still_answers_the_others(self):
        real = c.current

        def flaky(tenant, subject, ref, as_of=None):
            if ref == INTEREST:
                raise DbError("down")
            return real(tenant, subject, ref, as_of=as_of)

        with mock.patch.object(k.claims_mod, "current", flaky):
            env = self.describe(FULL)
        self.assertEqual(env["state"], k.KNOWN)
        self.assertEqual([v["predicate"] for v in env["values"]], [FIRST_SEEN])
        self.assertIn(INTEREST, env["coverage"]["unavailable"])
        self.assertIn(k.DEG_PREDICATE_UNAVAILABLE,
                      {d["reason"] for d in env["degradation"]})

    def test_every_predicate_unreadable_is_unavailable_not_unknown(self):
        """The failure that matters most: an outage must never read as
        'this customer has no interests'."""
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            env = self.describe(FULL)
        self.assertEqual(env["state"], k.UNAVAILABLE)
        self.assertNotEqual(env["state"], k.UNKNOWN)
        self.assertEqual(env["reason"], k.R_STORE_UNAVAILABLE)

    def test_an_undeclared_degradation_reason_is_rejected(self):
        """§6.1: 'unspecified' is not a declaration."""
        env = k._envelope("e", None, None, None, now(), None)
        with self.assertRaises(k.KnowledgeError):
            k._degrade(env, "unspecified", None)

    def test_degradation_entries_are_not_duplicated(self):
        stamp = now() - timedelta(days=200)
        self.interest(ABSENT, SOCIAL, observed=stamp, valid_from=stamp)
        self.interest(ABSENT, DESIGN, observed=stamp, valid_from=stamp)
        env = self.describe(ABSENT, predicates=[INTEREST])
        reasons = [d["reason"] for d in env["degradation"]]
        self.assertEqual(len(reasons), len(set(reasons)))

    def test_a_healthy_answer_is_not_marked_degraded(self):
        env = self.describe(FULL)
        self.assertFalse(env["degraded"])
        self.assertEqual(env["degradation"], [])


# ── Identity (2B/2D) ───────────────────────────────────────────────────────

class Identity(Harness):

    def test_unknown_entity_is_unknown_not_unavailable(self):
        env = self.describe(NOBODY)
        self.assertEqual(env["state"], k.UNKNOWN)
        self.assertEqual(env["reason"], k.R_UNKNOWN_ENTITY)

    def test_a_merged_party_answers_as_its_survivor(self):
        old = "55555555-5555-4555-8555-555555555555"
        self.parties.append({"knowledge_id": old, "tenant_id": TENANT,
                             "kind": p.PERSON, "resolution_state": p.MERGED,
                             "merged_into": FULL})
        env = self.describe(old)
        self.assertEqual(env["subject"], FULL)
        self.assertEqual(env["redirected_from"], old)
        self.assertEqual(env["state"], k.KNOWN)

    def test_a_disputed_party_is_unavailable_not_unknown(self):
        bad = "66666666-6666-4666-8666-666666666666"
        self.parties.append({"knowledge_id": bad, "tenant_id": TENANT,
                             "kind": p.PERSON, "resolution_state": p.DISPUTED,
                             "merged_into": None})
        env = self.describe(bad)
        self.assertEqual(env["state"], k.UNAVAILABLE)
        self.assertEqual(env["reason"], k.R_IDENTITY_DISPUTED)
        self.assertEqual(env["values"], [])

    def test_an_orphaned_merge_is_unavailable_not_unknown(self):
        orphan = "77777777-7777-4777-8777-777777777777"
        self.parties.append({"knowledge_id": orphan, "tenant_id": TENANT,
                             "kind": p.PERSON, "resolution_state": p.MERGED,
                             "merged_into": None})
        env = self.describe(orphan)
        self.assertEqual(env["state"], k.UNAVAILABLE)
        self.assertEqual(env["reason"], k.R_IDENTITY_UNRESOLVABLE)

    def test_identity_state_is_surfaced_not_assumed(self):
        env = self.describe(FULL)
        self.assertEqual(env["identity"]["resolution_state"], p.PROVISIONAL)
        self.assertEqual(env["confidence"]["identity_state"], p.PROVISIONAL)


# ── Authorization (2G D1, §6.2) ────────────────────────────────────────────

DESCRIPTOR = {"code": "knowledge.describe", "min_role": "STAFF",
              "customer_safe": False, "risk_tier": 1, "active": True}


class Authorization(Harness):

    def test_a_permitted_principal_gets_the_answer(self):
        env = self.describe(FULL, principal=policy.Principal("1", "OWNER", TENANT),
                            descriptor=DESCRIPTOR)
        self.assertEqual(env["state"], k.KNOWN)

    def test_a_client_is_denied_not_emptied(self):
        """§6.2: DENIED must never be indistinguishable from 'no data'."""
        env = self.describe(FULL, principal=policy.Principal("1", "CLIENT", TENANT),
                            descriptor=DESCRIPTOR)
        self.assertEqual(env["state"], k.DENIED)
        self.assertNotEqual(env["state"], k.UNKNOWN)
        self.assertEqual(env["reason"], k.R_NOT_AUTHORIZED)

    def test_a_principal_without_a_descriptor_fails_closed(self):
        env = self.describe(FULL, principal=policy.Principal("1", "OWNER", TENANT))
        self.assertEqual(env["state"], k.DENIED)

    def test_an_inactive_descriptor_denies(self):
        env = self.describe(FULL, principal=policy.Principal("1", "OWNER", TENANT),
                            descriptor=dict(DESCRIPTOR, active=False))
        self.assertEqual(env["state"], k.DENIED)

    def test_denied_leaks_no_knowledge(self):
        env = self.describe(FULL, principal=policy.Principal("1", "CLIENT", TENANT),
                            descriptor=DESCRIPTOR)
        self.assertEqual(env["values"], [])
        self.assertEqual(env["coverage"]["consulted"], [])
        self.assertNotIn(SOCIAL, repr(env))

    def test_there_is_exactly_one_authorization_path(self):
        """D1: 'two authorization paths is one authorization hole'. The gate
        must be policy.may_invoke, not a rule re-implemented here."""
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "knowledge.py")) as fh:
            src = fh.read()
        self.assertIn("may_invoke", src)
        for smell in ("min_role", "customer_safe", "OWNER", "STAFF"):
            self.assertNotIn(f'"{smell}"', src)


# ── Temporal inputs ────────────────────────────────────────────────────────

class Temporal(Harness):

    def test_as_known_at_hides_later_learning(self):
        before = self.anchor - timedelta(minutes=1)
        env = self.describe(FULL, as_known_at=before)
        self.assertEqual(env["state"], k.UNKNOWN)

    def test_the_time_bound_actually_used_is_reported(self):
        stamp = now() - timedelta(days=2)
        env = self.describe(FULL, as_known_at=stamp)
        self.assertEqual(env["evaluated_at"], stamp.isoformat())
        self.assertEqual(env["as_known_at"], stamp.isoformat())

    def test_as_of_is_used_when_as_known_at_is_absent(self):
        stamp = now() - timedelta(days=2)
        env = self.describe(FULL, as_of=stamp)
        self.assertEqual(env["evaluated_at"], stamp.isoformat())

    def test_as_known_at_wins_over_as_of(self):
        known, world = now() - timedelta(days=2), now() - timedelta(days=9)
        env = self.describe(FULL, as_of=world, as_known_at=known)
        self.assertEqual(env["evaluated_at"], known.isoformat())


# ── Confidence as a vector (2G §7.3) ───────────────────────────────────────

class ConfidenceVector(Harness):

    def test_confidence_is_never_a_single_number(self):
        env = self.describe(FULL)
        self.assertIsInstance(env["confidence"], dict)
        self.assertGreaterEqual(len(env["confidence"]), 4)

    def test_value_confidence_is_the_weakest_fact(self):
        env = self.describe(FULL)
        self.assertEqual(env["confidence"]["value_confidence"], 0.50)

    def test_provenance_ceiling_is_the_lowest_cap_present(self):
        env = self.describe(FULL)
        self.assertEqual(env["confidence"]["provenance_ceiling"], 0.50)

    def test_coverage_ratio_reflects_partial_knowledge(self):
        env = self.describe(PARTIAL)
        self.assertEqual(env["confidence"]["coverage_ratio"], 0.5)


# ── Isolation and PII ──────────────────────────────────────────────────────

class Isolation(unittest.TestCase):

    def _source(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "bic",
                               "knowledge.py")) as fh:
            return fh.read()

    def test_the_capability_never_touches_the_database(self):
        """Reaching past bic/claims.py would mean re-deriving supersession,
        retraction and cardinality — slightly differently, invisibly."""
        tree = ast.parse(self._source())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "db":
                self.assertEqual({a.name for a in node.names}, {"DbError"})
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("db", alias.name.split("."))
        for banned in ("select(", "insert(", "update(", "requests.", "rest/v1"):
            self.assertNotIn(banned, self._source())

    def test_the_capability_writes_nothing(self):
        """Matched against the CALLS in the AST, not against the prose.

        The module's own docstring explains retraction and supersession, so a
        substring search finds `retract` in an explanation and reports a write
        that does not exist. A test that reads comments is not a test.
        """
        called = set()
        for node in ast.walk(ast.parse(self._source())):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name:
                    called.add(name)
        for banned in ("assert_claim", "retract", "bind_identifier",
                       "resolve_or_create", "expire_identifier", "register",
                       "activate", "insert", "update", "create"):
            self.assertNotIn(banned, called)


class NoPii(Harness):

    def test_the_envelope_never_carries_source_ref(self):
        """source_ref can hold a wamid; a renderer must not be able to print
        one by printing the envelope."""
        blob = repr(self.describe(FULL))
        self.assertNotIn("source_ref", blob)
        self.assertNotIn("wamid", blob)

    def test_the_envelope_carries_only_the_source_scheme(self):
        env = self.describe(FULL, predicates=[INTEREST])
        self.assertEqual(env["values"][0]["provenance"]["source_kind"], "wa_msg")

    def test_the_claim_id_is_the_handle_back_to_the_evidence(self):
        env = self.describe(FULL, predicates=[INTEREST])
        stored = [x for x in self.db.claims
                  if x["predicate_concept"] == "declared_service_interest"
                  and x["subject"] == FULL]
        self.assertEqual(env["values"][0]["claim_id"], stored[0]["claim_id"])

    def test_no_identifier_value_can_reach_the_envelope(self):
        self.identifiers.append({"tenant_id": TENANT, "party_id": FULL,
                                 "identifier_class": p.CONTACT,
                                 "channel": p.WHATSAPP,
                                 "identifier_value": "919999000222",
                                 "valid_until": None})
        self.assertNotIn("919999000222", repr(self.describe(FULL)))


# ── The renderer (step 13) ─────────────────────────────────────────────────

class Renderer(Harness):

    def setUp(self):
        super().setUp()
        import webhook
        self.w = webhook
        self._extra = [
            mock.patch.object(self.w, "BIC_AVAILABLE", True),
            mock.patch.object(self.w.bic_config, "is_configured", lambda: True),
            mock.patch.object(self.w.bic_config, "DEFAULT_TENANT_ID", TENANT),
        ]
        for patch in self._extra:
            patch.start()
        self.identifiers.append({"tenant_id": TENANT, "party_id": FULL,
                                 "identifier_class": p.CONTACT,
                                 "channel": p.WHATSAPP,
                                 "identifier_value": "919999000222",
                                 "valid_until": None})

    def tearDown(self):
        for patch in reversed(self._extra):
            patch.stop()
        super().tearDown()

    def test_the_tool_is_a_renderer_and_derives_no_knowledge(self):
        """It must call the capability, not bic/claims.py."""
        import inspect
        src = inspect.getsource(self.w.tool_service_interest)
        self.assertIn("bic_knowledge.describe", src)
        self.assertNotIn("bic_claims", src)

    def test_the_reply_shows_the_claim_and_its_freshness(self):
        with redirect_stdout(io.StringIO()):
            out = self.w.tool_service_interest("919999000222")
        self.assertIn(SOCIAL, out)
        self.assertIn("tier 5", out)
        self.assertIn(k.FRESH, out)

    def test_the_reply_never_shows_the_phone_number(self):
        with redirect_stdout(io.StringIO()):
            out = self.w.tool_service_interest("919999000222")
        self.assertNotIn("919999000222", out)

    def test_denied_unknown_and_unavailable_render_differently(self):
        base = {"entity": FULL, "subject": FULL, "identity": {},
                "values": [], "conflicts": [], "degradation": [],
                "coverage": {"consulted": [INTEREST]}}
        denied = self.w.render_knowledge(dict(base, state="DENIED"))
        unknown = self.w.render_knowledge(dict(base, state="UNKNOWN"))
        gone = self.w.render_knowledge(dict(base, state="UNAVAILABLE",
                                            reason="store_unavailable"))
        self.assertEqual(len({denied, unknown, gone}), 3)
        self.assertIn("Not permitted", denied)
        self.assertIn("Nothing on record", unknown)
        self.assertIn("UNAVAILABLE", gone)
        self.assertNotIn("Nothing on record", gone)

    def test_a_conflict_reaches_the_reply(self):
        stamp = now()
        self.interest(FULL, DESIGN, observed=stamp, valid_from=stamp)
        self.interest(FULL, SOCIAL, observed=stamp, valid_from=stamp)
        with redirect_stdout(io.StringIO()):
            out = self.w.tool_service_interest("919999000222")
        self.assertIn("UNRESOLVED CONFLICT", out)


# ── The registry rows (migration 14) ───────────────────────────────────────

class MigrationRows(unittest.TestCase):

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260816000014_bic_knowledge_capability.sql")
        with open(path) as fh:
            self.sql = fh.read()

    def test_the_capability_is_activated(self):
        self.assertIn("active   = true", self.sql)
        self.assertIn("'LIMITED'", self.sql)
        self.assertIn("where code = 'knowledge.describe'", self.sql)

    def test_service_interest_becomes_a_binding_not_an_implementation(self):
        """§8.2: a vertical capability is a registry ROW over a generic one."""
        self.assertIn("binds_to       = 'knowledge.describe'", self.sql)
        self.assertIn("where code = 'service_interest'", self.sql)

    def test_the_declared_bounds_match_the_code(self):
        for text in ("180 days", "24 hours", "5 minutes"):
            self.assertIn(text, self.sql)
        self.assertEqual(k.STALENESS_BOUNDS["slow"], timedelta(days=180))
        self.assertEqual(k.STALENESS_BOUNDS["fast"], timedelta(hours=24))
        self.assertEqual(k.STALENESS_BOUNDS["live"], timedelta(minutes=5))

    def test_the_migration_creates_and_drops_nothing(self):
        lowered = " ".join(line for line in self.sql.splitlines()
                           if not line.strip().startswith("--")).lower()
        for ddl in ("create table", "drop table", "alter table", "drop column",
                    "delete from", "truncate"):
            self.assertNotIn(ddl, lowered)

    def test_the_migration_touches_no_fact_table(self):
        lowered = self.sql.lower()
        for table in ("bic_claims", "bic_parties", "bic_party_identifiers",
                      "bic_decision_records", "bic_facts", "bic_webhook_events"):
            self.assertNotIn(table, lowered)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Two distinctions found in review ───────────────────────────────────────

class OverclaimGuards(Harness):

    def test_partial_failure_with_no_values_is_unavailable_not_unknown(self):
        """UNKNOWN asserts we looked everywhere we were asked to. With one
        predicate unreadable and the rest empty, we did not."""
        real = c.current

        def flaky(tenant, subject, ref, as_of=None):
            if ref == INTEREST:
                raise DbError("down")
            return real(tenant, subject, ref, as_of=as_of)

        with mock.patch.object(k.claims_mod, "current", flaky):
            env = self.describe(ABSENT)
        self.assertEqual(env["values"], [])
        self.assertEqual(env["state"], k.UNAVAILABLE)
        self.assertIn(FIRST_SEEN, env["coverage"]["absent"])
        self.assertIn(INTEREST, env["coverage"]["unavailable"])

    def test_an_empty_predicate_list_consults_nothing(self):
        """A caller whose filter produced no predicates must not get a full
        scan of the vocabulary."""
        env = self.describe(FULL, predicates=[])
        self.assertEqual(env["coverage"]["consulted"], [])
        self.assertEqual(env["coverage"]["requested"], [])
        self.assertEqual(env["state"], k.UNKNOWN)
        self.assertEqual(env["values"], [])

    def test_omitting_predicates_is_not_the_same_as_passing_none_of_them(self):
        self.assertNotEqual(len(self.describe(FULL)["coverage"]["consulted"]),
                            len(self.describe(FULL, predicates=[])
                                ["coverage"]["consulted"]))


class SourceSchemeIsStructural(Harness):
    """A scheme has to LOOK like a scheme, or it is not shown.

    The envelope's no-PII guarantee cannot rest on every future writer
    remembering to prefix source_ref with `wa_msg:`. A bare wamid has no
    ':' at all, so a naive split returns the whole value.
    """

    def test_a_well_formed_scheme_is_shown(self):
        self.assertEqual(k._source_kind("wa_msg:wamid.HBgMOTE5OTk"), "wa_msg")

    def test_a_bare_wamid_is_never_shown(self):
        kind = k._source_kind("wamid.HBgMOTE5OTk5MDAwMjIy")
        self.assertEqual(kind, k.OPAQUE_SOURCE)
        self.assertNotIn("wamid", kind)

    def test_an_unprefixed_reference_carrying_a_number_is_never_shown(self):
        self.assertEqual(k._source_kind("lead_919999000222"), k.OPAQUE_SOURCE)

    def test_absent_and_opaque_are_different_answers(self):
        self.assertIsNone(k._source_kind(None))
        self.assertIsNone(k._source_kind(""))
        self.assertNotEqual(k._source_kind("wamid.X"), None)

    def test_an_unprefixed_source_ref_cannot_reach_the_envelope(self):
        c.assert_claim(TENANT, ABSENT, INTEREST, "Digital Ads",
                       source="whatsapp", provenance_tier=5,
                       asserted_by="whatsapp:menu_selection", confidence=0.50,
                       source_ref="wamid.HBgMOTE5OTk5MDAwMjIy")
        blob = repr(self.describe(ABSENT, predicates=[INTEREST]))
        self.assertNotIn("wamid", blob)
        self.assertNotIn("HBgM", blob)


class TenantIsolation(Harness):
    """Article II.5 — tenancy is not advisory."""

    OTHER = "99999999-9999-4999-8999-999999999999"

    def test_another_tenant_cannot_read_these_facts(self):
        env = k.describe(self.OTHER, FULL)
        self.assertEqual(env["state"], k.UNKNOWN)
        self.assertEqual(env["values"], [])
        self.assertNotIn(SOCIAL, repr(env))

    def test_a_cross_tenant_read_is_unknown_not_denied(self):
        """The party is invisible, not forbidden — a DENIED here would
        confirm to the wrong tenant that the knowledge_id exists."""
        env = k.describe(self.OTHER, FULL)
        self.assertEqual(env["reason"], k.R_UNKNOWN_ENTITY)
