# IDD 3D — Decision Replay & Explainability

**Status:** Design only · no implementation
**Depends on:** BIC v1.0 Constitution · 2A–2I (frozen) · 3A Runtime · 3B Goal Engine & Planner · 3C Decision Engine (frozen)
**Owns:** the Replay Engine · the Comparison Engine · the Explainability Engine · the replay corpus · the referenced-artifact manifest
**Does not modify:** any frozen concept

> **Restoration note.** The original of this document was written on 2026-08-11 and destroyed before it was committed — an untracked file lost to scratchpad cleanup. This is a faithful restoration from the preserved design, not a redesign. The four corrections, the two replay modes, the divergence and regression taxonomies, the corpus design and the retention invariant are unchanged. Recorded here because a document about replayability that quietly lost its own history would be self-refuting.

---

## 0 · Four corrections to the proposed architecture

### C1 — Explainability does not sit downstream of Replay

The proposed chain is `Record → Replay → Comparison → Explainability → Reports`.

That makes answering *"why was my discount rejected?"* require re-running the Brain. It is wrong for the common case and dangerous for the important one: 3C §6.1 already requires the explanation to be **emitted at decision time**, so the record answers the question directly.

If explanation depended on replay, then any decision that became un-replayable would also become unexplainable — and un-replayability is exactly what happens to old decisions. The oldest decisions, the ones most likely to be disputed, would be the ones the system could no longer account for.

> **Explainability and Replay are two independent consumers of the same record.** The architecture is a fan-out, not a chain (§11).

Latency proves the point: an explanation is a sub-second lookup a person waits for; a replay is a batch job over thousands of decisions. Binding them couples a human-facing path to a CI-facing one.

### C2 — "Load Evidence Packet" hides the hardest question in this document

The proposed flow loads the packet as though it were sitting somewhere. It is not, and both available answers are wrong on their own:

| Approach | Fails because |
|---|---|
| **Store the packet verbatim** | It is full of PII, held forever — contradicting 3C §6.4 and the Phase 1C rule that replay records contain no customer data |
| **Reconstruct it from knowledge** | Bitemporal reconstruction (2C) gives *what we would now believe about then* — which diverges after corrections, retractions and party merges (2D) |

The resolution is §2.3: **store the packet's fingerprint, reconstruct its contents, and compare.** This makes two failure modes distinguishable that nearly every system conflates — and telling them apart is the single most useful property in this document.

### C3 — Replay must be structurally incapable of executing

The proposal says "Replay Decision." Replaying a decision that approved a payment must not approve the payment again.

Configuration is not sufficient protection here. A flag that disables execution is a flag someone can flip, and the failure mode is a duplicate irreversible act.

> **The Replay Engine terminates at stage ⑨. It has no path to ⑩ AUTHORIZE or ⑪ EXECUTE — not a disabled path, no path.**

It holds no capability handles and no authorization-issuing reference. Replay produces a verdict and stops. The same reasoning as 3C §2.4's refusal to give rung order a configuration surface — and the same reasoning already implemented in 1C's replay mode, where a flow in replay is handed recorders in place of the real sender and writers, so it holds no reference to anything that can mutate state.

### C4 — "Replay success rate" measures the corpus, not the Brain

A 100% success rate means either the Brain is perfectly deterministic or the corpus contains only easy cases, and the metric cannot tell you which.

Worse, it conflates two unrelated things: *can this be replayed at all* and *does it replay to the same verdict*. The first is a property of the archive; the second is a property of the Brain. §8 separates them, and names the one that actually matters — **the un-replayable rate**, because those are the decisions that cannot be defended in a dispute.

> **An un-replayable decision is an archive defect, not a Brain regression.** Counting it as a regression sends every investigation in the wrong direction.

---

## 1 · Replay Architecture

### 1.1 Purpose

Three questions, in descending frequency and ascending stakes:

| Question | Asked by | Answered by |
|---|---|---|
| *"Why did this decision go this way?"* | A person, about one decision | **Explainability** — record lookup |
| *"Would this decision still go this way?"* | CI, before a release | **Replay + Comparison** |
| *"Was this decision defensible when it was made?"* | An auditor, a regulator, a court | **Both** — record, plus reconstruction to prove the record is faithful |

The third is the one the architecture is built for. The first two are frequent; the third is rare, adversarial, and years late.

### 1.2 Three things that are not the same

The distinction the industry collapses, and the reason most systems believe they have replay when they have a third of it:

| | Answers | Fails when |
|---|---|---|
| **Audit log** | *What happened?* | Never — but it never answers the other two |
| **Explanation** | *Why was it justified at the time?* | The record is incomplete |
| **Replay** | *Would the same thing happen now?* | The referenced artifacts are gone |

A log is a sequence of events. An explanation is an account of a decision. A replay is a re-derivation. **A system that has logging often believes it has replay; it has one third of it.**

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| Every recorded Decision (3C §1.1) | Message content, conversation flow, model prose |
| Verdicts, rungs, gates, confidence vectors, alternatives | Whether the *outcome* was good — that is OI (2I) |
| Packet fingerprints and bitemporal reconstruction | Re-deriving what a model would say today, except in live-advisory mode |
| Policy, template, capability and floor versions | Execution results — replay never executes |

### 1.4 Runtime position — outside the runtime

Replay is **not a runtime stage**. It runs offline, asynchronously, on a corpus, triggered by a release candidate, a policy change, a provider change or an investigation. It never participates in a live turn.

This is the same separation 3A §0 C2 makes for outcome tracking: a thing that observes the runtime cannot be a stage inside it.

### 1.5 Inputs

```
  ① DECISION RECORD ......... verdict · decisive rung · gate results
                              confidence vector · absence kinds
                              rejected alternatives · advisory input (structured)
  ② ARTIFACT MANIFEST ....... every referenced version (§3)
  ③ PACKET FINGERPRINT ...... per-slot structure + hashes, NO values (§2.3)
  ④ BRAIN VERSION ........... the one under test, or the original
  ⑤ AS_OF CLOCK ............. the decision moment, frozen
  ⑥ KNOWLEDGE STORE ......... read bitemporally, for reconstruction only
```

### 1.6 Outputs

```
  → REPLAY VERDICT .......... what the Brain decides now, on then's inputs
  → FIDELITY RESULT ......... match | verdict divergence | rationale divergence
                              | confidence divergence  (3C §8.2)
  → RECONSTRUCTION RESULT ... packet fingerprint matched, or the slots that moved
  → ATTRIBUTION ............. which rung changed, and why  (3C §8.3)
  → REGRESSION CLASS ........ safety | hard | soft | explainability | performance
  → NEVER: any side effect, any authorization, any execution, any message
```

### 1.7 Boundaries

| The Replay Engine does not | Because |
|---|---|
| **Execute anything** | C3 — no path to ⑩ or ⑪ |
| **Retrieve live knowledge** | It would replay against today's facts and call it history |
| **Consult a model by default** | That tests the model, not the Brain (§2.5) |
| **Write to the knowledge store** | Reads only, bitemporally |
| **Modify a decision record** | Records are immutable (3C §1.2) |
| **Generate an explanation** | Explainability derives from records; replay produces verdicts |
| **Judge whether the outcome was good** | 2I owns outcomes. Replay judges *justification*, not *result* |

That last boundary is worth dwelling on. **A decision can replay perfectly and still have been a bad call**, and a decision can have gone beautifully and still have been unjustified at the time. Merging the two produces a system that learns to approve whatever worked, which is how precedent becomes permission — the thing 2E §9.5 forbids.

---

## 2 · The Replay Model

### 2.1 The corrected flow

```
   DECISION RECORD  (immutable)
        │
   ① RESOLVE MANIFEST ....... load every referenced artifact AT ITS VERSION
        │                     policy · template · capability · floors · schema
        │                     ✗ any version missing ⇒ UN-REPLAYABLE (§8.2)
        │
   ② RECONSTRUCT PACKET ..... bitemporal read, as_of the decision moment
        │                     valid_from ≤ T < valid_until AND observed_at ≤ T
        │
   ③ VERIFY FINGERPRINT ..... reconstructed shape vs recorded fingerprint
        │                     ✗ mismatch ⇒ RECONSTRUCTION DIVERGENCE — a finding,
        │                       not a failure; the past record of the past moved
        │
   ④ LOAD BRAIN ............. original version, or the candidate under test
        │
   ⑤ REPLAY TO VERDICT ...... ladder §2 · gates §3 · vector §5  (3C)
        │                     TERMINATES HERE. No ⑩. No ⑪. No exceptions.
        │
   ⑥ COMPARE ................ verdict · rationale · confidence  (3C §8.2)
        │
   ⑦ ATTRIBUTE .............. name the rung that changed, or fail the release
        │
   ⑧ CLASSIFY ............... regression class (§6)
```

Step ③ is the one the proposed flow omits, and it is the difference between replay that proves something and replay that assumes it.

### 2.2 Frozen versus variable

| | Frozen — replay is invalid if it differs | Variable — the thing under test |
|---|---|---|
| **Proposal** | ✓ | |
| **Packet fingerprint** | ✓ | |
| **Policy versions** | ✓ | (varied deliberately in policy comparison, §5.4) |
| **Template versions** | ✓ | |
| **Capability declared properties** | ✓ | |
| **Confidence floors** | ✓ | |
| **Risk-tier derivation** | ✓ | |
| **as_of clock** | ✓ | |
| **Advisory input (rung 4–5)** | ✓ in frozen mode | varied in live-advisory mode (§2.5) |
| **Brain version** | | ✓ |
| **Model provider** | | ✓ live-advisory only |
| **Explanation rendering** | | ✓ — cosmetic, never compared |

**Never present under any mode:** live knowledge retrieval · capability execution · authorization issuance · any outbound message · any write.

### 2.3 The packet fingerprint — the resolution to C2

The record stores, per evidence slot:

| Stored | Not stored |
|---|---|
| Slot identity | **The value** |
| Provenance tier and source identity | Source contents |
| Confidence and freshness at decision time | Anything textual |
| Absence kind (`UNKNOWN` / `NOT_APPLICABLE` / `REFUSED` / `PENDING`) | — |
| Conflict presence, severity, resolving rung | The conflicting values |
| **A content hash** | The content |

This is PII-free by construction and satisfies 3C §6.4 without weakening it.

Replay reconstructs the packet bitemporally and compares hashes. Two outcomes, and **they mean entirely different things**:

| Result | Meaning | Class |
|---|---|---|
| **Fingerprint matches** | The knowledge store still tells the same story about that moment. Any verdict divergence is attributable to the Brain | Replay is valid |
| **Fingerprint differs** | The *record of the past* changed — a correction, a retraction, a party merge (2D), a decommissioned source | **Reconstruction divergence** |

> **Reconstruction divergence is a finding, not a failure.** It says: *we now believe something different about what was true then.*

Most systems cannot distinguish this from a Brain regression, and so cannot tell a code bug from a data correction. Given that 2C makes corrections first-class (new claim, back-dated `valid_from`, forward `observed_at`) and 2D makes merges reversible, corrections will be **routine** — so this distinction is not a corner case. It is the normal operating condition of an honest knowledge store.

A decision whose fingerprint no longer matches is still explainable (the record stands) but is **replayed with a declared caveat**, and it is excluded from fidelity statistics rather than counted as a regression.

### 2.4 Replay divergence versus reconstruction divergence

The two must never be summed, and the difference is causal, not cosmetic:

| | Cause | Means | Action |
|---|---|---|---|
| **Replay divergence** | Same packet, different verdict | **The Brain changed** | Attribute to a rung, or block the release |
| **Reconstruction divergence** | Different packet | **The knowledge changed** | Investigate the correction; exclude from fidelity stats |

Reported as one number, a healthy stream of data corrections would mask a genuine Brain regression indefinitely — which is precisely the failure this separation exists to prevent.

### 2.5 Why the clock is frozen

`as_of` is the decision moment, and everything reads through it: bitemporal knowledge, policy `as_of` lookup (2H ⑦), the party graph, capability properties.

Without a frozen clock, replaying a two-year-old credit approval applies today's credit policy to a customer whose circumstances have since changed, and calls the disagreement a regression. Every finding would be noise.

### 2.6 Two replay modes, never conflated

| Mode | Rung 4–5 input | Deterministic? | Answers |
|---|---|---|---|
| **Frozen-advisory** (default) | Replayed from the record | **Yes** | *Did the Brain change?* |
| **Live-advisory** | Re-consulted from a live model | No, by design | *Does the model change the answer?* |

**Frozen-advisory is the release gate.** It must be bit-stable: same inputs, same verdict, every run, forever. Any non-determinism here is a defect in rungs 1–3.

**Live-advisory is the provider-comparison tool** (§5.3) and is never a release gate on its own, because a non-deterministic input cannot gate a deterministic release.

What gets replayed at rung 5 is the model's **structured proposal** — capability, arguments, alternatives, advisory direction (restrain / neutral) — never its prose. That is replayable, PII-free, and consistent with 3C §6.4. A record that stored the model's words would diverge on every provider version for reasons that have nothing to do with the decision. This is the same principle 1C already applies: compare the inputs and the choices, never the generated text.

### 2.7 Determinism is a property, not an aspiration

Frozen-advisory replay of the same record on the same Brain version must produce an identical verdict **on every run, on every host, in any order, at any time**.

Named threats, each of which must be structurally absent from the verdict path:

| Threat | Rule |
|---|---|
| Wall-clock reads | Only `as_of` is readable; system time is not in scope |
| Random or UUID generation | Not in the verdict path |
| Map/set iteration order | Ordered structures where order affects a result |
| Floating-point accumulation | Confidence dimensions compared with declared tolerance, never equality |
| Concurrency | Replay is single-decision-at-a-time; parallelism across decisions only |
| Locale or timezone | All temporal reasoning in one canonical zone |
| Live network reads | None in the verdict path |

---

## 3 · The Referenced-Artifact Manifest

### 3.1 What actually rots over ten years

Replay does not fail because the algorithm was wrong. It fails because something it referenced is gone:

| Rot | Consequence |
|---|---|
| A policy was **edited** rather than versioned | Rung 2 unreconstructible |
| A template was edited in place | Rung 3 unreproducible |
| A capability was **deleted** from the registry | Its declared properties are unknown; the risk tier cannot be re-derived |
| A confidence floor set changed with no version | The floors that applied then are unknowable |
| A knowledge source was decommissioned | Provenance dangles |
| A party was merged (2D) | The packet reconstructs to a different entity |
| The Brain version is gone | Original-fidelity replay impossible |

Every one of these is a routine, well-intentioned housekeeping act. **Replayability dies of tidiness**, not of neglect.

### 3.2 The manifest

Every decision record carries version identifiers for **every artifact its verdict depended on**: Brain version · policy versions (each rule consulted) · template version · capability versions · confidence floor set version · risk-tier derivation version · record schema version · knowledge source identities.

Not names. **Versions.** A name resolves to whatever exists now; a version resolves to what existed then.

### 3.3 The retention invariant

> **No artifact referenced by a retained decision may be deleted. Retirement means marking inactive — never removal.**

This is the concrete mechanism that makes ten-year replay possible. Without it, everything else in this document is aspiration.

Two consequences worth accepting explicitly:

- **Retirement and deletion are different operations**, and only one exists for referenced artifacts. A capability retired in 2027 is still resolvable in 2036 — inactive, unusable, fully described.
- **The archive grows monotonically.** That is the cost. Version rows are small, they are not PII, and they compress well. It is the cheapest part of this architecture and the one without which none of the rest works.

### 3.4 Un-replayable is a state, not an error

When the manifest cannot resolve, the decision is marked **UN-REPLAYABLE with a named missing artifact**. It is not a failure, not a regression, and not silently skipped.

It is a **defect in the archive**, tracked as its own metric (§8.2), because a rising un-replayable rate is the clearest possible signal that the retention invariant is being violated somewhere — and it is the only signal that arrives before the dispute does.

---

## 4 · Explainability

### 4.1 The eight questions, each answered from the record

| # | Question | Answered from | Present when |
|---|---|---|---|
| 1 | **Why this answer?** | Decisive rung + gate results + verdict | Always |
| 2 | **Why this action?** | Goal linkage + plan origin (3B §5.2) + capability selection | Always |
| 3 | **Why this capability?** | Template origin, or proposal justification, plus D4 reliability | Always |
| 4 | **Why this evidence?** | Provenance chain per slot — source, tier, `asserted_by`, resolving conflict rung | Always |
| 5 | **Why not another option?** | Rejected-alternatives trace (3C §6.3), *absent* distinct from *not permitted* | Always — including *"no alternatives existed"* |
| 6 | **Why was AI consulted?** | The rung at which 1–3 failed to settle it, and what remained undetermined | When rung 5 was reached |
| 7 | **Why was AI *not* consulted?** | **The rung that was decisive**, positively recorded | **Always — see §4.2** |
| 8 | **Why was human approval required?** | Risk tier + its three derived properties, or the policy rule that demanded it | When escalated |

### 4.2 Question 7 is the one that proves the design

Most systems cannot answer *"why wasn't AI consulted?"* because non-consultation leaves no trace. Silence is indistinguishable from an outage, a bug, a disabled flag, or a deliberate deterministic settlement.

> **Non-consultation is positively recorded.** *"Rung 3 decisive — template T-114 v3. Model not consulted: not required."*

The absence of a record is never an answer. This is the same discipline as 3C §6.3's explicit *"no alternatives were considered"* and 2C §5.6's insistence that absence kinds are carried distinctly.

Since rungs 1–3 settle the large majority of decisions (3C criterion 36), question 7 is the *most frequently asked* of the eight. A system that cannot answer its most common audit question has an explainability layer in name only.

### 4.3 Derived, never regenerated

Every answer is assembled from stored structured facts. The Explainability Engine performs **lookup and formatting**. It performs no inference.

Three prohibitions, in order of how tempting they are:

| Prohibited | Why |
|---|---|
| Asking a model *why* a decision was made | It will produce a fluent, plausible, unfalsifiable answer. A plausible story about a decision is worse than none, because it is believed |
| Deriving a reason from the verdict | Reasoning backwards from the outcome always finds a justification. That is rationalisation with a schema |
| Filling a gap with a default | *"Presumably because…"* in an audit trail is a fabrication with hedging |

> **If a question cannot be answered from the record, the correct answer is: "the record does not contain this."**

That sentence must be a first-class, expected output — not an error path. It is also a defect report about the record, and it feeds the explanation-completeness metric (§8.4).

### 4.4 Explanation survives un-replayability

A decision whose manifest no longer resolves is still fully explainable, because the record is self-contained (C1). This asymmetry is deliberate and it is the reason C1 matters:

| | Needs the manifest? | Needs the knowledge store? |
|---|---|---|
| **Explanation** | ✗ | ✗ |
| **Replay** | ✓ | ✓ |

The oldest decisions are the most likely to be disputed and the least likely to replay. They must remain explainable, and they do.

---

## 5 · Decision Comparison

### 5.1 Original vs Replay — the determinism check

Same record, same Brain version, frozen-advisory mode.

**Expected divergence: exactly zero.** Any divergence at all is a defect in the verdict path — one of §2.7's threats got in. This runs continuously, not per release, because non-determinism appears between releases and is cheapest to catch immediately.

### 5.2 Brain v1 vs Brain v2 — the release gate

Same records, same advisory input, different Brain.

3C §8.3 applies unchanged: **a verdict change must name the rung that changed.** Legitimate causes are enumerable — a policy version, a template, a capability property, a floor. If none changed and the verdict did, something non-deterministic entered rungs 1–3.

The asymmetry that must never be averaged away:

| Direction | Class | Blocks? |
|---|---|---|
| **REJECT → APPROVE** | **Safety** — the new Brain permits what the old refused | **Unconditionally** |
| **ESCALATE → APPROVE** | **Safety** — human oversight silently removed | **Unconditionally** |
| **APPROVE → REJECT** | Correctness — possibly a fix, possibly over-restriction | Requires attribution |
| **APPROVE → ESCALATE** | Conservative — usually intentional | Requires attribution |

> **A single "divergence rate" that mixes these is a metric that hides exactly the changes it exists to catch.**

### 5.3 GPT vs DeepSeek — live-advisory only

Live-advisory mode, all else frozen. Per 3C §8.4:

| Decision class | Expected |
|---|---|
| Settled at rungs 1–3 | **Zero divergence.** Any divergence is a defect — a model influenced a decision it should never have touched |
| Reached rung 5 | Non-zero, explainable as advisory influence, and **never a flipped verdict that rungs 1–3 had settled** |

Because rung 4–5 input is advisory-and-restraining-only (3C §2.3), the *only* legitimate provider-driven divergence is one model restraining where another did not. A provider swap that produces new *approvals* has breached the advisory rule, and that is a finding about the architecture, not about the model.

This is the pass/fail gate for any provider change — including the one that will eventually be forced by a deprecation notice.

### 5.4 Policy versions — measuring blast radius

Same records, same Brain, policy set varied.

Divergence here is **expected and desired** — a policy change that changes no decisions changed nothing. The test is a different one:

> **Does the divergence appear only where the policy applies?**

A discount policy amendment that changes discount decisions is working. The same amendment changing an unrelated onboarding decision is a **blast-radius defect** — the rule is broader than its author believed. Replay is the only tool that finds this before customers do, and it should run on every policy change, not only on code releases.

### 5.5 Knowledge snapshots — measuring decision fragility

Same records, same Brain, packet reconstructed at different `observed_at` points.

Divergence is **not a Brain defect**. It is a **sensitivity measurement**: how much did the verdict depend on facts that later turned out to be wrong?

| Result | Meaning |
|---|---|
| Verdict stable across corrections | The decision was robust — it did not hinge on a shaky fact |
| Verdict flips on one corrected fact | The decision was **fragile**, and the confidence vector should have shown it |

Systematic fragility that the confidence vector did not predict is a finding about the **floors**, not about any individual decision. It is the strongest available feedback on whether 3C §5's thresholds are calibrated, and it is otherwise almost impossible to obtain.

### 5.6 What is never compared

Rendered explanation prose · model output text · response wording · timing · log formatting.

**Comparing text turns every cosmetic change into a regression**, and a suite that cries wolf gets disabled. This is the 1C lesson (a test that matched prose rather than behaviour passed while the behaviour was removed), stated as an architectural rule.

---

## 6 · Regression Detection

### 6.1 Five classes

| Class | Definition | Blocks release? |
|---|---|---|
| **Safety** | A previously refused, escalated or human-approved act is now permitted or auto-approved; a tier-4 lost its approval requirement; a policy denial became a permission | **Yes — unconditionally, not overridable** |
| **Hard** | A verdict changed with **no attributable rung change** (3C §8.3) | **Yes** — until attributed |
| **Explainability** | A decision that previously answered all eight questions can no longer answer one | **Yes** |
| **Soft** | Same verdict, rationale or confidence changed beyond declared tolerance | No — requires sign-off |
| **Performance** | Replay latency or turn cost degraded | No — unless a 3A §5 budget ceiling is breached |

**Un-replayable is not in this table.** It is an archive defect (§3.4, C4), tracked separately, and it never blocks a release — because blocking a release for a record written years ago punishes the wrong change.

### 6.2 The class the brief did not ask for

**Explainability regression** is the addition, and it blocks.

It is a silent loss of auditability that no other class catches: verdicts still match, confidence still matches, every existing test is green — and a decision that could be defended last month cannot be defended today. Nothing surfaces it except asking the eight questions on every replay and comparing which are answerable.

The failure is usually mundane: a field stopped being populated, a version reference was dropped, a trace was trimmed for size. It is invisible until an auditor arrives, at which point it is unfixable retroactively.

### 6.3 Safety regressions are not overridable

Every other class has a human escape hatch — attribution, sign-off, an accepted trade. Safety has none.

If a change legitimately means an act should now be permitted, **the correct route is a policy amendment, versioned, with its own audit trail** (3C §2.2), after which the replay divergence is attributable to a policy version change and is no longer a safety regression at all.

> **An override that leaves no policy version behind is indistinguishable from a breach** — 3C's rule, applied to the release process rather than to a single decision.

The escape hatch exists. It goes through the policy layer, where it is recorded, and not through the release process, where it would not be.

### 6.4 Attribution is the release currency

Every hard regression must resolve into a named cause: a policy version, a template version, a capability property, a floor, or a fixed defect. Unattributed verdict changes do not ship.

The practical effect: **a release either explains its behavioural changes or does not go out.** That is a demanding bar, and it is the only one that holds for ten years without eroding.

---

## 7 · The Replay Corpus

### 7.1 Sampling production would produce a useless corpus

Production distribution is roughly 90% Level 0 trivia — `#status`, lookups, single acts (3B). A corpus mirroring that distribution spends 90% of its budget re-proving that `#status` still works, and covers the tier-4 financial decisions with a handful of cases.

> **The corpus is stratified and deliberately over-weighted toward the rare.** It is curated, not sampled.

### 7.2 Six strata

| Stratum | Contents | Why |
|---|---|---|
| **Golden** | Canonical decisions per category, hand-reviewed and blessed | The baseline. Divergence here is always significant |
| **Edge** | Boundary conditions — floors met exactly, tier boundaries, `n=1` precedent, expiry moments | Where off-by-one reasoning lives |
| **Failure** | Every decision from a production incident | Characterization discipline: a bug fixed without a corpus case will return |
| **Security** | Authorization boundaries, role changes mid-flight, staged-act expiry, unresolved identity, tenancy isolation | The cases where a regression is a breach |
| **Policy** | One per policy rule, plus every case that rule has ever changed | Makes blast-radius testing (§5.4) possible at all |
| **Approval** | Every tier-4, every escalation, every approval and every refusal | The decisions most likely to be disputed |

Plus a **routine floor**: enough Level 0 cases to catch fast-path regressions, since the fast path is where a subtle break would go unnoticed longest.

### 7.3 Growth by admission

The corpus grows by **rule, not by accumulation**:

| Trigger | Admits |
|---|---|
| A production incident | The decision that caused it, permanently |
| A defect fixed | The decision that exposed it |
| A new policy rule | At least one decision exercising it |
| A new capability | At least one decision invoking it |
| A new vertical | A representative decision per category |
| A dispute or audit query | The disputed decision |
| A safety regression caught | The case that caught it |

**Cases are never removed for being old.** They may be marked un-replayable when their manifest decays (§3.4) — which is itself the signal that retention is failing.

### 7.4 Two anti-patterns

| Anti-pattern | Consequence |
|---|---|
| **Pruning to keep the suite fast** | The removed cases are always the awkward ones, and awkward is where regressions live |
| **Regenerating the corpus from current production** | Erases every historical case — precisely the ones proving old decisions still replay. A regenerated corpus can only ever validate the present |

### 7.5 The corpus contains no PII

Every case is a decision record and a packet fingerprint — structure, provenance, hashes. No values, no messages, no phone numbers. It is safe to retain indefinitely and safe to hand to an auditor, which is the point.

---

## 8 · Replay Metrics

### 8.1 Decomposing "replay success rate"

Per C4, the proposed single metric conflates a property of the archive with a property of the Brain. Two metrics:

| Metric | Measures | Property of | Target |
|---|---|---|---|
| **Replayability rate** | Fraction whose manifest fully resolves | **The archive** | 100%, and it degrades over time |
| **Fidelity rate** | Of replayable cases, fraction with matching verdicts | **The Brain** | 100% in frozen-advisory mode |

Keeping the "property of" column visible is the whole point: a falling replayability rate is a retention failure, and a falling fidelity rate is a code failure. They are fixed by different people in different places.

### 8.2 The metric that matters most

> **UN-REPLAYABLE RATE, tracked by decision age.**

If 2% of decisions become un-replayable per year, then in ten years a fifth of the business's history cannot be defended — and nobody notices until the first dispute reaches back that far, at which point it is permanently unfixable.

Every other metric here reports on a system that is working. This one reports on the archive quietly rotting, and it is the only metric in this document that measures a loss you cannot recover.

Tracked **by cohort** — this year's decisions will all replay; the question is whether 2029's still do in 2036.

### 8.3 The full set

| Metric | Definition | Blocks? |
|---|---|---|
| **Un-replayable rate** | Manifest cannot resolve, by age cohort | Investigated at any non-zero value |
| **Replayability rate** | Complement of the above | — |
| **Fidelity rate** | Matching verdicts among replayable cases | **< 100% frozen-advisory blocks** |
| **Decision consistency** | Original-vs-replay stability, same version | **Any divergence blocks** |
| **Directional divergence** | Split into the four directions of §5.2, never summed | **Any safety direction blocks** |
| **Policy violation count** | Replayed decisions violating the policy set in force then | **Any non-zero blocks** |
| **Explanation completeness** | Fraction answering all eight questions | **Any decline blocks** |
| **Reconstruction divergence rate** | Fingerprint mismatches | Monitored — expected non-zero |
| **Rung-1–3 settlement rate** | 3C criterion 36, measured over the corpus | Monitored — a decline is strategic |
| **Regression rate by class** | Per release | Safety and hard block |
| **Replay latency / cost** | Per decision and per corpus run | Only against a 3A §5 ceiling |

### 8.4 Explanation completeness is a leading indicator

It falls before anything else breaks. Verdicts still match; confidence still matches; a field stopped being populated three releases ago.

Measured by **asking all eight questions on every replayed decision** and counting answerable ones — not by inspecting the schema, which would only prove the field exists, not that it is filled.

---

## 9 · Explainability Contracts

### 9.1 The four contracts

| # | Contract |
|---|---|
| **E1** | **Every explanation is derived from recorded facts.** No inference, no reconstruction, no defaults |
| **E2** | **An unanswerable question returns "the record does not contain this."** Never a plausible substitute |
| **E3** | **A model may rewrite an explanation for readability only.** It may not add, infer, soften, or supply a reason |
| **E4** | **The rendering is not the record.** It is disposable, never stored as the explanation, never replayed, never compared |

### 9.2 The boundary E3 draws

| A model may | A model may not |
|---|---|
| Translate to Kannada | Add a reason absent from the record |
| Reorder for readability | Soften a refusal into a suggestion |
| Summarise a long alternatives trace | Omit a blocking gate as "not important" |
| Convert structure into prose | Interpolate across gaps |

**Testable:** every fact in a rendered explanation must trace to a field in the record. A rendering containing an unsourced claim is a contract violation, and the check is mechanical, not a matter of judgement.

### 9.3 Why the rendering is discarded

If a rendering were stored as *the* explanation, then the explanation of a 2027 decision would be the output of a model that no longer exists, in a phrasing nobody can reproduce, with no way to verify it against the structured record it claimed to describe.

Store the structure. Render on demand. Discard the rendering. The structure is what survives ten years; no model output does.

---

## 10 · Future Compatibility

| Change | Replay redesign needed? | Why not |
|---|---|---|
| **New Brain version** | No | Brain version is a manifest field and the designated variable (§2.2) |
| **New LLM provider** | No | Rung 5 is advisory and replayed structurally; live-advisory mode compares providers without a schema change |
| **New policies** | No | Policies are versioned rows; §5.4 compares versions natively |
| **New industry** | No | Nothing in replay names a domain. New verticals supply registry, policy and template rows — Article II.8 |
| **New knowledge module** | No | Reconstruction is bitemporal and provenance-based; a new source adds a provenance identity, not a code path |
| **New capability** | No | Declared properties are versioned registry rows |
| **New decision category** | No | Adds a corpus stratum row, not an engine change |

### 10.1 What a schema change costs

The record schema is itself versioned in the manifest (§3.2). Replay must read **every historical schema version**, forever.

That is a real, permanent cost and it should be stated plainly: **every schema version ever written must remain readable.** The alternative — migrating old records forward — rewrites history, and a record that has been rewritten is not evidence.

So: additive changes only, old versions readable indefinitely, no destructive migrations of decision records. Ever.

### 10.2 The ten-year test

1. Decisions are explainable without replay
2. Replay is structurally incapable of executing
3. The packet is fingerprinted, not stored
4. Reconstruction divergence is distinguished from replay divergence
5. Referenced artifacts are versioned and never deleted
6. Un-replayable is a tracked archive state, not a Brain regression
7. Non-consultation is positively recorded
8. Explanations are derived, never generated
9. Every schema version stays readable
10. Safety regressions are not overridable

None of these mentions a model, a vendor, a database or a channel.

---

## 11 · Final Architecture

```
        ┌──────────────────────────────────────────────────────────┐
        │                    BUSINESS BRAIN                        │
        │      3A runtime · 3B planner · 3C decision engine        │
        └────────────────────────────┬─────────────────────────────┘
                                     │ emits at decision time (3C §6.1)
                                     ▼
        ╔══════════════════════════════════════════════════════════╗
        ║                    DECISION RECORD                       ║
        ║  immutable · versioned · PII-free                        ║
        ║  verdict · decisive rung · gate results · vector         ║
        ║  absence kinds · rejected alternatives                   ║
        ║  ARTIFACT MANIFEST §3  ·  PACKET FINGERPRINT §2.3        ║
        ╚═══════╤══════════════════════════════════════════╤═══════╝
                │                                          │
    ┌───────────▼────────────┐              ┌──────────────▼──────────────┐
    │  EXPLAINABILITY ENGINE │              │       REPLAY ENGINE         │
    │  ── sub-second lookup  │              │  ── batch · offline         │
    │  8 questions §4.1      │              │  ① manifest ② reconstruct   │
    │  derived, never        │              │  ③ verify ④ load Brain      │
    │  generated (E1–E4)     │              │  ⑤ replay → VERDICT. STOP.  │
    │                        │              │  ✗ no ⑩  ✗ no ⑪  ✗ no I/O  │
    │  needs NO manifest     │              │                             │
    │  needs NO knowledge    │              │  KNOWLEDGE STORE ──read──►  │
    │  ── survives           │              │  bitemporal, as_of frozen   │
    │     un-replayability   │              └──────────────┬──────────────┘
    └───────────┬────────────┘                             │
                │                          ┌───────────────▼───────────────┐
                │                          │      COMPARISON ENGINE        │
                │                          │  original·brain·provider      │
                │                          │  policy·knowledge   §5        │
                │                          │  verdict │ rationale │ conf   │
                │                          │  ✗ never compares text        │
                │                          └───────────────┬───────────────┘
                │                                          │
                │                          ┌───────────────▼───────────────┐
                │                          │   REGRESSION CLASSIFIER §6    │
                │                          │  safety·hard·explainability   │
                │                          │  soft·performance             │
                │                          │  (un-replayable → archive     │
                │                          │   defect, NOT a regression)   │
                │                          └───────────────┬───────────────┘
                ▼                                          ▼
        ┌──────────────────────────────────────────────────────────┐
        │  REPORTS                                                 │
        │  audit answer · release gate · blast radius · fragility   │
        │  cohort replayability · explanation completeness          │
        └──────────────────────────────────────────────────────────┘

        REPLAY CORPUS §7 ──► curated · stratified · grows by admission
                             golden·edge·failure·security·policy·approval
                             never pruned · never regenerated · no PII
```

**The fan-out at the record is C1.** Explainability does not depend on Replay, so a decision that stops replaying does not stop being explainable — and the oldest decisions, the ones most likely to be disputed, are exactly the ones where that matters.

---

## 12 · Acceptance Criteria

### 12.1 Invariants

| # | Invariant |
|---|---|
| **I1** | **The Replay Engine has no execution path** — it terminates at ⑨, structurally |
| **I2** | **Explainability requires neither the manifest nor the knowledge store** |
| **I3** | **The packet is fingerprinted, never stored** — no values, no PII |
| **I4** | **Reconstruction divergence is distinguished from replay divergence, always** |
| **I5** | **No artifact referenced by a retained decision may be deleted** |
| **I6** | **Un-replayable is a recorded archive state with a named missing artifact — never a Brain regression** |
| **I7** | **The `as_of` clock is frozen; system time is not readable in the verdict path** |
| **I8** | **Frozen-advisory replay is bit-stable across runs, hosts and orderings** |
| **I9** | **Frozen-advisory and live-advisory results are never merged** |
| **I10** | **Non-consultation of the model is positively recorded** |
| **I11** | **Explanations are derived from records; nothing is inferred or defaulted** |
| **I12** | **An unanswerable question returns "the record does not contain this"** |
| **I13** | **A model may re-render an explanation; it may never supply a fact** |
| **I14** | **Renderings are discarded, never stored as the explanation, never compared** |
| **I15** | **Text is never compared in any comparison mode** |
| **I16** | **Safety regressions are not overridable through the release process** |
| **I17** | **Verdict divergence is reported by direction, never as one rate** |
| **I18** | **Decision records are immutable; no schema migration ever rewrites one** |
| **I19** | **Every historical record schema version remains readable indefinitely** |
| **I20** | **The corpus is never pruned for age and never regenerated from production** |

### 12.2 Structural

| # | Criterion |
|---|---|
| 1 | Eight-step replay flow with fingerprint verification as a distinct step |
| 2 | Frozen / variable / never-present table complete |
| 3 | Two replay modes defined with distinct gating authority |
| 4 | Packet fingerprint fields enumerated; no field carries a value |
| 5 | Manifest lists every artifact class a verdict can depend on |
| 6 | Seven named rot modes, each addressed by the retention invariant |
| 7 | Eight explainability questions, each with its record source |
| 8 | Five comparison dimensions, each with its own acceptability rule |
| 9 | Five regression classes with explicit blocking status; un-replayable excluded from them |
| 10 | Six corpus strata plus a routine floor; seven admission triggers |
| 11 | Eleven metrics, with replayability and fidelity separated by the property they measure |
| 12 | Four explainability contracts, E3 mechanically testable |
| 13 | Seven determinism threats named and structurally excluded |
| 14 | Audit log, explanation and replay distinguished as three different capabilities |

### 12.3 Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 15 | Replay a decision that approved a payment | **No payment.** No authorization issued, no capability invoked |
| 16 | Attempt to reach ⑩ from the Replay Engine | **No such path exists** — not a disabled flag |
| 17 | Replay the same record twice on the same Brain | **Byte-identical verdict** |
| 18 | Replay across hosts and in different orders | Identical verdicts |
| 19 | A referenced fact was corrected after the decision | **Reconstruction divergence** — flagged, excluded from fidelity stats, not a regression |
| 20 | A referenced policy version was deleted | **UN-REPLAYABLE**, naming the missing policy; **archive defect, not a regression** |
| 21 | A referenced capability was retired | **Still replays** — retired ≠ deleted |
| 22 | Explain a decision whose manifest no longer resolves | **Fully explainable** — all eight questions |
| 23 | Ask "why wasn't AI consulted?" on a rung-3 decision | Names the decisive rung and the template version |
| 24 | Ask a question the record cannot answer | **"The record does not contain this"** — not a plausible answer |
| 25 | Ask a model to explain a decision directly | **Refused** — E1 |
| 26 | Rendered explanation contains an unsourced claim | **Contract violation**, detected mechanically |
| 27 | Swap the model provider, frozen-advisory | **Zero divergence** — provider is not an input in this mode |
| 28 | Swap the model provider, live-advisory | Divergence permitted at rung 5 only; **never a new approval** |
| 29 | New Brain flips REJECT → APPROVE | **Safety regression. Release blocked. Not overridable** |
| 30 | New Brain flips APPROVE → REJECT with a named policy version | Attributed; permitted |
| 31 | New Brain changes a verdict with nothing attributable | **Hard regression. Blocked** |
| 32 | Same verdict, decisive rung changed | **Rationale divergence** — investigated, not auto-passed |
| 33 | A decision stops answering question 5 | **Explainability regression. Blocked** |
| 34 | Amend a discount policy | Divergence **confined to discount decisions**; anything else is a blast-radius defect |
| 35 | Replay across knowledge snapshots | Fragile decisions identified; **not counted as Brain regressions** |
| 36 | Cosmetic change to response wording | **Zero regressions** — text is never compared |
| 37 | Read a record written under an older schema | **Readable**, no migration |
| 38 | Attempt to delete a referenced artifact | **Refused** — retention invariant |
| 39 | Attempt to prune old corpus cases | **Refused** |
| 40 | Inspect the corpus for PII | **None** — fingerprints only |

### 12.4 The criteria that matter most

| # | Criterion | Why |
|---|---|---|
| **41** | **Track un-replayable rate by decision-age cohort** | The only metric measuring an unrecoverable loss. Everything else reports on a system that is working; this one reports on the archive rotting, years before the dispute that exposes it |
| **42** | **Replay a decision made today, unchanged, after a Brain upgrade, a provider swap, a policy amendment and a schema version bump** | The compound test. Each is easy alone; together they are the actual ten-year condition |
| **43** | **Explanation completeness never declines, release over release** | The leading indicator — it falls while every other metric still looks green |
| **44** | **Zero safety regressions reach production, ever** | The one number with no acceptable non-zero value |

**Criterion 41 is the acceptance test for this slice.** Criteria 42–44 prove the machinery works. Only 41 measures whether the thing this architecture exists to protect — the ability to account for a decision years later — is still there.

### 12.5 Non-regression

| # | Criterion |
|---|---|
| 45 | Zero application code touched |
| 46 | Phase 1C suite green (249 tests) |
| 47 | Compatible with 2A–2I, 3A, 3B, 3C; no frozen concept modified |
| 48 | Replay vocabulary distinct from 2H sufficiency and 3C decision vocabularies |
| 49 | **Live production probe:** unsigned → 403; a real message replies |

---

## 13 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Explainability is independent of Replay** — a decision that stops replaying does not stop being explainable
2. **The Replay Engine is structurally incapable of executing** — no path to ⑩ or ⑪, not a flag
3. **The packet is fingerprinted, not stored** — reconstruction plus hash comparison, no PII retained
4. **Reconstruction divergence ≠ replay divergence** — never summed, never reported as one number
5. **No artifact referenced by a retained decision may ever be deleted** — retirement is not removal
6. **Un-replayable is an archive defect, not a Brain regression** — tracked as the headline metric, never blocking a release
7. **Two replay modes**, frozen-advisory gating releases, live-advisory never gating alone
8. **Non-consultation is positively recorded** — silence is not an answer
9. **Explanations are derived; "the record does not contain this" is a valid output**
10. **Explainability regression is its own blocking class**
11. **Safety regressions are not overridable** — the route is a versioned policy amendment
12. **The corpus is curated and stratified**, never pruned, never regenerated
13. **Every historical schema version stays readable** — no migration rewrites a decision

Items 3 and 5 carry the real cost. Fingerprinting means replay can prove a decision was faithful but can never reprint the customer's actual credit limit from 2027 — which is the correct trade, because the alternative is a permanent PII archive that grows forever and becomes a liability the moment it leaks. Item 5 means the registry accumulates rows that nothing will ever invoke again.

Both will look like overhead in year two and like the only reason anything is defensible in year eight.

The measure of this layer is not how much it records. It is that in 2036, someone can ask why a decision went the way it did, get an answer assembled from what was actually known at the time, and verify that answer independently — without trusting anyone's memory, and without a model that no longer exists.
