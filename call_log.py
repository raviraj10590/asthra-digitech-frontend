"""The owner's call outcomes, typed on WhatsApp (owner request 2026-09-30).

The owner calls every lead from his own phone. The CRM cannot read a phone's
call log, and marking a call meant finding a dropdown inside each lead's page,
so nothing was marked. Now one message from the owner's number does it:

    5711 called interested
    2829 lost price
    3554 no answer

The last digits (4 or more) name the lead; the words name the outcome. The
outcome is written to the CRM's EXISTING fields — clients.pipeline_stage (the
same LEAD_STAGES the CRM's own dropdown writes), last_contacted_at, and a dated
line appended to notes. No new table, no migration.

Pure module: no network. api/webhook.py does the reads and writes.
"""
import re

# Stages the CRM already writes (src/lib/leadStage.ts LEAD_STAGES).
CONTACTED = "Contacted"
INTERESTED = "Interested"
SITE_VISIT = "Site Visit"
NEGOTIATION = "Negotiation"
WON = "Won"
LOST = "Lost"
NO_ANSWER = None           # a note only: the lead was not reached

# Strongest first: "called interested" is Interested, "called, lost" is Lost.
# Matched as whole words / phrases on the lower-cased text.
_OUTCOMES = (
    (WON, ("won", "order", "ordered", "confirmed", "booked", "advance paid",
           "deal done", "sold")),
    (LOST, ("lost", "not interested", "not intrested", "cancel", "cancelled",
            "dropped", "beda", "ಬೇಡ", "no deal")),
    (NO_ANSWER, ("no answer", "not answered", "not picking", "not picked",
                 "no response", "busy", "switch off", "switched off",
                 "not reachable", "unreachable", "ring", "ringing", "missed")),
    (NEGOTIATION, ("quote", "quotes", "quotation", "quotations", "negotiation",
                   "negotiating", "price talk", "discount")),
    (SITE_VISIT, ("site visit", "visit")),
    (INTERESTED, ("interested", "intrested", "interest", "hot", "positive",
                  "will buy",
                  # "Bharath want catalog and quotations" (2026-10-05)
                  "catalog", "catalogue", "brochure")),
    (CONTACTED, ("called", "call done", "contacted", "spoke", "talked",
                 "matadide", "maatadide", "ಮಾತಾಡಿದೆ", "ಕರೆ ಮಾಡಿದೆ", "done",
                 "call later", "follow up", "followup",
                 # "I talk with VINAY …", "I got call from VINAY kumar"
                 "talk", "talk with", "got call", "got a call", "spoke to")),
)

_LEAD_RE = re.compile(r"^\s*\+?(\d{4,13})\b[\s,:.-]*(.+)$", re.DOTALL)


def _has(low: str, phrase: str) -> bool:
    if phrase.isascii():
        return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", low) is not None
    return phrase in low


def parse(text: str):
    """(digits, stage, words) for an outcome message, else None.

    None means "not a call outcome", and the owner's message is handled as it
    always was. A message must START with the digits and carry a known outcome
    word; a number followed by anything else ("9845 ge call madi") is not one.
    """
    m = _LEAD_RE.match(text or "")
    if not m:
        return None
    digits, rest = m.group(1), m.group(2).strip()
    low = rest.lower()
    for stage, phrases in _OUTCOMES:
        if any(_has(low, p) for p in phrases):
            return digits, stage, rest
    return None


def stage_label(stage) -> str:
    return stage if stage else "No answer"


def note_line(stage, words: str, when: str) -> str:
    """The dated line appended to clients.notes. The owner's own words kept."""
    icon = {WON: "🏆", LOST: "❌", NEGOTIATION: "💰", SITE_VISIT: "📍",
            INTERESTED: "🔥", CONTACTED: "📞", NO_ANSWER: "📵"}[stage]
    return f"{icon} {when} call: {stage_label(stage)} — {words.strip()}"


def matches(digits: str, rows: list) -> list:
    """The CRM rows whose phone ends with these digits."""
    return [r for r in rows if (r.get("phone") or "").endswith(digits)]


def reply(stage, name: str, phone: str) -> str:
    who = f"{name} (…{phone[-4:]})" if name else f"…{phone[-4:]}"
    if stage is NO_ANSWER:
        return f"📵 {who}: no answer noted. Stage unchanged — try again later."
    return f"✅ {who} → *{stage}*"


def ambiguous_reply(digits: str, rows: list) -> str:
    lines = [f"⚠️ {len(rows)} leads end with {digits}. Send more digits:"]
    lines += [f"• {r.get('name') or '—'} — {r.get('phone')}" for r in rows[:5]]
    return "\n".join(lines)


def not_found_reply(digits: str) -> str:
    return f"⚠️ No lead in the CRM ends with {digits}. Check the number."


HELP = ("📞 *Mark a call* — send the last 4 digits and what happened:\n"
        "• 5711 called interested\n• 2829 lost price\n• 3554 no answer\n"
        "• 4028 quote sent\n• 1743 site visit\n• 4109 order confirmed\n"
        "Stages: Contacted · Interested · Site Visit · Negotiation · Won · Lost")


# ── CALL NOTES BY NAME (owner, 2026-10-05) ─────────────────────────────────
# The owner does not type last digits. What he actually sent:
#   "Call done" / "This is done customer interested after one month" /
#   "Shashi nanjappa"
#   "I got call from VINAY kumar MK he told call me 15 days letter"
#   "Bharath want catalog and quotations"
# and his assistant answered each with "noted — mark it in the CRM yourself".
# A note that names exactly one lead is now saved like a digits note, and a
# "call after N days/weeks/months" becomes a CRM follow-up on that date. A
# note that matches several leads is NOT written: the owner gets the
# candidates with their last digits. A note with no name waits (below).

_NUM_WORDS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "ten": 10, "fifteen": 15, "twenty": 20,
              "ondu": 1, "eradu": 2, "mooru": 3, "ಒಂದು": 1, "ಎರಡು": 2, "ಮೂರು": 3}
_UNIT_DAYS = (("month", 30), ("ತಿಂಗಳ", 30), ("thingal", 30), ("tingal", 30),
              ("week", 7), ("vara", 7), ("ವಾರ", 7), ("day", 1), ("dina", 1), ("ದಿನ", 1))
_DELAY_RE = re.compile(
    r"(?P<n>\d{1,3}|" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True)) + r")\s*"
    r"(?P<u>months?|weeks?|days?|ತಿಂಗಳ\S*|ವಾರ\S*|ದಿನ\S*|thingal\S*|tingal\S*|vara\S*|dina\S*)")
_DELAY_WORDS = (("next month", 30), ("next week", 7), ("tomorrow", 1), ("nale", 1),
                ("naale", 1), ("ನಾಳೆ", 1), ("day after tomorrow", 2))


def followup_days(text: str):
    """Days until the owner should call again, when the note says so; else None.

    "after one month" 30, "15 days letter" 15, "call me 2 weeks later" 14,
    "next week" 7, "tomorrow" 1. Only a delay tied to a unit is read — a bare
    "15" is not a date.
    """
    low = (text or "").lower()
    m = _DELAY_RE.search(low)
    if m:
        n = m.group("n")
        n = int(n) if n.isdigit() else _NUM_WORDS[n]
        unit = m.group("u")
        for stem, days in _UNIT_DAYS:
            if unit.startswith(stem):
                return n * days if 0 < n * days <= 365 else None
    for phrase, days in _DELAY_WORDS:
        if _has(low, phrase):
            return days
    return None


def outcome_of(text: str):
    """(stage, days) for a call note without digits, or None when it is not one.

    A follow-up time alone ("he told call me 15 days later") is a contact.
    """
    low = (text or "").lower()
    days = followup_days(text)
    for stage, phrases in _OUTCOMES:
        if any(_has(low, p) for p in phrases):
            return stage, days
    return (CONTACTED, days) if days else None


# Words in a note that are never a person's name.
_NOT_NAMES = {"call", "called", "done", "this", "that", "customer", "interested", "after",
              "month", "months", "week", "weeks", "days", "day", "later", "letter", "told",
              "with", "from", "talk", "want", "wants", "catalog", "quotation", "quotations",
              "transformer", "the", "and", "got", "him", "her", "said", "next", "one", "kva",
              "star", "plus", "gst", "lead", "whatsapp", "price", "not", "will", "sir"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z\u0C80-\u0CFF]{3,}", (text or "").lower())
            if w not in _NOT_NAMES}


def name_matches(text: str, rows: list) -> list:
    """The leads whose name shares a word with the note, best match first.

    A lead matches on any word of its name of 3+ letters. Ties are all
    returned — "Vinay" with two Vinays in the CRM is ambiguous, and the caller
    asks rather than guesses.
    """
    said = _words(text)
    if not said:
        return []
    scored = []
    for r in rows:
        hits = said & _words(r.get("name") or "")
        if hits:
            scored.append((len(hits), r))
    if not scored:
        return []
    best = max(n for n, _ in scored)
    return [r for n, r in scored if n == best]


def is_bare_name(text: str) -> bool:
    """'Shashi nanjappa' — a name and nothing else (1–4 words, no outcome)."""
    words = re.findall(r"\S+", text or "")
    return 0 < len(words) <= 4 and outcome_of(text) is None and not re.search(r"\d", text)


def pending_note(history: list, now, max_minutes: int = 30):
    """The owner's own recent call note that named nobody, or None.

    "Call done" then "This is done customer interested after one month" were
    sent BEFORE the name. Read back from his last few messages (newest first,
    within max_minutes), stopping at anything that was already saved.
    Returns (stage, days, words).
    """
    from datetime import datetime, timedelta
    notes = []
    for m in reversed(history or []):
        if m.get("role") == "assistant" and (m.get("content") or "").startswith(("✅", "📵", "📅")):
            break                      # an earlier note was already saved
        if m.get("role") != "user":
            continue
        try:
            at = datetime.fromisoformat((m.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            break
        if now - at > timedelta(minutes=max_minutes):
            break
        got = outcome_of(m.get("content"))
        if got is None:
            break
        notes.append((got, m.get("content").strip()))
        if len(notes) == 3:
            break
    if not notes:
        return None
    order = [s for s, _ in _OUTCOMES]
    stage = min((s for (s, _), _ in notes), key=order.index)
    days = next((d for (_, d), _ in notes if d), None)
    words = " / ".join(w for _, w in reversed(notes))
    return stage, days, words


def note_line_with_followup(stage, words: str, when: str, due) -> str:
    line = note_line(stage, words, when)
    return f"{line} — follow-up {due}" if due else line


def named_reply(stage, name: str, phone: str, due) -> str:
    base = reply(stage, name, phone)
    return f"{base}\n📅 Follow-up added: *{due}*" if due else base


def several_reply(rows: list) -> str:
    lines = [f"⚠️ This matches {len(rows)} leads — not saved. Send it again with the "
             "last 4 digits, e.g. *5711 interested call after 1 month*:"]
    lines += [f"• {r.get('name') or '—'} — …{(r.get('phone') or '')[-4:]}" for r in rows[:6]]
    return "\n".join(lines)


# A REQUEST TO THE ASSISTANT IS NOT A CALL NOTE. "draft a quotation for
# Bharath" names a lead and carries "quotation", and must still reach the
# assistant instead of moving Bharath to Negotiation.
_REQUEST_RE = re.compile(
    r"\?|(?<![a-z])(draft|write|prepare|make|create|send|share|give|show|list|tell me|"
    r"remind|what|how|why|when|which|can you|could you|please|pls|maadu|madu|kalisu|kodu|"
    r"helu|hel)(?![a-z])")


def is_request(text: str) -> bool:
    return bool(_REQUEST_RE.search((text or "").lower()))
