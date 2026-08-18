-- BIC 2A seed — core.party.first_seen_at@1
--
-- THE FIRST TIER-1 PREDICATE
-- --------------------------
-- Both existing predicates are tier 5: a customer describing themselves, capped
-- at 0.50 by Article II.6. This one is different in kind. It is not a claim the
-- customer makes — it is OUR OWN TRANSPORT recording when a message arrived,
-- through an HMAC-verified boundary. IDD-2C §6 maps system-generated timestamps
-- to tier 1, confidence 0.90, and this is the strongest evidence the store will
-- hold until a sovereign identifier appears.
--
-- WHY IT WAS CHOSEN
-- -----------------
-- Measured production: the welcome menu has NEVER been tapped, and the
-- VIP/ELECTION detector has fired twice in the bot's history (last 2026-07-04).
-- Meanwhile 9 new senders arrived in 30 days and 2 in the last 7. Of every
-- deterministic signal available, first contact is the only one that is
-- genuinely knowledge, single-valued, D12-safe, privacy-free, and not a
-- duplicate of an existing source of truth.
--
-- BITEMPORALITY IS REAL HERE, NOT DECORATIVE
-- ------------------------------------------
--   valid_from   when the party first contacted us — WORLD time
--   observed_at  when the Brain recorded it — SYSTEM time
-- For live capture these differ by milliseconds. The distinction still matters:
-- it is what makes "what did we believe in March?" answerable, and this is the
-- first predicate where the two are conceptually independent rather than
-- coincidentally equal.
--
-- STATIC VOLATILITY
-- -----------------
-- A first contact never changes. `static` gives it the widest staleness bound
-- in the vocabulary — a five-year-old first_seen_at is perfectly fresh, where a
-- five-month-old engagement_segment is not. That difference is what a 2G
-- capability will report instead of treating every fact as equally current.
--
-- NO BACKFILL. 22 senders predate this predicate and they stay unclaimed.
-- Backfilling would mean writing 22 claims with fabricated observed_at values —
-- knowledge that was never observed, which is exactly what the bitemporal,
-- append-only design exists to prevent. Forward capture only.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'core.party',
  'first_seen_at',
  1,
  -- TEMPORAL: the value IS a point in time, which needs different machinery
  -- from a category or a quantity (2A §3.3).
  'TEMPORAL',
  jsonb_build_object('type', 'timestamp'),
  null,
  -- single: a party has exactly ONE first contact. A second claim is a BUG,
  -- not a supersession — the writer checks for an existing claim and declines
  -- rather than appending a competing one.
  'single',
  'static',
  array['PERSON', 'ORGANIZATION']::text[],
  'ACTIVE',
  'raviraj',
  now(),
  'First seen at',
  'The moment this party first contacted us on WhatsApp, recorded by our own '
    || 'transport rather than reported by the customer. System-generated '
    || 'timestamp: provenance tier 1, confidence 0.90 (IDD-2C §6). Captured '
    || 'forward only — parties predating this predicate are never backfilled.',
  jsonb_build_array('2026-08-18T10:20:00+00:00')
)
on conflict (namespace, concept, version) do nothing;
