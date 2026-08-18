-- BIC 2A seed — the first predicate to reach production.
--
-- REGISTRY IS DATA (IDD-2A P5). This migration registers a concept the same
-- way any future one is registered: an INSERT. No Python enum, no branch, no
-- deployment coupling. A new industry's vocabulary arrives exactly like this.
--
-- WHY THIS PREDICATE FIRST
-- ------------------------
-- The value comes from a list WE authored: the customer taps a row in the
-- WhatsApp welcome menu and webhook.py maps row_id → service through a dict.
-- No model, no parsing, no free text. Extraction error is structurally
-- impossible — either a known row_id arrived or it did not.
--
-- CARDINALITY IS `single` AND THAT IS A REAL DECISION
-- ---------------------------------------------------
-- The fact recorded is "the service this party most recently asked about",
-- which a later tap should replace. `multi` would mean "every service they
-- have ever expressed interest in", where nothing supersedes anything. The
-- registry is the authority for this: bic/claims.py reads `cardinality` to
-- decide whether supersession is per-predicate or per-value (D12).
--
-- Note `svc_other` is absent from the value space. It means "no service
-- determined yet" — an absence, and an absence is never recorded as a value.

insert into bic_concepts (
  namespace, concept, version, category, value_space, unit,
  cardinality, volatility_class, applies_to,
  lifecycle, activated_by, activated_at,
  label, description, examples
) values (
  'core.party',
  'declared_service_interest',
  1,
  -- CLASSIFYING: it places the party in a category from a closed set, which
  -- is different machinery from a free-text DESCRIPTIVE value (2A §3.3).
  'CLASSIFYING',
  jsonb_build_object(
    'type', 'enum',
    'values', jsonb_build_array(
      'Social Media ನಿರ್ವಹಣೆ',
      'Website / App',
      'Election Campaign',
      'AI Chatbot',
      'Digital Ads',
      'Govt Schemes',
      'Design & Branding'
    )
  ),
  null,
  'single',
  'slow',
  array['PERSON', 'ORGANIZATION']::text[],
  -- Seeded ACTIVE: the value space is fixed by a menu that already exists in
  -- production, so there is nothing to draft. The activation audit records a
  -- human, as IDD-2A V2 requires — freezing a meaning is never anonymous.
  'ACTIVE',
  'raviraj',
  now(),
  'Declared service interest',
  'The Asthra DigiTech service a party selected from the WhatsApp welcome '
    || 'menu. Customer self-declaration: provenance tier 5, confidence capped '
    || 'at 0.50 (Article II.6).',
  jsonb_build_array('Website / App', 'Election Campaign')
)
on conflict (namespace, concept, version) do nothing;
