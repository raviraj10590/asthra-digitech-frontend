"""Ask the Brain about one customer, from the owner's own WhatsApp (2026-10-01).

WHY: "am asking through my number to the bot brain number but it does not
get data in CRM — its knowledge is limited." The owner assistant saw only its
own chat and a memory note; nothing about any lead. Now:

    5711                  -> the brief for the lead whose number ends 5711
    5711 enu helidru?     -> the same (digits first, no call-outcome words)
    #who Sudarshan        -> by name (or #who 5711)

The brief: name, kVA / place / urgency from their form, CRM stage and last
call note, the 🧠 AI summary, their last messages with the bot's replies,
open follow-ups, and a tap-to-call link.

Pure: api/webhook.py reads the CRM (through the tool registry) and calls
build(); nothing here touches the network.
"""
import re
from datetime import datetime, timedelta, timezone

import bairavi
import call_briefing

IST = timezone(timedelta(hours=5, minutes=30))
LAST_MESSAGES = 6
_WHO_RE = re.compile(r"^#who\s+(.+)$", re.I)
_DIGITS_FIRST_RE = re.compile(r"^\s*\+?(\d{4,13})\b(.*)$", re.S)


def query_of(text: str):
    """('phone', digits) / ('name', words) for a lookup message, else None.

    A message that starts with digits is a lookup ONLY when it is not a call
    outcome ("5711 called interested" stays with call_log) — the caller checks
    call_log first, so here any digits-first message qualifies.
    """
    t = (text or "").strip()
    m = _WHO_RE.match(t)
    if m:
        arg = m.group(1).strip()
        return ("phone", arg) if re.fullmatch(r"\+?\d{4,13}", arg) else ("name", arg)
    m = _DIGITS_FIRST_RE.match(t)
    if m:
        return ("phone", m.group(1))
    return None


def _ist(iso: str) -> str:
    try:
        t = call_briefing._ts(iso).astimezone(IST)
    except (ValueError, TypeError):
        return (iso or "")[:16]
    return f"{t.day} {t.strftime('%b')} {t.strftime('%I:%M %p').lstrip('0').lower()}"


def _form(messages: list) -> dict:
    for m in messages:
        body = m.get("body") or ""
        if (m.get("direction") or "").startswith("in") and bairavi.is_lead_form(body):
            p = bairavi.parse(body)
            return {"kva": p.get("capacity_kva"), "place": p.get("location"),
                    "urgency": p.get("urgency")}
    return {}


_URGENCY = {"IMMEDIATE": "needs it NOW", "WITHIN_1_MONTH": "within 1 month",
            "WITHIN_3_MONTHS": "1–3 months", "INFORMATION_ONLY": "price list / info"}


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def build(client: dict, messages: list, followups: list = ()) -> str:
    """The brief for one CRM lead."""
    msgs = sorted(messages or [], key=lambda m: m.get("created_at") or "")
    form = _form(msgs)
    phone = client.get("phone") or ""
    name = bairavi.display_name(client.get("name")) or client.get("name") or "—"
    lines = [f"👤 *{name}* · …{phone[-4:]}"]
    facts = []
    if form.get("kva"):
        facts.append(f"{form['kva']} kVA")
    if form.get("place"):
        facts.append(bairavi.place_display(form["place"]))
    if form.get("urgency") in _URGENCY:
        facts.append(_URGENCY[form["urgency"]])
    if facts:
        lines.append("📋 " + " · ".join(facts))
    stage = client.get("pipeline_stage") or "Lead"
    lines.append(f"📌 Stage: *{'New Lead' if stage == 'Lead' else stage}*"
                 + (f" · last contact {_ist(client['last_contacted_at'])}"
                    if client.get("last_contacted_at") else " · not called yet"))
    notes = (client.get("notes") or "").splitlines()
    summary = next((l.split(" — ", 1)[1] for l in reversed(notes)
                    if l.startswith("🧠 AI") and " — " in l), None)
    if summary:
        lines.append(f"🧠 {summary}")
    calls = [l for l in notes if " call: " in l]
    if calls:
        lines.append(f"📞 {calls[-1]}")
    open_fu = [f for f in followups or () if not f.get("is_done")]
    for f in open_fu[:2]:
        lines.append(f"⏰ {f.get('due_date')}: {_clip(f.get('note'), 80)}")
    shown = [m for m in msgs if not (m.get("direction", "").startswith("in")
                                     and bairavi.is_lead_form(m.get("body") or ""))]
    if shown:
        lines.append("")
        lines.append(f"💬 Last {min(LAST_MESSAGES, len(shown))} messages:")
        for m in shown[-LAST_MESSAGES:]:
            who = "👤" if (m.get("direction") or "").startswith("in") else "🤖"
            lines.append(f"{who} {_ist(m.get('created_at') or '')} — {_clip(m.get('body'), 90)}")
    lines.append("")
    lines.append(f"📲 wa.me/{phone} · mark a call: *{phone[-4:]} called interested*")
    return "\n".join(lines)


def choose_reply(query, rows: list):
    """'' when exactly one lead matched (caller builds the brief), else the
    reply for none / several."""
    kind, value = query
    if not rows:
        return f"⚠️ No lead in the CRM {'ends with' if kind == 'phone' else 'named'} {value}."
    if len(rows) > 1:
        lines = [f"⚠️ {len(rows)} leads match {value}. Send more digits:"]
        lines += [f"• {r.get('name') or '—'} — {r.get('phone')}" for r in rows[:6]]
        return "\n".join(lines)
    return ""
