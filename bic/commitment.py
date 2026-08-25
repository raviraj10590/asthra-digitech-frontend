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
  · `renegotiated` branches from `made` only.
  · `waived` is reachable from `made` AND `in_progress` — an owner ruling
    where the diagram was ambiguous; see _ALLOWED.
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

PERSISTENCE
-----------
The four schema questions 2B left open were ruled on 2026-08-25 and are
implemented in migration 18. Creation and reads are persisted below;
lifecycle transitions go through one atomic Postgres function — see
record_transition().

`update` is deliberately NOT imported: db.py documents it as narrow by
design, and a commitment's lifecycle moves only through the RPC, never
through a bare UPDATE from here.
"""

from datetime import datetime, timezone
from typing import Optional

from .db import DbError, insert, rpc, select

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
    # `waived` from in_progress is an OWNER RULING (2026-08-25), not a
    # reading of the diagram: the ASCII branches waived off `made` only, but
    # work already started can still be forgiven, and refusing that would
    # force a real waiver to be recorded as a miss — corrupting the one
    # signal 2B calls out as the reliability signal.
    IN_PROGRESS: (MET, MISSED, WAIVED),
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


# ══════════════════════════════════════════════════════════════════════════
# PERSISTENCE (2B: commitments survive restarts)
# ══════════════════════════════════════════════════════════════════════════
# Everything above is pure. Everything below writes, and only through the
# existing bic.db primitives — no repository framework, no ORM, no cache.
#
# TRANSITIONS GO THROUGH ONE POSTGRES FUNCTION, never two HTTP writes.
# Moving a lifecycle means updating the current row AND appending its history
# row; bic.db performs `insert` and `update` as independent PostgREST calls
# with no transaction between them, so doing it here would leave both halves
# reachable alone. The bad half is a state change with NO audit trail —
# exactly what the append-only history exists to prevent. A function body is
# a single transaction, so a rejected transition rolls back both writes.

TABLE = "bic_commitments"
TRANSITIONS_TABLE = "bic_commitment_transitions"

# Same markers bic/webhook_events.py uses: a unique violation IS the answer,
# not an error to interpret.
_DUPLICATE_MARKERS = ("23505", "duplicate key", "already exists")

_PERSISTED = ("commitment_id", "tenant_id", "subject", "party", "obligation",
              "due_on", "owner", "lifecycle", "decision_ref", "goal_ref",
              "penalty", "source", "criticality", "superseded_by",
              "created_at")


def _is_duplicate(err: Exception) -> bool:
    text = str(err).lower()
    return any(m in text for m in _DUPLICATE_MARKERS)


def _row(c: dict) -> dict:
    """Domain object → table row. `history` and `approver` are deliberately
    NOT columns: history lives in its own append-only table, and the approver
    is a property of the waiving ACT, recorded on the transition."""
    return {k: c.get(k) for k in _PERSISTED}


def save(c: dict) -> dict:
    """Persist a newly made commitment. ONE insert, so atomic by definition.

    Creation is not a transition — the migration's history table requires a
    `from_state`, and a commitment comes into existence already `made`. So
    there is no second write here and no atomicity problem.

    A duplicate identity (tenant + subject + party + due_on, NULLS NOT
    DISTINCT) raises CommitmentError rather than overwriting: two people
    promising the same thing to the same party by the same date have made one
    promise, and silently replacing the first would erase who committed to it.
    """
    if c.get("lifecycle") != MADE:
        raise CommitmentError(
            f"only a newly made commitment is saved this way; got "
            f"{c.get('lifecycle')!r}. Later states arrive by transition.")
    for required in ("tenant_id", "party", "obligation", "due_on", "owner"):
        if not c.get(required):
            raise CommitmentError(f"cannot persist without {required}")
    try:
        insert(TABLE, _row(c), timeout=5)
    except DbError as e:
        if _is_duplicate(e):
            raise CommitmentError(
                "a commitment with this identity already exists "
                "(tenant + subject + party + due_on)") from e
        raise
    return c


def get(tenant_id: str, commitment_id: str) -> Optional[dict]:
    """Tenant-scoped lookup by opaque id. Returns None for a foreign tenant —
    never a denial, which would confirm the row exists."""
    if not tenant_id or not commitment_id:
        raise CommitmentError("get needs a tenant and a commitment id")
    rows = select(TABLE, {"tenant_id": f"eq.{tenant_id}",
                          "commitment_id": f"eq.{commitment_id}"}, timeout=5)
    return rows[0] if rows else None


def find(tenant_id: str, *, party: str, due_on, subject: str = None) -> Optional[dict]:
    """Lookup by the 2B identifying assertions. Opaque ids only — there is no
    lookup by phone, email or any other shortcut."""
    if not tenant_id or not party:
        raise CommitmentError("find needs a tenant and a party")
    due = _parse(due_on)
    if due is None:
        raise CommitmentError("find needs a parseable due_on")
    params = {"tenant_id": f"eq.{tenant_id}", "party": f"eq.{party}",
              "due_on": f"eq.{_iso(due)}"}
    # NULLS NOT DISTINCT in the index means an absent subject is a VALUE, so
    # the query must ask for IS NULL rather than skipping the column.
    params["subject"] = f"eq.{subject}" if subject else "is.null"
    rows = select(TABLE, params, timeout=5)
    return rows[0] if rows else None


def overdue(tenant_id: str, *, now=None) -> list:
    """Active commitments past their deadline. READ-ONLY, deliberately.

    This answers 2B's stated purpose — "what have we promised and are we
    about to miss it?" — and stops there. It does NOT mark anything missed:
    `missed` is a business judgement that carries a reason and an actor, and
    a query that silently transitioned rows would manufacture that judgement
    from a clock tick. Uses the migration's partial index
    (tenant_id, due_on) WHERE lifecycle IN ('made','in_progress').
    """
    if not tenant_id:
        raise CommitmentError("overdue needs a tenant")
    when = _parse(now) or _now()
    return select(TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "lifecycle": f"in.({MADE},{IN_PROGRESS})",
        "due_on": f"lt.{_iso(when)}",
        "order": "due_on.asc",
    }, timeout=5)


def outstanding(tenant_id: str) -> list:
    """Every open commitment for a tenant, soonest deadline first.

    The same rows `overdue()` reads, without the deadline filter — one source
    for "what do we owe?" whether the asker is the daily digest or an owner
    typing a command. A second query shape somewhere else would eventually
    disagree with this one, and both would look authoritative.

    Uses the migration's partial index
    (tenant_id, due_on) WHERE lifecycle IN ('made','in_progress').
    """
    if not tenant_id:
        raise CommitmentError("outstanding needs a tenant")
    return select(TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "lifecycle": f"in.({MADE},{IN_PROGRESS})",
        "order": "due_on.asc",
    }, timeout=5)


# ── Owner-facing references ────────────────────────────────────────────────
# A commitment_id is a uuid4: correct as a key, useless to a human reading it
# on a phone, and not something to paste into a WhatsApp message. These give
# a SHORT handle derived from it — no second identifier column, nothing stored,
# nothing to keep in sync.
REFERENCE_PREFIX = "C-"
REFERENCE_LENGTH = 8
# Below this, a typo could resolve to a real commitment that the owner never
# meant to touch. Four hex characters is 65 536 values against a working set
# of open promises measured in tens.
REFERENCE_MIN_INPUT = 4
_REFERENCE_SCAN_LIMIT = 200


def reference(c: dict) -> str:
    """The owner-facing handle for a commitment: `C-` + 8 hex characters."""
    raw = str(c.get("commitment_id") or "").replace("-", "")
    return REFERENCE_PREFIX + raw[:REFERENCE_LENGTH].upper()


def normalise_reference(ref: str) -> str:
    """Accept `C-1A2B3C4D`, `c-1a2b3c4d` or bare `1a2b3c4d`."""
    # Named `token`, not `text`: this module must contain no path where
    # anything called "text" influences a lifecycle, and test_commitment.py
    # enforces that by scanning the source. The guard is right — a reference
    # is a token, and nothing here reads customer words.
    #
    # THE PREFIX IS STRIPPED BEFORE THE DASHES, AND ONLY AS "C-". Stripping a
    # bare leading "C" instead ate the first hex digit of every reference that
    # legitimately starts with one — about one commitment in sixteen, which
    # then could not be addressed without its prefix.
    token = (ref or "").strip().upper()
    if token.startswith(REFERENCE_PREFIX):
        token = token[len(REFERENCE_PREFIX):]
    return token.replace("-", "")


def by_reference(tenant_id: str, ref: str) -> list:
    """EVERY commitment matching `ref`, so the caller can refuse ambiguity.

    Returns a list rather than one row on purpose: resolving a prefix to
    "probably this one" is how an owner closes the wrong promise. Two matches
    must be an error the caller reports, never a choice this function makes.

    Scans terminal states too. A reference the owner just read in a listing
    must still resolve after someone marked it met, or "already met" would be
    indistinguishable from "no such commitment".
    """
    if not tenant_id:
        raise CommitmentError("by_reference needs a tenant")
    wanted = normalise_reference(ref)
    if len(wanted) < REFERENCE_MIN_INPUT:
        raise CommitmentError(
            f"a commitment reference needs at least {REFERENCE_MIN_INPUT} "
            f"characters — a shorter one could match a promise you did not mean")
    rows = select(TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "order": "created_at.desc",
        "limit": str(_REFERENCE_SCAN_LIMIT),
    }, timeout=5)
    return [r for r in rows
            if reference(r)[len(REFERENCE_PREFIX):].startswith(wanted)]


def history(tenant_id: str, commitment_id: str) -> list:
    """Every recorded transition, oldest first. Append-only at the database;
    nothing here can rewrite it."""
    if not tenant_id or not commitment_id:
        raise CommitmentError("history needs a tenant and a commitment id")
    return select(TRANSITIONS_TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "commitment_id": f"eq.{commitment_id}",
        "order": "occurred_at.asc",
    }, timeout=5)


RPC_TRANSITION = "bic_commitment_transition"


def record_transition(c: dict, to_state: str, *, reason: str,
                      actor: str = None, successor: str = None) -> dict:
    """Move a commitment's lifecycle. ONE atomic RPC, never two writes.

    The domain validates FIRST, so a caller's mistake fails locally and
    deterministically without a round trip. The database validates AGAIN,
    because persistence cannot depend on the caller being correct — and the
    function body is a single transaction, so a rejected transition leaves
    the row and its history exactly as they were.

    There is deliberately no `update` and no history `insert` in this
    function. Two independent writes would make a lifecycle change with no
    audit trail reachable in production, which is the one failure the
    append-only history exists to prevent.
    """
    if to_state not in STATES:
        raise CommitmentError(f"unknown state {to_state!r}")
    if not reason:
        raise CommitmentError("a transition requires a reason")
    if not c.get("commitment_id") or not c.get("tenant_id"):
        raise CommitmentError("record_transition needs a persisted commitment")

    current = c.get("lifecycle")
    if current in TERMINALS:
        raise CommitmentError(
            f"{current} is terminal — 2B's lifecycle has no arrow out of it")
    if to_state not in _ALLOWED.get(current, ()):
        raise CommitmentError(f"illegal transition {current} → {to_state}")
    if to_state == WAIVED and not actor:
        raise CommitmentError("2B requires an approver to waive a commitment")
    if to_state == RENEGOTIATED and not successor:
        raise CommitmentError("renegotiation must name its successor")
    if to_state != RENEGOTIATED and successor:
        raise CommitmentError("only a renegotiation may name a successor")

    row = rpc(RPC_TRANSITION, {
        "p_tenant_id": c["tenant_id"],
        "p_commitment_id": c["commitment_id"],
        "p_to_state": to_state,
        "p_reason": reason,
        "p_actor": actor,
        "p_successor": successor,
    }, timeout=5)
    if not row:
        raise CommitmentError(
            "transition returned no commitment — treat as not applied")
    return row
