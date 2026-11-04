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

import kannada_understanding as ku
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


# ── What the customer already told us (owner 2026-11-04, "sari madu") ───────
# A 45-message chat (…3602, SM Events, 2026-11-04) outgrew the ten turns the
# reply prompt sees: the bot called an events business "photography" twice,
# asked for the page it had been told was new, and asked for the name and the
# business a third time right after "Kk I will pay". The customer's own
# messages are short, so all of them (last CUSTOMER_SAID_DAYS) ride along as a
# block the model is told never to re-ask from or contradict.
CUSTOMER_SAID_DAYS = 30
CUSTOMER_SAID_ROWS = 120
CUSTOMER_SAID_CHARS = 4000
_BARE_ACK = re.compile(r"^(ok+|k+|kk+|ss+|s|sari|haa+|ha|hm+|yes|yep|no|thanks?|thank you|"
                       r"ಸರಿ|ಹೌದು|ಓಕೆ|👍|🙏)[\s.!🙏👍]*$", re.IGNORECASE)


def customer_said_block(messages: list) -> str:
    """The customer's own messages, oldest first, as one prompt block. Bare
    acknowledgements ("Kk", "Ss") say nothing on their own and are dropped.
    Over the size cap the OLDEST go first, but the first message (the ad form,
    which carries the name and the budget) always stays."""
    said = [" ".join((m or "").split())[:300] for m in messages]
    said = [s for s in said if s and not _BARE_ACK.match(s)]
    if not said:
        return ""
    head, rest = said[0], said[1:]
    while rest and len(head) + sum(len(s) + 3 for s in rest) > CUSTOMER_SAID_CHARS:
        rest.pop(0)
    lines = "\n".join(f"• {s}" for s in [head] + rest)
    return ("WHAT THIS CUSTOMER HAS ALREADY TOLD US in this chat (their own words, oldest first):\n"
            f"{lines}\n"
            "RULES: never ask again for anything answered above (name, business, area, page, "
            "services, budget, timeline). Describe their business ONLY with the words above — "
            "never call it something they did not say. If a service was already offered and "
            "discussed, do not offer it again as if new.")


# ── "I will pay" ───────────────────────────────────────────────────────────
# The same chat ended "Kk I will pay" and nobody was told: the bot promised
# "our team will send payment details" and asked for the name again. A
# customer agreeing to pay is the deal goal itself, so the owner hears at once
# and the bot stops asking questions.
PAY_INTENT = "ASTHRA_PAY_INTENT"
_PAY, _NOT_PAYING, said_will_pay = ku.PAY_RE, ku.NOT_PAYING, ku.said_will_pay


PAY_AGREED_NOTE = (
    "PAYMENT AGREED: the customer has just said they will pay. In this reply ask NO question. "
    "Thank them in one short line and say our team will send the payment details on this same "
    "WhatsApp shortly. Never write bank, UPI or account details yourself and never name an "
    "amount that was not already agreed in the chat.")
PAY_PENDING_NOTE = (
    "PAYMENT PENDING: this customer already said they will pay and the team is sending the "
    "payment details. Answer what they ask; do not ask for details they already gave and do "
    "not push for the payment again.")


def pay_intent_report(phone: str, said: str, last_offer: str = "") -> str:
    """The owner's alert: who, their words, the last price the bot named."""
    lines = ["🔥 Customer PAY maaDuttEne anta heLiddaare — payment details kaLisi",
             f"wa.me/{phone}", f"Customer: \"{' '.join((said or '').split())[:200]}\""]
    if last_offer:
        lines.append(f"Bot heLida bele: {' '.join(last_offer.split())[:300]}")
    lines += ["", f"👉 Advance bandaaga: #advance {phone[-4:]}"]
    return "\n".join(lines)


def last_offer(history: list) -> str:
    """The newest bot line that names a ₹ amount, or ''."""
    for turn in reversed(history or []):
        if turn.get("role") != "assistant":
            continue
        for line in reversed((turn.get("content") or "").splitlines()):
            if "₹" in line:
                return line.strip()
    return ""


# ── What our team sent from the CRM (owner 2026-11-04, "eradannu sari madu") ──
# Messages a person sends from the CRM inbox (quotation PDFs, payment details)
# go out through the CRM and never reach this chat's history, so the bot kept
# promising "we will send the quotation" after it had been sent. The CRM marks
# its own sends with metadata.action; the bot's mirrored replies carry
# metadata.source instead and are already in the history.
TEAM_SENT_DAYS = 30
TEAM_SENT_ROWS = 15
TEAM_ACTIONS = ("text", "media", "template")


def _team_line(row: dict) -> str:
    meta = row.get("metadata") or {}
    ts = _ts(row.get("created_at"))
    when = ts.astimezone(IST).strftime("%d %b %I:%M %p") if ts else "—"
    if row.get("message_type") == "media":
        kind = meta.get("original_type") or "file"
        what = f"{kind}: {meta.get('file_name') or row.get('body') or '—'}"
    elif row.get("message_type") == "template":
        what = "template message: " + " ".join((row.get("body") or "").split())[:200]
    else:
        what = " ".join((row.get("body") or "").split())[:300]
    return f"• {when} — {what}"


def team_sent_block(rows: list) -> str:
    """The team's own messages to this customer, oldest first, as one prompt
    block. Only the file NAME of a document is known, never its contents."""
    rows = [r for r in rows or [] if (r.get("metadata") or {}).get("action") in TEAM_ACTIONS]
    if not rows:
        return ""
    lines = "\n".join(_team_line(r) for r in rows)
    return ("WHAT OUR TEAM (a person, from the office) ALREADY SENT THIS CUSTOMER, oldest first (IST):\n"
            f"{lines}\n"
            "RULES: these really were sent. Never promise to send something already listed here "
            "(say it was sent and ask if they saw it). You know only a file's NAME, not what is in "
            "it — never quote amounts or terms from a document; for its details say our team will "
            "explain.")


# ── The owner's Bot Knowledge (CRM page, owner 2026-11-04 "1,2,3 maadu") ─────
# Prices, packages and service facts the owner edits without a deploy. The
# block follows the static prompt and is told to win where they differ, so a
# price the owner changes in the CRM is the price the bot says.
KNOWLEDGE_CHARS = 6000


def knowledge_block(rows: list) -> str:
    rows = [r for r in rows or [] if (r.get("topic") or "").strip() and (r.get("body") or "").strip()]
    if not rows:
        return ""
    text = "\n".join(f"• {r['topic'].strip()}: {' '.join(r['body'].split())}" for r in rows)[:KNOWLEDGE_CHARS]
    return ("OWNER'S LATEST KNOWLEDGE (the owner edits this in the CRM). Where it differs from anything "
            "above — a price, a package, a fact — THIS wins. Never mention GST, and never name a price "
            "that is not here or above.\n" + text)


# ── REPLY GUARD (owner 2026-11-05: "astra tappu sari maadu, bot tulu matadalla") ──────────────
# The 2026-11-05 debate: the model priced a zilla-panchayat campaign and promised "1,000–5,000
# followers", and twice said the AI bot speaks Tulu. The prompt already forbade the first two;
# the model did it anyway. So the reply is checked here, after the model, before anyone sees it.
# Words only an election customer uses. Not "ಪ್ರಚಾರ" / "campaign" (a shop's ad campaign) and not
# "party" (party halls, event companies).
_POLITICS_RE = re.compile(r"election|elction|candidate|chunav|ಚುನಾವಣ|ಎಲೆಕ್ಷನ್|ಅಭ್ಯರ್ಥಿ|ರಾಜಕೀಯ|politic|"
                          r"\bmla\b|\bmlc\b|panchayat|ಪಂಚಾಯ|corporator|ಕಾರ್ಪೊರೇಟರ್|ward member|ವಾರ್ಡ್ ಸದಸ್ಯ", re.I)
_RUPEE_RE = re.compile(r"₹\s*\d|\brs\.?\s*\d|\d\s*(?:rupees?|lakhs?|ಲಕ್ಷ)", re.I)
_NEGATED_RE = re.compile(r"ಇಲ್ಲ|ಆಗಲ್ಲ|ಸಾಧ್ಯವಿಲ್ಲ|ಹೇಳಲು ಆಗ|ಮಾಡಲ್ಲ|ಕೊಡಲ್ಲ|\bnot\b|\bno\b|can'?t|cannot|never|"
                         r"illa|aagalla|guarantee\s*(?:illa|ಇಲ್ಲ)|ಖಾತರಿ", re.I)
_RESULT_RE = re.compile(r"\d[\d,]*\s*(?:[–\-~]|to|ರಿಂದ)?\s*[\d,]*\s*\+?\s*(?:ಹೊಸ\s*)?(?:followers?|ಫಾಲೋವರ್|"
                        r"leads?|ಲೀಡ್|views?|ವ್ಯೂ|likes?|ಲೈಕ್|enquir|ಎನ್ಕ್ವೈರಿ|sales|ಮಾರಾಟ)", re.I)
_TULU_RE = re.compile(r"tulu|ತುಳು", re.I)

POLITICS_REPLY = ("ಸರಿ sir 🙏 ಚುನಾವಣಾ ಪ್ರಚಾರಕ್ಕೆ ಪೇಜ್ ಸೆಟಪ್, posts/reels, Facebook–Instagram ads, WhatsApp "
                  "ಪ್ರಚಾರ — ಎಲ್ಲಾ ಮಾಡ್ತೀವಿ. ನಿಮ್ಮ ಕ್ಷೇತ್ರ, ಅವಧಿ ಮತ್ತು ಬಜೆಟ್ ನೋಡಿ ಅಧಿಕೃತ quotation ಕಳಿಸ್ತೀವಿ; "
                  "ರವಿರಾಜ್ ಅವರು ನಿಮ್ಮ ಜೊತೆ ಮಾತಾಡ್ತಾರೆ.")
RESULT_LINE = "ಎಷ್ಟು followers/leads ಬರುತ್ತೆ ಅಂತ ಮುಂಚೆಯೇ promise ಮಾಡಲ್ಲ sir — ಫಲಿತಾಂಶ ad ಮತ್ತು content ಮೇಲೆ ಹೋಗುತ್ತೆ."
TULU_LINE = "ನಮ್ಮ AI bot ಕನ್ನಡ ಮತ್ತು English ನಲ್ಲಿ ಮಾತಾಡುತ್ತೆ — ತುಳು ಸದ್ಯ ಇಲ್ಲ."


def guard_reply(reply: str, customer_texts=()) -> tuple:
    """(reply to send, reasons) — the model's Asthra reply with what it may never say removed.

    * a political campaign gets no rupee figure: the whole reply becomes POLITICS_REPLY
      (the owner's rule: political work is quoted officially, never priced in chat);
    * a line promising a number of followers / leads / sales goes, replaced once by RESULT_LINE
      (a line that says such numbers CANNOT be promised stays);
    * a line saying the bot speaks Tulu becomes TULU_LINE (owner 2026-11-05: it does not).
    """
    reasons = []
    text = reply or ""
    said = " ".join(t or "" for t in customer_texts)
    if _POLITICS_RE.search(said) and _RUPEE_RE.search(text):
        return POLITICS_REPLY, ["political price"]
    out, result_dropped = [], False
    for line in text.split("\n"):
        if _TULU_RE.search(line) and not _NEGATED_RE.search(line):
            reasons.append("tulu claim")
            if TULU_LINE not in out:
                out.append(TULU_LINE)
            continue
        if _RESULT_RE.search(line) and not _NEGATED_RE.search(line):
            reasons.append("result promise")
            if not result_dropped:
                out.append(RESULT_LINE)
                result_dropped = True
            continue
        out.append(line)
    return "\n".join(out).strip(), reasons

