"""knowledge.explain — why do we believe this? (IDD-2G §7)

WHAT THIS IS
------------
"EXPLAIN is a capability kind, not a log" (§7.1). It is called, tested, gated
and audited like everything else, and it answers the four questions of §7.2:

    why this information? · why this source? · why not another? · what confidence?

WHAT IT CANNOT DO, STRUCTURALLY
-------------------------------
This module imports no retrieval function. No db, no claims, no party, no
registry. The single symbol it takes from bic/policy.py is `may_invoke`,
which is a pure function of (principal, descriptor) and performs no I/O —
that module can reach storage elsewhere, but nothing reachable from here
does. Its only input is a `knowledge.describe` envelope that somebody else
already retrieved. That is not tidiness — it is the enforcement mechanism
for §7.4:

    "Content comes from records; a model may narrate but never generate.
     A model-authored explanation is a plausible fiction fitted to the answer
     — convincing, unfalsifiable, and worse than silence."

A capability that could retrieve could also retrieve *differently* to suit the
story it wanted to tell. Removing the ability is stronger than forbidding it.

THE PIPELINE IS ONE-WAY
-----------------------
    knowledge.describe → structured evidence → knowledge.explain → narration

never

    model → search → choose facts → explain

The model is handed a finished brief. It cannot ask for more, because nothing
here can fetch more.

THE EXPLANATION IS NOT THE PROSE
--------------------------------
`explanation` is built deterministically FROM THE RECORDS and is always
present. `narration` is an OPTIONAL model rephrasing of that same material,
and it is validated before it is allowed into the envelope. Evidence is never
replaced by prose — §3.2 still applies, so the structured values, conflicts,
coverage and freshness ride along untouched.

WHAT THE NARRATION VALIDATOR ACTUALLY PROVES
--------------------------------------------
It proves the model introduced no NUMBER, IDENTIFIER, TIMESTAMP or CERTAINTY
CLAIM that is not in the evidence. It does NOT prove the prose is true — no
validator can, and pretending otherwise would be the same unfalsifiable
confidence §7.4 warns about. That is precisely why the deterministic
explanation is the primary artifact and narration is optional, labelled, and
droppable.
"""

import hashlib
import json
import re
from typing import Optional

from .policy import may_invoke

CAPABILITY = "knowledge.explain"

# Mirrors of the describe states. Redeclared rather than imported so this
# module keeps zero coupling to anything that can retrieve.
KNOWN, UNKNOWN, DENIED, UNAVAILABLE = "KNOWN", "UNKNOWN", "DENIED", "UNAVAILABLE"
STATES = (KNOWN, UNKNOWN, DENIED, UNAVAILABLE)

NARRATION_MODEL, NARRATION_NONE = "model", None

# ── Declared degradation (§6.1) ────────────────────────────────────────────
DEG_NARRATION_REJECTED = "narration_rejected"
DEG_NARRATION_UNAVAILABLE = "narration_unavailable"
DEG_LADDER_NOT_IMPLEMENTED = "conflict_ladder_not_implemented"
DEG_INHERITED = "inherited_from_evidence"
DEGRADATION_REASONS = (DEG_NARRATION_REJECTED, DEG_NARRATION_UNAVAILABLE,
                       DEG_LADDER_NOT_IMPLEMENTED, DEG_INHERITED)

# ── Why a narration was refused ────────────────────────────────────────────
REJ_UNSUPPORTED_NUMBER = "unsupported_number"
REJ_UNSUPPORTED_IDENTIFIER = "unsupported_identifier"
REJ_CERTAINTY_LANGUAGE = "certainty_language"
REJ_PII = "pii_in_narration"
REJ_EMPTY = "empty_narration"
REJECTION_REASONS = (REJ_UNSUPPORTED_NUMBER, REJ_UNSUPPORTED_IDENTIFIER,
                     REJ_CERTAINTY_LANGUAGE, REJ_PII, REJ_EMPTY)

# §8 of the slice brief, and §7.3 in spirit: "tier 1 / 0.90" must not become
# "highly certain". Provenance is a ceiling, and language that promotes it
# past that ceiling is the cheapest way to launder a weak fact into a strong
# impression. No IDD clause permits the transformation, so it is refused.
_CERTAINTY_RE = re.compile(
    r"\b(certain(ly)?|definitely|definitive|guarantee[ds]?|proven|proof|"
    r"undoubted(ly)?|indisputabl[ey]|beyond doubt|no doubt|absolutely|"
    r"100\s*%|verified|confirmed fact|known for sure|sure thing)\b", re.I)

# Numbers, uuids and timestamps the model might invent.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_UUIDISH_RE = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")

# PII shapes that must never appear in an explanation (§9 of the brief).
_PII_RES = (
    re.compile(r"\bwamid\.[A-Za-z0-9+/=_-]{6,}", re.I),
    re.compile(r"\b\+?\d{10,15}\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)


class ExplainError(RuntimeError):
    """The CALLER violated the contract. Never a storage failure."""


# ── The capability ─────────────────────────────────────────────────────────

def explain(evidence: dict, *, principal=None, descriptor=None,
            narrator=None, narrator_timeout: float = 8.0) -> dict:
    """Justify a `knowledge.describe` result.

    `evidence`   the describe envelope. REQUIRED — this capability retrieves
                 nothing, so there is no path by which it could obtain one
                 itself, and that is the point.
    `principal`  supply with `descriptor` to gate through the SAME
                 policy.may_invoke the Tool Registry uses. No second gate.
    `narrator`   OPTIONAL callable(brief:str) -> str. Omit it and no model is
                 called at all: the deterministic explanation stands alone.
                 Injected rather than imported so this module never depends
                 on a provider, never chooses one, and costs nothing to test.

    Never raises for a denied caller, missing knowledge or an unreachable
    store — those are STATES of the evidence, and each gets its own honest
    explanation rather than being flattened into "no comment".
    """
    if not isinstance(evidence, dict):
        raise ExplainError("evidence must be a knowledge.describe envelope")
    if evidence.get("capability") not in (None, "knowledge.describe"):
        raise ExplainError(
            f"knowledge.explain explains knowledge.describe results; got "
            f"{evidence.get('capability')!r} — explaining an unknown envelope "
            f"shape would mean guessing what its fields mean")

    out = _envelope(evidence)

    # 1. The one authorization path (§D1).
    if principal is not None:
        allowed, reason = may_invoke(principal, descriptor)
        if not allowed:
            out["state"] = DENIED
            out["denial_detail"] = reason
            out["explanation"] = [
                "You are not authorized to see this explanation.",
                f"The Tool Registry refused the call: {reason}.",
                "This is a permission outcome, not an absence of knowledge.",
            ]
            # An explanation of a refusal must not carry the thing refused.
            out["evidence"] = []
            out["conflicts"] = []
            out["questions"] = _questions_denied(reason)
            out["evidence_digest"] = _digest([])
            return out

    state = evidence.get("state")
    if state not in STATES:
        raise ExplainError(f"evidence carries unknown state {state!r}")

    # 2. Evidence is copied VERBATIM and digested. Nothing below may alter it.
    out["evidence"] = _frozen(evidence.get("values") or [])
    out["conflicts"] = _frozen(evidence.get("conflicts") or [])
    out["coverage"] = _frozen(evidence.get("coverage") or {})
    out["freshness"] = _frozen(evidence.get("freshness") or {})
    out["evidence_digest"] = _digest(out["evidence"])

    for entry in evidence.get("degradation") or []:
        _degrade(out, DEG_INHERITED, entry.get("reason"))
    if out["conflicts"]:
        # §7.2 asks for "the conflict rung that settled it". No rung settled
        # anything: the 2C ladder is deliberately not implemented (2G §3.4 puts
        # it below the Brain, and this slice does not own it). Saying so is an
        # honest degradation; naming a rung would be a fabricated one.
        _degrade(out, DEG_LADDER_NOT_IMPLEMENTED, None)

    out["state"] = state
    out["confidence"] = _confidence(evidence)
    out["questions"] = _four_questions(evidence, out)
    out["explanation"] = _explanation(evidence, out)

    # 3. Narration LAST, and only over material already fixed above.
    if narrator is not None:
        _narrate(out, narrator, narrator_timeout)

    # 4. The evidence must be byte-identical to what arrived.
    if _digest(out["evidence"]) != out["evidence_digest"]:
        raise ExplainError(
            "evidence changed during explanation — refusing to return an "
            "explanation of something other than what was retrieved")
    return out


# ── Envelope ───────────────────────────────────────────────────────────────

def _envelope(evidence: dict) -> dict:
    return {
        "capability": CAPABILITY,
        "kind": "EXPLAIN",
        "state": None,
        "entity": evidence.get("entity"),
        "subject": evidence.get("subject"),
        "identity": _frozen(evidence.get("identity") or {}),
        "explanation": [],
        "narration": None,
        "narration_source": NARRATION_NONE,
        "narration_rejected": None,
        "questions": {},
        "evidence": [],
        "evidence_digest": None,
        "evidence_refs": [],
        "conflicts": [],
        "coverage": {},
        "freshness": {},
        "confidence": {},
        "degraded": False,
        "degradation": [],
        # Carried, never minted. A trace id this module invented and stored
        # nowhere would look like an audit handle and lead nowhere.
        "trace_ref": evidence.get("trace_ref"),
        "explains": {
            "capability": evidence.get("capability") or "knowledge.describe",
            "evaluated_at": evidence.get("evaluated_at"),
            "as_of": evidence.get("as_of"),
            "as_known_at": evidence.get("as_known_at"),
        },
    }


def _frozen(value):
    """A deep copy through JSON. The caller's envelope cannot be mutated by
    us, and ours cannot be mutated by them."""
    return json.loads(json.dumps(value, default=str))


def _digest(evidence) -> str:
    canonical = json.dumps(evidence, sort_keys=True, default=str,
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _degrade(out: dict, reason: str, detail) -> None:
    if reason not in DEGRADATION_REASONS:
        raise ExplainError(f"{reason!r} is not a declared degradation reason")
    out["degraded"] = True
    entry = {"reason": reason, "detail": detail}
    if entry not in out["degradation"]:
        out["degradation"].append(entry)


# ── §7.3 confidence as a vector, with the dominating dimension NAMED ───────

def _confidence(evidence: dict) -> dict:
    """The vector, the projected scalar, and which dimension dominates.

    §7.3: "A single figure hides which dimension is weak. '0.52' could mean
    'good evidence, badly stale' or 'fresh but weakly sourced' — and those
    demand different responses. EXPLAIN returns the vector and names the
    dominating dimension."

    So the scalar is returned too (§7.2 asks for "the projected scalar"), but
    always beside the vector and always labelled as a projection — never as
    the answer.

    IDENTITY DOMINATES WHEN IT IS NOT RESOLVED. Every numeric dimension is
    conditional on having the right party: a 0.90 fact about a party we are
    only provisionally sure of is not a 0.90 answer. 2D has not landed, so
    every party in production is PROVISIONAL and this branch is the live one.
    """
    vector = dict(evidence.get("confidence") or {})
    numeric = {k: v for k, v in vector.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    identity_state = vector.get("identity_state")

    projected = min(numeric.values()) if numeric else None
    if identity_state and identity_state != "RESOLVED":
        dominating = "identity_state"
        why = (f"identity is {identity_state}, so every numeric dimension is "
               f"conditional on this being the right party")
    elif numeric:
        dominating = min(numeric, key=numeric.get)
        why = f"lowest dimension at {numeric[dominating]}"
    else:
        dominating, why = None, "no confidence dimensions present"

    return {
        "vector": vector,
        "projected_scalar": projected,
        "projection_rule": "minimum of the numeric dimensions — the weakest "
                           "dimension bounds the answer; never an average",
        "dominating_dimension": dominating,
        "dominating_because": why,
        "tier_caps_applied": _tier_caps(evidence),
    }


def _tier_caps(evidence: dict) -> list:
    """§7.2 "the tier caps applied" — per fact, with headroom made visible."""
    caps = []
    for value in evidence.get("values") or []:
        prov = value.get("provenance") or {}
        caps.append({
            "predicate": value.get("predicate"),
            "tier": prov.get("tier"),
            "cap": prov.get("cap"),
            "confidence": value.get("confidence"),
            "at_cap": (value.get("confidence") is not None
                       and prov.get("cap") is not None
                       and float(value["confidence"]) >= float(prov["cap"])),
        })
    return caps


# ── §7.2 the four questions ────────────────────────────────────────────────

def _four_questions(evidence: dict, out: dict) -> dict:
    coverage = evidence.get("coverage") or {}
    return {
        "why_this_information": {
            "slots_requested": coverage.get("requested"),
            "capabilities_called": [evidence.get("capability")
                                    or "knowledge.describe"],
            "consulted": coverage.get("consulted") or [],
            "found": coverage.get("known") or [],
            "absent": coverage.get("absent") or [],
            "unreadable": coverage.get("unavailable") or [],
            "not_a_registered_predicate": coverage.get("unregistered") or [],
            # §3.5 — the one thing that can never happen.
            "pruned": [],
            "pruning_note": "nothing is pruned; unresolved conflicts are "
                            "never budget-dropped (2G §3.5)",
            "ranking_scores": None,
            "ranking_note": "knowledge.describe applies no ranking, so there "
                            "are no scores to report",
        },
        "why_this_source": [_source_chain(v) for v in out["evidence"]],
        "why_not_another": _competing(out),
        "what_confidence": out["confidence"],
    }


def _source_chain(value: dict) -> dict:
    prov = value.get("provenance") or {}
    fresh = value.get("freshness") or {}
    return {
        "predicate": value.get("predicate"),
        "value": value.get("value"),
        "source": prov.get("source"),
        "tier": prov.get("tier"),
        "tier_cap": prov.get("cap"),
        "asserted_by": prov.get("asserted_by"),
        # The SCHEME only. The raw source_ref never entered the describe
        # envelope, so it cannot enter this one.
        "source_kind": prov.get("source_kind"),
        "semantic_version": value.get("semantic_version"),
        "status": value.get("status"),
        "valid_from": value.get("valid_from"),
        "observed_at": value.get("observed_at"),
        "freshness_verdict": fresh.get("verdict"),
        "volatility_class": fresh.get("volatility_class"),
        "evidence_ref": value.get("claim_id"),
        "settled_by_rung": None,
        "rung_note": "no conflict rung applied — the 2C ladder is not "
                     "implemented, and this value had nothing to outrank",
    }


def _competing(out: dict) -> list:
    if not out["conflicts"]:
        return []
    competing = []
    for conflict in out["conflicts"]:
        competing.append({
            "predicate": conflict.get("predicate"),
            "competing_values": conflict.get("values") or [],
            "resolved": False,
            "outranked_at_rung": None,
            "rung_note": "the 2C conflict ladder is not implemented, so no "
                         "value outranked another. Both are live and are "
                         "reported together (2G §3.5). Choosing one here "
                         "would be indistinguishable from knowing.",
        })
    return competing


# ── The deterministic explanation (content from records) ───────────────────

def _explanation(evidence: dict, out: dict) -> list:
    state = evidence.get("state")
    if state == UNKNOWN:
        return _explain_unknown(evidence)
    if state == UNAVAILABLE:
        return _explain_unavailable(evidence)
    return _explain_known(evidence, out)


def _explain_known(evidence: dict, out: dict) -> list:
    lines = []
    subject = evidence.get("subject") or evidence.get("entity")
    count = len(out["evidence"])
    lines.append(
        f"We hold {count} current fact{'s' if count != 1 else ''} about "
        f"party {subject}.")
    identity = evidence.get("identity") or {}
    if identity.get("resolution_state"):
        lines.append(
            f"The identity is {identity['resolution_state']}"
            + (" — corroborating evidence has not yet resolved it (2D R2)."
               if identity["resolution_state"] != "RESOLVED" else "."))
    for chain in out["questions"]["why_this_source"]:
        lines.append(
            f"{chain['predicate']} = {chain['value']}, asserted by "
            f"{chain['asserted_by']} at provenance tier {chain['tier']} "
            f"(cap {chain['tier_cap']}), recorded confidence "
            f"{_conf_of(out['evidence'], chain['predicate'])}. "
            f"Learned {chain['observed_at']}; freshness "
            f"{chain['freshness_verdict']} for a "
            f"{chain['volatility_class']} predicate. Evidence "
            f"{chain['evidence_ref']}.")
    for competing in out["questions"]["why_not_another"]:
        lines.append(
            f"EVIDENCE CONFLICTS on {competing['predicate']}: "
            f"{', '.join(str(v) for v in competing['competing_values'])} are "
            f"all currently asserted. No value has been selected.")
    absent = (evidence.get("coverage") or {}).get("absent") or []
    if absent:
        lines.append(
            f"We hold nothing for: {', '.join(absent)}. That is an absence of "
            f"record, not a statement about the party.")
    unreadable = (evidence.get("coverage") or {}).get("unavailable") or []
    if unreadable:
        lines.append(
            f"Could not read: {', '.join(unreadable)}. Unknown whether facts "
            f"exist there.")
    conf = out["confidence"]
    lines.append(
        f"Confidence is a vector {conf['vector']}; projected scalar "
        f"{conf['projected_scalar']} ({conf['projection_rule']}). The "
        f"dominating dimension is {conf['dominating_dimension']} — "
        f"{conf['dominating_because']}.")
    return lines


def _explain_unknown(evidence: dict) -> list:
    coverage = evidence.get("coverage") or {}
    consulted = coverage.get("consulted") or []
    lines = [
        "We hold no current knowledge matching this request.",
        f"This is insufficient stored knowledge, not a refusal and not an "
        f"outage. Reason: {evidence.get('reason')}.",
    ]
    if consulted:
        lines.append(
            f"Consulted {len(consulted)} predicate(s) — "
            f"{', '.join(consulted)} — and found no live claim.")
    else:
        lines.append("No predicate was consulted for this request.")
    lines.append("Nothing is inferred from the absence.")
    return lines


def _explain_unavailable(evidence: dict) -> list:
    coverage = evidence.get("coverage") or {}
    lines = [
        "The knowledge source could not be reached, so this request was not "
        "completed.",
        f"Reason: {evidence.get('reason')}.",
        "This is NOT an absence of knowledge and NOT a refusal. Whether facts "
        "exist is unknown.",
    ]
    unreadable = coverage.get("unavailable") or []
    if unreadable:
        lines.append(f"Unreadable: {', '.join(unreadable)}.")
    return lines


def _questions_denied(reason: str) -> dict:
    return {
        "why_this_information": {
            "slots_requested": None,
            "capabilities_called": [],
            "consulted": [], "found": [], "absent": [], "unreadable": [],
            "not_a_registered_predicate": [], "pruned": [],
            "pruning_note": "authorization refused before any evidence was read",
            "ranking_scores": None,
            "ranking_note": "not applicable to a refused call",
        },
        "why_this_source": [],
        "why_not_another": [],
        "what_confidence": {
            "vector": {}, "projected_scalar": None,
            "projection_rule": "not applicable to a refused call",
            "dominating_dimension": None,
            "dominating_because": f"call refused: {reason}",
            "tier_caps_applied": [],
        },
    }


def _conf_of(evidence: list, predicate: str):
    for value in evidence:
        if value.get("predicate") == predicate:
            return value.get("confidence")
    return None


# ── Narration (§7.4): the model may rephrase, never add ────────────────────

def build_brief(out: dict) -> str:
    """What the model is allowed to see. Nothing else reaches it.

    The brief is the deterministic explanation, already derived from records.
    The model is not given the raw envelope, not given storage, and not given
    a question — only material that has already passed through this module.
    """
    return "\n".join(out["explanation"])


def _narrate(out: dict, narrator, timeout: float) -> None:
    brief = build_brief(out)
    try:
        text = narrator(brief)
    except Exception as e:
        # Type only — a provider error body can echo the prompt.
        _degrade(out, DEG_NARRATION_UNAVAILABLE, type(e).__name__)
        return

    reason = validate_narration(text, out)
    if reason:
        # §7.4 / acceptance #26. The deterministic explanation survives; the
        # prose is dropped. A rejected narration is recorded, not hidden.
        out["narration"] = None
        out["narration_source"] = NARRATION_NONE
        out["narration_rejected"] = reason
        _degrade(out, DEG_NARRATION_REJECTED, reason)
        return

    out["narration"] = text
    out["narration_source"] = NARRATION_MODEL


def allowed_tokens(out: dict) -> set:
    """Every number and identifier the narration is permitted to contain."""
    allowed = set()

    def add(value):
        """A scalar: the whole value AND its numeric components.

        Timestamps go through here on purpose — "2026-08-18" is meaningful
        material a narration may legitimately quote, so its parts are allowed.
        """
        if value is None or isinstance(value, bool):
            return
        text = str(value)
        allowed.add(text)
        for number in _NUMBER_RE.findall(text):
            allowed.add(number)
            allowed.add(number.rstrip("0").rstrip(".") if "." in number else number)

    def add_opaque(value):
        """An identifier: the WHOLE string only, never its digits.

        A uuid is meaningless by construction (2B V3), and chopping it into
        number tokens quietly authorises whatever digits it happens to
        contain. A claim_id of 6bcbb44f-7f67-… would otherwise licence a
        narration asserting "7 open projects" — an invented business fact
        admitted on the strength of a random hex digit. Found by a test that
        failed only on the runs where the uuid happened to contain a bare 7.
        """
        if value is None or isinstance(value, bool):
            return
        allowed.add(str(value))

    for value in out["evidence"]:
        prov = value.get("provenance") or {}
        fresh = value.get("freshness") or {}
        add_opaque(value.get("claim_id"))
        for item in (value.get("value"), value.get("confidence"),
                     value.get("semantic_version"),
                     value.get("valid_from"), value.get("observed_at"),
                     value.get("predicate"), prov.get("tier"), prov.get("cap"),
                     fresh.get("age_seconds"), fresh.get("bound_seconds"),
                     fresh.get("observed_at")):
            add(item)
    for conflict in out["conflicts"]:
        for value in conflict.get("values") or []:
            add(value)
    for key, value in (out.get("confidence") or {}).get("vector", {}).items():
        add(value)
    add((out.get("confidence") or {}).get("projected_scalar"))
    # knowledge_ids are opaque for the same reason claim_ids are.
    add_opaque(out.get("subject"))
    add_opaque(out.get("entity"))
    for bucket in (out.get("coverage") or {}).values():
        if isinstance(bucket, list):
            for item in bucket:
                add(item)
    # Structural counts the narration may legitimately state.
    for count in (len(out["evidence"]), len(out["conflicts"]),
                  len((out.get("coverage") or {}).get("consulted") or []),
                  len((out.get("coverage") or {}).get("absent") or [])):
        allowed.add(str(count))
    return allowed


def validate_narration(text, out: dict) -> Optional[str]:
    """Return a rejection reason, or None if the narration is admissible.

    WHAT THIS ENFORCES: the model introduced no number, identifier, timestamp
    or certainty claim absent from the evidence.

    WHAT IT DOES NOT ENFORCE: that the prose is true. No validator can decide
    that, and claiming otherwise would be exactly the unfalsifiable confidence
    §7.4 warns about — which is why the deterministic explanation, not this
    prose, is the artifact of record.
    """
    if not text or not str(text).strip():
        return REJ_EMPTY
    text = str(text)

    for pattern in _PII_RES:
        if pattern.search(text):
            return REJ_PII
    if _CERTAINTY_RE.search(text):
        return REJ_CERTAINTY_LANGUAGE

    allowed = allowed_tokens(out)
    for uuidish in _UUIDISH_RE.findall(text):
        if uuidish not in allowed:
            return REJ_UNSUPPORTED_IDENTIFIER
    # An identifier already validated AS A WHOLE must not then be re-scanned
    # as loose digits: citing evidence 6bcbb44f-7f67-… would otherwise be
    # rejected for "containing" the number 7. Remove the accepted ones first,
    # so the number check sees only prose.
    scannable = _UUIDISH_RE.sub(" ", text)
    for number in _NUMBER_RE.findall(scannable):
        if number in allowed:
            continue
        if number.rstrip("0").rstrip(".") in allowed:
            continue
        return REJ_UNSUPPORTED_NUMBER
    return None
