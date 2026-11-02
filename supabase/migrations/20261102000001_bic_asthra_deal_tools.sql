-- The Asthra deal (owner, 2026-11-02): chat each Asthra customer until the
-- ADVANCE PAYMENT. The bot reports a requirement it cannot price; the owner
-- answers "#price 4521 75000 tingaLige" and the customer gets the quotation;
-- "#advance 4521" ends the deal and stops the 17-day follow-ups.
--
-- A tool is only invocable if bic_tool_defs holds its row (policy.may_invoke:
-- unknown tool -> DENY). No table, no column: two inserts. OWNER only — a
-- price and a payment are the owner's word.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'asthra_send_price',
  'Send a customer the owner''s quotation',
  'OWNER command "#price <last digits> <amount> [note]". Sends the customer '
    || 'whose number ends in those digits the quotation, only inside the '
    || 'WhatsApp 24-hour window; refuses when the digits match no chat or '
    || 'more than one.',
  'ACT', 'api.webhook', '1.0.0',
  'OWNER', 2, true, false,
  true,
  'LIMITED',
  10, 900, 'full'
)
on conflict (code) do nothing;

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'asthra_mark_advance',
  'Mark an Asthra deal done (advance received)',
  'OWNER command "#advance <last digits>". Writes ASTHRA_ADVANCE_PAID into '
    || 'the chat transcript; the follow-up sweep stops for that customer.',
  'ACT', 'api.webhook', '1.0.0',
  'OWNER', 2, true, false,
  true,
  'LIMITED',
  10, 600, 'full'
)
on conflict (code) do nothing;
