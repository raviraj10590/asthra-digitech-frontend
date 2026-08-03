"""Tool Registry — the ONLY path by which a business tool may execute.

    Policy → Registry → Tool → Audit → Response

Owner directive: there must be no bypass path. Handlers are registered into a
private map and are never exported; the only public execution entry point is
invoke(). A caller cannot reach a handler without passing the policy check,
because it has no reference to one.

Constitution: Article II.3 (nothing executes unguarded), Article VI
(authorization), Article II.10 (auditable).
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from . import config, db, policy

_HANDLERS = {}          # code -> callable          (private, never exported)
_REGISTRY_CACHE = {}    # code -> tool_def row
_REGISTRY_EXPIRES = 0.0

# Argument allowlist per tool. ALLOWLIST, never denylist: a new argument is
# invisible to the audit log until someone deliberately adds it here, so a
# field carrying PII cannot leak by being forgotten.
_ARG_ALLOWLIST = {
    "crm_sync_lead":    ["service_needed", "city", "has_name", "has_phone"],
    "crm_list_clients": ["limit"],
    "leads_today":      ["limit"],
    "roles_list":       [],
    "send_brochure":    ["has_recipient"],

    # Added 2026-08-03 (review M3). These declare audit_level='full' but had no
    # entry, so _redact returned {} — a "full" audit that recorded nothing. The
    # omission failed SAFE (nothing leaked), but crm_capture_self is the only
    # customer-path WRITE tool and its rows said a CRM write happened and
    # nothing about it.
    "crm_capture_self": ["service_needed", "city"],
    "memory_clear":     [],          # explicit: takes no arguments worth recording

    # PRIVILEGED (review C1, H4). `target` and `role` ARE the audit: a privilege
    # grant whose record omits who was granted what is not an audit trail.
    # `label` is deliberately excluded — free text that may carry a person's
    # name, and it is not needed to reconstruct the security event.
    "add_role":    ["target", "role"],
    "remove_role": ["target"],
    "chat_pause":  ["target"],
    "chat_resume": ["target"],
}


@dataclass
class ToolResult:
    ok: bool
    value: object = None
    error: Optional[str] = None
    denied: bool = False
    latency_ms: int = 0
    db_queries: int = 0
    meta: dict = field(default_factory=dict)


def register(code: str):
    """Decorator registering a handler. Import-time only."""
    def _wrap(fn):
        _HANDLERS[code] = fn
        return fn
    return _wrap


def _load_registry(force: bool = False) -> dict:
    """Tool defs from the DB, cached. Tool metadata is effectively static;
    re-reading per message would add a query per invocation for nothing."""
    global _REGISTRY_EXPIRES
    if not force and _REGISTRY_CACHE and _REGISTRY_EXPIRES > time.time():
        return _REGISTRY_CACHE
    try:
        rows = db.select("bic_tool_defs", {"select": "*"})
    except db.DbError as e:
        # Keep serving a stale registry if we have one — losing the ability to
        # run tools because a metadata read blipped would be worse than acting
        # on slightly old metadata. With no cache at all, every tool is denied
        # (unknown tool → DENY), which is the fail-closed outcome.
        print(f"tools: registry load failed ({e}); using {'stale cache' if _REGISTRY_CACHE else 'EMPTY registry — all tools will deny'}")
        return _REGISTRY_CACHE
    _REGISTRY_CACHE.clear()
    _REGISTRY_CACHE.update({r["code"]: r for r in rows})
    _REGISTRY_EXPIRES = time.time() + config.REGISTRY_CACHE_TTL
    return _REGISTRY_CACHE


def describe(principal: Optional[policy.Principal] = None) -> list:
    """Self-describing registry. With a principal, returns only what that
    principal may actually invoke — so callers cannot even see tools they are
    not permitted to run."""
    defs = _load_registry()
    out = []
    for code, d in sorted(defs.items()):
        if principal is not None:
            allowed, _ = policy.may_invoke(principal, d)
            if not allowed:
                continue
        out.append({
            "name": code,
            "description": d.get("description"),
            "required_role": d.get("min_role"),
            # Derived, not stored — a stored copy could contradict min_role,
            # and a contradiction inside an authorization table is a security bug.
            "owner_only": d.get("min_role") == "OWNER",
            "customer_visible": bool(d.get("customer_safe")),
            "risk_tier": d.get("risk_tier"),
            "side_effects": bool(d.get("side_effects")),
            "timeout": d.get("timeout_seconds"),
            "expected_latency_ms": d.get("expected_latency_ms"),
            "audit_level": d.get("audit_level"),
        })
    return out


def _redact(code: str, args: dict, audit_level: str) -> dict:
    """Allowlisted, non-sensitive argument summary."""
    if audit_level != "full":
        return {}
    allowed = _ARG_ALLOWLIST.get(code, [])
    out = {}
    for k in allowed:
        if k in args and args[k] is not None:
            v = args[k]
            out[k] = v if isinstance(v, (int, float, bool)) else str(v)[:120]
    return out


def _audit(principal, code, d, started, finished, ok, error, queries, args) -> None:
    """Best-effort audit write (owner-approved).

    Business continuity outranks audit completeness: a logging failure must
    never prevent or undo a tool that already ran. On failure we emit the record
    to stdout so it survives in the platform log rather than disappearing
    entirely.
    """
    if (d or {}).get("audit_level") == "none":
        return
    row = {
        "tenant_id": principal.tenant_id or config.DEFAULT_TENANT_ID,
        "tool": code,
        "role": principal.role,
        "channel": principal.channel,
        "args_redacted": _redact(code, args, (d or {}).get("audit_level", "basic")),
        "ok": ok,
        "error": (error or None) and str(error)[:500],
        "latency_ms": int((finished - started) * 1000),
        "db_queries": queries,
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(finished, timezone.utc).isoformat(),
        "source_ref": principal.sender_id,
    }
    try:
        db.insert("bic_tool_invocations", row)
    except Exception as e:
        # L1: the stored row keeps the full sender id — an audit trail that
        # cannot identify the actor is useless. The STDOUT fallback is a wider
        # surface (platform logs, shipped to whoever can read them), so the
        # identifier is truncated there. Same event, less exposure.
        safe = dict(row)
        ref = safe.get("source_ref") or ""
        safe["source_ref"] = f"...{ref[-4:]}" if ref else None
        print(f"AUDIT_FALLBACK {json.dumps(safe, default=str)} (reason: {e})")


def invoke(principal: policy.Principal, code: str, **args) -> ToolResult:
    """THE execution entry point. Policy → Tool → Audit → Response.

    Never raises: every failure becomes a ToolResult, so a caller cannot
    accidentally skip auditing by catching an exception somewhere upstream.
    """
    defs = _load_registry()
    d = defs.get(code)

    allowed, reason = policy.may_invoke(principal, d)
    if not allowed:
        started = finished = time.time()
        # Denials are audited too — an attempted privilege escalation is
        # exactly the event worth having a record of.
        _audit(principal, code, d, started, finished, False,
               f"denied: {reason}", 0, args)
        print(f"tools: DENIED {code} for {principal.role} ({reason})")
        return ToolResult(ok=False, denied=True, error=reason)

    handler = _HANDLERS.get(code)
    if handler is None:
        # Registry row exists but no handler is wired — a deployment mismatch.
        # Explicit failure, never a silent pass.
        started = finished = time.time()
        _audit(principal, code, d, started, finished, False, "handler missing", 0, args)
        return ToolResult(ok=False, error=f"no handler registered for {code}")

    db.reset_query_count()
    started = time.time()
    ok, value, error = True, None, None
    try:
        value = handler(principal=principal, timeout=d.get("timeout_seconds", 15), **args)
    except Exception as e:
        ok, error = False, str(e)
        print(f"tools: {code} raised: {e}")
    finished = time.time()

    queries = db.query_count()
    _audit(principal, code, d, started, finished, ok, error, queries, args)

    latency_ms = int((finished - started) * 1000)
    expected = d.get("expected_latency_ms")
    if expected and latency_ms > expected * 3:
        # Declared expectation gives regressions something to regress against.
        print(f"tools: {code} SLOW {latency_ms}ms (expected ~{expected}ms)")

    return ToolResult(ok=ok, value=value, error=error,
                      latency_ms=latency_ms, db_queries=queries,
                      meta={"expected_latency_ms": expected})
