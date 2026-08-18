"""Knowledge Assertions — ValueClaims (IDD-2C).

"Assertions are the only place facts live. Everything else is a view."

APPEND-ONLY, STRUCTURALLY
-------------------------
This module imports `insert` and `select` BY NAME. `db.update` never enters
its namespace, so there is no reference through which a committed claim could
be mutated — the same discipline decisions_cli.py uses to prove it cannot
write. Database triggers reject UPDATE and DELETE as well: the import rule
protects against accident, the trigger protects against intent.

Corrections are NEW CLAIMS. Errors are RETRACTIONS. Neither edits a byte.

STATUS IS DERIVED, NEVER STORED (C1)
------------------------------------
    SUPERSEDED  ⟺ a later claim exists for the same (subject, predicate)
    EXPIRED     ⟺ valid_until < as_of
    RETRACTED   ⟺ a retraction record references it
    ACTIVE      ⟺ none of the above

A stored status would be a second source of truth that drifts from the claims
it describes — and the drift is silent.

BITEMPORAL (§7.1) — TWO INDEPENDENT CLOCKS
------------------------------------------
    valid_from / valid_until   when it was true IN THE WORLD
    observed_at                when WE learned it
    recorded_at                when the row entered the store

`as_known_at(T)` filters on observed_at, not valid_from. That distinction is
the whole point: "what did we BELIEVE in March?" is the question every dispute
becomes, and it is not the same question as "what was true in March?".

CONFLICTS ARE SURFACED, NEVER RESOLVED HERE (§5.3)
--------------------------------------------------
`current()` returns a list. When two claims genuinely conflict it returns both,
flagged. The seven-rung ladder is NOT implemented in this slice — and silently
picking one would be worse than not resolving, because a silent choice is
indistinguishable from knowing.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from . import config, registry
from .db import DbError, insert, select     # NOTE: `insert`/`select` only.

TABLE = "bic_claims"
RETRACTIONS_TABLE = "bic_claim_retractions"

# §6.1 — six tiers, six ceilings. Article II.6: a model can never raise its
# own confidence. Mirrored in SQL so the cap holds even if this module is
# bypassed entirely.
TIER_CAPS = {0: 1.00, 1: 0.90, 2: 0.80, 3: 0.70, 4: 0.60, 5: 0.50}

PROPOSED, VALIDATED, REJECTED = "PROPOSED", "VALIDATED", "REJECTED"

# Derived post-commit states — computed on read, never columns.
ST_ACTIVE, ST_SUPERSEDED, ST_EXPIRED, ST_RETRACTED = (
    "ACTIVE", "SUPERSEDED", "EXPIRED", "RETRACTED")


class ClaimError(RuntimeError):
    """A claim violated a 2C rule. Never a database failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else dt


# ── Write ──────────────────────────────────────────────────────────────────

def assert_claim(tenant_id: str, subject: str, predicate_ref: str, value,
                 source: str, provenance_tier: int, asserted_by: str,
                 confidence: Optional[float] = None, source_ref: Optional[str] = None,
                 valid_from=None, valid_until=None, observed_at=None) -> dict:
    """Validate against the registry, then commit an immutable claim.

    The registry check is not optional and not advisory: an assertion whose
    predicate is unregistered, DRAFT, DEPRECATED or RETIRED is rejected, as is
    a value outside the registered value space (2C V6). No free-floating facts.
    """
    if not asserted_by:
        # V3: never null. An unattributable fact is a rumour.
        raise ClaimError("asserted_by is required — an unattributable fact is a rumour")
    if provenance_tier not in TIER_CAPS:
        raise ClaimError(f"provenance_tier must be 0-5, got {provenance_tier!r}")

    concept = registry.validate_assertion(predicate_ref, value)

    cap = TIER_CAPS[provenance_tier]
    if confidence is None:
        confidence = cap
    if confidence > cap:
        raise ClaimError(
            f"confidence {confidence} exceeds tier-{provenance_tier} cap {cap} "
            f"— provenance is a ceiling, not a hint")
    if not 0 <= confidence <= 1:
        raise ClaimError("confidence must be between 0 and 1")

    now = _now()
    observed = observed_at or now
    v_from = valid_from or observed
    if valid_until is not None and _iso(valid_until) < _iso(v_from):
        raise ClaimError("valid_until must not precede valid_from")

    row = {
        "claim_id": str(uuid.uuid4()),
        "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
        "subject": subject,
        "predicate_ns": concept["namespace"],
        "predicate_concept": concept["concept"],
        "semantic_version": concept["version"],
        "value": str(value),
        "source": source,
        "provenance_tier": provenance_tier,
        "asserted_by": asserted_by,
        "source_ref": source_ref,
        "confidence": round(float(confidence), 2),
        "valid_from": _iso(v_from),
        "valid_until": _iso(valid_until) if valid_until else None,
        "observed_at": _iso(observed),
        "pre_commit_state": VALIDATED,
    }
    insert(TABLE, row, timeout=5)
    return row


def retract(tenant_id: str, claim_id: str, reason: str, retracted_by: str) -> dict:
    """Record a retraction. The original claim is NEVER deleted or modified.

    Retraction means "we should never have asserted this" — an extraction bug,
    a wrong source, a keying error. Distinct from supersession, which means
    "this was true and no longer is."

    The retracted claim stays readable forever: the decision that used it was
    made on it, and an audit that cannot reproduce a past decision is not an
    audit. Excluded from current truth, included in historical replay.
    """
    if not reason or not retracted_by:
        raise ClaimError("retraction requires both a reason and an author")
    row = {
        "retraction_id": str(uuid.uuid4()),
        "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
        "claim_id": claim_id,
        "reason": reason,
        "retracted_by": retracted_by,
    }
    insert(RETRACTIONS_TABLE, row, timeout=5)
    return row


# ── Read ───────────────────────────────────────────────────────────────────

def history(tenant_id: str, subject: str, predicate_ref: str) -> List[dict]:
    """Every claim ever written for this (subject, predicate), newest first.

    Includes superseded, expired and retracted claims. History is the record;
    filtering it would make the store unable to answer the only question that
    matters years later.
    """
    ns, concept, _version = registry.parse_ref(predicate_ref)
    return select(TABLE, {
        "tenant_id": f"eq.{tenant_id}", "subject": f"eq.{subject}",
        "predicate_ns": f"eq.{ns}", "predicate_concept": f"eq.{concept}",
        "order": "valid_from.desc,observed_at.desc",
    }, timeout=5)


def as_known_at(tenant_id: str, subject: str, predicate_ref: str, when) -> List[dict]:
    """What we BELIEVED at time T — filtered on observed_at, not valid_from.

    Not the same as "what was true at T". A fact learned in June about March is
    invisible to a March-time query, which is precisely what makes replay
    honest: hindsight cannot contaminate a reconstruction.
    """
    ns, concept, _version = registry.parse_ref(predicate_ref)
    return select(TABLE, {
        "tenant_id": f"eq.{tenant_id}", "subject": f"eq.{subject}",
        "predicate_ns": f"eq.{ns}", "predicate_concept": f"eq.{concept}",
        "observed_at": f"lte.{_iso(when)}",
        "order": "valid_from.desc,observed_at.desc",
    }, timeout=5)


def current(tenant_id: str, subject: str, predicate_ref: str, as_of=None) -> dict:
    """Current truth, with conflicts SURFACED rather than resolved.

    Returns {claims, conflict, states, cardinality}. `conflict` is True when
    more than one claim survives a SINGLE-cardinality predicate — the
    seven-rung ladder is not implemented in this slice, and picking one
    silently would be the single most dangerous behaviour a knowledge system
    can exhibit, because it is indistinguishable from knowing.

    CARDINALITY DECIDES WHAT SUPERSESSION MEANS (D12)
    -------------------------------------------------
    Supersession is per-VALUE for a `multi` predicate and per-PREDICATE for a
    `single` one:

        single   a party has ONE current service interest — a later claim
                 replaces the earlier one, whatever its value
        multi    a party may hold SEVERAL phone numbers at once — a later
                 claim replaces only an earlier claim of THE SAME value

    Reading supersession globally for a `multi` predicate silently deletes
    true facts: assert phone A then phone B, and A becomes SUPERSEDED even
    though both are live. The registry is the authority on which rule applies,
    so the answer cannot drift from the declared meaning.
    """
    as_of = as_of or _now()
    rows = as_known_at(tenant_id, subject, predicate_ref, as_of)
    retracted = _retracted_ids(tenant_id, [r["claim_id"] for r in rows])
    cardinality = _cardinality(predicate_ref)

    # One supersession bucket for `single`; one bucket PER VALUE for `multi`.
    newest = {}
    for r in rows:
        key = _bucket(r, cardinality)
        stamp = _iso(r["valid_from"])
        if key not in newest or stamp > newest[key]:
            newest[key] = stamp

    states, live = {}, []
    for r in rows:
        state = derive_state(r, as_of=as_of, retracted_ids=retracted,
                             newest_valid_from=newest[_bucket(r, cardinality)])
        states[r["claim_id"]] = state
        if state == ST_ACTIVE:
            live.append(r)

    # For `single`, two surviving values is a genuine contradiction. Identical
    # values from several sources is agreement — evidence, not conflict (§5.4).
    # For `multi`, several values is the DECLARED SHAPE of the predicate and
    # never a conflict.
    distinct = {r["value"] for r in live}
    conflict = cardinality == "single" and len(distinct) > 1
    return {
        "claims": live,
        "states": states,
        "cardinality": cardinality,
        "conflict": conflict,
        "unresolved_values": sorted(distinct) if conflict else [],
    }


def _bucket(claim: dict, cardinality: str):
    """Supersession bucket: per-predicate for `single`, per-value for `multi`."""
    return claim["value"] if cardinality == "multi" else None


def _cardinality(predicate_ref: str) -> str:
    """The registry is the authority. A concept that cannot be read falls back
    to `single` — the conservative choice, since it can only mark MORE claims
    superseded, never fabricate a live one."""
    try:
        concept = registry.lookup_ref(predicate_ref)
    except Exception:
        return "single"
    return (concept or {}).get("cardinality") or "single"


def derive_state(claim: dict, as_of, retracted_ids, newest_valid_from) -> str:
    """Post-commit state, COMPUTED (C1). Never read from a column."""
    if claim["claim_id"] in retracted_ids:
        return ST_RETRACTED
    if claim.get("valid_until") and _iso(claim["valid_until"]) < _iso(as_of):
        return ST_EXPIRED
    if newest_valid_from and _iso(claim["valid_from"]) < _iso(newest_valid_from):
        return ST_SUPERSEDED
    return ST_ACTIVE


def _retracted_ids(tenant_id: str, claim_ids: List[str]) -> set:
    if not claim_ids:
        return set()
    rows = select(RETRACTIONS_TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "claim_id": f"in.({','.join(claim_ids)})",
    }, timeout=5)
    return {r["claim_id"] for r in rows}
