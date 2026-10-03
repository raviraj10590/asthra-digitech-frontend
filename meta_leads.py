"""Meta form leads who never messaged on WhatsApp (owner request 2026-10-03).

THE LEAK
--------
Meta's 7-day report (2026-10-03): 92 instant-form leads, 43 of whom also sent
the WhatsApp message the ad leads them to. The other 49 filled the form —
name, phone, kVA, place, urgency — and stopped. The bot only meets people
who message it, so they reached nobody: not the bot, not the CRM, not the
owner's call list.

WHAT THIS DOES (with api/meta_leads_sync.py, which owns the I/O)
--------------------------------------------------------------
For each form lead from the last day, after giving them time to message on
their own: if this phone has never written to us and was not already
contacted, put the lead in the CRM and (mode "send") open the conversation
with ONE approved WhatsApp template. When they reply, the ordinary Bairavi
flow takes over — it already holds their form answers, written to the
transcript exactly as a WhatsApp form handoff would have been.

WHAT IT NEVER DOES
------------------
Message anyone twice (a lead is claimed in the transcript BEFORE any side
effect), message anyone who already wrote to us, message owner or staff, or
send free text — a business-initiated message outside the 24-hour window is
template-only, and that is the only thing sent.

Pure: no network, no clock unless one is passed.
"""
import re
from datetime import datetime, timedelta, timezone

import bairavi

# ── The template (one source: its creation request and the CRM mirror) ─────
TEMPLATE_NAME = "bairavi_lead_followup"
TEMPLATE_LANGUAGE = "kn"
TEMPLATE_CATEGORY = "MARKETING"
TEMPLATE_BODY = (
    "ನಮಸ್ಕಾರ {{1}} ಅವರೇ 🙏\n"
    "*Bairavi Trans Solutions* (Kadaba) ಜಾಹೀರಾತಿನಲ್ಲಿ ನೀವು *{{2}}* transformer ಬಗ್ಗೆ "
    "ವಿಚಾರಣೆ ಕಳುಹಿಸಿದ್ದೀರಿ — ಧನ್ಯವಾದಗಳು.\n"
    "ದರ ಮತ್ತು ವಿವರಗಳಿಗೆ ಈ ಸಂದೇಶಕ್ಕೆ ಉತ್ತರಿಸಿ, ಅಥವಾ ನಮ್ಮ engineer ಕರೆ ಮಾಡಲು "
    "ಅನುಕೂಲವಾದ ಸಮಯ ತಿಳಿಸಿ."
)
TEMPLATE_FOOTER = "ಬೇಡವಾದರೆ STOP ಎಂದು ಉತ್ತರಿಸಿ"
TEMPLATE_EXAMPLES = ("Ravi", "63 kVA")
NAME_FALLBACK = "ಗ್ರಾಹಕ"          # "customer"
CAPACITY_FALLBACK = "ನಿಮ್ಮ"       # "your" -> "about your transformer"

# ── Timing ──────────────────────────────────────────────────────────────────
# The ad's own flow sends them to WhatsApp right after the form; most who do
# so, do it within a minute. Twenty minutes is a generous chance to arrive by
# themselves before we write first.
WAIT_MINUTES = 20
# Older than a day, a first message from us reads as cold outreach.
MAX_AGE_HOURS = 24
# A bound per run, so one sweep cannot send a burst.
MAX_PER_RUN = 10

MARK = "META_LEAD::"

# Decisions for one lead.
CONTACT = "CONTACT"
SKIP_TOO_NEW = "SKIP_TOO_NEW"
SKIP_TOO_OLD = "SKIP_TOO_OLD"
SKIP_NO_PHONE = "SKIP_NO_PHONE"
SKIP_ALREADY_WROTE = "SKIP_ALREADY_WROTE"
SKIP_ALREADY_HANDLED = "SKIP_ALREADY_HANDLED"
SKIP_INTERNAL = "SKIP_INTERNAL"

_FORM_INTRO = ("[Meta form] Hello! I filled out your form and would like to "
               "know more about your business.")
_STANDARD_LABELS = {"full_name": "Full name", "phone_number": "Phone number",
                    "city": "City", "email": "Email"}


def normalize_phone(raw) -> str:
    """'+91 94486 50033' / '9448650033' -> '919448650033'; None if not an
    Indian mobile we can message."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "91" + digits
    return None


def _value(field) -> str:
    vals = field.get("values") or []
    return ", ".join(str(v) for v in vals if str(v).strip())


def field(lead: dict, name: str) -> str:
    for f in lead.get("field_data") or []:
        if f.get("name") == name:
            return _value(f)
    return ""


def form_text(lead: dict) -> str:
    """The lead as a WhatsApp form handoff — the shape bairavi.parse already
    reads. Labels come from Meta's field names (custom questions arrive as the
    question text with underscores); values are the customer's own answers.
    The "[Meta form]" prefix keeps its origin visible to anyone reading the
    transcript."""
    lines = []
    for f in lead.get("field_data") or []:
        name = str(f.get("name") or "")
        label = _STANDARD_LABELS.get(name) or name.replace("_", " ").strip()
        value = _value(f).replace("_", " ")
        if label and value:
            lines.append(f"{label}: {value}")
    return _FORM_INTRO + "\n\n" + "\n".join(lines)


def template_params(parsed: dict) -> tuple:
    """({{1}}, {{2}}) for the template, never empty."""
    name = bairavi.display_name(parsed.get("name")) or NAME_FALLBACK
    kva = parsed.get("capacity_kva")
    return name[:40], (f"{kva} kVA" if kva else CAPACITY_FALLBACK)


def rendered(params) -> str:
    """The template as the customer reads it — for the CRM and transcript."""
    text = TEMPLATE_BODY
    for i, p in enumerate(params, start=1):
        text = text.replace("{{%d}}" % i, p)
    return text + "\n_" + TEMPLATE_FOOTER + "_"


def _ts(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def decide(lead: dict, now: datetime, *, wrote_before: bool, handled: bool,
           internal: bool) -> str:
    """What to do with one lead. Order matters: the cheap, certain reasons
    first, and the ones that need a lookup only for leads still in play."""
    created = _ts(lead.get("created_time"))
    if created is None or now - created > timedelta(hours=MAX_AGE_HOURS):
        return SKIP_TOO_OLD
    if now - created < timedelta(minutes=WAIT_MINUTES):
        return SKIP_TOO_NEW
    if not normalize_phone(field(lead, "phone_number")):
        return SKIP_NO_PHONE
    if internal:
        return SKIP_INTERNAL
    if handled:
        return SKIP_ALREADY_HANDLED
    if wrote_before:
        return SKIP_ALREADY_WROTE
    return CONTACT


def marker(lead_id: str, result: str) -> str:
    return f"{MARK}{lead_id}::{result}"


def since(now: datetime, hours: int = MAX_AGE_HOURS) -> int:
    """Unix seconds for Meta's time_created filter."""
    return int((now - timedelta(hours=hours)).astimezone(timezone.utc).timestamp())


def owner_summary(contacted: list) -> str:
    """One alert per run. `contacted` is [(name, phone, kva, sent_ok)]."""
    lines = [f"📋 *Meta form leads who never messaged — {len(contacted)} contacted*"]
    for name, phone, kva, ok in contacted:
        lines.append(f"• {name or '—'} · {kva or '?'} · wa.me/{phone}"
                     + ("" if ok else " ⚠️ template NOT delivered — call them"))
    lines.append("They are in the CRM (Calls page). Their replies come to the bot as usual.")
    return "\n".join(lines)
