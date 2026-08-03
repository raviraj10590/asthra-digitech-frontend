# IDD 3B — Goal Engine & Planner

**Status:** Design · No implementation · 2026-08-03
**Depends on:** Phase 2A–2I · Phase 3A Brain Runtime (all frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Three positions, stated first

### 0.1 Most turns need no planner at all

The overwhelming majority of business requests are **single-action**: answer a question, run a command, look something up, record a fact. The decision ladder terminates at rungs 1–3 with no model and no plan.

> **Planning is an exception path, not the default. Routing every turn through a planner adds a non-deterministic component to paths that were deterministic.**

The runtime must have a **fast path** where planning does not occur, and the trace must show which path was taken. If planning is on every turn, cost and latency rise, replay gets harder, and nothing is gained on the 90% of turns that never needed it.

### 0.2 Most plans are recipes, not novel constructions

*"Prepare a quotation"* is the same sequence every time. So is *"chase an overdue invoice"*, *"onboard a client"*, *"escalate a grievance"*.

> **Plans are declared templates first. A model proposes a plan only when no template matches — and that event is flagged, not routine.**

| Template-first | Model-first |
|---|---|
| Deterministic | Varies per run |
| Replayable exactly | Replay approximates |
| Free — no model call | Costs a call every time |
| **Authored by a domain expert** | Requires an engineer to debug |
| Auditable ahead of time | Auditable only afterwards |

This is the same mechanism that makes the 100-domain claim credible everywhere else in this architecture: **the extension point is a registry row, not code.** A plan template for tender submission should be authorable by someone who knows tenders.

When no template matches, the model proposes; the proposal is validated identically; and a repeatedly-successful proposal may be **promoted to a template by a human** — the same L5 promotion gate that governs lessons becoming policy (2E §5.5).

### 0.3 Priority is derived, never assigned

The brief asks for goal priority. **Assigned priority inflates** — within a quarter everything is urgent, and the field carries no information.

> **Priority is computed from deadline proximity, impact, and commitment status. It cannot be set directly.**

Derived priority is self-maintaining, explainable, and immune to the ratchet. A goal becomes urgent because its deadline approaches, not because someone said so.

---

## 1 · Goal Architecture

### 1.1 What a Goal is

> **A Goal is an admitted intention with a declared completion condition and an accountable owner.**

Three words carry weight:

- **Admitted** — it passed a gate. Not every intent becomes a goal.
- **Declared completion condition** — without it, the goal never ends.
- **Accountable owner** — never null, even when the work is autonomous.

### 1.2 Goal types

| Type | Lifespan | Survives restart? | Stored where | Examples |
|---|---|---|---|---|
| **Ephemeral** | One turn | No | Working memory | Answer a question · look up a client |
| **Session** | One conversation | No | Channel conversation state | Draft a proposal · negotiate terms |
| **Persistent** | Days to months | **Yes** | **Commitment module (2B)** | Chase an invoice · track a project · follow up a lead |

**Persistent goals are Commitments.** A goal the business holds itself to *is* a commitment with the business as counterparty. One concept, two vantage points — no duplicate store, no reconciliation.

### 1.3 Lifecycle

```
PROPOSED ──admit?──► ADMITTED ──► PLANNED ──► ACTIVE ──► COMPLETED
    │                                            │
    └──► REJECTED                          BLOCKED ──► ABANDONED
                                                 └───► EXPIRED
```

### 1.4 Admission is a gate, not a formality

A goal is **rejected** when it:

| Rejection reason | Why it matters |
|---|---|
| **Has no completion condition** | The single most important check — see below |
| Violates policy | Caught before work begins, not after |
| Duplicates an active goal | Prevents the same chase running twice |
| Exceeds the principal's authority | Authorization at admission, not just at execution |
| Has no admissible plan | No template, and no valid proposal |
| Conflicts with an active goal | §1.7 |

> **A goal with no defined completion condition may not be admitted.**

Without it, *"follow up this lead"* never ends. By year two the system holds thousands of zombie intentions that consume attention and mean nothing — and nobody can tell which are real.

### 1.5 Ownership

Every admitted goal has an **accountable owner** — an AGENT, never null.

For autonomous goals the owner is **the human who authorised the automation**, inherited exactly as accountability is inherited on autonomous decisions (Decision Engine spec). There is no such thing as a goal nobody is responsible for.

Ownership is time-bounded and transferable without touching the goal, so *"who owned this in March?"* stays answerable.

### 1.6 Priority — derived

| Input | Contribution |
|---|---|
| **Deadline proximity** | Rises as the due date approaches; steepens past it |
| **Impact** | From the goal's risk tier and business value |
| **Commitment status** | A goal backing an external commitment outranks an internal one |
| **Blocked duration** | A goal blocked a long time escalates rather than starving |
| **Dependency fan-out** | A goal blocking others inherits their urgency |

**No manual override field.** If the derivation is wrong, the inputs are wrong — fix the deadline or the impact classification, both of which are visible and auditable.

The one exception is an explicit, expiring, recorded escalation by a human, treated as a decision like any other.

### 1.7 Goal conflicts

| Conflict | Policy |
|---|---|
| Two goals need the same scarce resource | Derived priority, then deadline, then age |
| A new goal contradicts an active one | **Escalate — never silently abandon either** |
| A goal contradicts policy | Reject at admission |
| A customer goal opposes a business goal | **Business policy wins, and the customer is told plainly** |

### 1.8 Completion and cancellation

Four terminal transitions, each recorded to OI with its reason:

| Terminal | Meaning |
|---|---|
| **COMPLETED** | The completion condition was met |
| **ABANDONED** | An explicit human decision to stop |
| **EXPIRED** | The deadline passed without completion |
| **SUPERSEDED** | A newer goal replaced it |

**Abandonment is as informative as success.** A pattern of abandoned follow-ups is a signal the Learning Layer should be able to see, and it is invisible if abandoned goals are deleted.

---

## 2 · Planning Architecture

### 2.1 A plan is a validated task DAG

```
PLAN
├── goal_ref · plan_id · plan_version
├── origin            TEMPLATE(id, version) | PROPOSED(model, packet_ref)
├── tasks[]
│   ├── capability + args
│   ├── depends_on[]
│   ├── preconditions[]      re-verified AT EXECUTION (§2.6)
│   ├── postconditions[]     verified AFTER execution (§2.7)
│   ├── idempotency_key
│   ├── retry_policy         declared, never inferred
│   ├── compensation         declared, or NONE with reversibility stated
│   ├── approval_required
│   └── budget_share
├── ordering_constraints[]   including the irreversibility rule (§2.5)
└── validation               the whole-plan verdict (§4)
```

### 2.2 Template-first resolution

```
GOAL ADMITTED
    │
① MATCH TEMPLATE ──── found ──────► ② BIND ARGUMENTS ──┐
    │ none                                              │
    ▼                                                   │
③ PROPOSE (model) ─────────────────────────────────────►│
    │  flagged: no template matched                     │
    ▼                                                   ▼
④ VALIDATE WHOLE PLAN  ◄────────────────────────────────┘
    │
    ├── invalid ──► REJECT — with the specific violation
    ▼
⑤ EXECUTE
```

Templates are registry rows carrying: goal type, applicability conditions, task sequence, capability bindings, ordering constraints, and a version.

### 2.3 Decomposition depth is capped at 3

From 3A's budget. A goal decomposes into tasks; a task may decompose into sub-tasks; that is the limit.

Deeper decomposition is almost always a sign that the *goal* was too broad. The correct response is to reject the goal at admission and ask for a narrower one — not to plan more elaborately.

### 2.4 Parallel reads, sequential writes

The brief asks for parallel plans. **Accept for reads; reject for writes.**

| | Parallel | Rationale |
|---|---|---|
| **Reads** (QUERY capabilities) | ✅ | Independent, idempotent, retryable. Real latency benefit |
| **Writes** (ACT capabilities) | ❌ **Sequential** | Concurrent side effects make compensation ordering ambiguous, budget attribution unclear, and partial failure states combinatorial |

The complexity of parallel writes is permanent; the benefit is a few hundred milliseconds on rare multi-write plans. **Not worth it.**

### 2.5 Irreversible steps are ordered last

> **Within the constraints of the DAG, order irreversible tasks after reversible ones.**

If an irreversible step runs at position 5 and position 6 fails, the failure is unrecoverable. If irreversible steps run last, failures happen *before* the point of no return, where compensation still works.

Every capability declares reversibility (2G §3.1), so this is a mechanical ordering constraint the validator can enforce — not a matter of planner judgement.

**This is the highest-value planning rule in this document.** It converts a class of unrecoverable incidents into recoverable ones, at zero cost.

### 2.6 Preconditions — re-verified at execution

Declared per task, checked **when the task is about to run**, not when the plan was built.

The gap between planning and execution is where the world changes. This is the same TOCTOU class that Phase 1C found in production, where a privilege grant was validated at staging time and executed minutes later with no re-check.

### 2.7 Postconditions — the check most systems skip

> **A capability returning success is not evidence that the intended state change happened.**

Postconditions verify the *effect*: the CRM row exists, the message was accepted by the provider, the state actually transitioned.

A failed postcondition means the plan is in an **unknown state** — neither succeeded nor cleanly failed. That is the most dangerous condition, and it must escalate rather than retry, because retrying an unknown state can duplicate the effect.

This is the planning-time counterpart of 2I's execution-versus-outcome distinction.

### 2.8 Retry — only where declared safe

| Capability | Retry |
|---|---|
| Idempotent read | Freely, with backoff |
| Idempotent write (keyed) | Yes, same key |
| **Non-idempotent write** | **Never automatically. Escalate** |

This prevents sending two quotations or paying an invoice twice — one of the few genuinely unrecoverable bug classes in a business system.

### 2.9 Compensation — declared, never derived

| Policy | Meaning | Use for |
|---|---|---|
| `FAIL_FAST` | Abort the plan | Precondition failures |
| `COMPENSATE` | Undo completed steps in reverse | Multi-system writes |
| `CONTINUE_DEGRADED` | Skip, mark incomplete | Enrichment |
| `ESCALATE` | Hand to a human with full state | Anything irreversible |

**A task with no compensation must declare `reversible: false`**, which triggers the ordering rule in §2.5. Silence is not a valid declaration.

**A partially executed plan is never abandoned quietly.** It compensates, escalates, or records `residual_state` — what remains inconsistent. Silence here is how trust is lost permanently.

### 2.10 Escalation

Escalation is a **plan outcome**, and per 3A it is **terminal for the turn**. The approval decision starts a new turn carrying the plan state.

---

## 3 · Planner Contracts

### 3.1 Brain ↔ Planner

```
→  PlanRequest   { goal, packet_ref, principal, budget_share, risk_ceiling }
←  Plan | PlanRejection { reason, violation, missing }
```

The Planner receives the **already-assembled packet**. It never retrieves knowledge itself — retrieval is the Context Plane's job, and a planner that fetches could shop for facts that justify the plan it prefers.

### 3.2 Planner ↔ Knowledge

**There is no direct contract.** The Planner reads only what is in the packet.

If planning reveals a genuine information gap, it returns a `PlanRejection` with `missing`, and the runtime loops back to context assembly — **bounded at 2 refinements** (3A). It does not fetch on its own.

### 3.3 Planner ↔ Capability Registry

```
→  describe(principal)
←  capabilities the PRINCIPAL MAY INVOKE, with declared
   risk_tier · reversibility · cost · latency · degradation
```

**The Planner sees only capabilities this principal can actually invoke.** Planning against the full catalogue then filtering afterwards means building plans that were never executable — and one bug away from executing them.

### 3.4 Planner ↔ Decision Engine

```
→  the WHOLE plan, as a single proposal
←  PERMIT | DENY | ESCALATE | ABSTAIN
```

**The plan is adjudicated as one unit, before any task runs.** A plan that would fail authorization at step 7 must fail at step 0 — discovering that halfway through means the world is already half-changed.

Per-task approvals still occur at execution for tier ≥ 3 tasks; whole-plan adjudication is an additional gate, not a replacement.

---

## 4 · Planning Validation

Every plan passes all checks before any task executes. **All run; none is skippable.**

| # | Check | Rejects when | Failure class |
|---|---|---|---|
| 1 | **Well-formedness** | Cycles, orphans, unreachable tasks | Structural |
| 2 | **Capability existence** | Names a capability that is absent or inactive | Missing capability |
| 3 | **Authorization** | Any task exceeds the principal's authority | Policy conflict |
| 4 | **Preconditions satisfiable** | A precondition can never hold given the packet | Impossible plan |
| 5 | **Knowledge sufficiency** | Required args unavailable and unobtainable | Missing knowledge |
| 6 | **Budget feasibility** | Estimated cost, time or calls exceed the share | Budget violation |
| 7 | **Policy compliance** | Any task or the sequence violates a rule | Policy conflict |
| 8 | **Ordering constraints** | Irreversible task precedes reversible ones (§2.5) | Structural |
| 9 | **Compensation coverage** | A reversible-required task declares none | Structural |
| 10 | **Depth** | Decomposition exceeds 3 | Budget violation |

### 4.1 The five named failure modes

| Failure | Diagnosis | Response |
|---|---|---|
| **Impossible plan** | No ordering satisfies the preconditions | Reject; explain which precondition cannot hold |
| **Missing knowledge** | Required arguments unavailable | Return `missing` → runtime may refine **once more**, then refuse |
| **Budget violation** | Estimated consumption exceeds the share | Reject; **suggest a narrower goal** rather than truncating the plan |
| **Policy conflict** | A task or sequence violates a rule | Reject; name the rule **and its version** |
| **Missing capability** | Registry has no such capability, or the principal cannot invoke it | Reject; distinguish *absent* from *not permitted* — see below |

### 4.2 Absent ≠ not permitted

The same distinction 2G §6.2 makes for capability results applies here.

*"That capability does not exist"* is a configuration gap someone should fix. *"You may not invoke it"* is working authorization. Collapsing them sends diagnosis in the wrong direction — usually toward blaming the registry when the answer is a role.

### 4.3 Truncation is never a response to a budget violation

A plan that does not fit is **rejected**, not shortened. Silently dropping the last three tasks produces a plan that executes and leaves the goal half-achieved, with nothing marking it.

---

## 5 · Planning Explainability

| Question | Answered from |
|---|---|
| **Why this plan?** | `origin` — template id and version, **or** the model proposal with its packet reference |
| **Why these tasks?** | Each task's contribution to the completion condition |
| **Why this order?** | Dependency edges + ordering constraints, including which tasks are irreversible |
| **Why not another plan?** | Templates considered and why they did not apply; alternative orderings rejected and why |

### 5.1 The rejected-templates trace

*"Why not another plan?"* is answerable only if the **considered set** is recorded — which templates were evaluated, and which applicability condition each failed.

Without it, *"why didn't it use the standard quotation flow?"* has no answer, and the usual conclusion is that the system is unpredictable when in fact one condition was unmet.

### 5.2 Template origin is the strongest explanation available

A plan from a template explains itself: *"this is the standard tender submission sequence, version 3, authored by [name] on [date]."*

**That is a categorically better explanation than any post-hoc account of a generated plan** — and it is another reason to prefer templates beyond determinism and cost.

---

## 6 · Runtime Integration

### 6.1 Where the Planner sits

```
3A RUNTIME
    ④ GOAL ────────────────────────────────► Goal Engine (§1)
        │                                     admission gate
    ⑤ CONTEXT ─────────────────────────────► Context Plane (2H)
        │
    ⑥ SUFFICIENCY ─────────────────────────► PROCEED?
        │
    ⑦ PLAN ────────────────────────────────► PLANNER (§2)
        │                                     ├ template match
        │                                     ├ (⑧ CONSULT only if none)
        │                                     └ validate whole plan (§4)
    ⑨ DECIDE ──────────────────────────────► Decision Engine
        │                                     adjudicates the WHOLE plan
    ⑩ AUTHORIZE · ⑪ EXECUTE · ⑫ OBSERVE ──► per task, in order
```

### 6.2 The fast path — most turns skip planning entirely

```
INTENT ──► deterministic? ──yes──► single known action ──► ⑨ DECIDE
              │ no
              ▼
           GOAL ──► CONTEXT ──► PLAN ──► ⑨ DECIDE
```

A `#status` command, a factual question, a lookup — none creates a goal or a plan. The decision ladder settles them at rungs 1–3.

**The trace must record which path was taken**, so the proportion of turns reaching the planner is measurable. If it climbs, either goals are being admitted too readily or the fast path has eroded.

### 6.3 Consultation is conditional

Stage ⑧ runs **only** when no template matches. A model call for a plan that already exists as a recipe is pure cost and pure non-determinism.

### 6.4 Planning happens once per turn

Re-planning after a task failure is a **new turn**, not a loop back into ⑦ within the same one.

This keeps the turn short-lived and restartable (3A §2.3), keeps the budget attributable, and means a failed plan produces a recorded decision rather than an invisible retry.

---

## 7 · Acceptance Criteria

### 7.1 Invariants

| # | Invariant |
|---|---|
| **I1** | **No goal without a completion condition** |
| **I2** | **Every goal has a non-null accountable owner** |
| **I3** | **Priority is derived, never assigned** |
| **I4** | **Templates first; model proposal is the exception and is flagged** |
| **I5** | **The whole plan is validated before any task executes** |
| **I6** | **Irreversible tasks are ordered last** |
| **I7** | **Preconditions re-verified at execution, not at planning** |
| **I8** | **Postconditions verify effect, not return status** |
| **I9** | **Non-idempotent tasks are never auto-retried** |
| **I10** | **Parallel reads; sequential writes** |
| **I11** | **A partially executed plan is never abandoned silently** |
| **I12** | **Budget violation rejects the plan; it never truncates it** |
| **I13** | **The Planner never retrieves knowledge itself** |
| **I14** | **The Planner sees only capabilities the principal may invoke** |

### 7.2 Structural

| # | Criterion |
|---|---|
| 1 | Three goal types defined; persistent goals are Commitments |
| 2 | Admission gate with six rejection reasons |
| 3 | Priority derivation defined with five inputs and no override field |
| 4 | Four terminal goal transitions, each recorded to OI |
| 5 | Plan is a task DAG with the fields in §2.1 |
| 6 | Ten validation checks, all mandatory |
| 7 | Five named failure modes, each distinguishable |
| 8 | Four planner contracts declared |

### 7.3 Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 9 | Admit a goal with no completion condition | **REJECTED** |
| 10 | Admit a goal duplicating an active one | **REJECTED** |
| 11 | Set priority directly | **REJECTED** — derived only |
| 12 | Deadline approaches | Priority rises **without any edit** |
| 13 | Goal with a matching template | **Zero model calls**; origin = template + version |
| 14 | Goal with no matching template | Proposal **flagged**; validated identically |
| 15 | Plan referencing an unauthorized capability | **Rejected at validation**, before step 1 |
| 16 | Plan referencing an absent capability | Rejected, distinguishable from *not permitted* |
| 17 | Plan placing an irreversible task before a reversible one | **REJECTED** — reordered or refused |
| 18 | Plan exceeding budget | **REJECTED with a narrower-goal suggestion** — not truncated |
| 19 | Precondition true at planning, false at execution | **Caught at execution** |
| 20 | Capability returns success, postcondition fails | **Escalated as unknown state** — not retried |
| 21 | Non-idempotent task fails ambiguously | **Escalated, never auto-retried** |
| 22 | Plan with two independent write tasks | **Sequential** |
| 23 | Plan with two independent read tasks | May run in parallel |
| 24 | Task fails mid-plan with compensation declared | Completed steps compensated in reverse |
| 25 | Task fails mid-plan, compensation partial | `residual_state` recorded and escalated |
| 26 | Reversible-required task with no compensation declared | **REJECTED at validation** |
| 27 | Decomposition to depth 4 | **REJECTED** |
| 28 | Planner attempts to retrieve knowledge | **REJECTED** — returns `missing` instead |
| 29 | Ask why a template was not used | **Rejected-templates trace answers it** |
| 30 | Ask why this task order | Dependencies + irreversibility constraints |
| 31 | `#status` command | **No goal, no plan** — fast path, visible in the trace |
| 32 | Re-plan after failure | **A new turn**, not a loop within the same one |

### 7.4 The criteria that matter most

| # | Criterion | Why |
|---|---|---|
| **33** | **Measure the proportion of turns reaching the planner** | If it climbs, goals are being admitted too readily or the fast path eroded |
| **34** | **Measure the proportion of plans from templates vs proposals** | A falling template ratio means the recipe library is not keeping up — and non-determinism is growing |
| **35** | **Author a complete plan template for a new vertical using registry rows only** | Zero code. The same extensibility test as every other layer |

### 7.5 Non-regression

| # | Criterion |
|---|---|
| 36 | Zero application code touched |
| 37 | Phase 1C suite green (249 tests) |
| 38 | Compatible with 2A–2I and 3A; no frozen concept modified |
| 39 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 34 is the acceptance test for this slice.** Everything else proves the planner is well-formed. Only 34 proves it is *converging* — that the business is accumulating reusable recipes rather than re-deriving its own procedures with a model on every run.

A planner whose template ratio falls over time is a planner slowly becoming a cost centre and a source of variance.

---

## 8 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Planning is an exception path** — most turns take the fast path with no goal and no plan
2. **Templates first**; model proposal only when none matches, and flagged when it happens
3. **Priority is derived**, with no manual override field
4. **No goal without a completion condition**
5. **Irreversible tasks ordered last**
6. **Postconditions verify effect**, not return status
7. **Parallel reads, sequential writes**
8. **Whole-plan validation before any task executes**
9. **Budget violation rejects; it never truncates**
10. **Re-planning is a new turn**

Items 1 and 2 are the ones that will feel like under-building.

A general LLM planner is more impressive to demonstrate and worse to operate: it is non-deterministic where determinism was available, expensive on turns that needed nothing, and hard to explain after the fact. **The measure of a good planner here is how rarely it runs** — and how often, when it does, it is executing a recipe someone deliberately wrote.
