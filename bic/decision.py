"""Decision Record — the turn-scoped accumulator (IDD-3C §1.1 · IDD-3D).

WHAT THIS IS
------------
The artifact 3C emits and 3D consumes: an immutable, PII-free record of every
eligible business decision. One record per eligible turn.

WHY AN ACCUMULATOR RATHER THAN PARAMETERS
-----------------------------------------
The three facts worth recording — was a model consulted, which tools ran, did
policy deny anything — are produced deep inside business functions that 1C
froze. Threading a context object through them would mean reshaping those
functions, which is exactly what ADR 0003 forbade.

But all three are already SINGLE CHOKEPOINTS:

    AI consulted   → webhook._generate_ai_reply   (both callers route here)
    tool / denial  → tools.invoke                 (no-bypass invariant, tested)
    identity       → identity.resolve             (ADR 0005 single resolver)

So each reports to a turn-scoped accumulator instead. Same `threading.local()`
pattern db.py already uses for query counting, and for the same reason:
serverless invocations are effectively single-threaded per request, but
thread-local keeps concurrent requests from contaminating each other.

WHAT THIS IS NOT
----------------
Not bic_replay_records. That table is 1C diagnostic data with a 30-day pruner,
documented as "never read by production" and "removable after 1C". This one is
evidence, retained indefinitely, with NO pruner — 3D's retention invariant (I5).
Their lifecycles are opposite, which is why they are separate tables.

PRIVACY (3C §6.4, 3D §7.5)
--------------------------
This module has no parameter anywhere that accepts a phone number, a message,
a prompt, a model response or an evidence value. That is a property of the
signatures below, not of the discipline of callers — the record cannot carry
PII because there is no way to put PII into it.
"""

import os
import threading
import time
import uuid
from typing import Optional

from . import config, db

# ── Vocabularies ───────────────────────────────────────────────────────────
# Closed sets. The database CHECK constraints carry the same values; these
# constants exist so a typo is an AttributeError here rather than a rejected
# insert in production.

RUNG_1_CONSTITUTIONAL = "RUNG_1_CONSTITUTIONAL"
RUNG_2_POLICY = "RUNG_2_POLICY"
RUNG_3_DETERMINISTIC = "RUNG_3_DETERMINISTIC"
RUNG_4_PRECEDENT = "RUNG_4_PRECEDENT"
RUNG_5_MODEL_ADVISORY = "RUNG_5_MODEL_ADVISORY"
NOT_EVALUATED = "NOT_EVALUATED"

# Rungs 1 and 4 are in the vocabulary but UNREACHABLE in this slice:
#   rung 1 — identity degrades to least privilege, it never rejects outright
#   rung 4 — Organizational Intelligence (2E) is not implemented
# They are declared so a later slice can emit them without a migration.
EMITTABLE_RUNGS = (RUNG_2_POLICY, RUNG_3_DETERMINISTIC,
                   RUNG_5_MODEL_ADVISORY, NOT_EVALUATED)

CONSULTED_RESPONSE_GENERATION = "CONSULTED_RESPONSE_GENERATION"
CONSULTED_ALL_PROVIDERS_FAILED = "CONSULTED_ALL_PROVIDERS_FAILED"
NOT_CONSULTED_DETERMINISTIC_BRANCH = "NOT_CONSULTED_DETERMINISTIC_BRANCH"
NOT_CONSULTED_CHAT_PAUSED = "NOT_CONSULTED_CHAT_PAUSED"
NOT_CONSULTED_POLICY_DENIED = "NOT_CONSULTED_POLICY_DENIED"
NOT_CONSULTED_NOT_REQUIRED = "NOT_CONSULTED_NOT_REQUIRED"

PASS = "PASS"
FAIL = "FAIL"

# 3C §3.1's eight gates, in the order 3C defines them. ALL EIGHT APPEAR ON
# EVERY RECORD. An omitted key is indistinguishable from a gate that was never
# recorded (3D §4.3), so absence is stated rather than implied.
GATE_KEYS = ("constitutional", "authorization", "capability", "policy",
             "sufficiency", "goal_alignment", "budget", "consequence")

# Of those eight, exactly three have implementation backing today. The other
# five name capabilities that do not exist yet (2H sufficiency, 3B goals, no
# budget system, no risk tiers), so they are permanently NOT_EVALUATED until
# those slices land. Recording them as PASS would be a lie; omitting them would
# be indistinguishable from a bug.
GATES_WITHOUT_BACKING = ("policy", "sufficiency", "goal_alignment",
                         "budget", "consequence")

TABLE = "bic_decision_records"
SCHEMA_VERSION = 1

# 3D §3.2 — the referenced-artifact manifest. Vercel injects the commit SHA at
# build time, which makes it immutable per deploy and free. Everything else the
# manifest wants (policy, template, capability, floor versions) arrives when
# 3C is implemented.
BRAIN_VERSION = os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")

_local = threading.local()


class _Turn:
    """Mutable state for one turn. Never holds text, identifiers or PII."""

    __slots__ = ("turn_id", "started", "route", "role", "identity_degraded",
                 "ai_consulted", "ai_provider", "all_providers_failed",
                 "deterministic_reason", "selected_tools", "denied_tools",
                 "capability_failed", "closed")

    def __init__(self) -> None:
        self.turn_id = str(uuid.uuid4())
        self.started = time.perf_counter()
        self.route: Optional[str] = None
        self.role: Optional[str] = None
        self.identity_degraded = False
        self.ai_consulted = False
        self.ai_provider: Optional[str] = None
        self.all_providers_failed = False
        self.deterministic_reason: Optional[str] = None
        self.selected_tools: list = []
        self.denied_tools: list = []
        self.capability_failed = False
        self.closed = False


# ── Lifecycle ──────────────────────────────────────────────────────────────

def open_turn() -> str:
    """Begin recording. Returns the turn_id for log correlation.

    Called once, after the eligibility checks and before the routing fork.
    """
    _local.turn = _Turn()
    return _local.turn.turn_id


def current() -> Optional[_Turn]:
    """The open turn, or None. None means recording is not active — the marks
    below are then no-ops, so importing this module never changes behaviour."""
    return getattr(_local, "turn", None)


def is_open() -> bool:
    t = current()
    return t is not None and not t.closed


def close_turn() -> None:
    _local.turn = None


# ── Marks — each called from the one chokepoint that owns the fact ─────────

def mark_identity(role: str, degraded: bool = False) -> None:
    t = current()
    if t:
        t.role = role
        t.identity_degraded = bool(degraded)


def mark_route(route: str) -> None:
    t = current()
    if t:
        t.route = route


def mark_ai_consulted(provider: Optional[str] = None) -> None:
    """A model produced the reply. Called from _generate_ai_reply only."""
    t = current()
    if t:
        t.ai_consulted = True
        t.ai_provider = provider


def mark_ai_all_providers_failed() -> None:
    """A model WAS consulted; every provider failed. Still consultation —
    the distinction matters because 'we asked and got nothing' and 'we never
    asked' are different facts (3D §4.2)."""
    t = current()
    if t:
        t.ai_consulted = True
        t.all_providers_failed = True


def mark_deterministic_branch(reason: str = NOT_CONSULTED_DETERMINISTIC_BRANCH) -> None:
    """A deterministic branch SETTLED this turn and returned without consulting
    a model.

    This is the ONLY way RUNG_3_DETERMINISTIC can be emitted. It is never
    inferred from `ai_consulted is False`, because "no model ran" is also true
    when a model was unavailable, when the turn errored, and when nothing
    happened at all. Rung 3 is a claim that a rule decided — and a claim needs
    a witness.
    """
    t = current()
    if t:
        t.deterministic_reason = reason


def mark_tool_invoked(code: str) -> None:
    t = current()
    if t and code not in t.selected_tools:
        t.selected_tools.append(code)


def mark_tool_denied(code: str) -> None:
    t = current()
    if t and code not in t.denied_tools:
        t.denied_tools.append(code)


def mark_capability_failure() -> None:
    """The registry had no usable capability — unknown tool or missing handler.
    Distinct from a denial: 3B §4.2, *absent* is not *not permitted*."""
    t = current()
    if t:
        t.capability_failed = True


# ── Derivation ─────────────────────────────────────────────────────────────

def _derive_rung(t: _Turn) -> str:
    """3C §2.1 — stop at the first decisive rung, lowest wins.

    Only rungs with a witness are emitted. Everything else is NOT_EVALUATED,
    never a guess.
    """
    # Rung 1 is unreachable here: identity degrades to least privilege rather
    # than rejecting, so no constitutional REFUSAL is ever observed.
    if t.denied_tools:
        return RUNG_2_POLICY
    # Rung 3 requires BOTH an explicit branch witness AND that no model ran.
    # The witness alone is not enough: a branch could mark itself and a later
    # code path still consult a model, in which case the branch did not settle
    # the turn.
    if t.deterministic_reason and not t.ai_consulted:
        return RUNG_3_DETERMINISTIC
    # Rung 4 (precedent/OI) is not implemented and is never emitted.
    if t.ai_consulted:
        return RUNG_5_MODEL_ADVISORY
    return NOT_EVALUATED


def _derive_consultation_reason(t: _Turn) -> str:
    if t.ai_consulted:
        return (CONSULTED_ALL_PROVIDERS_FAILED if t.all_providers_failed
                else CONSULTED_RESPONSE_GENERATION)
    if t.denied_tools:
        return NOT_CONSULTED_POLICY_DENIED
    if t.deterministic_reason:
        return t.deterministic_reason
    return NOT_CONSULTED_NOT_REQUIRED


def _derive_gates(t: _Turn) -> dict:
    """3C §3.1. Three gates are real; five have no implementation to report on.

    A gate that never ran is NOT_EVALUATED, not PASS. "We did not check" and
    "we checked and it was fine" are different facts, and collapsing them is
    how a system comes to believe it validated something it never looked at.
    """
    gates = {k: NOT_EVALUATED for k in GATE_KEYS}

    # Constitutional — identity resolution ran and produced a principal. It
    # degrades to least privilege rather than failing, so FAIL is unreachable;
    # the degradation itself is carried separately in identity_degraded.
    gates["constitutional"] = PASS if t.role else NOT_EVALUATED

    # Authorization — policy.may_invoke. Only meaningful if a tool was tried.
    if t.denied_tools:
        gates["authorization"] = FAIL
    elif t.selected_tools:
        gates["authorization"] = PASS

    # Capability — registry resolution. Same: only meaningful if a tool ran.
    if t.capability_failed:
        gates["capability"] = FAIL
    elif t.selected_tools:
        gates["capability"] = PASS

    return gates


def build_record() -> Optional[dict]:
    """Assemble the record. Returns None when no turn is open.

    Every field here is structural. There is no code path by which a message,
    a prompt, a model response or a customer identifier reaches this dict.
    """
    t = current()
    if t is None:
        return None
    return {
        "tenant_id": config.DEFAULT_TENANT_ID,
        "schema_version": SCHEMA_VERSION,
        "turn_id": t.turn_id,
        "brain_version": BRAIN_VERSION,
        "route": t.route or "unknown",
        "role": t.role or "UNKNOWN",
        "identity_degraded": t.identity_degraded,
        "decisive_rung": _derive_rung(t),
        "gate_results": _derive_gates(t),
        "ai_consulted": t.ai_consulted,
        "ai_consultation_reason": _derive_consultation_reason(t),
        "ai_provider": t.ai_provider if t.ai_consulted else None,
        "selected_tools": sorted(t.selected_tools),
        "denied_tools": sorted(t.denied_tools),
        "latency_ms": round((time.perf_counter() - t.started) * 1000, 3),
    }


def flush() -> Optional[dict]:
    """Persist and close. Best-effort: a recording failure must never affect
    the customer's turn.

    NO SATURATION SKIP. bic_replay_records skips saturated roles because it is
    diagnostic data nothing reads; a Decision Record that skipped anything
    would have gaps exactly where a dispute later lands. Every eligible turn is
    recorded, every time.
    """
    t = current()
    if t is None or t.closed:
        return None
    t.closed = True
    record = build_record()
    try:
        db.insert(TABLE, record, timeout=3)
    except Exception as e:
        # Mirrors the 1C replay write: swallowed, because production must not
        # depend on evidence collection succeeding. Logged loudly, because a
        # silently failing decision record is an archive that looks healthy
        # and is empty (3D §8.2).
        print(f"DECISION_RECORD persist failed (ignored, production unaffected): {e}")
    finally:
        close_turn()
    return record
