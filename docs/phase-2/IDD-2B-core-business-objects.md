# IDD 2B — Core Business Objects

**Status:** Design · No implementation · 2026-08-03
**Depends on:** IDD-2A Semantic Registry (frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Headline: the proposed hierarchy has a structural defect

The brief proposes:

```
Party
├── Person
├── Organization
├── Customer
├── Supplier
└── Employee
```

**This mixes two incompatible things and will fail on contact with your own business.**

`Person` and `Organization` are **kinds** — what something *is*. Immutable, singular, permanent.
`Customer`, `Supplier`, `Employee` are **roles** — what something *does*. Temporal, plural, contextual.

The failure is concrete and immediate:

> A firm that buys social-media work from you **and** supplies you printing is simultaneously a Customer and a Supplier. Under the proposed hierarchy that requires either multiple inheritance or two records for one company — and the moment there are two records, "how much do we owe them net?" cannot be answered.

Three further failures follow:

| Problem | Consequence |
|---|---|
| Roles end; kinds do not | An employee who resigns is still a Person. If Employee is a *subtype*, what is the object after resignation? |
| Roles are time-bounded | "Were they a customer in FY24?" is unanswerable if the role is baked into the type |
| Roles are many | Customer + Supplier + Referrer + Employee's-spouse is normal, not exotic |

**Recommendation — the Party–Role model:**

```
Party  (abstract — never instantiated)
├── Person        ← KIND: immutable, one per party
└── Organization  ← KIND: immutable, one per party

PartyRole  (temporal, 0..N per Party, each with valid_from / valid_to)
├── Customer      ├── Supplier       ├── Employee
├── Partner       ├── Referrer       └── Competitor
```

One Party. Many roles. Each role time-bounded. Nothing duplicated.

This is the single most consequential decision in this document. Everything below assumes it.

---

## 1 · Core Object Architecture

### 1.1 What a Business Object is

A Business Object is a **contract**, not a container:

> *"To count as a Customer, a Party must have these assertions, may have those, participates in these relationships, and moves through this lifecycle."*

It declares what constitutes a valid business thing. It does not hold the data.

### 1.2 The four layers, and why conflating them fails

| Layer | Answers | Example | Owned by |
|---|---|---|---|
| **Semantic Registry** (2A) | *What does this word mean?* | `core.party.legal_name@1` means "name as registered with the authority" | Registry |
| **Business Object** (2B) | *What shape is a valid Customer?* | Customer requires a Party, a customer role, and ≥1 contact channel | Object model |
| **Knowledge Assertion** | *What is actually true, and how do we know?* | `legal_name = "Acme Pvt Ltd"`, Tally, 12 Mar, tier 0, conf 0.95 | Knowledge plane |
| **Database table** | *Where do the bytes sit?* | irrelevant to every layer above | Storage |

**Business Object ≠ database table.** A table stores rows and owns its columns. A Business Object owns nothing — it *projects* assertions that live in the knowledge plane and originate in systems we do not control. One Party's assertions can be projected simultaneously as a Customer and as a Supplier with **zero duplication**, because neither view owns the data.

**Business Object ≠ registry concept.** The registry defines *words*; the object composes words into a *thing*. `legal_name`, `gstin` and `credit_terms` are registry concepts; `Customer` is the statement that a valid customer has certain ones.

**Business Object ≠ assertion.** The object is the *type*; the assertion is the *instance fact*, with provenance, confidence and bitemporal validity. An object never has "a value" — it has assertions, each independently sourced and independently trustworthy.

### 1.3 Why this indirection is worth its cost

It is what makes Article II.7 true — *raw data is a cache*. The source systems stay authoritative. Add a second CRM in 2028 and the Customer object is unchanged; only an adapter is added. Had Customer been a table, the second CRM would have meant a migration.

---

## 2 · Core Object Catalogue

### 2.1 Recommended simplifications

Four merges. Each removes a boundary dispute rather than saving effort.

| Proposed | Recommend | Reasoning |
|---|---|---|
| `Customer`, `Supplier`, `Employee` as **types** | **PartyRole** instances | §0. Removes multiple inheritance and duplicate records |
| `Lead` + `Opportunity` | **One object** (`Lead`) | Two objects exist in CRM vendor models because enterprise sales hands off between marketing and sales teams. **You have no such handoff.** They are the same thing at different lifecycle states; separating them invents a conversion step that serves an org structure you do not have |
| `Product` + `Service` | **Offering** | Both are "a thing we supply for money." The differences — inventoried, serialised, delivered-over-time — are *attributes*, not kinds. One model serves an agency (services), a transformer plant (goods) and a hospital (both) |
| `Meeting` + `Communication` | **Interaction** | Both are OCCURRENCEs where parties exchange information. A phone call is both. The business question is *"when did we last touch this customer?"* — which needs **one timeline**, not two. `mode` distinguishes meeting / call / message / email / visit |

**23 proposed → 19 canonical**, and the conceptual reduction is far larger than the count suggests: the role pattern eliminates the multiple-inheritance problem entirely.

### 2.2 The catalogue

Category from 2A's closed set. **Every object's identity is a meaningless `knowledge_id`**; the columns below list the *identifying assertions* that feed resolution.

---

#### AGENT

| Object | Purpose | Identifying assertions | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Party** *(abstract)* | The thing that can act and be responsible. Never instantiated | — | — | kind | — | Party module |
| **Person** | A human | phone_e164, email, aadhaar_last4, pan | `prospective → active → inactive → deceased` | display_name | dob, gender, languages | Party |
| **Organization** | A legal or informal body | gstin, cin, phone_e164, domain | `prospective → active → dormant → dissolved` | legal_name | trade_name, incorporated_on, sector, size_band | Party |
| **PartyRole** | A role a Party plays, over a period | party + role_type + valid_from | `prospective → active → suspended → ended` | party, role_type, valid_from | valid_to, terms, owner, tier | Party |

**Business rules — Party**
- A Party has exactly one **kind**, assigned once, never changed. *(A Person cannot become an Organization.)*
- A Party may hold **any number of roles**, concurrently or serially.
- Roles are **time-bounded**; ending a role never deletes the Party or its history.
- **Merge is reversible.** Pre-merge state retained in full. Auto-merge only on tier 0–1 evidence above threshold; everything else queues for human confirmation.
- `DISPUTED` resolution state is first-class and must be surfaced, never silently resolved.

**Examples:** *Acme Pvt Ltd* is one Organization holding a Customer role (from Jan 2024) and a Supplier role (from Aug 2025). Net position is computable because there is one Party. — *Raviraj* is one Person holding an Employee role and, in `bot_roles`, an OWNER authorization; the authorization is not a business role and lives in the policy layer.

---

#### RESOURCE

| Object | Purpose | Identifying | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Offering** | Something we supply for money | sku, offering_code | `draft → active → deprecated → withdrawn` | name, fulfilment_kind | price_basis, unit, tax_class, lead_time | Catalog |
| **Asset** | A durable thing we own, use or maintain | serial_no, registration_no, tag | `acquired → commissioned → operating → down → retired → disposed` | asset_type, custodian | location, condition, warranty_until, spec | Asset |

**Business rules**
- `fulfilment_kind` ∈ {goods, service, hybrid}. **Semantic — frozen at ACTIVE.**
- Only `goods` may carry inventory or serial assertions. Enforced by `applies_to`.
- An Asset always has a **custodian** (an AGENT) while not `retired`.
- `disposed` is terminal and irreversible.

---

#### PLACE

| Object | Purpose | Identifying | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Location** | A place we refer to | geo_point, plot_id, address_hash | `proposed → active → superseded` | name, location_type | address, geo, parent_location, jurisdiction | Location |

**Business rules**
- Locations nest via `parent_of` — ward → constituency → district → state.
- A Location is **never deleted**; boundaries change, so it is `superseded` by a successor with a declared validity period. Election data spanning a delimitation depends on this.

---

#### OCCURRENCE

| Object | Purpose | Identifying | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Interaction** | A moment when parties exchanged information | channel + external_ref + occurred_at | `scheduled → held → completed` / `cancelled` / `no_show` | mode, occurred_at, participants | subject, outcome, sentiment, duration, location | Communication |
| **Payment** | Money actually moved | txn_ref, utr | `initiated → cleared` / `failed` / `reversed` | amount, currency, direction, value_date | method, payer, payee, against_invoice | Finance |

**Business rules — Interaction**
- `mode` ∈ {meeting, call, whatsapp, email, sms, visit, other}. One timeline per Party regardless of mode.
- An Interaction **has** zero or more Documents (artifacts). The *act* and the *content* are separate objects — 2A §2.3.
- Participants are `Participation` edges with roles, not a list of names.
- `no_show` is a distinct terminal state from `cancelled`. Conflating them destroys the reliability signal.

**Business rules — Payment**
- `direction` ∈ {inbound, outbound}. **Never inferred from sign** — a negative amount is ambiguous across systems.
- `reversed` does not delete; it appends a reversing record. Ledgers are append-only.
- Currency amounts carry currency **and** an as-of date.

---

#### ARTIFACT

| Object | Purpose | Identifying | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Document** | A recorded artifact | content_hash, external_ref | `draft → executed → superseded` / `void` | doc_type, created_at | issuer, effective_from, effective_to, extractions | Document |

**Business rules**
- Identity is the **content hash**. The same PDF sent twice is one Document with two Interactions.
- Documents `reference` any object — the only object with an unrestricted reference target.
- Extractions are **derived assertions** carrying formula and lineage, capped below their source tier.
- `superseded` requires naming the successor. Revision is modelled; deletion is not.

---

#### OBLIGATION

| Object | Purpose | Identifying | Lifecycle | Required | Optional | Steward |
|---|---|---|---|---|---|---|
| **Lead** | A pursued opportunity | source + party + created_at | `new → qualified → proposed → negotiating → won` / `lost` / `disqualified` / `expired` | party, source, created_at | need, budget_band, urgency, owner, score | Sales |
| **Quotation** | A priced offer, binding on us until it expires | quote_no + version | `draft → issued → accepted` / `rejected` / `expired` / `superseded` | party, lines, valid_until, total | terms, margin, approver, discount | Sales |
| **Order** | An accepted mutual commitment | order_no | `confirmed → in_fulfilment → delivered → closed` / `cancelled` | party, lines, promised_date | quotation, po_ref, delivery_terms | Sales |
| **Invoice** | A demand for payment | invoice_no | `raised → part_paid → settled` / `overdue` / `written_off` / `cancelled` | party, amount, currency, due_on | order, tax, gst_ref, aging | Finance |
| **Commitment** | Any promise with a party, obligation and deadline | subject + party + due_on | `made → in_progress → met` / `missed` / `waived` / `renegotiated` | party, obligation, due_on, owner | penalty, source, criticality | Commitment |
| **Project** | A bounded body of work under a commitment | project_code | `planned → active → on_hold → delivered → closed` / `cancelled` | party, scope, owner | budget, milestones, risk, start/end | Work |
| **Task** | A unit of assignable work | project + seq, or standalone id | `todo → in_progress → blocked → done` / `cancelled` | title, assignee | project, due_on, effort, priority | Work |
| **Policy** | A rule the business operates under | policy_code + version | `draft → active → superseded` / `retired` | rule, scope, effective_from | threshold, approver, penalty | Policy |

**Business rules — the commercial chain**
- `Quotation → Order → Invoice → Payment` is `temporal:precedes`. **This spine is identical for a transformer plant and a law firm** — only the line items differ. It is the business narrative, and it is what lets the Brain answer *"what happened with this customer?"* as a story rather than a join.
- A Quotation is **binding on us until `valid_until`**. Expiry is a state change, not a deletion.
- Quotation revisions **supersede**, never overwrite. Version is part of identity.
- An Invoice may exist without an Order (ad-hoc); an Order may exist without a Quotation (repeat). The chain is **typical, not mandatory** — enforcing it would break real businesses.
- `written_off` is terminal and requires an approver at tier 4.

**Business rules — Commitment**
- Commitment is the **generalisation** of the promise implicit in Quotation, Order, Project and SLA. It exists as its own object so that *"what have we promised and are we about to miss it?"* — one of the highest-value questions any business can ask — is answerable without a cross-module join no module owns.
- Every Commitment has an accountable **owner** (an AGENT). Never null.
- `missed` is recorded, never deleted. Missed commitments are the reliability signal.

**Business rules — Lead**
- **`Lead` and `Opportunity` are one object.** `qualified` is a lifecycle state, not a type change.
- `lost` requires a reason. A lost-reason-free pipeline teaches nothing.
- `disqualified` ≠ `lost`: never a real opportunity, versus lost to a competitor. Merging them corrupts conversion metrics.

---

## 3 · Inheritance Strategy

### 3.1 Three mechanisms, deliberately distinct

| Mechanism | Use | Changes over time? | Example |
|---|---|---|---|
| **Kind** (true subtyping) | What a thing *is* | **Never** | Person / Organization |
| **Role** (temporal association) | What a thing *does* | **Yes, many** | Customer, Supplier, Employee |
| **Extension** (package attributes) | Domain-specific facts | Additive only | `kva_rating` on Asset |

**Rule: if it can end, it is not a subtype.**

### 3.2 Specialization without duplication

```
                    ┌──────────────────┐
                    │  Party (abstract)│
                    │  knowledge_id    │
                    │  kind (frozen)   │
                    └────────┬─────────┘
              ┌──────────────┴──────────────┐
     ┌────────▼────────┐          ┌─────────▼────────┐
     │     Person      │          │   Organization   │
     │  dob, gender    │          │  gstin, sector   │
     └────────┬────────┘          └─────────┬────────┘
              └──────────────┬──────────────┘
                    ┌────────▼─────────┐
                    │    PartyRole     │  0..N, time-bounded
                    │ role_type        │
                    │ valid_from/to    │
                    └────────┬─────────┘
        ┌──────────┬─────────┼─────────┬──────────┐
   Customer    Supplier  Employee  Partner   Referrer
```

**Why no duplication.** Customer is not a copy of the Party — it is a *projection*: the same Party's assertions, viewed through a role that adds role-specific ones (credit terms, segment). `legal_name` is asserted **once** and read by every role view. Change it once, correct everywhere.

**The test that proves it:** a firm that is both Customer and Supplier has **one** `knowledge_id`, **one** `legal_name` assertion, and **two** PartyRole records. Net position across both roles is a single query. Under the proposed hierarchy it would be two records and an unanswerable question.

---

## 4 · Object Relationship Map

```
                        ┌──────────────────┐
                        │      PARTY       │  (Person | Organization)
                        └────────┬─────────┘
                                 │ plays 0..N
                        ┌────────▼─────────┐
                        │    PARTYROLE     │  customer | supplier | employee
                        └────────┬─────────┘
     ┌──────────┬────────────┬───┴────┬────────────┬──────────┐
     │          │            │        │            │          │
  ┌──▼───┐  ┌───▼─────┐  ┌───▼────┐ ┌─▼────────┐ ┌─▼───────┐ ┌▼──────────┐
  │ LEAD │  │ PROJECT │  │ORDER   │ │ INVOICE  │ │INTERACT.│ │COMMITMENT │
  └──┬───┘  └───┬─────┘  └───┬────┘ └─┬────────┘ └─┬───────┘ └───────────┘
     │          │            │        │            │
  ┌──▼──────┐   │         ┌──▼────────▼──┐      ┌──▼─────┐
  │QUOTATION│───┘         │   PAYMENT    │      │DOCUMENT│
  └─────────┘             └──────────────┘      └────────┘
                                                      │
        ┌─────────── DOCUMENT references ANY object ──┘

  PROJECT ──┬─ assigned_to ──► EMPLOYEE (PartyRole)
            ├─ part_of ◄────── TASK
            ├─ evidenced_by ─► DOCUMENT
            ├─ ─────────────► INTERACTION
            └─ uses ────────► ASSET
```

### 4.1 Every relationship, explained

| From → To | Class | Meaning | Time-bounded | Cardinality |
|---|---|---|---|---|
| Party → PartyRole | Structural | A party plays a role | **yes** | 1:N |
| PartyRole(customer) → Lead | Participation | Interest we are pursuing | no | 1:N |
| Lead → Quotation | Temporal `precedes` | Interest became a priced offer | no | 1:N |
| Quotation → Order | Temporal `precedes` | Offer was accepted | no | 1:1 |
| Order → Invoice | Transactional | Delivery became a payment demand | no | 1:N |
| Invoice → Payment | Transactional | Demand was settled | no | 1:N |
| PartyRole → Interaction | Participation | Party took part | no | N:M |
| PartyRole → Commitment | Transactional | We promised them something | **yes** | 1:N |
| Project → Task | Structural `part_of` | Work decomposition | no | 1:N |
| Project → PartyRole(employee) | Participation `assigned_to` | Who is doing it | **yes** | N:M |
| Project → Asset | Participation `uses` | Assets consumed or deployed | **yes** | N:M |
| Any → Document | Evidential `evidenced_by` | Proof for an object | no | N:M |
| Document → Any | Evidential `references` | What a document mentions | no | N:M |
| Task → Task | Structural `depends_on` | Sequencing | **yes** | N:M |
| Offering → Quotation line | Transactional | What was quoted | no | N:M |

### 4.2 Why Document is the only unrestricted reference

Documents mention everything: a PO names a customer, an order, products, a delivery site and a payment term. Constraining the target would force the model to anticipate every future document type. `references` is Evidential and **max depth 1** — it discovers and cites; it never justifies an action on its own.

### 4.3 The relationship that is deliberately absent

**There is no direct `Customer → Payment` edge.** It would be convenient and it would be wrong: payment relates to a Party through an Invoice, which relates through an Order. A shortcut edge creates two paths to the same fact, and two paths diverge. Traverse the chain.

---

## 5 · Lifecycle Design

Conceptual state machines. No storage implied.

### 5.1 The four lifecycle patterns

Nearly every object follows one of four shapes. Recognising this prevents inventing a bespoke lifecycle per object.

| Pattern | Shape | Objects |
|---|---|---|
| **Pursuit** | open → qualifying → resolved (win/lose) | Lead |
| **Fulfilment** | agreed → in progress → delivered → closed | Order, Project, Task |
| **Obligation** | raised → partially met → settled / defaulted | Invoice, Commitment |
| **Existence** | provisional → active → dormant → ended | Party, Asset, Offering, Location, Policy |

### 5.2 Detailed lifecycles

```
LEAD           new ─► qualified ─► proposed ─► negotiating ─► won
                 └────────┴───────────┴────────────┴────────► lost
                 └─► disqualified          └─► expired
   won/lost/disqualified/expired = TERMINAL.  lost REQUIRES a reason.

QUOTATION      draft ─► issued ─► accepted
                          ├─► rejected
                          ├─► expired        (valid_until passed)
                          └─► superseded     (new version issued)

ORDER          confirmed ─► in_fulfilment ─► delivered ─► closed
                    └──────────┴─────────────► cancelled

INVOICE        raised ─► part_paid ─► settled
                  ├────────┴─► overdue ─► written_off   (tier-4 approval)
                  └─► cancelled

PAYMENT        initiated ─► cleared
                    ├─► failed
                    └─► reversed            (appends, never deletes)

PROJECT        planned ─► active ─► on_hold ─► active ─► delivered ─► closed
                   └────────┴─────────┴──────────────► cancelled

TASK           todo ─► in_progress ─► blocked ─► in_progress ─► done
                  └───────┴──────────────┴────────────────► cancelled

COMMITMENT     made ─► in_progress ─► met
                 ├────────┴─► missed          (recorded, never deleted)
                 ├─► waived                   (requires approver)
                 └─► renegotiated ─► made     (new commitment, old one closed)

INTERACTION    scheduled ─► held ─► completed
                    ├─► cancelled
                    └─► no_show               (DISTINCT from cancelled)

PARTY          prospective ─► active ─► dormant ─► ended
                                  └─► merged     (reversible)

ASSET          acquired ─► commissioned ─► operating ⇄ down ─► retired ─► disposed

DOCUMENT       draft ─► executed ─► superseded
                            └─► void

POLICY         draft ─► active ─► superseded ─► retired
```

### 5.3 Rules governing all lifecycles

1. **Terminal states are terminal.** No transition out of `disposed`, `written_off`, `closed`, `ended`. Reopening means a **new object** linked by `temporal:supersedes`.
2. **Every transition is recorded** with actor, timestamp and reason — this feeds Organizational Intelligence.
3. **Unhappy states are first-class.** `lost`, `missed`, `no_show`, `disqualified`, `written_off`, `cancelled` are the states that carry the most business signal. A model with only happy paths teaches nothing.
4. **No object is deleted.** Terminal states, supersession and tombstones only.
5. **`on_hold` and `blocked` are reversible**; everything after them may not be.

---

## 6 · Cross-Module Rules

### 6.1 The rule

> **No vertical may define a new Party, Document, Interaction, Commitment or Location.**

Every industry has customers, paperwork, conversations, promises and places. A vertical that redefines them has forked the platform, and forks do not converge.

### 6.2 What each vertical actually adds

| Industry | Reuses unchanged | Adds (registry rows only) |
|---|---|---|
| **Transformer mfg.** | Party, Offering, Order, Invoice, Project, Document, Asset, Commitment | Entity: `TransformerUnit`, `Winding`, `TestCertificate`, `Tender`, `BOM`. Predicates: `kva_rating`, `impedance_pct`, `routine_test_result` |
| **Hospital** | Party, Interaction, Document, Commitment, Location | Entity: `Encounter`, `Order` (clinical), `Result`. Predicates: `triage_level`, `discharge_on`. **Policy: consent + residency** |
| **School** | Party, Interaction, Document, Commitment, Location | Entity: `Enrolment`, `Cohort`, `Assessment`. Predicates: `attendance_pct`, `grade` |
| **Retail** | Party, Offering, Order, Invoice, Payment, Location | Entity: `Basket`, `StoreVisit`. Predicates: `sku_velocity`. *Volume changes caching, not the model* |
| **Construction** | Party, Project, Task, Document, Asset, Commitment | Entity: `Site`, `Package`, `DrawingRevision`, `RFI`. **Drawing versioning is the whole game** |
| **Legal** | Party, Document, Interaction, Commitment | Entity: `Matter`, `Filing`, `Hearing`. **Privilege = a per-fact visibility rule, not a role** |
| **Accounting** | Party, Invoice, Payment, Document | Entity: `Ledger`, `Period`, `Reconciliation`. **Closed periods immutable** |

### 6.3 The two that will stress this model

Recorded now so they are not discovered during a sale:

- **Legal** — privilege is *per-fact*, not per-role. The frozen `visibility` + `acl_roles` model must be validated against it **before** a legal client is signed.
- **Hospital** — consent and data residency dominate everything, and consent is itself a Commitment with a lifecycle.

Neither is blocked by this model. Both need validation on paper first.

---

## 7 · Extension Rules

### 7.1 The contract

A vertical extends by **adding registry rows only**:

| Extension point | Mechanism | Code? |
|---|---|---|
| New entity type | Registry row, declaring one of 2A's six categories | No |
| New predicate | Registry row, declaring one of 2A's seven categories | No |
| New relationship type | Registry row, mapped to one of the six classes | No |
| New lifecycle | Registry row using one of the four patterns (§5.1) | No |
| New source system | Adapter conforming to the connector interface | **Adapter only** |
| New policy | Policy object row | No |

**Anything requiring a change to a core object is a platform gap, not a vertical.** That is the test.

### 7.2 Worked extensions

**Transformer Manufacturing**
```
TransformerUnit   extends Asset        (RESOURCE)
  + kva_rating (QUANTITATIVE, kVA) · impedance_pct · oil_type · routine_test_result
  + certified_by ──► TestCertificate   (Evidential)
  + supplied_under ► Tender            (Transactional)
Tender            extends Commitment   (OBLIGATION)   ← not a new object
```
Brain changes: **zero.** *"Which units will miss the delivery milestone?"* traverses the same `temporal:precedes` spine as *"which deals will slip?"* — because Project → Milestone → Delivery is structurally identical to Lead → Quotation → Order.

**Real Estate**
```
Parcel            extends Location     (PLACE)
Unit              extends Asset        (RESOURCE)
Tenancy           extends Commitment   (OBLIGATION)   ← a promise with a party and a term
  title chain = pure temporal:supersedes on Document
```

**Government Projects**
```
Scheme            extends Policy       (OBLIGATION)
Constituency      extends Location     (PLACE)
Grievance         extends Commitment   (OBLIGATION)   ← a promise to a citizen
Beneficiary       = PartyRole          ← NOT a new party type
```
`Beneficiary` as a **role** is the point. A citizen may be a beneficiary of three schemes, a grievance raiser, and a contractor's employee — one Party, four roles.

---

## 8 · Validation Rules

### V1 — No duplicate business objects
- Two objects may not share a category **and** an overlapping identifying assertion set
- A proposed object that can be expressed as an existing object + a role, or + a lifecycle state, or + a predicate **must be**. The four merges in §2.1 are this rule applied
- Human review gate; semantic duplication is not fully automatable (2A §V1)

### V2 — No semantic overlap
- Every object declares exactly one 2A category
- Every attribute maps to a registered predicate — no free-floating fields
- **If two objects answer the same business question, one must be removed**

### V3 — Stable identity
- Identity is a meaningless `knowledge_id`, permanent from creation
- Identifying assertions may change without changing identity (companies rename)
- Merge is reversible with full pre-merge state
- Lifecycle changes never change identity — a `won` Lead is the same object

### V4 — Reusable relationships
- Every relationship uses a registered type from one of the six frozen classes
- No object-pair-specific relationship where a generic one exists
- Inverses are **declared and derived**, never stored (2A §4.4)
- No shortcut edges duplicating a traversable path (§4.3)

### V5 — Future compatibility
- Attributes are additive; removal requires a new object version
- Lifecycle states are additive; removing one requires migrating existing instances
- Every attribute carries its `semantic_version`
- A vertical extension must not require modifying any core object

---

## 9 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | All 19 canonical objects defined with purpose, identity, lifecycle, required/optional attributes, relationships, ownership, rules, examples |
| 2 | Every object declares exactly one 2A entity category |
| 3 | Every attribute maps to a registered 2A predicate — zero free-floating fields |
| 4 | Every relationship maps to one of the six frozen classes |
| 5 | Every object has exactly one steward module and an accountable owner |
| 6 | Every lifecycle uses one of the four patterns, with terminal states marked |

### Modelling correctness — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 7 | Model a firm that is **both customer and supplier** | **One** Party, **one** `legal_name`, **two** PartyRoles; net position is a single query |
| 8 | End an employment | Role ends; Person unchanged; history intact |
| 9 | Model an employee who is also a customer | One Party, two roles, no duplication |
| 10 | Rename a company | Identity unchanged; old name retained with validity |
| 11 | Attempt to change a Party's kind | **REJECTED** — kind is frozen |
| 12 | Model a quotation revised three times | 3 versions, 2 `superseded`, 1 `issued`; all readable |
| 13 | Model an invoice with no order | **ACCEPTED** — the chain is typical, not mandatory |
| 14 | Model the same PDF sent to two customers | **One** Document, **two** Interactions |
| 15 | Traverse Customer → Payment | Only via Invoice → Order; **no shortcut edge exists** |
| 16 | Model a missed commitment | `missed` recorded and retained; not deleted |

### Extensibility — the criteria that matter most

| # | Test | Expected |
|---|---|---|
| 17 | Model **transformer manufacturing** end to end | Registry rows only; **zero core object changes** |
| 18 | Model **a hospital encounter** end to end | Registry rows only; zero core changes |
| 19 | Model **a government grievance** end to end | Registry rows only; `Beneficiary` is a role, not a type |
| 20 | Count core objects modified across 17–19 | **Exactly zero** |
| 21 | Record wall-clock time and author for #17 | Baseline for *days-to-onboard-a-vertical* |

### Non-regression

| # | Criterion |
|---|---|
| 22 | Zero application code touched; `api/webhook.py` byte-identical |
| 23 | Phase 1C suite green (226 tests); no-bypass invariant intact |
| 24 | Zero AI calls; zero schema; zero migrations |
| 25 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 20 is the acceptance test for this slice.** Criteria 1–16 prove the model is coherent. Only 17–20 prove it is *reusable*. If any vertical requires changing a core object, the model has failed regardless of how well-formed it is — and it is far cheaper to learn that on paper than after three industries are live.

---

## 10 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Party–Role separation** — Customer, Supplier and Employee become roles, not subtypes *(§0 — the structural correction)*
2. **Lead and Opportunity merge** into one object
3. **Product and Service merge** into `Offering`
4. **Meeting and Communication merge** into `Interaction`
5. **`Commitment` as a first-class core object** — the generalisation that makes *"what have we promised?"* answerable
6. **No shortcut relationships** — traverse the chain
7. The four lifecycle patterns, and terminal states being genuinely terminal

**Four of the twenty-three proposed objects are merged and three are reclassified.** Every change removes an ambiguity that would otherwise recur for a decade. If the Party–Role correction is rejected, this document needs rework before implementation — not during it, because every relationship in §4 assumes it.
