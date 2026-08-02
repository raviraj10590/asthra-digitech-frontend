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

### Slice 1B — Policy Gate · Tool Registry · Invocation logging
**Status: 📋 IDD WRITTEN — awaiting approval** → `docs/idd/1B-policy-tool-layer.md`

### Slice 1C — BrainRequest/BrainResponse · WhatsApp adapter
**Status: ⬜ NOT STARTED**

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
