-- BIC — Brain-local message references, so bic_claims stops storing wamids.
--
-- THE DEFECT THIS CLOSES
-- ----------------------
-- bic_claims.source_ref held `wa_msg:<wamid>`. Meta's wamid is NOT opaque: it
-- base64-embeds the sender's MSISDN. `wamid.HBgMOTE5OTk5MDAwNDQ0FQIAEhgg`
-- decodes to bytes containing "919999000444". Every claim written from an
-- inbound message therefore carried the customer's phone number in reversible
-- form inside the evidence table. The privacy tests missed it for months
-- because they only ever searched for the number in plaintext.
--
-- WHAT CHANGES, AND WHAT DELIBERATELY DOES NOT
-- --------------------------------------------
-- bic_webhook_events IS the integration layer: one row per inbound delivery,
-- keyed by Meta's identity. That is where an external identifier legitimately
-- belongs, so `wamid` REMAINS the primary key and remains the dedupe
-- mechanism — the unique violation is still the duplicate signal, unchanged.
--
-- This migration only adds OUR id alongside it. New claims point at
-- `msg:<brain_message_id>`; correlating a claim back to a Meta delivery is a
-- join on this table, available to an operator and to nobody downstream.
--
-- ADDITIVE AND IDEMPOTENT. `if not exists` on both objects. The column is NOT
-- NULL with a random default, so existing rows are filled without a rewrite
-- being written here and no row is ever deleted or updated by this file.
--
-- HISTORICAL CLAIMS ARE NOT TOUCHED. bic_claims is append-only and
-- trigger-enforced: rewriting `wa_msg:<wamid>` rows is impossible by
-- construction, and it would also destroy evidence — the record of what we
-- believed and on what basis. Old claims keep their old reference and remain
-- correlatable by the wamid they already contain; only new claims are opaque.
-- Closing the historical exposure is a RETENTION decision about bic_claims,
-- deliberately not pre-empted here.

alter table bic_webhook_events
  add column if not exists brain_message_id uuid not null default gen_random_uuid();

-- One Brain id per delivery, both directions. Without this a bug could point
-- two deliveries at one reference and silently merge two messages' provenance.
create unique index if not exists bic_webhook_events_brain_message_id_key
  on bic_webhook_events (brain_message_id);

comment on column bic_webhook_events.brain_message_id is
  'Brain-local opaque message id (uuid4, cryptographically random). This — not
   the wamid — is what bic_claims.source_ref points at, as `msg:<uuid>`. The
   wamid stays the primary key because dedupe needs Meta''s identity; this
   column exists so the evidence layer never has to store it.';
