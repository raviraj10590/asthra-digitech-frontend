-- BIC — Decision Record slice (IDD-3C §1.1 · IDD-3D §2.3, §3.2, §3.3)
--
-- The immutable, PII-free record of every eligible business decision. This is
-- the artifact 3C emits and 3D consumes.
--
-- ⚠️ NOT bic_replay_records, AND NOT A REPLACEMENT FOR IT.
-- The two are deliberately separate because their LIFECYCLES ARE OPPOSITE:
--
--   bic_replay_records   diagnostic · 30-day pruner · never read by production
--                        · "removable after 1C with a single migration"
--   bic_decision_records evidence   · NO pruner · retained indefinitely
--                        · read by Replay and Explainability when they exist
--
-- Putting Decision Record fields into the 1C diagnostic table would produce a
-- record that silently deletes itself every 30 days — reproducing on day one
-- exactly the failure 3D §8.2's un-replayable-rate metric exists to detect.
--
-- ── RETENTION INVARIANT (3D §3.3, I5) ──────────────────────────────────────
-- NO PRUNING FUNCTION IS DEFINED HERE, DELIBERATELY.
-- "No artifact referenced by a retained decision may be deleted. Retirement
-- means marking inactive — never removal." A decision the business cannot
-- account for in 2036 is a decision it cannot defend. Adding a pruner to this
-- table would violate the invariant the whole of 3D rests on.
--
-- ── PRIVACY (3C §6.4, 3D §2.3, §7.5) ───────────────────────────────────────
-- Contains NO customer identifier of any kind: no phone number, no hash, no
-- last-4, no sender column, no message content, no prompts, no model prose, no
-- raw evidence values. `role` is a role, not a person. `turn_id` is OUR OWN
-- random UUID — deliberately not Meta's wamid, which encodes the recipient
-- number. Party linkage arrives later via 2D `party_id`, additively.

create table if not exists bic_decision_records (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null,

  -- 3D §10.1: every historical schema version must stay readable, forever.
  -- Evolution is additive only; no migration ever rewrites a decision record.
  schema_version         smallint not null default 1,

  -- 3D §2.5: the frozen as_of clock. Replay reads everything through this.
  decided_at             timestamptz not null default now(),

  -- Correlates this record with the turn's stdout lines. Ours, random, and
  -- carrying no information about the sender.
  turn_id                uuid not null,

  -- 3D §3.2 referenced-artifact manifest. The only manifest field with a real
  -- source today; the rest (policy/template/capability/floor versions) arrive
  -- when 3C is implemented.
  brain_version          text not null,

  route                  text not null,
  role                   text not null,
  identity_degraded      boolean not null default false,

  -- 3C §2.1 decision ladder. The CHECK carries the FULL vocabulary so a future
  -- slice can emit rungs 1 and 4 without a migration, but this slice can only
  -- observe 2, 3 and 5 — anything else is NOT_EVALUATED rather than inferred.
  decisive_rung          text not null default 'NOT_EVALUATED'
                         check (decisive_rung in (
                           'RUNG_1_CONSTITUTIONAL',
                           'RUNG_2_POLICY',
                           'RUNG_3_DETERMINISTIC',
                           'RUNG_4_PRECEDENT',
                           'RUNG_5_MODEL_ADVISORY',
                           'NOT_EVALUATED')),

  -- 3C §3.1's eight gates. ALL EIGHT KEYS ARE ALWAYS PRESENT: an omitted key is
  -- indistinguishable from a gate that was never recorded (3D §4.3), and
  -- absence must be explicit. Three have real implementation backing today
  -- (constitutional, authorization, capability); the other five are
  -- NOT_EVALUATED because 2H, 3B, budgets and risk tiers do not exist yet.
  gate_results           jsonb not null default '{}'::jsonb,

  -- 3D §4.2 / I10 — the question that proves the design: "why was AI NOT
  -- consulted?" Silence is never an answer, so non-consultation is recorded
  -- POSITIVELY, with a structured reason, on every record.
  ai_consulted           boolean not null,
  ai_consultation_reason text not null
                         check (ai_consultation_reason in (
                           'CONSULTED_RESPONSE_GENERATION',
                           'CONSULTED_ALL_PROVIDERS_FAILED',
                           'NOT_CONSULTED_DETERMINISTIC_BRANCH',
                           'NOT_CONSULTED_CHAT_PAUSED',
                           'NOT_CONSULTED_POLICY_DENIED',
                           'NOT_CONSULTED_NOT_REQUIRED')),
  ai_provider            text,

  selected_tools         text[] not null default '{}',
  denied_tools           text[] not null default '{}',

  latency_ms             numeric(10,3)
);

-- A provider must never appear on a turn that consulted nothing. Enforced in
-- the database because 3D §5.3's provider comparison depends on it being true.
alter table bic_decision_records
  drop constraint if exists bic_decision_provider_consistency;
alter table bic_decision_records
  add constraint bic_decision_provider_consistency
  check (ai_consulted = true or ai_provider is null);

create index if not exists bic_decision_decided_idx
  on bic_decision_records (decided_at desc);
create index if not exists bic_decision_rung_idx
  on bic_decision_records (decisive_rung);
create index if not exists bic_decision_turn_idx
  on bic_decision_records (turn_id);

-- RLS enabled with NO policies: anon and authenticated are denied everything.
-- Only service_role (which bypasses RLS) can write. The anon key is PUBLIC —
-- it ships in the AI Kannada client bundle — so a publicly writable decision
-- record would be a forgeable one, and forgeable evidence is not evidence.
alter table bic_decision_records enable row level security;

comment on table bic_decision_records is
  'DECISION RECORD (3C/3D). Immutable, PII-free, RETAINED INDEFINITELY —
   no pruning function exists by design (3D retention invariant I5).
   Backend/service-role write only. Distinct from bic_replay_records, which is
   1C diagnostic data with a 30-day pruner and must not be confused with this.';
