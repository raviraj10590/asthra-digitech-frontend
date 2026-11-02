"""The owner's CRM on WhatsApp — phase 2: small writes behind #confirm
(owner, 2026-11-02: "phase two maadu").

    #fu 4521 naale            a follow-up for that lead (naale / 3 days /
    #fu 4521 15 nov quote     2 weeks / 15 nov / 2026-11-15), with a note
    #done 4521                that lead's open follow-ups are done
    #note 4521 site visit Mon a dated line on the lead's notes
    #stage 4521 won           the lead's stage (the CRM's own stage names)

Every one is staged first: the bot answers with what it is about to write,
naming the lead, and nothing is written until the owner sends #confirm. The
lead is found by its last 4+ digits, as call outcomes are ("5711 called
interested", which still writes at once — that is phase 1's habit and is
left alone).

Only the CRM's EXISTING fields and tables: clients.notes,
clients.pipeline_stage, follow_ups. No new table.

Pure module: no network, no clock unless passed. api/webhook.py does the I/O.
"""
import re
from datetime import date, datetime, timedelta, timezone

import call_log

IST = timezone(timedelta(hours=5, minutes=30))

FOLLOWUP, DONE, NOTE, STAGE = "followup", "done", "note", "stage"

STAGES = ("Lead", "Contacted", "Interested", "Site Visit", "Negotiation", "Won", "Lost")
_STAGE_WORDS = {s.lower(): s for s in STAGES}
_STAGE_WORDS.update({"sitevisit": "Site Visit", "visit": "Site Visit", "negotiate": "Negotiation",
                     "new": "Lead", "called": "Contacted", "hot": "Interested"})

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

_CMD_RE = re.compile(r"^#(fu|followup|follow-up|done|note|stage)\s+\+?(\d{4,15})\b\s*(.*)$",
                     re.IGNORECASE | re.DOTALL)
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})\b\s*(.*)$", re.DOTALL)
_DAY_MONTH_RE = re.compile(r"^(\d{1,2})\s*(?:st|nd|rd|th)?\s*([a-z]{3})[a-z]*\.?\b\s*(.*)$",
                           re.IGNORECASE | re.DOTALL)
_MONTH_DAY_RE = re.compile(r"^([a-z]{3})[a-z]*\.?\s*(\d{1,2})\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
_RELATIVE_RE = re.compile(
    r"^((?:\d{1,3}|one|two|three|four|five|six|seven|ten|fifteen|twenty|ondu|eradu|mooru)\s*"
    r"(?:months?|weeks?|days?|dina\S*|vara\S*|tingal\S*|thingal\S*)"
    r"|tomorrow|naale|nale|ನಾಳೆ|next week|next month|day after tomorrow)\b\s*(.*)$",
    re.IGNORECASE | re.DOTALL)

USAGE = ("❓ Usage:\n#fu 4521 naale [note] · #fu 4521 15 nov [note] · #fu 4521 3 days\n"
         "#done 4521 · #note 4521 <text> · #stage 4521 won")


def _due(rest: str, today: date):
    """(due date, the rest as the note) from the start of `rest`, else None."""
    rest = rest.strip()
    m = _ISO_RE.match(rest)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)
        except ValueError:
            return None
    for rx, day_i, mon_i in ((_DAY_MONTH_RE, 1, 2), (_MONTH_DAY_RE, 2, 1)):
        m = rx.match(rest)
        if m and m.group(mon_i)[:3].lower() in _MONTHS:
            try:
                d = date(today.year, _MONTHS[m.group(mon_i)[:3].lower()], int(m.group(day_i)))
            except ValueError:
                return None
            if d < today:                      # "15 jan" said in November is next January
                d = d.replace(year=today.year + 1)
            return d, m.group(3)
    m = _RELATIVE_RE.match(rest)
    if m:
        days = call_log.followup_days(m.group(1))
        if days:
            return today + timedelta(days=days), m.group(2)
    return None


def parse(text: str, today: date):
    """(kind, digits, details) for a phase-2 command, ("usage", None, None) for
    one of these words used wrongly, else None (not a phase-2 command)."""
    stripped = (text or "").strip()
    m = _CMD_RE.match(stripped)
    if not m:
        if re.match(r"^#(fu|followup|follow-up|done|note|stage)\b", stripped, re.IGNORECASE):
            return "usage", None, None
        return None
    word, digits, rest = m.group(1).lower(), m.group(2), " ".join(m.group(3).split())
    if word in ("fu", "followup", "follow-up"):
        got = _due(rest, today)
        if not got or got[0] < today or got[0] > today + timedelta(days=366):
            return "usage", None, None
        return FOLLOWUP, digits, {"due": got[0].isoformat(), "note": got[1].strip()}
    if word == "done":
        return DONE, digits, {}
    if word == "note":
        return (NOTE, digits, {"note": rest}) if rest else ("usage", None, None)
    stage = _STAGE_WORDS.get(rest.lower())
    return (STAGE, digits, {"stage": stage}) if stage else ("usage", None, None)


def _who(lead: dict) -> str:
    name = lead.get("name") or "—"
    return f"{name} (…{(lead.get('phone') or '')[-4:]})"


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def confirm_prompt(kind: str, lead: dict, details: dict, open_followups: int = 0) -> str:
    """What the owner is asked to #confirm — the lead and the exact write."""
    who = _who(lead)
    if kind == FOLLOWUP:
        return f"Follow-up for {who} on {_day(details['due'])}" + (
            f": {details['note']}" if details.get("note") else "") + "?"
    if kind == DONE:
        return f"Mark {open_followups} open follow-up(s) of {who} done?"
    if kind == NOTE:
        return f"Add a note to {who}: \"{details['note']}\"?"
    return f"Move {who} from {lead.get('pipeline_stage') or 'Lead'} to *{details['stage']}*?"


def note_line(text: str, now: datetime) -> str:
    return f"📝 {now.astimezone(IST).strftime('%d %b %H:%M')} {text.strip()}"


def done_reply(kind: str, lead: dict, details: dict, count: int = 0) -> str:
    who = _who(lead)
    if kind == FOLLOWUP:
        return f"✅ Follow-up saved: {who} on {_day(details['due'])}"
    if kind == DONE:
        return f"✅ {who}: {count} follow-up(s) marked done"
    if kind == NOTE:
        return f"✅ Note added to {who}"
    return f"✅ {who} → *{details['stage']}*"
