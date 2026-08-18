-- BIC — register the 2C read path as a tool.
--
-- The read goes through the Tool Registry like every other capability, so the
-- role gate is enforced by bic.policy rather than by an `if sender == OWNER`
-- check scattered in webhook.py (Slice 1C: no direct tool_*() execution).
--
-- min_role STAFF matches the other read-only owner tools (#leads, #clients,
-- #status). customer_safe is FALSE: a CLIENT principal must never reach this,
-- because knowledge about a party is internal analysis, not something the
-- chatbot discusses with the party.
--
-- risk_tier 1: read-only, no side effects, no irreversibility. Nothing here
-- writes, so no #confirm staging applies.

insert into bic_tool_defs
  (code, label, description, min_role, risk_tier, side_effects, customer_safe,
   timeout_seconds, expected_latency_ms, audit_level)
values
  ('service_interest', 'Declared service interest',
   'Current 2C ValueClaims for the caller''s declared service interest, with '
     || 'status derived at read time',
   'STAFF', 1, false, false, 10, 800, 'basic')
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
