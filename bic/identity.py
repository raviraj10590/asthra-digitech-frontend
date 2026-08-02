"""Canonical role resolver — Slice 1C integration.

THE single source of truth for "who is this sender". Both the legacy webhook
path and the new Brain pipeline resolve identity here, so a Decision Replay
disagreement can only ever mean a real logic difference — never two different
lookup implementations disagreeing with each other.

Relationship to the Policy Layer (1B, CLOSED and unchanged):
  • Principal, ROLE_ORDER and BOOTSTRAP_OWNERS are REUSED from bic.policy —
    bootstrap logic is not duplicated, it is imported.
  • bic.policy.may_invoke() remains the authorization decision. This module
    only answers WHO someone is, never WHAT they may do.
  • bic.policy.resolve_principal() is superseded for the live path. It is left
    untouched because 1B is closed; nothing in production calls it, so its
    cache is never populated and there is exactly one live cache.

Why the row fetcher is injected:
`bot_roles` is a PRE-BIC table with its own anon-select policy, reachable with
the anon key the webhook already uses. The BIC tables are deny-by-default and
need the service-role key. Injecting the fetcher lets this one resolver work
with whichever credential the host has, instead of hard-coding a credential
choice that would silently fail closed (which is exactly what made the earlier
replay comparison vacuous).
"""

import time
from typing import Callable, Optional, Tuple

from .policy import BOOTSTRAP_OWNERS, ROLE_ORDER, Principal  # reused, not redefined

ROLES_TABLE = "bot_roles"
CACHE_TTL = 300          # seconds

# THE cache. One dict, one TTL, shared by every caller.
_cache = {}              # phone -> (role, label, expires_at)

# Injected row fetcher: phone -> dict|None. Configured once at startup by the
# host (webhook.py). Never called for bootstrap owners.
_fetch_row: Optional[Callable[[str], Optional[dict]]] = None


def configure(fetch_row: Callable[[str], Optional[dict]]) -> None:
    """Install the row fetcher. Call once at import time."""
    global _fetch_row
    _fetch_row = fetch_row


def is_configured() -> bool:
    return _fetch_row is not None


def invalidate(phone: str) -> None:
    """Drop a cached entry — call after granting or revoking access."""
    _cache.pop(phone, None)


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()


def resolve(sender_id: str, channel: str = "whatsapp",
            tenant_id: Optional[str] = None) -> Principal:
    """Resolve a verified sender id to a Principal.

    FAIL CLOSED: an unknown role, an unconfigured fetcher, or a lookup failure
    all yield CLIENT. A failure can only ever LOWER privilege.

    Bootstrap owners resolve from env without any lookup, so administrative
    access survives a total database outage.
    """
    from . import config  # local import keeps module import order simple
    tenant = (tenant_id or config.DEFAULT_TENANT_ID or "").strip()
    if not tenant:
        return Principal(sender_id, "CLIENT", "", degraded=True, channel=channel)

    if sender_id in BOOTSTRAP_OWNERS:
        return Principal(sender_id, "OWNER", tenant, label="bootstrap", channel=channel)

    cached = _cache.get(sender_id)
    if cached and cached[2] > time.time():
        return Principal(sender_id, cached[0], tenant, label=cached[1], channel=channel)

    role, label, degraded = "CLIENT", None, False
    if _fetch_row is None:
        # Not configured: behave as CLIENT and mark degraded rather than
        # pretending the answer is authoritative.
        print("identity: no fetcher configured — defaulting to CLIENT (degraded)")
        degraded = True
    else:
        try:
            row = _fetch_row(sender_id)
            if row and row.get("role") in ROLE_ORDER:
                role, label = row["role"], row.get("label")
        except Exception as e:
            print(f"identity: role lookup failed, defaulting to CLIENT: {e}")
            degraded = True

    # A degraded result is never cached — otherwise one blip would pin a user
    # to CLIENT for the whole TTL.
    if not degraded:
        _cache[sender_id] = (role, label, time.time() + CACHE_TTL)

    return Principal(sender_id, role, tenant, label=label,
                     channel=channel, degraded=degraded)


def resolve_legacy(sender_id: str) -> Tuple[str, Optional[str]]:
    """(role, label) — the shape webhook.get_role() has always returned.

    Exists so the legacy path can delegate here without changing its own
    call sites or behaviour.
    """
    p = resolve(sender_id)
    return p.role, p.label
