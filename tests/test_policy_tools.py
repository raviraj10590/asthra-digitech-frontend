"""Slice 1B — policy + tool registry tests.

Stdlib unittest, fully offline (no network, no DB). Run:
    python3 -m unittest discover -s tests -v

These are security tests. Each asserts a Constitution invariant, and several
are NEGATIVE tests — proving the layer refuses things — because "it worked when
I tried it" says nothing about what it refuses.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BIC_TENANT_ID", "00000000-0000-0000-0000-000000000001")

from bic import policy, tools, db, config  # noqa: E402

TENANT = os.environ["BIC_TENANT_ID"]

DEFS = {
    "leads_today":   {"code": "leads_today",   "min_role": "STAFF",  "customer_safe": False, "active": True, "audit_level": "basic", "timeout_seconds": 10, "expected_latency_ms": 700},
    "roles_list":    {"code": "roles_list",    "min_role": "OWNER",  "customer_safe": False, "active": True, "audit_level": "basic", "timeout_seconds": 10, "expected_latency_ms": 600},
    "send_brochure": {"code": "send_brochure", "min_role": "CLIENT", "customer_safe": True,  "active": True, "audit_level": "basic", "timeout_seconds": 15, "expected_latency_ms": 1500},
    "crm_sync_lead": {"code": "crm_sync_lead", "min_role": "STAFF",  "customer_safe": False, "active": True, "audit_level": "full",  "timeout_seconds": 10, "expected_latency_ms": 1200},
    "retired_tool":  {"code": "retired_tool",  "min_role": "STAFF",  "customer_safe": False, "active": False,"audit_level": "basic", "timeout_seconds": 10, "expected_latency_ms": 100},
}


def P(role, sender="91999", tenant=TENANT):
    return policy.Principal(sender, role, tenant)


class TestPolicy(unittest.TestCase):
    def test_role_ordering(self):
        self.assertTrue(P("OWNER").at_least("STAFF"))
        self.assertTrue(P("MANAGER").at_least("STAFF"))
        self.assertFalse(P("STAFF").at_least("OWNER"))
        self.assertFalse(P("CLIENT").at_least("STAFF"))

    def test_unknown_role_is_client(self):
        """Unknown role → CLIENT (least privilege), never elevated."""
        p = P("WIZARD")
        self.assertEqual(p.rank, 0)
        self.assertFalse(p.at_least("STAFF"))

    def test_unknown_required_role_denies(self):
        self.assertFalse(P("OWNER").at_least("SUPREME_LEADER"))

    def test_bootstrap_owner_without_db(self):
        """Admin access must survive a total DB outage."""
        with mock.patch.object(db, "select", side_effect=db.DbError("down")):
            p = policy.resolve_principal(policy.BOOTSTRAP_OWNERS[0])
        self.assertEqual(p.role, "OWNER")

    def test_db_outage_fails_closed(self):
        """A lookup failure can only ever yield CLIENT — never more access."""
        policy.invalidate("91888")
        with mock.patch.object(db, "select", side_effect=db.DbError("down")):
            p = policy.resolve_principal("91888")
        self.assertEqual(p.role, "CLIENT")
        self.assertTrue(p.degraded)

    def test_degraded_result_is_not_cached(self):
        """A failed lookup must not poison the cache and pin someone to CLIENT."""
        policy.invalidate("91777")
        with mock.patch.object(db, "select", side_effect=db.DbError("down")):
            policy.resolve_principal("91777")
        with mock.patch.object(db, "select", return_value=[{"role": "STAFF", "label": "x"}]):
            p = policy.resolve_principal("91777")
        self.assertEqual(p.role, "STAFF")

    def test_unknown_tenant_denies(self):
        p = policy.Principal("91999", "OWNER", "")
        allowed, reason = policy.may_invoke(p, DEFS["leads_today"])
        self.assertFalse(allowed)
        self.assertIn("tenant", reason)

    def test_unknown_tool_denies_even_for_owner(self):
        allowed, reason = policy.may_invoke(P("OWNER"), None)
        self.assertFalse(allowed)
        self.assertIn("unknown tool", reason)

    def test_inactive_tool_denied(self):
        allowed, _ = policy.may_invoke(P("OWNER"), DEFS["retired_tool"])
        self.assertFalse(allowed)

    def test_client_allowlist(self):
        """CLIENT may invoke ONLY customer_safe tools."""
        self.assertTrue(policy.may_invoke(P("CLIENT"), DEFS["send_brochure"])[0])
        self.assertFalse(policy.may_invoke(P("CLIENT"), DEFS["leads_today"])[0])
        self.assertFalse(policy.may_invoke(P("CLIENT"), DEFS["roles_list"])[0])

    def test_missing_min_role_defaults_strictest(self):
        """A malformed def must not become a backdoor."""
        allowed, _ = policy.may_invoke(P("STAFF"), {"code": "x", "active": True})
        self.assertFalse(allowed)

    def test_principal_is_immutable(self):
        """No downstream code may mutate itself into more privilege."""
        with self.assertRaises(Exception):
            P("CLIENT").role = "OWNER"


class TestRegistry(unittest.TestCase):
    def setUp(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE.update(DEFS)
        tools._REGISTRY_EXPIRES = 1e18          # never expire during tests
        self.audits = []
        self._orig = tools._audit
        tools._audit = lambda *a, **k: self.audits.append((a, k))
        # Snapshot/restore instead of popping: webhook registers REAL handlers
        # at import, and popping them leaked across test files.
        self._handlers_snapshot = dict(tools._HANDLERS)

    def tearDown(self):
        tools._audit = self._orig
        tools._HANDLERS.clear()
        tools._HANDLERS.update(self._handlers_snapshot)

    def test_denied_call_never_reaches_handler(self):
        """The core guarantee: policy denial happens BEFORE execution."""
        called = []
        tools._HANDLERS["leads_today"] = lambda **kw: called.append(1)
        res = tools.invoke(P("CLIENT"), "leads_today")
        self.assertTrue(res.denied)
        self.assertFalse(res.ok)
        self.assertEqual(called, [], "handler ran despite denial")

    def test_denials_are_audited(self):
        tools.invoke(P("CLIENT"), "roles_list")
        self.assertEqual(len(self.audits), 1, "attempted escalation must be recorded")

    def test_unknown_tool_denied(self):
        res = tools.invoke(P("OWNER"), "definitely_not_a_tool")
        self.assertTrue(res.denied)

    def test_missing_handler_is_explicit_failure(self):
        """Registry row without a handler must fail loudly, not silently pass."""
        tools._HANDLERS.pop("leads_today", None)
        res = tools.invoke(P("OWNER"), "leads_today")
        self.assertFalse(res.ok)
        self.assertIn("no handler", res.error)

    def test_handler_exception_is_captured_and_audited(self):
        def boom(**kw):
            raise RuntimeError("kaboom")
        tools._HANDLERS["leads_today"] = boom
        res = tools.invoke(P("OWNER"), "leads_today")
        self.assertFalse(res.ok)
        self.assertIn("kaboom", res.error)
        self.assertEqual(len(self.audits), 1)

    def test_success_measures_latency(self):
        tools._HANDLERS["leads_today"] = lambda **kw: {"n": 3}
        res = tools.invoke(P("OWNER"), "leads_today")
        self.assertTrue(res.ok)
        self.assertEqual(res.value, {"n": 3})
        self.assertGreaterEqual(res.latency_ms, 0)

    def test_audit_failure_does_not_break_tool(self):
        """Business continuity outranks audit completeness (owner-approved)."""
        tools._audit = self._orig
        tools._HANDLERS["leads_today"] = lambda **kw: "fine"
        with mock.patch.object(db, "insert", side_effect=db.DbError("audit down")):
            res = tools.invoke(P("OWNER"), "leads_today")
        self.assertTrue(res.ok)
        self.assertEqual(res.value, "fine")

    def test_redaction_is_allowlist(self):
        """Unknown keys are dropped — a new PII field cannot leak by default."""
        out = tools._redact("crm_sync_lead",
                            {"service_needed": "web", "phone": "919999999999",
                             "message": "secret", "city": "Bengaluru"},
                            "full")
        self.assertIn("service_needed", out)
        self.assertIn("city", out)
        self.assertNotIn("phone", out)
        self.assertNotIn("message", out)

    def test_basic_audit_stores_no_args(self):
        self.assertEqual(tools._redact("leads_today", {"limit": 5}, "basic"), {})

    def test_describe_filters_by_principal(self):
        client_tools = [t["name"] for t in tools.describe(P("CLIENT"))]
        self.assertEqual(client_tools, ["send_brochure"])
        owner_tools = [t["name"] for t in tools.describe(P("OWNER"))]
        self.assertIn("roles_list", owner_tools)

    def test_owner_only_is_derived_not_stored(self):
        d = {t["name"]: t for t in tools.describe(P("OWNER"))}
        self.assertTrue(d["roles_list"]["owner_only"])
        self.assertFalse(d["leads_today"]["owner_only"])

    def test_empty_registry_denies_everything(self):
        """If the registry cannot load, unknown tool → DENY (fail closed)."""
        tools._REGISTRY_CACHE.clear()
        with mock.patch.object(db, "select", side_effect=db.DbError("down")):
            res = tools.invoke(P("OWNER"), "leads_today")
        self.assertTrue(res.denied)


class TestNoBypass(unittest.TestCase):
    def test_handlers_not_publicly_exported(self):
        """Owner directive: no module may execute a tool except the registry."""
        import bic
        self.assertNotIn("_HANDLERS", getattr(bic, "__all__", []))
        for name in dir(bic.tools):
            if name.startswith("_"):
                continue
            self.assertNotIn(
                name, ("handlers", "HANDLERS"),
                "handler map must not be publicly reachable",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
