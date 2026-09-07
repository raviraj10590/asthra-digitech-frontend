-- BIC 2A seed — biz.pipeline.conversion_rate@1
--
-- THE POLICY THIS ENCODES (OWNER RULING, 2026-09-07)
-- --------------------------------------------------
--   conversion event   first payment received (core.party.became_client_at@1)
--   window             30 calendar days from the party's OWN first enquiry
--   basis              ENQUIRY COHORT
--
-- The previous slice stopped exactly here and reported POLICY_REQUIRED rather
-- than choosing a window. These three lines are the decision that unblocked
-- it, and every rule in bic/conversion_evidence.py follows from them.
--
-- COHORT, NOT CALENDAR PERIOD
-- ---------------------------
-- "payments this month / enquiries this month" is cheap, always produces a
-- number, and compares two unrelated populations — the people who paid in
-- September mostly enquired earlier, so the ratio describes nobody. A cohort
-- follows ONE group forward through their own 30 days.
--
-- WHY THE UNIT IS A RATIO AND THE SPACE IS BOUNDED
-- ------------------------------------------------
-- 'min', NOT 'minimum', and 'max', NOT 'maximum': registry._check_value reads
-- space["min"] and space["max"]. Writing the long form here would register
-- bounds the validator never consults, so a rate of 4.0 would pass. Verified
-- against the validator, not assumed — the same trap 20260827000020 documents.
--
-- A conversion rate is a fraction of a known population, so it cannot exceed
-- 1. The bound is real evidence hygiene, not decoration: a numerator larger
-- than its denominator means the cohort logic is broken, and the store should
-- refuse the claim rather than publish an impossible business fact.
--
-- PROVISIONAL COHORTS ARE NEVER STORED HERE
-- -----------------------------------------
-- A September cohort cannot be final on October 1 — parties who enquired on
-- September 25 have until October 25 to pay. The producer computes such a
-- cohort and labels it PROVISIONAL, but asserts NO claim: a number that can
-- still only rise must not enter the predicate a reader trusts as settled.
-- No label carried on the claim would survive being read as "the conversion
-- rate", so the correct place to draw that line is before the write.
--
-- MISSING IS NOT ZERO
-- -------------------
-- became_client_at was activated on 2026-09-07 with NO backfill. For any
-- cohort that opened before that, "0 conversions recorded" means "we were not
-- recording", not "nobody paid". The producer reads this concept's own
-- activated_at from the registry and refuses to measure a cohort that opened
-- earlier. It reads the epoch rather than hardcoding it, so re-registering the
-- concept can never leave the arithmetic pointing at a stale date.
--
-- ORGANIZATION ONLY. This is a fact about Asthra, not about a counterparty —
-- a business-wide rate against a PERSON would be a category error, exactly as
-- with new_enquiries_per_month.
--
-- NO TABLE. NO COLUMN. ONE INSERT.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'biz.pipeline',
  'conversion_rate',
  1,
  'QUANTITATIVE',
  jsonb_build_object('type', 'number', 'min', 0, 'max', 1),
  'ratio',
  -- single: one value per subject per cohort. A recomputation of the SAME
  -- cohort supersedes rather than competes — the cohort is pinned by
  -- valid_until on the claim, not by the predicate.
  'single',
  -- slow, not fast: a cohort cannot change once its 30-day window has closed.
  -- Only an unclosed cohort moves, and an unclosed cohort is never stored.
  'slow',
  array['ORGANIZATION']::text[],
  'ACTIVE',
  'raviraj',
  now(),
  'Conversion rate (30-day enquiry cohort)',
  'Of the distinct parties whose first contact fell inside one calendar '
    || 'month (IST), the fraction whose FIRST PAYMENT arrived within 30 days '
    || 'of that party''s own first contact. Derived deterministically from '
    || 'core.party.first_seen_at@1 and core.party.became_client_at@1 — '
    || 'provenance tier 3 (rule-based inference over tier-1 facts), '
    || 'confidence capped at 0.70 (IDD-2C §6). Only cohorts whose full 30-day '
    || 'window has elapsed are recorded; an open cohort is PROVISIONAL and is '
    || 'never asserted. COMPLETENESS BOUNDARY: cohorts that opened before '
    || 'became_client_at existed are NOT measurable at all, because an '
    || 'unrecorded payment cannot be told apart from an absent one.',
  jsonb_build_array(0, 0.25, 1)
)
on conflict (namespace, concept, version) do nothing;
