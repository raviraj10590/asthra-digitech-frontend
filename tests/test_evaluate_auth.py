"""The evaluation endpoint must not be reachable by strangers.

WHY THIS FILE EXISTS
--------------------
`api/evaluate.py` shipped with `do_GET` calling `run_evaluations()` on the
first line — no token, no User-Agent check, nothing. `digest.py` and
`lead.py` both gated; this one did not, and it was the only endpoint whose
work costs money on every call: it reads production conversations, spends one
GPT-4o-mini call PER CONVERSATION (up to EVAL_MAX_CONVERSATIONS), and writes
rows back to Supabase. An anonymous GET spent real credit.

It also had ZERO tests of any kind, which is why the hole survived. These
drive the REAL `do_GET` with a real request line — the same lesson as
test_http_integration.py, where an audit found the actual front door was
executed by none of the tests and the defect lived exactly there.

Offline: `requests` and the scorer are replaced by tripwires, so any attempt
to reach the network during a REJECTED request fails the test rather than
escaping.
"""

import io
import json
import os
import sys
import unittest
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import evaluate as ev                                            # noqa: E402

TOKEN = "test-verify-token"
CRON_UA = "vercel-cron/1.0"


class _Tripwire:
    """Stands in for `requests`. Any call is a failure, and records itself."""

    def __init__(self, log):
        self.log = log

    def get(self, *a, **k):
        self.log.append(("GET", a[0] if a else None))
        raise AssertionError("network GET during a rejected request")

    def post(self, *a, **k):
        self.log.append(("POST", a[0] if a else None))
        raise AssertionError("network POST during a rejected request")


def get(path="/api/evaluate", ua="curl/8.4.0", token=TOKEN, result=None):
    """Drive the REAL do_GET. Returns (status, body, effects)."""
    hdrs = Message()
    hdrs["User-Agent"] = ua

    h = object.__new__(ev.handler)
    h.headers = hdrs
    h.path = path
    h.wfile = io.BytesIO()

    status = []
    h.send_response = lambda code, *a: status.append(code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None

    effects = {"net": [], "scored": [], "swept": 0}

    def _sweep():
        effects["swept"] += 1
        return result if result is not None else {
            "scored": 0, "skipped": 0, "conversations": 0}

    def _score(transcript):
        effects["scored"].append(transcript)
        raise AssertionError("OpenAI call during a rejected request")

    env = {} if token is None else {"VERIFY_TOKEN": token}
    with mock.patch.dict(os.environ, env, clear=False):
        if token is None:
            os.environ.pop("VERIFY_TOKEN", None)
        # VERIFY_TOKEN is read at import time (module constant, exactly like
        # digest.py), so patch the constant the gate actually compares.
        with mock.patch.object(ev, "VERIFY_TOKEN", token or ""), \
             mock.patch.object(ev, "requests", _Tripwire(effects["net"])), \
             mock.patch.object(ev, "score_conversation", _score), \
             mock.patch.object(ev, "run_evaluations", _sweep):
            h.do_GET()

    return (status[0] if status else None), h.wfile.getvalue(), effects


# ── 1-2 · the hole itself ──────────────────────────────────────────────────

class UnauthenticatedIsRejected(unittest.TestCase):

    def test_no_credentials_at_all_is_403(self):
        st, _, fx = get()
        self.assertEqual(st, 403)
        self.assertEqual(fx["swept"], 0)

    def test_wrong_token_is_403(self):
        st, _, fx = get(path="/api/evaluate?key=wrong")
        self.assertEqual(st, 403)
        self.assertEqual(fx["swept"], 0)

    def test_rejected_request_makes_zero_openai_calls(self):
        _, _, fx = get(path="/api/evaluate?key=wrong")
        self.assertEqual(fx["scored"], [])

    def test_rejected_request_makes_zero_supabase_calls(self):
        """Reads AND writes: the tripwire raises on either verb."""
        for path in ("/api/evaluate", "/api/evaluate?key=wrong"):
            _, _, fx = get(path=path)
            self.assertEqual(fx["net"], [], path)

    def test_rejected_request_returns_no_body(self):
        _, body, _ = get()
        self.assertEqual(body, b"")


# ── 3 · the authorised paths still work ────────────────────────────────────

class AuthenticatedStillRuns(unittest.TestCase):

    def test_vercel_cron_user_agent_runs_the_sweep(self):
        st, body, fx = get(ua=CRON_UA)
        self.assertEqual(st, 200)
        self.assertEqual(fx["swept"], 1)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_manual_call_with_the_token_runs_the_sweep(self):
        st, body, fx = get(path=f"/api/evaluate?key={TOKEN}")
        self.assertEqual(st, 200)
        self.assertEqual(fx["swept"], 1)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_result_payload_is_unchanged(self):
        """Evaluation semantics preserved: same keys, same values, merged."""
        st, body, _ = get(ua=CRON_UA,
                          result={"scored": 3, "skipped": 7, "conversations": 11})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body),
                         {"status": "ok", "scored": 3, "skipped": 7,
                          "conversations": 11})

    def test_token_still_works_alongside_other_query_params(self):
        st, _, fx = get(path=f"/api/evaluate?foo=1&key={TOKEN}&bar=2")
        self.assertEqual(st, 200)
        self.assertEqual(fx["swept"], 1)


# ── 4 · the guard cannot be walked around ──────────────────────────────────

class GuardCannotBeBypassed(unittest.TestCase):

    def test_empty_key_parameter_is_403(self):
        st, _, fx = get(path="/api/evaluate?key=")
        self.assertEqual(st, 403)
        self.assertEqual(fx["swept"], 0)

    def test_an_empty_verify_token_does_not_authenticate_a_keyless_request(self):
        """The bug the `key and` clause exists for.

        With VERIFY_TOKEN == "" a plain `key != VERIFY_TOKEN` comparison makes
        a request carrying no ?key at all compare EQUAL and sail through.
        """
        st, _, fx = get(path="/api/evaluate", token=None)
        self.assertEqual(st, 403)
        self.assertEqual(fx["swept"], 0)
        st, _, fx = get(path="/api/evaluate?key=", token=None)
        self.assertEqual(st, 403)
        self.assertEqual(fx["swept"], 0)

    def test_token_prefix_or_suffix_is_not_enough(self):
        for bad in (TOKEN[:-1], TOKEN + "x", " " + TOKEN):
            st, _, fx = get(path=f"/api/evaluate?key={bad}")
            self.assertEqual(st, 403, bad)
            self.assertEqual(fx["swept"], 0, bad)

    def test_token_in_a_different_parameter_is_not_accepted(self):
        for path in (f"/api/evaluate?token={TOKEN}",
                     f"/api/evaluate?KEY={TOKEN}",
                     f"/api/evaluate#key={TOKEN}"):
            st, _, fx = get(path=path)
            self.assertEqual(st, 403, path)
            self.assertEqual(fx["swept"], 0, path)

    def test_a_missing_user_agent_header_does_not_crash_or_pass(self):
        hdrs = Message()
        h = object.__new__(ev.handler)
        h.headers = hdrs
        h.path = "/api/evaluate"
        h.wfile = io.BytesIO()
        status = []
        h.send_response = lambda code, *a: status.append(code)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        with mock.patch.object(ev, "VERIFY_TOKEN", TOKEN), \
             mock.patch.object(ev, "run_evaluations",
                               lambda: self.fail("swept without auth")):
            h.do_GET()
        self.assertEqual(status, [403])

    def test_the_gate_runs_before_any_work(self):
        """Structural, not behavioural: a refactor must not reorder these.

        Every paid action lives inside run_evaluations(), so the guard is only
        worth anything while it precedes that call in do_GET.
        """
        import inspect
        src = inspect.getsource(ev.handler.do_GET)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        self.assertLess(code.index("send_response(403)"),
                        code.index("run_evaluations()"))
        self.assertIn("return", code[:code.index("run_evaluations()")])

    def test_evaluate_reuses_the_digest_gate_rather_than_a_second_one(self):
        """§D1 in spirit: two authorization paths is one authorization hole."""
        import inspect
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
        import digest as dg
        for mod in (ev, dg):
            src = inspect.getsource(mod.handler.do_GET)
            self.assertIn("vercel-cron", src)
            self.assertIn("VERIFY_TOKEN", src)
        self.assertEqual(ev.VERIFY_TOKEN, dg.VERIFY_TOKEN)


# ── 5 · no secrets, no PII in this file's fixtures ─────────────────────────

class NoSecretsOrPII(unittest.TestCase):

    def test_no_real_phone_numbers_in_the_fixtures(self):
        import re
        with open(__file__) as fh:
            self.assertNotRegex(fh.read(), r"\b91\d{10}\b")

    def test_no_real_token_value_is_hardcoded(self):
        """Fixtures must not carry the shipped default token.

        The needle is assembled at runtime so that THIS assertion is not
        itself the match — the first version of this test failed on its own
        source, which proves the check reads the whole file.
        """
        needle = "asthra_" + "secret_" + "2024"
        with open(__file__) as fh:
            self.assertNotIn(needle, fh.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
