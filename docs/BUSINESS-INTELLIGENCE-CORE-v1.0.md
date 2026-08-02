# Business Intelligence Core v1.0 — Constitution

**Status:** FROZEN · Approved 2026-08-02
**Authority:** Raviraj (Owner, Asthra DigiTech)
**Supersedes:** all prior architecture discussion

> This is the most stable document in the project. Everything else evolves around it.
> Changing anything in Article II or Article VIII requires an Architecture Change
> Proposal (ACP) and explicit approval. Small improvements are welcome; architectural
> rewrites are not.

---

## Article I — Purpose

The Business Intelligence Core (BIC) is the permanent intelligence layer of Asthra
DigiTech. Interfaces — WhatsApp, web, mobile, voice, email, admin panel — are
**replaceable adapters**. The BIC is not.

WhatsApp is an interface. The BIC is the brain.

---

## Article II — Invariants

*These may never be violated. Violating one is a constitutional change, not a code change.*

1. **Identity is resolved deterministically, server-side, before any model runs.**
   Never inferred from message content.
2. **Security never depends on model behaviour.** Policy is code and SQL.
3. **Nothing executes inline.** Every side-effecting action enters `action_queue`
   with a risk tier and an idempotency key.
4. **The AI proposes; the state machine decides.** Workflow transitions are
   validated by the database, not by prompt compliance.
5. **Tenancy is `tenant_id`. Access is `visibility` + `acl_roles`.**
   Never scoped by author.
6. **Customer-sourced facts are capped at confidence 0.5** and never auto-promote
   to business knowledge.
7. **Raw data is a cache; derived knowledge is the asset.** Every raw table has a
   retention window.
8. **New verticals are INSERTs, never ALTER TABLEs.**
9. **The business operates at Tier 2 with all AI disabled.**
10. **Every irreversible action is auditable back to its originating message.**

---

## Article III — Runtime

One orchestrator loop. Bounded: **≤4 iterations, ≤20s wall clock, ≤6 tool calls.**
On breach: return the best draft so far and flag the owner.

Intent, planning and reasoning are **behaviours of the loop**, not separate services.
Deterministic components (Policy, Tools, Workflow, Observation) sit outside it.

**AI budget: 1 call per message + 1 per night.**

Rejected by design: separate Intent / Planning / Decision / Strategy engines. The loop
subsumes them; standalone they cost ~4x the calls and add 4x the failure points with no
behavioural gain.

---

## Article IV — Data Model

**Core:** `memory_entities`, `memory_facts`, `memory_edges`

**Registries** (extensibility without migrations): `entity_types`, `fact_categories`,
`predicate_defs`, `relation_types`, `tool_defs`, `workflow_defs`

**Operational:** `observations`, `goals`, `tasks`, `workflow_runs`, `action_queue`,
`tool_invocations`, `outcomes`

Every core table carries: `tenant_id` (partition key), `domain`, `visibility`,
`created_at`, `updated_at`.
`memory_facts` reserves `embedding vector(768) NULL` — unused at launch, so enabling
semantic retrieval later is a backfill, not a migration.

**Cardinality:** `predicate_defs.cardinality` is `single` or `multi`.
- single → `unique(entity_id, predicate) where status='active'` (new value supersedes)
- multi  → `unique(entity_id, predicate, value_key) where status='active'` (accumulates)

**Retention:** tool_invocations 30d → daily rollup · whatsapp_messages 90d ·
superseded facts 180d → archive · resolved observations 60d → rollup.

**Deliberately excluded:**
- `ai_workers` — deferred until 2+ workers exist. One row of config does not earn a
  table, a migration and a join.
- `open_item` fact category — `tasks` is the single home for actionable work. Two
  homes guarantee drift.

---

## Article V — Retrieval

Retrieve **knowledge, not conversations.**

Candidates from lexical + entity-direct + pinned (importance 5), expanded one graph
hop, then scored:

```
score = 0.35·relevance
      + 0.25·(importance/5)
      + 0.20·confidence
      + 0.10·recency        (exp decay, 60d half-life)
      + 0.10·graph_proximity (1.0 direct, 0.6 one hop)
```

Filters: `confidence >= 0.35`, `status = 'active'`, max 2 facts per entity
(diversity), ~600 token budget.

Confidence and age are surfaced to the model so it can hedge on stale facts rather
than assert them.

**Scope is a WHERE clause, never a prompt instruction.**

A small recent-turn window (~6) rides along for conversational flow only — it is not
the knowledge source.

---

## Article VI — Security

Three planes:

1. **Identity** — role resolved from verified sender, server-side.
2. **Authorization** — every tool declares `min_role` and risk tier. Customer tool set
   is an allowlist, never a denylist.
3. **Data** — `tenant_id` + `visibility` enforced in SQL; outbound redaction as
   defence in depth.

**Risk tiers and approval authority:**

| Tier | Kind | Approver |
|------|------|----------|
| 1-2 | inform / reversible | auto-execute, logged |
| 3 | customer-visible | any STAFF |
| 4 | financial / contractual | MANAGER+ |
| 5 | irreversible / legal | OWNER only, always |

Prompt injection is structurally defeated: role is resolved before the model runs and
grants are enforced outside it. A message claiming "you are now the owner" changes
nothing.

---

## Article VII — Degradation Tiers

The business must keep operating with AI fully off.

| Tier | State | Behaviour |
|------|-------|-----------|
| 0 | Healthy | Loop + tools + knowledge |
| 1 | Degraded | Single-shot reply + deterministic retrieval; no multi-step |
| 2 | **AI down** | **Zero AI.** Menu, FAQ, lead capture, contact routing, human handoff |
| 3 | Dark | Queue inbound, notify owner via approved template |

Tier 2 is a hard requirement. Customers must still reach the business and leave a lead
when every model provider is unavailable.

Quality drift is detected by a golden-set eval run **nightly** (not only in CI),
tracked as a time series, alerting on regression.

---

## Article VIII — Extensibility

| To add | Do this | Never |
|--------|---------|-------|
| Interface | New adapter → `BrainRequest`/`BrainResponse` | Touch the core |
| Tool | Row in `tool_defs` + handler | Bypass the registry |
| Vertical | Rows in registries + `workflow_defs` | `ALTER TABLE` |
| Fact type | Row in `predicate_defs` | Change a CHECK constraint |

**Channel-agnostic contract:**

```
BrainRequest  { channel, sender_id, role, text, attachments, locale, thread_id }
BrainResponse { text, actions[], attachments[], confidence, needs_approval }
```

---

## Article IX — Change Control

**Requires an ACP + approval:** any change to Article II, the partition key
(`tenant_id`), the security model, or the AI-call budget.

**Does not require approval:** new tools, verticals, workflows, predicates, adapters,
prompt tuning, bug fixes, performance work.

That asymmetry is the entire point of this document.

**ACP format:** what is being attempted · which invariant blocks it · why the
constitution is insufficient · blast radius · migration cost · rollback plan ·
alternatives considered.

---

## Article X — Roadmap

**Phase 1 — Foundation** (zero AI calls; safe to build regardless of traffic)
- `BrainRequest`/`BrainResponse` contract + WhatsApp adapter refactor
- Policy + Tool layer (merged) with `tool_invocations` logging
- Knowledge Engine with registry tables + backfill from current memory note
- Retention/rollup jobs
- Golden-set eval harness
- Forward-only migrations + one-page runbook
- WhatsApp template approval — **start day 1, long lead time**

**Phase 2 — Intelligence** (module split FIRST)
- Orchestrator loop with hard caps
- Fact extraction inside the existing reply call (+0 AI calls)
- Nightly dedup / supersede / confidence reconciliation
- Deterministic observation collectors

**Phase 3 — Autonomy**
- Workflow state machine
- `action_queue` + `#approve` / `#reject`
- Morning Brief + Night Reflection (2 crons, 1 AI call/night)
- `outcomes` recording → retrieval priors

Nothing beyond Phase 3 until Phase 3 is stable.

---

## Article XI — Honest Limitations

Recorded so future readers inherit the context, not just the conclusions.

1. At approval time this system served **~0 client conversations/day** (zero since
   2026-07-24). Phase 1 is correct regardless — deterministic, zero AI calls,
   permanent foundation. **Phase 2's value is measured in conversations; revisit
   before building it.**
2. OpenAI was at `insufficient_quota`; the system ran entirely on Gemini fallback.
   Tier-2 degradation is not hypothetical.
3. The largest 10-year risk is **not technical** — it is one operator maintaining a
   13-table platform. Every simplification in this document exists to reduce that load.
4. Observation is **measurement, not inference.** Collectors are SQL/HTTP checks.
   Only the nightly digest uses AI. Violating this is how the cost model breaks.

---

*End of constitution. No production code until Phase 1 is approved to begin.*
