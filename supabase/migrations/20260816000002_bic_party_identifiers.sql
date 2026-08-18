-- BIC 2B/2D — Party identifiers: the ONLY place a channel identifier lives.
--
-- WHY THIS TABLE EXISTS AT ALL
-- ----------------------------
-- bic_parties is deliberately meaningless, so something must answer "which
-- party is this WhatsApp sender?". That mapping is PII, and confining it to
-- ONE table is what keeps bic_claims free of it: claims carry only the opaque
-- knowledge_id, so the entire fact store is queryable without touching a
-- phone number.
--
-- THIS IS NOT A SURROGATE IDENTITY MAP
-- ------------------------------------
-- IDD-2D §3.2-3.3 classifies identifiers into four classes and makes that
-- classification "the core design decision" — treating identifiers as equal
-- is named as "the single most common cause of false merges". This table IS
-- that object. 2D later adds a resolution ALGORITHM on top of it (scoring,
-- merge, DISPUTED); it does not replace the storage, so nothing built here
-- gets migrated away.
--
-- WHAT IS NOT IMPLEMENTED HERE (2D, deliberately absent)
-- ------------------------------------------------------
--   • no merge, no merge reversal, no pre-merge state
--   • no match scoring, no corroborating-signal logic
--   • no DISPUTED resolution
--   • no cross-class normalisation
-- This slice does exact match, or create. Nothing else.
--
-- THE TWO RULES THAT BIND FROM DAY ONE (2D §3.4)
--   R1  A phone number NEVER auto-merges two parties, at any confidence.
--   R2  A party created from a phone alone starts PROVISIONAL, never RESOLVED.
--   R3  A phone binding carries valid_from/valid_until — numbers change hands,
--       so a binding must be able to expire.
--
-- ══════════════════════════════════════════════════════════════════════════
-- RETENTION SEMANTICS — LOCKED BEFORE THE FIRST PRODUCTION WRITE
-- ══════════════════════════════════════════════════════════════════════════
-- This table is a DELIBERATE PII STORE. It holds the only channel identifier
-- in the BIC stack, and the rules below are the contract, not a default that
-- happened to fall out of the implementation.
--
--   ACTIVE      valid_until IS NULL. Exactly one such row per
--               (tenant, channel, identifier_value), enforced by the partial
--               unique index below.
--
--   EXPIRED     valid_until IS NOT NULL. The ROW IS RETAINED. Expiry is an
--               UPDATE that sets an end date — never a DELETE.
--
--   RESOLUTION  Only ACTIVE bindings resolve. An expired binding must never
--               resolve, or a recycled number would silently answer as its
--               previous holder — the exact false-merge 2D R1 forbids,
--               arrived at through the back door.
--
--   HISTORY     Expired rows stay queryable forever. A claim asserted while a
--               binding was live must remain explicable years later; deleting
--               the binding would leave an unattributable claim, which is
--               indistinguishable from a fabricated one.
--
--   PRUNING     NONE IN THIS SLICE. No pruner, no TTL, no scheduled job, no
--               cascade. Deliberate: bic_claims is append-only with no
--               pruner, so deleting an identifier could orphan a claim whose
--               subject can no longer be explained. A retention policy is a
--               real future decision (and a legal one) — it is recorded here
--               as an OPEN QUESTION rather than pre-empted by a default
--               nobody chose.
--
--   COST        Zero. Existing Supabase, existing Vercel. No new service.
--
-- The one thing this table must never become is a phone directory that
-- outlives its purpose without anyone having decided that it should.

create table if not exists bic_party_identifiers (
  identifier_id    uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null,
  party_id         uuid not null references bic_parties(knowledge_id),

  -- 2D §3.2. CONTACT is the weakest class: no uniqueness, recycled after
  -- disconnection, routinely shared. Recorded explicitly so a future resolver
  -- can never mistake a phone for a sovereign identifier.
  identifier_class text not null
    check (identifier_class in ('SOVEREIGN', 'CONTROLLED', 'CONTACT', 'NOMINAL')),

  channel          text not null,          -- 'whatsapp' for this slice
  identifier_value text not null,          -- E.164; the ONLY PII in the BIC stack

  -- 2D R3. A binding is true for a PERIOD, not forever.
  valid_from       timestamptz not null default now(),
  valid_until      timestamptz,

  created_at       timestamptz not null default now(),

  constraint bic_party_identifiers_validity_order
    check (valid_until is null or valid_until >= valid_from)
);

-- One LIVE binding per (channel, value) per tenant. A partial unique index —
-- expired bindings are excluded, so a recycled number can be re-bound to a
-- different party later without violating uniqueness or rewriting history.
create unique index if not exists bic_party_identifiers_live_idx
  on bic_party_identifiers (tenant_id, channel, identifier_value)
  where valid_until is null;

create index if not exists bic_party_identifiers_party_idx
  on bic_party_identifiers (tenant_id, party_id);

comment on table bic_party_identifiers is
  'IDD-2D §3.2 identifier classification. The only table in the BIC stack that
   holds a channel identifier (PII); bic_claims carries the opaque
   knowledge_id instead. Exact-match lookup only in this slice — no merge, no
   scoring, no DISPUTED. Bindings expire (2D R3) so recycled numbers can be
   re-bound without rewriting history.';

comment on column bic_party_identifiers.identifier_class is
  'IDD-2D §3.2. CONTACT (phone, email) never resolves identity alone and never
   auto-merges two parties (R1), whatever the confidence.';

alter table bic_party_identifiers enable row level security;
