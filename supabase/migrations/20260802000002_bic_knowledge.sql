-- BIC v1.0 — Slice 1A · Knowledge Engine core
-- Constitution: Article IV (Data Model), Article V (Retrieval), Article II.5/II.6
--
-- Three tables: entities (what knowledge is ABOUT), facts (atomic scored
-- statements), edges (relationships between entities).

-- pgvector: reserved now, unused until retrieval outgrows lexical search.
-- Article IV: "enabling semantic retrieval later is a backfill, not a
-- migration." Adding a vector column to a large table later is expensive;
-- adding it empty now is free.
create extension if not exists vector with schema extensions;

-- Trigram search powers Article V candidate generation (lexical stage). Chosen
-- over embeddings for launch: zero API calls, works for Kannada and English.
create extension if not exists pg_trgm with schema extensions;

-- Resolve extension objects (gin_trgm_ops, vector) without hard-coding a
-- schema. `create extension ... if not exists` is a no-op when the extension
-- already exists in a DIFFERENT schema, so qualifying as extensions.* breaks
-- on databases where these were installed earlier elsewhere — which is exactly
-- what happened here. search_path resolves it wherever it actually lives.
set local search_path = public, extensions;

-- ── Entities ───────────────────────────────────────────────────────────────
create table if not exists bic_entities (
  id          uuid primary key default gen_random_uuid(),

  -- Article II.5: tenancy is tenant_id, NOT the author. Per-person scoping
  -- fragments a company brain — staff and owner must share one knowledge base.
  -- Also the declared partition key (Article IV): present from row one so
  -- partitioning can be introduced later without a rewrite.
  tenant_id   uuid not null,
  domain      text not null default 'general',

  type        text not null references bic_entity_types(code),
  name        text not null,
  name_key    text not null,               -- normalised; see bic_normalise_key
  aliases     text[] not null default '{}',
  status      text not null default 'active'
                check (status in ('active', 'dormant', 'closed', 'merged')),
  merged_into uuid references bic_entities(id),  -- entity resolution (review C5)

  external_ref jsonb not null default '{}', -- e.g. {"crm_client_id": "..."}
                                            -- Article: CRM stays source of truth;
                                            -- we store a REFERENCE, never a copy.
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  constraint bic_entities_unique_name unique (tenant_id, type, name_key)
);

create index if not exists bic_entities_tenant_idx  on bic_entities (tenant_id, status);
create index if not exists bic_entities_name_trgm   on bic_entities using gin (name_key gin_trgm_ops);
create index if not exists bic_entities_domain_idx  on bic_entities (tenant_id, domain);

-- ── Facts ──────────────────────────────────────────────────────────────────
create table if not exists bic_facts (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null,
  domain      text not null default 'general',
  entity_id   uuid not null references bic_entities(id) on delete cascade,

  category    text not null references bic_fact_categories(code),
  predicate   text not null references bic_predicate_defs(code),
  value       text not null,
  value_key   text not null,               -- normalised value, for multi-cardinality dedupe
  content     text not null,               -- prompt-ready rendering

  -- Denormalised copy of bic_predicate_defs.cardinality. Required because a
  -- partial unique index cannot run a subquery against another table, and the
  -- two cardinality indexes below must be able to discriminate. Kept honest by
  -- the trigger bic_facts_set_cardinality() — the application never sets it.
  cardinality_hint text not null default 'single'
                     check (cardinality_hint in ('single', 'multi')),

  importance  smallint not null default 3 check (importance between 1 and 5),
  confidence  numeric(3,2) not null default 0.70 check (confidence between 0 and 1),

  -- Article II.5: access is visibility + acl_roles, never author.
  visibility  text not null default 'internal'
                check (visibility in ('internal', 'customer_safe')),
  acl_roles   text[] not null default '{}', -- empty = no extra restriction

  -- Article II.6: customer-sourced facts are capped at 0.5 confidence and
  -- never auto-promote. Provenance is what makes that enforceable — without
  -- it, a customer asserting "you agreed to 60% off" becomes owner truth.
  source      text not null default 'conversation'
                check (source in ('conversation', 'customer_claim', 'crm', 'derived', 'manual')),
  source_ref  text,
  created_by  text,                         -- provenance only, NOT access control

  status      text not null default 'active'
                check (status in ('active', 'superseded', 'retracted')),
  superseded_by uuid references bic_facts(id),

  valid_from  timestamptz not null default now(),
  valid_to    timestamptz,

  reference_count    integer not null default 0,
  last_referenced_at timestamptz,

  embedding   vector(768),       -- reserved, null until needed

  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  -- Article II.6 enforced in SQL, not in a prompt.
  constraint bic_facts_customer_claim_confidence
    check (source <> 'customer_claim' or confidence <= 0.5)
);

-- ── The cardinality indexes (architecture review finding C2) ───────────────
-- 'single' predicates: one active value per (entity, predicate). A new value
--          supersedes the old one. e.g. budget, status.
-- 'multi'  predicates: many active values, deduped by value_key. e.g. phone,
--          team_member. Using the 'single' index for these would silently
--          delete data — adding a 2nd team member would evict the 1st.
-- Enforcement is split across two partial indexes because Postgres cannot
-- consult bic_predicate_defs from within a unique index; the application
-- writes the correct shape and these indexes make violations impossible.
create unique index if not exists bic_facts_single_active
  on bic_facts (tenant_id, entity_id, predicate)
  where status = 'active' and cardinality_hint = 'single';

create unique index if not exists bic_facts_multi_active
  on bic_facts (tenant_id, entity_id, predicate, value_key)
  where status = 'active' and cardinality_hint = 'multi';

-- Keeps cardinality_hint synchronised with the registry, so the application
-- cannot desynchronise it by accident. Article: "the schema makes wrong things
-- impossible" — a denormalised column the app is trusted to set correctly is
-- exactly the kind of thing that silently rots over 10 years.
create or replace function bic_facts_set_cardinality()
returns trigger
language plpgsql
as $$
begin
  select cardinality into new.cardinality_hint
  from bic_predicate_defs
  where code = new.predicate;

  if new.cardinality_hint is null then
    raise exception 'unknown predicate %, register it in bic_predicate_defs first', new.predicate;
  end if;
  return new;
end;
$$;

drop trigger if exists bic_facts_cardinality_trg on bic_facts;
create trigger bic_facts_cardinality_trg
  before insert or update of predicate on bic_facts
  for each row execute function bic_facts_set_cardinality();

create index if not exists bic_facts_entity_idx   on bic_facts (entity_id, status);
create index if not exists bic_facts_tenant_idx   on bic_facts (tenant_id, status, importance desc);
create index if not exists bic_facts_content_trgm on bic_facts using gin (content gin_trgm_ops);
create index if not exists bic_facts_visibility_idx on bic_facts (tenant_id, visibility, status);

-- ── Edges ──────────────────────────────────────────────────────────────────
-- Kept as a separate table rather than modelling relations as facts: graph
-- traversal via a facts table means recursive self-joins on a polymorphic
-- column, which is materially worse. One of the few places extra structure pays.
create table if not exists bic_edges (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null,
  from_id    uuid not null references bic_entities(id) on delete cascade,
  to_id      uuid not null references bic_entities(id) on delete cascade,
  relation   text not null references bic_relation_types(code),
  weight     numeric(3,2) not null default 0.50 check (weight between 0 and 1),
  created_at timestamptz not null default now(),

  constraint bic_edges_unique unique (tenant_id, from_id, to_id, relation),
  constraint bic_edges_no_self check (from_id <> to_id)
);

create index if not exists bic_edges_from_idx on bic_edges (tenant_id, from_id, relation);
create index if not exists bic_edges_to_idx   on bic_edges (tenant_id, to_id, relation);

alter table bic_entities enable row level security;
alter table bic_facts    enable row level security;
alter table bic_edges    enable row level security;
