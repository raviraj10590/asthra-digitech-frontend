-- BIC 2I — Outcome Intelligence. Observation storage only.
--
-- THE ONE IDEA (IDD-2I §0.2)
-- --------------------------
--   "Record what happened. Derive whether it was good."
--
-- Record SUCCESS and you bake in a 2026 definition of success. When the
-- margin target changes in 2028, every historical outcome silently means
-- something different, and every lesson built on them is quietly wrong.
--
-- SO THERE IS NO SUCCESS COLUMN IN THIS TABLE, AND THERE NEVER WILL BE.
-- Evaluation is computed by bic/outcomes.evaluate() against a named,
-- VERSIONED yardstick and returned to the caller — never persisted. That
-- absence is invariant I1, enforced by the schema rather than by discipline.
--
-- WHY NOT bic_claims
-- ------------------
-- A claim asserts what is believed TRUE, bitemporally. An outcome observes
-- what the world DID, and may be revised by evidence that arrives months
-- later. Folding one into the other would let an unconfirmed observation
-- become knowledge — which §3.3 forbids, because a lesson built on
-- unconfirmed signal will already have influenced decisions by the time
-- reality arrives. Separate tables, separate lifecycles, no foreign key
-- between them.
--
-- EXECUTION IS NOT OUTCOME (I2)
-- -----------------------------
-- bic_tool_invocations and bic_webhook_events record whether OUR SYSTEM
-- worked. "Quotation sent, HTTP 200" is an execution result; "quotation
-- accepted on day 12" is an outcome. Nothing in this table is written from
-- an HTTP status.
--
-- APPEND-ONLY (I3)
-- ----------------
-- Revision APPENDS a new row pointing at the one it revises; it never edits.
-- The trigger below blocks UPDATE and DELETE for every caller including
-- service_role, which bypasses RLS but not triggers. "What did we believe
-- about this outcome in March?" must stay answerable — that question is what
-- separates *the decision was wrong* from *the outcome was later revised*.

create table if not exists bic_outcome_records (
  outcome_id        uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null,

  -- 2B knowledge_id. Meaningless and permanent, so no PII lands here.
  subject           uuid not null,

  -- I4: EXACTLY ONE attribution edge. Not a FK to bic_decision_records,
  -- deliberately — an outcome must remain recordable for a decision whose
  -- record was pruned by retention, and a dangling outcome is more useful
  -- than a refused write. §4.1: everything else is reachable by traversal,
  -- so there is no customer_id or project_id column here. Those would be
  -- shortcut edges (2B §4.3) and two paths to one fact always diverge.
  decision_ref      text not null,

  -- What KIND of outcome this window watches. Generic: the vertical meaning
  -- lives in goal/yardstick definitions, never in storage (§10, Step 12).
  outcome_kind      text not null,

  -- ── ① EXPECTATION, created at DECISION time (I6, §3.1) ────────────────
  -- "An outcome that only exists once something is observed can never record
  -- TIMED_OUT — because nothing is watching." NO_RESPONSE is the most common
  -- outcome in a small business, and this is the only way to see it.
  expected_state    text
    check (expected_state is null or expected_state in
           ('RESOLVED','DECLINED','CANCELLED','EXPIRED','NO_RESPONSE','SUPERSEDED')),
  window_seconds    integer not null check (window_seconds > 0),
  window_opened_at  timestamptz not null,
  window_closes_at  timestamptz not null,

  -- ── ② OBSERVATION — what the world DID (§2.2) ─────────────────────────
  -- Null until something is observed. Deliberately null rather than a
  -- placeholder state: a placeholder is indistinguishable from an
  -- observation, which is the whole failure this table exists to avoid.
  --
  -- NOTE WHAT IS ABSENT: SUCCESS, FAILURE, PARTIAL. Those are evaluations
  -- (§2.1), not observations, and they do not belong in any column.
  observed_state    text
    check (observed_state is null or observed_state in
           ('RESOLVED','DECLINED','CANCELLED','EXPIRED','NO_RESPONSE','SUPERSEDED')),

  -- §2.3 — how well we know. ORTHOGONAL to state; every outcome carries both.
  -- I7: TIMED_OUT means we watched and nothing came. UNOBSERVABLE means we
  -- never watched. A model that cannot tell them apart learns from a sample
  -- biased toward counterparties who bother to reply.
  observation_status text
    check (observation_status is null or observation_status in
           ('OBSERVED','INFERRED','REPORTED','TIMED_OUT','UNOBSERVABLE')),
  observed_at       timestamptz,

  -- §2.6 — delay describes the PATH, state describes the destination. A
  -- payment 40 days late that arrives is RESOLVED with a large variance; one
  -- that never arrives is TIMED_OUT. As a state, "delayed" would be
  -- permanently ambiguous, because a delayed outcome is still in flight.
  elapsed_seconds      integer,
  variance_vs_expected numeric,
  late_beyond_window   boolean not null default false,

  -- ── ③ LIFECYCLE (§3) ─────────────────────────────────────────────────
  -- Stored as the furthest stage DECLARED. The effective lifecycle is
  -- DERIVED at read time by bic/outcomes.current(), because a stored value
  -- goes stale the moment a window closes and nothing notices — the same
  -- reason 2C C1 forbids storing claim status.
  lifecycle         text not null default 'EXPECTED'
    check (lifecycle in ('EXPECTED','OBSERVED','CONFIRMED','CLOSED',
                         'REVISED','RETIRED','RETRACTED')),

  -- ── The 2H link: REFERENCES, not a copy of the packet ────────────────
  -- §4.1 keeps the packet reachable through the decision. Duplicating it
  -- here would create a second copy that drifts from the first.
  goal_ref            text,
  risk_tier           smallint check (risk_tier is null or risk_tier between 1 and 4),
  sufficiency_verdict text,
  evidence_refs       text[] not null default '{}',

  -- §4.2 — contributing factors are NOT attribution: zero or many,
  -- associative, and they may never justify an action alone. Recording them
  -- unquantified is still better than omitting them, because otherwise the
  -- model silently attributes their effect to the decision (§4.3).
  contributing_factors text[] not null default '{}',

  -- §3.4 — revision appends and points back. The original stays readable.
  revises           uuid references bic_outcome_records(outcome_id),

  -- Bounded, non-PII. Never a phone, never message text.
  observed_by       text,
  reason            text,
  recorded_at       timestamptz not null default now(),

  constraint bic_outcome_window_order check (window_closes_at >= window_opened_at),
  -- An observation needs both halves or neither: a state without a status
  -- hides how well we know it, and a status without a state knows nothing.
  constraint bic_outcome_observation_paired check (
    (observed_state is null and observation_status is null)
    or (observed_state is not null and observation_status is not null))
);

create index if not exists bic_outcome_decision_idx
  on bic_outcome_records (tenant_id, decision_ref, recorded_at);
create index if not exists bic_outcome_subject_idx
  on bic_outcome_records (tenant_id, subject);
-- Supports the timeout sweep: find open windows that have closed.
create index if not exists bic_outcome_open_window_idx
  on bic_outcome_records (tenant_id, window_closes_at)
  where lifecycle = 'EXPECTED';


-- Retraction is its own append-only record, mirroring 2C: the withdrawal is
-- itself auditable, and the original observation stays explicable forever.
create table if not exists bic_outcome_retractions (
  retraction_id uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null,
  outcome_id    uuid not null references bic_outcome_records(outcome_id),
  reason        text not null,
  retracted_by  text not null,
  retracted_at  timestamptz not null default now()
);

create index if not exists bic_outcome_retractions_idx
  on bic_outcome_retractions (tenant_id, outcome_id);


-- ── I3 enforced by the database, not by discipline ────────────────────────
drop trigger if exists bic_outcome_records_no_mutation on bic_outcome_records;
create trigger bic_outcome_records_no_mutation
  before update or delete on bic_outcome_records
  for each row execute function bic_reject_mutation();

drop trigger if exists bic_outcome_retractions_no_mutation on bic_outcome_retractions;
create trigger bic_outcome_retractions_no_mutation
  before update or delete on bic_outcome_retractions
  for each row execute function bic_reject_mutation();

alter table bic_outcome_records enable row level security;
alter table bic_outcome_retractions enable row level security;

comment on table bic_outcome_records is
  'IDD-2I Outcome Intelligence. Observations of what the WORLD did, never
   execution results (I2) and never knowledge claims. Append-only (I3):
   revision appends a row pointing at what it revises. There is deliberately
   NO success/verdict column — evaluation is derived against a versioned
   yardstick and never stored (I1), so changing the definition of good
   re-judges history instead of rewriting it.';

comment on column bic_outcome_records.decision_ref is
  'IDD-2I I4: exactly one attribution edge. I5: this records which decision
   PRECEDED the outcome — correlation, never causation.';

comment on column bic_outcome_records.observation_status is
  'IDD-2I I7: TIMED_OUT (we watched, nothing came) is DATA and is distinct
   from UNOBSERVABLE (we never had a means to learn it).';
