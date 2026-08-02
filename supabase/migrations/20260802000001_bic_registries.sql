-- BIC v1.0 — Slice 1A · Registries
-- Constitution: Article IV (Data Model), Article VIII (Extensibility)
--
-- WHY REGISTRY TABLES INSTEAD OF CHECK CONSTRAINTS:
-- A CHECK enum means every new business vertical (manufacturing, real estate,
-- govt) requires ALTER TABLE — i.e. a schema migration per vertical. Article
-- VIII forbids that: "New verticals are INSERTs, never ALTER TABLEs."
-- These tables are the mechanism that makes that guarantee real.

create table if not exists bic_entity_types (
  code        text primary key,
  label       text not null,
  domain      text not null default 'general',
  description text,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

create table if not exists bic_fact_categories (
  code        text primary key,
  label       text not null,
  description text,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

create table if not exists bic_relation_types (
  code         text primary key,
  label        text not null,
  -- named is_symmetric because SYMMETRIC is a reserved word in Postgres
  is_symmetric boolean not null default false,  -- 'related_to' is; 'client_of' is not
  description  text,
  active       boolean not null default true,
  created_at   timestamptz not null default now()
);

-- Cardinality is the load-bearing column here. Architecture review found that
-- assuming one value per predicate silently DESTROYS multi-valued facts:
-- adding a second team member would supersede the first. 'single' supersedes,
-- 'multi' accumulates. See bic_facts partial unique indexes in migration 0002.
create table if not exists bic_predicate_defs (
  code        text primary key,
  label       text not null,
  cardinality text not null default 'single'
                check (cardinality in ('single', 'multi')),
  volatile    boolean not null default false,  -- eligible for confidence decay
  decay_days  integer,                          -- null = never decays
  description text,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

-- Tool registry. Article II.2: security never depends on model behaviour —
-- min_role and risk_tier are enforced in code against THIS table, never by
-- asking the model to behave.
create table if not exists bic_tool_defs (
  code         text primary key,
  label        text not null,
  min_role     text not null default 'OWNER'
                 check (min_role in ('CLIENT', 'STAFF', 'MANAGER', 'OWNER')),
  risk_tier    smallint not null default 3 check (risk_tier between 1 and 5),
  side_effects boolean not null default false,
  customer_safe boolean not null default false, -- allowlist for CLIENT mode
  description  text,
  active       boolean not null default true,
  created_at   timestamptz not null default now()
);

-- ── Seed data ──────────────────────────────────────────────────────────────
-- Idempotent: on conflict do nothing, so re-running is harmless.

insert into bic_entity_types (code, label, domain, description) values
  ('person',   'Person',   'general', 'Staff, contacts, individuals'),
  ('customer', 'Customer', 'general', 'A client — CRM remains source of truth; we store a reference'),
  ('project',  'Project',  'general', 'Ongoing work, campaign, or engagement'),
  ('decision', 'Decision', 'general', 'A choice made, retained so it is not re-litigated'),
  ('topic',    'Topic',    'general', 'Subject area or theme'),
  ('org',      'Organisation', 'general', 'Company, department, or government body')
on conflict (code) do nothing;

insert into bic_fact_categories (code, label, description) values
  ('profile',       'Profile',       'Identity and descriptive attributes'),
  ('project',       'Project',       'Project state and attributes'),
  ('customer',      'Customer',      'Customer-related knowledge'),
  ('decision',      'Decision',      'A decision and its rationale'),
  ('preference',    'Preference',    'How the owner wants things done'),
  ('business_fact', 'Business Fact', 'Durable business knowledge')
on conflict (code) do nothing;
-- NOTE: 'open_item' is deliberately ABSENT. Architecture review removed it —
-- bic_tasks (Phase 3) is the single home for actionable work. Two homes for
-- "work to do" guarantees drift.

insert into bic_relation_types (code, label, is_symmetric, description) values
  ('works_on',    'Works On',    false, 'Person → Project'),
  ('client_of',   'Client Of',   false, 'Project/Person → Customer'),
  ('owns',        'Owns',        false, 'Person → Project/Asset'),
  ('depends_on',  'Depends On',  false, 'Blocking dependency'),
  ('blocks',      'Blocks',      false, 'Inverse of depends_on'),
  ('related_to',  'Related To',  true,  'Generic association'),
  ('decided_for', 'Decided For', false, 'Decision → Entity it applies to')
on conflict (code) do nothing;

insert into bic_predicate_defs (code, label, cardinality, volatile, decay_days, description) values
  ('name',         'Name',          'single', false, null, 'Canonical name'),
  ('role',         'Role',          'single', false, null, 'Job title or function'),
  ('phone',        'Phone',         'multi',  false, null, 'Contact number — a person may have several'),
  ('email',        'Email',         'multi',  false, null, 'Email address'),
  ('city',         'City',          'single', false, null, 'Location'),
  ('company',      'Company',       'single', false, null, 'Employer or organisation'),
  ('service_needed','Service Needed','multi', true,  180,  'Requested service'),
  ('budget',       'Budget',        'single', true,  90,   'Stated budget — volatile, decays'),
  ('timeline',     'Timeline',      'single', true,  90,   'Expected timing'),
  ('status',       'Status',        'single', true,  60,   'Current state — highly volatile'),
  ('team_member',  'Team Member',   'multi',  false, null, 'Person on a project — MUST be multi'),
  ('rationale',    'Rationale',     'multi',  false, null, 'Reason behind a decision'),
  ('preference',   'Preference',    'multi',  false, null, 'A stated working preference'),
  ('note',         'Note',          'multi',  false, null, 'Free-form durable note')
on conflict (code) do nothing;

-- ── Security: deny-by-default ──────────────────────────────────────────────
-- RLS on with NO policies = no access for anon/authenticated. Only the
-- service_role (which bypasses RLS) can read/write. Slice 1A ships zero code
-- that touches these tables, so locking them down now is free; the access
-- decision is made in 1B/1D when code actually needs them.
alter table bic_entity_types    enable row level security;
alter table bic_fact_categories enable row level security;
alter table bic_relation_types  enable row level security;
alter table bic_predicate_defs  enable row level security;
alter table bic_tool_defs       enable row level security;
