"""Party — the knowledge_id foundation (IDD-2B) + identifiers (IDD-2D §3.2).

WHAT THESE LOCK
---------------
2B V3 identity is meaningless and permanent · kind frozen at creation ·
2D R1 a phone NEVER auto-merges two parties · R2 phone-only identity stays
PROVISIONAL · R3 bindings expire.

The test that matters most is `no_auto_merge`: 2D §3.2 names treating
identifiers as equal "the single most common cause of false merges", and a
false merge silently fuses two real customers' histories.

Offline: no network, no database.
"""

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import party as p                               # noqa: E402
from bic.party import PartyError                          # noqa: E402

T = "00000000-0000-0000-0000-000000000001"
OTHER_T = "00000000-0000-0000-0000-0000000000ff"
PHONE_A = "919999900001"
PHONE_B = "919999900002"
MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")


class FakePartyDb:
    """In-memory bic_parties + bic_party_identifiers, including the SQL
    guarantees: the frozen-kind trigger and the live-binding unique index."""

    def __init__(self):
        self.parties = []
        self.identifiers = []

    def _table(self, name):
        return self.parties if name == p.PARTIES_TABLE else self.identifiers

    def select(self, table, params, timeout=None):
        return [dict(r) for r in self._table(table) if self._match(r, params)]

    def insert(self, table, row, timeout=None):
        if table == p.IDENTIFIERS_TABLE:
            # Partial unique index: one LIVE binding per (tenant, channel, value).
            for existing in self.identifiers:
                if (existing["tenant_id"] == row["tenant_id"]
                        and existing["channel"] == row["channel"]
                        and existing["identifier_value"] == row["identifier_value"]
                        and existing.get("valid_until") is None):
                    from bic.db import DbError
                    raise DbError("duplicate key value violates unique constraint")
            row = {**row, "valid_until": None}
        self._table(table).append(dict(row))

    def update(self, table, params, patch, timeout=None):
        for row in self._table(table):
            if self._match(row, params):
                if table == p.PARTIES_TABLE:
                    # Mirrors bic_parties_freeze_kind().
                    for frozen in ("kind", "knowledge_id"):
                        if frozen in patch and patch[frozen] != row.get(frozen):
                            raise AssertionError(f"{frozen} is frozen")
                row.update(patch)

    @staticmethod
    def _match(row, params):
        for k, v in params.items():
            if k in ("order", "limit"):
                continue
            v = str(v)
            if v == "is.null":
                if row.get(k) is not None:
                    return False
            elif v.startswith("eq.") and str(row.get(k)) != v[3:]:
                return False
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakePartyDb()
        self._p = [
            mock.patch.object(p, "select", self.db.select),
            mock.patch.object(p, "insert", self.db.insert),
            mock.patch.object(p, "update", self.db.update),
        ]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()


# ── Identity (2B V3) ───────────────────────────────────────────────────────

class KnowledgeId(Base):

    def test_is_a_random_uuid(self):
        kid = p.create(T)["knowledge_id"]
        self.assertRegex(kid, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-")

    def test_is_not_derived_from_the_identifier(self):
        """The whole point of meaningless identity: nothing about the phone
        can be recovered from, or predicts, the id."""
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertNotIn(PHONE_A, kid)
        for tail in (PHONE_A[-4:], PHONE_A[:4]):
            self.assertNotIn(tail, kid.replace("-", ""))

    def test_two_parties_from_the_same_phone_in_different_tenants_differ(self):
        """A derived id (uuid5 of the phone) would collide here. A random one
        cannot."""
        self.assertNotEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A),
                            p.resolve_or_create(OTHER_T, p.WHATSAPP, PHONE_A))

    def test_knowledge_id_cannot_be_reassigned(self):
        kid = p.create(T)["knowledge_id"]
        with self.assertRaises(AssertionError):
            p.update(p.PARTIES_TABLE, {"knowledge_id": f"eq.{kid}"},
                     {"knowledge_id": "11111111-1111-1111-1111-111111111111"})

    def test_party_object_holds_no_pii(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        row = self.db.parties[0]
        self.assertEqual(set(row),
                         {"knowledge_id", "tenant_id", "kind", "resolution_state"})
        for banned in ("phone", "name", "email", "label", "identifier_value"):
            self.assertNotIn(banned, row)
        self.assertNotIn(PHONE_A, str(row))


# ── kind (2B §2.2) ─────────────────────────────────────────────────────────

class Kind(Base):

    def test_defaults_to_person_for_a_whatsapp_sender(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(self.db.parties[0]["kind"], p.PERSON)

    def test_is_immutable_after_creation(self):
        """"A Person cannot become an Organization." """
        kid = p.create(T, kind=p.PERSON)["knowledge_id"]
        with self.assertRaises(AssertionError):
            p.update(p.PARTIES_TABLE, {"knowledge_id": f"eq.{kid}"},
                     {"kind": p.ORGANIZATION})

    def test_unknown_kind_rejected(self):
        with self.assertRaises(PartyError):
            p.create(T, kind="ROBOT")

    def test_trigger_exists_in_sql_not_only_in_python(self):
        with open(os.path.join(MIG, "20260816000001_bic_parties.sql")) as fh:
            sql = fh.read()
        self.assertIn("bic_parties_freeze_kind", sql)
        self.assertRegex(sql, r"before update on bic_parties")


# ── Lifecycle (2D R2) ──────────────────────────────────────────────────────

class Lifecycle(Base):

    def test_whatsapp_created_party_is_provisional(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(self.db.parties[0]["resolution_state"], p.PROVISIONAL)

    def test_module_never_writes_resolved(self):
        """R2: phone-only identity is NEVER RESOLVED. Promotion needs
        corroborating evidence, which is 2D and is not implemented."""
        import inspect
        src = inspect.getsource(p)
        self.assertNotRegex(src, r'resolution_state\s*=\s*RESOLVED')
        self.assertNotIn('"RESOLVED"', src.split("RESOLUTION_STATES")[-1])

    def test_lifecycle_state_can_change_unlike_kind(self):
        kid = p.create(T)["knowledge_id"]
        p.update(p.PARTIES_TABLE, {"knowledge_id": f"eq.{kid}"},
                 {"resolution_state": p.DISPUTED})
        self.assertEqual(p.lookup(T, kid)["resolution_state"], p.DISPUTED)

    def test_unknown_resolution_state_rejected(self):
        with self.assertRaises(PartyError):
            p.create(T, resolution_state="MAYBE")


# ── Identifier resolution (2D §3.2-3.5) ────────────────────────────────────

class IdentifierResolution(Base):

    def test_same_identifier_resolves_to_the_same_party(self):
        first = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        second = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.parties), 1)

    def test_different_identifier_creates_a_different_party(self):
        self.assertNotEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A),
                            p.resolve_or_create(T, p.WHATSAPP, PHONE_B))
        self.assertEqual(len(self.db.parties), 2)

    def test_create_if_absent(self):
        self.assertIsNone(p.find_by_identifier(T, p.WHATSAPP, PHONE_A))
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.find_by_identifier(T, p.WHATSAPP, PHONE_A), kid)

    def test_whatsapp_identifier_is_recorded_as_CONTACT(self):
        """2D §3.3: phone is CONTACT — no uniqueness, recycled, shared. A
        future resolver must never mistake it for a sovereign identifier."""
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(self.db.identifiers[0]["identifier_class"], p.CONTACT)

    def test_tenant_isolation(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertIsNone(p.find_by_identifier(OTHER_T, p.WHATSAPP, PHONE_A))

    def test_unknown_identifier_class_rejected(self):
        kid = p.create(T)["knowledge_id"]
        with self.assertRaises(PartyError):
            p.bind_identifier(T, kid, p.WHATSAPP, PHONE_A, identifier_class="VIBES")

    def test_concurrent_create_returns_the_winner_not_a_second_party(self):
        """The unique index is the arbiter. Losing the race must yield the
        winner's party — creating a second one would be an accidental split."""
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        real_create = p.create

        def racing_create(*a, **kw):
            row = real_create(*a, **kw)          # a fresh, orphaned party
            return row

        with mock.patch.object(p, "create", racing_create), \
             mock.patch.object(p, "find_by_identifier",
                               side_effect=[None, kid]):
            self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), kid)


# ── Expiry (2D R3) ─────────────────────────────────────────────────────────

class ExpiredBindings(Base):

    def test_expired_binding_does_not_resolve(self):
        """A recycled number must not resolve to its previous holder."""
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertIsNone(p.find_by_identifier(T, p.WHATSAPP, PHONE_A))

    def test_expiring_keeps_the_row(self):
        """History is not rewritten: a claim asserted while the binding was
        live must stay explicable years later."""
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(len(self.db.identifiers), 1)
        self.assertIsNotNone(self.db.identifiers[0]["valid_until"])

    def test_recycled_number_binds_to_a_new_party(self):
        old = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        new = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertNotEqual(old, new)


# ── R1 — the rule that must never bend ─────────────────────────────────────

class NoAutoMerge(Base):

    def test_module_exposes_no_merge_capability(self):
        """Absence is the guarantee. 2D's merge/scoring/DISPUTED machinery is
        not implemented, so it cannot be invoked early or by accident."""
        for banned in ("merge", "merge_parties", "score", "auto_merge",
                       "resolve_duplicates", "unmerge"):
            self.assertFalse(hasattr(p, banned), f"party.{banned} must not exist")

    def test_two_parties_are_never_fused(self):
        a = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        b = p.resolve_or_create(T, p.WHATSAPP, PHONE_B)
        self.assertNotEqual(a, b)
        self.assertEqual(len({r["knowledge_id"] for r in self.db.parties}), 2)

    def test_sharing_a_phone_across_tenants_does_not_link_parties(self):
        a = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        b = p.resolve_or_create(OTHER_T, p.WHATSAPP, PHONE_A)
        self.assertNotEqual(a, b)


# ── Schema guarantees ──────────────────────────────────────────────────────

class SchemaSafety(unittest.TestCase):

    def _sql(self, name):
        with open(os.path.join(MIG, name)) as fh:
            return fh.read()

    def test_parties_table_declares_no_pii_columns(self):
        """Scans COLUMN NAMES, not prose. The migration's comments necessarily
        discuss phone numbers in order to explain why none is stored."""
        sql = self._sql("20260816000001_bic_parties.sql")
        body = sql.split("create table if not exists bic_parties")[1].split(");")[0]
        columns = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--") or line.startswith("check"):
                continue
            m = re.match(r"^([a-z_]+)\s+(uuid|text|timestamptz|jsonb|integer)", line)
            if m:
                columns.add(m.group(1))
        self.assertEqual(columns, {"knowledge_id", "tenant_id", "kind",
                                   "resolution_state", "created_at"})

    def test_identifiers_are_the_only_pii_home(self):
        sql = self._sql("20260816000002_bic_party_identifiers.sql")
        self.assertIn("identifier_value", sql)
        self.assertIn("identifier_class", sql)

    def test_live_binding_uniqueness_is_partial(self):
        """Full uniqueness would make a recycled number unbindable forever."""
        sql = self._sql("20260816000002_bic_party_identifiers.sql")
        self.assertRegex(sql, r"unique index[\s\S]{0,200}where valid_until is null")

    def test_both_tables_are_rls_denied_by_default(self):
        for name in ("20260816000001_bic_parties.sql",
                     "20260816000002_bic_party_identifiers.sql"):
            sql = self._sql(name)
            self.assertIn("enable row level security", sql)
            self.assertNotIn("create policy", sql)

    def test_claims_subject_has_a_foreign_key_to_parties(self):
        sql = self._sql("20260816000004_bic_claims.sql")
        self.assertRegex(sql, r"subject\s+uuid not null references bic_parties\(knowledge_id\)")

    def test_migration_order_puts_parties_before_claims(self):
        """The FK cannot resolve unless bic_parties exists first."""
        names = sorted(n for n in os.listdir(MIG) if n.startswith("202608160"))
        order = {n.split("_", 1)[1]: i for i, n in enumerate(names)}
        self.assertLess(order["bic_parties.sql"], order["bic_claims.sql"])
        self.assertLess(order["bic_concepts.sql"], order["bic_claims.sql"])
        self.assertLess(order["bic_claims.sql"],
                        order["bic_seed_service_interest.sql"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
