-- BIC 2B — Commitment. The one persistent record of what the business owes.
--
-- WHY THIS TABLE AND NOT A DEFERRED-WORK QUEUE
-- --------------------------------------------
-- IDD-3B §1.2 types goals by lifespan and sends the persistent ones here:
--
--   "Persistent goals ARE Commitments. A goal the business holds itself to is
--    a commitment with the business as counterparty. One concept, two vantage
--    points — NO DUPLICATE STORE, NO RECONCILIATION."
--
-- A queue table would be that duplicate store, and within a year there would
-- be two answers to "what do we still owe this customer?" that disagree.
--
-- WHY TWO TABLES
-- --------------
-- 2B's stated purpose is that "what have we promised and are we about to miss
-- it?" is answerable "without a cross-module join no module owns" — a
-- CURRENT-STATE question, not a fold over an event stream. So the commitment
-- row carries current state and transitions in place, exactly as bic_parties
-- does ("resolution_state DOES change (that is its lifecycle)").
--
-- But 2B also requires that "`missed` is recorded, never deleted" (criterion
-- 16) and that renegotiation preserve history. A bare mutable row cannot
-- promise that, so every transition is ALSO written to an append-only,
-- trigger-protected companion — the same shape bic_claim_retractions uses to
-- record an act separately from the thing acted upon.
--
--   current state  → one indexed read
--   history        → immutable, even to service_role
--
-- WHAT IS RULED RATHER THAN READ
-- ------------------------------
-- 2B left four schema questions unanswered; they were ruled on 2026-08-25 and
-- are marked OWNER RULING below. Everything else is 2B verbatim.

create table if not exists bic_commitments (
  -- 2B: "Every object's identity is a meaningless knowledge_id."
  commitment_id  uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null,

  -- OWNER RULING: nullable. `subject` is the OBJECT of the promise (the
  -- invoice chased, the enquiry answered) — not the counterparty, or the
  -- identifying tuple would read party + party + due_on. 2B lists it as
  -- identifying but omits it from Required, so a promise about nothing but
  -- the party itself ("call them back") must remain representable.
  subject        uuid,

  -- 2B Required. The counterparty: a promise is made TO someone.
  party          uuid not null references bic_parties(knowledge_id),
  obligation     text not null,
  due_on         timestamptz not null,

  -- 2B: "Every Commitment has an accountable owner (an AGENT). Never null."
  -- An opaque AGENT reference — never a phone, an email or a name.
  owner          text not null,

  lifecycle      text not null default 'made'
    check (lifecycle in ('made','in_progress','met','missed','waived',
                         'renegotiated')),

  -- ONE attribution edge back to the turn that created the obligation.
  -- Deliberately NOT a foreign key, for the same reason bic_outcome_records
  -- gives: a commitment must stay recordable when the decision that created
  -- it has been pruned by retention, and a dangling reference is more useful
  -- than a refused write.
  decision_ref   text,
  goal_ref       text,

  -- 2B Optional, exactly. Nothing speculative.
  penalty        text,
  source         text,
  criticality    text,

  -- OWNER RULING: renegotiation closes this row and NAMES its successor,
  -- mirroring 2B's rule for Document ("superseded requires naming the
  -- successor. Revision is modelled; deletion is not."). One direction only:
  -- a back-pointer would be a second path to one fact, and two paths to the
  -- same fact always diverge (2B §4.3).
  superseded_by  uuid references bic_commitments(commitment_id),

  created_at     timestamptz not null default now(),

  -- A promise cannot be made already overdue.
  constraint bic_commitment_due_after_created check (due_on >= created_at),
  -- A successor may only be named by the state that produces one.
  constraint bic_commitment_successor_only_when_renegotiated
    check (superseded_by is null or lifecycle = 'renegotiated')
);

-- OWNER RULING: the 2B identifying tuple, tenant-scoped, with NULLS NOT
-- DISTINCT so two subject-less promises to the same party with the same
-- deadline are ONE commitment. Without it Postgres treats NULLs as distinct
-- and the tuple stops deduplicating exactly where duplicates are likeliest.
create unique index if not exists bic_commitments_identity_idx
  on bic_commitments (tenant_id, subject, party, due_on) nulls not distinct;

create index if not exists bic_commitments_party_idx
  on bic_commitments (tenant_id, party);
-- Supports the only question 2B says this object exists to answer:
-- "what have we promised and are we about to miss it?"
create index if not exists bic_commitments_due_idx
  on bic_commitments (tenant_id, due_on)
  where lifecycle in ('made','in_progress');
create index if not exists bic_commitments_decision_idx
  on bic_commitments (tenant_id, decision_ref);


-- ── Append-only history ────────────────────────────────────────────────────
-- OWNER RULING: current-state row + append-only transition history.
create table if not exists bic_commitment_transitions (
  transition_id uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null,
  commitment_id uuid not null references bic_commitments(commitment_id),

  from_state    text not null
    check (from_state in ('made','in_progress','met','missed','waived',
                          'renegotiated')),
  to_state      text not null
    check (to_state in ('made','in_progress','met','missed','waived',
                        'renegotiated')),

  -- An unexplained miss teaches nothing, and "missed commitments are the
  -- reliability signal" is the reason this object exists.
  reason        text not null,

  -- OWNER RULING: the approver lives HERE, not on the commitment. 2B's
  -- diagram requires an approver for `waived` but never lists one among the
  -- commitment's fields — because it is a property of the ACT, not of the
  -- promise. Same shape as bic_claim_retractions.retracted_by. Bounded,
  -- non-PII: an AGENT reference.
  actor         text,

  occurred_at   timestamptz not null default now(),

  -- The waiver requirement, enforced by the database rather than by manners.
  constraint bic_commitment_waiver_needs_an_actor
    check (to_state <> 'waived' or actor is not null)
);

create index if not exists bic_commitment_transitions_idx
  on bic_commitment_transitions (tenant_id, commitment_id, occurred_at);


-- ── Mutation policy ────────────────────────────────────────────────────────
-- The commitment row transitions in place (bic_parties precedent), but only
-- its lifecycle and successor may ever move. Everything else is frozen at
-- insert: a deadline changes by RENEGOTIATION, which closes one promise and
-- opens another, never by an UPDATE that quietly rewrites what was promised.
create or replace function bic_commitment_freeze()
returns trigger language plpgsql as $$
begin
  if new.tenant_id  is distinct from old.tenant_id
  or new.subject    is distinct from old.subject
  or new.party      is distinct from old.party
  or new.obligation is distinct from old.obligation
  or new.due_on     is distinct from old.due_on
  or new.owner      is distinct from old.owner
  or new.decision_ref is distinct from old.decision_ref
  or new.created_at is distinct from old.created_at then
    raise exception
      'bic_commitments: only lifecycle and superseded_by may change; % is frozen at insert (IDD-2B)',
      'the promise itself';
  end if;
  return new;
end $$;

drop trigger if exists bic_commitments_freeze on bic_commitments;
create trigger bic_commitments_freeze
  before update on bic_commitments
  for each row execute function bic_commitment_freeze();

-- 2B criterion 16: "missed recorded and retained; not deleted."
create or replace function bic_commitment_no_delete()
returns trigger language plpgsql as $$
begin
  raise exception
    'bic_commitments is never deleted from — missed commitments are the reliability signal (IDD-2B)';
end $$;

drop trigger if exists bic_commitments_no_delete on bic_commitments;
create trigger bic_commitments_no_delete
  before delete on bic_commitments
  for each row execute function bic_commitment_no_delete();

-- History is evidence, and evidence is append-only — enforced by trigger, so
-- even a direct console session with service_role cannot rewrite it.
drop trigger if exists bic_commitment_transitions_no_mutation
  on bic_commitment_transitions;
create trigger bic_commitment_transitions_no_mutation
  before update or delete on bic_commitment_transitions
  for each row execute function bic_reject_mutation();

alter table bic_commitments enable row level security;
alter table bic_commitment_transitions enable row level security;

comment on table bic_commitments is
  'IDD-2B Commitment: any promise with a party, obligation and deadline. The
   single persistent record of what the business owes — 3B §1.2 routes
   persistent goals here precisely so no second deferred-work store exists.
   Transitions in place; every transition is also appended to
   bic_commitment_transitions, which cannot be rewritten.';

comment on column bic_commitments.owner is
  'IDD-2B: an accountable AGENT, never null. An opaque reference — never a
   phone, an email or a name.';

comment on column bic_commitments.superseded_by is
  'Set only when lifecycle = renegotiated: the new commitment that replaced
   this one. One direction; the reverse is a query, not a column.';


-- ── The atomic transition ──────────────────────────────────────────────────
-- A lifecycle move is TWO writes: the commitment row and its history row.
-- PostgREST performs `update` and `insert` as independent HTTP calls with no
-- transaction between them, so doing it from the client leaves both halves
-- reachable alone. The bad half is a lifecycle change with NO audit trail —
-- precisely what the append-only history exists to prevent.
--
-- A function body is one transaction: every RAISE below rolls back the whole
-- thing, so a rejected transition leaves the row and the history untouched.
--
-- The Python domain (bic/commitment.py) remains authoritative for transition
-- semantics. These checks are not a second domain model; they are the subset
-- that must hold even if the caller is wrong, buggy, or someone at a console.
create or replace function bic_commitment_transition(
  p_tenant_id     uuid,
  p_commitment_id uuid,
  p_to_state      text,
  p_reason        text,
  p_actor         text default null,
  p_successor     uuid default null
) returns jsonb
language plpgsql
as $$
declare
  v_row       bic_commitments%rowtype;
  v_from      text;
  v_successor bic_commitments%rowtype;
begin
  if p_reason is null or btrim(p_reason) = '' then
    raise exception 'a transition requires a reason';
  end if;

  -- TENANT SCOPING IS THE LOOKUP, not a filter applied afterwards: a foreign
  -- tenant finds nothing, which is indistinguishable from "no such row" and
  -- therefore discloses nothing. FOR UPDATE serialises concurrent callers so
  -- two transitions cannot interleave on one commitment.
  select * into v_row
  from bic_commitments
  where commitment_id = p_commitment_id and tenant_id = p_tenant_id
  for update;

  if not found then
    raise exception 'no such commitment in this tenant';
  end if;

  v_from := v_row.lifecycle;

  -- No terminal reopen. 2B's lifecycle has no arrow out of a terminal state;
  -- a renegotiated promise is a NEW commitment, never a revived one.
  if v_from in ('met','missed','waived','renegotiated') then
    raise exception 'commitment is already terminal (%): it cannot reopen', v_from;
  end if;

  -- The legal moves, mirroring bic/commitment.py's _ALLOWED. `met` is
  -- reachable only through in_progress; `renegotiated` only from `made`;
  -- `waived` from either active state (owner ruling 2026-08-25).
  if not (
       (v_from = 'made'        and p_to_state in ('in_progress','missed','waived','renegotiated'))
    or (v_from = 'in_progress' and p_to_state in ('met','missed','waived'))
  ) then
    raise exception 'illegal transition % -> %', v_from, p_to_state;
  end if;

  -- 2B's diagram: waived "(requires approver)". Enforced here as well as by
  -- the transitions CHECK, so the rule holds even for a direct INSERT.
  if p_to_state = 'waived' and (p_actor is null or btrim(p_actor) = '') then
    raise exception 'waiving a commitment requires an actor';
  end if;

  if p_to_state = 'renegotiated' then
    if p_successor is null then
      raise exception 'renegotiation must name its successor';
    end if;
    if p_successor = p_commitment_id then
      raise exception 'a commitment cannot supersede itself';
    end if;
    select * into v_successor
    from bic_commitments
    where commitment_id = p_successor and tenant_id = p_tenant_id;
    if not found then
      raise exception 'successor does not exist in this tenant';
    end if;
    -- A successor is a promise not yet worked: anything else means the
    -- caller pointed at an unrelated or already-closed commitment.
    if v_successor.lifecycle <> 'made' then
      raise exception 'successor must be a newly made commitment, not %',
        v_successor.lifecycle;
    end if;
  elsif p_successor is not null then
    raise exception 'only a renegotiation may name a successor';
  end if;

  -- WRITE 1. Only lifecycle and superseded_by move; the freeze trigger
  -- rejects any attempt to touch the promise itself.
  update bic_commitments
     set lifecycle = p_to_state,
         superseded_by = case when p_to_state = 'renegotiated'
                              then p_successor else superseded_by end
   where commitment_id = p_commitment_id and tenant_id = p_tenant_id
   returning * into v_row;

  -- WRITE 2. Exactly one history row, in the same transaction as write 1.
  insert into bic_commitment_transitions
    (tenant_id, commitment_id, from_state, to_state, reason, actor)
  values
    (p_tenant_id, p_commitment_id, v_from, p_to_state, p_reason, p_actor);

  return to_jsonb(v_row);
end;
$$;

-- Backend-only, exactly as the retention functions are. A commitment must
-- never be transitionable by an anon key or by anything a model can reach.
revoke all on function bic_commitment_transition(uuid, uuid, text, text, text, uuid)
  from public, anon, authenticated;

comment on function bic_commitment_transition(uuid, uuid, text, text, text, uuid) is
  'The ONLY way a commitment lifecycle moves. Updates the row and appends its
   history row in ONE transaction, so a state change can never exist without
   the audit trail that explains it. Any validation failure rolls back both.';
