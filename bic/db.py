"""Single Supabase access point for the BIC.

Engineering Rule: never duplicate database logic. Every BIC table read/write
goes through here — one place for headers, timeouts, error handling and query
counting.

Query counting exists because the Performance Rules require measuring database
queries per operation, and "if something cannot be measured, it cannot be
optimised". A counter here means every tool gets that measurement for free
rather than each one remembering to instrument itself.
"""

import threading
from typing import Optional

import requests

from . import config

# Per-thread query counter. Serverless invocations are effectively
# single-threaded per request, but thread-local keeps concurrent requests from
# contaminating each other's counts.
_local = threading.local()


def reset_query_count() -> None:
    _local.queries = 0


def query_count() -> int:
    return getattr(_local, "queries", 0)


def _count() -> None:
    _local.queries = getattr(_local, "queries", 0) + 1


def _headers(prefer: str = "") -> dict:
    h = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


class DbError(RuntimeError):
    """Raised on a failed BIC database call.

    Distinct from a generic exception so callers can decide per-case whether a
    DB failure is fatal (policy lookups) or ignorable (audit writes).
    """


def select(table: str, params: dict, timeout: Optional[float] = None) -> list:
    """GET rows. Raises DbError on failure — callers choose how to react."""
    if not config.is_configured():
        raise DbError("BIC not configured: SUPABASE_SERVICE_ROLE_KEY is missing")
    _count()
    try:
        r = requests.get(
            f"{config.SUPABASE_URL}/rest/v1/{table}",
            headers=_headers(),
            params=params,
            timeout=timeout or config.DB_TIMEOUT_SECONDS,
        )
    except Exception as e:
        raise DbError(f"{table} select failed: {e}") from e
    if not r.ok:
        raise DbError(f"{table} select {r.status_code}: {r.text[:200]}")
    return r.json()


def insert(table: str, rows, timeout: Optional[float] = None) -> None:
    """POST rows. Raises DbError on failure."""
    if not config.is_configured():
        raise DbError("BIC not configured: SUPABASE_SERVICE_ROLE_KEY is missing")
    _count()
    try:
        r = requests.post(
            f"{config.SUPABASE_URL}/rest/v1/{table}",
            headers=_headers("return=minimal"),
            json=rows,
            timeout=timeout or config.DB_TIMEOUT_SECONDS,
        )
    except Exception as e:
        raise DbError(f"{table} insert failed: {e}") from e
    if not r.ok:
        raise DbError(f"{table} insert {r.status_code}: {r.text[:200]}")


def update(table: str, params: dict, patch: dict,
           timeout: Optional[float] = None) -> None:
    """PATCH rows matching `params`. Raises DbError on failure.

    ⚠️ NARROW BY DESIGN. Added for ONE case: the semantic registry's
    DRAFT → ACTIVE lifecycle transition (IDD-2A §5.2), which is a legitimate
    state change on a concept whose *meaning* stays frozen thereafter.

    IT MUST NOT BE USED ON APPEND-ONLY TABLES. `bic_claims`,
    `bic_claim_retractions` and `bic_decision_records` are immutable by design
    — corrections are new rows, errors are retractions. Two defences keep that
    true rather than aspirational:

      1. those modules import `insert`/`select` BY NAME, so `update` never
         enters their namespace (tests assert `hasattr(...) is False`)
      2. database triggers reject UPDATE and DELETE on those tables outright,
         so even a direct console session cannot mutate them

    Defence 2 is the one that matters: an import rule protects against
    accident, a trigger protects against intent.
    """
    if not config.is_configured():
        raise DbError("BIC not configured: SUPABASE_SERVICE_ROLE_KEY is missing")
    _count()
    try:
        r = requests.patch(
            f"{config.SUPABASE_URL}/rest/v1/{table}",
            headers=_headers("return=minimal"),
            params=params,
            json=patch,
            timeout=timeout or config.DB_TIMEOUT_SECONDS,
        )
    except Exception as e:
        raise DbError(f"{table} update failed: {e}") from e
    if not r.ok:
        raise DbError(f"{table} update {r.status_code}: {r.text[:200]}")
