"""
Asthra DigiTech — AI Conversation Evaluation Engine
Vercel Cron endpoint (separate from the bot). Runs on a schedule, reads
COMPLETED conversations from the last window, scores each with one GPT-4o-mini
call across 10 quality dimensions, and stores an internal report per chat.

Design guarantees:
  • Does NOT touch webhook.py / the conversation flow — zero customer latency.
  • Storage is env-gated on EVAL_TABLE — inert (read-only-ish) until configured.
  • "Completed" = a phone with no message in the last COMPLETED_AFTER_MIN minutes,
    so we never grade a chat still in progress.
  • Idempotent: a conversation already evaluated for its last-message timestamp
    is skipped, so re-running the cron never double-writes.
"""
import json, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

import requests

SUPABASE_URL   = os.environ.get("SUPABASE_URL", "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")
EVAL_TABLE     = os.environ.get("EVAL_TABLE", "").strip()          # e.g. "conversation_evals"
LOOKBACK_HOURS = int(os.environ.get("EVAL_LOOKBACK_HOURS", "24"))
COMPLETED_AFTER_MIN = int(os.environ.get("EVAL_COMPLETED_AFTER_MIN", "60"))
MAX_CONVERSATIONS   = int(os.environ.get("EVAL_MAX_CONVERSATIONS", "50"))  # cost guard

DIMENSIONS = [
    "response_quality", "lead_qualification", "buying_intent_detection",
    "objection_handling", "conversation_flow", "repeated_questions",
    "hallucination_risk", "policy_compliance", "meeting_conversion",
    "overall_score",
]

EVAL_SYSTEM = (
    "You are a QA analyst grading a WhatsApp sales conversation handled by an AI "
    "assistant for a digital-marketing agency. Score STRICTLY as integers 0-100 "
    "for each key: response_quality, lead_qualification, buying_intent_detection, "
    "objection_handling, conversation_flow, repeated_questions (100 = never "
    "repeated an answered question), hallucination_risk (100 = no invented facts, "
    "lower = risky claims), policy_compliance (pricing discipline, political "
    "neutrality, scope), meeting_conversion (did it ask for a meeting at the right "
    "time), overall_score. Also return: strengths (array of <=3 short phrases), "
    "weaknesses (array of <=3), improvement (ONE actionable sentence). "
    "Return ONLY valid JSON with these keys."
)


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────
def group_conversations(rows: list) -> dict:
    """messages rows → {phone: [rows sorted oldest-first]}."""
    convos: dict = {}
    for r in rows:
        convos.setdefault(r.get("phone"), []).append(r)
    for phone in convos:
        convos[phone].sort(key=lambda r: r.get("created_at", ""))
    return convos


def is_completed(msgs: list, now: datetime, after_min: int) -> bool:
    """True when the last message is older than `after_min` — chat has gone quiet."""
    if not msgs:
        return False
    try:
        last = datetime.fromisoformat(str(msgs[-1]["created_at"]).replace("Z", "+00:00"))
    except Exception:
        return False
    return (now - last) >= timedelta(minutes=after_min)


def build_transcript(msgs: list, max_turns: int = 40) -> str:
    """Render a role-tagged transcript for the grader (skips system markers)."""
    convo = [m for m in msgs if m.get("role") in ("user", "assistant")]
    lines = []
    for m in convo[-max_turns:]:
        who = "CUSTOMER" if m["role"] == "user" else "BOT"
        lines.append(f"{who}: {m.get('content', '')}")
    return "\n".join(lines)


def _clamp(v):
    try:
        return max(0, min(100, int(float(str(v).strip().rstrip("%")))))
    except (ValueError, TypeError):
        return None


def normalize_eval(raw: dict) -> dict:
    """Coerce model output into a clean record: clamped ints + list/str fields."""
    out = {}
    for k in DIMENSIONS:
        out[k] = _clamp(raw.get(k))
    for k in ("strengths", "weaknesses"):
        v = raw.get(k) or []
        out[k] = [str(x).strip() for x in v if str(x).strip()][:3] if isinstance(v, list) else []
    out["improvement"] = str(raw.get("improvement", "")).strip()
    # Overall fallback: mean of the other nine when the model omits it.
    if out["overall_score"] is None:
        nums = [out[k] for k in DIMENSIONS[:-1] if out[k] is not None]
        out["overall_score"] = round(sum(nums) / len(nums)) if nums else None
    return out


def format_report(ev: dict) -> str:
    """The short internal report (never sent to the customer)."""
    lines = [f"Conversation Score: {ev.get('overall_score', '—')}/100", ""]
    if ev.get("strengths"):
        lines.append("Strengths:")
        lines += [f"- {s}" for s in ev["strengths"]]
        lines.append("")
    if ev.get("weaknesses"):
        lines.append("Weaknesses:")
        lines += [f"- {w}" for w in ev["weaknesses"]]
        lines.append("")
    if ev.get("improvement"):
        lines += ["Recommended Improvement:", ev["improvement"]]
    return "\n".join(lines).strip()


# ── I/O (network) ─────────────────────────────────────────────────────────────
def _headers(prefer="return=minimal"):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
         "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def _get(table: str, params: dict) -> list:
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_headers(""),
                         params=params, timeout=10)
        return r.json() if r.ok else []
    except Exception as e:
        print(f"eval _get {table} error: {e}")
        return []


def already_evaluated(phone: str, last_ts: str) -> bool:
    """Idempotency: skip if this phone is already scored for this last-message ts."""
    if not EVAL_TABLE:
        return False
    rows = _get(EVAL_TABLE, {"phone": f"eq.{phone}", "last_message_at": f"eq.{last_ts}",
                             "select": "phone", "limit": "1"})
    return bool(rows)


def score_conversation(transcript: str) -> dict:
    """One GPT-4o-mini call. Runs in the cron, never on the customer path."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": EVAL_SYSTEM},
                  {"role": "user", "content": transcript}],
        max_tokens=400, temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def store_eval(phone: str, last_ts: str, ev: dict, report: str):
    if not EVAL_TABLE:
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/{EVAL_TABLE}", headers=_headers("resolution=merge-duplicates"),
            json={"phone": phone, "last_message_at": last_ts, "scores": ev,
                  "report": report, "evaluated_at": datetime.now(timezone.utc).isoformat()},
            timeout=10,
        )
    except Exception as e:
        print(f"store_eval error: {e}")


def run_evaluations() -> dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    rows = _get("whatsapp_messages", {"created_at": f"gte.{since}",
                                      "select": "phone,role,content,created_at"})
    convos = group_conversations(rows)
    scored = skipped = 0
    for phone, msgs in list(convos.items())[:MAX_CONVERSATIONS]:
        if not is_completed(msgs, now, COMPLETED_AFTER_MIN):
            skipped += 1; continue
        last_ts = msgs[-1].get("created_at", "")
        if already_evaluated(phone, last_ts):
            skipped += 1; continue
        transcript = build_transcript(msgs)
        if len(transcript) < 20:
            skipped += 1; continue
        try:
            ev = normalize_eval(score_conversation(transcript))
        except Exception as e:
            print(f"score error {phone}: {e}"); skipped += 1; continue
        store_eval(phone, last_ts, ev, format_report(ev))
        print(f"evaluated {phone}: {ev.get('overall_score')}/100")
        scored += 1
    return {"scored": scored, "skipped": skipped, "conversations": len(convos)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_evaluations()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", **result}).encode())

    def log_message(self, *a):
        pass
