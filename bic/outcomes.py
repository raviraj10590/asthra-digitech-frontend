"""Outcome Intelligence — what the world did (IDD-2I).

THE ONE IDEA (§0.2)
-------------------
> **Record what happened. Derive whether it was good.**

Record `SUCCESS` and you bake in a 2026 definition of success. When the margin
target changes in 2028, every historical outcome silently means something
different — and every lesson built on them is quietly wrong. So this module
stores OBSERVATIONS and computes EVALUATIONS, and the two never meet in a
column. That is I1, and it is the decision that keeps a ten-year loop honest.

EXECUTION IS NOT OUTCOME (I2)
-----------------------------
"Quotation sent, HTTP 200" is an execution result. "Quotation accepted on day
12" is an outcome. Train on the first and you learn whether your integration
works — not whether you win deals, while every metric stays green.

bic_tool_invocations and bic_webhook_events are execution telemetry. Nothing
in them is an outcome, and this module refuses to treat them as one.

NOT A CLAIM (Step 2 of the slice brief, and 2C)
-----------------------------------------------
An outcome is NOT written to bic_claims, ever. A claim asserts what is
believed true, bitemporally; an outcome observes what the world did and may
be revised by later evidence. Folding one into the other would let an
unconfirmed observation become knowledge — which §3.3 forbids, because a
lesson built on unconfirmed signal will have already influenced decisions by
the time reality arrives.

APPEND-ONLY, LIKE EVERY RECORD THAT MATTERS
-------------------------------------------
I3: revision APPENDS; it never edits. There is no update path in this module
and the table carries a mutation-rejecting trigger. "What did we believe about
this outcome in March?" stays answerable, which is what separates *the
decision was wrong* from *the outcome was later revised*.

ONE ATTRIBUTION EDGE (I4)
-------------------------
An outcome attributes to exactly one decision. Direct edges to Customer or
Project would be shortcut edges — forbidden by 2B §4.3, because two paths to
the same fact will diverge. Everything else is reachable by traversal.

AND IT IS CORRELATION, NOT CAUSATION (I5)
-----------------------------------------
"We cannot know whether we won because of the discount or because the
competitor was late." Attribution records which decision PRECEDED which
outcome. Contributing factors are recorded separately and may never justify
an action alone — without that split, attribution inflates until every
outcome links to everything plausibly nearby and the signal drowns.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config
from .db import DbError, insert, select

TABLE = "bic_outcome_records"
RETRACTIONS_TABLE = "bic_outcome_retractions"

# ── §2.2 Observed outcome states — what the world DID ──────────────────────
# Note what is absent: SUCCESS, FAILURE, PARTIAL. Those are evaluations
# (§2.1), and storing them here is the one mistake this whole design exists
# to prevent.
RESOLVED = "RESOLVED"        # concluded — accepted, paid, delivered
DECLINED = "DECLINED"        # they actively said no. An ACT, and learnable
CANCELLED = "CANCELLED"      # called off. WHO cancelled changes what it teaches
EXPIRED = "EXPIRED"          # a deadline passed with no act — lost by inattention
NO_RESPONSE = "NO_RESPONSE"  # we asked; silence. The most common small-business outcome
SUPERSEDED = "SUPERSEDED"    # renegotiated or replaced. Neither win nor loss
OBSERVED_STATES = (RESOLVED, DECLINED, CANCELLED, EXPIRED, NO_RESPONSE,
                   SUPERSEDED)

# ── §2.3 Observation status — how well we KNOW. Orthogonal to state ────────
OBSERVED = "OBSERVED"          # directly witnessed
INFERRED = "INFERRED"          # a proxy fired. Lower confidence
REPORTED = "REPORTED"          # a party told us. Tier 5, capped 0.50 (2C)
TIMED_OUT = "TIMED_OUT"        # the window closed with no signal. DATA, not a gap
UNOBSERVABLE = "UNOBSERVABLE"  # we never had a means to learn it
OBSERVATION_STATUSES = (OBSERVED, INFERRED, REPORTED, TIMED_OUT, UNOBSERVABLE)

# I7. TIMED_OUT means we watched and nothing came; UNOBSERVABLE means we never
# watched. A model that cannot tell them apart learns from a sample biased
# toward counterparties who bother to reply.

# Provenance ceiling per status (2C tiers). REPORTED is a customer-sourced
# fact and Article II.6 caps it at 0.50 however emphatic the telling.
STATUS_CONFIDENCE_CAP = {
    OBSERVED: 0.90, INFERRED: 0.70, REPORTED: 0.50,
    TIMED_OUT: 0.80, UNOBSERVABLE: 0.0,
}

# ── §3 Lifecycle ───────────────────────────────────────────────────────────
EXPECTED = "EXPECTED"    # window open, nothing observed yet
L_OBSERVED = "OBSERVED"  # a signal arrived
CONFIRMED = "CONFIRMED"  # corroborated, or the window closed
CLOSED = "CLOSED"        # terminal
REVISED = "REVISED"      # a later record supersedes this one
RETIRED = "RETIRED"      # too old to inform current lessons (§3.5)
RETRACTED = "RETRACTED"  # withdrawn; the row itself remains readable
LIFECYCLE = (EXPECTED, L_OBSERVED, CONFIRMED, CLOSED, REVISED, RETIRED,
             RETRACTED)

# ── §2.4 Evaluation verdicts — DERIVED, never stored ───────────────────────
SUCCESS, PARTIAL, FAILURE, NEUTRAL = "SUCCESS", "PARTIAL", "FAILURE", "NEUTRAL"
VERDICTS = (SUCCESS, PARTIAL, FAILURE, NEUTRAL)

# §6.1 — time delay degrades evidential value. An outcome observed long after
# the window closed is still recorded, but is not learning-ready.
LATE_UNRELIABLE_MULTIPLE = 3.0


class OutcomeError(RuntimeError):
    """A 2I rule was violated by the CALLER. Never a storage failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return v


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


# ── ① EXPECT — created at DECISION time, not outcome time (I6, §3.1) ───────

def expect(tenant_id: str, subject: str, decision_ref: str, *,
           outcome_kind: str, window_seconds: int, expected_state: str = None,
           goal_ref: str = None, risk_tier: int = None,
           sufficiency_verdict: str = None, evidence_refs: list = None,
           observed_by: str = None, at=None) -> dict:
    """Open an observation window. Returns the EXPECTED record.

    WHY THIS EXISTS AT ALL (§3.1, I6)
    ---------------------------------
    "An outcome that only exists once something is observed can never record
    TIMED_OUT — because nothing is watching. Creating the expectation up front
    is what makes silence measurable."

    NO_RESPONSE is the most common outcome in a small business (§2.2). A
    system that only records what arrives cannot see it at all, and will learn
    exclusively from counterparties who replied.

    THE 2H LINK. `goal_ref`, `risk_tier`, `sufficiency_verdict` and
    `evidence_refs` are copied from the Context Packet — NOT the whole packet.
    §4.1 keeps the packet reachable through the decision; duplicating it here
    would create a second copy that drifts from the first.
    """
    if not decision_ref:
        raise OutcomeError(
            "decision_ref is required — an outcome attributes to exactly one "
            "decision (IDD-2I I4); an unattributed outcome teaches nothing")
    if not subject:
        raise OutcomeError("subject is required")
    if expected_state is not None and expected_state not in OBSERVED_STATES:
        raise OutcomeError(f"unknown expected_state {expected_state!r}")
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise OutcomeError("window_seconds must be a positive integer — I12: "
                           "observation windows are declared per decision type")
    if not outcome_kind:
        raise OutcomeError("outcome_kind is required")

    opened = _parse(at) or _now()
    row = {
        "outcome_id": str(uuid.uuid4()),
        "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
        "subject": subject,
        # I4 — THE single attribution edge.
        "decision_ref": decision_ref,
        "outcome_kind": outcome_kind,
        "expected_state": expected_state,
        "window_seconds": window_seconds,
        "window_opened_at": _iso(opened),
        "window_closes_at": _iso(opened + timedelta(seconds=window_seconds)),
        # Nothing observed yet. Deliberately null rather than a placeholder
        # state: a placeholder would be indistinguishable from an observation.
        "observed_state": None,
        "observation_status": None,
        "observed_at": None,
        "lifecycle": EXPECTED,
        # From the 2H packet — references, not a copy of it.
        "goal_ref": goal_ref,
        "risk_tier": risk_tier,
        "sufficiency_verdict": sufficiency_verdict,
        "evidence_refs": list(evidence_refs or []),
        "contributing_factors": [],
        "revises": None,
        "observed_by": observed_by,
        "recorded_at": _iso(_now()),
    }
    insert(TABLE, row, timeout=5)
    return row


# ── ② OBSERVE — a signal arrived (§3.2) ────────────────────────────────────

def observe(tenant_id: str, expectation: dict, observed_state: str,
            observation_status: str, *, observed_at=None,
            evidence_refs: list = None, contributing_factors: list = None,
            observed_by: str = None, reason: str = None) -> dict:
    """Record what the world did. APPENDS a new row (I3).

    The expectation is never edited — it stays readable exactly as written, so
    "what did we expect in March?" remains answerable years later.

    `contributing_factors` are recorded but are NOT attribution (§4.2): zero
    or many, associative, and they may never justify an action alone. Omitting
    them is worse than recording them unquantified, because then the model
    silently attributes their effect to the decision (§4.3).
    """
    _check_observation(observed_state, observation_status)
    prior = _require(expectation)
    when = _parse(observed_at) or _now()
    opened = _parse(prior.get("window_opened_at"))
    closes = _parse(prior.get("window_closes_at"))
    elapsed = (when - opened).total_seconds() if opened else None
    window = prior.get("window_seconds") or 0
    row = dict(prior)
    row.update({
        "outcome_id": str(uuid.uuid4()),
        "observed_state": observed_state,
        "observation_status": observation_status,
        "observed_at": _iso(when),
        "lifecycle": L_OBSERVED,
        # §2.6 — delay describes the PATH; state describes the destination.
        "elapsed_seconds": None if elapsed is None else int(elapsed),
        "variance_vs_expected": (None if elapsed is None or not window
                                 else round(elapsed / window, 4)),
        "late_beyond_window": bool(closes and when > closes),
        "evidence_refs": list(evidence_refs or prior.get("evidence_refs") or []),
        "contributing_factors": list(contributing_factors or []),
        "revises": prior["outcome_id"],
        "observed_by": observed_by,
        "reason": reason,
        "recorded_at": _iso(_now()),
    })
    insert(TABLE, row, timeout=5)
    return row


def time_out(tenant_id: str, expectation: dict, *, at=None,
             observed_by: str = None) -> dict:
    """The window closed with no signal. THIS IS DATA (I7, §2.3).

    NO_RESPONSE + TIMED_OUT, not UNKNOWN. We watched, and nothing came —
    which is a real business result, and usually the most common one.
    """
    return observe(tenant_id, expectation, NO_RESPONSE, TIMED_OUT,
                   observed_at=at or _now(), observed_by=observed_by,
                   reason="observation window closed with no signal")


# ── ③ CONFIRM · ⑤ REVISE · ⑥ RETIRE — all append (§3.3-3.5) ────────────────

def confirm(tenant_id: str, observation: dict, *, corroborated_by: str = None,
            at=None) -> dict:
    """Corroborated by a second source, or the window closed (§3.3).

    Confirmation is the GATE TO LEARNING. Provisional outcomes must never feed
    lesson generation — a lesson built on unconfirmed signal will be revised
    the moment reality arrives, and by then it has already influenced
    decisions.
    """
    prior = _require(observation)
    if not prior.get("observed_state"):
        raise OutcomeError("nothing to confirm — this record has no observation")
    row = dict(prior)
    row.update({"outcome_id": str(uuid.uuid4()), "lifecycle": CONFIRMED,
                "revises": prior["outcome_id"], "observed_by": corroborated_by,
                "reason": "corroborated" if corroborated_by else "window closed",
                "recorded_at": _iso(_parse(at) or _now())})
    insert(TABLE, row, timeout=5)
    return row


def revise(tenant_id: str, prior_record: dict, observed_state: str,
           observation_status: str, *, observed_at=None, reason: str = None,
           evidence_refs: list = None, observed_by: str = None) -> dict:
    """Late evidence produces a NEW observation linked to the original (§3.4).

    The original remains readable forever. Without this, "what did we believe
    about this outcome in March?" becomes unanswerable — and that question is
    what distinguishes *the decision was wrong* from *the outcome was later
    revised*.
    """
    _check_observation(observed_state, observation_status)
    prior = _require(prior_record)
    return observe(tenant_id, prior, observed_state, observation_status,
                   observed_at=observed_at, evidence_refs=evidence_refs,
                   observed_by=observed_by,
                   reason=reason or "revised by later evidence")


def retire(tenant_id: str, record: dict, *, reason: str,
           retired_by: str = None) -> dict:
    """Retire from ACTIVE LEARNING (§3.5). Not deletion.

    "We used to believe this, and stopped in 2029 because the market changed"
    is itself organisational knowledge. The record stays fully readable and
    replayable; only its learning eligibility changes.
    """
    if not reason:
        raise OutcomeError("retirement requires a reason — an unexplained "
                           "retirement is indistinguishable from a deletion")
    prior = _require(record)
    row = dict(prior)
    row.update({"outcome_id": str(uuid.uuid4()), "lifecycle": RETIRED,
                "revises": prior["outcome_id"], "reason": reason,
                "observed_by": retired_by, "recorded_at": _iso(_now())})
    insert(TABLE, row, timeout=5)
    return row


def retract(tenant_id: str, outcome_id: str, reason: str,
            retracted_by: str) -> dict:
    """Withdraw an observation. The row itself is NEVER deleted.

    Mirrors 2C retraction: a separate append-only record, so the retraction is
    itself auditable and the original stays explicable.
    """
    if not reason or not retracted_by:
        raise OutcomeError("retraction requires a reason and an author — an "
                           "anonymous withdrawal is not an audit trail")
    row = {"retraction_id": str(uuid.uuid4()),
           "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
           "outcome_id": outcome_id, "reason": reason,
           "retracted_by": retracted_by, "retracted_at": _iso(_now())}
    insert(RETRACTIONS_TABLE, row, timeout=5)
    return row


def _check_observation(state, status) -> None:
    if state not in OBSERVED_STATES:
        raise OutcomeError(
            f"unknown observed_state {state!r}. SUCCESS/FAILURE are NOT "
            f"observed states — they are evaluations (IDD-2I §2.1)")
    if status not in OBSERVATION_STATUSES:
        raise OutcomeError(f"unknown observation_status {status!r}")


def _require(record) -> dict:
    if not isinstance(record, dict) or not record.get("outcome_id"):
        raise OutcomeError("expected an outcome record from expect()/observe()")
    return record


# ── Reads: history and derived lifecycle ───────────────────────────────────

def history(tenant_id: str, decision_ref: str) -> list:
    """Every record for a decision, oldest first. Nothing is hidden."""
    return select(TABLE, {
        "tenant_id": f"eq.{tenant_id}", "decision_ref": f"eq.{decision_ref}",
        "order": "recorded_at.asc",
    }, timeout=5)


def current(tenant_id: str, decision_ref: str, now=None) -> dict:
    """The latest record per outcome_kind, with lifecycle DERIVED at read time.

    Derived, never stored — the same rule 2C C1 applies to claim status. A
    stored lifecycle would go stale the moment a window closed, and nothing
    would notice.
    """
    now = _parse(now) or _now()
    rows = history(tenant_id, decision_ref)
    retracted = _retracted_ids(tenant_id, [r["outcome_id"] for r in rows])
    chains = {}
    for row in rows:
        chains.setdefault(row.get("outcome_kind"), []).append(row)

    out = {}
    for kind, chain in chains.items():
        latest = chain[-1]
        superseded = {r.get("revises") for r in chain if r.get("revises")}
        state = _derive(latest, now, retracted, superseded)
        out[kind] = {"record": latest, "lifecycle": state,
                     "chain_length": len(chain),
                     "superseded_ids": sorted(x for x in superseded if x)}
    return out


def _derive(record, now, retracted_ids, superseded_ids) -> str:
    if record["outcome_id"] in retracted_ids:
        return RETRACTED
    if record["outcome_id"] in superseded_ids:
        return REVISED
    stored = record.get("lifecycle")
    if stored in (RETIRED, CONFIRMED, CLOSED):
        return stored
    if stored == EXPECTED:
        closes = _parse(record.get("window_closes_at"))
        # The window closed and nothing arrived. Silence became measurable
        # precisely because the expectation was created up front (I6).
        return CLOSED if closes and now > closes else EXPECTED
    return stored or EXPECTED


def _retracted_ids(tenant_id: str, ids: list) -> set:
    if not ids:
        return set()
    try:
        rows = select(RETRACTIONS_TABLE, {
            "tenant_id": f"eq.{tenant_id}",
            "outcome_id": f"in.({','.join(ids)})"}, timeout=5)
    except DbError:
        return set()
    return {r["outcome_id"] for r in rows}


def due_for_timeout(tenant_id: str, now=None) -> list:
    """EXPECTED records whose window has closed. The caller decides what to do.

    Returns rows rather than acting: writing NO_RESPONSE is an observation,
    and observations are made deliberately, not as a side effect of a query.
    """
    now = _parse(now) or _now()
    rows = select(TABLE, {"tenant_id": f"eq.{tenant_id}",
                          "lifecycle": f"eq.{EXPECTED}",
                          "order": "window_closes_at.asc"}, timeout=5)
    return [r for r in rows
            if (_parse(r.get("window_closes_at")) or now) < now]


# ══════════════════════════════════════════════════════════════════════════
# EVALUATION — DERIVED, RECOMPUTABLE, NEVER STORED (I1, §2.4)
# ══════════════════════════════════════════════════════════════════════════

def yardstick(yardstick_id: str, version: str, rules: dict) -> dict:
    """A named, VERSIONED definition of good.

    The version is not decoration. §2.4: change the margin target and every
    historical outcome can be re-judged — but only because the evaluation
    names which yardstick produced it. Without the version, a re-evaluation is
    indistinguishable from a contradiction.
    """
    if not yardstick_id or not version:
        raise OutcomeError("a yardstick needs an id and a version")
    unknown = set(rules) - set(OBSERVED_STATES)
    if unknown:
        raise OutcomeError(f"yardstick rules must map observed states; "
                           f"got {sorted(unknown)}")
    bad = {v for v in rules.values() if v not in VERDICTS}
    if bad:
        raise OutcomeError(f"unknown verdict(s) {sorted(bad)}")
    return {"yardstick_id": yardstick_id, "version": version,
            "rules": dict(rules)}


def evaluate(record: dict, yardstick_def: dict, now=None) -> dict:
    """Was it good? Computed fresh, every time, and returned — not written.

    NOTHING HERE IS PERSISTED. There is no insert in this function and no
    caller can ask for one. That absence is the enforcement of I1: an
    evaluation column would freeze one era's definition of success into the
    permanent record.
    """
    state = record.get("observed_state")
    verdict = (yardstick_def["rules"].get(state, NEUTRAL) if state else NEUTRAL)
    status = record.get("observation_status")
    return {
        "outcome_ref": record.get("outcome_id"),
        "yardstick_ref": yardstick_def["yardstick_id"],
        "yardstick_version": yardstick_def["version"],
        "verdict": verdict,
        "observed_state": state,
        "observation_status": status,
        # §5 / I11 — the ceiling the evidence class imposes, carried so a
        # consumer cannot treat a REPORTED outcome like a witnessed one.
        "confidence_cap": STATUS_CONFIDENCE_CAP.get(status),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "variance_vs_expected": record.get("variance_vs_expected"),
        "computed_at": _iso(_parse(now) or _now()),
        "derived": True,
        "stored": False,
    }


# ── §7.1 The readiness gate ────────────────────────────────────────────────

def learning_readiness(record: dict, lifecycle: str, *,
                       evaluation: dict = None, conflicts: list = None) -> dict:
    """May this outcome feed a lesson? All conditions, or none.

        LEARNING-READY ⟺ status ∈ {CONFIRMED, CLOSED}
                     AND attribution is to exactly one decision
                     AND no unresolved evidence conflict
                     AND not LATE_UNRELIABLE
                     AND not RETIRED
                     AND evaluation exists, with a named yardstick

    "Anything else is recorded, queryable, and EXCLUDED from lesson
    generation." Returning the reasons rather than a bare boolean matters: a
    gate that says only "no" gets worked around.
    """
    variance = record.get("variance_vs_expected")
    late_unreliable = bool(variance and variance > LATE_UNRELIABLE_MULTIPLE)
    checks = {
        "status_confirmed_or_closed": lifecycle in (CONFIRMED, CLOSED),
        "single_attribution": bool(record.get("decision_ref")),
        "no_unresolved_conflict": not (conflicts or []),
        "not_late_unreliable": not late_unreliable,
        "not_retired": lifecycle != RETIRED,
        "evaluation_with_yardstick": bool(
            evaluation and evaluation.get("yardstick_ref")
            and evaluation.get("yardstick_version")),
    }
    return {"ready": all(checks.values()), "checks": checks,
            "blocked_by": sorted(k for k, v in checks.items() if not v),
            "lifecycle": lifecycle,
            # Provisional is the common blocker and deserves naming.
            "provisional": lifecycle in (EXPECTED, L_OBSERVED)}
