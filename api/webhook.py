"""
Asthra DigiTech — Kannada-First WhatsApp AI Assistant
Version 2.0 — Production Ready

Features:
  - Kannada-first (Bengaluru/Mysuru/North Karnataka/Coastal dialects)
  - Kanglish (Kannada in English letters) understanding
  - Voice message transcription via OpenAI Whisper
  - Interactive WhatsApp buttons (follow-up after brochure)
  - Smart lead collection → Supabase
  - Typo-tolerant keyword detection
  - Conversation memory per phone number
  - Auto brochure PDF delivery
"""

import json, os, re, time, tempfile, requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN",    "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",    "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY",    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtwenBybGx6Z3FscWtxZ2NncmJwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzMTE1NDMsImV4cCI6MjA5Mzg4NzU0M30.zFO_b3HfNNEac7eoofZuL7jIMz3MR7MtQyCY948CzTw")
BROCHURE_URL    = os.environ.get("BROCHURE_URL",    "")

def get_openai():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


# ══════════════════════════════════════════════════════════════════════════════
# KANNADA-FIRST SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """ನೀವು ಆಸ್ತ್ರ ಡಿಜಿಟೆಕ್ (Asthra DigiTech) ಕಂಪನಿಯ AI ಸಹಾಯಕ - "ಆಸ್ತ್ರ AI".
ನಿಮ್ಮ ಮೊದಲ ಭಾಷೆ ಕನ್ನಡ. ಯಾವಾಗಲೂ ನೈಸರ್ಗಿಕ, ಸ್ಥಳೀಯ ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡಿ.
ಯಂತ್ರ ಭಾಷಾಂತರ ಬಳಸಬೇಡಿ. ನೈಜ ಕನ್ನಡ ಗ್ರಾಹಕ ಸೇವಾ ಕಾರ್ಯನಿರ್ವಾಹಕರಂತೆ ಮಾತನಾಡಿ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏢 ಕಂಪನಿ ವಿವರ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ಕಂಪನಿ : ಆಸ್ತ್ರ ಡಿಜಿಟೆಕ್ (Asthra DigiTech)
ವಿಳಾಸ  : ಜಯನಗರ, ಬೆಂಗಳೂರು - 560078
ಫೋನ್   : +91 88844 48141 | +91 94493 56707
ಇಮೇಲ್  : info@asthradigitech.com
ವೆಬ್‌ಸೈಟ್: www.asthradigitech.com
MD      : ರವಿರಾಜ್ ಅವರು (ಪ್ರಮುಖ ಗ್ರಾಹಕರಿಗೆ ನೇರ ಸಂಪರ್ಕ)
ತಂಡ    : 80+ ಜನ | 80+ ಯೋಜನೆಗಳು | 80+ ಸಂತುಷ್ಟ ಗ್ರಾಹಕರು

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛠️ ನಮ್ಮ ಸೇವೆಗಳು
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ಸಾಮಾಜಿಕ ಮಾಧ್ಯಮ ನಿರ್ವಹಣೆ
   Instagram, Facebook, LinkedIn, YouTube, Twitter/X
   Content, Design, Scheduling, Analytics, Community management

2. ವೆಬ್‌ಸೈಟ್ ಡಿಸೈನ್ & ಡೆವಲಪ್‌ಮೆಂಟ್
   Business, Government, E-commerce, Landing pages, Portfolios

3. ಮೊಬೈಲ್ ಆ್ಯಪ್ ಡೆವಲಪ್‌ಮೆಂಟ್
   Android & iOS — business, government, delivery, booking apps

4. AI ಚಾಟ್‌ಬಾಟ್
   WhatsApp bot, Website chatbot, Customer support automation, Lead generation

5. WhatsApp ಆಟೊಮೇಶನ್
   WhatsApp Business API, Broadcast, Drip campaigns, Auto-reply

6. ಡಿಜಿಟಲ್ ಜಾಹೀರಾತು (Ads)
   Google Ads, Meta Ads (FB/Instagram), LinkedIn Ads, YouTube Ads

7. ರಾಜಕೀಯ ಡಿಜಿಟಲ್ ಕ್ಯಾಂಪೇನ್
   MLA / MP / ಚುನಾವಣೆ ಕ್ಯಾಂಪೇನ್, WhatsApp/Telegram ಗ್ರೂಪ್ ನಿರ್ವಹಣೆ
   Voter outreach, Political content, Reputation management

8. ಸರ್ಕಾರಿ ಯೋಜನೆಗಳು
   Government department social media, Public awareness campaigns
   Crisis communication, Citizen engagement

9. ಸೆಲೆಬ್ರಿಟಿ ಸೋಷಿಯಲ್ ಮೀಡಿಯಾ
   ಚಲನಚಿತ್ರ ತಾರೆಗಳು, ಕ್ರೀಡಾಪಟುಗಳು, Influencers — account management & growth

10. ಗ್ರಾಫಿಕ್ ಡಿಸೈನ್ & ಬ್ರ್ಯಾಂಡಿಂಗ್
    Logo, Brand identity, Brochure, Poster, Social media creatives

11. ಫೋಟೋಗ್ರಫಿ & ವಿಡಿಯೋಗ್ರಫಿ
    ಕಾರ್ಪೊರೇಟ್, ರಾಜಕೀಯ, ಘಟನೆ, ಉತ್ಪನ್ನ ಫೋಟೋ/ವಿಡಿಯೋ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 ಭಾಷಾ ನಿಯಮಗಳು
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• ಕನ್ನಡದಲ್ಲಿ ಬಂದರೆ → ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸಿ (ನೈಸರ್ಗಿಕ, ಸ್ಥಳೀಯ)
• ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಬಂದರೆ → ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಉತ್ತರಿಸಿ
• ಹಿಂದಿಯಲ್ಲಿ ಬಂದರೆ → ಹಿಂದಿಯಲ್ಲಿ ಉತ್ತರಿಸಿ
• Kanglish (kannada in English letters: "website beku", "price eshtu") → ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಉತ್ತರಿಸಿ
• ಮಿಶ್ರ ಭಾಷೆ → ಕನ್ನಡ ಮೊದಲು, Tech terms ಇಂಗ್ಲಿಷ್‌ನಲ್ಲೇ ಇರಲಿ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🗣️ ಕನ್ನಡ ಉಪಭಾಷೆಗಳು — ಎಲ್ಲವನ್ನೂ ಅರ್ಥ ಮಾಡಿ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• ಬೆಂಗಳೂರು: "ಏನ್ ಬೇಕಿತ್ತು?", "ಮಾಡ್ತೀರಾ?", "ಆಗುತ್ತಾ?"
• ಮೈಸೂರು: "ಏನು ಬೇಕಾಗಿದೆ?", "ಮಾಡುವಿರಾ?", "ಸಾಧ್ಯವೇ?"
• ಉತ್ತರ ಕರ್ನಾಟಕ: "ಏನ್ ಬೇಕ್ರಿ?", "ಮಾಡ್ತೀರ್ರಿ?", "ಆಕ್ಕೈತ್ರಿ?"
• ಕರಾವಳಿ: "ಏನ್ ಬೇಕಾತ್?", "ಮಾಡ್ಕೊಡ್ತ್ರಾ?", "ಸಾಧ್ಯ ಆದ್ದಾ?"
• Kanglish: "website beku", "price eshtu", "quotation beku", "meeting fix madi"
ಎಲ್ಲಾ ರೀತಿಯ ಕನ್ನಡ ಅರ್ಥ ಮಾಡಿ, Standard ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸಿ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 ಬೆಲೆ ಕೇಳಿದಾಗ (PRICING)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ಎಂದಿಗೂ Fixed price ಕೊಡಬೇಡಿ. ಬದಲಿಗೆ ಕೇಳಿ:
• ಯಾವ ಸೇವೆ ಬೇಕು?
• ಎಷ್ಟು ಪುಟಗಳು / ಫೀಚರ್‌ಗಳು?
• ಯಾವ ಭಾಷೆ ಬೇಕು?
• ಯಾವಾಗ ಬೇಕು? (Timeline)
• ನಿಮ್ಮ ಬಜೆಟ್ ಎಷ್ಟು?
ಅವರ ಉತ್ತರ ಬಂದ ಮೇಲೆ ಅಂದಾಜು estimate ಕೊಡಿ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 LEAD ಸಂಗ್ರಹ — ಸ್ವಾಭಾವಿಕವಾಗಿ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ಸಂಭಾಷಣೆಯ ನಡುವೆ ಸ್ವಾಭಾವಿಕವಾಗಿ ಸಂಗ್ರಹಿಸಿ:
• ಹೆಸರು | ಕಂಪನಿ/ಸಂಸ್ಥೆ | ಯಾವ ಸೇವೆ ಬೇಕು | ಬಜೆಟ್ | ನಗರ
ಒಂದೇ ಸಲ ಎಲ್ಲ ಕೇಳಬೇಡಿ. ಸಂಭಾಷಣೆ ಹರಿವಿನ ಮಧ್ಯೆ ಕೇಳಿ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ ತ್ವರಿತ ಉತ್ತರಗಳು
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ಕರೆ ಮಾಡಿ     → "📞 +91 88844 48141 | +91 94493 56707"
ಮೀಟಿಂಗ್       → "ಜಯನಗರ ಆಫೀಸ್ ಅಥವಾ Video call — ಯಾವ ದಿನ ಅನುಕೂಲ?"
ಪೋರ್ಟ್‌ಫೋಲಿಯೊ  → "www.asthradigitech.com ನೋಡಿ"
ದೂರು          → "ಕ್ಷಮಿಸಿ 🙏 ರವಿರಾಜ್ ಅವರು ವೈಯಕ್ತಿಕವಾಗಿ ಸಂಪರ್ಕಿಸುತ್ತಾರೆ"
MLA/ಮಂತ್ರಿ/ಸರ್ಕಾರ → "MD ರವಿರಾಜ್ ಅವರೊಂದಿಗೆ ನೇರ ಮಾತನಾಡಿ: +91 88844 48141"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ಟೋನ್ & ಶೈಲಿ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• WhatsApp style — 3-5 ಸಾಲು max
• ಸ್ನೇಹಿ ಆದರೆ ವೃತ್ತಿಪರ
• "ನಮಸ್ಕಾರ 🙏", "ಹೌದು, ಖಂಡಿತ!", "ಒಳ್ಳೆ ಪ್ರಶ್ನೆ!" ಬಳಸಿ
• Emoji ಕಡಿಮೆ ಆದರೆ ಸೂಕ್ತ ಕಡೆ ಬಳಸಿ
• ಪ್ರತಿ ಉತ್ತರ ಕೊನೆಯಲ್ಲಿ Soft CTA ಇರಲಿ
• Robot ಭಾಷೆ ಬಳಸಬೇಡಿ — ನಿಜವಾದ ಮಾನವನಂತೆ ಮಾತನಾಡಿ"""


# ══════════════════════════════════════════════════════════════════════════════
# BROCHURE KEYWORD DETECTION (Comprehensive + Fuzzy)
# ══════════════════════════════════════════════════════════════════════════════
BROCHURE_KEYWORDS = [
    # ── Kannada script ────────────────────────────────────────────────────────
    "ಬ್ರೋಚರ್", "ಬ್ರೋಷರ್", "ಬ್ರೊಚರ್", "ಕ್ಯಾಟಲಾಗ್", "ಕ್ಯಾಟಲಾಗ್",
    "ಕಂಪನಿ ಪ್ರೊಫೈಲ್", "ಪ್ರೊಫೈಲ್ ಕಳಿಸಿ", "ಪ್ರೊಫೈಲ್ ಕೊಡಿ",
    "ಬ್ರೋಚರ್ ಕಳಿಸಿ", "ಬ್ರೋಚರ್ ಕೊಡಿ", "ಬ್ರೋಚರ್ ಕಳ್ಳಿಸಿ",
    "ಡಾಕ್ಯುಮೆಂಟ್ ಕಳಿಸಿ", "ಪಿಡಿಎಫ್ ಕಳಿಸಿ", "ಪಿಡಿಎಫ್ ಕೊಡಿ",
    "ಮಾಹಿತಿ ಕಳಿಸಿ", "ವಿವರ ಕಳಿಸಿ", "ಕಂಪನಿ ಮಾಹಿತಿ", "ಕಂಪನಿ ವಿವರ",
    "ಪ್ಯಾಂಫ್ಲೆಟ್", "ಫ್ಲೈಯರ್",
    # ── Kanglish (Kannada in English letters) ─────────────────────────────────
    "brochure", "brochar", "brocher", "broucher", "broshur", "broshure",
    "brochre", "broshar", "brochar", "brocure", "brouchar",
    "catalogue", "catalog", "company profile", "profile",
    "pamphlet", "pamphlit", "pamplet", "flyer",
    "brochure kodi", "brochure kalisi", "brochure pathayisi", "brochure kalli",
    "details kodi", "details kalisi", "info kodi", "info kalisi",
    "maahiti kodi", "vivara kodi", "vivara kalisi",
    "pdf kodi", "pdf kalisi", "pdf pathayisi",
    "document kodi", "document kalisi",
    # ── English ────────────────────────────────────────────────────────────────
    "send brochure", "share brochure", "company document", "company pdf",
    "send pdf", "share pdf", "send profile", "share profile",
    "send catalogue", "share catalogue",
]

def is_brochure_request(text: str) -> bool:
    t = text.lower().strip()
    if any(kw.lower() in t for kw in BROCHURE_KEYWORDS):
        return True
    # Fuzzy regex — catches "brochur", "broochure", "broucher" etc.
    if re.search(r'br[o0]+[cks]h?[aeu]+r|br[o0]+sh+[aeu]+r', t):
        return True
    # Kannada: ಬ್ರೋ prefix
    if "ಬ್ರೋ" in t and ("ಚ" in t or "ಷ" in t):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _supa_headers(prefer="return=minimal"):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h

def fetch_history(phone: str, limit: int = 12) -> list:
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_supa_headers(""),
            params={
                "phone":  f"eq.{phone}",
                "order":  "created_at.desc",
                "limit":  str(limit),
                "select": "role,content",
            },
            timeout=5,
        )
        msgs = r.json() if r.ok else []
        return [{"role": m["role"], "content": m["content"]} for m in reversed(msgs)]
    except Exception as e:
        print(f"fetch_history error: {e}")
        return []

def save_message(phone: str, role: str, content: str):
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_supa_headers(),
            json={"phone": phone, "role": role, "content": content},
            timeout=5,
        )
    except Exception as e:
        print(f"save_message error: {e}")

def upsert_lead(phone: str, data: dict):
    """Insert or update lead info (merge on phone)."""
    if not data:
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/leads",
            headers=_supa_headers("resolution=merge-duplicates"),
            json={"phone": phone, **data},
            timeout=5,
        )
        print(f"lead upserted: {data}")
    except Exception as e:
        print(f"upsert_lead error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# LEAD EXTRACTION (GPT-4o-mini — fast & cheap)
# ══════════════════════════════════════════════════════════════════════════════
def extract_lead_info(history: list) -> dict:
    """Extract structured lead info from conversation history."""
    if len(history) < 3:
        return {}
    try:
        conv = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-10:])
        resp = get_openai().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract lead info from this WhatsApp conversation. "
                        "Return ONLY a valid JSON object with these optional fields: "
                        "name, company, service_needed, budget, city. "
                        "Only include fields that are clearly mentioned. "
                        "Return {} if nothing found."
                    ),
                },
                {"role": "user", "content": conv},
            ],
            max_tokens=150,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON even if there's surrounding text
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else {}
    except Exception as e:
        print(f"extract_lead_info error: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# VOICE MESSAGE TRANSCRIPTION (OpenAI Whisper)
# ══════════════════════════════════════════════════════════════════════════════
def transcribe_audio(media_id: str) -> str:
    """Download WhatsApp voice note and transcribe with Whisper (Kannada)."""
    try:
        # Step 1: Get media download URL from Meta
        meta_resp = requests.get(
            f"https://graph.facebook.com/v19.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10,
        )
        media_url = meta_resp.json().get("url", "")
        if not media_url:
            print("transcribe_audio: no media URL")
            return ""

        # Step 2: Download audio file
        audio_resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30,
        )

        # Step 3: Write to temp file (WhatsApp sends ogg/opus)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_resp.content)
            tmp = f.name

        # Step 4: Whisper transcription
        with open(tmp, "rb") as audio_file:
            result = get_openai().audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="kn",  # Kannada
                prompt=(
                    "ಕನ್ನಡ ಭಾಷೆ. ಡಿಜಿಟಲ್ ಮಾರ್ಕೆಟಿಂಗ್, "
                    "ವೆಬ್‌ಸೈಟ್, ಸೋಷಿಯಲ್ ಮೀಡಿಯಾ, ಬ್ರೋಚರ್, "
                    "Asthra DigiTech."
                ),
            )
        os.unlink(tmp)
        text = result.text.strip()
        print(f"🎤 Whisper: {text}")
        return text

    except Exception as e:
        print(f"transcribe_audio error: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# AI REPLY GENERATION
# ══════════════════════════════════════════════════════════════════════════════
def generate_reply(phone: str, user_message: str) -> str:
    history = fetch_history(phone, 12)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_message})

    try:
        resp = get_openai().chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=400,
            temperature=0.75,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"generate_reply error: {e}")
        return (
            "ನಮಸ್ಕಾರ 🙏 ಸ್ವಲ್ಪ ತಾಂತ್ರಿಕ ಸಮಸ್ಯೆ ಆಗಿದೆ. "
            "ತುರ್ತಿಗಾಗಿ ಕರೆ ಮಾಡಿ: +91 88844 48141"
        )


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP CLOUD API — SEND FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def _wa_post(payload: dict):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    print(f"WA API {r.status_code}: {r.text[:120]}")
    return r

def send_text(to: str, message: str):
    _wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message, "preview_url": False},
    })

def send_brochure(to: str):
    """Send company profile PDF as a document message."""
    if not BROCHURE_URL:
        send_text(to,
            "ಬ್ರೋಚರ್ ಶೀಘ್ರದಲ್ಲೇ ಕಳಿಸುತ್ತೇವೆ. "
            "ಈಗ ಕರೆ ಮಾಡಿ: +91 88844 48141"
        )
        return
    _wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "link": BROCHURE_URL,
            "caption": "ಆಸ್ತ್ರ ಡಿಜಿಟೆಕ್ — ಕಂಪನಿ ಪ್ರೊಫೈಲ್ 🙏",
            "filename": "Asthra_DigiTech_Company_Profile.pdf",
        },
    })

def send_followup_buttons(to: str):
    """Send interactive quick-reply buttons after brochure (max 3)."""
    r = _wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "ನಿಮಗೆ ಮುಂದೆ ಏನು ಬೇಕು? 👇"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "quotation", "title": "📋 ಕೋಟೇಶನ್"}},
                    {"type": "reply", "reply": {"id": "call",      "title": "📞 ಕರೆ ಮಾಡಿ"}},
                    {"type": "reply", "reply": {"id": "meeting",   "title": "🤝 ಮೀಟಿಂಗ್"}},
                ]
            },
        },
    })
    # Fallback: plain text if buttons not supported (old WhatsApp / error)
    if not r.ok:
        send_text(to,
            "ನಿಮಗೆ ಮುಂದೆ ಏನು ಬೇಕು?\n\n"
            "1️⃣ ಕೋಟೇಶನ್ — ಟೈಪ್ ಮಾಡಿ: quotation\n"
            "2️⃣ ಕರೆ ಮಾಡಿ: +91 88844 48141\n"
            "3️⃣ ಮೀಟಿಂಗ್ ಫಿಕ್ಸ್ — ಟೈಪ್ ಮಾಡಿ: meeting\n"
            "4️⃣ ಪೋರ್ಟ್‌ಫೋಲಿಯೊ: www.asthradigitech.com"
        )

def handle_button_reply(to: str, btn_id: str, btn_title: str):
    """Respond to WhatsApp quick-reply button taps."""
    if btn_id == "quotation":
        send_text(to,
            "ಖಂಡಿತ! ಕೋಟೇಶನ್ ತಯಾರಿಸಲು ಕೆಲವು ವಿವರ ಹೇಳಿ:\n\n"
            "1️⃣ ಯಾವ ಸೇವೆ ಬೇಕು?\n"
            "   (Website / App / Social Media / AI Chatbot / Ads / ...)\n"
            "2️⃣ ನಿಮ್ಮ ಕಂಪನಿ / ಸಂಸ್ಥೆ ಹೆಸರು?\n"
            "3️⃣ ನಿಮ್ಮ ಬಜೆಟ್ ಅಂದಾಜು ಎಷ್ಟು?\n"
            "4️⃣ ಯಾವಾಗ ಬೇಕು? 📅"
        )
    elif btn_id == "call":
        send_text(to,
            "📞 ನಮ್ಮ ತಂಡ ಮಾತನಾಡಲು ಸಿದ್ಧ!\n\n"
            "☎️ +91 88844 48141\n"
            "☎️ +91 94493 56707\n\n"
            "🕐 ಸೋಮ–ಶನಿ: ಬೆಳಿಗ್ಗೆ 9 – ರಾತ್ರಿ 7"
        )
    elif btn_id == "meeting":
        send_text(to,
            "🤝 ಮೀಟಿಂಗ್ ಫಿಕ್ಸ್ ಮಾಡೋಣ!\n\n"
            "📍 ಆಫೀಸ್: ಜಯನಗರ, ಬೆಂಗಳೂರು\n"
            "🖥️ ವಿಡಿಯೋ ಕಾಲ್ ಸಹ ಆಗುತ್ತದೆ\n\n"
            "ನಿಮಗೆ ಯಾವ ದಿನ ಮತ್ತು ಸಮಯ ಅನುಕೂಲ? 📅"
        )
    else:
        # Unknown button — let AI handle
        reply = generate_reply(to, btn_title)
        send_text(to, reply)


# ══════════════════════════════════════════════════════════════════════════════
# VERCEL SERVERLESS HANDLER
# ══════════════════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        """Meta webhook verification."""
        params    = parse_qs(urlparse(self.path).query)
        mode      = params.get("hub.mode",         [""])[0]
        token     = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge",    [""])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(challenge.encode())
            print("✅ Webhook verified")
        else:
            self.send_response(403)
            self.end_headers()

    def do_POST(self):
        """Receive and process incoming WhatsApp messages."""
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        try:
            data    = json.loads(body)
            entry   = data["entry"][0]
            changes = entry["changes"][0]
            value   = changes["value"]

            # Ignore delivery / read receipts
            if "statuses" in value:
                self._ok(); return

            messages = value.get("messages", [])
            if not messages:
                self._ok(); return

            msg      = messages[0]
            sender   = msg["from"]
            msg_type = msg.get("type", "")

            print(f"📨 {msg_type} from {sender}")

            # ── Interactive button reply ───────────────────────────────────
            if msg_type == "interactive":
                iact = msg.get("interactive", {})
                if iact.get("type") == "button_reply":
                    btn = iact["button_reply"]
                    handle_button_reply(sender, btn["id"], btn["title"])
                self._ok(); return

            # ── Voice / Audio message ─────────────────────────────────────
            if msg_type == "audio":
                media_id   = msg["audio"]["id"]
                transcribed = transcribe_audio(media_id)
                if not transcribed:
                    send_text(sender,
                        "🎤 ಧ್ವನಿ ಸಂದೇಶ ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. "
                        "ದಯವಿಟ್ಟು ಟೈಪ್ ಮಾಡಿ 🙏"
                    )
                    self._ok(); return
                # Acknowledge voice with transcription
                send_text(sender,
                    f"🎤 ನಿಮ್ಮ ಧ್ವನಿ ಸಂದೇಶ:\n"{transcribed}""
                )
                user_text = transcribed

            # ── Text message ──────────────────────────────────────────────
            elif msg_type == "text":
                user_text = msg["text"]["body"]

            else:
                # Image, video, sticker, etc. — acknowledge
                send_text(sender,
                    "ನಿಮ್ಮ ಸಂದೇಶ ಸ್ವೀಕರಿಸಿದ್ದೇವೆ 🙏 "
                    "ಪ್ರಶ್ನೆ ಅಥವಾ ವಿವರ ಟೈಪ್ ಮಾಡಿ."
                )
                self._ok(); return

            print(f"💬 Text: {user_text[:80]}")

            # Save user message to memory
            save_message(sender, "user", user_text)

            # ── Brochure request? ─────────────────────────────────────────
            if is_brochure_request(user_text):
                save_message(sender, "assistant", "[ಬ್ರೋಚರ್ PDF ಕಳಿಸಲಾಯಿತು]")
                send_text(sender,
                    "ಖಂಡಿತ! ನಮ್ಮ ಕಂಪನಿ ಪ್ರೊಫೈಲ್ ಇಲ್ಲಿದೆ 🙏"
                )
                send_brochure(sender)
                time.sleep(1)
                send_followup_buttons(sender)

            # ── Normal AI reply ───────────────────────────────────────────
            else:
                reply = generate_reply(sender, user_text)
                print(f"🤖 {reply[:80]}")
                send_text(sender, reply)
                save_message(sender, "assistant", reply)

                # Extract & save lead info every few turns
                history = fetch_history(sender, 8)
                if len(history) >= 4:
                    lead = extract_lead_info(history)
                    if lead:
                        upsert_lead(sender, lead)

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"Parse error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

        self._ok()

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def log_message(self, format, *args):
        pass  # suppress default access logs
