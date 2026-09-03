"""Phase 1C closure validation.

Covers the three properties the owner named that no existing test asserted:

  1. Replay logging still FUNCTIONS after the INTERNAL_ROLES consolidation —
     not merely "does not raise". The route computation changed on both sides
     of the comparison (review M1), so "it didn't crash" is not evidence.
  2. Rollback still works — BIC_POLICY_ENABLED=off must restore legacy
     behaviour for every command, including the four privileged ones that
     became registry-routed in the review fixes.
  3. No behavioural regression — the same turn down the legacy path and the
     Brain path produces identical observable effects.

Offline: no network, no AI, no database.
"""

import contextlib
import io
import json
import os
import sys
import time
import unittest
from contextlib import ExitStack
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                    # noqa: E402
from bic import brain, identity, policy, replay        # noqa: E402

OWNER = "910000000001"
CLIENT = "919555555555"
TARGET = "919999999999"


# ══════════════════════════════════════════════════════════════════════════
# 1. Replay logging still functions
# ══════════════════════════════════════════════════════════════════════════
class ReplayStillFunctions(unittest.TestCase):

    def setUp(self):
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)      # everyone unknown ⇒ CLIENT

    def tearDown(self):
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def _capture(self, sender, legacy_role):
        """Run one replay comparison, returning (stdout, persisted_record)."""
        persisted = []
        buf = io.StringIO()
        with mock.patch.object(w, "_bic_persist_replay", persisted.append), \
             contextlib.redirect_stdout(buf):
            w._bic_replay_compare(sender, legacy_role)
        return buf.getvalue(), (persisted[0] if persisted else None)

    def test_owner_turn_still_produces_a_record(self):
        out, rec = self._capture(OWNER, "OWNER")
        self.assertIn("BIC_REPLAY", out, "replay stopped emitting entirely")
        self.assertIsNotNone(rec, "replay stopped persisting")
        self.assertEqual(rec["route"], "owner")
        self.assertEqual(rec["role"], "OWNER")
        self.assertIsNotNone(rec["decision_hash"])

    def test_client_turn_still_produces_a_record(self):
        out, rec = self._capture(CLIENT, "CLIENT")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["route"], "client")
        self.assertEqual(rec["role"], "CLIENT")

    def test_matching_decision_reports_no_diff(self):
        out, rec = self._capture(OWNER, "OWNER")
        self.assertIn("BIC_REPLAY_MATCH", out)
        self.assertNotIn("diffs", rec)

    def test_a_genuine_disagreement_is_still_DETECTED(self):
        """The property that matters. Both sides now read the same
        INTERNAL_ROLES, so route can never disagree — but ROLE is still
        resolved independently of the legacy caller's value, and a role
        disagreement must still be caught. If this stops failing, replay has
        become decorative."""
        out, rec = self._capture(CLIENT, "OWNER")   # legacy says OWNER, BIC says CLIENT
        self.assertIn("BIC_REPLAY_DIFF", out,
                      "replay no longer detects a role disagreement")
        self.assertIn("diffs", rec)
        self.assertGreater(len(rec["diffs"]), 0)

    def test_replay_never_breaks_the_turn(self):
        """A replay failure must be swallowed — it is diagnostic, and the
        customer is being served by the production path regardless."""
        with mock.patch.object(w.bic_identity, "resolve",
                               mock.Mock(side_effect=RuntimeError("boom"))), \
             contextlib.redirect_stdout(io.StringIO()):
            w._bic_replay_compare(OWNER, "OWNER")   # must not raise

    def test_saturated_role_is_not_persisted(self):
        """OWNER has 48 samples, 0 diffs. More cost latency and add nothing."""
        wrote = []
        with mock.patch.object(w, "REPLAY_SKIP_ROLES", {"OWNER"}), \
             mock.patch.object(w.bic_db, "insert", lambda *a, **k: wrote.append(a)):
            w._bic_persist_replay({"route": "owner", "role": "OWNER"})
        self.assertEqual(wrote, [], "saturated role still writing on every turn")

    def test_role_with_missing_evidence_IS_persisted(self):
        """CLIENT has never produced a record — that is the evidence 1C still
        needs, so the skip must never swallow it."""
        wrote = []
        with mock.patch.object(w, "REPLAY_SKIP_ROLES", {"OWNER"}), \
             mock.patch.object(w.bic_db, "insert", lambda *a, **k: wrote.append(a)):
            w._bic_persist_replay({"route": "client", "role": "CLIENT"})
        self.assertEqual(len(wrote), 1, "CLIENT evidence was skipped — 1C needs it")

    def test_skip_is_reversible_without_a_deploy(self):
        with mock.patch.object(w, "REPLAY_SKIP_ROLES", set()), \
             mock.patch.object(w.bic_db, "insert", lambda *a, **k: None) as ins:
            w._bic_persist_replay({"route": "owner", "role": "OWNER"})

    def test_persistence_failure_is_swallowed(self):
        with mock.patch.object(w.bic_db, "insert",
                               mock.Mock(side_effect=RuntimeError("db down"))), \
             contextlib.redirect_stdout(io.StringIO()):
            w._bic_persist_replay({"route": "owner", "role": "OWNER"})

    def test_record_still_carries_no_pii(self):
        """Owner constraint: no phone numbers, prompts, or message content."""
        _, rec = self._capture(OWNER, "OWNER")
        blob = json.dumps(rec)
        self.assertNotIn(OWNER, blob, "full phone number in a replay record")
        for banned in ("text", "message", "prompt", "content", "reply"):
            self.assertNotIn(banned, rec, f"replay record carries '{banned}'")


# ══════════════════════════════════════════════════════════════════════════
# 2. Rollback still works
# ══════════════════════════════════════════════════════════════════════════
class RollbackRestoresLegacy(unittest.TestCase):
    """BIC_POLICY_ENABLED=off must restore legacy behaviour for EVERY command,
    including the four that became registry-routed during the review fixes.
    A rollback that only half-works is worse than none: it would leave the
    privileged commands broken in the exact situation you reach for rollback."""

    def setUp(self):
        # identity.configure() installs a MODULE-level fetcher. Without the
        # restore below, an OWNER-returning stub leaks into every later test
        # module and makes a stranger resolve as OWNER — which is exactly how
        # this test suite briefly "proved" that unknown numbers were owners.
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: {"role": "OWNER", "label": "test"})

    def tearDown(self):
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def test_flag_off_privileged_commands_still_work(self):
        """The regression that would matter most: with the registry
        unreachable, #stop must still pause the chat."""
        wrote = []
        with mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "save_message", lambda *a: wrote.append(a)):
            out = w.try_owner_command(OWNER, "OWNER", f"#stop {TARGET}")
        self.assertIn("paused", out.lower())
        self.assertEqual(wrote, [(TARGET, "system", "BOT_PAUSED")],
                         "rollback broke chat pause")

    def test_flag_off_role_grant_still_works(self):
        called = []
        with mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "_tool_add_role",
                               lambda *a, **k: called.append((a, k)) or "✅ granted"):
            out = w.OWNER_TOOLS["add_role"](OWNER, target=TARGET, role="STAFF",
                                            label="x", added_by=OWNER)
        self.assertEqual(out, "✅ granted")
        self.assertEqual(len(called), 1, "rollback broke role granting")

    def test_flag_off_read_tools_still_work(self):
        with mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "tool_leads", lambda s, **k: "LEGACY-LEADS"):
            self.assertEqual(
                w.run_tool(OWNER, "leads_today", _fallback=w.tool_leads),
                "LEGACY-LEADS")

    def test_flag_off_keeps_the_confirm_time_authorization_check(self):
        """C2's guard must NOT be flag-dependent. Rollback may restore legacy
        behaviour; it may not remove a security check."""
        ran = []
        marker = ("PENDING_CONFIRM::%f::add_role::%s"
                  % (time.time() + 300, json.dumps({"target": TARGET})))
        ctx = {"recent_sys": [marker], "history": [], "paused": False}
        with mock.patch.object(w, "_bic_enabled", lambda: False), \
             mock.patch.object(w, "get_role", lambda p: ("STAFF", None)), \
             mock.patch.object(w, "save_message", lambda *a: None), \
             mock.patch.dict(w.OWNER_TOOLS,
                             {"add_role": lambda s, **a: ran.append(a) or "GRANTED"}):
            out = w.handle_owner_text(OWNER, "OWNER", None, "#confirm", ctx)
        self.assertIn("Not permitted", out)
        self.assertEqual(ran, [], "rollback removed the confirm-time check")

    def test_flag_off_routes_owner_down_the_legacy_branch(self):
        with mock.patch.dict(os.environ, {"BIC_POLICY_ENABLED": "off"}), \
             mock.patch.object(w, "BIC_AVAILABLE", True):
            self.assertFalse(w._bic_enabled())

    def test_bic_import_failure_degrades_rather_than_breaks(self):
        """The other rollback lever: if bic/ fails to bundle, every tool must
        still run via its fallback."""
        with mock.patch.object(w, "BIC_AVAILABLE", False), \
             mock.patch.object(w, "tool_leads", lambda s, **k: "DEGRADED"):
            self.assertEqual(
                w.run_tool(OWNER, "leads_today", _fallback=w.tool_leads),
                "DEGRADED")


# ══════════════════════════════════════════════════════════════════════════
# 3. No behavioural regression
# ══════════════════════════════════════════════════════════════════════════
class NoBehaviouralRegression(unittest.TestCase):
    """Same turn, both paths, identical observable effects."""

    CTX = {"history": [{"role": "user", "content": "prior"}], "paused": False,
           "vip_alerted": False, "lead_alerted": False, "recent_sys": [],
           "last_user": {}}

    def setUp(self):
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)

    def tearDown(self):
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def _turn(self, flag_on, sender, text):
        sent, saved = [], []
        with ExitStack() as st:
            st.enter_context(mock.patch.object(w, "_bic_enabled", lambda: flag_on))
            st.enter_context(mock.patch.object(w, "send_text", lambda to, t: sent.append((to, t))))
            st.enter_context(mock.patch.object(w, "save_messages", lambda i: saved.append(list(i))))
            st.enter_context(mock.patch.object(w, "save_message", lambda *a: None))
            st.enter_context(mock.patch.object(w, "fetch_memory", lambda s: {}))
            st.enter_context(mock.patch.object(w, "maybe_alert_vip", lambda *a: None))
            st.enter_context(mock.patch.object(w, "notify_owner", lambda *a, **k: None))
            st.enter_context(mock.patch.object(w, "send_welcome_menu",
                                               lambda s: sent.append((s, "<MENU>"))))
            st.enter_context(mock.patch.object(w, "generate_reply", lambda *a, **k: "AI-REPLY"))
            st.enter_context(mock.patch.object(w, "extract_lead_info", lambda h: {}))
            st.enter_context(mock.patch.object(w, "after_hours_note", lambda: ""))
            if flag_on:
                w._bic_client_turn(sender, text, dict(self.CTX), "wamid.T")
            else:
                w.run_client_pipeline(sender, text, dict(self.CTX))
        return sent, saved

    def test_client_ai_reply_identical_across_the_flag(self):
        self.assertEqual(self._turn(False, CLIENT, "website price?"),
                         self._turn(True, CLIENT, "website price?"))

    def test_client_menu_identical_across_the_flag(self):
        self.assertEqual(self._turn(False, CLIENT, "menu"),
                         self._turn(True, CLIENT, "menu"))

    def test_paused_chat_silent_on_both(self):
        for flag in (False, True):
            sent, _ = [], None
            with ExitStack() as st:
                st.enter_context(mock.patch.object(w, "_bic_enabled", lambda: flag))
                st.enter_context(mock.patch.object(w, "send_text",
                                                   lambda to, t: sent.append(t)))
                st.enter_context(mock.patch.object(w, "save_messages", lambda i: None))
                st.enter_context(mock.patch.object(w, "save_message", lambda *a: None))
                st.enter_context(mock.patch.object(w, "fetch_memory", lambda s: {}))
                st.enter_context(mock.patch.object(w, "maybe_alert_vip", lambda *a: None))
                st.enter_context(mock.patch.object(w, "generate_reply", lambda *a, **k: "X"))
                ctx = dict(self.CTX, paused=True)
                if flag:
                    w._bic_client_turn(CLIENT, "website price?", ctx, None)
                else:
                    w.run_client_pipeline(CLIENT, "website price?", ctx)
            self.assertEqual(sent, [], f"flag={flag} broke silence on a paused chat")

    def test_pause_reply_text_unchanged_by_registry_routing(self):
        """H4 moved this into a tool. The wording customers and owners see
        must not have moved with it."""
        with mock.patch.object(w, "save_message", lambda *a: None):
            legacy_style = w.tool_chat_pause(OWNER, target=TARGET)
        self.assertEqual(legacy_style,
                         f"⏸️ Bot paused for wa.me/{TARGET} (auto-resumes in 24h)")
        with mock.patch.object(w, "save_message", lambda *a: None):
            self.assertEqual(w.tool_chat_resume(OWNER, target=TARGET),
                             f"▶️ Bot resumed for wa.me/{TARGET}")


class NoTestPollution(unittest.TestCase):
    """This suite installs module-level state (identity fetcher, registry
    handlers). A test that leaks it makes UNRELATED security tests pass or fail
    for the wrong reason — which happened during 1C closure: three
    characterization tests reported that a stranger resolved as OWNER.
    Cheap check, real bug class."""

    def test_this_module_restores_the_identity_fetcher(self):
        """Deterministic: drive setUp/tearDown directly rather than asserting
        global state, which other modules legitimately own while they run."""
        before = identity._fetch_row
        for cls in (ReplayStillFunctions, RollbackRestoresLegacy,
                    NoBehaviouralRegression):
            case = cls("run")
            case.setUp()
            self.assertIsNot(identity._fetch_row, before,
                             f"{cls.__name__}.setUp did not install a stub")
            case.tearDown()
            self.assertIs(identity._fetch_row, before,
                          f"{cls.__name__} leaked its identity stub")

    def test_identity_is_always_configured(self):
        """Order-independent floor: SOME fetcher must be installed. A test that
        left it as None would make every principal resolve degraded/CLIENT and
        quietly weaken every authorization assertion that follows."""
        self.assertTrue(identity.is_configured(),
                        "a test left the identity resolver unconfigured")

    def test_registry_handlers_are_intact(self):
        """Order-independent: handlers are installed at import and must survive
        every test module. test_policy_tools once deleted real handlers in its
        tearDown, which is why this floor exists."""
        from bic import tools
        for code in ("leads_today", "add_role", "chat_pause", "send_brochure"):
            self.assertIn(code, tools._HANDLERS,
                          f"a test removed the {code} handler and never restored it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
