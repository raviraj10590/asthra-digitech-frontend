"""
Asthra DigiTech — Daily WhatsApp Bot Digest
Runs via Vercel Cron (9:00 AM IST daily) → sends yesterday's bot summary
to the owner's WhatsApp.
"""

import json, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

import sys

# Guarded exactly like webhook.py's BIC import: a bundling failure must degrade
# to a log line, never break the digest that already works.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from bic import commitment as bic_commitment, config as bic_config
    BIC_AVAILABLE = True
except Exception as _bic_err:  # pragma: no cover - environment dependent
    BIC_AVAILABLE = False
    print(f"BIC: package import FAILED ({_bic_err}) — commitment report skipped")

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN",    "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",    "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY",    "")  # anon key — set in Vercel env vars
# OWNER_PHONE may be a comma-separated list (same env var the webhook uses).
OWNER_PHONES    = [p.strip() for p in
    os.environ.get("OWNER_PHONE", "918884448141").split(",") if p.strip()]


def _supa_get(table: str, params: dict) -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        params=params,
        timeout=10,
    )
    return r.json() if r.ok else []


def build_digest() -> str:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    msgs = _supa_get("whatsapp_messages", {
        "created_at": f"gte.{since}",
        "select": "phone,role,content",
    })
    leads = _supa_get("leads", {
        "select": "phone,name,company,service_needed,budget,city",
    })

    user_msgs  = [m for m in msgs if m.get("role") == "user"]
    phones     = sorted({m["phone"] for m in user_msgs})
    brochures  = sum(1 for m in msgs if m.get("role") == "assistant" and "ಬ್ರೋಚರ್ PDF" in m.get("content", ""))
    meetings   = sum(1 for m in msgs if m.get("role") == "system" and m.get("content") == "MEETING_REQUESTED")
    vip_alerts = sum(1 for m in msgs if m.get("role") == "system" and m.get("content") == "VIP_ALERTED")

    lines = [
        "☀️ ಆಸ್ತ್ರ AI — Daily Bot Report",
        "",
        f"💬 Conversations: {len(phones)}",
        f"📨 Messages received: {len(user_msgs)}",
        f"📄 Brochures sent: {brochures}",
        f"🤝 Meeting requests: {meetings}",
        f"👑 VIP/Election alerts: {vip_alerts}",
        f"📋 Total leads in DB: {len(leads)}",
    ]
    if phones:
        lines += ["", "Active chats:"]
        lines += [f"• wa.me/{p}" for p in phones[:10]]
    return "\n".join(lines)


def send_to_owner(text: str):
    ok_any = False
    for phone in OWNER_PHONES:
        # One phone failing (network error, bad number) must not block the rest.
        try:
            r = requests.post(
                f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"body": text, "preview_url": False},
                },
                timeout=10,
            )
            print(f"digest WA send to {phone} {r.status_code}: {r.text[:120]}")
            ok_any = ok_any or r.ok
        except Exception as e:
            print(f"digest WA send to {phone} FAILED: {e}")
    return ok_any


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Allow only Vercel Cron or a manual call with ?key=<VERIFY_TOKEN>
        ua  = self.headers.get("User-Agent", "")
        key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
        if "vercel-cron" not in ua and key != VERIFY_TOKEN:
            self.send_response(403)
            self.end_headers()
            return

        try:
            digest = build_digest()
            ok = send_to_owner(digest)
            body = {"ok": ok, "digest": digest}
        except Exception as e:
            print(f"digest error: {e}")
            body = {"ok": False, "error": str(e)}

        # BIC Slice 1C: 30-day retention for the replay diagnostic table.
        # Rides the existing daily cron rather than adding a fourth scheduler,
        # and does not depend on pg_cron (not guaranteed on the free tier).
        # Strictly best-effort — retention must never affect the digest, and a
        # failure here is a housekeeping miss, not an incident.
        # Audit finding M-3: bic_rollup_tool_invocations has existed since
        # Slice 1A and was NEVER CALLED, so the audit table grew without
        # bound. Wired onto the existing daily cron rather than adding a
        # scheduler — Vercel Hobby caps at 2 crons and both are in use.
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/rpc/bic_rollup_tool_invocations",
                headers={
                    "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                    "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json={"retain_days": 90},
                timeout=20,
            )
            print(f"bic tool-invocation rollup: {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"bic tool-invocation rollup failed (ignored): {e}")

        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/rpc/bic_prune_replay_records",
                headers={
                    "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                    "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json={"retain_days": 30},
                timeout=10,
            )
            print(f"bic replay retention: {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"bic replay retention failed (ignored): {e}")

        # IDD-2B: "what have we promised and are we about to miss it?" — the
        # question Commitment exists to answer. READ-ONLY, deliberately.
        #
        # NOTHING IS MARKED MISSED HERE. "`missed` is recorded, never
        # deleted... missed commitments are the reliability signal", and a
        # cron that transitioned rows would manufacture that judgement from a
        # clock tick, with no reason and no actor. A real miss goes through
        # the transition RPC with both. This only reports.
        #
        # Rides the existing daily cron — no third scheduler, per the note at
        # the top of this file.
        if BIC_AVAILABLE:
            try:
                due = bic_commitment.overdue(bic_config.DEFAULT_TENANT_ID)
                if due:
                    # Short references, not raw UUIDs — the SAME handles
                    # `#commitment <ref> ...` accepts, so the digest names
                    # exactly what the owner can act on. Never a phone, never
                    # a party id.
                    refs = ", ".join(bic_commitment.reference(c)
                                     for c in due[:10])
                    kinds = sorted({str(c.get("obligation")) for c in due})
                    send_to_owner(
                        f"⏰ {len(due)} overdue commitment(s): "
                        f"{', '.join(kinds)}\n"
                        f"{refs}{' …' if len(due) > 10 else ''}\n"
                        f"👉 Close with #commitment <ref> met — nothing is "
                        f"marked missed automatically.")
                print(f"bic overdue commitments: {len(due)}")
            except Exception as e:
                print(f"bic overdue commitment check failed (ignored): "
                      f"{type(e).__name__}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        pass
