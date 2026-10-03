"""The owner's CRM on WhatsApp — phase 1, read-only (owner request 2026-10-04:
"hanta ondu maadu").

    #today      the morning view: follow-ups due, chats waiting, new leads
    #followups  follow-ups due today and overdue
    #chats      conversations where the customer wrote last and nobody replied
    #pipeline   how many leads in each stage
    #week       the last 7 days in numbers
    #due        unpaid invoices (OWNER only — money)

Read-only: nothing here writes to the CRM. Every number is read straight from
the CRM on each call (no AI, no cache). Owner rule (2026-10-04): the Brain does
NOT read the NaraRouter tables (nara_insights / nara_lead_profiles), so there
is no AI heat or district here.

Pure module: no network, no clock unless passed. api/webhook.py does the reads.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

import bairavi
import brain_health

IST = timezone(timedelta(hours=5, minutes=30))
LIST_MAX = 8                     # one readable WhatsApp message
WAIT_MIN = timedelta(minutes=10)
WAIT_MAX = timedelta(days=7)
# The CRM often stores the bot's reply 0-2 s BEFORE the message it answers,
# so "the customer wrote last" must allow a reply stamped a little earlier.
REPLY_TOLERANCE = timedelta(seconds=5)
BOT_CHECK = "🤖"

VIEWS = {
    "#today": "today", "#followups": "followups", "#followup": "followups", "#fu": "followups",
    "#chats": "chats", "#chat": "chats", "#pipeline": "pipeline", "#week": "week",
}
MONEY = ("#due", "#dues", "#unpaid")

STAGE_ORDER = ("Lead", "Contacted", "Interested", "Site Visit", "Negotiation", "Won", "Lost")


def command(low: str):
    """'today' / 'followups' / ... / 'due' for an owner command, else None."""
    word = (low or "").strip().split(" ")[0]
    if word in MONEY:
        return "due"
    return VIEWS.get(word)


def _ts(value):
    """A CRM timestamp ('2026-09-29 12:33:12.51124+00', 5-digit fractions and
    '+00' included — Python 3.9 cannot read those) or a plain date."""
    if value and len(str(value)) == 10:
        return datetime.fromisoformat(str(value)).replace(tzinfo=IST)
    return brain_health._ts(value)


def _when(value) -> str:
    t = _ts(value)
    if not t:
        return "?"
    t = t.astimezone(IST)
    return f"{t.day} {t.strftime('%b')} {t.strftime('%I:%M %p').lstrip('0').lower()}"


def _line(text, limit=50) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def money(n) -> str:
    n = int(round(float(n or 0)))
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


# ── pieces ──────────────────────────────────────────────────────────────────

def due_followups(rows: list, today: str) -> list:
    """Open follow-ups due today or earlier, oldest first."""
    return sorted((r for r in rows if not r.get("is_done") and (r.get("due_date") or "9999") <= today),
                  key=lambda r: r.get("due_date") or "")


def waiting_chats(convos: list, now: datetime, staff_phones=(), last_reply=None) -> list:
    """Conversations whose last message is the customer's, owed a reply,
    10 minutes to 7 days old — newest first. `last_reply`: phone (last 10
    digits) -> newest outbound time; a reply within REPLY_TOLERANCE before the
    customer's message counts as answered."""
    staff = {p[-10:] for p in staff_phones if p}
    last_reply = last_reply or {}
    out = []
    for c in convos:
        if c.get("last_direction") != "inbound" or (c.get("phone") or "")[-10:] in staff:
            continue
        body = (c.get("last_body") or "").strip()
        f = bairavi.parse_followup(body, (), known={}) if body else {}
        if not body or f.get("is_ack") or f.get("declined") or bairavi.is_decline(body):
            continue
        t = _ts(c.get("last_created_at"))
        replied = last_reply.get((c.get("phone") or "")[-10:])
        if replied and t and replied >= t - REPLY_TOLERANCE:
            continue
        if t and WAIT_MIN <= now - t <= WAIT_MAX:
            out.append(c)
    return sorted(out, key=lambda c: c.get("last_created_at") or "", reverse=True)


def _name(c: dict, clients_by_key: dict) -> str:
    key = (c.get("phone") or "")[-10:]
    return clients_by_key.get(key) or c.get("contact_name") or c.get("phone") or "—"


# ── messages ────────────────────────────────────────────────────────────────

def followups_text(rows: list, clients_by_id: dict, today: str) -> str:
    every = due_followups(rows, today)
    due = [r for r in every if not (r.get("note") or "").startswith(BOT_CHECK)]
    checks = len(every) - len(due)
    if not every:
        return "✅ *Follow-ups:* nothing due today or overdue."
    over = sum(1 for r in due if r.get("due_date") < today)
    lines = [f"📋 *Follow-ups due* — {len(due)}" + (f" ({over} overdue)" if over else "")
             + (f" · plus {checks} 🤖 bot check{'s' if checks != 1 else ''} in the CRM" if checks else "")]
    for r in due[:LIST_MAX]:
        c = clients_by_id.get(r.get("client_id")) or {}
        late = " ⚠️" if r.get("due_date") < today else ""
        lines.append(f"• {c.get('name') or '—'} — {_line(r.get('note'), 45)}{late}"
                     + (f"\n   wa.me/{c['phone']}" if c.get("phone") else ""))
    if len(due) > LIST_MAX:
        lines.append(f"…and {len(due) - LIST_MAX} more in the CRM.")
    return "\n".join(lines)


def chats_text(convos: list, clients_by_key: dict, now: datetime, staff_phones=(), last_reply=None) -> str:
    waiting = waiting_chats(convos, now, staff_phones, last_reply)
    if not waiting:
        return "✅ *Chats:* nobody is waiting for a reply."
    lines = [f"💬 *Waiting for a reply* — {len(waiting)}"]
    for c in waiting[:LIST_MAX]:
        lines.append(f"• {_name(c, clients_by_key)} ({_when(c.get('last_created_at'))}): "
                     f"“{_line(c.get('last_body'), 50)}”\n   wa.me/{c.get('phone')}")
    if len(waiting) > LIST_MAX:
        lines.append(f"…and {len(waiting) - LIST_MAX} more in the CRM WhatsApp page.")
    return "\n".join(lines)


def pipeline_text(stages: list) -> str:
    counts = Counter((s or "Lead") for s in stages)
    total = sum(counts.values())
    lines = [f"📊 *Pipeline* — {total} leads"]
    for st in STAGE_ORDER:
        if counts.get(st):
            lines.append(f"• {st}: {counts[st]}")
    for st, n in counts.items():
        if st not in STAGE_ORDER:
            lines.append(f"• {st}: {n}")
    return "\n".join(lines)


def due_text(invoices: list, today: str) -> str:
    owing = [i for i in invoices if float(i.get("balance_due") or 0) > 0]
    if not owing:
        return "✅ *Payments:* no invoice has money due."
    owing.sort(key=lambda i: (i.get("due_date") or "9999"))
    total = sum(float(i["balance_due"]) for i in owing)
    lines = [f"💰 *Money due* — ₹{money(total)} on {len(owing)} invoice{'s' if len(owing) != 1 else ''}"]
    for i in owing[:LIST_MAX]:
        late = " ⚠️ overdue" if i.get("due_date") and i["due_date"] < today else ""
        lines.append(f"• {i.get('client_name') or '—'} — ₹{money(i['balance_due'])}"
                     f" ({i.get('invoice_number') or 'no number'}"
                     + (f", due {i['due_date']}" if i.get("due_date") else "") + f"){late}")
    return "\n".join(lines)


def week_text(stats: dict) -> str:
    return "\n".join([
        "📅 *Last 7 days*",
        f"• New leads: {stats.get('new_leads', 0)} (Bairavi {stats.get('bairavi_leads', 0)})",
        f"• Customer messages: {stats.get('inbound', 0)}",
        f"• Leads called / marked: {stats.get('called', 0)}",
        f"• Follow-ups open now: {stats.get('open_followups', 0)}",
    ])


def today_text(followup_rows, clients_by_id, convos, clients_by_key, new_leads, now, staff_phones=(),
               last_reply=None) -> str:
    today = now.astimezone(IST).date().isoformat()
    every = due_followups(followup_rows, today)
    due = [r for r in every if not (r.get("note") or "").startswith(BOT_CHECK)]
    checks = len(every) - len(due)
    waiting = waiting_chats(convos, now, staff_phones, last_reply)
    t = now.astimezone(IST)
    lines = [f"☀️ *Today — {t.day} {t.strftime('%b')}*", ""]
    lines.append(f"📋 Follow-ups due: *{len(due)}*" + (f" (+{checks} 🤖 bot checks)" if checks else ""))
    for r in due[:3]:
        c = clients_by_id.get(r.get("client_id")) or {}
        lines.append(f"   • {c.get('name') or '—'} — {_line(r.get('note'), 40)}")
    lines.append(f"💬 Chats waiting for you: *{len(waiting)}*")
    for c in waiting[:3]:
        lines.append(f"   • {_name(c, clients_by_key)}: “{_line(c.get('last_body'), 40)}”")
    lines.append(f"🆕 New leads (24 h): *{len(new_leads)}*")
    for c in new_leads[:3]:
        lines.append(f"   • {c.get('name') or '—'} — {c.get('phone') or ''}")
    lines += ["", "More: #followups · #chats · #calls · #pipeline · #week"]
    return "\n".join(lines)
