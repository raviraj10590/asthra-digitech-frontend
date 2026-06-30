"""
Asthra Digitech — WhatsApp Auto-Reply Bot
Vercel Serverless Function
Uses Meta WhatsApp Cloud API + OpenAI GPT-4o + Supabase memory
"""

import json
import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtwenBybGx6Z3FscWtxZ2NncmJwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzMTE1NDMsImV4cCI6MjA5Mzg4NzU0M30.zFO_b3HfNNEac7eoofZuL7jIMz3MR7MtQyCY948CzTw")
BROCHURE_URL    = os.environ.get("BROCHURE_URL", "")

# ── AI System Prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a smart, friendly WhatsApp sales assistant for Asthra Digitech, a digital marketing agency in Jayanagar, Bengaluru specialising in political and government social media.

ABOUT ASTHRA DIGITECH:
- Services: Social media management, election campaign digital strategy, government branding, content creation, WhatsApp/Telegram group management
- Clients: MLAs, MPs, political parties, government bodies, ministers — mainly Karnataka
- Office: Jayanagar, Bengaluru - 560078
- Phone: +91 88844 48141
- Email: info@asthradigitech.com
- Website: asthradigitech.com
- Head: Raviraj (handles high-value clients personally)

REPLY RULES:
1. Keep replies SHORT — WhatsApp style, 3-5 lines max
2. Be warm and professional. Use "Namaskara 🙏" if message is in Kannada
3. NEVER quote specific prices — say "packages are customised, let's discuss"
4. Election campaign: confirm capability, ask about constituency and timeline
5. Portfolio: offer to share work samples on WhatsApp
6. High-value lead (MLA, minister, party): offer to connect with Raviraj directly
7. Always end with a soft call-to-action (meet, call, or share more details)
8. Kannada/Kanglish message → reply in Kanglish. English message → reply in English
9. Complaints: apologise warmly, say Raviraj will personally follow up
10. If someone asks for a brochure/catalogue/company profile → say "Sure! Sending you our company brochure right now 📄" and nothing else

QUICK CONTEXT:
- Pricing → Packages are customised. Let's connect to understand your needs.
- Portfolio → Will send our work samples on WhatsApp
- Meeting → Available at Jayanagar office, or a quick call first
- Complaint → Apologise, assure resolution, escalate to Raviraj
"""

BROCHURE_KEYWORDS = [
    "brochure", "catalogue", "catalog", "company profile", "profile",
    "pamphlet", "flyer", "details send", "document", "pdf",
    "broshur", "brochar", "pamphlit",
    "brochure kodi", "details kodi", "info kodi", "pamphlet kodi"
]


def get_openai_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


# ── Supabase Memory ───────────────────────────────────────────────────────────
def fetch_history(phone: str, limit: int = 10) -> list:
    try:
        url = f"{SUPABASE_URL}/rest/v1/whatsapp_messages"
        params = {
            "phone": f"eq.{phone}",
            "order": "created_at.desc",
            "limit": limit,
            "select": "role,content"
        }
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        resp = requests.get(url, params=params, headers=headers, timeout=3)
        rows = resp.json() if resp.status_code == 200 else []
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception as e:
        print(f"Supabase fetch error: {e}")
        return []


def save_message(phone: str, role: str, content: str):
    try:
        url = f"{SUPABASE_URL}/rest/v1/whatsapp_messages"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        requests.post(url, headers=headers, json={
            "phone": phone, "role": role, "content": content
        }, timeout=3)
    except Exception as e:
        print(f"Supabase save error: {e}")


# ── Core Logic ────────────────────────────────────────────────────────────────
def is_brochure_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in BROCHURE_KEYWORDS)


def generate_reply(phone: str, user_message: str) -> str:
    history = fetch_history(phone)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    try:
        response = get_openai_client().chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI error: {e}")
        return (
            "Namaskara! 🙏 Thank you for reaching out to Asthra Digitech.\n"
            "Our team will get back to you shortly.\n"
            "For urgent queries: +91 88844 48141"
        )


def send_whatsapp_message(to: str, message: str):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    resp = requests.post(url, headers=headers, json=payload)
    print(f"WhatsApp text: {resp.status_code}")


def send_whatsapp_brochure(to: str):
    if not BROCHURE_URL:
        send_whatsapp_message(to,
            "📄 Please contact us at +91 88844 48141 and we'll send you our brochure on WhatsApp!")
        return
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "link": BROCHURE_URL,
            "filename": "Asthra_Digitech_Company_Profile.pdf",
            "caption": "Here's our company profile! 🙏 Call us at +91 88844 48141 for any queries."
        }
    }
    resp = requests.post(url, headers=headers, json=payload)
    print(f"WhatsApp brochure: {resp.status_code}")


# ── Vercel Serverless Handler ─────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        params    = parse_qs(urlparse(self.path).query)
        mode      = params.get("hub.mode", [""])[0]
        token     = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]
        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(challenge.encode())
        else:
            self.send_response(403)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            entry   = data["entry"][0]
            changes = entry["changes"][0]
            value   = changes["value"]
            if "statuses" in value:
                self._ok()
                return
            messages = value.get("messages", [])
            if not messages:
                self._ok()
                return
            msg      = messages[0]
            sender   = msg["from"]
            msg_type = msg.get("type", "")
            if msg_type != "text":
                self._ok()
                return
            incoming_text = msg["text"]["body"]
            print(f"💬 From {sender}: {incoming_text}")
            save_message(sender, "user", incoming_text)
            if is_brochure_request(incoming_text):
                reply = "Sure! Sending you our company brochure right now 📄"
                send_whatsapp_message(sender, reply)
                send_whatsapp_brochure(sender)
            else:
                reply = generate_reply(sender, incoming_text)
                send_whatsapp_message(sender, reply)
            save_message(sender, "assistant", reply)
            print(f"🤖 Reply: {reply}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"Parse error: {e}")
        self._ok()

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def log_message(self, format, *args):
        pass
