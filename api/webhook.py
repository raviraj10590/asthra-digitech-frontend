"""
Asthra DigiTech — Kannada-First WhatsApp AI Assistant
Version 2.1 — Production Ready

Features:
  - Kannada-first (Bengaluru/Mysuru/North Karnataka/Coastal dialects)
  - Kanglish (Kannada in English letters) understanding
  - Voice message transcription via OpenAI Whisper
  - Interactive WhatsApp buttons + services list menu
  - Welcome menu for first-time contacts
  - Smart lead collection → Supabase
  - Instant lead / VIP / election alerts to owner's WhatsApp
  - Owner commands: #stop <phone> / #start <phone> (pause bot per chat)
  - Duplicate webhook (Meta retry) protection
  - Business-hours awareness (IST)
  - Typo-tolerant keyword detection
  - Conversation memory per phone number
  - Auto brochure PDF delivery
"""

import json, os, re, time, tempfile, requests
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN",    "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",    "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY",    "")  # anon key — set in Vercel env vars
BROCHURE_URL    = os.environ.get("BROCHURE_URL",    "")
OWNER_PHONE     = os.environ.get("OWNER_PHONE",     "918884448141")  # Raviraj — lead alerts

IST = timezone(timedelta(hours=5, minutes=30))

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
👑 VIP / ರಾಜಕೀಯ ಗ್ರಾಹಕರು
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MLA / MP / ಮಂತ್ರಿ / ಪಕ್ಷದ ಕಚೇರಿ / ಸರ್ಕಾರಿ ಇಲಾಖೆ ಸಂಪರ್ಕಿಸಿದರೆ:
• ಬೆಲೆ ಚರ್ಚೆ ಮಾಡಬೇಡಿ, ಮಾರಾಟದ ಒತ್ತಡ ಹಾಕಬೇಡಿ
• ಗೌರವದಿಂದ: "MD ರವಿರಾಜ್ ಅವರು ನಿಮ್ಮನ್ನು ವೈಯಕ್ತಿಕವಾಗಿ ಸಂಪರ್ಕಿಸುತ್ತಾರೆ 🙏"
• ನೇರ ನಂಬರ್ ಕೊಡಿ: +91 88844 48141

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🗳️ ರಾಜಕೀಯ ಜ್ಞಾನ — ಕಟ್ಟುನಿಟ್ಟಾದ ನಿಯಮಗಳು
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ನಿಮಗೆ Karnataka ದ 224 ಕ್ಷೇತ್ರಗಳ ನೈಜ ಡೇಟಾ ಸಿಗುತ್ತದೆ (AI Kannada database).
ಸಂದೇಶದ ಜೊತೆ "REAL DATA" block ಬಂದರೆ ಅದನ್ನು ಬಳಸಿ — ಊಹಿಸಬೇಡಿ.
• ಸತ್ಯಾಂಶ ಮಾತ್ರ ಹೇಳಿ: ಶಾಸಕರ ಹೆಸರು, ಪಕ್ಷ, ಜಿಲ್ಲೆ, ಮತದಾರರ ಸಂಖ್ಯೆ, ಕ್ಷೇತ್ರದ ವಿಷಯಗಳು
• ಯಾವುದೇ ಪಕ್ಷ / ರಾಜಕಾರಣಿ ಬಗ್ಗೆ ಅಭಿಪ್ರಾಯ, ಹೊಗಳಿಕೆ, ಟೀಕೆ — ಎಂದಿಗೂ ಇಲ್ಲ
• Asthra ಎಲ್ಲಾ ಪಕ್ಷಗಳಿಗೂ ಕೆಲಸ ಮಾಡುತ್ತದೆ — ಸಂಪೂರ್ಣ ತಟಸ್ಥ (neutral)
• ಈ ಜ್ಞಾನವನ್ನು ಗ್ರಾಹಕರ ಅಗತ್ಯ ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲು ಬಳಸಿ — ರಾಜಕೀಯ ಚರ್ಚೆಗೆ ಅಲ್ಲ
• ಸುದ್ದಿ ಕೇಳಿದರೆ aikannada.shop ಲಿಂಕ್ ಹಂಚಿ (ನಮ್ಮದೇ ನ್ಯೂಸ್ ಪ್ಲಾಟ್‌ಫಾರ್ಮ್)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 SELF-DEMO — ನೀವೇ ನಮ್ಮ ಉತ್ಪನ್ನ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ನೀವು ಸ್ವತಃ Asthra ನಿರ್ಮಿಸಿದ AI chatbot. ಸಂಭಾಷಣೆ ಚೆನ್ನಾಗಿ ಸಾಗಿ
ಮುಗಿಯುವ ಹಂತದಲ್ಲಿ (ಒಮ್ಮೆ ಮಾತ್ರ, ಪ್ರತಿ ಸಂದೇಶದಲ್ಲೂ ಅಲ್ಲ) ಸೇರಿಸಿ:
"ಈ ತರಹದ AI chatbot ನಿಮ್ಮ business ಗೂ ಬೇಕಾ? ನಾವೇ ಮಾಡಿಕೊಡುತ್ತೇವೆ 😊"

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
# VIP / ELECTION LEAD DETECTION
# ══════════════════════════════════════════════════════════════════════════════
VIP_REGEXES = [
    r'\bmla\b', r'\bmp\b', r'\bminister\b', r'\bcm\b', r"cm'?s office",
    r'party office', r'\bmlc\b', r'\bias\b', r'\bips\b', r'corporator',
]
VIP_SUBSTRINGS = ['ಶಾಸಕ', 'ಸಂಸದ', 'ಮಂತ್ರಿ', 'ಮುಖ್ಯಮಂತ್ರಿ', 'ಸಚಿವ', 'ಪಕ್ಷದ ಕಚೇರಿ']

ELECTION_REGEXES = [
    r'\belection\b', r'\bcampaign\b', r'constituency', r'\bvoter',
    r'\bticket\b', r'panchayat', r'\bpolls?\b',
]
ELECTION_SUBSTRINGS = ['ಚುನಾವಣೆ', 'ಕ್ಷೇತ್ರ', 'ಮತದಾರ', 'ಪ್ರಚಾರ']

def is_vip_message(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in VIP_REGEXES) or any(s in t for s in VIP_SUBSTRINGS)

def is_election_message(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in ELECTION_REGEXES) or any(s in t for s in ELECTION_SUBSTRINGS)


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
    """Chat history for the AI — user/assistant turns only (system rows excluded)."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_supa_headers(""),
            params={
                "phone":  f"eq.{phone}",
                "role":   "in.(user,assistant)",
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

def fetch_last_user_message(phone: str) -> dict:
    """Most recent inbound message — used for Meta-retry deduplication."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_supa_headers(""),
            params={
                "phone":  f"eq.{phone}",
                "role":   "eq.user",
                "order":  "created_at.desc",
                "limit":  "1",
                "select": "content,created_at",
            },
            timeout=5,
        )
        rows = r.json() if r.ok else []
        return rows[0] if rows else {}
    except Exception as e:
        print(f"fetch_last_user_message error: {e}")
        return {}

def fetch_last_system_event(phone: str, marker: str) -> dict:
    """Latest bot-control event (BOT_PAUSED / VIP_ALERTED / ...) for a phone."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_supa_headers(""),
            params={
                "phone":   f"eq.{phone}",
                "role":    "eq.system",
                "content": f"like.{marker}*",
                "order":   "created_at.desc",
                "limit":   "1",
                "select":  "content,created_at",
            },
            timeout=5,
        )
        rows = r.json() if r.ok else []
        return rows[0] if rows else {}
    except Exception as e:
        print(f"fetch_last_system_event error: {e}")
        return {}

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


def _within_hours(iso_ts: str, hours: float) -> bool:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts < timedelta(hours=hours)
    except Exception:
        return False

def is_bot_paused(phone: str) -> bool:
    """Owner can pause the bot per chat (#stop) — auto-resumes after 24h."""
    ev = fetch_last_system_event(phone, "BOT_")
    if not ev:
        return False
    if ev["content"].startswith("BOT_PAUSED"):
        return _within_hours(ev.get("created_at", ""), 24)
    return False

def is_duplicate_webhook(phone: str, text: str) -> bool:
    """Meta retries webhooks — identical text within 60s is a retry, not a person."""
    last = fetch_last_user_message(phone)
    if not last:
        return False
    return last.get("content") == text and _within_hours(last.get("created_at", ""), 1 / 60)


# ══════════════════════════════════════════════════════════════════════════════
# POLITICAL INTELLIGENCE — constituency data + headlines from AI Kannada DB
# (facts only; the system prompt enforces strict party neutrality)
# ══════════════════════════════════════════════════════════════════════════════
NEWS_KEYWORDS = ["news", "ಸುದ್ದಿ", "headline", "suddi", "ರಾಜಕೀಯ ಬೆಳವಣಿಗೆ"]

def find_constituency_context(text: str) -> str:
    """If the message names one of Karnataka's 224 constituencies, return a
    REAL DATA block with that constituency's facts. Empty string otherwise."""
    if len(text) < 4:
        return ""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/constituencies",
            headers=_supa_headers(""),
            params={"select": "name,name_kn,slug", "limit": "300"},
            timeout=5,
        )
        rows = r.json() if r.ok else []
        t = text.lower()
        match_slug = None
        for row in rows:
            name_kn = row.get("name_kn") or ""
            name_en = (row.get("name") or "").lower()
            if name_kn and name_kn in text:
                match_slug = row["slug"]; break
            # English names: word-boundary match, ≥4 chars to avoid noise
            if len(name_en) >= 4 and re.search(r'\b' + re.escape(name_en) + r'\b', t):
                match_slug = row["slug"]; break
        if not match_slug:
            return ""

        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/constituencies",
            headers=_supa_headers(""),
            params={
                "slug": f"eq.{match_slug}",
                "select": "name,name_kn,district,reserved,current_mla_name,current_party,electors,major_communities,key_issues",
                "limit": "1",
            },
            timeout=5,
        )
        rows = r.json() if r.ok else []
        if not rows:
            return ""
        c = rows[0]
        parts = [f"REAL DATA — ಕ್ಷೇತ್ರ: {c.get('name_kn') or c.get('name')} ({c.get('name')}), ಜಿಲ್ಲೆ: {c.get('district')}"]
        if c.get("current_mla_name"):
            parts.append(f"ಹಾಲಿ ಶಾಸಕರು: {c['current_mla_name']} ({c.get('current_party') or '—'})")
        if c.get("reserved") and c["reserved"] not in ("General", None):
            parts.append(f"ಮೀಸಲಾತಿ: {c['reserved']}")
        if c.get("electors"):
            parts.append(f"ಮತದಾರರು: ~{c['electors']}")
        if c.get("major_communities"):
            parts.append(f"ಪ್ರಮುಖ ಸಮುದಾಯಗಳು: {c['major_communities']}")
        if c.get("key_issues"):
            parts.append(f"ಕ್ಷೇತ್ರದ ಪ್ರಮುಖ ವಿಷಯಗಳು: {c['key_issues']}")
        parts.append("(ಸತ್ಯಾಂಶ ಮಾತ್ರ ಬಳಸಿ — ತಟಸ್ಥವಾಗಿರಿ)")
        return "\n".join(parts)
    except Exception as e:
        print(f"find_constituency_context error: {e}")
        return ""

def news_context_if_asked(text: str) -> str:
    """If the user asks for news/headlines, return today's top political
    headlines from aikannada.shop as a REAL DATA block."""
    t = text.lower()
    if not any(k in t or k in text for k in NEWS_KEYWORDS):
        return ""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/articles",
            headers=_supa_headers(""),
            params={
                "published": "eq.true",
                "select": "title,slug,category",
                "order": "published_at.desc",
                "limit": "3",
            },
            timeout=5,
        )
        rows = r.json() if r.ok else []
        if not rows:
            return ""
        lines = ["REAL DATA — ಇಂದಿನ ಪ್ರಮುಖ ಸುದ್ದಿ (ನಮ್ಮ AI Kannada ಪ್ಲಾಟ್‌ಫಾರ್ಮ್‌ನಿಂದ):"]
        for a in rows:
            lines.append(f"• {a['title']} — https://www.aikannada.shop/news/{a['slug']}")
        lines.append("(ಈ ಸುದ್ದಿ ಹಂಚಿ, ಕೊನೆಯಲ್ಲಿ aikannada.shop ನಮ್ಮದೇ ಪ್ಲಾಟ್‌ಫಾರ್ಮ್ ಎಂದು ಹೆಮ್ಮೆಯಿಂದ ಹೇಳಿ)")
        return "\n".join(lines)
    except Exception as e:
        print(f"news_context_if_asked error: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# BUSINESS HOURS (IST)
# ══════════════════════════════════════════════════════════════════════════════
def after_hours_note() -> str:
    """Outside Mon–Sat 9am–7pm IST, set expectations for a human follow-up."""
    now = datetime.now(IST)
    if now.weekday() == 6 or not (9 <= now.hour < 19):
        return "\n\n🕐 ನಮ್ಮ ತಂಡ ಕೆಲಸದ ಸಮಯದಲ್ಲಿ (ಸೋಮ–ಶನಿ, ಬೆಳಿಗ್ಗೆ 9 – ಸಂಜೆ 7) ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತದೆ 🙏"
    return ""


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

    # Political intelligence: constituency facts + live headlines when relevant
    intel = "\n\n".join(x for x in (
        find_constituency_context(user_message),
        news_context_if_asked(user_message),
    ) if x)
    if intel:
        messages.append({"role": "system", "content": intel})

    messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_message})

    try:
        resp = get_openai().chat.completions.create(
            model="gpt-4o-mini",
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

def notify_owner(message: str):
    """Instant WhatsApp alert to Raviraj. Note: outside the 24h customer-service
    window with the owner's own number, Meta rejects free-form text — the owner
    should message the bot number occasionally to keep the window open."""
    try:
        send_text(OWNER_PHONE, message)
    except Exception as e:
        print(f"notify_owner error: {e}")

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

def send_welcome_menu(to: str):
    """First-contact greeting + tappable services list (free interactive message)."""
    send_text(to,
        "ನಮಸ್ಕಾರ 🙏 ಆಸ್ತ್ರ ಡಿಜಿಟೆಕ್‌ಗೆ ಸ್ವಾಗತ!\n\n"
        "ನಾನು ಆಸ್ತ್ರ AI — ನಿಮ್ಮ ಡಿಜಿಟಲ್ ಮಾರ್ಕೆಟಿಂಗ್ ಸಹಾಯಕ.\n"
        "ಕನ್ನಡ, English, ಹಿಂದಿ — ಯಾವ ಭಾಷೆಯಲ್ಲಾದರೂ ಮಾತನಾಡಿ!"
    )
    r = _wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "ನಿಮಗೆ ಯಾವ ಸೇವೆ ಬೇಕು? ಕೆಳಗೆ ಆಯ್ಕೆ ಮಾಡಿ 👇"},
            "action": {
                "button": "ಸೇವೆಗಳು 📋",
                "sections": [
                    {
                        "title": "Asthra DigiTech",
                        "rows": [
                            {"id": "svc_social",   "title": "📱 Social Media",      "description": "Instagram, FB, YouTube ನಿರ್ವಹಣೆ"},
                            {"id": "svc_website",  "title": "🌐 Website / App",     "description": "ವೆಬ್‌ಸೈಟ್ & ಮೊಬೈಲ್ ಆ್ಯಪ್"},
                            {"id": "svc_election", "title": "🗳️ Election Campaign", "description": "MLA/MP ಚುನಾವಣಾ ಪ್ರಚಾರ"},
                            {"id": "svc_chatbot",  "title": "🤖 AI Chatbot",        "description": "WhatsApp bot & automation"},
                            {"id": "svc_ads",      "title": "📢 Digital Ads",       "description": "Google & Meta ಜಾಹೀರಾತು"},
                            {"id": "svc_govt",     "title": "🏛️ Govt Schemes",      "description": "ಸರ್ಕಾರಿ ಇಲಾಖೆ ಪ್ರಚಾರ"},
                            {"id": "svc_design",   "title": "🎨 Design & Branding", "description": "Logo, Poster, Brochure"},
                            {"id": "svc_other",    "title": "💬 ಬೇರೆ / Other",      "description": "ನಿಮ್ಮ ಪ್ರಶ್ನೆ ಟೈಪ್ ಮಾಡಿ"},
                        ],
                    }
                ],
            },
        },
    })
    # Fallback: plain text menu if list message fails
    if not r.ok:
        send_text(to,
            "ನಮ್ಮ ಸೇವೆಗಳು:\n"
            "1️⃣ Social Media ನಿರ್ವಹಣೆ\n"
            "2️⃣ Website / App\n"
            "3️⃣ Election Campaign 🗳️\n"
            "4️⃣ AI Chatbot 🤖\n"
            "5️⃣ Digital Ads\n"
            "6️⃣ Govt Schemes\n"
            "7️⃣ Design & Branding\n\n"
            "ಯಾವುದು ಬೇಕು ಹೇಳಿ 😊"
        )

SERVICE_MENU_REPLIES = {
    "svc_social": (
        "Social Media ನಿರ್ವಹಣೆ",
        "ಸೂಪರ್! 📱 Instagram, Facebook, YouTube, LinkedIn — ಎಲ್ಲಾ ನಾವು ನೋಡಿಕೊಳ್ಳುತ್ತೇವೆ.\n\n"
        "ನಿಮ್ಮದು ಯಾವ ರೀತಿಯ business / ಸಂಸ್ಥೆ? ಈಗ social media ಇದೆಯಾ?"
    ),
    "svc_website": (
        "Website / App",
        "ಒಳ್ಳೆ ಆಯ್ಕೆ! 🌐 Business website, E-commerce, Government portal, Mobile app — ಎಲ್ಲಾ ಮಾಡುತ್ತೇವೆ.\n\n"
        "ಯಾವ ರೀತಿಯ website/app ಬೇಕು? ಎಷ್ಟು ಪುಟ/features ಅಂದಾಜು?"
    ),
    "svc_election": (
        "Election Campaign",
        "ನಮಸ್ಕಾರ 🙏 ಚುನಾವಣಾ ಡಿಜಿಟಲ್ ಪ್ರಚಾರ ನಮ್ಮ ವಿಶೇಷತೆ — Karnataka ದಲ್ಲಿ ಹಲವು ನಾಯಕರ ಜೊತೆ ಕೆಲಸ ಮಾಡಿದ್ದೇವೆ.\n\n"
        "ಯಾವ ಕ್ಷೇತ್ರ? ಯಾವ ಚುನಾವಣೆಗೆ ತಯಾರಿ? MD ರವಿರಾಜ್ ಅವರು ನಿಮ್ಮನ್ನು ವೈಯಕ್ತಿಕವಾಗಿ ಸಂಪರ್ಕಿಸುತ್ತಾರೆ."
    ),
    "svc_chatbot": (
        "AI Chatbot",
        "ಒಳ್ಳೆ ಪ್ರಶ್ನೆ! 🤖 ಈಗ ನೀವು ಮಾತನಾಡುತ್ತಿರುವುದೇ ನಮ್ಮ AI chatbot — ಇದೇ ತರಹ ನಿಮ್ಮ business ಗೂ ಮಾಡಿಕೊಡುತ್ತೇವೆ!\n\n"
        "ನಿಮ್ಮ business ಯಾವುದು? ದಿನಕ್ಕೆ ಎಷ್ಟು customer messages ಬರುತ್ತವೆ?"
    ),
    "svc_ads": (
        "Digital Ads",
        "ಖಂಡಿತ! 📢 Google Ads, Facebook/Instagram Ads, YouTube Ads — ROI focus ನಲ್ಲಿ ನಡೆಸುತ್ತೇವೆ.\n\n"
        "ಯಾವ product/service ಗೆ ads ಬೇಕು? ತಿಂಗಳ ad budget ಅಂದಾಜು ಎಷ್ಟು?"
    ),
    "svc_govt": (
        "Govt Schemes",
        "ನಮಸ್ಕಾರ 🙏 ಸರ್ಕಾರಿ ಇಲಾಖೆ / ಯೋಜನೆಗಳ ಪ್ರಚಾರದಲ್ಲಿ ನಮಗೆ ವಿಶೇಷ ಅನುಭವ (KSDC, India Skills ಇತ್ಯಾದಿ).\n\n"
        "ಯಾವ ಇಲಾಖೆ / ಯೋಜನೆ? ವಿವರ ಹೇಳಿ, MD ರವಿರಾಜ್ ಅವರು ನೇರವಾಗಿ ಮಾತನಾಡುತ್ತಾರೆ."
    ),
    "svc_design": (
        "Design & Branding",
        "ಸೂಪರ್! 🎨 Logo, Brand identity, Poster, Brochure, Social media creatives — ಎಲ್ಲಾ ಮಾಡುತ್ತೇವೆ.\n\n"
        "ಏನು design ಬೇಕು? ನಿಮ್ಮ ಕಂಪನಿ/ಸಂಸ್ಥೆ ಹೆಸರು ಹೇಳಿ."
    ),
    "svc_other": (
        "Other",
        "ಖಂಡಿತ! 😊 ನಿಮ್ಮ ಪ್ರಶ್ನೆ / ಅವಶ್ಯಕತೆ ಟೈಪ್ ಮಾಡಿ — ಕನ್ನಡ, English, ಹಿಂದಿ ಯಾವುದರಲ್ಲಾದರೂ ಸರಿ."
    ),
}

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
        notify_owner(f"📋 Quotation request from wa.me/{to}")
    elif btn_id == "call":
        send_text(to,
            "📞 ನಮ್ಮ ತಂಡ ಮಾತನಾಡಲು ಸಿದ್ಧ!\n\n"
            "☎️ +91 88844 48141\n"
            "☎️ +91 94493 56707\n\n"
            "🕐 ಸೋಮ–ಶನಿ: ಬೆಳಿಗ್ಗೆ 9 – ರಾತ್ರಿ 7"
        )
        notify_owner(f"📞 Call requested by wa.me/{to} — expect a call!")
    elif btn_id == "meeting":
        send_text(to,
            "🤝 ಮೀಟಿಂಗ್ ಫಿಕ್ಸ್ ಮಾಡೋಣ!\n\n"
            "📍 ಆಫೀಸ್: ಜಯನಗರ, ಬೆಂಗಳೂರು\n"
            "🖥️ ವಿಡಿಯೋ ಕಾಲ್ ಸಹ ಆಗುತ್ತದೆ\n\n"
            "ನಿಮಗೆ ಯಾವ ದಿನ ಮತ್ತು ಸಮಯ ಅನುಕೂಲ? 📅"
        )
        save_message(to, "system", "MEETING_REQUESTED")
        notify_owner(f"🤝 Meeting requested by wa.me/{to} — check chat for their preferred time")
    else:
        # Unknown button — let AI handle
        reply = generate_reply(to, btn_title)
        send_text(to, reply)

def handle_list_reply(to: str, row_id: str, row_title: str):
    """Respond to welcome-menu service selection + capture as lead."""
    service, reply = SERVICE_MENU_REPLIES.get(row_id, SERVICE_MENU_REPLIES["svc_other"])
    save_message(to, "user", f"[ಆಯ್ಕೆ: {row_title}]")
    send_text(to, reply)
    save_message(to, "assistant", reply)
    if row_id != "svc_other":
        upsert_lead(to, {"service_needed": service})
    if row_id in ("svc_election", "svc_govt"):
        notify_owner(f"🗳️ HOT: wa.me/{to} selected *{service}* from the menu — follow up personally!")


# ══════════════════════════════════════════════════════════════════════════════
# OWNER COMMANDS  (#stop <phone> / #start <phone> — sent from OWNER_PHONE)
# ══════════════════════════════════════════════════════════════════════════════
def handle_owner_command(text: str) -> bool:
    """Returns True if the message was an owner command (and was handled)."""
    stripped = text.strip()
    if stripped.lower() in ("#help", "#commands"):
        send_text(OWNER_PHONE,
            "🤖 Bot commands:\n\n"
            "#stop 91XXXXXXXXXX — pause bot for that chat (24h)\n"
            "#start 91XXXXXXXXXX — resume bot for that chat"
        )
        return True
    m = re.match(r'^#(stop|start)\s+(\+?\d{10,15})\s*$', stripped, re.IGNORECASE)
    if not m:
        return False
    action = m.group(1).lower()
    target = m.group(2).lstrip("+")
    if action == "stop":
        save_message(target, "system", "BOT_PAUSED")
        send_text(OWNER_PHONE, f"⏸️ Bot paused for wa.me/{target} (auto-resumes in 24h)")
    else:
        save_message(target, "system", "BOT_RESUMED")
        send_text(OWNER_PHONE, f"▶️ Bot resumed for wa.me/{target}")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# LEAD / VIP ALERTS TO OWNER
# ══════════════════════════════════════════════════════════════════════════════
def maybe_alert_vip(sender: str, user_text: str):
    """Instant owner alert for VIP / election messages — once per chat per 24h."""
    vip      = is_vip_message(user_text)
    election = is_election_message(user_text)
    if not (vip or election):
        return
    ev = fetch_last_system_event(sender, "VIP_ALERTED")
    if ev and _within_hours(ev.get("created_at", ""), 24):
        return
    save_message(sender, "system", "VIP_ALERTED")
    tag = "👑 VIP" if vip else "🗳️ ELECTION"
    notify_owner(
        f"{tag} lead on WhatsApp bot!\n\n"
        f"From: wa.me/{sender}\n"
        f"Message: {user_text[:200]}\n\n"
        f"⚡ Call them personally ASAP."
    )

def maybe_alert_lead(sender: str, lead: dict):
    """Owner alert when meaningful lead info is captured — once per chat per 24h."""
    meaningful = any(lead.get(k) for k in ("service_needed", "budget", "company"))
    if not meaningful:
        return
    ev = fetch_last_system_event(sender, "LEAD_ALERTED")
    if ev and _within_hours(ev.get("created_at", ""), 24):
        return
    save_message(sender, "system", "LEAD_ALERTED")
    lines = ["🔥 New lead captured by bot!", "", f"From: wa.me/{sender}"]
    for label, key in (("Name", "name"), ("Company", "company"),
                       ("Service", "service_needed"), ("Budget", "budget"), ("City", "city")):
        if lead.get(key):
            lines.append(f"{label}: {lead[key]}")
    notify_owner("\n".join(lines))


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

            # ── Interactive replies (buttons + welcome-menu list) ─────────
            if msg_type == "interactive":
                iact = msg.get("interactive", {})
                if iact.get("type") == "button_reply":
                    btn = iact["button_reply"]
                    handle_button_reply(sender, btn["id"], btn["title"])
                elif iact.get("type") == "list_reply":
                    row = iact["list_reply"]
                    handle_list_reply(sender, row["id"], row.get("title", ""))
                self._ok(); return

            # ── Voice / Audio message ─────────────────────────────────────
            if msg_type == "audio":
                media_id    = msg["audio"]["id"]
                transcribed = transcribe_audio(media_id)
                if not transcribed:
                    send_text(sender,
                        "🎤 ಧ್ವನಿ ಸಂದೇಶ ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. "
                        "ದಯವಿಟ್ಟು ಟೈಪ್ ಮಾಡಿ 🙏"
                    )
                    self._ok(); return
                # Acknowledge voice with transcription
                send_text(sender, f'🎤 ನಿಮ್ಮ ಧ್ವನಿ ಸಂದೇಶ:\n"{transcribed}"')
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

            # ── Owner commands (#stop / #start) ───────────────────────────
            if sender == OWNER_PHONE and handle_owner_command(user_text):
                self._ok(); return

            # ── Meta retry deduplication ──────────────────────────────────
            if is_duplicate_webhook(sender, user_text):
                print("↩️ duplicate webhook — skipped")
                self._ok(); return

            # ── First-time contact? (check BEFORE saving this message) ────
            is_new_contact = not fetch_history(sender, 1)

            # Save user message to memory
            save_message(sender, "user", user_text)

            # ── VIP / election detection → instant owner alert ────────────
            maybe_alert_vip(sender, user_text)

            # ── Human handoff: owner paused this chat ─────────────────────
            if is_bot_paused(sender):
                print(f"⏸️ bot paused for {sender} — staying silent")
                self._ok(); return

            # ── Brochure request? ─────────────────────────────────────────
            if is_brochure_request(user_text):
                save_message(sender, "assistant", "[ಬ್ರೋಚರ್ PDF ಕಳಿಸಲಾಯಿತು]")
                send_text(sender,
                    "ಖಂಡಿತ! ನಮ್ಮ ಕಂಪನಿ ಪ್ರೊಫೈಲ್ ಇಲ್ಲಿದೆ 🙏"
                )
                send_brochure(sender)
                time.sleep(1)
                send_followup_buttons(sender)
                notify_owner(f"📄 Brochure sent to wa.me/{sender}")

            # ── New contact: greet with services menu ─────────────────────
            elif is_new_contact:
                send_welcome_menu(sender)
                save_message(sender, "assistant", "[ಸ್ವಾಗತ + ಸೇವೆಗಳ ಮೆನು ಕಳಿಸಲಾಯಿತು]")

            # ── Normal AI reply ───────────────────────────────────────────
            else:
                reply = generate_reply(sender, user_text)
                print(f"🤖 {reply[:80]}")
                send_text(sender, reply + after_hours_note())
                save_message(sender, "assistant", reply)

                # Extract & save lead info every few turns
                history = fetch_history(sender, 8)
                if len(history) >= 4:
                    lead = extract_lead_info(history)
                    if lead:
                        upsert_lead(sender, lead)
                        maybe_alert_lead(sender, lead)

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
