-- BIC v1.0 — Slice 1B · Self-describing tool registry
-- Constitution: Article VI (authorization), Article VIII (extensibility)
--
-- Extends 1A's bic_tool_defs with the operational metadata the owner required,
-- so the registry describes itself: what a tool is, who may call it, how long
-- it should take, and how loudly to audit it.
--
-- This is an ALTER on a table BIC owns. Article VIII forbids ALTER TABLE for
-- adding VERTICALS (that must stay INSERT-only); evolving BIC's own schema
-- between slices is ordinary migration work.

alter table bic_tool_defs
  add column if not exists timeout_seconds     integer not null default 15,
  -- Baseline for regression detection: alert when observed p95 drifts far past
  -- this. Without a declared expectation there is nothing to regress against.
  add column if not exists expected_latency_ms integer not null default 1000,
  add column if not exists audit_level         text    not null default 'basic'
    check (audit_level in ('none', 'basic', 'full'));

comment on column bic_tool_defs.audit_level is
  'none  = record nothing (reserved for high-volume trivial reads)
   basic = tool, role, timing, outcome — NO arguments
   full  = basic + allowlist-redacted arguments';

-- Explicit start/end. The owner asked for start time AND end time AND duration:
-- storing all three means a crashed invocation is still visible (started_at set,
-- finished_at null) instead of vanishing — a row that never completes is exactly
-- the signal worth keeping.
alter table bic_tool_invocations
  add column if not exists started_at  timestamptz,
  add column if not exists finished_at timestamptz;

-- Find hung/crashed invocations.
create index if not exists bic_tool_inv_unfinished_idx
  on bic_tool_invocations (tenant_id, started_at)
  where finished_at is null;

-- ── Seed the five approved tools ───────────────────────────────────────────
-- Scope deliberately small (owner-approved): prove the mechanism before
-- migrating the rest. Registering a tool is an INSERT (Article VIII).
--
-- owner_only is NOT stored — it is derivable from min_role = 'OWNER'. Storing
-- both invites the two disagreeing, and a contradiction in an authorization
-- table is a security bug. The registry exposes owner_only as a computed
-- property instead.
insert into bic_tool_defs
  (code, label, description, min_role, risk_tier, side_effects, customer_safe,
   timeout_seconds, expected_latency_ms, audit_level)
values
  ('crm_sync_lead', 'Sync lead to CRM',
   'Upsert a captured lead into the Asthra CRM clients table',
   'STAFF', 3, true,  false, 10, 1200, 'full'),

  ('crm_list_clients', 'List CRM clients',
   'Read recent clients and total count from the CRM',
   'STAFF', 2, false, false, 10,  900, 'basic'),

  ('leads_today', 'Today''s leads',
   'Count and list leads captured today from the AI Kannada leads table',
   'STAFF', 2, false, false, 10,  700, 'basic'),

  ('roles_list', 'List access roles',
   'List OWNER/STAFF numbers with bot access',
   'OWNER', 2, false, false, 10,  600, 'basic'),

  -- The only customer-reachable tool. Included on purpose so the allowlist path
  -- is exercised in production, not only in tests.
  ('send_brochure', 'Send company brochure',
   'Send the Asthra DigiTech company profile PDF over WhatsApp',
   'CLIENT', 2, true,  true,  15, 1500, 'basic')
on conflict (code) do update set
  label               = excluded.label,
  description         = excluded.description,
  min_role            = excluded.min_role,
  risk_tier           = excluded.risk_tier,
  side_effects        = excluded.side_effects,
  customer_safe       = excluded.customer_safe,
  timeout_seconds     = excluded.timeout_seconds,
  expected_latency_ms = excluded.expected_latency_ms,
  audit_level         = excluded.audit_level;
