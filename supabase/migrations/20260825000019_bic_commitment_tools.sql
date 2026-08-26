-- BIC 2B — the OWNER consumer that CLOSES a commitment.
--
-- WHY THIS MIGRATION EXISTS AT ALL
-- --------------------------------
-- Stage ⑮ can now create a Commitment, but nothing could resolve one, so a
-- production promise would sit in `made` forever and the daily digest would
-- report it overdue indefinitely. These two rows are what make the closing
-- commands reachable.
--
-- A tool is only invocable if bic_tool_defs holds its row: policy.may_invoke
-- answers "unknown tool -> DENY" for anything absent, and tools._load_registry
-- reads the table. So registering a capability is a migration in this
-- architecture, exactly as it was for #suffice, #why and the privileged
-- role tools. Handling these commands in webhook.py without a row would mean
-- an owner action that never passes may_invoke — a SECOND authorization path,
-- which is the thing the registry exists to prevent.
--
-- NO TABLE. NO COLUMN. NO CHANGE TO ANY EXISTING MIGRATION. Two inserts.
--
-- RISK TIER 3, NOT 4. Tier 4 in this system is reserved for privilege
-- escalation (add_role/remove_role) — "nothing else in the system can escalate
-- privilege". Resolving a commitment changes one business record's lifecycle:
-- the same blast radius as chat_pause, which is tier 3 and side-effecting.
--
-- audit_level 'full' on the ACT. `met` and `waived` are TERMINAL in 2B — the
-- lifecycle has no arrow out of them — so who closed which promise, and on
-- what stated reason, is exactly what an audit trail is for.
--
-- customer_safe = false on BOTH. CLIENT is an allowlist (Article VI): a
-- customer must never see what the business owes, let alone close it.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   freshness, provenance_tiers, degradation, explainability)
values (
  'commitments_list',
  'What do we still owe?',
  'OWNER command #commitments. Lists this tenant''s open 2B commitments — '
    || 'obligation, lifecycle, deadline, overdue state and accountable owner — '
    || 'with a short reference for closing each one.',
  'QUERY', 'bic.commitment', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  10, 800, 'basic',

  'Live. Read straight from bic_commitments on every call, with no cache: a '
    || 'stale answer to "what have we promised" is worse than a slow one, '
    || 'because the owner acts on it.',

  array[0,1,2,3,4,5]::smallint[],

  'Store unreachable -> UNAVAILABLE naming the exception TYPE only, never a '
    || 'partial list. A short list and an empty list are both believable, so '
    || 'a truncated answer here would read as "nothing outstanding" and the '
    || 'owner would stop looking.',

  'Every row states its obligation, lifecycle, deadline and whether it is '
    || 'past due. Identifiers are opaque short references derived from the '
    || 'commitment id — never a phone, an email, a wamid or a raw uuid.'
)
on conflict (code) do nothing;

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'commitment_resolve',
  'Resolve a commitment',
  'OWNER command #commitment <ref> start|met|waive <reason>. Moves one 2B '
    || 'commitment through the atomic transition RPC. Only the transitions '
    || '2B''s lifecycle diagram permits are offered; `missed` is deliberately '
    || 'absent, being a judgement the daily digest must not be able to trigger.',
  'ACT', 'bic.commitment', '1.0.0',
  'OWNER', 3, true, false,
  true,
  'LIMITED',
  10, 900, 'full'
)
on conflict (code) do nothing;
