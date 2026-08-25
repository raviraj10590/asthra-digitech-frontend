"""Commitment — any promise with a party, obligation and deadline (IDD-2B).

    "Commitment is the GENERALISATION of the promise implicit in Quotation,
     Order, Project and SLA. It exists as its own object so that *what have we
     promised and are we about to miss it?* — one of the highest-value
     questions any business can ask — is answerable without a cross-module
     join no module owns."

WHY THIS OBJECT AND NOT A QUEUE
-------------------------------
IDD-3B §1.2 types goals by lifespan and sends the persistent ones here:

    Persistent | Days to months | Survives restart | **Commitment module (2B)**

    "Persistent goals ARE Commitments. A goal the business holds itself to is
     a commitment with the business as counterparty. One concept, two
     vantage points — NO DUPLICATE STORE, NO RECONCILIATION."

So durable deferred work is not a queue row; it is a promise the business
holds itself to. A separate deferred-work table would be the duplicate store
that sentence forbids, and within a year there would be two answers to "what
do we still owe this customer?" that quietly disagree.

THE LIFECYCLE IS 2B's, READ EXACTLY (§ lifecycle diagram)
---------------------------------------------------------
    COMMITMENT     made ─► in_progress ─► met
                     ├────────┴─► missed      (recorded, never deleted)
                     ├─► waived               (requires approver)
                     └─► renegotiated ─► made (new commitment, old one closed)

Read off the diagram, and deliberately no wider:
  · `met` is reachable ONLY through `in_progress` — nothing is met without
    having been worked on.
  · `missed` branches from BOTH `made` and `in_progress` — that is what the
    `├────────┴─►` spans.
  · `waived` and `renegotiated` branch from `made` only.
  · `renegotiated` CLOSES this commitment and names its successor; it does
    not reopen. 2B applies the same rule to Document: "`superseded` requires
    naming the successor. Revision is modelled; deletion is not."

These are NOT the 3B goal states. A goal is what we are trying to do; a
commitment is what we owe. Reusing one vocabulary for both would be the
duplicate-concept error this architecture keeps refusing.

OWNER IS AN AGENT AND IS NEVER NULL
-----------------------------------
"Every Commitment has an accountable owner (an AGENT). Never null." AGENT is
2B's category holding Party/Person/Organization/PartyRole, and "every object's
identity is a meaningless knowledge_id" — so both `owner` and `party` are
opaque ids from bic/party.py. No phone, no email, no name lands here.

MISSED IS THE RELIABILITY SIGNAL
--------------------------------
"`missed` is recorded, never deleted." There is no deletion path in this
module and no way to rewrite a terminal state. A business that quietly drops
its missed promises cannot answer the one question this object exists for.

NOT A GOAL, NOT AN OUTCOME, NOT A CLAIM
---------------------------------------
A missed Commitment is what WE failed to do. An Outcome (2I) is what the
WORLD did. This module writes to neither, imports neither, and asserts no
knowledge: it never touches bic_claims.

PERSISTENCE IS DELIBERATELY ABSENT HERE
---------------------------------------
2B requires this object to survive restarts, but four schema-level questions
are not answered by 2B (identity of `subject`, storage of the `waived`
approver, the successor link, and whether rows transition in place or append).
Those are reported for a ruling rather than guessed at in a migration, so this
module is the contract only — pure, in-memory, no table.
"""

from datetime import datetime, timezone
from typing import Optional

# ── §2B lifecycle states ───────────────────────────────────────────────────
MADE = "made"
IN_PROGRESS = "in_progress"
MET = "met"
MISSED = "missed"
WAIVED = "waived"
RENEGOTIATED = "renegotiated"

STATES = (MADE, IN_PROGRESS, MET, MISSED, WAIVED, RENEGOTIATED)
TERMINALS = (MET, MISSED, WAIVED, RENEGOTIATED)

# Transitions read directly off 2B's diagram. Anything absent is illegal —
# including made → met, because nothing is met without being worked on.
_ALLOWED = {
    MADE: (IN_PROGRESS, MISSED, WAIVED, RENEGOTIATED),
    IN_PROGRESS: (MET, MISSED),
}


class CommitmentError(RuntimeError):
    """A 2B rule was violated by the CALLER."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v) -> str:
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()


def _parse(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def make(*, tenant_id: str, party: str, obligation: str, due_on,
         owner: str, subject: str = None, decision_ref: str = None,
         goal_ref: str = None, penalty: str = None, source: str = None,
         criticality: str = None, at=None) -> dict:
    """Create a commitment in `made`.

    Required by 2B: party, obligation, due_on, owner. Optional: penalty,
    source, criticality. Nothing else is added — a field that might be useful
    later is a field nobody can explain today.
    """
    if not tenant_id:
        raise CommitmentError("a commitment needs a tenant")
    if not party:
        raise CommitmentError("2B requires a party — a promise is made TO someone")
    if not obligation:
        raise CommitmentError("2B requires an obligation — what was promised")
    if not owner:
        raise CommitmentError(
            "2B requires an accountable owner (an AGENT), never null — "
            "there is no such thing as a promise nobody is answerable for")
    due = _parse(due_on)
    if due is None:
        raise CommitmentError(
            "2B requires a deadline — without due_on 'are we about to miss "
            "it?' is unanswerable, which is the question this object exists for")

    created = _parse(at) or _now()
    if due < created:
        raise CommitmentError("due_on precedes creation — a promise cannot be "
                              "made already overdue")
    return {
        "commitment_id": _new_id(),
        "tenant_id": tenant_id,
        # Identifying assertions (2B): subject + party + due_on. Opaque
        # knowledge_ids, never PII.
        "subject": subject,
        "party": party,
        "due_on": _iso(due),
        "obligation": obligation,
        "owner": owner,
        "lifecycle": MADE,
        # Attribution back to the turn that created the obligation. One edge,
        # matching every other record in this codebase.
        "decision_ref": decision_ref,
        "goal_ref": goal_ref,
        "penalty": penalty,
        "source": source,
        "criticality": criticality,
        "approver": None,
        "superseded_by": None,
        "created_at": _iso(created),
        "history": [{"state": MADE, "reason": "made", "at": _iso(created)}],
    }


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _transition(c: dict, state: str, reason: str, at=None, **extra) -> dict:
    current = c.get("lifecycle")
    if current in TERMINALS:
        raise CommitmentError(
            f"{current} is terminal — 2B's lifecycle has no arrow out of it. "
            f"A renegotiated promise is a NEW commitment, not a reopened one.")
    if state not in _ALLOWED.get(current, ()):
        raise CommitmentError(f"illegal transition {current} → {state}")
    moved = dict(c)
    moved["lifecycle"] = state
    moved.update(extra)
    moved["history"] = list(c.get("history") or []) + [
        {"state": state, "reason": reason, "at": _iso(_parse(at) or _now())}]
    return moved


def start(c: dict, *, at=None) -> dict:
    """made → in_progress. Work has begun."""
    return _transition(c, IN_PROGRESS, "work started", at=at)


def meet(c: dict, *, at=None) -> dict:
    """in_progress → met. Reachable only through in_progress."""
    return _transition(c, MET, "obligation met", at=at)


def miss(c: dict, *, reason: str, at=None) -> dict:
    """→ missed, from made or in_progress.

    "`missed` is recorded, never deleted. Missed commitments are the
    reliability signal." A reason is required because an unexplained miss
    teaches nothing.
    """
    if not reason:
        raise CommitmentError("a missed commitment requires a reason — it is "
                              "the reliability signal, not a silent drop")
    return _transition(c, MISSED, reason, at=at)


def waive(c: dict, *, approver: str, reason: str, at=None) -> dict:
    """made → waived. 2B's diagram: "(requires approver)".

    The approver is recorded, not merely required: a waiver nobody is named
    on is indistinguishable from the obligation being dropped.
    """
    if not approver:
        raise CommitmentError("2B requires an approver to waive a commitment")
    if not reason:
        raise CommitmentError("a waiver requires a reason")
    return _transition(c, WAIVED, reason, at=at, approver=approver)


def renegotiate(c: dict, *, due_on, obligation: str = None, owner: str = None,
                reason: str, at=None) -> tuple:
    """made → renegotiated, closing this one and returning its successor.

    2B: "renegotiated → made (new commitment, old one closed)". Returns
    (closed, successor) so the caller cannot accidentally keep only one half.
    The successor is NAMED on the closed record, following 2B's rule for
    Document: "superseded requires naming the successor."
    """
    if not reason:
        raise CommitmentError("renegotiation requires a reason")
    successor = make(
        tenant_id=c["tenant_id"], party=c["party"],
        obligation=obligation or c["obligation"], due_on=due_on,
        owner=owner or c["owner"], subject=c.get("subject"),
        decision_ref=c.get("decision_ref"), goal_ref=c.get("goal_ref"),
        penalty=c.get("penalty"), source=c.get("source"),
        criticality=c.get("criticality"), at=at)
    closed = _transition(c, RENEGOTIATED, reason, at=at,
                         superseded_by=successor["commitment_id"])
    return closed, successor


def is_overdue(c: dict, *, now=None) -> bool:
    """Deterministic: past due and not yet in a terminal state. Detection
    only — this module never transitions anything on its own, because
    "missed" is a business judgement with a reason attached."""
    if c.get("lifecycle") in TERMINALS:
        return False
    due = _parse(c.get("due_on"))
    return bool(due and (_parse(now) or _now()) > due)


def describe(c: dict) -> dict:
    """Bounded, non-PII view for tracing. Carries no party, owner or subject —
    all three are opaque ids, but a trace line does not need them."""
    return {"commitment_id": c.get("commitment_id"),
            "lifecycle": c.get("lifecycle"),
            "obligation": c.get("obligation"),
            "due_on": c.get("due_on"),
            "decision_ref": c.get("decision_ref"),
            "superseded_by": c.get("superseded_by")}
