"""GET /api/status — two facts for the Uptime Kuma monitor on the owner's Mac (owner 2026-11-05,
"1,2 maadu"): is the WhatsApp token alive and how long until it expires, and how long ago the
recovery sweep last finished.

    GET /api/status                 both facts
    GET /api/status?only=recovery   the sweep only — no call to Meta, safe every few minutes

WHY A PUBLIC GET. Kuma runs on the Mac and cannot hold the Brain's secrets; this endpoint checks
them here and answers with booleans and whole numbers only: no token, phone, WAMID or message
text. It changes nothing and sends nothing to anyone.

    {"whatsapp": {"ok": true, "state": "OK", "days_left": 9},
     "recovery": {"minutes_ago": 3}}

days_left is null for a permanent token (debug_token expires_at = 0) or when Meta did not say;
minutes_ago is null when no sweep has been recorded yet.
"""
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

_API = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_API), _API):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://kpzprllzgqlqkqgcgrbp.supabase.co")
RECOVERY_KEY = "recovery_last_ok"     # written by api/recovery.py after each sweep


def days_left(expires_at, now=None):
    """Whole days until a debug_token expires_at (epoch seconds); None if permanent or unknown."""
    if not isinstance(expires_at, (int, float)) or expires_at <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    return int((expires_at - now.timestamp()) // 86400)


def minutes_since(iso, now=None):
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - then).total_seconds() // 60))


def whatsapp_status() -> dict:
    import digest                      # its probe is read-only: a GET and a debug_token
    import health
    state, expires_at = digest.probe_whatsapp()
    return {"ok": state == health.OK, "state": state, "days_left": days_left(expires_at)}


def recovery_status() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        return {"minutes_ago": None}
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/app_settings",
                         headers={"apikey": key, "Authorization": f"Bearer {key}"},
                         params={"key": f"eq.{RECOVERY_KEY}", "select": "updated_at"}, timeout=5)
        rows = r.json() if r.ok else []
    except Exception as e:
        print(f"STATUS recovery read failed type={type(e).__name__}")
        rows = []
    return {"minutes_ago": minutes_since(rows[0].get("updated_at")) if rows else None}


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        only = (parse_qs(urlparse(self.path).query).get("only") or [""])[0]
        out = {"recovery": recovery_status()}
        if only != "recovery":
            try:
                out["whatsapp"] = whatsapp_status()
            except Exception as e:
                print(f"STATUS whatsapp failed type={type(e).__name__}")
                out["whatsapp"] = {"ok": False, "state": "UNKNOWN", "days_left": None}
        body = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
