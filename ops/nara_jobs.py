#!/usr/bin/env python3
"""NaraRouter free-tier jobs, run every morning on the owner's Mac (08:15).

WHY THIS FILE EXISTS (2026-10-01)
  The owner asked where NaraRouter's daily free tokens could be useful. The
  one job built for it (CRM scripts/nara_call_list.py, 2026-09-23) had never
  run on schedule: launchd may not read ~/Documents, so every morning the log
  said "Operation not permitted" and the free quota went unused. This file
  lives under ~/Projects, which launchd can read, and does two jobs:

  1. LEAD SUMMARIES. One line per Bairavi lead with new customer messages —
     what they need, where, what they asked, any objection — written onto the
     CRM lead as a single "🧠" line in notes (replaced, never piled up). The
     9:00 call briefing and the CRM show it next to the lead.

  2. BOT HEALTH CHECK. Yesterday's conversations, checked two ways:
       deterministic  English paragraph to a Kannada writer; the same bot
                      message three times; a real message left unanswered
       model          an OK/ISSUE verdict with a short reason (advisory)
     Each flagged conversation becomes ONE CRM follow-up due today
     ("🤖 Bot check: ..."), which the 9:00 briefing counts.

WHERE FAILURE IS HARMLESS BY DESIGN
  Free models are slow (3-30 s) and may vanish. Nothing here is on the
  customer path: a failed call means a missing summary or check, never a
  missed reply. Every call is logged to api_key_activity (timings, sizes,
  outcome only — never the key, prompt, answer, phone, name or text).

WHAT LEAVES THE MAC
  Conversation text goes to NaraRouter, as it already did for the call list.
  Phone numbers are not sent: the transcript carries only CUSTOMER/BOT lines.

Secrets: NaraRouter key from macOS Keychain service "asthra-nararouter";
Supabase management token from ~/.supabase/access-token.
Env: CRM_OWNER_EMAIL (required), NARA_MODEL, DRY_RUN=1 (read + call, write nothing),
     LIMIT (stop after N conversations per job).
"""
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bairavi  # noqa: E402  (is_ack for "was this message owed a reply?")

CRM_PROJECT = "liftfuckrabwdyzbjnnx"
NARA_BASE = "https://router.bynara.id/v1"
NARA_UA = "curl/8.7.1"          # the router's Cloudflare rejects default Python user-agents
PROVIDER, KEY_LABEL = "nararouter", "NaraRouter free"
MODEL = os.environ.get("NARA_MODEL", "ling-3.0-flash-sante-free")
IST = timezone(timedelta(hours=5, minutes=30))
OWNER_LAST4 = ("9951", "8141")  # the owner's own numbers are test traffic, not leads
SOURCE = "bairavi-transformer"
SUMMARY_DAYS = 14
MAX_TRANSCRIPT_CHARS = 6000
TIMEOUT_S = 240
BOT_CHECK_TAG = "🤖 Bot check:"
SUMMARY_TAG = "🧠 AI"
REPLY_TOLERANCE_S = 5           # the CRM often stores the bot's reply 0-2 s BEFORE the message
UNANSWERED_AFTER_S = 600

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ───────────────────────────────────────────── pure helpers (tested)

_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}(?::?\d{2})?)?$")


def ts(iso: str) -> datetime:
    m = _ISO_RE.match((iso or "").strip())
    if not m:
        raise ValueError(f"unreadable timestamp {iso!r}")
    date, clock, frac, zone = m.groups()
    t = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S").replace(
        microsecond=int((frac or "0")[:6].ljust(6, "0")))
    if not zone or zone == "Z":
        return t.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    d = zone[1:].replace(":", "")
    return t.replace(tzinfo=timezone(sign * timedelta(hours=int(d[:2]), minutes=int(d[2:4] or 0))))


def stamp(t: datetime) -> str:
    t = t.astimezone(IST)
    return f"{t.day:02d} {MONTHS[t.month - 1]} {t.hour:02d}:{t.minute:02d}"


def transcript(messages: list) -> str:
    """CUSTOMER/BOT lines, oldest first, newest kept when too long. No phone numbers."""
    lines = []
    for m in sorted(messages, key=lambda m: m.get("created_at") or ""):
        body = re.sub(r"\+?\d[\d ]{8,}\d", "[number]", (m.get("body") or "").strip())
        if body:
            who = "CUSTOMER" if (m.get("direction") or "").startswith("in") else "BOT"
            lines.append(f"{who}: {body}")
    text = "\n".join(lines)
    return text[-MAX_TRANSCRIPT_CHARS:]


SUMMARY_SYSTEM = (
    "You read a WhatsApp conversation between Bairavi Trans Solutions, a transformer "
    "manufacturer, and a customer. Output ONE line and nothing else, exactly:\n"
    "sum=<max 20 English words: what the customer needs (kVA, how many, purpose), where, "
    "what they asked, any objection or hesitation>\n"
    "Only facts the CUSTOMER stated; leave out anything not stated (never write 'not stated'). "
    "Never guess. Never write a price or a phone number.")
_SUM_RE = re.compile(r"sum=([^\n`]+)")


def parse_summary(text: str):
    """The summary line, or None when the model gave nothing trustworthy."""
    hits = _SUM_RE.findall(text or "")
    if not hits:
        return None
    s = hits[-1].strip().strip('"').strip()
    # "delivery not stated kVA not stated" is padding, not information.
    s = re.sub(r"[\s,;]*\b[\w-]+ not (?:stated|mentioned|given|specified)\b", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;.-")
    if (not s or s.startswith("<") or s.endswith(">") or "₹" in s
            or re.search(r"\d{8,}", s) or len(s) > 200):
        return None
    return s


def summary_line(summary: str, now: datetime) -> str:
    return f"{SUMMARY_TAG} {stamp(now)} — {summary}"


def with_summary(notes: str, line: str) -> str:
    """notes with exactly one 🧠 line: the new one, at the end."""
    kept = [l for l in (notes or "").splitlines() if not l.startswith(SUMMARY_TAG)]
    return "\n".join([l for l in kept if l.strip()] + [line]).strip()


def summary_is_stale(notes: str, last_inbound: datetime, now: datetime) -> bool:
    """True when there is no summary, or the customer wrote after it was made."""
    for l in reversed((notes or "").splitlines()):
        m = re.match(rf"^{re.escape(SUMMARY_TAG)} (\d{{2}}) ([A-Z][a-z]{{2}}) (\d{{2}}):(\d{{2}}) — ", l)
        if m:
            made = datetime(now.astimezone(IST).year, MONTHS.index(m.group(2)) + 1, int(m.group(1)),
                            int(m.group(3)), int(m.group(4)), tzinfo=IST)
            if made > now:                      # "31 Dec" read in January
                made = made.replace(year=made.year - 1)
            return last_inbound > made
    return True


def _kannada(s: str) -> int:
    return sum(1 for ch in s or "" if "ಀ" <= ch <= "೿")


def _latin(s: str) -> int:
    return sum(1 for ch in s or "" if "a" <= ch.lower() <= "z")


def deterministic_issues(messages: list) -> list:
    """Problems the code can prove, in plain words, newest conversation order."""
    msgs = sorted(messages, key=lambda m: m.get("created_at") or "")
    issues = []
    wrote_kannada = False
    for m in msgs:
        body = m.get("body") or ""
        if (m.get("direction") or "").startswith("in"):
            wrote_kannada = wrote_kannada or _kannada(body) > 0
        elif wrote_kannada and _latin(body) >= 40 and _kannada(body) < _latin(body):
            issues.append("English reply to a customer writing Kannada")
            break
    outbound = [(m.get("body") or "").strip() for m in msgs
                if not (m.get("direction") or "").startswith("in")]
    for body in set(outbound):
        if body and len(body) > 20 and outbound.count(body) >= 3:
            issues.append("the same bot message was sent 3+ times")
            break
    for m in msgs:
        if not (m.get("direction") or "").startswith("in"):
            continue
        body = (m.get("body") or "").strip()
        if bairavi.is_lead_form(body) or len(body) < 4:
            continue
        f = bairavi.parse_followup(body, (), known={})
        if f.get("is_ack") or f.get("declined"):
            continue
        t = ts(m["created_at"])
        replied = any(not (o.get("direction") or "").startswith("in")
                      and -REPLY_TOLERANCE_S <= (ts(o["created_at"]) - t).total_seconds() <= UNANSWERED_AFTER_S
                      for o in msgs)
        if not replied:
            issues.append(f"no reply to “{body[:40]}”")
            break
    return issues


CHECK_SYSTEM = (
    "You review a WhatsApp conversation between a transformer manufacturer's BOT and a CUSTOMER. "
    "Did the BOT make a real mistake: ignore or misunderstand what the customer said, repeat itself, "
    "ask for something already given, answer in the wrong language, or sound rude? Output ONE line:\n"
    "verdict=OK\nor\nverdict=ISSUE; reason=<max 12 English words>")
_VERDICT_RE = re.compile(r"verdict=(OK|ISSUE)(?:\s*;\s*reason=([^\n`]+))?", re.I)


def parse_verdict(text: str):
    """(True, None) for OK, (False, reason) for an issue, None when unreadable."""
    hits = _VERDICT_RE.findall(text or "")
    if not hits:
        return None
    verdict, reason = hits[-1]
    if verdict.upper() == "OK":
        return True, None
    reason = (reason or "").strip()
    if not reason or reason.startswith("<") or len(reason) > 120:
        reason = "possible mistake (no reason given)"
    return False, reason


def bot_check_note(issues: list, model_reason) -> str:
    parts = list(issues) + ([f"AI: {model_reason}"] if model_reason else [])
    return f"{BOT_CHECK_TAG} " + "; ".join(parts)


def is_owner(phone: str) -> bool:
    return (phone or "")[-4:] in OWNER_LAST4


# ───────────────────────────────────────────── I/O

def nara_key() -> str:
    key = os.environ.get("NARA_API_KEY")
    if key:
        return key.strip()
    r = subprocess.run(["security", "find-generic-password", "-s", "asthra-nararouter", "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _sql(query: str):
    token = open(os.path.expanduser("~/.supabase/access-token")).read().strip()
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{CRM_PROJECT}/database/query",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "asthra-nara-jobs"})
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.load(r)
    if isinstance(out, dict) and out.get("message"):
        raise RuntimeError(out["message"][:200])
    return out


def q(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def call_model(key: str, system: str, text: str, job: str, activity: list) -> str:
    """content + reasoning of one call ('' on failure); one activity row appended."""
    act = {"created_at": datetime.now(timezone.utc).isoformat(), "provider": PROVIDER,
           "key_label": KEY_LABEL, "job": job, "model": MODEL, "outcome": "network_error",
           "http_status": None, "latency_ms": None, "input_chars": len(system) + len(text),
           "output_chars": 0, "est_tokens": 0}
    started = time.monotonic()
    out = ""
    try:
        req = urllib.request.Request(NARA_BASE + "/chat/completions", data=json.dumps({
            "model": MODEL, "max_tokens": 3000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": NARA_UA,
                     "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            act["http_status"] = r.status
            msg = json.load(r)["choices"][0]["message"]
        out = ((msg.get("content") or "") + "\n" + (msg.get("reasoning") or "")).strip()
        act["output_chars"] = len(out)
        act["outcome"] = "ok" if out else "no_answer"
    except urllib.error.HTTPError as e:
        act["http_status"], act["outcome"] = e.code, "http_error"
    except (TimeoutError, urllib.error.URLError) as e:
        act["outcome"] = "timeout" if "timed out" in str(e) else "network_error"
    except (KeyError, IndexError, ValueError):
        act["outcome"] = "no_answer"
    act["latency_ms"] = int((time.monotonic() - started) * 1000)
    if act["http_status"] == 200:
        act["est_tokens"] = math.ceil((act["input_chars"] + act["output_chars"]) / 3)
    activity.append(act)
    return out


def log_activity(rows: list, owner_email: str):
    if not rows:
        return
    cols = ("created_at", "provider", "key_label", "job", "model", "outcome", "http_status",
            "latency_ms", "input_chars", "output_chars", "est_tokens")
    values = ",\n".join(
        f"({q(r['created_at'])}::timestamptz, {q(r['provider'])}, {q(r['key_label'])}, {q(r['job'])}, "
        f"{q(r['model'])}, {q(r['outcome'])}, {q(r['http_status'])}::smallint, {q(r['latency_ms'])}::int, "
        f"{q(r['input_chars'])}::int, {q(r['output_chars'])}::int, {q(r['est_tokens'])}::int)"
        for r in rows)
    _sql(f"insert into public.api_key_activity (user_id, {', '.join(cols)})\n"
         f"select u.id, v.* from (values\n{values}\n) as v({', '.join(cols)})\n"
         f"cross join (select id from auth.users where lower(email) = lower({q(owner_email)}) limit 1) u")


def load(days: int):
    clients = _sql(f"select id, name, phone, notes, business_id, user_id, created_at from public.clients "
                   f"where source = {q(SOURCE)} and created_at > now() - interval '{int(days)} days'")
    clients = [c for c in clients if not is_owner(c.get("phone"))]
    if not clients:
        return [], {}
    phones = ",".join(q(c["phone"]) for c in clients)
    msgs = _sql(f"select phone, direction, body, created_at from public.whatsapp_messages "
                f"where phone in ({phones}) and created_at > now() - interval '{int(days)} days' "
                f"order by created_at")
    by_phone = {}
    for m in msgs:
        by_phone.setdefault(m["phone"], []).append(m)
    return clients, by_phone


def run(dry: bool, limit: int, owner_email: str) -> dict:
    now = datetime.now(timezone.utc)
    key = nara_key()
    if not key:
        raise SystemExit("no NaraRouter key in Keychain service asthra-nararouter")
    clients, by_phone = load(SUMMARY_DAYS)
    activity, stats = [], {"summaries": 0, "summary_failed": 0, "checked": 0, "flagged": 0}

    # 1. summaries for leads the customer has written to since the last one
    todo = []
    for c in clients:
        inbound = [m for m in by_phone.get(c["phone"], []) if (m.get("direction") or "").startswith("in")]
        if inbound and summary_is_stale(c.get("notes"), ts(inbound[-1]["created_at"]), now):
            todo.append(c)
    for c in todo[:limit or None]:
        s = parse_summary(call_model(key, SUMMARY_SYSTEM, transcript(by_phone[c["phone"]]),
                                     "lead_summary", activity))
        if not s:
            stats["summary_failed"] += 1
            continue
        stats["summaries"] += 1
        if not dry:
            _sql(f"update public.clients set notes = {q(with_summary(c.get('notes'), summary_line(s, now)))} "
                 f"where id = {q(c['id'])}")

    # 2. yesterday's conversations (IST day)
    y0 = (now.astimezone(IST) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    y1 = y0 + timedelta(days=1)
    due = now.astimezone(IST).date().isoformat()
    checked = 0
    for c in clients:
        msgs = by_phone.get(c["phone"], [])
        if not any(y0 <= ts(m["created_at"]) < y1 for m in msgs):
            continue
        if limit and checked >= limit:
            break
        checked += 1
        issues = deterministic_issues(msgs)
        reason = None
        if sum(1 for m in msgs if (m.get("direction") or "").startswith("in")) >= 3:
            v = parse_verdict(call_model(key, CHECK_SYSTEM, transcript(msgs), "bot_check", activity))
            if v and not v[0]:
                reason = v[1]
        if not issues and not reason:
            continue
        stats["flagged"] += 1
        note = bot_check_note(issues, reason)
        if not dry:
            _sql(f"insert into public.follow_ups (user_id, client_id, note, due_date, platform, business_id) "
                 f"select {q(c['user_id'])}, {q(c['id'])}, {q(note)}, {q(due)}::date, 'WhatsApp', "
                 f"{q(c.get('business_id'))} where not exists (select 1 from public.follow_ups "
                 f"where client_id = {q(c['id'])} and due_date = {q(due)}::date "
                 f"and note like {q(BOT_CHECK_TAG + '%')})")
    stats["checked"] = checked
    if not dry:
        log_activity(activity, owner_email)
    stats["api_calls"] = len(activity)
    stats["api_ok"] = sum(1 for a in activity if a["outcome"] == "ok")
    return stats


def main():
    owner_email = os.environ.get("CRM_OWNER_EMAIL", "")
    if not owner_email:
        raise SystemExit("CRM_OWNER_EMAIL is required")
    dry = os.environ.get("DRY_RUN") == "1"
    limit = int(os.environ.get("LIMIT", "0"))
    started = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    stats = run(dry, limit, owner_email)
    print(f"{started} nara_jobs {'DRY ' if dry else ''}{json.dumps(stats)}")
    # MONDAYS: the weekly learning report (ops/learning_report.py). Separate
    # and best-effort — it must never cost the summaries or the health check.
    if datetime.now(IST).weekday() == 0 and not dry:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import learning_report
            learning_report.report()
        except BaseException as e:          # SystemExit included: no key yet is not a crash
            print(f"learning report skipped: {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
