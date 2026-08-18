-- BIC 2B — Party: the smallest legitimate business-object identity.
--
-- WHAT A knowledge_id IS (IDD-2B §2.2, V3)
-- ----------------------------------------
-- "Every object's identity is a meaningless knowledge_id; the columns listed
--  are the IDENTIFYING ASSERTIONS that feed resolution."
--
-- Meaningless is the whole design. Companies rename, people marry, GSTINs are
-- reissued, phone numbers change hands — identity survives all of it because
-- it encodes nothing. Anything derived from an attribute (a phone hash, a
-- UUIDv5 over an email, a CRM row id) breaks the moment that attribute
-- changes, and breaks silently.
--
-- WHAT IS DELIBERATELY ABSENT
-- ---------------------------
-- No name. No phone. No email. No CRM key. Not one descriptive column.
-- Every attribute of a party is a 2C claim ABOUT this id, which is what makes
-- the fact store queryable without ever touching PII. The single channel
-- identifier a WhatsApp party has lives in bic_party_identifiers, not here.
--
-- WHY NOT bic_entities (Phase 1A)
-- -------------------------------
-- It has `name`, `name_key` and `aliases` as COLUMNS where 2B requires
-- assertions; it stores `status` and `merged_into` where 2C C1 requires
-- derived state; and decisively, bic_facts references it ON DELETE CASCADE —
-- deleting an entity destroys its facts, which no trigger can reconcile with
-- append-only. 1A has no production reader or writer and stays frozen legacy.
--
-- TENANT-SCOPED, unlike bic_concepts. Vocabulary is shared between tenants;
-- a party never is (Article II.5).

create table if not exists bic_parties (
  -- Meaningless and permanent from creation (2B V3). Never derived from any
  -- attribute of the party.
  knowledge_id     uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null,

  -- FROZEN AT CREATION (2B §2.2): "A Party has exactly one kind, assigned
  -- once, never changed. A Person cannot become an Organization."
  kind             text not null check (kind in ('PERSON', 'ORGANIZATION')),

  -- 2D §2.1. A party built from a phone number alone is PROVISIONAL and stays
  -- that way (2D R2) — phone is a CONTACT identifier: not unique, recycled
  -- after disconnection, and routinely shared.
  resolution_state text not null default 'PROVISIONAL'
    check (resolution_state in
           ('UNRESOLVED', 'PROVISIONAL', 'RESOLVED', 'DISPUTED', 'MERGED')),

  created_at       timestamptz not null default now()
);

create index if not exists bic_parties_tenant_idx
  on bic_parties (tenant_id, resolution_state);

comment on table bic_parties is
  'IDD-2B Party. Identity is a meaningless, permanent knowledge_id; every
   descriptive attribute is a 2C claim about it, never a column here. kind is
   frozen at creation. Parties created from a phone alone stay PROVISIONAL
   (2D R2). Tenant-scoped.';

-- ── kind is immutable (2B §2.2) ────────────────────────────────────────────
-- A CHECK constraint cannot express "never changes", so this is a trigger.
-- resolution_state DOES change (that is its lifecycle); kind never does.
create or replace function bic_parties_freeze_kind()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.kind is distinct from old.kind then
    raise exception
      'bic_parties.kind is frozen at creation (IDD-2B §2.2): % cannot become %',
      old.kind, new.kind
      using errcode = 'check_violation';
  end if;
  if new.knowledge_id is distinct from old.knowledge_id then
    raise exception
      'bic_parties.knowledge_id is permanent (IDD-2B V3) and cannot be reassigned'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

revoke all on function bic_parties_freeze_kind() from public, anon, authenticated;

drop trigger if exists bic_parties_freeze on bic_parties;
create trigger bic_parties_freeze
  before update on bic_parties
  for each row execute function bic_parties_freeze_kind();

comment on trigger bic_parties_freeze on bic_parties is
  'IDD-2B §2.2 + V3: kind is assigned once and never changed; knowledge_id is
   permanent. Binds every caller including service_role, which bypasses RLS
   but not triggers.';

-- Deny by default: no policy is defined, so only the service-role key reaches
-- this table. Consistent with every other BIC table.
alter table bic_parties enable row level security;
