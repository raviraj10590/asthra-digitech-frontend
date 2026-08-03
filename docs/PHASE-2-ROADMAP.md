# Phase 2 — Business Knowledge Layer · Implementation Roadmap

**Status:** Planning · No implementation · 2026-08-03
**Governed by:** BIC v1.0 Constitution (frozen) · Business Knowledge Architecture (frozen)
**Predecessor:** Phase 1C frozen at `0cb4ec8`

---

## Scope discipline

The Knowledge Architecture describes a platform for 100+ industries. **Phase 2 builds almost none of it, deliberately.**

The architecture's value is that unbuilt modules cost nothing — module 40 is as cheap to add in 2030 as today. So Phase 2 builds the **thin vertical slice** that proves the architecture works end to end, plus the two things that cannot be backfilled.

**Phase 2 delivers 3 knowledge modules, not 15.** Anything else is Phase 3.

### Ordering principle

Slices are ordered by **what cannot be recovered later**, not by what is most interesting:

1. **Cannot be backfilled** — outcome history, decision history. Every day not capturing is a day permanently lost.
2. **Everything joins on it** — identity resolution. Get it wrong early and every downstream number is wrong.
3. **Everything else.**

---

## Slice map

| Slice | Objective | Backfillable? |
|---|---|---|
| **2A** | Semantic Registry — the vocabulary | n/a (foundation) |
| **2B** | Organizational Intelligence — decision + execution capture | ❌ **never** |
| **2C** | Party — identity resolution | ⚠️ painful |
| **2D** | Communication — WhatsApp history as knowledge | ✅ (we retain raw) |
| **2E** | Knowledge Capabilities — QUERY + EXPLAIN | ✅ |
| **2F** | Business Context Packet + Sufficiency Gate | ✅ |
| **2G** | Outcome capture — closing the learning loop | ❌ **never** |

**2B and 2G are the compounding assets.** Everything else can be rebuilt from source systems; a decision you never recorded is gone.

---

# Slice 2A — Semantic Registry

### Objective
Establish the vocabulary layer: what an entity type, predicate and relation type *are*, and how they are versioned. No instance data, no behaviour change.

### Deliverables
- Entity type, predicate and relation-type registries with explicit versioning
- Predicate **volatility class** (drives freshness scoring later)
- Relation types mapped to the six frozen semantic classes
- Verification report: structural + behavioural, per ADR 0002 method
- **Immutable-meaning rule enforced at the registry level**

### Acceptance criteria
1. Registries applied and structurally verified against production
2. A predicate's meaning cannot be changed — only superseded by a new predicate (enforced, not documented)
3. Every registry row carries a version
4. Zero application code touched · zero behaviour change · zero AI calls
5. Fully reversible by `git revert` (tables additive and unread)
6. **Live probe:** bot still serves; unsigned → 403; signed traffic replies

### Rollback
`git revert` + redeploy. Tables are additive and read by nothing.

### Risks
| Risk | Mitigation |
|---|---|
| Registry becomes an engineer-only artefact, blocking the 100-domain thesis | Track **days-to-onboard-a-vertical** from this slice onward |
| Predicate meanings drift | Immutability enforced in the registry, not by convention |
| Over-modelling before a consumer exists | Only predicates 2C/2D actually need |

### Documentation
IDD-2A · ADR: predicate immutability · verification report · roadmap update

---

# Slice 2B — Organizational Intelligence (capture)

### Objective
Record what the Brain **decided** and what was **executed**. Not what happened afterwards — that is 2G.

> **This is the highest-priority slice in Phase 2.** Nothing consumes it for months. It is still first, because it is the only asset a competitor cannot buy, copy, or replicate with a better model — and every day not recording is permanently lost.

### Deliverables
- Decision record: proposal, classification, principal, evidence reference, policy version, verdict, **alternatives considered with rejection reasons**
- Execution record: capability, idempotency key, result, latency, cost
- Immutability: append-only, annotatable, never editable
- Retention + rollup, wired to the **existing** cron (Hobby caps at 2)
- PII policy identical to `bic_replay_records`: no prompts, no message content, no phone numbers

### Acceptance criteria
1. Every owner-path decision produces exactly one decision record
2. Every tool execution produces exactly one execution record, linked not embedded
3. `accountable_human` is **never null** — autonomous decisions inherit it
4. Records are replayable **without the world** (self-contained)
5. Zero PII — asserted by test, verified against production rows
6. Write failure never affects a live conversation
7. **Live probe:** one real owner turn produces one decision record

### Rollback
Feature-flagged write, defaulting **off**. Flag off → no records, zero behaviour change. Table drop is a single migration; nothing reads it yet.

### Risks
| Risk | Mitigation |
|---|---|
| Hot-path write cost (the M4 lesson) | Same saturation-skip pattern; measure before enabling broadly |
| Surveillance drift — recording *people* rather than *decisions* | Subjects restricted to decisions and outcomes. Enforced by schema |
| Records too thin to be useful in 2 years | Include rejected alternatives from day one — the expensive field, and the one that cannot be reconstructed |
| Nothing consumes it, so it silently breaks | Add a read path in 2E even if trivial |

### Documentation
IDD-2B · ADR: OI as a peer substrate, not a layer · ADR: rejected-alternatives capture · PII conformance report

---

# Slice 2C — Party (identity resolution)

### Objective
Answer "is this phone, this GST number and this walk-in the same party?" Everything downstream joins on this.

> The hardest slice in Phase 2. Budget more for it than any other.

### Deliverables
- Party knowledge object with the frozen envelope
- External reference set (phone, email, GSTIN, CRM id) with per-reference confidence
- Resolution state machine: `UNRESOLVED → PROVISIONAL → RESOLVED | DISPUTED | MERGED`
- **Reversible merge** with full pre-merge state retained
- Auto-merge only above a high threshold **and** only on tier-0/1 evidence
- Human confirmation queue for everything else

### Acceptance criteria
1. Merge is demonstrably reversible — **an actual merge performed and undone in production**
2. Auto-merge never fires on tier ≥ 2 evidence
3. `DISPUTED` is surfaced, never silently resolved
4. Resolution is deterministic and replayable
5. No existing behaviour changes — Party is written but not yet read by the bot
6. **Live probe:** a real WhatsApp sender resolves to a Party with correct external refs

### Rollback
Write-only slice behind a flag; nothing reads Party yet. Flag off → inert. Merges are reversible by design, so even a bad merge is recoverable.

### Risks
| Risk | Severity | Mitigation |
|---|---|---|
| **False merge** — two customers blended, near-silent, corrupts every downstream figure | **Existential** | Reversible merges; high auto-merge threshold; sampled audits; `DISPUTED` first-class |
| False split (duplicates) | Low | Self-correcting — someone notices |
| Resolution logic drifts | Medium | Decision-replay the resolution, same pattern as 1C |

### Documentation
IDD-2C · **ADR: reversible merge (mandatory)** · ADR: resolution thresholds · merge/unmerge runbook

---

# Slice 2D — Communication

### Objective
Turn WhatsApp conversation history into structured knowledge: who said what, when, and what was committed.

### Deliverables
- Communication objects linked to Party (2C)
- Assertions extracted with provenance — **customer-sourced facts capped at 0.5 confidence** (Article II.6)
- Bitemporal fields: `valid_from/to` distinct from `observed_at`
- Derived-vs-asserted marked explicitly; derived carries its formula and inputs

### Acceptance criteria
1. Every assertion carries source, provenance tier, confidence and lineage
2. No customer-sourced fact exceeds 0.5 confidence — enforced, tested, verified in production rows
3. Bitemporality present from the first row (cannot be retrofitted)
4. Raw message retained — extraction can be re-run with a better parser
5. Zero behaviour change: written, not yet read
6. **Live probe:** a real conversation produces assertions with correct provenance

### Rollback
Flag-gated write. Off → inert. Extraction is idempotent and re-runnable.

### Risks
| Risk | Mitigation |
|---|---|
| Extraction quality poor at low volume | Retain raw; treat extraction as replaceable |
| Confidence inflation | Provenance-capped, never model-asserted |
| Cost on hot path | Extract **asynchronously**, never in the request path |

### Documentation
IDD-2D · ADR: bitemporal from day one · ADR: async extraction · provenance conformance report

---

# Slice 2E — Knowledge Capabilities (QUERY + EXPLAIN)

### Objective
Expose knowledge through the **existing** Capability Plane. `bic_tool_defs` is already V0 of the Capability Registry — extend it, do not build a parallel system.

### Deliverables
- Knowledge capabilities registered alongside business tools, same policy gate, same audit
- `EXPLAIN` as a **first-class callable capability**, not a log
- Read path for OI (proves 2B is alive)
- Freshness and provenance surfaced in every result

### Acceptance criteria
1. Knowledge is reachable **only** through the Capability Plane — no direct reads, AST-enforced like the 1C no-bypass invariant
2. Every capability declares min_role, risk tier, freshness bound, degradation behaviour
3. `EXPLAIN` returns source, chain, competing claims and the confidence calculation for any fact
4. Every invocation audited, denials included
5. **Live probe:** an owner command returns knowledge, with an audit row and a working `EXPLAIN`

### Rollback
Capabilities are registry rows — deactivate with one UPDATE, no deploy. Same lever proven in 1C.

### Risks
| Risk | Mitigation |
|---|---|
| A parallel access path appears "temporarily" | Derived AST invariant from day one — the C-1 lesson |
| `EXPLAIN` rots because nothing calls it | Make it user-facing, not a debug tool |
| Registry bloat | Reuse the existing table; no new registry |

### Documentation
IDD-2E · ADR: capability plane reuse · no-bypass invariant extension

---

# Slice 2F — Business Context Packet + Sufficiency Gate

### Objective
Assemble a typed, auditable, replayable packet — and give the system the right to refuse.

> **The differentiating slice.** A system that reliably says *"I can't answer this, and here is exactly what is missing"* is worth more to a business than one that guesses fluently.

### Deliverables
- Business Context Packet: slots, facts with provenance, conflicts, sufficiency verdict, policy scope, retrieval trace
- Deterministic conflict-resolution ladder — unresolvable conflicts **surfaced, never silently picked**
- Sufficiency Gate: coverage · freshness · conflicts · confidence-vs-risk-tier
- Actionable refusal naming the specific gaps

### Acceptance criteria
1. The packet is self-contained and replayable **without live systems**
2. The same packet produces the same decision across model providers — **tested against two model families**
3. Refusals name specific missing slots and staleness, never a bare "I don't know"
4. Conflicts are never silently resolved
5. Zero AI calls in assembly — the LLM sees only the finished packet
6. **Live probe:** a real query produces a packet; an artificially staled source produces a specific refusal

### Rollback
Flag-gated. Off → the 1C path serves unchanged. Both paths run in shadow with decision comparison before the flag flips — the pattern proven in 1C.

### Risks
| Risk | Mitigation |
|---|---|
| Packet bloat: more context, worse answers, higher cost | Measure **accuracy against packet size**, not size alone |
| Sufficiency thresholds get lowered until nothing is blocked | Threshold changes are themselves recorded decisions; drift monitored |
| Refusals annoy users into disabling the gate | Make refusals *useful* — they must tell someone what to fix |

### Documentation
IDD-2F · ADR: packet as a typed artefact · ADR: conflict ladder · **multi-provider equivalence report**

---

# Slice 2G — Outcome capture

### Objective
Record what actually happened after a decision — closing the loop that makes the system compound.

### Deliverables
- Outcome records linked to decisions, arriving **asynchronously** — hours to months later
- Explicit `UNKNOWN` on timeout, treated as a valid learnable signal
- Decision → Execution → Outcome chain queryable end to end
- Calibration foundation: predicted confidence vs observed outcome

### Acceptance criteria
1. Outcomes link to decisions without mutating them (records stay immutable)
2. Outcome arrival is decoupled from the turn — proven with a multi-day gap
3. `UNKNOWN` recorded on timeout, not silently dropped
4. At least one complete decision → execution → outcome chain in production
5. Calibration can be computed, even if the sample is small

### Rollback
Additive and read by nothing. Drop is one migration.

### Risks
| Risk | Mitigation |
|---|---|
| Outcomes never arrive; the loop stays open | Explicit timeout → `UNKNOWN`; monitor arrival rate |
| Execution result mistaken for outcome — the classic error | Separate record types, separate clocks, enforced by schema |
| Hindsight contamination | Decision records reference the evidence packet as it was, never a reconstruction |

### Documentation
IDD-2G · ADR: outcome ≠ execution · calibration methodology

---

## Cross-cutting requirements — every slice

Derived from what actually went wrong in Phase 1C.

| # | Requirement |
|---|---|
| 1 | **Live production probe in the acceptance criteria.** Not optional. Three reviews missed an open webhook because all three read artefacts |
| 2 | **Request-path controls ship in observe mode first.** Enforce only on measured evidence |
| 3 | **Invariant sets derived from source, never hand-maintained.** A leading underscore once exempted the two most dangerous functions in the codebase |
| 4 | **Mutation-test every new invariant.** A test that cannot fail manufactures confidence |
| 5 | **Clean tree before any destructive verification.** The harness destroyed uncommitted work twice |
| 6 | **Environment-dependent validation identified at IDD time**, with the required production conditions arranged before the slice starts |
| 7 | **`tenant_id` on every new table.** Cannot be retrofitted |
| 8 | **Provenance and bitemporality from the first row.** Cannot be retrofitted |
| 9 | **Meaningless identifiers.** No business meaning in any key |
| 10 | **Tier 2 operation preserved** — the business runs with AI entirely off |

---

## Phase 2 exit criteria

Phase 2 is complete when **all** hold:

1. Three knowledge modules live: Party, Communication, and one business domain
2. A real question is answered from the Knowledge Layer, through the Capability Plane, with a Business Context Packet and a working `EXPLAIN`
3. A real question is **correctly refused** with specific named gaps
4. One complete decision → execution → outcome chain exists in production
5. A merge has been performed and reversed in production
6. The same packet yields the same decision across two model providers
7. Zero regressions in the Phase 1C surface — 226 tests still green, no-bypass invariant intact
8. Every slice has a live production probe on record

---

## Explicitly NOT in Phase 2

Recorded because each will be proposed and each is Phase 3+:

Learning Layer · Knowledge Packages · additional knowledge modules (Finance, People, Work, Supplier, Catalog, Policy, Analytics) · multi-tenancy activation · predictive scoring · autonomous action · vertical packs · `webhook.py` decomposition · the Decision Engine spec's L0–L5 risk model

**The Decision Engine specification is written and frozen. It is not implemented in Phase 2.**

---

## Deferred Phase 1C items folded into Phase 2

| ID | Item | Slice |
|---|---|---|
| D1 | `crm_sync_lead` has no dispatch site — **needs owner decision** | before 2A |
| D3 | Raw JSON leaked to owner — **highest-priority deferred defect** | before 2A |
| D2 | `do_POST` returns 200 on internal error | 2A |
| D5 | `bic_tool_defs` missing `tenant_id` | 2A |
| D7 | Dead `resolve_principal` / `_role_cache` removal | 2A (first slice permitted to touch 1B) |
| D8 | S5/S6 — client path through the Brain | 2F |
| D10 | DeepSeek key rotation | **immediate, not a slice** |

---

## Recommended sequencing

```
NOW      D10 (rotate key) · D3 (JSON leak) · D1 decision
         └─ small, unblocking, and D3 is customer-visible today

2A → 2B  foundation, then the thing that cannot be backfilled
         └─ 2B is the highest-value slice in Phase 2

2C       identity — the hardest; budget accordingly

2D → 2E  first real knowledge, first real read path

2F       the differentiator: packet + the right to refuse

2G       close the loop
```

**One measurement to track from 2A onward:** *days to onboard a vertical we have never seen.* If it is under a week without an engineer touching the core, the architecture is real. If not, we have built a bespoke system with a plugin folder — and it is far better to learn that at vertical #2 than at vertical #40.
