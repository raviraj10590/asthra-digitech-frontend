"""Semantic Registry (IDD-2A) — the vocabulary.

WHAT THESE LOCK
---------------
P1 namespaced identifiers · P2 meanings immutable once ACTIVE · P3 a new
meaning is a new version · P5 registry is DATA — a new industry's predicates
can be added with zero code changes.

The extensibility proof (§7) is the criterion 2A itself calls the one that
matters most: if adding `mfg.transformer.kva_rating` needs an engineer, the
multi-industry thesis is already dead.

Offline: no network, no database.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import registry as r                            # noqa: E402
from bic.registry import RegistryError                    # noqa: E402


class FakeDb:
    """In-memory stand-in for bic_concepts, including the ACTIVE freeze."""

    def __init__(self):
        self.rows = []

    def select(self, table, params, timeout=None):
        out = [row for row in self.rows if self._match(row, params)]
        if params.get("order", "").startswith("version.desc"):
            out.sort(key=lambda x: x["version"], reverse=True)
        if params.get("limit"):
            out = out[:int(params["limit"])]
        return [dict(x) for x in out]

    def insert(self, table, row, timeout=None):
        self.rows.append(dict(row))

    def update(self, table, params, patch, timeout=None):
        for row in self.rows:
            if self._match(row, params):
                # Mirrors the SQL trigger: semantics frozen once out of DRAFT.
                if row["lifecycle"] != r.DRAFT:
                    for f in r.SEMANTIC_FIELDS:
                        if f in patch and patch[f] != row.get(f):
                            raise AssertionError(
                                f"semantic field {f} mutated after ACTIVE")
                row.update(patch)

    @staticmethod
    def _match(row, params):
        for k, v in params.items():
            if k in ("order", "limit"):
                continue
            if not str(v).startswith("eq."):
                return False
            if str(row.get(k)) != str(v)[3:]:
                return False
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self._p = [
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def _legal_name(self, version=1, activate=True):
        r.register("core.party", "legal_name", version, "DESCRIPTIVE",
                   {"type": "text"}, "Legal name")
        if activate:
            r.activate("core.party", "legal_name", version, "raviraj")
        return f"core.party.legal_name@{version}"


# ── Identifiers (P1) ───────────────────────────────────────────────────────

class Identifiers(Base):

    def test_parses_a_full_reference(self):
        self.assertEqual(r.parse_ref("core.party.legal_name@1"),
                         ("core.party", "legal_name", 1))

    def test_unqualified_name_is_rejected(self):
        """P1: an unqualified name is rejected at registration."""
        for bad in ("legal_name", "legal_name@1", "core.party.legal_name", ""):
            with self.assertRaises(RegistryError):
                r.parse_ref(bad)

    def test_namespace_must_be_lowercase_dotted(self):
        with self.assertRaises(RegistryError):
            r.register("Core.Party", "legal_name", 1, "DESCRIPTIVE",
                       {"type": "text"}, "x")

    def test_format_round_trips(self):
        self.assertEqual(r.format_ref("mfg.transformer", "kva_rating", 2),
                         "mfg.transformer.kva_rating@2")


# ── Versioning (P3, §5.1) ──────────────────────────────────────────────────

class Versioning(Base):

    def test_version_must_be_positive_integer(self):
        for bad in (0, -1, "1"):
            with self.assertRaises(RegistryError):
                r.register("core.party", "x", bad, "DESCRIPTIVE",
                           {"type": "text"}, "x")

    def test_versions_are_never_reused(self):
        self._legal_name(1)
        with self.assertRaises(RegistryError):
            r.register("core.party", "legal_name", 1, "DESCRIPTIVE",
                       {"type": "text"}, "Legal name")

    def test_two_versions_coexist_as_different_concepts(self):
        """@1 and @2 are DIFFERENT concepts that share a name (P3)."""
        self._legal_name(1)
        self._legal_name(2)
        self.assertEqual(r.lookup("core.party", "legal_name", 1)["version"], 1)
        self.assertEqual(r.lookup("core.party", "legal_name", 2)["version"], 2)

    def test_latest_returns_highest_version(self):
        self._legal_name(1)
        self._legal_name(3)
        self.assertEqual(r.lookup("core.party", "legal_name", "latest")["version"], 3)

    def test_unknown_version_returns_none_not_a_neighbour(self):
        """V3: never a silent fallback to a nearby version."""
        self._legal_name(1)
        self.assertIsNone(r.lookup("core.party", "legal_name", 7))


# ── Immutability (P2) ──────────────────────────────────────────────────────

class SemanticImmutability(Base):

    def test_semantic_field_is_frozen_after_activation(self):
        self._legal_name()
        with self.assertRaises(AssertionError):
            r.update("bic_concepts",
                     {"namespace": "eq.core.party", "concept": "eq.legal_name",
                      "version": "eq.1"},
                     {"value_space": {"type": "enum", "values": ["a"]}})

    def test_semantic_fields_are_editable_while_draft(self):
        r.register("core.party", "draft_x", 1, "DESCRIPTIVE", {"type": "text"}, "X")
        r.update("bic_concepts",
                 {"namespace": "eq.core.party", "concept": "eq.draft_x",
                  "version": "eq.1"},
                 {"cardinality": "multi"})
        self.assertEqual(r.lookup("core.party", "draft_x", 1)["cardinality"], "multi")

    def test_presentational_edit_allowed_after_activation(self):
        """Fixing a Kannada label must never mint a version."""
        self._legal_name()
        r.set_presentation("core.party", "legal_name", 1, label="ಕಾನೂನು ಹೆಸರು")
        self.assertEqual(r.lookup("core.party", "legal_name", 1)["label"],
                         "ಕಾನೂನು ಹೆಸರು")

    def test_semantic_field_via_set_presentation_is_rejected(self):
        self._legal_name()
        with self.assertRaises(RegistryError):
            r.set_presentation("core.party", "legal_name", 1, category="STATE")

    def test_semantic_and_presentational_sets_are_disjoint(self):
        self.assertEqual(set(r.SEMANTIC_FIELDS) & set(r.PRESENTATIONAL_FIELDS), set())


# ── Lifecycle (§5.2) ───────────────────────────────────────────────────────

class Lifecycle(Base):

    def test_registration_starts_in_draft(self):
        r.register("core.party", "x", 1, "DESCRIPTIVE", {"type": "text"}, "X")
        self.assertEqual(r.lookup("core.party", "x", 1)["lifecycle"], r.DRAFT)

    def test_activation_records_who_and_when(self):
        self._legal_name()
        row = r.lookup("core.party", "legal_name", 1)
        self.assertEqual(row["lifecycle"], r.ACTIVE)
        self.assertEqual(row["activated_by"], "raviraj")
        self.assertIsNotNone(row["activated_at"])

    def test_activation_requires_an_author(self):
        """V2: freezing a meaning forever is not anonymous."""
        r.register("core.party", "x", 1, "DESCRIPTIVE", {"type": "text"}, "X")
        with self.assertRaises(RegistryError):
            r.activate("core.party", "x", 1, "")

    def test_cannot_activate_twice(self):
        self._legal_name()
        with self.assertRaises(RegistryError):
            r.activate("core.party", "legal_name", 1, "raviraj")

    def test_cannot_activate_unregistered(self):
        with self.assertRaises(RegistryError):
            r.activate("core.party", "ghost", 1, "raviraj")

    def test_draft_concept_rejects_assertions(self):
        r.register("core.party", "x", 1, "DESCRIPTIVE", {"type": "text"}, "X")
        with self.assertRaises(RegistryError):
            r.validate_assertion("core.party.x@1", "value")

    def test_deprecated_and_retired_reject_new_assertions_but_stay_readable(self):
        """Retirement removes the ability to CREATE, never to INTERPRET."""
        for state in (r.DEPRECATED, r.RETIRED):
            self.db.rows = []
            ref = self._legal_name()
            r.update("bic_concepts",
                     {"namespace": "eq.core.party", "concept": "eq.legal_name",
                      "version": "eq.1"}, {"lifecycle": state})
            with self.assertRaises(RegistryError):
                r.validate_assertion(ref, "Acme")
            self.assertIsNotNone(r.lookup("core.party", "legal_name", 1))


# ── Value space, unit, cardinality, volatility ─────────────────────────────

class SemanticFields(Base):

    def test_quantitative_requires_a_unit(self):
        with self.assertRaises(RegistryError):
            r.register("mfg.transformer", "kva_rating", 1, "QUANTITATIVE",
                       {"type": "number"}, "kVA rating")

    def test_quantitative_with_unit_is_accepted(self):
        r.register("mfg.transformer", "kva_rating", 1, "QUANTITATIVE",
                   {"type": "number", "min": 0}, "kVA rating", unit="kVA")
        self.assertEqual(r.lookup("mfg.transformer", "kva_rating", 1)["unit"], "kVA")

    def test_unknown_category_rejected(self):
        with self.assertRaises(RegistryError):
            r.register("core.party", "x", 1, "FINANCIAL", {"type": "text"}, "X")

    def test_seven_categories_exactly(self):
        self.assertEqual(len(r.CATEGORIES), 7)

    def test_enum_requires_values(self):
        with self.assertRaises(RegistryError):
            r.register("core.order", "status", 1, "STATE", {"type": "enum"}, "Status")

    def test_value_outside_enum_rejected(self):
        r.register("core.order", "status", 1, "STATE",
                   {"type": "enum", "values": ["open", "closed"]}, "Status")
        r.activate("core.order", "status", 1, "raviraj")
        with self.assertRaises(RegistryError):
            r.validate_assertion("core.order.status@1", "cancelled")
        r.validate_assertion("core.order.status@1", "open")     # must not raise

    def test_number_range_enforced(self):
        r.register("mfg.transformer", "kva_rating", 1, "QUANTITATIVE",
                   {"type": "number", "min": 10, "max": 100}, "kVA", unit="kVA")
        r.activate("mfg.transformer", "kva_rating", 1, "raviraj")
        for bad in (5, 500, "abc"):
            with self.assertRaises(RegistryError):
                r.validate_assertion("mfg.transformer.kva_rating@1", bad)
        r.validate_assertion("mfg.transformer.kva_rating@1", 50)

    def test_empty_value_rejected(self):
        ref = self._legal_name()
        for empty in (None, ""):
            with self.assertRaises(RegistryError):
                r.validate_assertion(ref, empty)

    def test_cardinality_and_volatility_vocabularies(self):
        self.assertEqual(set(r.CARDINALITIES), {"single", "multi"})
        self.assertEqual(set(r.VOLATILITY_CLASSES),
                         {"static", "slow", "fast", "live"})
        with self.assertRaises(RegistryError):
            r.register("core.party", "x", 1, "DESCRIPTIVE", {"type": "text"},
                       "X", cardinality="many")
        with self.assertRaises(RegistryError):
            r.register("core.party", "y", 1, "DESCRIPTIVE", {"type": "text"},
                       "Y", volatility_class="hourly")

    def test_compatibility_vocabulary_is_the_five_declared(self):
        self.assertEqual(set(r.COMPATIBILITY),
                         {"EQUIVALENT", "NARROWER", "BROADER",
                          "OVERLAPPING", "UNRELATED"})


# ── Unregistered predicates ────────────────────────────────────────────────

class UnregisteredRejected(Base):

    def test_unregistered_predicate_rejected(self):
        """No free-floating facts."""
        with self.assertRaises(RegistryError):
            r.validate_assertion("core.party.nonexistent@1", "x")

    def test_wrong_version_rejected(self):
        self._legal_name(1)
        with self.assertRaises(RegistryError):
            r.validate_assertion("core.party.legal_name@2", "Acme")


# ── P5 · the criterion 2A says matters most ────────────────────────────────

class ExtensibilityWithoutCode(Base):

    def test_a_new_industry_needs_no_code_change(self):
        """§7: add a new industry's predicates with ZERO code changes.

        Manufacturing, healthcare and real estate below are vocabulary the
        module has never heard of — no branch, no enum edit, no deployment.
        """
        new_industry = [
            ("mfg.transformer", "kva_rating", "QUANTITATIVE",
             {"type": "number", "min": 0}, "kVA", "kVA rating"),
            ("health.encounter", "discharge_on", "TEMPORAL",
             {"type": "timestamp"}, None, "Discharge date"),
            ("realestate.plot", "plot_area", "QUANTITATIVE",
             {"type": "number", "min": 0}, "sqft", "Plot area"),
        ]
        for ns, concept, cat, space, unit, label in new_industry:
            r.register(ns, concept, 1, cat, space, label, unit=unit)
            r.activate(ns, concept, 1, "domain-expert")
            self.assertEqual(r.lookup(ns, concept, 1)["lifecycle"], r.ACTIVE)

        r.validate_assertion("mfg.transformer.kva_rating@1", 250)
        r.validate_assertion("realestate.plot.plot_area@1", 1200)

    def test_registry_holds_no_business_data(self):
        """"Not one row of business data." No tenant, subject or value."""
        self._legal_name()
        row = r.lookup("core.party", "legal_name", 1)
        for banned in ("tenant_id", "subject", "value", "phone", "customer"):
            self.assertNotIn(banned, row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
