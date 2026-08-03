# IDD 2E — Organizational Intelligence

**Status:** Design · No implementation · 2026-08-03
**Depends on:** 2A Semantic Registry · 2B Core Business Objects · 2C Knowledge Assertions · 2D Party & Identity (all frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · The thesis, and the thing that could go wrong

**Thesis.** The Brain gets better every year without the model changing, because the *evidence available to it* improves. OI is where that evidence accumulates.

```
Brain decides  ──►  OI records the DECISION (+ its evidence reference)
                          │
                    world responds
                          │
                    OI records the OUTCOME (asynchronously, later)
                          │
              Learning mines DECISION+OUTCOME pairs
                          │
              writes DERIVED KNOWLEDGE ──► Brain reasons better
                          │
                      (loop closes)
```

The LLM stays a commodity. What compounds is *ours*.

### The risk this document must design against

> **A system that learns from its own history will automate its habits — including the bad ones — and do so with the false authority of repetition.**

Three specific failures, and where each is addressed:

| Failure | Mechanism | Addressed |
|---|---|---|
| **Precedent poisoning** | "We did X 50 times" becomes evidence, though 30 went badly | §5.3 — outcome-weighted, never frequency-weighted |
| **Bias fossilisation** | "We always rejected that segment" becomes "we should" | §5.5 — Lessons are hypotheses, never rules |
| **Surveillance drift** | OI quietly becomes employee monitoring | §1.4 — subject restricted to decisions, not people |

Each is easier to prevent now than to remove later.

---

## 1 · What Organizational Intelligence Is

### 1.1 The one-line definition

> **Knowledge is what we know about the world. Organizational Intelligence is what we know about our own conduct.**

The test is **who the subject is.**

- *"Acme's credit limit is ₹5,00,000"* — subject is Acme. **Knowledge.**
- *"We approved an 18% discount for Acme on 3 August against the margin guideline, and they paid 40 days late"* — subject is **us**. **OI.**

### 1.2 Six things, sharply separated

| | Subject | Retention | Mutable? | Answers |
|---|---|---|---|---|
| **Knowledge** | The world | Long, superseded | Append-only | *What is true?* |
| **Organizational Intelligence** | **Us** | **Permanent** | **Immutable, annotatable** | *What did we decide, do, and get?* |
| **Memory** | The current turn | **Discarded at turn end** | Ephemeral | *What am I holding right now?* |
| **Logs** | Technical events | Hours to days | Append-only | *What did the software do?* |
| **Analytics** | Derived measures | Recomputed | **A view, not a store** | *What do the numbers say?* |
| **History** | Time itself | — | — | **Not a thing — a dimension of the other five** |

Two of these are commonly confused with OI and are not:

**Logs are not OI.** A log says `POST /api/webhook 200 5ms`. OI says *"we permitted a discount because margin history supported it."* Logs are technical, expire in hours, and carry no business meaning. Conflating them produces an OI store full of noise and an audit trail full of nothing.

**Analytics is not OI.** Analytics is a *view* computed over knowledge and OI. It has no independent existence. Building "an analytics store" alongside OI creates a second source of truth for numbers that must agree — and they will not.

**Memory is explicitly not persistent.** Per the Brain runtime spec: anything surviving a turn was written somewhere auditable. Memory is what the Brain holds *during* a turn and discards after. If it persisted, no decision would be reproducible.

### 1.3 Why OI must exist as its own substrate

Four properties that Knowledge cannot provide:

| Property | Why Knowledge cannot supply it |
|---|---|
| **Immutability of the record** | Knowledge is *superseded* as the world changes. **A decision, once made, is history and can never be revised** — only annotated |
| **Different erasure obligations** | A customer may demand erasure of their data. They cannot erase our record that we made a decision — though it must be de-identified (§1.5) |
| **Internal-only visibility** | Knowledge may be partly customer-facing. Decision history never is |
| **It is the only non-replicable asset** | A competitor can sync the same CRM, buy the same model, and read this document. They cannot obtain five years of *your* decisions and what they led to |

### 1.4 What OI must never become

> **OI records decisions and their outcomes. It does not record people and their activity.**

The line matters because it is one product decision away from being crossed. *"Which employee has the worst decision record?"* is a question this data could answer, and answering it turns an institutional-learning system into a surveillance system — after which nobody records honestly, and the asset is destroyed.

**Design constraint:** the subject of an OI record is a **decision**, never a person. `decided_by` exists for accountability and audit, not for aggregation into performance metrics. Aggregating decision quality by individual is out of scope permanently, not just for now.

### 1.5 Erasure and the audit obligation

These conflict, and the conflict must be resolved explicitly rather than discovered later.

| Obligation | Requirement |
|---|---|
| Data protection | A party may require erasure of their personal data |
| Audit / accounting | We must be able to reproduce why a decision was made |

**Resolution: OI references parties by `knowledge_id`, never by identity.** On erasure, the party's *claims* are purged and a tombstone remains. The OI record survives intact — its shape, reasoning and outcome are preserved, and the subject is a de-identified reference.

*"On 3 August we approved an 18% discount for a party in the Belagavi segment with 11 prior orders"* remains answerable and auditable. Who they were does not.

---

## 2 · Decision Model

### 2.1 What a Decision record holds

```
DECISION
├── IDENTITY
│   ├── decision_id · tenant_id
│   ├── turn_ref · goal_ref
│   ├── brain_version         ← which cognition produced it
│   └── engine_version        ← which adjudicator judged it
│
├── CONTEXT
│   ├── evidence_ref          → the frozen Context Packet (§2.3)
│   ├── decisive_facts[]      → inline copy of the facts that MATTERED
│   ├── assumptions[]         → defaults, inferences, bridged gaps
│   └── known_gaps[]          → what we knew we did not know
│
├── CLASSIFICATION
│   ├── category · impact · reversibility · risk_level
│   └── mode                  normal | emergency | degraded
│
├── PRINCIPAL
│   ├── decided_by            the resolved principal
│   ├── authority_basis       role, delegation chain
│   └── accountable_human     ← NEVER NULL, even when autonomous
│
├── ALTERNATIVES
│   ├── chosen                the action taken
│   └── rejected[]            each with its REJECTION REASON
│
├── REASONING
│   ├── rules_applied[]       + policy_version
│   ├── decisive_rule         which one actually settled it
│   ├── precedent_refs[]      prior decisions consulted (§9)
│   └── confidence_vector     + projected scalar + required floor
│
├── VERDICT
│   ├── verdict               PERMIT | DENY | ESCALATE | ABSTAIN
│   ├── gate_results[]        in order, with the first failure
│   └── approval              approvers, timestamps, basis shown to them
│
└── MODEL  (null when no model was consulted)
    ├── model_identity + version
    ├── task_contract         CLASSIFY | EXTRACT | DRAFT | PLAN …
    └── proposal_accepted     was the model's proposal taken?
```

### 2.2 The two fields that are almost always omitted

**`rejected[]` with reasons.** Without it, *"why not something else?"* is permanently unanswerable, and every post-mortem becomes speculation. It is also what makes precedent useful — knowing we *considered and rejected* an option is often worth more than knowing we chose another.

**`assumptions[]`.** When evidence is absent, something fills the gap — a default, an inference, a convention. Unrecorded, the decision appears to rest on evidence it did not have. **This is the most common way a well-audited system turns out to have been guessing.**

### 2.3 Evidence: referenced, with a decisive subset inlined

Per 2C §1.3, OI **references** the evidence packet; it never copies the knowledge plane. But a reference to a packet that has been pruned is a dangling pointer, and replay then fails silently.

**Tiered retention:**

| Tier | Content | Retained |
|---|---|---|
| **Inline** | `decisive_facts` — the handful that actually settled it, with provenance and values as they stood | **Forever, with the decision** |
| **Referenced** | The full Context Packet | Per packet retention policy |
| **Degraded** | If the packet is pruned, replay proceeds on the decisive subset | Flagged as `PARTIAL_EVIDENCE` |

This keeps decisions replayable-without-the-world (the Decision Engine's core requirement) at bounded cost, and — critically — **replay degradation is visible rather than silent.**

### 2.4 Immutability and annotation

A Decision is **immutable**. It may be **annotated** — *"later found to rest on a stale credit limit"* — and annotations are themselves timestamped and attributed.

**A decision is never edited, and never deleted.** Editing one would make every dependent analysis unreproducible; deleting one would make the pattern of deletions the most interesting thing in the dataset.

---

## 3 · Execution Model

### 3.1 The record

```
EXECUTION
├── decision_ref              → the authorising decision
├── plan
│   ├── planned_actions[]     the task DAG as approved
│   └── task_ref              which task this execution is
├── invocation
│   ├── capability + version
│   ├── idempotency_key
│   ├── authorization_ref     the scoped, expiring grant used
│   └── preconditions_verified_at_issuance[]
├── result
│   ├── status                SUCCEEDED | FAILED | PARTIAL | TIMED_OUT
│   ├── error_class           when failed
│   └── output_ref            never the output itself if it carries PII
├── retry
│   ├── attempt_no + of_max
│   ├── retry_policy          the declared policy for this capability
│   └── prior_attempt_refs[]
├── compensation
│   ├── required · performed · compensation_ref
│   └── residual_state        ← what remains inconsistent, if anything
└── cost
    ├── duration_ms · db_queries
    ├── model_tokens (in/out) · currency_cost
    └── capability_cost_class
```

### 3.2 Three fields that earn their place

**`preconditions_verified_at_issuance`.** The Decision Engine re-verifies critical preconditions when the authorization is issued, not when the verdict was reached. Recording *what was re-checked and what it found* is what makes a TOCTOU incident diagnosable rather than mysterious.

**`residual_state`.** When compensation partially succeeds, something is left inconsistent. Recording *what* turns an incident into a work item. Omitting it means the inconsistency is discovered months later by an auditor.

**`cost`.** Not for billing — for **learning**. *"This decision path costs ₹40 and succeeds 60% of the time"* is exactly the kind of fact that should change behaviour, and it is invisible without per-execution cost.

### 3.3 Retry and idempotency

Per the Brain runtime spec: **non-idempotent writes are never retried automatically.** The execution record proves the rule was honoured, by carrying the idempotency key and the declared retry policy. A retry without a key in the record is a defect, detectable by inspection.

---

## 4 · Outcome Model

### 4.1 Three records, three clocks

| Record | When | Certain? | Question |
|---|---|---|---|
| **Decision** | Synchronously, before acting | ✅ we know what we chose | *What did we decide?* |
| **Execution** | Synchronously, after acting | ✅ we know what the system returned | *What did we do?* |
| **Outcome** | **Asynchronously — hours to months** | ⚠️ only when the world responds | *What did it lead to?* |

### 4.2 Why Outcome must be asynchronous — and the failure if it is not

**The outcome of "send the quotation" is whether they accept it.** That happens in four days, not four milliseconds.

> **The failure mode: recording execution success as outcome.** *"Quotation sent successfully"* is an execution result. Train the Learning Layer on it and you learn **whether your API works** — not whether you win deals. The models produced would be confidently, uselessly wrong, and nothing would surface the error, because every metric would look healthy.

This is the single most consequential separation in OI, and it is the one most systems collapse.

### 4.3 Worked examples

| Object | Execution result *(immediate)* | Outcome *(later)* | Typical lag |
|---|---|---|---|
| **Quotation** | Sent, delivered | Accepted / rejected / expired / **ignored** | 2–30 days |
| **Project** | Kicked off | Delivered on time & margin / late / over budget / cancelled | 1–12 months |
| **Invoice** | Raised, delivered | Settled on time / late by N days / written off | 15–120 days |
| **Lead** | Contacted, replied | Converted / lost / disqualified / **went silent** | 1–90 days |
| **Complaint** | Acknowledged, resolved | Party retained / churned / escalated / referred us anyway | 1–24 months |

### 4.4 `UNKNOWN` is a valid outcome and a real signal

Most outcomes never arrive explicitly. The customer does not send a rejection — they go quiet.

| Outcome state | Meaning |
|---|---|
| `OBSERVED` | We learned what happened |
| `INFERRED` | Derived from a proxy (an invoice settled ⇒ the project delivered) — **lower confidence** |
| `TIMED_OUT` | The window passed with no signal. **This is data** |
| `UNOBSERVABLE` | We never had a way to learn it |

**`TIMED_OUT` on a quotation is a lost deal by silence**, and it is one of the most common outcomes in a small business. A model that only learns from explicit wins and losses is trained on a biased sample, and biased toward the customers who bother to reply.

### 4.5 Outcomes never mutate decisions

An outcome **links** to its decision. It does not modify it. Decisions stay immutable; the chain `Decision → Execution → Outcome` is assembled by traversal, not by updating a record.

This is also what prevents **hindsight contamination**: the decision records the evidence as it stood, and the outcome is appended alongside. Reading them together answers *"was the decision wrong, or was the world unkind?"* — which is the difference between learning and superstition.

---

## 5 · Lessons

### 5.1 What a Lesson is — and is not

> **A Lesson is a generalisation across decisions and outcomes. It is a HYPOTHESIS, not a rule.**

```
LESSON
├── claim              "discounts above 15% correlate with payment delay > 30 days"
├── scope              segment, size band, geography, period, offering class
├── evidence
│   ├── supporting_decisions[]   with outcomes
│   ├── contradicting_decisions[]  ← REQUIRED, not optional
│   ├── sample_size · effect_size · confidence_interval
├── derived_at · derived_by       (human | learning layer)
├── status             PROPOSED | ACTIVE | WEAKENING | RETIRED | REFUTED
├── expiry             explicit, or a re-validation cadence
└── promoted_to_policy null | policy_ref   ← REQUIRES A HUMAN (§5.5)
```

### 5.2 What qualifies as a Lesson

All four must hold:

1. **Minimum sample.** A single outcome is an anecdote. Threshold declared per lesson class, never universal
2. **Outcome-linked.** Decisions with no outcome contribute nothing
3. **Contradicting evidence recorded.** A lesson citing only supporting cases is not a lesson, it is a belief
4. **Scoped.** *"Discounts cause delays"* is unusable. *"Above 15%, for new customers in retail, in FY25"* is testable

### 5.3 Outcome-weighted, never frequency-weighted

> **"We did X fifty times" is not evidence if thirty went badly.**

Frequency-weighted precedent automates habits, with the confidence conferred by repetition. Every lesson weights by **outcome quality**, not occurrence count.

**Corollary — negative lessons are first-class.** *"We tried this four times and lost three"* is more actionable than most positive findings, and systems that only surface successes are systematically over-confident.

### 5.4 When a Lesson becomes obsolete

| Trigger | Meaning |
|---|---|
| **Expiry reached** | Every lesson carries one. **A lesson without an expiry is dogma** |
| **Contradicting evidence accumulates** | Recent outcomes diverge → `WEAKENING` |
| **Scope conditions no longer hold** | The segment, market or regulation changed |
| **Refuted** | A deliberate test contradicted it |
| **Outcome drift detected** | §7.6 — the same decision now yields different outcomes |
| **Superseded** | A better-scoped lesson replaces it |

**Retired lessons are retained.** *"We used to believe this, and stopped in 2029 because…"* is itself organisational knowledge, and it prevents the same wrong lesson being rediscovered.

### 5.5 Lessons never become rules automatically

> **A Lesson informs decisions as EVIDENCE. It never determines them as POLICY.**
> **Promotion to Policy is a human decision — Structural category, risk level L5.**

This is the guard against bias fossilisation. Without it, *"we always rejected this segment"* becomes *"we should reject this segment"* — encoded, enforced, and invisible.

Automatic promotion would also make the system's rules unauditable: nobody could say who decided, when, or on what basis. **The gap between "the data suggests" and "the business has decided" must have a human in it, permanently.**

---

## 6 · Organizational Experience

### 6.1 Experience is derived knowledge — not a fourth substrate

The important simplification.

**Experience is not a new store.** It is **derived claims in the knowledge plane** (2C §8), computed from OI, reaching the Brain as ordinary facts with formula, inputs and lineage.

```
OI  (decisions + executions + outcomes)
        │
        │  Learning Layer, asynchronous, off the request path
        ▼
DERIVED CLAIMS in the knowledge plane
   supplier_reliability = 0.73   formula, inputs, computed_at, tier 3
        │
        ▼
Read by the Brain like any other fact — capped, explainable, invalidated
```

Inventing an "experience store" would create a fourth thing needing its own retrieval, provenance and explanation. Routing it through derived knowledge means **one explanation mechanism** serves observed and learned facts alike — the property that makes the whole platform explainable with one implementation.

### 6.2 What accumulates

| Experience | Derived from | Subject |
|---|---|---|
| Supplier reliability | Commitments met/missed, delivery outcomes | Party |
| Customer payment behaviour | Invoice settlement vs due date | Party |
| Customer risk | Disputes, churn signals, payment history | Party |
| Preferred supplier by category | Reliability × price × lead time | Offering class |
| Channel effectiveness | Lead source → conversion outcome | Channel |
| Project pattern | Estimate vs actual, by project type | Offering class |
| Sales pattern | Win rate by segment, discount band, season | Segment |
| Approval timeliness | Government submission → approval lag | Authority |

### 6.3 The rules experience inherits

Because it is derived knowledge, it automatically obeys 2C §8:

- **Capped below its weakest input** — experience built on tier-4 extractions cannot exceed tier 4
- **Never authoritative** — a computed reliability score never outranks an asserted fact
- **Invalidated when inputs change**, not on a timer
- **Depth-capped at 2** — a score built on a score built on a score is numerology
- **Deletable and rebuildable** — it is a projection, not a fact

### 6.4 Sample size is part of the value

*"Reliability 0.73"* is meaningless alone. *"0.73, n=4"* and *"0.73, n=180"* are different facts, and the first should not drive a tier-4 decision.

**Every experience claim carries its sample size and confidence interval.** Consumers that ignore them are misusing the data, and the Sufficiency Gate can enforce a minimum n by risk tier.

---

## 7 · Decision Replay

Extending the mechanism proven in Phase 1C.

### 7.1 The property that makes replay possible

> **Freeze the packet; vary one thing.**

Because evidence is referenced and the decisive subset inlined (§2.3), a decision can be re-adjudicated without querying live systems. If replay must query the world, it is not replay — it is a new decision wearing a historical label.

### 7.2 Five modes, deliberately distinguished

| Mode | Holds fixed | Varies | Answers |
|---|---|---|---|
| **Fidelity** | Evidence, policy, thresholds — all as of then | **Engine/Brain version** | Does the new version decide the same? |
| **Version comparison** | Evidence | **Two named versions** | What changed between v3 and v4? |
| **Historical** | Everything as of then | Nothing | Was that decision sound *on what we knew*? |
| **Counterfactual** | Evidence | **Policy or thresholds, as of now** | Would we decide differently today? |
| **Evidential** | Engine, policy | **Evidence — adding what we later learned** | Was it wrong, or unlucky? |

**Conflating fidelity and counterfactual is the classic replay error.** Replaying old decisions under new policy and calling the differences "regressions" floods the harness with false alarms — the engine is fine, the rules changed — and a muted harness protects nothing.

**Evidential replay is the one that makes an organisation mature.** *"Was the decision wrong, or was the world unkind?"* is a question almost no business can answer, and it is the difference between learning and blame.

### 7.3 Regression detection

Against a maintained corpus of decisions with known-good verdicts:

| Class | Meaning | Gate |
|---|---|---|
| **Safety regression** | Something previously denied is now permitted | **Blocks release** |
| **Authority regression** | A decision now requires less approval | **Blocks release** |
| **Correctness regression** | A previously-right verdict is now wrong | Blocks release |
| **Explanation regression** | Same verdict, weaker justification | Review |
| **Cost regression** | Same verdict, materially more expensive | Review |
| **Improvement** | Previously wrong, now right | Add to corpus |

**The corpus must be adversarially maintained** — near-misses, disputed calls, and decisions that went badly. A corpus of easy cases proves only that easy cases are easy.

### 7.4 Decision drift

The same decision inputs now produce a different decision.

| Cause | Legitimate? |
|---|---|
| Brain version changed | ✅ if intended and reviewed |
| Policy changed | ✅ if approved |
| Thresholds changed | ⚠️ **only if approved as an L5 decision** |
| Model roster changed | ⚠️ investigate — the packet should dominate |
| **Nothing identifiable changed** | ❌ **investigate immediately** |

The last row is the alarming one. Unexplained drift means hidden state has entered the system — the failure the Brain's memory rules exist to prevent.

### 7.5 Confidence drift

Stated confidence stops matching observed outcomes.

> **If decisions made at 0.8 confidence turn out right 55% of the time, the confidence scale is broken and must be fixed or withdrawn.**

Calibration is measured continuously by bucketing decisions by stated confidence and comparing against outcomes. **A published calibration curve is the only honest claim a system can make about how much it should be trusted.** Everything else is marketing.

### 7.6 Outcome drift — the third drift, and the one that ages Lessons

Not in the brief; it is the drift that matters most for §5.

> **The same decision, made the same way, now produces a different outcome — because the world changed.**

Neither the engine nor the confidence scale is broken. Reality moved. A discount strategy that worked in a growth market fails in a downturn; a supplier that was reliable for three years changes ownership.

**Outcome drift is the primary trigger for lesson obsolescence** (§5.4). Without it, lessons calcify: they keep testing as "supported" against historical evidence while quietly ceasing to be true.

---

## 8 · Explainability

Five questions, each answered **from records** — never reconstructed, because a reconstruction is a plausible story, and a plausible story about a decision is worse than none because it is believed.

| Question | Answered from |
|---|---|
| **Why this?** | Verdict + gates passed + `decisive_rule` + `decisive_facts` |
| **Why not another?** | `rejected[]` with per-alternative rejection reasons |
| **Why this tool?** | Capability selection: required, authorised, available, and why cheaper options were insufficient |
| **Why this knowledge?** | Retrieval trace: slots requested, capabilities called, ranking, conflicts resolved, what was pruned |
| **Why this rule?** | `rules_applied` + `policy_version` — **the rules as they stood then**, not as they stand now |

### 8.1 Two rules

**Explanation is a capability, not a log.** If nothing calls it, it rots silently. Making it user-facing keeps it correct, because users notice when it is wrong.

**A model may narrate an explanation; it may never generate one.** Content comes from records; the LLM makes it readable. A model-authored explanation is a fiction fitted to the outcome — convincing, unfalsifiable, and worthless.

### 8.2 Explaining a Lesson

Lessons need one more question: **"why do you believe this?"** — answered by supporting decisions, **contradicting** decisions, sample size, effect size, scope and expiry. A lesson that cannot show its contradicting evidence is not explainable and must not be `ACTIVE`.

---

## 9 · OI Retrieval

### 9.1 The question being answered

> *"Have we been here before, and how did it go?"*

Retrieval happens at the **precedent rung** of the decision ladder — before consulting a model, after deterministic rules and policy. Most decisions should terminate here or above.

### 9.2 Similarity is structural, never textual

**Do not use embedding similarity over decision text.** It matches on phrasing, not situation — two decisions worded alike may be entirely different, and two identical situations described differently would never match.

Comparison is over **structured features**:

| Feature | Weight driver |
|---|---|
| **Decision category** | Must match exactly — a Value decision is not precedent for an Authority decision |
| **Risk level** | Must be within one level |
| **Slot profile** | Which evidence slots were filled |
| **Party characteristics** | Segment, size band, tenure, geography — **not identity** |
| **Offering class** | What was being decided about |
| **Temporal context** | Season, fiscal period, market conditions |

### 9.3 Ranking

| Signal | Rule |
|---|---|
| **Structural similarity** | Category and risk are gates, not weights |
| **Outcome quality** | **Weighted by outcome, never by frequency** (§5.3) |
| **Recency** | Decayed — but decay rate is *domain-specific*, not global |
| **Sample size** | n=3 and n=300 are different evidence; surfaced, never hidden |
| **Success AND failure rate** | **Both returned.** A precedent set showing only successes is a lie by omission |
| **Business context match** | Same segment beats a general pattern |

### 9.4 What retrieval must return

Not a verdict — **evidence**:

```
PRECEDENT SET
├── comparable_decisions[]   with verdicts and outcomes
├── outcome_distribution     won / lost / timed_out / unknown
├── sample_size + coverage   how much of the space this represents
├── contradicting_cases[]    ← ALWAYS, never filtered out
├── applicable_lessons[]     with scope, expiry and confidence
└── gaps                     "no comparable precedent" is a valid, useful answer
```

**"We have never been here before" is a valuable answer** and must be returned explicitly. Silently returning weak precedent as though it were strong is how a system becomes confidently wrong.

### 9.5 Precedent never decides

Precedent is **evidence at the fourth rung**, not authority. It informs the proposal and the confidence assessment. It cannot override policy, and it cannot lift a decision above its required approval level.

**A pattern of past approvals is not permission.**

---

## 10 · Future Expansion

OI is domain-blind by construction. It reasons about **decisions**, never about transformers or patients. Every vertical contributes decisions and outcomes in the same shape.

| Industry | Characteristic decision | Outcome | Lag | Lesson it produces |
|---|---|---|---|---|
| **Manufacturing** | Accept a spec deviation | Field failure rate, warranty claims | 6–24 mo | Which deviations are safe |
| **Healthcare** | Discharge timing | Readmission within 30 days | 30 days | Discharge criteria refinement |
| **Education** | Intervention for an at-risk student | Term outcome, retention | 3–12 mo | Which interventions work, for whom |
| **Construction** | Approve a design change | Schedule slip, cost variance | 1–18 mo | Change-order risk patterns |
| **Retail** | Markdown timing and depth | Sell-through, margin realised | 1–8 wk | Markdown curves by category |
| **Government** | Prioritise a grievance | Resolution time, citizen satisfaction | 1–6 mo | Which categories need escalation |

### 10.1 Why no redesign is needed

Every row above is: *a decision, made on evidence, under policy, with an outcome arriving later*. The **structure is identical**; only the vocabulary differs — and vocabulary lives in the 2A registry.

The domain-specific parts — what counts as an outcome, how long to wait, what a lesson's scope is — are **registry rows and configuration**, never OI code.

### 10.2 The one genuine variation

**Outcome lag varies by three orders of magnitude** — retail markdown in weeks, manufacturing field failure in years.

Consequence: **the outcome-window is a per-decision-type declaration**, not a global constant. A global timeout would either mark manufacturing outcomes `TIMED_OUT` while they are still pending, or leave retail decisions open for years.

This is the only place a vertical materially changes OI behaviour, and it is a declared parameter rather than a code path.

---

## 11 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Decision, Execution and Outcome are **three distinct records on three clocks** |
| 2 | Decision includes `rejected[]` with reasons and `assumptions[]` |
| 3 | `accountable_human` is non-null on **every** decision, including autonomous ones |
| 4 | Evidence referenced with a decisive subset inlined; degraded replay flagged |
| 5 | Lesson carries scope, expiry, sample size and **contradicting evidence** |
| 6 | Experience is **derived knowledge**, not a separate substrate |
| 7 | Five replay modes defined and distinguished |
| 8 | Three drifts defined: decision, confidence, **outcome** |
| 9 | Retrieval returns a precedent **set** with contradicting cases, never a verdict |
| 10 | Outcome window is declared per decision type |

### Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 11 | Attempt to edit a committed decision | **REJECTED**; annotation permitted |
| 12 | Record execution success as outcome | **REJECTED** — different records, different clocks |
| 13 | Quotation sent, no reply for the declared window | Outcome `TIMED_OUT`, **retained as data** |
| 14 | Complete one Decision → Execution → Outcome chain in production | Traversable end to end |
| 15 | Derive a lesson from 50 decisions, 30 with bad outcomes | Lesson reflects **outcome weighting**, not frequency |
| 16 | Propose a lesson with only supporting evidence | **REJECTED** — contradicting evidence required |
| 17 | Lesson with no expiry | **REJECTED** |
| 18 | Attempt automatic Lesson → Policy promotion | **REJECTED** — requires a human, L5 |
| 19 | Experience claim contradicts an asserted fact | **Asserted fact wins** |
| 20 | Experience claim without sample size | **REJECTED** |
| 21 | Fidelity replay after a policy change | Policy change **not** reported as a regression |
| 22 | Counterfactual replay | Clearly labelled as counterfactual, never as a regression |
| 23 | Evidential replay with later-learned facts | Distinguishes *wrong decision* from *unlucky outcome* |
| 24 | Decision drift with no identifiable cause | **Flagged for investigation** |
| 25 | Confidence calibration: 0.8-bucket right 55% of the time | **Scale flagged as broken** |
| 26 | Outcome drift detected | Dependent lessons move to `WEAKENING` |
| 27 | Retrieval where no comparable precedent exists | Returns **"no precedent"** explicitly |
| 28 | Retrieval where 3 of 4 precedents failed | **Failures surfaced**, not filtered |
| 29 | Precedent pattern of approvals on a tier-4 action | **Does not** lower the approval requirement |
| 30 | Erase a party who appears in decisions | Claims purged; **decision records survive de-identified** |
| 31 | Aggregate decision quality by individual employee | **Not supported** — out of scope by design |

### Compounding — the criteria that matter most

| # | Criterion |
|---|---|
| 32 | A decision made today is **replayable in full** with no live system queries |
| 33 | The Brain consults precedent **before** consulting a model, and this is visible in the trace |
| 34 | At least one lesson has been derived, tested against new outcomes, and **retired or reinforced** on evidence |
| 35 | A published calibration curve exists and is updated continuously |

### Non-regression

| # | Criterion |
|---|---|
| 36 | Zero application code touched |
| 37 | Phase 1C suite green (226 tests) |
| 38 | Compatible with 2A–2D; no frozen concept modified |
| 39 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 34 is the acceptance test for this slice.** Everything else proves OI is well-formed. Only 34 proves it is *learning* — that the organisation formed a belief, tested it against reality, and changed its mind on evidence. A store of decisions that never changes any belief is an archive, not intelligence.

---

## 12 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | **Precedent poisoning** — bad habits automated with the authority of repetition | **High** | Outcome-weighted, never frequency-weighted (§5.3) |
| **R2** | **Bias fossilisation** — "we always rejected X" becomes "we should" | **High** | Lessons are hypotheses; promotion to policy requires a human (§5.5) |
| **R3** | **Surveillance drift** — OI becomes employee monitoring | **High** | Subject is a decision, never a person. Individual aggregation out of scope permanently (§1.4) |
| **R4** | **Execution mistaken for outcome** | **High** | Separate records, separate clocks, enforced (§4.2) |
| **R5** | Outcomes never arrive; the loop stays open | Medium | Declared windows, `TIMED_OUT` as data, arrival rate monitored |
| **R6** | Lessons calcify while testing as "supported" | Medium | Mandatory expiry + outcome-drift trigger (§7.6) |
| **R7** | OI grows unbounded | Medium | Rollup pattern proven in 1C; decisions retained, executions rolled up |
| **R8** | Nothing consumes OI, so it silently breaks | Medium | Retrieval (§9) shipped in the same slice — a write-only store rots |
| **R9** | Erasure vs audit conflict discovered late | Medium | Resolved now (§1.5): de-identified references, tombstones |

---

## 13 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **OI's subject is a decision, never a person** — individual performance aggregation is permanently out of scope
2. **Decision, Execution and Outcome are three records on three clocks** — execution success is never an outcome
3. **`rejected[]` and `assumptions[]` are mandatory** — without them, *"why not?"* and *"what did we guess?"* are unanswerable forever
4. **Experience is derived knowledge**, not a fourth substrate
5. **Lessons are hypotheses; promotion to Policy requires a human at L5**
6. **Lessons are outcome-weighted, carry mandatory expiry, and must record contradicting evidence**
7. **Precedent is evidence at the fourth rung, never authority** — a pattern of approvals is not permission
8. **Similarity is structural, never textual** — no embeddings over decision text
9. **`TIMED_OUT` is a valid outcome and real data**
10. **Erasure de-identifies OI records; it never deletes them**

Items 1, 5 and 7 are the ones that will come under pressure. Each will be argued as friction — *"just let it auto-promote the lesson", "the data clearly shows", "we already approved this ten times."*

**Each of those arguments is the risk arriving in a reasonable voice.** They are recorded here with their reasoning so that reversing them requires re-arguing the case, not merely finding the guard inconvenient.
