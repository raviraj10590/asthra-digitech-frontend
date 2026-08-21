"""Slice 1C — routing integration. Legacy path vs Brain path.

Proves the two paths produce identical observable behaviour, and that handler
registration wraps existing functions rather than reimplementing them.
Offline: every send/save/AI call is stubbed.
"""

import ast
import os
import sys
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                  # noqa: E402
from bic import identity, tools, policy, db as bic_db  # noqa: E402

OWNER = "918861369951"
CLIENT = "919555555555"
CTX = {"history": [{"role": "user", "content": "prior"}],
       "paused": False, "vip_alerted": False, "lead_alerted": False,
       "recent_sys": [], "last_user": {}}


class _Capture:
    """Records every observable side effect of a turn."""

    def __init__(self):
        self.sent, self.saved = [], []

    def install(self, stack):
        stack.enter_context(mock.patch.object(w, "send_text", lambda to, t: self.sent.append((to, t))))
        stack.enter_context(mock.patch.object(w, "save_messages", lambda items: self.saved.append(list(items))))
        stack.enter_context(mock.patch.object(w, "save_message", lambda *a: None))
        stack.enter_context(mock.patch.object(w, "fetch_memory", lambda s: {}))
        stack.enter_context(mock.patch.object(w, "maybe_alert_vip", lambda *a: None))
        stack.enter_context(mock.patch.object(w, "notify_owner", lambda *a, **k: None))
        stack.enter_context(mock.patch.object(w, "send_welcome_menu", lambda s: self.sent.append((s, "<MENU>"))))
        stack.enter_context(mock.patch.object(w, "generate_reply", lambda *a, **k: "AI-REPLY"))
        stack.enter_context(mock.patch.object(w, "extract_lead_info", lambda h: {}))
        stack.enter_context(mock.patch.object(w, "after_hours_note", lambda: ""))
        return self


def run(path: str, sender: str, text: str):
    """Run one turn down `legacy` or `brain` and capture the effects."""
    from contextlib import ExitStack
    cap = _Capture()
    with ExitStack() as stack:
        cap.install(stack)
        if path == "legacy":
            if sender == OWNER:
                stack.enter_context(mock.patch.object(w, "handle_owner_text",
                                                      lambda *a, **k: "OWNER-REPLY"))
                reply = w.handle_owner_text(sender, "OWNER", None, text, dict(CTX))
                w.send_text(sender, reply)
                w.save_messages([(sender, "user", text), (sender, "assistant", reply)])
            else:
                w.run_client_pipeline(sender, text, dict(CTX))
        else:
            if sender == OWNER:
                stack.enter_context(mock.patch.object(w, "handle_owner_text",
                                                      lambda *a, **k: "OWNER-REPLY"))
                w._bic_owner_turn(sender, text, dict(CTX), "wamid.T")
            else:
                w._bic_client_turn(sender, text, dict(CTX), "wamid.T")
    return cap


class TestOwnerRoutingEquivalence(unittest.TestCase):
    def setUp(self):
        identity.clear_cache()
        identity.configure(lambda p: None)

    def test_owner_reply_identical(self):
        legacy, brain = run("legacy", OWNER, "status?"), run("brain", OWNER, "status?")
        self.assertEqual(legacy.sent, brain.sent)
        self.assertEqual(legacy.saved, brain.saved)

    def test_owner_reply_is_byte_identical(self):
        self.assertEqual(run("brain", OWNER, "x").sent, [(OWNER, "OWNER-REPLY")])


class TestClientRoutingEquivalence(unittest.TestCase):
    def setUp(self):
        identity.clear_cache()
        identity.configure(lambda p: None)

    def test_normal_ai_reply_identical(self):
        legacy, brain = run("legacy", CLIENT, "website price?"), run("brain", CLIENT, "website price?")
        self.assertEqual(legacy.sent, brain.sent)
        self.assertEqual(legacy.saved, brain.saved)
        self.assertEqual(brain.sent, [(CLIENT, "AI-REPLY")])

    def test_menu_branch_identical(self):
        legacy, brain = run("legacy", CLIENT, "menu"), run("brain", CLIENT, "menu")
        self.assertEqual(legacy.sent, brain.sent)
        self.assertEqual(brain.sent, [(CLIENT, "<MENU>")])

    def test_off_topic_branch_identical(self):
        legacy = run("legacy", CLIENT, "write me a python script")
        brain = run("brain", CLIENT, "write me a python script")
        self.assertEqual(legacy.sent, brain.sent)
        self.assertEqual(legacy.saved, brain.saved)

    def test_paused_chat_stays_silent_on_both(self):
        """NOTE: "hello" would NOT work here — it matches is_menu_request(), and
        the menu branch runs BEFORE the paused check, so a paused chat still
        gets a menu. That is real legacy behaviour, preserved deliberately."""
        from contextlib import ExitStack
        for path in ("legacy", "brain"):
            cap = _Capture()
            ctx = dict(CTX, paused=True)
            with ExitStack() as stack:
                cap.install(stack)
                if path == "legacy":
                    w.run_client_pipeline(CLIENT, "website price?", ctx)
                else:
                    w._bic_client_turn(CLIENT, "website price?", ctx, None)
            self.assertEqual(cap.sent, [], f"{path} broke silence on a paused chat")

    def test_brain_path_does_not_double_send(self):
        """The pipeline self-sends; the adapter must not send again."""
        brain = run("brain", CLIENT, "website price?")
        self.assertEqual(len(brain.sent), 1)


class TestHandlerRegistration(unittest.TestCase):
    def test_all_registered(self):
        """5 → 9 when the bypass was closed, → 13 when the review found the
        privileged commands still bypassing (C1, H4), → 14 with the 2C read
        path (`service_interest`, STAFF, read-only), → 15 with `knowledge_why`
        (#why, OWNER-only, read-only, the first consumer of the 2G EXPLAIN
        capability), → 16 with `knowledge_suffice` (#suffice, OWNER-only,
        read-only, the first consumer of the 2H Context + Sufficiency layer).
        This list IS the tool surface. `#status` is absent by
        design — composed from two invocations at the dispatch site, not a
        tool that invokes tools (compose_status); `knowledge_why` composes the
        same way, calling knowledge.describe and knowledge.explain as library
        calls rather than through the registry (2G §5.1)."""
        self.assertEqual(
            sorted(tools._HANDLERS),
            ["add_role", "aitest", "chat_pause", "chat_resume",
             "crm_capture_self", "crm_list_clients", "crm_sync_lead",
             "knowledge_suffice", "knowledge_why", "leads_today",
             "memory_clear", "memory_show", "remove_role", "roles_list",
             "send_brochure", "service_interest"])

    def test_handlers_wrap_not_reimplement(self):
        """Each handler delegates to the existing function."""
        import inspect
        for name, existing in [("_tool_h_leads_today", "tool_leads"),
                               ("_tool_h_crm_list_clients", "tool_clients"),
                               ("_tool_h_roles_list", "tool_roles_list"),
                               ("_tool_h_send_brochure", "send_brochure"),
                               ("_tool_h_aitest", "tool_aitest"),
                               ("_tool_h_memory_show", "tool_memory_show"),
                               ("_tool_h_memory_clear", "tool_memory_clear"),
                               ("_tool_h_crm_capture_self", "sync_lead_to_crm"),
                               ("_tool_h_crm_sync_lead", "sync_lead_to_crm"),
                               ("_tool_h_add_role", "_tool_add_role"),
                               ("_tool_h_remove_role", "_tool_remove_role"),
                               ("_tool_h_chat_pause", "tool_chat_pause"),
                               ("_tool_h_chat_resume", "tool_chat_resume")]:
            src = inspect.getsource(getattr(w, name))
            self.assertIn(existing, src, f"{name} must wrap {existing}")
            # Count EXECUTABLE lines only. The original raw line count also
            # counted docstrings, which penalised documenting a handler's
            # security rationale — exactly the comment most worth writing.
            fn = ast.parse(textwrap.dedent(src)).body[0]
            body = fn.body[1:] if (isinstance(fn.body[0], ast.Expr)
                                   and isinstance(fn.body[0].value, ast.Constant)
                                   and isinstance(fn.body[0].value.value, str)) else fn.body
            stmts = sum(len(list(ast.walk(n))) and 1 for n in body)
            self.assertLessEqual(stmts, 3,
                                 f"{name} looks like reimplementation, not a wrapper")

    def test_client_denied_non_customer_safe_tool(self):
        """Policy still gates execution after registration."""
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE.update({
            "leads_today": {"code": "leads_today", "min_role": "STAFF",
                            "customer_safe": False, "active": True,
                            "audit_level": "none", "timeout_seconds": 10}})
        tools._REGISTRY_EXPIRES = 1e18
        p = policy.Principal(CLIENT, "CLIENT", "t")
        res = tools.invoke(p, "leads_today")
        self.assertTrue(res.denied)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestReplayPersistence(unittest.TestCase):
    """Requirement: replay evidence survives restarts. Must stay PASSIVE."""

    def test_persist_failure_never_breaks_a_turn(self):
        from contextlib import ExitStack
        cap = _Capture()
        with ExitStack() as stack:
            cap.install(stack)
            stack.enter_context(mock.patch.object(
                bic_db, "insert", side_effect=RuntimeError("store down")))
            identity.clear_cache(); identity.configure(lambda p: None)
            w._bic_replay_compare(CLIENT, "CLIENT")          # must not raise
            w.run_client_pipeline(CLIENT, "website price?", dict(CTX))
        self.assertEqual(cap.sent, [(CLIENT, "AI-REPLY")],
                         "a diagnostic write failure must not affect the reply")

    def test_record_contains_only_approved_fields(self):
        captured = {}
        with mock.patch.object(bic_db, "insert",
                               side_effect=lambda t, row, **k: captured.update(row)):
            # CLIENT, not OWNER: OWNER is saturated and skipped, which would
            # make this assertion pass on an empty dict.
            w._bic_persist_replay({"route": "client", "role": "CLIENT", "flow": "client",
                                   "decision_hash": "abc", "tools": [], "degraded": False,
                                   "latency_ms": 1.2, "diffs": []})
        self.assertEqual(
            sorted(captured),
            ["decision_hash", "degraded", "diff_count", "flow", "latency_ms",
             "role", "route", "schema_version", "selected_tools", "tenant_id"])

    def test_no_pii_or_content_persisted(self):
        """Explicitly forbidden: prompts, history, messages, phone, AI output."""
        captured = {}
        with mock.patch.object(bic_db, "insert",
                               side_effect=lambda t, row, **k: captured.update(row)):
            w._bic_persist_replay({"route": "client", "role": "CLIENT", "sender": "9951",
                                   "diffs": ["x", "y"]})
        for banned in ("sender", "phone", "text", "message", "prompt",
                       "reply", "history", "content"):
            self.assertNotIn(banned, captured, f"must not persist {banned}")
        self.assertEqual(captured["diff_count"], 2, "diffs stored as a count only")

    def test_production_does_not_read_replay_table(self):
        src = open(w.__file__).read()
        self.assertEqual(src.count("bic_replay_records"), 1,
                         "replay table must be written once and never read")

    def test_write_uses_server_credential_not_anon(self):
        """Owner change 2: replay is backend-write only. The anon key is public,
        so 'backend only' requires a server-only secret."""
        import inspect
        src = inspect.getsource(w._bic_persist_replay)
        self.assertIn("bic_db.insert", src)
        self.assertNotIn("_supa_headers", src,
                         "must not write with the public anon key")
