-- Conversion Evidence v1 — the OWNER capability that records a first payment.
--
-- WHY A REGISTRY ROW AND NOT A ROLE CHECK AT THE DISPATCH SITE
-- ------------------------------------------------------------
-- try_owner_command is reached by INTERNAL_ROLES = ('OWNER','STAFF'), so a
-- command handled inline would be STAFF-reachable. This one writes a permanent
-- business fact about revenue. The alternative is a role check written at the
-- dispatch site — the SECOND AUTHORIZATION PATH this codebase repeatedly
-- refuses, "two authorization paths is one authorization hole" (C-1, Phase 1C).
-- So it is the row, exactly as with 20260904000023 and 20260905000024.
--
-- ACT, RISK TIER 3, side_effects TRUE — and every one of those is deliberate.
-- It is the only tool in the system that writes an IRREVERSIBLE business
-- claim: append-only storage means a mistake cannot be edited away, only
-- retracted, and a retraction is itself permanent history. audit_level 'full'
-- for the same reason.
--
-- customer_safe = false. CLIENT is an allowlist (Article VI). A customer must
-- never be able to assert that they have paid — that is the whole point of
-- sourcing this from the owner in role rather than from the conversation.
--
-- NO AUTOMATIC PAYMENT DETECTION, BY DESIGN
-- -----------------------------------------
-- There is no trustworthy payment event source in this system today. No bank
-- feed, no Tally integration, no payment gateway webhook. Building a natural
-- language detector over "looks like they paid" would manufacture tier 4
-- model-derived evidence and present it as a financial fact — the single
-- worst thing this predicate could become. The owner names the party and
-- confirms explicitly, or nothing is recorded.
--
-- TWO-STEP EXPLICIT CONFIRMATION, NOT THE SHARED PENDING-CONFIRM FLOW
-- -------------------------------------------------------------------
-- The existing _stage_confirm/#confirm machinery accepts CONFIRM_WORDS =
-- {"#confirm", "confirm", "yes", "ok", "haudu", "ಹೌದು"} — already carrying a
-- documented KNOWN HAZARD comment in webhook.py that a bare "ok", one of the
-- most common WhatsApp replies there is, executes whatever is staged. For a
-- permanent revenue fact that is not an acceptable trigger. This command
-- therefore requires the word `confirm` INSIDE the command itself
-- (`#paid <phone> [date] confirm`), which holds no pending state, cannot be
-- fired by a stray reply, and needs no change to the shared flow that other
-- commands still depend on.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'record_first_payment',
  'Record first payment received',
  'OWNER command #paid <phone> [YYYY-MM-DD] confirm. Records '
    || 'core.party.became_client_at@1 for one party at provenance tier 1 '
    || '(owner-confirmed). The party must already be known to the Brain — the '
    || 'phone is LOOKED UP, never created, so this can neither mint an '
    || 'identity nor attach revenue to a party we have never observed. Reads '
    || 'before writing and declines if a first payment already exists: a '
    || 'second is a defect, not a correction. Records a timestamp and nothing '
    || 'else — no amount, no currency, no transaction reference ever enters a '
    || 'claim.',
  'ACT', 'api.webhook', '1.0.0',
  'OWNER', 3, true, false,
  true,
  'LIMITED',
  10, 900, 'full'
)
on conflict (code) do nothing;
