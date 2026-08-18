-- BIC 2G — Capability Descriptor. Infrastructure only.
--
-- IDD-2G D1: "Knowledge Capabilities register in the SAME registry, pass the
-- SAME Policy Gate, and write the SAME audit trail." Building a parallel
-- knowledge registry would create a second authorization path, and "two
-- authorization paths is one authorization hole" — the C-1 finding from 1C.
--
-- So this migration creates NO new table. It extends bic_tool_defs with the
-- §3.1 descriptor fields that 1B did not already carry. The fields 1B owns —
-- min_role, customer_safe, risk_tier, side_effects, timeout_seconds,
-- expected_latency_ms, audit_level — are reused untouched.
--
-- BACKWARD COMPATIBILITY IS THE POINT
-- -----------------------------------
-- 15 tool rows are live and invoked in production. Every column below is
-- nullable or defaulted, and every 2G constraint is conditional on `kind`, so
-- the existing rows remain valid without being edited. bic/tools.py loads with
-- `select *` and reads by key, so unknown columns are simply ignored by code
-- that predates them.
--
-- WHAT IS DELIBERATELY NOT HERE
-- -----------------------------
-- No retrieval. No knowledge.describe handler. No LLM. No vector store. This
-- migration only lets the registry DESCRIBE a capability; nothing can execute
-- one yet.

alter table bic_tool_defs
  -- §D1: the one field that separates a capability from a Phase-1 tool.
  -- Defaults to ACT because that is the conservative reading — §1.2: "a QUERY
  -- can be retried freely and an ACT cannot." Existing rows keep the
  -- non-retryable treatment they have today; reclassifying the 15 is a
  -- separate, deliberate decision and is NOT done here.
  add column if not exists kind text not null default 'ACT'
    check (kind in ('QUERY', 'ASSERT', 'EXPLAIN', 'SUBSCRIBE', 'ACT')),

  -- §3.1 identity
  add column if not exists module text,
  add column if not exists semver text,

  -- §3.1 inputs / outputs: typed slots and the GUARANTEED result shape.
  add column if not exists inputs  jsonb,
  add column if not exists outputs jsonb,

  -- §3.3 freshness is a guarantee, not a hope. Bounds derive from the
  -- predicate's volatility class (2A §3.5), so they are per-fact.
  add column if not exists freshness text,

  -- §3.1 "which tiers results may carry" (2C provenance tiers 0-5).
  add column if not exists provenance_tiers smallint[],

  -- §3.1 how result confidence is derived AND CAPPED. A capability may never
  -- inflate past the 2C tier cap.
  add column if not exists confidence_rule text,

  -- §6.1 declared degradation. "unspecified" is not a valid declaration,
  -- "because an undeclared failure mode becomes an improvised one at 2 a.m."
  add column if not exists degradation text,

  -- §7 what EXPLAIN returns for this capability.
  add column if not exists explainability text,

  -- §3.1 rollout status.
  add column if not exists status text not null default 'GENERAL'
    check (status in ('SHADOW', 'LIMITED', 'GENERAL', 'DEPRECATED')),
  add column if not exists successor text,

  -- §8.1-8.2 NAMED BINDINGS. A vertical capability is a registry ROW over a
  -- generic one — "ten vertical capabilities, zero new implementations". The
  -- binding names the generic capability and the parameters it fixes.
  add column if not exists binds_to text references bic_tool_defs(code),
  add column if not exists binding_params jsonb;


-- ── 2G completeness, enforced only for capabilities ────────────────────────
-- Acceptance #17: registering a capability with degradation = unspecified is
-- REJECTED. Conditional on kind so the 15 legacy ACT rows stay valid.
alter table bic_tool_defs drop constraint if exists bic_tool_defs_capability_complete;
alter table bic_tool_defs add constraint bic_tool_defs_capability_complete check (
  kind = 'ACT'
  or (freshness        is not null
      and provenance_tiers is not null
      and degradation  is not null
      and explainability is not null)
);

-- Never a valid declaration for ANY row, legacy included.
alter table bic_tool_defs drop constraint if exists bic_tool_defs_degradation_declared;
alter table bic_tool_defs add constraint bic_tool_defs_degradation_declared
  check (degradation is null or degradation <> 'unspecified');

-- §3.1 "(+ successor)" — a deprecation with nowhere to go is a dead end.
alter table bic_tool_defs drop constraint if exists bic_tool_defs_successor_pair;
alter table bic_tool_defs add constraint bic_tool_defs_successor_pair
  check (status <> 'DEPRECATED' or successor is not null);

-- A binding binds to something OTHER than itself.
alter table bic_tool_defs drop constraint if exists bic_tool_defs_binding_not_self;
alter table bic_tool_defs add constraint bic_tool_defs_binding_not_self
  check (binds_to is null or binds_to <> code);

comment on column bic_tool_defs.kind is
  'IDD-2G §D1. QUERY reads knowledge · ASSERT adds it · EXPLAIN justifies it ·
   SUBSCRIBE streams change · ACT changes the world (Phase 1 tools). The
   separation matters because a QUERY can be retried freely and an ACT cannot.';

comment on column bic_tool_defs.binds_to is
  'IDD-2G §8.2: a named vertical capability is a registry ROW over one of the
   generic capabilities — never a new implementation. This is the mechanism
   that makes the extension claim true rather than aspirational.';


-- ── The first generic capability, DESCRIBED but not implemented ────────────
-- §2.1 #3: "All current assertions about an entity — conflict-resolved,
-- provenance-tagged."
--
-- active = false and status = SHADOW. There is no handler yet, and an
-- unreachable capability is the correct state for one: policy.may_invoke()
-- already denies an inactive row ("tool inactive"), so this cannot be called
-- through the one authorization path — no second mechanism is introduced to
-- hold it back.
insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   inputs, outputs, freshness, provenance_tiers, confidence_rule,
   degradation, explainability)
values (
  'knowledge.describe',
  'Describe an entity',
  'What do we currently assert about this entity, with what evidence?',
  'QUERY', 'knowledge', '0.1.0',
  'STAFF', 1, false, false,
  false,            -- not invokable: no handler exists yet
  'SHADOW',
  10, 800, 'basic',
  jsonb_build_object(
    'entity',       jsonb_build_object('type','knowledge_id','required',true),
    'predicates',   jsonb_build_object('type','array','required',false),
    'as_of',        jsonb_build_object('type','timestamp','required',false),
    'as_known_at',  jsonb_build_object('type','timestamp','required',false)),
  -- §3.2: a capability never returns a bare value.
  jsonb_build_object(
    'values',    jsonb_build_array('value','provenance','confidence','as_of','observed_at'),
    'conflicts', 'unresolved contradictions — never omitted (§3.5)',
    'coverage',  'what was consulted, what was not',
    'freshness', 'oldest contributing fact + staleness verdict',
    'degraded',  'true + reason when operating below full',
    'trace_ref', 'for EXPLAIN',
    'states',    jsonb_build_array('KNOWN','UNKNOWN','DENIED','UNAVAILABLE')),
  'Per-predicate, derived from the 2A volatility_class of each predicate read; '
    || 'staleness verdict returned with the result rather than applied silently.',
  array[0,1,2,3,4,5]::smallint[],
  'Inherited from the 2C claim; capped by provenance tier and never inflated.',
  'Knowledge unavailable -> degraded=true with coverage stated, never empty as '
    || 'though complete. Conflicts -> resolved value PLUS conflicts, never a '
    || 'silent pick. Stale -> age and verdict attached. Timeout -> partial plus '
    || 'what was not reached. Unauthorized -> DENIED and audited, which must '
    || 'never look like empty (§6.2).',
  'Source, derivation chain, competing claims, and confidence as a vector — '
    || 'never a single number (§7.3). Narration by a model is permitted; '
    || 'generation of the explanation is not (§7.4).'
)
on conflict (code) do nothing;
