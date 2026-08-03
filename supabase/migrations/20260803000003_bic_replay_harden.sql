-- BIC v1.0 — Slice 1C · Harden the replay diagnostic table
--
-- Owner changes:
--   2. Remove the anonymous INSERT policy — backend writes only
--   3. Add schema_version
--   4. Automatic 30-day retention
--
-- ⚠️ CONSEQUENCE OF CHANGE 2 — read before deploying:
-- The anon key is PUBLIC. There is no way to distinguish "the backend webhook"
-- from "anyone holding the anon key", because they present the same credential.
-- So "only the backend may write" necessarily requires a SERVER-ONLY secret.
--
-- With this migration applied, replay writes require a service-role credential.
-- Until one is configured, every replay write fails — harmlessly, because the
-- write is best-effort and swallowed — but NO EVIDENCE IS COLLECTED.
--
-- This is not re-coupling the architecture to a credential; it is the direct
-- logical consequence of requiring that only the backend can write. The
-- requirement remains "evidence must survive restarts and log expiration";
-- change 2 additionally requires "and must not be publicly writable", and those
-- two together admit no anon-key solution.

-- ── 3. schema_version ──────────────────────────────────────────────────────
-- Lets a later reader tell which shape a row was written in, so the table can
-- evolve without silently mixing incompatible records.
alter table bic_replay_records
  add column if not exists schema_version smallint not null default 1;

-- ── 2. Remove public write capability ──────────────────────────────────────
-- After this, RLS is enabled with NO policies at all: anon and authenticated
-- are denied everything. Only service_role (which bypasses RLS) can write.
drop policy if exists bic_replay_anon_insert on bic_replay_records;

-- ── 4. Automatic retention ─────────────────────────────────────────────────
-- Diagnostic data has no long-term value and must not become an analytics
-- system. 30 days is ample for validating a migration.
--
-- No pg_cron dependency (not guaranteed on the free tier). Invoked by the
-- existing daily digest cron — Article X adds no fourth scheduler.
create or replace function bic_prune_replay_records(retain_days integer default 30)
returns integer
language plpgsql
as $$
declare
  v_deleted int := 0;
begin
  delete from bic_replay_records
  where created_at < now() - (retain_days || ' days')::interval;
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

-- Deletion is never model- or client-callable.
revoke all on function bic_prune_replay_records(integer) from public, anon, authenticated;

comment on table bic_replay_records is
  'DIAGNOSTIC ONLY — Slice 1C migration validation. Append-only, backend-write
   only, never read by production logic, 30-day retention. Removable after 1C
   with: drop table bic_replay_records; drop function bic_prune_replay_records(integer);';
