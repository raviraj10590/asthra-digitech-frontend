"""Policy layer — deterministic identity and authorization.

Constitution:
  Article II.1  identity resolved server-side, before any model runs
  Article II.2  security never depends on model behaviour
  Article VI    role → grants; CLIENT access is an allowlist

There is NO AI in this module and there must never be. Everything here is a
pure function of the verified sender identity and the registry.

FAIL CLOSED, always:
  unknown role   → CLIENT (least privilege)
  unknown tool   → DENY
  unknown tenant → DENY
A lookup failure must never produce MORE access than success would.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from . import config, db

# Ordered least → most privileged. Comparison is by index, so adding a role
# between existing ones is a one-line change and every check adapts.
ROLE_ORDER = ["CLIENT", "STAFF", "MANAGER", "OWNER"]

ROLES_TABLE = "bot_roles"

# Bootstrap owners from env. These work even when the database is unreachable,
# so administrative access is never a single point of failure.
BOOTSTRAP_OWNERS = [
    p.strip()
    for p in os.environ.get("OWNER_PHONE", "918884448141,918861369951").split(",")
    if p.strip()
]

_role_cache = {}
ROLE_CACHE_TTL = 300


@dataclass(frozen=True)
class Principal:
    """The verified identity of whoever is asking. Frozen: once resolved, no
    downstream code may mutate it into something more privileged."""

    sender_id: str
    role: str
    tenant_id: str
    label: Optional[str] = None
    channel: str = "whatsapp"
    degraded: bool = field(default=False)  # True when resolved via fallback

    @property
    def rank(self) -> int:
        # Unknown role sorts to CLIENT — the fail-closed default.
        return ROLE_ORDER.index(self.role) if self.role in ROLE_ORDER else 0

    def at_least(self, required: str) -> bool:
        if required not in ROLE_ORDER:
            return False  # unknown requirement → deny
        return self.rank >= ROLE_ORDER.index(required)

    @property
    def is_owner(self) -> bool:
        return self.role == "OWNER"


def resolve_principal(sender_id: str, channel: str = "whatsapp",
                      tenant_id: Optional[str] = None) -> Principal:
    """@deprecated — SUPERSEDED BY bic.identity.resolve()

    ⚠️ DO NOT CALL. Retained only so Slice 1B remains untouched after closure.
    Nothing in production reaches this function, so its module-level
    `_role_cache` is never populated and there is exactly one live cache
    (bic.identity._cache).

    Superseded 2026-08-02 by the canonical resolver (ADR 0005). The problem it
    solved is unchanged; what changed is that `bic.identity` is now the ONE
    implementation shared by the legacy webhook path and the Brain, so a
    Decision Replay disagreement can only mean a real logic difference rather
    than two lookups differing.

    Differences worth knowing if you are tempted to use this:
      • reads bot_roles via bic.db (SERVICE-ROLE key). bic.identity injects the
        fetcher instead, letting the caller use the anon key that bot_roles'
        own RLS policy already permits — least privilege, and it removed the
        hidden dependency that made replay comparisons vacuous.
      • keeps a SECOND cache, which is exactly the duplication ADR 0005 removed.

    REMOVAL CONDITIONS — delete this function when ALL of:
      1. Slice 1C is accepted and BIC_POLICY_ENABLED has been true in
         production through at least one full migration stage without rollback.
      2. No caller remains: `grep -rn "resolve_principal" --include=*.py`
         returns only this definition and its tests.
      3. A slice is open that is permitted to modify bic/policy.py — 1B is
         closed, so removal needs an explicit phase, not an opportunistic edit.
    Until then it stays as documented dead code rather than a silent trap.

    Article II.1: the sender id comes from the transport (Meta's authenticated
    webhook payload), never from message content. Nothing a user can type
    influences the outcome.
    """
    tenant = (tenant_id or config.DEFAULT_TENANT_ID or "").strip()
    if not tenant:
        # Unknown tenant → DENY. Return the least-privileged principal rather
        # than raising, so callers get a safe object instead of an exception
        # path that might be caught and ignored somewhere upstream.
        return Principal(sender_id, "CLIENT", "", degraded=True, channel=channel)

    if sender_id in BOOTSTRAP_OWNERS:
        return Principal(sender_id, "OWNER", tenant, label="bootstrap", channel=channel)

    cached = _role_cache.get(sender_id)
    if cached and cached[2] > time.time():
        return Principal(sender_id, cached[0], tenant, label=cached[1], channel=channel)

    role, label, degraded = "CLIENT", None, False
    try:
        rows = db.select(
            ROLES_TABLE,
            {"phone": f"eq.{sender_id}", "active": "eq.true", "select": "role,label"},
        )
        if rows and rows[0].get("role") in ROLE_ORDER:
            role, label = rows[0]["role"], rows[0].get("label")
    except db.DbError as e:
        # FAIL CLOSED. A database outage must never escalate anyone; it can only
        # ever leave them as CLIENT. Bootstrap owners are already handled above,
        # so admin access survives this path.
        print(f"policy: role lookup failed, defaulting to CLIENT: {e}")
        degraded = True

    if not degraded:
        _role_cache[sender_id] = (role, label, time.time() + ROLE_CACHE_TTL)

    return Principal(sender_id, role, tenant, label=label,
                     channel=channel, degraded=degraded)


def invalidate(sender_id: str) -> None:
    """Drop a cached role — call after granting/revoking access."""
    _role_cache.pop(sender_id, None)


def may_invoke(principal: Principal, tool_def: dict) -> tuple[bool, str]:
    """Authorization decision. Returns (allowed, reason).

    Order matters: every deny condition is checked before any allow.
    """
    if not tool_def:
        return False, "unknown tool"                    # unknown tool → DENY
    if not tool_def.get("active", True):
        return False, "tool inactive"
    if not principal.tenant_id:
        return False, "unknown tenant"                  # unknown tenant → DENY

    # CLIENT is an ALLOWLIST (Article VI): a customer may invoke a tool only if
    # it is explicitly marked customer_safe. Never a denylist — a tool added
    # without thinking about customer exposure defaults to unreachable.
    if principal.role == "CLIENT":
        if not tool_def.get("customer_safe"):
            return False, "not customer-safe"
        return True, "ok"

    required = tool_def.get("min_role") or "OWNER"      # missing → strictest
    if not principal.at_least(required):
        return False, f"requires {required}, caller is {principal.role}"

    return True, "ok"
