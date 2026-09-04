"""Semantic Registry — the vocabulary (IDD-2A).

WHAT THIS IS
------------
"It holds no customer, no order, no message — not one row of business data."
It answers exactly one question: what does this concept mean, and which
version of that meaning are we using?

WHY IT EXISTS AT ALL
--------------------
Its only consumer is bic/claims.py, which cannot write a fact without it:
IDD-2C V6 requires the predicate to be REGISTERED AND ACTIVE at write time,
the value to satisfy the registered value space, and every claim to record the
`semantic_version` it was written under. Without that version a 2036 reader
silently reinterprets a 2026 fact — the most insidious failure available here.

REGISTRY IS DATA, NOT CODE (P5)
-------------------------------
Adding a predicate is one row. No deployment, no code change, no branch. If
defining `kva_rating` required an engineer, the multi-industry thesis would
already be dead — so `register()` takes a category from a closed set and a
value space as data, and knows nothing about any particular industry.

NO tenant_id
------------
Vocabulary is shared. `core.party.legal_name@1` means the same thing for every
tenant; per-tenant meanings would make one tenant's facts uninterpretable by
another. This is the only BIC module that deliberately omits tenancy.
"""

import re
from typing import Optional, Tuple

from . import config  # noqa: F401  (kept for symmetry with sibling modules)
from .db import DbError, select, insert, update

TABLE = "bic_concepts"

# ── Closed vocabularies (IDD-2A) ───────────────────────────────────────────
# Each predicate category earns its place by needing DIFFERENT MACHINERY, not
# by describing a different subject. A category requiring no distinct
# machinery is a namespace, not a category (§3.3).
CATEGORIES = ("IDENTIFYING", "DESCRIPTIVE", "STATE", "TEMPORAL",
              "QUANTITATIVE", "CLASSIFYING", "DERIVED")

DRAFT, ACTIVE, DEPRECATED, RETIRED = "DRAFT", "ACTIVE", "DEPRECATED", "RETIRED"
LIFECYCLE = (DRAFT, ACTIVE, DEPRECATED, RETIRED)

CARDINALITIES = ("single", "multi")
VOLATILITY_CLASSES = ("static", "slow", "fast", "live")

# §5.3 — how @1 relates to @2. Without a declared relation a reader assumes
# equivalence and silently corrupts every historical analysis.
COMPATIBILITY = ("EQUIVALENT", "NARROWER", "BROADER", "OVERLAPPING", "UNRELATED")

# Semantic fields are frozen at ACTIVE (P2). Presentational fields stay
# editable forever — fixing a Kannada label must never mint a version;
# changing what a predicate MEANS must always mint one.
SEMANTIC_FIELDS = ("namespace", "concept", "version", "category", "value_space",
                   "unit", "cardinality", "volatility_class", "applies_to")
PRESENTATIONAL_FIELDS = ("label", "description", "examples")

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
_CONCEPT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_REF_RE = re.compile(r"^(?P<ns>[a-z][a-z0-9_.]*)\.(?P<concept>[a-z][a-z0-9_]*)"
                     r"@(?P<version>\d+)$")


class RegistryError(RuntimeError):
    """A registration or validation rule was violated. Never a DB failure."""


# ── Identifiers ────────────────────────────────────────────────────────────

def parse_ref(ref: str) -> Tuple[str, str, int]:
    """`core.party.legal_name@1` → ('core.party', 'legal_name', 1).

    P1: an unqualified name is REJECTED. Namespacing is what lets a package add
    `mfg.unit` without colliding with `realestate.unit`.
    """
    m = _REF_RE.match(ref or "")
    if not m:
        raise RegistryError(
            f"invalid concept reference {ref!r} — expected <namespace>.<concept>@<version>")
    return m.group("ns"), m.group("concept"), int(m.group("version"))


def format_ref(namespace: str, concept: str, version: int) -> str:
    return f"{namespace}.{concept}@{version}"


# ── Registration ───────────────────────────────────────────────────────────

def register(namespace: str, concept: str, version: int, category: str,
             value_space: dict, label: str, unit: Optional[str] = None,
             cardinality: str = "single", volatility_class: str = "slow",
             applies_to: Optional[list] = None, description: Optional[str] = None,
             examples: Optional[list] = None) -> dict:
    """Create a concept in DRAFT. Semantics stay editable until activation.

    Nothing is frozen here, deliberately (§3.1 of 2C makes the same move for
    claims): correction is cheap before commit and honest after.
    """
    if not _NAMESPACE_RE.match(namespace or ""):
        raise RegistryError(f"namespace {namespace!r} must be lowercase, dotted")
    if not _CONCEPT_RE.match(concept or ""):
        raise RegistryError(f"concept {concept!r} must be lowercase, underscored")
    if not isinstance(version, int) or version < 1:
        raise RegistryError("version must be an integer >= 1")
    if category not in CATEGORIES:
        raise RegistryError(f"unknown category {category!r}")
    if cardinality not in CARDINALITIES:
        raise RegistryError(f"unknown cardinality {cardinality!r}")
    if volatility_class not in VOLATILITY_CLASSES:
        raise RegistryError(f"unknown volatility_class {volatility_class!r}")
    _validate_value_space(value_space)
    # §3.5 — "unit is mandatory for QUANTITATIVE; changing it silently corrupts
    # every comparison." Rejected here as well as in SQL, so the caller gets a
    # useful message rather than a constraint violation.
    if category == "QUANTITATIVE" and not unit:
        raise RegistryError("QUANTITATIVE predicates must declare a unit")
    if not label:
        raise RegistryError("label is required")

    # §5.1 — versions are monotonic and never reused. A re-registration would
    # mean two different meanings sharing one identifier.
    if _fetch(namespace, concept, version):
        raise RegistryError(
            f"{format_ref(namespace, concept, version)} already exists — "
            f"versions are never reused")

    row = {
        "namespace": namespace, "concept": concept, "version": version,
        "category": category, "value_space": value_space, "unit": unit,
        "cardinality": cardinality, "volatility_class": volatility_class,
        "applies_to": applies_to or [], "lifecycle": DRAFT,
        "label": label, "description": description, "examples": examples,
    }
    insert(TABLE, row, timeout=5)
    return row


def activate(namespace: str, concept: str, version: int, activated_by: str) -> None:
    """DRAFT → ACTIVE. Semantics are frozen from this moment (P2).

    `activated_by` is required: V2 says every semantic change produces an audit
    record naming the human who approved it. Freezing a meaning forever is the
    most consequential act in this module, and it is not anonymous.
    """
    if not activated_by:
        raise RegistryError("activated_by is required — freezing a meaning is not anonymous")
    row = _fetch(namespace, concept, version)
    if not row:
        raise RegistryError(f"{format_ref(namespace, concept, version)} is not registered")
    if row["lifecycle"] != DRAFT:
        raise RegistryError(
            f"only DRAFT concepts can be activated; "
            f"{format_ref(namespace, concept, version)} is {row['lifecycle']}")
    update(TABLE, _key(namespace, concept, version),
           {"lifecycle": ACTIVE, "activated_by": activated_by,
            "activated_at": "now()"}, timeout=5)


def set_presentation(namespace: str, concept: str, version: int, **fields) -> None:
    """Edit presentational fields — legal in EVERY lifecycle state, forever.

    This is the half of P2 that makes it usable. Without it, a typo in a
    Kannada label would be frozen for ten years, and the pressure to "just fix
    the definition quietly" would eventually win.
    """
    unknown = set(fields) - set(PRESENTATIONAL_FIELDS)
    if unknown:
        raise RegistryError(
            f"{sorted(unknown)} are not presentational — semantic fields are "
            f"frozen at ACTIVE; create a new version instead")
    if not fields:
        return
    update(TABLE, _key(namespace, concept, version), fields, timeout=5)


# ── Lookup ─────────────────────────────────────────────────────────────────

def lookup(namespace: str, concept: str, version="latest") -> Optional[dict]:
    """Fetch one concept. `version="latest"` takes the highest registered.

    V3: a reader requesting an unknown version gets an explicit miss (None),
    NEVER a silent fallback to a neighbouring version.
    """
    if version == "latest":
        rows = select(TABLE, {
            "namespace": f"eq.{namespace}", "concept": f"eq.{concept}",
            "order": "version.desc", "limit": "1",
        }, timeout=5)
        return rows[0] if rows else None
    return _fetch(namespace, concept, int(version))


def lookup_ref(ref: str) -> Optional[dict]:
    return _fetch(*parse_ref(ref))


def applies_to_ref(ref: str) -> Optional[list]:
    """The party kinds this concept may describe, or None if unregistered.

    Read-only accessor, added so 2H can enforce subject scope without
    importing a db primitive itself (bic/context.py deliberately cannot reach
    storage). Returns the registry's own `applies_to` verbatim — an empty
    list keeps its existing meaning of "anything", exactly as
    knowledge._concepts_for reads it.

    None and [] are deliberately NOT the same answer: None means the
    predicate is not registered at all, which the sufficiency gate already
    classifies separately (UNKNOWABLE, "no fact of this kind can be recorded
    yet") and must not be collapsed into "applies to anything".
    """
    row = lookup_ref(ref)
    return None if row is None else (row.get("applies_to") or [])


def active_concepts() -> list:
    """Every ACTIVE concept, newest version first.

    Read-only. Exists because a 2G capability's `predicates` input is
    OPTIONAL (IDD-2G §3.1) — with none supplied it must consult the whole
    live vocabulary, and asking the registry is the only way to do that
    without a Python list that would drift from the rows (P5).
    """
    return select(TABLE, {
        "lifecycle": f"eq.{ACTIVE}",
        "order": "namespace.asc,concept.asc,version.desc",
    }, timeout=5)


# ── The consumer-facing gate ───────────────────────────────────────────────

def validate_assertion(ref: str, value) -> dict:
    """THE check bic/claims.py calls before committing a fact (2C V6).

    Returns the concept row when the assertion is admissible; raises
    RegistryError otherwise. Raising rather than returning a boolean is
    deliberate: a caller that ignores a `False` writes an invalid fact, and a
    fact store admits no such thing.
    """
    namespace, concept, version = parse_ref(ref)
    row = _fetch(namespace, concept, version)
    if row is None:
        raise RegistryError(f"{ref} is not registered — no free-floating facts")
    # §5.2 — DEPRECATED and RETIRED accept NO new assertions, while existing
    # ones stay readable forever. Retirement removes the ability to CREATE,
    # never the ability to INTERPRET.
    if row["lifecycle"] != ACTIVE:
        raise RegistryError(
            f"{ref} is {row['lifecycle']}; only ACTIVE concepts accept new assertions")
    _check_value(row, value)
    return row


# ── Internals ──────────────────────────────────────────────────────────────

def _key(namespace: str, concept: str, version: int) -> dict:
    return {"namespace": f"eq.{namespace}", "concept": f"eq.{concept}",
            "version": f"eq.{version}"}


def _fetch(namespace: str, concept: str, version: int) -> Optional[dict]:
    rows = select(TABLE, dict(_key(namespace, concept, version), limit="1"), timeout=5)
    return rows[0] if rows else None


def _validate_value_space(space) -> None:
    if not isinstance(space, dict) or "type" not in space:
        raise RegistryError("value_space must be a dict with a 'type'")
    kind = space["type"]
    if kind not in ("text", "enum", "number", "boolean", "timestamp"):
        raise RegistryError(f"unsupported value_space type {kind!r}")
    if kind == "enum" and not space.get("values"):
        raise RegistryError("enum value_space must declare non-empty 'values'")


def _check_value(row: dict, value) -> None:
    """Value must satisfy the REGISTERED value space (2C V6)."""
    space = row.get("value_space") or {}
    kind = space.get("type")
    ref = format_ref(row["namespace"], row["concept"], row["version"])

    if value is None or value == "":
        raise RegistryError(f"{ref}: empty value — absence is recorded as an "
                            f"absence kind, never as an empty claim")
    if kind == "enum":
        if value not in space.get("values", []):
            raise RegistryError(f"{ref}: {value!r} is outside the registered enumeration")
    elif kind == "number":
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise RegistryError(f"{ref}: {value!r} is not numeric")
        if "min" in space and num < space["min"]:
            raise RegistryError(f"{ref}: {num} below registered minimum {space['min']}")
        if "max" in space and num > space["max"]:
            raise RegistryError(f"{ref}: {num} above registered maximum {space['max']}")
    elif kind == "boolean":
        if str(value).lower() not in ("true", "false"):
            raise RegistryError(f"{ref}: {value!r} is not a boolean")
