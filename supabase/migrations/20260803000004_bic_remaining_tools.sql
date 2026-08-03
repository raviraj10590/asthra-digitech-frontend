-- BIC v1.0 — Slice 1C · Register the remaining owner tools
--
-- Closes the Tool Registry bypass: every tool execution must flow
--   Policy → Tool Registry → Tool Invocation → existing business function
-- Registration alone was insufficient; these rows are what let the remaining
-- dispatch sites route through invoke() instead of calling tool_*() directly.
--
-- min_role is STAFF for these because try_owner_command() applies NO role gate
-- today — any principal reaching the owner pipeline (OWNER/STAFF/MANAGER) can
-- run them. STAFF preserves current behaviour exactly; tightening any of them
-- would be a behaviour change and is deliberately NOT bundled in here.
--
-- roles_list stays OWNER (seeded in 20260803000001). It is reachable by STAFF
-- today, so that is a tightening in principle — but there are currently ZERO
-- effective STAFF users (the only bot_roles STAFF row is also a bootstrap
-- OWNER, and bootstrap wins), so no behaviour changes in practice. Recorded
-- rather than silently applied.

insert into bic_tool_defs
  (code, label, description, min_role, risk_tier, side_effects, customer_safe,
   timeout_seconds, expected_latency_ms, audit_level)
values
  ('status', 'Business status snapshot',
   'Bot health plus today''s leads and CRM client count',
   'STAFF', 2, false, false, 15, 2000, 'basic'),

  ('aitest', 'AI provider probe',
   'Probe every configured AI provider and report reachability + latency',
   'STAFF', 2, false, false, 30, 3000, 'basic'),

  ('memory_show', 'Show memory note',
   'Return the current long-term memory note for this principal',
   'STAFF', 1, false, false, 10, 500, 'basic'),

  -- Destructive: wipes the rolling memory note. Higher tier than the reads.
  ('memory_clear', 'Clear memory note',
   'Erase the long-term memory note for this principal',
   'STAFF', 3, true, false, 10, 500, 'full')
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
