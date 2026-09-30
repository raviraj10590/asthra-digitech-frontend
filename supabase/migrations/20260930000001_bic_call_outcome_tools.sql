-- Owner call outcomes from WhatsApp (owner request 2026-09-30).
--
-- "I called almost all of them but there is no option to tick them in the
-- CRM, and the CRM cannot read my phone's call log." The owner now sends
-- "5711 called interested" from WhatsApp and the lead's EXISTING CRM fields
-- are updated: clients.pipeline_stage, clients.last_contacted_at, and a dated
-- line appended to clients.notes. The CRM's own Calls page writes the same
-- three fields.
--
-- A tool is only invocable if bic_tool_defs holds its row (policy.may_invoke:
-- unknown tool -> DENY), so both paths are registered here, as every owner
-- command before them was. No table, no column: two inserts.
--
-- STAFF, not OWNER: whoever makes the calls marks them. Same tier as
-- leads_today / crm_list_clients (operational lookups) and crm_sync_lead
-- (the existing CRM write).

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'crm_calls_to_make',
  'Leads still to call',
  'OWNER/STAFF command #calls. Bairavi leads from the last 14 days whose CRM '
    || 'stage is still the default and that nobody has marked, newest first.',
  'QUERY', 'api.webhook', '1.0.0',
  'STAFF', 1, false, false,
  true,
  'LIMITED',
  10, 700, 'basic',

  'Live. Read straight from the CRM clients table on every call, no cache: '
    || 'a lead marked a minute ago must already be off the list.',

  array[0,1,2,3,4,5]::smallint[],

  'CRM unreachable -> "Could not reach the CRM", never an empty list: an '
    || 'empty list reads as "everyone has been called".',

  'Each row is a name and the number to call; the list says it covers '
    || 'unmarked Bairavi leads from the last 14 days.'
)
on conflict (code) do nothing;

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'crm_call_outcome',
  'Record a call outcome',
  'OWNER/STAFF message "<last digits> <outcome>", e.g. "5711 called '
    || 'interested". Sets the CRM lead''s pipeline_stage and last_contacted_at '
    || 'and appends a dated note; "no answer" appends the note only. Refuses '
    || 'when the digits match no lead or more than one.',
  'ACT', 'api.webhook', '1.0.0',
  'STAFF', 2, true, false,
  true,
  'LIMITED',
  10, 900, 'full'
)
on conflict (code) do nothing;
