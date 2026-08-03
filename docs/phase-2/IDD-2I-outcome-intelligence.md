# IDD 2I — Outcome Intelligence

**Status:** Design · No implementation · 2026-08-03
**Depends on:** 2A–2H (all frozen). Extends 2E's Outcome record; **does not redesign it.**
**Gate:** implementation may not begin until this document is approved

---

## 0 · Two things to settle before designing

### 0.1 Outcome Intelligence is a subsystem, not a substrate

2E established three record types inside Organizational Intelligence: Decision, Execution, **Outcome**. This document goes deeper on the third.

> **Outcome remains a record type *within* OI. It does not become a fourth substrate.**

Knowledge, OI and Learning are the three stores. Adding "Outcome Intelligence" as a peer would give it its own retrieval, provenance and explanation machinery — duplicating what OI already owns, and creating exactly the sync debt this architecture has rejected five times.

What *is* distinct is the **process discipline**: decisions are synchronous and complete on creation; outcomes are asynchronous, revisable, frequently absent, and uncertainly attributed. That machinery — observation, confirmation, drift detection, learning readiness — is what this document designs.

**Subsystem, not substrate.**

### 0.2 The most important idea here: observation ≠ evaluation

The brief lists `Success` and `Failure` as outcome states. **They are not observations. They are judgements against an expectation that will itself change.**

```
OBSERVED  (immutable fact)              EVALUATED  (derived, recomputable)
"accepted, day 12, 14% margin"    →     "SUCCESS"   under FY25 targets (18%)
                                  →     "PARTIAL"   under FY26 targets (12%)
```

Record `SUCCESS` and you have baked in a definition of success that was true in 2026. When the margin target changes in 2028, every historical outcome silently means something different — and every lesson built on them is quietly wrong.

> **Record what happened. Derive whether it was good.**

The observation is an immutable OI record. The evaluation is **derived knowledge** (2C §8) — recomputable, versioned by the yardstick that produced it, and safe to rebuild when the yardstick changes.

This is the single decision that keeps a ten-year learning loop honest.

---

## 1 · What an Outcome Is

> **An Outcome is what the world did in response to what we did.**

Not what we intended. Not what the system returned. What actually happened, observed later, from outside.

### 1.1 The seven, separated

| | Subject | When known | Mutable | Answers |
|---|---|---|---|---|
| **Decision** | Our choice | Synchronously | Immutable | *What did we decide, and why?* |
| **Execution** | Our action | Synchronously | Immutable | *What did we do, and did the system accept it?* |
| **Outcome** | **The world's response** | **Asynchronously — later** | **Immutable; revisable by appending** | *What happened as a result?* |
| **Experience** | Aggregate behaviour | Continuously recomputed | Derived knowledge | *What is this party/segment usually like?* |
| **Lesson** | A generalisation | Proposed, tested | Retirable hypothesis | *What do we believe follows from this?* |
| **Policy** | A rule we chose | On approval | Versioned | *What are we obliged to do?* |
| **Knowledge** | The world | Continuously | Superseded | *What is true?* |

### 1.2 The two boundaries that get blurred

**Execution ≠ Outcome.** *"Quotation sent, HTTP 200"* is an execution result. *"Quotation accepted on day 12"* is an outcome. Train on the first and you learn **whether your integration works** — not whether you win deals. Every metric stays green while the models become confidently useless. (2E §4.2.)

**Lesson ≠ Policy.** An outcome informs a lesson; a lesson is a hypothesis; a policy is a rule the business has *chosen*. **Promotion from lesson to policy requires a human at L5** (2E §5.5). The gap between *"the data suggests"* and *"we have decided"* must have a person in it, permanently — otherwise past bias becomes enforced rule with nobody accountable.

---

## 2 · Outcome Model

### 2.1 The corrected state set

The brief's nine states mix three different things. Separated:

| Proposed | What it actually is | Where it belongs |
|---|---|---|
| Success | **Evaluation** | Derived (§2.4) |
| Failure | **Evaluation** | Derived (§2.4) |
| Partial success | **Evaluation** | Derived (§2.4) |
| Cancelled | Observation — an act occurred | ✅ Observed state |
| Expired | Observation — a deadline passed | ✅ Observed state |
| No response | Observation — **absence is data** | ✅ Observed state |
| Unknown | **Epistemic** — we did not observe | ✅ Observation status |
| **Delayed** | **A timing property, not a state** | An attribute (§2.3) |
| **Disputed** | **Two meanings, must be split** | §2.5 |

### 2.2 Observed outcome states — what the world did

| State | Meaning | Why it exists separately |
|---|---|---|
| **RESOLVED** | The thing concluded — accepted, paid, delivered, discharged | The base case. Evaluation judges *how well* |
| **DECLINED** | The counterparty actively said no | An **act**. Carries a reason and is learnable |
| **CANCELLED** | Called off — by them, by us, or by circumstance | Distinct from DECLINED: *who* cancelled changes what it teaches |
| **EXPIRED** | A deadline passed with no act | **Absence of decision**, not a decision. Often means we lost by inattention |
| **NO_RESPONSE** | We asked; nothing came back within the window | **The most common outcome in a small business.** Losing by silence is not the same as losing to a competitor |
| **SUPERSEDED** | Overtaken — renegotiated, replaced, restructured | Neither win nor loss. Forcing it into either corrupts both |

### 2.3 Observation status — how well we know

Orthogonal to state. Every outcome carries both.

| Status | Meaning |
|---|---|
| **OBSERVED** | Directly witnessed — payment cleared, reply received |
| **INFERRED** | Derived from a proxy — invoice settled ⇒ project delivered. **Lower confidence** |
| **REPORTED** | A party told us. **Tier 5, capped 0.50** (2C) |
| **TIMED_OUT** | The window closed with no signal. **This is data, not a gap** |
| **UNOBSERVABLE** | We never had a means to learn it. **Structurally different from timed out** |

**`TIMED_OUT` ≠ `UNKNOWN`.** The first means we watched and nothing came; the second means we never watched. A model trained without that distinction treats "no signal" and "no observation" identically, and learns from a biased sample — biased toward counterparties who bother to reply.

### 2.4 Evaluation — derived, never stored on the outcome

```
EVALUATION  (a derived claim, 2C §8)
├── outcome_ref          which observation is being judged
├── yardstick_ref        WHICH definition of good, WITH ITS VERSION
├── verdict              SUCCESS | PARTIAL | FAILURE | NEUTRAL
├── dimensions[]         margin, timeliness, satisfaction, cost
├── computed_at
└── supersedes           prior evaluation under an older yardstick
```

**Re-evaluable by construction.** Change the margin target and every historical outcome can be re-judged — because the observation never claimed to be good or bad.

### 2.5 `Disputed` splits in two

| Meaning | Where it belongs |
|---|---|
| **The counterparty disputed it** — a real business event | An **observed state** on the underlying object (an Invoice can be `disputed`), plus an Interaction. Not an outcome state |
| **Our sources disagree about what happened** | An **evidence conflict** on the outcome record (2C §5), surfaced, never silently resolved |

Collapsing them means *"the customer is contesting the bill"* and *"we can't tell if they paid"* become the same record. They demand opposite responses.

### 2.6 `Delayed` is an attribute

Every outcome carries `elapsed` and `variance_vs_expected`. A payment 40 days late that arrives is `RESOLVED` with a large positive variance. One that never arrives is `TIMED_OUT`.

**Delay describes the path; state describes the destination.** As a state it would be permanently ambiguous — a delayed outcome is still in flight, so it is not an outcome yet.

---

## 3 · Outcome Lifecycle

```
   decision executes
        │
① EXPECTED ─────────► a window opens, with a declared duration
        │              nothing observed yet
        ▼
② OBSERVED ─────────► a signal arrived
        │              status: OBSERVED | INFERRED | REPORTED
        ▼
③ CONFIRMED ────────► corroborated, or the window closed
        │              becomes eligible for learning (§7.1)
        ▼
④ CLOSED ───────────► terminal. No further observation expected
        │
        ⋮ (later)
⑤ REVISED ──────────► new evidence APPENDS; the original is never edited
        ⋮
⑥ RETIRED ──────────► too old to inform current lessons (§3.5)
```

### 3.1 Creation — at decision time, not at outcome time

> **The expectation is created when the decision is made, not when the result appears.**

An outcome that only exists once something is observed can never record `TIMED_OUT` — because nothing is watching. Creating the expectation up front is what makes silence measurable.

Each expectation declares: the observation window, what would count as a signal, and how to observe it.

### 3.2 Observation

Three routes: **direct** (payment clears), **inferred** (a proxy fires), **reported** (someone tells us). Each carries its status and confidence cap (§2.3).

### 3.3 Confirmation

An outcome becomes `CONFIRMED` when corroborated by a second source, **or** when the window closes and the absence itself is the answer.

**Confirmation is the gate to learning.** Provisional outcomes must never feed lesson generation — a lesson built on unconfirmed signal will be revised the moment reality arrives, and the lesson will already have influenced decisions.

### 3.4 Revision — append, never edit

Late evidence produces a **new observation** linked to the original. The original remains readable forever.

Without this, *"what did we believe about this outcome in March?"* becomes unanswerable — and that question is what distinguishes *the decision was wrong* from *the outcome was later revised*.

### 3.5 Retirement

An outcome is **retired from active learning** when its era no longer resembles the present (§8). It stays fully readable and replayable.

**Retirement is a learning-eligibility flag, not deletion.** *"We used to believe this, and stopped in 2029 because the market changed"* is itself organisational knowledge.

---

## 4 · Outcome Attribution

### 4.1 One attribution edge, everything else by traversal

```
OUTCOME ──attributed_to──► DECISION
                              │
              ┌───────────────┼───────────────┬──────────────┐
              ▼               ▼               ▼              ▼
          EXECUTION      EVIDENCE_REF      POLICY       GOAL / TASK
                              │
                              ▼
                    KNOWLEDGE ASSERTIONS
                              │
                              ▼
            PARTY · PROJECT · COMMITMENT · INVOICE
```

> **An outcome attributes to exactly one decision. Everything else is reachable from there.**

Direct edges to Customer or Project would be **shortcut edges** — forbidden by 2B §4.3, because two paths to the same fact will diverge. Traverse the chain.

### 4.2 Contributing factors are not attribution

A supplier delay affected the outcome but was not in the decision's evidence. Recording it as attribution would credit the decision with something it never saw.

| | Attribution | Contributing factor |
|---|---|---|
| Cardinality | **Exactly one** | Zero or many |
| Meaning | *This decision produced this outcome* | *This also influenced it* |
| Strength | Structural | **Associative — max depth 1** (2A) |
| May justify an action alone | — | **Never** |

Without this split, attribution inflates: every outcome ends up linked to everything plausibly nearby, and the learning signal drowns.

### 4.3 The honest limit — correlation, not causation

> **We cannot know whether we won because of the discount or because the competitor was late.**

Attribution records **which decision preceded which outcome**. It does not establish cause.

Three consequences, each load-bearing:

1. **Lessons inherit this uncertainty** and must carry it — a lesson claiming causation from attribution alone is unsupported
2. **Counterfactuals are unavailable.** We never observe what would have happened otherwise
3. **Contributing factors must be recorded** even when unquantifiable, or the model silently attributes their effect to the decision

A system that confidently attributes causation will learn wrong things confidently — which is worse than learning nothing, because it acts.

### 4.4 Multi-decision outcomes

Some outcomes follow a chain: quote → negotiate → discount → win. Which decision won it?

**Each decision gets its own outcome record for its own effect.** The final business result attributes to the **terminal** decision, with the chain reachable by `temporal:precedes` traversal.

Splitting one outcome across several decisions would require assigning weights — and any weighting scheme would be invented, not observed.

---

## 5 · Learning Signals

Not all evidence is equal. Confusing the classes is how a learning system acquires confident nonsense.

| # | Class | Example | Objective? | Delay | Confidence ceiling |
|---|---|---|---|---|---|
| 1 | **Deterministic metric** | Invoice settled; days late | ✅ | Short–medium | **1.00** — tier 0 |
| 2 | **Financial outcome** | Realised margin, cost variance | ✅ | Medium | **1.00** — tier 0 |
| 3 | **Operational outcome** | Delivered on date; defect count | ✅ | Medium | 0.90 |
| 4 | **Business KPI** | Conversion rate, churn | ✅ but **aggregate** | Long | 0.90 — see §5.2 |
| 5 | **Human feedback** | Owner marks a recommendation wrong | ✅ intent, ⚠️ sample | Immediate | **0.90** — tier 1 |
| 6 | **Customer feedback** | *"Your price was too high"* | ❌ **self-reported** | Variable | **0.50** — tier 5 |
| 7 | **Probabilistic signal** | Sentiment, engagement, propensity | ❌ inferred | Immediate | **0.60** — tier 4 |

### 5.1 The two that must never be treated as fact

**Customer feedback is tier 5.** *"Your price was too high"* is a stated reason, not the reason. It may be politeness, negotiation, or genuine. It is what they **said** — 2F §7.2's speech-act split applies exactly. Treating stated loss reasons as causes produces a pipeline that optimises for a story customers tell rather than the behaviour they exhibit.

**Probabilistic signals never decide.** Sentiment and propensity rank and prioritise. They may not satisfy a tier ≥ 3 action alone.

### 5.2 Human feedback is high-trust and low-sample

The owner marking a recommendation wrong is **tier 1** — authoritative about intent. But it is one observation, and one observation is not a lesson (2E §5.2).

**High trust, small sample.** It should update a specific case immediately and a general lesson only with corroboration.

### 5.3 KPIs are aggregates and cannot attribute

Conversion rate moving tells you *something* changed, never *which decision* caused it. KPIs are **drift detectors** (§8), not attribution evidence.

Using a KPI as outcome evidence for an individual decision is the most common way a learning system fools itself: the metric moves, a recent change is blamed, and the wrong lesson is learned confidently.

---

## 6 · Outcome Quality

Every outcome carries a quality vector — never a single score, for the reason given in 2C §7.2: a scalar hides which dimension is weak.

| Dimension | Question | Weak means |
|---|---|---|
| **Confidence** | How sure are we this is what happened? | Tier-capped by observation status |
| **Evidence strength** | How many independent sources? | One source, unreconciled |
| **Attribution certainty** | How cleanly does this trace to one decision? | Many contributing factors |
| **Timeliness** | Did it arrive within the expected window? | Very late outcomes are weak evidence |
| **Completeness** | Do we know the whole result, or a fragment? | Partial observation |

### 6.1 Time delay degrades evidential value

An outcome arriving far outside its window is **weaker evidence**, not stronger. The longer the gap, the more intervening causes could explain it.

Confidence decays with `variance_vs_expected`, and outcomes arriving beyond a declared multiple of the window are flagged `LATE_UNRELIABLE` — recorded, but excluded from lesson generation by default.

### 6.2 Contradictions

Two sources disagreeing about what happened is an **evidence conflict** (2C §5), resolved by the deterministic ladder with unresolved conflicts **surfaced, never silently picked**.

**A contradicted outcome is not learning-ready** (§7.1). Learning from a contested fact teaches whichever source happened to win a tiebreak.

### 6.3 Missing evidence

Four kinds, from 2C §5.6 — `UNKNOWN`, `NOT_APPLICABLE`, `REFUSED`, `PENDING`.

**`REFUSED` is commercially significant.** *"The customer declined to say why we lost"* is a different fact from *"we never asked"*, and only one of them is a process failure we can fix.

---

## 7 · Learning Readiness

This section adds a **gate**. It does not redesign 2E's lesson lifecycle.

### 7.1 The readiness gate

An outcome may feed learning only when **all** hold:

```
LEARNING-READY ⟺  status ∈ {CONFIRMED, CLOSED}
              AND attribution is to exactly one decision
              AND no unresolved evidence conflict
              AND not LATE_UNRELIABLE
              AND not RETIRED
              AND evaluation exists, with a named yardstick
```

Anything else is recorded, queryable, and **excluded from lesson generation**.

Without this gate, lessons form on provisional, contested and stale outcomes — and lessons formed that way influence decisions before reality has finished arriving.

### 7.2 The loop, and where this document sits

```
DECISION ──► EXECUTION ──► OUTCOME  ◄── this document
                              │
                       readiness gate  §7.1
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              EXPERIENCE            LESSONS
        (derived knowledge,      (hypotheses, 2E §5)
         recomputed, 2E §6)            │
                    │             validated · retired
                    └─────────┬─────────┘
                              ▼
                    POLICY PROPOSAL
                              │
                    ⚠️ HUMAN APPROVAL — L5
                              ▼
                          POLICY
                              │
                              ▼
                    influences the next DECISION
```

### 7.3 Experience accumulation

Experience is **derived knowledge** (2E §6.1), recomputed from ready outcomes. Not a new store.

Each experience claim carries **sample size and confidence interval** — *"reliability 0.73, n=4"* and *"0.73, n=180"* are different facts, and only one should drive a tier-4 decision.

### 7.4 Lesson validation and retirement

Per 2E §5. This document supplies the **triggers**:

| Trigger | Effect |
|---|---|
| New ready outcomes contradict the lesson | → `WEAKENING` |
| Outcome drift detected (§8) | → `WEAKENING`, review scope |
| Expiry reached | → review or retire |
| Supporting outcomes retired | → recompute; may fall below sample threshold |
| A deliberate test refutes it | → `REFUTED` |

### 7.5 Policy proposal — the boundary

A lesson may **propose** a policy. It may never become one.

> **Promotion is a human decision, Structural category, L5** (2E §5.5).

This is the guard against bias fossilisation, and it is the item most likely to be argued away as friction. Recorded with its reasoning so that reversing it requires re-arguing the case.

---

## 8 · Drift Detection

### 8.1 The correction: one observable, several explanations

The brief lists five drifts as though each were separately detectable. They are not.

> **You detect ONE thing — outcomes changed. The other four are candidate explanations.**

```
                 ┌──────────────────────────────┐
                 │  OUTCOME DRIFT — OBSERVABLE  │
                 │  same decision, different    │
                 │  outcome distribution        │
                 └──────────────┬───────────────┘
                                │ attribute to a cause
        ┌───────────────┬───────┴───────┬────────────────┐
        ▼               ▼               ▼                ▼
   BUSINESS        MARKET          OPERATIONAL       POLICY
   we changed      world changed   execution changed  rules changed
```

Presenting five parallel detectors implies five independent measurements. In practice there is one signal and an attribution problem — and pretending otherwise produces four detectors that mostly fire together and confuse each other.

### 8.2 The observable

**Outcome drift:** the distribution of outcomes for comparable decisions has shifted beyond expected variation.

Detected by comparing recent ready outcomes against the historical distribution for the same decision class, controlling for sample size. **Small samples drift by chance; the detector must not fire on noise.**

### 8.3 The four candidate explanations

| Cause | Evidence that supports it | Response |
|---|---|---|
| **Business drift** — we changed | New offerings, segments, pricing, team | Re-scope lessons; old segment lessons may not transfer |
| **Market drift** — the world changed | Drift across *all* segments simultaneously; external indicators | Retire era-bound lessons |
| **Operational drift** — our execution changed | Execution records show latency, failure or cost changes | Fix operations; the decision was fine |
| **Policy drift** — our rules changed | Policy version history | **Expected.** Not a regression — verify it is the intended effect |

### 8.4 Distinguishing them

Cheap, decisive discriminators before any modelling:

- **Policy drift** — check the policy version log. If a rule changed, that is the first hypothesis and it is verifiable.
- **Operational drift** — check execution records. If latency or failure rates moved, the decision quality is not implicated.
- **Business drift** — drift concentrated in *new* segments while established ones hold steady.
- **Market drift** — drift across *all* segments at once, including established ones.

**Check in that order.** The first two are verifiable from records we already keep; the last two require judgement. Reaching for "the market changed" before checking the policy log is how a team explains away its own regression.

### 8.5 What drift triggers

Drift **never** silently changes behaviour. It:

1. Moves affected lessons to `WEAKENING`
2. Raises a review — a **decision** for a human, not an automatic adjustment
3. Widens confidence on affected derived experience
4. Is recorded in OI as an observation about ourselves

> **Automatic adaptation to drift is how a system silently changes its own behaviour with nobody accountable.** The detector reports; humans decide.

---

## 9 · Explainability

Five questions, answered **from records** — never reconstructed.

| Question | Answered from |
|---|---|
| **Why was this outcome recorded?** | Observation status, source, window, trigger |
| **What evidence supports it?** | Every observation, with provenance, tier, timestamp, and any conflicts |
| **Which decision produced it?** | The single attribution edge, plus contributing factors marked as such |
| **Which policy influenced it?** | Traversal: outcome → decision → `policy_version` **as it stood then** |
| **What uncertainty remains?** | Quality vector (§6) + attribution certainty + unresolved conflicts |

### 9.1 The question with the most honest answer

*"Which decision produced it?"* must answer **"this decision preceded it"**, not **"this decision caused it"** (§4.3).

An explanation claiming causation from attribution alone is unsupported — and it is the explanation a model would happily generate if asked. Content comes from records; a model may narrate but never generate.

---

## 10 · Future Expansion

Outcome Intelligence is domain-blind. Every vertical supplies the same shape with different vocabulary and, critically, **different clocks**.

| Industry | Decision | Observed outcome | Signal class | Typical lag |
|---|---|---|---|---|
| **Manufacturing** | Accept a spec deviation | Field failure / warranty claim | Operational, deterministic | **6–24 months** |
| **Healthcare** | Discharge timing | Readmission within 30 days | Deterministic | 30 days |
| **Retail** | Markdown depth | Sell-through, realised margin | Financial | **1–8 weeks** |
| **Construction** | Approve a change order | Schedule slip, cost variance | Operational, financial | 1–18 months |
| **Education** | Intervention for a student | Term outcome, retention | Deterministic, aggregate | 3–12 months |
| **Government** | Prioritise a grievance | Resolution time, satisfaction | Operational + tier-5 feedback | 1–6 months |
| **Legal** | Filing strategy | Ruling, settlement | Deterministic, **binary** | **6 months – 5 years** |

### 10.1 The one genuine variation

**Observation windows vary by three orders of magnitude** — retail in weeks, legal in years.

Consequence: **the window is a per-decision-type declaration**, never a global constant. A global timeout would either mark manufacturing outcomes `TIMED_OUT` while they are legitimately pending, or hold retail decisions open for years.

This is the only place a vertical materially changes Outcome behaviour, and it is a declared parameter — not a code path.

### 10.2 The vertical that stresses the model

**Legal.** Outcomes are near-binary (won/lost), lags reach years, and sample sizes stay small. Small-sample, long-lag, binary outcomes are the hardest case for drift detection — noise dominates.

Consequence: **for such domains the drift detector must require a materially larger sample before firing**, or it will report drift that is chance. Recorded now so it is a declared parameter rather than a surprise.

---

## 11 · Acceptance Criteria

### 11.1 Architectural invariants — must never change

| # | Invariant |
|---|---|
| **I1** | **Observation and evaluation are separate.** Outcomes record what happened; goodness is derived |
| **I2** | **Execution result is never an outcome** |
| **I3** | **Outcomes are immutable.** Revision appends; it never edits |
| **I4** | **Exactly one attribution edge** per outcome. Contributing factors are separate and weaker |
| **I5** | **Attribution records correlation, never causation** |
| **I6** | **Expectations are created at decision time**, so silence is measurable |
| **I7** | **`TIMED_OUT` is data**, distinct from `UNKNOWN` |
| **I8** | **Only learning-ready outcomes feed lessons** |
| **I9** | **Lessons never become policy automatically** — human, L5 |
| **I10** | **Drift reports; it never adapts** |
| **I11** | **Customer feedback is tier 5**; probabilistic signals never decide alone |
| **I12** | **Observation windows are declared per decision type** |

### 11.2 Structural

| # | Criterion |
|---|---|
| 1 | Six observed states and five observation statuses, defined and orthogonal |
| 2 | Evaluation is a derived claim carrying a versioned yardstick |
| 3 | `Delayed` is an attribute; `Disputed` is split in two |
| 4 | Lifecycle has six stages, with revision as append |
| 5 | Quality is a vector, never a scalar |
| 6 | Seven learning-signal classes with confidence ceilings |
| 7 | Readiness gate defined with six conditions |
| 8 | One observable drift, four candidate explanations, checked in a stated order |

### 11.3 Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 9 | Record `SUCCESS` directly on an outcome | **REJECTED** — evaluation is derived |
| 10 | Change the margin yardstick, re-evaluate history | Verdicts change; **observations unchanged** |
| 11 | Record an execution result as an outcome | **REJECTED** |
| 12 | Quotation sent, no reply within the window | `NO_RESPONSE` / `TIMED_OUT` — **retained as data** |
| 13 | Attribute one outcome to two decisions | **REJECTED** — one edge; use contributing factors |
| 14 | Contributing factor used to justify an action alone | **REJECTED** — associative, depth 1 |
| 15 | Edit a confirmed outcome | **REJECTED**; revision appends |
| 16 | Late evidence arrives | New observation; original readable; belief-at-time answerable |
| 17 | Outcome arrives far beyond its window | Flagged `LATE_UNRELIABLE`, excluded from learning |
| 18 | Two sources contradict on what happened | Conflict surfaced; outcome **not learning-ready** |
| 19 | Provisional outcome feeds a lesson | **REJECTED** — readiness gate |
| 20 | Customer states a loss reason | Recorded at **tier 5**, ≤ 0.50 |
| 21 | Sentiment signal used alone for a tier-3 action | **REJECTED** |
| 22 | KPI movement used to attribute one decision | **REJECTED** — KPIs detect drift, not attribution |
| 23 | Owner marks a recommendation wrong | Tier 1; updates the case, not the general lesson |
| 24 | Drift detected on a small sample | **Does not fire** — noise threshold |
| 25 | Drift detected | Lessons `WEAKENING`; **no automatic behaviour change** |
| 26 | Policy changed last week, outcomes shifted | **Policy drift checked first**, from the version log |
| 27 | Ask why an outcome was recorded | Observation, source, window, trigger |
| 28 | Ask which decision caused it | **"Preceded"**, not "caused" |
| 29 | Retired outcome | Excluded from learning, **still readable and replayable** |
| 30 | Add a vertical with a 2-year window | Declared parameter only; **zero model changes** |

### 11.4 Learning — the criteria that matter most

| # | Criterion |
|---|---|
| 31 | One complete Decision → Execution → Outcome → Evaluation chain exists in production |
| 32 | An evaluation has been **recomputed under a changed yardstick**, and the observation was untouched |
| 33 | A lesson has been derived from ready outcomes, tested against new ones, and **retired or reinforced** |
| 34 | Drift has been detected, attributed to a cause, and **reviewed by a human** |

### 11.5 Non-regression

| # | Criterion |
|---|---|
| 35 | Zero application code touched |
| 36 | Phase 1C suite green (249 tests) |
| 37 | Compatible with 2A–2H; no frozen concept modified |
| 38 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 32 is the acceptance test for this slice.** Everything else proves the model is well-formed. Only 32 proves it is *durable* — that a change in what the business considers good does not silently rewrite its own history. A learning loop that cannot survive a changed definition of success will quietly teach the wrong thing the first time targets move.

---

## 12 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | Evaluation baked into the observation | **High** | I1 — the single most consequential decision here |
| **R2** | Attribution inflation; everything linked to everything | **High** | §4.2 — one edge, factors separate |
| **R3** | Causation claimed from correlation | **High** | I5, §9.1 — explanations say "preceded" |
| **R4** | Lessons formed on provisional outcomes | **High** | §7.1 readiness gate |
| **R5** | Drift detector fires on noise | Medium | §8.2 sample thresholds; §10.2 for small-sample domains |
| **R6** | Automatic adaptation to drift | **High** | I10 — detectors report, humans decide |
| **R7** | Customer feedback treated as cause | Medium | §5.1 — tier 5, speech-act split |
| **R8** | Outcomes never arrive; the loop stays open | Medium | I6 — expectations created at decision time |
| **R9** | KPI used to attribute individual decisions | Medium | §5.3 — the classic self-deception |

---

## 13 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Outcome Intelligence is a subsystem of OI**, not a fourth substrate
2. **Observation ≠ evaluation** — outcomes record what happened; goodness is derived and re-computable
3. **Six observed states**; Success/Failure/Partial removed as states
4. **`Delayed` is an attribute**; **`Disputed` splits** into a business event and an evidence conflict
5. **Expectations are created at decision time**, so silence is measurable
6. **One attribution edge**; contributing factors are separate and may never justify an action
7. **Attribution is correlation, not causation** — and explanations must say so
8. **Learning-readiness gate** before any lesson generation
9. **One observable drift with four candidate explanations**, checked in a stated order
10. **Drift reports; it never adapts**

Item 2 is the one that matters most over ten years.

Recording `SUCCESS` costs nothing today and quietly corrupts everything later: the first time a margin target moves, every historical outcome means something different, every lesson built on them is wrong, and **nothing in the data will say so.** Recording the observation and deriving the verdict costs one indirection now and keeps the entire learning loop honest for as long as the business runs.
