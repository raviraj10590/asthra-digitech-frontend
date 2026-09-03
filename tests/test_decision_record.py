"""Decision Record slice — the artifact 3C emits and 3D consumes.

WHAT THESE TESTS LOCK
---------------------
1.  the decisive rung reflects what actually settled the turn
2.  all eight 3C gates appear on every record; only backed ones report PASS/FAIL
3.  AI consultation is recorded positively when it happens
4.  AI NON-consultation is recorded positively when it does not (3D §4.2 / I10)
5.  the non-consultation reason is structured and deterministic
6.  no PII, message, prompt, model prose or evidence value can enter the record
7.  the 1C replay path is untouched and still works
8.  schema_version is present and forward-compatible
9.  BIC_REPLAY_SKIP_ROLES still governs ONLY the 1C table; the Decision Record
    has no skip
10. RUNG_3 is emitted only for an OBSERVED deterministic branch, and
    ai_consulted=False alone can never produce it

Offline: no network, no AI, no database.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import decision as d                            # noqa: E402
import webhook as w                                      # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        d.close_turn()

    def tearDown(self):
        d.close_turn()


# ── 1 · decisive rung ──────────────────────────────────────────────────────

class DecisiveRung(Base):

    def test_model_consultation_yields_rung_5(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_consulted("openai")
        self.assertEqual(d.build_record()["decisive_rung"], d.RUNG_5_MODEL_ADVISORY)

    def test_observed_deterministic_branch_yields_rung_3(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        self.assertEqual(d.build_record()["decisive_rung"], d.RUNG_3_DETERMINISTIC)

    def test_policy_denial_yields_rung_2(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_tool_denied("send_brochure")
        self.assertEqual(d.build_record()["decisive_rung"], d.RUNG_2_POLICY)

    def test_nothing_observed_yields_not_evaluated(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        self.assertEqual(d.build_record()["decisive_rung"], d.NOT_EVALUATED)

    def test_lowest_rung_wins(self):
        """3C §2.1 — the ladder stops at the first decisive rung."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        d.mark_ai_consulted("openai")
        d.mark_tool_denied("send_brochure")
        self.assertEqual(d.build_record()["decisive_rung"], d.RUNG_2_POLICY)

    def test_unimplemented_rungs_are_never_emitted(self):
        """Rung 1 degrades rather than rejecting; rung 4 (OI) does not exist."""
        for marks in (
            lambda: None,
            lambda: d.mark_ai_consulted("openai"),
            lambda: d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST),
            lambda: d.mark_tool_denied("x"),
            lambda: d.mark_capability_failure(),
        ):
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT", degraded=True)
            marks()
            rung = d.build_record()["decisive_rung"]
            self.assertIn(rung, d.EMITTABLE_RUNGS)
            self.assertNotEqual(rung, d.RUNG_1_CONSTITUTIONAL)
            self.assertNotEqual(rung, d.RUNG_4_PRECEDENT)


# ── 10 · RUNG_3 may never be inferred ──────────────────────────────────────

class Rung3RequiresAWitness(Base):
    """The approved safety rule: RUNG_3 only for an OBSERVED terminating
    branch. `ai_consulted is False` is also true when the model was
    unavailable, when the turn errored, and when nothing happened."""

    def test_no_ai_alone_does_not_produce_rung_3(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        rec = d.build_record()
        self.assertFalse(rec["ai_consulted"])
        self.assertEqual(rec["decisive_rung"], d.NOT_EVALUATED)

    def test_provider_failure_does_not_produce_rung_3(self):
        """Every provider failed — no model output, but a model WAS consulted."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_all_providers_failed()
        rec = d.build_record()
        self.assertNotEqual(rec["decisive_rung"], d.RUNG_3_DETERMINISTIC)
        self.assertTrue(rec["ai_consulted"])

    def test_capability_failure_alone_does_not_produce_rung_3(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_capability_failure()
        self.assertEqual(d.build_record()["decisive_rung"], d.NOT_EVALUATED)

    def test_witness_plus_later_ai_call_is_not_rung_3(self):
        """A branch that marked itself but did NOT prevent consultation did not
        settle the turn."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        d.mark_ai_consulted("gemini")
        self.assertEqual(d.build_record()["decisive_rung"], d.RUNG_5_MODEL_ADVISORY)


# ── 2 · gate results ───────────────────────────────────────────────────────

class GateResults(Base):

    def test_all_eight_keys_always_present(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        gates = d.build_record()["gate_results"]
        self.assertEqual(set(gates), set(d.GATE_KEYS))
        self.assertEqual(len(gates), 8)

    def test_unbacked_gates_are_always_not_evaluated(self):
        """2H sufficiency, 3B goals, budgets and risk tiers do not exist."""
        d.open_turn()
        d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        d.mark_ai_consulted("openai")
        gates = d.build_record()["gate_results"]
        for key in d.GATES_WITHOUT_BACKING:
            self.assertEqual(gates[key], d.NOT_EVALUATED, f"{key} must not claim a result")

    def test_constitutional_passes_when_identity_resolved(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        self.assertEqual(d.build_record()["gate_results"]["constitutional"], d.PASS)

    def test_authorization_fails_on_denial(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_tool_denied("send_brochure")
        self.assertEqual(d.build_record()["gate_results"]["authorization"], d.FAIL)

    def test_authorization_passes_when_a_tool_ran(self):
        d.open_turn()
        d.mark_identity("OWNER")
        d.mark_tool_invoked("send_brochure")
        self.assertEqual(d.build_record()["gate_results"]["authorization"], d.PASS)

    def test_authorization_not_evaluated_when_no_tool_was_tried(self):
        """"We did not check" is not "we checked and it was fine"."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_consulted("openai")
        self.assertEqual(d.build_record()["gate_results"]["authorization"], d.NOT_EVALUATED)

    def test_capability_fails_distinctly_from_authorization(self):
        """3B §4.2 — absent is not the same as not permitted."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_capability_failure()
        gates = d.build_record()["gate_results"]
        self.assertEqual(gates["capability"], d.FAIL)
        self.assertEqual(gates["authorization"], d.NOT_EVALUATED)


# ── 3 & 4 · consultation recorded positively, both ways ────────────────────

class ConsultationIsPositivelyRecorded(Base):

    def test_consultation_records_flag_and_provider(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_consulted("deepseek")
        rec = d.build_record()
        self.assertTrue(rec["ai_consulted"])
        self.assertEqual(rec["ai_provider"], "deepseek")
        self.assertEqual(rec["ai_consultation_reason"], d.CONSULTED_RESPONSE_GENERATION)

    def test_non_consultation_is_never_absent_or_null(self):
        """3D §4.2 — silence is not an answer. The fields are always present."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        rec = d.build_record()
        self.assertIn("ai_consulted", rec)
        self.assertIn("ai_consultation_reason", rec)
        self.assertIs(rec["ai_consulted"], False)
        self.assertIsNotNone(rec["ai_consultation_reason"])
        self.assertNotEqual(rec["ai_consultation_reason"], "")

    def test_provider_is_null_when_not_consulted(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        self.assertIsNone(d.build_record()["ai_provider"])

    def test_all_providers_failed_is_still_consultation(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_all_providers_failed()
        rec = d.build_record()
        self.assertTrue(rec["ai_consulted"])
        self.assertEqual(rec["ai_consultation_reason"], d.CONSULTED_ALL_PROVIDERS_FAILED)


# ── 5 · the reason vocabulary is closed and deterministic ──────────────────

class ReasonIsStructured(Base):

    VOCAB = {
        d.CONSULTED_RESPONSE_GENERATION, d.CONSULTED_ALL_PROVIDERS_FAILED,
        d.NOT_CONSULTED_DETERMINISTIC_BRANCH, d.NOT_CONSULTED_CHAT_PAUSED,
        d.NOT_CONSULTED_POLICY_DENIED, d.NOT_CONSULTED_NOT_REQUIRED,
    }

    def test_reason_is_always_from_the_closed_vocabulary(self):
        for marks in (
            lambda: None,
            lambda: d.mark_ai_consulted("openai"),
            lambda: d.mark_ai_all_providers_failed(),
            lambda: d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST),
            lambda: d.mark_deterministic_branch(d.BRANCH_CHAT_PAUSED, d.NOT_CONSULTED_CHAT_PAUSED),
            lambda: d.mark_tool_denied("x"),
            lambda: d.mark_capability_failure(),
        ):
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
            marks()
            self.assertIn(d.build_record()["ai_consultation_reason"], self.VOCAB)

    def test_paused_chat_has_its_own_reason(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_CHAT_PAUSED, d.NOT_CONSULTED_CHAT_PAUSED)
        self.assertEqual(d.build_record()["ai_consultation_reason"],
                         d.NOT_CONSULTED_CHAT_PAUSED)

    def test_denial_reason_beats_branch_reason(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        d.mark_tool_denied("send_brochure")
        self.assertEqual(d.build_record()["ai_consultation_reason"],
                         d.NOT_CONSULTED_POLICY_DENIED)

    def test_same_marks_produce_the_same_reason_every_time(self):
        seen = set()
        for _ in range(25):
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
            d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
            seen.add(d.build_record()["ai_consultation_reason"])
        self.assertEqual(len(seen), 1)


# ── 6 · PII lock ───────────────────────────────────────────────────────────

class NoPiiEverEntersTheRecord(Base):
    """The strongest test here. A leak in this record is a permanent one —
    there is no pruner, by design."""

    PHONE = "918861369951"
    KANNADA = "ನಮಸ್ಕಾರ, ನನಗೆ website ಬೇಕು"
    PROMPT = "You are Asthra DigiTech's assistant. Reply in Kannada."
    MODEL_PROSE = "ಖಂಡಿತ! ನಮ್ಮ ತಂಡ ಸಹಾಯ ಮಾಡುತ್ತದೆ."

    def _record_blob(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_route("client")
        d.mark_ai_consulted("openai")
        d.mark_tool_invoked("send_brochure")
        d.mark_tool_denied("crm_sync_lead")
        return json.dumps(d.build_record(), default=str, ensure_ascii=False)

    def test_no_phone_number_in_any_form(self):
        """The 4-digit suffix check was removed: PROBABILISTIC, not a leak.

        The record carries a random uuid4 turn_id, and a given 4-digit run
        occurs in 32 hex characters about 1 time in 2,300 — enough to fail
        the suite intermittently. The full number and the 6-digit prefix are
        kept: both are long enough that a collision is ~1e-6 or rarer, and
        anything genuinely derived from the phone would embed them.
        """
        blob = self._record_blob()
        self.assertNotIn(self.PHONE, blob)
        self.assertNotIn(self.PHONE[:6], blob)

    def test_no_message_prompt_or_model_prose(self):
        blob = self._record_blob()
        for secret in (self.KANNADA, self.PROMPT, self.MODEL_PROSE):
            self.assertNotIn(secret, blob)

    def test_field_set_is_exactly_the_approved_schema(self):
        """A new field cannot appear without this test failing — which is the
        point: PII arrives by accretion, one 'harmless' field at a time."""
        d.open_turn()
        d.mark_identity("CLIENT")
        self.assertEqual(set(d.build_record()), {
            "tenant_id", "schema_version", "turn_id", "brain_version",
            "route", "role", "identity_degraded", "decisive_rung", "branch_id",
            "gate_results", "ai_consulted", "ai_consultation_reason",
            "ai_provider", "selected_tools", "denied_tools", "tool_results",
            "latency_ms",
        })

    def test_module_exposes_no_way_to_pass_text(self):
        """Structural, not disciplinary: there is no parameter to abuse."""
        import inspect
        for name in ("mark_identity", "mark_route", "mark_ai_consulted",
                     "mark_deterministic_branch", "mark_tool_invoked",
                     "mark_tool_denied", "open_turn", "build_record"):
            params = set(inspect.signature(getattr(d, name)).parameters)
            for banned in ("text", "message", "prompt", "sender", "phone",
                           "body", "reply", "content"):
                self.assertNotIn(banned, params, f"{name} accepts {banned}")

    def test_turn_id_is_ours_not_metas(self):
        """Meta's wamid encodes the recipient number; ours is random."""
        import uuid
        d.open_turn()
        d.mark_identity("CLIENT")
        tid = d.build_record()["turn_id"]
        uuid.UUID(tid)                       # raises if not a real UUID
        self.assertNotIn("wamid", tid)
        # Full number, not a 4-digit slice: the slice collides with a random
        # uuid4 often enough to flake, and randomness is proved directly by
        # test_two_turns_get_different_ids below.
        self.assertNotIn(self.PHONE, tid)

    def test_two_turns_get_different_ids(self):
        d.open_turn(); first = d.current().turn_id
        d.close_turn()
        d.open_turn(); second = d.current().turn_id
        self.assertNotEqual(first, second)


# ── 7 · the 1C replay path is untouched ────────────────────────────────────

class PhaseOneCUnchanged(Base):

    def test_replay_module_still_intact(self):
        from bic import replay
        self.assertTrue(hasattr(replay, "Decision"))
        self.assertTrue(hasattr(replay, "decision_hash"))
        self.assertTrue(hasattr(replay, "compare"))

    def test_replay_records_table_is_a_different_table(self):
        self.assertNotEqual(d.TABLE, "bic_replay_records")
        self.assertEqual(d.TABLE, "bic_decision_records")

    def test_migration_defines_no_pruner_for_the_decision_table(self):
        """3D I5 retention invariant. bic_replay_records prunes at 30 days;
        this table must not, or the evidence deletes itself.

        Asserts on the MIGRATION, not on module prose — a comment saying
        "no pruner" is not the same fact as no pruner existing, and a test
        that reads comments passes while the behaviour walks away.
        """
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260811000001_bic_decision_records.sql")
        with open(path, encoding="utf-8") as fh:
            sql = fh.read().lower()
        # No function creation, no scheduled deletion, no TTL of any kind.
        self.assertNotIn("create or replace function", sql)
        self.assertNotIn("delete from", sql)
        self.assertNotIn("pg_cron", sql)
        # And the table it creates is the decision table, not the 1C one.
        self.assertIn("create table if not exists bic_decision_records", sql)
        self.assertNotIn("alter table bic_replay_records", sql)

    def test_digest_prunes_only_the_1c_table(self):
        """The daily digest must never be pointed at the decision table."""
        path = os.path.join(os.path.dirname(__file__), "..", "api", "digest.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("bic_prune_replay_records", src)
        self.assertNotIn("bic_decision_records", src)

    def test_replay_persist_still_writes_to_its_own_table(self):
        import inspect
        src = inspect.getsource(w._bic_persist_replay)
        self.assertIn("bic_replay_records", src)
        self.assertNotIn("bic_decision_records", src)


# ── 8 · schema version ─────────────────────────────────────────────────────

class SchemaVersion(Base):

    def test_schema_version_advanced_additively(self):
        """v2 added branch_id, v3 added tool_results. v1 and v2 rows remain
        readable, carrying NULL in the columns that did not yet exist."""
        d.open_turn()
        d.mark_identity("CLIENT")
        self.assertEqual(d.build_record()["schema_version"], 3)

    def test_reader_tolerates_unknown_future_keys(self):
        """3D §10.1 — additive evolution; old readers must not break."""
        d.open_turn()
        d.mark_identity("CLIENT")
        rec = d.build_record()
        rec["some_future_field_v4"] = "x"
        self.assertEqual(json.loads(json.dumps(rec, default=str))["schema_version"], 3)

    def test_brain_version_is_always_recorded(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        bv = d.build_record()["brain_version"]
        self.assertTrue(bv)
        self.assertIsInstance(bv, str)


# ── 9 · skip-role contract ─────────────────────────────────────────────────

class SkipRolesGovernOnlyThe1CTable(Base):

    def test_replay_skip_roles_default_is_unchanged(self):
        self.assertEqual(
            os.environ.get("BIC_REPLAY_SKIP_ROLES", "OWNER"), "OWNER")

    def test_decision_record_has_no_skip_mechanism(self):
        import inspect
        src = inspect.getsource(d)
        self.assertNotIn("SKIP_ROLES", src)

    def test_owner_turn_still_produces_a_decision_record(self):
        """The role bic_replay_records skips must still be recorded here."""
        d.open_turn()
        d.mark_identity("OWNER")
        d.mark_route("owner")
        rec = d.build_record()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["role"], "OWNER")

    def test_every_role_is_recorded(self):
        for role in ("OWNER", "STAFF", "MANAGER", "CLIENT"):
            d.close_turn(); d.open_turn(); d.mark_identity(role)
            self.assertEqual(d.build_record()["role"], role)


# ── Lifecycle ──────────────────────────────────────────────────────────────

class Lifecycle(Base):

    def test_marks_are_no_ops_when_no_turn_is_open(self):
        """Importing the module must never change behaviour on its own."""
        d.close_turn()
        d.mark_ai_consulted("openai")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        d.mark_tool_invoked("x")
        self.assertIsNone(d.build_record())

    def test_flush_closes_the_turn(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        with mock.patch.object(d.db, "insert", lambda *a, **k: None):
            d.flush()
        self.assertFalse(d.is_open())

    def test_flush_is_idempotent(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        with mock.patch.object(d.db, "insert", lambda *a, **k: None):
            first = d.flush()
            second = d.flush()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_persist_failure_never_raises(self):
        """A failed write must not affect the customer's turn."""
        d.open_turn()
        d.mark_identity("CLIENT")

        def boom(*a, **k):
            raise RuntimeError("supabase down")

        with mock.patch.object(d.db, "insert", boom):
            d.flush()          # must not raise
        self.assertFalse(d.is_open())

    def test_writes_to_the_decision_table(self):
        seen = {}
        d.open_turn()
        d.mark_identity("CLIENT")
        with mock.patch.object(d.db, "insert",
                               lambda t, r, **k: seen.update(table=t, row=r)):
            d.flush()
        self.assertEqual(seen["table"], "bic_decision_records")
        self.assertIn("decisive_rung", seen["row"])


# ── Wiring: the marks are actually reached from production code ────────────

class ProductionWiring(Base):

    def test_generate_ai_reply_marks_consultation(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        with mock.patch.object(w, "_provider_chain",
                               lambda: [("openai", lambda m, t: "hi")]):
            w._generate_ai_reply([{"role": "user", "content": "x"}], "sorry")
        rec = d.build_record()
        self.assertTrue(rec["ai_consulted"])
        self.assertEqual(rec["ai_provider"], "openai")

    def test_generate_ai_reply_marks_total_failure(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        with mock.patch.object(w, "_provider_chain",
                               lambda: [("openai", lambda m, t: "")]):
            w._generate_ai_reply([{"role": "user", "content": "x"}], "sorry")
        self.assertEqual(d.build_record()["ai_consultation_reason"],
                         d.CONSULTED_ALL_PROVIDERS_FAILED)

    def test_client_pipeline_branches_carry_a_witness(self):
        """Each deterministic branch must mark itself — otherwise RUNG_3 could
        only ever be inferred, which the approved design forbids."""
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertGreaterEqual(src.count("mark_deterministic_branch"), 5,
                                "a deterministic branch lost its witness")

    def test_do_post_flushes_in_a_finally(self):
        import inspect
        src = inspect.getsource(w.SimpleHandler.do_POST) \
            if hasattr(w, "SimpleHandler") else inspect.getsource(w.handler.do_POST)
        self.assertIn("_decision_open", src)
        self.assertIn("finally", src)
        self.assertIn("_decision_flush", src)

    def test_tools_reports_invocation_and_denial(self):
        import inspect
        from bic import tools
        src = inspect.getsource(tools.invoke)
        self.assertIn("mark_tool_invoked", src)
        self.assertIn("mark_tool_denied", src)
        self.assertIn("mark_capability_failure", src)



# ── Schema conformance — code vs migration, without a database ─────────────

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "supabase",
                         "migrations", "20260811000001_bic_decision_records.sql")

# Additive evolution spans several files: the CREATE TABLE plus every later
# ALTER ... ADD COLUMN. Reading only the first would make a column added in a
# follow-up migration look absent from the schema.
import glob as _glob
_MIGRATION_GLOB = os.path.join(os.path.dirname(__file__), "..", "supabase",
                               "migrations", "*bic_decision*.sql")


def _migration_sql():
    with open(MIGRATION, encoding="utf-8") as fh:
        return fh.read()


def _all_decision_sql():
    out = []
    for path in sorted(_glob.glob(_MIGRATION_GLOB)):
        with open(path, encoding="utf-8") as fh:
            out.append(fh.read())
    return "\n".join(out)


def _declared_columns():
    """Column names from the CREATE TABLE body.

    Deliberately a parse of the migration rather than a second hand-written
    list: two lists drift, and the drift is invisible until a live write fails.
    """
    import re
    sql = _migration_sql()
    body = sql.split("create table if not exists bic_decision_records", 1)[1]
    body = body.split("\n);", 1)[0]
    cols = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--") or line.startswith("("):
            continue
        m = re.match(r"^([a-z_]+)\s+(uuid|text|smallint|boolean|jsonb|numeric|timestamptz)",
                     line)
        if m:
            cols.append(m.group(1))
    # Columns introduced by later additive migrations.
    for m in re.finditer(r"add column if not exists\s+([a-z_]+)",
                         _all_decision_sql(), re.I):
        cols.append(m.group(1))
    return set(cols)


class SchemaConformance(Base):
    """The write path never runs against a real database in these tests, and in
    production a failed write is SWALLOWED. So a column-name mismatch would
    produce an archive that is silently empty while every test stays green.
    These tests are the only thing standing between that and a live deploy."""

    # Set by the DB, never sent by the writer.
    DB_DEFAULTED = {"id", "decided_at"}

    def test_migration_parses_to_the_expected_column_count(self):
        cols = _declared_columns()
        self.assertEqual(len(cols), 19, f"parsed {sorted(cols)}")

    def test_every_written_field_exists_as_a_column(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        written = set(d.build_record())
        missing = written - _declared_columns()
        self.assertEqual(missing, set(), f"written but not in schema: {missing}")

    def test_every_required_column_is_written(self):
        d.open_turn()
        d.mark_identity("CLIENT")
        written = set(d.build_record())
        required = _declared_columns() - self.DB_DEFAULTED
        self.assertEqual(required - written, set(),
                         f"column exists but nothing writes it: {required - written}")

    def test_not_null_columns_are_never_none(self):
        """A null into a NOT NULL column fails the insert — silently, because
        the write is best-effort."""
        for marks in (
            lambda: None,
            lambda: d.mark_ai_consulted("openai"),
            lambda: d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST),
            lambda: d.mark_tool_denied("x"),
        ):
            d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
            marks()
            rec = d.build_record()
            for col in ("tenant_id", "schema_version", "turn_id", "brain_version",
                        "route", "role", "identity_degraded", "decisive_rung",
                        "gate_results", "ai_consulted", "ai_consultation_reason"):
                self.assertIsNotNone(rec[col], f"{col} is NOT NULL in schema")

    def test_every_emittable_rung_satisfies_the_check_constraint(self):
        """If the code can emit a value the CHECK rejects, every write of that
        kind fails in production and nothing says so."""
        sql = _migration_sql()
        rung_clause = sql.split("check (decisive_rung in (", 1)[1].split("))", 1)[0]
        for rung in d.EMITTABLE_RUNGS:
            self.assertIn(f"'{rung}'", rung_clause, f"{rung} would be rejected")

    def test_every_reason_satisfies_the_check_constraint(self):
        sql = _migration_sql()
        clause = sql.split("check (ai_consultation_reason in (", 1)[1].split("))", 1)[0]
        for reason in (d.CONSULTED_RESPONSE_GENERATION,
                       d.CONSULTED_ALL_PROVIDERS_FAILED,
                       d.NOT_CONSULTED_DETERMINISTIC_BRANCH,
                       d.NOT_CONSULTED_CHAT_PAUSED,
                       d.NOT_CONSULTED_POLICY_DENIED,
                       d.NOT_CONSULTED_NOT_REQUIRED):
            self.assertIn(f"'{reason}'", clause, f"{reason} would be rejected")

    def test_provider_consistency_constraint_is_never_violated(self):
        """CHECK (ai_consulted = true or ai_provider is null)."""
        d.close_turn(); d.open_turn(); d.mark_identity("CLIENT")
        d.mark_deterministic_branch(d.BRANCH_MENU_REQUEST)
        rec = d.build_record()
        self.assertFalse(rec["ai_consulted"])
        self.assertIsNone(rec["ai_provider"])

    def test_record_is_json_serialisable(self):
        """db.insert sends it as JSON; an unserialisable value fails the write."""
        d.open_turn()
        d.mark_identity("CLIENT")
        d.mark_ai_consulted("openai")
        json.dumps(d.build_record())          # no default= crutch


class WriteFailsHarmlesslyUntilMigrated(Base):
    """Current production reality: the table does not exist yet."""

    def test_missing_table_does_not_break_the_turn(self):
        d.open_turn()
        d.mark_identity("CLIENT")

        def undefined_table(*a, **k):
            from bic.db import DbError
            raise DbError("bic_decision_records insert 404: relation does not exist")

        with mock.patch.object(d.db, "insert", undefined_table):
            self.assertIsNotNone(d.flush())   # returns the record, raises nothing
        self.assertFalse(d.is_open())

    def test_failure_is_logged_loudly_not_silently(self):
        """A silently failing archive looks healthy and is empty (3D §8.2)."""
        import contextlib, io
        buf = io.StringIO()
        d.open_turn()
        d.mark_identity("CLIENT")

        def boom(*a, **k):
            raise RuntimeError("relation does not exist")

        with mock.patch.object(d.db, "insert", boom), contextlib.redirect_stdout(buf):
            d.flush()
        self.assertIn("DECISION_RECORD persist failed", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
