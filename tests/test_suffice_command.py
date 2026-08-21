"""`#suffice` — the first consumer of the 2H Context + Sufficiency layer.

THE QUESTION, AND WHY IT IS NOT #why's
--------------------------------------
#why asks "what do we believe, and on what evidence". #suffice asks "is that
enough to DO this thing" — and IDD-2H §4.4 makes the answer depend on the
thing: sufficiency is a property of the (evidence, action) pair, never of the
evidence alone. Several tests below run IDENTICAL evidence through goals of
different risk tiers and assert the verdicts differ. That is the whole point
of the layer; if those tests passed with equal verdicts, the gate would be
decoration.

WHAT THESE TESTS GUARD
----------------------
Mostly the ways a gate says PROCEED when it should not: a goal inferred from
text rather than named, a stale fact filling a high-tier slot, a contested
value counting as settled, an unregistered predicate reported as "ask the
customer" when no answer could be recorded.

Offline: no network, no AI, no database.
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
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                              # noqa: E402
from bic import context as cx, goals as gl, policy               # noqa: E402
from bic import owner_context as oc                              # noqa: E402
from tests import test_context_sufficiency as C                  # noqa: E402
from tests import test_why_command as W                          # noqa: E402

TENANT = C.TENANT
INTEREST, FIRST_SEEN = C.INTEREST, C.FIRST_SEEN
DESCRIPTOR = {"code": "knowledge_suffice", "min_role": "OWNER",
              "customer_safe": False, "risk_tier": 1, "active": True}


def code_only(obj) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


class Base(W.Harness):
    """Reuses the #why harness: same party/claims/registry wiring, plus the
    owner-context takeover that selects the customer."""

    def suffice(self, goal_id="social_media_enquiry", select=True, **kw):
        if select:
            self.owner_took_over(W.PHONE_A)
        with redirect_stdout(io.StringIO()):
            return w.tool_suffice(W.OWNER, goal_id=goal_id, **kw)


# ── 1-2 · authorization ────────────────────────────────────────────────────

class Authorization(Base):

    def test_owner_allowed(self):
        self.assertTrue(policy.may_invoke(
            policy.Principal(W.OWNER, "OWNER", TENANT), DESCRIPTOR)[0])

    def test_staff_denied(self):
        allowed, reason = policy.may_invoke(
            policy.Principal(W.OWNER, "STAFF", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertIn("OWNER", reason)

    def test_client_denied(self):
        allowed, reason = policy.may_invoke(
            policy.Principal("919999000777", "CLIENT", TENANT), DESCRIPTOR)
        self.assertFalse(allowed)
        self.assertEqual(reason, "not customer-safe")

    def test_routed_through_the_registry(self):
        src = inspect.getsource(w.try_owner_command)
        self.assertIn('run_tool(sender, "knowledge_suffice"', src)

    def test_no_second_authorization_path(self):
        src = code_only(w.tool_suffice)
        for smell in ("OWNER_PHONE", "min_role", "is_owner", "role =="):
            self.assertNotIn(smell, src)

    def test_no_hardcoded_phone(self):
        import re
        self.assertIsNone(re.search(r"\b\d{10,15}\b", code_only(w.tool_suffice)))


# ── 3-4 · customer context ─────────────────────────────────────────────────

class CustomerContext(Base):

    def test_uses_the_selected_customer(self):
        out = self.suffice()
        self.assertIn(W.CUST_A, out)

    def test_no_customer_context_is_deterministic(self):
        self.db.claims.clear()
        out = self.suffice(select=False)
        self.assertIn("NO_CUSTOMER_CONTEXT", out)
        self.assertIn("not a permission problem", out)
        self.assertIn("not an outage", out)

    def test_ambiguous_context_does_not_proceed(self):
        stamp = W.now() - timedelta(minutes=1)
        self.owner_took_over(W.PHONE_A, when=stamp)
        self.owner_took_over(W.PHONE_B, when=stamp)
        with redirect_stdout(io.StringIO()):
            out = w.tool_suffice(W.OWNER, goal_id="social_media_enquiry")
        self.assertIn("NO_CUSTOMER_CONTEXT", out)

    def test_the_selecting_signal_is_named(self):
        self.assertIn("selected by: you", self.suffice())

    def test_fallback_signal_is_labelled_weaker(self):
        out = self.suffice(select=False)
        self.assertIn("not an explicit choice", out)


# ── 5-7 · the three goals ──────────────────────────────────────────────────

class Goals(Base):

    def test_social_media_goal(self):
        out = self.suffice("social_media_enquiry")
        self.assertIn("social_media_enquiry", out)
        self.assertIn("risk tier 1", out)

    def test_real_estate_goal(self):
        out = self.suffice("real_estate_enquiry")
        self.assertIn("real_estate_enquiry", out)
        self.assertIn("risk tier 2", out)

    def test_transformer_goal(self):
        out = self.suffice("transformer_quotation")
        self.assertIn("transformer_quotation", out)
        self.assertIn("risk tier 4", out)
        self.assertIn("human approval required", out)

    def test_all_three_are_registered(self):
        self.assertEqual(gl.known_ids(),
                         ["real_estate_enquiry", "social_media_enquiry",
                          "transformer_quotation"])

    def test_the_same_evidence_gives_different_verdicts_by_goal(self):
        """§4.4 — sufficiency is a property of the (evidence, action) pair."""
        a = self.suffice("social_media_enquiry").split("\n")[0]
        self.invocations.clear()
        b = self.suffice("transformer_quotation").split("\n")[0]
        self.assertNotEqual(a, b)


# ── 8-12 · the five verdicts ───────────────────────────────────────────────

class Verdicts(Base):

    def test_proceed(self):
        self.assertIn("PROCEED", self.suffice("social_media_enquiry"))

    def test_clarify_or_refuse_when_slots_are_unfillable(self):
        out = self.suffice("transformer_quotation")
        self.assertTrue(any(v in out for v in ("CLARIFY", "REFUSE")))

    def test_retrieve_when_the_only_gap_is_the_confidence_floor(self):
        """A tier-5 customer declaration (cap 0.50) cannot meet a tier-2
        floor of 0.60 — provenance is a ceiling, not a hint."""
        g = cx.goal("g", 2, [cx.slot("service_interest", INTEREST,
                                     cx.OBTAINABLE_BY_ASKING)])
        p = cx.assemble(TENANT, "x", None, g, W.CUST_A,
                        describe=C.describer(C.envelope([C.F_INTEREST])))
        out = w.render_sufficiency(p)
        self.assertIn("RETRIEVE", out)
        self.assertIn("below the tier-2 floor", out)

    def test_real_estate_refuses_because_its_predicates_are_unregistered(self):
        """The goal names budget and locality, which 2A does not hold. That
        gap cannot be closed by asking the customer — no answer they give
        could be recorded — so REFUSE outranks the floor-miss RETRIEVE."""
        out = self.suffice("real_estate_enquiry")
        self.assertIn("REFUSE", out)
        self.assertIn("UNKNOWABLE", out)
        self.assertIn("not registered", out)
        self.assertIn("below the tier-2 floor", out)

    def test_escalate_when_above_the_principal_ceiling(self):
        strong = copy.deepcopy(C.F_INTEREST)
        strong["confidence"], strong["provenance"]["tier"] = 0.99, 0
        strong["provenance"]["cap"] = 1.0
        g = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        staff = policy.Principal("910000000002", "STAFF", TENANT)
        p = cx.assemble(TENANT, "x", staff, g, W.CUST_A,
                        describe=C.describer(C.envelope([strong])))
        out = w.render_sufficiency(p)
        self.assertIn("ESCALATE", out)

    def test_refuse_on_a_high_severity_conflict(self):
        other = copy.deepcopy(C.F_INTEREST)
        other["value"] = "Digital Ads"
        other["claim_id"] = "zz"
        env = C.envelope([C.F_INTEREST, other], conflicts=[
            {"predicate": INTEREST, "values": ["a", "b"], "resolved": False}])
        g = cx.goal("g", 4, [cx.slot("s", INTEREST, cx.OBTAINABLE_BY_ASKING)])
        p = cx.assemble(TENANT, "x", None, g, W.CUST_A,
                        describe=C.describer(env))
        out = w.render_sufficiency(p)
        self.assertIn("REFUSE", out)
        self.assertIn("CONFLICT (HIGH)", out)

    def test_every_verdict_has_a_next_action(self):
        for v in cx.VERDICTS:
            self.assertTrue(w._NEXT_ACTION.get(v), v)


# ── 13-14 · unknown goal, unavailable ──────────────────────────────────────

class DeterministicRefusals(Base):

    def test_unknown_goal(self):
        out = self.suffice("does_not_exist")
        self.assertIn("UNKNOWN_GOAL", out)
        for g in gl.known_ids():
            self.assertIn(g, out)

    def test_empty_goal_is_unknown_not_a_default(self):
        self.assertIn("UNKNOWN_GOAL", self.suffice(""))

    def test_goal_is_never_inferred_from_text(self):
        """A goal sets the evidence bar; inferring it would let a customer's
        phrasing lower that bar."""
        src = code_only(w.tool_suffice).lower()
        for smell in ("classify", "infer", "detect_intent", "similar", "fuzzy"):
            self.assertNotIn(smell, src)
        self.assertIn("lookup", src)

    def test_context_outage_is_unavailable_not_no_context(self):
        with mock.patch.object(w.bic_owner_context, "resolve",
                               side_effect=RuntimeError(f"boom {W.OWNER}")):
            out = self.suffice()
        self.assertIn("UNAVAILABLE", out)
        self.assertNotIn("NO_CUSTOMER_CONTEXT", out)
        self.assertNotIn(W.OWNER, out)

    def test_assembly_failure_is_unavailable(self):
        with mock.patch.object(w.bic_context, "assemble",
                               side_effect=RuntimeError("boom")):
            out = self.suffice()
        self.assertIn("UNAVAILABLE", out)

    def test_the_refusal_states_are_all_different(self):
        unknown = self.suffice("nope")
        self.db.claims.clear()
        no_ctx = self.suffice(select=False)
        with mock.patch.object(w.bic_owner_context, "resolve",
                               side_effect=RuntimeError("x")):
            unavailable = self.suffice()
        self.assertEqual(len({unknown, no_ctx, unavailable}), 3)


# ── 15-18 · evidence quality carried through ───────────────────────────────

class EvidenceQuality(Base):

    def test_provenance_is_shown(self):
        out = self.suffice("social_media_enquiry")
        self.assertIn("tier 1 (cap 0.9)", out)
        self.assertIn("tier 5 (cap 0.5)", out)

    def test_confidence_floor_is_shown(self):
        self.assertIn("confidence floor 0.5", self.suffice("social_media_enquiry"))
        self.invocations.clear()
        self.assertIn("confidence floor 0.6", self.suffice("real_estate_enquiry"))

    def test_freshness_is_shown_per_fact(self):
        out = self.suffice("social_media_enquiry")
        self.assertIn("PERMANENT", out)
        self.assertIn("FRESH", out)

    def test_high_tier_declares_stale_evidence_not_accepted(self):
        self.assertIn("stale evidence not accepted",
                      self.suffice("transformer_quotation"))

    def test_weakest_fact_is_named(self):
        out = self.suffice("social_media_enquiry")
        self.assertIn("Weakest fact", out)
        self.assertIn(INTEREST, out)

    def test_unregistered_predicate_is_not_reported_as_askable(self):
        """Telling an owner to ask for a fact the system cannot record would
        waste a customer conversation."""
        out = self.suffice("transformer_quotation")
        self.assertIn("UNKNOWABLE", out)
        self.assertIn("not registered", out)


# ── 19-20 · tenant isolation and PII ───────────────────────────────────────

class Security(Base):

    def test_tenant_isolation(self):
        g = gl.lookup("social_media_enquiry")
        p = cx.assemble(C.OTHER_TENANT, "x", None, g, W.CUST_A,
                        describe=C.describer(C.envelope([C.F_INTEREST])))
        out = w.render_sufficiency(p)
        self.assertNotIn("Design & Branding", out)

    def test_no_phone_in_the_reply(self):
        out = self.suffice()
        for phone in (W.OWNER, W.PHONE_A, W.PHONE_B):
            self.assertNotIn(phone, out)

    def test_no_wamid_or_source_ref(self):
        out = self.suffice()
        self.assertNotIn("wamid", out)
        self.assertNotIn("source_ref", out)
        self.assertNotIn("<withheld>", out)

    def test_no_packet_internals_leak(self):
        out = self.suffice()
        for smell in ("packet_id", "evidence_ref", "claim_id", "bic_claims",
                      "rest/v1", "prn_"):
            self.assertNotIn(smell, out)

    def test_no_email_shape(self):
        import re
        self.assertIsNone(re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.suffice()))


# ── 21-22 · no LLM, immutable packet ───────────────────────────────────────

class Determinism(Base):

    def test_no_llm_decides_the_verdict(self):
        src = code_only(w.tool_suffice).lower() + code_only(cx).lower()
        for provider in ("openai", "gemini", "groq", "deepseek", "generate_reply",
                         "llm", "completion", "narrator"):
            self.assertNotIn(provider, src)

    def test_verdict_is_repeatable(self):
        outs = set()
        for _ in range(5):
            self.invocations.clear()
            outs.add(self.suffice("social_media_enquiry").split("\n")[0])
        self.assertEqual(len(outs), 1)

    def test_packet_is_immutable(self):
        g = gl.lookup("social_media_enquiry")
        p = cx.assemble(TENANT, "x", None, g, W.CUST_A,
                        describe=C.describer(C.envelope([C.F_INTEREST])))
        with self.assertRaises(cx.ContextError):
            p["goal_ref"] = "tampered"

    def test_renderer_decides_nothing(self):
        src = code_only(w.render_sufficiency)
        for smell in ("min(", "max(", "sorted(packet", "if confidence",
                      "recompute"):
            self.assertNotIn(smell, src)

    def test_no_storage_access_in_the_handler(self):
        src = code_only(w.tool_suffice)
        for banned in ("requests.", "rest/v1", "SUPABASE_URL", "bic_db",
                       "bic_claims", "select("):
            self.assertNotIn(banned, src)

    def test_no_registered_handler_nesting(self):
        src = code_only(w.tool_suffice)
        self.assertNotIn("run_tool", src)
        self.assertNotIn("invoke_tool", src)


# ── 23-24 · nothing else moved ─────────────────────────────────────────────

class NoRegression(unittest.TestCase):

    def test_why_is_unchanged(self):
        src = code_only(w.tool_knowledge_why)
        self.assertIn("bic_knowledge.describe", src)
        self.assertIn("bic_explain.explain", src)
        self.assertNotIn("bic_context", src)
        self.assertNotIn("suffice", src)

    def test_why_renderer_untouched(self):
        self.assertNotIn("suffice", code_only(w.render_explanation))

    def test_interest_unchanged(self):
        self.assertNotIn("suffice", code_only(w.tool_service_interest))

    def test_webhook_lifecycle_untouched(self):
        src = code_only(w._finalize_delivery)
        self.assertIn("bic_events.COMPLETED", src)
        self.assertNotIn("suffice", src)

    def test_describe_and_explain_untouched(self):
        from bic import knowledge, explain
        for module in (knowledge, explain):
            self.assertNotIn("suffice", code_only(module))
            self.assertNotIn("goals", code_only(module))

    def test_decision_records_and_replay_untouched(self):
        from bic import decision, replay
        for module in (decision, replay):
            self.assertNotIn("suffice", code_only(module))

    def test_engine_stays_free_of_vertical_vocabulary(self):
        """The goals moved to bic/goals.py precisely so this stays true."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "bic",
                                "context.py")).read().lower()
        for word in ("transformer", "kva", "realestate", "voltage", "locality"):
            self.assertNotIn(word, src)

    def test_help_lists_suffice(self):
        self.assertIn("#suffice", w.OWNER_COMMANDS_HELP)


class MigrationRow(unittest.TestCase):

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260816000016_bic_knowledge_suffice.sql")
        with open(path) as fh:
            self.sql = fh.read()
        out, i, in_str = [], 0, False
        while i < len(self.sql):
            ch = self.sql[i]
            if in_str:
                if ch == "'":
                    if i + 1 < len(self.sql) and self.sql[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
                i += 1
                continue
            if ch == "'":
                in_str = True
                i += 1
                continue
            if self.sql[i:i + 2] == "--":
                while i < len(self.sql) and self.sql[i] != "\n":
                    i += 1
                continue
            out.append(ch)
            i += 1
        self.code = "".join(out)

    def test_owner_only(self):
        self.assertRegex(self.sql, r"'OWNER', 1, false, false")

    def test_one_insert_no_ddl(self):
        import re
        self.assertEqual(len(re.findall(r"(?im)^\s*insert into", self.code)), 1)
        self.assertIsNone(re.search(
            r"(?im)^\s*(create|drop|alter|delete|truncate|grant|revoke)\b",
            self.code))

    def test_only_bic_tool_defs(self):
        import re
        self.assertEqual(sorted(set(re.findall(r"bic_[a-z_]+", self.code))),
                         ["bic_tool_defs"])

    def test_declares_no_binding(self):
        self.assertNotIn("binds_to", self.code)

    def test_no_phone_literal(self):
        import re
        self.assertIsNone(re.search(r"\b\d{10,15}\b", self.sql))


if __name__ == "__main__":
    unittest.main(verbosity=2)
