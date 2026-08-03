# IDD 2C — Knowledge Assertions & Fact Model

**Status:** Design · No implementation · 2026-08-03
**Depends on:** IDD-2A Semantic Registry (frozen) · IDD-2B Core Business Objects (frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Four corrections, stated first

### C1 — "Status" on an immutable assertion is a contradiction

The brief lists `Status` as an assertion field, with a lifecycle `Proposed → Validated → Active → Superseded → Expired → Retracted → Archived`.

But an assertion moving from `Active` to `Superseded` means **mutating a record we have declared immutable**. Either immutability is real and status cannot be stored, or status is stored and immutability is decoration.

**Resolution — split the lifecycle at the commit boundary:**

| Phase | States | Stored? |
|---|---|---|
| **Pre-commit** — not yet a fact | `PROPOSED`, `VALIDATED`, `REJECTED` | **Yes.** Mutable, because nothing depends on them yet |
| **Post-commit** — a fact forever | `ACTIVE`, `SUPERSEDED`, `EXPIRED`, `RETRACTED` | **No — derived on read** |

Post-commit states are **computed**, never written:

```
SUPERSEDED  ⟺  a later assertion exists for the same (subject, predicate)
EXPIRED     ⟺  valid_until < now
RETRACTED   ⟺  a retraction record referencing this assertion exists
ACTIVE      ⟺  none of the above
```

This is not pedantry. A stored status is a second source of truth that will drift from the assertions it describes — and the drift is silent.

### C2 — "Last Verified" also implies mutation

Same problem. **Re-verification produces a new assertion**, identical in value with a fresh `observed_at`. Confirmation is evidence, and evidence is appended.

`last_verified` is then derived: `max(observed_at)` across assertions with the same subject, predicate and value. Three sources independently confirming a GSTIN is three assertions and a strong signal — richer than one mutable timestamp.

### C3 — "Object / Value" in one field creates polymorphism everywhere

2A §4.5 already settled this: if the target is **an entity we track**, it is a relationship; if it is **a value**, it is a predicate. Merging them into one polymorphic field forces every consumer to type-switch forever.

**But the discrimination is already free:** the registry knows which a predicate is. So:

> **One `Claim` envelope · two shapes · discriminated by the registered predicate, not by inspecting the target.**

`ValueClaim` (subject, predicate, value) and `LinkClaim` (subject, relationship, target). Identical metadata — provenance, confidence, bitemporality, lineage. No polymorphic field, no type-switching, one set of rules.

### C4 — The proposed fact categories re-derive a taxonomy 2A already owns

The brief lists: *Identity, Attribute, Relationship, State, Event, Financial, Operational, Derived, Human-entered, AI-derived, Imported.*

That is **four axes collapsed into one list** — the same error corrected in 2A §3.1:

| Item | What it actually is |
|---|---|
| Identity, Attribute, State, Event | ≈ the 2A **predicate categories** |
| Relationship | the **relationship registry** — not a predicate |
| Financial, Operational | **namespaces** |
| Derived | a **derivation property** |
| Human-entered, AI-derived, Imported | **provenance tiers** |

**Recommendation: facts have no categories of their own.** A fact's category *is* its predicate's category, inherited from 2A. Defining a parallel list here creates a second taxonomy that must be kept in sync with the first — and taxonomies that must be kept in sync diverge.

§4 shows every proposed category resolving to something that already exists.

---

## 1 · Fact Architecture

### 1.1 Five layers

| Layer | Answers | Mutable? | Example |
|---|---|---|---|
| **Semantic Registry** (2A) | What does this *word* mean? | Meanings frozen; new = new version | `core.party.legal_name@1` |
| **Business Objects** (2B) | What *shape* is a valid Customer? | Versioned contract | Customer = Party + customer role + ≥1 channel |
| **Knowledge Assertions** (2C) | What is *true*, and how do we know? | **Append-only, never edited** | `legal_name = "Acme Pvt Ltd"`, Tally, 12 Mar, tier 0 |
| **Organizational Intelligence** | What did *we decide and do*? | Immutable, annotatable | "Approved 18% discount on this evidence" |
| **Physical storage** | Where do the bytes live? | Irrelevant above | not modelled here |

### 1.2 How they connect

```
   SEMANTIC REGISTRY ─── defines the vocabulary ───┐
   (meaning)                                       │
        │ predicate category, value space,         │
        │ unit, cardinality, volatility            │
        ▼                                          ▼
   BUSINESS OBJECTS ◄── projects ──── KNOWLEDGE ASSERTIONS
   (structure)                        (facts, append-only)
        │  "a Customer requires             │  subject · predicate · value
        │   these predicates"               │  provenance · confidence
        │                                   │  valid_from/to · observed_at
        │                                   │
        └──────────► used as EVIDENCE ──────┘
                            │
                            ▼
                 ORGANIZATIONAL INTELLIGENCE
                 (decisions, referencing the evidence
                  packet as it stood at the time)
```

**The load-bearing relationships:**

- The registry **constrains** assertions. An assertion whose predicate is unregistered is rejected — no free-floating facts.
- Business Objects **project** assertions. They own nothing. This is why one Party can be both Customer and Supplier with zero duplication (2B §3.2).
- OI **references** assertions as evidence; it never copies them. A decision points at the packet as it stood, so replay is honest and hindsight cannot contaminate it.
- Nothing flows the other way. Assertions do not know which objects project them; OI does not modify facts.

### 1.3 The rule that keeps this correct for a decade

> **Assertions are the only place facts live. Everything else is a view.**

The moment a Business Object caches a value, or OI copies a fact instead of referencing it, there are two sources of truth — and one will be wrong without anyone noticing.

---

## 2 · The Claim Model

### 2.1 One envelope

Every claim — value or link — carries the same metadata. This is what makes provenance, confidence and time uniform across the whole knowledge plane.

```
CLAIM
├── IDENTITY
│   ├── claim_id            immutable, meaningless
│   └── tenant_id           partition key, on every claim (Article II.5)
│
├── ASSERTION
│   ├── subject             knowledge_id of the entity this is about
│   ├── predicate           registered concept + version — e.g. legal_name@1
│   └── target              value  (ValueClaim)  |  knowledge_id (LinkClaim)
│                           shape determined by the REGISTRY, not inspection
│
├── PROVENANCE
│   ├── source              system, document, human, or model — §6
│   ├── provenance_tier     0 authoritative … 5 self-reported
│   ├── asserted_by         the principal or process that made the claim
│   └── source_ref          pointer back to the origin record
│
├── CONFIDENCE
│   └── confidence          CAPPED BY TIER. Never model-asserted
│
├── TIME  (bitemporal — cannot be retrofitted)
│   ├── valid_from          when it became true IN THE WORLD
│   ├── valid_until         when it stopped (null = still true)
│   └── observed_at         when WE learned it
│
├── SEMANTICS
│   └── semantic_version    which registry version this was written under
│
├── DERIVATION  (null for original facts)
│   ├── formula             how it was computed
│   ├── inputs              the claims it was computed from
│   ├── computed_at
│   └── invalidated_by      trigger that makes it stale
│
└── COMMIT
    ├── recorded_at         when it entered the store
    └── pre_commit_state    PROPOSED | VALIDATED | REJECTED  (§3)
```

### 2.2 Field-by-field

| Field | Purpose | Why it must exist |
|---|---|---|
| **subject** | What the claim is about | Always a `knowledge_id`, never a business key — 2B §V3 |
| **predicate** | Which registered meaning | Includes the **version**. Without it, a 2036 reader silently reinterprets a 2026 fact |
| **target** | The value, or the linked entity | Shape from the registry — no polymorphism at the point of use |
| **source** | Where it came from | An unsourced fact is a rumour |
| **provenance_tier** | How authoritative the source is | The **cap** on confidence, not a hint |
| **asserted_by** | Which principal or process | Accountability. Never null |
| **source_ref** | Pointer to the origin record | Makes `EXPLAIN` answerable |
| **confidence** | Evidentiary strength | **Capped by tier.** Customer-sourced ≤ 0.50 (Article II.6) |
| **valid_from / valid_until** | World time | "What was true in March?" |
| **observed_at** | System time | "What did we *believe* in March?" — the question every dispute becomes |
| **semantic_version** | Registry version at write time | The single cheapest 10-year decision; impossible to retrofit |
| **derivation** | Formula, inputs, invalidation | §8. Absent ⇒ an original fact |
| **recorded_at** | Entry into the store | Distinct from `observed_at` when backfilling history |
| **pre_commit_state** | Validation stage | Only meaningful before commit — §3 |

### 2.3 Deliberately absent

| Not a field | Why |
|---|---|
| `status` | **Derived** (C1). Storing it creates a second source of truth |
| `last_verified` | **Derived** (C2). Verification appends a new claim |
| `category` | **Inherited** from the predicate (C4) |
| `is_current` | Derived from `valid_until` and supersession |
| `updated_at` | Claims are never updated. Its presence would invite mutation |

Each omission is load-bearing. A field that implies mutation will eventually be mutated.

---

## 3 · Assertion Lifecycle

### 3.1 Pre-commit — stored and mutable

```
  ┌──────────┐  validate  ┌───────────┐  commit   ╔═══════════╗
  │ PROPOSED │───────────►│ VALIDATED │──────────►║ IMMUTABLE ║
  └────┬─────┘            └───────────┘           ╚═══════════╝
       │ fails
       ▼
  ┌──────────┐
  │ REJECTED │  retained with reason — rejections are signal
  └──────────┘
```

| State | Meaning |
|---|---|
| **PROPOSED** | Extracted or received; not yet checked |
| **VALIDATED** | Passed §9 validation; eligible to commit |
| **REJECTED** | Failed validation. **Retained with the reason** — a rejection rate per source is a quality metric |

**Nothing is immutable until commit.** This is what makes correction cheap before, and honest after.

### 3.2 Post-commit — derived, never stored

```
                    ╔════════════════════╗
                    ║  COMMITTED CLAIM   ║  immutable forever
                    ╚═════════╦══════════╝
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    ┌──────────┐       ┌────────────┐      ┌───────────┐
    │  ACTIVE  │       │ SUPERSEDED │      │  EXPIRED  │
    │ nothing  │       │ a newer    │      │valid_until│
    │ overrides│       │ claim wins │      │ < now     │
    └──────────┘       └────────────┘      └───────────┘
                              │
                        ┌─────▼──────┐
                        │ RETRACTED  │  a retraction record exists
                        └────────────┘
```

| Derived state | Computed as |
|---|---|
| **ACTIVE** | Not superseded, not expired, not retracted |
| **SUPERSEDED** | A later claim exists for the same (subject, predicate) with a later `valid_from` |
| **EXPIRED** | `valid_until < now` |
| **RETRACTED** | A retraction record references it |

### 3.3 Retraction — the state that must not be a delete

Retraction means *"we should never have asserted this"* — an extraction bug, a wrong source, a keying error. Distinct from supersession, which means *"this was true and no longer is."*

> **A retraction is a new record referencing the original, with a reason and an author. The original claim remains readable forever.**

Deleting it would destroy the answer to *"why did we decide that in March?"* — because the decision was made on the retracted fact, and an audit that cannot reproduce a past decision is not an audit.

**Retracted claims are excluded from current truth, included in historical replay.**

### 3.4 Archival

Archival is a **storage tier**, not a lifecycle state. Cold claims move to cheaper storage and remain queryable. Nothing about their meaning or status changes. Listing `Archived` alongside `Retracted` conflates where bytes live with what is true.

---

## 4 · Fact Categories

### 4.1 Facts inherit their category — they do not have their own

Per C4. Here is where every proposed category actually resolves:

| Proposed | Resolves to | Layer |
|---|---|---|
| **Identity** | `IDENTIFYING` predicate | 2A §3.2 |
| **Attribute** | `DESCRIPTIVE` predicate | 2A §3.2 |
| **State** | `STATE` predicate | 2A §3.2 |
| **Event** | Not a fact category — an **OCCURRENCE entity** (2B). Facts *about* an event are ordinary claims on it | 2B §2.2 |
| **Relationship** | A **LinkClaim** via the relationship registry | 2A §4 |
| **Financial** | The `fin.*` **namespace**. `invoice_amount` is QUANTITATIVE | 2A §3.1 |
| **Operational** | A **namespace** | 2A §3.1 |
| **Derived** | The **derivation block** — an orthogonal property, not a category | §8 |
| **Human-entered** | **Provenance tier 1** | §6 |
| **AI-derived** | **Provenance tier 4** | §6 |
| **Imported** | **Provenance tier 0–2**, depending on the source system | §6 |

**Eleven proposed categories collapse to zero new concepts.** Every one is already expressible.

### 4.2 Why this matters more than it looks

A second taxonomy would need syncing with 2A forever. When they diverge — and they would — a fact could be `Attribute` here and `QUANTITATIVE` there, and no rule would say which governs.

**One taxonomy. Defined once. Inherited everywhere.**

The three axes that *are* real, and are already modelled:

```
WHAT KIND OF FACT   →  predicate category   (2A, 7 values)
WHERE IT CAME FROM  →  provenance tier      (§6, 6 tiers)
HOW IT WAS PRODUCED →  derivation           (§8, present or absent)
```

Any fact is one point in that three-dimensional space. `invoice_amount` = QUANTITATIVE × tier-0 × original. `payment_reliability` = DERIVED × tier-3 × computed.

---

## 5 · Truth & Conflict Model

### 5.1 What a conflict is

Two ACTIVE claims about the same `(subject, predicate)` whose validity periods overlap and whose values differ.

**Not conflicts:**
- Different validity periods → **history**, not disagreement
- A `multi` cardinality predicate with several values → **normal**
- Different predicates → different facts

### 5.2 The resolution ladder — deterministic, ordered, stopping at the first decisive rung

| # | Rung | Rationale |
|---|---|---|
| **1** | **Explicit human override**, unexpired | A human who has looked outranks every heuristic |
| **2** | **Source authority** — the declared system of record for that predicate | Tally owns `invoice_amount`; the CRM does not |
| **3** | **Provenance tier** | Tier 0 beats tier 4 regardless of recency |
| **4** | **Temporal validity** | Currently-valid beats expired |
| **5** | **Observation recency** | Newer observation of equal authority wins |
| **6** | **Confidence** | Last numeric tiebreak |
| **7** | **UNRESOLVED** | **Emit both, flagged** |

### 5.3 Rung 7 is the important one

> **When the system cannot decide, it must say so — never pick.**

An unflagged silent choice between contradictory facts is the most dangerous behaviour a knowledge system can exhibit, because it is **indistinguishable from knowing**. Every downstream consumer treats a resolved answer as settled.

Unresolved conflicts propagate into the Context Packet and **cannot be budget-pruned** — a contradiction trimmed for token economy becomes an invisible wrong answer.

### 5.4 Multiple sources agreeing

Agreement is **evidence**, not redundancy. Three independent tier-1 sources asserting the same GSTIN is stronger than one tier-1 source — but the aggregate is still **capped by the best tier present**, never summed above it. Agreement raises confidence within the cap; it never breaches it.

### 5.5 Stale information

Staleness is **not** a conflict. A single claim past its predicate's TTL is *current but old*.

Handled by freshness scoring (2A volatility class) feeding the Sufficiency Gate. A stale claim is served **with its age stated**, and whether that is acceptable depends on the decision's time-sensitivity — a founding date at 5 years old is fine; a credit limit at 9 days may not be.

### 5.6 Missing information

**Absence is a fact about our knowledge, and must be explicit.**

| Kind | Meaning |
|---|---|
| **UNKNOWN** | We have never learned it |
| **NOT_APPLICABLE** | The predicate does not apply to this subject |
| **REFUSED** | The party declined to provide it |
| **PENDING** | Requested, not yet received |

Collapsing these into "null" destroys real information. *"The customer refused to state their budget"* is commercially significant; *"we never asked"* is a process gap. Both become null in a naive model, and both matter.

---

## 6 · Provenance Model

### 6.1 Six tiers, with confidence caps

| Tier | Source class | Cap | Examples |
|---|---|---|---|
| **0** | **Authoritative system of record** | **1.00** | Tally for invoices, GST portal, bank statement, MCA registry |
| **1** | **Verified human, in role** | **0.90** | Owner-confirmed, staff-entered under authorization |
| **2** | **High-quality document extraction** | **0.80** | Signed PO, executed contract, test certificate |
| **3** | **Rule-based inference** | **0.70** | Deterministic derivation from tier 0–2 facts |
| **4** | **Model-derived** | **0.60** | LLM extraction from conversation |
| **5** | **Self-reported / unverified claim** | **0.50** | What a customer says about their own budget (Article II.6) |

### 6.2 Mapping the named sources

| Source | Tier | Note |
|---|---|---|
| **Government portal** (GST, MCA, ECI) | **0** | Authoritative for what it registers, and only that |
| **ERP / Tally** | **0** | For financial facts. **Tier 2 for anything else** |
| **CRM** | **1–2** | Depends: system-generated timestamps are tier 1; human-typed notes are tier 1; AI-enriched fields are tier 4 |
| **Bank / payment gateway** | **0** | For money movement |
| **Email** | **2** | The artifact is evidence; extraction from it is tier 4 |
| **Google Drive** | **varies** | **A location, not a source.** Tier comes from the *document*, not the folder it sits in |
| **Website form** | **5** | Self-reported by definition |
| **WhatsApp** | **4–5** | Extraction is tier 4; what the customer *claims* is tier 5 |
| **Human** | **1** | Only when acting in an authorized role |
| **AI** | **4** | **Never higher.** A model cannot raise its own confidence |

### 6.3 Three rules that make the hierarchy hold

**Tier is per fact, not per system.** Tally is authoritative for `invoice_amount` and merely a copy for `customer_phone`. A source's tier is declared **per predicate**, not globally. Systems that are authoritative for everything do not exist.

**Google Drive is a location, not a source.** Its tier depends entirely on the document. Treating a storage location as provenance is a common and corrosive error — it launders an unsigned draft into the same tier as an executed contract.

**AI is capped at 0.60, permanently.** Not because models are bad, but because a system in which model output can reach tier 0 has no floor. Article II.6 exists to keep fluency from becoming evidence.

---

## 7 · Temporal Knowledge

### 7.1 Two independent clocks

| Clock | Question | Fields |
|---|---|---|
| **World time** | When was it true? | `valid_from`, `valid_until` |
| **System time** | When did we know it? | `observed_at` |

Both are required, and neither can be retrofitted. Without world time, you cannot answer *"what was true in March?"* Without system time, you cannot answer *"what did we **believe** in March?"* — and every dispute, audit and post-mortem is the second question.

### 7.2 The three tenses

| Tense | Query shape |
|---|---|
| **Historical truth** | `valid_from ≤ T < valid_until`, `observed_at ≤ T` |
| **Current truth** | `valid_until` null or future, ACTIVE, not retracted |
| **Future commitment** | `valid_from > now` — a scheduled or promised fact |

**Future-dated claims are ordinary claims**, not a special kind. A price effective 1 April, a contract starting next quarter, a promised delivery — all are claims whose `valid_from` is in the future. They become current by the passage of time, with no state change and no job to run.

### 7.3 Worked example — an employee changes company

Under 2B, employment is a **PartyRole**, not a subtype. So:

```
Priya (Person, knowledge_id P-7742) — ONE party, permanently

  LinkClaim   P-7742 ──employed_by──► Acme (ORG-31)
              valid_from 2021-06-01   valid_until 2026-03-31
              observed_at 2021-06-03  tier 1   ← retained forever

  LinkClaim   P-7742 ──employed_by──► Brightline (ORG-88)
              valid_from 2026-04-01   valid_until null
              observed_at 2026-04-04  tier 1   ← current

  ValueClaim  P-7742 · mobile_e164 · +91… 
              valid_from 2019-01-01   valid_until null   ← unaffected
```

**What is preserved, and why it matters:**

- *"Who was our contact at Acme in 2023?"* → **Priya.** Still answerable.
- *"Which quotations did Priya handle at Acme?"* → intact; the Interactions still link to the party.
- *"Where does Priya work now?"* → Brightline.
- *"Did we know she had left when we sent the March quote?"* → **compare `observed_at` (4 Apr) against the quote date.** We did not. That is the question that decides whether a mistake was negligence or bad luck.
- Her phone number is untouched — it belongs to the Person, not the role.

**Nothing was updated. Nothing was deleted.** One claim acquired a `valid_until`; another was appended.

Had `Employee` been a subtype (the 2B correction), this would have required either deleting the Acme employment — destroying history — or creating a second Priya. Both are wrong, and the second is worse because it is silent.

### 7.4 Retroactive correction

Learning in June that a role actually ended in March is a **new claim** with `valid_from` in March and `observed_at` in June. The original is superseded, not edited.

Both remain readable, which is what makes *"what did we believe when we approved that?"* answerable — and that question is the entire point of bitemporality.

---

## 8 · Derived Knowledge

### 8.1 Three things, not one

The brief groups computed, inferred and cached. **Cached is not derived**, and merging them causes a specific failure.

| Kind | Definition | Recomputable? | On input change | Tier |
|---|---|---|---|---|
| **Computed** | Deterministic function of other claims | ✅ exactly | **Invalidate** | ≤ 3 |
| **Inferred** | Probabilistic or heuristic conclusion | ⚠️ approximately | **Invalidate** | ≤ 4 |
| **Cached** | A **copy** of a fact owned elsewhere | ✅ by re-fetching | **TTL expiry** | inherits source |

**Why the separation is load-bearing.** A cached value is not our fact — it belongs to Tally, and Tally may change it without telling us. It carries a TTL and is re-fetched. A computed value *is* ours, and becomes wrong when its **inputs** change, not when a clock runs out. Merging them means either caching things that should invalidate, or invalidating things that should merely expire. Article II.7 — *raw data is a cache* — depends on this distinction being explicit.

### 8.2 Separation from original facts

| Property | Original | Derived |
|---|---|---|
| `derivation` block | **null** | **required** — formula, inputs, computed_at, invalidation trigger |
| Deletable | ❌ never | ✅ safe — rebuildable |
| Confidence | Provenance-capped | **Capped below its weakest input** |
| Conflict authority | Can win | **Can never outrank an original fact**, at any confidence |

### 8.3 Two hard rules

**Derived facts are never authoritative.** However confident a derived value is, an asserted fact wins in the conflict ladder. A computed credit exposure never overrides a bank statement.

**Derivation depth is capped at 2 without explicit approval.** A score built on a score built on a score is numerology: confidence compounds downward and the lineage becomes unexplainable. If depth 3 is genuinely needed, it is a decision with a name attached.

### 8.4 Invalidation

Every derived claim declares its inputs. When an input is superseded or retracted, the derived claim is **marked stale**, not deleted — because a decision made on it must remain reproducible. Stale derived claims are excluded from current truth and included in historical replay, exactly like retracted originals.

---

## 9 · Validation Rules

### V1 — Immutable history
- Committed claims are **append-only**; no update path exists
- Corrections are **new claims**; errors are **retractions**
- Post-commit status is derived, never stored (C1)
- Retracted and superseded claims remain readable **forever**

### V2 — Reproducibility
- Every claim records `semantic_version`
- Every derived claim records formula, inputs and `computed_at`
- A query is reproducible: *"as we knew it at time T"* returns the same result today and in 2036
- Projection across registry versions requires a **declared** compatibility relation; absence blocks projection rather than guessing (2A §5.3)

### V3 — Auditability
- Every claim has a non-null `asserted_by` and `source_ref`
- Rejections retained with reasons
- Retractions carry reason and author
- Conflicts recorded when detected, not only when resolved

### V4 — Explainability
- Any fact answers: *why do we believe this?* — source, chain, competing claims, confidence calculation
- Any absence answers *why* — UNKNOWN / NOT_APPLICABLE / REFUSED / PENDING (§5.6)
- Explanation is a **capability**, not a log — content from records, never model-generated

### V5 — Deterministic replay
- The conflict ladder is total and deterministic — same inputs, same outcome, every time
- No AI participates in resolution
- Resolution is a pure function of claims plus registry; no hidden state, no wall-clock dependence beyond the explicit as-of time

### V6 — Referential and semantic integrity
- Predicate must be registered and ACTIVE at write time
- Subject must exist; target of a LinkClaim must exist
- Value must satisfy the registered value space, unit and cardinality
- **Confidence must not exceed the tier cap** — hard rejection, not a warning
- `valid_until` ≥ `valid_from`; `observed_at` ≥ `valid_from` unless explicitly backfilled

---

## 10 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Claim envelope defined with every field in §2.1, each with a stated purpose |
| 2 | ValueClaim and LinkClaim share one envelope; shape determined by the registry |
| 3 | No `status`, `last_verified`, `category` or `updated_at` field exists |
| 4 | Pre-commit states stored; post-commit states derived — the boundary is explicit |
| 5 | Six provenance tiers with caps; every named source mapped |
| 6 | Conflict ladder specified as 7 ordered, deterministic rungs |
| 7 | Four absence kinds distinguished |
| 8 | Computed / inferred / cached separated with distinct invalidation |

### Behavioural — must be demonstrated, not asserted

| # | Test | Expected |
|---|---|---|
| 9 | Attempt to update a committed claim | **REJECTED** — no update path |
| 10 | Assert a fact with confidence above its tier cap | **REJECTED** |
| 11 | Assert with an unregistered predicate | **REJECTED** |
| 12 | Assert with a value outside the registered value space | **REJECTED** |
| 13 | Correct a wrong fact | New claim; original readable; original SUPERSEDED |
| 14 | Retract a mistaken fact | Retraction record; original **still readable**; excluded from current truth |
| 15 | Query "as we knew it at time T" | Returns the belief at T, **not** current belief |
| 16 | Two tier-0 sources disagree | **UNRESOLVED**, both emitted, flagged — not silently picked |
| 17 | Tier-4 claim contradicts a tier-0 claim | Tier 0 wins at rung 3 |
| 18 | Three sources agree | Confidence rises **within** the best tier's cap, never above |
| 19 | Model attempts to raise its own confidence | **REJECTED** — capped at 0.60 |
| 20 | Derived claim contradicts an original | **Original wins**, regardless of confidence |
| 21 | Input to a derived claim is superseded | Derived marked **stale**, not deleted |
| 22 | Attempt derivation at depth 3 | **REJECTED** without explicit approval |
| 23 | Employee changes company | Both roles retained; history queryable; phone unaffected |
| 24 | Retroactive correction | New claim, back-dated `valid_from`, forward `observed_at`; both readable |
| 25 | Prune a conflict for token budget | **REJECTED** — conflicts are never budget-pruned |
| 26 | Distinguish REFUSED from UNKNOWN | Both representable and distinguishable |

### Reproducibility — the criterion that matters most

| # | Test | Expected |
|---|---|---|
| 27 | Run the same as-of query twice, a week apart, with new facts added between | **Identical results** |
| 28 | Replay a historical decision using only its evidence reference | Same facts, same conflict outcome, same verdict |
| 29 | Reinterpret a v1 claim under a v2 predicate with no declared compatibility | **REJECTED** — no silent projection |

### Non-regression

| # | Criterion |
|---|---|
| 30 | Zero application code touched; `api/webhook.py` byte-identical |
| 31 | Phase 1C suite green (226 tests); no-bypass invariant intact |
| 32 | Zero AI calls, zero schema, zero migrations |
| 33 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 28 is the acceptance test for this slice.** Criteria 1–27 prove the model is well-formed. Only 28 proves it is *trustworthy* — that a decision made in 2026 can be honestly re-examined in 2036, on the evidence as it stood, without hindsight contamination. A fact model that cannot do that is a database with extra columns.

---

## 11 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Post-commit status is derived, not stored** (C1) — the correction that makes immutability real
2. **`last_verified` removed**; verification appends a claim (C2)
3. **ValueClaim / LinkClaim as two shapes of one envelope** (C3), discriminated by the registry
4. **Facts inherit their category from the predicate** — no parallel taxonomy (C4)
5. **Retraction is a record, never a delete**; retracted claims remain readable forever
6. **Unresolved conflicts are emitted, never silently resolved** — and never budget-pruned
7. **Cached is not derived** — different invalidation, different ownership
8. **Provenance tier is per predicate, not per system** — Tally is authoritative for invoices, not for phone numbers
9. **Four absence kinds**, not null
10. **Derived facts never outrank originals**, at any confidence

**Four of the thirteen proposed assertion fields are removed or reclassified, and eleven proposed fact categories collapse to zero new concepts.** None of these is a preference. `status` and `last_verified` contradict immutability outright; a parallel category list would drift from 2A within a year.

If item 1 is rejected, this document needs rework before implementation — every rule in §3, §5 and §9 depends on it.
