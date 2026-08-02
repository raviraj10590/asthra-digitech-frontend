# BIC v1.0 — Progress Tracker

Governed by `docs/BUSINESS-INTELLIGENCE-CORE-v1.0.md` (FROZEN).
A slice is COMPLETE only when every Quality Gate item passes.

---

## Phase 1 — Foundation

### Slice 1A — Migration tooling · Knowledge schema · Registries
**Status: ✅ COMPLETE** (engineering) — owner-approved 2026-08-02

Engineering completion and deployment readiness are tracked separately. The
three outstanding operational tasks do not change 1A's implementation, so they
sit in the Deployment Checklist below rather than blocking the slice.

| Quality Gate | Status |
|---|---|
| Migrations applied | ✅ 4/4, `local ✓ / remote ✓` |
| BIC tables created | ✅ 10 tables |
| Structural verification | ✅ 10/10 PASS |
| Behavioural verification | ✅ PASS (incl. 3 negative tests) |
| No behaviour change | ✅ zero application code touched |
| Zero additional AI calls | ✅ |
| No public API changes | ✅ |
| Fully reversible | ✅ `git revert`; tables additive & unread |
| Documentation updated | ✅ ADR 0001, ADR 0002, RUNBOOK, this tracker |
| Bot operational | ✅ webhook 403 check |

**Verification results** (2026-08-02, via Management API — see ADR 0002):

```
tables            10/10  PASS      trigger_present     1/1  PASS
entity_types       6/6   PASS      confidence_check    1/1  PASS
fact_categories    6/6   PASS      cardinality_idx     2/2  PASS
relation_types     7/7   PASS      rls_enabled       10/10  PASS
predicate_defs   14/14   PASS      no_open_item        0/0  PASS
```

Behavioural:
```
trigger derives 'single' for budget ................ PASS
trigger derives 'multi'  for team_member ........... PASS
multi predicate accumulates (team_count = 2) ....... PASS   ← review finding C2
customer_claim confidence > 0.5 REJECTED ........... PASS   ← Article II.6
unregistered predicate REJECTED .................... PASS
duplicate single-cardinality REJECTED .............. PASS
post-test row counts all zero (no residue) ......... PASS
```

---

## Deployment Checklist (operational — not slice implementation)

Owner-only tasks. They do not alter any slice's code.

| # | Task | Blocks | Status |
|---|---|---|---|
| D1 | Run `#aitest` from WhatsApp — confirm DeepSeek live | nothing (verification) | ⬜ |
| D2 | Rotate the exposed DeepSeek API key | nothing (security hygiene) | ⬜ |
| D3 | Add `SUPABASE_SERVICE_ROLE_KEY` to bot Vercel env | **1B deploy** | ⬜ |

⚠️ **D3 blocks 1B's deployment, not its design.** BIC tables are deny-by-default
RLS, so no code can read or write them until the service-role key exists. 1B can
be designed and built against it; it cannot go to production without it.

---

### Slice 1B — Security Boundary
**Status: ✅ ACCEPTED & CLOSED** — owner-accepted 2026-08-02

🔒 **This slice is closed. Do not reopen it to add handlers, imports, or build
config.** Anything that touches `webhook.py`, imports `bic/`, or wires a handler
is Slice 1C work by definition.

**Scope (owner-fixed):** 1B solves exactly one problem — the security boundary.

| Scope item | Status |
|---|---|
| Policy Layer | ✅ `bic/policy.py` |
| Tool Registry | ✅ `bic/tools.py` |
| Tool Invocation Logging | ✅ `bic/tools.py::_audit` |
| Authorization | ✅ `policy.may_invoke` |
| Characterization tests | ✅ 20 tests, mutation-verified |
| Feature flag | ✅ `BIC_POLICY_ENABLED` (defined, consumed in 1C) |

**Explicitly NOT in 1B** (deferred to 1C, owner directive 2026-08-02):
`BrainRequest` · `BrainResponse` · Webhook Adapter · routing refactor ·
conversation-flow changes · **tool handler wiring**.

> A merge of 1B and 1C was proposed and **rejected**. Rationale recorded because
> the temptation will recur: pulling future work forward because it is
> convenient makes review, rollback, testing and debugging all harder. Each
> phase solves exactly one problem.
> 1A = Database Foundation · 1B = Security Boundary · 1C = Request Architecture
> · 1D = Knowledge Integration

**Tests:** 45 total, offline, green (25 policy/registry + 20 characterization).

**`api/webhook.py` unchanged.** Production behaviour is byte-identical.

**⚠️ Known state — the layer is NOT running in production.** Vercel's Python
builder bundles what the entrypoint imports; nothing imports `bic/`, so it ships
in git but not in the Lambda. This is *correct* for 1B (no integration), but it
means:
- 1B is verified by unit tests, not by production execution
- **1C prerequisite:** confirm `bic/` is bundled the first time an `api/*.py`
  module imports it. If Vercel does not pick it up automatically, add
  `includeFiles` to `vercel.json`. Deliberately not pre-configured here — it
  cannot be verified without an import, and unverifiable config is a liability.

**Registry rows exist for 5 tools; handlers are intentionally unregistered.**
1B delivers the enforcement mechanism (proven against mock handlers, including
"registry row without handler → explicit failure"). Connecting real handlers is
integration work and belongs to 1C.

### Slice 1C — Request Architecture
**Status: 🚧 IN PROGRESS**

| Item | Status |
|---|---|
| BrainRequest / BrainResponse | ✅ `bic/contract.py` |
| Brain runtime | ✅ `bic/brain.py` |
| **Bundling verified in production** | ✅ see below |
| Webhook Adapter | ⬜ |
| Feature-flag migration | ⬜ |
| Old vs new comparison | ⬜ |

**✅ Prerequisite 2 RESOLVED — `bic/` bundles correctly.**
Confirmed in production, not assumed: the deployed Lambda logs
`BIC: package import OK`. One line was required — `sys.path.insert` of the repo
root, because the function's directory is `api/` and `bic/` is its sibling, not
its child. **No `includeFiles` needed.** The import is guarded, so a future
bundling failure degrades to a log line and `BIC_AVAILABLE=False`, never a 500
on a live customer webhook.

Contains: `BrainRequest` · `BrainResponse` · Webhook Adapter · routing
migration · feature-flag rollout · old-vs-new behaviour comparison
(response text, memory updates, tool execution, CRM updates, latency).

**Prerequisites:**
1. D3 — `SUPABASE_SERVICE_ROLE_KEY` in bot Vercel env. Once the new path is
   live every invocation writes to `bic_tool_invocations`; without the key those
   writes fail and the rollout runs blind, with no data for the behaviour
   comparison.
2. Confirm `bic/` is bundled by Vercel on first import (see 1B note).
3. Wire the 5 approved tool handlers to existing business functions —
   **wrap, never rewrite**.

### Slice 1D — Knowledge backfill · Retention · Golden set · Docs
**Status: ⬜ NOT STARTED**

---

## Long-lead items (start early, block later phases)

| Item | Blocks | Status |
|---|---|---|
| WhatsApp message template approval (Meta) | Phase 3 proactive Digital COO | ⬜ **not started — days-to-weeks lead time** |
| Retention job wired to scheduler | Article II.7 data growth | ⬜ functions exist, not invoked |

---

## Known deviations from plan

- **1A scope** additionally produced ADR 0002 (verification method), unplanned
  but necessary once the SQL editor proved unusable.
- **Two SQL defects** were caught during 1A and fixed before completion:
  `symmetric` is a Postgres reserved word; `extensions.gin_trgm_ops` fails to
  resolve when the extension already exists in another schema. Both recorded in
  ADR 0001.
