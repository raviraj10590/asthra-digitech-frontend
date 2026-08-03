# IDD 2G — Knowledge Capabilities

**Status:** Design · No implementation · 2026-08-03
**Depends on:** 2A · 2B · 2C · 2D · 2E · 2F (all frozen) · BIC v1.0 Tool Registry (Phase 1B, production)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Two decisions that shape everything below

### D1 — This is not a new registry. It is the existing one.

Phase 1B built a Tool Registry with policy gating, invocation audit and no-bypass enforcement. It is in production, mutation-verified, with 13 registered tools and zero bypass violations.

> **Knowledge Capabilities register in the *same* registry, pass the *same* Policy Gate, and write the *same* audit trail.**

Building a parallel "knowledge registry" would create a second authorization path — and **two authorization paths is one authorization hole**. The C-1 finding in Phase 1C was exactly that: a set of operations reaching the world without passing the gate. That lesson cost a day to find and must not be re-learned.

What changes is one field: `kind`.

| `kind` | Effect | Examples |
|---|---|---|
| `QUERY` | Reads knowledge | resolve, find, describe, timeline |
| `ASSERT` | Adds knowledge | record a claim |
| `EXPLAIN` | Justifies knowledge | why do we believe this |
| `SUBSCRIBE` | Streams change | watch a commitment |
| `ACT` | **Changes the world** | send_brochure, add_role *(Phase 1)* |

### D2 — A capability per object type does not scale, and would break the 100-domain thesis

The proposed catalogue lists *Find Party, Find Customer, Find Project, Find Offering, Find Commitment, Find Documents, Find Communications…*

**Two problems:**

**Find Party and Find Customer are the same capability.** Customer is a *role* (2D §1.4), not a type. Making them separate forces one capability per role — Find Supplier, Find Employee, Find Beneficiary, Find Patient, Find Contractor — with no upper bound.

**Every new vertical would add capabilities the Brain must learn.** A hospital adds Find Encounter, Find Result; construction adds Find RFI, Find DrawingRevision. Within five industries the Brain knows about eighty capabilities — which directly contradicts the stated objective that *"new industries add capabilities without changing the Business Brain."*

> **Recommendation: a small set of GENERIC capabilities, parameterised by registry concepts — plus named bindings as registry rows for readability.**

```
GENERIC (fixed, ~13 implementations — the Brain learns these once)
    knowledge.find(type=Party, role=customer, filters=…)

NAMED BINDING (a registry ROW — zero new implementation)
    sales.find_customer  ⇒  knowledge.find(type=Party, role=customer)
    health.find_patient  ⇒  knowledge.find(type=Party, role=patient)
```

Named bindings give a domain expert readable vocabulary. The implementation count stays constant as domains multiply. **This is the mechanism that makes the extension claim true rather than aspirational.**

---

## 1 · What a Knowledge Capability Is

> **A Knowledge Capability is a declared, policy-gated, audited contract for obtaining or asserting business knowledge — expressed in business terms, with provenance and freshness attached.**

### 1.1 Differentiated from six neighbours

| | What it exposes | Who may call | Audited | Provenance | Stable when storage changes |
|---|---|---|---|---|---|
| **Database** | Tables, rows | Anyone with credentials | No | No | ❌ |
| **API** | Endpoints, payloads | Whoever holds the key | Sometimes | No | ❌ |
| **Repository** | Storage operations per aggregate | The application | No | No | ⚠️ |
| **Search** | Ranked text matches | Caller | No | Weak | ❌ |
| **Query** | An expression over a schema | Whoever can write one | No | No | ❌ |
| **Tool** *(Phase 1)* | An action on the world | Policy-gated | ✅ | n/a | ✅ |
| **Knowledge Capability** | **A business question, answered with provenance** | **Policy-gated** | ✅ | ✅ | ✅ |

### 1.2 The distinctions that carry weight

**Versus a Repository.** A repository exposes *storage operations* — `save`, `findById`, `delete`. Those are shaped by persistence. A capability exposes a *business question* — *"who is this party and how confident are we?"* — and is shaped by the business. When storage changes, repositories change; capabilities do not.

**Versus an API.** An API is a transport contract. A capability is a *semantic* contract: it declares which registry concepts it reads, what freshness it guarantees, what it does when degraded, and what provenance its results carry. Two APIs returning the same JSON can mean different things; two capabilities cannot.

**Versus Search.** Search returns *matches*. A capability returns *knowledge* — resolved, conflict-checked, provenance-tagged. Search is a **retrieval strategy** available *inside* a capability (§4.4), never a capability boundary in itself.

**Versus a Tool.** Same registry, same gate, same audit. The difference is `kind`: a Tool changes the world, a Knowledge Capability changes what we know. The separation matters because **a QUERY can be retried freely and an ACT cannot.**

### 1.3 The rule the Brain lives by

> **The Brain requests capabilities. It never knows how they are satisfied.**

No table names, no SQL, no index choices, no vector stores, no cursors, no row counts in any capability output. If a storage concept appears in a result, the boundary has leaked — and the Brain becomes coupled to a storage decision it cannot see.

---

## 2 · Capability Catalogue

### 2.1 The generic core — thirteen capabilities

| # | Capability | Kind | Purpose | Why it exists as its own capability |
|---|---|---|---|---|
| 1 | `knowledge.resolve` | QUERY | Identifiers → Party | Identity resolution has **unique rules** (2D): sovereign vs contact identifiers, no auto-merge on phone, PROVISIONAL states. Not a generic find |
| 2 | `knowledge.find` | QUERY | Entities of a type matching criteria | The workhorse. Replaces every proposed *Find X* |
| 3 | `knowledge.describe` | QUERY | All current assertions about an entity | Conflict-resolved, provenance-tagged (§3.4) |
| 4 | `knowledge.traverse` | QUERY | Follow relationships from an entity | Graph traversal has **depth and class limits** (2A §4.1) a generic find cannot express |
| 5 | `knowledge.timeline` | QUERY | Temporal view of an entity | Bitemporal — *"as we knew it at T"*. Fundamentally different from a filtered find |
| 6 | `knowledge.search` | QUERY | Lexical + semantic candidates | Returns **candidates**, never facts (§4.4) |
| 7 | `knowledge.explain` | EXPLAIN | Why do we believe this? | **First-class, not a log** (§7) |
| 8 | `knowledge.assert` | ASSERT | Record a new claim | The only write path into the knowledge plane |
| 9 | `knowledge.subscribe` | SUBSCRIBE | Notify on change | Commitment due, state transition |
| 10 | `oi.precedent` | QUERY | Comparable past decisions + outcomes | **Structural** similarity, outcome-weighted (2E §9) |
| 11 | `oi.lessons` | QUERY | Applicable lessons, scoped | Carries scope, expiry, contradicting evidence (2E §5) |
| 12 | `policy.lookup` | QUERY | Rules in force, as of a time | Policy is versioned; *"as of then"* is required for replay |
| 13 | `policy.validate` | QUERY | Does this proposal violate a rule? | **Pure and total** — the Decision Engine's gate 6 |

### 2.2 How every proposed capability maps

| Proposed | Realised as |
|---|---|
| Find Party | `knowledge.resolve` or `knowledge.find(type=Party)` |
| **Find Customer** | `knowledge.find(type=Party, role=customer)` — **a role, not a type** |
| Find Project / Offering / Commitment | `knowledge.find(type=…)` |
| Find Documents | `knowledge.find(type=Document, …)` |
| Find Communications | `knowledge.find(type=Interaction, …)` |
| Find Similar Decisions | `oi.precedent` |
| Find Lessons | `oi.lessons` |
| Find Policies | `policy.lookup` |
| Find Organizational Experience | `knowledge.describe` — **experience is derived knowledge** (2E §6.1) |
| Find Related Assertions | `knowledge.describe` / `knowledge.traverse` |
| Timeline Retrieval | `knowledge.timeline` |
| Relationship Traversal | `knowledge.traverse` |
| Semantic Search | `knowledge.search` |
| Constraint Validation | `policy.validate` |
| Business Rule Lookup | `policy.lookup` |
| **Context Retrieval** | **Not a capability — see §5.1** |

**Eighteen proposed capabilities collapse to thirteen generic ones**, and the thirteen do not grow when a vertical is added.

### 2.3 Why `resolve` is separate from `find`

The one place a generic answer would be wrong.

Identity resolution (2D §3) carries rules nothing else does: four identifier classes with different merge authority, phone never auto-merging, PROVISIONAL as a normal outcome, DISPUTED surfaced rather than resolved. Folding it into `find` would either lose those rules or force `find` to carry them for every type — and a generic find that silently applies merge logic is a false-merge waiting to happen.

---

## 3 · Capability Contracts

### 3.1 What every capability declares

Extending the Phase 1B descriptor already in production:

```
CAPABILITY DESCRIPTOR
├── identity        id · module · semver · kind
├── purpose         the business question, in business language
├── inputs          typed slots: required, optional, validation
├── outputs         guaranteed shape + guaranteed fields
├── authorization   min_role · visibility · acl · tenant scope        ← 1B
├── risk            risk_tier · side_effects · reversibility          ← 1B
├── performance     cost_class · latency_class · timeout · rate_limit ← 1B
├── freshness       guaranteed staleness bound (§3.3)
├── provenance      which tiers results may carry
├── confidence      how result confidence is derived and capped
├── degradation     DECLARED behaviour when degraded (§6)
├── explainability  what EXPLAIN returns for this capability
└── status          SHADOW | LIMITED | GENERAL | DEPRECATED (+ successor)
```

Fields marked ← 1B already exist in `bic_tool_defs`. **This is an extension, not a new schema.**

### 3.2 Every result carries its own trustworthiness

> **A capability never returns a bare value.**

```
CAPABILITY RESULT
├── value / values[]
├── per-item metadata
│   ├── provenance      source, tier, asserted_by
│   ├── confidence      capped by tier (2C)
│   ├── as_of           the world time this was true
│   └── observed_at     when we learned it
├── conflicts[]         unresolved contradictions — NEVER omitted (§3.5)
├── coverage            what was searched, what was not
├── freshness           oldest contributing fact + staleness verdict
├── degraded            true + reason, if operating below full
└── trace_ref           for EXPLAIN
```

A caller that ignores this metadata is misusing the capability — but it **cannot claim it was unavailable.**

### 3.3 Freshness is a guarantee, not a hope

Every capability declares a staleness bound. If it cannot meet it, it **says so in the result** rather than silently returning older data.

Bounds derive from the predicate's volatility class (2A §3.5), so they are per-fact rather than global: a founding date at five years old is fresh; a credit limit at nine days may not be.

### 3.4 Conflict resolution happens below the Brain

The deterministic ladder (2C §5.2) is applied **inside** the capability. The Brain receives the resolved value **plus any unresolved conflicts**.

**Rationale.** The ladder is deterministic and total, so it can execute anywhere — but if the Brain applied it, every consumer would need to implement it identically, and they would diverge. One implementation, below the boundary, invoked identically by every caller.

### 3.5 Unresolved conflicts are never omitted

Per 2C §5.3 they cannot be budget-pruned. Restated here because this is the boundary where it would be tempting: a caller asking for one value and receiving one value plus a conflict flag may ignore the flag — but **the capability must never make that choice on the caller's behalf.**

### 3.6 Failure behaviour is declared, not improvised

Every capability declares what it does when it cannot fully answer. `"unspecified"` is not a valid declaration — see §6.

---

## 4 · Retrieval Strategies

Six strategies. **Choosing wrongly is the most common cause of a correct-looking wrong answer.**

| # | Strategy | Use when | Never use when |
|---|---|---|---|
| 1 | **Identity lookup** | You have an identifier | You have a description |
| 2 | **Relationship traversal** | You have an entity and want connected ones | You want entities matching a property |
| 3 | **Timeline** | The question is *when* or *what changed* | You want current state only |
| 4 | **Semantic retrieval** | You have a description, not an identifier | **You need a fact** — see §4.4 |
| 5 | **Pattern retrieval** | You want aggregate behaviour over many entities | You want one entity's facts |
| 6 | **Similarity retrieval** | You want comparable *situations* (2E precedent) | You want comparable *text* |

### 4.1 Identity lookup — always try first

Cheapest, most certain, fully explainable. If an identifier exists, nothing else should run.

### 4.2 Relationship traversal — bounded by class

Per 2A §4.1, every relationship class declares a maximum depth: Structural 5, Participation 2, Transactional 2, Evidential 2, **Associative 1**.

**Traversal must never pass *through* a supernode** (2D — the Company entity connects to everything), only terminate at one. Unbounded traversal from a supernode returns the entire graph, slowly.

### 4.3 Timeline — bitemporal by default

Every timeline query accepts an as-of time and defaults to *now*. Because it is bitemporal, *"what did we believe on 12 March?"* is a parameter, not a different capability.

### 4.4 Semantic retrieval returns candidates, never facts

> **Search finds things to look at. It never establishes that something is true.**

Three rules:

1. Results are **candidates** requiring confirmation from an identity or relationship path
2. A semantic match **alone may not satisfy** a tier ≥ 3 decision
3. Every result carries **why it matched** — an unexplainable match is unusable evidence

This prevents the common failure where an embedding match on a document becomes an asserted fact with no provenance chain.

### 4.5 Similarity is structural, never textual

Restated from 2E §9.2 because this is where it is implemented. Comparison is over **category, risk level, slot profile, party characteristics, temporal context** — not over text. Two decisions worded alike may be entirely different; two identical situations described differently would never match.

---

## 5 · Capability Composition

### 5.1 Context Assembly is not a capability — challenge

The brief lists *Context Retrieval* in the catalogue. It cannot be one, for a reason established in production.

Phase 1C found that **a registered handler calling other registered handlers corrupts the invocation audit**: `invoke()` resets a shared query counter, so a nesting handler under-reports the work its own audit row claims. `#status` was rebuilt as a composite *command* rather than a composite *tool*, and the rule was made test-enforced: **no registered handler may call another.**

That rule holds here.

> **Composition happens in the Context Plane, not inside the registry.**

```
BRAIN  ── "I need context for task T" ──►  CONTEXT PLANE
                                              │  calls capabilities
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            knowledge.resolve         knowledge.describe          oi.precedent
                    └─────────────────────────┼─────────────────────────┘
                                              ▼
                              BUSINESS CONTEXT PACKET
                              (typed, auditable, replayable)
```

The Context Plane is **not** in the registry. It is a plane that *calls* the registry — so every constituent call is independently gated and audited, and the audit trail shows exactly what was consulted.

### 5.2 The five named compositions

Each is a **Context Plane recipe** — a declared list of capability calls with parameters. Recipes are configuration; **no new capability is implemented.**

| Composition | Capabilities invoked |
|---|---|
| **Customer Summary** | `resolve` → `describe` → `traverse`(commitments, invoices) → `timeline` → `oi.precedent` |
| **Project Brief** | `find`(project) → `describe` → `traverse`(tasks, team, assets) → `timeline` → `oi.lessons` |
| **Sales Context** | `resolve` → `describe` → `traverse`(open leads, quotations) → `oi.precedent` → `policy.lookup`(discount) |
| **Government Proposal** | `find`(tender) → `policy.lookup`(eligibility) → `traverse`(past submissions) → `oi.lessons` → `policy.validate` |
| **Manufacturing Context** | `find`(unit) → `describe` → `traverse`(BOM, certificates) → `policy.lookup`(conformity) → `oi.precedent` |

**All five use the same thirteen capabilities.** Adding a sixth composition adds a recipe row, not an implementation.

### 5.3 Why recipes are declared rather than assembled by the model

A model-assembled retrieval plan would be non-deterministic, unauditable, and unrepeatable — and replay would be impossible, because the same question could gather different evidence on different runs.

**The model may propose a recipe; the Context Plane validates it against the registry and the principal's authorization before executing.** Same pattern as the Decision Engine: AI proposes, the deterministic layer decides.

---

## 6 · Failure Handling

### 6.1 Every capability declares its degradation

`"unspecified"` is not valid. This is enforced at registration, because an undeclared failure mode becomes an improvised one at 2 a.m.

| Failure | Behaviour | Never |
|---|---|---|
| **Knowledge unavailable** | Return `degraded=true`, empty or partial, **coverage stated** | Return empty as though complete |
| **Conflicting facts** | Return resolved value **plus conflicts** | Silently pick |
| **Low confidence** | Return with confidence attached | Suppress, or inflate |
| **Missing relationships** | Return what exists, **name what is missing** | Imply completeness |
| **Stale information** | Return **with age and staleness verdict** | Return silently as current |
| **Timeout** | Partial result + `degraded` + what was not reached | Block past the budget |
| **Source unreachable** | Cached with age, or explicit absence | Fabricate |
| **Unauthorized** | **Denial** — audited, distinct from empty | Return empty *(indistinguishable from "no data")* |

### 6.2 The distinction that matters most

> **"You may not see this" and "there is nothing here" must never look the same.**

Returning empty on a denial silently teaches the caller that a party has no invoices when in fact they have thirty. Every downstream conclusion is then wrong, and nothing surfaces it.

### 6.3 An outage must not present as an authorization failure

The mirror image, learned in Phase 1C: a registry outage fails closed to an empty registry, so every tool answered *"not permitted"* — sending diagnosis toward roles instead of connectivity.

**Capability results distinguish `DENIED` from `UNAVAILABLE`.** Both are failures; they have different causes and different fixes.

### 6.4 Degradation is reported, never hidden

A degraded result reaching the Sufficiency Gate (Brain spec) causes a refusal with specifics rather than a confident answer on partial data. **This only works if degradation is visible** — a capability that silently returns less is worse than one that fails.

---

## 7 · Explainability

### 7.1 EXPLAIN is a capability kind, not a log

Restated from the Knowledge Architecture because this is where it is realised. If explanation is only a log line, nothing consumes it and it rots. As a capability it is called, tested, gated and audited like everything else.

### 7.2 The four questions

| Question | Answered from |
|---|---|
| **Why this information?** | Slots requested, capabilities called, ranking scores, what was pruned and why |
| **Why this source?** | Provenance chain — source, tier, asserted_by, the conflict rung that settled it |
| **Why not another?** | Competing claims, and the rung at which each was outranked |
| **What confidence?** | The confidence **vector** (2C), the projected scalar, the tier caps applied, and the weakest relevant dimension |

### 7.3 Confidence is explained as a vector, never a number

A single figure hides which dimension is weak. *"0.52"* could mean *"good evidence, badly stale"* or *"fresh but weakly sourced"* — and those demand different responses. **EXPLAIN returns the vector and names the dominating dimension.**

### 7.4 Two rules

**Content comes from records; a model may narrate but never generate.** A model-authored explanation is a plausible fiction fitted to the answer — convincing, unfalsifiable, and worse than silence.

**Explanation must be user-facing.** Kept as an internal debug tool, it decays unnoticed. Users notice when an explanation is wrong.

---

## 8 · Future Expansion

### 8.1 What a vertical actually adds

| Extension point | Mechanism | New implementation? |
|---|---|---|
| New entity types | 2A registry rows | **No** |
| New predicates | 2A registry rows | **No** |
| New relationships | 2A registry rows | **No** |
| **New named capabilities** | **Registry bindings over the thirteen** | **No** |
| New retrieval recipes | Context Plane configuration | **No** |
| New source systems | An adapter | **Adapter only** |
| New policies | Policy rows | **No** |

### 8.2 Worked bindings

```
health.find_patient      ⇒ knowledge.find(type=Party, role=patient)
health.encounter_history ⇒ knowledge.timeline(entity=Party, filter=Encounter)
mfg.unit_certificates    ⇒ knowledge.traverse(from=TransformerUnit,
                                              rel=certified_by, depth=1)
mfg.conformity_rules     ⇒ policy.lookup(scope=BIS, as_of=…)
gov.grievance_history    ⇒ knowledge.timeline(entity=Party, filter=Grievance)
gov.scheme_eligibility   ⇒ policy.validate(proposal, scope=Scheme)
legal.matter_documents   ⇒ knowledge.find(type=Document, refs=Matter)
edu.student_progress     ⇒ knowledge.timeline(entity=Party, filter=Assessment)
constr.open_rfis         ⇒ knowledge.find(type=RFI, state=open)
retail.basket_history    ⇒ knowledge.timeline(entity=Party, filter=Basket)
```

**Ten vertical capabilities. Zero new implementations. Zero Brain changes.**

### 8.3 The one place a vertical changes behaviour

Not the capability set — the **declared parameters**:

- **Freshness bounds** — a hospital's vitals staleness tolerance is minutes; a land registry's is years
- **Traversal depth** — construction drawing chains run deeper than retail baskets
- **Visibility rules** — legal privilege is **per-fact**, not per-role ⚠️

**Legal privilege is flagged for validation before a legal client is signed.** The frozen `visibility` + `acl_roles` model assumes role-scoped visibility. A single message that is partly privileged may not fit, and finding that out during implementation would be expensive.

---

## 9 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Knowledge Capabilities register in the **existing** registry — no parallel registry exists |
| 2 | Thirteen generic capabilities defined; named vertical capabilities are **registry bindings** |
| 3 | Every capability declares freshness, provenance, degradation and explainability |
| 4 | `kind` distinguishes QUERY / ASSERT / EXPLAIN / SUBSCRIBE / ACT |
| 5 | Context Assembly is **not** a registered capability |
| 6 | Every result shape carries provenance, confidence, conflicts, coverage, freshness |
| 7 | Six retrieval strategies defined with use and misuse conditions |
| 8 | Five named compositions defined as **recipes**, not implementations |

### Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 9 | Any capability output inspected for storage concepts | **No** table names, SQL, cursors or row counts |
| 10 | Call a capability without authorization | **DENIED and audited** — distinguishable from empty |
| 11 | Query knowledge the principal may not see | **DENIED**, never silently empty |
| 12 | Source unreachable | `UNAVAILABLE` — **distinct from** `DENIED` |
| 13 | Two tier-0 sources conflict | Resolved value **plus** the conflict, never silent |
| 14 | Conflict present, token budget tight | **Conflict is not pruned** |
| 15 | Stale data returned | Age and staleness verdict attached |
| 16 | Capability times out | Partial result + `degraded` + what was not reached |
| 17 | Register a capability with `degradation = unspecified` | **REJECTED** |
| 18 | A registered handler calls another capability | **REJECTED** — nesting rule (§5.1) |
| 19 | Semantic search result used alone for a tier-3 action | **REJECTED** — candidates, not facts |
| 20 | Semantic match returned | Carries **why it matched** |
| 21 | Traverse an Associative edge to depth 2 | **REJECTED** — max depth 1 |
| 22 | Traverse *through* a supernode | **REJECTED** — may terminate at one only |
| 23 | Timeline query as of a past date | Belief at that date, **not** current belief |
| 24 | `oi.precedent` where 3 of 4 precedents failed | **Failures surfaced**, not filtered |
| 25 | `EXPLAIN` on any returned fact | Source, chain, competing claims, confidence **vector** |
| 26 | Model asked to generate an explanation | **REJECTED** — narration only |
| 27 | Model proposes a retrieval recipe | **Validated** against registry and authorization before execution |

### Extensibility — the criteria that matter most

| # | Test | Expected |
|---|---|---|
| 28 | Add ten vertical capabilities across five industries (§8.2) | **Registry bindings only** |
| 29 | Count new capability implementations across 28 | **Exactly zero** |
| 30 | Count Brain changes across 28 | **Exactly zero** |
| 31 | Add a sixth named composition | **Recipe row only** |

### Non-regression

| # | Criterion |
|---|---|
| 32 | Zero application code touched |
| 33 | Phase 1C suite green (226 tests); no-bypass invariant intact |
| 34 | Compatible with 2A–2F; no frozen concept modified |
| 35 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 29 is the acceptance test for this slice.** Everything else proves the layer is well-formed. Only 29 proves it is a *platform*: ten vertical capabilities, five industries, **zero new implementations**. If a vertical needs a new capability implemented, the generic set is wrong — and it is far cheaper to discover that here than after three industries are live.

---

## 10 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | A parallel knowledge registry appears "temporarily" | **High** | D1. One registry, enforced by the same AST invariant as Phase 1C |
| **R2** | Capability-per-object-type creeps back in | **High** | D2. Named bindings satisfy the readability urge without new implementations |
| **R3** | Storage concepts leak into outputs | **High** | Criterion 9, checked structurally |
| **R4** | Denial returned as empty | **High** | §6.2. The failure is silent and corrupts every downstream conclusion |
| **R5** | Semantic search results treated as facts | **High** | §4.4. Candidates require a confirming path |
| **R6** | Composition implemented as nested capabilities | Medium | §5.1. Already test-enforced in production |
| **R7** | Freshness declared but unenforced | Medium | Bound is part of the contract; violation reported in the result |
| **R8** | Legal privilege does not fit role-scoped visibility | Medium | §8.3. **Validate on paper before signing a legal client** |

---

## 11 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **One registry.** Knowledge Capabilities extend the Phase 1B registry — no parallel system
2. **Thirteen generic capabilities**, with vertical capabilities as registry bindings
3. **Customer is a role parameter**, not a capability — and by extension every role
4. **Context Assembly is not a capability** — composition lives in the Context Plane
5. **No storage concepts in outputs** — ever
6. **`DENIED` ≠ `UNAVAILABLE` ≠ empty** — three distinct outcomes
7. **Semantic search returns candidates, never facts**
8. **Conflict resolution happens below the Brain**, and conflicts are always surfaced
9. **Degradation must be declared** at registration; `unspecified` is rejected
10. **EXPLAIN is a capability**, returning a confidence vector rather than a number

Item 2 is the one to think hardest about. **It trades immediate readability for long-term stability** — `knowledge.find(type=Party, role=customer)` reads worse than `find_customer`, and named bindings recover most of that.

But the alternative compounds: one capability per object type per vertical means the Brain's surface grows with every industry, and the claim that new domains need no Brain changes quietly stops being true. That claim is the thesis of the entire platform.
