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

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        pass
