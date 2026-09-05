"""`upsert_lead` — the write that announced success 17 times and stored 0 rows.

THE DEFECT THIS PINS
--------------------
requests.post() does NOT raise on 4xx/5xx; it returns a Response. The previous
implementation was:

    try:
        requests.post(...)
        print(f"lead upserted: {data}")
    except Exception as e:
        ...

so every PostgREST rejection fell straight through to an unconditional success
log. Production evidence: 17 `crm_capture_self` audit rows (that tool is
invoked on the line after the POST, so it counts executions of upsert_lead)
matching 17 declared_service_interest claims, against 0 rows in `leads`. The
HTTP status that would have named the cause — RLS denial, constraint
violation, bad Prefer target — was discarded all 17 times.

This suite drives the REAL upsert_lead with fake Response objects. It does not
fix the underlying rejection: it makes the rejection visible, which is what
lets the next task read the status and choose the actual remedy.

SECOND DEFECT, SAME FUNCTION: the success log printed the whole lead dict —
name, company, budget, city — into Vercel logs. The redaction convention
already existed one line below it (`LEAD_CRM_SYNC_FAILED phone=...{last4}`)
and simply was not applied.

Offline: no HTTP, no provider, no database. Every network primitive is
replaced by a fake.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

PHONE = "919999000444"
LAST4 = PHONE[-4:]
# A lead carrying every PII-bearing field the old success log leaked.
LEAD = {"name": "Ravi Kumar", "company": "Acme Traders",
        "service_needed": "Digital Ads", "budget": "50000",
        "city": "Bengaluru"}
PII = ("Ravi Kumar", "Acme Traders", "50000", "Bengaluru", PHONE)


class FakeResponse:
    """Exactly the surface upsert_lead touches: .ok, .status_code, .text.

    `ok` is computed the way requests does — 2xx/3xx true, 4xx/5xx false — so
    a test cannot accidentally set a status and an inconsistent ok.
    """

    def __init__(self, status_code, text="[]"):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return self.status_code < 400


_UNSET = object()   # so data=None can mean "explicitly empty", not "omitted"


# The leads WRITE now authenticates with the service-role credential, because
# `leads` holds customer PII and correctly denies INSERT to the public anon
# role (production: anon SELECT 200, anon INSERT 401 / 42501). A fake value is
# injected here so the suite exercises the real header-building path; the
# missing-credential case has its own class below.
FAKE_SERVICE_ROLE = "test-service-role-key-not-a-real-credential"
FAKE_ANON = "test-anon-key-not-a-real-credential"


def run(status=None, exc=None, data=_UNSET, synced=True, why="ok",
        audit_raises=None, service_role=FAKE_SERVICE_ROLE, anon=FAKE_ANON):
    """Drive the REAL upsert_lead.

    Returns (stdout, posts, invocations, audits) — `audits` are the durable
    bic_tool_invocations rows the write produced.
    """
    posts, invocations, audits = [], [], []

    def fake_db_insert(table, row, timeout=None):
        audits.append({"table": table, "row": row})
        if audit_raises is not None:
            raise audit_raises

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "headers": headers, "json": json,
                      "timeout": timeout})
        if exc is not None:
            raise exc
        return FakeResponse(status)

    def fake_invoke(phone, code, _fallback=None, **kw):
        invocations.append({"phone": phone, "code": code, "kw": kw})
        return synced, why

    buf = io.StringIO()
    with mock.patch.object(w.requests, "post", fake_post), \
         mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", service_role), \
         mock.patch.object(w, "SUPABASE_KEY", anon), \
         mock.patch.object(w, "invoke_tool", fake_invoke), \
         mock.patch.object(w, "BIC_AVAILABLE", True), \
         mock.patch.object(w.bic_config, "is_configured", lambda: True), \
         mock.patch.object(w.bic_db, "insert", fake_db_insert), \
         redirect_stdout(buf):
        w.upsert_lead(PHONE, LEAD if data is _UNSET else data)
    return buf.getvalue(), posts, invocations, audits


# ══════════════════════════════════════════════════════════════════════════
# 1 · the three response outcomes
# ══════════════════════════════════════════════════════════════════════════

class ResponseHandling(unittest.TestCase):

    def test_2xx_logs_success(self):
        out, posts, _, _ = run(status=201)
        self.assertIn("LEAD_UPSERT_OK", out)
        self.assertNotIn("LEAD_UPSERT_FAILED", out)
        self.assertEqual(len(posts), 1)

    def test_4xx_does_not_claim_success(self):
        """THE REGRESSION. A rejected write must never log success."""
        out, _, _, _ = run(status=401)
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertIn("LEAD_UPSERT_FAILED", out)

    def test_5xx_does_not_claim_success(self):
        out, _, _, _ = run(status=500)
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertIn("LEAD_UPSERT_FAILED", out)

    def test_the_status_code_is_captured(self):
        """The single fact the old code destroyed, and the whole point of the
        change: 401 (RLS) and 409 (constraint) need different remedies."""
        for status in (400, 401, 403, 404, 409, 500, 503):
            with self.subTest(status=status):
                out, _, _, _ = run(status=status)
                self.assertIn(f"status={status}", out)

    def test_the_old_unconditional_success_string_is_gone(self):
        """Guards the exact phrasing that misled the production log for a
        month, on both the success and failure paths."""
        for status in (201, 401, 500):
            with self.subTest(status=status):
                out, _, _, _ = run(status=status)
                self.assertNotIn("lead upserted", out)

    def test_2xx_boundary_is_at_400(self):
        for ok_status in (200, 201, 204):
            self.assertIn("LEAD_UPSERT_OK", run(status=ok_status)[0])
        for bad_status in (400, 422):
            self.assertIn("LEAD_UPSERT_FAILED", run(status=bad_status)[0])


class TransportException(unittest.TestCase):

    def test_exception_does_not_claim_success(self):
        out, _, _, _ = run(exc=RuntimeError("connection reset"))
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertNotIn("lead upserted", out)

    def test_exception_behaviour_is_preserved(self):
        """Unchanged from before: the marker and the exception text."""
        out, _, _, _ = run(exc=RuntimeError("connection reset"))
        self.assertIn("upsert_lead error", out)
        self.assertIn("connection reset", out)

    def test_exception_still_reaches_the_crm_step(self):
        _, _, inv, _ = run(exc=RuntimeError("boom"))
        self.assertEqual([i["code"] for i in inv], ["crm_capture_self"])


# ══════════════════════════════════════════════════════════════════════════
# 2 · PII — neither log may carry the lead
# ══════════════════════════════════════════════════════════════════════════

class NoPiiInLogs(unittest.TestCase):

    def test_success_log_carries_no_lead_payload(self):
        out, _, _, _ = run(status=201)
        for secret in PII:
            self.assertNotIn(secret, out, secret)

    def test_failure_log_carries_no_lead_payload(self):
        out, _, _, _ = run(status=401)
        for secret in PII:
            self.assertNotIn(secret, out, secret)

    def test_only_the_phone_suffix_appears(self):
        """Matches the LEAD_CRM_SYNC_FAILED convention one line below."""
        for status in (201, 401):
            out, _, _, _ = run(status=status)
            self.assertIn(f"phone=...{LAST4}", out)
            self.assertNotIn(PHONE, out)

    def test_the_error_body_is_never_logged(self):
        """A PostgREST error body echoes the offending row — which for this
        table is precisely the PII the success log was cleaned of."""
        posts_text = "duplicate key value violates unique constraint: " \
                     "Key (phone)=(919999000444) name=Ravi Kumar"

        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(409, text=posts_text)
        buf = io.StringIO()
        with mock.patch.object(w.requests, "post", fake_post), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY",
                               FAKE_SERVICE_ROLE), \
             mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
             redirect_stdout(buf):
            w.upsert_lead(PHONE, LEAD)
        out = buf.getvalue()
        self.assertIn("status=409", out)
        self.assertNotIn("Ravi Kumar", out)
        self.assertNotIn(PHONE, out)

    def test_crm_failure_marker_still_redacts(self):
        out, _, _, _ = run(status=201, synced=False, why="not permitted")
        self.assertIn("LEAD_CRM_SYNC_FAILED", out)
        self.assertIn(f"phone=...{LAST4}", out)
        self.assertNotIn(PHONE, out)


# ══════════════════════════════════════════════════════════════════════════
# 3 · everything else must be byte-identical
# ══════════════════════════════════════════════════════════════════════════

class UnchangedBehaviour(unittest.TestCase):

    def test_empty_data_posts_nothing(self):
        for empty in ({}, None):
            out, posts, inv, _ = run(status=201, data=empty)
            self.assertEqual(posts, [])
            self.assertEqual(inv, [])
            self.assertEqual(out, "")

    def test_payload_endpoint_headers_and_timeout_are_unchanged(self):
        _, posts, _, _ = run(status=201)
        p = posts[0]
        self.assertTrue(p["url"].endswith("/rest/v1/leads"))
        self.assertEqual(p["json"], {"phone": PHONE, **LEAD})
        self.assertEqual(p["headers"]["Prefer"], "resolution=merge-duplicates")
        self.assertEqual(p["timeout"], 5)

    def test_crm_invocation_is_preserved_on_success_and_failure(self):
        """The CRM step is deliberately NOT gated on the upsert result —
        preserving existing behaviour, so a rejected lead still reaches the
        CRM rather than being lost by both stores at once."""
        for status in (201, 401, 500):
            with self.subTest(status=status):
                _, _, inv, _ = run(status=status)
                self.assertEqual(len(inv), 1)
                self.assertEqual(inv[0]["code"], "crm_capture_self")
                self.assertEqual(inv[0]["kw"]["data"], LEAD)

    def test_a_failed_upsert_with_a_failed_sync_is_visibly_lost(self):
        """The comment this replaced claimed the lead "IS still in the leads
        table, so this is recoverable" — untrue exactly when the upsert
        failed, which is the production case."""
        out, _, _, _ = run(status=401, synced=False, why="denied")
        self.assertIn("LEAD_UPSERT_FAILED", out)
        self.assertIn("stored=False", out)

    def test_a_successful_upsert_reports_stored_true(self):
        out, _, _, _ = run(status=201, synced=False, why="denied")
        self.assertIn("stored=True", out)

    def test_no_real_http_is_performed(self):
        """The suite replaces requests.post entirely; nothing here can leave
        the process."""
        import inspect
        src = inspect.getsource(w.upsert_lead)
        self.assertIn("requests.post", src)
        _, posts, _, _ = run(status=201)
        self.assertEqual(len(posts), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
# 4 · the DURABLE record — the log line is not enough
# ══════════════════════════════════════════════════════════════════════════

class DurableOutcomeRecord(unittest.TestCase):
    """Vercel retains logs ~1 hour; a lead-writing event happens roughly once
    a day. The status that identifies the production failure therefore has to
    live in a table, not a log line.
    """

    def audit(self, **kw):
        _, _, _, audits = run(**kw)
        self.assertEqual(len(audits), 1, "expected exactly one durable row")
        self.assertEqual(audits[0]["table"], "bic_tool_invocations")
        return audits[0]["row"]

    def test_2xx_records_a_success_row(self):
        row = self.audit(status=201)
        self.assertTrue(row["ok"])
        self.assertEqual(row["tool"], w.LEAD_UPSERT_EVENT)
        self.assertTrue(row["args_redacted"]["stored"])
        self.assertIsNone(row["error"])

    def test_4xx_records_a_failure_row_with_the_status(self):
        row = self.audit(status=401)
        self.assertFalse(row["ok"])
        self.assertEqual(row["args_redacted"]["http_status"], 401)
        self.assertEqual(row["error"], "http_401")

    def test_5xx_records_a_failure_row_with_the_status(self):
        row = self.audit(status=503)
        self.assertFalse(row["ok"])
        self.assertEqual(row["args_redacted"]["http_status"], 503)
        self.assertEqual(row["error"], "http_503")

    def test_every_candidate_status_is_preserved_exactly(self):
        """400 / 401 / 409 lead to three DIFFERENT remedies. Collapsing them
        would send the next fix hunting for the wrong thing."""
        for status in (400, 401, 403, 404, 409, 500, 503):
            with self.subTest(status=status):
                row = self.audit(status=status)
                self.assertEqual(row["args_redacted"]["http_status"], status)
                self.assertEqual(row["error"], f"http_{status}")

    def test_transport_exception_is_distinguishable_from_rejection(self):
        """No HTTP status exists when the request never reached PostgREST.
        None + the exception type says so; http_0 or a fake status would not."""
        row = self.audit(exc=TimeoutError("timed out"))
        self.assertFalse(row["ok"])
        self.assertIsNone(row["args_redacted"]["http_status"])
        self.assertEqual(row["error"], "TimeoutError")

    def test_a_failed_response_never_records_success(self):
        for status in (400, 401, 500):
            with self.subTest(status=status):
                row = self.audit(status=status)
                self.assertFalse(row["ok"])
                self.assertFalse(row["args_redacted"]["stored"])

    def test_empty_data_records_nothing(self):
        _, posts, inv, audits = run(status=201, data={})
        self.assertEqual((posts, inv, audits), ([], [], []))

    def test_latency_and_timestamps_are_present(self):
        row = self.audit(status=201)
        self.assertIsInstance(row["latency_ms"], int)
        self.assertGreaterEqual(row["latency_ms"], 0)
        self.assertIn("started_at", row)
        self.assertIn("finished_at", row)

    def test_the_row_satisfies_the_tables_not_null_columns(self):
        """tenant_id, tool, role and ok are NOT NULL in migration
        20260802000003; a row missing any of them would be rejected — and
        this record exists precisely because a rejected write went unnoticed."""
        row = self.audit(status=401)
        for col in ("tenant_id", "tool", "role", "ok"):
            self.assertIsNotNone(row.get(col), col)


class DurableRecordCarriesNoPii(unittest.TestCase):

    def row(self, **kw):
        return run(**kw)[3][0]["row"]

    def test_no_lead_values_are_stored(self):
        for status in (201, 401):
            blob = str(self.row(status=status))
            for secret in PII:
                self.assertNotIn(secret, blob, f"{secret} @ {status}")

    def test_only_field_names_are_stored_never_values(self):
        row = self.row(status=401)
        self.assertEqual(row["args_redacted"]["fields"],
                         ["budget", "city", "company", "name", "service_needed"])

    def test_the_full_phone_is_not_stored(self):
        row = self.row(status=401)
        self.assertEqual(row["source_ref"], f"...{LAST4}")
        self.assertNotIn(PHONE, str(row))

    def test_the_postgrest_error_body_is_never_stored(self):
        """The body echoes the offending row — the very PII this record is
        built to exclude. Only the bounded status code is kept."""
        body = "Key (phone)=(919999000444) name=Ravi Kumar budget=50000"

        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(409, text=body)
        audits = []
        with mock.patch.object(w.requests, "post", fake_post), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY",
                               FAKE_SERVICE_ROLE), \
             mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
             mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(w.bic_db, "insert",
                               lambda t, r, timeout=None: audits.append(r)), \
             redirect_stdout(io.StringIO()):
            w.upsert_lead(PHONE, LEAD)
        blob = str(audits[0])
        self.assertIn("http_409", blob)
        self.assertNotIn("Ravi Kumar", blob)
        self.assertNotIn(PHONE, blob)
        self.assertNotIn("50000", blob)


class DurableRecordIsBestEffort(unittest.TestCase):
    """Business continuity outranks audit completeness — bic/tools.py::_audit
    states the same rule. A logging failure must never break a lead capture
    that already happened."""

    def test_an_audit_failure_does_not_raise(self):
        out, posts, inv, _ = run(status=201,
                                 audit_raises=RuntimeError("store down"))
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(inv), 1)
        self.assertIn("LEAD_UPSERT_AUDIT_FAILED", out)

    def test_an_audit_failure_logs_the_type_only(self):
        out, _, _, _ = run(status=401,
                           audit_raises=RuntimeError(f"row {PHONE} rejected"))
        self.assertIn("RuntimeError", out)
        self.assertNotIn(PHONE, out)

    def test_the_crm_step_still_runs_after_an_audit_failure(self):
        _, _, inv, _ = run(status=401, audit_raises=RuntimeError("x"))
        self.assertEqual([i["code"] for i in inv], ["crm_capture_self"])

    def test_nothing_is_recorded_when_bic_is_unavailable(self):
        audits = []
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: FakeResponse(401)), \
             mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             mock.patch.object(w.bic_db, "insert",
                               lambda t, r, timeout=None: audits.append(r)), \
             redirect_stdout(io.StringIO()):
            w.upsert_lead(PHONE, LEAD)
        self.assertEqual(audits, [])

    def test_the_event_code_is_not_a_registered_tool(self):
        """Deliberately unregistered: nothing invokes it, and a bic_tool_defs
        row would advertise a capability that does not exist. The column is
        not a FK, which is what makes this legitimate."""
        mig = os.path.join(os.path.dirname(__file__), "..", "supabase",
                           "migrations")
        for name in os.listdir(mig):
            with open(os.path.join(mig, name)) as fh:
                sql = "\n".join(l for l in fh if not l.strip().startswith("--"))
            self.assertNotIn(f"'{w.LEAD_UPSERT_EVENT}'", sql, name)
