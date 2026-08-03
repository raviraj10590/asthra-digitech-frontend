-- BIC v1.0 — Slice 1C · Register the PRIVILEGED commands (review C1, H4)
--
-- The engineering review found that the four highest-privilege operations in
-- the bot were the ONLY ones still bypassing the Tool Registry:
--
--   add_role / remove_role  — can mint or revoke an OWNER. Guarded by a single
--                             inline `if role != "OWNER"` string compare at
--                             STAGING time, re-checked nowhere, audited nowhere.
--   chat_pause / chat_resume — can silence the bot for ANY phone number, with
--                             no role check at all, writing to a third party's
--                             message history.
--
-- The security boundary was inverted relative to risk: every read-only tool
-- (#leads, #memory) passed the Policy Gate while the operation that decides who
-- is privileged did not.
--
-- Why the no-bypass test missed them: it enumerated functions named `tool_*`.
-- These are named `_tool_*`. A leading underscore exempted the two most
-- dangerous functions in the file. The test is widened in the same change.
--
-- ── Role assignment ────────────────────────────────────────────────────────
-- add_role / remove_role  → OWNER. Matches the existing inline staging check
--                           exactly, so behaviour is preserved, not tightened.
-- chat_pause / chat_resume → OWNER. This IS a tightening: today any principal
--                           reaching try_owner_command (OWNER/STAFF/MANAGER)
--                           can pause any customer. There are currently ZERO
--                           effective non-owner internal users — the only
--                           bot_roles STAFF row is phone …9951, which is also a
--                           bootstrap OWNER, and bootstrap wins — so no live
--                           behaviour changes. Recorded explicitly rather than
--                           applied silently, because it becomes a real
--                           restriction the moment a genuine STAFF is added.
--                           If STAFF should keep pause rights, change min_role
--                           here — one UPDATE, no code change. That is the
--                           point of the registry.
--
-- risk_tier 4 for role changes: nothing else in the system can escalate
-- privilege. audit_level 'full' on all four — these are exactly the events an
-- audit trail exists for.

insert into bic_tool_defs
  (code, label, description, min_role, risk_tier, side_effects, customer_safe,
   timeout_seconds, expected_latency_ms, audit_level)
values
  ('add_role', 'Grant bot access',
   'Grant OWNER or STAFF access to a phone number',
   'OWNER', 4, true, false, 10, 800, 'full'),

  ('remove_role', 'Revoke bot access',
   'Revoke bot access for a phone number',
   'OWNER', 4, true, false, 10, 800, 'full'),

  ('chat_pause', 'Pause bot for a chat',
   'Silence the bot for one customer conversation (auto-resumes in 24h)',
   'OWNER', 3, true, false, 10, 600, 'full'),

  ('chat_resume', 'Resume bot for a chat',
   'Resume automated replies for one customer conversation',
   'OWNER', 3, true, false, 10, 600, 'full')
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
