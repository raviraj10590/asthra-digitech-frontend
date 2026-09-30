-- One customer's brief, asked from the owner's own WhatsApp (2026-10-01).
--
-- "am asking through my number to the bot brain number but it does not get
-- data in CRM — its knowledge is limited." The owner assistant had no way to
-- read a lead. "5711" / "#who <name>" now returns the lead's form facts,
-- CRM stage, last call note, AI summary, last messages and open follow-ups.
-- Registered here because policy.may_invoke denies any unregistered tool.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'crm_customer_brief',
  'One customer from the CRM',
  'OWNER/STAFF "5711" or "#who <name>": the CRM lead''s form facts, stage, '
    || 'last call note, AI summary, recent messages and open follow-ups.',
  'QUERY', 'api.webhook', '1.0.0',
  'STAFF', 1, false, false,
  true,
  'LIMITED',
  10, 900, 'basic',

  'Live. Read from the CRM clients, whatsapp_messages and follow_ups tables '
    || 'on every call, no cache.',

  array[0,1,2,3,4,5]::smallint[],

  'CRM unreachable -> "Could not reach the CRM", never an empty brief. '
    || 'Several matches -> a list asking for more digits, never a guess.',

  'Every line names its source: the form, the CRM stage, the dated call '
    || 'note, the stamped AI summary, the timestamped messages.'
)
on conflict (code) do nothing;
