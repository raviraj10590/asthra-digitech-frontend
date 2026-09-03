"""Durable Meta retry deduplication, keyed by wamid.

THE DEFECT
----------
is_duplicate_webhook() compares inbound text against ctx["last_user"], read at
the START of the request — but the inbound message is only persisted by
save_messages() AFTER generate_reply() and AFTER send_text(). Production p50
for an AI turn is ~24s and 56.9% of turns exceed 20s, so on most turns Meta's
retry arrives while the message is still invisible to that check, is not
recognised as a duplicate, and produces a SECOND reply to a real customer.

THE FIX
-------
Claim Meta's own delivery id before any processing. The claim is an INSERT on
a PRIMARY KEY: the unique violation IS the duplicate answer, so two concurrent
retries cannot both win. A read-then-write check would reopen the same race.

Offline: no network, no AI, no database.
"""

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

from bic import webhook_events as ev                    # noqa: E402
from bic.db import DbError                              # noqa: E402

WAMID = "wamid.HBgMOTE5OTk5MDAwNTU1FQIAEhgg"
OTHER = "wamid.HBgMOTE5OTk5MDAwNjY2FQIAEhgg"
MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
SQL = os.path.join(MIG, "20260816000013_bic_webhook_events.sql")


class FakeEventsDb:
    """In-memory bic_webhook_events, enforcing the PRIMARY KEY like Postgres."""

    def __init__(self):
        self.rows = {}
        self.inserts = 0

    def insert(self, table, row, timeout=None):
        self.inserts += 1
        if row["wamid"] in self.rows:
            raise DbError('bic_webhook_events insert 409: duplicate key value '
                          'violates unique constraint "bic_webhook_events_pkey"')
        self.rows[row["wamid"]] = dict(row)

    def update(self, table, params, patch, timeout=None):
        key = params["wamid"][3:]
        if key in self.rows:
            self.rows[key].update(patch)

    def select(self, table, params, timeout=None):
        key = params.get("wamid", "eq.")[3:]
        return [dict(self.rows[key])] if key in self.rows else []


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeEventsDb()
        self._p = [
            mock.patch.object(ev, "insert", self.db.insert),
            mock.patch.object(ev, "update", self.db.update),
            mock.patch.object(ev, "select", self.db.select),
            mock.patch.object(ev.config, "is_configured", lambda: True),
        ]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()


# ── 1-2, 9-10 · the claim ──────────────────────────────────────────────────

class Claiming(Base):

    def test_first_wamid_is_accepted(self):
        self.assertEqual(ev.claim(WAMID), ev.ACCEPTED)
        self.assertEqual(self.db.rows[WAMID]["state"], ev.ACCEPTED)

    def test_same_wamid_twice_is_duplicate(self):
        self.assertEqual(ev.claim(WAMID), ev.ACCEPTED)
        self.assertEqual(ev.claim(WAMID), ev.DUPLICATE)

    def test_duplicate_writes_no_second_row(self):
        ev.claim(WAMID); ev.claim(WAMID)
        self.assertEqual(len(self.db.rows), 1)

    def test_different_wamids_are_independent(self):
        self.assertEqual(ev.claim(WAMID), ev.ACCEPTED)
        self.assertEqual(ev.claim(OTHER), ev.ACCEPTED)
        self.assertEqual(len(self.db.rows), 2)

    def test_concurrent_identical_claims_yield_exactly_one_winner(self):
        """The race the old check could not survive: two retries arriving
        together. The PRIMARY KEY serialises them — no read-then-write."""
        results = [ev.claim(WAMID) for _ in range(5)]
        self.assertEqual(results.count(ev.ACCEPTED), 1)
        self.assertEqual(results.count(ev.DUPLICATE), 4)
        self.assertEqual(self.db.inserts, 5)     # every attempt hit the DB
        self.assertEqual(len(self.db.rows), 1)   # exactly one survived

    def test_duplicate_after_completion_is_still_duplicate(self):
        ev.claim(WAMID)
        ev.mark(WAMID, ev.COMPLETED)
        self.assertEqual(ev.claim(WAMID), ev.DUPLICATE)

    def test_missing_wamid_does_not_block_the_turn(self):
        self.assertEqual(ev.claim(""), ev.ACCEPTED)
        self.assertEqual(len(self.db.rows), 0)


# ── 6-7 · state machine ────────────────────────────────────────────────────

class StateMachine(Base):

    def test_normal_transition(self):
        ev.claim(WAMID)
        ev.mark(WAMID, ev.PROCESSING)
        self.assertEqual(self.db.rows[WAMID]["state"], ev.PROCESSING)
        ev.mark(WAMID, ev.COMPLETED)
        row = self.db.rows[WAMID]
        self.assertEqual(row["state"], ev.COMPLETED)
        self.assertIsNotNone(row["completed_at"])
        self.assertNotIn("failure_class", row)

    def test_failed_transition_records_a_bounded_class(self):
        ev.claim(WAMID)
        ev.mark(WAMID, ev.PROCESSING)
        ev.mark(WAMID, ev.FAILED, "DATABASE")
        row = self.db.rows[WAMID]
        self.assertEqual(row["state"], ev.FAILED)
        self.assertEqual(row["failure_class"], "DATABASE")
        self.assertIsNotNone(row["completed_at"])

    def test_unknown_failure_class_is_coerced_not_stored_raw(self):
        ev.claim(WAMID)
        ev.mark(WAMID, ev.FAILED, "psycopg2.OperationalError: could not connect")
        self.assertEqual(self.db.rows[WAMID]["failure_class"], "UNKNOWN")

    def test_unknown_state_is_ignored(self):
        ev.claim(WAMID)
        ev.mark(WAMID, "WEDGED")
        self.assertEqual(self.db.rows[WAMID]["state"], ev.ACCEPTED)

    def test_crash_before_processing_leaves_ACCEPTED(self):
        ev.claim(WAMID)
        self.assertEqual(self.db.rows[WAMID]["state"], ev.ACCEPTED)

    def test_crash_during_processing_leaves_PROCESSING(self):
        """Stuck in-flight is the observable symptom of a crash — visible,
        not silent, and the partial index exists to find it."""
        ev.claim(WAMID)
        ev.mark(WAMID, ev.PROCESSING)
        self.assertEqual(self.db.rows[WAMID]["state"], ev.PROCESSING)
        self.assertEqual(ev.claim(WAMID), ev.DUPLICATE)  # retry still blocked


# ── 8, 12 · no raw text, no PII ────────────────────────────────────────────

class NoRawTextOrPii(Base):

    SECRET = "919999000555 said: email ravi@example.com"

    def test_no_exception_text_reaches_the_row(self):
        ev.claim(WAMID)
        ev.mark(WAMID, ev.FAILED, self.SECRET)
        blob = str(self.db.rows[WAMID])
        self.assertNotIn("919999000555", blob)
        self.assertNotIn("ravi@example.com", blob)
        self.assertEqual(self.db.rows[WAMID]["failure_class"], "UNKNOWN")

    def test_row_carries_only_the_approved_fields(self):
        ev.claim(WAMID)
        self.assertEqual(set(self.db.rows[WAMID]), {"wamid", "tenant_id", "state"})

    def test_module_accepts_no_message_or_phone_parameter(self):
        import inspect
        for fn in (ev.claim, ev.mark, ev.lookup):
            params = set(inspect.signature(fn).parameters)
            for banned in ("text", "message", "phone", "sender", "body", "prompt"):
                self.assertNotIn(banned, params, f"{fn.__name__}({banned})")

    def test_failure_vocabulary_matches_the_decision_record(self):
        from bic import decision
        self.assertEqual(set(ev.FAILURE_CLASSES), set(decision.FAILURE_CLASSES))


# ── fail-open ──────────────────────────────────────────────────────────────

class FailOpen(Base):

    def test_store_unavailable_accepts_rather_than_dropping_the_turn(self):
        """A duplicate reply is bad. No reply at all, because a bookkeeping
        table blipped, is worse."""
        with mock.patch.object(ev, "insert", side_effect=DbError("connection refused")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ev.claim(WAMID), ev.ACCEPTED)
            self.assertIn("WEBHOOK_CLAIM_UNAVAILABLE", buf.getvalue())

    def test_unconfigured_bic_accepts_silently(self):
        with mock.patch.object(ev.config, "is_configured", lambda: False):
            self.assertEqual(ev.claim(WAMID), ev.ACCEPTED)

    def test_mark_failure_never_raises(self):
        ev.claim(WAMID)
        with mock.patch.object(ev, "update", side_effect=DbError("down")):
            with redirect_stdout(io.StringIO()):
                ev.mark(WAMID, ev.COMPLETED)   # must not raise


# ── 3-5, 11 · integration with the live webhook ────────────────────────────

class WebhookIntegration(unittest.TestCase):

    def test_claim_runs_before_every_dispatch_fork(self):
        """Placed at the earliest point where the wamid is known, so it also
        protects interactive menu taps and media acknowledgements."""
        import inspect, webhook as w
        src = inspect.getsource(w.handler.do_POST)
        claim_at = src.index("bic_events.claim(")
        for later in ('if msg_type == "interactive"', "send_typing(",
                      "_decision_open(", "run_client_pipeline("):
            self.assertLess(claim_at, src.index(later), f"claim must precede {later}")

    def test_duplicate_returns_before_any_side_effect(self):
        import inspect, webhook as w
        src = inspect.getsource(w.handler.do_POST)
        block = src[src.index("bic_events.claim("):]
        early_exit = block.index("self._ok(); return")
        for side_effect in ("send_typing(", "_decision_open(",
                            "run_client_pipeline(", "generate_reply("):
            idx = block.find(side_effect)
            if idx != -1:
                self.assertLess(early_exit, idx,
                                f"{side_effect} reachable before the duplicate return")

    def test_legacy_content_dedupe_is_retained(self):
        """The two guards answer different questions: this one catches a
        genuine re-send that Meta gives a NEW wamid."""
        import webhook as w
        self.assertTrue(callable(w.is_duplicate_webhook))
        import inspect
        self.assertIn("is_duplicate_webhook(ctx", inspect.getsource(w.handler.do_POST))

    def test_terminal_states_are_marked_around_dispatch(self):
        """PROCESSING is written in do_POST; the terminals moved into
        _finalize_delivery so that EVERY exit path reaches one — including the
        six early-return branches that used to strand rows at ACCEPTED."""
        import inspect, webhook as w
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn("bic_events.PROCESSING", src)
        self.assertIn("_finalize_delivery(lifecycle", src)
        fin = inspect.getsource(w._finalize_delivery)
        self.assertIn("bic_events.COMPLETED", fin)
        self.assertIn("bic_events.FAILED", fin)

    def test_processing_is_marked_before_any_early_return(self):
        """The regression guard for the original bug: no `return` may sit
        between the claim and the PROCESSING mark."""
        import inspect, re, webhook as w
        src = inspect.getsource(w.handler.do_POST).splitlines()
        claim = next(i for i, l in enumerate(src) if "bic_events.claim" in l)
        proc = next(i for i, l in enumerate(src) if "bic_events.PROCESSING" in l)
        # Comments stripped first. A comment reading "before ANY branch can
        # return" is prose, not a return statement, and matching it reports a
        # leak that does not exist.
        code = [l.split("#", 1)[0] for l in src[claim + 1:proc]]
        between = [l.strip() for l in code if re.search(r"\breturn\b", l)]
        # Exactly one may precede it: the DUPLICATE path, which deliberately
        # creates no new row and must not touch the winner's.
        self.assertEqual(len(between), 1, f"unguarded returns: {between}")

    def test_failed_mark_uses_the_bounded_class_not_the_exception(self):
        import inspect, webhook as w
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn("_turn_failure_class(_e)", src)
        self.assertNotIn("str(_e)", src)


# ── 8, 13 · schema ─────────────────────────────────────────────────────────

class Schema(unittest.TestCase):

    def _sql(self):
        with open(SQL) as fh:
            return fh.read()

    def _code(self):
        return "\n".join(l for l in self._sql().splitlines()
                         if not l.strip().startswith("--"))

    def test_wamid_is_the_primary_key(self):
        self.assertRegex(self._code(), r"wamid\s+text primary key")

    def test_tenant_id_present_but_not_in_the_key(self):
        """Article II.5 convention — but a wamid is globally unique at Meta,
        so keying on tenant too would let one delivery be claimed twice."""
        code = self._code()
        self.assertRegex(code, r"tenant_id\s+uuid not null")
        self.assertNotRegex(code, r"primary key\s*\([^)]*tenant_id")

    def test_state_and_failure_vocabularies_are_closed(self):
        code = self._code()
        self.assertIn("'ACCEPTED', 'PROCESSING', 'COMPLETED', 'FAILED'", code)
        for cls in ev.FAILURE_CLASSES:
            self.assertIn(f"'{cls}'", code)

    def test_terminal_state_requires_a_completion_timestamp(self):
        self.assertIn("bic_webhook_events_completion_pair", self._code())

    def test_no_pii_columns(self):
        """Scans COLUMN NAMES, not prose. The COMMENT ON statements
        necessarily discuss "the inbound message" to explain the defect."""
        body = self._code().split("create table if not exists bic_webhook_events")[1]
        body = body.split(");")[0]
        columns = set()
        for line in body.splitlines():
            m = re.match(r"\s*([a-z_]+)\s+(text|uuid|timestamptz)", line)
            if m:
                columns.add(m.group(1))
        self.assertEqual(columns, {"wamid", "tenant_id", "state",
                                   "failure_class", "created_at",
                                   "updated_at", "completed_at"})

    def test_rls_on_with_zero_policies(self):
        code = self._code()
        self.assertIn("enable row level security", code)
        self.assertNotIn("create policy", code)

    def test_migration_is_additive_only(self):
        code = self._code().lower()
        for banned in ("drop ", "delete ", "truncate", "alter table bic_claims",
                       "pg_cron", "cron.schedule", "on delete cascade"):
            self.assertNotIn(banned, code)

    def test_deliberately_no_append_only_trigger(self):
        """Unlike claims and decision records, these rows MUST transition."""
        self.assertNotIn("bic_reject_mutation", self._code())


if __name__ == "__main__":
    unittest.main(verbosity=2)
