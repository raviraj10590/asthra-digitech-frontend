"""Phase 1A — Supabase credential separation (2026-10-01).

PUBLIC / BROWSER (AI Kannada web + mobile, Realty Launch-Kit form)
    -> the project's anon / publishable key
BRAIN SERVER (this repository)
    -> SUPABASE_SERVICE_ROLE_KEY, for every table

The Brain read and wrote its private tables (whatsapp_messages, bot_roles)
with the public key through `true` RLS policies — and that key is shipped in
aikannada.shop's browser JavaScript. After this phase no Brain call depends on
any public policy, so Phase 1B can remove them without breaking a turn.

Offline: every network call is faked; the keys below are fixtures.
"""
import ast
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import webhook as w  # noqa: E402

ANON = "test-public-anon-key"
SERVICE = "test-server-service-role-key"
PHONE = "919000005711"


class _R:
    def __init__(self, data=None, status=200, headers=None):
        self._d, self.status_code, self.ok = data if data is not None else [], status, status < 400
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._d


def capture(fn, *args, **kwargs):
    """Run fn with requests faked; return every (method, url, headers)."""
    calls = []

    def rec(method):
        def f(url, headers=None, **k):
            calls.append((method, url, headers or {}))
            return _R()
        return f
    with mock.patch.object(w, "SUPABASE_KEY", ANON), \
         mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE), \
         mock.patch.object(w.requests, "get", rec("GET")), \
         mock.patch.object(w.requests, "post", rec("POST")), \
         mock.patch.object(w.requests, "patch", rec("PATCH")), \
         mock.patch.object(w.requests, "delete", rec("DELETE")), \
         redirect_stdout(io.StringIO()):
        try:
            fn(*args, **kwargs)
        except Exception:
            pass
    return calls


def brain_db_calls(calls, table):
    return [c for c in calls if f"/rest/v1/{table}" in c[1] and w.SUPABASE_URL in c[1]]


def assert_server_key(tc, calls, table):
    hits = brain_db_calls(calls, table)
    tc.assertTrue(hits, f"no call to {table}")
    for method, url, headers in hits:
        tc.assertEqual(headers.get("apikey"), SERVICE, f"{method} {table}")
        tc.assertEqual(headers.get("Authorization"), f"Bearer {SERVICE}", f"{method} {table}")
        tc.assertNotIn(ANON, str(headers), f"{method} {table} sent the public key")


class WhatsappMessages(unittest.TestCase):
    def test_context_read(self):
        assert_server_key(self, capture(w.fetch_context, PHONE), "whatsapp_messages")

    def test_message_and_flow_marker_save(self):
        import bairavi
        calls = capture(w.save_messages, [(PHONE, "user", "hi"),
                                          (PHONE, "assistant", bairavi.flow_marker(()))])
        assert_server_key(self, calls, "whatsapp_messages")


class BotRoles(unittest.TestCase):
    def test_role_read(self):
        w.bic_identity._cache.clear() if hasattr(w, "bic_identity") else None
        assert_server_key(self, capture(w._fetch_role_row, "919111111111"), "bot_roles")

    def test_staff_list_read(self):
        assert_server_key(self, capture(w.staff_and_owner_numbers), "bot_roles")

    def test_role_writes(self):
        assert_server_key(self, capture(w._tool_add_role, "918861369951", "919111111111",
                                        "STAFF", "x", "918861369951"), "bot_roles")
        assert_server_key(self, capture(w._tool_remove_role, "918861369951", "919111111111"),
                          "bot_roles")


class Leads(unittest.TestCase):
    def test_lead_write(self):
        assert_server_key(self, capture(w.upsert_lead, PHONE, {"name": "X", "source": "test"}),
                          "leads")

    def test_lead_read(self):
        assert_server_key(self, capture(w.tool_leads, "918861369951"), "leads")


class BicAndShadow(unittest.TestCase):
    def test_bic_db_uses_the_service_role(self):
        from bic import config, db
        with mock.patch.object(config, "SUPABASE_SERVICE_ROLE_KEY", SERVICE), \
             mock.patch.object(config, "SUPABASE_URL", "https://x.supabase.co"):
            h = db._headers() if hasattr(db, "_headers") else None
        src = open(os.path.join(ROOT, "bic", "db.py")).read()
        self.assertIn("config.SUPABASE_SERVICE_ROLE_KEY", src)
        self.assertNotIn("SUPABASE_KEY\"", src)
        if h is not None:
            self.assertEqual(h["apikey"], SERVICE)

    def test_shadow_write(self):
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", SERVICE):
            h = w._shadow_write_headers()
        self.assertEqual(h["apikey"], SERVICE)


class NoSilentDowngrade(unittest.TestCase):
    def test_missing_server_key_is_named_never_the_public_key(self):
        buf = io.StringIO()
        with mock.patch.object(w, "SUPABASE_KEY", ANON), \
             mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", ""), redirect_stdout(buf):
            h = w._supa_headers()
        self.assertNotIn(ANON, str(h))
        self.assertIn("BRAIN_DB_CREDENTIAL_MISSING", buf.getvalue())
        self.assertNotIn(SERVICE, buf.getvalue())


class CronModules(unittest.TestCase):
    """digest / nudge / evaluate read private tables server-side."""

    def test_they_read_the_service_role_variable(self):
        for f in ("api/digest.py", "api/nudge.py", "api/evaluate.py"):
            src = open(os.path.join(ROOT, f)).read()
            self.assertIn('SUPABASE_SERVER_KEY', src, f)
            self.assertIn('os.environ.get("SUPABASE_SERVICE_ROLE_KEY"', src, f)
            self.assertNotRegex(src, r'os\.environ\.get\(\s*"SUPABASE_KEY"', f)
            self.assertNotRegex(src, r"\bSUPABASE_KEY\b", f)


class NoPublicKeyForBrainTables(unittest.TestCase):
    """Structural: no Brain module sends the public key to the database."""

    def test_no_header_is_built_from_the_public_key(self):
        pat = re.compile(r'"apikey"\s*:\s*SUPABASE_KEY\b|Bearer \{SUPABASE_KEY\}')
        for path in ("api/webhook.py", "api/digest.py", "api/nudge.py", "api/evaluate.py",
                     "api/lead.py", "health.py", "bairavi.py", "interpretation.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            self.assertIsNone(pat.search(src), path)


class TheServiceRoleNeverReachesABrowser(unittest.TestCase):
    """This repository ships no browser code; the service-role variable is
    only read inside server functions, never under a public prefix."""

    def test_no_client_side_files(self):
        for dirpath, _, files in os.walk(ROOT):
            if any(p in dirpath for p in ("/.git", "/node_modules", "/tests", "/.learning")):
                continue
            for f in files:
                self.assertFalse(f.endswith((".html", ".tsx", ".jsx")), os.path.join(dirpath, f))

    def test_no_public_prefixed_secret(self):
        for dirpath, _, files in os.walk(ROOT):
            if any(p in dirpath for p in ("/.git", "/node_modules", "/tests")):
                continue
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json")):
                    src = open(os.path.join(dirpath, f), encoding="utf-8", errors="ignore").read()
                    self.assertNotRegex(src, r"(NEXT_PUBLIC|VITE|EXPO_PUBLIC)_[A-Z_]*SERVICE_ROLE", f)

    def test_the_service_role_is_never_logged(self):
        for path in ("api/webhook.py", "api/digest.py", "api/nudge.py", "api/evaluate.py"):
            tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                    for n in ast.walk(node):
                        if isinstance(n, ast.Name):
                            self.assertNotIn(n.id, ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVER_KEY"),
                                             f"{path}: print() references the server key")


if __name__ == "__main__":
    unittest.main()
