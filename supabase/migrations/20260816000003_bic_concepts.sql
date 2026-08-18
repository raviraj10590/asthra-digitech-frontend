-- BIC — Semantic Registry (IDD-2A)
--
-- THE VOCABULARY, AND NOTHING ELSE.
-- "It holds no customer, no order, no message — not one row of business data."
-- It answers exactly one question: what does this concept mean, and which
-- version of that meaning are we using?
--
-- NO tenant_id — DELIBERATELY, AND UNIQUELY IN THIS SYSTEM.
-- Every other BIC table carries tenant_id under Article II.5. This one does
-- not, because vocabulary is SHARED: `core.party.legal_name@1` means the same
-- thing for every tenant, and per-tenant meanings would make a fact written by
-- one tenant uninterpretable by another. Stated here so the absence reads as a
-- decision rather than an oversight.
--
-- IMMUTABILITY IS ENFORCED BY TRIGGER, NOT BY CONVENTION.
-- P2: once ACTIVE, semantic fields can never change. A rule that lives only in
-- application code is a rule that gets bypassed within a year — by a migration,
-- a console session, or a well-meaning fix. The trigger below cannot be.
--
-- THE SEMANTIC / PRESENTATIONAL SPLIT is what makes P2 usable. Without it
-- either nothing can be fixed (a typo is frozen forever) or everything drifts
-- (meaning changes under cover of "wording"). IDD-2A's test: could a reasonable
-- person, reading only this field, draw a different conclusion about which
-- real-world facts satisfy the predicate? If yes it is semantic.
--
-- REGISTRY IS DATA, NOT CODE (P5). Adding a predicate is one INSERT. If it
-- required a deployment, the multi-industry thesis would already be dead.

create table if not exists bic_concepts (
  -- ── SEMANTIC IDENTITY — frozen at ACTIVE ────────────────────────────────
  -- P1: <namespace>.<concept>@<version>. Namespacing is what lets a package
  -- add mfg.unit without colliding with realestate.unit.
  namespace     text not null check (namespace ~ '^[a-z][a-z0-9_.]*$'),
  concept       text not null check (concept   ~ '^[a-z][a-z0-9_]*$'),
  -- P3/5.1: monotonic integers, never reused, never renumbered. @1 and @2 are
  -- DIFFERENT concepts that share a name — not compatible revisions.
  version       integer not null check (version >= 1),

  -- IDD-2A §3.2. Seven categories, each earning its place by needing DIFFERENT
  -- MACHINERY, not by describing a different subject.
  category      text not null check (category in (
                  'IDENTIFYING', 'DESCRIPTIVE', 'STATE', 'TEMPORAL',
                  'QUANTITATIVE', 'CLASSIFYING', 'DERIVED')),

  -- {"type":"text"} | {"type":"enum","values":[…]} | {"type":"number",…}
  value_space   jsonb not null,
  unit          text,
  cardinality   text not null default 'single'
                  check (cardinality in ('single', 'multi')),
  -- §3.5: where "static vs operational knowledge" correctly lives — a
  -- per-predicate attribute, not a separate store. A product price is `fast`
  -- in retail and `slow` in manufacturing. One registry, per-industry tuning.
  volatility_class text not null default 'slow'
                  check (volatility_class in ('static', 'slow', 'fast', 'live')),
  applies_to    text[] not null default '{}',

  -- ── LIFECYCLE (§5.2) ────────────────────────────────────────────────────
  -- RETIRED NEVER MEANS UNREADABLE. Retirement removes the ability to CREATE,
  -- never the ability to INTERPRET. A hospital retiring a predicate must still
  -- read ten years of assertions written under it.
  lifecycle     text not null default 'DRAFT'
                  check (lifecycle in ('DRAFT', 'ACTIVE', 'DEPRECATED', 'RETIRED')),

  -- ── SUPERSESSION (§5.3) ─────────────────────────────────────────────────
  -- The field that prevents silent corruption. Without a declared relation a
  -- reader assumes equivalence and silently corrupts every historical
  -- analysis. Columns ship now because retrofitting them is expensive; the
  -- transitions that populate them are deferred until a @2 exists.
  replaced_by_version integer,
  compatibility text check (compatibility in (
                  'EQUIVALENT', 'NARROWER', 'BROADER', 'OVERLAPPING', 'UNRELATED')),

  -- ── PRESENTATIONAL — editable forever, in every state ───────────────────
  label         text not null,
  description   text,
  examples      jsonb,

  -- ── AUDIT (V2: every semantic change names the human who approved it) ───
  activated_at  timestamptz,
  activated_by  text,
  created_at    timestamptz not null default now(),

  primary key (namespace, concept, version)
);

-- §3.5: "unit is mandatory for QUANTITATIVE; changing it silently corrupts
-- every comparison." Enforced in the schema so a unitless kva_rating cannot
-- be activated by any path.
alter table bic_concepts
  drop constraint if exists bic_concepts_quantitative_unit;
alter table bic_concepts
  add constraint bic_concepts_quantitative_unit
  check (category <> 'QUANTITATIVE' or unit is not null);

-- §5.3: a replacement without a declared compatibility relation is exactly the
-- silent-corruption case. Both or neither.
alter table bic_concepts
  drop constraint if exists bic_concepts_supersession_pair;
alter table bic_concepts
  add constraint bic_concepts_supersession_pair
  check ((replaced_by_version is null) = (compatibility is null));

-- An ACTIVE concept must record who activated it and when (V2).
alter table bic_concepts
  drop constraint if exists bic_concepts_activation_audit;
alter table bic_concepts
  add constraint bic_concepts_activation_audit
  check (lifecycle = 'DRAFT'
         or (activated_at is not null and activated_by is not null));

create index if not exists bic_concepts_lookup_idx
  on bic_concepts (namespace, concept, version desc);
create index if not exists bic_concepts_lifecycle_idx
  on bic_concepts (lifecycle);

-- ── P2 ENFORCED STRUCTURALLY ───────────────────────────────────────────────
-- Semantic fields are write-once at ACTIVE. Presentational fields stay
-- editable in every state, forever — fixing a Kannada label must never mint a
-- version; changing what credit_limit MEANS must always mint one.
--
-- Lifecycle may still advance (ACTIVE→DEPRECATED→RETIRED) and supersession may
-- still be declared, because neither alters what the concept MEANS.
create or replace function bic_concepts_freeze_semantics()
returns trigger
language plpgsql
as $$
begin
  if old.lifecycle <> 'DRAFT' then
    if new.namespace        is distinct from old.namespace
    or new.concept          is distinct from old.concept
    or new.version          is distinct from old.version
    or new.category         is distinct from old.category
    or new.value_space      is distinct from old.value_space
    or new.unit             is distinct from old.unit
    or new.cardinality      is distinct from old.cardinality
    or new.volatility_class is distinct from old.volatility_class
    or new.applies_to       is distinct from old.applies_to then
      raise exception
        'semantic fields are frozen once ACTIVE (%.%@%) — create a new version instead',
        old.namespace, old.concept, old.version
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists bic_concepts_freeze on bic_concepts;
create trigger bic_concepts_freeze
  before update on bic_concepts
  for each row execute function bic_concepts_freeze_semantics();

-- Vocabulary is not customer data: it contains no subject, no value, no PII.
-- RLS is still enabled so reads are deliberate rather than accidental; no
-- policy exists, so only service_role (which bypasses RLS) may touch it.
alter table bic_concepts enable row level security;

comment on table bic_concepts is
  'SEMANTIC REGISTRY (IDD-2A). The vocabulary — no business data, no PII.
   Shared across tenants BY DESIGN: no tenant_id, because a meaning must not
   differ per tenant. Semantic fields frozen at ACTIVE by trigger; presentational
   fields editable forever. RETIRED means no new assertions, never unreadable.';
