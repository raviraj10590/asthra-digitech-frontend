-- BIC 2A seed — core.party.became_client_at@1
--
-- THE CONVERSION EVENT, AND WHY IT IS AN EVENT RATHER THAN A STATUS
-- -----------------------------------------------------------------
-- The audit that preceded this found no record anywhere in the system that a
-- party had become a client. Every candidate failed on evidence:
--
--   leads.status            3 rows, all 'new', created_at == updated_at on all
--                           three, and NO CODE ANYWHERE WRITES THE COLUMN. It
--                           is a database default, not a lifecycle.
--   bic_commitments         0 rows. Never exercised.
--   bic_outcome_records     106 rows, all customer_reply. Engagement, not
--                           commerce.
--   bic_parties.kind        PERSON/ORGANIZATION, frozen at creation by
--                           trigger. Structurally incapable of holding a
--                           lifecycle transition.
--   CRM `clients`           written automatically for EVERY extracted lead by
--                           sync_lead_to_crm. A row there means "the bot
--                           extracted a lead", not "this party is a client".
--                           Its name asserts precisely what it does not mean.
--
-- So the event did not exist and had to be created. It is stored as a CLAIM,
-- not a status column, because a claim inherits retraction, bitemporality,
-- versioning and the registry gate for free. A status column would be a second
-- source of truth with no staleness rules and no audit.
--
-- THE BUSINESS DEFINITION (OWNER RULING, 2026-09-07)
-- -------------------------------------------------
-- A party is CONVERTED when the business records the party's FIRST PAYMENT
-- RECEIVED. Not a meeting, not a proposal, not a signature — the first
-- payment. Everything else follows from that one sentence:
--
--   single      one party has exactly one first payment, forever. A second
--               claim is a BUG, not a supersession, exactly as with
--               first_seen_at — so the writer READS BEFORE WRITING and
--               declines rather than appending a competing value.
--   static      once established it is permanent. Later payments do not
--               create new conversion events. A refund does not erase the
--               historical fact that the first payment occurred: the event
--               records THAT IT HAPPENED, not that the money is still held.
--   TEMPORAL    the value IS a point in time, which needs different machinery
--               from a category or a quantity (2A §3.3).
--
-- TIER 1, NOT TIER 0 — THE ONE PLACE THIS COULD HAVE BEEN INFLATED
-- ----------------------------------------------------------------
-- 2C §6.1 is explicit: tier 0 is an AUTHORITATIVE SYSTEM OF RECORD — Tally, a
-- bank statement, the GST portal. Tier 1 is "verified human, in role —
-- owner-confirmed", capped at 0.90. An owner typing a command is tier 1. It
-- would have been easy, and wrong, to call the owner's own word about their
-- own business tier 0; the cap exists so that when a real payment system is
-- integrated later it can supersede this on authority rather than on recency.
--
-- NO BACKFILL. NOT ONE ROW.
-- -------------------------
-- 27 parties currently hold first_seen_at and an unknown number of them have
-- already paid. We do not know WHICH, and we do not know WHEN. Marking them
-- converted would mean writing fabricated payment timestamps — knowledge that
-- was never observed, which is exactly what the bitemporal, append-only design
-- exists to prevent. Forward capture only, identical to first_seen_at's own
-- "22 senders predate this predicate and they stay unclaimed".
--
-- The consequence is accepted rather than hidden: for some months to come the
-- conversion numerator will be incomplete, and the Business Operating Review
-- must keep saying so instead of reporting a falsely low rate.
--
-- NO FINANCIAL DATA. The value is a timestamp and nothing else. No amount, no
-- currency, no transaction reference, no card, no bank detail ever enters a
-- Brain claim. We need to know THAT the first payment happened and WHEN; the
-- money itself belongs in the accounting system, not the evidence store.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'core.party',
  'became_client_at',
  1,
  'TEMPORAL',
  jsonb_build_object('type', 'timestamp'),
  null,
  'single',
  'static',
  array['PERSON', 'ORGANIZATION']::text[],
  'ACTIVE',
  'raviraj',
  now(),
  'Became client at',
  'The moment this party''s FIRST PAYMENT was received, as confirmed by the '
    || 'owner in role. Provenance tier 1, confidence 0.90 (IDD-2C §6.1: '
    || 'verified human, in role). One per party and permanent: later payments '
    || 'create no new event, and a refund does not erase the historical fact '
    || 'that the first payment occurred. Never inferred from a CRM row, a '
    || 'lead, a conversation, a proposal or a meeting. Captured forward only '
    || '— parties who had already paid before this predicate existed are NOT '
    || 'backfilled, so the conversion numerator is knowingly incomplete until '
    || 'enough forward history accrues.',
  jsonb_build_array('2026-09-07T10:20:00+00:00')
)
on conflict (namespace, concept, version) do nothing;
