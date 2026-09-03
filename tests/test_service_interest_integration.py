"""The first production consumer, end to end.

    menu tap → PROVISIONAL PERSON party → WhatsApp CONTACT identifier
             → knowledge_id → core.party.declared_service_interest@1
             → ValueClaim → owner-only read

WHY THIS FILE IS THE POINT OF THE WHOLE SLICE
---------------------------------------------
Phase 1A built bic_facts, passed its tests, and acquired no production caller;
two weeks later it still had none, and it is now frozen legacy. A knowledge
store with no consumer is indistinguishable from no knowledge store. These
tests exist to prove the path is actually wired, not merely available.

The isolation tests matter just as much: the lead is the revenue and the reply
is the customer experience. A knowledge store that can break either is worse
than no knowledge store, so every failure mode below must leave both intact.

Offline: no network, no AI, no database.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# SYNTHETIC owner numbers. These tests never exercise owner bootstrap — the
# read-path tests call the tool directly and the policy test builds a
# Principal explicitly — so there is no reason for a real number to appear
# here. (Older test modules pin the real defaults; those predate this file and
# `setdefault` makes whichever module imports first the winner. Nothing below
# depends on the outcome either way.)
os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                      # noqa: E402
from bic import claims as c, party as p, registry as r    # noqa: E402
from bic.db import DbError                               # noqa: E402
from tests.test_claims import ClaimsDb                   # noqa: E402

SENDER = "919999000222"
# Meta's wamid, kept ONLY to prove it is refused: it base64-embeds
# the sender's number, so it must never reach a claim.
META_WAMID = "wamid.HBgMOTE5OTk5MDAwMjIyFQIAEhgg"
# The Brain-local message reference the producers actually receive.
MSG_ID = "7e6d5c4b-3a29-4187-9b6a-5c4d3e2f1a0b"
# PII-free fixtures for the derivation proofs: vary only WHO sent the message.
OTHER_SENDER = "918888000111"
SAFE_MSG_ID = "wamid.TEST-NO-EMBEDDED-MSISDN"
WEBSITE_ROW, WEBSITE_SERVICE = "svc_website", "Website / App"


class Harness(unittest.TestCase):
    """Wires party + claims + registry onto one in-memory store, and stubs the
    outbound side of webhook.py so nothing leaves the process."""

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []
        self.leads = []

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
            if table == p.IDENTIFIERS_TABLE:
                row = {**row, "valid_until": None}
                self.identifiers.append(row)
            else:
                self.parties.append(dict(row))

        self._patches = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(p, "insert", party_insert),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
            # Outbound side of the webhook, fully stubbed.
            mock.patch.object(w, "send_text", lambda *a, **k: None),
            mock.patch.object(w, "save_messages", lambda *a, **k: None),
            mock.patch.object(w, "notify_owner", lambda *a, **k: None),
            mock.patch.object(w, "upsert_lead",
                              lambda phone, data: self.leads.append((phone, data))),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            # No service-role key in the test env; the guard is exercised
            # explicitly by test_unconfigured_bic_writes_nothing.
            mock.patch.object(w.bic_config, "is_configured", lambda: True),
        ]
        for x in self._patches:
            x.start()

        # The predicate is registered as DATA, exactly as the seed migration
        # does it — no Python enum mirrors the registry.
        r.register("core.party", "declared_service_interest", 1, "CLASSIFYING",
                   {"type": "enum", "values": [
                       "Social Media ನಿರ್ವಹಣೆ", "Website / App", "Election Campaign",
                       "AI Chatbot", "Digital Ads", "Govt Schemes",
                       "Design & Branding"]},
                   "Declared service interest", cardinality="single")
        r.activate("core.party", "declared_service_interest", 1, "raviraj")

    def tearDown(self):
        for x in reversed(self._patches):
            x.stop()

    def _tap(self, row_id=WEBSITE_ROW, message_id=MSG_ID, sender=SENDER):
        buf = io.StringIO()
        with redirect_stdout(buf):
            w.handle_list_reply(sender, row_id, "title", message_id=message_id)
        return buf.getvalue()

    def _claim_against_fresh_store(self, sender=SENDER, message_id=SAFE_MSG_ID):
        """One claim, written against a brand-new store with no shared rows."""
        self.tearDown()
        self.setUp()
        self._tap(message_id=message_id, sender=sender)
        return dict(self.db.claims[0])


# ── The path ───────────────────────────────────────────────────────────────

class VerticalPath(Harness):

    def test_menu_tap_creates_party_identifier_and_claim(self):
        self._tap()

        self.assertEqual(len(self.parties), 1)
        self.assertEqual(self.parties[0]["kind"], p.PERSON)
        self.assertEqual(self.parties[0]["resolution_state"], p.PROVISIONAL)

        self.assertEqual(len(self.identifiers), 1)
        self.assertEqual(self.identifiers[0]["identifier_class"], p.CONTACT)
        self.assertEqual(self.identifiers[0]["channel"], p.WHATSAPP)

        self.assertEqual(len(self.db.claims), 1)
        claim = self.db.claims[0]
        self.assertEqual(claim["value"], WEBSITE_SERVICE)
        self.assertEqual(claim["subject"], self.parties[0]["knowledge_id"])

    def test_claim_carries_the_approved_provenance(self):
        self._tap()
        claim = self.db.claims[0]
        self.assertEqual(claim["provenance_tier"], 5)
        self.assertEqual(claim["confidence"], 0.50)
        self.assertEqual(claim["asserted_by"], "whatsapp:menu_selection")
        self.assertEqual(claim["source_ref"], f"msg:{MSG_ID}")

    def test_second_tap_reuses_the_same_party(self):
        self._tap()
        self._tap("svc_ads")
        self.assertEqual(len(self.parties), 1)
        self.assertEqual(len(self.db.claims), 2)
        self.assertEqual(len({x["subject"] for x in self.db.claims}), 1)

    def test_later_tap_supersedes_the_earlier_interest(self):
        self._tap()
        self._tap("svc_ads")
        kid = self.parties[0]["knowledge_id"]
        view = c.current(w.bic_config.DEFAULT_TENANT_ID, kid,
                         w.SERVICE_INTEREST_PREDICATE)
        self.assertEqual([x["value"] for x in view["claims"]], ["Digital Ads"])
        self.assertFalse(view["conflict"])

    def test_every_menu_service_is_registered_and_assertable(self):
        """The seed's value space and the live menu cannot drift apart."""
        for row_id in w.CLAIMABLE_SERVICE_ROWS:
            service = w.SERVICE_MENU_REPLIES[row_id][0]
            r.validate_assertion(w.SERVICE_INTEREST_PREDICATE, service)


# ── PII ────────────────────────────────────────────────────────────────────

class NoPii(Harness):

    def test_claim_row_contains_no_phone_and_no_message_text(self):
        """PLAINTEXT absence only — see test_claim_body_does_not_vary_with_the_sender.

        The removed `SENDER[-4:]` ("0222") assertion was probabilistic: the
        blob carries random uuid4s, and a 4-digit run collides often enough
        to fail roughly 1 suite run in 400. Third occurrence of this defect
        in the suite, after test_party.py and test_first_seen_at.py.
        """
        self._tap()
        blob = str(self.db.claims[0])
        self.assertNotIn(SENDER, blob)
        self.assertNotIn("title", blob)

    def test_claim_body_does_not_vary_with_the_sender(self):
        """Nothing outside identity may encode WHO sent the message.

        Deterministic, and unlike a substring check it also catches an
        ENCODED leak — a base64 or hashed sender would differ here while
        passing the plaintext assertion above.
        """
        mine = self._claim_against_fresh_store(sender=SENDER)
        theirs = self._claim_against_fresh_store(sender=OTHER_SENDER)
        # valid_from is WALL CLOCK on this path (unlike first_seen_at, which
        # is handed the instant), so it differs by microseconds between two
        # captures. Excluded from the equality, then proved below to track
        # the clock rather than the sender.
        VARIES_BY_DESIGN = {"claim_id", "subject", "observed_at", "valid_from"}
        self.assertEqual(
            {k: v for k, v in mine.items() if k not in VARIES_BY_DESIGN},
            {k: v for k, v in theirs.items() if k not in VARIES_BY_DESIGN})
        self.assertNotEqual(mine["subject"], theirs["subject"])

        gap = abs(datetime.fromisoformat(mine["valid_from"])
                  - datetime.fromisoformat(theirs["valid_from"]))
        self.assertLess(gap, timedelta(seconds=5))

    def test_claim_identity_is_not_derived_from_the_sender(self):
        """Regeneration proof: a derived subject would repeat across stores."""
        first = self._claim_against_fresh_store()
        second = self._claim_against_fresh_store()
        self.assertNotEqual(first["subject"], second["subject"])
        self.assertNotEqual(first["claim_id"], second["claim_id"])

    def test_phone_appears_only_in_the_identifiers_table(self):
        self._tap()
        self.assertIn(SENDER, str(self.identifiers))
        self.assertNotIn(SENDER, str(self.parties))
        self.assertNotIn(SENDER, str(self.db.claims))

    def test_source_ref_is_a_brain_local_reference(self):
        """The gap this test used to PIN is now closed.

        It previously recorded that source_ref held Meta's wamid, which
        base64-embeds the sender MSISDN. source_ref is now `msg:<uuid4>` —
        a Brain-local reference that carries nothing.
        """
        self._tap()
        ref = self.db.claims[0]["source_ref"]
        self.assertEqual(ref, f"msg:{MSG_ID}")
        self.assertTrue(ref.startswith("msg:"))
        self.assertNotIn(SENDER, ref)
        self.assertNotIn("wamid", ref)

    def test_a_wamid_is_refused_rather_than_stored(self):
        """Passing Meta's id must produce NO source_ref, never a stored wamid."""
        self.tearDown(); self.setUp()
        self._tap(message_id=META_WAMID)
        self.assertIsNone(self.db.claims[0]["source_ref"])

    def test_failure_log_never_leaks_the_identifier(self):
        """DbError embeds the response body, and a unique-violation on the
        identifiers table echoes the phone number."""
        with mock.patch.object(p, "resolve_or_create",
                               side_effect=DbError(f"duplicate key ... {SENDER}")):
            out = self._tap()
        self.assertIn("CLAIM_WRITE_FAILED", out)
        self.assertIn("reason=DbError", out)
        self.assertNotIn(SENDER, out)


# ── Isolation: the claim must never break the business ─────────────────────

class FailureIsolation(Harness):

    def test_identity_failure_does_not_break_lead_capture_or_reply(self):
        with mock.patch.object(p, "resolve_or_create",
                               side_effect=DbError("parties down")):
            out = self._tap()
        self.assertEqual(self.leads, [(SENDER, {"service_needed": WEBSITE_SERVICE})])
        self.assertIn("CLAIM_WRITE_FAILED", out)

    def test_claim_failure_does_not_break_lead_capture(self):
        with mock.patch.object(c, "assert_claim", side_effect=DbError("claims down")):
            self._tap()
        self.assertEqual(len(self.leads), 1)

    def test_registry_rejection_does_not_break_lead_capture(self):
        with mock.patch.object(r, "validate_assertion",
                               side_effect=r.RegistryError("not registered")):
            out = self._tap()
        self.assertEqual(len(self.leads), 1)
        self.assertIn("CLAIM_WRITE_FAILED", out)

    def test_reply_is_sent_before_any_knowledge_work(self):
        order = []
        with mock.patch.object(w, "send_text", lambda *a, **k: order.append("reply")), \
             mock.patch.object(p, "resolve_or_create",
                               side_effect=lambda *a, **k: order.append("party") or "x"):
            with redirect_stdout(io.StringIO()):
                w.handle_list_reply(SENDER, WEBSITE_ROW, "t", message_id=MSG_ID)
        self.assertEqual(order[0], "reply")

    def test_unconfigured_bic_writes_nothing_and_stays_silent(self):
        with mock.patch.object(w.bic_config, "is_configured", lambda: False):
            out = self._tap()
        self.assertEqual(self.db.claims, [])
        self.assertNotIn("CLAIM_WRITE_FAILED", out)
        self.assertEqual(len(self.leads), 1)


# ── D11 ────────────────────────────────────────────────────────────────────

class D11UnknownRow(Harness):

    def test_known_service_row_captures(self):
        self._tap(WEBSITE_ROW)
        self.assertEqual(len(self.leads), 1)
        self.assertEqual(len(self.db.claims), 1)

    def test_svc_other_captures_nothing(self):
        """`svc_other` means "no service determined" — an absence, and an
        absence is never recorded as a value."""
        self._tap("svc_other")
        self.assertEqual(self.leads, [])
        self.assertEqual(self.db.claims, [])

    def test_unknown_row_writes_no_lead_no_claim_and_no_Other(self):
        """THE D11 REGRESSION: an unrecognised id used to fall through to the
        svc_other entry and capture the literal service "Other"."""
        out = self._tap("svc_totally_made_up")
        self.assertEqual(self.leads, [])
        self.assertEqual(self.db.claims, [])
        self.assertNotIn("Other", str(self.leads))
        self.assertIn("MENU_UNKNOWN_ROW", out)

    def test_unknown_row_still_gets_a_reply(self):
        """Customer UX is unchanged — only the CAPTURE is gated."""
        sent = []
        with mock.patch.object(w, "send_text", lambda to, text: sent.append(text)):
            with redirect_stdout(io.StringIO()):
                w.handle_list_reply(SENDER, "svc_bogus", "t")
        self.assertEqual(len(sent), 1)

    def test_malformed_row_id_is_not_logged_verbatim(self):
        out = self._tap("../../etc/passwd\nINJECTED")
        self.assertIn("<malformed>", out)
        self.assertNotIn("INJECTED", out)

    def test_claimable_rows_exclude_svc_other(self):
        self.assertNotIn("svc_other", w.CLAIMABLE_SERVICE_ROWS)
        self.assertEqual(len(w.CLAIMABLE_SERVICE_ROWS), 7)


# ── Read path ──────────────────────────────────────────────────────────────

class OwnerReadPath(Harness):

    def test_read_returns_the_claim_with_derived_status(self):
        self._tap()
        out = w.tool_service_interest(SENDER)
        self.assertIn(WEBSITE_SERVICE, out)
        self.assertIn("ACTIVE", out)
        self.assertIn("tier 5", out)
        self.assertIn("0.5", out)
        self.assertIn(self.parties[0]["knowledge_id"], out)

    def test_read_never_displays_the_phone_number(self):
        self._tap()
        out = w.tool_service_interest(SENDER)
        self.assertNotIn(SENDER, out)

    def test_read_before_any_tap_is_graceful(self):
        self.assertIn("No party record", w.tool_service_interest("919999000999"))

    def test_read_reports_superseded_claims_as_absent_from_current(self):
        self._tap()
        self._tap("svc_ads")
        out = w.tool_service_interest(SENDER)
        self.assertIn("Digital Ads", out)
        self.assertNotIn(WEBSITE_SERVICE, out)

    def test_read_failure_reports_type_only(self):
        with mock.patch.object(p, "find_by_identifier",
                               side_effect=DbError(f"boom {SENDER}")):
            out = w.tool_service_interest(SENDER)
        self.assertIn("DbError", out)
        self.assertNotIn(SENDER, out)


class ReadPathIsGated(unittest.TestCase):
    """The role gate lives in the Tool Registry, not in an inline sender check."""

    def test_tool_is_registered_as_staff_and_not_customer_safe(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260816000007_bic_service_interest_tool.sql")
        with open(path) as fh:
            sql = fh.read()
        self.assertIn("'service_interest'", sql)
        self.assertIn("'STAFF'", sql)
        # customer_safe=false → a CLIENT principal is denied by bic.policy.
        self.assertRegex(sql, r"'STAFF',\s*1,\s*false,\s*false")

    def test_command_routes_through_the_registry_not_a_direct_call(self):
        import inspect
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('run_tool(sender, "service_interest"', src)

    def test_client_cannot_reach_the_command(self):
        """try_owner_command is only reachable from the owner pipeline; a
        CLIENT principal is denied at the registry before the handler runs."""
        from bic import policy
        self.assertFalse(policy.may_invoke(
            policy.Principal("919999000222", "CLIENT", "t"),
            {"code": "service_interest", "min_role": "STAFF",
             "customer_safe": False, "risk_tier": 1})[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
