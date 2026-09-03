"""core.party.first_seen_at@1 — the first TIER-1 predicate.

WHY THIS ONE MATTERS DIFFERENTLY
--------------------------------
Both existing predicates are tier 5, capped at 0.50: a customer describing
themselves is weak evidence however cleanly it is detected. This one is our
own transport recording when a message arrived through an HMAC-verified
boundary — IDD-2C §6 tier 1, confidence 0.90.

So these tests prove two things nothing else in the suite can:
  • the tier cap is DATA-DRIVEN, not hardcoded to 0.50
  • valid_from and observed_at are conceptually independent, not
    coincidentally equal

A SECOND CLAIM IS A BUG, NOT A SUPERSESSION. A party has exactly one first
contact, so the writer reads before writing and declines.

NO BACKFILL. 22 senders predate this predicate and stay unclaimed; writing
them would fabricate observed_at values for knowledge never observed.

Offline: no network, no AI, no database.
"""

import io
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                      # noqa: E402
from bic import claims as c, party as p, registry as r    # noqa: E402
from bic import message_ref as mr                        # noqa: E402
from bic.db import DbError                               # noqa: E402
from tests.test_claims import ClaimsDb                   # noqa: E402

SENDER = "919999000444"
# Meta's wamid, kept ONLY to prove it is refused: it base64-embeds
# the sender's number, so it must never reach a claim.
META_WAMID = "wamid.HBgMOTE5OTk5MDAwNDQ0FQIAEhgg"
# The Brain-local message reference the producers actually receive.
MSG_ID = "9f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f"
FIRST_SEEN = datetime(2026, 8, 18, 10, 30, tzinfo=timezone.utc)
# A second sender and a message id that embed NO phone number, so the
# derivation tests below vary exactly one thing: who sent the message.
OTHER_SENDER = "918888000111"
SAFE_MSG_ID = "wamid.TEST-NO-EMBEDDED-MSISDN"
MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
SEED = os.path.join(MIG, "20260816000012_bic_seed_first_seen_at.sql")


class Harness(unittest.TestCase):

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

        def party_insert(table, row, timeout=None):
            (self.identifiers if table == p.IDENTIFIERS_TABLE
             else self.parties).append({**row, "valid_until": None}
                                       if table == p.IDENTIFIERS_TABLE else dict(row))

        self._p = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(p, "insert", party_insert),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w.bic_config, "is_configured", lambda: True),
        ]
        for x in self._p:
            x.start()

        r.register("core.party", "first_seen_at", 1, "TEMPORAL",
                   {"type": "timestamp"}, "First seen at",
                   cardinality="single", volatility_class="static")
        r.activate("core.party", "first_seen_at", 1, "raviraj")

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def _capture(self, when=FIRST_SEEN, message_id=MSG_ID, sender=SENDER):
        buf = io.StringIO()
        with redirect_stdout(buf):
            w.record_first_seen(sender, when, message_id)
        return buf.getvalue()

    def _claim_against_fresh_store(self, sender=SENDER, message_id=SAFE_MSG_ID):
        """One claim, written against a brand-new store with no shared rows.

        Needed for the regeneration proof below: a value DERIVED from the
        sender is identical every time it is computed, so two independent
        stores are what tell derivation apart from randomness.
        """
        self.tearDown()
        self.setUp()
        self._capture(message_id=message_id, sender=sender)
        return dict(self.db.claims[0])


# ── 1-3 · the chain ────────────────────────────────────────────────────────

class TheChain(Harness):

    def test_new_sender_creates_a_party(self):
        self._capture()
        self.assertEqual(len(self.parties), 1)
        self.assertEqual(self.parties[0]["kind"], p.PERSON)
        self.assertEqual(self.parties[0]["resolution_state"], p.PROVISIONAL)

    def test_new_sender_creates_a_contact_identifier(self):
        self._capture()
        self.assertEqual(len(self.identifiers), 1)
        self.assertEqual(self.identifiers[0]["identifier_class"], p.CONTACT)
        self.assertEqual(self.identifiers[0]["channel"], p.WHATSAPP)
        self.assertIsNone(self.identifiers[0]["valid_until"])

    def test_new_sender_creates_the_claim_on_that_party(self):
        self._capture()
        self.assertEqual(len(self.db.claims), 1)
        claim = self.db.claims[0]
        self.assertEqual(claim["subject"], self.parties[0]["knowledge_id"])
        self.assertEqual(claim["predicate_ns"], "core.party")
        self.assertEqual(claim["predicate_concept"], "first_seen_at")
        self.assertEqual(claim["semantic_version"], 1)


# ── 4-5, 16 · time ─────────────────────────────────────────────────────────

class TimestampSemantics(Harness):

    def test_valid_from_is_the_first_inbound_timestamp(self):
        self._capture(when=FIRST_SEEN)
        self.assertEqual(self.db.claims[0]["valid_from"], FIRST_SEEN.isoformat())

    def test_observed_at_is_a_separate_system_timestamp(self):
        """World time vs system time — independent fields, not one value."""
        past = datetime.now(timezone.utc) - timedelta(days=30)
        self._capture(when=past)
        claim = self.db.claims[0]
        self.assertEqual(claim["valid_from"], past.isoformat())
        self.assertNotEqual(claim["observed_at"], claim["valid_from"])
        self.assertGreater(claim["observed_at"], claim["valid_from"])

    def test_value_is_iso8601_utc(self):
        self._capture()
        value = self.db.claims[0]["value"]
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
        self.assertEqual(datetime.fromisoformat(value), FIRST_SEEN)

    def test_value_equals_valid_from(self):
        self._capture()
        self.assertEqual(self.db.claims[0]["value"], self.db.claims[0]["valid_from"])


# ── 6-9 · provenance ───────────────────────────────────────────────────────

class Provenance(Harness):

    def test_tier_is_1_not_5(self):
        """The tier cap is DATA-DRIVEN. Both other predicates are tier 5; if
        0.50 were hardcoded anywhere, this claim could not exist."""
        self._capture()
        self.assertEqual(self.db.claims[0]["provenance_tier"], 1)

    def test_confidence_is_0_90(self):
        self._capture()
        self.assertEqual(self.db.claims[0]["confidence"], 0.90)

    def test_confidence_sits_exactly_at_the_tier_1_cap(self):
        self.assertEqual(c.TIER_CAPS[1], 0.90)

    def test_asserted_by(self):
        self._capture()
        self.assertEqual(self.db.claims[0]["asserted_by"], "whatsapp:first_contact")

    def test_source_ref_is_a_brain_local_reference(self):
        self._capture()
        self.assertEqual(self.db.claims[0]["source_ref"], f"msg:{MSG_ID}")


# ── 10-11, 17-18 · exactly once ────────────────────────────────────────────

class ExactlyOnce(Harness):

    def test_second_capture_writes_no_second_claim(self):
        self._capture()
        out = self._capture()
        self.assertEqual(len(self.db.claims), 1)
        self.assertIn("FIRST_SEEN_DUPLICATE_SUPPRESSED", out)

    def test_duplicate_is_declined_not_superseded(self):
        """A party has ONE first contact. A competing value would be a defect
        dressed up as a correction."""
        self._capture(when=FIRST_SEEN)
        self._capture(when=FIRST_SEEN + timedelta(days=1))
        self.assertEqual(len(self.db.claims), 1)
        self.assertEqual(self.db.claims[0]["valid_from"], FIRST_SEEN.isoformat())

    def test_existing_sender_receives_no_backfill(self):
        """A party that already carries the claim is never re-asserted, which
        is what keeps the 22 pre-existing senders unclaimed."""
        self._capture()
        before = list(self.db.claims)
        self._capture()
        self.assertEqual(self.db.claims, before)

    def test_current_resolves_to_one_live_value(self):
        self._capture()
        kid = self.parties[0]["knowledge_id"]
        view = c.current(w.bic_config.DEFAULT_TENANT_ID, kid, w.FIRST_SEEN_PREDICATE)
        self.assertEqual(len(view["claims"]), 1)
        self.assertFalse(view["conflict"])
        self.assertEqual(view["cardinality"], "single")

    def test_claims_are_append_only_from_this_module(self):
        self.assertFalse(hasattr(c, "update"))


# ── 12-13 · the customer is never affected ─────────────────────────────────

class FailureIsolation(Harness):

    def test_identity_failure_is_swallowed(self):
        with mock.patch.object(p, "resolve_or_create",
                               side_effect=DbError(f"down {SENDER}")):
            out = self._capture()
        self.assertIn("CLAIM_WRITE_FAILED", out)
        self.assertNotIn(SENDER, out)
        self.assertEqual(self.db.claims, [])

    def test_claim_failure_is_swallowed(self):
        with mock.patch.object(c, "assert_claim", side_effect=DbError("claims down")):
            out = self._capture()
        self.assertIn("reason=DbError", out)

    def test_registry_rejection_is_swallowed(self):
        with mock.patch.object(r, "validate_assertion",
                               side_effect=r.RegistryError("not registered")):
            out = self._capture()
        self.assertIn("CLAIM_WRITE_FAILED", out)

    def test_nothing_ever_propagates_to_the_caller(self):
        """The welcome menu has already been sent by the time this runs."""
        for exc in (RuntimeError("boom"), DbError("x"), ValueError("y")):
            with mock.patch.object(p, "resolve_or_create", side_effect=exc):
                with redirect_stdout(io.StringIO()):
                    w.record_first_seen(SENDER, FIRST_SEEN, MSG_ID)  # must not raise

    def test_unconfigured_bic_is_silent(self):
        with mock.patch.object(w.bic_config, "is_configured", lambda: False):
            out = self._capture()
        self.assertEqual(self.db.claims, [])
        self.assertEqual(out, "")


# ── 14-15, 19 · privacy, no AI, registry ───────────────────────────────────

class PrivacyAndRegistry(Harness):

    def test_no_pii_in_the_claim(self):
        """The sender's number must not appear in the claim in plaintext.

        SCOPE, stated honestly: this proves PLAINTEXT absence only. It does
        NOT prove the claim carries no trace of the sender — see
        test_source_ref_carries_the_meta_message_id below, which pins the
        one place a trace survives.

        The removed line asserted `SENDER[-4:]` ("0444") was absent too. That
        was PROBABILISTIC, not a correctness claim: the blob carries a random
        uuid4 claim_id and subject, and a given 4-digit run occurs in 32 hex
        characters often enough to fail ~1 run in 400 (measured: 1/400 over
        400 isolated runs). An accidental substring is not a leak, and the
        same defect was already removed from test_party.py. Derivation is
        now proved directly, by regeneration, in the two tests below.

        The full 12-character number is still asserted absent: that
        collision is ~1e-13, and anything genuinely derived would embed it.
        """
        self._capture()
        blob = str(self.db.claims[0])
        self.assertNotIn(SENDER, blob)

    def test_claim_identity_is_not_derived_from_the_sender(self):
        """PROVED BY REGENERATION, NOT BY SUBSTRING ABSENCE.

        A subject derived from the phone — uuid5(phone), a hash, a prefix —
        is identical every time it is computed. A meaningless identifier is
        not. So the same sender resolved against two independent stores must
        produce a different subject and a different claim_id.
        """
        first = self._claim_against_fresh_store()
        second = self._claim_against_fresh_store()
        self.assertNotEqual(first["subject"], second["subject"])
        self.assertNotEqual(first["claim_id"], second["claim_id"])
        for claim in (first, second):
            self.assertNotIn(SENDER, str(claim))

    def test_claim_body_does_not_vary_with_the_sender(self):
        """Nothing outside identity may encode WHO sent the message.

        Two different senders, everything else held constant. Every field
        except the identity/timing ones must be byte-identical — if any
        carried the sender, in any encoding, it would differ here. This is
        the assertion that actually tests "not derived/stored", and unlike a
        substring check it cannot pass by luck.
        """
        mine = self._claim_against_fresh_store(sender=SENDER)
        theirs = self._claim_against_fresh_store(sender=OTHER_SENDER)
        VARIES_BY_DESIGN = {"claim_id", "subject", "observed_at"}
        self.assertEqual(
            {k: v for k, v in mine.items() if k not in VARIES_BY_DESIGN},
            {k: v for k, v in theirs.items() if k not in VARIES_BY_DESIGN})
        self.assertNotEqual(mine["subject"], theirs["subject"])

    def test_source_ref_is_a_brain_local_reference_only(self):
        """source_ref is `msg:<uuid4>` — provenance, not a provider id.

        IDD-2C calls source_ref a "pointer back to the origin record". The
        origin record is OURS: a row in bic_webhook_events. This asserts the
        pointer is our id and nothing else.
        """
        self._capture()
        ref = self.db.claims[0]["source_ref"]
        self.assertEqual(ref, f"msg:{MSG_ID}")
        self.assertNotIn(SENDER, ref)
        self.assertNotIn("wamid", ref)

    def test_a_wamid_can_never_be_stored_as_a_source_ref(self):
        """Requirement 3: the raw wamid must not reach bic_claims.

        Structural, not conventional: reference() refuses anything that is
        not a bare uuid, so a caller that passes Meta's id gets a claim with
        NO provenance pointer rather than one carrying a phone number.
        """
        self.tearDown(); self.setUp()
        self._capture(message_id=META_WAMID)
        self.assertIsNone(self.db.claims[0]["source_ref"])

    def test_no_base64_encoded_phone_anywhere_in_the_claim(self):
        """Requirement 2 — the encoding that defeated the old plaintext tests.

        META_WAMID decodes to bytes containing the sender's number. Checking
        for the number in plaintext never caught that, so this checks the
        encoded forms directly.
        """
        import base64
        self._capture()
        blob = str(self.db.claims[0])
        for enc in (base64.b64encode(SENDER.encode()).decode(),
                    base64.b64encode(SENDER.encode()).decode().rstrip("="),
                    base64.b64encode(b"\x0c" + SENDER.encode()).decode()[:16],
                    META_WAMID, META_WAMID.split(".", 1)[1]):
            self.assertNotIn(enc, blob, f"encoded sender leaked: {enc[:12]}…")

    def test_one_message_yields_one_stable_reference(self):
        """Requirement 4: every claim from a delivery shares its reference.

        Provenance is per-MESSAGE, so a second claim written for the same
        inbound message must point at the same origin record — otherwise
        "what did this message tell us?" is unanswerable.
        """
        self._capture()
        first = self.db.claims[0]["source_ref"]
        self.assertEqual(first, mr.reference(MSG_ID))
        self.assertEqual(mr.reference(MSG_ID), mr.reference(MSG_ID))

    def test_the_reference_is_not_derivable_from_the_sender(self):
        """Requirement 5, proved by regeneration.

        A reference derived from the phone would repeat. new_id() must not,
        and must not contain the number in any form.
        """
        ids = {mr.new_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)
        for i in ids:
            self.assertNotIn(SENDER, i)
            self.assertTrue(mr.is_valid(i))
        # A derived id would also be STABLE for a fixed sender; these are not.
        self.assertNotEqual(mr.new_id(), mr.new_id())

    def test_provenance_scheme_still_parses_for_replay(self):
        """Requirement 7: the 2G reader shows a scheme, never the value."""
        from bic import knowledge as k
        self._capture()
        ref = self.db.claims[0]["source_ref"]
        self.assertEqual(k._source_kind(ref), "msg")
        self.assertEqual(k._source_kind(f"wa_msg:{META_WAMID}"), "wa_msg")

    def test_phone_lives_only_in_the_identifier_table(self):
        self._capture()
        self.assertIn(SENDER, str(self.identifiers))
        self.assertNotIn(SENDER, str(self.parties))
        self.assertNotIn(SENDER, str(self.db.claims))

    def test_claim_field_set_is_the_approved_one(self):
        self._capture()
        self.assertEqual(set(self.db.claims[0]), {
            "claim_id", "tenant_id", "subject", "predicate_ns",
            "predicate_concept", "semantic_version", "value", "source",
            "provenance_tier", "asserted_by", "source_ref", "confidence",
            "valid_from", "valid_until", "observed_at", "pre_commit_state"})

    def test_registry_validation_is_a_hard_gate(self):
        with self.assertRaises(r.RegistryError):
            r.validate_assertion("core.party.first_seen_at@2", FIRST_SEEN.isoformat())

    def test_no_ai_in_the_capture_path(self):
        import inspect
        src = inspect.getsource(w.record_first_seen)
        for banned in ("openai", "gemini", "deepseek", "generate_reply",
                       "extract_lead_info", "completions", "embedding"):
            self.assertNotIn(banned, src)


# ── 20 · nothing else moved ────────────────────────────────────────────────

class NonRegression(unittest.TestCase):

    def _seed(self):
        with open(SEED) as fh:
            return fh.read()

    def test_seed_declares_the_approved_semantics(self):
        s = self._seed()
        self.assertIn("'first_seen_at'", s)
        self.assertIn("'TEMPORAL'", s)
        self.assertIn("'single'", s)
        self.assertIn("'static'", s)
        self.assertIn("'ACTIVE'", s)
        self.assertNotIn("'multi'", s)

    def test_seed_value_space_is_a_timestamp(self):
        self.assertIn("jsonb_build_object('type', 'timestamp')", self._seed())

    def test_seed_is_insert_only(self):
        code = "\n".join(l for l in self._seed().splitlines()
                         if not l.strip().startswith("--")).lower()
        for banned in ("alter ", "drop ", "delete ", "update ", "create table"):
            self.assertNotIn(banned, code)

    def test_D13_D14_D15_unaffected(self):
        """The hardening still holds: no merge fn, survivor chain intact,
        class-scoped identity."""
        for banned in ("merge", "unmerge", "split", "score"):
            self.assertFalse(hasattr(p, banned))
        self.assertTrue(hasattr(p, "resolve_survivor"))
        self.assertTrue(hasattr(p, "DisputedIdentityError"))

    def test_writer_touches_no_frozen_subsystem(self):
        import inspect
        src = inspect.getsource(w.record_first_seen)
        for banned in ("bic_decision", "bic_replay", "bic_facts",
                       "mark_", "WEBHOOK_TURN"):
            self.assertNotIn(banned, src)

    def test_three_predicates_now_all_single(self):
        import re as _re
        cards = set()
        for n in ("20260816000006_bic_seed_service_interest.sql",
                  "20260816000011_bic_seed_engagement_segment.sql",
                  "20260816000012_bic_seed_first_seen_at.sql"):
            with open(os.path.join(MIG, n)) as fh:
                body = "\n".join(l for l in fh.read().splitlines()
                                 if not l.strip().startswith("--"))
            cards.update(_re.findall(r"'(single|multi)'", body))
        self.assertEqual(cards, {"single"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
