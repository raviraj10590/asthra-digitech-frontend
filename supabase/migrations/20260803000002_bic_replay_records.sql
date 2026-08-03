-- BIC v1.0 — Slice 1C · Durable replay evidence (diagnostic only)
--
-- Requirement: "Replay evidence must survive process restarts and log
-- expiration." The first implementation wrote to stdout; real owner testing
-- produced records that were unrecoverable within hours because platform log
-- retention is ~1h. An evidence channel that expires is not evidence.
--
-- ⚠️ THIS IS NOT AN AUDIT SYSTEM.
--   • diagnostic only, used to validate the 1C migration
--   • append-only; anon may INSERT and nothing else
--   • NEVER read by production code
--   • production logic has ZERO dependency on it
--
-- Separate from bic_tool_invocations on purpose: that IS the security audit
-- trail and stays service-role-only. The anon key is PUBLIC (it ships in the
-- AI Kannada client bundle), so granting it insert on the audit table would
-- make the audit trail forgeable. Diagnostic data can accept that tradeoff;
-- an audit trail cannot.
--
-- ── REMOVAL (requirement 9) ────────────────────────────────────────────────
-- Once 1C is accepted this table is optional infrastructure. Remove with a
-- single migration; production is unaffected because nothing reads it:
--
--   drop table if exists bic_replay_records;
--
-- No code change is required beyond deleting the best-effort write in
-- webhook._bic_persist_replay(), which already swallows every failure.

create table if not exists bic_replay_records (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null,

  -- Exactly the metadata approved in requirement 10. Nothing else.
  route          text,          -- owner | client
  role           text,          -- OWNER | STAFF | MANAGER | CLIENT
  flow           text,          -- flow actually selected
  decision_hash  text,          -- stable hash of the Decision
  selected_tools text[] not null default '{}',
  degraded       boolean not null default false,
  latency_ms     numeric(10,3),
  diff_count     integer not null default 0,

  created_at     timestamptz not null default now()
);

-- NO sender column, not even a suffix: requirement 10 does not list one, and
-- the smallest thing that satisfies the requirement stores no identifier at
-- all. Route/role/flow are sufficient to validate the migration.
--
-- Deliberately absent, per explicit instruction: prompts, conversation
-- history, customer messages, phone numbers, AI responses.

create index if not exists bic_replay_created_idx
  on bic_replay_records (created_at desc);

alter table bic_replay_records enable row level security;

-- Append-only for the public anon key: INSERT and nothing else. No select,
-- update or delete policy exists, so records cannot be read or tampered with
-- through the public key — only appended. Analysis is done with an
-- administrative credential.
drop policy if exists bic_replay_anon_insert on bic_replay_records;
create policy bic_replay_anon_insert
  on bic_replay_records for insert to anon with check (true);
