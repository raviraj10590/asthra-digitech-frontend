"""Identity retention — the PII contract, locked before the first write.

`bic_party_identifiers` is a DELIBERATE PII STORE: the only place in the BIC
stack holding a channel identifier. These tests are the contract, not a
description of whatever the implementation happens to do.

    ACTIVE      valid_until IS NULL — resolves
    EXPIRED     valid_until set — row RETAINED, does NOT resolve
    HISTORY     expired rows stay readable forever
    DELETION    none. No pruner, no TTL, no cascade, no delete path.

WHY NO PRUNER (and why that is a decision, not an oversight)
------------------------------------------------------------
bic_claims is append-only with no pruner. Deleting an identifier would orphan
claims whose subject can no longer be explained — and an unexplainable claim
is indistinguishable from a fabricated one. A retention policy is a real
future decision, and a legal one; it is left OPEN rather than pre-empted by a
default nobody chose.

Offline: no network, no database.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import party as p                               # noqa: E402
from tests.test_party import Base, T, PHONE_A, PHONE_B, MIG   # noqa: E402


class ActiveBindings(Base):

    def test_active_identifier_resolves(self):
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.find_by_identifier(T, p.WHATSAPP, PHONE_A), kid)

    def test_active_binding_has_null_valid_until(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertIsNone(self.db.identifiers[0]["valid_until"])

    def test_same_active_binding_resolves_the_same_party_every_time(self):
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        for _ in range(5):
            self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), kid)
        self.assertEqual(len(self.db.parties), 1)
        self.assertEqual(len(self.db.identifiers), 1)


class ExpiredBindings(Base):

    def test_expired_identifier_does_not_resolve(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertIsNone(p.find_by_identifier(T, p.WHATSAPP, PHONE_A))

    def test_expiry_sets_valid_until_and_keeps_the_row(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(len(self.db.identifiers), 1)
        self.assertIsNotNone(self.db.identifiers[0]["valid_until"])

    def test_expiry_preserves_every_other_field(self):
        """Expiry ends a binding; it does not redact one."""
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        before = dict(self.db.identifiers[0])
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        after = self.db.identifiers[0]
        for field in ("party_id", "channel", "identifier_value",
                      "identifier_class", "tenant_id"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["party_id"], kid)

    def test_reused_number_does_not_silently_merge_two_parties(self):
        """THE failure this whole classification exists to prevent: a recycled
        number answering as its previous holder fuses two real customers'
        histories, silently."""
        first = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        second = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)

        self.assertNotEqual(first, second)
        self.assertEqual(len(self.db.parties), 2)
        # Both bindings survive: one expired, one live.
        self.assertEqual(len(self.db.identifiers), 2)

    def test_the_old_party_keeps_its_own_binding_after_recycling(self):
        """Retention is a property of the STORED ROWS, not of any read API.

        Asserted against the store directly: bic/party.py deliberately exposes
        no history function — a read path that returns raw identifiers is 2D's
        to design, once a real consumer needs it and its access control can be
        decided along with it.
        """
        first = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        second = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)

        by_party = {row["party_id"]: row for row in self.db.identifiers}
        self.assertEqual(set(by_party), {first, second})
        self.assertIsNotNone(by_party[first]["valid_until"])   # retained, ended
        self.assertIsNone(by_party[second]["valid_until"])     # live

    def test_only_the_live_binding_resolves_after_recycling(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        second = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.find_by_identifier(T, p.WHATSAPP, PHONE_A), second)


class NoDeletion(unittest.TestCase):
    """Deletion is absent STRUCTURALLY, not merely unused."""

    def _sql(self, name):
        with open(os.path.join(MIG, name)) as fh:
            return fh.read()

    def test_module_exposes_no_identifier_history_api(self):
        """Retention does NOT require a history API, and a history API would
        be the one function able to hand out raw phone numbers. 2D adds a
        controlled interface when a real consumer exists and its access
        control can be decided alongside it — until then, absence."""
        for banned in ("identifier_history", "list_identifiers",
                       "identifiers_for_party", "export_identifiers"):
            self.assertFalse(hasattr(p, banned), f"party.{banned} must not exist")

    def test_no_function_returns_a_raw_identifier_to_a_caller(self):
        """find_by_identifier returns a party_id; lookup returns the party row,
        which holds no PII by construction."""
        self.assertNotIn("identifier_value", str(p.lookup.__doc__ or ""))
        import inspect
        src = inspect.getsource(p.find_by_identifier)
        self.assertIn('rows[0]["party_id"]', src)

    def test_module_exposes_no_delete_capability(self):
        for banned in ("delete", "delete_identifier", "purge", "prune",
                       "forget", "redact", "cleanup", "drop_party"):
            self.assertFalse(hasattr(p, banned), f"party.{banned} must not exist")

    def test_module_issues_no_delete_at_all(self):
        import inspect
        src = inspect.getsource(p)
        self.assertNotIn("requests.delete", src)
        self.assertNotIn("db.delete", src)
        # db.py exposes no delete primitive for anything to reach for.
        from bic import db
        self.assertFalse(hasattr(db, "delete"))

    def test_identifiers_do_not_cascade_from_parties(self):
        """A party delete must not silently take its bindings with it."""
        sql = self._sql("20260816000002_bic_party_identifiers.sql")
        self.assertIn("references bic_parties(knowledge_id)", sql)
        self.assertNotIn("on delete cascade", sql.lower())

    def test_no_pruner_or_ttl_in_either_migration(self):
        for name in ("20260816000001_bic_parties.sql",
                     "20260816000002_bic_party_identifiers.sql"):
            sql = self._sql(name).lower()
            for banned in ("pg_cron", "cron.schedule", "delete from",
                           "truncate", "interval '30 days'"):
                self.assertNotIn(banned, sql, f"{banned} in {name}")

    def test_retention_contract_is_documented_in_the_migration(self):
        """The contract lives with the schema, so it cannot drift out of sight."""
        sql = self._sql("20260816000002_bic_party_identifiers.sql")
        self.assertIn("RETENTION SEMANTICS", sql)
        for clause in ("ACTIVE", "EXPIRED", "HISTORY", "PRUNING"):
            self.assertIn(clause, sql)


class PiiBoundary(Base):

    def test_claims_table_never_receives_an_identifier(self):
        """bic_claims stays PII-free: the boundary is the whole payoff of a
        meaningless knowledge_id."""
        import inspect
        from bic import claims
        src = inspect.getsource(claims)
        self.assertNotIn("identifier_value", src)
        self.assertNotIn(p.IDENTIFIERS_TABLE, src)

    def test_identifiers_table_is_the_only_pii_home_in_the_stack(self):
        import inspect
        from bic import claims, decision, registry
        for module in (claims, decision, registry):
            self.assertNotIn("bic_party_identifiers", inspect.getsource(module),
                             f"{module.__name__} must not touch the PII table")

    def test_party_row_still_holds_no_identifier_after_expiry(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertNotIn(PHONE_A, str(self.db.parties))


class NoNewCost(unittest.TestCase):

    def test_no_new_service_or_dependency_introduced(self):
        import inspect
        src = inspect.getsource(p)
        for banned in ("boto3", "redis", "kafka", "elasticsearch", "vault",
                       "http://", "https://"):
            self.assertNotIn(banned, src)

    def test_party_module_depends_only_on_existing_bic_infrastructure(self):
        import inspect
        src = inspect.getsource(p)
        self.assertIn("from .db import", src)
        self.assertIn("from . import config", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
