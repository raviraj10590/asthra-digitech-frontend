-- BIC 2H/3A — the OWNER descriptive business status command.
--
-- WHY A MIGRATION AT ALL, WHEN THE TASK PREFERS NONE
-- --------------------------------------------------
-- handle_owner_text is reached by INTERNAL_ROLES = ('OWNER','STAFF'), so a
-- command composed at the dispatch site (the `#status` precedent) would be
-- reachable by STAFF. This answer carries the tenant's own business
-- evidence, which `business_new_enquiries` already restricts to OWNER.
--
-- The only ways to keep that restriction are (a) a role check written at the
-- dispatch site, or (b) a registry row. (a) is the SECOND AUTHORIZATION PATH
-- this codebase repeatedly refuses — "two authorization paths is one
-- authorization hole", the C-1 finding from Phase 1C — so it is (b). One
-- INSERT, no table, no column, mirroring 20260903000022 exactly.
--
-- QUERY, RISK TIER 1, side_effects false. It reads an already-measured claim
-- and renders it. It authorizes nothing and executes nothing: the reply is
-- advisory, and AUTHORIZE/EXECUTE are deliberately untouched by this slice.
--
-- customer_safe = false. CLIENT is an allowlist (Article VI): a customer
-- must never receive Asthra's own business status.
--
-- NOT A RECOMMENDATION. This command describes what the Brain has measured
-- and states plainly what it cannot say. `business_focus_recommendation`
-- remains blocked on its own missing evidence and is NOT reachable here.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'business_status',
  'Business status this month',
  'OWNER descriptive business status. Assembles the BUSINESS-scoped 2H '
    || 'packet for goal business_month_review, reports what the evidence '
    || 'supports and what it does not, and may narrate the packet. Describes '
    || 'only; recommends nothing, authorizes nothing, executes nothing.',
  'QUERY', 'api.webhook', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  20, 3000, 'basic',

  'Live. Re-assembles the 2H packet on every call with no cache. Each fact '
    || 'carries the freshness verdict its own 2A volatility_class produces, '
    || 'and a STALE reading is shown as stale rather than presented as '
    || 'current.',

  array[3]::smallint[],

  'Evidence absent but the predicate is registered -> RETRIEVE, stated as '
    || '"measured but not currently available", never invented. Predicate '
    || 'unregistered -> UNKNOWABLE, stated as outside the evidence model. '
    || 'Conflict -> surfaced unresolved, no value chosen. Narration rejected '
    || 'by the 2G validator -> the deterministic rendering is returned and '
    || 'the refusal is named. Store unreachable -> the exception TYPE only.',

  'Every stated number carries its predicate, provenance tier and cap, '
    || 'confidence and freshness verdict. The reply separates what the '
    || 'evidence supports from what it does not, and names each missing slot '
    || 'with its epistemic class. No phone, no transcript, no claim_id, no '
    || 'subject id reaches the owner or the model.'
)
on conflict (code) do nothing;
