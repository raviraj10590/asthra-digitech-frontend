"""Capability descriptors — IDD-2G §3.1. VALIDATION ONLY.

WHAT THIS MODULE IS
-------------------
The rules a 2G descriptor must satisfy, expressed once so the registry and the
tests cannot disagree. It validates descriptions of capabilities; it does not
retrieve, resolve, rank or assert anything.

WHAT IS DELIBERATELY ABSENT
---------------------------
No retrieval. No knowledge.describe implementation. No database access. No
LLM, no embeddings, no vector store, no network. The absence of a `select`
import is the guarantee: this module cannot read knowledge even by accident.

ONE REGISTRY, ONE GATE (§D1)
----------------------------
Capabilities live in bic_tool_defs alongside Phase-1 tools and pass
bic.policy.may_invoke() unchanged. There is no second registry and no second
authorization path, because "two authorization paths is one authorization
hole" — the C-1 finding that cost a day in Phase 1C.

THE BOUNDARY THAT MUST NOT LEAK (§1.3)
--------------------------------------
"The Brain requests capabilities. It never knows how they are satisfied."
No table names, no SQL, no cursors, no row counts in a descriptor. If a
storage concept appears, the Brain becomes coupled to a storage decision it
cannot see — so STORAGE_CONCEPTS below is checked at registration rather than
left to review.
"""

import re
from typing import Optional

# §D1 — the one field that separates a capability from a Phase-1 tool.
QUERY, ASSERT, EXPLAIN, SUBSCRIBE, ACT = (
    "QUERY", "ASSERT", "EXPLAIN", "SUBSCRIBE", "ACT")
KINDS = (QUERY, ASSERT, EXPLAIN, SUBSCRIBE, ACT)

# Kinds that read or justify knowledge must carry the full §3.1 contract.
# ACT is the Phase-1 tool shape and predates 2G.
CAPABILITY_KINDS = (QUERY, ASSERT, EXPLAIN, SUBSCRIBE)

# §3.1 rollout status.
SHADOW, LIMITED, GENERAL, DEPRECATED = "SHADOW", "LIMITED", "GENERAL", "DEPRECATED"
STATUSES = (SHADOW, LIMITED, GENERAL, DEPRECATED)

# §3.1 — required of every capability. Mirrors the SQL constraint so a caller
# gets a useful message instead of a constraint violation.
REQUIRED_CAPABILITY_FIELDS = (
    "freshness", "provenance_tiers", "degradation", "explainability")

# §6.1 — "'unspecified' is not valid. This is enforced at registration,
# because an undeclared failure mode becomes an improvised one at 2 a.m."
UNSPECIFIED = "unspecified"

# §1.3 — storage concepts that must never appear in a descriptor.
STORAGE_CONCEPTS = (
    "select ", "insert into", "update ", "delete from", "join ", "where ",
    "bic_claims", "bic_parties", "bic_party_identifiers", "bic_concepts",
    "bic_tool_defs", "bic_decision_records", "bic_facts", "bic_entities",
    "postgres", "supabase", "jsonb", "primary key", "foreign key",
    "row_count", "rowcount", "cursor", "offset ", "limit ", "table ",
)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class CapabilityError(RuntimeError):
    """A descriptor violated a 2G rule. Never a database failure."""


def is_capability(descriptor: dict) -> bool:
    """True for QUERY/ASSERT/EXPLAIN/SUBSCRIBE, False for a Phase-1 ACT tool."""
    return (descriptor.get("kind") or ACT) in CAPABILITY_KINDS


def is_binding(descriptor: dict) -> bool:
    """§8.2: a named vertical capability is a ROW over a generic one."""
    return bool(descriptor.get("binds_to"))


def validate(descriptor: dict) -> None:
    """Raise CapabilityError unless the descriptor satisfies §3.1.

    Phase-1 ACT tools are validated only for the vocabularies they now carry;
    the 2G contract is required of capabilities. That asymmetry is what lets
    15 live tool rows keep working without being rewritten.
    """
    code = descriptor.get("code") or ""
    if not _CODE_RE.match(code):
        raise CapabilityError(f"invalid capability code {code!r}")

    kind = descriptor.get("kind") or ACT
    if kind not in KINDS:
        raise CapabilityError(f"unknown kind {kind!r}; expected one of {KINDS}")

    status = descriptor.get("status") or GENERAL
    if status not in STATUSES:
        raise CapabilityError(f"unknown status {status!r}; expected one of {STATUSES}")
    if status == DEPRECATED and not descriptor.get("successor"):
        raise CapabilityError(f"{code}: DEPRECATED requires a successor")

    # Never a valid declaration, for any row.
    if (descriptor.get("degradation") or "").strip().lower() == UNSPECIFIED:
        raise CapabilityError(
            f"{code}: degradation='unspecified' is not a declaration (§6.1) — "
            f"an undeclared failure mode becomes an improvised one")

    if is_capability(descriptor):
        _validate_capability(descriptor, code)

    _reject_storage_concepts(descriptor, code)


def _validate_capability(descriptor: dict, code: str) -> None:
    missing = [f for f in REQUIRED_CAPABILITY_FIELDS if not descriptor.get(f)]
    if missing:
        raise CapabilityError(
            f"{code}: capability is missing required §3.1 declarations: "
            f"{', '.join(missing)}")

    semver = descriptor.get("semver")
    if semver and not _SEMVER_RE.match(semver):
        raise CapabilityError(f"{code}: semver {semver!r} is not MAJOR.MINOR.PATCH")

    tiers = descriptor.get("provenance_tiers") or []
    if not all(isinstance(t, int) and 0 <= t <= 5 for t in tiers):
        raise CapabilityError(
            f"{code}: provenance_tiers must be 2C tiers 0-5, got {tiers!r}")

    if is_binding(descriptor) and descriptor["binds_to"] == code:
        raise CapabilityError(f"{code}: a binding cannot bind to itself")


def _reject_storage_concepts(descriptor: dict, code: str) -> None:
    """§1.3 — the boundary must not leak.

    Scans the DECLARED text of the descriptor. A capability whose contract
    mentions a table has already told the Brain how it is satisfied.
    """
    haystack = " ".join(
        str(descriptor.get(f) or "")
        for f in ("purpose", "description", "outputs", "inputs",
                  "freshness", "degradation", "explainability", "confidence_rule")
    ).lower()
    for concept in STORAGE_CONCEPTS:
        if concept in haystack:
            raise CapabilityError(
                f"{code}: descriptor leaks a storage concept ({concept.strip()!r}) — "
                f"the Brain must never know how a capability is satisfied (§1.3)")


def binding_target(descriptor: dict) -> Optional[str]:
    """The generic capability a named binding delegates to (§8.2).

    A binding needs NO implementation of its own — that is the whole mechanism
    behind "ten vertical capabilities, zero new implementations".
    """
    return descriptor.get("binds_to")
