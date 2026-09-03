-- BIC 2A/2G — the OWNER bridge from a chat message to real business evidence.
--
-- WHY THIS MIGRATION EXISTS
-- -------------------------
-- biz.pipeline.new_enquiries_per_month@1 has been live and auto-refreshing
-- since 2026-08-27, but nothing OWNER-facing could read it: "Do NOT route
-- OWNER questions through this metric yet" was the explicit ruling on that
-- slice. This is that routing, and ONLY that routing — no OWNER GOAL, no
-- business-scoped 2H, no OWNER DECIDE/AUTHORIZE, no planning, no autonomy.
--
-- A tool is only invocable if bic_tool_defs holds its row (policy.may_invoke
-- answers "unknown tool -> DENY" for anything absent), so registering this
-- capability is a migration, exactly as it was for #why, #suffice and the
-- commitment tools. No second authorization path.
--
-- NO TABLE. NO COLUMN. ONE INSERT.
--
-- QUERY, NOT ACT. Pure read over an existing claim; nothing is created,
-- moved or resolved. risk_tier 1 and side_effects false match
-- commitments_list, the closest precedent (a read-only OWNER business view).
--
-- OWNER, NOT STAFF. leads_today and crm_list_clients (operational lookups)
-- are STAFF; commitments_list and roles_list (business-standing / access)
-- are OWNER. A top-line pipeline count sits with the latter.
--
-- customer_safe = false. CLIENT is an allowlist (Article VI): a customer
-- must never see Asthra's own internal enquiry count.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'business_new_enquiries',
  'New enquiries this month',
  'Direct OWNER read of biz.pipeline.new_enquiries_per_month@1 — the '
    || 'Brain''s own measured count of distinct parties first seen this '
    || 'calendar month (IST). Answers exactly one question: "how many new '
    || 'enquiries this month?" Never DeepSeek, never the CRM snapshot, '
    || 'never a hardcoded number — a thin renderer over the same '
    || 'knowledge.describe capability #why and #service_interest already use.',
  'QUERY', 'api.webhook', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  10, 700, 'basic',

  'Live. Reads knowledge.describe -> claims.current on every call, no '
    || 'cache. The predicate''s own volatility_class (fast, 24h) governs '
    || 'the STALE/FRESH verdict shown alongside the number; this tool adds '
    || 'no staleness of its own and never presents a stale reading as '
    || 'current.',

  array[3]::smallint[],

  'Store unreachable -> UNAVAILABLE naming the exception TYPE only, never a '
    || 'fabricated zero. No live claim yet -> UNKNOWN, stated as "no '
    || 'evidence on record", never silently omitted. More than one live '
    || 'claim (should never occur for a single-cardinality predicate, but '
    || 'checked rather than assumed) -> refused, not guessed.',

  'Value, unit, month, confidence, provenance tier and tier cap, and the '
    || 'freshness verdict with its age against the volatility bound. No '
    || 'claim_id, no subject id, no phone — an internal identifier teaches '
    || 'the owner nothing and is suppressed by the renderer, not merely '
    || 'omitted by accident.'
)
on conflict (code) do nothing;
