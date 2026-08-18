"""D12 — supersession is cardinality-aware (IDD-2A §3 · IDD-2C §5.3).

THE BUG THIS LOCKS OUT
----------------------
`current()` used to derive SUPERSEDED from valid_from alone. For a `multi`
predicate that silently DELETES TRUE FACTS: assert phone A, then phone B, and
A is reported superseded even though both are live — and it is reported as a
conflict, which is the opposite of the truth.

    single   supersession is per PREDICATE — a later claim replaces the
             earlier one whatever its value, and two live values conflict
    multi    supersession is per VALUE — a later claim replaces only an
             earlier claim of the SAME value, and several values are the
             declared shape, never a conflict

The registry is the authority for which rule applies, so the answer cannot
drift from the declared meaning.

Offline: no network, no database.
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
from tests.test_claims import ClaimsDb, T, SUBJ, NOW      # noqa: E402


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
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def _register(self, concept, cardinality):
        r.register("core.party", concept, 1, "DESCRIPTIVE", {"type": "text"},
                   concept, cardinality=cardinality)
        r.activate("core.party", concept, 1, "raviraj")
        return f"core.party.{concept}@1"

    def _assert(self, ref, value, days_ago):
        when = NOW - timedelta(days=days_ago)
        return c.assert_claim(T, SUBJ, ref, value, "tally", 1, "raviraj",
                              valid_from=when, observed_at=when)


class SingleCardinality(Base):

    def setUp(self):
        super().setUp()
        self.ref = self._register("legal_name", "single")

    def test_later_value_supersedes_the_earlier_one(self):
        old = self._assert(self.ref, "Old Name", 10)
        new = self._assert(self.ref, "New Name", 1)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertEqual(view["states"][old["claim_id"]], c.ST_SUPERSEDED)
        self.assertEqual(view["states"][new["claim_id"]], c.ST_ACTIVE)
        self.assertEqual([x["value"] for x in view["claims"]], ["New Name"])

    def test_two_values_at_the_same_instant_conflict(self):
        self._assert(self.ref, "Acme Pvt Ltd", 5)
        self._assert(self.ref, "Acme Limited", 5)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertTrue(view["conflict"])
        self.assertEqual(len(view["unresolved_values"]), 2)

    def test_cardinality_is_reported(self):
        self._assert(self.ref, "Acme", 1)
        self.assertEqual(c.current(T, SUBJ, self.ref, as_of=NOW)["cardinality"],
                         "single")


class MultiCardinality(Base):

    def setUp(self):
        super().setUp()
        self.ref = self._register("contact_channel", "multi")

    def test_different_values_coexist_and_neither_is_superseded(self):
        """THE D12 REGRESSION. Both are true at once."""
        first = self._assert(self.ref, "phone-a", 10)
        second = self._assert(self.ref, "phone-b", 1)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertEqual(view["states"][first["claim_id"]], c.ST_ACTIVE)
        self.assertEqual(view["states"][second["claim_id"]], c.ST_ACTIVE)
        self.assertEqual(sorted(x["value"] for x in view["claims"]),
                         ["phone-a", "phone-b"])

    def test_several_values_are_not_a_conflict(self):
        """Multiplicity is the DECLARED SHAPE, not a contradiction."""
        self._assert(self.ref, "phone-a", 10)
        self._assert(self.ref, "phone-b", 1)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertFalse(view["conflict"])
        self.assertEqual(view["unresolved_values"], [])

    def test_a_repeated_value_still_supersedes_its_own_earlier_claim(self):
        """Per-VALUE supersession: re-asserting the same value replaces only
        that value's earlier claim, and leaves the other value untouched."""
        stale = self._assert(self.ref, "phone-a", 10)
        other = self._assert(self.ref, "phone-b", 8)
        fresh = self._assert(self.ref, "phone-a", 1)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertEqual(view["states"][stale["claim_id"]], c.ST_SUPERSEDED)
        self.assertEqual(view["states"][fresh["claim_id"]], c.ST_ACTIVE)
        self.assertEqual(view["states"][other["claim_id"]], c.ST_ACTIVE)

    def test_expiry_still_applies_per_claim(self):
        expired = c.assert_claim(
            T, SUBJ, self.ref, "phone-old", "tally", 1, "raviraj",
            valid_from=NOW - timedelta(days=30), observed_at=NOW - timedelta(days=30),
            valid_until=NOW - timedelta(days=2))
        live = self._assert(self.ref, "phone-new", 1)
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertEqual(view["states"][expired["claim_id"]], c.ST_EXPIRED)
        self.assertEqual(view["states"][live["claim_id"]], c.ST_ACTIVE)

    def test_retraction_still_applies_per_claim(self):
        a = self._assert(self.ref, "phone-a", 5)
        self._assert(self.ref, "phone-b", 5)
        c.retract(T, a["claim_id"], "keying error", "raviraj")
        view = c.current(T, SUBJ, self.ref, as_of=NOW)
        self.assertEqual(view["states"][a["claim_id"]], c.ST_RETRACTED)
        self.assertEqual([x["value"] for x in view["claims"]], ["phone-b"])


class RegistryIsTheAuthority(Base):

    def test_cardinality_comes_from_the_registry_not_a_hardcoded_list(self):
        """P5: no Python table mirrors the registry. Registering a NEW multi
        predicate the module has never heard of behaves correctly with zero
        code changes."""
        ref = self._register("unheard_of_predicate", "multi")
        self._assert(ref, "x", 5)
        self._assert(ref, "y", 1)
        self.assertFalse(c.current(T, SUBJ, ref, as_of=NOW)["conflict"])
        self.assertEqual(len(c.current(T, SUBJ, ref, as_of=NOW)["claims"]), 2)

    def test_unreadable_concept_falls_back_to_single(self):
        """Conservative: the fallback can only mark MORE claims superseded,
        never fabricate a live one."""
        ref = self._register("legal_name", "single")
        self._assert(ref, "a", 5)
        self._assert(ref, "b", 1)
        with mock.patch.object(r, "lookup_ref", side_effect=RuntimeError("db down")):
            view = c.current(T, SUBJ, ref, as_of=NOW)
        self.assertEqual(view["cardinality"], "single")
        self.assertEqual(len(view["claims"]), 1)


class ProductionPredicateIsSingle(unittest.TestCase):

    def test_seeded_predicate_declares_single_cardinality(self):
        """D12 standing instruction: no production `multi` predicate until the
        semantics are correct. This one is single, and the seed proves it."""
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260816000006_bic_seed_service_interest.sql")
        with open(path) as fh:
            sql = fh.read()
        self.assertIn("'single'", sql)
        self.assertNotIn("'multi'", sql)


if __name__ == "__main__":
    unittest.main(verbosity=2)
