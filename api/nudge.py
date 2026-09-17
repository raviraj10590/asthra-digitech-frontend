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
import bairavi
import nudge as nudge_rules

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",
                                 "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY", "")

# A sweep must never run away. Even a broken query cannot cost more than this
# many messages, which is the difference between a bug and an incident.
MAX_SENDS_PER_RUN = 25
CANDIDATE_LOOKBACK_HOURS = 24


def _headers():
    return {"apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
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
                    "order": "created_at.desc", "limit": "40"},
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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
