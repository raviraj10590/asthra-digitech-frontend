"""Bairavi follow-up sweep — ask again, once, when nobody answered.

Owner's ruling, 2026-09-17: "if they not replied your question you ask them
one hour later again."

Every rule about WHETHER to nudge lives in nudge.py, which is pure and
tested offline. This file owns only what the runtime owns: the cron gate, the
queries, and the send.

NO NEW TABLES. What a reply was waiting for is recorded in the transcript row
the Bairavi branch already writes (bairavi.flow_marker), and a nudge writes
its own marker there too — so "did we already ask again" is answered by the
same history the bot already reads.

SCHEDULING, STATED PLAINLY: Vercel Hobby caps at 2 crons and both are in use
(digest, evaluate), so this endpoint is NOT in vercel.json. It is built to be
called hourly by a pg_cron job on the Brain's Supabase project — the pattern
the CRM already uses — and until that job exists this sweep does not run. See
supabase/migrations/…_bairavi_nudge_hourly.sql.

PRIVACY: logs carry counts, reasons and the last four digits of a number.
Never a name, never message text.
"""

import json, os, sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asthra_deal
import bairavi
import learned
import nudge as nudge_rules

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",
                                 "https://kpzprllzgqlqkqgcgrbp.supabase.co")
# Server-only credential (Phase 1A, 2026-10-01): reads and writes the Brain's
# private whatsapp_messages. The project's public anon key is NOT used here.
SUPABASE_SERVER_KEY    = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

# A sweep must never run away. Even a broken query cannot cost more than this
# many messages, which is the difference between a bug and an incident.
MAX_SENDS_PER_RUN = 25
CANDIDATE_LOOKBACK_HOURS = 24


def _headers():
    return {"apikey": SUPABASE_SERVER_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVER_KEY}",
            "Content-Type": "application/json"}


def _parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def candidates(now):
    """Phones whose most recent Bairavi reply is still waiting on an answer.

    Filtered in the query to rows that actually carry `awaiting=`, so a
    conversation that was fully answered is never fetched at all.
    """
    since = (now - timedelta(hours=CANDIDATE_LOOKBACK_HOURS)).isoformat()
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_headers(),
            params={"select": "phone", "role": "eq.assistant",
                    "content": "like.*awaiting=*",
                    "created_at": f"gte.{since}",
                    "order": "created_at.desc", "limit": "500"},
            timeout=10,
        )
        if not r.ok:
            print(f"BAIRAVI_NUDGE_CANDIDATES_FAILED status={r.status_code}")
            return []
        seen, out = set(), []
        for row in r.json():
            p = row.get("phone")
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out
    except Exception as e:
        print(f"BAIRAVI_NUDGE_CANDIDATES_FAILED type={type(e).__name__}")
        return []


def conversation(phone):
    """Recent rows for one phone, newest first, with timestamps."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers=_headers(),
            params={"select": "role,content,created_at", "phone": f"eq.{phone}",
                    "order": "created_at.desc,id.desc", "limit": "60"},
            timeout=10,
        )
        if not r.ok:
            print(f"BAIRAVI_NUDGE_FETCH_FAILED status={r.status_code} "
                  f"phone=...{phone[-4:]}")
            return None
        return r.json()
    except Exception as e:
        print(f"BAIRAVI_NUDGE_FETCH_FAILED type={type(e).__name__} "
              f"phone=...{phone[-4:]}")
        return None


def read_state(rows, now):
    """Turn a conversation into the five facts nudge.decide needs.

    Rows arrive newest first, which is the order these questions are asked
    in: what did we last ask, has anything happened since, and is the chat
    paused.
    """
    awaiting, asked_at = (), None
    replied_since = False
    nudges_since = 0
    paused = False

    # Pause first, on the same rule fetch_context uses: the newest BOT_* row
    # wins, and only within 24 hours.
    for row in rows:
        if row.get("role") == "system" and (row.get("content") or "").startswith("BOT_"):
            ts = _parse_ts(row.get("created_at"))
            fresh = ts is not None and (now - ts) < timedelta(hours=24)
            paused = row.get("content") == "BOT_PAUSED" and fresh
            break

    # Then walk back to the last reply that was waiting for something,
    # counting what has happened since.
    for row in rows:
        role = row.get("role")
        content = row.get("content") or ""
        if role == "user":
            replied_since = True
            break
        if role == "assistant":
            if nudge_rules.NUDGE_MARKER in content:
                nudges_since += 1
                continue
            fields = bairavi.marker_awaiting(content)
            if fields:
                awaiting = fields
                asked_at = _parse_ts(row.get("created_at"))
            break

    return {"awaiting": awaiting, "asked_at": asked_at,
            "customer_replied_since": replied_since,
            "nudges_since": nudges_since, "paused": paused}


def send(phone, body):
    """One WhatsApp text. Returns True only when Meta accepted it."""
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone, "type": "text",
                  "text": {"body": body, "preview_url": False}},
            timeout=10,
        )
        if not r.ok:
            # STATUS ONLY. A Meta error body echoes the message we just sent.
            print(f"BAIRAVI_NUDGE_SEND_FAILED status={r.status_code} "
                  f"phone=...{phone[-4:]}")
        return r.ok
    except Exception as e:
        print(f"BAIRAVI_NUDGE_SEND_FAILED type={type(e).__name__} "
              f"phone=...{phone[-4:]}")
        return False


def record(phone, awaiting):
    """Write the nudge into the transcript.

    CHECKED, and it matters more here than usual: if this write is lost the
    next run has no memory of the nudge and would send it again. A failure is
    therefore reported loudly rather than swallowed.
    """
    marker = f"{nudge_rules.NUDGE_MARKER} awaiting={','.join(awaiting)}"
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
            headers={**_headers(), "Prefer": "return=minimal"},
            json=[{"phone": phone, "role": "assistant", "content": marker}],
            timeout=10,
        )
        if not r.ok:
            print(f"BAIRAVI_NUDGE_RECORD_FAILED status={r.status_code} "
                  f"phone=...{phone[-4:]} — this nudge may repeat")
        return r.ok
    except Exception as e:
        print(f"BAIRAVI_NUDGE_RECORD_FAILED type={type(e).__name__} "
              f"phone=...{phone[-4:]} — this nudge may repeat")
        return False


def run_sweep(now=None):
    now = now or datetime.now(timezone.utc)
    counts = {"considered": 0, "sent": 0, "send_failed": 0}
    sent = 0

    for phone in candidates(now):
        if sent >= MAX_SENDS_PER_RUN:
            counts["capped"] = counts.get("capped", 0) + 1
            continue
        rows = conversation(phone)
        if rows is None:
            counts["fetch_failed"] = counts.get("fetch_failed", 0) + 1
            continue
        counts["considered"] += 1

        state = read_state(rows, now)
        verdict = nudge_rules.decide(now=now, **state)
        if verdict != nudge_rules.SEND:
            counts[verdict] = counts.get(verdict, 0) + 1
            continue

        known = bairavi.established_from_history(
            [{"role": r.get("role"), "content": r.get("content")}
             for r in reversed(rows)])
        body = nudge_rules.compose(state["awaiting"], bairavi.question_for, known)

        if send(phone, body):
            record(phone, state["awaiting"])
            sent += 1
            counts["sent"] += 1
            print(f"BAIRAVI_NUDGE_SENT phone=...{phone[-4:]} "
                  f"awaiting={','.join(state['awaiting'])}")
        else:
            counts["send_failed"] += 1

    print(nudge_rules.summarise(counts))
    return counts


# ── Asthra deal follow-ups (owner, 2026-11-02) ─────────────────────────────
# Rides on this hourly job rather than a cron of its own (Hobby's two are
# taken). Every rule is in asthra_deal.py; this is only reads and sends.
ASTHRA_MAX_SENDS_PER_RUN = 15
ASTHRA_LOOKBACK_DAYS = 60
GRAPH = "https://graph.facebook.com/v19.0"


def asthra_candidates(now):
    """Phones whose chat carries a deal sign (a lead alerted, a quotation
    asked for, a price sent) in the lookback."""
    since = (now - timedelta(days=ASTHRA_LOOKBACK_DAYS)).isoformat()
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/whatsapp_messages", headers=_headers(),
            params={"select": "phone", "role": "eq.system",
                    "content": f"in.({','.join(asthra_deal.DEAL_SIGNS)})",
                    "created_at": f"gte.{since}",
                    "order": "created_at.desc", "limit": "1000"},
            timeout=10)
        if not r.ok:
            print(f"ASTHRA_FOLLOWUP_CANDIDATES_FAILED status={r.status_code}")
            return []
        return list(dict.fromkeys(x["phone"] for x in r.json() if x.get("phone")))
    except Exception as e:
        print(f"ASTHRA_FOLLOWUP_CANDIDATES_FAILED type={type(e).__name__}")
        return []


def asthra_template_approved() -> bool:
    """Is the follow-up template APPROVED in the account that owns the bot's
    number? Checked from the sender's side, as meta_leads_sync does."""
    auth = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        phone = requests.get(f"{GRAPH}/{PHONE_NUMBER_ID}", headers=auth,
                             params={"fields": "health_status"}, timeout=10).json()
        waba = next((e.get("id") for e in (phone.get("health_status") or {}).get("entities") or []
                     if e.get("entity_type") == "WABA"), None)
        if not waba:
            return False
        rows = requests.get(f"{GRAPH}/{waba}/message_templates", headers=auth,
                            params={"name": asthra_deal.TEMPLATE_NAME,
                                    "fields": "name,status,language"}, timeout=10).json().get("data") or []
        return any(r.get("name") == asthra_deal.TEMPLATE_NAME
                   and r.get("language") == asthra_deal.TEMPLATE_LANGUAGE
                   and r.get("status") == "APPROVED" for r in rows)
    except Exception as e:
        print(f"ASTHRA_TEMPLATE_CHECK_FAILED type={type(e).__name__}")
        return False


def send_template(phone):
    try:
        r = requests.post(
            f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone, "type": "template",
                  "template": {"name": asthra_deal.TEMPLATE_NAME,
                               "language": {"code": asthra_deal.TEMPLATE_LANGUAGE}}},
            timeout=10)
        if not r.ok:
            print(f"ASTHRA_FOLLOWUP_SEND_FAILED status={r.status_code} phone=...{phone[-4:]}")
        return r.ok
    except Exception as e:
        print(f"ASTHRA_FOLLOWUP_SEND_FAILED type={type(e).__name__} phone=...{phone[-4:]}")
        return False


def save_assistant(phone, content):
    """The follow-up into the transcript, so the next run knows the day."""
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/whatsapp_messages",
                          headers={**_headers(), "Prefer": "return=minimal"},
                          json=[{"phone": phone, "role": "assistant", "content": content}],
                          timeout=10)
        if not r.ok:
            print(f"ASTHRA_FOLLOWUP_RECORD_FAILED status={r.status_code} "
                  f"phone=...{phone[-4:]} — this follow-up may repeat")
        return r.ok
    except Exception as e:
        print(f"ASTHRA_FOLLOWUP_RECORD_FAILED type={type(e).__name__} "
              f"phone=...{phone[-4:]} — this follow-up may repeat")
        return False


def run_asthra_followups(now=None, staff=()):
    now = now or datetime.now(timezone.utc)
    counts = {"considered": 0, "sent": 0, "send_failed": 0}
    staff = {p[-10:] for p in staff if p}
    template_ok = None
    for phone in asthra_candidates(now):
        if phone[-10:] in staff:
            continue
        if counts["sent"] >= ASTHRA_MAX_SENDS_PER_RUN:
            counts["capped"] = counts.get("capped", 0) + 1
            continue
        rows = conversation(phone)
        if rows is None:
            counts["fetch_failed"] = counts.get("fetch_failed", 0) + 1
            continue
        counts["considered"] += 1
        verdict, day = asthra_deal.decide(rows, now)
        if verdict != asthra_deal.SEND:
            counts[verdict] = counts.get(verdict, 0) + 1
            continue
        if asthra_deal.window_open(rows, now):
            text = asthra_deal.followup_text(day)
            ok = send(phone, text)
        else:
            if template_ok is None:
                template_ok = asthra_template_approved()
            if not template_ok:
                counts["template_not_approved"] = counts.get("template_not_approved", 0) + 1
                continue
            text = asthra_deal.TEMPLATE_BODY
            ok = send_template(phone)
        if ok:
            save_assistant(phone, f"{text}\n{asthra_deal.marker(day)}")
            counts["sent"] += 1
            print(f"ASTHRA_FOLLOWUP_SENT phone=...{phone[-4:]} day={day}")
        else:
            counts["send_failed"] += 1
    print(asthra_deal.summarise(counts))
    return counts


def staff_numbers():
    """OWNER/STAFF numbers, never followed up. Bootstrap env list + bot_roles."""
    nums = [p.strip() for p in os.environ.get("OWNER_PHONE", "918861369951").split(",") if p.strip()]
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/bot_roles", headers=_headers(),
                         params={"select": "phone", "active": "eq.true",
                                 "role": "in.(OWNER,STAFF)"}, timeout=10)
        if r.ok:
            nums += [x.get("phone") or "" for x in r.json()]
    except Exception as e:
        print(f"ASTHRA_STAFF_READ_FAILED type={type(e).__name__}")
    return nums


# ── Auto-suggest (owner, 2026-11-02) ──────────────────────────────────────
# The owner's hand-written CRM replies of the last few hours, paired with the
# customer question they answered, offered to the owner to learn. Rules in
# learned.py; dedupe by the CRM message id (learned_answers.source_ref).
LEARN_LOOKBACK_HOURS = 3


def _crm():
    url = os.environ.get("CRM_SUPABASE_URL", "")
    key = os.environ.get("CRM_SUPABASE_SERVICE_KEY", "")
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


# Only the bot's own two businesses learn (owner, 2026-11-02): a chat whose
# CRM lead belongs to any OTHER business (a client's leads) is never offered,
# so another client's answers cannot reach Asthra's or Bairavi's customers.
CRM_SLUG_TO_BUSINESS = {"bairavi-trans-solutions": learned.BAIRAVI,
                        "asthra-digitech": learned.ASTHRA}


def _business_of(phone, crm_url, crm_headers):
    """learned.BAIRAVI / learned.ASTHRA, or None for another business's chat
    (or one that cannot be read — skipping is the safe direction)."""
    try:
        r = requests.get(f"{crm_url}/rest/v1/clients", headers=crm_headers,
                         params={"select": "business_id,source", "phone": f"eq.{phone}"}, timeout=10)
        r.raise_for_status()
        clients = r.json()
        biz_ids = {c["business_id"] for c in clients if c.get("business_id")}
        slugs = set()
        if biz_ids:
            b = requests.get(f"{crm_url}/rest/v1/businesses", headers=crm_headers,
                             params={"select": "slug", "id": f"in.({','.join(biz_ids)})"}, timeout=10)
            b.raise_for_status()
            slugs = {x.get("slug") for x in b.json()}
        if any(s not in CRM_SLUG_TO_BUSINESS for s in slugs):
            return None
        if learned.BAIRAVI in {CRM_SLUG_TO_BUSINESS[s] for s in slugs} or any(
                c.get("source") == "bairavi-transformer" for c in clients):
            return learned.BAIRAVI
        t = requests.get(f"{SUPABASE_URL}/rest/v1/whatsapp_messages", headers=_headers(),
                         params={"select": "id", "phone": f"eq.{phone}", "role": "eq.assistant",
                                 "content": f"like.*{bairavi.FLOW_MARKER}*", "limit": "1"},
                         timeout=10)
        t.raise_for_status()
        return learned.BAIRAVI if t.json() else learned.ASTHRA
    except Exception as e:
        print(f"LEARN_BUSINESS_UNKNOWN type={type(e).__name__} phone=...{phone[-4:]}")
        return None


def run_learn_suggestions(now=None, staff=(), notify=None):
    now = now or datetime.now(timezone.utc)
    counts = {"pairs": 0, "suggested": 0}
    url, headers = _crm()
    owner_id = os.environ.get("CRM_OWNER_USER_ID", "")
    if not (url and owner_id):
        counts["crm_not_configured"] = 1
        return counts
    staff10 = {p[-10:] for p in staff if p}
    since = (now - timedelta(hours=LEARN_LOOKBACK_HOURS)).isoformat()
    try:
        r = requests.get(f"{url}/rest/v1/whatsapp_messages", headers=headers,
                         params={"select": "phone", "direction": "eq.outbound",
                                 "message_type": "eq.text", "metadata->>source": "is.null",
                                 "user_id": f"eq.{owner_id}", "created_at": f"gte.{since}",
                                 "limit": "200"}, timeout=10)
        r.raise_for_status()
        phones = list(dict.fromkeys(x["phone"] for x in r.json()
                                    if x.get("phone") and x["phone"][-10:] not in staff10))
    except Exception as e:
        print(f"LEARN_CANDIDATES_FAILED type={type(e).__name__}")
        return counts
    fresh = []
    for phone in phones:
        try:
            r = requests.get(f"{url}/rest/v1/whatsapp_messages", headers=headers,
                             params={"select": "id,phone,direction,message_type,body,created_at,metadata",
                                     "phone": f"eq.{phone}", "user_id": f"eq.{owner_id}",
                                     "created_at": f"gte.{(now - timedelta(hours=LEARN_LOOKBACK_HOURS + learned.PAIR_WINDOW_HOURS)).isoformat()}",
                                     "order": "created_at.asc", "limit": "200"}, timeout=10)
            r.raise_for_status()
            msgs = [dict(m, created_at=_parse_ts(m.get("created_at")),
                         source=(m.get("metadata") or {}).get("source"))
                    for m in r.json() if _parse_ts(m.get("created_at"))]
        except Exception as e:
            print(f"LEARN_FETCH_FAILED type={type(e).__name__} phone=...{phone[-4:]}")
            continue
        found = learned.pairs(msgs)
        counts["pairs"] += len(found)
        if not found:
            continue
        biz = _business_of(phone, url, headers)
        if biz is None:
            counts["other_business"] = counts.get("other_business", 0) + 1
            continue
        rows = [{"business": biz, "question": q["body"].strip()[:1000],
                 "answer": a["body"].strip()[:1000], "source_ref": str(a["id"])} for q, a in found]
        try:
            ins = requests.post(f"{SUPABASE_URL}/rest/v1/learned_answers",
                                headers={**_headers(),
                                         "Prefer": "resolution=ignore-duplicates,return=representation"},
                                params={"on_conflict": "source_ref"}, json=rows, timeout=10)
            ins.raise_for_status()
            fresh += ins.json()
        except Exception as e:
            print(f"LEARN_SAVE_FAILED type={type(e).__name__}")
    for row in fresh[:learned.MAX_SUGGESTIONS_PER_RUN]:
        if notify:
            notify(learned.suggestion_text(row))
        counts["suggested"] += 1
    print("LEARN_SUGGEST_RUN " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return counts


def _notify_owner(text):
    import webhook as w          # heavy; only when there is something to say
    w.notify_owner(text)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # THE SAME GATE digest.py and evaluate.py use — one cron-auth
        # contract, not three. `key` must be non-empty so a request carrying
        # no key cannot compare equal to an unset VERIFY_TOKEN.
        ua = self.headers.get("User-Agent", "")
        key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
        if "vercel-cron" not in ua and not (key and key == VERIFY_TOKEN):
            self.send_response(403)
            self.end_headers()
            return

        result = run_sweep()
        staff = staff_numbers()
        result["asthra"] = run_asthra_followups(staff=staff)
        result["learn"] = run_learn_suggestions(staff=staff, notify=_notify_owner)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
