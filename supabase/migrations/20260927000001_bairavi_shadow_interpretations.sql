-- =====================================================================
-- Bairavi interpretation SHADOW telemetry (architecture Step 2)
-- =====================================================================
--
-- WHY THIS EXISTS
-- ---------------
-- In shadow mode an interpreter reads each Bairavi follow-up AFTER production
-- has fully handled it; its proposal is validated and compared with the
-- parser that actually decided the turn. Vercel runtime logs are too short-
-- lived for the owner's 1-2 week review, so the comparison is kept here.
--
-- WHAT IT IS NOT
-- --------------
-- Not CRM data, not transcript, not customer memory, not lead state, not
-- Business Brain memory, not a Decision Record. No foreign keys, no triggers,
-- nothing in the live pipeline reads it. Observation only.
--
-- DESIGN B — NO CUSTOMER WORDS (owner-approved 2026-09-27)
-- ---------------------------------------------------------
-- No phone, no message body, no WhatsApp message id, no evidence text, no
-- delivery-place text, no raw model output. `turn_key` is
-- HMAC-SHA256(SHADOW_TURN_KEY, wamid)[:32]; with the secret, a reviewer can
-- find the original message in the CRM transcript, which stays the single
-- place customer words live. Evidence is described by structure only.
--
-- SECURITY
-- --------
-- RLS on with NO policies (the Brain's service-role-only pattern), and every
-- privilege revoked from anon/authenticated as a second layer. The service
-- role may INSERT / SELECT / DELETE — no UPDATE: rows are append-only.
--
-- RETENTION
-- ---------
-- bairavi_prune_shadow_interpretations(retain_days) — called daily by
-- api/digest.py with 14 (owner-approved). No pg_cron dependency.
--
-- APPLIED: NO — created locally for review. Do not `supabase db push`
-- (the Brain's migration ledger has known drift).
-- =====================================================================

create table if not exists public.bairavi_shadow_interpretations (
  id                 bigint generated always as identity primary key,
  created_at         timestamptz not null default now(),
  business           text not null default 'bairavi' check (business in ('bairavi')),
  turn_key           text not null check (turn_key ~ '^[0-9a-f]{32}$'),
  record_version     smallint not null check (record_version > 0),
  contract_version   text not null check (char_length(contract_version) between 1 and 24),
  validator_version  text not null check (char_length(validator_version) between 1 and 24),
  prompt_version     text not null check (prompt_version ~ '^[0-9a-f]{12}$'),
  provider           text check (char_length(provider) <= 20),
  model              text check (char_length(model) <= 40),
  status             text not null check (status in
                       ('ok', 'invalid_shadow', 'provider_failed', 'skipped_deadline', 'shadow_error')),
  error_class        text check (char_length(error_class) <= 40),   -- exception TYPE only
  awaiting           text[] not null default '{}'
                       check (awaiting <@ array['delivery', 'purpose', 'capacity', 'quantity', 'callback']),
  latency_ms         integer check (latency_ms >= 0),
  budget_ms          integer check (budget_ms >= 0),
  deadline_left_ms   integer,
  intent             text check (intent in ('answer', 'question', 'greeting', 'ack', 'correction',
                       'price_request', 'quotation_request', 'callback_choice', 'off_topic', 'unclear')),
  questions          text[] check (questions <@ array['delivery_time', 'delivery_area', 'warranty',
                       'payment', 'transport', 'who_are_you', 'range', 'discom_approval', 'other']),
  is_correction      boolean,
  -- {field: {value (never for delivery_place), evidence_found, value_in_evidence,
  --          evidence_len, outcome}} — structure only, no customer words
  proposed           jsonb check (proposed is null or jsonb_typeof(proposed) = 'object'),
  -- {capacity_kva, quantity, application, callback, delivery_place_accepted: bool}
  accepted           jsonb check (accepted is null or jsonb_typeof(accepted) = 'object'),
  -- [[field, reason], ...] — fixed vocabularies
  rejected           jsonb not null default '[]'::jsonb check (jsonb_typeof(rejected) = 'array'),
  ambiguous          text check (ambiguous in
                       ('capacity_kva', 'quantity', 'application', 'delivery_place', 'callback')),
  -- {field: MATCH|SHADOW_ONLY|PARSER_ONLY|CONFLICT|INVALID_SHADOW|SKIPPED}
  comparison         jsonb check (comparison is null or jsonb_typeof(comparison) = 'object'),
  conflict_fields    text[] not null default '{}',
  -- {field: {parser, shadow}} for non-place fields only (never delivery_place)
  diffs              jsonb check (diffs is null or (jsonb_typeof(diffs) = 'object'
                                                    and not diffs ? 'delivery_place')),
  constraint bairavi_shadow_one_per_turn_version
    unique (turn_key, contract_version, validator_version)
);

create index if not exists bairavi_shadow_created_idx
  on public.bairavi_shadow_interpretations (created_at);

-- ── access: service role only ────────────────────────────────────────────
alter table public.bairavi_shadow_interpretations enable row level security;
-- (deliberately NO policies)
revoke all on public.bairavi_shadow_interpretations from public, anon, authenticated;
revoke all on sequence public.bairavi_shadow_interpretations_id_seq from public, anon, authenticated;
revoke update on public.bairavi_shadow_interpretations from service_role;
grant insert, select, delete on public.bairavi_shadow_interpretations to service_role;
grant usage on sequence public.bairavi_shadow_interpretations_id_seq to service_role;

-- ── retention ─────────────────────────────────────────────────────────────
create or replace function public.bairavi_prune_shadow_interpretations(retain_days integer)
returns integer
language sql
security invoker
as $$
  with d as (
    delete from public.bairavi_shadow_interpretations
    where created_at < now() - make_interval(days => greatest(retain_days, 1))
    returning 1
  )
  select count(*)::integer from d;
$$;

revoke execute on function public.bairavi_prune_shadow_interpretations(integer)
  from public, anon, authenticated;
grant execute on function public.bairavi_prune_shadow_interpretations(integer) to service_role;
