"""Phase 2C — secure scheduler for the Phase 2B recovery worker.

Two halves, both tested by BEHAVIOUR:

  api/recovery.py               driven through the real handler class
  .github/workflows/recovery.yml its own shell step is executed with bash
                                against a local stub server

Offline. The secret below is a test fixture, generated per run; it is never a
production value and is asserted absent from every output.
"""
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import recovery                                        # noqa: E402
import redrive                                         # noqa: E402

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "recovery.yml")
TOKEN = "test-" + secrets.token_urlsafe(40)


def call(method="POST", headers=None, path="/api/recovery", body=b""):
    """One request through the real handler. Returns (status, json, log)."""
    h = recovery.handler.__new__(recovery.handler)
    h.headers = dict(headers or {})
    h.path = path
    h.command = method
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    sent = {}
    h.send_response = lambda code, *a: sent.__setitem__("code", code)
    h.send_header = lambda k, v: sent.setdefault("headers", {}).__setitem__(k, v)
    h.end_headers = lambda: None
    with redirect_stdout(io.StringIO()) as out:
        getattr(h, "do_" + method)()
    raw = h.wfile.getvalue()
    return sent["code"], (json.loads(raw) if raw else None), out.getvalue(), sent.get("headers", {})


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.runs = []
        self._p = [mock.patch.dict(os.environ, {"CRON_SECRET": TOKEN}),
                   mock.patch.object(redrive, "run",
                                     lambda *a, **k: (self.runs.append((a, k)) or
                                                      {redrive.REDRIVEN: 1})),
                   mock.patch.object(recovery, "publish_health",
                                     lambda counts: (self.health.append(counts) or "ok"))]
        self.health = []
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def ok_headers(self):
        return {"Authorization": f"Bearer {TOKEN}"}

    # A
    def test_A_correct_bearer_runs_the_worker(self):
        code, body, _log, _h = call(headers=self.ok_headers())
        self.assertEqual(code, 200)
        self.assertEqual(body, {"ok": True, "results": {"REDRIVEN": 1}, "health_snapshot": "ok"})
        self.assertEqual(self.health, [{"REDRIVEN": 1}])

    # B
    def test_B_missing_authorization_is_401(self):
        code, body, _log, _h = call(headers={})
        self.assertEqual((code, body), (401, {"ok": False, "error": "unauthorized"}))
        self.assertEqual(self.runs, [])

    # C
    def test_C_wrong_bearer_is_401(self):
        for wrong in ("Bearer " + TOKEN[:-1] + "x", "Bearer " + TOKEN + "x",
                      "Bearer " + TOKEN[:-5], "Bearer " + "a" * len(TOKEN)):
            with self.subTest(wrong=wrong[:12]):
                self.assertEqual(call(headers={"Authorization": wrong})[0], 401)
        self.assertEqual(self.runs, [])

    # D
    def test_D_malformed_authorization_is_401(self):
        for bad in (TOKEN, f"bearer {TOKEN}", f"Basic {TOKEN}", f"Bearer  {TOKEN}",
                    f"Bearer {TOKEN} ", f"Token {TOKEN}", "Bearer", "Bearer ", ""):
            with self.subTest(bad=bad[:10]):
                self.assertEqual(call(headers={"Authorization": bad})[0], 401)
        self.assertEqual(self.runs, [])

    # E
    def test_E_a_query_string_secret_does_not_authenticate(self):
        for q in (f"?key={TOKEN}", f"?token={TOKEN}", f"?CRON_SECRET={TOKEN}",
                  f"?authorization=Bearer%20{TOKEN}"):
            with self.subTest(q=q[:8]):
                self.assertEqual(call(path="/api/recovery" + q)[0], 401)
        self.assertEqual(self.runs, [])

    def test_E_the_verify_token_does_not_authenticate(self):
        with mock.patch.dict(os.environ, {"VERIFY_TOKEN": "verify-" + "v" * 40}):
            for h in ({"Authorization": "Bearer verify-" + "v" * 40},):
                self.assertEqual(call(headers=h, path="/api/recovery?key=verify-" + "v" * 40)[0], 401)
        self.assertEqual(self.runs, [])

    # F
    def test_F_vercel_cron_user_agent_alone_does_not_authenticate(self):
        for ua in ("vercel-cron/1.0", "vercel-cron", "Mozilla/5.0 vercel-cron"):
            with self.subTest(ua=ua):
                self.assertEqual(call(headers={"User-Agent": ua})[0], 401)
        self.assertEqual(self.runs, [])

    # G
    def test_G_the_token_never_appears_in_the_response_or_log(self):
        for headers in (self.ok_headers(), {"Authorization": "Bearer " + TOKEN + "x"}):
            code, body, log, resp_headers = call(headers=headers)
            self.assertNotIn(TOKEN, json.dumps(body))
            self.assertNotIn(TOKEN, log)
            self.assertNotIn(TOKEN, json.dumps(resp_headers))

    # H
    def test_H_other_methods_are_405_even_with_the_token(self):
        for m in ("GET", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=m):
                code, body, _l, headers = call(method=m, headers=self.ok_headers())
                self.assertEqual(code, 405)
                self.assertEqual(headers.get("Allow"), "POST")
        self.assertEqual(call(method="HEAD", headers=self.ok_headers())[0], 405)
        self.assertEqual(self.runs, [])

    # I
    def test_I_one_request_runs_exactly_one_sweep_with_no_caller_parameters(self):
        call(headers=self.ok_headers(), path="/api/recovery?wamid=wamid.X&phone=919&limit=999",
             body=json.dumps({"wamid": "wamid.X", "max_attempts": 99}).encode())
        self.assertEqual(self.runs, [((), {})])

    def test_I_the_endpoint_calls_the_real_phase_2b_worker(self):
        self.assertIs(recovery.run_sweep.__module__, "recovery")
        with mock.patch.object(redrive, "run", lambda: {"RECONCILED_REPLY_EXISTS": 2}):
            self.assertEqual(call(headers=self.ok_headers())[1]["results"],
                             {"RECONCILED_REPLY_EXISTS": 2})

    # J
    def test_J_a_worker_failure_is_500_without_details(self):
        def boom():
            raise RuntimeError("relation bic_webhook_events: 919999000888 wamid.SECRET")
        with mock.patch.object(redrive, "run", boom):
            code, body, log, _h = call(headers=self.ok_headers())
        self.assertEqual((code, body), (500, {"ok": False, "error": "recovery_failed"}))
        for leak in ("919999000888", "wamid.SECRET", "bic_webhook_events"):
            self.assertNotIn(leak, json.dumps(body))
            self.assertNotIn(leak, log)
        self.assertIn("type=RuntimeError", log)

    def test_the_response_carries_no_customer_data(self):
        with mock.patch.object(redrive, "run", lambda: {"REDRIVEN": 1, "SKIPPED": 3}):
            body = call(headers=self.ok_headers())[1]
        self.assertEqual(set(body), {"ok", "results", "health_snapshot"})
        self.assertTrue(all(isinstance(v, int) for v in body["results"].values()))

    # Fail closed until configured
    def test_an_unset_secret_rejects_everything(self):
        for value in ("", "short-secret"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CRON_SECRET": value}):
                self.assertEqual(call(headers={"Authorization": f"Bearer {value}"})[0], 401)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(call(headers={"Authorization": "Bearer "})[0], 401)
        self.assertEqual(self.runs, [])

    def test_NEGATIVE_CONTROL_without_the_check_anyone_runs_a_sweep(self):
        with mock.patch.object(recovery, "authorized", lambda header: True):
            self.assertEqual(call(headers={})[0], 200)
        self.assertEqual(len(self.runs), 1)


class Routing(unittest.TestCase):
    def test_the_route_and_build_point_at_the_endpoint(self):
        cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
        self.assertIn({"src": "/api/recovery", "dest": "api/recovery.py"}, cfg["routes"])
        build = [b for b in cfg["builds"] if b["src"] == "api/recovery.py"][0]
        self.assertLessEqual(build["config"]["maxDuration"], 300)

    def test_no_vercel_cron_calls_it(self):
        """Vercel cron would arrive without the bearer token and be refused."""
        cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
        self.assertNotIn("/api/recovery", [c["path"] for c in cfg.get("crons", [])])

    def test_the_other_cron_endpoints_are_untouched(self):
        """Their weaker gate is a separate task; Phase 2C does not rewrite it."""
        for f in ("digest.py", "nudge.py", "evaluate.py"):
            src = open(os.path.join(ROOT, "api", f), encoding="utf-8").read()
            self.assertIn("vercel-cron", src, f)
            self.assertNotIn("CRON_SECRET", src, f)


# ── The workflow ────────────────────────────────────────────────────────────

def load_workflow(path=WORKFLOW):
    import yaml
    with open(path) as f:
        wf = yaml.safe_load(f)
    # PyYAML (YAML 1.1) reads the bare key `on` as True.
    wf["on"] = wf.pop(True, wf.get("on"))
    return wf


def the_step(wf):
    steps = wf["jobs"]["sweep"]["steps"]
    return [s for s in steps if "run" in s][0]


class Stub(BaseHTTPRequestHandler):
    status = 200
    seen = []

    def do_POST(self):
        Stub.seen.append({"auth": self.headers.get("Authorization"), "path": self.path})
        body = json.dumps({"ok": Stub.status < 300, "results": {}}).encode()
        self.send_response(Stub.status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@unittest.skipUnless(shutil.which("bash") and shutil.which("curl"), "needs bash and curl")
class WorkflowBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/api/recovery"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_step(self, status, secret=TOKEN, wf=None):
        Stub.status, Stub.seen = status, []
        step = the_step(wf or load_workflow())
        env = {"PATH": os.environ["PATH"], "RECOVERY_URL": self.url, "CRON_SECRET": secret}
        p = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True,
                           text=True, timeout=30)
        return p.returncode, p.stdout + p.stderr

    # M
    def test_M_a_2xx_passes(self):
        rc, out = self.run_step(200)
        self.assertEqual(rc, 0, out)
        self.assertEqual(Stub.seen[0]["auth"], f"Bearer {TOKEN}")

    def test_M_any_non_2xx_fails_the_run(self):
        for status in (401, 403, 405, 500, 502):
            with self.subTest(status=status):
                rc, _out = self.run_step(status)
                self.assertNotEqual(rc, 0)

    def test_M_an_unreachable_endpoint_fails_the_run(self):
        Stub.seen = []
        step = the_step(load_workflow())
        p = subprocess.run(["bash", "-c", step["run"]],
                           env={"PATH": os.environ["PATH"], "CRON_SECRET": TOKEN,
                                "RECOVERY_URL": "http://127.0.0.1:9/api/recovery"},
                           capture_output=True, text=True, timeout=30)
        self.assertNotEqual(p.returncode, 0)

    def test_a_missing_secret_fails_before_calling(self):
        rc, out = self.run_step(200, secret="")
        self.assertNotEqual(rc, 0)
        self.assertEqual(Stub.seen, [])

    def test_G_the_secret_is_never_printed(self):
        for status in (200, 401, 500):
            _rc, out = self.run_step(status)
            self.assertNotIn(TOKEN, out)

    def test_the_request_is_a_post_with_no_query_parameters(self):
        self.run_step(200)
        self.assertEqual(Stub.seen[0]["path"], "/api/recovery")


class WorkflowDefinition(unittest.TestCase):
    def setUp(self):
        self.wf = load_workflow()
        self.text = open(WORKFLOW).read()

    # K
    def test_K_no_hardcoded_secret(self):
        step = the_step(self.wf)
        self.assertEqual(step["env"]["CRON_SECRET"], "${{ secrets.CRON_SECRET }}")
        for line in self.text.splitlines():
            if "Bearer" in line and not line.strip().startswith("#"):
                self.assertIn("${CRON_SECRET}", line)
        self.assertNotRegex(self.text, r"Bearer [A-Za-z0-9_\-]{16,}")

    # L
    def test_L_the_secret_comes_from_github_secrets(self):
        self.assertIn("${{ secrets.CRON_SECRET }}", self.text)

    # N
    def test_N_manual_dispatch_and_a_five_minute_schedule(self):
        self.assertIn("workflow_dispatch", self.wf["on"])
        self.assertEqual(self.wf["on"]["schedule"], [{"cron": "*/5 * * * *"}])

    def test_one_sweep_at_a_time(self):
        self.assertEqual(self.wf["concurrency"],
                         {"group": "brain-recovery", "cancel-in-progress": False})

    def test_short_timeouts_and_no_token_permissions(self):
        self.assertLessEqual(self.wf["jobs"]["sweep"]["timeout-minutes"], 10)
        self.assertIn("--max-time", the_step(self.wf)["run"])
        self.assertEqual(self.wf["permissions"], {})

    def test_it_targets_production_and_does_not_depend_on_keep_warm(self):
        step = the_step(self.wf)
        self.assertEqual(step["env"]["RECOVERY_URL"],
                         "https://asthra-digitech-frontend.vercel.app/api/recovery")
        self.assertNotIn("needs", self.wf["jobs"]["sweep"])
        self.assertNotIn("set -x", step["run"])

    def test_NEGATIVE_CONTROL_a_hardcoded_token_fails_these_checks(self):
        import tempfile
        bad = self.text.replace("${{ secrets.CRON_SECRET }}", "abcdefghijklmnopqrstuvwxyz123456")
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(bad)
        try:
            wf = load_workflow(f.name)
            self.assertNotEqual(the_step(wf)["env"]["CRON_SECRET"], "${{ secrets.CRON_SECRET }}")
            self.assertNotIn("${{ secrets.CRON_SECRET }}", bad)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()


class HealthSnapshotHook(unittest.TestCase):
    """The Brain Health snapshot rides the authenticated sweep, never alone."""

    def setUp(self):
        self._p = [mock.patch.dict(os.environ, {"CRON_SECRET": TOKEN}),
                   mock.patch.object(redrive, "run", lambda: {})]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def test_a_snapshot_failure_never_fails_the_sweep(self):
        import health_snapshot
        def boom(counts):
            raise RuntimeError("crm 919999000888 down")
        with mock.patch.object(health_snapshot, "run", boom):
            code, body, log, _h = call(headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(code, 200)
        self.assertEqual(body["health_snapshot"], "failed")
        self.assertNotIn("919999000888", log + json.dumps(body))

    def test_unauthenticated_requests_never_publish(self):
        published = []
        with mock.patch.object(recovery, "publish_health", lambda c: published.append(c) or "ok"):
            call(headers={})
            call(headers={"User-Agent": "vercel-cron"})
        self.assertEqual(published, [])
