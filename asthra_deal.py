"""An Asthra customer is chatted with until the deal is done.

Owner's goal, 2026-11-02: "asthra digitech gu customer message haktidare same
number ge avara deal finish aagovare chat madbeku". The deal is done when the
ADVANCE PAYMENT arrives; until then a quiet customer is followed up for 17
days. The owner's prices and rules for the AI prompt live in
webhook.SYSTEM_PROMPT; this module owns the rest:

    the varadi   the AI ends its reply with QUOTE_MARKER + a one-line summary
                 when it has the requirements for a service with no listed
                 price. The customer never sees it; the owner gets the summary.
    #price       the owner's price for that customer, sent to them.
    #advance     the owner says the advance came: the deal is done and the
                 follow-ups stop.
    follow-ups   days 1, 2, 4, 7, 10, 14 and 17 after the customer's last
                 message, daytime only, stopped by a reply, a "beda", a #stop
                 pause or #advance.

NO NEW TABLES. Everything is a row in whatsapp_messages, the same no-new-
storage rule nudge.py follows, so "was this customer already followed up on
day 4" is answered by the history the bot already reads.

Pure module: no network and no clock of its own. api/webhook.py and
api/nudge.py do the reads and sends.
"""
import re
from datetime import datetime, timedelta, timezone

import bairavi

IST = timezone(timedelta(hours=5, minutes=30))

# ── The varadi (requirement summary for the owner) ──────────────────────────
QUOTE_MARKER = "[[QUOTE_READY]]"
QUOTE_REQUESTED = "ASTHRA_QUOTE_REQUESTED"
PRICE_SENT = "ASTHRA_PRICE_SENT"
ADVANCE_PAID = "ASTHRA_ADVANCE_PAID"
# A follow-up is an assistant row (the customer saw it), marked so the next
# sweep can tell which day it was.
FOLLOWUP_MARKER = "[Asthra follow-up]"


def split_quote_marker(reply: str):
    """(text for the customer, summary for the owner or None).

    Everything from the marker on is the owner's. A marker with nothing after
    it still counts — the owner then reads the chat himself."""
    text = reply or ""
    i = text.find(QUOTE_MARKER)
    if i < 0:
        return text, None
    summary = " ".join(text[i + len(QUOTE_MARKER):].split())
    return text[:i].rstrip(), summary or "—"


def quote_report(phone: str, summary: str) -> str:
    """The owner's WhatsApp alert: who, what they need, and the reply to send."""
    digits = phone[-4:]
    parts = [p.strip() for p in summary.split("|") if p.strip()]
    lines = [f"📋 Hosa requirement — quotation beku", f"wa.me/{phone}"]
    lines += parts or [summary]
    lines += ["", f"👉 Bele heLi: #price {digits} <amount> <note>",
              f"   ex: #price {digits} 75000 tingaLige"]
    return "\n".join(lines)


# ── #price / #advance ──────────────────────────────────────────────────────
_PRICE_RE = re.compile(r"^#price\s+\+?(\d{4,15})\s+(?:₹|rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(k|l|lakh|lac)?\b\s*(.*)$",
                       re.IGNORECASE | re.DOTALL)
_ADVANCE_RE = re.compile(r"^#advance\s+\+?(\d{4,15})\s*$", re.IGNORECASE)


def parse_price(text: str):
    """(digits, rupees, note) for '#price 4521 75000 tingaLige', else None."""
    m = _PRICE_RE.match((text or "").strip())
    if not m:
        return None
    amount = float(m.group(2).replace(",", ""))
    unit = (m.group(3) or "").lower()
    amount *= 1000 if unit == "k" else 100000 if unit in ("l", "lakh", "lac") else 1
    if amount <= 0:
        return None
    return m.group(1), int(round(amount)), " ".join(m.group(4).split())


def parse_advance(text: str):
    """The digits for '#advance 4521', else None."""
    m = _ADVANCE_RE.match((text or "").strip())
    return m.group(1) if m else None


def rupees(n: int) -> str:
    """₹ in Indian grouping: 75000 -> ₹75,000, 150000 -> ₹1,50,000."""
    s = str(int(n))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail]) if groups else "₹" + tail


def price_message(amount: int, note: str = "") -> str:
    """The owner's price as the customer reads it. Never mentions GST (owner,
    2026-11-02: "gst vishaya matadbeda")."""
    figure = rupees(amount) + (f" ({note})" if note else "")
    return ("ನಮಸ್ಕಾರ 🙏 ನಿಮ್ಮ requirement ಪ್ರಕಾರ ನಮ್ಮ quotation:\n"
            f"*{figure}*\n\n"
            "ಒಪ್ಪಿಗೆ ಇದ್ದರೆ ತಿಳಿಸಿ — advance payment ಬಂದ ತಕ್ಷಣ ಕೆಲಸ ಶುರು ಮಾಡುತ್ತೇವೆ. "
            "ಏನಾದರೂ ಬದಲಾವಣೆ ಬೇಕಿದ್ದರೆ ಇಲ್ಲೇ ಹೇಳಿ 🙏")


def owner_price_receipt(phone: str, amount: int, delivered: bool, window_open: bool) -> str:
    if delivered:
        return (f"✅ {rupees(amount)} quotation wa.me/{phone} ge kaLiside. "
                f"Advance bandaaga: #advance {phone[-4:]}")
    if not window_open:
        return (f"⚠️ wa.me/{phone} kone message 24 gante hinde — WhatsApp namballa, "
                "quotation hogilla. Dayavittu call maadi / neeve message maadi.")
    return f"⚠️ wa.me/{phone} ge quotation hogilla (WhatsApp reject). Call maadi."


def advance_receipt(phone: str) -> str:
    return (f"🎉 wa.me/{phone} deal mugiyitu — advance bandide. "
            "Follow-up nillisalaagide.")


# ── Follow-ups ─────────────────────────────────────────────────────────────
FOLLOWUP_DAYS = (1, 2, 4, 7, 10, 14, 17)
# Day 1 goes at 20 h, still inside WhatsApp's 24-hour window, so it is a plain
# message. Every later day needs the approved template.
DAY1_AFTER = timedelta(hours=20)
WINDOW = timedelta(hours=22)
DAY_START_IST, DAY_END_IST = 9, 21

SEND = "SEND"
DEAL_DONE = "DEAL_DONE"
CHAT_PAUSED = "CHAT_PAUSED"
DECLINED = "DECLINED"
NOT_DUE = "NOT_DUE"
FINISHED = "FINISHED"
OUTSIDE_DAYTIME = "OUTSIDE_DAYTIME"
BAIRAVI = "BAIRAVI"
NO_CUSTOMER_MESSAGE = "NO_CUSTOMER_MESSAGE"

# The rows that make a chat an Asthra DEAL worth following: a lead the bot
# alerted the owner about, a quotation asked for, a price sent.
DEAL_SIGNS = ("LEAD_ALERTED", QUOTE_REQUESTED, PRICE_SENT)


def _ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def followup_day(content: str):
    m = re.search(re.escape(FOLLOWUP_MARKER) + r" day=(\d+)", content or "")
    return int(m.group(1)) if m else None


def due_day(elapsed: timedelta):
    """The latest follow-up day reached after `elapsed` of silence, or None."""
    reached = None
    for day in FOLLOWUP_DAYS:
        at = DAY1_AFTER if day == 1 else timedelta(days=day)
        if elapsed >= at:
            reached = day
    return reached


def decide(rows: list, now: datetime):
    """(verdict, day) for one conversation. `rows` newest first, each with
    role / content / created_at. Only chats carrying one of DEAL_SIGNS are
    passed in (the sweep's query picks them), so a long chat whose sign has
    scrolled out of the window is still a deal.

    Order matters: the facts that end the deal for good come first, so a log
    line names the real reason."""
    contents = [(r.get("role"), r.get("content") or "") for r in rows]
    if any(role == "system" and c == ADVANCE_PAID for role, c in contents):
        return DEAL_DONE, None
    if any((role == "assistant" and bairavi.FLOW_MARKER in c)
           or (role == "system" and c.startswith("META_LEAD::")) for role, c in contents):
        return BAIRAVI, None
    for row in rows:
        c = row.get("content") or ""
        if row.get("role") == "system" and c.startswith("BOT_"):
            ts = _ts(row.get("created_at"))
            if c == "BOT_PAUSED" and ts and now - ts < timedelta(hours=24):
                return CHAT_PAUSED, None
            break

    last_user = next((r for r in rows if r.get("role") == "user"), None)
    if not last_user:
        return NO_CUSTOMER_MESSAGE, None
    if bairavi.is_decline(last_user.get("content") or ""):
        return DECLINED, None
    since = _ts(last_user.get("created_at"))
    if since is None:
        return NOT_DUE, None

    sent = 0
    for row in rows:
        if row is last_user:
            break
        if row.get("role") == "assistant":
            sent = max(sent, followup_day(row.get("content")) or 0)
    if sent >= FOLLOWUP_DAYS[-1]:
        return FINISHED, None
    day = due_day(now - since)
    if day is None or day <= sent:
        return NOT_DUE, None
    hour = now.astimezone(IST).hour
    if not DAY_START_IST <= hour < DAY_END_IST:
        return OUTSIDE_DAYTIME, None
    return SEND, day


def window_open(rows: list, now: datetime) -> bool:
    """True while a plain WhatsApp message can still reach this customer."""
    last_user = next((r for r in rows if r.get("role") == "user"), None)
    ts = _ts((last_user or {}).get("created_at"))
    return bool(ts and now - ts < WINDOW)


def followup_text(day: int) -> str:
    """The day-1 message (inside the 24-hour window)."""
    return ("ನಮಸ್ಕಾರ 🙏 Asthra DigiTech ಇಂದ — ನಿನ್ನೆ ನೀವು ಕೇಳಿದ ವಿಷಯದ ಬಗ್ಗೆ ಏನಾದರೂ "
            "ಪ್ರಶ್ನೆ ಇದ್ದರೆ ಇಲ್ಲೇ ಕೇಳಿ. ಮುಂದುವರಿಸಲು ಸಿದ್ಧರಿದ್ದರೆ ತಿಳಿಸಿ, ನಾವು ತಕ್ಷಣ ಶುರು ಮಾಡುತ್ತೇವೆ.")


# The template for days 2-17. Created once in the WhatsApp account (see
# api/nudge.py); until Meta approves it those days are skipped, not sent free.
TEMPLATE_NAME = "asthra_deal_followup"
TEMPLATE_LANGUAGE = "kn"
TEMPLATE_CATEGORY = "MARKETING"
TEMPLATE_BODY = (
    "ನಮಸ್ಕಾರ 🙏 *Asthra DigiTech* ಇಂದ.\n"
    "ನೀವು ಕೇಳಿದ ಸೇವೆಯ ಬಗ್ಗೆ ಇನ್ನೂ ಆಸಕ್ತಿ ಇದೆಯಾ? ಏನಾದರೂ ಪ್ರಶ್ನೆ ಇದ್ದರೆ ಈ ಸಂದೇಶಕ್ಕೆ "
    "ಉತ್ತರಿಸಿ — ನಾವು ತಕ್ಷಣ ಸಹಾಯ ಮಾಡುತ್ತೇವೆ."
)
TEMPLATE_FOOTER = "ಬೇಡವಾದರೆ STOP ಎಂದು ಉತ್ತರಿಸಿ"


def marker(day: int) -> str:
    return f"{FOLLOWUP_MARKER} day={day}"


def summarise(counts: dict) -> str:
    parts = [f"{k.lower()}={v}" for k, v in sorted(counts.items()) if v]
    return "ASTHRA_FOLLOWUP_RUN " + (" ".join(parts) or "considered=0")
