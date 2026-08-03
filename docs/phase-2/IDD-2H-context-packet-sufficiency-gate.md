# IDD 2H — Business Context Packet & Sufficiency Gate

**Status:** Design · No implementation · 2026-08-03
**Depends on:** 2A–2G (all frozen) · BIC v1.0 · Brain Runtime spec · Decision Engine spec
**Gate:** implementation may not begin until this document is approved

---

## 0 · The one idea, and three corrections

### 0.1 The idea

> **The packet is the only thing a model ever sees, and it is not a prompt.**

A prompt is provider-shaped text. A packet is a **typed, immutable, auditable business artifact**. Rendering a packet into whatever text a given provider wants is the model adapter's job — and it is the reason a model can be replaced without touching anything above it.

```
KNOWLEDGE PLANE ──► CONTEXT PLANE ──► PACKET ──► adapter ──► model
                                        │
                                        └──► stored, replayed, explained
```

The packet outlives the model. That is the whole point.

### 0.2 C1 — Policies are not evidence, and must not be presented as such

The brief lists *Policies* alongside *Business Facts*. If they arrive in the same shape, a model will reason about a policy the way it reasons about a fact — weighing it, trading it off, arguing around it.

**Policy appears in the packet for one reason only: to stop the model proposing something that will be rejected downstream.** It is advisory to the *proposer*. Enforcement happens in the Decision Engine, deterministically, after the model has spoken.

> **Facts describe what is. Constraints describe what is permitted. A packet that blurs them invites the model to negotiate with the rules.**

Structurally separated in §2.

### 0.3 C2 — "Confidence" is not a packet-level field

The brief lists `Confidence` as a top-level element. There is no such thing as the confidence *of a packet*.

- **Every fact** carries confidence (2C — capped by provenance tier)
- **The packet** carries a *sufficiency assessment* — a verdict, not a number

A single packet-level confidence scalar would be an average over unlike things, and it would invite the model to reason about "how sure is this briefing," which is meaningless. Replaced by the Sufficiency Assessment (§4).

### 0.4 C3 — The budget must never cut structure

A token budget that can prune anything will eventually prune a conflict, and **a trimmed conflict becomes an invisible wrong answer.**

> **The budget applies to evidence only. Conflicts, constraints, missing-information and the sufficiency assessment are structural and are never budget-eligible.**

If structure plus minimum evidence exceeds the budget, the correct outcome is **refusal**, not silent truncation (§5.4).

---

## 1 · Purpose

### 1.1 Why the packet exists

| Problem it solves | Without it |
|---|---|
| **Model independence** | Swapping providers means rewriting prompts and re-testing everything |
| **Replayability** | A decision cannot be re-examined, because the inputs were never captured |
| **Explainability** | *"Why did it say that?"* has no answer beyond the model's own account |
| **Auditability** | No record of what the system knew when it acted |
| **Security** | The model would need access to systems — and would then be inside the trust boundary |
| **Determinism** | Retrieval would vary per run, so nothing could be compared |

### 1.2 Why every model must receive the *same* packet

Three consequences, each load-bearing:

1. **Comparison becomes possible.** Two providers on identical input differ only by reasoning. Any other setup confounds model quality with retrieval quality.
2. **Replay becomes honest.** A decision replays against a frozen packet, so *"would v4 decide differently?"* is answerable with one variable changed.
3. **Lock-in becomes visible.** The provider-independence test — *swap the entire roster, replay the corpus, do decisions hold?* — is only meaningful if the packet is the sole input.

> **The day a model needs a specially-shaped packet, the moat has quietly become theirs.**

### 1.3 Differentiated from five neighbours

| | What it is | Lifespan | Owned by | Model-specific? |
|---|---|---|---|---|
| **Prompt** | Provider-shaped text | One call | Model adapter | **Yes** |
| **Context window** | A provider's input capacity | Per model version | The vendor | **Yes** |
| **Memory** | Working state within a turn | **Discarded at turn end** | Brain | No |
| **Knowledge** | Facts about the world | Permanent, superseded | Knowledge plane | No |
| **Organizational Intelligence** | Facts about our conduct | Permanent, immutable | OI substrate | No |
| **Business Context Packet** | **A briefing assembled for one question** | **Immutable, retained** | **Context Plane** | **No** |

**Versus a prompt.** A prompt is what a packet *becomes* at the last moment. Prompts are disposable; packets are records. Storing prompts instead of packets couples the audit trail to a vendor's interface.

**Versus a context window.** A window is a *capacity constraint* of a particular model. The packet is sized by **business sufficiency**, then fitted to whatever window the chosen model has. Sizing packets to windows would make the knowledge layer depend on vendor pricing decisions.

**Versus memory.** Memory is what the Brain holds *during* a turn and discards. The packet is what it *shows the model*, and it survives.

---

## 2 · Packet Structure

Six sections. The grouping is deliberate — it prevents the category confusion of C1.

```
BUSINESS CONTEXT PACKET
│
├── ① HEADER ─────────────── identity and replayability
│   ├── packet_id · tenant · packet_schema_version
│   ├── assembled_at · as_of        ← the world-time this depicts
│   ├── turn_ref · goal_ref
│   └── assembly_version            ← which Context Plane built it
│
├── ② QUESTION ───────────── what is being asked
│   ├── request                     the inbound ask, normalised
│   ├── intent + confidence         classified, not assumed
│   ├── goal                        admitted goal this serves
│   └── required_slots[]            what an answer NEEDS
│
├── ③ PRINCIPAL ──────────── who is asking, and what they may see
│   ├── principal_ref · role · authority_basis
│   ├── visibility_scope            what this packet is permitted to contain
│   └── risk_tier_ceiling           the highest action this principal may take
│
├── ④ EVIDENCE ───────────── what we know    ⟵ BUDGET APPLIES HERE ONLY
│   ├── facts[]                     each: value · predicate · provenance ·
│   │                               confidence · as_of · observed_at
│   ├── relationships[]             traversed subgraph, depth-bounded
│   ├── timeline[]                  ordered, bitemporal
│   └── organizational_intelligence
│       ├── precedent_set           comparable decisions + OUTCOMES
│       └── lessons[]               scope, expiry, contradicting evidence
│
├── ⑤ BOUNDARIES ─────────── what constrains the answer   ⟵ NEVER PRUNED
│   ├── policies[]                  + policy_version, ADVISORY (§0.2)
│   ├── active_commitments[]        forward obligations a proposal may breach
│   ├── constraints[]               capacity, credit, calendar, capability
│   └── open_risks[]                known, unresolved
│
└── ⑥ EPISTEMIC STATE ────── what we do NOT know   ⟵ NEVER PRUNED
    ├── conflicts[]                 unresolved contradictions (§6)
    ├── missing[]                   per required slot, with WHY (§4.3)
    ├── freshness                   oldest contributing fact + verdict
    ├── coverage                    what was searched, what was not
    ├── degradation                 which capabilities degraded, and how
    ├── sufficiency                 the verdict (§4)
    └── evidence_refs[]             pointers for EXPLAIN and replay
```

### 2.1 Why §6 exists as its own section

Most systems represent absence as absence — a missing field. **That is indistinguishable from a field nobody needed.**

Making epistemic state a first-class section means the model receives *"we do not know their current credit limit, and the Finance sync last succeeded nine days ago"* rather than silence. A model given silence will fill it; a model given a stated gap will say so.

### 2.2 What must never be in the packet

| Never | Why |
|---|---|
| Prompts, model output, reasoning traces | Couples the record to a vendor's interface |
| Table names, cursors, row counts, storage ids | Boundary leak (2G) |
| Raw conversation transcripts, by default | 2F §8.2 — fetched explicitly, gated and audited |
| Anything outside `visibility_scope` | The packet is assembled *for a principal* |
| PII beyond what the question requires | Minimisation is structural, not a policy note |
| A packet-level confidence scalar | §0.3 |

---

## 3 · Context Assembly

### 3.1 The pipeline

```
QUESTION + PRINCIPAL
  │
① RESOLVE IDENTITY      knowledge.resolve — server-side, before anything
  │                     PROVISIONAL and DISPUTED carried forward, not hidden
② CLASSIFY INTENT       → required_slots[]
  │
③ PLAN                  slots → capability calls, scoped to the principal
  │                     capabilities the principal cannot invoke are NOT planned
④ RETRIEVE              knowledge.describe · find · traverse · timeline
  │                     parallel where independent; each gated and audited
⑤ TRAVERSE              depth-bounded by relationship class; never through
  │                     a supernode
⑥ ASSEMBLE TIMELINE     bitemporal, as_of applied
  │
⑦ RETRIEVE BOUNDARIES   policy.lookup(as_of) · active commitments · constraints
  │
⑧ RETRIEVE OI           oi.precedent (structural, outcome-weighted) · oi.lessons
  │
⑨ RESOLVE CONFLICTS     deterministic ladder; unresolved SURFACED (§6)
  │
⑩ COLLECT RISKS         open risks touching any retrieved entity
  │
⑪ DETECT MISSING        required_slots − filled = missing, WITH REASONS
  │
⑫ BUDGET                prune EVIDENCE only (§5)
  │
⑬ ASSESS SUFFICIENCY    → verdict (§4)
  │
⑭ FREEZE                packet becomes immutable
```

### 3.2 Four properties of assembly

**Identity first, always.** Article II.1 — resolved server-side before any model runs. A packet assembled before identity is resolved cannot have a visibility scope, and therefore cannot be safe.

**Authorization shapes the plan, not the output.** Capabilities the principal cannot invoke are never called. Filtering *after* retrieval means the data was fetched, and a filter is one bug away from being bypassed.

**Assembly makes no AI calls.** Every step is deterministic. A model may *propose* a retrieval recipe; the Context Plane validates it against the registry and the principal's authorization before executing (2G §5.3).

**Assembly is composition, not nesting.** The Context Plane calls capabilities; capabilities never call each other (2G §5.1, enforced since Phase 1C).

### 3.3 Bounded refinement

If required slots are unfilled, assembly may refine its plan **at most twice**, then stop and report.

Unbounded refinement is how an agent quietly spends ₹400 discovering that a field is empty.

---

## 4 · Sufficiency Gate

### 4.1 The four conditions

```
SUFFICIENT ⟺  coverage    — every required slot is filled
          AND freshness   — within tolerance FOR THIS INTENT
          AND conflicts   — no unresolved HIGH-severity contradiction
          AND confidence  — ≥ the floor for the action's RISK TIER
```

All four. Any failure produces something other than "answer".

### 4.2 Five verdicts

| Verdict | When | The Brain then |
|---|---|---|
| **PROCEED** | All four conditions hold | Consults the model |
| **CLARIFY** | Missing evidence **a human could supply now** | Asks one specific question |
| **RETRIEVE** | Missing evidence **the system could still fetch**, within budget | Refines once (§3.3) |
| **ESCALATE** | Sufficient evidence, but the action exceeds the principal's tier ceiling | Routes to an approver |
| **REFUSE** | Missing evidence that **cannot be obtained**, or unresolved high-severity conflict | Declines, **naming the gaps** |

### 4.3 The distinction that makes this work

> **"We don't have it" and "we can't get it" require different responses, and a gate that cannot tell them apart will either refuse too often or ask pointless questions.**

Every missing slot is classified:

| Class | Meaning | Verdict |
|---|---|---|
| `OBTAINABLE_BY_ASKING` | A human here knows it | **CLARIFY** |
| `OBTAINABLE_BY_RETRIEVAL` | A system has it; we did not fetch it | **RETRIEVE** |
| `UNOBTAINABLE_NOW` | Source down, sync stale | **REFUSE**, with the reason |
| `UNKNOWABLE` | Nobody has ever recorded it | **REFUSE**, with the gap |
| `REFUSED` | The party declined to provide it | **REFUSE** — and this is commercially significant |

This maps directly onto 2C §5.6's four absence kinds. **Absence is data.**

### 4.4 Thresholds scale with risk, not with the question

| Risk tier | Action | Confidence floor | Freshness tolerance |
|---|---|---|---|
| 1 | Answer a question | 0.50 | Generous |
| 2 | Draft for a human | 0.60 | Generous |
| 3 | Change internal state | 0.80 | Tight |
| 4 | Irreversible / financial | **0.95 + human approval** | **Tightest** |

The same fact may be sufficient for a summary and insufficient for a payment. **Sufficiency is a property of the (evidence, action) pair — never of the evidence alone.**

### 4.5 Refusal must be actionable

A bare *"I don't know"* is a different failure.

> *"I can't price this. Missing: current credit terms — Finance sync last succeeded 9 days ago, tolerance is 24 hours. Their order history and open receivables are current if a partial answer helps."*

That paragraph tells a human exactly what to fix. **It is nearly free once the packet exists, and it is the most under-built capability in the industry.**

### 4.6 Thresholds are governed, not tuned

Threshold changes are **Structural decisions at L5** (Decision Engine spec). Recorded, approved, replayable.

Without this, thresholds drift downward every time they block work, and within a year nothing is gated. **That erosion is silent and is the most likely way this gate dies.**

---

## 5 · Context Budget

### 5.1 The goal is correctness, not capacity

> **More context can make answers worse.** Beyond a point it costs more, buries the decisive facts, and measurably reduces accuracy.

**The metric is accuracy against packet size — never size alone.** A team optimising for "more context" will degrade the system while believing it is improving it.

### 5.2 What the budget may and may not touch

| Section | Budget-eligible |
|---|---|
| ① Header · ② Question · ③ Principal | ❌ |
| **④ Evidence** | ✅ **only this** |
| ⑤ Boundaries | ❌ |
| ⑥ Epistemic state | ❌ |

### 5.3 Ranking within evidence

| Signal | Rule |
|---|---|
| **Relevance to required slots** | Slot-filling facts are near-unprunable |
| **Provenance** | Tier 0 outranks tier 4 regardless of match quality |
| **Freshness** | Decayed per predicate volatility, not globally |
| **Specificity** | A fact about *this* party beats a segment pattern |
| **Evidence density** | Prefer few high-provenance facts over many weak ones |
| **Diversity** | Independent corroboration beats five restatements of one source |
| **Conflict density** | Rising conflict is a **sufficiency signal**, not a pruning target |

### 5.4 When the budget cannot be met

Structure plus minimum evidence exceeding the budget is **not** a pruning problem.

> **Verdict: REFUSE, stating that the question is too broad for a reliable answer.**

Silently truncating produces a confident answer on a fraction of the evidence, and nothing marks it. Refusing invites the human to narrow the question — which is the correct outcome.

---

## 6 · Conflict Handling

### 6.1 The invariant

> **The Brain must never receive a hidden conflict.**

A silently-resolved contradiction is **indistinguishable from knowledge**. Every consumer downstream treats it as settled.

### 6.2 Representation

Each conflict carries: the claims in tension, each with provenance and confidence · the resolution rung reached (2C §5.2) · the winner, or `UNRESOLVED` · severity · **the business consequence of being wrong**.

That last field converts a data-quality note into a decision input. *"Two credit limits differ by ₹4 lakh"* is actionable in a way that *"conflict detected"* is not.

### 6.3 Severity governs the gate

| Severity | Meaning | Gate effect |
|---|---|---|
| **HIGH** | The conflicting values would change the decision | **Blocks** — REFUSE or ESCALATE |
| **MEDIUM** | Affects confidence, not direction | Reduces confidence |
| **LOW** | Immaterial | Recorded only |

Severity is computed from the **decision at hand**, not from the facts alone. A ₹4 lakh discrepancy is HIGH for a credit decision and LOW for a greeting.

### 6.4 Priority never becomes silence

When the ladder resolves, the packet carries the winner **and** the losers, with the rung that settled it. The model sees a resolved value; the record shows the contest.

### 6.5 Unknowns and missing facts

`UNKNOWN`, `NOT_APPLICABLE`, `REFUSED`, `PENDING` (2C §5.6) are carried distinctly. Collapsing them into null destroys real information — *"the customer refused to state their budget"* is commercially significant; *"we never asked"* is a process gap.

---

## 7 · Explainability

Five questions, answered **from the packet itself**. Not reconstructed — a reconstruction is a plausible story, and a plausible story about evidence is worse than none because it is believed.

| Question | Answered from |
|---|---|
| **Why is this fact included?** | Which required slot it fills, its rank, its provenance |
| **Why was another excluded?** | The pruning trace: what was considered, its score, and why it lost |
| **Why this evidence?** | Retrieval trace: capabilities called, parameters, coverage |
| **Why this policy?** | Policy id + **version as of the packet's `as_of`** |
| **Why this confidence?** | The confidence **vector**, tier caps applied, dominating weak dimension |

### 7.1 The pruning trace is what makes exclusion explainable

Most systems can say what they included. **Almost none can say what they left out and why** — and that is where a wrong answer usually originates.

The trace records *considered but excluded* items with their scores. It is a bounded summary, not the full candidate set, but it must be sufficient to answer *"did you look at the March email?"*

### 7.2 A model may narrate; it may never generate

Content comes from the packet. The LLM makes it readable.

---

## 8 · Replay Compatibility

### 8.1 The core property

> **A packet must be replayable without the world.**

Everything needed to re-adjudicate is in it — the question, the principal's authority *as it stood*, the evidence, the policies at their versions, the thresholds in force. If replay must query live systems, it is not replay; it is a new decision wearing a historical label.

### 8.2 Immutability

Frozen at assembly. Never edited, never appended. A later correction produces a **new packet** linked by `supersedes`.

### 8.3 Versioning — three independent versions

| Version | Records | Why separate |
|---|---|---|
| `packet_schema_version` | The packet's shape | Readers must interpret old packets correctly |
| `assembly_version` | Which Context Plane built it | Assembly changes are the usual cause of drift |
| `policy_version` | Rules as of `as_of` | Replaying under *today's* policy is a counterfactual, not a regression |

**Conflating these is the classic replay error.** A policy change reported as an engine regression floods the harness with false alarms, and a muted harness protects nothing.

### 8.4 Evidence references — tiered retention

Per 2E §2.3:

| Tier | Content | Retained |
|---|---|---|
| **Inline** | Decisive facts, values as they stood | **Forever, with the decision** |
| **Referenced** | The full packet | Per retention policy |
| **Degraded** | If pruned, replay proceeds on the decisive subset, flagged `PARTIAL_EVIDENCE` |

**Replay degradation is visible, never silent.**

### 8.5 Brain version compatibility

A packet is **model-agnostic and Brain-agnostic**. Any Brain version can consume any packet whose `packet_schema_version` it supports.

Two majors supported concurrently, minimum 12 months — the same discipline as the capability registry.

### 8.6 The provider-independence test

> Freeze the corpus of packets. Swap the entire model roster. Replay. **If decisions hold within tolerance, independence is real.**

Run quarterly. **The day only one provider passes, the moat has quietly become theirs — and that day arrives silently unless it is being measured.**

---

## 9 · Future Expansion

The packet is domain-blind. Every vertical fills the same six sections with different vocabulary.

| Industry | Question | Distinctive evidence | Distinctive boundary | Tightest slot |
|---|---|---|---|---|
| **Manufacturing** | Accept a spec deviation? | Test results, BIS clause, customer spec | Conformity rules, warranty | Certificate freshness |
| **Healthcare** | Discharge now? | Vitals, assessment, care plan | Discharge criteria, **consent** | **Vitals freshness — minutes** |
| **Retail** | Markdown depth? | Sell-through, stock age, margin | Pricing policy | Stock accuracy |
| **Construction** | Approve a change? | Drawing revision, cost impact | Contract terms, safety | **Drawing version currency** |
| **Education** | Intervene for this student? | Attendance, assessments | Safeguarding, **minors' data** | Attendance recency |
| **Government** | Prioritise this grievance? | Category, history, SLA | Scheme rules, statutory limits | SLA clock |
| **Legal** | Advise on this filing? | Matter history, precedent | Deadlines, **privilege** | Filing deadline |

### 9.1 What actually varies

Not the structure — the **declared parameters**:

- **Freshness tolerance** — minutes for vitals, years for a land registry
- **Risk-tier mapping** — what counts as "material"
- **Required slots per intent** — registry configuration
- **Conflict severity thresholds**

All registry rows and configuration. **Zero packet-structure changes.**

### 9.2 Two verticals that need validation first

- **Legal** — privilege is *per-fact*, not per-role. `visibility_scope` assumes role-scoped visibility. A single message may be partly privileged. **Validate on paper before signing a legal client.**
- **Healthcare** — consent governs whether evidence may enter a packet at all, and consent is itself a Commitment with a lifecycle.

Neither is blocked. Both are cheaper to resolve now than during implementation.

---

## 10 · Acceptance Criteria

### 10.1 Architectural invariants — these must never change

| # | Invariant |
|---|---|
| **I1** | **The model receives only the packet.** No system access, ever |
| **I2** | **The packet is immutable** once assembled |
| **I3** | **The packet is model-agnostic.** Rendering is the adapter's job |
| **I4** | **No storage concepts** appear in a packet |
| **I5** | **Conflicts are never hidden** |
| **I6** | **Missing information is explicit**, with a reason |
| **I7** | **Every fact carries provenance** |
| **I8** | **The gate can always refuse** |
| **I9** | **Policy is advisory in the packet**; enforcement is downstream and deterministic |
| **I10** | **The budget cuts evidence only** — never structure |
| **I11** | **Assembly makes no AI calls** |
| **I12** | **Identity is resolved before assembly begins** |

Changing any of these is a constitutional amendment, not a refactor.

### 10.2 Structural

| # | Criterion |
|---|---|
| 1 | Six sections defined, with budget eligibility marked per section |
| 2 | Evidence and Boundaries are structurally separate |
| 3 | No packet-level confidence scalar exists |
| 4 | Epistemic state is a first-class section |
| 5 | Five sufficiency verdicts defined |
| 6 | Five missing-information classes defined |
| 7 | Three independent versions carried |
| 8 | Conflict representation includes business consequence |

### 10.3 Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 9 | Inspect any packet for storage concepts | **None** |
| 10 | Assemble for a principal lacking visibility | Restricted capabilities **not called** — not filtered after |
| 11 | Conflict present, budget tight | **Conflict retained**, evidence pruned |
| 12 | Structure + minimum evidence exceeds budget | **REFUSE**, not truncate |
| 13 | Required slot unfilled, obtainable by asking | **CLARIFY** with one specific question |
| 14 | Required slot unfilled, source unreachable | **REFUSE**, naming the source and its staleness |
| 15 | Party refused to provide a fact | Distinguishable from "never asked" |
| 16 | Sufficient evidence, action above tier ceiling | **ESCALATE**, not refuse |
| 17 | Same evidence, tier-1 vs tier-4 action | **Different verdicts** |
| 18 | HIGH-severity conflict present | **Blocks**; does not merely lower confidence |
| 19 | Attempt to edit an assembled packet | **REJECTED** |
| 20 | Replay a packet with no live systems reachable | **Succeeds** |
| 21 | Replay under today's policy | Labelled **counterfactual**, not regression |
| 22 | Full packet pruned by retention | Replay proceeds on decisive subset, flagged `PARTIAL_EVIDENCE` |
| 23 | Ask why a fact was excluded | **Pruning trace answers it** |
| 24 | Ask why a policy applied | Policy id **and version as of `as_of`** |
| 25 | Ask about confidence | Returns the **vector**, names the weak dimension |
| 26 | Assembly attempts an AI call | **REJECTED** |
| 27 | Model proposes a retrieval recipe | **Validated** against registry and authorization first |
| 28 | Refinement loop | Bounded at two |
| 29 | Lower a threshold | Requires an **L5 Structural decision**, recorded |

### 10.4 Portability — the criteria that matter most

| # | Test | Expected |
|---|---|---|
| 30 | Render one packet for two providers | Same packet, **different prompts** |
| 31 | Replay the corpus across two model families | **Decisions hold within tolerance** |
| 32 | Count packet-structure changes when adding a vertical | **Exactly zero** |
| 33 | Measure accuracy against packet size | **Curve produced** — not size alone |

### 10.5 Non-regression

| # | Criterion |
|---|---|
| 34 | Zero application code touched |
| 35 | Phase 1C suite green (226 tests) |
| 36 | Compatible with 2A–2G |
| 37 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 31 is the acceptance test for this slice.** Everything else proves the packet is well-formed. Only 31 proves it is *portable* — that the business reasons the same way regardless of whose model is running. That is the property the entire architecture exists to protect, and it is the one that decays silently if it is not measured.

---

## 11 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | Packet becomes prompt-shaped for one provider | **Existential** | I3 + criterion 31, run quarterly |
| **R2** | Budget prunes a conflict | **High** | I10 — structure is not budget-eligible |
| **R3** | Sufficiency thresholds erode under delivery pressure | **High** | §4.6 — changes are L5 decisions, drift monitored |
| **R4** | Packet bloat degrades accuracy while looking like progress | **High** | Criterion 33 — measure accuracy vs size |
| **R5** | Policy treated as negotiable evidence | Medium | §0.2 — structural separation |
| **R6** | Refusals annoy users into disabling the gate | Medium | §4.5 — make refusals *useful* |
| **R7** | Retention pruning silently degrades replay | Medium | §8.4 — `PARTIAL_EVIDENCE` flag |
| **R8** | Legal privilege does not fit `visibility_scope` | Medium | §9.2 — validate before signing |

---

## 12 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **The packet is not a prompt** — rendering is the adapter's job (I3)
2. **Policies are boundaries, not evidence** — advisory in the packet, enforced downstream
3. **No packet-level confidence scalar** — a sufficiency verdict replaces it
4. **The budget cuts evidence only** — structure is never prunable
5. **When the budget cannot be met, REFUSE** — never truncate silently
6. **Five sufficiency verdicts**, including CLARIFY and RETRIEVE as distinct from REFUSE
7. **Missing information is classified by obtainability** — "don't have" ≠ "can't get"
8. **Sufficiency is a property of (evidence, action)** — never of evidence alone
9. **Conflict severity is computed against the decision at hand**
10. **Threshold changes are L5 Structural decisions**
11. **Twelve invariants (§10.1) are constitutional** — changing one requires an amendment

Item 11 is the one to weigh most carefully. **Declaring something constitutional means accepting that a future deadline will not be sufficient reason to change it** — and the twelve listed are the properties that make the system replayable, explainable and portable.

If any of them is likely to be traded away under pressure, it is better to say so now than to discover it during an incident.
