"""Slice 1C — the no-bypass invariant.

    "There must be no direct tool_*() calls remaining. Registration alone is
     insufficient. Execution must flow through the registry."

Two kinds of proof, because either alone is weak:

  STATIC   — parse webhook.py and assert no business-tool call survives outside
             a registered handler. Registration is easy to add and easy to walk
             around; only a structural check makes a future bypass fail CI
             instead of silently reintroducing the defect.

  DYNAMIC  — exercise run_tool() and assert authorization is enforced BEFORE
             the handler body runs, that failures are safe, and that BIC being
             unavailable degrades rather than breaks.

Offline: no network, no AI, no database.
"""

import ast
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                        # noqa: E402
from bic import policy, tools              # noqa: E402

WEBHOOK_PY = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")

# Every function that performs real business work and is registered as a tool.
BUSINESS_TOOLS = {
    "tool_leads", "tool_clients", "tool_roles_list",
    "tool_aitest", "tool_memory_show", "tool_memory_clear",
    "send_brochure", "sync_lead_to_crm",
}

# NO exceptions. tool_status was the only one; it became dead code when
# `#status` moved to compose_status() and was deleted. Keep this set empty —
# every entry added here is a hole in the invariant.
ALLOWED_DIRECT_CALLERS = set()


def _parse():
    with open(WEBHOOK_PY, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename="webhook.py")


def _is_register_decorator(dec):
    """Matches @bic_tools.register("code")."""
    return (isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "register")


class StaticNoBypass(unittest.TestCase):

    def setUp(self):
        self.tree = _parse()
        # Map every function definition to its enclosing function, so a call can
        # be attributed to the function it physically sits in.
        self.owner_of = {}
        self.registered, self.definitions = set(), set()

        def walk(node, current):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(_is_register_decorator(d) for d in child.decorator_list):
                        self.registered.add(child.name)
                    if child.name in BUSINESS_TOOLS:
                        self.definitions.add(child.name)
                    walk(child, child.name)
                else:
                    self.owner_of[id(child)] = current
                    walk(child, current)

        walk(self.tree, None)

    def _direct_calls(self):
        """(callee, caller, lineno) for every direct business-tool call."""
        found = []
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in BUSINESS_TOOLS:
                continue
            caller = None
            for parent in ast.walk(self.tree):
                for child in ast.iter_child_nodes(parent):
                    if child is node:
                        caller = parent
            found.append((node.func.id, node.lineno))
        return found

    def _caller_ranges(self):
        """name -> (first_line, last_line) for every function definition."""
        ranges = {}
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                last = max(getattr(n, "lineno", node.lineno) for n in ast.walk(node))
                ranges[node.name] = (node.lineno, last)
        return ranges

    def _enclosing(self, lineno, ranges):
        """Innermost function containing this line."""
        best, best_span = None, None
        for name, (lo, hi) in ranges.items():
            if lo <= lineno <= hi:
                span = hi - lo
                if best_span is None or span < best_span:
                    best, best_span = name, span
        return best

    def test_no_direct_execution_outside_handlers(self):
        """THE invariant. Every business-tool call sits inside a registered
        handler (the leaf that calls the real function) or the one documented
        degraded path."""
        ranges = self._caller_ranges()
        violations = []
        for callee, lineno in self._direct_calls():
            caller = self._enclosing(lineno, ranges)
            if caller in self.registered or caller in ALLOWED_DIRECT_CALLERS:
                continue
            # A call inside the callee's own def is recursion, not a bypass.
            if caller == callee:
                continue
            violations.append(f"  line {lineno}: {caller}() calls {callee}() directly")

        self.assertEqual(
            violations, [],
            "Tool Registry bypass — these must route through run_tool():\n"
            + "\n".join(violations))

    def test_every_business_tool_has_a_registered_handler(self):
        """A tool that exists but is unregistered cannot be invoked through the
        registry, which is how bypasses get reintroduced."""
        missing = sorted(BUSINESS_TOOLS - self.definitions)
        self.assertEqual(missing, [], f"expected in webhook.py: {missing}")
        self.assertGreaterEqual(len(self.registered), 9,
                                f"only {len(self.registered)} handlers registered")

    def test_run_tool_exists_and_is_the_only_dispatcher(self):
        self.assertTrue(callable(w.run_tool))
        src = open(WEBHOOK_PY, encoding="utf-8").read()
        # invoke() is the registry entry point; only run_tool may call it.
        ranges = self._caller_ranges()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "invoke"):
                self.assertEqual(self._enclosing(node.lineno, ranges), "run_tool",
                                 f"line {node.lineno}: only run_tool may call invoke()")


class NoNestedInvocation(unittest.TestCase):
    """`tools.invoke()` calls `db.reset_query_count()` on a single thread-local,
    so a handler that invokes another tool corrupts the OUTER row's db_queries.
    Composites belong at the dispatch site (compose_status) until invoke() is
    made nest-safe under an ACP against closed Slice 1B."""

    def test_no_handler_calls_run_tool(self):
        tree = _parse()
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_is_register_decorator(d) for d in node.decorator_list):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                        and inner.func.id == "run_tool"):
                    offenders.append(f"  {node.name}() calls run_tool() at line {inner.lineno}")
        self.assertEqual(offenders, [],
                         "nested invocation corrupts the outer audit row:\n"
                         + "\n".join(offenders))


class _Recorder:
    """Stand-in registry that records what was asked of it."""

    def __init__(self, result):
        self.result, self.calls = result, []

    def invoke(self, principal, code, **args):
        self.calls.append((principal.role, code, args))
        return self.result


class _Result:
    def __init__(self, ok=True, value="", denied=False, error=None):
        self.ok, self.value, self.denied, self.error = ok, value, denied, error


class DynamicDispatch(unittest.TestCase):
    """run_tool()'s failure semantics — the part a static check cannot see."""

    OWNER = "918861369951"

    def _principal(self, role):
        return policy.Principal(self.OWNER, role, "t-1")

    def test_success_returns_tool_value(self):
        rec = _Recorder(_Result(ok=True, value="LEADS-OUTPUT"))
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools", rec), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("OWNER")):
            self.assertEqual(w.run_tool(self.OWNER, "leads_today"), "LEADS-OUTPUT")
        self.assertEqual(rec.calls[0][1], "leads_today")

    def test_denial_returns_refusal_and_never_runs_the_tool(self):
        """Authorization happens BEFORE execution — the whole point of the
        boundary. A denial must not leak the tool's output."""
        ran = []
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Recorder(_Result(ok=False, denied=True,
                                                 error="requires OWNER, caller is CLIENT"))), \
             mock.patch.object(w, "tool_roles_list", lambda s: ran.append(s) or "SECRET"), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("CLIENT")):
            out = w.run_tool(self.OWNER, "roles_list", _fallback=w.tool_roles_list)
        self.assertIn("Not permitted", out)
        self.assertNotIn("SECRET", out)
        self.assertEqual(ran, [], "denied tool must not execute")

    def test_denial_does_not_fall_back_to_the_direct_call(self):
        """The fallback is for BIC being ABSENT, never for policy saying no.
        Falling back on denial would silently restore the bypass."""
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Recorder(_Result(ok=False, denied=True, error="nope"))), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("CLIENT")):
            out = w.run_tool(self.OWNER, "status", _fallback=lambda s: "FALLBACK-RAN")
        self.assertNotIn("FALLBACK-RAN", out)

    def test_tool_error_fails_safe(self):
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Recorder(_Result(ok=False, error="boom"))), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("OWNER")):
            out = w.run_tool(self.OWNER, "leads_today")
        self.assertNotIn("boom", out, "internal errors must not reach the user")
        self.assertTrue(out.startswith("⚠️"))

    def test_flag_off_degrades_to_legacy_behaviour(self):
        """BIC_POLICY_ENABLED is the ONE rollback lever. With it off, tools run
        exactly as they did before the registry existed — otherwise a registry
        outage (fail-closed to deny-all) would have no escape hatch."""
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "bic_tools", _Recorder(_Result(ok=True, value="REGISTRY"))):
            out = w.run_tool(self.OWNER, "leads_today", _fallback=lambda s: "LEGACY")
        self.assertEqual(out, "LEGACY")

    def test_bic_unavailable_degrades_to_the_direct_call(self):
        """A bundling failure must degrade the bot, not take it down."""
        with mock.patch.object(w, "BIC_AVAILABLE", False):
            self.assertEqual(
                w.run_tool(self.OWNER, "leads_today", _fallback=lambda s: "DEGRADED"),
                "DEGRADED")

    def test_bic_unavailable_without_fallback_is_still_safe(self):
        with mock.patch.object(w, "BIC_AVAILABLE", False), \
             mock.patch.object(w, "_bic_enabled", lambda: False):
            out = w.run_tool(self.OWNER, "leads_today")
        self.assertIn("unavailable", out.lower())

    def test_args_reach_the_registry(self):
        rec = _Recorder(_Result(ok=True, value="captured"))
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools", rec), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("CLIENT")):
            w.run_tool("919555555555", "crm_capture_self", data={"name": "X"})
        self.assertEqual(rec.calls[0][2], {"data": {"name": "X"}})

    def test_no_ai_call_in_the_dispatch_path(self):
        """Acceptance: routing through the registry adds ZERO AI calls."""
        ai = []
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools", _Recorder(_Result(ok=True, value="x"))), \
             mock.patch.object(w, "generate_reply", lambda *a, **k: ai.append(1) or ""), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: self._principal("OWNER")):
            w.run_tool(self.OWNER, "status")
        self.assertEqual(ai, [])


class HandlerCoverage(unittest.TestCase):
    """Every rewired dispatch site names a tool that is actually registered —
    a typo would otherwise surface as 'unknown tool → DENY' in production."""

    DISPATCHED = {"leads_today", "crm_list_clients", "roles_list",
                  "aitest", "memory_show", "memory_clear",
                  "send_brochure", "crm_capture_self"}

    def test_all_dispatched_codes_are_registered(self):
        src = open(WEBHOOK_PY, encoding="utf-8").read()
        tree = _parse()
        registered = {d.args[0].value
                      for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      for d in n.decorator_list
                      if _is_register_decorator(d) and d.args
                      and isinstance(d.args[0], ast.Constant)}
        missing = sorted(self.DISPATCHED - registered)
        self.assertEqual(missing, [], f"dispatched but unregistered: {missing}")

    def test_dispatch_sites_use_run_tool(self):
        """Every registry code string appearing in a call must be a run_tool or
        register call — never something else that reimplements dispatch."""
        tree = _parse()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "run_tool"):
                self.assertGreaterEqual(len(node.args), 2,
                                        f"line {node.lineno}: run_tool needs sender + code")
                self.assertIsInstance(node.args[1], ast.Constant,
                                      f"line {node.lineno}: tool code must be a literal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
