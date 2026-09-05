-- Business Reasoning Core v1 — the OWNER diagnostic/strategic surface.
--
-- WHY A MIGRATION WHEN THE TASK PREFERS NONE
-- ------------------------------------------
-- It introduces NO SCHEMA CHANGE and NO PERSISTENT REASONING STATE. It is one
-- INSERT of one registry row, exactly like 20260904000023.
--
-- It exists because handle_owner_text is reached by INTERNAL_ROLES =
-- ('OWNER','STAFF'), so a command composed at the dispatch site would be
-- STAFF-reachable. This surface carries the tenant's own business evidence
-- plus its diagnoses and priorities, which business_status already restricts
-- to OWNER. The only alternatives are a role check written at the dispatch
-- site — the SECOND AUTHORIZATION PATH this codebase repeatedly refuses,
-- "two authorization paths is one authorization hole" (C-1, Phase 1C) — or a
-- registry row. So it is the row.
--
-- The reasoning objects themselves (situation, diagnoses, priorities,
-- recommendations) are computed per turn and deliberately NOT persisted:
-- nothing yet reads them back, and inventing a table for convenience would
-- create state whose staleness rules nobody has decided.
--
-- QUERY, RISK TIER 1, side_effects false. It reads registered claims and
-- reasons over them. It authorizes nothing and executes nothing — AUTHORIZE
-- and EXECUTE are untouched by this slice and the reply is advisory.
--
-- customer_safe = false. CLIENT is an allowlist (Article VI): a customer must
-- never receive Asthra's own diagnoses or priorities.
--
-- NOT A RECOMMENDATION ENGINE FOR ACTION. It may recommend MEASUREMENT and
-- INVESTIGATION. An ACT recommendation requires a SUPPORTED diagnosis, and no
-- registered evidence can currently produce one. business_focus_recommendation
-- remains blocked on its own five slots and is NOT reachable from here.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'business_reasoning',
  'Business reasoning',
  'OWNER diagnostic and strategic reasoning over registered business '
    || 'evidence. Builds a situation, derives movement only from comparable '
    || 'observations, grades each conclusion as FACT / DERIVED / CORRELATION '
    || '/ HYPOTHESIS / UNKNOWN / CONTRADICTED, and produces priorities and '
    || 'advisory recommendations. Recommends measurement or investigation; '
    || 'never asserts a cause the evidence cannot establish.',
  'QUERY', 'api.webhook', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  25, 4000, 'basic',

  'Live. Re-assembles the 2H packet and re-reads claim history on every call '
    || 'with no cache. Each fact carries the freshness verdict its own 2A '
    || 'volatility_class produces, and a STALE reading is never used to '
    || 'derive a trend.',

  array[3]::smallint[],

  'Single observation -> reported as a fact, never as a trend. Predicate '
    || 'registered but unavailable -> UNKNOWN, measurable, stated as such. '
    || 'Predicate unregistered -> UNKNOWN, not measurable, stated as outside '
    || 'the evidence model. Conflict -> CONTRADICTED, surfaced unresolved '
    || 'with no value chosen. Claim history unreadable -> trends are lost, '
    || 'facts are not. Narration rejected by the 2G validator -> the '
    || 'deterministic rendering is returned and the refusal is named.',

  'Every stated number carries its predicate, confidence and freshness. Every '
    || 'conclusion carries its epistemic category, its supporting and '
    || 'contradicting evidence, and what additional evidence would change it. '
    || 'Causes are never asserted. No phone, no transcript, no claim_id and '
    || 'no subject id reaches the owner or the model.'
)
on conflict (code) do nothing;
