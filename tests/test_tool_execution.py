"""Execution outcome capture — did the capability actually succeed?

BEFORE THIS FIELD
-----------------
The record proved a tool was AUTHORIZED and INVOKED, never whether it RAN
successfully. Verifying the 2026-08-15 brochure turn required md5-matching a
reply marker in whatsapp_messages — the same coupling branch_id removed,
reappearing one level down (IDD-3D §4.4).

FOUR STATES THAT MUST STAY DISTINCT
-----------------------------------
    selected · authorized · invoked · executed-with-a-result

Collapsing any pair is the defect this slice exists to prevent. A denied tool
and a missing handler both produce NO execution result, because neither ran.

SCOPE: execution result only. Business outcome is 2I and is deliberately
unobservable from here.

Offline: no network, no AI, no database.
"""

import inspect as _inspect
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import decision as d                          # noqa: E402
from bic import decisions_cli as cli                    # noqa: E402
from bic import tools as t                              # noqa: E402
from bic import policy as p                             # noqa: E402
from bic.db import DbError                              # noqa: E402

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "supabase",
                         "migrations", "20260815000002_bic_decision_tool_results.sql")

PRINCIPAL = p.Principal(sender_id="x", role="OWNER", label="O",
                        tenant_id="t", channel="whatsapp")


class Base(unittest.TestCase):
    def setUp(self):
        d.close_turn()

    def tearDown(self):
        d.close_turn()

    def _results(self):
        return d.build_record()["tool_results"]


# ── 1 & 2 · success and failure ────────────────────────────────────────────

class ExecutionResult(Base):

    def test_success_is_recorded(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        d.mark_tool_execution("send_brochure", True, None, 812)
        r = self._results()
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["tool"], "send_brochure")
        self.assertEqual(r[0]["status"], "SUCCEEDED")
        self.assertIsNone(r[0]["failure_class"])
        self.assertEqual(r[0]["latency_ms"], 812)

    def test_failure_is_recorded_with_a_class(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        d.mark_tool_execution("send_brochure", False, d.FAIL_DATABASE, 91)
        r = self._results()
        self.assertEqual(r[0]["status"], "FAILED")
        self.assertEqual(r[0]["failure_class"], "DATABASE")

    def test_failure_class_key_present_on_success_too(self):
        """A reader must never have to distinguish 'succeeded' from
        'failed but the key is missing'."""
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_execution("send_brochure", True, None, 10)
        self.assertIn("failure_class", self._results()[0])

    def test_failure_without_a_class_defaults_to_unknown(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_execution("x", False, None, 5)
        self.assertEqual(self._results()[0]["failure_class"], "UNKNOWN")

    def test_multiple_executions_are_all_recorded(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_execution("a", True, None, 1)
        d.mark_tool_execution("b", False, d.FAIL_TIMEOUT, 2)
        self.assertEqual(len(self._results()), 2)


# ── 3 & 4 · missing handler and denial produce NO result ───────────────────

class NothingRanMeansNoResult(Base):

    def test_denied_tool_has_no_execution_result(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_tool_denied("send_brochure")
        rec = d.build_record()
        self.assertEqual(rec["tool_results"], [])
        self.assertEqual(rec["denied_tools"], ["send_brochure"])
        self.assertEqual(rec["selected_tools"], [])

    def test_missing_handler_has_no_execution_result(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_capability_failure()
        rec = d.build_record()
        self.assertEqual(rec["tool_results"], [])
        self.assertEqual(rec["gate_results"]["capability"], d.FAIL)

    def test_denial_path_in_invoke_records_no_execution(self):
        """Through the real invoke(), not a hand-built accumulator."""
        d.open_turn(); d.mark_identity("CLIENT")
        with mock.patch.object(t, "_load_registry", lambda force=False: {}), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            res = t.invoke(PRINCIPAL, "nope")
        self.assertTrue(res.denied)
        self.assertEqual(self._results(), [])


# ── 5 · invocation stays separate from execution ───────────────────────────

class InvocationIsNotExecution(Base):

    def test_invoked_but_not_yet_executed_shows_no_result(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        rec = d.build_record()
        self.assertEqual(rec["selected_tools"], ["send_brochure"])
        self.assertEqual(rec["tool_results"], [])

    def test_execution_failure_does_not_remove_it_from_selected_tools(self):
        """A failed capability was still selected and invoked — three facts."""
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        d.mark_tool_execution("send_brochure", False, d.FAIL_CONNECTION, 40)
        rec = d.build_record()
        self.assertEqual(rec["selected_tools"], ["send_brochure"])
        self.assertEqual(rec["denied_tools"], [])
        self.assertEqual(rec["tool_results"][0]["status"], "FAILED")
        self.assertEqual(rec["gate_results"]["authorization"], d.PASS)


# ── 6 & 7 · no raw error text, no PII ──────────────────────────────────────

class NoRawErrorTextOrPii(Base):

    SECRET = "customer 918861369951 said: send to ravi@example.com"

    def test_exception_message_never_reaches_the_record(self):
        """The real invoke() path with a handler that raises a message
        containing a phone number and an email."""
        boom = lambda **kw: (_ for _ in ()).throw(ValueError(self.SECRET))
        defs = {"t1": {"code": "t1", "active": True, "customer_safe": True,
                       "min_role": "CLIENT"}}
        d.open_turn(); d.mark_identity("OWNER")
        with mock.patch.object(t, "_load_registry", lambda force=False: defs), \
             mock.patch.dict(t._HANDLERS, {"t1": boom}, clear=False), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            t.invoke(PRINCIPAL, "t1")
        blob = json.dumps(d.build_record(), default=str)
        self.assertNotIn("918861369951", blob)
        self.assertNotIn("ravi@example.com", blob)
        self.assertNotIn(self.SECRET, blob)
        self.assertEqual(d.build_record()["tool_results"][0]["failure_class"],
                         "VALUE")

    def test_marker_accepts_no_exception_or_text_parameter(self):
        params = set(_inspect.signature(d.mark_tool_execution).parameters)
        self.assertEqual(params, {"code", "succeeded", "failure_class",
                                  "latency_ms"})
        for banned in ("exc", "exception", "error", "message", "text", "args"):
            self.assertNotIn(banned, params)

    def test_unknown_failure_class_is_coerced_not_stored(self):
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_execution("t", False, self.SECRET, 5)
        self.assertEqual(self._results()[0]["failure_class"], "UNKNOWN")

    def test_coercion_is_logged(self):
        import contextlib, io
        buf = io.StringIO()
        d.open_turn(); d.mark_identity("OWNER")
        with contextlib.redirect_stdout(buf):
            d.mark_tool_execution("t", False, "arbitrary text", 5)
        self.assertIn("unknown failure_class", buf.getvalue())

    def test_vocabulary_values_are_bare_identifiers(self):
        for cls in d.FAILURE_CLASSES:
            self.assertRegex(cls, r"^[A-Z_]+$")

    def test_entry_keys_are_exactly_four(self):
        """No room for arguments or messages to be added casually."""
        d.open_turn(); d.mark_identity("OWNER")
        d.mark_tool_execution("t", True, None, 1)
        self.assertEqual(set(self._results()[0]),
                         {"tool", "status", "failure_class", "latency_ms"})


# ── Failure classification ─────────────────────────────────────────────────

class FailureClassification(Base):

    def test_classification_is_by_type_not_message(self):
        cases = [
            (TimeoutError("x"), "TIMEOUT"),
            (ConnectionError("x"), "CONNECTION"),
            (DbError("x"), "DATABASE"),
            (PermissionError("x"), "PERMISSION"),
            (ValueError("x"), "VALUE"),
            (KeyError("x"), "VALUE"),
            (RuntimeError("x"), "UNKNOWN"),
        ]
        for exc, expected in cases:
            self.assertEqual(t._failure_class(exc), expected, repr(exc))

    def test_message_content_does_not_change_the_class(self):
        a = t._failure_class(RuntimeError("timeout connection database"))
        b = t._failure_class(RuntimeError(""))
        self.assertEqual(a, b)

    def test_every_class_is_in_the_vocabulary(self):
        for exc in (TimeoutError(), ConnectionError(), DbError(""),
                    PermissionError(), ValueError(), RuntimeError()):
            self.assertIn(t._failure_class(exc), d.FAILURE_CLASSES)


# ── 8, 9, 10 · schema version compatibility ────────────────────────────────

class VersionCompatibility(Base):

    V1 = {"decided_at": "2026-08-15T05:26:33+00:00", "turn_id": "v1",
          "decisive_rung": "RUNG_3_DETERMINISTIC", "ai_consulted": False,
          "selected_tools": [], "denied_tools": [], "schema_version": 1}
    V2 = {**V1, "turn_id": "v2", "branch_id": "MENU_REQUEST",
          "schema_version": 2}
    V3 = {**V2, "turn_id": "v3", "branch_id": "BROCHURE_REQUEST",
          "selected_tools": ["send_brochure"], "schema_version": 3,
          "tool_results": [{"tool": "send_brochure", "status": "SUCCEEDED",
                            "failure_class": None, "latency_ms": 812}]}

    def test_v1_row_renders(self):
        self.assertIn("R3_DETERM", cli.render_table([self.V1]))

    def test_v2_row_renders(self):
        self.assertIn("MENU_REQUEST", cli.render_table([self.V2]))

    def test_v3_row_renders_execution(self):
        self.assertIn("send_brochure:OK", cli.render_table([self.V3]))

    def test_all_three_versions_render_together(self):
        cli.render_table([self.V1, self.V2, self.V3])

    def test_null_and_empty_are_displayed_differently(self):
        """A v1 row (unknown) must not look like a recorded empty result."""
        self.assertEqual(cli._fmt_execution(None), "-")
        self.assertEqual(cli._fmt_execution([]), "none")

    def test_summary_separates_not_recorded_from_none_executed(self):
        summary = dict(cli.execution_summary(
            [self.V1, {**self.V3, "tool_results": []}]))
        self.assertEqual(summary["<not recorded>"], 1)
        self.assertEqual(summary["<none executed>"], 1)

    def test_schema_version_is_three(self):
        self.assertEqual(d.SCHEMA_VERSION, 3)

    def test_new_records_declare_version_three(self):
        d.open_turn(); d.mark_identity("CLIENT")
        self.assertEqual(d.build_record()["schema_version"], 3)


# ── Migration ──────────────────────────────────────────────────────────────

class MigrationIsAdditive(Base):

    def _sql(self):
        with open(MIGRATION, encoding="utf-8") as fh:
            return fh.read().lower()

    def test_adds_column_if_not_exists(self):
        self.assertIn("add column if not exists tool_results jsonb", self._sql())

    def test_has_no_default(self):
        """A default of '[]' would make historical rows assert something they
        cannot support."""
        sql = self._sql()
        self.assertNotIn("tool_results jsonb default", sql)
        self.assertNotIn("tool_results jsonb not null", sql)

    def test_array_type_check_present(self):
        self.assertIn("jsonb_typeof(tool_results) = 'array'", self._sql())

    def test_nothing_destructive(self):
        sql = self._sql()
        for bad in ("drop table", "delete from", "truncate", "drop column",
                    "update bic_decision_records", "create or replace function",
                    "pg_cron", "create policy", "disable row level security"):
            self.assertNotIn(bad, sql, f"{bad!r} present")


# ── 12, 13, 14 · CLI ───────────────────────────────────────────────────────

class CliSurface(Base):

    ROW = VersionCompatibility.V3

    def test_allowlist_includes_tool_results(self):
        self.assertIn("tool_results", cli.COLUMNS)

    def test_table_shows_execution(self):
        self.assertIn("send_brochure:OK", cli.render_table([self.ROW]))

    def test_table_shows_failure_with_class(self):
        failed = {**self.ROW, "tool_results": [
            {"tool": "send_brochure", "status": "FAILED",
             "failure_class": "DATABASE", "latency_ms": 12}]}
        self.assertIn("send_brochure:FAIL/DATABASE", cli.render_table([failed]))

    def test_json_carries_the_full_structure(self):
        parsed = json.loads(cli.render_json([self.ROW]))[0]["tool_results"][0]
        self.assertEqual(parsed["status"], "SUCCEEDED")
        self.assertEqual(parsed["latency_ms"], 812)

    def test_execution_summary_counts_outcomes(self):
        summary = dict(cli.execution_summary([self.ROW]))
        self.assertEqual(summary["send_brochure OK"], 1)

    def test_summary_appears_in_providers_view(self):
        self.assertIn("by execution result", cli.render_summary([self.ROW]))

    def test_cli_still_cannot_write(self):
        self.assertFalse(hasattr(cli, "insert"))


# ── 11 · unchanged behaviour ───────────────────────────────────────────────

class NothingElseChanged(Base):

    def test_duplicate_detection_unchanged(self):
        rows = [{"turn_id": "a"}, {"turn_id": "a"}, {"turn_id": "b"}]
        self.assertEqual(cli.find_duplicates(rows), [("a", 2)])

    def test_record_field_set_grew_by_exactly_one(self):
        d.open_turn(); d.mark_identity("CLIENT")
        self.assertEqual(set(d.build_record()), {
            "tenant_id", "schema_version", "turn_id", "brain_version",
            "route", "role", "identity_degraded", "decisive_rung", "branch_id",
            "gate_results", "ai_consulted", "ai_consultation_reason",
            "ai_provider", "selected_tools", "denied_tools", "tool_results",
            "latency_ms",
        })

    def test_rung_derivation_unaffected_by_execution_result(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_BROCHURE_REQUEST)
        d.mark_tool_invoked("send_brochure")
        d.mark_tool_execution("send_brochure", False, d.FAIL_DATABASE, 9)
        rec = d.build_record()
        self.assertEqual(rec["decisive_rung"], d.RUNG_3_DETERMINISTIC)
        self.assertEqual(rec["branch_id"], "BROCHURE_REQUEST")

    def test_marks_are_no_ops_with_no_open_turn(self):
        d.close_turn()
        d.mark_tool_execution("x", True, None, 1)
        self.assertIsNone(d.build_record())

    def test_single_observation_point(self):
        """No duplicate instrumentation: only tools.invoke() calls it."""
        import glob
        hits = 0
        for path in glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                           "bic", "*.py")) + \
                    glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                           "api", "*.py")):
            if os.path.basename(path) == "decision.py":
                continue
            with open(path, encoding="utf-8") as fh:
                hits += fh.read().count("mark_tool_execution(")
        self.assertEqual(hits, 1, "execution is observed in more than one place")


# ── MULTI-TOOL AUDIT ───────────────────────────────────────────────────────
#
# Not hypothetical: webhook.compose_status() invokes leads_today AND
# crm_list_clients in one turn (the `#status` command). Every property below
# is exercised by that real production path.

def _defs(*codes):
    return {c: {"code": c, "active": True, "customer_safe": True,
                "min_role": "CLIENT"} for c in codes}


class MultiToolExecution(Base):

    def _invoke_all(self, handlers, codes):
        """Drive the REAL invoke() once per code, as compose_status does."""
        with mock.patch.object(t, "_load_registry",
                               lambda force=False: _defs(*codes)), \
             mock.patch.dict(t._HANDLERS, handlers, clear=False), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            for c in codes:
                t.invoke(PRINCIPAL, c)

    # 1 · two successes → two entries
    def test_two_successes_produce_two_entries(self):
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "a",
                          "crm_list_clients": lambda **k: "b"},
                         ["leads_today", "crm_list_clients"])
        r = self._results()
        self.assertEqual(len(r), 2)
        self.assertTrue(all(e["status"] == "SUCCEEDED" for e in r))

    # 2 · order preserved
    def test_order_is_preserved(self):
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "a",
                          "crm_list_clients": lambda **k: "b"},
                         ["leads_today", "crm_list_clients"])
        self.assertEqual([e["tool"] for e in self._results()],
                         ["leads_today", "crm_list_clients"])

    def test_order_is_preserved_when_reversed(self):
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "a",
                          "crm_list_clients": lambda **k: "b"},
                         ["crm_list_clients", "leads_today"])
        self.assertEqual([e["tool"] for e in self._results()],
                         ["crm_list_clients", "leads_today"])

    # 3 · success then failure — both recorded
    def test_success_then_failure_records_both(self):
        def boom(**k):
            raise DbError("db down")
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "ok",
                          "crm_list_clients": boom},
                         ["leads_today", "crm_list_clients"])
        r = self._results()
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["status"], "SUCCEEDED")
        self.assertEqual(r[1]["status"], "FAILED")
        self.assertEqual(r[1]["failure_class"], "DATABASE")

    # 4 · a failure must not overwrite an earlier success
    def test_failure_does_not_overwrite_prior_success(self):
        def boom(**k):
            raise TimeoutError("slow")
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "ok",
                          "crm_list_clients": boom},
                         ["leads_today", "crm_list_clients"])
        first = self._results()[0]
        self.assertEqual(first["tool"], "leads_today")
        self.assertEqual(first["status"], "SUCCEEDED")
        self.assertIsNone(first["failure_class"])

    def test_failure_then_success_also_keeps_both(self):
        def boom(**k):
            raise ConnectionError("net")
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": boom,
                          "crm_list_clients": lambda **k: "ok"},
                         ["leads_today", "crm_list_clients"])
        r = self._results()
        self.assertEqual([e["status"] for e in r], ["FAILED", "SUCCEEDED"])
        self.assertEqual(r[0]["failure_class"], "CONNECTION")

    # 5 · denial among successes adds no entry
    def test_denied_tool_among_successes_adds_no_entry(self):
        defs = _defs("leads_today")          # crm_list_clients absent → denied
        d.open_turn(); d.mark_identity("OWNER")
        with mock.patch.object(t, "_load_registry", lambda force=False: defs), \
             mock.patch.dict(t._HANDLERS, {"leads_today": lambda **k: "ok"},
                             clear=False), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            t.invoke(PRINCIPAL, "leads_today")
            t.invoke(PRINCIPAL, "crm_list_clients")
        rec = d.build_record()
        self.assertEqual(len(rec["tool_results"]), 1)
        self.assertEqual(rec["tool_results"][0]["tool"], "leads_today")

    # 6 · missing handler among successes adds no entry
    def test_missing_handler_among_successes_adds_no_entry(self):
        """`clear=True` is load-bearing and order-independent: importing
        webhook registers 13 real handlers into tools._HANDLERS, so a test that
        merely *assumed* crm_list_clients was unregistered passed alone and
        failed in the full suite. Control the map; never assume its state."""
        d.open_turn(); d.mark_identity("OWNER")
        with mock.patch.object(t, "_load_registry",
                               lambda force=False: _defs("leads_today",
                                                         "crm_list_clients")), \
             mock.patch.dict(t._HANDLERS, {"leads_today": lambda **k: "ok"},
                             clear=True), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            t.invoke(PRINCIPAL, "leads_today")
            t.invoke(PRINCIPAL, "crm_list_clients")   # registered, no handler
        rec = d.build_record()
        self.assertEqual(len(rec["tool_results"]), 1)
        self.assertEqual(rec["tool_results"][0]["tool"], "leads_today")
        self.assertEqual(rec["gate_results"]["capability"], d.FAIL)

    # 7 · every entry has exactly the four keys
    def test_every_entry_has_exactly_four_keys(self):
        def boom(**k):
            raise RuntimeError("x")
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "ok",
                          "crm_list_clients": boom},
                         ["leads_today", "crm_list_clients"])
        for e in self._results():
            self.assertEqual(set(e),
                             {"tool", "status", "failure_class", "latency_ms"})

    # 8 & 9 · no raw text, no arguments, no PII — across several entries
    def test_no_exception_text_or_arguments_in_any_entry(self):
        secret = "918861369951 ravi@example.com"

        def boom(**k):
            raise ValueError(secret)
        d.open_turn(); d.mark_identity("OWNER")
        with mock.patch.object(t, "_load_registry",
                               lambda force=False: _defs("leads_today",
                                                         "crm_list_clients")), \
             mock.patch.dict(t._HANDLERS,
                             {"leads_today": lambda **k: "ok",
                              "crm_list_clients": boom}, clear=False), \
             mock.patch.object(t.db, "insert", lambda *a, **k: None):
            t.invoke(PRINCIPAL, "leads_today", target=secret)
            t.invoke(PRINCIPAL, "crm_list_clients", note=secret)
        blob = json.dumps(d.build_record()["tool_results"], default=str)
        self.assertNotIn("918861369951", blob)
        self.assertNotIn("ravi@example.com", blob)
        self.assertNotIn("target", blob)
        self.assertNotIn("note", blob)

    # 10 · single-tool behaviour unchanged
    def test_single_tool_still_produces_exactly_one_entry(self):
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"send_brochure": lambda **k: True},
                         ["send_brochure"])
        self.assertEqual(len(self._results()), 1)

    # Documented asymmetry, pinned so it cannot drift silently
    def test_same_tool_twice_gives_two_results_but_one_selected_entry(self):
        """selected_tools is a SET of capabilities used; tool_results is a LIST
        of executions. Running one tool twice is one capability and two
        executions — so the lengths legitimately differ, and a reader must not
        assume they match."""
        d.open_turn(); d.mark_identity("OWNER")
        self._invoke_all({"leads_today": lambda **k: "ok"},
                         ["leads_today", "leads_today"])
        rec = d.build_record()
        self.assertEqual(len(rec["tool_results"]), 2)
        self.assertEqual(rec["selected_tools"], ["leads_today"])

    def test_cli_renders_multiple_executions(self):
        rows = [{"decided_at": "2026-08-15T08:00:00+00:00",
                 "decisive_rung": "RUNG_3_DETERMINISTIC", "schema_version": 3,
                 "tool_results": [
                     {"tool": "leads_today", "status": "SUCCEEDED",
                      "failure_class": None, "latency_ms": 10},
                     {"tool": "crm_list_clients", "status": "FAILED",
                      "failure_class": "DATABASE", "latency_ms": 20}]}]
        out = cli.render_table(rows)
        self.assertIn("leads_today:OK", out)
        self.assertIn("crm_list_clients:FAIL/DATABASE", out)

    def test_summary_counts_each_execution_separately(self):
        rows = [{"tool_results": [
            {"tool": "leads_today", "status": "SUCCEEDED",
             "failure_class": None, "latency_ms": 1},
            {"tool": "leads_today", "status": "SUCCEEDED",
             "failure_class": None, "latency_ms": 2}]}]
        self.assertEqual(dict(cli.execution_summary(rows))["leads_today OK"], 2)


class EmptyOnlyForObservedTurns(Base):

    def test_empty_list_requires_an_open_turn(self):
        """[] is a positive claim — 'observed, nothing ran'. With no turn open
        there is no record at all, so [] can never be emitted spuriously."""
        d.close_turn()
        self.assertIsNone(d.build_record())

    def test_observed_turn_with_no_tools_emits_empty_list(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_ai_consulted("deepseek")
        self.assertEqual(d.build_record()["tool_results"], [])

    def test_writer_never_emits_null(self):
        """NULL is reserved for rows written before the column existed."""
        for marks in (lambda: None,
                      lambda: d.mark_ai_consulted("openai"),
                      lambda: d.mark_tool_denied("x"),
                      lambda: d.mark_capability_failure()):
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
            marks()
            self.assertIsNotNone(d.build_record()["tool_results"])


class SchemaParserHandlesDecisionMigrations(Base):

    def test_decision_migrations_are_exactly_the_expected_set(self):
        """Pinned by NAME, not by count: a decision migration appearing here
        unannounced is the thing worth catching, and an additive one (the
        2026-08-16 append-only trigger) is recorded deliberately rather than
        by bumping a number."""
        import glob
        pattern = os.path.join(os.path.dirname(__file__), "..", "supabase",
                               "migrations", "*bic_decision*.sql")
        names = sorted(os.path.basename(p) for p in glob.glob(pattern))
        self.assertEqual(names, [
            "20260811000001_bic_decision_records.sql",
            "20260815000001_bic_decision_branch_id.sql",
            "20260815000002_bic_decision_tool_results.sql",
            "20260816000005_bic_decision_records_append_only.sql",
        ])

    def test_cli_allowlist_resolves_across_all_three(self):
        import glob
        pattern = os.path.join(os.path.dirname(__file__), "..", "supabase",
                               "migrations", "*bic_decision*.sql")
        sql = ""
        for path in sorted(glob.glob(pattern)):
            with open(path, encoding="utf-8") as fh:
                sql += fh.read().lower()
        for col in cli.COLUMNS:
            self.assertIn(col, sql, f"{col} in no migration")


if __name__ == "__main__":
    unittest.main(verbosity=2)
