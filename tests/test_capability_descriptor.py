"""2G capability descriptors — infrastructure only (IDD-2G §3.1).

WHAT THIS SLICE IS
------------------
The registry can now DESCRIBE a Knowledge Capability. Nothing can execute one:
`knowledge.describe` is registered SHADOW and inactive, with no handler.

THE INVARIANT THAT MATTERS MOST
-------------------------------
§D1: capabilities register in the SAME registry and pass the SAME gate.
"Two authorization paths is one authorization hole" — the C-1 finding from
Phase 1C. Several tests below exist only to prove no second path appeared.

Offline: no network, no database, no LLM.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import capability as cap                        # noqa: E402
from bic import policy, tools                            # noqa: E402
from bic.capability import CapabilityError               # noqa: E402

MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
DESCRIPTOR_SQL = os.path.join(MIG, "20260816000010_bic_capability_descriptor.sql")


def sql():
    with open(DESCRIPTOR_SQL) as fh:
        return fh.read()


def code_only():
    return "\n".join(l for l in sql().splitlines() if not l.strip().startswith("--"))


def executable_python(module):
    """Module source with comments and STRINGS (incl. docstrings) removed.

    Needed because this module's own prose says "no LLM" and names
    may_invoke() in order to explain that it does neither — scanning raw
    source would match the explanation instead of the code.
    """
    import io, inspect, tokenize
    out = []
    src = inspect.getsource(module)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def a_capability(**over):
    d = {"code": "knowledge.describe", "kind": cap.QUERY, "status": cap.SHADOW,
         "semver": "0.1.0", "freshness": "per-predicate volatility bound",
         "provenance_tiers": [0, 1, 2, 3, 4, 5],
         "degradation": "degraded=true with coverage stated",
         "explainability": "source, chain, competing claims, confidence vector"}
    d.update(over)
    return d


# ── 1-2 · the 15 live tools must not notice this slice ─────────────────────

class ExistingToolsUnaffected(unittest.TestCase):

    def test_all_fifteen_handlers_still_registered(self):
        import webhook  # noqa: F401  — registers the handlers at import
        # 14 → 15 with `knowledge_why` (#why), → 16 with `knowledge_suffice`
        # (#suffice, OWNER-only, read-only, the first 2H consumer), → 18 with
        # the 2B commitment pair: `commitments_list` (#commitments, read-only)
        # and `commitment_resolve` (#commitment <ref> …, the first OWNER tool
        # that MOVES a business obligation), → 19 with `business_new_enquiries`
        # (the OWNER → real business evidence bridge — a direct factual read
        # of biz.pipeline.new_enquiries_per_month@1, no OWNER GOAL/2H/DECIDE),
        # -> 20 with `business_status` (the OWNER DESCRIPTIVE business status:
        # business-scoped 2H -> sufficiency -> packet-only CONSULT -> DECIDE,
        # advisory only; it authorizes nothing and executes nothing).
        # Plus the `status` composite which is never a handler. Bumping this
        # number is meant to be a conscious act: the count is what makes an
        # accidental new tool surface visible.
        # -> 21 with `business_reasoning` (the Business Reasoning Core:
        # situation -> patterns -> diagnosis -> priorities -> recommendations,
        # advisory only; it authorizes nothing and executes nothing).
        self.assertEqual(len(tools._HANDLERS), 21)

    def test_legacy_act_tool_validates_without_2G_fields(self):
        """A Phase-1 row carries no freshness/degradation and must stay valid."""
        cap.validate({"code": "send_brochure", "kind": cap.ACT})

    def test_legacy_rows_default_to_ACT_and_GENERAL(self):
        s = code_only()
        self.assertRegex(s, r"kind text not null default 'ACT'")
        self.assertRegex(s, r"status text not null default 'GENERAL'")

    def test_every_added_column_is_nullable_or_defaulted(self):
        """Existing rows are never rewritten by this migration."""
        for line in code_only().splitlines():
            m = re.match(r"\s*add column if not exists (\w+)\s+(.+?),?$", line)
            if m and "not null" in m.group(2):
                self.assertIn("default", m.group(2),
                              f"{m.group(1)} is NOT NULL without a default")

    def test_migration_never_rewrites_or_drops_data(self):
        s = code_only().lower()
        for banned in ("drop table", "drop column", "delete from", "truncate",
                       "update bic_tool_defs set"):
            self.assertNotIn(banned, s)

    def test_policy_gate_is_untouched_by_this_slice(self):
        import inspect
        self.assertNotIn("kind", inspect.getsource(policy.may_invoke))


# ── 3-5 · vocabularies and required declarations ───────────────────────────

class DescriptorValidation(unittest.TestCase):

    def test_kind_vocabulary_enforced(self):
        self.assertEqual(cap.KINDS, ("QUERY", "ASSERT", "EXPLAIN", "SUBSCRIBE", "ACT"))
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(kind="LOOKUP"))

    def test_status_vocabulary_enforced(self):
        self.assertEqual(cap.STATUSES, ("SHADOW", "LIMITED", "GENERAL", "DEPRECATED"))
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(status="BETA"))

    def test_capability_requires_the_four_2G_declarations(self):
        for field in cap.REQUIRED_CAPABILITY_FIELDS:
            with self.assertRaises(CapabilityError, msg=field):
                cap.validate(a_capability(**{field: None}))

    def test_degradation_unspecified_is_rejected(self):
        """Acceptance #17."""
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(degradation="unspecified"))
        with self.assertRaises(CapabilityError):
            cap.validate({"code": "legacy", "kind": cap.ACT,
                          "degradation": "Unspecified"})

    def test_deprecated_requires_a_successor(self):
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(status=cap.DEPRECATED))
        cap.validate(a_capability(status=cap.DEPRECATED, successor="knowledge.find"))

    def test_provenance_tiers_must_be_2C_tiers(self):
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(provenance_tiers=[0, 9]))

    def test_semver_shape_enforced(self):
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(semver="v1"))

    def test_invalid_code_rejected(self):
        for bad in ("", "Knowledge.Describe", "knowledge describe", "1.bad"):
            with self.assertRaises(CapabilityError):
                cap.validate(a_capability(code=bad))

    def test_sql_mirrors_the_python_rules(self):
        s = code_only()
        self.assertIn("bic_tool_defs_capability_complete", s)
        self.assertIn("bic_tool_defs_degradation_declared", s)
        self.assertIn("bic_tool_defs_successor_pair", s)


# ── 7-8 · generic capability and named bindings ────────────────────────────

class GenericAndBindings(unittest.TestCase):

    def test_knowledge_describe_is_registered_as_a_QUERY(self):
        s = sql()
        self.assertIn("'knowledge.describe'", s)
        self.assertRegex(s, r"'QUERY', 'knowledge', '0\.1\.0'")

    def test_knowledge_describe_is_shadow_and_inactive(self):
        """No handler exists, so it must be unreachable — via the EXISTING
        gate, not a new mechanism. policy.may_invoke denies inactive rows."""
        s = sql()
        self.assertIn("'SHADOW'", s)
        denied, reason = policy.may_invoke(
            policy.Principal("x", "OWNER", "t"),
            {"code": "knowledge.describe", "active": False, "min_role": "STAFF"})
        self.assertFalse(denied)
        self.assertEqual(reason, "tool inactive")

    def test_no_handler_is_implemented_for_it(self):
        import webhook  # noqa: F401
        self.assertNotIn("knowledge.describe", tools._HANDLERS)

    def test_a_named_binding_needs_no_new_implementation(self):
        """Acceptance #29 — the criterion the whole slice is judged on."""
        binding = a_capability(code="sales.customer_snapshot",
                               binds_to="knowledge.describe",
                               binding_params={"role": "customer"})
        cap.validate(binding)
        self.assertTrue(cap.is_binding(binding))
        self.assertEqual(cap.binding_target(binding), "knowledge.describe")
        import webhook  # noqa: F401
        self.assertNotIn("sales.customer_snapshot", tools._HANDLERS)

    def test_ten_vertical_bindings_add_zero_implementations(self):
        """§8.2 worked bindings, across five industries."""
        import webhook  # noqa: F401
        before = len(tools._HANDLERS)
        for code in ("health.find_patient", "health.encounter_history",
                     "mfg.unit_certificates", "mfg.conformity_rules",
                     "gov.grievance_history", "gov.scheme_eligibility",
                     "legal.matter_documents", "edu.student_progress",
                     "constr.open_rfis", "retail.basket_history"):
            cap.validate(a_capability(code=code, binds_to="knowledge.describe"))
        self.assertEqual(len(tools._HANDLERS), before)

    def test_a_binding_cannot_bind_to_itself(self):
        with self.assertRaises(CapabilityError):
            cap.validate(a_capability(code="x.y", binds_to="x.y"))
        self.assertIn("bic_tool_defs_binding_not_self", code_only())


# ── 9 · one registry, one gate ─────────────────────────────────────────────

class SingleAuthorizationPath(unittest.TestCase):

    def test_no_second_registry_table_is_created(self):
        s = code_only().lower()
        self.assertNotIn("create table", s)
        self.assertIn("alter table bic_tool_defs", s)

    def test_capability_module_holds_no_authorization_logic(self):
        src = executable_python(cap)
        for banned in ("may_invoke", "authorize", "permit", "grant"):
            self.assertNotIn(banned, src)

    def test_capability_module_cannot_reach_the_database(self):
        """No db/network import: it cannot read knowledge even by accident."""
        src = executable_python(cap)
        for banned in ("db", "requests", "psycopg", "urllib", "socket"):
            self.assertNotIn(f" {banned} ", f" {src} ")


# ── 10-12 · boundary, PII, no LLM ──────────────────────────────────────────

class BoundaryAndSafety(unittest.TestCase):

    def test_storage_concepts_are_rejected_in_a_descriptor(self):
        """§1.3 — if a storage concept appears, the boundary has leaked."""
        for leak in ("reads from bic_claims",
                     "SELECT * from the claims table",
                     "returns the row_count",
                     "uses a cursor over jsonb"):
            with self.assertRaises(CapabilityError, msg=leak):
                cap.validate(a_capability(description=leak))

    def test_the_shipped_descriptor_leaks_no_storage_concept(self):
        """The registered knowledge.describe row must pass its own rule."""
        cap.validate(a_capability(
            description="What do we currently assert about this entity, "
                        "with what evidence?",
            outputs="values, conflicts, coverage, freshness, degraded, trace_ref"))

    def test_no_pii_in_the_migration(self):
        s = sql()
        self.assertNotRegex(s, r"\b91\d{10}\b")
        for banned in ("phone", "email", "identifier_value"):
            self.assertNotIn(banned, s.lower())

    def test_no_llm_anywhere_in_descriptor_registration(self):
        """Executable code only — the prose says "no LLM" to explain itself."""
        src = (executable_python(cap) + " " + code_only()).lower()
        # NOTE "vector" alone is not banned: §7.3 requires confidence to be
        # explained AS A VECTOR rather than a single number. The thing being
        # excluded is a vector STORE, which is a different noun entirely.
        for banned in ("openai", "gemini", "deepseek", "groq", "anthropic",
                       "embedding", "pgvector", "vector database",
                       "vector store", "vector search", "completion"):
            self.assertNotIn(banned, src)

    def test_module_declares_no_retrieval_functions(self):
        """Infrastructure only — knowledge.describe is NOT implemented here."""
        for banned in ("describe", "find", "resolve", "timeline", "search",
                       "retrieve", "query"):
            self.assertFalse(hasattr(cap, banned), f"capability.{banned} must not exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
