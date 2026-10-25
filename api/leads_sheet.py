"""
Bairavi leads as CSV, for the owner's Google Sheet (owner's choice 2026-10-06:
"form na sheets ge connect maadu" -> a new sheet fed from the CRM).

The sheet holds one cell:  =IMPORTDATA("https://<brain>/api/leads_sheet?key=…")
Google refetches it about once an hour, so every lead the CRM has — Meta form
and WhatsApp alike — shows up there without anyone copying rows.

TEAM NOTES BACK INTO THE CRM (owner, 2026-10-06: "marketing guys e sheet nodi
call madtare matte entry madtare ... crm li gottagbeku"). The sheet's Apps
Script (sheet/leads_sheet.gs) POSTs {id, note, by} here when someone types in
the "Team note" column; the note is appended to that lead's CRM notes as
"📝 06 Oct 15:40 Sheet (by): …" and comes back in the "Call notes" column on
the next refresh. Only a lead of this source and owner can be written, and
only its notes, pipeline stage and last-contacted time.

STAGE FROM THE NOTE (owner, 2026-10-25: 308 of 318 leads still sat at "Lead"
because nobody moved them after calling). A note is written after a call, so
it means at least "Contacted"; clear words move it further (stage_from_note).
The stage only moves forward, "Lost" needs explicit words, a "Won" lead is
never touched, and a "Lost" lead comes back only when a note shows interest.

The key (LEADS_SHEET_KEY) is the only gate, so it is long, random and compared
in constant time; without it set the endpoint answers 503 rather than serving
anyone. Logs carry counts only — no name, phone or note.
"""
import json
import csv
import hmac
import io
import os
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

CRM_SUPABASE_URL = os.environ.get("CRM_SUPABASE_URL", "")
CRM_SUPABASE_SERVICE_KEY = os.environ.get("CRM_SUPABASE_SERVICE_KEY", "")
CRM_OWNER_USER_ID = os.environ.get("CRM_OWNER_USER_ID", "")
LEADS_SHEET_KEY = os.environ.get("LEADS_SHEET_KEY", "")
SOURCE = os.environ.get("LEADS_SHEET_SOURCE", "bairavi-transformer")

IST = timezone(timedelta(hours=5, minutes=30))
PAGE = 1000
MAX_PAGES = 10
HEADER = ["Date (IST)", "Name", "Phone", "Transformer", "Place", "Stage", "Last contacted (IST)", "Call notes", "CRM id"]
NOTE_MAX = 500
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _ist(ts: str) -> str:
    if not ts:
        return ""
    # Postgres writes "+00" or "+00:00" and 1–6 fraction digits; Python 3.9's
    # fromisoformat takes only "+HH:MM" and 3 or 6 digits.
    m = re.match(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d(?::?\d\d)?)?$", ts.strip())
    if not m:
        return ""
    tz = m.group(3) or "+00:00"
    tz = "+00:00" if tz == "Z" else (tz + ":00" if len(tz) == 3 else tz[:3] + ":" + tz[-2:])
    # "06 Oct 2026 · 15:09": a Sheet in a US locale read "06-10-2026" as 10
    # June and showed it as 46183.63 (owner, 2026-10-06). The "·" keeps Sheets
    # from converting it at all, so it reads the same in every locale.
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{tz}").astimezone(IST).strftime("%d %b %Y · %H:%M")


def _phone(raw: str) -> str:
    """+91 95905 59112 — spaced, so the sheet keeps it as text, not 9.19E+11."""
    d = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(d) == 12 and d.startswith("91"):
        return f"+91 {d[2:7]} {d[7:]}"
    if len(d) == 10:
        return f"+91 {d[:5]} {d[5:]}"
    return d


def _cell(v) -> str:
    """No formula injection: a cell never starts with = + - @."""
    s = str(v or "").strip()
    return " " + s if s[:1] in ("=", "+", "-", "@") else s


def parse_notes(notes: str) -> dict:
    """First line "Service: Transformer 25 kVA | City: davanagere"; the
    lines after it are the owner's call notes."""
    lines = (notes or "").splitlines()
    first, rest = (lines[0] if lines else ""), lines[1:]
    fields = {}
    for part in first.split("|"):
        k, sep, v = part.partition(":")
        if sep:
            fields[k.strip().lower()] = v.strip()
    if not fields:                     # no "Key: value" line — all of it is notes
        rest = lines
    return {"service": fields.get("service", ""), "city": fields.get("city", ""),
            "calls": " / ".join(l.strip() for l in rest if l.strip())}


def to_csv(rows: list) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(HEADER)
    for r in rows:
        n = parse_notes(r.get("notes"))
        w.writerow([_ist(r.get("created_at")), _cell(r.get("name")), _phone(r.get("phone")),
                    _cell(n["service"]), _cell(n["city"]), _cell(r.get("pipeline_stage")),
                    _ist(r.get("last_contacted_at")), _cell(n["calls"]), r.get("id") or ""])
    return out.getvalue()


def fetch_leads() -> list:
    headers = {"apikey": CRM_SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {CRM_SUPABASE_SERVICE_KEY}"}
    out = []
    for page in range(MAX_PAGES):
        r = requests.get(f"{CRM_SUPABASE_URL}/rest/v1/clients", headers=headers, timeout=10, params={
            "user_id": f"eq.{CRM_OWNER_USER_ID}", "source": f"eq.{SOURCE}",
            "select": "id,name,phone,notes,pipeline_stage,created_at,last_contacted_at",
            "order": "created_at.desc", "limit": str(PAGE), "offset": str(page * PAGE)})
        r.raise_for_status()
        rows = r.json()
        out.extend(rows)
        if len(rows) < PAGE:
            break
    return out


def note_line(note: str, by: str, now: datetime) -> str:
    """"📝 06 Oct 15:40 Sheet (Ravi): called, will visit Monday"."""
    note = " ".join((note or "").split())[:NOTE_MAX]
    by = " ".join((by or "").split())[:40]
    when = now.astimezone(IST).strftime("%d %b %H:%M")
    return f"📝 {when} Sheet{f' ({by})' if by else ''}: {note}"


def valid_note(body: dict):
    """(id, note, by) or None — an id that is a CRM uuid and a non-empty note."""
    lead_id = str(body.get("id") or "").strip().lower()
    note = " ".join(str(body.get("note") or "").split())
    if not _UUID.match(lead_id) or not note:
        return None
    return lead_id, note, str(body.get("by") or "")


# Order is the sales progression (CRM src/lib/leadStage.ts LEAD_STAGES); Lost is apart.
STAGES = ("Lead", "Contacted", "Interested", "Site Visit", "Negotiation", "Won")
# Checked top to bottom; the team writes fast Kanglish with typos ("not intrested", "cl back").
_STAGE_RULES = (
    ("Lost", re.compile(r"not\s*int\w*rest|no\s*interest|interest\s*illa|\bbeda\b|ಬೇಡ|no\s*need|not\s*requir|"
                        r"cancel|already\s*(bought|purchas|took)|wrong\s*number", re.I)),
    ("Won", re.compile(r"order\s*(confirm|placed|aay|done|final)|advance\s*(paid|receiv|band)|po\s*receiv|"
                       r"payment\s*receiv", re.I)),
    ("Negotiation", re.compile(r"quot\w*\s*(sent|kals|shared)|sent\s*(the\s*)?quot|negotiat|discount|"
                               r"rate\s*kam|price\s*(less|kam|high|jasti)|final\s*price", re.I)),
    ("Site Visit", re.compile(r"site\s*visit|visit\s*(madid|done|plan|fix|on|tomorrow|monday|next)|site\s*ge\s*hog", re.I)),
    ("Interested", re.compile(r"interest|ಆಸಕ್ತಿ|estimat|quot|share\s*(the\s*)?(price|rate|details)|"
                              r"send\s*(the\s*)?(price|rate|details)|need\s*\d+\s*kva", re.I)),
)


def stage_from_note(note: str) -> str:
    """The stage a team note points to; any note at all means "Contacted"."""
    for stage, rx in _STAGE_RULES:
        if rx.search(note or ""):
            return stage
    return "Contacted"


def next_stage(current: str, target: str):
    """The stage to store, or None to leave it: forward only, never touch Won."""
    current = current or "Lead"
    if current == "Won" or target == current:
        return None
    rank = {s: i for i, s in enumerate(STAGES)}
    if target == "Lost":
        return target                       # explicit "not interested"
    if current == "Lost":                   # only real interest brings a lost lead back
        return target if rank[target] >= rank["Interested"] else None
    return target if rank.get(target, 0) > rank.get(current, 0) else None


def save_note(lead_id: str, line: str, note: str = ""):
    """Append to THIS owner's lead of THIS source and move its stage if the note says so.

    Returns None if there is no such lead, else the new stage (or "" when it stayed)."""
    headers = {"apikey": CRM_SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {CRM_SUPABASE_SERVICE_KEY}",
               "Content-Type": "application/json"}
    where = {"id": f"eq.{lead_id}", "user_id": f"eq.{CRM_OWNER_USER_ID}", "source": f"eq.{SOURCE}"}
    r = requests.get(f"{CRM_SUPABASE_URL}/rest/v1/clients", headers=headers, timeout=10,
                     params=dict(where, select="notes,pipeline_stage"))
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    now = datetime.now(timezone.utc).isoformat()
    notes = ((rows[0].get("notes") or "").rstrip() + "\n" + line).strip()
    patch = {"notes": notes, "updated_at": now, "last_contacted_at": now}
    stage = next_stage(rows[0].get("pipeline_stage"), stage_from_note(note))
    if stage:
        patch["pipeline_stage"] = stage
    r = requests.patch(f"{CRM_SUPABASE_URL}/rest/v1/clients", headers=headers, timeout=10,
                       params=where, json=patch)
    r.raise_for_status()
    return stage or ""


def authorised(query: str) -> bool:
    given = (parse_qs(query).get("key") or [""])[0]
    return bool(LEADS_SHEET_KEY) and hmac.compare_digest(given.encode(), LEADS_SHEET_KEY.encode())


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if not (LEADS_SHEET_KEY and CRM_SUPABASE_URL and CRM_SUPABASE_SERVICE_KEY and CRM_OWNER_USER_ID):
            return self._send(503, "not configured\n")
        if not authorised(urlparse(self.path).query):
            print("LEADS_SHEET denied")
            return self._send(403, "forbidden\n")
        try:
            rows = fetch_leads()
        except Exception as e:
            print(f"LEADS_SHEET_FAILED type={type(e).__name__}")
            return self._send(502, "CRM unreachable\n")
        print(f"LEADS_SHEET ok rows={len(rows)}")
        return self._send(200, to_csv(rows), "text/csv; charset=utf-8")

    def do_POST(self):
        if not (LEADS_SHEET_KEY and CRM_SUPABASE_URL and CRM_SUPABASE_SERVICE_KEY and CRM_OWNER_USER_ID):
            return self._send(503, "not configured\n")
        if not authorised(urlparse(self.path).query):
            print("LEADS_SHEET_NOTE denied")
            return self._send(403, "forbidden\n")
        try:
            length = min(int(self.headers.get("Content-Length", 0) or 0), 8192)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, "bad json\n")
        parsed = valid_note(body if isinstance(body, dict) else {})
        if not parsed:
            return self._send(400, "need id and note\n")
        lead_id, note, by = parsed
        try:
            result = save_note(lead_id, note_line(note, by, datetime.now(timezone.utc)), note)
        except Exception as e:
            print(f"LEADS_SHEET_NOTE_FAILED type={type(e).__name__}")
            return self._send(502, "CRM unreachable\n")
        ok = result is not None
        print(f"LEADS_SHEET_NOTE {'saved' if ok else 'no-such-lead'}{f' stage={result}' if result else ''}")
        return self._send(200 if ok else 404, "saved\n" if ok else "no such lead\n")

    def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
