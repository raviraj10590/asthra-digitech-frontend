"""2B identity hardening — D13, D14, D15. Written BEFORE the implementation.

WHY THESE THREE, AND WHY NOW
----------------------------
The 2D analysis found that production holds only CONTACT-class evidence, so
2D's resolution algorithm has nothing to resolve yet. These are the defects
that must not be live when it eventually does — each one is silent.

    D13  resolution_state admits 'MERGED' but nothing records the survivor,
         so a merged party becomes an orphan: claims still point at it and
         nothing says where to redirect.
    D14  resolve_or_create() never inspects resolution_state, so after a
         merge a sender would resolve to the ABSORBED party and new claims
         would attach to a dead identity.
    D15  live-binding uniqueness is scoped per CHANNEL, so one phone can be
         bound to two different parties on whatsapp and sms at once.

None of this implements 2D. No auto-merge, no scoring, no dispute resolution.

Offline: no network, no database.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import party as p                               # noqa: E402
from bic.party import PartyError                          # noqa: E402
from tests.test_party import Base, T, OTHER_T, PHONE_A, PHONE_B, MIG  # noqa: E402


# ── D13 · a MERGED party must name its survivor ────────────────────────────

class D13MergedSurvivor(Base):

    def test_merged_into_column_exists_with_fk(self):
        with open(os.path.join(MIG, "20260816000008_bic_parties_merged_into.sql")) as fh:
            sql = fh.read()
        self.assertRegex(sql, r"merged_into\s+uuid\s+references bic_parties\(knowledge_id\)")

    def test_merged_requires_a_survivor(self):
        """MERGED with no pointer is the orphan case D13 exists to prevent."""
        with open(os.path.join(MIG, "20260816000008_bic_parties_merged_into.sql")) as fh:
            sql = fh.read()
        self.assertIn("bic_parties_merged_pair", sql)
        # both directions of the biconditional
        self.assertRegex(sql, r"resolution_state\s*=\s*'MERGED'\)\s*=\s*\(merged_into is not null\)")

    def test_no_cascade_on_the_survivor_fk(self):
        with open(os.path.join(MIG, "20260816000008_bic_parties_merged_into.sql")) as fh:
            sql = fh.read()
        self.assertNotIn("on delete cascade", sql.lower())

    def test_migration_adds_no_merge_automation(self):
        """D13 is a STRUCTURAL fix. No merge behaviour ships with it.

        Scans EXECUTABLE SQL only — the comments necessarily say "never
        deleted" in order to explain why nothing is deleted."""
        with open(os.path.join(MIG, "20260816000008_bic_parties_merged_into.sql")) as fh:
            code = "\n".join(l for l in fh.read().splitlines()
                             if not l.strip().startswith("--")).lower()
        for banned in ("insert into", "update bic_parties set",
                       "delete from", "on delete cascade"):
            self.assertNotIn(banned, code)

    def test_module_exposes_no_merge_function(self):
        for banned in ("merge", "auto_merge", "unmerge", "split", "score"):
            self.assertFalse(hasattr(p, banned), f"party.{banned} must not exist yet")


# ── D14 · never resolve a dead identity ────────────────────────────────────

class D14ResolutionState(Base):

    def _party_in_state(self, state, merged_into=None):
        row = p.create(T)
        patch = {"resolution_state": state}
        if merged_into:
            patch["merged_into"] = merged_into
        p.update(p.PARTIES_TABLE,
                 {"knowledge_id": f"eq.{row['knowledge_id']}"}, patch)
        return row["knowledge_id"]

    def test_provisional_resolves(self):
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), kid)

    def test_resolved_resolves(self):
        kid = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.update(p.PARTIES_TABLE, {"knowledge_id": f"eq.{kid}"},
                 {"resolution_state": p.RESOLVED})
        self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), kid)

    def test_merged_party_resolves_to_its_survivor(self):
        survivor = p.create(T)["knowledge_id"]
        absorbed = self._party_in_state(p.MERGED, merged_into=survivor)
        p.bind_identifier(T, absorbed, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), survivor)

    def test_merge_chain_is_followed_to_the_end(self):
        final = p.create(T)["knowledge_id"]
        middle = self._party_in_state(p.MERGED, merged_into=final)
        first = self._party_in_state(p.MERGED, merged_into=middle)
        p.bind_identifier(T, first, p.WHATSAPP, PHONE_A)
        self.assertEqual(p.resolve_or_create(T, p.WHATSAPP, PHONE_A), final)

    def test_merge_cycle_raises_rather_than_looping(self):
        """A cycle is corrupt data; hanging forever is worse than failing."""
        a = p.create(T)["knowledge_id"]
        b = p.create(T)["knowledge_id"]
        for x, y in ((a, b), (b, a)):
            p.update(p.PARTIES_TABLE, {"knowledge_id": f"eq.{x}"},
                     {"resolution_state": p.MERGED, "merged_into": y})
        p.bind_identifier(T, a, p.WHATSAPP, PHONE_A)
        with self.assertRaises(PartyError):
            p.resolve_or_create(T, p.WHATSAPP, PHONE_A)

    def test_merged_without_survivor_raises(self):
        """Defensive: the DB constraint forbids this, but a resolver that
        trusts the constraint blindly returns None to its caller."""
        orphan = self._party_in_state(p.MERGED)
        p.bind_identifier(T, orphan, p.WHATSAPP, PHONE_A)
        with self.assertRaises(PartyError):
            p.resolve_or_create(T, p.WHATSAPP, PHONE_A)

    def test_disputed_is_never_silently_resolved(self):
        """2D §3.8: DISPUTED is surfaced, never auto-cleared. Returning the
        party anyway would attach new facts to contested identity."""
        kid = self._party_in_state(p.DISPUTED)
        p.bind_identifier(T, kid, p.WHATSAPP, PHONE_A)
        with self.assertRaises(p.DisputedIdentityError):
            p.resolve_or_create(T, p.WHATSAPP, PHONE_A)

    def test_disputed_error_is_a_party_error(self):
        """So existing best-effort callers keep catching it."""
        self.assertTrue(issubclass(p.DisputedIdentityError, PartyError))

    def test_disputed_does_not_create_a_second_party(self):
        kid = self._party_in_state(p.DISPUTED)
        p.bind_identifier(T, kid, p.WHATSAPP, PHONE_A)
        before = len(self.db.parties)
        with self.assertRaises(p.DisputedIdentityError):
            p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(len(self.db.parties), before)

    def test_unknown_sender_still_creates_a_provisional_party(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_B)
        self.assertEqual(self.db.parties[-1]["resolution_state"], p.PROVISIONAL)


# ── D15 · identity is class-scoped, not transport-scoped ───────────────────

class D15IdentifierUniqueness(Base):

    def test_same_phone_on_another_channel_resolves_to_the_same_party(self):
        """THE D15 REGRESSION. A phone is CONTACT identity regardless of
        transport (2D §3.3); channel is a delivery detail."""
        via_whatsapp = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        via_sms = p.resolve_or_create(T, "sms", PHONE_A)
        self.assertEqual(via_whatsapp, via_sms)
        self.assertEqual(len(self.db.parties), 1)

    def test_controlled_identifiers_stay_scoped_to_their_issuing_system(self):
        """2D §3.2: CONTROLLED is unique WITHIN one issuing system only. Two
        systems' customer IDs can both be '12345' and mean different people."""
        a = p.create(T)["knowledge_id"]
        b = p.create(T)["knowledge_id"]
        p.bind_identifier(T, a, "tally", "12345", identifier_class=p.CONTROLLED)
        p.bind_identifier(T, b, "crm", "12345", identifier_class=p.CONTROLLED)
        self.assertEqual(p.find_by_identifier(T, "tally", "12345",
                                              identifier_class=p.CONTROLLED), a)
        self.assertEqual(p.find_by_identifier(T, "crm", "12345",
                                              identifier_class=p.CONTROLLED), b)

    def test_tenant_isolation_still_holds(self):
        a = p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        b = p.resolve_or_create(OTHER_T, "sms", PHONE_A)
        self.assertNotEqual(a, b)

    def test_expired_binding_still_does_not_resolve_across_channels(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertIsNone(p.find_by_identifier(T, "sms", PHONE_A))

    def test_expiry_is_keyed_the_same_way_as_lookup(self):
        """Otherwise a binding made via WhatsApp is un-expirable by a caller
        that only knows the number — it keeps resolving while looking ended."""
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, "sms", PHONE_A)          # different transport
        self.assertIsNone(p.find_by_identifier(T, p.WHATSAPP, PHONE_A))
        self.assertEqual(len(self.db.identifiers), 1)   # retained, not deleted

    def test_sql_uniqueness_is_class_scoped_for_contact(self):
        with open(os.path.join(MIG, "20260816000009_bic_identifier_uniqueness.sql")) as fh:
            sql = fh.read()
        self.assertRegex(sql, r"unique index[\s\S]{0,300}identifier_class, identifier_value")
        self.assertRegex(sql, r"where valid_until is null")

    def test_sql_keeps_channel_scope_for_controlled(self):
        with open(os.path.join(MIG, "20260816000009_bic_identifier_uniqueness.sql")) as fh:
            sql = fh.read()
        self.assertIn("CONTROLLED", sql)
        self.assertRegex(sql, r"identifier_class, channel, identifier_value")

    def test_nominal_is_never_a_uniqueness_key(self):
        """§3.7: names never match. A unique index on NOMINAL would make them."""
        with open(os.path.join(MIG, "20260816000009_bic_identifier_uniqueness.sql")) as fh:
            sql = fh.read()
        self.assertNotRegex(sql, r"unique index[^;]*'NOMINAL'")


# ── Retention and PII must be unchanged by all three fixes ─────────────────

class UnchangedGuarantees(Base):

    def test_expired_bindings_still_retained(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        p.expire_identifier(T, p.WHATSAPP, PHONE_A)
        self.assertEqual(len(self.db.identifiers), 1)
        self.assertIsNotNone(self.db.identifiers[0]["valid_until"])

    def test_still_no_delete_path(self):
        from bic import db
        self.assertFalse(hasattr(db, "delete"))
        import inspect
        self.assertNotIn("requests.delete", inspect.getsource(p))

    def test_party_row_still_holds_no_pii(self):
        p.resolve_or_create(T, p.WHATSAPP, PHONE_A)
        self.assertNotIn(PHONE_A, str(self.db.parties))

    def test_no_pruning_introduced_by_the_new_migrations(self):
        for name in ("20260816000008_bic_parties_merged_into.sql",
                     "20260816000009_bic_identifier_uniqueness.sql"):
            with open(os.path.join(MIG, name)) as fh:
                sql = fh.read().lower()
            for banned in ("pg_cron", "delete from", "truncate", "on delete cascade"):
                self.assertNotIn(banned, sql, f"{banned} in {name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
