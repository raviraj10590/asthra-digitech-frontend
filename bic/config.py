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
# Runtime kill-switch for the policy/tool layer. This slice touches the routing
# path, and `git revert` needs a deploy — a routing regression needs stopping
# NOW. Set BIC_POLICY_ENABLED=off to fall back to the legacy inline path.
POLICY_ENABLED = os.environ.get("BIC_POLICY_ENABLED", "on").strip().lower() != "off"

# Network timeout for BIC's own reads (registry, roles). Tool timeouts are
# per-tool and come from bic_tool_defs.
DB_TIMEOUT_SECONDS = float(os.environ.get("BIC_DB_TIMEOUT", "5"))

# Registry cache TTL. Tool defs change rarely; re-reading them on every message
# would add a query per invocation for data that is effectively static.
REGISTRY_CACHE_TTL = int(os.environ.get("BIC_REGISTRY_CACHE_TTL", "300"))


def is_configured() -> bool:
    """True when BIC has what it needs to reach its own tables."""
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
