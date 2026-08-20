"""knowledge.describe — the first real 2G capability (IDD-2G).

WHAT A CAPABILITY IS
--------------------
"A declared, policy-gated, audited contract for obtaining or asserting
business knowledge — expressed in business terms, with provenance and
freshness attached." This module is the QUERY half of that sentence, made
executable against facts that are already in production.

WHAT IT IS NOT
--------------
It is not a query API over bic_claims. The difference is the envelope: a query
API returns rows and lets the caller decide what they mean, while a capability
returns an answer that carries how well it is known, how old it is, what was
consulted, what was NOT found, and whether the answer is degraded. A caller
that ignores every field except `values` still cannot mistake UNKNOWN for
DENIED, because those are different states rather than different row counts.

THE FOUR STATES (2G §6.2, §6.3)
-------------------------------
    KNOWN        at least one live claim was found
    UNKNOWN      we looked and there is nothing. A real, useful answer.
    DENIED       the caller is not permitted to know. NEVER rendered as empty
                 — "no data" and "not allowed" must never look alike, or an
                 access control failure becomes indistinguishable from an
                 absence of facts.
    UNAVAILABLE  we could not reach the knowledge. Also never empty: a store
                 outage that reads as "the customer has no interests" is how a
                 system lies without anyone writing a lie.

NO SECOND AUTHORIZATION PATH (2G D1)
------------------------------------
The gate is `bic.policy.may_invoke` — the same function the Tool Registry
calls, given the same descriptor. "Two authorization paths is one
authorization hole." A caller that supplies a principal but no descriptor is
DENIED, because may_invoke denies an unknown tool.

NO DATABASE ACCESS
------------------
This module imports no `db` primitive and issues no PostgREST call. Every fact
arrives through bic/claims.py, every meaning through bic/registry.py, every
identity through bic/party.py. That is not tidiness: bic/claims.py is the only
place that knows supersession, retraction and cardinality (D12), and a
capability that reached past it into the table would re-derive that logic
slightly differently and be wrong in a way nobody could see.

CONFLICTS ARE CARRIED, NEVER PRUNED (2G §3.5)
---------------------------------------------
When a single-cardinality predicate has two live values, BOTH appear in
`values` and the disagreement is named in `conflicts`. The seven-rung
resolution ladder (2G §3.4) is not implemented here and must not be: choosing
silently is indistinguishable from knowing.

NO PII
------
The envelope carries `claim_id` (opaque) and `source_kind` (the scheme of the
source reference, e.g. `wa_msg`), never `source_ref` itself, never an
identifier value, never message text. Explainability survives — a privileged
reader can fetch the claim by id — but a renderer cannot leak a wamid or a
phone number by printing the envelope.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import claims as claims_mod
from . import party as party_mod
from . import registry
from .db import DbError
from .policy import may_invoke

# ── Result states (2G §6.2, §6.3) ──────────────────────────────────────────
KNOWN, UNKNOWN, DENIED, UNAVAILABLE = "KNOWN", "UNKNOWN", "DENIED", "UNAVAILABLE"
STATES = (KNOWN, UNKNOWN, DENIED, UNAVAILABLE)

# ── Freshness verdicts ─────────────────────────────────────────────────────
FRESH, STALE, PERMANENT = "FRESH", "STALE", "PERMANENT"
FRESHNESS_VERDICTS = (FRESH, STALE, PERMANENT)

# ── Declared degradation reasons (2G §6.1) ─────────────────────────────────
# "Unspecified" degradation is rejected: a capability that admits to being
# degraded without saying how leaves the caller with strictly less information
# than one that never mentioned it.
DEG_PREDICATE_UNAVAILABLE = "predicate_unavailable"
DEG_PREDICATE_UNREGISTERED = "predicate_unregistered"
DEG_CONFLICT_PRESENT = "conflict_present"
DEG_STALE_VALUE = "stale_value"
DEGRADATION_REASONS = (
    DEG_PREDICATE_UNAVAILABLE, DEG_PREDICATE_UNREGISTERED,
    DEG_CONFLICT_PRESENT, DEG_STALE_VALUE,
)

# ── Reasons a whole call cannot be answered ────────────────────────────────
R_IDENTITY_DISPUTED = "identity_disputed"
R_IDENTITY_UNRESOLVABLE = "identity_unresolvable"
R_STORE_UNAVAILABLE = "store_unavailable"
R_UNKNOWN_ENTITY = "unknown_entity"
R_NO_CLAIMS = "no_claims_found"
R_NOT_AUTHORIZED = "not_authorized"

# ══════════════════════════════════════════════════════════════════════════
# STALENESS BOUNDS — A CHOSEN NUMBER, NOT AN IDD NUMBER
# ══════════════════════════════════════════════════════════════════════════
# IDD-2G §3.3: "Every capability declares a staleness bound... Bounds derive
# from the predicate's volatility class (2A §3.5), so they are per-fact rather
# than global." The IDD fixes the MECHANISM (per-volatility, per-fact) and the
# registry supplies the class. It does not state the durations.
#
# These four numbers are therefore a DECISION made here, and they are stated
# as data so that changing them is a one-line review rather than an
# archaeology exercise:
#
#   static  a fact that cannot change (first contact happened when it
#           happened). No bound: PERMANENT, never STALE. A bound here would
#           report a true, immutable fact as suspect purely because time
#           passed, which is worse than useless.
#   slow    180 days. Calibrated to Asthra DigiTech's actual sales rhythm: a
#           service interest declared last week is actionable, one declared
#           eight months ago is a re-qualification, not a lead.
#   fast    24 hours.
#   live    5 minutes.
#
# `fast` and `live` have NO production consumer yet — no seeded predicate uses
# either class. They are declared rather than omitted so that the first
# predicate that needs one inherits a considered default instead of a hurried
# one, but they are untested against reality and should be revisited by
# whoever registers that predicate.
STALENESS_BOUNDS = {
    "static": None,
    "slow": timedelta(days=180),
    "fast": timedelta(hours=24),
    "live": timedelta(minutes=5),
}

# A volatility class the registry allows but this table does not cover would
# silently fall through to "no bound" — i.e. would claim permanence. Guard it.
_DEFAULT_BOUND = STALENESS_BOUNDS["slow"]


class KnowledgeError(RuntimeError):
    """A capability contract was violated by the CALLER. Never a DB failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp):
    """Timestamps arrive from PostgREST as strings and from tests as datetimes."""
    if isinstance(stamp, datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    if not stamp:
        return None
    text = str(stamp).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(stamp):
    parsed = _parse(stamp)
    return parsed.isoformat() if parsed else None


# ── The capability ─────────────────────────────────────────────────────────

def describe(tenant_id: str, entity: str, predicates: Optional[list] = None,
             *, as_of=None, as_known_at=None,
             principal=None, descriptor=None, trace_ref=None) -> dict:
    """What do we know about this party, and how well do we know it?

    `entity`      a knowledge_id (2B). Never a phone, never a name.
    `predicates`  OPTIONAL (2G §3.1). OMITTED (None) means "the whole live
                  vocabulary that applies to this kind of party" — asked of
                  the registry, never a hard-coded list that would drift. An
                  EMPTY list means consult nothing, and is not the same thing.
    `as_of`       world time: what was TRUE then.
    `as_known_at` system time: what we BELIEVED then.
    `principal`   supply together with `descriptor` to have the call gated by
                  the same policy the Tool Registry uses. Omit both for an
                  internal call that is already gated by its caller.
    `trace_ref`   the caller's existing audit handle (a decision-record id).
                  NOT generated here: a uuid this module minted and stored
                  nowhere would look like an audit handle while leading
                  nowhere, and §7 explainability that dead-ends is worse than
                  none. When absent, the per-value `claim_id` is the durable
                  handle back to the evidence.

    Always returns an envelope. Never raises for missing knowledge, a denied
    caller or an unreachable store — each of those is a distinct STATE, and
    turning one into an exception is how they get flattened into "no data".
    """
    started = _now()
    envelope = _envelope(entity, predicates, as_of, as_known_at, started,
                         trace_ref)

    # 1. Authorization — the Tool Registry's own gate, or nothing (D1).
    if principal is not None:
        allowed, reason = may_invoke(principal, descriptor)
        if not allowed:
            envelope["state"] = DENIED
            envelope["reason"] = R_NOT_AUTHORIZED
            envelope["denial_detail"] = reason
            return envelope

    # 2. Identity — a MERGED party must answer as its survivor, and a DISPUTED
    #    one must not answer at all (2D §3.8, D14).
    try:
        subject = party_mod.resolve_survivor(tenant_id, entity)
        party = party_mod.lookup(tenant_id, subject)
    except party_mod.DisputedIdentityError:
        envelope["state"] = UNAVAILABLE
        envelope["reason"] = R_IDENTITY_DISPUTED
        return envelope
    except party_mod.PartyError:
        # Not found, orphaned MERGED, or a merge cycle. The first is genuine
        # absence of knowledge; the other two are corrupt identity. They are
        # NOT the same, and only the first is UNKNOWN.
        if party_mod.lookup(tenant_id, entity) is None:
            envelope["state"] = UNKNOWN
            envelope["reason"] = R_UNKNOWN_ENTITY
            return envelope
        envelope["state"] = UNAVAILABLE
        envelope["reason"] = R_IDENTITY_UNRESOLVABLE
        return envelope
    except DbError:
        envelope["state"] = UNAVAILABLE
        envelope["reason"] = R_STORE_UNAVAILABLE
        return envelope

    envelope["subject"] = subject
    envelope["identity"] = {
        "kind": (party or {}).get("kind"),
        # 2D R2: a party known only by a phone is PROVISIONAL, and a caller
        # deciding whether to act on these facts needs to see that.
        "resolution_state": (party or {}).get("resolution_state"),
    }
    if subject != entity:
        # The caller asked about an absorbed identity. Say so rather than
        # quietly answering about somebody else.
        envelope["redirected_from"] = entity

    # 3. Which predicates to consult.
    try:
        concepts = _concepts_for(predicates, party)
    except DbError:
        envelope["state"] = UNAVAILABLE
        envelope["reason"] = R_STORE_UNAVAILABLE
        return envelope

    for ref in concepts["unregistered"]:
        envelope["coverage"]["unregistered"].append(ref)
        _degrade(envelope, DEG_PREDICATE_UNREGISTERED, ref)
    # `as_of` and `as_known_at` collapse into one cutoff — see the note on
    # _cutoff(). Recorded in the envelope so a reader can see which was used.
    cutoff = _cutoff(as_of, as_known_at, started)
    envelope["evaluated_at"] = _iso(cutoff)

    # 4. Consult each predicate. One failing predicate degrades the answer; it
    #    does not destroy it (2G §6.1).
    for concept in concepts["concepts"]:
        ref = registry.format_ref(concept["namespace"], concept["concept"],
                                  concept["version"])
        envelope["coverage"]["consulted"].append(ref)
        try:
            result = claims_mod.current(tenant_id, subject, ref, as_of=cutoff)
        except DbError:
            envelope["coverage"]["unavailable"].append(ref)
            _degrade(envelope, DEG_PREDICATE_UNAVAILABLE, ref)
            continue

        live = result.get("claims") or []
        if not live:
            envelope["coverage"]["absent"].append(ref)
            continue
        envelope["coverage"]["known"].append(ref)

        states = result.get("states") or {}
        for claim in live:
            value = _value(claim, concept, cutoff,
                           states.get(claim.get("claim_id")))
            envelope["values"].append(value)
            if value["freshness"]["verdict"] == STALE:
                _degrade(envelope, DEG_STALE_VALUE, ref)

        if result.get("conflict"):
            envelope["conflicts"].append({
                "predicate": ref,
                "values": list(result.get("unresolved_values") or []),
                "cardinality": result.get("cardinality"),
                "reason": "multiple_active_values_on_single_cardinality",
                # 2G §3.4: the ladder lives above this capability, not inside
                # it. Saying so in the payload stops a caller assuming the
                # disagreement was already adjudicated and just not shown.
                "resolved": False,
            })
            _degrade(envelope, DEG_CONFLICT_PRESENT, ref)

    # 5. State.
    if envelope["values"]:
        envelope["state"] = KNOWN
    elif envelope["coverage"]["unavailable"]:
        # Nothing found AND something unreadable. UNKNOWN would assert that we
        # looked everywhere we were asked to look, and we did not. "We learned
        # nothing" and "there is nothing" are different answers, and only the
        # store can tell them apart. coverage.absent still names the
        # predicates we DID reach and found empty, so no information is lost
        # by refusing to overclaim here.
        envelope["state"] = UNAVAILABLE
        envelope["reason"] = R_STORE_UNAVAILABLE
    else:
        envelope["state"] = UNKNOWN
        envelope["reason"] = R_NO_CLAIMS

    envelope["freshness"] = _overall_freshness(envelope["values"])
    envelope["confidence"] = _confidence_vector(envelope)
    return envelope


# ── Envelope construction ──────────────────────────────────────────────────

def _envelope(entity, predicates, as_of, as_known_at, started,
              trace_ref) -> dict:
    return {
        "capability": "knowledge.describe",
        "state": UNKNOWN,
        "reason": None,
        "entity": entity,
        "subject": None,
        "identity": {"kind": None, "resolution_state": None},
        "values": [],
        "conflicts": [],
        "coverage": {
            "requested": None if predicates is None else list(predicates),
            "consulted": [],
            "known": [],
            "absent": [],
            "unavailable": [],
            "unregistered": [],
        },
        "freshness": {"verdict": None, "oldest_observed_at": None,
                      "stale_predicates": []},
        "confidence": None,
        "degraded": False,
        "degradation": [],
        "trace_ref": trace_ref,
        "asked_at": _iso(started),
        "evaluated_at": None,
        "as_of": _iso(as_of),
        "as_known_at": _iso(as_known_at),
    }


def _degrade(envelope: dict, reason: str, ref) -> None:
    """Record a NAMED degradation. §6.1 rejects 'unspecified'."""
    if reason not in DEGRADATION_REASONS:
        raise KnowledgeError(
            f"{reason!r} is not a declared degradation reason — an unnamed "
            f"degradation tells the caller strictly less than silence")
    envelope["degraded"] = True
    entry = {"reason": reason, "predicate": ref}
    if entry not in envelope["degradation"]:
        envelope["degradation"].append(entry)


def _cutoff(as_of, as_known_at, started):
    """The single time bound bic/claims.py accepts.

    KNOWN LIMITATION, DELIBERATELY NOT PAPERED OVER. `claims.current(as_of=T)`
    filters `observed_at <= T` and also derives expiry at T, so one parameter
    does the work of both world time and system time. Passing `as_of` and
    `as_known_at` separately would require new temporal semantics inside
    bic/claims.py, which this slice does not own.

    So: `as_known_at` wins when supplied, otherwise `as_of`, otherwise now —
    and the envelope reports both inputs plus the `evaluated_at` actually
    used, so a reader can see the collapse instead of being fooled by it.
    """
    return _parse(as_known_at) or _parse(as_of) or started


def _concepts_for(predicates, party) -> dict:
    """Resolve the predicate list to concept rows.

    An explicitly requested predicate that is not registered is a CALLER
    error, not missing knowledge — it is reported as `unregistered`, never as
    `absent`, because "we have no such fact" and "there is no such thing as
    that fact" are different answers.
    """
    if predicates is not None:
        # An EMPTY list means consult nothing. Treating it as "omitted" would
        # turn a filtered-to-empty caller list into a full scan of the
        # vocabulary — the opposite of what the caller computed, and the
        # expensive direction to be wrong in.
        found, unregistered = [], []
        for ref in predicates:
            try:
                row = registry.lookup_ref(ref)
            except registry.RegistryError:
                unregistered.append(ref)
                continue
            if row is None:
                unregistered.append(ref)
            else:
                found.append(row)
        return {"concepts": found, "unregistered": unregistered}

    kind = (party or {}).get("kind")
    concepts = []
    for row in registry.active_concepts():
        applies = row.get("applies_to") or []
        # An empty applies_to means "anything"; a populated one is a filter.
        if applies and kind and kind not in applies:
            continue
        concepts.append(row)
    return {"concepts": concepts, "unregistered": []}


def _value(claim: dict, concept: dict, cutoff, status) -> dict:
    """One live claim, rendered as knowledge rather than as a row.

    `status` is READ from bic/claims.py rather than assumed to be ACTIVE.
    Only live claims reach here, so hard-coding ACTIVE would be true today and
    silently wrong the moment an EXPLAIN capability wants superseded ones —
    and the derivation is exactly what 2C C1 says must never be stored.
    """
    ref = registry.format_ref(concept["namespace"], concept["concept"],
                              concept["version"])
    return {
        "predicate": ref,
        "label": concept.get("label"),
        "value": claim.get("value"),
        "unit": concept.get("unit"),
        # From the registry, because it is what makes SUPERSEDED mean two
        # different things (D12) — a reader that does not know the cardinality
        # cannot interpret "one live value" correctly.
        "cardinality": concept.get("cardinality"),
        "semantic_version": claim.get("semantic_version"),
        "status": status,
        "confidence": claim.get("confidence"),
        "provenance": {
            "tier": claim.get("provenance_tier"),
            "cap": claims_mod.TIER_CAPS.get(claim.get("provenance_tier")),
            "source": claim.get("source"),
            # The SCHEME only. `source_ref` itself can carry a wamid, and a
            # renderer that prints the envelope must not be able to leak one.
            "source_kind": _source_kind(claim.get("source_ref")),
            "asserted_by": claim.get("asserted_by"),
        },
        "valid_from": _iso(claim.get("valid_from")),
        "valid_until": _iso(claim.get("valid_until")),
        "observed_at": _iso(claim.get("observed_at")),
        "freshness": _freshness(claim, concept, cutoff),
        # Opaque, and the only handle back to the underlying row.
        "claim_id": claim.get("claim_id"),
    }


# A scheme is a lowercase identifier and nothing else. Anything that fails
# this is not shown.
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# There IS a source reference, but it declares no scheme we can safely show.
# Distinct from None, which means there is no source reference at all.
OPAQUE_SOURCE = "opaque"


def _source_kind(source_ref) -> Optional[str]:
    """The SCHEME of a source reference, or nothing.

    Splitting on ':' and returning the head is not enough. A source_ref
    written without a prefix — a bare `wamid.HBgM...`, a `lead_9199...` —
    has no ':' at all, so the head IS the whole value and the wamid walks
    straight into the envelope. Every writer today prefixes with `wa_msg:`,
    so nothing leaks in production; but the docstring above this module
    promises that a renderer CANNOT print a wamid, and a promise that holds
    only while every future writer remembers a convention is not that promise.

    So a scheme is shown only when there IS a delimiter and the part before
    it is shaped like a lowercase identifier. Both halves are needed: the
    delimiter check stops `lead_919999000222`, which is a perfectly valid
    identifier shape and still a phone number; the shape check stops
    `910000000000:x`. This is the structural version of the guarantee rather
    than a convention every future writer has to remember.
    """
    if not source_ref:
        return None
    text = str(source_ref)
    if ":" not in text:
        # No delimiter means no scheme. The head is the WHOLE value, so
        # returning it would show a bare wamid or a `lead_<phone>` in full.
        return OPAQUE_SOURCE
    head = text.split(":", 1)[0]
    return head if _SCHEME_RE.match(head) else OPAQUE_SOURCE


def _freshness(claim: dict, concept: dict, cutoff) -> dict:
    """Per-fact staleness, from the predicate's volatility class (2G §3.3).

    Measured from `observed_at` — when we LEARNED it — not `valid_from`. A
    fact backdated to last year but confirmed this morning is fresh
    knowledge about an old event; measuring from valid_from would call it
    stale and be wrong in the one case that matters.
    """
    volatility = concept.get("volatility_class")
    bound = STALENESS_BOUNDS.get(volatility, _DEFAULT_BOUND)
    observed = _parse(claim.get("observed_at"))
    age = None
    if observed and cutoff:
        age = max((cutoff - observed).total_seconds(), 0.0)

    if bound is None:
        verdict = PERMANENT
    elif age is None:
        # No observed_at is not freshness information; refusing to guess is
        # the point of having a verdict field at all.
        verdict = STALE
    else:
        verdict = STALE if age > bound.total_seconds() else FRESH

    return {
        "verdict": verdict,
        "volatility_class": volatility,
        "bound_seconds": None if bound is None else int(bound.total_seconds()),
        "age_seconds": None if age is None else int(age),
        "observed_at": _iso(claim.get("observed_at")),
    }


def _overall_freshness(values: list) -> dict:
    """The WORST verdict, not the average.

    An answer built from one fresh fact and one stale one is a stale answer.
    Averaging would let a pile of permanent facts hide the single decayed one
    the caller was actually going to act on.
    """
    if not values:
        return {"verdict": None, "oldest_observed_at": None,
                "stale_predicates": []}
    stale = sorted({v["predicate"] for v in values
                    if v["freshness"]["verdict"] == STALE})
    verdicts = {v["freshness"]["verdict"] for v in values}
    if STALE in verdicts:
        overall = STALE
    elif FRESH in verdicts:
        overall = FRESH
    else:
        overall = PERMANENT
    observed = sorted(o for o in (v["observed_at"] for v in values) if o)
    return {"verdict": overall,
            "oldest_observed_at": observed[0] if observed else None,
            "stale_predicates": stale}


def _confidence_vector(envelope: dict) -> dict:
    """Confidence as a VECTOR, not a number (2G §7.3).

    A single blended score is the most dangerous thing this module could
    return: 0.5 could mean a well-sourced fact about a doubtful identity, or a
    rumour about a certain one, and the caller cannot tell which. So the
    dimensions stay separate and the caller does its own collapsing, knowingly.

      value_confidence     lowest per-claim confidence — the weakest fact
                           bounds the answer
      provenance_ceiling   lowest tier cap present; the best this answer could
                           possibly be worth however sure the asserter felt
      coverage_ratio       how much of what we consulted we actually know
      identity_state       the party's resolution_state, NOT a number. 2D
                           has not landed, so there is no calibrated
                           probability that this identity is the right one;
                           emitting one would be inventing it. PROVISIONAL is
                           what we actually know (2D R2).
    """
    values = envelope["values"]
    coverage = envelope["coverage"]
    consulted = len(coverage["consulted"])
    known = len(coverage["known"])
    confidences = [v["confidence"] for v in values if v["confidence"] is not None]
    caps = [v["provenance"]["cap"] for v in values
            if v["provenance"]["cap"] is not None]
    return {
        "value_confidence": min(confidences) if confidences else None,
        "provenance_ceiling": min(caps) if caps else None,
        "coverage_ratio": round(known / consulted, 4) if consulted else None,
        "identity_state": envelope["identity"]["resolution_state"],
    }
