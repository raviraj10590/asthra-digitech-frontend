-- BIC v1.0 — Slice 1A · Retention
-- Constitution: Article II.7 — "Raw data is a cache; derived knowledge is the
-- asset. Every raw table has a retention window."
--
-- These ship in Phase 1, NOT later. The architecture review found the original
-- append-only design contradicted the stated principle that knowledge should
-- evolve rather than grow forever, and blew the 500MB free tier within months.
--
-- Functions only — no pg_cron dependency. They are invoked by the existing
-- scheduler (cron-job.org), because Article X adds no fourth scheduler and
-- pg_cron is not guaranteed on the free tier.

-- Roll raw tool invocations into daily aggregates, then delete the raw rows.
-- Idempotent: re-running for the same day recomputes rather than duplicates.
create or replace function bic_rollup_tool_invocations(retain_days integer default 30)
returns table (days_rolled integer, rows_deleted integer)
language plpgsql
as $$
declare
  v_days int := 0;
  v_deleted int := 0;
  cutoff date := (now() at time zone 'utc')::date - retain_days;
begin
  insert into bic_tool_stats_daily (tenant_id, day, tool, calls, failures,
                                    p95_latency_ms, tokens_in, tokens_out)
  select tenant_id,
         (created_at at time zone 'utc')::date as day,
         tool,
         count(*),
         count(*) filter (where ok = false),
         percentile_disc(0.95) within group (order by latency_ms)::int,
         coalesce(sum(tokens_in), 0),
         coalesce(sum(tokens_out), 0)
  from bic_tool_invocations
  where (created_at at time zone 'utc')::date < cutoff
  group by tenant_id, day, tool
  on conflict (tenant_id, day, tool) do update
    set calls = excluded.calls,
        failures = excluded.failures,
        p95_latency_ms = excluded.p95_latency_ms,
        tokens_in = excluded.tokens_in,
        tokens_out = excluded.tokens_out;

  get diagnostics v_days = row_count;

  delete from bic_tool_invocations
  where (created_at at time zone 'utc')::date < cutoff;

  get diagnostics v_deleted = row_count;

  return query select v_days, v_deleted;
end;
$$;

-- Archive superseded facts past the retention window.
-- Deliberately NOT a hard delete of history: valid_from/valid_to lineage on the
-- ACTIVE row is what auditability needs (Article II.10); the dead rows behind it
-- are not. Facts never referenced are dropped; referenced ones are retained
-- longer because something in the system pointed at them.
create or replace function bic_prune_superseded_facts(retain_days integer default 180)
returns integer
language plpgsql
as $$
declare
  v_deleted int := 0;
begin
  delete from bic_facts
  where status = 'superseded'
    and valid_to < now() - (retain_days || ' days')::interval
    and reference_count = 0;

  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

-- Deletes are irreversible, so both functions are OWNER-operated via the
-- scheduler and never callable by the model. Article II.3: nothing
-- side-effecting executes inline.
revoke all on function bic_rollup_tool_invocations(integer) from public, anon, authenticated;
revoke all on function bic_prune_superseded_facts(integer) from public, anon, authenticated;
