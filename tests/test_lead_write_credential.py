"""The `leads` write authenticates with the SERVICE-ROLE key, not the anon key.

THE DEFECT THIS FIXES
---------------------
`upsert_lead` posted to /rest/v1/leads with `SUPABASE_KEY` — the public anon
key. Production evidence, gathered over four tasks:

  anon  GET  /rest/v1/leads  -> HTTP 200   (key valid, table exposed)
  anon  POST /rest/v1/leads  -> HTTP 401   (durable: http_status=401, stored=false)
  service_role, same project -> BIC writes succeed continuously

Postgres raises 42501 insufficient_privilege, and PostgREST maps 42501 to 401
rather than 403 when the JWT role is the configured anon role — which is why an
AUTHORIZATION failure presented as an AUTHENTICATION one and stayed misread.

`leads` holds customer PII (name, company, budget, city, phone). The database
is RIGHT to refuse the public key; the application was wrong to offer it. The
fix gives this one write the privileged credential the same process already
holds and already uses successfully for the Brain tables. It does NOT grant
anon INSERT, which would widen a public credential's write surface to a PII
table to paper over an application-side credential choice.

THE BLAST RADIUS IS THE POINT
-----------------------------
`_supa_headers` has 19 call sites. Changing IT would have escalated all of
them to service-role — a blanket RLS bypass dressed as a one-table fix. A
separate builder confines the escalation to the single write that needs it,
and the tests below pin that boundary in both directions.

Offline: no HTTP, no provider, no database.
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
LEAD = {"name": "Ravi Kumar", "company": "Acme Traders",
        "service_needed": "Digital Ads", "budget": "50000",
        "city": "Bengaluru"}

# Distinctive so a leak is unmistakable in any blob.
SERVICE_ROLE = "svc-role-SENTINEL-8f3a2b1c"
ANON = "anon-key-SENTINEL-1a2b3c4d"


class FakeResponse:
    def __init__(self, status_code, text="[]"):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return self.status_code < 400


def run(status=201, service_role=SERVICE_ROLE, anon=ANON, data=None,
        exc=None):
    """Drive the REAL upsert_lead. Returns (stdout, posts, audits)."""
    posts, audits = [], []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "headers": headers, "json": json,
                      "timeout": timeout})
        if exc is not None:
            raise exc
        return FakeResponse(status)

    buf = io.StringIO()
    with mock.patch.object(w.requests, "post", fake_post), \
         mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", service_role), \
         mock.patch.object(w, "SUPABASE_KEY", anon), \
         mock.patch.object(w, "invoke_tool", lambda *a, **k: (True, "ok")), \
         mock.patch.object(w, "BIC_AVAILABLE", True), \
         mock.patch.object(w.bic_config, "is_configured", lambda: True), \
         mock.patch.object(w.bic_db, "insert",
                           lambda t, r, timeout=None: audits.append(r)), \
         redirect_stdout(buf):
        w.upsert_lead(PHONE, LEAD if data is None else data)
    return buf.getvalue(), posts, audits


# ══════════════════════════════════════════════════════════════════════════
# 1 · the credential actually used
# ══════════════════════════════════════════════════════════════════════════

class ServiceRoleIsUsed(unittest.TestCase):

    def test_the_write_sends_the_service_role_key(self):
        _, posts, _ = run()
        h = posts[0]["headers"]
        self.assertEqual(h["apikey"], SERVICE_ROLE)
        self.assertEqual(h["Authorization"], f"Bearer {SERVICE_ROLE}")

    def test_the_write_never_sends_the_anon_key(self):
        """THE REGRESSION. The anon key is what produced the 401."""
        _, posts, _ = run()
        blob = str(posts[0]["headers"])
        self.assertNotIn(ANON, blob)

    def test_both_credential_headers_are_present(self):
        h = run()[1][0]["headers"]
        self.assertIn("apikey", h)
        self.assertIn("Authorization", h)
        self.assertTrue(h["Authorization"].startswith("Bearer "))

    def test_the_builder_returns_service_role_headers(self):
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_ROLE):
            h = w._leads_write_headers("resolution=merge-duplicates")
        self.assertEqual(h["apikey"], SERVICE_ROLE)
        self.assertEqual(h["Authorization"], f"Bearer {SERVICE_ROLE}")
        self.assertEqual(h["Prefer"], "resolution=merge-duplicates")
        self.assertEqual(h["Content-Type"], "application/json")

    def test_the_credential_is_stripped(self):
        """A trailing newline in an env var silently corrupts a Bearer
        header — the same normalisation bic/config.py applies."""
        import inspect
        src = inspect.getsource(w)
        self.assertIn(
            'SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()',
            src)


# ══════════════════════════════════════════════════════════════════════════
# 2 · no silent fallback
# ══════════════════════════════════════════════════════════════════════════

class NoSilentFallbackToAnon(unittest.TestCase):

    def test_missing_credential_makes_no_request_at_all(self):
        """Retrying with anon would reproduce the exact 401 being removed,
        and would do it silently."""
        _, posts, _ = run(service_role="")
        self.assertEqual(posts, [])

    def test_missing_credential_never_falls_back_to_anon(self):
        out, posts, audits = run(service_role="")
        self.assertNotIn(ANON, str(posts))
        self.assertNotIn(ANON, str(audits))
        self.assertNotIn(ANON, out)

    def test_missing_credential_is_reported_not_swallowed(self):
        out, _, audits = run(service_role="")
        self.assertIn("LEAD_UPSERT_FAILED", out)
        self.assertIn("no_service_role_credential", out)
        self.assertEqual(audits[0]["error"], "missing_service_role_credential")
        self.assertFalse(audits[0]["ok"])

    def test_missing_credential_never_claims_success(self):
        out, _, audits = run(service_role="")
        self.assertNotIn("LEAD_UPSERT_OK", out)
        self.assertFalse(audits[0]["args_redacted"]["stored"])

    def test_the_builder_returns_none_rather_than_anon_headers(self):
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", ""), \
             mock.patch.object(w, "SUPABASE_KEY", ANON):
            self.assertIsNone(w._leads_write_headers())

    def test_whitespace_only_credential_is_treated_as_missing(self):
        _, posts, _ = run(service_role="   ")
        self.assertEqual(posts, [], "a blank credential must not be used")

    def test_the_crm_step_still_runs_when_the_credential_is_missing(self):
        """The CRM mirror uses a DIFFERENT credential and must not be lost."""
        calls = []
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", ""), \
             mock.patch.object(w, "invoke_tool",
                               lambda p, c, **k: (calls.append(c), (True, "ok"))[1]), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             redirect_stdout(io.StringIO()):
            w.upsert_lead(PHONE, LEAD)
        self.assertEqual(calls, ["crm_capture_self"])


# ══════════════════════════════════════════════════════════════════════════
# 3 · the secret never escapes
# ══════════════════════════════════════════════════════════════════════════

class TheSecretIsNeverExposed(unittest.TestCase):

    def test_the_service_role_key_never_appears_in_stdout(self):
        for status in (201, 401, 409, 500):
            with self.subTest(status=status):
                out, _, _ = run(status=status)
                self.assertNotIn(SERVICE_ROLE, out)

    def test_the_service_role_key_is_not_persisted(self):
        for status in (201, 401):
            _, _, audits = run(status=status)
            self.assertNotIn(SERVICE_ROLE, str(audits[0]), status)

    def test_a_transport_exception_does_not_leak_the_key(self):
        """The exception message is printed; a requests error can carry the
        request headers, so this pins that the sentinel never reaches it."""
        out, _, audits = run(exc=RuntimeError("connection reset"))
        self.assertNotIn(SERVICE_ROLE, out)
        self.assertNotIn(SERVICE_ROLE, str(audits))

    def test_no_lead_pii_is_logged_or_stored(self):
        out, _, audits = run(status=401)
        for secret in ("Ravi Kumar", "Acme Traders", "50000", "Bengaluru",
                       PHONE):
            self.assertNotIn(secret, out, secret)
            self.assertNotIn(secret, str(audits[0]), secret)
        self.assertIn(f"phone=...{LAST4}", out)

    def test_the_key_is_not_hardcoded_anywhere_in_source(self):
        import inspect
        src = inspect.getsource(w)
        self.assertNotIn(SERVICE_ROLE, src)
        self.assertIn('os.environ.get("SUPABASE_SERVICE_ROLE_KEY"', src)


# ══════════════════════════════════════════════════════════════════════════
# 4 · the shared helper and every other caller are untouched
# ══════════════════════════════════════════════════════════════════════════

class SharedHelperUnchanged(unittest.TestCase):

    def test_supa_headers_still_returns_the_anon_key(self):
        with mock.patch.object(w, "SUPABASE_KEY", ANON), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_ROLE):
            h = w._supa_headers()
        self.assertEqual(h["apikey"], ANON)
        self.assertEqual(h["Authorization"], f"Bearer {ANON}")
        self.assertNotIn(SERVICE_ROLE, str(h))

    def test_supa_headers_default_prefer_is_unchanged(self):
        with mock.patch.object(w, "SUPABASE_KEY", ANON):
            self.assertEqual(w._supa_headers()["Prefer"], "return=minimal")
            self.assertNotIn("Prefer", w._supa_headers(""))
            self.assertEqual(w._supa_headers("count=exact")["Prefer"],
                             "count=exact")

    def test_the_shared_helper_source_never_mentions_service_role(self):
        """STRUCTURAL: proves the 19 shared call sites were not escalated."""
        import inspect
        src = inspect.getsource(w._supa_headers)
        self.assertNotIn("SERVICE_ROLE", src)

    def test_other_callers_still_send_the_anon_key(self):
        """save_messages writes whatsapp_messages with anon and SUCCEEDS in
        production — it must keep that credential."""
        posts = []
        with mock.patch.object(w.requests, "post",
                               lambda url, headers=None, json=None, timeout=None:
                                   posts.append({"url": url, "headers": headers})), \
             mock.patch.object(w, "SUPABASE_KEY", ANON), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_ROLE), \
             redirect_stdout(io.StringIO()):
            w.save_messages([(PHONE, "user", "hi")])
        self.assertIn("whatsapp_messages", posts[0]["url"])
        self.assertEqual(posts[0]["headers"]["apikey"], ANON)
        self.assertNotIn(SERVICE_ROLE, str(posts[0]["headers"]))

    def test_only_the_leads_write_uses_the_new_builder(self):
        """One call site, and it is the write. A second would mean the
        escalation spread."""
        import inspect
        src = inspect.getsource(w)
        calls = src.count("_leads_write_headers(")
        # 1 definition + 1 call site
        self.assertEqual(calls, 2, "the service-role builder gained a caller")


# ══════════════════════════════════════════════════════════════════════════
# 5 · everything else about the write is byte-identical
# ══════════════════════════════════════════════════════════════════════════

class RequestShapeUnchanged(unittest.TestCase):

    def test_url_payload_prefer_and_timeout_are_unchanged(self):
        _, posts, _ = run()
        p = posts[0]
        self.assertTrue(p["url"].endswith("/rest/v1/leads"))
        self.assertEqual(p["json"], {"phone": PHONE, **LEAD})
        self.assertEqual(p["headers"]["Prefer"], "resolution=merge-duplicates")
        self.assertEqual(p["timeout"], 5)

    def test_response_status_handling_is_intact(self):
        self.assertIn("LEAD_UPSERT_OK", run(status=201)[0])
        for bad in (400, 401, 403, 409, 500):
            out, _, _ = run(status=bad)
            self.assertIn("LEAD_UPSERT_FAILED", out, bad)
            self.assertIn(f"status={bad}", out, bad)
            self.assertNotIn("LEAD_UPSERT_OK", out, bad)

    def test_durable_telemetry_is_intact(self):
        _, _, audits = run(status=401)
        row = audits[0]
        self.assertEqual(row["tool"], "lead_upsert")
        self.assertEqual(row["args_redacted"]["http_status"], 401)
        self.assertFalse(row["args_redacted"]["stored"])
        self.assertEqual(row["error"], "http_401")
        _, _, ok_audits = run(status=201)
        self.assertTrue(ok_audits[0]["ok"])
        self.assertEqual(ok_audits[0]["args_redacted"]["http_status"], 201)

    def test_an_empty_payload_still_short_circuits(self):
        _, posts, audits = run(data={})
        self.assertEqual(posts, [])
        self.assertEqual(audits, [])

    def test_the_crm_step_still_runs_after_a_successful_write(self):
        calls = []
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: FakeResponse(201)), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_ROLE), \
             mock.patch.object(w, "invoke_tool",
                               lambda p, c, **k: (calls.append(c), (True, "ok"))[1]), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             redirect_stdout(io.StringIO()):
            w.upsert_lead(PHONE, LEAD)
        self.assertEqual(calls, ["crm_capture_self"])


class UnrelatedPathsUntouched(unittest.TestCase):

    def test_the_extraction_guard_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn(
            "if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):", src)

    def test_extract_lead_info_provider_config_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.extract_lead_info)
        self.assertIn('model="gpt-4o-mini"', src)
        self.assertIn("max_tokens=380", src)
        self.assertIn("temperature=0", src)
        self.assertIn("generate_reply_gemini", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
