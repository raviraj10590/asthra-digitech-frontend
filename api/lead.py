"""
Asthra DigiTech — Website lead intake

Public endpoint the website's contact form posts to, so web enquiries land in
the CRM's clients table alongside WhatsApp leads. One lead pipeline, every
channel.

Why an endpoint instead of the website calling Supabase directly: the CRM's
clients table has no anon-insert policy, so writing to it needs the
service-role key. Putting that key in a PHP file on shared hosting risks
leaking it if PHP ever fails to execute. Here the key stays in Vercel's env
(same place the webhook already keeps it) and the website holds no secret at
all — it just posts form fields to a URL.

Spam control is a shared token (LEAD_INTAKE_TOKEN). It is deliberately
low-privilege: worst case someone who obtains it can create junk CRM rows —
it grants no read access and cannot touch anything else.
"""

import json, os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

import requests

CRM_SUPABASE_URL         = os.environ.get("CRM_SUPABASE_URL",         "")
CRM_SUPABASE_SERVICE_KEY = os.environ.get("CRM_SUPABASE_SERVICE_KEY", "")
CRM_OWNER_USER_ID        = os.environ.get("CRM_OWNER_USER_ID",        "")
LEAD_INTAKE_TOKEN        = os.environ.get("LEAD_INTAKE_TOKEN",        "")

WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
OWNER_PHONES    = [p.strip() for p in
    os.environ.get("OWNER_PHONE", "918884448141,918861369951").split(",") if p.strip()]


def _crm_headers():
    return {
        "apikey": CRM_SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {CRM_SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


def sync_website_lead(name: str, email: str, phone: str, subject: str, message: str) -> tuple:
    """Upsert a website enquiry into the CRM's clients table.

    Mirrors webhook.sync_lead_to_crm: clients has no unique constraint on
    phone, so this is a lookup-then-insert-or-patch rather than an upsert.
    Returns (ok, detail) so the caller can report a real status instead of
    assuming success."""
    if not (CRM_SUPABASE_URL and CRM_SUPABASE_SERVICE_KEY and CRM_OWNER_USER_ID):
        return False, "CRM not configured"

    notes_parts = ["Source: website contact form"]
    if subject:
        notes_parts.append(f"Subject: {subject}")
    if message:
        notes_parts.append(message)
    notes = " | ".join(notes_parts)

    try:
        existing = []
        if phone:
            r = requests.get(
                f"{CRM_SUPABASE_URL}/rest/v1/clients",
                headers=_crm_headers(),
                params={"phone": f"eq.{phone}", "user_id": f"eq.{CRM_OWNER_USER_ID}",
                        "select": "id,notes"},
                timeout=5,
            )
            if not r.ok:
                return False, f"lookup {r.status_code}: {r.text[:200]}"
            existing = r.json()

        if existing:
            prior = existing[0].get("notes") or ""
            patch = {"notes": f"{prior}\n{notes}".strip() if prior else notes}
            if name:
                patch["name"] = name
            if email:
                patch["email"] = email
            r = requests.patch(
                f"{CRM_SUPABASE_URL}/rest/v1/clients",
                headers={**_crm_headers(), "Prefer": "return=minimal"},
                params={"id": f"eq.{existing[0]['id']}"},
                json=patch,
                timeout=5,
            )
        else:
            r = requests.post(
                f"{CRM_SUPABASE_URL}/rest/v1/clients",
                headers={**_crm_headers(), "Prefer": "return=minimal"},
                json={
                    "user_id": CRM_OWNER_USER_ID,
                    "name": name or (f"Website Lead {phone}" if phone else "Website Lead"),
                    "phone": phone or None,
                    "email": email or None,
                    "notes": notes,
                },
                timeout=5,
            )
        if not r.ok:
            return False, f"write {r.status_code}: {r.text[:200]}"
        return True, "updated" if existing else "created"
    except Exception as e:
        return False, str(e)


def notify_owner(text: str):
    """Best-effort WhatsApp alert so a web lead is seen immediately rather than
    only on the next CRM visit. Never affects the response to the website."""
    if not (WHATSAPP_TOKEN and PHONE_NUMBER_ID):
        return
    for phone in OWNER_PHONES:
        try:
            requests.post(
                f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                         "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": phone, "type": "text",
                      "text": {"body": text, "preview_url": False}},
                timeout=5,
            )
        except Exception as e:
            print(f"notify_owner error ({phone}): {e}")


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"

        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        if not LEAD_INTAKE_TOKEN or data.get("token") != LEAD_INTAKE_TOKEN:
            print("lead intake: bad or missing token")
            self._json(403, {"error": "forbidden"})
            return

        # Honeypot: a field real users never see, so bots that fill every input
        # are dropped. Answer 200 so the bot doesn't learn it was rejected.
        if (data.get("website") or "").strip():
            print("lead intake: honeypot triggered")
            self._json(200, {"ok": True})
            return

        name    = (data.get("name")    or "").strip()[:200]
        email   = (data.get("email")   or "").strip()[:200]
        phone   = (data.get("phone")   or "").strip()[:32]
        subject = (data.get("subject") or "").strip()[:200]
        message = (data.get("message") or "").strip()[:2000]

        if not (phone or email):
            self._json(400, {"error": "phone or email required"})
            return

        ok, detail = sync_website_lead(name, email, phone, subject, message)
        print(f"lead intake: crm sync ok={ok} ({detail}) phone={phone}")

        if ok:
            notify_owner(
                "🌐 New website enquiry\n\n"
                f"Name: {name or '—'}\n"
                f"Phone: {phone or '—'}\n"
                f"Email: {email or '—'}\n"
                f"Subject: {subject or '—'}\n\n"
                f"{message[:300] or '(no message)'}\n\n"
                "Saved to CRM."
            )

        # Always 200 to the website: the enquiry email has already been sent by
        # mail.php, and a CRM failure must not surface as an error to a real
        # customer. The real outcome is in `synced` and in the Vercel logs.
        self._json(200, {"ok": True, "synced": ok})

    def do_GET(self):
        self._json(405, {"error": "POST only"})

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
