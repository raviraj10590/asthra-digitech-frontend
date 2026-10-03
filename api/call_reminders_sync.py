"""Remind the owner about promised calls that have not happened (see
call_reminders.py for what a promise is, when it is due and when it is done).

Runs from api/recovery.py after each authenticated sweep, inside the owner's
call hours only. One WhatsApp message per run, to the owner and staff, listing
every customer whose promised call is overdue and not yet handled; each one at
most once per day, for up to a week. Never messages a customer.

CALL_REMINDERS=off disables it. Never raises; logs counts only — no name,
phone or message text.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import bairavi
import call_reminders as cr
import webhook as w

PAGE = 1000          # PostgREST's default max rows; read in pages, never assume one
MAX_PAGES = 20


def enabled() -> bool:
    return os.environ.get("CALL_REMINDERS", "on").strip().lower() != "off"


def _paged(url: str, headers: dict, params: dict) -> list:
    out = []
    for page in range(MAX_PAGES):
        r = requests.get(url, headers=headers,
                         params=dict(params, limit=str(PAGE), offset=str(page * PAGE)),
                         timeout=10)
        r.raise_for_status()
        rows = r.json()
        out.extend(rows)
        if len(rows) < PAGE:
            return out
    return out


def brain_history(now) -> list:
    since = (now - timedelta(days=cr.MAX_AGE_DAYS + 3)).isoformat()
    return _paged(f"{w.SUPABASE_URL}/rest/v1/whatsapp_messages", w._supa_headers(),
                  {"created_at": f"gte.{since}", "select": "phone,role,content,created_at",
                   "order": "created_at.asc,id.asc"})


def crm_state(phones, since):
    """({phone: [client rows]}, {phone: [manual outbound times]})."""
    inlist = "in.(" + ",".join(phones) + ")"
    clients = _paged(f"{w.CRM_SUPABASE_URL}/rest/v1/clients", w._crm_headers(),
                     {"phone": inlist, "user_id": f"eq.{w.CRM_OWNER_USER_ID}",
                      "select": "phone,name,pipeline_stage,last_contacted_at"})
    outbound = _paged(f"{w.CRM_SUPABASE_URL}/rest/v1/whatsapp_messages", w._crm_headers(),
                      {"phone": inlist, "user_id": f"eq.{w.CRM_OWNER_USER_ID}",
                       "direction": "eq.outbound", "created_at": f"gte.{since}",
                       "select": "phone,created_at,metadata"})
    by_client, manual = defaultdict(list), defaultdict(list)
    for c in clients:
        by_client[c.get("phone")].append(c)
    for m in outbound:
        # The bot's own sends (replies, templates) are not the owner calling.
        if ((m.get("metadata") or {}).get("source")) != "asthra_ai_bot":
            manual[m.get("phone")].append(m.get("created_at"))
    return by_client, manual


def _bump(counts, key):
    counts[key] = counts.get(key, 0) + 1


def run(now=None) -> dict:
    """One pass. Returns counts (no PII). Never raises."""
    if not enabled():
        return {"mode": "off"}
    now = now or datetime.now(timezone.utc)
    if not cr.in_call_hours(now):
        return {"skipped": "outside_call_hours"}
    counts = {}
    try:
        rows = brain_history(now)
    except Exception as e:
        print(f"CALL_REMINDERS brain_read_failed type={type(e).__name__}")
        return {"error": "brain_read_failed"}
    by_phone = defaultdict(list)
    for r in rows:
        by_phone[r.get("phone")].append(r)
    try:
        staff = set(w.staff_and_owner_numbers())
    except Exception:
        staff = set()
    today = cr.ist_day(now)
    due = []
    for phone, history in by_phone.items():
        if not phone or phone in staff:
            continue
        p = cr.promise(history)
        if not p:
            continue
        _bump(counts, "promises")
        chosen = cr._ts(p["chosen_at"])
        if p["declined_after"]:
            _bump(counts, "declined")
            continue
        if not chosen or now - chosen > timedelta(days=cr.MAX_AGE_DAYS):
            _bump(counts, "too_old")
            continue
        if cr.due_at(p["slot"], chosen) > now:
            _bump(counts, "not_due_yet")
            continue
        markers = [r.get("content") or "" for r in history if r.get("role") == "system"]
        if cr.reminded_today(markers, p["chosen_at"], today):
            _bump(counts, "reminded_today")
            continue
        due.append((phone, history, p))
    if not due:
        print("CALL_REMINDERS " + json.dumps(counts, sort_keys=True))
        return counts
    try:
        clients, manual = crm_state([d[0] for d in due],
                                    (now - timedelta(days=cr.MAX_AGE_DAYS + 3)).isoformat())
    except Exception as e:
        # Fail closed: without the CRM we cannot tell a done call from a missed one.
        print(f"CALL_REMINDERS crm_read_failed type={type(e).__name__}")
        return dict(counts, error="crm_read_failed")
    items = []
    for phone, history, p in due:
        rows = clients.get(phone) or [{}]
        if any(cr.handled(p["chosen_at"], c, manual.get(phone)) for c in rows):
            _bump(counts, "handled")
            continue
        state = bairavi.established_from_history(
            [r for r in history if r.get("role") in ("user", "assistant")])
        items.append({"phone": phone,
                      "name": rows[0].get("name") or bairavi.display_name(state.get("name")),
                      "kva": state.get("capacity_kva"),
                      "place": state.get("delivery_location") or state.get("location"),
                      "slot": p["slot"], "chosen_at": p["chosen_at"],
                      "complained": p["complained_after"]})
    if items:
        try:
            delivered = w.notify_owner(cr.compose(items, now))
        except Exception as e:
            print(f"CALL_REMINDERS notify_failed type={type(e).__name__}")
            delivered = 0
        if delivered:
            # Recorded only after a delivered reminder, so a failed one is retried.
            w.save_messages([(it["phone"], "system", cr.marker(it["chosen_at"], today))
                             for it in items])
            counts["reminded"] = len(items)
        else:
            counts["notify_failed"] = len(items)
    print("CALL_REMINDERS " + json.dumps(counts, sort_keys=True))
    return counts
