"""Regression locks for the Phase 1C engineering review findings.

One test class per finding. Each asserts the DEFECT cannot come back, not
merely that the current code works — the C1 lesson was that a green suite
proves nothing about what the suite does not look at.

Offline: no network, no AI, no database.
"""

import ast
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                # noqa: E402
from bic import brain, config, policy, tools       # noqa: E402

OWNER = "918861369951"
CLIENT = "919555555555"
WEBHOOK_PY = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")


def _src():
    with open(WEBHOOK_PY, encoding="utf-8") as fh:
        return fh.read()


class _Result:
    def __init__(self, ok=True, value="", denied=False, error=None):
        self.ok, self.value, self.denied, self.error = ok, value, denied, error


class _Registry:
    def __init__(self, result):
        self.result, self.calls = result, []

    def invoke(self, principal, code, **args):
        self.calls.append((principal.role, code, args))
        return self.result


def _bic_on(role="OWNER", result=None):
    """Context managers putting run_tool on the registry path."""
    principal = policy.Principal(OWNER, role, "t-1")
    return [
        mock.patch.object(w, "BIC_AVAILABLE", True),
        mock.patch.object(w, "_bic_enabled", lambda: True),
        mock.patch.object(w, "bic_tools", _Registry(result or _Result(ok=True, value="OK"))),
        mock.patch.object(w.bic_identity, "resolve", lambda s, **k: principal),
    ]


class C1_PrivilegedCommandsRoute(unittest.TestCase):
    """add_role / remove_role / chat_pause / chat_resume must not bypass."""

    def test_owner_tools_dispatch_through_run_tool(self):
        """The two entries that can mint an OWNER must go through the gate."""
        tree = ast.parse(_src())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", None) == "OWNER_TOOLS" for t in node.targets)):
                continue
            src = ast.dump(node)
            self.assertIn("run_tool", src,
                          "OWNER_TOOLS must dispatch via run_tool, not call _tool_* directly")
            return
        self.fail("OWNER_TOOLS not found")

    def test_privileged_handlers_registered(self):
        for code in ("add_role", "remove_role", "chat_pause", "chat_resume"):
            self.assertIn(code, tools._HANDLERS, f"{code} has no handler")

    def test_add_role_produces_an_invocation(self):
        reg = _Registry(_Result(ok=True, value="granted"))
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools", reg), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "OWNER", "t-1")):
            w.OWNER_TOOLS["add_role"](OWNER, target="919999999999",
                                      role="OWNER", label="x", added_by=OWNER)
        self.assertEqual(reg.calls[0][1], "add_role",
                         "granting OWNER must produce a registry invocation")

    def test_denied_grant_never_touches_bot_roles(self):
        wrote = []
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Registry(_Result(ok=False, denied=True,
                                                 error="requires OWNER, caller is STAFF"))), \
             mock.patch.object(w, "_tool_add_role",
                               lambda *a, **k: wrote.append(a) or "GRANTED"), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "STAFF", "t-1")):
            out = w.OWNER_TOOLS["add_role"](OWNER, target="919999999999",
                                            role="OWNER", label="x", added_by=OWNER)
        self.assertIn("Not permitted", out)
        self.assertEqual(wrote, [], "a denied grant must not reach bot_roles")


class C2_ConfirmTimeAuthorization(unittest.TestCase):
    """Authorization must be re-checked when #confirm arrives, not only when
    the action was staged."""

    CTX = {"recent_sys": [], "history": [], "paused": False}

    def _ctx_with_pending(self):
        import json, time
        marker = ("PENDING_CONFIRM::%f::add_role::%s"
                  % (time.time() + 300,
                     json.dumps({"target": "919999999999", "role": "OWNER",
                                 "label": "x", "added_by": OWNER})))
        return dict(self.CTX, recent_sys=[marker])

    def test_demoted_owner_cannot_complete_a_staged_grant(self):
        ran = []
        with mock.patch.object(w, "get_role", lambda p: ("STAFF", None)), \
             mock.patch.object(w, "save_message", lambda *a: None), \
             mock.patch.dict(w.OWNER_TOOLS,
                             {"add_role": lambda s, **a: ran.append(a) or "GRANTED"}):
            out = w.handle_owner_text(OWNER, "OWNER", None, "#confirm",
                                      self._ctx_with_pending())
        self.assertIn("Not permitted", out)
        self.assertEqual(ran, [], "a demoted owner completed a staged grant")

    def test_still_owner_completes_normally(self):
        ran = []
        with mock.patch.object(w, "get_role", lambda p: ("OWNER", None)), \
             mock.patch.object(w, "save_message", lambda *a: None), \
             mock.patch.dict(w.OWNER_TOOLS,
                             {"add_role": lambda s, **a: ran.append(a) or "GRANTED"}):
            out = w.handle_owner_text(OWNER, "OWNER", None, "#confirm",
                                      self._ctx_with_pending())
        self.assertEqual(out, "GRANTED")
        self.assertEqual(len(ran), 1)

    def test_the_recheck_is_not_flag_dependent(self):
        """Rollback must not remove an authorization check. The guard runs on
        the legacy path too."""
        ran = []
        with mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "get_role", lambda p: ("STAFF", None)), \
             mock.patch.object(w, "save_message", lambda *a: None), \
             mock.patch.dict(w.OWNER_TOOLS,
                             {"add_role": lambda s, **a: ran.append(a) or "GRANTED"}):
            out = w.handle_owner_text(OWNER, "OWNER", None, "#confirm",
                                      self._ctx_with_pending())
        self.assertIn("Not permitted", out)
        self.assertEqual(ran, [])


class H1_NoFalseSuccessRecords(unittest.TestCase):
    """A failed brochure must never be recorded, or reported, as sent."""

    CTX = {"history": [], "paused": False, "vip_alerted": False,
           "lead_alerted": False, "recent_sys": [], "last_user": {}}

    def _run(self, sent_ok):
        from contextlib import ExitStack
        sent, saved, notified = [], [], []
        with ExitStack() as st:
            st.enter_context(mock.patch.object(w, "send_text", lambda to, t: sent.append(t)))
            st.enter_context(mock.patch.object(w, "save_messages", lambda i: saved.extend(i)))
            st.enter_context(mock.patch.object(w, "save_message", lambda *a: None))
            st.enter_context(mock.patch.object(w, "notify_owner", lambda m, **k: notified.append(m)))
            st.enter_context(mock.patch.object(w, "send_followup_buttons", lambda s: None))
            st.enter_context(mock.patch.object(w, "fetch_memory", lambda s: {}))
            st.enter_context(mock.patch.object(w, "maybe_alert_vip", lambda *a: None))
            st.enter_context(mock.patch.object(w, "time", mock.Mock(sleep=lambda n: None)))
            st.enter_context(mock.patch.object(w, "invoke_tool",
                                               lambda s, c, **k: (sent_ok, "x")))
            w.run_client_pipeline(CLIENT, "brochure please", dict(self.CTX))
        return sent, saved, notified

    def test_success_path_unchanged(self):
        sent, saved, notified = self._run(True)
        transcript = " ".join(t for _, _, t in saved)
        self.assertIn("ಕಳಿಸಲಾಯಿತು", transcript)
        self.assertTrue(any("Brochure sent" in n for n in notified))

    def test_failure_is_not_recorded_as_success(self):
        sent, saved, notified = self._run(False)
        transcript = " ".join(t for _, _, t in saved)
        self.assertNotIn("ಕಳಿಸಲಾಯಿತು", transcript,
                         "transcript claims the brochure was sent when it was not")
        self.assertFalse(any("Brochure sent" in n for n in notified),
                         "owner was told a failed send succeeded")

    def test_failure_tells_the_customer_and_the_owner(self):
        sent, saved, notified = self._run(False)
        self.assertTrue(any("⚠️" in t for t in sent), "customer left with a false promise")
        self.assertTrue(any("FAILED" in n for n in notified), "owner not alerted")

    def test_send_brochure_reports_its_outcome(self):
        with mock.patch.object(w, "BROCHURE_URL", ""), \
             mock.patch.object(w, "send_text", lambda *a: None):
            self.assertFalse(w.send_brochure(CLIENT))
        with mock.patch.object(w, "BROCHURE_URL", "https://x/y.pdf"), \
             mock.patch.object(w, "_wa_post", lambda p: None):
            self.assertTrue(w.send_brochure(CLIENT))


class H2_TimeoutIsHonoured(unittest.TestCase):
    """bic_tool_defs.timeout_seconds must reach the network call."""

    def test_handlers_pass_timeout_through(self):
        import inspect
        for name in ("_tool_h_leads_today", "_tool_h_crm_list_clients",
                     "_tool_h_roles_list"):
            src = inspect.getsource(getattr(w, name))
            self.assertIn("timeout=timeout", src, f"{name} discards its timeout")

    def test_business_functions_accept_a_timeout(self):
        import inspect
        for fn in (w.tool_leads, w.tool_clients, w.tool_roles_list):
            self.assertIn("timeout", inspect.signature(fn).parameters,
                          f"{fn.__name__} cannot honour a registry timeout")

    def test_timeout_reaches_requests(self):
        seen = {}

        class _R:
            ok = True
            headers = {}
            def json(self): return []

        def fake_get(url, **kw):
            seen["timeout"] = kw.get("timeout")
            return _R()

        with mock.patch.object(w.requests, "get", fake_get):
            w.tool_leads(OWNER, timeout=17)
        self.assertEqual(seen["timeout"], 17)


class H3_SingleFlagSourceOfTruth(unittest.TestCase):

    def test_dead_constant_is_gone(self):
        self.assertFalse(hasattr(config, "POLICY_ENABLED"),
                         "bic.config.POLICY_ENABLED is back — two readers, "
                         "opposite defaults, and 'false' != 'off' is True")

    def test_flag_defaults_to_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BIC_POLICY_ENABLED", None)
            with mock.patch.object(w, "BIC_AVAILABLE", True):
                self.assertFalse(w._bic_enabled(), "unset flag must mean legacy")

    def test_false_actually_disables(self):
        """The deleted constant treated 'false' as enabled. Lock the semantics."""
        for value in ("false", "off", "0", "no", "FALSE", "garbage", ""):
            with mock.patch.dict(os.environ, {"BIC_POLICY_ENABLED": value}), \
                 mock.patch.object(w, "BIC_AVAILABLE", True):
                self.assertFalse(w._bic_enabled(), f"{value!r} must disable")
        for value in ("true", "1", "yes", "on", "TRUE", "On"):
            with mock.patch.dict(os.environ, {"BIC_POLICY_ENABLED": value}), \
                 mock.patch.object(w, "BIC_AVAILABLE", True):
                self.assertTrue(w._bic_enabled(), f"{value!r} must enable")


class M1_OneInternalRolesDefinition(unittest.TestCase):

    def test_webhook_uses_the_brain_definition(self):
        self.assertIs(w.INTERNAL_ROLES, brain.INTERNAL_ROLES)

    def test_manager_is_not_routed_internally(self):
        """1C is byte-identical: legacy never gave MANAGER the internal
        pipeline, so neither may the Brain while the flag decides routing."""
        self.assertNotIn("MANAGER", brain.INTERNAL_ROLES)
        self.assertIn("MANAGER", policy.ROLE_ORDER,
                      "MANAGER must remain a valid authorization rank")

    def test_no_stray_routing_literal_in_do_post(self):
        tree = ast.parse(_src())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
        for node in ast.walk(fn):
            if isinstance(node, ast.Tuple):
                vals = [getattr(e, "value", None) for e in node.elts]
                self.assertNotEqual(
                    vals, ["OWNER", "STAFF"],
                    "do_POST re-inlined the routing tuple instead of using "
                    "INTERNAL_ROLES")


class M5_OutageIsNotAnAuthzFailure(unittest.TestCase):

    def test_empty_registry_reports_unavailable(self):
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Registry(_Result(ok=False, denied=True,
                                                 error="unknown tool"))), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "OWNER", "t-1")):
            ok, text = w.invoke_tool(OWNER, "leads_today")
        self.assertFalse(ok)
        self.assertIn("unavailable", text.lower())
        self.assertNotIn("Not permitted", text,
                         "an outage must not be reported as an authz failure")

    def test_real_denial_still_says_not_permitted(self):
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Registry(_Result(ok=False, denied=True,
                                                 error="requires OWNER, caller is CLIENT"))), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "CLIENT", "t-1")):
            ok, text = w.invoke_tool(OWNER, "roles_list")
        self.assertFalse(ok)
        self.assertIn("Not permitted", text)


class M3_AuditAllowlistCoversFullTools(unittest.TestCase):

    def test_full_audit_tools_have_allowlist_entries(self):
        for code in ("crm_capture_self", "memory_clear", "add_role",
                     "remove_role", "chat_pause", "chat_resume"):
            self.assertIn(code, tools._ARG_ALLOWLIST,
                          f"{code} declares full audit but records nothing")

    def test_privilege_grants_record_target_and_role(self):
        out = tools._redact("add_role",
                            {"target": "919999999999", "role": "OWNER",
                             "label": "Some Person"}, "full")
        self.assertEqual(out.get("target"), "919999999999")
        self.assertEqual(out.get("role"), "OWNER")
        self.assertNotIn("label", out, "free-text label must stay out of the audit")

    def test_allowlist_still_excludes_unknown_args(self):
        out = tools._redact("add_role",
                            {"target": "9", "secret_token": "abc"}, "full")
        self.assertNotIn("secret_token", out)


class L1_AuditFallbackRedactsPhone(unittest.TestCase):

    def test_stdout_fallback_truncates_source_ref(self):
        import io, contextlib
        principal = policy.Principal("918861369951", "OWNER", "t-1")
        buf = io.StringIO()
        with mock.patch.object(tools.db, "insert",
                               mock.Mock(side_effect=RuntimeError("down"))), \
             contextlib.redirect_stdout(buf):
            tools._audit(principal, "leads_today", {"audit_level": "basic"},
                         0.0, 0.0, True, None, 0, {})
        printed = buf.getvalue()
        self.assertIn("AUDIT_FALLBACK", printed)
        self.assertNotIn("918861369951", printed,
                         "full phone number leaked to platform logs")
        self.assertIn("9951", printed, "fallback must stay diagnosable")


class L5_ReturnCoercion(unittest.TestCase):

    def test_none_becomes_empty_string(self):
        self.assertEqual(w._coerce_tool_text(None), "")

    def test_non_string_is_stringified(self):
        self.assertEqual(w._coerce_tool_text(42), "42")

    def test_compose_status_survives_a_none_returning_handler(self):
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools", _Registry(_Result(ok=True, value=None))), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "OWNER", "t-1")):
            out = w.compose_status(OWNER)   # must not raise TypeError
        self.assertIn("Bot online", out)


class H4_PauseResumeIsGated(unittest.TestCase):

    def test_pause_dispatch_routes_through_run_tool(self):
        tree = ast.parse(_src())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "try_owner_command")
        src = ast.dump(fn)
        self.assertIn("chat_pause", src)
        self.assertIn("chat_resume", src)
        # BOT_PAUSED must be written by the tool, never inline in the dispatcher.
        self.assertNotIn("BOT_PAUSED", src,
                         "try_owner_command still writes BOT_PAUSED directly")

    def test_denied_pause_does_not_write(self):
        wrote = []
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w, "_bic_enabled", lambda: True), \
             mock.patch.object(w, "bic_tools",
                               _Registry(_Result(ok=False, denied=True,
                                                 error="requires OWNER, caller is STAFF"))), \
             mock.patch.object(w, "save_message", lambda *a: wrote.append(a)), \
             mock.patch.object(w.bic_identity, "resolve",
                               lambda s, **k: policy.Principal(OWNER, "STAFF", "t-1")):
            out = w.try_owner_command(OWNER, "STAFF", "#stop 919999999999")
        self.assertIn("Not permitted", out)
        self.assertEqual(wrote, [], "a denied pause still silenced a customer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
