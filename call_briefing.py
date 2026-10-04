"""Morning call briefing — sent to the owner right after the 9:00 digest.

WHY (2026-09-30): every lead review ended with a hand-written "call these
people" list, and the owner then asked for a way to tick calls off. The call
outcomes now live on the CRM lead (pipeline_stage / last_contacted_at / dated
notes lines, written by the Calls page or by "5711 called interested"), so
the list can be built every morning from the same data:

    🔥 Call first   asked to be called NOW, or needs the transformer now
    📅 Promised     chose "this evening" / "tomorrow" — a call we promised
    🕒 Also waiting everyone else not yet marked (count + newest few)
    📊 Yesterday    new leads, and how yesterday's calls went

Pure: no network. api/digest.py reads the CRM and sends the text.
Every name, kVA and place comes from the lead's own form; nothing is invented.
"""
import re
from datetime import datetime, timedelta, timezone

import bairavi

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_DAYS = 14
MAX_FIRST = 8
MAX_PROMISED = 8
MAX_OTHERS = 3
# The owner's own numbers are test traffic, never a lead — the CRM's Lead
# Insights uses the same two (src/lib/leadInsights.ts OWNER_LAST4).
OWNER_LAST4 = ("9951", "8141")

# The bot's own confirmation of the chosen call time (bairavi.py, callback
# close and the "will you call now?" confirmation). Latest one wins.
# "now" includes the morning promise made at night or before 9 (bairavi
# callback_when_kn): those customers were promised a call by 10, so they
# belong in 🔥 Call first, not in "also waiting". The older "after 9" wording
# is kept so promises made before 2026-10-04 are still recognised.
_SLOT_RE = {"now": re.compile(r"engineer \*(?:ಈಗಲೇ|(?:ಇಂದು|ನಾಳೆ) ಬೆಳಿಗ್ಗೆ (?:9 ಗಂಟೆಯ ನಂತರ|10 ಗಂಟೆಯ ಒಳಗೆ))\*"),
            "evening": re.compile(r"engineer \*ಇಂದು ಸಂಜೆ\*"),
            "tomorrow": re.compile(r"engineer \*ನಾಳೆ\*")}
_SLOT_EN = {"now": "asked: call NOW", "evening": "asked: this evening",
            "tomorrow": "asked: tomorrow"}
_STAGE_ORDER = ("Won", "Negotiation", "Site Visit", "Interested", "Contacted",
                "No answer", "Lost")
_CALL_LINE_RE = re.compile(r"^\S+ (\d{2} [A-Z][a-z]{2}) \d{2}:\d{2} call: ([A-Za-z ]+?) — ")


_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
                     r"(Z|[+-]\d{2}(?::?\d{2})?)?$")


def _ts(iso: str) -> datetime:
    """Postgres/PostgREST timestamps in every shape they arrive in:
    'T' or space, 0-9 fraction digits, 'Z', '+00', '+05:30' or no zone."""
    m = _ISO_RE.match((iso or "").strip())
    if not m:
        raise ValueError(f"unreadable timestamp {iso!r}")
    date, clock, frac, zone = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    t = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S").replace(microsecond=micro)
    if not zone or zone == "Z":
        return t.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    digits = zone[1:].replace(":", "")
    offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
    return t.replace(tzinfo=timezone(sign * offset))


def is_unmarked(c: dict) -> bool:
    """Same rule as the CRM Calls page: default stage and never contacted."""
    return (c.get("pipeline_stage") or "Lead") == "Lead" and not c.get("last_contacted_at")


def chosen_slot(outbound: list):
    """(slot, when) from the newest bot confirmation, else (None, None)."""
    for m in sorted(outbound, key=lambda m: m.get("created_at") or "", reverse=True):
        body = m.get("body") or ""
        for slot, rx in _SLOT_RE.items():
            if rx.search(body):
                return slot, m.get("created_at")
    return None, None


def _form_facts(inbound: list) -> dict:
    for m in inbound:
        body = m.get("body") or ""
        if bairavi.is_lead_form(body):
            p = bairavi.parse(body)
            return {"kva": p.get("capacity_kva"), "place": p.get("location"),
                    "urgency": p.get("urgency")}
    return {"kva": None, "place": None, "urgency": None}


SUMMARY_TAG = "🧠 AI"   # written by ops/nara_jobs.py at 08:15


def ai_summary(notes: str):
    """The newest NaraRouter summary on the lead, without its date stamp."""
    for line in reversed((notes or "").splitlines()):
        if line.startswith(SUMMARY_TAG) and " — " in line:
            return line.split(" — ", 1)[1].strip() or None
    return None


def _line(n: int, lead: dict, now: datetime) -> str:
    bits = [lead["name"] or "—"]
    if lead["kva"]:
        bits.append(f"{lead['kva']} kVA")
    if lead["place"]:
        bits.append(bairavi.place_display(lead["place"])[:40])
    if lead["slot"]:
        bits.append(_SLOT_EN[lead["slot"]] + _when(lead["slot_at"], now))
    elif lead["urgency"] == "IMMEDIATE":
        bits.append("needs it NOW")
    text = f"{n}. " + " · ".join(bits)
    if lead.get("summary"):
        text += f"\n   🧠 {lead['summary'][:140]}"
    return text + f"\n   wa.me/{lead['phone']} · …{lead['phone'][-4:]}"


def _when(iso, now: datetime) -> str:
    if not iso:
        return ""
    t = _ts(iso).astimezone(IST)
    day = "today" if t.date() == now.astimezone(IST).date() else \
          "yesterday" if t.date() == (now.astimezone(IST) - timedelta(days=1)).date() else \
          t.strftime("%d %b")
    return f" ({day} {t.strftime('%I:%M %p').lstrip('0').lower()})"


def yesterdays_calls(clients: list, now: datetime) -> dict:
    """Stage -> count, from the dated call lines both paths write."""
    y = (now.astimezone(IST) - timedelta(days=1)).strftime("%d %b")
    out = {}
    for c in clients:
        for line in (c.get("notes") or "").splitlines():
            m = _CALL_LINE_RE.match(line.strip())
            if m and m.group(1) == y:
                stage = m.group(2).strip()
                out[stage] = out.get(stage, 0) + 1
    return out


def build(clients: list, messages: list, now: datetime = None,
          owner_phones=(), bot_checks: int = 0) -> str:
    """The briefing text, or "" when there is nothing to say."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    by_phone = {}
    for m in messages or []:
        by_phone.setdefault(m.get("phone"), []).append(m)

    own = {p[-4:] for p in owner_phones or ()} | set(OWNER_LAST4)
    clients = [c for c in clients or [] if (c.get("phone") or "")[-4:] not in own]
    recent = [c for c in clients if c.get("created_at") and _ts(c["created_at"]) >= since]
    todo = []
    for c in recent:
        if not is_unmarked(c):
            continue
        msgs = by_phone.get(c["phone"], [])
        slot, slot_at = chosen_slot([m for m in msgs if m.get("direction") == "outbound"])
        todo.append({"name": bairavi.display_name(c.get("name")) or c.get("name"),
                     "phone": c["phone"], "created_at": c["created_at"],
                     "slot": slot, "slot_at": slot_at, "summary": ai_summary(c.get("notes")),
                     **_form_facts([m for m in msgs if m.get("direction") == "inbound"])})

    first = [l for l in todo if l["slot"] == "now" or (not l["slot"] and l["urgency"] == "IMMEDIATE")]
    promised = [l for l in todo if l["slot"] in ("evening", "tomorrow")]
    others = [l for l in todo if l not in first and l not in promised]
    newest = lambda xs: sorted(xs, key=lambda l: l["created_at"], reverse=True)
    # NEWEST FIRST: a request from this morning outranks one from last week,
    # which has most likely been handled already and just not marked.
    first = sorted(first, key=lambda l: l["slot_at"] or l["created_at"], reverse=True)
    promised = sorted(promised, key=lambda l: l["slot_at"] or "", reverse=True)

    y_start = (now.astimezone(IST) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    y_end = y_start + timedelta(days=1)
    new_yesterday = sum(1 for c in recent if y_start <= _ts(c["created_at"]).astimezone(IST) < y_end)
    calls = yesterdays_calls(clients or [], now)

    if not todo and not new_yesterday and not calls and not bot_checks:
        return ""
    today = now.astimezone(IST).strftime("%d %b")
    lines = [f"📞 *Today's call plan* — {today}", ""]
    if first:
        lines.append(f"🔥 *Call first* ({len(first)})")
        lines += [_line(i, l, now) for i, l in enumerate(first[:MAX_FIRST], 1)]
        if len(first) > MAX_FIRST:
            lines.append(f"   …and {len(first) - MAX_FIRST} more")
        lines.append("")
    if promised:
        lines.append(f"📅 *Promised a call* ({len(promised)})")
        lines += [_line(i, l, now) for i, l in enumerate(promised[:MAX_PROMISED], 1)]
        if len(promised) > MAX_PROMISED:
            lines.append(f"   …and {len(promised) - MAX_PROMISED} more")
        lines.append("")
    if others:
        lines.append(f"🕒 *Also not called yet*: {len(others)} (newest below)")
        lines += [_line(i, l, now) for i, l in enumerate(newest(others)[:MAX_OTHERS], 1)]
        lines.append("")
    if not todo:
        lines += ["✅ Everyone from the last 14 days has been marked.", ""]
    summary = [f"🆕 {new_yesterday} new lead" + ("s" if new_yesterday != 1 else "")]
    if calls:
        summary.append(" · ".join(f"{calls[s]} {s}" for s in _STAGE_ORDER if s in calls))
    else:
        summary.append("no calls marked")
    lines.append("📊 *Yesterday*: " + " — ".join(summary))
    if bot_checks:
        lines.append(f"🤖 *Bot check*: {bot_checks} chat{'s' if bot_checks != 1 else ''} "
                     "flagged for a look — CRM → Follow-ups")
    lines.append("")
    lines.append("After a call, reply e.g. *5711 called interested* · full list: asthra.website/calls")
    return "\n".join(lines)
