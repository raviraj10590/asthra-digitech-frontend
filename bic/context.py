"""Business Context Packet & Sufficiency Gate (IDD-2H).

THE ONE IDEA (§0.1)
-------------------
"The packet is the only thing a model ever sees, and it is not a prompt."

A prompt is provider-shaped text. A packet is a typed, immutable, auditable
business artifact. Rendering it into whatever text a provider wants is the
adapter's job — and that is precisely why a model can be replaced without
touching anything above it. The packet outlives the model.

THE QUESTION THIS ANSWERS
-------------------------
"Do I have enough trustworthy information to complete this business task?"

Not "what do we know" — 2G answers that. Sufficiency is a property of the
(evidence, action) PAIR, never of the evidence alone (§4.4). The same fact
can be sufficient for a summary and insufficient for a payment.

THE THREE CORRECTIONS, HONOURED STRUCTURALLY
--------------------------------------------
C1 (§0.2) Policies are NOT evidence. They live in BOUNDARIES, never in
          EVIDENCE, and they are advisory to the proposer — enforcement is
          downstream and deterministic. A packet that blurs them invites the
          model to negotiate with the rules.
C2 (§0.3) There is NO packet-level confidence scalar. Every FACT carries
          confidence; the PACKET carries a sufficiency verdict. A single
          number would be an average over unlike things.
C3 (§0.4) The budget cuts EVIDENCE only. Conflicts, boundaries, missing-
          information and the verdict are structural and never budget-
          eligible. A trimmed conflict is an invisible wrong answer.

NO STORAGE, NO MODEL
--------------------
This module imports no db primitive and calls no provider. Evidence arrives
through knowledge.describe; identity through owner_context/party. I11:
"Assembly makes no AI calls" is enforced by there being nothing here that
could make one.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from .policy import may_invoke

# ── Versions, independently carried (§8.3) ─────────────────────────────────
# Conflating these is the classic replay error: a policy change reported as an
# engine regression floods the harness with false alarms.
PACKET_SCHEMA_VERSION = "2H.1.0"
ASSEMBLY_VERSION = "context.assemble/1.0.0"

# ── Five sufficiency verdicts (§4.2) ───────────────────────────────────────
PROCEED, CLARIFY, RETRIEVE, ESCALATE, REFUSE = (
    "PROCEED", "CLARIFY", "RETRIEVE", "ESCALATE", "REFUSE")
VERDICTS = (PROCEED, CLARIFY, RETRIEVE, ESCALATE, REFUSE)

# ── Five missing-information classes (§4.3) ────────────────────────────────
# "We don't have it" and "we can't get it" require different responses, and a
# gate that cannot tell them apart will either refuse too often or ask
# pointless questions. Maps onto 2C §5.6 absence kinds — absence is data.
OBTAINABLE_BY_ASKING = "OBTAINABLE_BY_ASKING"
OBTAINABLE_BY_RETRIEVAL = "OBTAINABLE_BY_RETRIEVAL"
UNOBTAINABLE_NOW = "UNOBTAINABLE_NOW"
UNKNOWABLE = "UNKNOWABLE"
REFUSED = "REFUSED"
MISSING_CLASSES = (OBTAINABLE_BY_ASKING, OBTAINABLE_BY_RETRIEVAL,
                   UNOBTAINABLE_NOW, UNKNOWABLE, REFUSED)

_CLASS_TO_VERDICT = {
    OBTAINABLE_BY_ASKING: CLARIFY,
    OBTAINABLE_BY_RETRIEVAL: RETRIEVE,
    UNOBTAINABLE_NOW: REFUSE,
    UNKNOWABLE: REFUSE,
    REFUSED: REFUSE,
}

# ── Subject scope (§2.2 "whose context is this?") ──────────────────────────
# A packet has always carried a `subject`. It has never carried what KIND of
# thing that subject is, and the two questions the Brain must answer are not
# the same question:
#
#   PARTY     "why is this customer's engagement low?"  → about a counterparty
#   BUSINESS  "what should I focus on this month?"      → about Asthra itself
#
# Forcing the second into the first is what this adds scope to prevent. There
# is no fake party for the business: the subject of a BUSINESS packet is the
# tenant's own ORGANIZATION party, which 2B already models and
# bic/pipeline_evidence.py already resolves — this introduces no second
# identity concept.
#
# PARTY is the default everywhere, so every goal, packet and caller that
# existed before this constant behaves exactly as it did.
PARTY, BUSINESS = "PARTY", "BUSINESS"
SCOPES = (PARTY, BUSINESS)

# The 2B party kind a BUSINESS-scoped subject must be, and the value the 2A
# registry's `applies_to` must contain for a predicate to be assertable about
# it. Named here so the compatibility rule is one constant, not a literal
# repeated at each comparison.
BUSINESS_PARTY_KIND = "ORGANIZATION"

# ── Assembly outcome, kept SEPARATE from the verdict ───────────────────────
# A packet that could not be assembled and a packet that was assembled and
# found wanting are different situations. Collapsing them would make an
# outage read as an insufficiency.
A_OK, A_DENIED, A_UNAVAILABLE, A_UNKNOWN = (
    "OK", "DENIED", "UNAVAILABLE", "UNKNOWN")
ASSEMBLY_STATES = (A_OK, A_DENIED, A_UNAVAILABLE, A_UNKNOWN)

# ── Conflict severity (§6.3) ───────────────────────────────────────────────
HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

# ══════════════════════════════════════════════════════════════════════════
# THRESHOLDS — GOVERNED, NOT TUNED (§4.6)
# ══════════════════════════════════════════════════════════════════════════
# §4.4 gives the confidence floors as a table. They are reproduced exactly.
#
# Lowering any of these is a Structural decision at L5, recorded and
# approved — NOT a code edit. §4.6: "Without this, thresholds drift downward
# every time they block work, and within a year nothing is gated. That
# erosion is silent and is the most likely way this gate dies."
RISK_CONFIDENCE_FLOOR = {1: 0.50, 2: 0.60, 3: 0.80, 4: 0.95}

# §4.4 states freshness tolerance in words — "Generous / Generous / Tight /
# Tightest" — not numbers. Rather than invent durations, this reuses the
# freshness VERDICT that knowledge.describe already computes per fact from
# the predicate's own volatility class. Tiers 1-2 accept a STALE fact but
# record the degradation; tiers 3-4 do not accept it at all.
RISK_ACCEPTS_STALE = {1: True, 2: True, 3: False, 4: False}

# §4.4: tier 4 is "0.95 + human approval". Approval is not a threshold, so it
# is carried separately rather than folded into the number.
RISK_REQUIRES_APPROVAL = {1: False, 2: False, 3: False, 4: True}


class ContextError(RuntimeError):
    """The CALLER violated the contract. Never a storage failure."""


class FrozenPacket(dict):
    """A packet is immutable once assembled (I2, criterion 19).

    Assembly ends with a freeze. Every later reader — the Brain, EXPLAIN,
    replay — sees exactly what the gate saw. A packet that could be edited
    after assessment would make the verdict unfalsifiable.
    """

    def _frozen(self, *a, **k):
        raise ContextError(
            "packet is immutable once assembled (IDD-2H I2) — assemble a new "
            "one rather than editing the record of what was decided")

    __setitem__ = __delitem__ = _frozen
    pop = popitem = clear = update = setdefault = _frozen


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return v


def _deep(value):
    return json.loads(json.dumps(value, default=str))


# ── The generic requirement mechanism (§2 required_slots) ──────────────────

def slot(name: str, predicate: str, absent_class: str = OBTAINABLE_BY_ASKING,
         optional: bool = False) -> dict:
    """One thing an answer NEEDS.

    GENERIC BY CONSTRUCTION. A slot names a 2A predicate and what to do when
    it is absent. It carries no industry vocabulary, so adding a vertical adds
    ROWS, never code — acceptance criterion 32 ("count packet-structure
    changes when adding a vertical: exactly zero").

    `absent_class` is the caller's declaration of who could supply the fact if
    it is missing. It is the §4.3 distinction that decides whether the gate
    asks a question or refuses, and only the goal's author knows it.
    """
    if absent_class not in MISSING_CLASSES:
        raise ContextError(f"unknown absence class {absent_class!r}")
    return {"name": name, "predicate": predicate,
            "absent_class": absent_class, "optional": bool(optional)}


def goal(goal_id: str, risk_tier: int, required_slots: list,
         description: str = "", scope: str = PARTY) -> dict:
    """A business task, with what it needs, what it risks, and who it is about.

    `risk_tier` is what makes sufficiency a property of the (evidence, action)
    pair: the SAME evidence yields different verdicts for a tier-1 answer and
    a tier-4 payment (§4.4, criterion 17).

    `scope` is goal DATA in exactly the way risk_tier is: the author of the
    goal knows whether it asks about a counterparty or about the business,
    and nothing downstream can infer it from free text without letting the
    phrasing of a message decide which evidence is admissible. Defaults to
    PARTY, so every goal written before scope existed keeps its meaning.
    """
    if risk_tier not in RISK_CONFIDENCE_FLOOR:
        raise ContextError(f"risk_tier must be 1-4, got {risk_tier!r}")
    if scope not in SCOPES:
        raise ContextError(f"scope must be one of {SCOPES}, got {scope!r}")
    return {"goal_id": goal_id, "risk_tier": int(risk_tier),
            "description": description, "required_slots": list(required_slots),
            "scope": scope}


# ── Assembly (§3.1) ────────────────────────────────────────────────────────

def assemble(tenant_id: str, request: str, principal, goal_def: dict,
             subject: str, *, describe=None, as_of=None, turn_ref=None,
             policies=None, constraints=None, commitments=None,
             open_risks=None, evidence_budget=None, descriptor=None,
             applies_to=None) -> dict:
    """Build a Business Context Packet, then freeze it.

    ORDER IS THE CONTRACT (§3.2). Identity is resolved by the CALLER and
    passed in as `subject`: I12 requires identity before assembly begins, and
    a packet assembled before identity is resolved cannot have a visibility
    scope, and therefore cannot be safe.

    `describe` is injected — the knowledge.describe capability. Injected
    rather than imported so this module cannot reach storage even by
    accident, and so the gate is testable without one.

    Authorization SHAPES THE PLAN, not the output (§3.2). When the principal
    may not invoke retrieval, the capability is never called — filtering after
    retrieval means the data was fetched, and a filter is one bug away from
    being bypassed.

    `applies_to` is injected for the same reason `describe` is: deciding
    whether a predicate may describe this subject needs the 2A registry, and
    this module must not be able to reach storage. It is
    `callable(predicate_ref) -> list[str] | None` returning the concept's
    registered `applies_to`. Injected but NOT optional for BUSINESS scope —
    see _out_of_scope: silently skipping the check would let a party-scoped
    predicate become business-scoped, which is the whole failure this guards.
    """
    if not isinstance(goal_def, dict) or "required_slots" not in goal_def:
        raise ContextError("goal_def must come from context.goal()")
    if not subject:
        raise ContextError(
            "identity must be resolved before assembly (IDD-2H I12) — a "
            "packet without a subject has no visibility scope")

    started = _now()
    tier = goal_def["risk_tier"]
    packet = _skeleton(tenant_id, request, principal, goal_def, subject,
                       started, as_of, turn_ref)

    # ① AUTHORIZATION SHAPES THE PLAN — before any retrieval.
    if principal is not None and descriptor is not None:
        allowed, reason = may_invoke(principal, descriptor)
        if not allowed:
            packet["assembly_state"] = A_DENIED
            packet["epistemic"]["degradation"].append(
                {"capability": "knowledge.describe", "reason": "not_authorized",
                 "detail": reason})
            packet["epistemic"]["coverage"] = {
                "planned": [], "retrieved": [], "not_planned":
                    [s["predicate"] for s in goal_def["required_slots"]],
                "note": "capability not planned — principal lacks authority"}
            return _finish(packet, goal_def, tier, denied_reason=reason)

    # ④ RETRIEVE — one capability call, gated and audited by the capability.
    #
    # SCOPE FILTERS THE PLAN, exactly as authorization does above: a predicate
    # that cannot describe this kind of subject is never requested, rather
    # than requested and then discarded. Same reasoning as §3.2's rule for
    # authority — filtering after retrieval means the data was fetched, and a
    # filter is one bug away from being bypassed.
    out_of_scope = _out_of_scope(goal_def, applies_to)
    predicates = [s["predicate"] for s in goal_def["required_slots"]
                  if s["predicate"] not in out_of_scope]
    packet["epistemic"]["coverage"]["planned"] = list(predicates)
    packet["epistemic"]["coverage"]["out_of_scope"] = sorted(out_of_scope)
    for ref in sorted(out_of_scope):
        packet["epistemic"]["degradation"].append(
            {"capability": "knowledge.describe", "reason": "out_of_scope",
             "detail": f"{ref} does not apply to a {packet['scope']} subject"})
    evidence_envelope = None
    if describe is not None:
        try:
            evidence_envelope = describe(tenant_id, subject,
                                         predicates=predicates, as_of=as_of)
        except Exception as e:
            # Type only — a store error body can echo an identifier.
            packet["assembly_state"] = A_UNAVAILABLE
            packet["epistemic"]["degradation"].append(
                {"capability": "knowledge.describe",
                 "reason": "retrieval_failed", "detail": type(e).__name__})
            return _finish(packet, goal_def, tier)

    if evidence_envelope is not None:
        _ingest(packet, evidence_envelope, tier)

    # ⑤-⑧ BOUNDARIES — structurally separate from evidence (C1).
    packet["boundaries"]["policies"] = _deep(policies or [])
    packet["boundaries"]["constraints"] = _deep(constraints or [])
    packet["boundaries"]["active_commitments"] = _deep(commitments or [])
    packet["boundaries"]["open_risks"] = _deep(open_risks or [])

    # ⑫ BUDGET — evidence only (C3, I10).
    if evidence_budget is not None:
        _apply_budget(packet, evidence_budget, goal_def)

    return _finish(packet, goal_def, tier)


def _out_of_scope(goal_def, applies_to) -> set:
    """Predicates the goal requires that cannot describe this kind of subject.

    THE RULE IS THE REGISTRY'S OWN, NOT A NEW ONE. 2A already records
    `applies_to` per concept, and knowledge._concepts_for already honours it
    when it consults the whole vocabulary. It does NOT honour it when the
    caller names predicates explicitly — which is every call assembly makes —
    so a business goal naming a PERSON-only predicate, or a party goal naming
    a business-only one, would retrieve it without complaint. This closes
    that gap in 2H rather than changing 2G's contract for every other caller.

    An empty or absent `applies_to` means "anything", matching
    _concepts_for's own reading of it.

    PARTY scope does not filter. A party subject may be a PERSON or an
    ORGANIZATION (2B allows a firm to be a counterparty), and assembly is
    handed an opaque knowledge_id whose kind it cannot know without a lookup
    it must not perform. Constraining PARTY here would reject legitimate
    organization-counterparty goals on a guess. BUSINESS scope is different:
    its subject kind is fixed by construction, so the check is exact.
    """
    if goal_def.get("scope", PARTY) != BUSINESS:
        return set()
    if applies_to is None:
        raise ContextError(
            "a BUSINESS-scoped goal requires the `applies_to` resolver: "
            "without it a party-scoped predicate would silently become "
            "business-scoped, which is the failure scope exists to prevent")
    blocked = set()
    for s in goal_def["required_slots"]:
        kinds = applies_to(s["predicate"])
        if kinds and BUSINESS_PARTY_KIND not in kinds:
            blocked.add(s["predicate"])
    return blocked


def _skeleton(tenant_id, request, principal, goal_def, subject, started,
              as_of, turn_ref) -> dict:
    role = getattr(principal, "role", None)
    return {
        # ① HEADER
        "packet_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "packet_schema_version": PACKET_SCHEMA_VERSION,
        "assembly_version": ASSEMBLY_VERSION,
        "policy_version": None,
        "assembled_at": _iso(started),
        "as_of": _iso(as_of),
        "turn_ref": turn_ref,
        "goal_ref": goal_def["goal_id"],
        # WHO THIS PACKET IS ABOUT. Assembly received it, retrieved with it,
        # and used to discard it — leaving a stored, replayable artifact that
        # could not say whose context it was. A packet that outlives the turn
        # (§8.1) must be self-describing, and an opaque knowledge_id is the
        # right handle: meaningless by design (2B V3), so it carries no PII.
        "subject": subject,
        # WHAT KIND OF THING THE SUBJECT IS. `subject` alone is an opaque
        # knowledge_id: a stored, replayed packet could not say whether it
        # described a customer or the business, and those two readings of the
        # same id support completely different decisions. Declared by the
        # goal, carried here so the packet stays self-describing (§8.1).
        "scope": goal_def.get("scope", PARTY),
        "assembly_state": A_OK,
        # ② QUESTION
        "question": {
            "request": request,
            "intent": goal_def["goal_id"],
            "intent_confidence": None,
            "goal": goal_def["goal_id"],
            "risk_tier": goal_def["risk_tier"],
            "required_slots": _deep(goal_def["required_slots"]),
        },
        # ③ PRINCIPAL
        "principal": {
            # OPAQUE, NEVER THE PHONE. §2.2 forbids "PII beyond what the
            # question requires", and the packet is stored, replayed and
            # explained — a raw sender id here would outlive the turn in
            # every one of those records. The digest is stable, so two
            # packets from the same principal still correlate.
            "principal_ref": _principal_ref(principal),
            "role": role,
            "authority_basis": "tool_registry/policy.may_invoke" if role else None,
            "visibility_scope": tenant_id,
            "risk_tier_ceiling": _tier_ceiling(role),
        },
        # ④ EVIDENCE — budget applies HERE ONLY
        "evidence": {"facts": [], "relationships": [], "timeline": [],
                     "organizational_intelligence":
                         {"precedent_set": [], "lessons": []}},
        # ⑤ BOUNDARIES — never pruned
        "boundaries": {"policies": [], "active_commitments": [],
                       "constraints": [], "open_risks": []},
        # ⑥ EPISTEMIC STATE — never pruned
        "epistemic": {
            "conflicts": [], "missing": [],
            "freshness": {"verdict": None, "oldest_observed_at": None},
            "coverage": {"planned": [], "retrieved": [], "absent": [],
                         "unavailable": [], "unregistered": [],
                         # Required by the goal, never requested, because the
                         # predicate cannot describe this scope's subject.
                         # Distinct from `absent` (we looked and found none)
                         # and from `unregistered` (no such predicate).
                         "out_of_scope": []},
            "degradation": [], "sufficiency": None, "evidence_refs": [],
            "pruning_trace": [],
        },
    }


def _principal_ref(principal) -> Optional[str]:
    """A stable, opaque handle for the asking principal.

    Correlation across packets is what `principal_ref` is FOR; identifying the
    human is not. A salted-per-tenant scheme would be stronger still, but the
    tenant is already scoped elsewhere and a second secret to manage would be
    its own liability at this size.
    """
    sender = getattr(principal, "sender_id", None)
    if not sender:
        return None
    return "prn_" + hashlib.sha256(str(sender).encode("utf-8")).hexdigest()[:16]


def _tier_ceiling(role) -> Optional[int]:
    """The highest action this principal may take. Read from the role the
    Tool Registry already assigns — not a second authority model."""
    return {"OWNER": 4, "STAFF": 3, "CLIENT": 1}.get(role)


def _ingest(packet, env, tier) -> None:
    """Fold a knowledge.describe envelope into EVIDENCE and EPISTEMIC STATE."""
    state = env.get("state")
    if state == "DENIED":
        packet["assembly_state"] = A_DENIED
        packet["epistemic"]["degradation"].append(
            {"capability": "knowledge.describe", "reason": "denied",
             "detail": env.get("reason")})
        return
    if state == "UNAVAILABLE":
        packet["assembly_state"] = A_UNAVAILABLE
        packet["epistemic"]["degradation"].append(
            {"capability": "knowledge.describe", "reason": "unavailable",
             "detail": env.get("reason")})
    elif state == "UNKNOWN":
        packet["assembly_state"] = A_UNKNOWN

    for value in env.get("values") or []:
        prov = value.get("provenance") or {}
        fresh = value.get("freshness") or {}
        # I7: every fact carries provenance. I4: no storage concepts — the
        # claim_id is an opaque evidence reference, not a row locator.
        packet["evidence"]["facts"].append({
            "predicate": value.get("predicate"),
            "value": value.get("value"),
            "provenance": {"source": prov.get("source"),
                           "tier": prov.get("tier"),
                           "cap": prov.get("cap"),
                           "source_kind": prov.get("source_kind"),
                           "asserted_by": prov.get("asserted_by")},
            "confidence": value.get("confidence"),
            "as_of": value.get("valid_from"),
            "observed_at": value.get("observed_at"),
            "freshness": {"verdict": fresh.get("verdict"),
                          "volatility_class": fresh.get("volatility_class")},
            "evidence_ref": value.get("claim_id"),
        })
        if value.get("claim_id"):
            packet["epistemic"]["evidence_refs"].append(value["claim_id"])

    # §6 — conflicts are carried, never hidden (I5). Severity is computed
    # from the DECISION AT HAND, not from the facts alone (§6.3): a
    # discrepancy is HIGH for a state change and LOW for a greeting.
    for conflict in env.get("conflicts") or []:
        packet["epistemic"]["conflicts"].append({
            "predicate": conflict.get("predicate"),
            "claims_in_tension": conflict.get("values") or [],
            "resolution_rung": None,
            "winner": "UNRESOLVED",
            "severity": _severity(tier),
            "business_consequence": (
                f"an unresolved value for {conflict.get('predicate')} would "
                f"change a tier-{tier} action" if tier >= 3 else
                f"an unresolved value for {conflict.get('predicate')} affects "
                f"confidence, not direction"),
            "rung_note": "2C ladder not implemented; surfaced unresolved",
        })

    coverage = env.get("coverage") or {}
    packet["epistemic"]["coverage"]["retrieved"] = list(coverage.get("known") or [])
    packet["epistemic"]["coverage"]["absent"] = list(coverage.get("absent") or [])
    packet["epistemic"]["coverage"]["unavailable"] = list(
        coverage.get("unavailable") or [])
    # 2G distinguishes "we hold no such fact" from "there is no such KIND of
    # fact". Collapsing them would tell an owner to go and ask the customer
    # for something the system could not record even if they answered.
    packet["epistemic"]["coverage"]["unregistered"] = list(
        coverage.get("unregistered") or [])
    packet["epistemic"]["freshness"] = _deep(env.get("freshness") or {})
    for entry in env.get("degradation") or []:
        packet["epistemic"]["degradation"].append(
            {"capability": "knowledge.describe",
             "reason": entry.get("reason"), "detail": entry.get("predicate")})


def _severity(tier: int) -> str:
    """§6.3 — severity is a property of the decision, not of the facts."""
    if tier >= 3:
        return HIGH
    return MEDIUM if tier == 2 else LOW


# ── §5 Budget: evidence only, never structure ──────────────────────────────

def _apply_budget(packet, budget: int, goal_def) -> None:
    """Prune EVIDENCE only (C3, I10, criterion 11).

    Conflicts, boundaries, missing-information and the verdict are structural
    and are not budget-eligible. Ranking keeps facts that satisfy a required
    slot: dropping the evidence the question needs, to fit a budget, produces
    a confident answer built on whatever survived.
    """
    facts = packet["evidence"]["facts"]
    if budget < 0:
        raise ContextError("evidence_budget must be >= 0")
    if len(facts) <= budget:
        return
    required = {s["predicate"] for s in goal_def["required_slots"]}
    ranked = sorted(
        facts,
        key=lambda f: (f["predicate"] not in required,
                       -(f.get("confidence") or 0)))
    kept, dropped = ranked[:budget], ranked[budget:]
    packet["evidence"]["facts"] = kept
    for f in dropped:
        # §7.1 — the pruning trace is what makes exclusion explainable.
        packet["epistemic"]["pruning_trace"].append({
            "predicate": f["predicate"], "evidence_ref": f["evidence_ref"],
            "reason": "evidence_budget",
            "required_slot": f["predicate"] in required})


# ── §4 The Sufficiency Gate ────────────────────────────────────────────────

def _finish(packet, goal_def, tier, denied_reason=None) -> dict:
    packet["epistemic"]["missing"] = _detect_missing(packet, goal_def,
                                                     denied_reason)
    packet["epistemic"]["sufficiency"] = _assess(packet, goal_def, tier,
                                                 denied_reason)
    return FrozenPacket(packet)


def _detect_missing(packet, goal_def, denied_reason) -> list:
    """⑪ required_slots − filled = missing, WITH REASONS (I6, §4.3).

    A slot is FILLED only by a fact that actually supports a decision:
    present, not in unresolved conflict, confident enough for the tier, and
    fresh enough for the tier. A stale or contested fact that silently filled
    a slot would be the exact failure the gate exists to prevent (§8 of the
    slice brief).
    """
    tier = goal_def["risk_tier"]
    floor = RISK_CONFIDENCE_FLOOR[tier]
    accepts_stale = RISK_ACCEPTS_STALE[tier]
    by_pred = {}
    for f in packet["evidence"]["facts"]:
        by_pred.setdefault(f["predicate"], []).append(f)
    conflicted = {c["predicate"] for c in packet["epistemic"]["conflicts"]}
    unreadable = set(packet["epistemic"]["coverage"].get("unavailable") or [])
    unregistered = set(packet["epistemic"]["coverage"].get("unregistered") or [])
    out_of_scope = set(packet["epistemic"]["coverage"].get("out_of_scope") or [])

    missing = []
    for s in goal_def["required_slots"]:
        if s["optional"]:
            continue
        pred = s["predicate"]
        facts = by_pred.get(pred) or []
        if denied_reason is not None:
            missing.append(_gap(s, UNOBTAINABLE_NOW,
                                f"not authorized: {denied_reason}"))
            continue
        if pred in unreadable:
            missing.append(_gap(s, UNOBTAINABLE_NOW,
                                "source unreachable during assembly"))
            continue
        if pred in out_of_scope:
            # UNKNOWABLE for the same reason `unregistered` is: no answer
            # anyone could give would be recordable. The predicate exists and
            # is perfectly askable — just not ABOUT this subject. Asking the
            # owner for a customer's declared interest when the question was
            # about the business would be a nonsense question, so the gate
            # must not classify this as OBTAINABLE_BY_ASKING.
            missing.append(_gap(
                s, UNKNOWABLE,
                "predicate does not apply to a "
                f"{packet.get('scope')}-scoped subject, so no fact of this "
                "kind can exist for it"))
            continue
        if pred in unregistered:
            # UNKNOWABLE, not "ask the customer": the vocabulary to hold this
            # fact does not exist, so no answer they give could be recorded.
            # Registering the predicate (2A) is the fix, not a conversation.
            missing.append(_gap(
                s, UNKNOWABLE,
                "predicate is not registered in the semantic registry, so no "
                "fact of this kind can be recorded yet"))
            continue
        if pred in conflicted:
            missing.append(_gap(s, OBTAINABLE_BY_ASKING,
                                "value is contested; no winner selected"))
            continue
        if not facts:
            missing.append(_gap(s, s["absent_class"], "no fact on record"))
            continue
        best = max(facts, key=lambda f: (f.get("confidence") or 0))
        conf = best.get("confidence")
        verdict = (best.get("freshness") or {}).get("verdict")
        if verdict == "STALE" and not accepts_stale:
            missing.append(_gap(
                s, OBTAINABLE_BY_RETRIEVAL,
                f"only a STALE fact is on record; tier-{tier} does not "
                f"accept stale evidence"))
            continue
        if conf is None or conf < floor:
            missing.append(_gap(
                s, OBTAINABLE_BY_RETRIEVAL,
                f"confidence {conf} is below the tier-{tier} floor {floor}"))
    return missing


def _gap(s, cls, why) -> dict:
    return {"slot": s["name"], "predicate": s["predicate"],
            "class": cls, "why": why, "verdict_if_alone": _CLASS_TO_VERDICT[cls]}


def _assess(packet, goal_def, tier, denied_reason) -> dict:
    """§4.1 four conditions, §4.2 five verdicts.

        SUFFICIENT ⟺ coverage AND freshness AND conflicts AND confidence

    All four. Any failure produces something other than "answer" (I8: the
    gate can always refuse).
    """
    ep = packet["epistemic"]
    floor = RISK_CONFIDENCE_FLOOR[tier]
    missing = ep["missing"]
    high_conflicts = [c for c in ep["conflicts"] if c["severity"] == HIGH]
    stale = [f for f in packet["evidence"]["facts"]
             if (f.get("freshness") or {}).get("verdict") == "STALE"]
    pruned_required = [p for p in ep["pruning_trace"] if p.get("required_slot")]

    conditions = {
        "coverage": not missing,
        # A STALE fact never blocks a tier that accepts it; it degrades.
        "freshness": RISK_ACCEPTS_STALE[tier] or not stale,
        "conflicts": not high_conflicts,
        "confidence": all((f.get("confidence") or 0) >= floor
                          for f in packet["evidence"]["facts"]
                          if f["predicate"] in
                          {s["predicate"] for s in goal_def["required_slots"]}),
    }

    ceiling = packet["principal"]["risk_tier_ceiling"]
    verdict, reason = _verdict(conditions, missing, high_conflicts, tier,
                               ceiling, denied_reason, pruned_required)

    return {
        "verdict": verdict,
        "reason": reason,
        "conditions": conditions,
        "risk_tier": tier,
        "confidence_floor": floor,
        "accepts_stale_evidence": RISK_ACCEPTS_STALE[tier],
        "requires_human_approval": RISK_REQUIRES_APPROVAL[tier],
        "principal_tier_ceiling": ceiling,
        # §4.5 — a refusal must be actionable: it names the gaps.
        "gaps": [{"slot": m["slot"], "class": m["class"], "why": m["why"]}
                 for m in missing],
        "blocking_conflicts": [c["predicate"] for c in high_conflicts],
        # C2 — NO packet-level confidence scalar. The weakest contributing
        # fact is named instead, so the reader knows WHICH dimension is weak.
        "weakest_fact": _weakest(packet),
    }


def _verdict(conditions, missing, high_conflicts, tier, ceiling,
             denied_reason, pruned_required):
    if denied_reason is not None:
        return REFUSE, f"principal not authorized to assemble this context"
    # §5.4 — if the budget cut evidence a required slot needed, the correct
    # outcome is refusal, not a silently smaller answer.
    if pruned_required:
        return REFUSE, ("evidence required by a slot was pruned to meet the "
                        "budget; refusing rather than answering on what fitted")
    # §6.3 — HIGH severity BLOCKS. It does not merely lower confidence.
    if high_conflicts:
        return REFUSE, (f"unresolved HIGH-severity conflict on "
                        f"{', '.join(c['predicate'] for c in high_conflicts)}")
    if missing:
        # The most severe class present decides; REFUSE outranks RETRIEVE
        # outranks CLARIFY, because answering the easiest gap first would
        # promise a resolution the hardest gap cannot deliver.
        order = [REFUSE, RETRIEVE, CLARIFY]
        verdicts = {m["verdict_if_alone"] for m in missing}
        for v in order:
            if v in verdicts:
                names = ", ".join(m["slot"] for m in missing
                                  if m["verdict_if_alone"] == v)
                return v, f"missing: {names}"
    if not conditions["freshness"]:
        return RETRIEVE, f"tier-{tier} does not accept stale evidence"
    if not conditions["confidence"]:
        return RETRIEVE, "a required fact is below the tier confidence floor"
    # §4.2 ESCALATE — sufficient evidence, action above the principal's tier.
    if ceiling is not None and tier > ceiling:
        return ESCALATE, (f"evidence is sufficient, but a tier-{tier} action "
                          f"exceeds this principal's ceiling of {ceiling}")
    return PROCEED, "all four sufficiency conditions hold"


def _weakest(packet):
    facts = [f for f in packet["evidence"]["facts"]
             if f.get("confidence") is not None]
    if not facts:
        return None
    f = min(facts, key=lambda x: x["confidence"])
    return {"predicate": f["predicate"], "confidence": f["confidence"],
            "provenance_tier": (f.get("provenance") or {}).get("tier"),
            "freshness": (f.get("freshness") or {}).get("verdict")}


# ── Integrity ──────────────────────────────────────────────────────────────

def digest(packet: dict) -> str:
    """Content hash — replay can prove it read the packet that was assessed."""
    return hashlib.sha256(
        json.dumps(packet, sort_keys=True, default=str,
                   ensure_ascii=False).encode("utf-8")).hexdigest()
