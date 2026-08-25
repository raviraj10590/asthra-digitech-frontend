"""Goal lifecycle — an admitted intention that knows when it is finished.

    "A Goal is an admitted intention with a declared completion condition and
     an accountable owner." (IDD-3B §1.1)

All three words are enforced here: admission is a gate (§1.4), a goal with no
completion condition MAY NOT BE ADMITTED, and `owner` is never null (§1.5).

THE STATES ARE THE IDD'S, NOT CONVENIENT SYNONYMS (§1.3)
--------------------------------------------------------
    PROPOSED ──admit?──► ADMITTED ──► PLANNED ──► ACTIVE ──► COMPLETED
        │                                            │
        └──► REJECTED                          BLOCKED ──► ABANDONED
                                                     └───► EXPIRED

There is deliberately no OPEN and no REFUSED. "Open" is ADMITTED/ACTIVE, and a
refusal is either REJECTED (it never became a goal) or BLOCKED (it is a goal
and something is in the way). Renaming states to whatever reads naturally in
the moment is how two vocabularies for one concept start.

WHY PLANNED IS SKIPPED HERE
---------------------------
§0.1: "Most turns need no planner at all... planning is an exception path."
This slice answers a single-action enquiry, so it goes ADMITTED → ACTIVE
directly. PLANNED is not removed from the model, merely unreached.

WHY NOTHING IS PERSISTED
------------------------
§1.2 types a goal by lifespan. "Answer a question" is EPHEMERAL — one turn,
working memory, does not survive restart. `social_media_enquiry` is exactly
that, so this module needs no table and no migration. Only PERSISTENT goals
become Commitments (2B), and none exist yet.

That also bounds which terminals are reachable. §1.8 lists four — COMPLETED,
ABANDONED, EXPIRED, SUPERSEDED — but ABANDONED requires a human decision to
stop, EXPIRED a deadline to pass, and SUPERSEDED a later goal to replace this
one. All three need a goal that outlives the turn. They are defined here and
unreachable in this slice, which is the honest shape: absent, not invented.

NOT SUFFICIENCY, AND NOT AN OUTCOME
-----------------------------------
2H asks "is there enough evidence to take the next step"; this asks "what are
we trying to do, and are we done". PROCEED is permission to act, never proof
of completion — see `complete()`, which refuses to take anyone's word for it.

2I observes what the WORLD did afterwards, asynchronously. A goal reaching
COMPLETED is not an Outcome Record and is never written as one: this module
imports nothing from bic.outcomes and writes to no table at all.
"""

from datetime import datetime, timezone
from typing import Optional

# ── §1.3 lifecycle states ──────────────────────────────────────────────────
PROPOSED = "PROPOSED"
ADMITTED = "ADMITTED"
REJECTED = "REJECTED"
PLANNED = "PLANNED"        # unreached in this slice (§0.1 fast path)
ACTIVE = "ACTIVE"
BLOCKED = "BLOCKED"
COMPLETED = "COMPLETED"
ABANDONED = "ABANDONED"    # requires a human decision to stop (§1.8)
EXPIRED = "EXPIRED"        # requires a deadline to pass (§1.8)
SUPERSEDED = "SUPERSEDED"  # requires a later goal to replace it (§1.8)

STATES = (PROPOSED, ADMITTED, REJECTED, PLANNED, ACTIVE, BLOCKED,
          COMPLETED, ABANDONED, EXPIRED, SUPERSEDED)
TERMINALS = (COMPLETED, ABANDONED, EXPIRED, SUPERSEDED, REJECTED)

# ── §1.2 goal types ────────────────────────────────────────────────────────
EPHEMERAL = "EPHEMERAL"
SESSION = "SESSION"
PERSISTENT = "PERSISTENT"
GOAL_TYPES = (EPHEMERAL, SESSION, PERSISTENT)

# ── Completion conditions — a CLOSED set the mechanism can actually check ──
# Only conditions the Brain can observe today. "Customer became a paying
# client" is a real business outcome and belongs to 2I once there is a source
# for it; asserting it here would be fabricating a result from a reply.
RESPONSE_DELIVERED = "RESPONSE_DELIVERED"
COMPLETION_CONDITIONS = (RESPONSE_DELIVERED,)

# ── Bounded blocker reasons. Never free text, never customer words ─────────
BLOCKED_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
BLOCKED_NOT_AUTHORIZED = "NOT_AUTHORIZED"
BLOCKED_UNAVAILABLE = "UNAVAILABLE"
BLOCKERS = (BLOCKED_INSUFFICIENT_EVIDENCE, BLOCKED_NOT_AUTHORIZED,
            BLOCKED_UNAVAILABLE)

# §1.5 — an accountable owner, never null. The automation acts; accountability
# inherits to the human who authorised it, who is identified through the
# tenant and deliberately NOT copied here, so no person lands in this record.
AUTONOMOUS_OWNER = "agent:brain"


class GoalError(RuntimeError):
    """A lifecycle rule was violated by the CALLER."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v) -> str:
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


def admit(goal_def: dict, *, tenant_id: str, subject: str,
          decision_ref: Optional[str] = None, at=None) -> dict:
    """④ Admission — the gate (§1.4). Returns an ADMITTED goal INSTANCE.

    The DEFINITION is reusable data owned by bic/goals.py. The INSTANCE is
    this subject's pursuit of it right now, and holds nothing the definition
    already holds.

    Raises GoalError when the definition declares no completion condition:
    "A goal with no defined completion condition may not be admitted" —
    without it the goal never ends, and by year two the system holds
    thousands of zombie intentions nobody can tell apart from real ones.
    """
    if not isinstance(goal_def, dict) or not goal_def.get("goal_id"):
        raise GoalError("goal_def must come from the goal registry")
    completion = goal_def.get("completion")
    if completion not in COMPLETION_CONDITIONS:
        raise GoalError(
            f"goal {goal_def.get('goal_id')!r} declares no admissible "
            f"completion condition (IDD-3B §1.4) — got {completion!r}")
    if not subject:
        raise GoalError("an admitted goal needs a subject")
    if not tenant_id:
        raise GoalError("an admitted goal needs a tenant")

    return {
        "goal_id": goal_def["goal_id"],
        "goal_type": goal_def.get("goal_type", EPHEMERAL),
        "tenant_id": tenant_id,
        # Opaque 2B knowledge_id. Never a phone, never message text.
        "subject": subject,
        "owner": AUTONOMOUS_OWNER,
        "completion": completion,
        "lifecycle": ADMITTED,
        "blocker": None,
        # The single attribution edge back to the turn that admitted it.
        "decision_ref": decision_ref,
        "admitted_at": _iso(at or _now()),
        # Every transition, oldest first — so "what state was this in, and
        # why?" stays answerable without a store.
        "history": [{"state": ADMITTED, "reason": "admitted",
                     "at": _iso(at or _now())}],
    }


def _transition(instance: dict, state: str, reason: str, at=None) -> dict:
    if instance.get("lifecycle") in TERMINALS:
        raise GoalError(
            f"{instance['lifecycle']} is terminal; the IDD lifecycle (§1.3) "
            f"has no arrow back out of it. Reopening is not defined.")
    moved = dict(instance)
    moved["lifecycle"] = state
    moved["history"] = list(instance.get("history") or []) + [
        {"state": state, "reason": reason, "at": _iso(at or _now())}]
    return moved


def activate(instance: dict, *, at=None) -> dict:
    """ADMITTED → ACTIVE. The decision was made and authorized; the action is
    about to be taken. Still not completion."""
    return _transition(instance, ACTIVE, "decided and authorized", at=at)


def block(instance: dict, blocker: str, *, at=None) -> dict:
    """→ BLOCKED, with a bounded reason. Not terminal: BLOCKED is a goal that
    still exists and is waiting on something (§1.3)."""
    if blocker not in BLOCKERS:
        raise GoalError(f"unknown blocker {blocker!r}")
    moved = _transition(instance, BLOCKED, blocker, at=at)
    moved["blocker"] = blocker
    return moved


def is_complete(instance: dict, observed: dict) -> bool:
    """Deterministic evaluation of the DECLARED condition against OBSERVED
    facts. Nobody's assertion is consulted — including a model's.

    RESPONSE_DELIVERED MEANS THE ANSWER WENT OUT, NOT THAT A MESSAGE DID.
    An earlier version checked only "did we send something", and a CLARIFY
    or REFUSE reply is something — so blocked goals were reporting COMPLETED
    while still carrying their blocker. The goal is achieved only when the
    action it authorised was actually carried out, so completion requires
    ACTIVE: decided, authorised, and then delivered.
    """
    if instance.get("completion") != RESPONSE_DELIVERED:
        return False
    return (instance.get("lifecycle") == ACTIVE
            and bool(observed.get("response_delivered")))


def complete(instance: dict, observed: dict, *, at=None) -> dict:
    """→ COMPLETED, but only if the completion condition is actually met.

    THE POINT OF THIS FUNCTION IS THE REFUSAL. A model may propose wording;
    it may not declare a goal finished, and neither may a customer saying
    "done". Completion is derived from what was observed, so a claim without
    the condition being satisfied leaves the goal exactly where it was.
    """
    if not is_complete(instance, observed):
        raise GoalError(
            f"completion condition {instance.get('completion')!r} is not "
            f"satisfied — a goal is completed by evidence, never by assertion")
    return _transition(instance, COMPLETED, "completion condition met", at=at)


def describe(instance: dict) -> dict:
    """A bounded, non-PII view for tracing. Carries no subject, no history
    detail — just what a log line may say about this goal."""
    return {"goal_id": instance.get("goal_id"),
            "lifecycle": instance.get("lifecycle"),
            "blocker": instance.get("blocker"),
            "completion": instance.get("completion"),
            "owner": instance.get("owner"),
            "decision_ref": instance.get("decision_ref")}
