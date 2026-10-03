-- The owner's CRM on WhatsApp, phase 1 — read-only (owner request 2026-10-04:
-- "hanta ondu maadu").
--
--   crm_owner_view  #today #followups #chats #pipeline #week   (STAFF, read-only)
--   crm_money_due   #due — unpaid invoices                      (OWNER, read-only)
--
-- A tool is only invocable if bic_tool_defs holds its row (policy.may_invoke:
-- unknown tool -> DENY). No table, no column: two inserts. Neither tool
-- writes anything, and neither reads the NaraRouter tables (owner rule).

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'crm_owner_view',
  'CRM views on WhatsApp',
  'OWNER/STAFF commands #today, #followups, #chats, #pipeline, #week. Read-only '
    || 'views of the CRM: follow-ups due, conversations waiting for a reply, new '
    || 'leads, stage counts and 7-day numbers.',
  'QUERY', 'api.webhook', '1.0.0',
  'STAFF', 1, false, false,
  true,
  'LIMITED',
  12, 1500, 'basic',

  'Live. Read straight from the CRM on every call, no cache.',

  array[0,1,2,3,4,5]::smallint[],

  'CRM unreachable -> "Could not reach the CRM", never an empty list: an '
    || 'empty list reads as "nothing to do".',

  'Each list names the lead, the reason it is listed and its number; counts '
    || 'say what they count and over which period.'
),
(
  'crm_money_due',
  'Unpaid invoices',
  'OWNER command #due. Invoices with a balance due, oldest due date first, '
    || 'with the total. Read-only.',
  'QUERY', 'api.webhook', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  10, 900, 'basic',

  'Live. Read straight from the CRM invoices table on every call, no cache.',

  array[0,1,2,3,4,5]::smallint[],

  'CRM unreachable -> "Could not reach the CRM", never "no invoice has money '
    || 'due".',

  'Each line is the client, the amount due, the invoice number and its due date.'
)
on conflict (code) do nothing;
