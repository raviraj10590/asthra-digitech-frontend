-- BIC 2B hardening — D15: identity is CLASS-scoped, not TRANSPORT-scoped.
--
-- THE DEFECT
-- ----------
-- The live-binding unique index was (tenant_id, channel, identifier_value),
-- which lets ONE phone number be simultaneously bound to TWO DIFFERENT
-- parties — one via 'whatsapp', one via 'sms'. IDD-2D §3.3 classifies a phone
-- as CONTACT regardless of how the message arrived; channel is a delivery
-- detail, not an identity scope. The old rule silently splits one person in
-- two, which is the mirror image of the false merge §3.6 works so hard to
-- prevent, and just as silent.
--
-- WHY NOT SIMPLY DROP `channel` FROM THE KEY
-- ------------------------------------------
-- Because it is correct for exactly one class. §3.2:
--
--   SOVEREIGN   issued by a state authority, unique GLOBALLY
--   CONTROLLED  unique WITHIN ONE ISSUING SYSTEM only — "two systems'
--               customer IDs are unrelated"
--   CONTACT     no uniqueness of its own; one value = one identity to us
--   NOMINAL     names. Never a matching key at all (§3.7)
--
-- Tally customer 12345 and CRM customer 12345 are different people. Dropping
-- the scope for CONTROLLED would create the false merge; keeping it for
-- CONTACT creates the false split. So the rule is per-class, expressed as two
-- partial unique indexes plus a deliberate absence for NOMINAL.
--
-- `channel` REMAINS on the table for CONTROLLED scoping and as provenance of
-- where a binding was seen. It is only removed from the CONTACT/SOVEREIGN key.
--
-- RETENTION UNCHANGED: both indexes stay partial on `valid_until is null`, so
-- expired bindings are still retained, still non-resolving, and a recycled
-- number can still be re-bound later without rewriting history.

drop index if exists bic_party_identifiers_live_idx;

-- SOVEREIGN and CONTACT: one live binding per (tenant, class, value),
-- whatever transport carried it.
create unique index if not exists bic_party_identifiers_live_global_idx
  on bic_party_identifiers (tenant_id, identifier_class, identifier_value)
  where valid_until is null
    and identifier_class in ('SOVEREIGN', 'CONTACT');

-- CONTROLLED: unique only within its issuing system (§3.2).
create unique index if not exists bic_party_identifiers_live_system_idx
  on bic_party_identifiers (tenant_id, identifier_class, channel, identifier_value)
  where valid_until is null
    and identifier_class = 'CONTROLLED';

-- NOMINAL has NO unique index, deliberately. A uniqueness constraint on names
-- would make them a matching key, which §3.7 forbids outright: fuzzy or exact,
-- names produce false merges "at exactly the rate that makes them hard to
-- detect". Aliases are evidence, never identity.

comment on index bic_party_identifiers_live_global_idx is
  'IDD-2D §3.2-3.3: SOVEREIGN and CONTACT identity is scoped by CLASS, not by
   transport. One phone is one identity whether it arrives by WhatsApp or SMS.';

comment on index bic_party_identifiers_live_system_idx is
  'IDD-2D §3.2: CONTROLLED identifiers are unique WITHIN ONE ISSUING SYSTEM
   only, so `channel` (the issuing system) stays part of the key here.';
