"""Stage ⑫ OBSERVE — what actually happened when we executed.

    "⑫ Observe | Brain | Result unparseable | Record raw; mark degraded"
    (IDD-3A §1.2)

THE ONE THING THIS PREVENTS
---------------------------
Assuming an action worked because we asked for it. The Brain used to hand its
goal a hardcoded "response_delivered: True" immediately after calling send —
so a WhatsApp API rejection (HTTP 400, an expired token, a rate limit) still
reported the enquiry as answered and the goal as COMPLETED. The customer got
nothing and the record said otherwise. Observation is what makes "we tried"
and "it happened" different facts.

EXECUTION OBSERVATION IS NOT A BUSINESS OUTCOME (IDD-2I I2)
-----------------------------------------------------------
    "Quotation sent, HTTP 200" is an execution result.
    "Quotation accepted on day 12" is an outcome.

This module records the first and must never be read as the second.
SUCCEEDED here means the channel accepted the message — nothing about whether
the customer read it, liked it, or bought anything. Those are 2I's, observed
asynchronously from outside the turn. So this module writes no outcome
record, imports nothing from bic.outcomes, and touches no claim: an
observation that became a claim would let "we sent it" harden into knowledge.

DEGRADED IS A REAL ANSWER, NOT A MISSING ONE
--------------------------------------------
When the channel returns something unreadable we record UNKNOWN and mark the
observation degraded, exactly as §1.2 requires — and UNKNOWN never counts as
delivery. "We could not tell" and "it worked" are different facts, and only
one of them may finish a goal.

NOTHING IS PERSISTED
--------------------
An execution observation belongs to the turn that produced it. The Decision
Record (⑬) already captures the decision, and the goal it feeds is EPHEMERAL
(3B §1.2). No table, no migration.
"""

from datetime import datetime, timezone
from typing import Optional

from .decision import FAILURE_CLASSES, FAIL_UNKNOWN

# ── Bounded execution states ───────────────────────────────────────────────
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"          # result unparseable — §1.2 "record raw; mark degraded"
STATES = (SUCCEEDED, FAILED, UNKNOWN)

# Bounded action vocabulary. A free-text action name would eventually carry
# customer data into a trace line.
RESPONSE_DELIVERY = "RESPONSE_DELIVERY"
ACTIONS = (RESPONSE_DELIVERY,)


class ObserveError(RuntimeError):
    """A CALLER violated the observation contract."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v) -> str:
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


def _classify(status: Optional[int]) -> str:
    """Channel status → the SAME bounded failure vocabulary the Decision
    Record already uses. A second taxonomy for the same idea would drift."""
    if status is None:
        return FAIL_UNKNOWN
    if status in (401, 403):
        return "PERMISSION"
    if status == 408 or status == 504:
        return "TIMEOUT"
    if status == 429 or 500 <= status < 600:
        return "CONNECTION"
    if 400 <= status < 500:
        return "VALUE"
    return FAIL_UNKNOWN


def execution(result, *, action: str = RESPONSE_DELIVERY, at=None) -> dict:
    """Observe one execution attempt. Deterministic, no I/O, no model.

    `result` is whatever the channel primitive returned. A response-like
    object (anything carrying `ok` / `status_code`) is read; an exception
    instance is a failure; None means the primitive told us nothing, which
    is UNKNOWN and degraded — never success.
    """
    if action not in ACTIONS:
        raise ObserveError(f"unknown action {action!r}")

    when = _iso(at or _now())
    # DID THE CHANNEL ANSWER US? This is the delivery-certainty signal, and
    # it is what makes I13 enforceable downstream. A status code means the
    # channel processed the request and told us the verdict, so a rejection
    # PROVES nothing was delivered. An exception or an unreadable result
    # means we never heard back: the request may or may not have landed, and
    # that ambiguity is precisely what may not be auto-retried.
    base = {"action": action, "observed_at": when, "attempted": True,
            "channel_responded": False}

    if isinstance(result, BaseException):
        # Type only — an exception's text can echo an identifier or a body.
        return {**base, "state": FAILED, "delivered": False, "degraded": False,
                "failure_class": _exception_class(result)}   # never answered

    status = getattr(result, "status_code", None)
    ok = getattr(result, "ok", None)
    if ok is None and status is None:
        # §1.2 — record raw, mark degraded. Deliberately NOT success: an
        # unreadable result is not evidence that anything arrived.
        return {**base, "state": UNKNOWN, "delivered": False, "degraded": True,
                "failure_class": None}

    answered = {**base, "channel_responded": True}
    delivered = bool(ok) if ok is not None else (200 <= int(status) < 300)
    if delivered:
        return {**answered, "state": SUCCEEDED, "delivered": True,
                "degraded": False, "failure_class": None, "status": status}
    return {**answered, "state": FAILED, "delivered": False, "degraded": False,
            "failure_class": _classify(status), "status": status}


def _exception_class(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "TIMEOUT"
    if "connection" in name:
        return "CONNECTION"
    if "value" in name:
        return "VALUE"
    if "permission" in name:
        return "PERMISSION"
    return FAIL_UNKNOWN


def not_attempted(*, action: str = RESPONSE_DELIVERY, at=None) -> dict:
    """No execution was attempted — the Brain refused, clarified, or was
    denied. Distinct from a failed attempt: nothing was tried, so nothing
    can have gone wrong, and nothing may be reported as delivered."""
    if action not in ACTIONS:
        raise ObserveError(f"unknown action {action!r}")
    return {"action": action, "observed_at": _iso(at or _now()),
            "attempted": False, "channel_responded": False, "state": UNKNOWN,
            "delivered": False, "degraded": False, "failure_class": None}


def delivered(observation: Optional[dict]) -> bool:
    """The single question the goal's completion condition may ask. Only a
    SUCCEEDED observation answers yes — never UNKNOWN, never a missing one."""
    return bool(observation and observation.get("state") == SUCCEEDED
                and observation.get("delivered"))


def describe(observation: dict) -> dict:
    """Bounded, non-PII view for tracing."""
    return {"action": observation.get("action"),
            "state": observation.get("state"),
            "attempted": observation.get("attempted"),
            "channel_responded": observation.get("channel_responded"),
            "degraded": observation.get("degraded"),
            "failure_class": observation.get("failure_class")}
