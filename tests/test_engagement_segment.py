"""core.party.engagement_segment@1 — the first predicate from real traffic.

WHY THIS PREDICATE EXISTS
-------------------------
Measured production: 754 inbound turns across 24 senders, and 47 of 50
Decision Records hit NO deterministic branch. The welcome menu has never been
tapped, so declared_service_interest has zero claims after weeks live.

This one is detected inside maybe_alert_vip(), which runs on ORDINARY
free-form messages — where 94% of real traffic actually is. Deterministic
regex, no AI, no new UI path for the customer to discover.

THE STAKES ARE HIGHER THAN THE MENU PATH
----------------------------------------
maybe_alert_vip() runs BEFORE the customer's reply is generated. An exception
escaping the knowledge write would cost a real reply to a VIP lead — so the
isolation tests below are the ones that matter most.

Offline: no network, no AI, no database.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                      # noqa: E402
from bic import claims as c, party as p, registry as r    # noqa: E402
from bic.db import DbError                               # noqa: E402
from tests.test_claims import ClaimsDb                   # noqa: E402

SENDER = "919999000333"
# Meta's wamid, kept ONLY to prove it is refused: it base64-embeds
# the sender's number, so it must never reach a claim.
META_WAMID = "wamid.HBgMOTE5OTk5MDAwMzMzFQIAEhgg"
# The Brain-local message reference the producers actually receive.
MSG_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
VIP_TEXT = "I am an MLA and need campaign help"          # matches BOTH
VIP_ONLY = "our corporator wants a website"
ELECTION_ONLY = "we need help with the election campaign"
NEITHER = "what is the price of a website"
MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
SEED = os.path.join(MIG, "20260816000011_bic_seed_engagement_segment.sql")


class Harness(unittest.TestCase):

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers, self.alerts, self.markers = [], [], [], []

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
            mock.patch.object(w, "notify_owner", lambda m: self.alerts.append(m)),
            mock.patch.object(w, "save_message",
                              lambda ph, ro, ct: self.markers.append(ct)),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w.bic_config, "is_configured", lambda: True),
        ]
        for x in self._p:
            x.start()

        # Registered as DATA, exactly as the seed migration does it.
        r.register("core.party", "engagement_segment", 1, "CLASSIFYING",
                   {"type": "enum", "values": ["VIP", "ELECTION"]},
                   "Engagement segment", cardinality="single",
                   volatility_class="slow")
        r.activate("core.party", "engagement_segment", 1, "raviraj")

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def _turn(self, text, already=False, message_id=MSG_ID):
        buf = io.StringIO()
        with redirect_stdout(buf):
            w.maybe_alert_vip(SENDER, text, already, message_id)
        return buf.getvalue()

    def _values(self):
        return [c["value"] for c in self.db.claims]


# ── 1-4 · detection and precedence ─────────────────────────────────────────

class DetectionAndPrecedence(Harness):

    def test_vip_message_records_VIP(self):
        self._turn(VIP_ONLY)
        self.assertEqual(self._values(), ["VIP"])

    def test_election_message_records_ELECTION(self):
        self._turn(ELECTION_ONLY)
        self.assertEqual(self._values(), ["ELECTION"])

    def test_both_matching_records_VIP(self):
        """Must mirror the alert `tag` precedence so a stored claim can never
        contradict an alert already sent to the owner."""
        out_alert = self._turn(VIP_TEXT)
        self.assertEqual(self._values(), ["VIP"])
        self.assertIn("VIP", self.alerts[0])
        self.assertNotIn("ELECTION", self.alerts[0])

    def test_neither_records_nothing(self):
        self._turn(NEITHER)
        self.assertEqual(self.db.claims, [])
        self.assertEqual(self.parties, [])
        self.assertEqual(self.alerts, [])

    def test_claim_is_written_after_the_alert_not_before(self):
        order = []
        with mock.patch.object(w, "notify_owner", lambda m: order.append("alert")), \
             mock.patch.object(p, "resolve_or_create",
                               side_effect=lambda *a, **k: order.append("claim") or "kid"):
            with redirect_stdout(io.StringIO()):
                w.maybe_alert_vip(SENDER, VIP_ONLY, False, MSG_ID)
        self.assertEqual(order, ["alert", "claim"])


# ── 5-6 · duplication and supersession ─────────────────────────────────────

class DuplicationAndSupersession(Harness):

    def test_repeated_detection_within_the_window_writes_no_duplicate(self):
        """The existing 24h alert dedupe gates the claim too."""
        self._turn(VIP_ONLY, already=False)
        self._turn(VIP_ONLY, already=True)     # ctx["vip_alerted"] now True
        self.assertEqual(len(self.db.claims), 1)

    def test_same_segment_re_detected_after_the_window_does_not_duplicate_truth(self):
        """Two identical claims are agreement, not conflict (2C §5.4) — and
        `current` still resolves to one live value."""
        self._turn(VIP_ONLY)
        self._turn(VIP_ONLY)
        kid = self.parties[0]["knowledge_id"]
        view = c.current(w.bic_config.DEFAULT_TENANT_ID, kid,
                         w.ENGAGEMENT_SEGMENT_PREDICATE)
        self.assertFalse(view["conflict"])
        self.assertEqual({x["value"] for x in view["claims"]}, {"VIP"})

    def test_later_different_segment_supersedes(self):
        self._turn(ELECTION_ONLY)
        self._turn(VIP_ONLY)
        kid = self.parties[0]["knowledge_id"]
        view = c.current(w.bic_config.DEFAULT_TENANT_ID, kid,
                         w.ENGAGEMENT_SEGMENT_PREDICATE)
        self.assertEqual([x["value"] for x in view["claims"]], ["VIP"])
        self.assertIn(c.ST_SUPERSEDED, view["states"].values())

    def test_same_party_reused_across_turns(self):
        self._turn(VIP_ONLY)
        self._turn(ELECTION_ONLY)
        self.assertEqual(len(self.parties), 1)
        self.assertEqual(len({x["subject"] for x in self.db.claims}), 1)


# ── 7-8 · the isolation that matters ───────────────────────────────────────

class FailureIsolation(Harness):

    def test_identity_failure_does_not_break_the_owner_alert(self):
        with mock.patch.object(p, "resolve_or_create",
                               side_effect=DbError(f"down {SENDER}")):
            out = self._turn(VIP_ONLY)
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("CLAIM_WRITE_FAILED", out)
        self.assertNotIn(SENDER, out)

    def test_claim_failure_does_not_break_the_owner_alert(self):
        with mock.patch.object(c, "assert_claim", side_effect=DbError("claims down")):
            self._turn(VIP_ONLY)
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.markers, ["VIP_ALERTED"])

    def test_knowledge_failure_never_propagates_to_the_caller(self):
        """maybe_alert_vip runs BEFORE the customer's reply — an escaping
        exception would cost a real reply to a VIP lead."""
        with mock.patch.object(p, "resolve_or_create",
                               side_effect=RuntimeError("boom")):
            with redirect_stdout(io.StringIO()):
                w.maybe_alert_vip(SENDER, VIP_ONLY, False, MSG_ID)  # must not raise

    def test_unconfigured_bic_writes_nothing_and_stays_silent(self):
        with mock.patch.object(w.bic_config, "is_configured", lambda: False):
            out = self._turn(VIP_ONLY)
        self.assertEqual(self.db.claims, [])
        self.assertEqual(len(self.alerts), 1)
        self.assertNotIn("CLAIM_WRITE_FAILED", out)


# ── 9-12 · provenance and privacy ──────────────────────────────────────────

class ProvenanceAndPrivacy(Harness):

    def test_tier_and_confidence(self):
        self._turn(VIP_ONLY)
        claim = self.db.claims[0]
        self.assertEqual(claim["provenance_tier"], 5)
        self.assertEqual(claim["confidence"], 0.50)
        self.assertEqual(claim["asserted_by"], "whatsapp:vip_detection")

    def test_source_ref_is_a_brain_local_reference(self):
        self._turn(VIP_ONLY)
        self.assertEqual(self.db.claims[0]["source_ref"], f"msg:{MSG_ID}")

    def test_no_message_text_keyword_or_phone_in_the_claim(self):
        self._turn(VIP_TEXT)
        blob = str(self.db.claims[0])
        self.assertNotIn(SENDER, blob)
        self.assertNotIn("MLA", blob)          # the matched keyword
        self.assertNotIn("campaign", blob)     # the message text
        self.assertEqual(self.db.claims[0]["value"], "VIP")

    def test_phone_appears_only_in_the_identifier_table(self):
        self._turn(VIP_ONLY)
        self.assertIn(SENDER, str(self.identifiers))
        self.assertNotIn(SENDER, str(self.parties))
        self.assertNotIn(SENDER, str(self.db.claims))

    def test_claim_field_set_is_the_approved_one(self):
        self._turn(VIP_ONLY)
        self.assertEqual(set(self.db.claims[0]), {
            "claim_id", "tenant_id", "subject", "predicate_ns",
            "predicate_concept", "semantic_version", "value", "source",
            "provenance_tier", "asserted_by", "source_ref", "confidence",
            "valid_from", "valid_until", "observed_at", "pre_commit_state"})


# ── 13-16 · registry, no AI, no regressions ────────────────────────────────

class RegistryAndNonRegression(unittest.TestCase):

    def _seed(self):
        with open(SEED) as fh:
            return fh.read()

    def test_seed_declares_the_approved_semantics(self):
        s = self._seed()
        self.assertIn("'engagement_segment'", s)
        self.assertIn("'CLASSIFYING'", s)
        self.assertIn("'single'", s)
        self.assertIn("'slow'", s)
        self.assertIn("'ACTIVE'", s)
        self.assertNotIn("'multi'", s)

    def test_seed_value_space_matches_the_executable_vocabulary_exactly(self):
        """The seed enum and what the detector can actually produce must not
        drift, or every production write fails registry validation."""
        import re
        block = self._seed().split("jsonb_build_array(", 1)[1].split(")", 1)[0]
        seeded = {m.group(1) for m in re.finditer(r"'([^']+)'", block)}
        self.assertEqual(seeded, {w.SEGMENT_VIP, w.SEGMENT_ELECTION})

    def test_detection_uses_no_ai(self):
        import inspect
        src = inspect.getsource(w.maybe_alert_vip) + inspect.getsource(w.is_vip_message) \
            + inspect.getsource(w.is_election_message)
        for banned in ("openai", "gemini", "deepseek", "generate_reply",
                       "extract_lead_info", "completions"):
            self.assertNotIn(banned, src)

    def test_writer_touches_no_frozen_subsystem(self):
        import inspect
        src = inspect.getsource(w.record_engagement_segment)
        for banned in ("bic_decision", "bic_replay", "bic_facts",
                       "mark_", "WEBHOOK_TURN"):
            self.assertNotIn(banned, src)

    def test_seed_migration_is_insert_only(self):
        code = "\n".join(l for l in self._seed().splitlines()
                         if not l.strip().startswith("--")).lower()
        for banned in ("alter table", "drop", "delete", "update ", "create table"):
            self.assertNotIn(banned, code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
