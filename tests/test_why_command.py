"""`#why` — OWNER customer context → describe → explain → render.

WHY THIS FILE WAS REWRITTEN
---------------------------
The first version resolved the party bound to the CURRENT CONVERSATION. That
was technically correct and practically useless: for an owner it resolves to
the owner's own party, which does not exist and never will, so production
returned "cannot identify a customer" — correctly — and describe→explain never
ran. The subject now comes from owner context, and the tests that asserted the
old conversation-based behaviour are gone because that behaviour is gone.

WHAT THESE TESTS GUARD
----------------------
Mostly the subject-selection boundary. An explanation attached to the WRONG
customer is worse than no explanation: it is confident, specific, and about
somebody else. So the tests below care less about prose than about which party
was chosen, on what evidence, and whether the system ever picks silently.

Fixtures are the real production claim shapes. Offline: no network, no AI,
no database.
"""

import ast
import inspect
import io
import os
import sys
import textwrap
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                                  # noqa: E402
from bic import claims as c, explain as bx, knowledge as k           # noqa: E402
from bic import owner_context as oc, party as p, policy              # noqa: E402
from bic import registry as r                                        # noqa: E402
from bic.db import DbError                                           # noqa: E402
from tests.test_claims import ClaimsDb                               # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
OWNER = "910000000001"

CUST_A = "805d1c4e-0000-4000-8000-000000000001"   # two facts
CUST_B = "d542ac32-0000-4000-8000-000000000002"   # partial knowledge
PHONE_A, PHONE_B = "919999000111", "919999000222"

INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"
SEGMENT = "core.party.engagement_segment@1"
SOCIAL = "Social Media ನಿರ್ವಹಣೆ"
SERVICES = [SOCIAL, "Website / App", "Election Campaign", "AI Chatbot",
            "Digital Ads", "Govt Schemes", "Design & Branding"]

DESCRIPTOR = {"code": "knowledge_why", "min_role": "OWNER",
              "customer_safe": False, "risk_tier": 1, "active": True}


def code_only(obj) -> str:
    """Source with docstrings, comments and string literals blanked.

    A raw search finds a forbidden token inside the DOCSTRING that explains why
    it is forbidden. This has bitten the project repeatedly; negative
    assertions read this, positive assertions read the raw source.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value=""), node)
            return node

    return ast.unparse(Blank().visit(tree))


def ts(text):
    return datetime.fromisoformat(text + "+00:00")


def now():
    return datetime.now(timezone.utc)


class Harness(unittest.TestCase):

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers, self.invocations = [], [], []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for key, val in params.items():
                    if key in ("order", "limit", "select"):
                        continue
                    val = str(val)
                    if val == "is.null" and row.get(key) is not None:
                        keep = False
                    elif val.startswith("eq.") and str(row.get(key)) != val[3:]:
                        keep = False
                if keep:
                    out.append(dict(row))
            return out

        def oc_select(table, params, timeout=None):
            limit = int(params.get("limit", 100))
            if table == oc.INVOCATIONS_TABLE:
                rows = []
                for row in self.invocations:
                    ok = True
                    for key, val in params.items():
                        if key in ("order", "limit", "select"):
                            continue
                        val = str(val)
                        if val.startswith("eq.") and str(row.get(key)) != val[3:]:
                            ok = False
                        elif val.startswith("in.") and str(row.get(key)) not in \
                                val[4:-1].split(","):
                            ok = False
                        elif val == "is.true" and row.get(key) is not True:
                            ok = False
                    if ok:
                        rows.append(dict(row))
                rows.sort(key=lambda x: x["created_at"], reverse=True)
                return rows[:limit]
            if table == oc.CLAIMS_TABLE:
                tenant = str(params.get("tenant_id", "")).replace("eq.", "")
                rows = [dict(x) for x in self.db.claims
                        if str(x.get("tenant_id")) == tenant]
                rows.sort(key=lambda x: x["observed_at"], reverse=True)
                return rows[:limit]
            raise AssertionError(f"unexpected table {table}")

        self._patches = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(oc, "select", oc_select),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w.bic_config, "is_configured", lambda: True),
            mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", TENANT),
            mock.patch.object(w, "send_text", lambda *a, **kw: None),
        ]
        for patch in self._patches:
            patch.start()

        for ns, concept, cat, vol in (
                ("core.party", "declared_service_interest", "CLASSIFYING", "slow"),
                ("core.party", "engagement_segment", "CLASSIFYING", "slow"),
                ("core.party", "first_seen_at", "TEMPORAL", "static")):
            space = ({"type": "enum", "values": SERVICES}
                     if concept == "declared_service_interest" else
                     {"type": "enum", "values": ["VIP", "ELECTION"]}
                     if concept == "engagement_segment" else
                     {"type": "timestamp"})
            r.register(ns, concept, 1, cat, space, concept.replace("_", " "),
                       cardinality="single", volatility_class=vol,
                       applies_to=["PERSON", "ORGANIZATION"])
            r.activate(ns, concept, 1, "raviraj")

        for kid, phone in ((CUST_A, PHONE_A), (CUST_B, PHONE_B)):
            self.parties.append({"knowledge_id": kid, "tenant_id": TENANT,
                                 "kind": p.PERSON,
                                 "resolution_state": p.PROVISIONAL,
                                 "merged_into": None})
            self.identifiers.append({"tenant_id": TENANT, "party_id": kid,
                                     "identifier_class": p.CONTACT,
                                     "channel": p.WHATSAPP,
                                     "identifier_value": phone,
                                     "valid_until": None})

        # Real production claim shapes.
        c.assert_claim(TENANT, CUST_A, FIRST_SEEN,
                       "2026-08-18T16:07:48.492062+00:00", source="whatsapp",
                       provenance_tier=1, asserted_by="whatsapp:first_contact",
                       confidence=0.90, source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T16:07:48.492062"),
                       observed_at=ts("2026-08-18T16:07:48.997941"))
        c.assert_claim(TENANT, CUST_A, INTEREST, "Design & Branding",
                       source="whatsapp", provenance_tier=5,
                       asserted_by="whatsapp:menu_selection", confidence=0.50,
                       source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T16:08:15.536992"),
                       observed_at=ts("2026-08-18T16:08:15.536992"))
        c.assert_claim(TENANT, CUST_B, INTEREST, SOCIAL, source="whatsapp",
                       provenance_tier=5, asserted_by="whatsapp:menu_selection",
                       confidence=0.50, source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T11:07:50.829544"),
                       observed_at=ts("2026-08-18T11:07:50.829544"))

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()

    def owner_took_over(self, phone, when=None, tool="chat_pause", ok=True,
                        role="OWNER"):
        self.invocations.append({
            "tenant_id": TENANT, "tool": tool, "role": role, "ok": ok,
            "args_redacted": {"target": phone},
            "created_at": (when or now()).isoformat(),
        })

    def why(self, sender=OWNER, **kwargs):
        with redirect_stdout(io.StringIO()):
            return w.tool_knowledge_why(sender, **kwargs)


# ── 1. Owner context created ───────────────────────────────────────────────

class ContextCreated(Harness):

    def test_an_owner_takeover_creates_context(self):
        self.owner_took_over(PHONE_A)
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.OWNER_ACTION)
        self.assertEqual(ctx["party_id"], CUST_A)
        self.assertEqual(ctx["source"], "chat_pause")

    def test_chat_resume_also_creates_context(self):
        self.owner_took_over(PHONE_B, tool="chat_resume")
        self.assertEqual(oc.resolve(TENANT)["party_id"], CUST_B)

    def test_context_reports_its_age_and_ttl(self):
        self.owner_took_over(PHONE_A, when=now() - timedelta(hours=2))
        ctx = oc.resolve(TENANT)
        self.assertGreaterEqual(ctx["age_seconds"], 7100)
        self.assertEqual(ctx["expires_after_seconds"], 86400)

    def test_a_failed_invocation_creates_no_context(self):
        self.owner_took_over(PHONE_A, ok=False)
        self.assertNotEqual(oc.resolve(TENANT)["state"], oc.OWNER_ACTION)

    def test_a_non_owner_invocation_creates_no_owner_context(self):
        self.owner_took_over(PHONE_A, role="STAFF")
        self.assertNotEqual(oc.resolve(TENANT)["state"], oc.OWNER_ACTION)


# ── 2. `#why` uses the current customer ────────────────────────────────────

class WhyUsesCurrentCustomer(Harness):

    def test_why_explains_the_customer_the_owner_took_over(self):
        self.owner_took_over(PHONE_A)
        out = self.why()
        self.assertIn(CUST_A, out)
        self.assertNotIn(CUST_B, out)
        self.assertIn("Design & Branding", out)

    def test_why_never_falls_back_to_owner_self_identity(self):
        """The owner has no party; answering about them would silently change
        the subject of the question."""
        out = self.why()
        self.assertNotIn(OWNER, out)
        src = code_only(w.tool_knowledge_why)
        self.assertNotIn("find_by_identifier", src)

    def test_the_selecting_signal_is_named_in_the_reply(self):
        self.owner_took_over(PHONE_A)
        self.assertIn("selected by: you", self.why())

    def test_the_weaker_signal_is_labelled_as_weaker(self):
        out = self.why()      # no owner action → recent activity
        self.assertIn("not an explicit choice", out)

    def test_full_explanation_renders_for_the_selected_customer(self):
        self.owner_took_over(PHONE_A)
        out = self.why()
        self.assertIn(FIRST_SEEN, out)
        self.assertIn(INTEREST, out)
        self.assertIn("tier 1 (cap 0.9)", out)
        self.assertIn("tier 5 (cap 0.5)", out)
        self.assertIn("PERMANENT (static)", out)
        self.assertIn("FRESH (slow)", out)
        self.assertIn("Confidence vector", out)


# ── 3. Latest context wins, deterministically ──────────────────────────────

class LatestWins(Harness):

    def test_the_most_recent_takeover_wins(self):
        self.owner_took_over(PHONE_B, when=now() - timedelta(hours=3))
        self.owner_took_over(PHONE_A, when=now() - timedelta(minutes=5))
        self.assertEqual(oc.resolve(TENANT)["party_id"], CUST_A)

    def test_ordering_is_by_time_not_insertion(self):
        self.owner_took_over(PHONE_A, when=now() - timedelta(minutes=5))
        self.owner_took_over(PHONE_B, when=now() - timedelta(hours=3))
        self.assertEqual(oc.resolve(TENANT)["party_id"], CUST_A)

    def test_owner_action_outranks_recent_activity(self):
        """CUST_B was taken over; CUST_A has the newer claim. The explicit
        signal must win."""
        self.owner_took_over(PHONE_B)
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.OWNER_ACTION)
        self.assertEqual(ctx["party_id"], CUST_B)

    def test_resolution_is_repeatable(self):
        self.owner_took_over(PHONE_A)
        self.assertEqual({oc.resolve(TENANT)["party_id"] for _ in range(5)},
                         {CUST_A})


# ── 4. Expiry ──────────────────────────────────────────────────────────────

class Expiry(Harness):

    def test_an_expired_takeover_is_not_used(self):
        self.owner_took_over(PHONE_B, when=now() - timedelta(hours=25))
        ctx = oc.resolve(TENANT)
        self.assertNotEqual(ctx["state"], oc.OWNER_ACTION)

    def test_expired_context_falls_through_to_recent_activity(self):
        self.owner_took_over(PHONE_B, when=now() - timedelta(hours=25))
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.RECENT_ACTIVITY)
        self.assertEqual(ctx["party_id"], CUST_A)

    def test_just_inside_the_window_still_counts(self):
        self.owner_took_over(PHONE_B, when=now() - timedelta(hours=23))
        self.assertEqual(oc.resolve(TENANT)["state"], oc.OWNER_ACTION)

    def test_the_ttl_is_the_products_own_pause_window(self):
        """24h is borrowed from chat_pause's auto-resume, not invented here."""
        self.assertEqual(oc.OWNER_ACTION_TTL, timedelta(hours=24))

    def test_recent_activity_does_not_expire_but_reports_age(self):
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.RECENT_ACTIVITY)
        self.assertIsNone(ctx["expires_after_seconds"])
        self.assertGreater(ctx["age_seconds"], 0)


# ── 5. No context ──────────────────────────────────────────────────────────

class NoContext(Harness):

    def test_no_action_and_no_claims_is_none(self):
        self.db.claims.clear()
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.NONE)
        self.assertEqual(ctx["reason"], oc.R_NO_ACTION_NO_CLAIMS)

    def test_why_says_no_customer_is_selected(self):
        self.db.claims.clear()
        out = self.why()
        self.assertIn("No customer is currently selected", out)
        self.assertIn("not a permission problem", out)
        self.assertIn("not an outage", out)

    def test_a_takeover_of_someone_with_no_party_is_reported_not_skipped(self):
        """Falling through to an older action would silently answer about a
        DIFFERENT customer than the one the owner last chose."""
        self.owner_took_over(PHONE_A, when=now() - timedelta(hours=2))
        self.owner_took_over("919999000999", when=now() - timedelta(minutes=1))
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.NONE)
        self.assertEqual(ctx["reason"], oc.R_SELECTED_HAS_NO_PARTY)
        self.assertIsNone(ctx["party_id"])

    def test_that_case_never_answers_about_the_older_customer(self):
        self.owner_took_over(PHONE_A, when=now() - timedelta(hours=2))
        self.owner_took_over("919999000999", when=now() - timedelta(minutes=1))
        out = self.why()
        self.assertNotIn(CUST_A, out)
        self.assertIn("No customer is currently selected", out)


# ── 6. Two simultaneous customers ──────────────────────────────────────────

class Ambiguity(Harness):

    def test_two_takeovers_at_the_same_instant_are_ambiguous(self):
        stamp = now() - timedelta(minutes=1)
        self.owner_took_over(PHONE_A, when=stamp)
        self.owner_took_over(PHONE_B, when=stamp)
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.AMBIGUOUS)
        self.assertEqual(ctx["reason"], oc.R_TWO_OWNER_ACTIONS)

    def test_nothing_is_chosen(self):
        stamp = now() - timedelta(minutes=1)
        self.owner_took_over(PHONE_A, when=stamp)
        self.owner_took_over(PHONE_B, when=stamp)
        ctx = oc.resolve(TENANT)
        self.assertIsNone(ctx["party_id"])
        self.assertEqual(sorted(ctx["candidates"]), sorted([CUST_A, CUST_B]))

    def test_two_parties_sharing_the_newest_observation_are_ambiguous(self):
        stamp = ts("2026-08-19T10:00:00.000000")
        for subject in (CUST_A, CUST_B):
            c.assert_claim(TENANT, subject, SEGMENT, "VIP", source="whatsapp",
                           provenance_tier=5, asserted_by="whatsapp:keyword",
                           confidence=0.50, source_ref="wa_msg:<withheld>",
                           valid_from=stamp, observed_at=stamp)
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.AMBIGUOUS)
        self.assertEqual(ctx["reason"], oc.R_TWO_ACTIVE_PARTIES)
        self.assertIsNone(ctx["party_id"])

    def test_why_surfaces_the_ambiguity_and_explains_nothing(self):
        stamp = now() - timedelta(minutes=1)
        self.owner_took_over(PHONE_A, when=stamp)
        self.owner_took_over(PHONE_B, when=stamp)
        out = self.why()
        self.assertIn("Two customers are equally current", out)
        self.assertIn(CUST_A, out)
        self.assertIn(CUST_B, out)
        self.assertNotIn("Design & Branding", out)

    def test_the_ambiguity_message_says_how_to_resolve_it(self):
        stamp = now() - timedelta(minutes=1)
        self.owner_took_over(PHONE_A, when=stamp)
        self.owner_took_over(PHONE_B, when=stamp)
        self.assertIn("#stop", self.why())


# ── 7. Tenant isolation ────────────────────────────────────────────────────

class TenantIsolation(Harness):

    def test_another_tenants_owner_action_is_invisible(self):
        self.invocations.append({
            "tenant_id": OTHER_TENANT, "tool": "chat_pause", "role": "OWNER",
            "ok": True, "args_redacted": {"target": PHONE_A},
            "created_at": now().isoformat()})
        ctx = oc.resolve(TENANT)
        self.assertEqual(ctx["state"], oc.RECENT_ACTIVITY)

    def test_another_tenant_sees_no_context_here(self):
        self.owner_took_over(PHONE_A)
        ctx = oc.resolve(OTHER_TENANT)
        self.assertEqual(ctx["state"], oc.NONE)
        self.assertIsNone(ctx["party_id"])

    def test_no_cross_tenant_claim_leak(self):
        ctx = oc.resolve(OTHER_TENANT)
        self.assertNotIn(CUST_A, repr(ctx))
        self.assertNotIn(CUST_B, repr(ctx))


# ── 8-9. Authorization ─────────────────────────────────────────────────────

class Authorization(Harness):

    def test_owner_allowed(self):
        self.assertTrue(policy.may_invoke(
            policy.Principal(OWNER, "OWNER", TENANT), DESCRIPTOR)[0])

    def test_staff_denied(self):
        allowed, reason = policy.may_invoke(
            policy.Principal(OWNER, "STAFF", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertIn("OWNER", reason)

    def test_client_denied(self):
        allowed, reason = policy.may_invoke(
            policy.Principal("919999000777", "CLIENT", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertEqual(reason, "not customer-safe")

    def test_denial_reveals_no_knowledge(self):
        reason = policy.may_invoke(
            policy.Principal(OWNER, "CLIENT", TENANT), DESCRIPTOR)[1]
        for secret in (CUST_A, CUST_B, "Design & Branding"):
            self.assertNotIn(secret, reason)

    def test_no_second_authorization_path_in_the_handler(self):
        src = code_only(w.tool_knowledge_why)
        for smell in ("OWNER_PHONE", "min_role", "is_owner", "role =="):
            self.assertNotIn(smell, src)

    def test_context_resolution_never_authorizes(self):
        src = code_only(oc)
        for smell in ("may_invoke", "min_role", "customer_safe", "Principal"):
            self.assertNotIn(smell, src)


# ── 10-11. Call order ──────────────────────────────────────────────────────

class CallOrder(Harness):

    def test_context_then_describe_then_explain(self):
        self.owner_took_over(PHONE_A)
        order = []
        real_resolve, real_describe, real_explain = (
            oc.resolve, k.describe, bx.explain)

        def spy_ctx(*a, **kw):
            order.append("context"); return real_resolve(*a, **kw)

        def spy_desc(*a, **kw):
            order.append("describe"); return real_describe(*a, **kw)

        def spy_exp(*a, **kw):
            order.append("explain"); return real_explain(*a, **kw)

        with mock.patch.object(w.bic_owner_context, "resolve", spy_ctx), \
             mock.patch.object(w.bic_knowledge, "describe", spy_desc), \
             mock.patch.object(w.bic_explain, "explain", spy_exp):
            self.why()
        self.assertEqual(order, ["context", "describe", "explain"])

    def test_describe_receives_the_context_party(self):
        self.owner_took_over(PHONE_B)
        seen = {}
        real = k.describe

        def spy(tenant, entity, *a, **kw):
            seen["entity"] = entity
            return real(tenant, entity, *a, **kw)

        with mock.patch.object(w.bic_knowledge, "describe", spy):
            self.why()
        self.assertEqual(seen["entity"], CUST_B)

    def test_explain_receives_the_describe_envelope(self):
        self.owner_took_over(PHONE_A)
        seen = {}
        real = bx.explain

        def spy(evidence, **kw):
            seen["evidence"] = evidence
            return real(evidence, **kw)

        with mock.patch.object(w.bic_explain, "explain", spy):
            self.why()
        self.assertEqual(seen["evidence"]["capability"], "knowledge.describe")
        self.assertEqual(seen["evidence"]["subject"], CUST_A)

    def test_describe_is_never_called_without_context(self):
        self.db.claims.clear()
        called = []
        with mock.patch.object(w.bic_knowledge, "describe",
                               lambda *a, **kw: called.append(a)):
            self.why()
        self.assertEqual(called, [])


# ── 12-14. What context resolution must NOT do ─────────────────────────────

class ContextDiscipline(Harness):

    def test_no_phone_input_is_required_from_the_owner(self):
        self.owner_took_over(PHONE_A)
        self.assertIn(CUST_A, self.why())
        params = inspect.signature(w.tool_knowledge_why).parameters
        self.assertNotIn("target", params)
        self.assertNotIn("phone", params)

    def test_the_command_takes_no_argument(self):
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('if low == "#why"', src)
        self.assertNotIn('#why ', src.split('if low == "#why"')[1][:200])

    def test_no_fuzzy_matching(self):
        src = code_only(oc).lower()
        for smell in ("fuzzy", "similar", "levenshtein", "ilike", "like.",
                      "distance", "best_match", "score"):
            self.assertNotIn(smell, src)

    def test_no_ai_selects_the_context(self):
        src = code_only(oc).lower()
        for provider in ("openai", "gemini", "groq", "openrouter", "deepseek",
                         "anthropic", "model", "prompt", "llm", "embed"):
            self.assertNotIn(provider, src)

    def test_exactly_one_identifier_lookup_path(self):
        src = code_only(oc)
        self.assertIn("find_by_identifier", src)
        for banned in ("resolve_or_create", "create(", "bind_identifier"):
            self.assertNotIn(banned, src)

    def test_context_writes_nothing(self):
        src = code_only(oc)
        for banned in ("insert", "update", "assert_claim", "delete"):
            self.assertNotIn(banned, src)

    def test_the_scan_is_bounded(self):
        self.assertLessEqual(oc._SCAN_LIMIT, 50)


# ── Failure states still distinct ──────────────────────────────────────────

class FailureStates(Harness):

    def test_context_outage_is_not_rendered_as_no_customer(self):
        with mock.patch.object(w.bic_owner_context, "resolve",
                               side_effect=DbError(f"boom {OWNER}")):
            out = self.why()
        self.assertIn("DbError", out)
        self.assertNotIn("No customer is currently selected", out)
        self.assertNotIn(OWNER, out)

    def test_unknown_renders_distinctly(self):
        self.owner_took_over(PHONE_A)
        for claim in list(self.db.claims):
            if claim["subject"] == CUST_A:
                self.db.claims.remove(claim)
        out = self.why()
        self.assertIn("UNKNOWN", out)
        self.assertIn("Nothing is inferred from the absence", out)

    def test_unavailable_renders_distinctly(self):
        self.owner_took_over(PHONE_A)
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            out = self.why()
        self.assertIn("UNAVAILABLE", out)
        self.assertIn("NOT an absence of knowledge", out)

    def test_knowledge_failure_reports_the_type_only(self):
        self.owner_took_over(PHONE_A)
        with mock.patch.object(w.bic_knowledge, "describe",
                               side_effect=RuntimeError(f"boom {PHONE_A}")):
            out = self.why()
        self.assertIn("RuntimeError", out)
        self.assertNotIn(PHONE_A, out)

    def test_explain_failure_reports_the_type_only(self):
        self.owner_took_over(PHONE_A)
        with mock.patch.object(w.bic_explain, "explain",
                               side_effect=RuntimeError(f"boom {PHONE_A}")):
            out = self.why()
        self.assertIn("RuntimeError", out)
        self.assertNotIn(PHONE_A, out)

    def test_the_four_outcomes_render_differently(self):
        self.owner_took_over(PHONE_A)
        known = self.why()
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            unavailable = self.why()
        self.invocations.clear(); self.db.claims.clear()
        none_ctx = self.why()
        with mock.patch.object(w.bic_owner_context, "resolve",
                               side_effect=DbError("x")):
            outage = self.why()
        self.assertEqual(len({known, unavailable, none_ctx, outage}), 4)


# ── Conflicts survive ──────────────────────────────────────────────────────

class Conflicts(Harness):

    def _conflict(self):
        self.owner_took_over(PHONE_A)
        stamp = ts("2026-08-18T16:08:15.536992")
        c.assert_claim(TENANT, CUST_A, INTEREST, "Digital Ads",
                       source="whatsapp", provenance_tier=5,
                       asserted_by="whatsapp:menu_selection", confidence=0.50,
                       source_ref="wa_msg:<withheld>",
                       valid_from=stamp, observed_at=stamp)
        return self.why()

    def test_conflict_is_stated(self):
        out = self._conflict()
        self.assertIn("EVIDENCE CONFLICTS", out)
        self.assertIn("No value has been selected", out)

    def test_both_values_shown(self):
        out = self._conflict()
        self.assertIn("Design & Branding", out)
        self.assertIn("Digital Ads", out)

    def test_degraded_shown(self):
        self.assertIn("Degraded", self._conflict())


# ── Narration fallback ─────────────────────────────────────────────────────

class NarrationFallback(Harness):

    def setUp(self):
        super().setUp()
        self.owner_took_over(PHONE_A)

    def test_crashing_narrator_does_not_fail_the_command(self):
        def boom(brief):
            raise RuntimeError("provider down: prompt was 'secret internal'")
        out = self.why(narrator=boom)
        self.assertIn("Design & Branding", out)
        self.assertNotIn("secret internal", out)

    def test_rejected_narration_falls_back(self):
        out = self.why(narrator=lambda b: "There are 7 open projects.")
        self.assertIn("Narration refused", out)
        self.assertIn("Design & Branding", out)

    def test_certainty_language_refused(self):
        out = self.why(narrator=lambda b: "We are certain about this.")
        self.assertIn("certainty_language", out)
        self.assertNotIn("We are certain", out)

    def test_faithful_narration_is_appended(self):
        out = self.why(narrator=lambda b: "Two facts are on record.")
        self.assertIn("Two facts are on record.", out)
        self.assertIn("tier 1 (cap 0.9)", out)


# ── PII ────────────────────────────────────────────────────────────────────

class NoPii(Harness):

    def setUp(self):
        super().setUp()
        self.owner_took_over(PHONE_A)

    def test_no_phone_in_the_reply(self):
        out = self.why()
        for phone in (OWNER, PHONE_A, PHONE_B):
            self.assertNotIn(phone, out)

    def test_no_raw_source_ref_or_wamid(self):
        out = self.why()
        self.assertNotIn("source_ref", out)
        self.assertNotIn("wamid", out)
        self.assertNotIn("<withheld>", out)

    def test_only_the_source_scheme_is_shown(self):
        self.assertIn("via wa_msg", self.why())

    def test_context_object_carries_no_phone(self):
        ctx = oc.resolve(TENANT)
        self.assertNotIn(PHONE_A, repr(ctx))

    def test_ambiguous_candidates_are_opaque_ids_only(self):
        stamp = now() - timedelta(minutes=1)
        self.invocations.clear()
        self.owner_took_over(PHONE_A, when=stamp)
        self.owner_took_over(PHONE_B, when=stamp)
        out = self.why()
        for phone in (PHONE_A, PHONE_B):
            self.assertNotIn(phone, out)

    def test_no_email_shape(self):
        import re
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.why()))


# ── 15-17. Nothing else moved ──────────────────────────────────────────────

class NoRegression(unittest.TestCase):

    def test_interest_unchanged(self):
        src = code_only(w.tool_service_interest)
        self.assertIn("bic_knowledge.describe", src)
        self.assertNotIn("explain", src)
        self.assertNotIn("owner_context", src)

    def test_interest_still_uses_conversation_identity(self):
        """#interest is about the CALLER's own claims and must keep resolving
        the sender; only #why changed subject."""
        self.assertIn("find_by_identifier", code_only(w.tool_service_interest))

    def test_customer_facing_renderer_unchanged(self):
        self.assertNotIn("owner_context", code_only(w.render_knowledge))
        self.assertNotIn("explain", code_only(w.render_knowledge))

    def test_decision_records_untouched(self):
        import bic.decision as decision
        self.assertNotIn("owner_context", code_only(decision))
        self.assertNotIn("knowledge_why", code_only(decision))

    def test_d2_webhook_dedupe_untouched(self):
        import bic.webhook_events as events
        self.assertNotIn("owner_context", code_only(events))
        self.assertNotIn("knowledge_why", code_only(events))

    def test_replay_untouched(self):
        import bic.replay as replay
        self.assertNotIn("owner_context", code_only(replay))

    def test_describe_and_explain_untouched(self):
        for module in (k, bx):
            self.assertNotIn("owner_context", code_only(module))

    def test_claims_and_party_untouched(self):
        for module in (c, p):
            self.assertNotIn("owner_context", code_only(module))

    def test_help_lists_why(self):
        self.assertIn("#why", w.OWNER_COMMANDS_HELP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
