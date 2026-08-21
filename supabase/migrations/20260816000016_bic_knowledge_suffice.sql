-- BIC 2H — `#suffice`, the first consumer of the Context + Sufficiency layer.
--
-- WHAT IT ANSWERS, AND WHY IT IS NOT #why
-- ---------------------------------------
-- #why asks "what do we believe, and on what evidence". #suffice asks "is
-- that enough to DO this thing" — and the answer depends on the thing.
-- IDD-2H §4.4: sufficiency is a property of the (evidence, action) pair,
-- never of the evidence alone. The identical customer-declared fact is
-- sufficient to answer an enquiry (tier 1, floor 0.50) and insufficient to
-- price a transformer (tier 4, floor 0.95).
--
-- A COMPOSITE COMMAND, NOT A COMPOSITE TOOL (2G §5.1)
-- ---------------------------------------------------
-- Phase 1C established that a registered handler invoking another corrupts
-- the outer audit row's db_queries. #suffice reaches owner_context,
-- knowledge.describe and the Context Plane as LIBRARY calls from one handler,
-- exactly as #status and #why do. So this row sets NO binds_to: a §8.2
-- binding fixes parameters on ONE capability, and this composes several.
--
-- NO MODEL RUNS. IDD-2H I11: "Assembly makes no AI calls." The verdict is
-- computed from records by bic/context.py. A model may narrate it later; it
-- may never decide it.
--
-- OWNER-ONLY, VIA THE EXISTING GATE. min_role and customer_safe are read by
-- policy.may_invoke — the same function every other tool passes through. No
-- second authorization path, and no phone number is hardcoded anywhere.
--
-- NO TABLE. NO COLUMN. ONE INSERT.

insert into bic_tool_defs
  (code, label, description, kind, module, semver,
   min_role, risk_tier, side_effects, customer_safe, active, status,
   timeout_seconds, expected_latency_ms, audit_level,
   inputs, outputs, freshness, provenance_tiers, confidence_rule,
   degradation, explainability)
values (
  'knowledge_suffice',
  'Is there enough to proceed?',
  'OWNER command #suffice <goal>. Assembles a Business Context Packet for the '
    || 'currently selected customer and returns the IDD-2H sufficiency verdict.',
  'QUERY', 'bic.context', '1.0.0',
  'OWNER', 1, false, false,
  true,
  'LIMITED',
  10, 1200, 'basic',

  jsonb_build_object(
    'sender',  jsonb_build_object(
        'type','transport-supplied identifier','required',true,
        'note','from the authenticated webhook payload, never message text'),
    'goal_id', jsonb_build_object(
        'type','registered goal id','required',true,
        'note','named by the caller, NEVER inferred from free text — a goal '
               || 'sets the evidence bar, so inferring it would let a '
               || 'customer''s phrasing lower that bar')),

  jsonb_build_object(
    'verdict', jsonb_build_array('PROCEED','CLARIFY','RETRIEVE','ESCALATE','REFUSE'),
    'states',  jsonb_build_array('NO_CUSTOMER_CONTEXT','UNKNOWN_GOAL','UNAVAILABLE'),
    'shows',   jsonb_build_array('goal','risk tier','confidence floor',
                                 'known facts with tier/cap/confidence/freshness',
                                 'missing slots with class and reason',
                                 'conflicts with severity and consequence',
                                 'weakest fact','degradation','next action'),
    'never_shows', jsonb_build_array('phone','email','raw source_ref','wamid',
                                     'packet id','evidence refs','prompt')),

  'Inherited per-fact from knowledge.describe (2A volatility class). Tiers 1-2 '
    || 'accept a STALE fact and record the degradation; tiers 3-4 do not accept '
    || 'it at all, so a stale fact cannot silently fill a high-risk slot.',

  array[0,1,2,3,4,5]::smallint[],

  'Never recomputed. Facts carry confidence from the 2C claim; the PACKET '
    || 'carries a verdict, not a number (IDD-2H C2 — a packet-level confidence '
    || 'scalar would be an average over unlike things). Floors are the §4.4 '
    || 'table: tier 1 = 0.50, 2 = 0.60, 3 = 0.80, 4 = 0.95 plus human approval. '
    || 'Lowering one is an L5 Structural decision (§4.6), not a code edit.',

  'Unknown goal -> UNKNOWN_GOAL naming the registered set; never a default '
    || 'goal, which would answer a different question at a different risk '
    || 'tier. No customer selected -> NO_CUSTOMER_CONTEXT, explicitly neither '
    || 'a permission problem nor an outage. Context or knowledge unreadable -> '
    || 'UNAVAILABLE with the exception TYPE only. Principal not authorized -> '
    || 'the capability is NOT CALLED (§3.2: filtering after retrieval means '
    || 'the data was fetched). Budget pruned evidence a slot needed -> REFUSE '
    || 'rather than answering on what fitted (§5.4).',

  'The packet itself: which slots the goal required, which were filled and by '
    || 'what evidence, which are missing and in which of the five §4.3 classes, '
    || 'the four sufficiency conditions individually, the confidence floor '
    || 'applied, unresolved conflicts with severity computed from the decision '
    || 'at hand (§6.3), and the weakest contributing fact by name.'
)
on conflict (code) do nothing;
