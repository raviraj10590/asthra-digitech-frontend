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
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)

        # BOOTSTRAP_OWNERS IS ALSO MODULE-LEVEL STATE, AND IT IS FROZEN AT
        # IMPORT TIME — this is the second half of the fragility the comment
        # below already names for identity._fetch_row.
        #
        # bic.policy.BOOTSTRAP_OWNERS is computed ONCE, from
        # os.environ.get("OWNER_PHONE", ...), the first time bic.policy is
        # imported in this process. 25 other test files call
        # os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
        # — a DIFFERENT pair from the "918884448141,918861369951" this file
        # sets at its own top of file — and setdefault() is a no-op once any
        # earlier file has already set the variable. So whichever file's
        # bic.policy import happens to run first in THIS process decides
        # which phone numbers are bootstrap owners for every test that
        # follows, for the rest of that process.
        #
        # OWNER = "918861369951" below is a LITERAL constant, not read back
        # from BOOTSTRAP_OWNERS the way test_contract_brain.py and
        # test_policy_tools.py do it (OWNER = policy.BOOTSTRAP_OWNERS[0]) —
        # that pattern is immune to this by construction, because it never
        # assumes a specific value. This class assumes one, so it must
        # guarantee it directly rather than hope collection order supplies
        # it. Full suite collection order happens to put a matching file
        # first today, which is exactly why this was never caught by
        # `pytest tests/` — only by a differently-ordered subset.
        #
        # Scoped monkeypatch, not a new production reset hook: mock.patch
        # already restores the prior list on tearDown (even on failure), so
        # nothing needs to be added to bic/policy.py for this.
        #
        # THE MODULE THAT LOOKS UP THE NAME, NOT THE MODULE THAT DEFINES IT.
        # bic/identity.py does `from .policy import BOOTSTRAP_OWNERS` — that
        # copies the REFERENCE into identity's own module namespace once, at
        # identity's first import. identity.resolve()'s `if sender_id in
        # BOOTSTRAP_OWNERS` reads identity's own copy of the name, not
        # policy's. Patching policy.BOOTSTRAP_OWNERS reassigns policy's
        # attribute to a new list object and leaves identity's copy pointing
        # at the old one — exactly the module-identity trap this codebase's
        # own tests have hit before (patches on one module's name silently
        # not visible through a from-import elsewhere). Verified: the first
        # version of this fix patched policy and did not fix the failure;
        # patching identity does.
        self._owners_patch = mock.patch.object(identity, "BOOTSTRAP_OWNERS", [OWNER])
        self._owners_patch.start()

    def tearDown(self):
        # IDENTITY IS MODULE-LEVEL STATE. configure() installs a fetcher for
        # the whole process, so a test that installs one and walks away
        # re-roles every later test's phone numbers. This module left a
        # fetcher returning STAFF for ANY number, which routed the webhook
        # lifecycle suite down the OWNER branch and failed five of its tests
        # ~130 tests later. Same save/restore discipline as
        # test_1c_closure_validation.py.
        identity.configure(self._saved_fetcher)
        identity.clear_cache()
        self._owners_patch.stop()

    def test_owner_reply_identical(self):
        legacy, brain = run("legacy", OWNER, "status?"), run("brain", OWNER, "status?")
        self.assertEqual(legacy.sent, brain.sent)
        self.assertEqual(legacy.saved, brain.saved)

    def test_owner_reply_is_byte_identical(self):
        self.assertEqual(run("brain", OWNER, "x").sent, [(OWNER, "OWNER-REPLY")])


class BootstrapOwnersIsolation(unittest.TestCase):
    """Regression test for the exact cross-file pollution TestOwnerRoutingEquivalence's
    setUp/tearDown now guards against.

    bic.identity.BOOTSTRAP_OWNERS is frozen at import time from
    os.environ.get("OWNER_PHONE", ...). This file sets that env var to
    "918884448141,918861369951"; 25 other test files set it to
    "910000000001,910000000002"; os.environ.setdefault() means whichever
    file's bic.identity import runs first in the process wins, for every
    test that follows. `pytest tests/` happens to collect a matching file
    first today, which is exactly why this went uncaught until a
    differently-ordered subset invocation surfaced it.

    These tests reproduce the contamination DIRECTLY rather than hoping a
    particular file ordering recreates it — deliberate, not incidental,
    and immune to ever going stale if collection order changes again.
    """

    WRONG_CAMP = ["910000000001", "910000000002"]

    def test_setup_corrects_a_contaminated_bootstrap_list(self):
        with mock.patch.object(identity, "BOOTSTRAP_OWNERS", list(self.WRONG_CAMP)):
            self.assertNotIn(OWNER, identity.BOOTSTRAP_OWNERS)
            case = TestOwnerRoutingEquivalence("test_owner_reply_is_byte_identical")
            case.setUp()
            try:
                self.assertEqual(identity.BOOTSTRAP_OWNERS, [OWNER])
                # Not just the list contents — the actual observable symptom
                # this bug produced: the brain flow silently returning no
                # reply because the sender resolved as CLIENT, not OWNER.
                self.assertEqual(run("brain", OWNER, "x").sent,
                                 [(OWNER, "OWNER-REPLY")])
            finally:
                case.tearDown()

    def test_teardown_restores_the_prior_state_for_whoever_runs_next(self):
        """A fixture that corrects itself but never lets go would just move
        the pollution downstream instead of removing it — exactly the
        failure mode identity.configure's own tearDown comment already
        warns about, now true of BOOTSTRAP_OWNERS too."""
        with mock.patch.object(identity, "BOOTSTRAP_OWNERS", list(self.WRONG_CAMP)):
            case = TestOwnerRoutingEquivalence("test_owner_reply_identical")
            case.setUp()
            case.tearDown()
            self.assertEqual(identity.BOOTSTRAP_OWNERS, self.WRONG_CAMP)


class TestClientRoutingEquivalence(unittest.TestCase):
    def setUp(self):
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)

    def tearDown(self):
        # IDENTITY IS MODULE-LEVEL STATE. configure() installs a fetcher for
        # the whole process, so a test that installs one and walks away
        # re-roles every later test's phone numbers. This module left a
        # fetcher returning STAFF for ANY number, which routed the webhook
        # lifecycle suite down the OWNER branch and failed five of its tests
        # ~130 tests later. Same save/restore discipline as
        # test_1c_closure_validation.py.
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

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
        read-only, the first consumer of the 2H Context + Sufficiency layer),
        → 18 with the 2B commitment pair: `commitments_list` (#commitments,
        OWNER-only, read-only) and `commitment_resolve` (#commitment <ref>
        start|met|waive, OWNER-only and the first tool here that MOVES a
        business obligation — through the atomic RPC, never a bare UPDATE),
        → 19 with `business_new_enquiries` (OWNER-only, read-only — the
        direct factual bridge from a chat message to
        biz.pipeline.new_enquiries_per_month@1, the first business-level
        predicate an OWNER question can reach). This list IS the tool
        surface. `#status` is absent by design — composed from two
        invocations at the dispatch site, not a tool that invokes tools
        (compose_status); `knowledge_why` composes the same way, calling
        knowledge.describe and knowledge.explain as library calls rather
        than through the registry (2G §5.1)."""
        self.assertEqual(
            sorted(tools._HANDLERS),
            ["add_role", "aitest", "business_new_enquiries", "chat_pause",
             "chat_resume", "commitment_resolve", "commitments_list",
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
