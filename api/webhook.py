"""
Asthra Digitech — WhatsApp Auto-Reply Bot
Vercel Serverless Function
Uses Meta WhatsApp Cloud API + OpenAI GPT-4
"""

import json
import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from openai import OpenAI

# ── Config (set in Vercel dashboard → Environment Variables) ─────────────────
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")

def get_openai_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

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
"""


def generate_reply(user_message: str) -> str:
    try:
        response = get_openai_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
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
    print(f"WhatsApp send: {resp.status_code} | {resp.text}")
    return resp


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
            reply = generate_reply(incoming_text)
            send_whatsapp_message(sender, reply)

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
