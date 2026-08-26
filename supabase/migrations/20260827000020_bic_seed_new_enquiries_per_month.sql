-- BIC 2A — the FIRST business-level predicate.
--
-- Every predicate registered until now describes a COUNTERPARTY:
-- declared_service_interest, engagement_segment, first_seen_at. This one
-- describes the BUSINESS. It is the first fact the Brain can hold about
-- Asthra itself rather than about someone Asthra talks to.
--
-- EXACT MEANING, FROZEN AT @1
-- ---------------------------
--   "The number of DISTINCT parties known to the Brain whose
--    core.party.first_seen_at@1 falls within one calendar month,
--    measured in IST (UTC+05:30)."
--
-- Every clause is load-bearing:
--
--   DISTINCT PARTIES    not messages, not claims, not leads, not CRM clients.
--                       A party seen ten times in a month counts once.
--
--   KNOWN TO THE BRAIN  the completeness boundary, and it is deliberately
--                       narrow. This is NOT "all enquiries Asthra received"
--                       and NOT "all leads generated". It is what the Brain
--                       itself observed on its own transport. Anyone reading
--                       this value as total business demand is reading it
--                       wrong, and the label says so.
--
--   CALENDAR MONTH IST  not a rolling 30 days. Ruled by the owner on
--                       2026-08-27. A calendar month is what the business
--                       already reports on (compliance, ITR) and what the
--                       owner means by "this month". The consequence is
--                       accepted: the value resets on the 1st, so a reading
--                       taken on the 2nd is legitimately small.
--
--   first_seen_at       the ONLY source. Chosen because the Brain writes it
--                       itself at tier 1 and it is therefore complete by
--                       construction over the population it covers. The
--                       `leads` table was rejected as a source: it is empty
--                       in production while the business demonstrably has
--                       clients, so a metric derived from it would be
--                       literally true and substantively false.
--
-- QUANTITATIVE REQUIRES A UNIT (2A §3.5)
-- --------------------------------------
-- "unit is mandatory for QUANTITATIVE; changing it silently corrupts every
-- comparison." This is the first QUANTITATIVE predicate in the registry, so
-- it sets the convention: 'count' for a dimensionless tally.
--
-- VOLATILITY = fast
-- -----------------
-- bic/knowledge.py notes that `fast` (24h) had no production consumer and
-- "should be revisited by whoever registers that predicate." That is this
-- migration, and 24h is the right bound: the count genuinely changes as new
-- parties appear during an open month, so a value more than a day old is
-- suspect while the month is still running. `slow` (180d) would report a
-- stale monthly figure as fresh; `live` (5m) would mark a correct value
-- stale minutes after it was computed, for a metric nothing recomputes that
-- often.
--
-- SUBJECT IS THE BUSINESS ITSELF
-- ------------------------------
-- bic_claims.subject is FK-constrained to bic_parties, so this fact attaches
-- to an ORGANIZATION party representing the tenant's own business — which is
-- 2B's existing model ("a firm is a SEPARATE Organization party"), not a new
-- identity concept. applies_to therefore names ORGANIZATION only: asserting
-- a business-wide pipeline count against a PERSON would be a category error.
--
-- NO TABLE. NO COLUMN. ONE INSERT.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'biz.pipeline',
  'new_enquiries_per_month',
  1,
  -- QUANTITATIVE: the value is a magnitude that can be compared and trended,
  -- which needs different machinery from a category or a timestamp (2A §3.3).
  'QUANTITATIVE',
  -- 'min', NOT 'minimum': registry._check_value reads space["min"]. Writing
  -- 'minimum' here would register a floor the validator never consults, so a
  -- negative count would pass. Verified against the validator, not assumed.
  jsonb_build_object('type', 'number', 'min', 0),
  'count',
  -- single: one value per subject per calendar month. A later recomputation
  -- of the SAME month supersedes rather than competes — the month is pinned
  -- by valid_from/valid_until on the claim, not by the predicate.
  'single',
  'fast',
  array['ORGANIZATION']::text[],
  'ACTIVE',
  'raviraj',
  now(),
  'New enquiries per month (Brain-known)',
  'Distinct parties whose first contact with the Brain falls inside one '
    || 'calendar month, measured in IST. Derived deterministically from '
    || 'core.party.first_seen_at@1 — provenance tier 3 (rule-based inference '
    || 'over tier-1 facts), confidence capped at 0.70 (IDD-2C §6). '
    || 'COMPLETENESS BOUNDARY: counts only what the Brain itself observed on '
    || 'its own transport. It is not total business demand, not all leads, '
    || 'and not the CRM client count.',
  jsonb_build_array(0, 7, 23)
)
on conflict (namespace, concept, version) do nothing;
