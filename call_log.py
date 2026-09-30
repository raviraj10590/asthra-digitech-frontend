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
    (NEGOTIATION, ("quote", "quotation", "negotiation", "negotiating",
                   "price talk", "discount")),
    (SITE_VISIT, ("site visit", "visit")),
    (INTERESTED, ("interested", "intrested", "interest", "hot", "positive",
                  "will buy")),
    (CONTACTED, ("called", "call done", "contacted", "spoke", "talked",
                 "matadide", "maatadide", "ಮಾತಾಡಿದೆ", "ಕರೆ ಮಾಡಿದೆ", "done",
                 "call later", "follow up", "followup")),
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
