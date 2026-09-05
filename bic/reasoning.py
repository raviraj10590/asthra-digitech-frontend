"""Business Reasoning Core v1 — reasoning ACROSS evidence, not retrieval of one.

WHAT THIS IS
------------
`business_status` answers "what is the number?". This answers "what is going
on, why might it be, what matters, and what should we do" — in stages, with
every intermediate object carrying the epistemic weight it actually has.

    evidence -> situation -> patterns -> diagnosis -> priorities
             -> recommendations -> rationale

THE ONE RULE THE WHOLE MODULE EXISTS TO ENFORCE
-----------------------------------------------
An observation is not a diagnosis, and a diagnosis is not a cause. "Enquiries
are 14" is a FACT. "Enquiries fell" needs a second comparable observation.
"Marketing is underperforming" needs marketing evidence, which does not exist.
"The ads caused it" needs causal evidence, which nothing here can produce.
Each of those is a different epistemic category and the boundary between them
is the product.

DETERMINISTIC BY DEFAULT (§14). Freshness, trend, confidence aggregation,
threshold checks, missing-evidence detection and contradiction detection are
arithmetic and belong in code. Nothing in this module calls a model. The
caller may hand the finished packet to CONSULT for LANGUAGE; the conclusions
are already fixed by then, so the model cannot become the source of truth.

NO AUTHORIZE, NO EXECUTE, NO COMMITMENTS. Recommendations are advisory. This
module has no write path of any kind — it takes data and returns objects.

WHAT IT DELIBERATELY WILL NOT DO
--------------------------------
It will not invent conversion, pipeline value, capacity, attribution or
revenue. Those predicates are unregistered, and the honest output is
"unmeasurable, and here is what it would take to measure it" — which is a
useful recommendation, not a failure to produce one.
"""

from typing import List, Optional

from . import context as ctx_mod
from . import knowledge as k_mod
from . import registry as reg_mod

# ── Epistemic categories (§2) ──────────────────────────────────────────────
# Every reasoning object carries exactly one. The ordering is deliberate:
# it is the strength ladder, and nothing may be promoted up it without the
# evidence that rung requires.
FACT = "FACT"                  # directly supported by registered evidence
DERIVED = "DERIVED"            # arithmetic on supported facts, nothing more
CORRELATION = "CORRELATION"    # move together; causality NOT established
HYPOTHESIS = "HYPOTHESIS"      # plausible, not established
UNKNOWN = "UNKNOWN"            # no trustworthy evidence exists
CONTRADICTED = "CONTRADICTED"  # trustworthy evidence conflicts with it

EPISTEMIC = (FACT, DERIVED, CORRELATION, HYPOTHESIS, UNKNOWN, CONTRADICTED)

# Categories that may support a recommendation at all. HYPOTHESIS is included
# ONLY because a hypothesis can justify going and measuring — never acting as
# though it were settled; enforcement of that distinction is in recommend().
ACTIONABLE = (FACT, DERIVED)

# ── Pattern kinds (§5) ─────────────────────────────────────────────────────
INCREASE = "INCREASE"
DECREASE = "DECREASE"
FLAT = "FLAT"
THRESHOLD_BREACH = "THRESHOLD_BREACH"
DIVERGENCE = "DIVERGENCE"
CONTRADICTION = "CONTRADICTION"
RECURRENCE = "RECURRENCE"
PATTERNS = (INCREASE, DECREASE, FLAT, THRESHOLD_BREACH, DIVERGENCE,
            CONTRADICTION, RECURRENCE)

# ── Diagnosis states (§6) ──────────────────────────────────────────────────
SUPPORTED = "SUPPORTED"        # evidence is strong enough to state it
PLAUSIBLE = "PLAUSIBLE"        # evidence suggests, does not prove
UNRESOLVED = "UNRESOLVED"      # evidence insufficient to choose
DIAGNOSIS_STATES = (SUPPORTED, PLAUSIBLE, UNRESOLVED)

# ── Recommendation kinds (§8) ──────────────────────────────────────────────
# MEASURE is first-class and is the honest answer far more often than ACT.
MEASURE = "MEASURE"            # capture evidence that does not yet exist
INVESTIGATE = "INVESTIGATE"    # evidence exists but does not resolve the cause
ACT = "ACT"                    # change something in the business
RECOMMENDATION_KINDS = (MEASURE, INVESTIGATE, ACT)

# A trend needs at least this many comparable observations. Two. One
# measurement is a point, and a line through one point is a decision about
# what you wanted to see (§5).
MIN_TREND_OBSERVATIONS = 2

# Below this relative change, two observations are the same reading with
# noise on it rather than a movement. A judgement call, named rather than
# buried: 5%.
FLAT_BAND = 0.05


class ReasoningError(ValueError):
    """A caller handed the core something it must not silently accept."""


# ══════════════════════════════════════════════════════════════════════════
# 1 · OBSERVATIONS — evidence in, epistemic objects out (§3)
# ══════════════════════════════════════════════════════════════════════════

def _number(value):
    """Numeric reading of a claim value, or None. Claim values are strings."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def observation(fact: dict) -> dict:
    """One packet fact -> one epistemic observation.

    GENERIC BY CONSTRUCTION (§3). Nothing here knows what an enquiry is. It
    reads the predicate, the value and the metadata 2C/2G already attach, so
    any registered business predicate flows through unchanged the day it is
    registered.

    A STALE reading is still a FACT — it was true when observed — but it is
    carried with its freshness so the layers above can refuse to trend on it.
    """
    fresh = fact.get("freshness") or {}
    prov = fact.get("provenance") or {}
    return {
        "predicate": fact.get("predicate"),
        "label": fact.get("label") or fact.get("predicate"),
        "value": fact.get("value"),
        "numeric": _number(fact.get("value")),
        "unit": fact.get("unit"),
        "observed_at": fact.get("observed_at"),
        "valid_from": fact.get("valid_from"),
        "freshness": fresh.get("verdict"),
        "provenance_tier": prov.get("tier"),
        "confidence": fact.get("confidence"),
        "epistemic": FACT,
        "evidence_ref": fact.get("claim_id"),
    }


def unknowns_from(packet: dict) -> List[dict]:
    """Missing slots -> UNKNOWN observations, each keeping WHY it is missing.

    The distinction the owner needs is not "we don't know" but "nothing can
    know this yet" (UNKNOWABLE — the predicate is not registered) versus "it
    is measured and we could not read it" (OBTAINABLE_BY_RETRIEVAL). The
    first is a product gap; the second is an outage. Collapsing them would
    send someone hunting for a broken query that never existed.
    """
    suff = (packet.get("epistemic") or {}).get("sufficiency") or {}
    out = []
    for gap in suff.get("gaps") or []:
        cls = gap.get("class")
        out.append({
            "slot": gap.get("slot"),
            "predicate": gap.get("predicate") or gap.get("slot"),
            "epistemic": UNKNOWN,
            "missing_class": cls,
            "measurable": cls != ctx_mod.UNKNOWABLE,
            "why": ("not in the evidence model — nothing records it yet"
                    if cls == ctx_mod.UNKNOWABLE
                    else "measured, but not currently available"),
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
# 2 · SITUATION MODEL (§4)
# ══════════════════════════════════════════════════════════════════════════

def situation(packet: dict, history=None) -> dict:
    """The Business Situation object: what is known, changed, stable, missing.

    `history` maps predicate -> prior claim rows (newest first), exactly what
    bic.claims.history returns. It is INJECTED rather than fetched here so
    this module keeps no database dependency and stays testable without one.

    Fields are only populated from evidence. There is no "0 anomalies" default
    that would read as "we checked and found none" when nothing was checked.
    """
    facts = (packet.get("evidence") or {}).get("facts") or []
    ep = packet.get("epistemic") or {}
    obs = [observation(f) for f in facts]
    unknown = unknowns_from(packet)

    changes, stable = [], []
    for o in obs:
        t = trend(o, (history or {}).get(o["predicate"]) or [])
        if t is None:
            continue
        (stable if t["pattern"] == FLAT else changes).append(t)

    contradictions = [{
        "predicate": c.get("predicate"),
        "epistemic": CONTRADICTED,
        "competing": len(c.get("competing_values") or []),
        "note": "more than one live value; no value has been selected",
    } for c in ep.get("conflicts") or []]

    return {
        "as_of": (packet.get("question") or {}).get("as_of")
                 or _latest(obs, "observed_at"),
        "scope": packet.get("scope"),
        "observations": obs,
        "changes": changes,
        "stable_signals": stable,
        "anomalies": [],          # only threshold/divergence findings land here
        "unknowns": unknown,
        "contradictions": contradictions,
        "confidence": aggregate_confidence(obs),
        "sufficiency": (ep.get("sufficiency") or {}).get("verdict"),
    }


def _latest(obs, key):
    vals = [o.get(key) for o in obs if o.get(key)]
    return max(vals) if vals else None


def aggregate_confidence(obs: List[dict]) -> Optional[float]:
    """Confidence of the WEAKEST supporting observation, not the average.

    A conclusion resting on several facts is only as strong as its shakiest
    leg; averaging lets one high-confidence reading launder a poor one into
    respectability. None when there is nothing to be confident about — never
    0.0, which would read as "we are certain it is nothing".
    """
    vals = [o["confidence"] for o in obs
            if o.get("confidence") is not None and o.get("epistemic") in ACTIONABLE]
    return min(vals) if vals else None


# ══════════════════════════════════════════════════════════════════════════
# 3 · PATTERN DETECTION (§5)
# ══════════════════════════════════════════════════════════════════════════

def comparable(a: dict, b: dict) -> bool:
    """Two claim rows may be compared only if they mean the same thing.

    Same predicate, same semantic version, both numeric. A version bump is a
    redefinition — comparing across it produces a trend in the DEFINITION and
    reports it as a trend in the BUSINESS, which is the most expensive kind of
    wrong answer available here.
    """
    if not a or not b:
        return False
    if a.get("predicate_ns") != b.get("predicate_ns"):
        return False
    if a.get("predicate_concept") != b.get("predicate_concept"):
        return False
    if a.get("semantic_version") != b.get("semantic_version"):
        return False
    return _number(a.get("value")) is not None and _number(b.get("value")) is not None


def trend(obs: dict, prior_claims: List[dict]) -> Optional[dict]:
    """Two or more comparable observations -> a DERIVED movement. Else None.

    RETURNS NONE FOR A SINGLE POINT, and that is the entire point of the
    function (§5). A single measurement is a FACT; calling it a trend invents
    a direction the evidence cannot support.

    STALE READINGS DO NOT TREND. An old value compared against a current one
    measures the gap between two clocks as much as two months of business.
    """
    if obs.get("numeric") is None or obs.get("freshness") == k_mod.STALE:
        return None
    usable = [c for c in (prior_claims or [])
              if _number(c.get("value")) is not None
              and c.get("claim_id") != obs.get("evidence_ref")]
    if len(usable) + 1 < MIN_TREND_OBSERVATIONS:
        return None

    prev = usable[0]
    # The prior row must be comparable to the current one. The current
    # observation is a packet fact, so rebuild the minimum comparable() needs
    # — using the REGISTRY'S OWN parser, because "biz.pipeline" is the
    # namespace and "new_enquiries_per_month" the concept, and hand-splitting
    # on the first dot silently produces a reference that matches nothing.
    try:
        ns, concept, version = reg_mod.parse_ref(obs.get("predicate") or "")
    except Exception:
        return None
    current = {"predicate_ns": ns, "predicate_concept": concept,
               "semantic_version": version, "value": obs.get("value")}
    if not comparable(current, prev):
        return None

    before, now = _number(prev["value"]), obs["numeric"]
    delta = now - before
    rel = abs(delta) / abs(before) if before else (0.0 if delta == 0 else 1.0)
    pattern = FLAT if rel <= FLAT_BAND else (INCREASE if delta > 0 else DECREASE)
    return {
        "predicate": obs["predicate"],
        "label": obs["label"],
        "pattern": pattern,
        "epistemic": DERIVED,          # arithmetic on two facts, nothing more
        "from_value": prev["value"],
        "to_value": obs["value"],
        "delta": delta,
        "relative": round(rel, 4),
        "observations": len(usable) + 1,
        "evidence_refs": [obs.get("evidence_ref"), prev.get("claim_id")],
        # NOT a cause. The movement is derived; why it moved is not.
        "cause": None,
    }


def divergence(trends: List[dict]) -> List[dict]:
    """Two trusted signals moving oppositely — a CORRELATION, never a cause."""
    out = []
    ups = [t for t in trends if t["pattern"] == INCREASE]
    downs = [t for t in trends if t["pattern"] == DECREASE]
    for u in ups:
        for d in downs:
            out.append({
                "pattern": DIVERGENCE,
                "epistemic": CORRELATION,
                "signals": [u["predicate"], d["predicate"]],
                "evidence_refs": u["evidence_refs"] + d["evidence_refs"],
                "note": "these moved in opposite directions over the same "
                        "period; no causal link is established",
                "cause": None,
            })
    return out


# ══════════════════════════════════════════════════════════════════════════
# 4 · DIAGNOSIS (§6)
# ══════════════════════════════════════════════════════════════════════════

def diagnose(sit: dict) -> List[dict]:
    """Situation -> candidate explanations, each graded by what supports it.

    A DIAGNOSIS IS NEVER AN OBSERVATION RESTATED. "Enquiries fell" is the
    observation; the diagnosis is what would explain it, and with no
    explanatory evidence registered the only honest verdict is UNRESOLVED
    with the missing evidence named.

    This function therefore produces mostly UNRESOLVED today, and that is the
    correct output for this evidence base rather than a shortcoming of the
    engine.
    """
    out = []
    for t in sit.get("changes") or []:
        if t["pattern"] == FLAT:
            continue
        explanatory = [u for u in sit.get("unknowns") or []]
        out.append({
            "about": t["predicate"],
            "statement": f"{t['label']} moved ({t['pattern'].lower()})",
            "state": UNRESOLVED,
            "epistemic": HYPOTHESIS,
            "supporting_evidence": list(t["evidence_refs"]),
            "contradicting_evidence": [],
            "confidence": None,          # a cause has no confidence to report
            "missing_evidence": [u["predicate"] for u in explanatory],
            "why_unresolved": (
                "the movement is established; its cause is not. No registered "
                "evidence distinguishes channel, campaign, market, follow-up "
                "or measurement loss."),
        })

    for c in sit.get("contradictions") or []:
        out.append({
            "about": c["predicate"],
            "statement": "the evidence for this predicate disagrees with itself",
            "state": UNRESOLVED,
            "epistemic": CONTRADICTED,
            "supporting_evidence": [],
            "contradicting_evidence": [c["predicate"]],
            "confidence": None,
            "missing_evidence": [],
            "why_unresolved": "competing live values; resolve the conflict "
                              "before drawing any conclusion from it",
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
# 5 · PRIORITISATION (§7)
# ══════════════════════════════════════════════════════════════════════════

def prioritise(sit: dict, diagnoses: List[dict]) -> List[dict]:
    """What deserves attention, ranked ONLY on evidence-backed dimensions.

    DIMENSIONS: magnitude (measured), confidence (measured), evidence quality
    (measured), recurrence (counted). NOT included: money, revenue-at-risk or
    "business impact" — none of those is registered, and scoring on an
    invented impact is how a reasoning engine starts fabricating.

    UNCERTAINTY IS A PRIORITY, NOT A DISQUALIFIER. A predicate that cannot be
    measured at all outranks a small movement in one that can: you cannot
    manage what you have not defined, and the fix is cheap and permanent.
    """
    items = []

    for u in sit.get("unknowns") or []:
        # UNKNOWABLE (unregistered) ranks above a merely unavailable reading:
        # one is a missing definition, the other a missing fetch.
        weight = 0.8 if not u.get("measurable") else 0.5
        items.append({
            "priority": f"Define and capture {u['predicate']}",
            "kind": MEASURE,
            "score": weight,
            "epistemic": UNKNOWN,
            "reason": (f"{u['predicate']} is {u['why']}. It cannot be "
                       "reasoned about until it exists."),
            "evidence_refs": [],
            "uncertainty": "high",
        })

    for t in sit.get("changes") or []:
        if t["pattern"] == FLAT:
            continue
        conf = sit.get("confidence")
        items.append({
            "priority": f"Investigate the movement in {t['label']}",
            "kind": INVESTIGATE,
            # Magnitude and confidence only — both measured, neither invented.
            "score": round(min(1.0, t["relative"]) * (conf or 0.5), 4),
            "epistemic": DERIVED,
            "reason": (f"{t['label']} moved by {t['relative']:.0%} between two "
                       "comparable observations; the cause is not established."),
            "evidence_refs": list(t["evidence_refs"]),
            "uncertainty": "medium" if conf and conf >= 0.7 else "high",
        })

    for d in diagnoses:
        if d["state"] == UNRESOLVED and d["epistemic"] == CONTRADICTED:
            items.append({
                "priority": f"Resolve conflicting evidence for {d['about']}",
                "kind": INVESTIGATE,
                "score": 0.9,
                "epistemic": CONTRADICTED,
                "reason": "contradictory live values make every downstream "
                          "conclusion unsafe.",
                "evidence_refs": [],
                "uncertainty": "high",
            })

    items.sort(key=lambda x: -x["score"])
    return items


# ══════════════════════════════════════════════════════════════════════════
# 6 · RECOMMENDATIONS (§8)
# ══════════════════════════════════════════════════════════════════════════

def recommend(priorities: List[dict], diagnoses: List[dict]) -> List[dict]:
    """Priorities -> recommendations. Never evidence -> recommendation.

    THE GATE THAT MATTERS: an ACT recommendation requires a SUPPORTED
    diagnosis. Today none exists, so this returns MEASURE and INVESTIGATE
    only — which is the correct advice for a business that can see its
    enquiry count and nothing downstream of it.

    "Define a conversion event before optimising acquisition" is a real
    recommendation. "Increase the ad budget" is a guess wearing one.
    """
    supported = {d["about"] for d in diagnoses if d["state"] == SUPPORTED}
    out = []
    for p in priorities:
        if p["kind"] == ACT and p.get("about") not in supported:
            continue                        # refused: no supported diagnosis
        out.append({
            "recommendation": p["priority"],
            "kind": p["kind"],
            "reason": p["reason"],
            "supporting_evidence": list(p.get("evidence_refs") or []),
            "assumptions": ([] if p["kind"] == MEASURE else
                            ["the movement observed is representative of the "
                             "period, not an artefact of collection"]),
            "confidence": None if p["epistemic"] is UNKNOWN else p.get("score"),
            "epistemic": p["epistemic"],
            "expected_objective": (
                "make the quantity measurable, so it can be reasoned about"
                if p["kind"] == MEASURE else
                "establish the cause before changing anything"),
            "would_change_if": (
                f"{p['priority'].split()[-1]} becomes registered and measured"
                if p["kind"] == MEASURE else
                "explanatory evidence (channel, campaign, follow-up, or "
                "measurement integrity) becomes available"),
            "advisory": True,
            "action_required": False,
        })
    return out


def rationale(sit: dict, diagnoses: List[dict], recs: List[dict]) -> dict:
    """WHY the recommendations follow — not a restatement of them (§9).

    Names the chain and, deliberately, the weakest link in it. A rationale
    that only lists what supported the answer is marketing; the useful half
    is what would have changed it.
    """
    return {
        "known": [o["label"] for o in sit.get("observations") or []],
        "derived": [t["label"] for t in sit.get("changes") or []],
        "unresolved": [d["about"] for d in diagnoses
                       if d["state"] == UNRESOLVED],
        "unknown": [u["predicate"] for u in sit.get("unknowns") or []],
        "confidence": sit.get("confidence"),
        "limiting_factor": (
            "no explanatory evidence is registered, so no cause can be "
            "established from what the business currently measures"
            if any(d["state"] == UNRESOLVED for d in diagnoses)
            else "evidence is sufficient for the conclusions drawn"),
        "no_action_authorised": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# 7 · THE WHOLE CHAIN
# ══════════════════════════════════════════════════════════════════════════

def reason(packet: dict, history=None) -> dict:
    """packet -> {situation, patterns, diagnoses, priorities, recommendations,
    rationale}. Pure: no I/O, no model, no writes.

    SCOPE IS ENFORCED, NOT ASSUMED. A PARTY packet reaching here would mean a
    customer's context is being reasoned about as though it were the
    business — the one confusion 2H's scope field exists to prevent.
    """
    if packet.get("scope") != ctx_mod.BUSINESS:
        raise ReasoningError(
            f"business reasoning requires a BUSINESS-scoped packet, "
            f"got {packet.get('scope')!r}")
    sit = situation(packet, history)
    div = divergence(sit["changes"])
    sit["anomalies"] = div
    dia = diagnose(sit)
    pri = prioritise(sit, dia)
    rec = recommend(pri, dia)
    return {
        "situation": sit,
        "patterns": list(sit["changes"]) + list(sit["stable_signals"]) + div,
        "diagnoses": dia,
        "priorities": pri,
        "recommendations": rec,
        "rationale": rationale(sit, dia, rec),
        "advisory": True,
        "action_required": False,
    }
