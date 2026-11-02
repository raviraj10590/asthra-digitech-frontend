-- Auto-suggest (owner, 2026-11-02: "auto sugest ... maadu"). The bot offers to
-- learn an answer the owner wrote by hand; only an approved row is ever used.
-- Service role only, like every Brain table since the 2026-10-01 lockdown:
-- RLS on, no policies, nothing granted to anon/authenticated (this database
-- also serves AI Kannada's public site).

create table if not exists public.learned_answers (
  id          bigint generated always as identity primary key,
  business    text not null check (business in ('asthra', 'bairavi')),
  question    text not null check (char_length(question) between 1 and 1000),
  answer      text not null check (char_length(answer) between 1 and 1000),
  status      text not null default 'suggested'
              check (status in ('suggested', 'approved', 'skipped', 'removed')),
  source_ref  text unique,            -- CRM whatsapp_messages.id of the owner's reply
  created_at  timestamptz not null default now(),
  decided_at  timestamptz
);
create index if not exists learned_answers_status on public.learned_answers (status, business);

alter table public.learned_answers enable row level security;
revoke all on public.learned_answers from anon, authenticated;

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level)
values (
  'learned_answers',
  'Approve / skip / list / remove learned answers',
  'OWNER commands #learn <id> [better answer], #skip <id>, #unlearn <id>, '
    || '#learned. Changes learned_answers.status; an approved answer is what '
    || 'the bot may give a customer who asks the same question.',
  'ACT', 'api.webhook', '1.0.0',
  'OWNER', 2, true, false,
  true,
  'LIMITED',
  10, 700, 'full'
)
on conflict (code) do nothing;
