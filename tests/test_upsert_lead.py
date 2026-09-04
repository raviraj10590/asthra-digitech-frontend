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


def run(status=None, exc=None, data=_UNSET, synced=True, why="ok"):
    """Drive the REAL upsert_lead. Returns (stdout, posts, invocations)."""
    posts, invocations = [], []

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
         mock.patch.object(w, "invoke_tool", fake_invoke), \
         redirect_stdout(buf):
        w.upsert_lead(PHONE, LEAD if data is _UNSET else data)
    return buf.getvalue(), posts, invocations


# ══════════════════════════════════════════════════════════════════════════
# 1 · the three response outcomes
# ══════════════════════════════════════════════════════════════════════════

class ResponseHandling(unittest.TestCase):

    def test_2xx_logs_success(self):
        out, posts, _ = run(status=201)
        self.assertIn("LEAD_UPSERT_OK", out)
        self.assertNotIn("LEAD_UPSERT_FAILED", out)
        self.assertEqual(len(posts), 1)

    def test_4xx_does_not_claim_success(self):
        """THE REGRESSION. A rejected write must never log success."""
        out, _, _ = run(status=401)
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertIn("LEAD_UPSERT_FAILED", out)

    def test_5xx_does_not_claim_success(self):
        out, _, _ = run(status=500)
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertIn("LEAD_UPSERT_FAILED", out)

    def test_the_status_code_is_captured(self):
        """The single fact the old code destroyed, and the whole point of the
        change: 401 (RLS) and 409 (constraint) need different remedies."""
        for status in (400, 401, 403, 404, 409, 500, 503):
            with self.subTest(status=status):
                out, _, _ = run(status=status)
                self.assertIn(f"status={status}", out)

    def test_the_old_unconditional_success_string_is_gone(self):
        """Guards the exact phrasing that misled the production log for a
        month, on both the success and failure paths."""
        for status in (201, 401, 500):
            with self.subTest(status=status):
                out, _, _ = run(status=status)
                self.assertNotIn("lead upserted", out)

    def test_2xx_boundary_is_at_400(self):
        for ok_status in (200, 201, 204):
            self.assertIn("LEAD_UPSERT_OK", run(status=ok_status)[0])
        for bad_status in (400, 422):
            self.assertIn("LEAD_UPSERT_FAILED", run(status=bad_status)[0])


class TransportException(unittest.TestCase):

    def test_exception_does_not_claim_success(self):
        out, _, _ = run(exc=RuntimeError("connection reset"))
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertNotIn("lead upserted", out)

    def test_exception_behaviour_is_preserved(self):
        """Unchanged from before: the marker and the exception text."""
        out, _, _ = run(exc=RuntimeError("connection reset"))
        self.assertIn("upsert_lead error", out)
        self.assertIn("connection reset", out)

    def test_exception_still_reaches_the_crm_step(self):
        _, _, inv = run(exc=RuntimeError("boom"))
        self.assertEqual([i["code"] for i in inv], ["crm_capture_self"])


# ══════════════════════════════════════════════════════════════════════════
# 2 · PII — neither log may carry the lead
# ══════════════════════════════════════════════════════════════════════════

class NoPiiInLogs(unittest.TestCase):

    def test_success_log_carries_no_lead_payload(self):
        out, _, _ = run(status=201)
        for secret in PII:
            self.assertNotIn(secret, out, secret)

    def test_failure_log_carries_no_lead_payload(self):
        out, _, _ = run(status=401)
        for secret in PII:
            self.assertNotIn(secret, out, secret)

    def test_only_the_phone_suffix_appears(self):
        """Matches the LEAD_CRM_SYNC_FAILED convention one line below."""
        for status in (201, 401):
            out, _, _ = run(status=status)
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
             mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
             redirect_stdout(buf):
            w.upsert_lead(PHONE, LEAD)
        out = buf.getvalue()
        self.assertIn("status=409", out)
        self.assertNotIn("Ravi Kumar", out)
        self.assertNotIn(PHONE, out)

    def test_crm_failure_marker_still_redacts(self):
        out, _, _ = run(status=201, synced=False, why="not permitted")
        self.assertIn("LEAD_CRM_SYNC_FAILED", out)
        self.assertIn(f"phone=...{LAST4}", out)
        self.assertNotIn(PHONE, out)


# ══════════════════════════════════════════════════════════════════════════
# 3 · everything else must be byte-identical
# ══════════════════════════════════════════════════════════════════════════

class UnchangedBehaviour(unittest.TestCase):

    def test_empty_data_posts_nothing(self):
        for empty in ({}, None):
            out, posts, inv = run(status=201, data=empty)
            self.assertEqual(posts, [])
            self.assertEqual(inv, [])
            self.assertEqual(out, "")

    def test_payload_endpoint_headers_and_timeout_are_unchanged(self):
        _, posts, _ = run(status=201)
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
                _, _, inv = run(status=status)
                self.assertEqual(len(inv), 1)
                self.assertEqual(inv[0]["code"], "crm_capture_self")
                self.assertEqual(inv[0]["kw"]["data"], LEAD)

    def test_a_failed_upsert_with_a_failed_sync_is_visibly_lost(self):
        """The comment this replaced claimed the lead "IS still in the leads
        table, so this is recoverable" — untrue exactly when the upsert
        failed, which is the production case."""
        out, _, _ = run(status=401, synced=False, why="denied")
        self.assertIn("LEAD_UPSERT_FAILED", out)
        self.assertIn("stored=False", out)

    def test_a_successful_upsert_reports_stored_true(self):
        out, _, _ = run(status=201, synced=False, why="denied")
        self.assertIn("stored=True", out)

    def test_no_real_http_is_performed(self):
        """The suite replaces requests.post entirely; nothing here can leave
        the process."""
        import inspect
        src = inspect.getsource(w.upsert_lead)
        self.assertIn("requests.post", src)
        _, posts, _ = run(status=201)
        self.assertEqual(len(posts), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
