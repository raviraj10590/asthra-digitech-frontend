#!/usr/bin/env python3
"""The Brain's learning loop (owner request 2026-10-01: "shadow mode ai learning loop").

    shadow mode (live, silent)  ->  weekly report (this file, owner's Mac)
          ->  a lesson is confirmed  ->  `promote` adds it to the lesson bank
          ->  tests/test_learned_cases.py enforces it on every future change

1. REPORT (Mondays, from ops/nara_jobs.py, or `learning_report.py report`)
   Every Bairavi message of the last 7 days where the AI interpreter read
   something different from the rules (shadow mode), shown WITH the
   customer's words, plus the chats the 08:15 health check flagged.

   Shadow rows hold no customer words (Design B, owner-approved 2026-09-27):
   turn_key = HMAC-SHA256(SHADOW_TURN_KEY, brain message ref)[:32]. The words
   are found here, on the owner's Mac, by recomputing that HMAC for each
   bic_webhook_events.brain_message_id and following its wamid to the CRM
   transcript. The key is read from the macOS Keychain and never printed;
   the report is written to .learning/ (git-ignored), never sent anywhere.

2. PROMOTE (`learning_report.py promote <id> field=value ...`)
   Records the RIGHT reading of one message in tests/data/learned_cases.json.
   Phone numbers are masked before anything is written.

Read-only against both databases.
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BRAIN_PROJECT = "kpzprllzgqlqkqgcgrbp"
CRM_PROJECT = "liftfuckrabwdyzbjnnx"
KEYCHAIN_SERVICE = "asthra-shadow-turn-key"
OUT_DIR = os.path.join(ROOT, ".learning")
BANK = os.path.join(ROOT, "tests", "data", "learned_cases.json")
IST = timezone(timedelta(hours=5, minutes=30))
DAYS = 7
PROMOTABLE = ("capacity_kva", "quantity", "application", "delivery_location", "callback",
              "delivery_same", "asked_price", "asked_discount", "declined", "is_ack")
_WRITE = re.compile(r"\b(insert|update|delete|alter|drop|create|truncate|grant|revoke)\b", re.I)


# ───────────────────────────────────────────── pure helpers (tested)

def turn_key(secret: str, ref: str) -> str:
    """Exactly api/webhook.py shadow_turn_key."""
    return hmac.new(secret.encode("utf-8"), str(ref).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def mask(text: str) -> str:
    return re.sub(r"\+?\d[\d ]{8,}\d", "[number]", text or "")


def lessons(shadow_rows: list, refs: list, bodies: dict, secret: str) -> list:
    """Disagreements joined to the customer's words. `refs` are
    (brain_message_id, wamid) pairs; `bodies` maps wamid -> text."""
    by_key = {turn_key(secret, r): w for r, w in refs if r and w}
    out = []
    for row in shadow_rows:
        diffs = row.get("diffs") or {}
        conflicts = row.get("conflict_fields") or []
        rejected = row.get("rejected") or []
        if not (diffs or conflicts or rejected or row.get("status") == "invalid"):
            continue
        wamid = by_key.get(row.get("turn_key"))
        text = bodies.get(wamid) if wamid else None
        out.append({
            "id": (row.get("turn_key") or "")[:8],
            "at": row.get("created_at"),
            "text": mask(text) if text else None,
            "awaiting": row.get("awaiting") or [],
            "status": row.get("status"),
            "conflicts": conflicts,
            "diffs": diffs,
            "rejected": rejected,
        })
    return out


def render(items: list, flags: list, now: datetime) -> str:
    d = now.astimezone(IST).strftime("%d %b %Y")
    lines = [f"# Brain learning report — week to {d}", "",
             f"{len(items)} message(s) where the AI read something different from the rules; "
             f"{len(flags)} chat(s) flagged by the health check.", "",
             "To make a lesson permanent:",
             "`python3 ops/learning_report.py promote <id> field=value ...`", ""]
    if items:
        lines += ["## AI vs rules", ""]
    for it in items:
        lines.append(f"### `{it['id']}` — {it['text']!r}" if it["text"] else
                     f"### `{it['id']}` — (message not found in the CRM)")
        lines.append(f"- waiting for: {', '.join(it['awaiting']) or '—'} · status: {it['status']}")
        for f, v in (it["diffs"] or {}).items():
            lines.append(f"- **{f}**: rules = `{v.get('parser')}` · AI = `{v.get('shadow')}`")
        for f, r in it["rejected"] or []:
            lines.append(f"- AI proposal for **{f}** refused by the validator ({r})")
        lines.append("")
    if flags:
        lines += ["## Health-check flags", ""]
        lines += [f"- **{f['name'] or '—'}** (…{(f['phone'] or '')[-4:]}): {f['note']}" for f in flags]
        lines.append("")
    return "\n".join(lines)


def parse_expectations(pairs: list) -> dict:
    """['application=AGRICULTURE', 'quantity=2', 'delivery_same=true'] -> typed dict."""
    out = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"expected field=value, got {p!r}")
        k, v = p.split("=", 1)
        if k not in PROMOTABLE:
            raise ValueError(f"{k!r} is not a promotable field ({', '.join(PROMOTABLE)})")
        low = v.strip().lower()
        out[k] = (None if low in ("none", "null", "-") else True if low == "true"
                  else False if low == "false" else int(v) if v.strip().isdigit() else v.strip())
    return out


def add_case(bank: list, item: dict, expect: dict, now: datetime) -> list:
    if not item.get("text"):
        raise ValueError("this lesson has no customer text to test against")
    if any(c["text"] == item["text"] and c["awaiting"] == item["awaiting"] for c in bank):
        raise ValueError("already in the lesson bank")
    return bank + [{"id": item["id"], "text": mask(item["text"]), "awaiting": item["awaiting"],
                    "expect": expect, "added": now.astimezone(IST).date().isoformat()}]


# ───────────────────────────────────────────── I/O

def _sql(project: str, query: str):
    s = query.strip().lower()
    if not s.startswith(("select", "with")) or _WRITE.search(query):
        raise ValueError("read-only")
    token = open(os.path.expanduser("~/.supabase/access-token")).read().strip()
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project}/database/query",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "asthra-learning-report"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    if isinstance(out, dict) and out.get("message"):
        raise RuntimeError(out["message"][:200])
    return out


def secret() -> str:
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def gather(now: datetime):
    key = secret()
    if not key:
        raise SystemExit(f"no shadow key in Keychain service {KEYCHAIN_SERVICE}")
    shadow = _sql(BRAIN_PROJECT, f"select turn_key, created_at, status, awaiting, conflict_fields, "
                                 f"diffs, rejected from public.bairavi_shadow_interpretations "
                                 f"where created_at > now() - interval '{DAYS} days' order by created_at")
    refs = [(r["brain_message_id"], r["wamid"]) for r in _sql(
        BRAIN_PROJECT, f"select brain_message_id, wamid from public.bic_webhook_events "
                       f"where created_at > now() - interval '{DAYS + 1} days'")]
    wamids = [w for _, w in refs if w]
    bodies = {}
    for i in range(0, len(wamids), 200):
        chunk = ",".join("'" + w.replace("'", "''") + "'" for w in wamids[i:i + 200])
        for r in _sql(CRM_PROJECT, f"select wa_message_id, body from public.whatsapp_messages "
                                   f"where wa_message_id in ({chunk})"):
            bodies[r["wa_message_id"]] = r["body"]
    flags = _sql(CRM_PROJECT, "select c.name, c.phone, f.note from public.follow_ups f "
                              "join public.clients c on c.id = f.client_id "
                              f"where f.note like '🤖 Bot check:%' and f.due_date > "
                              f"(now() - interval '{DAYS} days')::date order by f.due_date")
    return lessons(shadow, refs, bodies, key), flags


def report() -> str:
    now = datetime.now(timezone.utc)
    items, flags = gather(now)
    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.join(OUT_DIR, "learning-" + now.astimezone(IST).date().isoformat())
    with open(stem + ".md", "w") as f:
        f.write(render(items, flags, now))
    with open(stem + ".json", "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    print(f"learning report: {len(items)} lessons, {len(flags)} flags -> {stem}.md")
    return stem


def promote(lesson_id: str, pairs: list):
    now = datetime.now(timezone.utc)
    reports = sorted(p for p in os.listdir(OUT_DIR) if p.endswith(".json")) if os.path.isdir(OUT_DIR) else []
    item = None
    for name in reversed(reports):
        for it in json.load(open(os.path.join(OUT_DIR, name))):
            if it["id"] == lesson_id:
                item = it
                break
        if item:
            break
    if not item:
        raise SystemExit(f"no lesson {lesson_id} in {OUT_DIR}")
    bank = json.load(open(BANK)) if os.path.exists(BANK) else []
    bank = add_case(bank, item, parse_expectations(pairs), now)
    os.makedirs(os.path.dirname(BANK), exist_ok=True)
    with open(BANK, "w") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)
    print(f"added lesson {lesson_id} to {os.path.relpath(BANK, ROOT)}; run the tests to see it enforced")


def main(argv):
    if len(argv) >= 2 and argv[1] == "promote":
        if len(argv) < 4:
            raise SystemExit("usage: learning_report.py promote <id> field=value ...")
        promote(argv[2], argv[3:])
    else:
        report()


if __name__ == "__main__":
    main(sys.argv)
