"""POST /api/recovery — run ONE Phase 2B recovery sweep (Phase 2C).

    POST /api/recovery
    Authorization: Bearer <CRON_SECRET>

Called every ~5 minutes by .github/workflows/recovery.yml, because Vercel
Hobby cron runs at most daily.

AUTHENTICATION IS THE BEARER TOKEN AND NOTHING ELSE
---------------------------------------------------
digest / nudge / evaluate accept `User-Agent: vercel-cron` or
`?key=VERIFY_TOKEN`. A User-Agent is whatever the caller types, and a query
string lands in access logs. This endpoint can make the bot message customers,
so it accepts neither: only `Authorization: Bearer <CRON_SECRET>`, compared in
constant time. An unset or short CRON_SECRET rejects every request — the
endpoint fails closed until the secret is configured.

THE CALLER CHOOSES NOTHING
--------------------------
No body, query or header is read beyond Authorization. WAMID, phone, batch,
attempt limit and thresholds all come from api/redrive.py and the server's own
environment. The request means only: "run one sweep under the server's policy".

WHAT GOES BACK
--------------
401 / 405 / 500 carry a fixed one-word error. 200 carries the sweep's counts
by result name (REDRIVEN, RECONCILED, …) — no WAMID, phone or message text.
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# api/ for `redrive` / `webhook`, the repo root for `bic` and `bairavi`.
_API = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_API), _API):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# A shorter value is treated as unset: a guessable secret is no secret.
MIN_SECRET_LENGTH = 32


def authorized(header) -> bool:
    """True only for exactly `Bearer <CRON_SECRET>`. Read per request, so the
    secret is never cached in a module global that a log could reach."""
    secret = os.environ.get("CRON_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH or not isinstance(header, str):
        return False
    scheme, _, token = header.partition(" ")
    if scheme != "Bearer" or not token or token != token.strip():
        return False
    return hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8"))


def run_sweep() -> dict:
    """The existing Phase 2B worker, imported only after authentication so an
    unauthenticated request never loads the bot."""
    import redrive
    return redrive.run()


def meta_leads(now=None) -> dict:
    """Reach Meta form leads who never messaged (api/meta_leads_sync.py).
    Off unless META_LEADS_MODE says otherwise. Counts only; never raises."""
    try:
        import meta_leads_sync
        return meta_leads_sync.run(now)
    except Exception as e:
        print(f"RECOVERY_ENDPOINT meta_leads=failed type={type(e).__name__}")
        return {"error": "meta_leads_failed"}


def call_reminders(now=None) -> dict:
    """Remind the owner about promised calls that are overdue
    (api/call_reminders_sync.py). Owner-facing only; never raises."""
    try:
        import call_reminders_sync
        return call_reminders_sync.run(now)
    except Exception as e:
        print(f"RECOVERY_ENDPOINT call_reminders=failed type={type(e).__name__}")
        return {"error": "call_reminders_failed"}


def publish_health(counts) -> str:
    """After the sweep, push the Brain's aggregate health to the CRM's Brain
    Health page (brain_health.py). Best-effort: 'ok' / 'failed', never raises,
    and never changes the sweep's own status code."""
    try:
        import health_snapshot
        return health_snapshot.run(counts)
    except Exception as e:
        print(f"RECOVERY_ENDPOINT health=failed type={type(e).__name__}")
        return "failed"


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        if not authorized(self.headers.get("Authorization")):
            print("RECOVERY_ENDPOINT auth=rejected")
            return self._json(401, {"ok": False, "error": "unauthorized"})
        try:
            counts = run_sweep()
        except Exception as e:
            # TYPE ONLY: an exception message can carry a URL, a phone or a
            # database error body.
            print(f"RECOVERY_ENDPOINT result=error type={type(e).__name__}")
            return self._json(500, {"ok": False, "error": "recovery_failed"})
        results = {str(k): int(v) for k, v in (counts or {}).items()}
        leads = meta_leads()
        reminders = call_reminders()
        health = publish_health(results)
        print("RECOVERY_ENDPOINT result=ok health=" + health + " " + json.dumps(results, sort_keys=True))
        return self._json(200, {"ok": True, "results": results, "health_snapshot": health,
                                "meta_leads": leads, "call_reminders": reminders})

    def _method_not_allowed(self):
        self._json(405, {"ok": False, "error": "method_not_allowed"}, allow="POST")

    do_GET = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _method_not_allowed

    def do_HEAD(self):
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def _json(self, code: int, payload: dict, allow: str = None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if allow:
            self.send_header("Allow", allow)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # The default access log is not printed; it adds nothing here.
        pass
