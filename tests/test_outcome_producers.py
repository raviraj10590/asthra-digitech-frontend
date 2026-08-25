"""IDD-2I — the first real outcome producer (customer_reply).

Two layers:
  - Producer unit tests: bic/outcome_producers.py against a fake outcomes
    store, offline (no network, no AI, no database).
  - Webhook eligibility tests: which branches of run_client_pipeline call
    into the producer, proven from the real function (not a reimplementation
    of it), with the producer calls themselves mocked out.

Ineligible-branch and "unchanged" claims (webhook lifecycle, #why, #suffice)
are proven by the existing suites for those modules continuing to pass
unmodified — not duplicated here.
"""

import ast
import os
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import outcome_producers as op                          # noqa: E402
from bic import outcomes as oc                                   # noqa: E402
from bic.db import DbError                                       # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
SENDER = "919999000111"
OTHER_SENDER = "919999000222"
DECISION = "dec-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def ts(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def code_only(path) -> str:
    """Source with docstrings/string literals blanked — comments are already
    invisible to ast.unparse(). Mirrors tests/test_outcomes.py's helper."""
    tree = ast.parse(pathlib.Path(path).read_text())

    class Blank(ast.NodeTransformer):
        def visit_Constant(self, n):
            if isinstance(n.value, str):
                return ast.copy_location(ast.Constant(value=""), n)
            return n

    return ast.unparse(Blank().visit(tree))


PRODUCER_MODULE = os.path.join(os.path.dirname(__file__), "..", "bic",
                               "outcome_producers.py")


class FakeOutcomeDb:
    """In-memory bic_outcome_records store that honours order/limit like
    PostgREST does — test_outcomes.py's fake ignores both, which would
    silently break _latest_outcome_row's "most recent row" query."""

    def __init__(self):
        self.records = []

    def insert(self, table, row, timeout=None):
        if table == oc.TABLE:
            self.records.append(dict(row))
        elif table == oc.RETRACTIONS_TABLE:
            pass
        else:
            raise AssertionError(f"unexpected table {table}")

    def select(self, table, params, timeout=None):
        rows = self.records if table == oc.TABLE else []
        out = []
        for row in rows:
            keep = True
            for key, val in params.items():
                if key in ("order", "limit", "select"):
                    continue
                val = str(val)
                if val.startswith("eq.") and str(row.get(key)) != val[3:]:
                    keep = False
            if keep:
                out.append(dict(row))
        order = params.get("order")
        if order:
            field, _, direction = order.partition(".")
            out.sort(key=lambda r: r.get(field) or "",
                     reverse=(direction == "desc"))
        limit = params.get("limit")
        if limit:
            out = out[:int(limit)]
        return out


class Base(unittest.TestCase):

    def setUp(self):
        self.db = FakeOutcomeDb()
        self._p = [
            mock.patch.object(oc, "insert", self.db.insert),
            mock.patch.object(oc, "select", self.db.select),
            mock.patch.object(op.party, "resolve_or_create",
                              lambda tenant_id, channel, sender, kind=None:
                              f"subj-{tenant_id}-{sender}"),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()


# ── 1, 8 · expectation creation, attribution ────────────────────────────────

class ExpectationCreation(Base):

    def test_eligible_call_creates_expectation(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 1)
        rec = self.db.records[0]
        self.assertEqual(rec["decision_ref"], DECISION)
        self.assertEqual(rec["outcome_kind"], op.CUSTOMER_REPLY_KIND)
        self.assertEqual(rec["lifecycle"], oc.EXPECTED)
        self.assertEqual(rec["window_seconds"], op.CUSTOMER_REPLY_WINDOW_SECONDS)

    def test_missing_decision_ref_creates_nothing(self):
        """No attribution edge (I4) — never fabricate one."""
        op.expect_customer_reply(SENDER, "", tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 0)

    def test_party_resolution_failure_is_swallowed(self):
        with mock.patch.object(op.party, "resolve_or_create",
                               side_effect=DbError("down")):
            op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 0)

    def test_store_failure_is_swallowed(self):
        with mock.patch.object(oc, "insert", side_effect=DbError("down")):
            op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 0)

    def test_exactly_one_decision_ref(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        self.assertEqual(self.db.records[0]["decision_ref"], DECISION)

    def test_no_shortcut_attribution_columns(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        rec = self.db.records[0]
        for shortcut in ("customer_id", "project_id", "lead_id", "phone", "wamid"):
            self.assertNotIn(shortcut, rec)


# ── 3, 4, 5, 17 · observation, idempotency, append-only ─────────────────────

class ReplyObservation(Base):

    def test_reply_after_expectation_creates_observation(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        op.observe_customer_reply(SENDER, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 2)
        obs = self.db.records[1]
        self.assertEqual(obs["observed_state"], oc.RESOLVED)
        self.assertEqual(obs["observation_status"], oc.OBSERVED)
        self.assertEqual(obs["observed_by"], "whatsapp:inbound_message")
        # append-only: the original expectation row is untouched, not edited
        self.assertEqual(self.db.records[0]["lifecycle"], oc.EXPECTED)
        self.assertIsNone(self.db.records[0]["observed_state"])

    def test_unrelated_inbound_message_creates_no_observation(self):
        """No expectation was ever opened for this subject."""
        op.observe_customer_reply(OTHER_SENDER, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), 0)

    def test_second_reply_does_not_duplicate_the_observation(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        op.observe_customer_reply(SENDER, tenant_id=TENANT)
        after_first = len(self.db.records)
        op.observe_customer_reply(SENDER, tenant_id=TENANT)
        self.assertEqual(len(self.db.records), after_first)

    def test_observation_store_failure_is_swallowed(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        with mock.patch.object(oc, "insert", side_effect=DbError("down")):
            op.observe_customer_reply(SENDER, tenant_id=TENANT)


# ── 6, 7 · cron timeout sweep ────────────────────────────────────────────────

class TimeoutSweep(Base):

    def test_expired_window_is_swept_as_no_response(self):
        past = ts("2000-01-01T00:00:00")
        oc.expect(TENANT, "subj-x", DECISION, outcome_kind=op.CUSTOMER_REPLY_KIND,
                 window_seconds=60, at=past)
        result = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(result["swept"], 1)
        self.assertEqual(len(self.db.records), 2)
        obs = self.db.records[1]
        self.assertEqual(obs["observed_state"], oc.NO_RESPONSE)
        self.assertEqual(obs["observation_status"], oc.TIMED_OUT)

    def test_repeated_sweep_does_not_duplicate_the_timeout(self):
        past = ts("2000-01-01T00:00:00")
        oc.expect(TENANT, "subj-x", DECISION, outcome_kind=op.CUSTOMER_REPLY_KIND,
                 window_seconds=60, at=past)
        first = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        second = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(first["swept"], 1)
        self.assertEqual(second["swept"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(self.db.records), 2)

    def test_open_window_is_not_swept(self):
        oc.expect(TENANT, "subj-x", DECISION, outcome_kind=op.CUSTOMER_REPLY_KIND,
                 window_seconds=86400)
        result = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(result["swept"], 0)
        self.assertEqual(len(self.db.records), 1)

    def test_already_replied_window_is_not_timed_out(self):
        past = ts("2000-01-01T00:00:00")
        exp = oc.expect(TENANT, "subj-x", DECISION, outcome_kind=op.CUSTOMER_REPLY_KIND,
                        window_seconds=60, at=past)
        oc.observe(TENANT, exp, oc.RESOLVED, oc.OBSERVED,
                  observed_at=past + timedelta(seconds=30))
        result = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(result["swept"], 0)
        self.assertEqual(len(self.db.records), 2)

    def test_sweep_only_touches_customer_reply_kind(self):
        past = ts("2000-01-01T00:00:00")
        oc.expect(TENANT, "subj-x", DECISION, outcome_kind="owner_engagement",
                 window_seconds=60, at=past)
        result = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(result["swept"], 0)
        self.assertEqual(len(self.db.records), 1)

    def test_sweep_failure_on_one_row_does_not_block_others(self):
        past = ts("2000-01-01T00:00:00")
        oc.expect(TENANT, "subj-a", DECISION, outcome_kind=op.CUSTOMER_REPLY_KIND,
                 window_seconds=60, at=past)
        real_time_out = oc.time_out
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            raise DbError("down")

        with mock.patch.object(oc, "time_out", flaky):
            result = op.sweep_customer_reply_timeouts(tenant_id=TENANT)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["swept"], 0)


# ── 9 · tenant isolation ─────────────────────────────────────────────────────

class TenantIsolation(Base):

    def test_observe_does_not_cross_tenants(self):
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        op.observe_customer_reply(SENDER, tenant_id=OTHER_TENANT)
        self.assertEqual(len(self.db.records), 1)
        self.assertEqual(self.db.records[0]["lifecycle"], oc.EXPECTED)


# ── 10, 11, 12, 16, 18 · security/boundaries ────────────────────────────────

class SecurityAndBoundaries(Base):

    def test_no_pii_vocabulary_in_producer_code(self):
        code = code_only(PRODUCER_MODULE).lower()
        for banned in ("phone", "email", "wamid", "message_body"):
            self.assertNotIn(banned, code)

    def test_no_ai_or_provider_dependency(self):
        code = code_only(PRODUCER_MODULE).lower()
        for banned in ("openai", "gemini", "deepseek", "llm", "completion",
                       "embed"):
            self.assertNotIn(banned, code)

    def test_never_writes_to_claims_or_party_tables(self):
        code = code_only(PRODUCER_MODULE)
        for banned in ("bic_claims", "bic_parties", "assert_claim"):
            self.assertNotIn(banned, code)

    def test_does_not_call_evaluate_or_learning_readiness(self):
        """This slice records outcomes; it does not judge or learn from them
        (IDD-2I Step 9 — do not implement learning)."""
        code = code_only(PRODUCER_MODULE)
        self.assertNotIn("evaluate(", code)
        self.assertNotIn("learning_readiness(", code)

    def test_observed_reply_is_not_learning_ready(self):
        """A freshly observed-but-unconfirmed reply must still fail 2I's own
        readiness gate — this producer creates provisional evidence, not
        confirmed evidence."""
        op.expect_customer_reply(SENDER, DECISION, tenant_id=TENANT)
        op.observe_customer_reply(SENDER, tenant_id=TENANT)
        view = oc.current(TENANT, DECISION)
        entry = view[op.CUSTOMER_REPLY_KIND]
        r = oc.learning_readiness(entry["record"], entry["lifecycle"])
        self.assertTrue(r["provisional"])
        self.assertFalse(r["ready"])


# ── source shape: exactly one eligible action, one universal observe site ──

class EligibleActionScope(unittest.TestCase):
    """Proves scope from the real webhook.py source rather than reproducing
    it — matches this codebase's own test_branch_id.py / test_decision_record
    pattern (inspect.getsource + count)."""

    @classmethod
    def setUpClass(cls):
        import webhook as w
        cls.src = __import__("inspect").getsource(w.run_client_pipeline)

    def test_expect_customer_reply_is_registered_once_per_path(self):
        """Still ONE eligible action (the AI reply), now reachable by two
        mutually exclusive paths: the Brain branch registers it after ⑫
        confirms delivery, the legacy branch in its own `else`. A turn takes
        exactly one of them, so a turn opens at most one window — proven
        behaviourally in test_brain_decision_loop's ExecutionRecovery."""
        self.assertEqual(self.src.count("expect_customer_reply("), 2)
        brain = self.src.index("_bic_decide_and_record(")
        legacy = self.src.index("# Legacy path — unchanged.")
        first = self.src.index("expect_customer_reply(")
        second = self.src.index("expect_customer_reply(", first + 1)
        self.assertLess(brain, first, "the brain registration follows DECIDE")
        self.assertLess(legacy, second, "the second lives in the legacy path")

    def test_the_brain_registration_follows_delivery_not_precedes_it(self):
        """Registering before the send opened a window for a message that
        might never go out; 2I would close it as NO_RESPONSE when we never
        asked."""
        self.assertLess(self.src.index("EXECUTION_OBSERVED"),
                        self.src.index("expect_customer_reply("))

    def test_observe_customer_reply_is_called_once_unconditionally(self):
        self.assertEqual(self.src.count("observe_customer_reply("), 1)
        # placed before the branch fork, so it runs for every dispatched turn
        fork = self.src.index("is_new_contact")
        self.assertLess(self.src.index("observe_customer_reply("), fork)

    def test_expect_call_is_inside_the_normal_ai_reply_branch(self):
        marker = self.src.index("Normal AI reply")
        self.assertGreater(self.src.index("expect_customer_reply("), marker)
