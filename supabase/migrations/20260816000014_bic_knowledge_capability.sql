-- BIC 2G — knowledge.describe becomes invokable, and service_interest becomes
-- a BINDING rather than a second implementation.
--
-- Migration 10 registered knowledge.describe with active = false / SHADOW,
-- because a descriptor without a handler is a promise, and an invokable
-- promise is a lie. bic/knowledge.py now implements it against real
-- production claims, so the row is corrected to say what is true.
--
-- STATUS IS 'LIMITED', NOT 'GENERAL'
-- ---------------------------------
-- §3.1 rollout status is a claim about exposure, not about code quality. One
-- internal consumer reads this capability today, over three seeded predicates
-- and five real claims. GENERAL would assert a breadth of use that does not
-- exist, and the point of having four statuses is to be able to say so.
--
-- WHAT CHANGES AND WHAT DOES NOT
-- ------------------------------
-- No table is created. No column is added. No claim, party, identifier or
-- decision record is touched. This migration edits exactly two rows of
-- bic_tool_defs, and both edits are reversible by re-running migration 10's
-- values.

-- ── 1. The generic capability, now implemented ─────────────────────────────
update bic_tool_defs set
  active   = true,
  status   = 'LIMITED',
  semver   = '1.0.0',
  module   = 'bic.knowledge',

  -- §3.3 freshness: migration 10 declared the MECHANISM. The IDD specifies
  -- that bounds derive from the 2A volatility class and are per-fact; it does
  -- not specify the durations. Those are a decision, so they are written down
  -- here in the same place a reviewer looks for the guarantee, mirroring
  -- STALENESS_BOUNDS in bic/knowledge.py.
  freshness =
    'Per-fact, from the predicate volatility_class (2A §3.5), measured from '
      || 'observed_at: static = PERMANENT (no bound) · slow = 180 days · '
      || 'fast = 24 hours · live = 5 minutes. The verdict is RETURNED with '
      || 'each value and with the answer as a whole (worst verdict wins); a '
      || 'stale fact is never withheld and never silently accepted. Durations '
      || 'are a chosen calibration, not an IDD constant; fast and live have no '
      || 'production consumer yet.',

  -- §3.2, corrected to the envelope the handler actually returns. Migration
  -- 10 described an intended shape; this is the shipped one.
  outputs = jsonb_build_object(
    'state',      jsonb_build_array('KNOWN','UNKNOWN','DENIED','UNAVAILABLE'),
    'reason',     'why, when the state is not KNOWN',
    'subject',    'the knowledge_id actually answered about (a MERGED entity '
                    || 'redirects, and redirected_from names the original)',
    'identity',   jsonb_build_object('kind','', 'resolution_state',''),
    'values',     jsonb_build_array('predicate','value','confidence',
                                    'provenance','valid_from','observed_at',
                                    'freshness','claim_id'),
    'conflicts',  'unresolved contradictions, carried with resolved = false — '
                    || 'never omitted, never adjudicated here (§3.4, §3.5)',
    'coverage',   jsonb_build_array('requested','consulted','known','absent',
                                    'unavailable','unregistered'),
    'freshness',  'worst verdict across contributing facts + oldest observed_at',
    'confidence', 'a VECTOR (§7.3): value_confidence, provenance_ceiling, '
                    || 'coverage_ratio, identity_state — never one number',
    'degraded',   'boolean, with degradation[] naming each reason (§6.1)',
    'trace_ref',  'the caller''s audit handle when supplied; per-value '
                    || 'claim_id is the durable handle to the evidence'),

  degradation =
    'Predicate unreadable -> that predicate is listed in coverage.unavailable '
      || 'and degradation names predicate_unavailable; other predicates still '
      || 'answer. EVERY predicate unreadable -> UNAVAILABLE, never UNKNOWN. '
      || 'Unregistered predicate requested -> coverage.unregistered, never '
      || 'coverage.absent, because "no such fact" and "no such kind of fact" '
      || 'are different answers. Conflict -> both values returned plus a '
      || 'conflicts entry. Stale -> value returned with verdict STALE. '
      || 'Identity DISPUTED or merge chain corrupt -> UNAVAILABLE, never a '
      || 'guessed identity. Unauthorized -> DENIED, which must never look '
      || 'like empty (§6.2).',

  explainability =
    'Every value carries predicate, semantic_version, provenance tier and its '
      || 'cap, source kind, asserter, valid_from, observed_at, freshness '
      || 'verdict with the bound applied, and claim_id. No source_ref, no '
      || 'identifier value, no message text: explainability must not become a '
      || 'PII side channel. Narration by a model is permitted; generation of '
      || 'the explanation is not (§7.4).'
where code = 'knowledge.describe';


-- ── 2. service_interest, re-declared as a named binding (§8.1-8.2) ─────────
-- "Ten vertical capabilities, zero new implementations." service_interest is
-- knowledge.describe with one parameter fixed. Recording that as a binding is
-- what makes the extension claim testable rather than aspirational: the row
-- names its target and the parameters it pins, and the handler behind it is
-- the generic one.
--
-- kind moves ACT -> QUERY, which is a correction, not a reclassification of
-- convenience: it reads knowledge and changes nothing, so it is freely
-- retryable, and calling it ACT told the runtime the opposite.
update bic_tool_defs set
  kind           = 'QUERY',
  module         = 'bic.knowledge',
  semver         = '1.0.0',
  status         = 'LIMITED',
  binds_to       = 'knowledge.describe',
  binding_params = jsonb_build_object(
    'predicates', jsonb_build_array('core.party.declared_service_interest@1')),
  description    =
    'Named binding over knowledge.describe, fixed to the caller''s own '
      || 'declared service interest. No separate implementation.',
  -- Inherited from the binding target. Restated rather than left null because
  -- the §D1 completeness constraint applies to every QUERY row, and a caller
  -- reading THIS row must see the guarantee it is actually getting.
  freshness =
    'Inherited from knowledge.describe. declared_service_interest is '
      || 'volatility slow -> 180 days from observed_at, then STALE. A stale '
      || 'declaration is shown with its age, never dropped and never treated '
      || 'as current.',
  provenance_tiers = array[5]::smallint[],
  confidence_rule  =
    'Inherited from the 2C claim and capped at the tier-5 ceiling of 0.50 '
      || '(Article II.6: a customer-sourced fact is never worth more).',
  degradation      =
    'Inherited from knowledge.describe: DENIED, UNKNOWN and UNAVAILABLE are '
      || 'distinct rendered outcomes, and none of them renders as an empty '
      || 'list of interests.',
  explainability   =
    'Inherited from knowledge.describe. The rendered reply shows value, '
      || 'confidence, tier, asserter, observed_at and freshness verdict, and '
      || 'never the phone number that resolved the party.'
where code = 'service_interest';
