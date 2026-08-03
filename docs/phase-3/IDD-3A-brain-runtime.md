# IDD 3A — Business Brain Runtime

**Status:** Design · No implementation · 2026-08-03
**Supersedes:** the pre-Phase-2 "Business Brain v1 — Runtime Architecture" note
**Depends on:** BIC v1.0 · Decision Engine spec · Phase 2A–2I (all frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Four corrections to the proposed stage list

The proposed order is close. Four changes, each preventing a permanent defect.

### C1 — Policy Validation is not a stage after Decision

The list reads `… → Decision → Policy Validation → Capability Execution`.

**Policy is gate 6 *inside* adjudication** (Decision Engine spec §6). Making it a separate stage afterwards means the decision is reached, then possibly invalidated — two places that can say no, which will diverge.

> **One adjudicator. Policy is a gate within it, never a second opinion after it.**

### C2 — Outcome Tracking cannot be a runtime stage

Outcomes arrive **hours to months later** (2I). A stage implies the turn waits for one.

**Correction:** the runtime synchronously **registers an expectation** (2I §3.1 — created at decision time, so silence is measurable). Observation happens in a separate asynchronous process that is not part of any turn.

The stage is *Register Expectation*, not *Outcome Tracking*.

### C3 — Planning cannot precede Context

You cannot plan what to do before knowing what is true. The list places `Planning` before `Context Request`.

**Correction:** `Intent → Goal → Context → Sufficiency → Plan`. Intent and goal determine *which slots are required*; context fills them; only then can a plan be formed.

For most turns the plan is a single known action and planning is deterministic — the decision ladder terminates at rung 1–3 without any model involvement.

### C4 — The runtime is a bounded loop, not a pipeline

A strictly linear runtime cannot express: context assembly discovering it needs more; a failed capability requiring replanning; a clarification changing the goal.

Linear designs handle these by smuggling loops inside a stage, where they become invisible and unbounded.

> **Bounded iteration with a declared budget. Loops are legal, visible and finite.**

---

## 1 · Runtime Architecture

### 1.1 The stages

```
                    ╔══════════════════════════════════════════════╗
                    ║ TURN BUDGET — time · money · calls · depth   ║
                    ║ exhausted anywhere ⇒ DEGRADE, never fail     ║
                    ╚══════════════════════════════════════════════╝

  INBOUND EVENT  (channel)
        │
   ① ADMIT ............ idempotency · dedupe · tenant · turn_id
        │               a replayed delivery returns the prior response
   ② IDENTIFY ......... BIC Kernel resolves the Principal
        │               BEFORE anything else runs (Article II.1)
   ③ INTERPRET ........ intent + required_slots
        │               deterministic first; model only if ambiguous
   ④ GOAL ............. admit · reuse · reject
        │               not every intent becomes a goal
        │
        ├──────────────► ⑤ CONTEXT ....... request a packet (2H)
        │                      │
        │                ⑥ SUFFICIENCY ── PROCEED │ CLARIFY │ RETRIEVE
        │                      │           ESCALATE │ REFUSE
        │                      │
        │                ⑦ PLAN .......... goal → task DAG
        │                      │           validated WHOLE before any step
        │                      │
        │                ⑧ CONSULT ....... LLM proposes (never decides)
        │                      │           skipped when rungs 1–3 settle it
        │                      │
        │                ⑨ DECIDE ........ Decision Engine adjudicates
        │                      │           policy is a gate INSIDE this
        │                      │
        │                ⑩ AUTHORIZE ..... kernel: scoped, expiring,
        │                      │           single-use · preconditions
        │                      │           RE-VERIFIED at issuance
        │                      │
        │                ⑪ EXECUTE ....... via capability · idempotent
        │                      │
        │                ⑫ OBSERVE ....... what actually happened
        │                      │
        └───── task remaining? ┘   ← the only loop back, budget-capped
                               │
   ⑬ RECORD ........... Decision + Execution → OI (before responding)
        │
   ⑭ REGISTER EXPECTATION ... outcome window opens (2I)
        │
   ⑮ RESPOND .......... channel-neutral, then rendered by the channel
        │
        ⋮  asynchronously, hours to months later
   ⑯ OBSERVE OUTCOME ... separate process, NOT part of any turn
```

### 1.2 Stage contracts

| # | Stage | Owner | Failure mode | Response |
|---|---|---|---|---|
| **①** | Admit | Brain | Duplicate delivery | Idempotency key; replay the prior response, **execute nothing** |
| **②** | Identify | **Kernel** | Directory unreachable | Fail closed to least privilege; bootstrap owners survive total outage |
| **③** | Interpret | Brain | Ambiguity | One clarifying question — **never guess on a tier ≥ 3 action** |
| **④** | Goal | Brain | Conflicting or duplicate goals | Admission gate; **no goal without a completion condition** |
| **⑤** | Context | **Context Plane** | Slow or partial sources | Partial packet with declared gaps — never silent omission |
| **⑥** | Sufficiency | Context Plane | — | Five verdicts (2H §4.2) |
| **⑦** | Plan | Brain | Plan references an unavailable or unauthorized capability | **Validate the whole plan before executing any step** |
| **⑧** | Consult | Brain → LLM | Empty, malformed, ungrounded output | Treat as failure; retry on a different model; then degrade |
| **⑨** | Decide | **Decision Engine** | Proposal invents facts or capabilities | Reject — **never repair a bad proposal into a good action** |
| **⑩** | Authorize | **Kernel** | World changed since the verdict | Re-verify critical preconditions **at issuance** |
| **⑪** | Execute | Capability Registry | Partial failure mid-plan | Compensate or halt; **never leave a half-applied plan silent** |
| **⑫** | Observe | Brain | Result unparseable | Record raw; mark degraded |
| **⑬** | Record | Brain → OI | Store unavailable | **Buffer and retry — the audit may lag, never vanish** |
| **⑭** | Register expectation | Brain → OI | — | Window declared per decision type (2I §10.1) |
| **⑮** | Respond | Brain → Channel | Send fails | Retry idempotently; queue for human |
| **⑯** | Observe outcome | **Async process** | Never arrives | `TIMED_OUT` — itself data (2I §2.3) |

### 1.3 Record before respond

⑬ precedes ⑮ deliberately. **If the audit record cannot be written, the response is not sent.**

Inverting this produces an audit trail with holes exactly where things went wrong — because the failures that break recording are the failures that matter.

---

## 2 · Runtime State Machine

### 2.1 States

```
                     ┌──────────┐
                     │ RECEIVED │
                     └────┬─────┘
             ┌────────────┼────────────┐
             ▼            ▼            ▼
      ┌───────────┐ ┌──────────┐ ┌───────────┐
      │ DUPLICATE │ │ REJECTED │ │ ADMITTED  │
      │ (replay)  │ │ (auth)   │ └─────┬─────┘
      └───────────┘ └──────────┘       │
                                       ▼
                              ┌──────────────────┐
                              │  INTERPRETING    │
                              └────────┬─────────┘
                                       ▼
                              ┌──────────────────┐
                    ┌─────────┤  ASSEMBLING      │◄──────┐
                    │         └────────┬─────────┘       │ RETRIEVE
                    │                  ▼                 │ (≤2)
                    │         ┌──────────────────┐       │
                    │         │  ASSESSING       ├───────┘
                    │         └────────┬─────────┘
        CLARIFY ────┤                  │ PROCEED
                    │                  ▼
                    │         ┌──────────────────┐
                    │         │  PLANNING        │
                    │         └────────┬─────────┘
                    │                  ▼
                    │         ┌──────────────────┐
                    │         │  CONSULTING      │  (skippable)
                    │         └────────┬─────────┘
                    │                  ▼
                    │         ┌──────────────────┐
                    │         │  ADJUDICATING    │
                    │         └────────┬─────────┘
                    │      ┌───────────┼───────────┐
                    │      ▼           ▼           ▼
                    │  ┌────────┐ ┌─────────┐ ┌──────────┐
                    │  │ DENIED │ │EXECUTING│ │ESCALATED │
                    │  └───┬────┘ └────┬────┘ └────┬─────┘
                    │      │           │           │ TERMINAL
                    │      │      ┌────┴────┐      │ (approval
                    │      │      ▼         ▼      │  starts a
                    │      │  ┌───────┐ ┌────────┐ │  NEW turn)
                    │      │  │ DONE  │ │ FAILED │ │
                    │      │  └───┬───┘ └───┬────┘ │
                    ▼      ▼      ▼         ▼      ▼
                  ┌────────────────────────────────────┐
                  │  RECORDING  →  RESPONDING  →  CLOSED│
                  └────────────────────────────────────┘

     Any state ──budget exhausted──► DEGRADED ──► RECORDING
     Any state ──unrecoverable────► FAILED   ──► RECORDING
```

### 2.2 Transitions

| From → To | Trigger |
|---|---|
| RECEIVED → DUPLICATE | Idempotency key already seen · prior response replayed |
| RECEIVED → REJECTED | Signature invalid, or principal unresolvable |
| RECEIVED → ADMITTED | Authentic, novel, tenant resolved |
| ADMITTED → INTERPRETING | Principal resolved |
| INTERPRETING → ASSEMBLING | Intent classified, slots known |
| ASSEMBLING → ASSESSING | Packet assembled |
| ASSESSING → ASSEMBLING | **RETRIEVE** — bounded at 2 (2H §3.3) |
| ASSESSING → CLARIFY-terminal | Missing evidence a human can supply |
| ASSESSING → PLANNING | **PROCEED** |
| ASSESSING → ESCALATED | Action above the principal's tier ceiling |
| ASSESSING → DENIED | REFUSE — unobtainable evidence or high-severity conflict |
| PLANNING → CONSULTING | Judgement required |
| PLANNING → ADJUDICATING | **Rungs 1–3 settled it — no model needed** |
| CONSULTING → ADJUDICATING | Proposal received |
| CONSULTING → DEGRADED | All providers failed |
| ADJUDICATING → EXECUTING / DENIED / ESCALATED | Verdict |
| EXECUTING → EXECUTING | Next task in the DAG |
| EXECUTING → DONE / FAILED | Plan complete, or unrecoverable |
| **ESCALATED** | **TERMINAL for this turn** — see §2.3 |
| any → DEGRADED | Budget exhausted |
| DONE / FAILED / DENIED / DEGRADED / CLARIFY → RECORDING | Always |
| RECORDING → RESPONDING | Record durable |
| RESPONDING → CLOSED | Response dispatched |

### 2.3 A turn never spans a human approval

The proposed list includes `Awaiting Approval` as a runtime state. **It must not be one.**

Approval takes minutes to days. A turn holding open across it would mean:

- runtime state living for hours, surviving restarts and deployments
- a serverless invocation that cannot complete
- ambiguity about what the world may do in between

> **ESCALATED is terminal. The approval decision creates a NEW turn, entering at ④ with the staged action as its goal.**

The Decision Engine already re-verifies authorization at approval time and at authorization issuance, so nothing is lost — and the runtime stays short-lived and restartable.

### 2.4 `Retrying` is not a state

Retry is a **transition back into EXECUTING**, carrying an attempt counter. As a state it would need its own transitions to every other state, doubling the machine for no expressive gain.

### 2.5 `Waiting` is not a state

Ambiguous — waiting for what? Replaced by the specific cases: `ASSEMBLING` (waiting on capabilities), `CONSULTING` (waiting on a model), `ESCALATED` (waiting on a human, and terminal).

---

## 3 · Responsibilities

| Component | Owns | **Must never** |
|---|---|---|
| **Business Brain** | **Orchestration only** — the turn, intent, goals, planning, sequencing, degradation, narration | Own business data · hold hidden state between turns · authorize itself · reach a system directly · resolve conflicts · reason unaided |
| **BIC Kernel** | Identity, Policy Gate, capability registry, invocation audit, authorization issuance, degradation tiers | Reason · interpret · be influenced by a model |
| **Knowledge Platform** | Facts, provenance, conflict resolution, packet assembly, sufficiency assessment | Decide · act · call a model |
| **LLM** | Language and inference over the packet | **Everything else.** No tools, no data, no identity, no memory |
| **Capability Registry** | The declared interface, gating, audit, degradation contract | Contain business logic — a capability routes, it does not compute |
| **Channels** | Transport, rendering, delivery state | Interpret · authorize · decide |

### 3.1 The Brain owns almost no memory

Per the pre-Phase-2 spec, reaffirmed: **anything surviving a turn was written somewhere auditable.**

| Memory | Scope | Owner |
|---|---|---|
| Working memory | One turn, discarded at end | Brain |
| Turn cache | Deduplicated capability results within a turn | Brain |
| Conversation | Recent exchange for reference resolution | **Channel**, read by Brain |
| Goal state | Persistent goals | **Commitment module** (2B) |

Hidden state destroys replay. If turn 40 depends on something accumulated in turn 12 and never written down, no decision after turn 12 is reproducible.

---

## 4 · Runtime Contracts

Conceptual. Each is a boundary the runtime may not reach around.

### 4.1 Brain ↔ Knowledge Platform

```
→  ContextRequest   { task, required_slots, principal, freshness_tolerance,
                      risk_tier, as_of }
←  BusinessContextPacket  (2H — six sections, immutable, sufficiency verdict)
```

**Brain asks by task and slots, never by entity or query.** A slot-shaped request is *checkable* — the platform can report what it could not supply. An entity-shaped request either returns a row or does not, and cannot fail meaningfully.

### 4.2 Brain ↔ LLM

```
→  ReasoningRequest  { task_contract, packet, output_schema }
←  Proposal          { content, referenced_facts[], confidence, alternatives[] }
```

**Abstraction is over reasoning TASKS, not models** — `CLASSIFY · EXTRACT · DRAFT · SUMMARIZE · COMPARE · PLAN · CRITIQUE · NARRATE`. That set is stable for a decade because it describes what businesses need thought about, not what a vendor sells.

**The LLM returns a proposal. Never a decision, never an action.**

Empty, malformed, ungrounded or contract-violating output is a **failure**, not a response — the DeepSeek incident (all tokens consumed as reasoning, HTTP 200, empty content) is why this is stated rather than assumed.

### 4.3 Brain ↔ BIC Kernel

```
→  identity.resolve(sender_ref, channel)          ← BEFORE anything else
→  capability.invoke(principal, code, args)       ← the only execution path
→  authorization.issue(decision, scope)           ← scoped, expiring, single-use
←  Principal | Result | Denial | Authorization
```

The Brain **runs inside** the kernel, it does not call it as a peer. Every downward path is gated and audited; there is no other route.

### 4.4 Brain ↔ Capability Registry

```
→  invoke(principal, capability, args, idempotency_key)
←  CapabilityResult { value, provenance, confidence, conflicts,
                      coverage, freshness, degraded, trace_ref }
```

`DENIED`, `UNAVAILABLE` and empty are **three distinguishable outcomes** (2G §6.2). Returning empty on a denial teaches the Brain that a party has no invoices when they have thirty.

### 4.5 Brain ↔ Channels

```
←  InboundEvent   { channel, sender_ref, content, message_id, attachments }
→  Response       { text, attachments, actions }   ← CHANNEL-NEUTRAL
```

**The Brain emits meaning; the channel renders it.** WhatsApp buttons, email HTML and voice SSML are rendering concerns. A Brain that emits channel-specific output cannot serve a second channel without change.

---

## 5 · Runtime Budgets

### 5.1 The budgets

| Budget | Default | Rationale |
|---|---|---|
| **Wall clock** | 25 s | Under the 30 s function ceiling, leaving room to record and respond |
| **Loop iterations** | 5 | Task-DAG passes |
| **Planning depth** | 3 | Sub-task nesting |
| **Context refinements** | **2** | 2H §3.3 — unbounded refinement is how ₹400 is spent discovering an empty field |
| **Capability executions** | 20 | Per turn |
| **AI consultations** | **2** | One primary, one fallback provider |
| **Currency** | Per-tier cap | Tier 1 turns must not cost like tier 4 turns |
| **Traversal depth** | Per relationship class (2A) | Structural 5 · Participation 2 · **Associative 1** |

### 5.2 Exhaustion degrades; it never fails

> **A budget breach produces a partial, honest answer — never a timeout.**

*"Here is what I established before I ran out of time"* is useful. Silence is not.

Over millions of turns, an unbudgeted runtime is how one pathological conversation consumes a day's compute — and how the failure is discovered from the invoice.

### 5.3 Budget state is recorded

Consumption per turn goes into OI. *"This decision path costs ₹40 and succeeds 60% of the time"* is a fact that should change behaviour, and it is invisible without per-turn cost.

---

## 6 · Failure Model

### 6.1 Deterministic responses

| Failure | Response | Never |
|---|---|---|
| **LLM failure** | Fallback provider → deterministic path → templated reply | Retry the same provider in a loop |
| **All LLMs fail** | **Tier 2** — commands, lookups, rules. The business continues (Article II.9) | Go offline |
| **Knowledge unavailable** | Partial packet, gaps named; sufficiency likely refuses | Answer as though data were present |
| **Capability failure** | Per declared policy: retry (idempotent only) / compensate / escalate | **Auto-retry a non-idempotent write** |
| **Timeout** | Partial result, `degraded`, what was not reached | Block past the budget |
| **Permission denied** | Recorded as a verdict, not an error; distinct from empty | Return empty |
| **Low confidence** | Refuse with specifics, or escalate | Answer anyway |
| **Incomplete context** | Sufficiency verdict decides — CLARIFY / RETRIEVE / REFUSE | Proceed silently |
| **Partial execution** | Compensate, or record `residual_state` and escalate | **Abandon silently** |
| **Duplicate request** | Replay the recorded response; execute nothing | Re-execute |

### 6.2 Degradation tiers

Computed per turn from live health, declared in the response. Never a manual switch.

| Tier | State | Behaviour |
|---|---|---|
| **T0** | Healthy | Full — AI-assisted, all sources |
| **T1** | Some sources degraded | Answer from what is fresh; **name the gaps** |
| **T2** | **AI unavailable** | **Deterministic only.** The constitutional floor |
| **T3** | Knowledge unavailable | Read-only from cache, staleness stated |
| **T4** | Severe | Acknowledge, queue, notify a human. **Never silence** |

### 6.3 Three rules

1. **Degrade loudly.** A degraded answer that looks normal is worse than a refusal — the user cannot know to check it.
2. **Never fabricate to preserve fluency.** The most damaging failure available here is a system that stays articulate as it becomes wrong.
3. **Every degradation is recorded.** Degradation frequency per source is the clearest early-warning signal the platform has.

---

## 7 · Explainability

| Question | Answered from |
|---|---|
| **Why this goal?** | Intent classification + goal admission record + rejected goals |
| **Why this plan?** | Task DAG, capability selection, why cheaper options were insufficient |
| **Why this capability?** | Required · authorised · available · declared cost and freshness |
| **Why this knowledge?** | Packet retrieval trace: slots, capabilities called, ranking, **what was pruned** |
| **Why this decision?** | Verdict + gates + decisive rule + decisive facts |
| **Why not another path?** | **Rejected alternatives with reasons** — at goal, plan and decision level |

### 7.1 The runtime trace

Every turn produces a trace: stages entered, budget consumed, capabilities invoked, packet reference, verdict, degradation. **Bounded and structured** — not a log dump.

**Rejected alternatives are recorded at three levels** — goals not admitted, plans not chosen, actions not taken. Almost no system records the first two, and *"why did it decide to do that at all?"* is unanswerable without them.

### 7.2 A model may narrate; it may never generate

Content comes from records. A model-authored explanation is a plausible fiction fitted to the outcome.

---

## 8 · Runtime Replay

### 8.1 What replay varies

| Mode | Fixed | Varied | Answers |
|---|---|---|---|
| **Fidelity** | Packet, policy, thresholds as of then | **Brain version** | Does the new runtime decide the same? |
| **Model** | Packet, Brain | **Model roster** | Does the decision survive a provider swap? |
| **Counterfactual** | Packet | Policy/thresholds **as of now** | Would we decide differently today? |
| **Evidential** | Brain, policy | **Evidence, plus what we later learned** | Was it wrong, or unlucky? |

**Conflating fidelity and counterfactual floods the harness with false alarms** — the runtime is fine, the rules changed — and a muted harness protects nothing.

### 8.2 Determinism

Everything except ⑧ CONSULT is deterministic. Given the same packet and versions, the runtime reaches the same verdict every time.

**The model is the only non-deterministic component, and it only proposes.** That is what makes the system replayable despite containing an LLM.

### 8.3 Version compatibility

Three independent versions per turn: `runtime_version`, `packet_schema_version`, `policy_version`. Two majors supported concurrently, minimum 12 months.

### 8.4 Brain upgrades and model replacement

**Brain upgrade:** replay the corpus. Safety and authority regressions block release. Then shadow-run both versions against live packets before the flag flips — the pattern proven in Phase 1C.

**Model replacement:** replay the corpus across the new roster. If decisions hold within tolerance, the swap is safe.

> Run the provider-independence check quarterly. **The day only one provider passes, the moat has quietly become theirs** — and that day arrives silently unless measured.

---

## 9 · Runtime Invariants

Consolidated across every phase. Changing any is a constitutional amendment.

| # | Invariant |
|---|---|
| **I1** | The Brain never owns business data |
| **I2** | The Brain holds **no hidden state between turns** |
| **I3** | The LLM never accesses storage, tools, identity or memory |
| **I4** | The LLM receives **only** the Business Context Packet |
| **I5** | The LLM **proposes**; the state machine decides |
| **I6** | Identity is resolved **before any model runs** |
| **I7** | Every action passes the Policy Gate |
| **I8** | Every execution is audited, including denials |
| **I9** | Every decision is replayable **without the world** |
| **I10** | Record before respond |
| **I11** | Every turn is **bounded** by a declared budget |
| **I12** | Budget exhaustion **degrades**; it never fails silently |
| **I13** | Non-idempotent actions are **never auto-retried** |
| **I14** | A turn **never spans a human approval** |
| **I15** | The business operates at **Tier 2 with AI entirely off** |
| **I16** | Duplicate deliveries **replay**; they never re-execute |
| **I17** | Responses are **channel-neutral**; rendering belongs to the channel |
| **I18** | Outcome observation is **asynchronous** and outside every turn |

### 9.1 The four that will come under pressure

| # | Pressure it will face |
|---|---|
| **I5** | *"Just let the model call the tool directly — it's faster"* |
| **I11** | *"This one turn needs more time"* |
| **I13** | *"It probably didn't go through, just retry it"* |
| **I14** | *"Keep the turn open, the approval will come in a minute"* |

Each argument is reasonable in the moment and corrosive in aggregate. Recorded with their reasoning so reversing one requires re-arguing the case, not merely finding the guard inconvenient.

---

## 10 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Sixteen stages defined, with owner and failure mode each |
| 2 | Policy validation is **inside** adjudication, not a stage after it |
| 3 | Outcome observation is asynchronous, outside the turn |
| 4 | Planning follows Context, never precedes it |
| 5 | The runtime is a bounded loop with a declared iteration cap |
| 6 | State machine defined; `Waiting`, `Retrying`, `Awaiting Approval` are **not** states |
| 7 | Every contract in §4 declared conceptually |
| 8 | Eight budgets with defaults and exhaustion behaviour |
| 9 | Five degradation tiers |
| 10 | Eighteen invariants declared constitutional |

### Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 11 | Duplicate delivery | Prior response replayed; **nothing executed** |
| 12 | Model proposes a capability the principal cannot invoke | **Rejected at plan validation**, before any step runs |
| 13 | Model returns empty content, HTTP 200 | Treated as **failure**; fallback provider |
| 14 | All providers fail | **Tier 2** — deterministic commands still work |
| 15 | Non-idempotent write fails ambiguously | **Escalated, never auto-retried** |
| 16 | Budget exhausted mid-plan | Partial result, `degraded`, recorded — **not a timeout** |
| 17 | Action above the principal's tier ceiling | ESCALATED and **terminal**; approval starts a new turn |
| 18 | Approval granted 3 hours later | **New turn**, authorization re-verified |
| 19 | Audit store unavailable | Response **withheld**; record buffered and retried |
| 20 | Capability returns DENIED | Distinguishable from empty in the trace |
| 21 | Context refinement loop | **Bounded at 2** |
| 22 | Rungs 1–3 settle the decision | **CONSULTING skipped** — zero model calls, visible in the trace |
| 23 | Partial plan execution | Compensated, or `residual_state` recorded and escalated |
| 24 | Ask why a goal was not admitted | **Rejected goals answer it** |
| 25 | Ask what was pruned from the packet | Pruning trace answers it |
| 26 | Replay a turn with no live systems | **Succeeds** |
| 27 | Replay under today's policy | Labelled **counterfactual**, not regression |
| 28 | Same packet, two model families | **Decisions hold within tolerance** |
| 29 | Brain upgrade with a safety regression | **Blocks release** |
| 30 | Response inspected for channel specifics | **None** — channel-neutral |

### The principles that will still hold in 2036

| # | Principle | Why it survives |
|---|---|---|
| **P1** | **AI proposes; the state machine decides** | Model capability will change beyond recognition. Where authority sits should not |
| **P2** | **The model sees only the packet** | The single decision that keeps providers replaceable |
| **P3** | **Identity before reasoning** | Security that depends on model behaviour is not security |
| **P4** | **Everything bounded** | Unbounded loops are how autonomous systems become unpredictable and expensive |
| **P5** | **Record before act** | An audit trail with holes where things went wrong is not an audit trail |
| **P6** | **Degrade loudly, never fabricate** | The most damaging failure is a system that stays articulate as it becomes wrong |
| **P7** | **Replayable without the world** | Without it, no decision can ever be honestly re-examined |

**Criterion 28 is the acceptance test for this slice.** Everything else proves the runtime is well-formed. Only 28 proves it is *portable* — that the business reasons the same way regardless of whose model is running.

---

## 11 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Policy validation is inside adjudication**, not a stage after it
2. **Outcome tracking is asynchronous** — the stage is *register expectation*
3. **Planning follows Context**
4. **The runtime is a bounded loop**, not a pipeline
5. **A turn never spans a human approval** — ESCALATED is terminal
6. **`Waiting`, `Retrying`, `Awaiting Approval` are not states**
7. **Reasoning-task abstraction, not model abstraction**
8. **Record before respond** — no record, no response
9. **Budget exhaustion degrades**, never fails
10. **Eighteen invariants are constitutional**

Item 5 is the one most likely to be resisted, because holding the turn open *feels* simpler. It is not: it means runtime state living for hours across restarts and deployments, in a serverless environment that cannot hold it, with no clarity about what the world may do in between.

Ending the turn and starting a new one on approval costs one extra record and buys a runtime that is short-lived, restartable, and honest about time.
