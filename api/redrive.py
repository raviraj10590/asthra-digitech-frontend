"""Phase 2B — safe recovery and re-drive of inbound WhatsApp deliveries.

WHAT IT DOES
------------
Finds bic_webhook_events rows that did not end well — FAILED, or PROCESSING
for longer than any live invocation can run — and, one WAMID at a time,
either proves the customer was already answered (and closes the row) or
re-enters the SAME client decision path a live delivery takes.

THE RULE ABOVE ALL OTHERS: NEVER A SECOND REPLY
-----------------------------------------------
A WhatsApp send is not idempotent (bic/recovery.py, invariant I13). Before
re-driving, the CRM conversation for that phone is read AFTER the inbound
message. Phase 2A mirrors every customer text send there with its verdict:

    sent / delivered / read   Meta accepted a reply      -> close COMPLETED
    pending                   a reply's fate is UNKNOWN  -> owner, never resent
    failed                    Meta rejected it           -> may be re-driven
    a newer inbound           the chat moved on          -> owner, not re-driven

Manual replies the owner typed in the CRM are outbound rows too, so they
block a re-drive just the same. When the CRM shows nothing but the Brain
transcript holds an assistant row after the message, the mirror may simply
have failed: that is ambiguous, so it goes to the owner as well.

WHERE THE ORIGINAL MESSAGE COMES FROM
-------------------------------------
bic_webhook_events stores no phone and no text, by design. The CRM stores
every inbound message with its wa_message_id (492/492 over the 14 days to
2026-10-01). The re-drive uses that row — the original WAMID, phone and body —
and nothing reconstructed.

WHAT IT WILL NOT TOUCH
----------------------
* ACCEPTED rows. Since the lifecycle fix, PROCESSING is written immediately
  after the claim, so a row left at ACCEPTED means the mark itself failed and
  nothing else is known. The three in production (2026-08-20, image/audio)
  are also far outside WhatsApp's 24 h reply window.
* Non-text messages, owner/staff chats (their replies are not mirrored, so
  there is no delivery evidence to check), and anything older than the
  recovery window.
* A row whose claim store is unreachable: every database failure here fails
  CLOSED. The live claim's fail-open is unchanged — a delivery processed
  without a claim has no row, so recovery cannot see it, let alone repeat it.

BOUNDED
-------
Every attempt is written BEFORE the re-drive as a system row in that
customer's Brain transcript ("RECOVERY::<wamid>::attempt=<n>…") — the same
convention as BOT_PAUSED / LEAD_ALERTED, and outside the user/assistant
history the model reads. If the attempt cannot be written, nothing is
re-driven. After RECOVERY_MAX_ATTEMPTS the owner is told once and a
"final" row stops the WAMID from being picked again.

NO ENDPOINT, NO SCHEDULE — DELIBERATELY
---------------------------------------
Nothing calls run() yet. The existing cron gate (User-Agent "vercel-cron" or
?key=VERIFY_TOKEN) is spoofable, the project is on the Hobby plan (Vercel
cron at most daily), and no CRON_SECRET exists. Exposing this would let
anyone trigger customer sends. See the Phase 2B report for what is needed.
"""
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone

import requests

import webhook as w
from bic import webhook_events as ev
from bic import recovery as bic_recovery

# ── Thresholds (env-overridable, the project's os.environ.get convention) ────
# PROCESSING is stale after 10 min. Production durations (929 completed turns
# to 2026-10-01): p50 5.5 s, p99 68 s, max 122 s; Vercel's longest possible
# function run on this plan is 300 s. 600 s is twice that hard cap, so a row
# this old cannot belong to an invocation that is still running.
STALE_PROCESSING_SECONDS = int(os.environ.get("RECOVERY_STALE_SECONDS", "600"))
# A FAILED row is already terminal; this pause only lets the CRM mirror (3 s
# timeout) and Meta's status receipts land before the evidence is read.
FAILED_SETTLE_SECONDS = int(os.environ.get("RECOVERY_FAILED_SETTLE_SECONDS", "120"))
# WhatsApp accepts a free-form reply only within 24 h of the customer's last
# message; past that a re-drive could only be rejected.
WINDOW_HOURS = int(os.environ.get("RECOVERY_WINDOW_HOURS", "23"))
# The project's one stated try-again budget (bic/recovery.py).
MAX_ATTEMPTS = int(os.environ.get("RECOVERY_MAX_ATTEMPTS", str(bic_recovery.MAX_ATTEMPTS)))
BATCH = 5

MARK = "RECOVERY::"

# Results — the structured log and the "final" row use these words.
REDRIVEN = "REDRIVEN"                      # re-entered the decision path
RECONCILED = "RECONCILED_REPLY_EXISTS"     # Meta accepted a reply already
HUMAN_REVIEW = "HUMAN_REVIEW"              # reply fate unknown — owner decides
SUPERSEDED = "SUPERSEDED"                  # customer wrote again since
EXHAUSTED = "EXHAUSTED"                    # attempt budget spent
LOST_RACE = "LOST_RACE"                    # another worker owns it
SKIPPED = "SKIPPED"                        # not recoverable; row untouched
STORE_UNAVAILABLE = "STORE_UNAVAILABLE"    # fail closed

_ACCEPTED_STATUSES = ("sent", "delivered", "read")
_UNKNOWN_STATUSES = ("pending",)


def _now():
    return datetime.now(timezone.utc)


def _ref(wamid: str) -> str:
    """Log reference for a WAMID. The full id stays in the durable rows (event
    table, RECOVERY:: marker); logs carry a stable digest, as the live path
    keeps wamids out of per-message log lines."""
    return hashlib.sha256((wamid or "").encode()).hexdigest()[:12]


def _log(wamid, prev_state, reason, attempt, outbound, result, **extra):
    tail = "".join(f" {k}={v}" for k, v in extra.items())
    print(f"RECOVERY wamid_ref={_ref(wamid)} prev_state={prev_state} "
          f"reason={reason} attempt={attempt} outbound={outbound} "
          f"result={result}{tail}")


# ── Evidence readers. Each raises on failure; the caller fails closed. ──────

def crm_inbound(wamid: str):
    """The original inbound row (phone, body, type, time), or None."""
    r = requests.get(f"{w.CRM_SUPABASE_URL}/rest/v1/whatsapp_messages",
                     headers=w._crm_headers(),
                     params={"wa_message_id": f"eq.{wamid}",
                             "direction": "eq.inbound",
                             "user_id": f"eq.{w.CRM_OWNER_USER_ID}",
                             "select": "phone,body,message_type,created_at",
                             "limit": "1"},
                     timeout=5)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def crm_after(phone: str, since: str) -> list:
    """Every CRM message for this phone after `since`, oldest first."""
    r = requests.get(f"{w.CRM_SUPABASE_URL}/rest/v1/whatsapp_messages",
                     headers=w._crm_headers(),
                     params={"phone": f"eq.{phone}",
                             "user_id": f"eq.{w.CRM_OWNER_USER_ID}",
                             "created_at": f"gt.{since}",
                             "select": "direction,status,wa_message_id,created_at",
                             "order": "created_at.asc",
                             "limit": "50"},
                     timeout=5)
    r.raise_for_status()
    return r.json()


def recovery_marks(phone: str, wamid: str) -> list:
    """This WAMID's RECOVERY:: rows in the Brain transcript."""
    r = requests.get(f"{w.SUPABASE_URL}/rest/v1/whatsapp_messages",
                     headers=w._supa_headers(),
                     params={"phone": f"eq.{phone}", "role": "eq.system",
                             "content": f"like.{MARK}{wamid}::*",
                             "select": "content", "limit": "50"},
                     timeout=5)
    r.raise_for_status()
    return [row.get("content") or "" for row in r.json()]


def reply_evidence(after: list) -> str:
    """Classify what the CRM shows after the inbound message."""
    if any((m.get("direction") or "").startswith("in") for m in after):
        return SUPERSEDED
    statuses = [(m.get("status") or "").lower() for m in after
                if (m.get("direction") or "").startswith("out")]
    if any(s in _ACCEPTED_STATUSES for s in statuses):
        return RECONCILED
    if any(s in _UNKNOWN_STATUSES for s in statuses):
        return HUMAN_REVIEW
    # Only rejected sends, or nothing at all.
    return "REJECTED_ONLY" if statuses else "NONE"


def _split_history(ctx: dict, body: str):
    """Strip this delivery's own rows from the history the pipeline will
    read: the customer's message (Phase 2A saved it first) and anything the
    failed attempt saved after it. Returns (assistant_rows_after, stripped)."""
    hist = ctx.get("history") or []
    for i in range(len(hist) - 1, -1, -1):
        if hist[i].get("role") == "user" and hist[i].get("content") == body:
            tail = hist[i:]
            ctx["history"] = hist[:i]
            return sum(1 for m in tail[1:] if m.get("role") == "assistant"), len(tail)
    return 0, 0


# ── One WAMID ───────────────────────────────────────────────────────────────

def recover_one(row: dict) -> str:
    wamid, prev = row.get("wamid") or "", row.get("state")
    reason = (f"failed:{row.get('failure_class') or 'UNKNOWN'}"
              if prev == ev.FAILED else "stale_processing")
    if prev not in (ev.FAILED, ev.PROCESSING) or not wamid:
        _log(wamid, prev, reason, 0, "n/a", SKIPPED, why="state")
        return SKIPPED

    try:
        inbound = crm_inbound(wamid)
    except Exception as e:
        _log(wamid, prev, reason, 0, "unknown", STORE_UNAVAILABLE, err=type(e).__name__)
        return STORE_UNAVAILABLE
    if not inbound:
        _log(wamid, prev, reason, 0, "unknown", SKIPPED, why="no_source")
        return SKIPPED
    phone, body = inbound.get("phone") or "", inbound.get("body") or ""
    if inbound.get("message_type") != "text" or not body.strip():
        _log(wamid, prev, reason, 0, "unknown", SKIPPED, why="not_text")
        return SKIPPED
    try:
        role = w.get_role(phone)[0]
    except Exception as e:
        _log(wamid, prev, reason, 0, "unknown", STORE_UNAVAILABLE, err=type(e).__name__)
        return STORE_UNAVAILABLE
    if role != "CLIENT":
        _log(wamid, prev, reason, 0, "unknown", SKIPPED, why="not_client")
        return SKIPPED

    try:
        marks = recovery_marks(phone, wamid)
    except Exception as e:
        _log(wamid, prev, reason, 0, "unknown", STORE_UNAVAILABLE, err=type(e).__name__)
        return STORE_UNAVAILABLE
    attempts = sum(1 for m in marks if "::attempt=" in m)
    if any("::final=" in m for m in marks) or attempts >= MAX_ATTEMPTS:
        _log(wamid, prev, reason, attempts, "unknown", EXHAUSTED)
        return EXHAUSTED

    # ── THE LOCK. From here this worker alone owns the WAMID. ───────────────
    if not ev.reclaim(wamid, prev, row.get("updated_at") or ""):
        _log(wamid, prev, reason, attempts, "unknown", LOST_RACE)
        return LOST_RACE

    def release(fc="DATABASE"):
        ev.mark(wamid, ev.FAILED, fc)

    try:
        evidence = reply_evidence(crm_after(phone, inbound.get("created_at") or ""))
    except Exception as e:
        release()
        _log(wamid, prev, reason, attempts, "unknown", STORE_UNAVAILABLE, err=type(e).__name__)
        return STORE_UNAVAILABLE

    if evidence == RECONCILED:
        ev.mark(wamid, ev.COMPLETED)
        _final(phone, wamid, RECONCILED)
        _log(wamid, prev, reason, attempts, "accepted", RECONCILED)
        return RECONCILED
    if evidence in (HUMAN_REVIEW, SUPERSEDED):
        release(row.get("failure_class") or "UNKNOWN")
        _final(phone, wamid, evidence)
        _tell_owner(phone, evidence)
        _log(wamid, prev, reason, attempts,
             "unknown" if evidence == HUMAN_REVIEW else "n/a", evidence)
        return evidence

    # ── Bounded: the attempt is durable BEFORE anything can be sent. ────────
    attempt = attempts + 1
    if w.save_message(phone, "system",
                      f"{MARK}{wamid}::attempt={attempt}::prev={prev}::reason={reason}") != w.SAVE_OK:
        release()
        _log(wamid, prev, reason, attempts, evidence.lower(), STORE_UNAVAILABLE, why="attempt_not_recorded")
        return STORE_UNAVAILABLE

    result = _redrive(wamid, row, phone, body, prior_marks=len(marks) + 1,
                      crm_has_failed_send=(evidence == "REJECTED_ONLY"))
    if result != REDRIVEN:
        release()
        if result == HUMAN_REVIEW:
            _final(phone, wamid, HUMAN_REVIEW)
            _tell_owner(phone, HUMAN_REVIEW)
        _log(wamid, prev, reason, attempt, evidence.lower(), result)
        return result

    state = (ev.lookup(wamid) or {}).get("state")
    if state == ev.FAILED and attempt >= MAX_ATTEMPTS:
        _final(phone, wamid, EXHAUSTED)
        _tell_owner(phone, EXHAUSTED)
    _log(wamid, prev, reason, attempt, evidence.lower(), REDRIVEN, final_state=state)
    return REDRIVEN


def _redrive(wamid, row, phone, body, prior_marks, crm_has_failed_send) -> str:
    """Re-enter the live client path for ONE delivery, as do_POST would,
    without a second claim and without a second customer row."""
    w._TURN_EXTRAS.clear()
    w._TURN_EXTRAS["turn_sender"] = phone
    ctx = w.fetch_context(phone)
    if ctx.get("degraded"):
        return STORE_UNAVAILABLE
    assistant_after, stripped = _split_history(ctx, body)
    if assistant_after and not crm_has_failed_send:
        # The failed attempt saved a reply the CRM never recorded: the mirror
        # may have failed after a real send. Ambiguous — not re-sent.
        return HUMAN_REVIEW
    if stripped:
        w._TURN_EXTRAS["incoming_saved"] = (phone, body)
    elif w._save_incoming_first(phone, body) != w.SAVE_OK:
        return STORE_UNAVAILABLE
    if ctx.get("stored_messages") is not None:
        # Present the count as the live turn saw it: before this message, and
        # without this WAMID's own RECOVERY:: rows.
        # `stripped` rows (the message and the failed attempt's own rows)
        # were in the count; a message saved just now was not.
        ctx["stored_messages"] = max(0, int(ctx["stored_messages"]) - stripped - prior_marks)

    lifecycle = {"wamid": wamid, "claimed": True, "terminal": False}
    try:
        if w._bic_enabled():
            w._bic_client_turn(phone, body, ctx, row.get("brain_message_id"))
        else:
            w.run_client_pipeline(phone, body, ctx, message_id=row.get("brain_message_id"))
        w._finalize_delivery(lifecycle)
    except Exception as e:
        w._finalize_delivery(lifecycle, w._turn_failure_class(e))
    finally:
        w._TURN_EXTRAS.clear()
    return REDRIVEN


def _final(phone, wamid, result):
    w.save_message(phone, "system", f"{MARK}{wamid}::final={result}")


_OWNER_TEXT = {
    HUMAN_REVIEW: "the reply's delivery could not be confirmed, so it was NOT sent again",
    SUPERSEDED: "the customer has written again since, so the old message was NOT re-answered",
    EXHAUSTED: "automatic recovery gave up after its attempt limit",
}


def _tell_owner(phone, result):
    w.notify_owner(f"🛟 *Recovery needs you* — wa.me/{phone}\n"
                   f"An earlier customer message failed to process: {_OWNER_TEXT[result]}.\n"
                   "Please check the chat and reply manually if needed.")


# ── The sweep ───────────────────────────────────────────────────────────────

def run(now=None) -> dict:
    """One bounded sweep. Returns counts by result."""
    now = now or _now()
    if not (w.BIC_AVAILABLE and ev.config.is_configured()
            and w.CRM_SUPABASE_URL and w.CRM_SUPABASE_SERVICE_KEY and w.CRM_OWNER_USER_ID):
        print("RECOVERY_SWEEP skipped=not_configured")
        return {STORE_UNAVAILABLE: 1}
    newest = min(STALE_PROCESSING_SECONDS, FAILED_SETTLE_SECONDS)
    try:
        rows = ev.candidates((ev.FAILED, ev.PROCESSING),
                             (now - timedelta(hours=WINDOW_HOURS)).isoformat(),
                             (now - timedelta(seconds=newest)).isoformat(),
                             limit=BATCH * 4)
    except Exception as e:
        print(f"RECOVERY_SWEEP store_unavailable err={type(e).__name__}")
        return {STORE_UNAVAILABLE: 1}
    counts, handled = {}, 0
    for row in rows:
        if handled >= BATCH:
            break
        if row.get("state") == ev.PROCESSING and not _older_than(row, STALE_PROCESSING_SECONDS, now):
            continue
        if row.get("state") == ev.FAILED and not _older_than(row, FAILED_SETTLE_SECONDS, now):
            continue
        result = recover_one(row)
        counts[result] = counts.get(result, 0) + 1
        handled += 1
    print("RECOVERY_SWEEP " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return counts


def _parse_ts(value):
    """Postgres timestamps ('…:21.62012+00:00', '…+00', 'Z') on Python 3.9,
    whose fromisoformat wants exactly 6 fraction digits and a ±HH:MM offset."""
    m = re.match(r"^(.*?T?\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}(?::?\d{2})?)?$",
                 str(value or "").replace(" ", "T"))
    if not m:
        return None
    base, frac, tz = m.groups()
    tz = "+00:00" if tz in (None, "Z") else (tz if ":" in tz or len(tz) == 6 else
                                             (tz + ":00" if len(tz) == 3 else tz[:3] + ":" + tz[3:]))
    try:
        return datetime.fromisoformat(f"{base}.{(frac or '0')[:6].ljust(6, '0')}{tz}")
    except ValueError:
        return None


def _older_than(row, seconds, now) -> bool:
    t = _parse_ts(row.get("updated_at"))
    return t is not None and now - t >= timedelta(seconds=seconds)
