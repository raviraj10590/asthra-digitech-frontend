# IDD 2A — Semantic Registry

**Status:** Design · No implementation · 2026-08-03
**Slice:** Phase 2A, first slice of the Business Knowledge Layer
**Governed by:** BIC v1.0 Constitution (frozen) · Business Knowledge Architecture (frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · What this slice is, and what it is not

The Semantic Registry is **the vocabulary**. It holds no customer, no order, no message — not one row of business data. It answers exactly one question:

> *What does this concept mean, and which version of that meaning are we using?*

**Why it is first.** Every knowledge module reads its meaning from here. Build a module first and its vocabulary becomes implicit in its code — and implicit vocabulary cannot be versioned, cannot be extended by a domain expert, and cannot support a second industry without a rewrite.

**The 10-year test.** A predicate defined today must still be readable, unambiguous and correctly interpreted in 2036 — including by code that has been rewritten several times, and including for assertions written under a definition that has since been superseded.

---

## 1 · Registry Principles

Five rules. Everything else in this document follows from them.

### P1 — Every concept has a unique, stable, namespaced identifier

```
<namespace>.<concept>@<version>

core.party.legal_name@1
core.commitment.due_on@1
mfg.transformer.kva_rating@1
health.encounter.discharge_on@1
```

**Namespacing is not decoration.** It is what allows a Knowledge Package to add `mfg.unit` without colliding with `realestate.unit`. An unqualified name is rejected at registration.

**Semantic identifiers are readable — unlike instance identifiers, which must be meaningless.** These are opposite rules and both are correct. An instance key encoding business meaning becomes a business rule that will change. A *vocabulary* key is the meaning itself, and immutability (P2) is what keeps it stable.

### P2 — Meanings are immutable

Once a concept reaches `ACTIVE`, its **semantic fields can never change**.

### P3 — A new meaning is a new version, never an edit

`credit_limit@1` and `credit_limit@2` are different concepts that share a name. Assertions written under `@1` stay `@1` forever.

### P4 — Existing meanings are never modified, only superseded

Supersession is explicit and directional: `@1` declares `replaced_by: @2` and a **compatibility relation** (§6). Nothing is silently rewritten.

### P5 — The registry is data, not code

A domain expert must be able to define a predicate without an engineer. If defining `kva_rating` requires a deployment, the 100-domain thesis is already dead.

---

### The distinction P2 depends on: semantic vs presentational fields

Rules P2–P4 are useless without saying precisely *what* is immutable. Without this, either nothing can be fixed (typos are frozen forever) or everything drifts (meaning changes under cover of "wording").

| **SEMANTIC — frozen at ACTIVE** | **PRESENTATIONAL — editable forever** |
|---|---|
| identifier and namespace | display label |
| definition (the normative sentence) | description prose, help text |
| semantic class / category | examples |
| value space (type, enumeration, range) | localised names (kn-IN, hi-IN) |
| unit and unit system | tags, documentation links |
| cardinality | display ordering, grouping |
| identifying? (feeds entity resolution) | icon, colour |
| volatility class | |

**The test:** *could a reasonable person, reading only this field, draw a different conclusion about which real-world facts satisfy the predicate?* If yes, it is semantic. If no, presentational.

Fixing a Kannada translation must never mint a version. Changing whether `credit_limit` means approved exposure or available headroom must always mint one.

---

## 2 · Entity Categories

### 2.1 Challenging the proposed list

The brief proposes: *Party, Organization, Asset, Product, Document, Event, Activity, Communication, Commitment, Location, Financial, Policy, Knowledge, Analytics, Future extensions.*

These are not one taxonomy. Sorted honestly:

| Proposed | Problem |
|---|---|
| **Organization** | An Organization *is* a Party. Two categories, one concept — every join must then handle both |
| **Event / Activity** | Not distinguishable in practice. Is a site visit an event or an activity? The boundary will be re-litigated forever |
| **Financial** | A **domain**, not an entity kind. It spans money (resource), payment (occurrence) and invoice (obligation) |
| **Analytics** | Not an entity. Derived measures are **predicates with a formula**, not things in the world |
| **Knowledge** | Not an entity. It is the substrate this registry describes — including it is a category error |
| **Future extensions** | Reserving a slot for the unknown is how taxonomies rot. §2.3 gives the extension contract instead |

A taxonomy whose members answer different questions cannot route anything. *"Is an invoice Financial or Commitment?"* has no answer.

### 2.2 The permanent taxonomy — six categories, by ontological kind

Classification is by **what kind of thing it is**, not by which department uses it. Departments change; ontology does not.

| # | Category | Test | Includes |
|---|---|---|---|
| **1** | **AGENT** | Can act; can be held responsible | Person, Organization, Team, System, Government Body |
| **2** | **RESOURCE** | Has value; can be owned, used or consumed | Asset, Product, Material, Inventory, Money Instrument |
| **3** | **PLACE** | Occupies space | Location, Site, Territory, Constituency, Ward, Plot |
| **4** | **OCCURRENCE** | Happens in time; has temporal parts | Event, Activity, Meeting, Payment, Delivery, Encounter |
| **5** | **ARTIFACT** | A recorded representation | Document, Message, Drawing, Certificate, Recording |
| **6** | **OBLIGATION** | A normative social fact — binding, not physical | Commitment, Policy, Contract, Warranty, Entitlement, SLA |

**Every entity type declares exactly one category.** The category is semantic and therefore frozen.

### 2.3 Resolving the two hard cases

**Organization collapses into AGENT.** A Party is anything that can act and bear responsibility. Person and Organization are *entity types* within AGENT, not separate categories. This matters practically: in most Indian SMEs the same firm is customer, supplier and referrer. One category, one identity resolution problem, one set of joins.

**Communication is two entities, not one.** This is the case that causes years of confusion if left unresolved:

```
core.communication@1   (OCCURRENCE)  — the ACT of communicating
        │  has_content
        ▼
core.message@1         (ARTIFACT)    — the CONTENT that was sent
```

*"When did we contact them?"* asks about the OCCURRENCE. *"What did the quotation say?"* asks about the ARTIFACT. One entity cannot answer both without ambiguity. A WhatsApp message forwarded three times is **one artifact, three occurrences** — and the count matters commercially.

### 2.4 Where the rejected items actually live

| Proposed | Resolution |
|---|---|
| Organization | Entity type inside **AGENT** |
| Event, Activity | Entity types inside **OCCURRENCE** |
| Financial | A **namespace** (`fin.*`) spanning RESOURCE, OCCURRENCE, OBLIGATION |
| Analytics | **Derived predicates** (§3, category 7) |
| Knowledge | The substrate itself — not a category |
| Future extensions | The extension contract, below |

### 2.5 Extension contract — replacing "Future extensions"

A new **entity type** is admissible if it declares exactly one of the six categories, a namespace, and a definition distinguishing it from every existing type in that namespace.

A new **category** requires proving the thing is not an AGENT, RESOURCE, PLACE, OCCURRENCE, ARTIFACT or OBLIGATION. **I expect zero such additions in ten years.** If one is proposed, the far likelier explanation is a domain concept wearing a costume — a "Clinical Entity" is an OCCURRENCE, an ARTIFACT, or an OBLIGATION.

---

## 3 · Predicate Registry

### 3.1 Challenging the proposed list

Proposed: *Identity, Attribute, Relationship, Status, Temporal, Financial, Operational, Derived, Confidence, Provenance.*

Three corrections:

| Item | Correction |
|---|---|
| **Relationship** | Not a predicate. Relationships are **edges** with their own registry (§4). A predicate describes *one* entity; an edge connects *two*. Conflating them means every query must check both shapes |
| **Financial, Operational** | **Domains, not predicate kinds.** `invoice_amount` and `transformer_weight` are both QUANTITATIVE — they differ in namespace and unit, not in kind |
| **Confidence, Provenance** | **Assertion metadata, present on every assertion regardless of predicate.** Making them predicate categories implies some predicates lack confidence — and a fact without provenance is a rumour (Article II.6) |

### 3.2 The seven predicate categories

The axis: **what role does this predicate play in describing its entity?**

| # | Category | Purpose | Distinctive handling | Examples |
|---|---|---|---|---|
| **1** | **IDENTIFYING** | Contributes to establishing *which* entity this is | **Feeds entity resolution.** Carries a discriminating-power weight. Never auto-merges alone unless globally unique | `gstin`, `phone_e164`, `serial_no`, `aadhaar_last4` |
| **2** | **DESCRIPTIVE** | An intrinsic property that is not a measure | Free or enumerated value space | `legal_name`, `oil_type`, `blood_group` |
| **3** | **STATE** | Position in a declared lifecycle | **Mutually exclusive values; transitions may be constrained.** Always single-cardinality | `order_status`, `resolution_state`, `discharge_status` |
| **4** | **TEMPORAL** | A point or interval in time | **Must declare business-time vs system-time.** Timezone-explicit; supports fiscal and seasonal calendars | `founded_on`, `due_on`, `valid_from` |
| **5** | **QUANTITATIVE** | A measured or counted value | **Unit is mandatory and semantic.** Currency amounts carry currency + as-of date | `kva_rating`, `invoice_amount`, `plot_area` |
| **6** | **CLASSIFYING** | Assigns the entity to a bucket | Enumerated, from a declared scheme; the scheme is itself versioned | `customer_segment`, `risk_tier`, `abc_class` |
| **7** | **DERIVED** | Computed from other knowledge | **Declares formula, input set and invalidation trigger.** Confidence capped below its weakest input. Never authoritative in conflict resolution | `payment_reliability`, `lifetime_value`, `days_to_slip` |

### 3.3 Why these seven and not others

Each category earns its place by needing **different machinery**, not by describing a different subject:

- IDENTIFYING feeds a resolution algorithm nothing else touches
- STATE needs mutual exclusion and transition rules
- TEMPORAL needs bitemporality and business calendars
- QUANTITATIVE needs units and currency-as-of
- CLASSIFYING needs a versioned scheme
- DERIVED needs formula, lineage and invalidation
- DESCRIPTIVE needs none of the above — it is the residual

A category requiring no distinct machinery is a namespace, not a category.

### 3.4 Assertion metadata — on every assertion, not a category

| Field | Rule |
|---|---|
| `source` | System of record, document, human, or model |
| `provenance_tier` | 0 authoritative … 5 customer-claimed |
| `confidence` | **Capped by tier.** Customer-sourced ≤ 0.50 (Article II.6). A model can never raise its own confidence |
| `observed_at` / `valid_from` / `valid_to` | Bitemporal. Cannot be retrofitted — present from the first row |
| `asserted_by` | The principal or process |
| `lineage` | For DERIVED: formula, inputs, computed_at |

### 3.5 Every predicate also declares

| Field | Why it is semantic |
|---|---|
| `cardinality` | single / multi. Changing it changes which facts are valid |
| `volatility_class` | static / slow / fast / live — drives freshness scoring and TTL |
| `value_space` | type, enumeration or range |
| `unit` | mandatory for QUANTITATIVE; changing it silently corrupts every comparison |
| `applies_to` | which entity categories or types may carry it |

**Volatility is where "static vs operational knowledge" correctly lives** — as a per-predicate attribute, not as a separate store. A product price is `fast` in retail and `slow` in manufacturing. One registry, per-industry tuning.

---

## 4 · Relationship Registry

### 4.1 Six semantic classes (closed set — frozen)

Relationship *names* are unlimited. Relationship *semantics* are six. This is what stops the graph becoming a swamp by year three.

| Class | Meaning | Transitive? | Max depth |
|---|---|---|---|
| **Structural** | Composition, classification | Yes | 5 |
| **Participation** | An agent plays a role in something | No | 2 |
| **Transactional** | Value or obligation flows | No | 2 |
| **Temporal** | Ordering, replacement | Yes | 5 |
| **Evidential** | Support, provenance | No | 2 |
| **Associative** | Weak, discovered, statistical | No | **1** |

**Associative edges may never, alone, justify an action.** They rank and discover. An irreversible act must rest on a Structural, Participation or Transactional edge at provenance tier ≤ 2.

### 4.2 The proposed relationship types, classified

| Relationship | Class | Direction | Cardinality | Time-bounded | Inverse |
|---|---|---|---|---|---|
| `owns` | Transactional | AGENT → RESOURCE | 1:N | **yes** | `owned_by` |
| `works_for` | Participation | AGENT → AGENT | N:1* | **yes** | `employs` |
| `manages` | Participation | AGENT → AGENT/RESOURCE | 1:N | **yes** | `managed_by` |
| `reports_to` | Participation | AGENT → AGENT | N:1 | **yes** | `has_report` |
| `purchased` | Transactional | AGENT → RESOURCE | N:M | no† | `purchased_by` |
| `supplies` | Transactional | AGENT → RESOURCE/AGENT | N:M | **yes** | `supplied_by` |
| `attends` | Participation | AGENT → OCCURRENCE | N:M | no† | `attended_by` |
| `assigned_to` | Participation | OCCURRENCE/OBLIGATION → AGENT | N:1 | **yes** | `has_assignment` |
| `created_by` | Evidential | * → AGENT | N:1 | no† | `created` |
| `references` | Evidential | ARTIFACT → * | N:M | no | `referenced_by` |
| `depends_on` | Structural | * → * | N:M | **yes** | `depended_on_by` |
| `parent_of` | Structural | * → * | 1:N | **yes** | `child_of` |
| `child_of` | — | **see §4.4** | | | |

\* `works_for` is N:1 in most businesses but **must be modelled N:M** — consultants and contractors are normal, and a model that forbids them fails on contact with reality.
† Historical facts. `purchased` happened at a moment and does not expire, though the *purchase event* has a timestamp.

### 4.3 Time-bounding is the default

Most of the table is time-bounded, and that is deliberate. *"Ravi owns this account"* was true until March. A relationship that cannot expire produces a graph that is confidently wrong about the past — worse than one that admits ignorance.

Every edge carries `valid_from` / `valid_to`, `confidence`, `provenance`, `tenant_id`, and — for Associative only — `salience` for pruning.

### 4.4 The inverse-pair rule

`parent_of` and `child_of` are the same fact stated twice.

> **Store one direction. Declare the inverse. Derive it on read.**

Storing both doubles write cost and creates a consistency failure mode with no detector: nothing prevents `A parent_of B` existing while `B child_of A` does not. Registering `child_of` as a stored type is therefore **rejected** — it is registered as the declared inverse of `parent_of`.

The same applies to every pair in the table's rightmost column.

**Canonical direction rule:** store from the *more specific* to the *more general*, or from *actor* to *acted-upon*. `child_of` would violate this; `parent_of` follows it.

### 4.5 Where predicates end and relationships begin

The recurring question. The rule:

> If the target is an **entity we track**, it is a relationship. If it is a **value**, it is a predicate.

`customer.city = "Belagavi"` is a DESCRIPTIVE predicate — until Belagavi becomes a PLACE entity with its own attributes, at which point it becomes `located_in`. Both are legitimate at different maturities. **The registry must record which choice was made**, because migrating between them is a semantic change requiring a new version.

---

## 5 · Versioning

### 5.1 Integer versions, not semver

Semantic versioning encodes *compatible vs breaking*. That distinction does not apply to a meaning: a meaning either is the same or it is not. There is no "backward-compatible meaning change."

```
core.party.legal_name@1
core.party.legal_name@2      ← a DIFFERENT concept that shares a name
```

Versions are monotonic integers, never reused, never renumbered.

### 5.2 Lifecycle

```
DRAFT ──► ACTIVE ──► DEPRECATED ──► RETIRED
  │                       │
  └──► ABANDONED          └── replaced_by + compatibility declared
```

| State | Semantics editable? | New assertions? | Existing assertions readable? |
|---|---|---|---|
| **DRAFT** | Yes | No | n/a |
| **ACTIVE** | **No — frozen** | Yes | Yes |
| **DEPRECATED** | No | **No** | Yes |
| **RETIRED** | No | No | **Yes — always** |

**RETIRED never means unreadable.** A hospital retiring a predicate must still read ten years of assertions written under it. Retirement removes the ability to *create*, never to *interpret*.

### 5.3 Compatibility relations — the field that prevents silent corruption

When `@1` is replaced by `@2`, the registry must declare *how* they relate. Without this, a reader will assume equivalence and silently corrupt every historical analysis.

| Relation | Meaning | Auto-projection |
|---|---|---|
| **EQUIVALENT** | Same facts satisfy both; only presentation changed | ✅ safe |
| **NARROWER** | `@2` accepts a subset of `@1` | ⚠️ lossy — declare the filter |
| **BROADER** | `@2` accepts a superset | ✅ safe upward |
| **OVERLAPPING** | Partial, neither contains the other | ❌ **manual mapping required** |
| **UNRELATED** | Different concepts that happen to share a name | ❌ **never project** |

**Worked example.** `credit_limit@1` = "approved exposure"; the business later wants "available headroom." These are `UNRELATED` — and the correct action is not a version bump but a **new predicate** `credit_headroom@1`. Both coexist forever. This is the single cheapest ten-year decision available and the most expensive to retrofit: reinterpreted history is corrupted history, and the corruption is silent.

### 5.4 Read-time projection, never history rewriting

A reader requests a version. Old assertions are **projected** through declared compatibility relations. **Stored assertions are never altered.** History is interpreted, not edited.

Every assertion records the `semantic_version` it was written under. Without it, V4 silently reinterprets V1 data — the most insidious failure available to a system like this.

### 5.5 Concurrent support

**Two ACTIVE versions of a concept, minimum 12 months overlap.** Consumers declare compatibility *ranges*, never pins. Deprecation requires a named successor **and** a consumer list — the same discipline already enforced on capabilities in Phase 1B.

---

## 6 · Validation Rules

### V1 — No duplicate meanings

| Layer | Rule | Automatable? |
|---|---|---|
| **Identifier** | `(namespace, concept, version)` unique | ✅ fully |
| **Definition** | Normalised definition text must not exactly match another ACTIVE concept in the same namespace | ✅ exact match only |
| **Semantic** | Two concepts must not describe the same real-world fact | ❌ **human review** |

Honest limitation: **semantic duplication cannot be fully automated.** `legal_name` and `registered_name` may or may not be the same concept — only a domain expert knows. The registry mitigates rather than solves: a mandatory review gate before DRAFT → ACTIVE, plus a similarity report surfacing near-matches. Claiming otherwise would be false assurance.

### V2 — Immutable semantics

- Semantic fields are write-once at ACTIVE; the transition is irreversible
- Any attempted semantic change is **rejected**, with a message pointing at version creation
- Presentational fields remain editable in every state
- Every semantic change produces an audit record naming the human who approved it

### V3 — Backward compatibility

- Every assertion carries its `semantic_version`
- Retired concepts remain readable forever
- Projection requires a **declared** compatibility relation; absence of a declaration blocks projection rather than guessing
- A reader requesting an unknown version gets an explicit error, never a silent fallback

### V4 — Extensibility

- Namespacing mandatory; unqualified identifiers rejected
- New concepts are additive — a package installation never modifies an existing meaning
- Every concept declares its category from the closed set
- Relationship types map to one of the six frozen classes
- **Registry rows are data**; adding a concept requires no deployment

### V5 — Referential integrity

- `applies_to` must name existing, ACTIVE entity types
- `replaced_by` must name an existing concept in the same namespace
- Relationship endpoints must name existing categories or types
- Enumerated value spaces reference a versioned scheme
- **A concept with dependents cannot be RETIRED** until every dependent declares a successor

---

## 7 · Acceptance Criteria

Objective tests. Phase 2B does not begin until all pass.

### Structural

| # | Test |
|---|---|
| 1 | All six entity categories registered; every entity type declares exactly one |
| 2 | All seven predicate categories registered; every predicate declares exactly one |
| 3 | All six relationship classes registered; every relationship type declares exactly one |
| 4 | Every concept has a namespaced, versioned identifier — unqualified names rejected |
| 5 | The relationship types in §4.2 are registered with class, direction, cardinality, time-bounding and inverse |
| 6 | `child_of` is registered as a **declared inverse**, not a stored type |

### Behavioural — each must be demonstrated, not asserted

| # | Test | Expected |
|---|---|---|
| 7 | Attempt to modify the definition of an ACTIVE concept | **REJECTED** with a pointer to version creation |
| 8 | Attempt to modify a presentational field of an ACTIVE concept | **ACCEPTED** |
| 9 | Register two concepts with identical `(namespace, concept, version)` | **REJECTED** |
| 10 | Create version `@2` of an ACTIVE concept | **ACCEPTED**; `@1` unchanged and still readable |
| 11 | Declare `replaced_by` without a compatibility relation | **REJECTED** |
| 12 | Project an assertion across an `UNRELATED` relation | **REJECTED** |
| 13 | Retire a concept that has dependents | **REJECTED** |
| 14 | Read an assertion written under a RETIRED version | **SUCCEEDS**, interpreted under the version it was written with |
| 15 | Register an entity type with no category | **REJECTED** |
| 16 | Register a relationship type outside the six classes | **REJECTED** |
| 17 | Register a QUANTITATIVE predicate with no unit | **REJECTED** |
| 18 | Register a DERIVED predicate with no formula or input set | **REJECTED** |
| 19 | Register an unqualified identifier | **REJECTED** |
| 20 | Traverse an Associative edge to depth 2 | **REJECTED** — max depth 1 |

### Non-regression

| # | Test |
|---|---|
| 21 | Zero application code touched; `api/webhook.py` byte-identical |
| 22 | Phase 1C suite still green (226 tests); no-bypass invariant intact |
| 23 | Zero additional AI calls |
| 24 | Fully reversible by `git revert` — tables additive and read by nothing |
| 25 | **Live production probe:** bot serves normally; unsigned → 403; a real message replies |

### Extensibility proof — the criterion that matters most

| # | Test |
|---|---|
| 26 | Define a complete vertical vocabulary (**transformer manufacturing**: entity types, predicates, relationships) **using registry entries only — zero code changes** |
| 27 | Record the wall-clock time taken, and who did it |

**Criterion 26 is the real acceptance test for this slice.** Criteria 1–25 prove the registry is well-formed. Only 26 proves it is a *platform*. If a new vertical needs an engineer, the registry has failed regardless of how many other tests pass — and it is far better to learn that here, at vertical #1, than at vertical #40.

---

## 8 · Rollback

| Lever | Time | Effect |
|---|---|---|
| `git revert` + push | ~60 s | Removes registry tables |
| Vercel Instant Rollback | **< 2 s** (measured) | Full deployment revert |

**Risk is structurally near-zero:** this slice adds tables that nothing reads and touches no application code. The Phase 1C rollback drill measured <2 s rollback, 1 s recovery, 100% availability across 183 samples.

---

## 9 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | Registry becomes engineer-only; the 100-domain thesis dies quietly | **High** | Criterion 26. Track *days-to-onboard-a-vertical* from this slice onward |
| **R2** | Semantic duplication accumulates — three predicates meaning the same thing | **High** | V1 review gate + similarity report. **Not fully solvable; monitored, not claimed** |
| **R3** | Over-modelling before any consumer exists | Medium | Register only what 2C and 2D will actually consume. Resist completeness |
| **R4** | Immutability is bypassed under delivery pressure ("just this once") | **High** | Enforced at the registry, not by convention. Every semantic change audited with a named approver |
| **R5** | Version proliferation — `@7` within a year | Medium | Versions require review. High churn signals a modelling failure, not a process failure |
| **R6** | Predicate-vs-relationship judgement made inconsistently | Medium | §4.5 rule; record the choice; migration is a semantic change |

---

## 10 · Required Documentation

| Artefact | Purpose |
|---|---|
| This IDD | Design gate before implementation |
| **ADR: predicate immutability** | The single most consequential 10-year decision |
| **ADR: semantic vs presentational fields** | The distinction immutability depends on |
| **ADR: Communication as OCCURRENCE + ARTIFACT** | Prevents years of ambiguity |
| **ADR: inverse-pair rule** | Why `child_of` is derived, not stored |
| ADR: entity categories by ontological kind | Why Organization collapsed into AGENT |
| Verification report | Structural + behavioural, per ADR 0002 method |
| Vertical onboarding report | Criterion 26 evidence, including elapsed time |
| Registry authoring guide | For the domain expert, not the engineer — R1's mitigation |

---

## 11 · Approval gate

Implementation may not begin until:

1. This IDD is approved
2. The six entity categories are accepted **or amended**
3. The seven predicate categories are accepted **or amended**
4. The inverse-pair rule is accepted (it removes `child_of` from the proposed list)
5. `Organization` collapsing into `AGENT` is accepted
6. The three rejected categories — Financial, Analytics, Knowledge — are accepted as not being entity categories

**Six of the fifteen proposed classifications are changed by this document.** None is a stylistic preference; each removes a boundary dispute that would otherwise recur for a decade. If any is rejected, the corresponding section needs rework before implementation, not during it.
