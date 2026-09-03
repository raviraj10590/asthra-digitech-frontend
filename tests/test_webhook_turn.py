"""D2 — turn observability. Making vanishing turns visible.

THE DEFECT
----------
Two windows could swallow a turn without trace: a failure in fetch_context()
or get_role(), both BEFORE the Decision Record opens. A real message was once
investigated for an hour and the only available conclusion was "it never
arrived" — inferred from ABSENCE of evidence.

Everything from the routing fork onward was already covered: the Decision
Record flushes from a `finally`, so a turn that raises mid-dispatch is still
recorded. These tests lock the remaining gap.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
No HTTP status changes. Returning 5xx at the context/route stage would trigger
a Meta retry into a code path whose duplicate protection (is_duplicate_webhook)
depends on the very fetch_context that just failed — a retry storm with dedupe
blind. Tests below lock every status as unchanged.

No Decision Record is fabricated for a turn that never entered the decision
lifecycle. `decision_record: false` states the absence.

Offline: no network, no AI, no database.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                     # noqa: E402
from bic import decision as d                            # noqa: E402
from bic.db import DbError                               # noqa: E402

SENDER = "919999000111"
SECRET_TEXT = "my number is 919999000111 and email ravi@example.com"

VALID = {"entry": [{"changes": [{"value": {"messages": [
    {"from": SENDER, "type": "text", "id": "wamid.TEST",
     "text": {"body": SECRET_TEXT}}]}}]}]}


class Harness(unittest.TestCase):
    """Drives the real do_POST with a fake socket, capturing stdout."""

    def setUp(self):
        d.close_turn()

    def tearDown(self):
        d.close_turn()

    def _post(self, payload=None, raw=None, **patches):
        body = raw if raw is not None else json.dumps(payload or VALID).encode()

        handler = w.handler.__new__(w.handler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        status = {}
        handler.send_response = lambda c, *a: status.setdefault("code", c)
        handler.send_header = lambda *a, **k: None
        handler.end_headers = lambda: None

        defaults = {
            "send_typing": lambda *a, **k: None,
            "fetch_context": lambda s: {"history": [{"x": 1}], "paused": False,
                                        "vip_alerted": False, "last_user": {}},
            "get_role": lambda s: ("CLIENT", "Test"),
            "_bic_replay_compare": lambda *a, **k: None,
            "_decision_open": lambda *a, **k: None,
            "_decision_flush": lambda *a, **k: None,
            "run_client_pipeline": lambda *a, **k: None,
            "_bic_client_turn": lambda *a, **k: None,
            "_bic_enabled": lambda: False,
            "is_duplicate_webhook": lambda ctx, t: False,
        }
        defaults.update(patches)

        buf = io.StringIO()
        stack = [mock.patch.object(w, k, v) for k, v in defaults.items()]
        for p in stack:
            p.start()
        try:
            with redirect_stdout(buf):
                handler.do_POST()
        finally:
            for p in reversed(stack):
                p.stop()
        return buf.getvalue(), status.get("code")

    @staticmethod
    def _turns(out):
        return [json.loads(l.split("WEBHOOK_TURN ", 1)[1])
                for l in out.splitlines() if l.startswith("WEBHOOK_TURN ")]


# ── 1 & 11 · exactly one line per request ──────────────────────────────────

class ExactlyOnePerRequest(Harness):

    def test_success_emits_exactly_one(self):
        out, _ = self._post()
        self.assertEqual(len(self._turns(out)), 1)

    def test_parse_failure_emits_exactly_one(self):
        out, _ = self._post(raw=b"{not json")
        self.assertEqual(len(self._turns(out)), 1)

    def test_context_failure_emits_exactly_one(self):
        def boom(s):
            raise DbError("supabase down")
        out, _ = self._post(fetch_context=boom)
        self.assertEqual(len(self._turns(out)), 1)

    def test_receipt_payload_emits_exactly_one(self):
        out, _ = self._post({"entry": [{"changes": [
            {"value": {"statuses": [{"id": "x"}]}}]}]})
        self.assertEqual(len(self._turns(out)), 1)

    def test_empty_messages_emits_exactly_one(self):
        out, _ = self._post({"entry": [{"changes": [{"value": {}}]}]})
        self.assertEqual(len(self._turns(out)), 1)


# ── 2 · normal success ─────────────────────────────────────────────────────

class SuccessfulTurn(Harness):

    def test_outcome_is_ok(self):
        out, _ = self._post()
        self.assertEqual(self._turns(out)[0]["outcome"], "OK")

    def test_failure_class_is_null_on_success(self):
        out, _ = self._post()
        self.assertIsNone(self._turns(out)[0]["failure_class"])

    def test_dispatch_began_on_a_text_turn(self):
        out, _ = self._post()
        self.assertTrue(self._turns(out)[0]["dispatch_began"])

    def test_stage_reaches_dispatch(self):
        out, _ = self._post()
        self.assertEqual(self._turns(out)[0]["stage"], "DISPATCH")


# ── 3 · fetch_context failure ──────────────────────────────────────────────

class ContextFailure(Harness):

    def _run(self):
        def boom(s):
            raise DbError("connection refused to supabase")
        return self._post(fetch_context=boom)

    def test_stage_is_context(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["stage"], "CONTEXT")

    def test_outcome_is_internal_error(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["outcome"], "INTERNAL_ERROR")

    def test_no_decision_record_claimed(self):
        out, _ = self._run()
        self.assertFalse(self._turns(out)[0]["decision_record"])

    def test_dispatch_never_began(self):
        out, _ = self._run()
        self.assertFalse(self._turns(out)[0]["dispatch_began"])

    def test_no_decision_record_is_fabricated(self):
        """The turn never entered the decision lifecycle. Inventing a record
        would be manufactured evidence."""
        opened = []
        def boom(s):
            raise DbError("down")
        self._post(fetch_context=boom,
                   _decision_open=lambda *a, **k: opened.append(1))
        self.assertEqual(opened, [])

    def test_failure_class_is_database(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["failure_class"], "DATABASE")


# ── 4 · get_role failure ───────────────────────────────────────────────────

class RouteFailure(Harness):

    def _run(self):
        def boom(s):
            raise ConnectionError("role lookup unreachable")
        return self._post(get_role=boom)

    def test_stage_is_route(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["stage"], "ROUTE")

    def test_no_decision_record_claimed(self):
        out, _ = self._run()
        self.assertFalse(self._turns(out)[0]["decision_record"])

    def test_failure_class_is_connection(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["failure_class"], "CONNECTION")


# ── 5 · parse failure ──────────────────────────────────────────────────────

class ParseFailure(Harness):

    def test_malformed_json_is_parse_error(self):
        out, _ = self._post(raw=b"{not json at all")
        t = self._turns(out)[0]
        self.assertEqual(t["outcome"], "PARSE_ERROR")
        self.assertEqual(t["stage"], "PARSE")

    def test_missing_entry_is_parse_error(self):
        out, _ = self._post({"nope": True})
        self.assertEqual(self._turns(out)[0]["outcome"], "PARSE_ERROR")

    def test_missing_sender_is_parse_error(self):
        out, _ = self._post({"entry": [{"changes": [{"value": {"messages": [
            {"type": "text"}]}}]}]})
        self.assertEqual(self._turns(out)[0]["outcome"], "PARSE_ERROR")

    def test_parse_failure_claims_no_decision_record(self):
        out, _ = self._post(raw=b"{")
        self.assertFalse(self._turns(out)[0]["decision_record"])


# ── 6 · dispatch failure still yields a real Decision Record ───────────────

class DispatchFailure(Harness):

    def _run(self):
        def boom(*a, **k):
            raise RuntimeError("handler exploded")
        # Real _decision_open/_decision_flush so the accumulator behaves as in
        # production; only the DB write is stubbed.
        with mock.patch.object(d.db, "insert", lambda *a, **k: None):
            return self._post(
                run_client_pipeline=boom,
                _decision_open=w._decision_open,
                _decision_flush=w._decision_flush)

    def test_stage_is_dispatch(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["stage"], "DISPATCH")

    def test_decision_record_is_true(self):
        out, _ = self._run()
        self.assertTrue(self._turns(out)[0]["decision_record"])

    def test_outcome_is_internal_error(self):
        out, _ = self._run()
        self.assertEqual(self._turns(out)[0]["outcome"], "INTERNAL_ERROR")

    def test_a_real_decision_record_was_flushed(self):
        out, _ = self._run()
        self.assertIn("DECISION_RECORD ", out)

    def test_exactly_one_decision_record(self):
        """The `finally` must not produce a second one."""
        out, _ = self._run()
        self.assertEqual(out.count("DECISION_RECORD {"), 1)


# ── 7 & 8 · no PII, no raw exception text ──────────────────────────────────

class NothingSensitiveInTheLine(Harness):

    def _line(self, out):
        return [l for l in out.splitlines() if l.startswith("WEBHOOK_TURN ")][0]

    def test_no_sender_or_message_on_success(self):
        out, _ = self._post()
        line = self._line(out)
        self.assertNotIn(SENDER, line)
        self.assertNotIn("ravi@example.com", line)
        self.assertNotIn(SECRET_TEXT, line)

    def test_no_exception_message_on_failure(self):
        def boom(s):
            raise DbError(f"failed for {SENDER}: {SECRET_TEXT}")
        out, _ = self._post(fetch_context=boom)
        line = self._line(out)
        self.assertNotIn(SENDER, line)
        self.assertNotIn("ravi@example.com", line)
        self.assertNotIn("failed for", line)

    def test_no_stack_trace(self):
        def boom(s):
            raise ValueError("x")
        out, _ = self._post(fetch_context=boom)
        line = self._line(out)
        for token in ("Traceback", "File \"", "line ", ".py"):
            self.assertNotIn(token, line)

    def test_field_set_is_exactly_as_approved(self):
        out, _ = self._post()
        self.assertEqual(set(self._turns(out)[0]), {
            "outcome", "stage", "failure_class", "decision_record",
            "dispatch_began", "body_bytes"})

    def test_wamid_is_not_included(self):
        """Meta's wamid encodes the recipient number."""
        out, _ = self._post()
        self.assertNotIn("wamid", self._line(out))


# ── 9 · bounded vocabularies ───────────────────────────────────────────────

class BoundedVocabularies(Harness):

    OUTCOMES = {"OK", "PARSE_ERROR", "INTERNAL_ERROR"}
    STAGES = {"PARSE", "CONTEXT", "ROUTE", "DISPATCH"}
    CLASSES = {"TIMEOUT", "CONNECTION", "DATABASE", "VALUE", "PERMISSION",
               "UNKNOWN", None}

    def test_every_path_stays_in_vocabulary(self):
        def db_boom(s):
            raise DbError("x")
        def to_boom(s):
            raise TimeoutError("x")
        def val_boom(s):
            raise ValueError("x")
        cases = [{}, {"raw": b"{"}, {"fetch_context": db_boom},
                 {"get_role": to_boom}, {"fetch_context": val_boom}]
        for case in cases:
            out, _ = self._post(**case) if "raw" not in case \
                else self._post(raw=case["raw"])
            t = self._turns(out)[0]
            self.assertIn(t["outcome"], self.OUTCOMES)
            self.assertIn(t["stage"], self.STAGES)
            self.assertIn(t["failure_class"], self.CLASSES)

    def test_classifier_reuses_the_tools_taxonomy(self):
        from bic import decision as dd
        self.assertEqual(w._turn_failure_class(DbError("x")), dd.FAIL_DATABASE)
        self.assertEqual(w._turn_failure_class(TimeoutError()), dd.FAIL_TIMEOUT)
        self.assertEqual(w._turn_failure_class(RuntimeError()), dd.FAIL_UNKNOWN)


# ── 10 · body_bytes ────────────────────────────────────────────────────────

class BodyBytes(Harness):

    def test_matches_payload_length(self):
        payload = json.dumps(VALID).encode()
        out, _ = self._post()
        self.assertEqual(self._turns(out)[0]["body_bytes"], len(payload))

    def test_accurate_on_malformed_body(self):
        raw = b"{not json"
        out, _ = self._post(raw=raw)
        self.assertEqual(self._turns(out)[0]["body_bytes"], len(raw))


# ── 12 · HTTP status regression lock ───────────────────────────────────────

class HttpStatusUnchanged(Harness):
    """D2 must not alter retry semantics. Returning 5xx at CONTEXT would make
    Meta retry into a path whose dedupe depends on the fetch_context that just
    failed."""

    def test_success_is_200(self):
        _, code = self._post()
        self.assertEqual(code, 200)

    def test_parse_failure_is_200(self):
        _, code = self._post(raw=b"{")
        self.assertEqual(code, 200)

    def test_context_failure_is_200(self):
        def boom(s):
            raise DbError("x")
        _, code = self._post(fetch_context=boom)
        self.assertEqual(code, 200)

    def test_route_failure_is_200(self):
        def boom(s):
            raise ConnectionError("x")
        _, code = self._post(get_role=boom)
        self.assertEqual(code, 200)

    def test_dispatch_failure_is_200(self):
        def boom(*a, **k):
            raise RuntimeError("x")
        _, code = self._post(run_client_pipeline=boom)
        self.assertEqual(code, 200)

    def test_receipts_are_200(self):
        _, code = self._post({"entry": [{"changes": [
            {"value": {"statuses": [{"id": "x"}]}}]}]})
        self.assertEqual(code, 200)

    def test_no_5xx_anywhere_in_the_dispatch_paths(self):
        def boom(s):
            raise DbError("x")
        for case in ({}, {"fetch_context": boom}):
            _, code = self._post(**case)
            self.assertLess(code, 500)

    def test_source_adds_no_new_status_codes(self):
        """The only send_response calls remain the pre-existing 200/403/503."""
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        import re
        codes = sorted(set(re.findall(r"send_response\((\d{3})\)", src)))
        self.assertEqual(codes, ["403", "503"])   # 200 lives in _ok()


# ── Duplicate/retry semantics untouched ────────────────────────────────────

class RetrySemanticsUnchanged(Harness):

    def test_duplicate_still_short_circuits(self):
        seen = []
        out, code = self._post(is_duplicate_webhook=lambda ctx, t: True,
                               _decision_open=lambda *a, **k: seen.append(1))
        self.assertEqual(code, 200)
        self.assertEqual(seen, [], "duplicate reached the routing fork")
        self.assertEqual(len(self._turns(out)), 1)

    def test_duplicate_turn_reports_no_dispatch(self):
        out, _ = self._post(is_duplicate_webhook=lambda ctx, t: True)
        t = self._turns(out)[0]
        self.assertFalse(t["dispatch_began"])
        self.assertEqual(t["outcome"], "OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
