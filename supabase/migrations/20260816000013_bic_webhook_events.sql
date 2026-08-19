-- BIC — durable Meta message-id deduplication.
--
-- THE DEFECT THIS CLOSES
-- ----------------------
-- is_duplicate_webhook() compares the inbound text against ctx["last_user"],
-- read from whatsapp_messages at the START of the request. But the inbound
-- message is only persisted by save_messages() AFTER generate_reply() and
-- AFTER send_text(). So for the entire duration of AI generation the message
-- is invisible to the dedupe check.
--
-- Production measurement: AI turns have a p50 of ~24s and 56.9% of all turns
-- exceed 20s. Meta re-delivers a webhook it has not seen acknowledged, so a
-- retry landing inside that window is NOT recognised as a duplicate — it
-- starts a second full turn and the customer receives a second reply. This is
-- customer-visible and happens on the majority of turns.
--
-- WHY wamid AND NOT CONTENT MATCHING
-- ----------------------------------
-- Meta's message id is the delivery's own identity: globally unique, stable
-- across retries of the same event, and already threaded through this codebase
-- as BrainRequest.message_id and as the claims' source_ref. Matching on
-- (text, timestamp) is a heuristic that also mis-fires when a customer
-- genuinely sends the same short word twice ("ok", "ಸರಿ"). A primary key on
-- wamid makes the database itself the arbiter: the unique violation IS the
-- duplicate signal, with no window to race inside.
--
-- WHY THIS TABLE IS MUTABLE — deliberately unlike its neighbours
-- --------------------------------------------------------------
-- bic_claims, bic_claim_retractions and bic_decision_records are append-only,
-- trigger-enforced, because they are EVIDENCE: what we believed and why. This
-- table is OPERATIONAL DELIVERY STATE — a row's whole purpose is to advance
-- ACCEPTED -> PROCESSING -> COMPLETED/FAILED. It carries no evidence, informs
-- no decision, and is never read by the Brain. So it gets no append-only
-- trigger, and that difference is a design decision rather than an omission.
--
-- NO PII, BY CONSTRUCTION. No phone, no message text, no prompt, no model
-- output. A wamid is Meta's opaque delivery identifier. failure_class is drawn
-- from the closed vocabulary already used by the Decision Record; raw
-- exception text is never stored.
--
-- NO PRUNING in this migration: no cron, no TTL, no delete path. Retention for
-- operational rows is a separate decision and is deliberately not pre-empted.

create table if not exists bic_webhook_events (
  -- Meta's own delivery identity. PRIMARY KEY is the entire mechanism: the
  -- claim is an INSERT, and a unique violation means "already claimed".
  wamid         text primary key,

  -- Article II.5 convention. NOT part of the key: a wamid is globally unique
  -- at Meta, so including tenant would let the same delivery be claimed twice.
  tenant_id     uuid not null,

  state         text not null default 'ACCEPTED'
    check (state in ('ACCEPTED', 'PROCESSING', 'COMPLETED', 'FAILED')),

  -- Closed vocabulary, mirroring bic/decision.py. Never raw exception text:
  -- an exception message can carry a phone number or a response body.
  failure_class text
    check (failure_class is null or failure_class in
           ('TIMEOUT', 'CONNECTION', 'DATABASE', 'VALUE', 'PERMISSION', 'UNKNOWN')),

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  completed_at  timestamptz,

  -- A terminal state must say when it terminated; a live one must not pretend.
  constraint bic_webhook_events_completion_pair
    check ((state in ('COMPLETED', 'FAILED')) = (completed_at is not null)),

  -- Only a FAILED row may name a failure.
  constraint bic_webhook_events_failure_pair
    check (failure_class is null or state = 'FAILED')
);

-- Finding rows stuck mid-flight: the observable symptom of a crashed or
-- timed-out invocation. Partial, because terminal rows are the vast majority.
create index if not exists bic_webhook_events_inflight_idx
  on bic_webhook_events (state, created_at)
  where state in ('ACCEPTED', 'PROCESSING');

comment on table bic_webhook_events is
  'Durable Meta webhook delivery state, keyed by wamid. Closes the retry
   window that opened because the inbound message is persisted only after AI
   generation (~24s p50). MUTABLE by design — operational state, not evidence:
   unlike bic_claims and bic_decision_records it carries no append-only
   trigger, because its rows exist to transition. Contains no PII.';

comment on column bic_webhook_events.wamid is
  'Meta''s opaque message id. PRIMARY KEY: the claim is an INSERT and the
   unique violation is the duplicate signal, so there is no read-then-write
   window for two concurrent retries to race inside.';

-- Deny by default, consistent with every other BIC table. service_role only.
alter table bic_webhook_events enable row level security;
