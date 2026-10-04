"""Promised calls that have not happened — the owner is reminded (2026-10-03).

Owner request: "build first one" — the call reminder suggested from the data:
in the 14 days to 2026-10-03, 27 Bairavi customers chose a call time
(12 "now", 5 "this evening", 10 "tomorrow") and 19 of them were never marked
as called in the CRM. A customer promised "ಈಗಲೇ" who hears nothing goes cold.

WHAT A PROMISE IS
-----------------
The moment a customer picked a time, read from the transcript exactly as the
live flow reads it: bairavi.callback_request() on each customer message, with
the awaiting context of the reply before it. The latest choice wins. Nothing
new is stored to know this.

WHEN IT IS DUE (owner's call hours, 9 am – 9 pm IST)
---------------------------------------------------
    now       one hour after the choice; chosen at night -> 10 am
    evening   8 pm that day (or an hour after, if chosen after 8 pm);
              chosen after 9 pm -> 8 pm the next day
    tomorrow  noon the next day

WHEN IT IS DONE
---------------
The CRM shows a call after the promise (last_contacted_at — what "5711 called
interested" and the Calls page write), the lead has left the "Lead" stage, or
the owner wrote to them by hand from the CRM after the promise. A customer
who declined afterwards ("no thanks", "STOP") is not chased.

Pure: no network, no clock unless one is passed.
"""
from datetime import datetime, timedelta, timezone

import bairavi
import brain_health

IST = timezone(timedelta(hours=5, minutes=30))
CALL_HOURS = bairavi.CALL_HOURS          # (9, 21), owner 2026-10-03
MAX_AGE_DAYS = 7                         # stop chasing a week-old promise
MAX_LINES = 15                           # one readable WhatsApp message
MARK = "CALL_REMINDER::"

_SLOT_TEXT = {bairavi.CALLBACK_NOW: "now", bairavi.CALLBACK_EVENING: "this evening",
              bairavi.CALLBACK_TOMORROW: "tomorrow"}


def _ts(value):
    return brain_health._ts(value)


def promise(history) -> dict:
    """The customer's latest call-time choice in this Bairavi conversation:
    {slot, chosen_at (str, as stored), declined_after, complained_after}, or None.

    `history` is the transcript, oldest first, as Brain stores it
    (role / content / created_at). Bracketed system rows are ignored.
    """
    rows = [r for r in history or [] if r.get("role") in ("user", "assistant")]
    if not bairavi.in_transformer_flow(rows):
        return None
    awaiting, found = (), None
    for r in rows:
        text = r.get("content") or ""
        if r.get("role") == "assistant":
            if bairavi.FLOW_MARKER in text:
                awaiting = bairavi.marker_awaiting(text)
            continue
        if bairavi.is_lead_form(text):
            continue
        # THE CUSTOMER'S OWN TIME (2026-10-04, option B): the answer to "what
        # time shall we call?" after a night-time "now" sets when it is due.
        if found and bairavi.AWAITING_CALL_TIME in awaiting:
            when = bairavi.parse_call_time(text)
            if when:
                found.update(time_hour=when["hour"], time_label=when["label_en"],
                             time_at=r.get("created_at"))
                continue
        slot = bairavi.callback_request(text, awaiting)
        if slot:
            found = {"slot": slot, "chosen_at": r.get("created_at"),
                     "declined_after": False, "complained_after": False,
                     "time_hour": None, "time_label": None, "time_at": None}
            continue
        if found:
            if bairavi.is_decline(text):
                found["declined_after"] = True
            if bairavi.call_missed(text):
                found["complained_after"] = True
    return found


def due_at(slot: str, chosen_at, time_hour: int = None, time_at=None) -> datetime:
    """When the promised call should have happened (aware, IST).

    A time the customer named wins: the call is due at that hour, today, or
    tomorrow when they named it after call hours."""
    if time_hour is not None and time_at:
        said = (_ts(time_at) if isinstance(time_at, str) else time_at).astimezone(IST)
        day = said.replace(hour=0, minute=0, second=0, microsecond=0)
        if said.hour >= CALL_HOURS[1]:
            day += timedelta(days=1)
        return day + timedelta(hours=time_hour)
    chosen = (_ts(chosen_at) if isinstance(chosen_at, str) else chosen_at).astimezone(IST)
    start, end = CALL_HOURS
    day = chosen.replace(hour=0, minute=0, second=0, microsecond=0)
    if slot == bairavi.CALLBACK_NOW:
        if chosen.hour >= end:
            return day + timedelta(days=1, hours=start + 1)
        if chosen.hour < start:
            return day + timedelta(hours=start + 1)
        return chosen + timedelta(hours=1)
    if slot == bairavi.CALLBACK_EVENING:
        if chosen.hour >= end:
            return day + timedelta(days=1, hours=20)
        return max(day + timedelta(hours=20), chosen + timedelta(hours=1))
    # tomorrow
    return day + timedelta(days=1, hours=12)


def handled(chosen_at, client: dict = None, manual_outbound=()) -> bool:
    """Has the owner dealt with this promise since it was made?"""
    chosen = _ts(chosen_at)
    client = client or {}
    called = _ts(client.get("last_contacted_at"))
    if called and chosen and called >= chosen:
        return True
    if (client.get("pipeline_stage") or "Lead") != "Lead":
        return True
    return any(_ts(t) and chosen and _ts(t) >= chosen for t in manual_outbound or ())


def marker(chosen_at: str, today_ist: str) -> str:
    return f"{MARK}{chosen_at}::{today_ist}"


def reminded_today(markers, chosen_at: str, today_ist: str) -> bool:
    return marker(chosen_at, today_ist) in set(markers or ())


def in_call_hours(now: datetime) -> bool:
    h = now.astimezone(IST).hour
    return CALL_HOURS[0] <= h < CALL_HOURS[1]


def ist_day(now: datetime) -> str:
    return now.astimezone(IST).date().isoformat()


def _when(value) -> str:
    t = _ts(value)
    if not t:
        return "?"
    t = t.astimezone(IST)
    return f"{t.day} {t.strftime('%b')} {t.strftime('%I:%M %p').lstrip('0').lower()}"


def _one_line(text, limit: int = 40) -> str:
    """Addresses arrive with line breaks ("Baleathiguppe\nPandavapura\nMandya");
    a list item must stay one line."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def compose(items: list, now: datetime) -> str:
    """The owner's message. `items`: dicts with phone, name, kva, place, slot,
    chosen_at, complained.

    NEWEST PROMISE FIRST: a lead who asked an hour ago is the likeliest sale;
    a week-old one still appears, lower down, until the cap sends the rest to
    the Calls page."""
    items = sorted(items, key=lambda i: _ts(i["chosen_at"]) or now, reverse=True)
    lines = [f"⏰📞 *Customers waiting for your call — {len(items)}*"]
    for it in items[:MAX_LINES]:
        days = (now.astimezone(IST).date() - _ts(it["chosen_at"]).astimezone(IST).date()).days
        facts = " · ".join(x for x in (_one_line(it.get("name"), 30) or "—",
                                       f"{it['kva']} kVA" if it.get("kva") else None,
                                       _one_line(it.get("place"))) if x)
        lines.append(f"• {facts} — asked *{_SLOT_TEXT.get(it['slot'], it['slot'])}*"
                     + (f" (their time: *{it['time_label']}*)" if it.get("time_label") else "") + " "
                     f"({_when(it['chosen_at'])})"
                     + (f" · day {days + 1}" if days else "")
                     + (" · 📵 *complained: no call*" if it.get("complained") else "")
                     + f"\n   wa.me/{it['phone']}")
    if len(items) > MAX_LINES:
        lines.append(f"…and {len(items) - MAX_LINES} more on the CRM Calls page.")
    example = items[0]["phone"][-4:]
    lines.append(f"\nAfter calling, send *{example} called interested* (or mark it on "
                 "the Calls page) — they leave this list.")
    return "\n".join(lines)
