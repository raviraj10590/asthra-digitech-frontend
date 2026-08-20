-- BIC 2G — knowledge.explain registered as a capability descriptor.
--
-- §2.1 #7: "knowledge.explain · EXPLAIN · Why do we believe this? ·
-- First-class, not a log (§7)". §7.1 makes the reason explicit: "If
-- explanation is only a log line, nothing consumes it and it rots. As a
-- capability it is called, tested, gated and audited like everything else."
--
-- ACTIVE / LIMITED — THE CONSUMER NOW EXISTS
-- ------------------------------------------
-- An earlier draft of this migration registered the row SHADOW/inactive
-- because nothing dispatched it. `#why` is that dispatch, so the row is
-- corrected to say what is true: the capability is reachable and one internal
-- command uses it. LIMITED rather than GENERAL for the same reason
-- knowledge.describe is LIMITED — status is a claim about EXPOSURE, and a
-- single owner-only command is not general availability.
--
-- NO TABLE. NO COLUMN. TWO INSERTS, both into the existing registry.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   inputs, outputs, freshness, provenance_tiers, confidence_rule,
   degradation, explainability)
values (
  'knowledge.explain',
  'Explain what we believe',
  'Why do we believe this? Justifies an already-retrieved knowledge.describe '
    || 'result. Retrieves nothing itself.',
  'EXPLAIN', 'bic.explain', '1.0.0',
  'STAFF', 1, false, false,
  true,             -- reachable: #why dispatches it (see the second row)
  'LIMITED',
  10, 400, 'basic',

  -- §3.1 inputs. The evidence is REQUIRED and is the whole input: this
  -- capability cannot fetch, so there is no entity/predicate slot to offer.
  -- A capability that could retrieve could retrieve DIFFERENTLY to suit the
  -- story it wanted to tell; removing the ability beats forbidding it.
  jsonb_build_object(
    'evidence',  jsonb_build_object(
        'type','knowledge.describe result','required',true),
    'principal', jsonb_build_object('type','Principal','required',false),
    'narrator',  jsonb_build_object(
        'type','callable(brief)->text','required',false,
        'note','injected; no provider is imported by the module')),

  -- §3.2 the guaranteed shape. Evidence rides along untouched — an
  -- explanation never REPLACES the structured result it explains.
  jsonb_build_object(
    'state',            jsonb_build_array('KNOWN','UNKNOWN','DENIED','UNAVAILABLE'),
    'explanation',      'deterministic, derived from records; always present',
    'narration',        'optional model prose; null when absent or rejected',
    'narration_source', jsonb_build_array('model', null),
    'narration_rejected','rejection reason when prose was refused',
    'questions',        jsonb_build_array('why_this_information','why_this_source',
                                          'why_not_another','what_confidence'),
    'evidence',         'verbatim copy of the describe values',
    'evidence_digest',  'sha256 over the evidence, checked after narration',
    'conflicts',        'carried unresolved; never adjudicated here',
    'coverage',         'verbatim',
    'freshness',        'verbatim',
    'confidence',       'vector + projected scalar + dominating dimension (§7.3)',
    'degraded',         'boolean with degradation[] naming each reason',
    'trace_ref',        'carried from the evidence; never minted here'),

  -- §3.3. This capability reads nothing, so it adds no staleness of its own.
  'Adds no staleness: no retrieval occurs. Every freshness verdict is carried '
    || 'verbatim from the knowledge.describe result being explained, and the '
    || 'explanation names the verdict and its volatility class per fact.',

  -- §3.1 provenance. Whatever the evidence carried, unchanged.
  array[0,1,2,3,4,5]::smallint[],

  -- §3.1 confidence: never re-derived, never inflated.
  'Never recomputed. The confidence vector is carried verbatim from the '
    || 'evidence; EXPLAIN adds only a projected scalar (minimum of the '
    || 'numeric dimensions, labelled as a projection) and NAMES the '
    || 'dominating dimension per §7.3. Language that promotes a tier cap — '
    || '"tier 1 / 0.90" becoming "highly certain" — is refused by the '
    || 'narration validator, because no IDD clause permits that transformation.',

  -- §6.1 declared degradation.
  'Narration refused (unsupported number, unsupported identifier, certainty '
    || 'language, PII, or empty) -> prose dropped, deterministic explanation '
    || 'returned, degradation names narration_rejected with the reason. '
    || 'Narrator unreachable -> narration_unavailable, explanation still '
    || 'returned. Conflicts present -> conflict_ladder_not_implemented, '
    || 'because §7.2 asks for the rung that settled it and no rung did. '
    || 'Evidence degraded -> inherited_from_evidence. DENIED -> the refusal '
    || 'is explained and NO evidence is attached. UNKNOWN and UNAVAILABLE get '
    || 'distinct explanations and are never merged into "no comment".',

  -- §7 what EXPLAIN returns.
  'The four questions of §7.2: why this information (slots, capabilities '
    || 'called, consulted/found/absent/unreadable, and that nothing was '
    || 'pruned per §3.5); why this source (source, tier, cap, asserted_by, '
    || 'source scheme, semantic_version, valid_from, observed_at, freshness '
    || 'verdict, evidence ref); why not another (competing claims, carried '
    || 'unresolved); what confidence (the vector, the projected scalar, the '
    || 'tier caps applied, and the dominating dimension). A model may narrate '
    || 'this material and may never generate it (§7.4).'
)
on conflict (code) do nothing;


-- ── #why — the composite COMMAND that consumes the capability ─────────────
-- §5.1: "Composition happens in the Context Plane, not inside the registry",
-- because Phase 1C proved that a registered handler invoking another
-- registered handler corrupts the outer audit row's db_queries. #why calls
-- knowledge.describe and knowledge.explain as LIBRARY calls from one handler,
-- exactly as #status composes at the dispatch site.
--
-- So this row deliberately sets NO binds_to. A binding (§8.2) fixes parameters
-- on ONE generic capability; #why composes TWO. Claiming a binding here would
-- describe the wrong relationship and hide the second call from anyone reading
-- the registry.
--
-- OWNER-ONLY, VIA THE EXISTING GATE. min_role = 'OWNER' and customer_safe =
-- false are read by policy.may_invoke() — the same function every other tool
-- passes through. No second authorization path, and no phone number is
-- hardcoded anywhere: authority comes from the roles table, not from a
-- constant in the source.
insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   inputs, outputs, freshness, provenance_tiers, confidence_rule,
   degradation, explainability)
values (
  'knowledge_why',
  'Why we believe this',
  'OWNER command #why. Identifies the party bound to the current conversation, '
    || 'calls knowledge.describe, then knowledge.explain, and renders the '
    || 'justification. Composite command, not a composite tool (§5.1).',
  'EXPLAIN', 'api.webhook', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  10, 900, 'basic',

  jsonb_build_object(
    'sender', jsonb_build_object(
        'type','transport-supplied identifier','required',true,
        'note','from the authenticated webhook payload, never from message text')),

  jsonb_build_object(
    'reply', 'WhatsApp text rendering the EXPLAIN envelope',
    'states', jsonb_build_array('KNOWN','UNKNOWN','DENIED','UNAVAILABLE',
                                'cannot_identify_party'),
    'shows', jsonb_build_array('predicate','value','tier','cap','confidence',
                               'freshness verdict','volatility class',
                               'asserted_by','source scheme','evidence ref',
                               'conflicts','absent coverage','confidence vector'),
    'never_shows', jsonb_build_array('phone','email','raw source_ref','wamid',
                                     'prompt','model context')),

  'Inherited from knowledge.describe via knowledge.explain: per-fact, from the '
    || '2A volatility_class, with the verdict shown beside every value.',

  array[0,1,2,3,4,5]::smallint[],

  'Never recomputed at any layer. The renderer prints the confidence vector and '
    || 'the dominating dimension as EXPLAIN produced them, and no wording is '
    || 'substituted for a number.',

  'Party not bound to this conversation -> a deterministic "cannot identify" '
    || 'reply that is explicitly neither a permission problem nor an outage; '
    || 'nothing is guessed from conversation text, because that is 2D matching '
    || 'and it is not implemented. Identity unreachable, knowledge unreadable, '
    || 'or explanation failure -> the exception TYPE only, never its body. '
    || 'Narration rejected or unavailable -> the deterministic explanation is '
    || 'still returned and the refusal is stated. UNKNOWN, DENIED and '
    || 'UNAVAILABLE render as three distinct replies and none renders empty.',

  'The full §7.2 set as produced by knowledge.explain, rendered for a human: '
    || 'why this information, why this source, why not another, what '
    || 'confidence. Conflicts are always shown and never pruned to shorten the '
    || 'message (§3.5).'
)
on conflict (code) do nothing;
