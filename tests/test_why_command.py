"""`#why` — the first real consumer of the 2G EXPLAIN capability.

WHAT THIS SLICE IS FOR
----------------------
IDD-2G §7.4: "Explanation must be user-facing. Kept as an internal debug tool,
it decays unnoticed. Users notice when an explanation is wrong." knowledge.explain
existed with no caller, which is the 1A failure mode — a store nobody reads.
This command is what makes it real.

THE ORDER IS THE GUARANTEE
--------------------------
    identify party → knowledge.describe → knowledge.explain → render

A model that ran before retrieval could choose which facts to look for, and an
explanation of facts chosen to fit a story is the "plausible fiction" §7.4
exists to prevent. Several tests below assert the ORDER, not just the output.

Fixtures are the five real production claims already validated against the
live database. Offline: no network, no AI, no database.
"""

import ast
import copy
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
from bic import party as p, policy, registry as r                    # noqa: E402
from bic.db import DbError                                           # noqa: E402
from tests.test_claims import ClaimsDb                               # noqa: E402


def code_only(obj) -> str:
    """Source with every docstring, comment and string literal blanked.

    Searching raw source for a forbidden token finds it in the DOCSTRING that
    explains why the token is forbidden, and reports a violation that does not
    exist. This has now bitten this project repeatedly: `drop` inside "prose
    dropped", `run_tool` inside "never through run_tool()", `guess` inside
    "nothing is guessed". A test that reads English is not a test of code.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value=""), node)
            return node

    return ast.unparse(Blank().visit(tree))


TENANT = "00000000-0000-0000-0000-000000000001"
OWNER = "910000000001"
STRANGER = "919999000777"
FULL = "805d1c4e-0000-4000-8000-000000000001"
PART = "d542ac32-0000-4000-8000-000000000002"

INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"
SEGMENT = "core.party.engagement_segment@1"
SOCIAL = "Social Media ನಿರ್ವಹಣೆ"
SERVICES = [SOCIAL, "Website / App", "Election Campaign", "AI Chatbot",
            "Digital Ads", "Govt Schemes", "Design & Branding"]


def ts(text):
    return datetime.fromisoformat(text + "+00:00")


class Harness(unittest.TestCase):
    """party + claims + registry on one in-memory store, outbound stubbed."""

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for key, val in params.items():
                    if key in ("order", "limit"):
                        continue
                    val = str(val)
                    if val == "is.null" and row.get(key) is not None:
                        keep = False
                    elif val.startswith("eq.") and str(row.get(key)) != val[3:]:
                        keep = False
                if keep:
                    out.append(dict(row))
            return out

        self._patches = [
            mock.patch.object(p, "select", party_select),
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

        r.register("core.party", "declared_service_interest", 1, "CLASSIFYING",
                   {"type": "enum", "values": SERVICES},
                   "Declared service interest", cardinality="single",
                   volatility_class="slow", applies_to=["PERSON", "ORGANIZATION"])
        r.activate("core.party", "declared_service_interest", 1, "raviraj")
        r.register("core.party", "engagement_segment", 1, "CLASSIFYING",
                   {"type": "enum", "values": ["VIP", "ELECTION"]},
                   "Engagement segment", cardinality="single",
                   volatility_class="slow", applies_to=["PERSON", "ORGANIZATION"])
        r.activate("core.party", "engagement_segment", 1, "raviraj")
        r.register("core.party", "first_seen_at", 1, "TEMPORAL",
                   {"type": "timestamp"}, "First seen at", cardinality="single",
                   volatility_class="static", applies_to=["PERSON", "ORGANIZATION"])
        r.activate("core.party", "first_seen_at", 1, "raviraj")

        # The two real production parties.
        for kid, phone in ((FULL, OWNER), (PART, "919999000555")):
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
        c.assert_claim(TENANT, FULL, FIRST_SEEN,
                       "2026-08-18T16:07:48.492062+00:00", source="whatsapp",
                       provenance_tier=1, asserted_by="whatsapp:first_contact",
                       confidence=0.90, source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T16:07:48.492062"),
                       observed_at=ts("2026-08-18T16:07:48.997941"))
        c.assert_claim(TENANT, FULL, INTEREST, "Design & Branding",
                       source="whatsapp", provenance_tier=5,
                       asserted_by="whatsapp:menu_selection", confidence=0.50,
                       source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T16:08:15.536992"),
                       observed_at=ts("2026-08-18T16:08:15.536992"))
        c.assert_claim(TENANT, PART, INTEREST, SOCIAL, source="whatsapp",
                       provenance_tier=5, asserted_by="whatsapp:menu_selection",
                       confidence=0.50, source_ref="wa_msg:<withheld>",
                       valid_from=ts("2026-08-18T11:07:50.829544"),
                       observed_at=ts("2026-08-18T11:07:50.829544"))

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()

    def why(self, sender=OWNER, **kwargs):
        with redirect_stdout(io.StringIO()):
            return w.tool_knowledge_why(sender, **kwargs)


# ── 1-2. Authorization through the ONE existing gate ───────────────────────

DESCRIPTOR = {"code": "knowledge_why", "min_role": "OWNER",
              "customer_safe": False, "risk_tier": 1, "active": True}


class Authorization(Harness):

    def test_owner_is_allowed(self):
        self.assertTrue(policy.may_invoke(
            policy.Principal(OWNER, "OWNER", TENANT), DESCRIPTOR)[0])

    def test_staff_is_denied_because_the_command_is_owner_only(self):
        allowed, reason = policy.may_invoke(
            policy.Principal(OWNER, "STAFF", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertIn("OWNER", reason)

    def test_client_is_denied(self):
        allowed, reason = policy.may_invoke(
            policy.Principal(STRANGER, "CLIENT", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertEqual(reason, "not customer-safe")

    def test_unknown_tenant_is_denied(self):
        self.assertFalse(policy.may_invoke(
            policy.Principal(OWNER, "OWNER", ""), DESCRIPTOR)[0])

    def test_denial_does_not_reveal_whether_knowledge_exists(self):
        """The registry refuses before the handler runs, so the refusal text
        cannot depend on what is stored."""
        denied = policy.may_invoke(
            policy.Principal(OWNER, "CLIENT", TENANT), DESCRIPTOR)[1]
        self.assertNotIn("Design & Branding", denied)
        self.assertNotIn(FULL, denied)

    def test_the_command_routes_through_the_registry(self):
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('run_tool(sender, "knowledge_why"', src)

    def test_no_phone_number_is_hardcoded_in_the_handler(self):
        import re
        self.assertIsNone(re.search(r"\b\d{10,15}\b",
                                    code_only(w.tool_knowledge_why)))

    def test_there_is_no_second_authorization_path(self):
        src = code_only(w.tool_knowledge_why)
        for smell in ("OWNER_PHONE", "min_role", "role ==", "is_owner"):
            self.assertNotIn(smell, src)


# ── 3. Party identification ────────────────────────────────────────────────

class PartyIdentification(Harness):

    def test_the_party_comes_from_the_conversation_not_from_typed_input(self):
        out = self.why(OWNER)
        self.assertIn(FULL, out)

    def test_the_owner_never_supplies_a_phone_number(self):
        self.assertEqual(w.try_owner_command(OWNER, "OWNER", "#why") is None, False)
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('if low == "#why"', src)

    def test_an_unmapped_conversation_returns_a_deterministic_refusal(self):
        out = self.why(STRANGER)
        self.assertIn("Cannot identify a customer", out)

    def test_the_refusal_is_neither_a_denial_nor_an_outage(self):
        out = self.why(STRANGER)
        self.assertIn("not a permission problem", out)
        self.assertIn("not an outage", out)

    def test_nothing_is_guessed_from_conversation_text(self):
        """2D matching is not implemented and must not be improvised."""
        src = code_only(w.tool_knowledge_why).lower()
        for smell in ("fuzzy", "similar", "guess", "best_match", "levenshtein"):
            self.assertNotIn(smell, src)

    def test_identity_errors_report_the_type_only(self):
        with mock.patch.object(p, "find_by_identifier",
                               side_effect=DbError(f"boom {OWNER}")):
            out = self.why(OWNER)
        self.assertIn("DbError", out)
        self.assertNotIn(OWNER, out)


# ── 4-5. The real production parties ───────────────────────────────────────

class RealProductionAcceptance(Harness):

    def test_two_fact_party_demonstrates_both_facts(self):
        out = self.why(OWNER)
        self.assertIn(FIRST_SEEN, out)
        self.assertIn(INTEREST, out)
        self.assertIn("Design & Branding", out)
        self.assertIn("2026-08-18T16:07:48.492062+00:00", out)

    def test_two_fact_party_preserves_both_tiers_and_confidences(self):
        out = self.why(OWNER)
        self.assertIn("tier 1 (cap 0.9)", out)
        self.assertIn("tier 5 (cap 0.5)", out)
        self.assertIn("confidence 0.9", out)
        self.assertIn("confidence 0.5", out)

    def test_two_fact_party_preserves_freshness_per_predicate(self):
        out = self.why(OWNER)
        self.assertIn("PERMANENT (static)", out)
        self.assertIn("FRESH (slow)", out)

    def test_partial_party_explains_only_what_is_known(self):
        out = self.why("919999000555")
        self.assertIn(SOCIAL, out)
        self.assertNotIn("Design & Branding", out)

    def test_partial_party_names_the_gaps(self):
        out = self.why("919999000555")
        self.assertIn("Not on record", out)
        self.assertIn(FIRST_SEEN, out)
        self.assertIn(SEGMENT, out)
        self.assertIn("absence of record", out)

    def test_evidence_refs_are_shown(self):
        out = self.why(OWNER)
        for claim in self.db.claims:
            if claim["subject"] == FULL:
                self.assertIn(claim["claim_id"], out)

    def test_the_confidence_vector_is_shown_with_its_dominating_dimension(self):
        out = self.why(OWNER)
        self.assertIn("Confidence vector", out)
        self.assertIn("dominating", out)
        self.assertIn("identity_state", out)

    def test_confidence_is_not_inflated_into_words(self):
        """Word boundaries matter: "proven" is a substring of
        "provenance_ceiling", which is a field name, not a claim of proof."""
        import re as _re
        out = self.why(OWNER)
        for inflated in ("certain", "certainly", "definitely", "guaranteed",
                         "proven", "highly confident", "no doubt"):
            self.assertIsNone(_re.search(rf"\b{inflated}\b", out, _re.I),
                              f"{inflated!r} appears as a word in the reply")


# ── 6-7, 9. Call order and the model boundary ──────────────────────────────

class CallOrder(Harness):

    def test_describe_is_called_before_explain(self):
        order = []
        real_describe, real_explain = k.describe, bx.explain

        def spy_describe(*a, **kw):
            order.append("describe")
            return real_describe(*a, **kw)

        def spy_explain(*a, **kw):
            order.append("explain")
            return real_explain(*a, **kw)

        with mock.patch.object(w.bic_knowledge, "describe", spy_describe), \
             mock.patch.object(w.bic_explain, "explain", spy_explain):
            self.why(OWNER)
        self.assertEqual(order, ["describe", "explain"])

    def test_explain_receives_the_describe_envelope(self):
        seen = {}
        real_explain = bx.explain

        def spy(evidence, **kw):
            seen["evidence"] = evidence
            return real_explain(evidence, **kw)

        with mock.patch.object(w.bic_explain, "explain", spy):
            self.why(OWNER)
        self.assertEqual(seen["evidence"]["capability"], "knowledge.describe")
        self.assertEqual(len(seen["evidence"]["values"]), 2)

    def test_the_model_never_runs_before_describe(self):
        calls = []

        def narrator(brief):
            calls.append(("narrate", brief))
            return "Two facts are on record."

        order = []
        real_describe = k.describe

        def spy_describe(*a, **kw):
            order.append("describe")
            self.assertEqual(calls, [], "model ran before retrieval")
            return real_describe(*a, **kw)

        with mock.patch.object(w.bic_knowledge, "describe", spy_describe):
            self.why(OWNER, narrator=narrator)
        self.assertEqual(order, ["describe"])
        self.assertEqual(len(calls), 1)

    def test_no_model_is_called_at_all_by_default(self):
        """Production passes no narrator: an owner command is the wrong place
        for a second model round-trip."""
        self.assertIs(
            inspect.signature(w.tool_knowledge_why).parameters["narrator"].default,
            None)

    def test_the_handler_does_not_query_supabase_directly(self):
        src = inspect.getsource(w.tool_knowledge_why)
        for banned in ("requests.", "rest/v1", "_supa_headers", "SUPABASE_URL",
                       "bic_db", "bic_claims"):
            self.assertNotIn(banned, src)

    def test_the_handler_calls_no_other_registered_tool(self):
        """2G §5.1 / 1C: a registered handler invoking another corrupts the
        outer audit row. #why composes with library calls, like #status."""
        src = code_only(w.tool_knowledge_why)
        self.assertNotIn("run_tool", src)
        self.assertNotIn("invoke_tool", src)


# ── 8, 14-16. Failure states stay distinct ─────────────────────────────────

class FailureStates(Harness):

    def test_unknown_renders_distinctly(self):
        for claim in list(self.db.claims):
            if claim["subject"] == FULL:
                self.db.claims.remove(claim)
        out = self.why(OWNER)
        self.assertIn("UNKNOWN", out)
        self.assertIn("no current knowledge", out)
        self.assertIn("Nothing is inferred from the absence", out)

    def test_unavailable_renders_distinctly(self):
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            out = self.why(OWNER)
        self.assertIn("UNAVAILABLE", out)
        self.assertIn("NOT an absence of knowledge", out)

    def test_denied_renders_distinctly(self):
        env = k.describe(TENANT, FULL)
        justification = bx.explain(
            env, principal=policy.Principal(OWNER, "CLIENT", TENANT),
            descriptor=DESCRIPTOR)
        out = w.render_explanation(justification)
        self.assertIn("DENIED", out)
        self.assertIn("not authorized", out)

    def test_a_denied_render_carries_no_evidence(self):
        env = k.describe(TENANT, FULL)
        out = w.render_explanation(bx.explain(
            env, principal=policy.Principal(OWNER, "CLIENT", TENANT),
            descriptor=DESCRIPTOR))
        self.assertNotIn("Design & Branding", out)
        self.assertNotIn(FULL, out)

    def test_the_three_states_render_three_different_replies(self):
        denied = w.render_explanation(bx.explain(
            k.describe(TENANT, FULL),
            principal=policy.Principal(OWNER, "CLIENT", TENANT),
            descriptor=DESCRIPTOR))
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            unavailable = self.why(OWNER)
        for claim in list(self.db.claims):
            if claim["subject"] == FULL:
                self.db.claims.remove(claim)
        unknown = self.why(OWNER)
        self.assertEqual(len({denied, unavailable, unknown}), 3)

    def test_none_of_them_renders_empty(self):
        with mock.patch.object(k.claims_mod, "current",
                               side_effect=DbError("down")):
            self.assertGreater(len(self.why(OWNER)), 40)

    def test_knowledge_read_failure_reports_the_type_only(self):
        with mock.patch.object(w.bic_knowledge, "describe",
                               side_effect=RuntimeError(f"boom {OWNER}")):
            out = self.why(OWNER)
        self.assertIn("RuntimeError", out)
        self.assertNotIn(OWNER, out)

    def test_explain_failure_reports_the_type_only(self):
        with mock.patch.object(w.bic_explain, "explain",
                               side_effect=RuntimeError(f"boom {OWNER}")):
            out = self.why(OWNER)
        self.assertIn("RuntimeError", out)
        self.assertNotIn(OWNER, out)


# ── 13. Conflicts survive rendering ────────────────────────────────────────

class Conflicts(Harness):

    def _conflict(self):
        stamp = ts("2026-08-18T16:08:15.536992")
        c.assert_claim(TENANT, FULL, INTEREST, "Digital Ads", source="whatsapp",
                       provenance_tier=5, asserted_by="whatsapp:menu_selection",
                       confidence=0.50, source_ref="wa_msg:<withheld>",
                       valid_from=stamp, observed_at=stamp)
        return self.why(OWNER)

    def test_a_conflict_is_stated_in_the_reply(self):
        out = self._conflict()
        self.assertIn("EVIDENCE CONFLICTS", out)
        self.assertIn("No value has been selected", out)

    def test_both_competing_values_are_shown(self):
        out = self._conflict()
        self.assertIn("Design & Branding", out)
        self.assertIn("Digital Ads", out)

    def test_two_simultaneous_conflicts_are_both_rendered(self):
        """§3.5 — the renderer is exactly the boundary where dropping the
        second conflict "to keep the message short" would be tempting.
        Asserted behaviourally: a source grep proves nothing about output."""
        stamp = ts("2026-08-18T16:08:15.536992")
        c.assert_claim(TENANT, FULL, INTEREST, "Digital Ads", source="whatsapp",
                       provenance_tier=5, asserted_by="whatsapp:menu_selection",
                       confidence=0.50, source_ref="wa_msg:<withheld>",
                       valid_from=stamp, observed_at=stamp)
        for segment in ("VIP", "ELECTION"):
            c.assert_claim(TENANT, FULL, SEGMENT, segment, source="whatsapp",
                           provenance_tier=5,
                           asserted_by="whatsapp:keyword_signal",
                           confidence=0.50, source_ref="wa_msg:<withheld>",
                           valid_from=stamp, observed_at=stamp)
        out = self.why(OWNER)
        self.assertEqual(out.count("EVIDENCE CONFLICTS"), 2)
        for expected in ("Design & Branding", "Digital Ads", "VIP", "ELECTION"):
            self.assertIn(expected, out)

    def test_the_degraded_state_is_shown(self):
        self.assertIn("Degraded", self._conflict())


# ── 17-18. Narration fallback ──────────────────────────────────────────────

class NarrationFallback(Harness):

    def test_a_crashing_narrator_does_not_fail_the_command(self):
        def boom(brief):
            raise RuntimeError("provider down: prompt was 'secret internal'")
        out = self.why(OWNER, narrator=boom)
        self.assertIn("Design & Branding", out)
        self.assertIn("tier 5", out)
        self.assertNotIn("secret internal", out)

    def test_a_rejected_narration_falls_back_to_the_deterministic_output(self):
        out = self.why(OWNER, narrator=lambda b: "There are 7 open projects.")
        self.assertIn("Narration refused", out)
        self.assertIn("unsupported_number", out)
        self.assertIn("Design & Branding", out)

    def test_confidence_inflating_narration_is_refused(self):
        out = self.why(OWNER, narrator=lambda b: "We are certain about this.")
        self.assertIn("certainty_language", out)
        self.assertNotIn("We are certain", out)

    def test_a_faithful_narration_is_appended_not_substituted(self):
        out = self.why(OWNER, narrator=lambda b: "Two facts are on record.")
        self.assertIn("Two facts are on record.", out)
        self.assertIn("tier 1 (cap 0.9)", out)
        self.assertIn(FIRST_SEEN, out)

    def test_narration_never_replaces_the_evidence(self):
        plain = self.why(OWNER)
        narrated = self.why(OWNER, narrator=lambda b: "Two facts are on record.")
        for fragment in (FIRST_SEEN, INTEREST, "tier 1 (cap 0.9)",
                         "tier 5 (cap 0.5)", "Confidence vector"):
            self.assertIn(fragment, plain)
            self.assertIn(fragment, narrated)


# ── 19. PII ────────────────────────────────────────────────────────────────

class NoPii(Harness):

    def test_the_reply_never_shows_the_phone_number(self):
        self.assertNotIn(OWNER, self.why(OWNER))

    def test_the_reply_never_shows_a_raw_source_ref_or_wamid(self):
        out = self.why(OWNER)
        self.assertNotIn("source_ref", out)
        self.assertNotIn("wamid", out)
        self.assertNotIn("<withheld>", out)

    def test_only_the_source_scheme_is_shown(self):
        self.assertIn("via wa_msg", self.why(OWNER))

    def test_no_prompt_or_model_context_reaches_the_reply(self):
        out = self.why(OWNER, narrator=lambda b: "Two facts are on record.")
        self.assertNotIn("brief", out.lower())
        self.assertNotIn("We hold 2 current facts about party", out.split("🗣")[-1])

    def test_no_email_shape_appears(self):
        import re
        self.assertIsNone(re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                                    self.why(OWNER)))


# ── 20-24. Nothing else moved ──────────────────────────────────────────────

class NoRegression(unittest.TestCase):

    def test_interest_is_unchanged(self):
        src = code_only(w.tool_service_interest)
        self.assertIn("bic_knowledge.describe", src)
        self.assertNotIn("explain", src)

    def test_interest_still_routes_to_its_own_tool(self):
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('run_tool(sender, "service_interest"', src)

    def test_the_customer_facing_renderer_is_unchanged(self):
        self.assertNotIn("explain", code_only(w.render_knowledge))

    def test_why_is_not_reachable_by_a_customer(self):
        """try_owner_command is the owner pipeline; the registry row is
        OWNER-only and not customer_safe."""
        self.assertFalse(policy.may_invoke(
            policy.Principal(STRANGER, "CLIENT", TENANT), DESCRIPTOR)[0])

    def test_decision_records_module_untouched(self):
        import bic.decision as decision
        self.assertFalse(hasattr(decision, "explain"))
        self.assertNotIn("knowledge_why", code_only(decision))

    def test_replay_module_untouched(self):
        import bic.replay as replay
        self.assertNotIn("knowledge_why", code_only(replay))
        self.assertNotIn("explain", code_only(replay))

    def test_knowledge_describe_untouched_by_this_slice(self):
        """knowledge.py DISCUSSES explainability in prose; what matters is
        that it neither imports nor calls the explain capability."""
        self.assertNotIn("explain", code_only(k))

    def test_claims_and_party_untouched(self):
        for module in (c, p):
            self.assertNotIn("explain", code_only(module))
            self.assertNotIn("knowledge_why", code_only(module))

    def test_help_text_lists_the_new_command(self):
        self.assertIn("#why", w.OWNER_COMMANDS_HELP)

    def test_existing_help_entries_survive(self):
        for command in ("#leads", "#clients", "#status", "#roles", "#interest"):
            self.assertIn(command, w.OWNER_COMMANDS_HELP)


class RendererIsPresentationOnly(unittest.TestCase):
    """It chooses line breaks. Every judgement was made by the capability."""

    def test_the_renderer_reaches_no_storage(self):
        src = code_only(w.render_explanation)
        for banned in ("requests.", "rest/v1", "select(", "describe(",
                       "explain(", "bic_claims", "bic_party"):
            self.assertNotIn(banned, src)

    def test_the_renderer_recomputes_no_confidence(self):
        src = code_only(w.render_explanation)
        for smell in ("min(", "max(", "sum(", "round(", "* 100", "/ len"):
            self.assertNotIn(smell, src)

    def test_the_renderer_makes_no_selection_among_values(self):
        src = code_only(w.render_explanation)
        for smell in ("sorted(justification[", "evidence'][0]", "values[0]"):
            self.assertNotIn(smell, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
