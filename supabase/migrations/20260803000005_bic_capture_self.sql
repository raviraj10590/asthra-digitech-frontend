-- BIC v1.0 — Slice 1C · Self-service lead capture tool
--
-- upsert_lead() runs inside the CLIENT pipeline and must record the conversing
-- customer's own details in the CRM. Routing that through crm_sync_lead would
-- be denied (STAFF, not customer_safe), silently breaking lead capture.
--
-- The fix is NOT to relax crm_sync_lead. Two operations share one
-- implementation but have different exposure:
--   crm_sync_lead    STAFF  — sync an arbitrary lead; an administrative action
--   crm_capture_self CLIENT — record MY OWN details; a data-capture step
--
-- crm_capture_self is safe by construction: its handler always uses
-- principal.sender_id, which the WhatsApp transport authenticated. A customer
-- cannot name another subject, and can only persist data they already supplied
-- by talking to the bot — no capability they did not already have.
--
-- side_effects = true (a CRM write), so it is audited at full level despite
-- being customer-reachable.

insert into bic_tool_defs
  (code, label, description, min_role, risk_tier, side_effects, customer_safe,
   timeout_seconds, expected_latency_ms, audit_level)
values
  ('crm_capture_self', 'Capture own lead details',
   'Record the authenticated caller''s own lead details in the CRM',
   'CLIENT', 2, true, true, 10, 1500, 'full')
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
