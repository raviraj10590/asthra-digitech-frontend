"""Durable Meta webhook deduplication, keyed by wamid.

THE DEFECT THIS CLOSES
----------------------
is_duplicate_webhook() compares inbound text against the last saved message,
but the inbound message is only persisted AFTER generate_reply() and
send_text(). Production p50 for an AI turn is ~24s and 56.9% of turns exceed
20s, so for most turns there is a long window in which Meta's retry sees no
saved message, is not recognised as a duplicate, and produces a SECOND reply
to a real customer.

WHY A PRIMARY KEY RATHER THAN A CHECK
-------------------------------------
`claim()` is an INSERT. A unique violation IS the duplicate answer. Any
read-then-write design ("select, then insert if absent") reopens exactly the
race it is meant to close, because two retries can both read absent. The
database decides, atomically, once.

FAIL OPEN, DELIBERATELY
-----------------------
If the claim cannot be written at all — the store is down — `claim()` returns
ACCEPTED rather than blocking the turn. A possible duplicate reply is bad; a
customer receiving NO reply because our bookkeeping table was unavailable is
worse. That trade is stated here so it is never mistaken for an oversight.

OPERATIONAL STATE, NOT EVIDENCE
-------------------------------
Rows here transition. That is the opposite of bic_claims and
bic_decision_records, which are append-only and trigger-protected because they
record what we believed. Nothing in this module is ever read by the Brain, and
nothing here informs a decision.
"""

from datetime import datetime, timezone
from typing import Optional

from . import config
from .db import DbError, insert, select, update

TABLE = "bic_webhook_events"

ACCEPTED, PROCESSING, COMPLETED, FAILED = (
    "ACCEPTED", "PROCESSING", "COMPLETED", "FAILED")
STATES = (ACCEPTED, PROCESSING, COMPLETED, FAILED)

# Returned by claim() — never a stored state. A duplicate leaves no new row.
DUPLICATE = "DUPLICATE"

# Mirrors bic/decision.py. Raw exception text is never stored: a message can
# carry a phone number or a response body.
FAILURE_CLASSES = ("TIMEOUT", "CONNECTION", "DATABASE",
                   "VALUE", "PERMISSION", "UNKNOWN")

# PostgREST surfaces a unique violation as 409 with SQLSTATE 23505.
_DUPLICATE_MARKERS = ("23505", "duplicate key", "already exists")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim(wamid: str, tenant_id: Optional[str] = None) -> str:
    """Claim this delivery. Returns ACCEPTED (ours to process) or DUPLICATE.

    The INSERT is the claim. There is no prior read, so two simultaneous
    retries cannot both win: Postgres serialises them on the primary key and
    exactly one gets ACCEPTED.

    Returns ACCEPTED when the store is unreachable (see module docstring) —
    processing a turn twice is a lesser harm than not answering a customer.
    """
    if not wamid:
        # No delivery identity to claim on. Proceed rather than drop the turn;
        # the legacy content check still applies downstream.
        return ACCEPTED
    if not config.is_configured():
        return ACCEPTED
    try:
        insert(TABLE, {
            "wamid": wamid,
            "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
            "state": ACCEPTED,
        }, timeout=5)
        return ACCEPTED
    except DbError as e:
        if _is_duplicate(e):
            return DUPLICATE
        # Any OTHER database failure fails OPEN.
        print(f"WEBHOOK_CLAIM_UNAVAILABLE reason={type(e).__name__} — "
              f"processing without a durable claim")
        return ACCEPTED


def _is_duplicate(err: Exception) -> bool:
    text = str(err).lower()
    return any(m in text for m in _DUPLICATE_MARKERS)


def mark(wamid: str, state: str, failure_class: Optional[str] = None) -> None:
    """Advance a claimed delivery. Best-effort: never breaks a live turn.

    ACCEPTED -> PROCESSING -> COMPLETED | FAILED. The transition is not
    enforced here — a stuck row is diagnostic, and refusing to record a
    terminal state because the previous one was missed would destroy exactly
    the signal an operator needs.
    """
    if not wamid or state not in STATES or not config.is_configured():
        return
    patch = {"state": state, "updated_at": _now().isoformat()}
    if state in (COMPLETED, FAILED):
        patch["completed_at"] = _now().isoformat()
    if state == FAILED:
        patch["failure_class"] = (failure_class
                                  if failure_class in FAILURE_CLASSES else "UNKNOWN")
    try:
        update(TABLE, {"wamid": f"eq.{wamid}"}, patch, timeout=5)
    except Exception as e:
        print(f"WEBHOOK_EVENT_MARK_FAILED state={state} "
              f"reason={type(e).__name__}")


def lookup(wamid: str) -> Optional[dict]:
    """Read one delivery's state. Diagnostics only — never a gate."""
    if not wamid or not config.is_configured():
        return None
    try:
        rows = select(TABLE, {"wamid": f"eq.{wamid}", "limit": "1"}, timeout=5)
    except DbError:
        return None
    return rows[0] if rows else None
