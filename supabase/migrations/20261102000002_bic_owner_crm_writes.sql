-- Owner CRM on WhatsApp, phase 2 (owner, 2026-11-02: "phase two maadu"):
-- #fu / #done / #note / #stage, each staged and written only after #confirm.
-- Writes only the CRM's existing fields: follow_ups rows, follow_ups.is_done,
-- clients.notes, clients.pipeline_stage. OWNER only, like every #confirm action.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'crm_owner_write',
  'Owner CRM write (after #confirm)',
  'OWNER commands #fu <digits> <date> [note], #done <digits>, #note <digits> '
    || '<text>, #stage <digits> <stage>. Staged with the lead named; written '
    || 'only after #confirm, to follow_ups or the lead''s notes / stage.',
  'ACT', 'api.webhook', '1.0.0',
  'OWNER', 2, true, false,
  true,
  'LIMITED',
  10, 900, 'full'
)
on conflict (code) do nothing;
