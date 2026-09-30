-- #voicetest (owner request 2026-10-01: Kannada voice replies).
--
-- Voice replies to customers ship OFF (VOICE_REPLIES env). Before switching
-- them on, the owner hears a sample: "#voicetest [text]" synthesises the
-- text and sends the voice note to the person who asked — never to a
-- customer. Registered here because policy.may_invoke denies any tool
-- without a bic_tool_defs row. No table, no column: one insert.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'voice_test',
  'Hear a voice-reply sample',
  'OWNER/STAFF command #voicetest [text]. Synthesises the text (or a stock '
    || 'Bairavi greeting) as a Kannada voice note and sends it to the '
    || 'requester only.',
  'ACT', 'api.webhook', '1.0.0',
  'STAFF', 1, true, false,
  true,
  'LIMITED',
  20, 6000, 'basic'
)
on conflict (code) do nothing;
