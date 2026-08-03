# IDD 3C — Decision Engine

**Status:** Design only · no implementation
**Depends on:** BIC v1.0 Constitution · 2A–2I (frozen) · 3A Runtime (frozen) · 3B Goal Engine & Planner (frozen)
**Owns:** Stage ⑨ `ADJUDICATING` · the decision ladder · the decision record
**Does not modify:** any frozen concept

---

## 0 · Four positions, stated first

### 0.1 There are no "decision sources" — there are proposal sources and one authority

The brief asks how decisions may *originate* from rules, templates, LLMs, humans, OI, policy and knowledge, and asks for precedence among them.

**Reframe.** None of those originate a decision. They originate **proposals** and **constraints**. The Decision Engine originates every decision, and it is the only thing that does.

This is not pedantry. If the architecture says *"the LLM is a decision source with low precedence,"* then precedence is a dial, and dials get turned — usually at 11pm during an incident, by someone who reasons that the model has been right lately. If the architecture says *"the LLM is never a decision source,"* there is no dial.

What actually varies between decisions is **which rung of the ladder was decisive**, and that is a recorded fact, not a configuration.

### 0.2 The ladder has never been specified — this document specifies it

3A §1.1 says planning skips the model *"when rungs 1–3 settle it."* 3B §0.1 says single-action requests *"terminate at rungs 1–3."* 2E §9.1 places precedent at *"the fourth rung."*

Three frozen documents depend on a five-rung ladder that no document defines. That is a real gap and it belongs here. §2 defines it.

### 0.3 The dispositive/advisory split is the whole design

| Rungs | Class | May settle a decision alone? |
|---|---|---|
| **1–3** | **Dispositive** | **Yes** |
| **4–5** | **Advisory** | **Never** |

Precedent and model output can raise or lower confidence, shape a proposal, and change which alternatives are considered. Neither can produce a verdict.

Everything else in this document — replayability, LLM independence, Tier 2 operation with AI off, explainability — is a consequence of that single line. It is the line that will come under the most pressure, because rung 5 is the one that demos well.

### 0.4 Absence of a verdict is never approval

The conventional statement is *"fail closed."* Taken literally that means DENY on every uncertainty, and a system that denies without offering a route forward is one that people learn to work around. Shadow processes are worse than a permissive system, because they are invisible.

The precise rule:

> **When the engine cannot reach a verdict, it may not APPROVE. It falls through CLARIFY → ESCALATE → REJECT, taking the first that is available.**

REJECT is the floor, not the default. The engine must exhaust the routes that keep a human in the loop before it becomes an obstacle.

---

## 1 · Decision Architecture

### 1.1 What a Decision is

> **A Decision is an adjudicated verdict on a specific proposed act, by a named authority, on a stated evidence set, at a recorded moment, under a versioned rule set.**

Five clauses, all load-bearing:

| Clause | Without it |
|---|---|
| **a specific proposed act** | A "decision" about nothing in particular cannot be validated, executed or audited |
| **by a named authority** | Nobody is accountable — see §1.3 |
| **on a stated evidence set** | The verdict cannot be replayed, only re-guessed |
| **at a recorded moment** | Later facts contaminate the assessment of an earlier call |
| **under a versioned rule set** | A policy edit silently rewrites the past |

A recommendation is not a decision. An intent is not a decision. A model's output is not a decision. **A decision is the moment the business commits.**

### 1.2 Lifecycle

```
   PROPOSED ──► ADJUDICATING ──┬──► APPROVED ──► AUTHORIZED ──► EXECUTED
                               │                     │
                               │                     └──► SUPERSEDED
                               ├──► REJECTED   (terminal)
                               ├──► CLARIFY    (terminal — new turn on reply)
                               ├──► ESCALATED  (terminal — new turn on approval)
                               ├──► DEFERRED   (terminal — new turn on wake)
                               └──► RETRY      (bounded re-entry, §4.6)

   Every terminal state ──► RECORDED ──► OUTCOME WINDOW OPEN (2I)
```

Three properties of this lifecycle:

1. **A decision is immutable once recorded.** Changing your mind creates a *new* decision that supersedes the old one. The superseding link is recorded; the original is never edited. Anything else destroys the audit trail exactly where it matters.
2. **APPROVED is not AUTHORIZED.** The verdict says the act is permitted in principle. The kernel issues a scoped, expiring, single-use authorization separately, re-verifying preconditions at issuance (3A ⑩). Between the two, the world may have changed.
3. **Every terminal state opens an outcome window** (2I). A REJECTED decision has an outcome too — sometimes the customer went elsewhere, and that is worth knowing.

### 1.3 Ownership — accountability never attaches to software

Every decision carries an **accountable principal**. Not the engine.

| Case | Accountable |
|---|---|
| Settled at rungs 1–3 | The principal on whose authority the act proceeds |
| Escalated and approved | **The approver**, not the requester |
| Approved under a standing policy | The policy owner, at the policy's version |
| Model-influenced (rung 5) | Still the principal — the model has no standing |

> **No decision is ever "made by the AI."** Where a proposal came from is provenance. Who is answerable is ownership. They are different fields and must never be merged.

Practically: when something goes wrong, *"the system decided"* must be an unavailable answer.

### 1.4 Boundaries — what the Decision Engine does not do

| Does not | Because |
|---|---|
| **Retrieve knowledge** | It adjudicates on the packet it was handed (2H). An engine that fetches can fetch until it gets the answer it likes |
| **Author or repair plans** | 3B owns planning. *Never repair a bad proposal into a good action* (3A §1.2 ⑨) |
| **Execute** | Capability Registry. Adjudication and execution in one component means a bug in one is a breach in the other |
| **Issue authorization** | Kernel, at issuance, re-verified |
| **Generate text** | It emits a structured verdict; channels render it |
| **Learn** | OI observes outcomes asynchronously. An engine that updated itself mid-turn would not be replayable |
| **Decide about evidence** | That is the Sufficiency Gate — see §1.5 |

### 1.5 The Sufficiency Gate is not a second Decision Engine

An obvious criticism: 2H's gate emits PROCEED / CLARIFY / RETRIEVE / ESCALATE / REFUSE, which looks like adjudication.

They answer different questions:

| | Question | Input | Output |
|---|---|---|---|
| **Sufficiency Gate** (⑥) | *"Is the evidence adequate for an act of this risk?"* | Packet + risk tier | Verdict on **evidence** |
| **Decision Engine** (⑨) | *"May this specific act proceed?"* | Packet + proposal + policy + precedent | Verdict on **action** |

The gate can say PROCEED and the engine still REJECT — sufficient evidence for a well-founded refusal. The gate never says APPROVE, and the engine never says RETRIEVE.

**Their vocabularies are deliberately non-overlapping.** 2H says REFUSE; 3C says REJECT. Never harmonise these names — the distinction is load-bearing in every trace.

---

## 2 · The Decision Ladder

### 2.1 Five rungs, evaluated in order, stopping at the first decisive one

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ RUNG 1  CONSTITUTIONAL INVARIANT                     DISPOSITIVE│
  │         BIC Article II. Not overridable by anyone, at any tier, │
  │         under any policy. Identity unresolved ⇒ no act.         │
  ├─────────────────────────────────────────────────────────────────┤
  │ RUNG 2  POLICY                                       DISPOSITIVE│
  │         Explicit versioned rules. May DENY or may REQUIRE       │
  │         approval. Evaluated `as_of` the decision moment.        │
  ├─────────────────────────────────────────────────────────────────┤
  │ RUNG 3  DETERMINISTIC RULE / TEMPLATE VERDICT        DISPOSITIVE│
  │         The recipe's own declared outcome, or a business rule   │
  │         with no judgement in it. Same inputs ⇒ same verdict.    │
  ├═════════════════════════════════════════════════════════════════┤
  │ RUNG 4  PRECEDENT  (OI)                                ADVISORY │
  │         "Have we been here before, and how did it go?"          │
  │         Evidence. Never authority. (2E §9.5)                    │
  ├─────────────────────────────────────────────────────────────────┤
  │ RUNG 5  MODEL PROPOSAL                                 ADVISORY │
  │         Consulted only when 1–4 leave the act undetermined.     │
  │         Grounded in the packet. Never a verdict.                │
  └─────────────────────────────────────────────────────────────────┘
```

### 2.2 Human approval is not a rung — it is an outcome

The tempting design puts "human" at the top of the ladder as the ultimate override. It is wrong twice:

- A human **cannot** override rung 1. Article II is not waivable by seniority.
- A human **can** change rung 2 — but that is a *policy amendment*, a separate versioned act with its own audit trail, not an in-flight override.

So human judgement enters as **ESCALATE**, an outcome (§4.4), and the approval creates a new turn (3A §2.3). What the approver then supplies is authority at rung 2 or 3 for the *new* decision — never a bypass of the ladder for the old one.

> **An override that leaves no policy version behind is indistinguishable from a breach.**

### 2.3 What "dispositive" means precisely

A dispositive rung may settle a decision **without any input from rungs below it**. An advisory rung may never settle one, in either direction.

The asymmetry that matters most:

| Advisory rungs may | Advisory rungs may not |
|---|---|
| Lower confidence below a floor → force ESCALATE or REJECT | Raise confidence to clear a floor a dispositive rung set |
| Add alternatives for consideration | Remove an alternative a rule requires |
| Supply reasoning that appears in the record | Supply the verdict |
| Recommend against an act rungs 1–3 permit | Recommend for an act rungs 1–3 forbid |

Advisory input is therefore **asymmetric: it can restrain, it cannot enable.** A model that says "this looks fine" adds nothing to a permission. A model that says "this looks wrong" is worth surfacing.

### 2.4 Precedence is total and has no configuration surface

Rung order is **fixed at 1 < 2 < 3 < 4 < 5** and is not tenant-configurable, not environment-configurable, and not overridable by any flag. A system where a customer can promote rung 5 above rung 2 has no invariants, only defaults.

Conflicts *within* a rung — two policies disagreeing — resolve by 2C §5.2's deterministic conflict ladder, and an unresolved HIGH-severity conflict blocks (2H §6.3). It never resolves by picking one silently.

### 2.5 Most decisions never reach rung 4

By design, and it is measurable (§10, criterion 36). The `#status` command, a factual lookup, a brochure send to a known contact — all settle at rungs 1–3 with zero model calls and zero precedent retrieval.

This is the same argument 3B §0.1 makes about planning, applied to adjudication. Rung 5 is the exception path. Its frequency is a health metric, not a capability metric.

---

## 3 · Decision Validation

### 3.1 Eight gates, fixed order, all evaluated

```
  ① CONSTITUTIONAL   Article II. Identity · tenancy · inline execution · audit
  ② AUTHORIZATION    May THIS principal perform THIS act? (kernel)
  ③ POLICY           Versioned rules, as_of now
  ④ SUFFICIENCY      Confidence floors for this risk tier, all of them (§5)
  ⑤ GOAL ALIGNMENT   Does this act advance a live goal, or conflict with a commitment?
  ⑥ CAPABILITY       Exists · active · healthy · invocable by this principal
  ⑦ BUDGET           Within the turn's and the goal's remaining share
  ⑧ CONSEQUENCE      Reversibility · blast radius · third-party effect (§3.3)
```

**All eight are evaluated. All failures are recorded. The most fundamental one is reported.**

Evaluating only until the first failure sends someone to fix one thing when three are broken; they fix it, retry, and hit the second — a loop that trains people to distrust the system. Reporting all eight is the opposite failure: a wall of text where the actual blocker is buried.

So: evaluate all, record all, lead with the lowest-numbered failure, and list the rest as *"also blocking."*

### 3.2 Overlap with 3B §4 is deliberate, not duplication

3B validates a **plan's structure** before any task runs. 3C validates a **proposed act**. Several checks appear in both at different scope:

| Check | 3B scope | 3C scope |
|---|---|---|
| Authorization | Does any task in the DAG exceed authority? | May this principal do this now? |
| Policy | Does the sequence violate a rule? | Does this act violate a rule, as_of now? |
| Capability | Does the registry have it? | Is it healthy and invocable at this instant? |
| Budget | Does the plan fit? | Does this step fit what remains? |

The world changes between planning and execution. A check that passed at plan time and is not re-run is a check that expired. This is the same reasoning as 3B I7 (preconditions re-verified at execution) and 3A ⑩ (authorization re-verified at issuance).

### 3.3 "Safety" is not a check — it decomposes into three

A gate named *safety* becomes a catch-all: broad enough that anything can be justified through it, and vague enough that nobody can test it. Replace it with three named, answerable properties:

| Property | Question | Data source |
|---|---|---|
| **Reversibility** | Can this be undone, and is the compensation declared? | Capability registry (3B §2.9) |
| **Blast radius** | How many parties, records or rupees does this touch? | Plan scope + capability metadata |
| **Third-party effect** | Does this act become visible outside the tenant? | Capability metadata |

Each is a declared capability property — a registry row, not a judgement. Together they determine the **risk tier**, which is what actually drives the floors.

### 3.4 Risk tiers — 2H's four, unchanged

| Tier | Action class | Confidence floors | Human approval |
|---|---|---|---|
| 1 | Answer a question | Lowest | No |
| 2 | Draft for a human | Low | No |
| 3 | Change internal state | High | No |
| 4 | Irreversible / financial / externally visible | **Highest** | **Always** |

**No new risk scale is introduced.** Tier is derived from §3.3's three properties, and derivation is deterministic. There is no field where a capability author writes its own tier — self-assigned risk trends downward for the same reason self-assigned priority trends upward (3B §0.3).

### 3.5 Goal alignment is a real gate, not a formality

An act that advances no live goal and satisfies no standing commitment is **not automatically rejected** — but it is flagged, and at tier ≥ 3 it escalates.

The failure this catches: a plan that is individually valid at every step and collectively pointless, or worse, that quietly violates a commitment made in another conversation. Commitments are persistent goals (3B §1.2); an act conflicting with one is a conflict the engine must surface, not discover after delivery.

---

## 4 · Decision Outcomes

### 4.1 Six outcomes

| Outcome | Meaning | Terminal? | Requires |
|---|---|---|---|
| **APPROVE** | The act may proceed | No — → AUTHORIZED | All eight gates pass; all floors met |
| **REJECT** | The act may not proceed | **Yes** | A named blocking gate and its rule version |
| **CLARIFY** | Cannot decide; a human here can supply what is missing | **Yes** | **One** specific question |
| **ESCALATE** | Cannot decide at this authority; a named approver can | **Yes** | A named approver or role, and a staged act |
| **RETRY** | Blocked by something transient and non-semantic | Bounded re-entry | A changed input; a counter |
| **DEFER** | Correct act, wrong time | **Yes** | **A wake condition** |

### 4.2 REJECT must be actionable

The 2H §4.5 standard applies unchanged. A bare refusal is a separate failure.

> *"Cannot approve this discount. Blocking: policy DISC-04 v7 caps field discounts at 15% for accounts under 12 months; this account is 4 months old. Also blocking: credit terms last synced 9 days ago against a 24-hour tolerance. An approval from the accounts lead would clear the first."*

That names the rule, its version, the fact that triggered it, the second blocker, and the route forward. It is nearly free once the gates have all been evaluated (§3.1), and it is the difference between a system people use and a system people route around.

### 4.3 CLARIFY asks exactly one question

Not a form. Not a list. **One.**

A system that responds to a request with five questions has moved its own work onto the person who asked. If five things are genuinely missing, that is a REJECT naming the five gaps, or a RETRIEVE at the sufficiency gate — not an interrogation.

Selecting the one question: **the missing input that unblocks the most gates**, tie-broken by the lowest-numbered gate.

### 4.4 ESCALATE is terminal and stages the act

Per 3A §2.3, a turn never spans a human approval. ESCALATE ends the turn. The staged act carries: the proposal, the packet reference, the failing gate, the proposed approver, and an expiry.

**The staged act expires.** An approval arriving three weeks later approves a decision whose evidence is three weeks stale. The new turn re-adjudicates from scratch — the approval supplies authority, not a bypass of §3.

This is also where the Phase 1C confirm-time re-check generalises: *"your access changed since this action was staged"* is a rung-2 denial on the new turn, and it must remain flag-independent.

### 4.5 DEFER without a wake condition is a rejection nobody recorded

DEFER means: the act is correct, the evidence is sufficient, the authority exists — and now is the wrong moment. *Send the reminder after the invoice due date. Follow up after the festival week.*

**Mandatory: a wake condition** — an absolute time, or a named event. A DEFER without one is an act that will never happen, recorded as though it will. That is worse than a REJECT, because a REJECT is visible.

The wake creates a new turn. The deferred decision does not resume; it is re-adjudicated, because the world moved — which was the entire point of deferring.

### 4.6 RETRY — admissible, and narrower than it looks

**Challenge to the brief.** Re-adjudicating identical inputs must, by determinism (§7.2), produce an identical verdict. So RETRY is only coherent when an **input has changed**. Otherwise it is an infinite loop with extra logging.

RETRY is therefore admissible in exactly one case:

> The blocking gate failed for a **transient, non-semantic** reason — a source was unreachable, a capability health check was momentarily red — and re-assembling the packet may change the input.

Constraints:

| Rule | Rationale |
|---|---|
| **Bounded at 2**, reusing 2H §3.3's retrieval bound | One bound for the whole turn; two mechanisms would compose into four attempts |
| **Never for a semantic failure** | A policy denial does not become a permission by asking twice |
| **Never after a partial execution** | 3B I9 — non-idempotent work is escalated, never auto-retried |
| **The counter is recorded** | A decision reached on attempt 2 is not the same evidence as one reached on attempt 1 |

Everything else people call "retry" is 3A's `ASSESSING → ASSEMBLING` transition or an execution-layer retry. Neither is a decision outcome.

### 4.7 The fallback order

When no verdict is reachable:

```
   CLARIFY  ──if a human here can supply it
      ↓
   ESCALATE ──if a named approver exists and the act is stageable
      ↓
   REJECT   ──floor
```

**APPROVE is not in this chain and never enters it.** (§0.4)

---

## 5 · Decision Confidence

### 5.1 No global score — a vector, and it is a conjunction

A single blended confidence number is the most dangerous simplification available here, because **aggregation lets a strong dimension mask a fatal one**. Evidence at 0.97 and precedent at n=1 averages to something comfortable. The n=1 is the whole story.

Five independent dimensions, each with its own floor per risk tier:

| # | Dimension | Measures | Weak means |
|---|---|---|---|
| **D1** | **Evidence sufficiency** | Are the required slots filled, fresh, and adequately sourced? | We are guessing about the facts |
| **D2** | **Evidence agreement** | Conflict severity across sources (2H §6.3) | Our sources disagree about the facts |
| **D3** | **Precedent support** | n, outcome distribution, contradicting cases (2E §9.4) | We have not been here before |
| **D4** | **Capability reliability** | Does this capability actually succeed, historically? (2I) | The mechanism is unreliable |
| **D5** | **Model agreement** | Present only when rung 5 was consulted | The advisor is unsure or dissenting |

> **All applicable floors must be met. There is no trade between dimensions and no aggregation function anywhere in the engine.**

D5 is absent — not zero, *absent* — when the model was not consulted, which is most turns. A dimension that does not apply must not be scored, or its absence starts reading as a weakness.

### 5.2 Evidence strength and conflicting evidence

D1 and D2 come from the packet and are not recomputed here. What the engine adds is the **(evidence, action) pairing**: the same packet is sufficient for a summary and insufficient for a payment (2H §4.4).

An unresolved HIGH-severity conflict blocks — it cannot be averaged away, because severity is computed against *this* decision (2H §6.3). A ₹4 lakh discrepancy is fatal for a credit decision and immaterial for a greeting.

### 5.3 Unknowns are not low confidence

The single most common modelling error at this layer:

| State | Meaning | Correct handling |
|---|---|---|
| **Low confidence** | We looked; the evidence is weak | A score against a floor |
| **UNKNOWN** | Nobody has ever recorded it | Not a score — a gap |
| **NOT_APPLICABLE** | The question does not arise here | Not a score — excluded |
| **REFUSED** | The party declined to tell us | Not a score — **and commercially significant** |
| **PENDING** | Asked; not yet answered | Not a score — a wait |

Collapsing these into a low number destroys real information and produces confident nonsense. This is 2C §5.6 and 2H §6.5 applied at the decision layer, and it is the reason the vector carries **absence kinds alongside scores, never instead of them.**

*"The customer refused to state their budget"* and *"we never asked"* must never render as the same 0.3.

### 5.4 Confidence never lifts a tier ceiling

High confidence does not convert a tier-4 act into a tier-3 one. Approval requirements come from §3.3's declared properties, not from how sure the system feels.

**Restated as an invariant because it will be argued about:** a 0.99 across all five dimensions on an irreversible financial act still requires human approval. Confidence governs whether to proceed *within* a tier. It never moves the tier.

---

## 6 · Decision Explainability

### 6.1 The record is the decision

The explanation is **emitted at decision time, from the inputs that were actually used**. It is never reconstructed afterwards.

A reconstruction is a plausible story about a decision, and a plausible story is worse than no story, because it is believed. This is 2H §7's principle about packets, applied where the stakes are highest.

If the record cannot be written, the response is not sent (3A §1.3).

### 6.2 Five questions, answered from the record

| Question | Answered from |
|---|---|
| **Why approved?** | The decisive rung, the gates passed, the confidence vector against each floor |
| **Why rejected?** | The blocking gate, **the rule and its version**, the fact that triggered it, the other blockers |
| **Why this evidence?** | Provenance chain per claim — source, tier, `asserted_by`, the conflict rung that settled it (2G §6) |
| **Why this capability?** | Template origin (3B §5.2), or the proposal's justification, plus D4 reliability |
| **Why not another proposal?** | **The rejected-alternatives trace** — §6.3 |

### 6.3 Rejected alternatives — the part nobody records

Most systems record what they did. Almost none record what they considered and discarded, which is precisely what a reviewer needs six months later.

Every decision carries alternatives with, for each: what it was, which gate or floor it failed, and at which rung. Three sources:

- templates that matched the goal but failed validation (3B §5.1)
- capabilities that could have served and were absent, unhealthy, or not permitted — **and *absent* is recorded distinctly from *not permitted*** (3B §4.2)
- proposals from rung 5 that were not adopted, with the reason

**"No alternatives were considered" is itself a valid and informative record.** Most rung-1–3 decisions have exactly one path, and saying so plainly is more honest than manufacturing a comparison.

### 6.4 What the record must never contain

Carried forward from Phase 1C, unchanged and non-negotiable:

> No prompts · no model output text · no customer message content · no conversation history · no phone numbers · **no PII of any kind.**

Decisions are compared by structured verdict and rung, never by text. A record containing generated prose is not replayable — it is a transcript, and transcripts diverge on every model version for reasons that have nothing to do with the decision.

### 6.5 A model may narrate; it may never generate the record

3A §7.2 unchanged. The record is assembled from structured facts. A model may be asked to phrase that record for a human reader, and the phrasing is not the record — it is a rendering, discarded after sending, and never replayed.

---

## 7 · Runtime Integration

### 7.1 Where the engine sits

```
   ⑦ PLAN ──── whole plan, as ONE proposal (3B §3.4)
       │
   ⑧ CONSULT ─ rung 5, SKIPPED when rungs 1–3 settled it
       │
   ⑨ DECIDE ── ┌──────────────────────────────────────┐
       │       │  DECISION ENGINE                     │
       │       │  ladder §2 · gates §3 · vector §5    │
       │       │  → verdict + record                  │
       │       └──────────────────────────────────────┘
       │            │
       │      APPROVE │ REJECT │ CLARIFY │ ESCALATE │ RETRY │ DEFER
       ▼
   ⑩ AUTHORIZE ─ kernel · scoped · expiring · single-use
       │          preconditions RE-VERIFIED at issuance
       ▼
   ⑪ EXECUTE ─── per tier ≥ 3 task: RE-ENTER ⑨ at task scope
       │
   ⑬ RECORD ──── decision + execution → OI, BEFORE responding
```

### 7.2 The engine is invoked at two scopes

| Scope | When | Question |
|---|---|---|
| **Plan scope** | Once, before any task runs | *"May this whole plan proceed?"* |
| **Task scope** | Per tier ≥ 3 task, at execution | *"May this specific act proceed, now?"* |

Same engine, same ladder, same gates. **Task scope may DENY what plan scope approved** — the world moved, a precondition failed, a role changed. That is not an inconsistency; it is the reason both exist. A plan approved at 09:00 and executing at 09:40 is executing against a different world.

### 7.3 The fast path

Most turns reach ⑨ with a single known act, settle at rung 1, 2 or 3, skip ⑧ entirely, and emit APPROVE with a one-line record.

**The fast path must be visible in the trace and measured** (§10, criterion 36) — not an optimisation that quietly erodes, but a declared property with a number attached.

### 7.4 Relationship to 3B's three planning levels

The planning tiers and the ladder are orthogonal, and it is worth being explicit because they are easy to conflate:

| | 3B decides | 3C decides |
|---|---|---|
| **Question** | *How* to achieve it | *Whether* it may proceed |
| **Level 0 / no plan** | Direct act | Still adjudicated — usually rung 1–3 |
| **Level 1 / template** | Recipe | Still adjudicated — the template's verdict is rung **3**, not a bypass |
| **Level 2 / model plan** | Proposal | Still adjudicated — the proposal is rung **5**, advisory |

> **A template never bypasses adjudication. It supplies a rung-3 input to it.**

A promoted template (3B) is a human-written recipe that has been reviewed — which is exactly what makes it dispositive at rung 3. Promotion is the act of moving something from rung 5 to rung 3, and it requires a human at L5. That is the only path by which model-originated reasoning ever becomes dispositive, and it passes through a person.

---

## 8 · Replay Compatibility

### 8.1 What makes replay meaningful here

Replay compares **verdicts**, never text. That is only a real test because rungs 1–3 are dispositive and deterministic. If a model could decide, replaying across model versions would measure model mood, not correctness.

> **§0.3 is what turns replay from a diff into a test.**

### 8.2 Three divergence classes

| Class | Same verdict? | Same rationale? | Verdict |
|---|---|---|---|
| **Verdict divergence** | ✗ | — | **Blocks release** unless the changed rung is named |
| **Rationale divergence** | ✓ | ✗ | **Investigate** — the verdict may have been reached by luck |
| **Confidence divergence** | ✓ | ✓ (vector differs) | **Acceptable within declared tolerance** |

Rationale divergence is the class most systems ignore and the most informative. Two Brain versions reaching APPROVE by different rungs are not agreeing — they are coinciding. One of them will stop coinciding.

### 8.3 The release rule

> **A new Brain version that changes a verdict must name the rung that changed and the reason. A verdict change that cannot be attributed to a rung is unexplained, and an unexplained verdict change does not ship.**

Legitimate causes are enumerable: a policy version changed, a template changed, a capability's declared properties changed, a floor changed. If none of those changed and the verdict did, something non-deterministic entered rungs 1–3 — which is a defect, not a feature.

### 8.4 Model replacement

Swap the LLM. Replay the corpus. Expected:

| Decision class | Expected divergence |
|---|---|
| Settled at rungs 1–3 | **Zero.** Any divergence is a defect |
| Reached rung 5 | Non-zero and **must be explainable** as advisory influence — and must never have flipped a verdict rungs 1–3 had already settled |

This is the LLM-independence test, and it is a pass/fail gate on any model change.

### 8.5 What replay records store

Structured only: proposal shape, decisive rung, gate results, confidence vector, absence kinds, rejected alternatives, rule versions, verdict. Never prompts, model text, message content, or PII (§6.4).

---

## 9 · Future Expansion

### 9.1 New industries

Nothing in the engine names an industry. A new vertical supplies:

| Supplied as | What |
|---|---|
| Registry rows | Capabilities, with their reversibility / blast radius / third-party properties |
| Policy rows | Versioned rules |
| Template rows | Recipes (3B) |
| Data | Precedent, accumulated by operating |

**Zero engine changes.** This is Article II.8 — new verticals are INSERTs — applied to adjudication, and it is testable (§10, criterion 38).

### 9.2 New LLMs

Rung 5 is advisory, skippable, and the only place a model touches. The engine has no model-specific logic, no provider-specific parsing in the verdict path, and no dependency on any model being available.

### 9.3 Operating with AI off — Tier 2

Article II.9 requires the business to function at Tier 2 with AI disabled. In this design that is not a fallback mode; it is the normal path with rung 5 unavailable:

- Rungs 1–3 unaffected — full dispositive capability
- Rung 4 unaffected — precedent is structural retrieval, not embedding similarity (2E §9.2), so it does not need a model
- D5 absent from the vector, which is a declared state, not a degradation
- Turns that *require* rung 5 escalate to a human rather than failing

**If most decisions settle at rungs 1–3, losing the model costs a fraction of throughput, not the business.** That is the operational meaning of §0.3, and the reason criterion 36 is the one to watch.

### 9.4 The ten-year test

What must still hold in 2036:

1. The Decision Engine is the only authority
2. Rungs 1–3 dispositive, 4–5 advisory
3. Advisory input restrains; it never enables
4. Human approval is an outcome, not a rung
5. Absence of a verdict is never approval
6. Accountability attaches to a principal, never to software
7. No global confidence score
8. Unknown is not low confidence
9. Confidence never lifts a tier ceiling
10. Explanations are emitted, never reconstructed

None of these mentions a model, a vendor, a database or a channel. That is the test.

---

## 10 · Acceptance Criteria

### 10.1 Invariants

| # | Invariant |
|---|---|
| **I1** | **The Decision Engine is the sole authority; nothing else emits a verdict** |
| **I2** | **Rungs 1–3 are dispositive; rungs 4–5 are advisory and may never settle a decision** |
| **I3** | **Advisory input may restrain but never enable** |
| **I4** | **Rung order is fixed and has no configuration surface** |
| **I5** | **Human approval is an outcome, never a rung; overrides leave a policy version behind** |
| **I6** | **Absence of a verdict is never APPROVE** |
| **I7** | **Every decision has a named accountable principal, never the engine** |
| **I8** | **A decision is immutable once recorded; changes supersede, never edit** |
| **I9** | **APPROVE ≠ AUTHORIZED; the kernel re-verifies at issuance** |
| **I10** | **No global confidence score and no aggregation function** |
| **I11** | **All applicable floors must be met; dimensions do not trade** |
| **I12** | **Unknown, NOT_APPLICABLE, REFUSED and PENDING are never scores** |
| **I13** | **Confidence never lifts a tier ceiling** |
| **I14** | **All eight gates are evaluated; all failures recorded** |
| **I15** | **Explanations are emitted at decision time, never reconstructed** |
| **I16** | **The record contains no prompts, model text, message content or PII** |
| **I17** | **A DEFER without a wake condition is invalid** |
| **I18** | **RETRY requires a changed input and is bounded at 2** |
| **I19** | **The engine never retrieves knowledge, authors plans, executes, or issues authorization** |
| **I20** | **A verdict change across Brain versions must name the rung that changed** |

### 10.2 Structural

| # | Criterion |
|---|---|
| 1 | Five rungs defined, ordered, with the dispositive/advisory split explicit |
| 2 | Eight validation gates defined in fixed order |
| 3 | Six outcomes defined, each with its mandatory fields |
| 4 | Confidence vector of five dimensions, each with per-tier floors, no aggregator |
| 5 | Five absence kinds carried distinctly from scores |
| 6 | Risk tier derived from three declared capability properties; no self-assigned tier field |
| 7 | Five explainability questions answerable from the record alone |
| 8 | Three replay divergence classes defined with distinct handling |
| 9 | Two adjudication scopes (plan, task) defined with the same ladder |
| 10 | Decision vocabulary non-overlapping with 2H's sufficiency vocabulary |

### 10.3 Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 11 | Model proposes an act that policy forbids | **REJECT** — rung 2 decisive, model recorded as advisory only |
| 12 | Model proposes against an act rungs 1–3 permit | Recorded, surfaced; **does not flip the verdict** |
| 13 | Precedent shows 40 successes for a policy-forbidden act | **REJECT** — precedent is not permission |
| 14 | Precedent shows n=1 with a good outcome | D3 below floor at tier ≥ 3 → ESCALATE |
| 15 | Attempt to configure rung 5 above rung 2 | **No such configuration exists** |
| 16 | Identity unresolved | **REJECT at rung 1** before any other gate |
| 17 | Engine cannot reach a verdict, human can supply the gap | **CLARIFY**, exactly one question |
| 18 | Engine cannot reach a verdict, no human input helps, approver exists | **ESCALATE** |
| 19 | Engine cannot reach a verdict, no route available | **REJECT** — never APPROVE |
| 20 | Three gates fail | All three recorded; **lowest-numbered reported**; others listed |
| 21 | Tier-4 act with 0.99 on all five dimensions | **Still requires human approval** |
| 22 | Evidence 0.97, precedent n=1, tier 3 | **Blocked** — no averaging |
| 23 | Party refused to supply a required fact | Carried as `REFUSED`, **not as 0.0** |
| 24 | Fact never recorded anywhere | Carried as `UNKNOWN`, distinct from low confidence |
| 25 | Model not consulted | D5 **absent**, not zero |
| 26 | DEFER submitted without a wake condition | **REJECTED as malformed** |
| 27 | DEFER wakes | **New turn, re-adjudicated** — not resumed |
| 28 | ESCALATE approved three weeks later | Staged act **expired**; re-adjudicated from scratch |
| 29 | Approver's role changed since staging | **Rung-2 denial on the new turn**, flag-independent |
| 30 | RETRY after a policy denial | **Refused** — semantic failures do not retry |
| 31 | RETRY attempted a third time | **Refused** — bounded at 2 |
| 32 | Plan approved at plan scope, precondition false at execution | **Task scope DENIES** |
| 33 | Ask "why not another proposal?" | Rejected-alternatives trace answers it, with *absent* distinct from *not permitted* |
| 34 | Decision with one possible path | Record states **"no alternatives"** explicitly |
| 35 | Engine attempts to retrieve knowledge | **Refused** — adjudicates on the packet only |

### 10.4 The criteria that matter most

| # | Criterion | Why |
|---|---|---|
| **36** | **Measure the proportion of decisions settled at rungs 1–3** | The single health metric for this layer. If it falls, the business is drifting into model dependence, and its ability to operate at Tier 2 is eroding — silently, until the day the model is unavailable |
| **37** | **Swap the LLM, replay the corpus: zero verdict divergence on rung 1–3 decisions** | The LLM-independence gate. Pass/fail on any model change |
| **38** | **Adjudicate a decision for a new vertical using registry, policy and template rows only** | Zero engine code. The same extensibility test as every other layer |
| **39** | **Every recorded decision answers all five explainability questions with no reconstruction** | If it cannot, the record is a log, not an audit trail |

**Criterion 36 is the acceptance test for this slice**, and it pairs with 3B's criterion 34.

3B's number says whether the business is accumulating reusable procedures. 36 says whether it is retaining the ability to decide without a model. A system can pass every structural test in this document and still fail slowly, one convenient rung-5 consultation at a time — and the only thing that catches that is a number, tracked over years.

### 10.5 Non-regression

| # | Criterion |
|---|---|
| 40 | Zero application code touched |
| 41 | Phase 1C suite green (249 tests) |
| 42 | Compatible with 2A–2I, 3A, 3B; no frozen concept modified |
| 43 | Decision vocabulary distinct from 2H's sufficiency vocabulary throughout |
| 44 | **Live production probe:** unsigned → 403; a real message replies |

---

## 11 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **The Decision Engine is the sole authority** — rules, templates, models, precedent and humans supply proposals and constraints, never verdicts
2. **Rungs 1–3 dispositive, 4–5 advisory** — and advisory input restrains but never enables
3. **Human approval is an outcome, not a rung** — an override that leaves no policy version behind is a breach
4. **Absence of a verdict is never APPROVE** — the fallback is CLARIFY → ESCALATE → REJECT
5. **No global confidence score** — five dimensions, all floors conjunctive, no aggregator anywhere
6. **Unknown is not low confidence** — absence kinds are carried, never scored
7. **Confidence never lifts a tier ceiling** — a tier-4 act needs human approval at any confidence
8. **All eight gates evaluated, all failures recorded, the most fundamental reported**
9. **Explanations emitted at decision time**, including rejected alternatives
10. **RETRY requires a changed input**; **DEFER requires a wake condition**

Items 2 and 5 are the ones that will feel like under-building. A single confidence score is easier to display and easier to threshold, and a model that can decide is faster to demonstrate. Both trade a property that cannot be recovered later: once a verdict can come from rung 5, replay stops being a test, and once confidence is a scalar, the dimension that should have blocked the decision is already averaged away.

The measure of this engine is not how cleverly it decides. It is that in ten years, someone can ask why a decision went the way it did, and get an answer that does not depend on a model that no longer exists.
