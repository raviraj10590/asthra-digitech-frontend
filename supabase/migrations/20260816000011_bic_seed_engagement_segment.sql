-- BIC 2A seed — the first predicate sourced from ORDINARY conversation.
--
-- WHY THIS PREDICATE, AND WHY NOW
-- -------------------------------
-- Measured production traffic: 754 inbound turns across 24 senders, of which
-- 47 of 50 Decision Records hit NO deterministic branch at all. Every
-- structured path is rare or unused — the welcome menu has never been tapped,
-- so core.party.declared_service_interest@1 has zero claims.
--
-- This predicate is different: it is detected inside maybe_alert_vip(), which
-- runs on ORDINARY FREE-FORM MESSAGES — where 94% of real traffic lives. No UI
-- path the customer has to discover, and no new behaviour asked of them.
--
-- DETERMINISTIC, NOT MODEL-DERIVED
-- --------------------------------
-- The value comes from VIP_REGEXES / ELECTION_REGEXES in webhook.py: fixed
-- regex and substring vocabularies in English and Kannada. No AI, no
-- extraction, no inference. The alternative candidate — extract_lead_info() —
-- calls gpt-4o-mini and returns free text, which is both tier 4 and a privacy
-- problem, so it was rejected.
--
-- TIER 5 EVEN THOUGH DETECTION IS EXACT
-- -------------------------------------
-- The DETECTION is deterministic; the CONTENT is a customer describing
-- themselves in their own words. IDD-2C §6 maps "what the customer claims" to
-- tier 5, and Article II.6 caps that at 0.50 permanently. A clean regex does
-- not make a self-description authoritative.
--
-- WHAT IS STORED: the label, and nothing else. Never the message, never the
-- matched keyword, never the phone number. The claim says only that this
-- party belongs to a segment.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'core.party',
  'engagement_segment',
  1,
  -- CLASSIFYING: it places the party in a category from a closed set, which is
  -- different machinery from a free-text DESCRIPTIVE value (2A §3.3).
  'CLASSIFYING',
  jsonb_build_object(
    'type', 'enum',
    -- Exactly the two the detector can produce. VIP wins when both match,
    -- mirroring the alert tag precedence in maybe_alert_vip() so a stored
    -- claim can never contradict an alert already sent to the owner.
    'values', jsonb_build_array('VIP', 'ELECTION')
  ),
  null,
  -- single: a party belongs to ONE segment at a time. A later different
  -- detection supersedes rather than accumulating (bic/claims.py reads
  -- cardinality to decide, per D12).
  'single',
  -- slow: a principal does not stop being an MLA next week, but a segment
  -- declared eight months ago is stale for outreach. That per-fact staleness
  -- is what a 2G capability will report rather than silently ignore.
  'slow',
  array['PERSON', 'ORGANIZATION']::text[],
  'ACTIVE',
  'raviraj',
  now(),
  'Engagement segment',
  'Which Asthra DigiTech engagement segment a party falls in, detected from '
    || 'deterministic keyword signals in ordinary WhatsApp conversation. VIP = '
    || 'a political or bureaucratic principal (MLA, MP, minister, corporator). '
    || 'ELECTION = campaign or constituency work. Customer self-description: '
    || 'provenance tier 5, confidence capped at 0.50 (Article II.6).',
  jsonb_build_array('VIP', 'ELECTION')
)
on conflict (namespace, concept, version) do nothing;
