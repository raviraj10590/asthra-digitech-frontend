"""branch_id — making a deterministic Decision Record self-explanatory.

BEFORE THIS FIELD
-----------------
The record proved that *a* deterministic rule settled a turn, never *which*.
Identifying the menu branch in production required md5-matching a reply marker
in whatsapp_messages — a table with its own retention, full of customer data.

That is the coupling IDD-3D §4.4 names: an explanation that needs a second
store is an explanation that expires. These tests lock the fix.

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
import webhook as w                                     # noqa: E402

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "supabase",
                         "migrations", "20260815000001_bic_decision_branch_id.sql")


class Base(unittest.TestCase):
    def setUp(self):
        d.close_turn()

    def tearDown(self):
        d.close_turn()


# ── 1 · Each branch records its own id ─────────────────────────────────────

class EachBranchRecordsItsId(Base):

    def test_all_five_branches_round_trip(self):
        for branch in d.BRANCH_IDS:
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
            d.mark_deterministic_branch(branch)
            rec = d.build_record()
            self.assertEqual(rec["branch_id"], branch)
            self.assertEqual(rec["decisive_rung"], d.RUNG_3_DETERMINISTIC)

    def test_vocabulary_is_exactly_the_five_live_branches(self):
        self.assertEqual(set(d.BRANCH_IDS), {
            "MENU_REQUEST", "OFF_TOPIC", "CHAT_PAUSED",
            "BROCHURE_REQUEST", "NEW_CONTACT"})

    def test_chat_paused_keeps_its_distinct_reason(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_CHAT_PAUSED,
                                    d.NOT_CONSULTED_CHAT_PAUSED)
        rec = d.build_record()
        self.assertEqual(rec["branch_id"], "CHAT_PAUSED")
        self.assertEqual(rec["ai_consultation_reason"],
                         d.NOT_CONSULTED_CHAT_PAUSED)

    def test_branch_id_is_required(self):
        """No default — a branch added later cannot record NULL silently."""
        sig = _inspect.signature(d.mark_deterministic_branch)
        self.assertIs(sig.parameters["branch_id"].default, _inspect.Parameter.empty)


# ── 2 · AI decisions carry no branch ───────────────────────────────────────

class AiDecisionsHaveNoBranch(Base):

    def test_ai_turn_has_null_branch_id(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_ai_consulted("deepseek")
        rec = d.build_record()
        self.assertEqual(rec["decisive_rung"], d.RUNG_5_MODEL_ADVISORY)
        self.assertIsNone(rec["branch_id"])

    def test_turn_with_nothing_observed_has_null_branch_id(self):
        d.open_turn(); d.mark_identity("CLIENT")
        self.assertIsNone(d.build_record()["branch_id"])

    def test_provider_failure_turn_has_null_branch_id(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_ai_all_providers_failed()
        self.assertIsNone(d.build_record()["branch_id"])


# ── 3 · Never inferred ─────────────────────────────────────────────────────

class NeverInferred(Base):

    def test_branch_id_comes_only_from_the_explicit_mark(self):
        """Absence of AI must not manufacture a branch."""
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_tool_invoked("send_brochure")          # tool, but no branch mark
        rec = d.build_record()
        self.assertFalse(rec["ai_consulted"])
        self.assertIsNone(rec["branch_id"])

    def test_decision_module_cannot_read_any_table(self):
        """Structural, not prose: `select` is never imported, so branch_id
        cannot be back-filled from whatsapp_messages or anywhere else.

        (An earlier version of this test scanned the source for words like
        'reply' and tripped on a comment — a test matching prose rather than
        behaviour, which is the defect it was meant to prevent.)
        """
        self.assertFalse(hasattr(d, "select"))
        self.assertFalse(hasattr(d, "requests"))

    def test_branch_marker_accepts_no_text_parameter(self):
        params = set(_inspect.signature(d.mark_deterministic_branch).parameters)
        self.assertEqual(params, {"branch_id", "reason"})
        for banned in ("text", "message", "content", "reply", "sender"):
            self.assertNotIn(banned, params)

    def test_branch_id_is_not_derived_from_the_rung(self):
        """Independent fields: a branch that fired then hit a policy denial is
        recorded as BOTH, because both happened."""
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_BROCHURE_REQUEST)
        d.mark_tool_denied("send_brochure")
        rec = d.build_record()
        self.assertEqual(rec["decisive_rung"], d.RUNG_2_POLICY)
        self.assertEqual(rec["branch_id"], "BROCHURE_REQUEST")


# ── 4 · Historical rows stay readable ──────────────────────────────────────

class HistoricalRowsRemainReadable(Base):

    V1_ROW = {
        "decided_at": "2026-08-15T05:26:33.523682+00:00",
        "turn_id": "old-row-0000-0000-0000-000000000001",
        "decisive_rung": "RUNG_3_DETERMINISTIC", "ai_consulted": False,
        "ai_provider": None, "selected_tools": [], "denied_tools": [],
        "latency_ms": 3252.086, "schema_version": 1,
        # no branch_id — written before the column existed
    }

    def test_cli_renders_a_v1_row_without_crashing(self):
        out = cli.render_table([self.V1_ROW])
        self.assertIn("R3_DETERM", out)

    def test_v1_row_shows_branch_as_absent_not_invented(self):
        out = cli.render_table([self.V1_ROW])
        self.assertNotIn("MENU_REQUEST", out)

    def test_v1_row_survives_json(self):
        json.loads(cli.render_json([self.V1_ROW]))

    def test_branch_summary_buckets_v1_rows_as_none(self):
        self.assertEqual(dict(cli.branch_summary([self.V1_ROW])), {"<none>": 1})

    def test_schema_version_advanced(self):
        """v2 added branch_id; v3 added tool_results. Both additive, so v1 and
        v2 rows stay readable — this pins the current version so an
        unintended bump fails loudly."""
        self.assertEqual(d.SCHEMA_VERSION, 3)

    def test_new_records_declare_the_current_version(self):
        d.open_turn(); d.mark_identity("CLIENT")
        self.assertEqual(d.build_record()["schema_version"], 3)


# ── 5 · Migration is additive ──────────────────────────────────────────────

class MigrationIsAdditive(Base):

    def _sql(self):
        with open(MIGRATION, encoding="utf-8") as fh:
            return fh.read().lower()

    def test_uses_add_column_if_not_exists(self):
        self.assertIn("add column if not exists branch_id", self._sql())

    def test_never_drops_or_recreates_the_table(self):
        sql = self._sql()
        for destructive in ("drop table", "create table", "truncate",
                            "delete from", "update bic_decision_records"):
            self.assertNotIn(destructive, sql, f"{destructive!r} present")

    def test_adds_no_pruning_function(self):
        """The retention invariant (3D I5) must survive schema evolution."""
        sql = self._sql()
        self.assertNotIn("create or replace function", sql)
        self.assertNotIn("pg_cron", sql)

    def test_check_constraint_permits_null(self):
        self.assertIn("branch_id is null or branch_id in", self._sql())

    def test_check_constraint_lists_exactly_the_code_vocabulary(self):
        sql = self._sql()
        for branch in d.BRANCH_IDS:
            self.assertIn(f"'{branch.lower()}'", sql,
                          f"{branch} would be rejected by the database")


# ── 6 & 7 · Read path ──────────────────────────────────────────────────────

class ReadPath(Base):

    ROW = {
        "decided_at": "2026-08-15T06:10:00.000000+00:00",
        "turn_id": "t-0000", "decisive_rung": "RUNG_3_DETERMINISTIC",
        "branch_id": "BROCHURE_REQUEST", "ai_consulted": False,
        "ai_provider": None, "selected_tools": ["send_brochure"],
        "denied_tools": [], "latency_ms": 1200.0, "schema_version": 2,
    }

    def test_branch_id_is_in_the_column_allowlist(self):
        self.assertIn("branch_id", cli.COLUMNS)

    def test_table_output_shows_the_branch(self):
        self.assertIn("BROCHURE_REQUEST", cli.render_table([self.ROW]))

    def test_json_output_includes_branch_id(self):
        self.assertEqual(json.loads(cli.render_json([self.ROW]))[0]["branch_id"],
                         "BROCHURE_REQUEST")

    def test_branch_filter_reaches_the_query(self):
        self.assertEqual(cli.build_params(branch="MENU_REQUEST")["branch_id"],
                         "eq.MENU_REQUEST")

    def test_branch_filter_absent_when_unset(self):
        self.assertNotIn("branch_id", cli.build_params())

    def test_providers_mode_reports_branches(self):
        out = cli.render_summary([self.ROW])
        self.assertIn("deterministic branch", out)
        self.assertIn("BROCHURE_REQUEST", out)


# ── 9 · No PII can enter branch_id ─────────────────────────────────────────

class BranchIdCannotCarryPii(Base):

    def test_unknown_value_is_discarded_not_stored(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch("918861369951 wants a brochure")
        rec = d.build_record()
        self.assertIsNone(rec["branch_id"])

    def test_discarded_value_is_logged_loudly(self):
        import contextlib, io
        buf = io.StringIO()
        d.open_turn(); d.mark_identity("CLIENT")
        with contextlib.redirect_stdout(buf):
            d.mark_deterministic_branch("some free text")
        self.assertIn("unknown branch_id", buf.getvalue())

    def test_reason_is_still_set_even_when_the_id_is_rejected(self):
        """The turn was still settled deterministically; only the label failed."""
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch("bogus")
        self.assertEqual(d.build_record()["ai_consultation_reason"],
                         d.NOT_CONSULTED_DETERMINISTIC_BRANCH)

    def test_every_permitted_value_is_a_bare_identifier(self):
        import re
        for branch in d.BRANCH_IDS:
            self.assertRegex(branch, r"^[A-Z_]+$")


# ── 10 · Unchanged behaviour ───────────────────────────────────────────────

class NothingElseChanged(Base):

    def test_all_five_production_sites_pass_a_branch_id(self):
        src = _inspect.getsource(w.run_client_pipeline)
        self.assertEqual(src.count("mark_deterministic_branch"), 5)
        for branch in d.BRANCH_IDS:
            self.assertIn(f"BRANCH_{branch}", src,
                          f"no production site marks {branch}")

    def test_duplicate_detection_unchanged(self):
        rows = [{"turn_id": "a"}, {"turn_id": "a"}, {"turn_id": "b"}]
        self.assertEqual(cli.find_duplicates(rows), [("a", 2)])

    def test_flush_still_idempotent(self):
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        with mock.patch.object(d.db, "insert", lambda *a, **k: None):
            self.assertIsNotNone(d.flush())
            self.assertIsNone(d.flush())

    def test_record_field_set_is_exactly_as_approved(self):
        d.open_turn(); d.mark_identity("CLIENT")
        self.assertEqual(set(d.build_record()), {
            "tenant_id", "schema_version", "turn_id", "brain_version",
            "route", "role", "identity_degraded", "decisive_rung", "branch_id",
            "gate_results", "ai_consulted", "ai_consultation_reason",
            "ai_provider", "selected_tools", "denied_tools", "tool_results",
            "latency_ms",
        })

    def test_writes_only_to_the_decision_table(self):
        """Behavioural: capture the table actually passed to db.insert.
        (Scanning the source for 'bic_replay_records' would fail on the
        comment that explains why the two tables are separate.)"""
        seen = {}
        d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_OFF_TOPIC)
        with mock.patch.object(d.db, "insert",
                               lambda t, r, **k: seen.update(table=t)):
            d.flush()
        self.assertEqual(seen["table"], "bic_decision_records")


if __name__ == "__main__":
    unittest.main(verbosity=2)
