"""Party — the knowledge_id foundation (IDD-2B, with IDD-2D §3.2 identifiers).

WHAT THIS MODULE IS FOR
-----------------------
bic_claims.subject must be a real knowledge_id. This is the smallest thing
that legitimately provides one.

A knowledge_id is MEANINGLESS and PERMANENT (2B V3). It is not derived from a
phone, an email, a name or a CRM row id — anything derived from an attribute
breaks when that attribute changes, and breaks silently. The database
generates it; nothing here computes it.

WHERE THE PII IS
----------------
Exactly one place: `bic_party_identifiers.identifier_value`. Claims carry the
opaque knowledge_id, so the whole fact store is queryable without touching a
phone number. That separation is the entire practical payoff of a meaningless
identity, and this module is the only thing that crosses it.

WHAT THIS MODULE DELIBERATELY DOES NOT DO (2D)
----------------------------------------------
No merge. No merge reversal. No match scoring. No corroborating signals. No
DISPUTED resolution. No cross-class normalisation. There is no merge function
below, and its ABSENCE is the guarantee that 2D has not leaked in early.

    R1  a phone NEVER auto-merges two parties, at any confidence
    R2  a party created from a phone alone starts PROVISIONAL, never RESOLVED
    R3  a binding carries valid_from/valid_until — numbers change hands

R1 is not a rule this module enforces so much as one it CANNOT break: exact
match or create, and nothing in between.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from . import config
from .db import DbError, insert, select, update

PARTIES_TABLE = "bic_parties"
IDENTIFIERS_TABLE = "bic_party_identifiers"

# 2B §2.2 — assigned once, never changed.
PERSON, ORGANIZATION = "PERSON", "ORGANIZATION"
KINDS = (PERSON, ORGANIZATION)

# 2D §2.1 lifecycle.
UNRESOLVED, PROVISIONAL, RESOLVED, DISPUTED, MERGED = (
    "UNRESOLVED", "PROVISIONAL", "RESOLVED", "DISPUTED", "MERGED")
RESOLUTION_STATES = (UNRESOLVED, PROVISIONAL, RESOLVED, DISPUTED, MERGED)

# 2D §3.2 — "not all identifiers are equal, and treating them equally is the
# single most common cause of false merges."
SOVEREIGN, CONTROLLED, CONTACT, NOMINAL = (
    "SOVEREIGN", "CONTROLLED", "CONTACT", "NOMINAL")
IDENTIFIER_CLASSES = (SOVEREIGN, CONTROLLED, CONTACT, NOMINAL)

WHATSAPP = "whatsapp"


class PartyError(RuntimeError):
    """A 2B/2D rule was violated. Never a database failure."""


class DisputedIdentityError(PartyError):
    """The identifier resolves to a DISPUTED party (IDD-2D §3.8).

    A subclass of PartyError so existing best-effort callers keep catching it,
    but a distinct type so a future review queue can single it out. DISPUTED
    is "surfaced, never auto-resolved" — returning the party anyway would
    attach new facts to a contested identity, silently.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else dt


# ── Creation ───────────────────────────────────────────────────────────────

def create(tenant_id: str, kind: str = PERSON,
           resolution_state: str = PROVISIONAL) -> dict:
    """Create a party with a random, meaningless knowledge_id.

    `uuid4()` — random, carrying nothing. 2B V3 requires the id to be
    meaningless and permanent, which is a property of the VALUE, not of where
    it was generated; bic/claims.py mints claim_id the same way. The column
    keeps its `gen_random_uuid()` default as a backstop for any other writer.

    What matters is what it is NOT derived from: no phone, no hash of one, no
    email, no CRM row id, no name. Anything derived from an attribute breaks
    when that attribute changes, and breaks silently.
    """
    if kind not in KINDS:
        raise PartyError(f"kind must be one of {KINDS}, got {kind!r}")
    if resolution_state not in RESOLUTION_STATES:
        raise PartyError(f"unknown resolution_state {resolution_state!r}")

    row = {
        "knowledge_id": str(uuid.uuid4()),
        "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
        "kind": kind,
        "resolution_state": resolution_state,
    }
    insert(PARTIES_TABLE, row, timeout=5)
    return row


def lookup(tenant_id: str, knowledge_id: str) -> Optional[dict]:
    rows = select(PARTIES_TABLE, {
        "tenant_id": f"eq.{tenant_id}",
        "knowledge_id": f"eq.{knowledge_id}",
        "limit": "1",
    }, timeout=5)
    return rows[0] if rows else None


# ── Identifiers (2D §3.2) ──────────────────────────────────────────────────

def find_by_identifier(tenant_id: str, channel: str, identifier_value: str,
                       identifier_class: str = CONTACT) -> Optional[str]:
    """Exact match on a LIVE binding → knowledge_id, or None.

    SCOPED BY CLASS, NOT BY TRANSPORT (D15, IDD-2D §3.2-3.3). A phone is the
    same identity whether it arrived by WhatsApp or SMS, so `channel` is NOT
    part of the key for CONTACT or SOVEREIGN. It remains part of the key for
    CONTROLLED, which is unique only within its issuing system — Tally
    customer 12345 and CRM customer 12345 are different people.

    Exact match only. No normalisation beyond the caller's, no fuzzy matching,
    no scoring — those are 2D §3.5 and are not implemented. Expired bindings
    are excluded: a recycled number must not resolve to its previous holder.
    """
    rows = select(IDENTIFIERS_TABLE,
                  dict(_identity_key(tenant_id, channel, identifier_value,
                                     identifier_class), limit="1"),
                  timeout=5)
    return rows[0]["party_id"] if rows else None


def _identity_key(tenant_id: str, channel: str, identifier_value: str,
                  identifier_class: str) -> dict:
    """The lookup key, mirroring the two partial unique indexes in SQL."""
    key = {
        "tenant_id": f"eq.{tenant_id}",
        "identifier_class": f"eq.{identifier_class}",
        "identifier_value": f"eq.{identifier_value}",
        "valid_until": "is.null",
    }
    if identifier_class == CONTROLLED:
        key["channel"] = f"eq.{channel}"
    return key


def bind_identifier(tenant_id: str, party_id: str, channel: str,
                    identifier_value: str,
                    identifier_class: str = CONTACT) -> dict:
    """Bind a channel identifier to a party.

    CONTACT by default because that is what a phone number is (2D §3.3): no
    uniqueness, recycled after disconnection, routinely shared. Recording the
    class explicitly means a future resolver can never mistake it for a
    sovereign identifier and auto-merge on it.
    """
    if identifier_class not in IDENTIFIER_CLASSES:
        raise PartyError(f"unknown identifier_class {identifier_class!r}")
    if not identifier_value:
        raise PartyError("identifier_value is required")

    row = {
        "tenant_id": tenant_id or config.DEFAULT_TENANT_ID,
        "party_id": party_id,
        "identifier_class": identifier_class,
        "channel": channel,
        "identifier_value": identifier_value,
    }
    insert(IDENTIFIERS_TABLE, row, timeout=5)
    return row


def expire_identifier(tenant_id: str, channel: str, identifier_value: str,
                      when=None, identifier_class: str = CONTACT) -> None:
    """End a binding (2D R3). The row is kept — history is not rewritten.

    Numbers change hands. Expiring rather than deleting means a claim asserted
    while the binding was live stays explicable years later.

    Keyed identically to find_by_identifier (D15): if lookup is class-scoped
    but expiry stayed channel-scoped, a binding created via WhatsApp could not
    be ended by a caller that only knew the number — it would keep resolving
    while appearing to have been expired.
    """
    update(IDENTIFIERS_TABLE,
           _identity_key(tenant_id, channel, identifier_value, identifier_class),
           {"valid_until": _iso(when or _now())}, timeout=5)


# ── Resolution-state gate (D14) ────────────────────────────────────────────

# A merge chain longer than this is corrupt data, not deep history.
_MAX_MERGE_DEPTH = 16


def resolve_survivor(tenant_id: str, knowledge_id: str) -> str:
    """Follow merged_into to the party that is actually usable today.

    IDD-2D §6.1 point 5: "Both knowledge_ids remain valid forever; the
    absorbed one resolves to the survivor." Claims are never rewritten to
    point at the survivor — that is exactly what keeps a merge reversible
    (§6.2) — so the redirection has to happen HERE, on every read.

    This does NOT merge anything. It only honours a merge that some future,
    human-approved 2D operation recorded. Today nothing can set MERGED, so in
    practice this returns its argument unchanged.

    Raises rather than guessing when the data is unusable:
      • DISPUTED        §3.8 — surfaced, never auto-resolved
      • MERGED, no ptr  the D13 orphan; the DB constraint forbids it, but a
                        resolver that trusts a constraint blindly hands its
                        caller a None it never checked
      • cycle           corrupt; hanging forever is worse than failing loudly
    """
    seen = []
    current = knowledge_id
    for _ in range(_MAX_MERGE_DEPTH):
        if current in seen:
            raise PartyError(
                f"merge cycle detected in party chain {seen + [current]} — "
                f"refusing to resolve corrupt identity")
        seen.append(current)

        row = lookup(tenant_id, current)
        if row is None:
            raise PartyError(f"party {current} not found while resolving identity")

        state = row.get("resolution_state")
        if state == DISPUTED:
            raise DisputedIdentityError(
                f"party {current} is DISPUTED — contradicting identity evidence "
                f"must be resolved by a human before new facts attach (2D §3.8)")
        if state != MERGED:
            return current

        survivor = row.get("merged_into")
        if not survivor:
            raise PartyError(
                f"party {current} is MERGED but names no survivor — orphaned "
                f"identity (D13); claims pointing here cannot be redirected")
        current = survivor

    raise PartyError(
        f"merge chain from {knowledge_id} exceeded {_MAX_MERGE_DEPTH} hops — "
        f"refusing to resolve")


# ── The one function the production path calls ─────────────────────────────

def resolve_or_create(tenant_id: str, channel: str, identifier_value: str,
                      kind: str = PERSON) -> str:
    """Exact match, or create a PROVISIONAL party. Returns a knowledge_id.

    PROVISIONAL is not a placeholder to be upgraded later by this module —
    2D R2 says a party known only by a phone number IS provisional, and only
    corroborating evidence (which 2D, not this slice, evaluates) can change
    that. Nothing here ever writes RESOLVED.

    PERSON is the right kind for a WhatsApp sender rather than a fudge around
    a frozen field: a sender is a human holding a handset. If they represent a
    firm, that firm is a SEPARATE Organization party linked by a role later —
    which is exactly why 2B allows a party any number of roles.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    existing = find_by_identifier(tenant, channel, identifier_value)
    if existing:
        # D14: an identifier binding is not automatically a usable identity.
        # A MERGED party must redirect to its survivor and a DISPUTED one must
        # not resolve at all — otherwise new facts attach to a dead or
        # contested identity, silently.
        return resolve_survivor(tenant, existing)

    party = create(tenant, kind=kind, resolution_state=PROVISIONAL)
    knowledge_id = party["knowledge_id"]
    try:
        bind_identifier(tenant, knowledge_id, channel, identifier_value,
                        identifier_class=CONTACT)
    except DbError:
        # A concurrent turn won the unique index. Re-read rather than retry:
        # the other writer's party is as valid as ours, and creating a second
        # one would be the auto-merge R1 forbids, arrived at by accident.
        winner = find_by_identifier(tenant, channel, identifier_value)
        if winner:
            return winner
        raise
    return knowledge_id
