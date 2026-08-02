-- BIC v1.0 — Slice 1A · Observability
-- Constitution: Article II.10 (auditable), Performance Rules (measure or you
-- cannot optimise).
--
-- This table is doing quadruple duty on purpose: audit trail, cost visibility,
-- latency data, and Learning input (which tools actually help). It is also the
-- fix for a real operational gap — Vercel retains logs for roughly an hour, so
-- today there is effectively NO durable record of what the system did. A
-- 10-day outage went unnoticed for exactly this reason.

create table if not exists bic_tool_invocations (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null,

  tool         text not null,              -- not FK: keep logging a tool even
                                           -- after it is removed from the registry
  role         text not null,              -- role of the CALLER, for audit
  channel      text not null default 'whatsapp',

  args_redacted jsonb not null default '{}', -- NEVER raw args: may hold PII/secrets
  ok           boolean not null,
  error        text,

  latency_ms   integer,
  tokens_in    integer,
  tokens_out   integer,
  db_queries   integer,                    -- Performance Rules: measure queries

  source_ref   text,                       -- originating message → Article II.10
  created_at   timestamptz not null default now()
);

create index if not exists bic_tool_inv_created_idx on bic_tool_invocations (created_at desc);
create index if not exists bic_tool_inv_tool_idx    on bic_tool_invocations (tenant_id, tool, created_at desc);
-- Partial index: failure queries are the common operational question
-- ("what is broken?"), and failures are a small fraction of rows.
create index if not exists bic_tool_inv_failed_idx  on bic_tool_invocations (tenant_id, created_at desc)
  where ok = false;

-- Rollup target. Raw rows live 30 days (Article IV retention); the aggregate
-- lives forever at ~1/1000th the size. Without this, projected growth was
-- ~7GB over 5 years against a 500MB free tier — the free tier dies in month 4
-- and the first symptom is writes failing, i.e. the bot silently stops working.
create table if not exists bic_tool_stats_daily (
  tenant_id   uuid not null,
  day         date not null,
  tool        text not null,
  calls       integer not null default 0,
  failures    integer not null default 0,
  p95_latency_ms integer,
  tokens_in   bigint not null default 0,
  tokens_out  bigint not null default 0,
  primary key (tenant_id, day, tool)
);

alter table bic_tool_invocations enable row level security;
alter table bic_tool_stats_daily enable row level security;
