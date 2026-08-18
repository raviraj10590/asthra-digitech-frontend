-- BIC — Knowledge Assertions: ValueClaims (IDD-2C)
--
-- "Assertions are the only place facts live. Everything else is a view."
--
-- APPEND-ONLY. There is no UPDATE path. Corrections are new claims;
-- errors are retractions; neither edits a byte of what was written.
--
-- ── WHAT IS DELIBERATELY ABSENT (IDD-2C §2.3) ─────────────────────────────
-- Each omission is load-bearing. A field that implies mutation will eventually
-- be mutated.
--
--   status         DERIVED on read (C1). A stored status is a second source of
--                  truth that drifts from the claims it describes — silently.
--   superseded_by  same problem: writing it mutates a record declared immutable.
--   updated_at     claims are never updated; its presence would invite it.
--   last_verified  DERIVED (C2). Re-verification APPENDS a new claim with a
--                  fresh observed_at. Three sources confirming a GSTIN is three
--                  claims and a strong signal — richer than one mutable field.
--   category       INHERITED from the predicate (C4). A parallel taxonomy would
--                  drift from 2A within a year.
--   is_current     derived from valid_until and supersession.
--
-- Post-commit state is computed, never stored:
--   SUPERSEDED ⟺ a later claim exists for the same (subject, predicate)
--   EXPIRED    ⟺ valid_until < as_of
--   RETRACTED  ⟺ a retraction record references it
--   ACTIVE     ⟺ none of the above
--
-- ── BITEMPORALITY (§7.1) — CANNOT BE RETROFITTED ──────────────────────────
--   valid_from / valid_until   when it was true IN THE WORLD
--   observed_at                when WE learned it  ← "what did we BELIEVE in
--                              March?" is the question every dispute becomes
--   recorded_at                when the row entered the store; distinct from
--                              observed_at when backfilling history
--
-- ── CONFIDENCE CAPS IN SQL, NOT APPLICATION CODE (§6.1) ───────────────────
-- Article II.6. A model can never raise its own confidence. Enforced here so
-- the cap holds even if the application is bypassed entirely — a cap that
-- lives only in Python is a cap that a console session ignores.

create table if not exists bic_claims (
  claim_id        uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null,

  -- Always a knowledge_id, never a business key (2B §V3). The foreign key is
  -- declared here rather than added later BECAUSE this migration has never
  -- been applied: establishing it now costs one line, while adding it after
  -- deployment would mean validating it against live rows that may already
  -- point nowhere. A subject column with no referent is exactly the shape of
  -- the Phase 1A failure this stack exists to avoid.
  subject         uuid not null references bic_parties(knowledge_id),

  -- The registered meaning INCLUDING its version. Without the version a 2036
  -- reader silently reinterprets a 2026 fact — the most insidious failure
  -- available to a system like this.
  predicate_ns      text not null,
  predicate_concept text not null,
  semantic_version  integer not null,

  value           text not null,

  -- ── PROVENANCE (§6) ─────────────────────────────────────────────────────
  source          text not null,
  -- 0 authoritative system of record … 5 self-reported. Tier is the CAP on
  -- confidence, not a hint. Tier is per FACT, not per system: Tally is
  -- authoritative for invoice_amount and merely a copy for customer_phone.
  provenance_tier smallint not null check (provenance_tier between 0 and 5),
  -- V3: never null. An unattributable fact is a rumour.
  asserted_by     text not null,
  source_ref      text,

  confidence      numeric(3,2) not null check (confidence between 0 and 1),

  -- ── TIME ────────────────────────────────────────────────────────────────
  valid_from      timestamptz not null,
  valid_until     timestamptz,
  observed_at     timestamptz not null,
  recorded_at     timestamptz not null default now(),

  -- ── COMMIT (§3.1) ───────────────────────────────────────────────────────
  -- Pre-commit states are STORED and mutable, because nothing depends on them
  -- yet. Post-commit states are derived. The boundary is the whole point of C1.
  -- REJECTED rows are retained with their reason: a rejection rate per source
  -- is a quality metric.
  pre_commit_state text not null default 'VALIDATED'
                    check (pre_commit_state in ('PROPOSED', 'VALIDATED', 'REJECTED'))
);

-- §6.1 tier caps. Six tiers, six ceilings, enforced by the database.
alter table bic_claims drop constraint if exists bic_claims_tier_cap;
alter table bic_claims add constraint bic_claims_tier_cap check (
  (provenance_tier = 0 and confidence <= 1.00) or
  (provenance_tier = 1 and confidence <= 0.90) or
  (provenance_tier = 2 and confidence <= 0.80) or
  (provenance_tier = 3 and confidence <= 0.70) or
  (provenance_tier = 4 and confidence <= 0.60) or
  (provenance_tier = 5 and confidence <= 0.50)
);

-- V6: valid_until >= valid_from. A validity interval that ends before it
-- begins is not history, it is corruption.
alter table bic_claims drop constraint if exists bic_claims_validity_order;
alter table bic_claims add constraint bic_claims_validity_order
  check (valid_until is null or valid_until >= valid_from);

create index if not exists bic_claims_subject_idx
  on bic_claims (tenant_id, subject, predicate_ns, predicate_concept, valid_from desc);
create index if not exists bic_claims_observed_idx
  on bic_claims (tenant_id, observed_at desc);

alter table bic_claims enable row level security;

comment on table bic_claims is
  'KNOWLEDGE ASSERTIONS — ValueClaims (IDD-2C). APPEND-ONLY: no update path,
   no stored status, no updated_at. Corrections are new claims; errors are
   retractions. Bitemporal: valid_from/until is world time, observed_at is
   system time. Confidence capped by provenance tier in SQL.';


-- ── RETRACTION IS A RECORD, NEVER A DELETE (§3.3) ─────────────────────────
-- "We should never have asserted this" — an extraction bug, a wrong source, a
-- keying error. Distinct from supersession, which means "this was true and no
-- longer is."
--
-- Deleting the claim would destroy the answer to "why did we decide that in
-- March?" — because the decision WAS made on the retracted fact, and an audit
-- that cannot reproduce a past decision is not an audit.
--
-- Retracted claims are excluded from current truth, INCLUDED in historical
-- replay. That asymmetry is the entire reason this is a separate table.
create table if not exists bic_claim_retractions (
  retraction_id uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null,
  claim_id      uuid not null references bic_claims(claim_id),
  reason        text not null,
  retracted_by  text not null,
  retracted_at  timestamptz not null default now()
);

create index if not exists bic_claim_retractions_claim_idx
  on bic_claim_retractions (claim_id);

alter table bic_claim_retractions enable row level security;

comment on table bic_claim_retractions is
  'Append-only retractions (IDD-2C §3.3). A retraction NEVER deletes or mutates
   the original claim, which stays readable forever. Retracted claims are
   excluded from current truth and included in historical replay.';


-- ── APPEND-ONLY, ENFORCED BY THE DATABASE ─────────────────────────────────
-- IDD-2C V1: "Committed claims are append-only; NO UPDATE PATH EXISTS."
--
-- Application-level discipline is not enough for this. Python code that
-- declines to import `update` protects against ACCIDENT; a trigger protects
-- against INTENT — a console session, a migration, a future contributor who
-- has not read V1. The whole value of an immutable record is that nobody can
-- quietly change it, including us.
--
-- DELETE is blocked for the same reason: retraction is a RECORD, never a
-- delete (§3.3). Deleting a claim would destroy the answer to "why did we
-- decide that in March?" — the decision was made ON that fact, and an audit
-- that cannot reproduce a past decision is not an audit.
--
-- Note this binds service_role too: RLS is bypassed by service_role, triggers
-- are not. That asymmetry is exactly what makes this worth doing.
create or replace function bic_reject_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception
    '% is append-only: % rejected. Corrections are new rows; errors are retractions.',
    tg_table_name, tg_op
    using errcode = 'restrict_violation';
end;
$$;

revoke all on function bic_reject_mutation() from public, anon, authenticated;

drop trigger if exists bic_claims_no_mutation on bic_claims;
create trigger bic_claims_no_mutation
  before update or delete on bic_claims
  for each row execute function bic_reject_mutation();

drop trigger if exists bic_claim_retractions_no_mutation on bic_claim_retractions;
create trigger bic_claim_retractions_no_mutation
  before update or delete on bic_claim_retractions
  for each row execute function bic_reject_mutation();
