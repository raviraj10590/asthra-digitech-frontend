"""BIC configuration — environment only, no hardcoded values.

Constitution: Article IV. Code Quality Rule: configuration instead of
hardcoded values.
"""

import os

# ── Tenancy ────────────────────────────────────────────────────────────────
# Single tenant today. The column exists on every BIC table (Article II.5), so
# enabling multi-tenant later means resolving this per-request instead of
# reading a constant — a code change in ONE place, never a schema redesign.
# Owner directive: do not build multi-tenancy now; only avoid blocking it.
DEFAULT_TENANT_ID = os.environ.get(
    "BIC_TENANT_ID", "00000000-0000-0000-0000-000000000001"
).strip()

# ── Data plane ─────────────────────────────────────────────────────────────
# BIC tables are deny-by-default RLS with no policies, so the anon key cannot
# read or write them. The service-role key is required. Deliberately NOT
# falling back to the anon key: a silent downgrade would look like "logging
# mysteriously stopped" rather than a clear misconfiguration.
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://kpzprllzgqlqkqgcgrbp.supabase.co"
).strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

# ── Feature flag ───────────────────────────────────────────────────────────
# DELETED 2026-08-03 (review finding H3). There was a POLICY_ENABLED constant
# here reading the same BIC_POLICY_ENABLED env var as webhook._bic_enabled(),
# with the OPPOSITE default (unset ⇒ True) and a broken comparison:
#
#     os.environ.get("BIC_POLICY_ENABLED", "on").lower() != "off"
#
# `"false" != "off"` evaluates to True, so setting the var to "false" — the most
# natural way anyone would attempt a rollback — disabled the live path and
# ENABLED this constant. It had zero call sites, but it sat in the config module
# under the name a future engineer would reach for first, and the rollback lever
# is the load-bearing safety property of this entire migration.
#
# THE ONE SOURCE OF TRUTH IS webhook._bic_enabled(). It reads the env var
# directly, defaults to FALSE, and accepts only ("true","1","yes","on").
# Do not add a second reader here. If BIC code ever needs the flag, have the
# host inject it — the same pattern identity.configure() already uses.

# Network timeout for BIC's own reads (registry, roles). Tool timeouts are
# per-tool and come from bic_tool_defs.
DB_TIMEOUT_SECONDS = float(os.environ.get("BIC_DB_TIMEOUT", "5"))

# Registry cache TTL. Tool defs change rarely; re-reading them on every message
# would add a query per invocation for data that is effectively static.
REGISTRY_CACHE_TTL = int(os.environ.get("BIC_REGISTRY_CACHE_TTL", "300"))

# Back-off after a FAILED registry read (audit M-1). Short, because a real
# outage should be retried reasonably soon; long enough that a single turn
# never makes more than one doomed database call. Deliberately far below
# REGISTRY_CACHE_TTL — this is a circuit breaker, not a cache.
REGISTRY_FAILURE_BACKOFF = int(os.environ.get("BIC_REGISTRY_FAILURE_BACKOFF", "30"))


def is_configured() -> bool:
    """True when BIC has what it needs to reach its own tables."""
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
