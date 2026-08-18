"""Knowledge Assertions — ValueClaims (IDD-2C), with the registry as consumer.

THE POINT OF THIS SUITE
-----------------------
2A exists to serve 2C. `VerticalSlice` below runs the whole approved path —
register → activate → validate → commit → current → history → as_known_at —
so the registry is proven by an actual consumer rather than in isolation. That
is the entire reason these two slices landed together: Phase 1A built
bic_facts with no consumer, and two weeks later it had none.

Offline: no network, no database, no AI.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import claims as c                              # noqa: E402
from bic import registry as r                            # noqa: E402
from bic import decision as d                            # noqa: E402
from bic.claims import ClaimError                        # noqa: E402
from bic.registry import RegistryError                   # noqa: E402
from tests.test_registry import FakeDb                   # noqa: E402

T = "00000000-0000-0000-0000-000000000001"
OTHER_T = "00000000-0000-0000-0000-0000000000ff"
SUBJ = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class ClaimsDb(FakeDb):
    """Adds the append-only behaviour the SQL triggers enforce."""

    def __init__(self):
        super().__init__()
        self.claims = []
        self.retractions = []

    def select(self, table, params, timeout=None):
        if table == c.TABLE:
            return self._filter(self.claims, params)
        if table == c.RETRACTIONS_TABLE:
            return self._filter(self.retractions, params)
        return super().select(table, params, timeout)

    def insert(self, table, row, timeout=None):
        if table == c.TABLE:
            self.claims.append(dict(row))
        elif table == c.RETRACTIONS_TABLE:
            self.retractions.append(dict(row))
        else:
            super().insert(table, row, timeout)

    def update(self, table, params, patch, timeout=None):
        # Mirrors bic_reject_mutation(): these tables admit no UPDATE at all.
        if table in (c.TABLE, c.RETRACTIONS_TABLE):
            raise AssertionError(f"{table} is append-only: UPDATE rejected")
        super().update(table, params, patch, timeout)

    def _filter(self, rows, params):
        out = []
        for row in rows:
            keep = True
            for k, v in params.items():
                if k in ("order", "limit"):
                    continue
                v = str(v)
                if v.startswith("eq.") and str(row.get(k)) != v[3:]:
                    keep = False
                elif v.startswith("lte.") and str(row.get(k)) > v[4:]:
                    keep = False
                elif v.startswith("in.") and str(row.get(k)) not in v[4:-1].split(","):
                    keep = False
            if keep:
                out.append(dict(row))
        out.sort(key=lambda x: (x.get("valid_from", ""), x.get("observed_at", "")),
                 reverse=True)
        return out


class Base(unittest.TestCase):
    def setUp(self):
        self.db = ClaimsDb()
        self._p = [
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
        ]
        for p in self._p:
            p.start()
        r.register("core.party", "legal_name", 1, "DESCRIPTIVE",
                   {"type": "text"}, "Legal name")
        r.activate("core.party", "legal_name", 1, "raviraj")
        self.REF = "core.party.legal_name@1"

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def _assert(self, value="Acme Pvt Ltd", tier=1, conf=None, tenant=T, **kw):
        return c.assert_claim(tenant, SUBJ, self.REF, value, "tally", tier,
                              "raviraj", confidence=conf, **kw)


# ── THE VERTICAL SLICE — the acceptance path ───────────────────────────────

class VerticalSlice(Base):

    def test_full_path_register_activate_validate_commit_read(self):
        # observed_at is ANCHORED to NOW rather than left to default to wall
        # clock: the as_known_at assertion below uses a NOW-relative bound, so
        # a defaulted observed_at makes the test start failing once real time
        # passes that bound. A test that rots with the calendar is worse than
        # no test — it fails long after the change that would explain it.
        claim = self._assert("Acme Pvt Ltd", observed_at=NOW)
        self.assertEqual(claim["predicate_ns"], "core.party")
        self.assertEqual(claim["semantic_version"], 1)

        cur = c.current(T, SUBJ, self.REF)
        self.assertEqual(len(cur["claims"]), 1)
        self.assertEqual(cur["claims"][0]["value"], "Acme Pvt Ltd")
        self.assertFalse(cur["conflict"])
        self.assertEqual(cur["states"][claim["claim_id"]], c.ST_ACTIVE)

        self.assertEqual(len(c.history(T, SUBJ, self.REF)), 1)
        self.assertEqual(len(c.as_known_at(T, SUBJ, self.REF, NOW + timedelta(days=1))), 1)

    def test_registry_is_a_hard_gate_not_advisory(self):
        with self.assertRaises(RegistryError):
            c.assert_claim(T, SUBJ, "core.party.unknown@1", "x", "tally", 1, "raviraj")


# ── Validation at write time (V6) ──────────────────────────────────────────

class WriteValidation(Base):

    def test_inactive_predicate_rejected(self):
        r.register("core.party", "draft_pred", 1, "DESCRIPTIVE",
                   {"type": "text"}, "Draft")
        with self.assertRaises(RegistryError):
            c.assert_claim(T, SUBJ, "core.party.draft_pred@1", "x", "tally", 1, "r")

    def test_value_outside_value_space_rejected(self):
        r.register("core.order", "status", 1, "STATE",
                   {"type": "enum", "values": ["open", "closed"]}, "Status")
        r.activate("core.order", "status", 1, "raviraj")
        with self.assertRaises(RegistryError):
            c.assert_claim(T, SUBJ, "core.order.status@1", "cancelled", "crm", 1, "r")

    def test_asserted_by_is_required(self):
        with self.assertRaises(ClaimError):
            c.assert_claim(T, SUBJ, self.REF, "Acme", "tally", 1, "")

    def test_invalid_tier_rejected(self):
        for bad in (-1, 6, "one"):
            with self.assertRaises(ClaimError):
                c.assert_claim(T, SUBJ, self.REF, "Acme", "tally", bad, "r")

    def test_valid_until_before_valid_from_rejected(self):
        with self.assertRaises(ClaimError):
            self._assert(valid_from=NOW, valid_until=NOW - timedelta(days=1))


# ── Confidence caps (§6.1, Article II.6) ───────────────────────────────────

class ConfidenceCaps(Base):

    def test_every_tier_cap_enforced(self):
        for tier, cap in c.TIER_CAPS.items():
            with self.assertRaises(ClaimError, msg=f"tier {tier}"):
                self._assert(tier=tier, conf=cap + 0.01)
            self._assert(tier=tier, conf=cap)          # at the cap is fine

    def test_model_cannot_raise_its_own_confidence(self):
        """Tier 4 is model-derived and capped at 0.60, permanently."""
        with self.assertRaises(ClaimError):
            self._assert(tier=4, conf=0.95)

    def test_customer_claim_capped_at_half(self):
        self.assertEqual(c.TIER_CAPS[5], 0.50)
        with self.assertRaises(ClaimError):
            self._assert(tier=5, conf=0.51)

    def test_confidence_defaults_to_the_tier_cap(self):
        self.assertEqual(self._assert(tier=2)["confidence"], 0.80)


# ── Bitemporality (§7) ─────────────────────────────────────────────────────

class Bitemporal(Base):

    def test_world_time_and_observation_time_are_independent(self):
        claim = self._assert(valid_from=NOW - timedelta(days=90), observed_at=NOW)
        self.assertNotEqual(claim["valid_from"], claim["observed_at"])

    def test_recorded_at_is_stamped_by_the_database_not_the_caller(self):
        """The third clock belongs to the store, so a backfill cannot forge
        when a row actually arrived."""
        self.assertNotIn("recorded_at", self._assert())
        with open(os.path.join(os.path.dirname(__file__), "..", "supabase",
                               "migrations",
                               "20260816000004_bic_claims.sql")) as fh:
            sql = fh.read()
        self.assertRegex(sql, r"recorded_at\s+timestamptz\s+not null\s+default now\(\)")

    def test_as_known_at_excludes_later_observations(self):
        """A fact learned in June about March is invisible to a March query."""
        march, june = NOW - timedelta(days=150), NOW - timedelta(days=60)
        self._assert("Old Name", valid_from=march, observed_at=march)
        self._assert("New Name", valid_from=march, observed_at=june)

        as_march = c.as_known_at(T, SUBJ, self.REF, march)
        self.assertEqual([x["value"] for x in as_march], ["Old Name"])
        self.assertEqual(len(c.as_known_at(T, SUBJ, self.REF, NOW)), 2)

    def test_retroactive_correction_keeps_both_readable(self):
        """§7.4: new claim, back-dated valid_from, forward observed_at."""
        self._assert("Wrong", valid_from=NOW - timedelta(days=100),
                     observed_at=NOW - timedelta(days=100))
        self._assert("Corrected", valid_from=NOW - timedelta(days=100),
                     observed_at=NOW)
        self.assertEqual(len(c.history(T, SUBJ, self.REF)), 2)

    def test_as_known_at_is_not_simply_current_rows(self):
        past = NOW - timedelta(days=10)
        self._assert("Later", valid_from=past, observed_at=NOW)
        self.assertEqual(c.as_known_at(T, SUBJ, self.REF, past), [])


# ── Derived status (C1) ────────────────────────────────────────────────────

class DerivedStatus(Base):

    def test_status_is_never_a_stored_column(self):
        claim = self._assert()
        for banned in ("status", "updated_at", "superseded_by",
                       "last_verified", "category", "is_current"):
            self.assertNotIn(banned, claim, f"{banned} must not be stored")

    def test_supersession_is_derived_from_a_later_claim(self):
        old = self._assert("Old", valid_from=NOW - timedelta(days=10))
        new = self._assert("New", valid_from=NOW)
        cur = c.current(T, SUBJ, self.REF)
        self.assertEqual(cur["states"][old["claim_id"]], c.ST_SUPERSEDED)
        self.assertEqual(cur["states"][new["claim_id"]], c.ST_ACTIVE)
        self.assertEqual([x["value"] for x in cur["claims"]], ["New"])

    def test_expiry_is_derived_from_valid_until(self):
        claim = self._assert(valid_from=NOW - timedelta(days=10),
                             valid_until=NOW - timedelta(days=1),
                             observed_at=NOW - timedelta(days=10))
        cur = c.current(T, SUBJ, self.REF, as_of=NOW)
        self.assertEqual(cur["states"][claim["claim_id"]], c.ST_EXPIRED)
        self.assertEqual(cur["claims"], [])


# ── Retraction (§3.3) ──────────────────────────────────────────────────────

class Retraction(Base):

    def test_retraction_excludes_from_current_but_keeps_it_readable(self):
        claim = self._assert("Mistake")
        c.retract(T, claim["claim_id"], "keying error", "raviraj")
        cur = c.current(T, SUBJ, self.REF)
        self.assertEqual(cur["claims"], [])
        self.assertEqual(cur["states"][claim["claim_id"]], c.ST_RETRACTED)
        # Included in historical replay — the decision was made ON this fact.
        self.assertEqual(len(c.history(T, SUBJ, self.REF)), 1)

    def test_retraction_never_deletes_or_mutates_the_claim(self):
        claim = self._assert("Mistake")
        before = dict(self.db.claims[0])
        c.retract(T, claim["claim_id"], "wrong source", "raviraj")
        self.assertEqual(len(self.db.claims), 1)
        self.assertEqual(self.db.claims[0], before)

    def test_retraction_requires_reason_and_author(self):
        claim = self._assert()
        for reason, who in (("", "raviraj"), ("oops", "")):
            with self.assertRaises(ClaimError):
                c.retract(T, claim["claim_id"], reason, who)


# ── Conflicts surfaced, never resolved (§5.3) ──────────────────────────────

class ConflictsSurfaced(Base):

    def test_two_contradictory_claims_are_both_returned(self):
        self._assert("Acme Pvt Ltd", tier=0, valid_from=NOW)
        self._assert("Acme Private Limited", tier=4, valid_from=NOW)
        cur = c.current(T, SUBJ, self.REF)
        self.assertTrue(cur["conflict"])
        self.assertEqual(len(cur["claims"]), 2)
        self.assertEqual(len(cur["unresolved_values"]), 2)

    def test_higher_tier_does_not_silently_win(self):
        """The 7-rung ladder is NOT implemented in this slice. Picking one
        silently is indistinguishable from knowing."""
        self._assert("Tier0", tier=0, valid_from=NOW)
        self._assert("Tier5", tier=5, valid_from=NOW)
        self.assertTrue(c.current(T, SUBJ, self.REF)["conflict"])

    def test_agreement_is_not_a_conflict(self):
        """§5.4: several sources asserting the same value is evidence."""
        self._assert("Acme", tier=0, valid_from=NOW)
        self._assert("Acme", tier=1, valid_from=NOW)
        cur = c.current(T, SUBJ, self.REF)
        self.assertFalse(cur["conflict"])
        self.assertEqual(len(cur["claims"]), 2)


# ── Append-only, structurally ──────────────────────────────────────────────

class AppendOnly(Base):

    def test_claims_module_has_no_update_in_its_namespace(self):
        self.assertFalse(hasattr(c, "update"))

    def test_decision_module_has_no_update_in_its_namespace(self):
        self.assertFalse(hasattr(d, "update"))

    def test_module_imports_only_insert_and_select(self):
        import inspect
        self.assertIn("from .db import DbError, insert, select",
                      inspect.getsource(c))

    def test_database_rejects_update_on_claims(self):
        self._assert()
        with self.assertRaises(AssertionError):
            self.db.update(c.TABLE, {"claim_id": "eq.x"}, {"value": "tampered"})

    def test_database_rejects_update_on_retractions(self):
        with self.assertRaises(AssertionError):
            self.db.update(c.RETRACTIONS_TABLE, {"claim_id": "eq.x"},
                           {"reason": "changed"})

    def test_correction_appends_rather_than_edits(self):
        self._assert("Wrong")
        self._assert("Right")
        self.assertEqual(len(self.db.claims), 2)


# ── Tenancy and PII ────────────────────────────────────────────────────────

class TenancyAndPii(Base):

    def test_tenant_isolation(self):
        self._assert("Tenant A", tenant=T)
        self._assert("Tenant B", tenant=OTHER_T)
        self.assertEqual([x["value"] for x in c.history(T, SUBJ, self.REF)],
                         ["Tenant A"])
        self.assertEqual([x["value"] for x in c.history(OTHER_T, SUBJ, self.REF)],
                         ["Tenant B"])

    def test_tenant_id_on_every_claim_and_retraction(self):
        claim = self._assert()
        self.assertEqual(claim["tenant_id"], T)
        self.assertEqual(c.retract(T, claim["claim_id"], "x", "y")["tenant_id"], T)

    def test_claim_field_set_is_exactly_as_approved(self):
        self.assertEqual(set(self._assert()), {
            "claim_id", "tenant_id", "subject", "predicate_ns",
            "predicate_concept", "semantic_version", "value", "source",
            "provenance_tier", "asserted_by", "source_ref", "confidence",
            "valid_from", "valid_until", "observed_at", "pre_commit_state"})

    def test_module_exposes_no_phone_or_message_parameter(self):
        import inspect
        params = set(inspect.signature(c.assert_claim).parameters)
        for banned in ("phone", "message", "text", "prompt", "sender"):
            self.assertNotIn(banned, params)


# ── Existing Brain components unaffected ───────────────────────────────────

class NoRegression(Base):

    def test_decision_record_schema_version_unchanged(self):
        self.assertEqual(d.SCHEMA_VERSION, 3)

    def test_decision_record_still_builds(self):
        d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
        rec = d.build_record()
        self.assertEqual(rec["schema_version"], 3)
        d.close_turn()

    def test_claims_never_touch_legacy_or_replay_tables(self):
        import inspect
        src = inspect.getsource(c)
        for table in ("bic_facts", "bic_entities", "bic_edges",
                      "bic_replay_records", "bic_decision_records"):
            self.assertNotIn(table, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
