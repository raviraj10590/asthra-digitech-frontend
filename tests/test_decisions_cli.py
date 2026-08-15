"""Decision Record diagnostics — read-only guarantees and query correctness.

The two properties that matter most here are not features:

  1. it CANNOT write — proven structurally, not by reading the docstring
  2. it CANNOT print customer data — proven by the column allowlist

Everything else is convenience. Offline: no network, no database.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import decisions_cli as cli                   # noqa: E402
from bic.db import DbError                             # noqa: E402

ROW_AI = {
    "decided_at": "2026-08-15T05:58:13.898740+00:00",
    "turn_id": "aaaaaaaa-0000-0000-0000-000000000001",
    "brain_version": "2ba4f5733a844cfce2d8da5457240b432842ffef",
    "route": "client", "role": "CLIENT", "identity_degraded": False,
    "decisive_rung": "RUNG_5_MODEL_ADVISORY", "ai_consulted": True,
    "ai_consultation_reason": "CONSULTED_RESPONSE_GENERATION",
    "ai_provider": "gemini", "selected_tools": [], "denied_tools": [],
    "latency_ms": 2091.5, "schema_version": 1,
    "gate_results": {"constitutional": "PASS"},
}
ROW_DET = {
    **ROW_AI,
    "decided_at": "2026-08-15T05:26:33.523682+00:00",
    "turn_id": "bbbbbbbb-0000-0000-0000-000000000002",
    "decisive_rung": "RUNG_3_DETERMINISTIC", "ai_consulted": False,
    "ai_consultation_reason": "NOT_CONSULTED_DETERMINISTIC_BRANCH",
    "ai_provider": None, "latency_ms": 3252.086,
}
ROW_TOOL = {
    **ROW_DET,
    "turn_id": "cccccccc-0000-0000-0000-000000000003",
    "selected_tools": ["send_brochure"], "denied_tools": [],
}
ROWS = [ROW_AI, ROW_DET, ROW_TOOL]


# ── 1 · Read-only, structurally ────────────────────────────────────────────

class CannotWrite(unittest.TestCase):

    def test_insert_is_not_in_the_module_namespace(self):
        """The strongest form: there is no reference to write through."""
        self.assertFalse(hasattr(cli, "insert"))

    def test_module_never_names_a_write_verb(self):
        import inspect as _inspect
        src = _inspect.getsource(cli)
        body = src.split('"""', 2)[-1]          # skip the module docstring
        for verb in ("db.insert", "insert(", "delete(", "update(", "upsert("):
            self.assertNotIn(verb, body, f"write verb {verb!r} present")

    def test_only_select_is_imported_from_db(self):
        import inspect as _inspect
        src = _inspect.getsource(cli)
        self.assertIn("from .db import DbError, select", src)


# ── 2 · No PII, by allowlist ───────────────────────────────────────────────

class CannotPrintCustomerData(unittest.TestCase):

    BANNED = ("phone", "sender", "content", "message", "body", "text",
              "prompt", "reply", "wamid")

    def test_column_allowlist_contains_no_pii_column(self):
        for col in cli.COLUMNS:
            for banned in self.BANNED:
                self.assertNotIn(banned, col, f"{col} looks like PII")

    def test_query_never_selects_star(self):
        params = cli.build_params()
        self.assertNotEqual(params["select"], "*")
        self.assertNotIn("*", params["select"])

    def test_allowlist_matches_the_committed_schema(self):
        """If a column is added to the table, this test forces a decision
        about whether the diagnostic may print it."""
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260811000001_bic_decision_records.sql")
        with open(path, encoding="utf-8") as fh:
            sql = fh.read().lower()
        for col in cli.COLUMNS:
            self.assertIn(col, sql, f"{col} is not in the migration")

    def test_rendered_output_contains_no_unexpected_field(self):
        out = cli.render_table(ROWS)
        for banned in self.BANNED:
            self.assertNotIn(banned, out.lower())


# ── 3 · Query construction ─────────────────────────────────────────────────

class QueryBuilding(unittest.TestCase):

    def test_defaults(self):
        p = cli.build_params()
        self.assertEqual(p["limit"], "20")
        self.assertEqual(p["order"], "decided_at.desc")

    def test_limit_is_honoured(self):
        self.assertEqual(cli.build_params(limit=5)["limit"], "5")

    def test_rung_filter(self):
        p = cli.build_params(rung="RUNG_5_MODEL_ADVISORY")
        self.assertEqual(p["decisive_rung"], "eq.RUNG_5_MODEL_ADVISORY")

    def test_ai_filter_both_ways(self):
        self.assertEqual(cli.build_params(ai=True)["ai_consulted"], "is.true")
        self.assertEqual(cli.build_params(ai=False)["ai_consulted"], "is.false")

    def test_ai_filter_absent_when_unset(self):
        self.assertNotIn("ai_consulted", cli.build_params())

    def test_route_and_role_filters(self):
        p = cli.build_params(route="owner", role="OWNER")
        self.assertEqual(p["route"], "eq.owner")
        self.assertEqual(p["role"], "eq.OWNER")

    def test_since_and_until(self):
        p = cli.build_params(since="2026-08-15T05:00:00Z")
        self.assertEqual(p["decided_at"], "gte.2026-08-15T05:00:00Z")
        p2 = cli.build_params(since="2026-08-15T05:00:00Z",
                              until="2026-08-15T06:00:00Z")
        self.assertEqual(p2["decided_at"],
                         ["gte.2026-08-15T05:00:00Z", "lte.2026-08-15T06:00:00Z"])

    def test_until_alone(self):
        self.assertEqual(cli.build_params(until="2026-08-15T06:00:00Z")["decided_at"],
                         "lte.2026-08-15T06:00:00Z")


# ── 4 · Analysis ───────────────────────────────────────────────────────────

class Analysis(unittest.TestCase):

    def test_no_duplicates_in_clean_rows(self):
        self.assertEqual(cli.find_duplicates(ROWS), [])

    def test_duplicate_turn_id_detected(self):
        dupes = cli.find_duplicates(ROWS + [ROW_AI])
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0][1], 2)

    def test_provider_summary_counts_non_consultation_as_none(self):
        summary = dict(cli.provider_summary(ROWS))
        self.assertEqual(summary["gemini"], 1)
        self.assertEqual(summary["<none>"], 2)

    def test_provider_never_attributed_when_ai_not_consulted(self):
        """A stale provider on a non-consulted row must not be counted."""
        contradictory = {**ROW_DET, "ai_provider": "deepseek", "ai_consulted": False}
        self.assertEqual(dict(cli.provider_summary([contradictory])),
                         {"<none>": 1})

    def test_rung_summary(self):
        summary = dict(cli.rung_summary(ROWS))
        self.assertEqual(summary["RUNG_3_DETERMINISTIC"], 2)
        self.assertEqual(summary["RUNG_5_MODEL_ADVISORY"], 1)


# ── 5 · Rendering ──────────────────────────────────────────────────────────

class Rendering(unittest.TestCase):

    def test_table_lists_every_row(self):
        out = cli.render_table(ROWS)
        self.assertIn("3 record(s)", out)
        self.assertIn("gemini", out)
        self.assertIn("send_brochure", out)

    def test_table_handles_empty(self):
        self.assertIn("no decision records", cli.render_table([]))

    def test_json_is_valid_and_lossless(self):
        parsed = json.loads(cli.render_json(ROWS))
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["decisive_rung"], "RUNG_5_MODEL_ADVISORY")

    def test_json_preserves_full_rung_names(self):
        """Abbreviations are for the terminal only; automation sees the truth."""
        self.assertIn("RUNG_5_MODEL_ADVISORY", cli.render_json(ROWS))

    def test_null_latency_does_not_crash(self):
        cli.render_table([{**ROW_DET, "latency_ms": None}])

    def test_duplicate_report_states_the_scan_window(self):
        out = cli.render_duplicates([], 11)
        self.assertIn("11", out)


# ── 6 · Exit codes ─────────────────────────────────────────────────────────

class ExitCodes(unittest.TestCase):

    def test_success_returns_zero(self):
        with mock.patch.object(cli, "fetch", lambda p, **k: ROWS), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)

    def test_db_error_returns_one(self):
        def boom(*a, **k):
            raise DbError("SUPABASE_SERVICE_ROLE_KEY is missing")
        buf = io.StringIO()
        with mock.patch.object(cli, "fetch", boom), redirect_stderr(buf):
            self.assertEqual(cli.main([]), 1)
        self.assertIn("error", buf.getvalue().lower())

    def test_bad_ai_flag_returns_one_without_querying(self):
        called = []
        with mock.patch.object(cli, "fetch", lambda *a, **k: called.append(1)), \
             redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--ai", "maybe"]), 1)
        self.assertEqual(called, [], "queried despite invalid arguments")

    def test_duplicates_mode_runs(self):
        with mock.patch.object(cli, "fetch", lambda p, **k: ROWS), \
             redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cli.main(["--duplicates"]), 0)
        self.assertIn("no duplicate", buf.getvalue())

    def test_providers_mode_runs(self):
        with mock.patch.object(cli, "fetch", lambda p, **k: ROWS), \
             redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cli.main(["--providers"]), 0)
        self.assertIn("gemini", buf.getvalue())

    def test_json_mode_emits_parseable_output(self):
        with mock.patch.object(cli, "fetch", lambda p, **k: ROWS), \
             redirect_stdout(io.StringIO()) as buf:
            cli.main(["--json"])
        json.loads(buf.getvalue())

    def test_filters_reach_the_query(self):
        seen = {}
        with mock.patch.object(cli, "fetch",
                               lambda p, **k: seen.update(p) or ROWS), \
             redirect_stdout(io.StringIO()):
            cli.main(["--rung", "RUNG_2_POLICY", "--ai", "false", "-n", "5"])
        self.assertEqual(seen["decisive_rung"], "eq.RUNG_2_POLICY")
        self.assertEqual(seen["ai_consulted"], "is.false")
        self.assertEqual(seen["limit"], "5")


# ── 7 · Production behaviour untouched ─────────────────────────────────────

class NoProductionImpact(unittest.TestCase):

    def test_not_exported_from_the_bic_package(self):
        """The kernel's public surface stays config/db/policy/tools."""
        import bic
        self.assertNotIn("decisions_cli", bic.__all__)

    def test_webhook_does_not_import_the_diagnostic(self):
        path = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn("decisions_cli", fh.read())

    def test_reads_the_decision_table_only(self):
        self.assertEqual(cli.TABLE, "bic_decision_records")
        import inspect as _inspect
        src = _inspect.getsource(cli)
        self.assertNotIn("bic_replay_records", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
