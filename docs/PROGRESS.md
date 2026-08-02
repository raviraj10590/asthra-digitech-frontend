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
| Webhook Adapter | ✅ `adapters/whatsapp.py` |
| Adapter wiring (OWNER path) | ✅ behind fail-safe flag |
| Adapter wiring (CLIENT path) | ⬜ **required — see migration plan** |
| Feature-flag routing | ✅ fail-safe, defaults FALSE |
| Decision Replay Mode | ✅ deployed, structured logging, **no longer vacuous** |
| Old vs new comparison | 🟡 unblocked — awaiting live samples |
| Duplicate role resolution removed | ✅ ADR 0005 IMPLEMENTED |
| Latency instrumentation | ✅ measurement only |

---

#### Incremental migration plan (owner review point 1 & 6)

The OWNER/CLIENT split is a **temporary migration state, not the target**.
Recorded here with an explicit removal plan so it cannot become permanent.

| Stage | State | Exit condition |
|---|---|---|
| **S1** ✅ | OWNER via Brain (flag-gated); CLIENT legacy | flag fail-safe verified |
| **S2** ✅ | Role resolution unified (ADR 0005) | one resolver, one cache — done |
| **S3** 🟡 | Replay produces genuine evidence | ≥20 non-degraded samples, 0 diffs |
| **S4** ⬜ | `BIC_POLICY_ENABLED=true` for OWNER | replies verified identical |
| **S5** ⬜ | CLIENT path wrapped and routed through Brain | characterization green |
| **S6** ⬜ | Split removed — one pipeline | ADR 0003 superseded |

**1C is complete only at S6.** Stages S1–S5 are reversible by flag or
`git revert`. If S5 proves unsafe, the split must be removed by moving CLIENT
forward — never by making the split permanent.

**Removal plan for ADR 0003's empty-response bridge:** at S5 the client
handlers gain injected collaborators so they return a populated
`BrainResponse`; `render()` then becomes the single output path and ADR 0003 is
marked superseded.

---

#### Replay status — genuine, with one honest caveat

`bic.identity` is now the ONE resolver used by both the legacy path and the
Brain (ADR 0005). Both perform the same real lookup with the same cache, so a
`BIC_REPLAY_DIFF` can only mean a real logic difference.

⚠️ **Route comparison is now tautological** — both sides call the same function,
so route can never disagree. That is the intended end state, but it means route
matches are **not independent evidence**. Genuine divergence signal arrives with
tool selection at S5.

Degraded samples (`"degraded": true`) are excluded from any tally.

Full specification: `docs/REPLAY-SPEC.md`.

**Tests:** 104 offline, green.

**Client-flow bridge is TEMPORARY** — see ADR 0003. The client flow will send
its own messages and return `BrainResponse(text="")`. Accepted for 1C only
(behaviour preservation > purity). No future phase may depend on it.

---

#### Decision Replay Mode — design settled (ADR 0004)

"Shadow Mode" (execute both pipelines) was **rejected**: neither path is a pure
function, so a second execution would duplicate CRM rows, double AI spend, and
send the customer the same message twice.

**Replaced by Decision Replay Mode.** The legacy path remains the only
production path. The new pipeline **predicts what it would do and does not
execute**. No sends, no writes, no mutations — intended operations are recorded
instead:

```
legacy:  send_brochure(client)
replay:  record {tool: "send_brochure", arguments: {...}}
```

Safety is **structural**: in replay mode the flow is injected with recorders in
place of the real sender/writers, so it holds no reference to anything that can
mutate state. It cannot write even if a future edit tries to.

**Compare:** route · selected tools · intended side effects · assembled prompt.
**Do not compare generated reply text** — LLM output is non-deterministic, so
identical-and-correct pipelines would still differ on every message and the
harness would be abandoned as noise. Compare the *inputs* to the model; the AI
call is stubbed in replay mode (zero added cost). Rationale in ADR 0004.

**Acceptance:** enable `BIC_POLICY_ENABLED` once both pipelines consistently
produce equivalent DECISIONS across a representative sample.

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
1. ⬜ D3 — `SUPABASE_SERVICE_ROLE_KEY` in bot Vercel env. Once the new path is
   live every invocation writes to `bic_tool_invocations`; without the key those
   writes fail and the rollout runs blind, with no data for the behaviour
   comparison.
2. ✅ ~~Confirm `bic/` is bundled by Vercel~~ — **RESOLVED**, verified in
   production (`BIC: package import OK`).
3. ⬜ Wrap the 5 approved tool handlers around existing business functions —
   **wrap, never rewrite**.

#### 🔴 BLOCKER — replay evidence is not durable

**Requirement (owner-corrected):**
> Replay evidence must survive process restarts and log expiration.

Deliberately stated as a requirement, not an implementation. `SUPABASE_SERVICE_ROLE_KEY`
is *one enabler*, not the blocker itself.

**What happened:** owner testing on 2026-08-02 produced 140 messages and real
replay records. All were **unrecoverable within hours** — they were written with
`print()` to stdout, and the platform retains logs ~1 hour. `bic_tool_invocations`
holds 0 rows because its writes need a credential that is unset, so the audit
fallback also lands in the same expiring bucket.

**An evidence channel that expires is not evidence.** Criteria 4 and 5 are
structurally unsatisfiable until this is fixed — a re-test today would evaporate
identically.

**Acceptance checklist for 1C (owner-defined):**

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Adapter wired | 🟡 OWNER only | S5 completes it |
| 2 | Feature flag operational | ✅ | verified unset/false/true/TRUE/1/off/garbage |
| 3 | Decision Replay implemented | ✅ | `bic/replay.py` + structured logging |
| 4 | Replay accuracy evidence | ❌ | **evidence not durable** — see blocker |
| 5 | Latency verified in production | ❌ | same root cause |
| 6 | Zero regressions | ✅ | 104 tests green, characterization + cache mutation-verified |
| 7 | Rollback verified | 🟡 | flag logic verified; not yet exercised in production |
| 8 | Routing correctness | 🟡 | owner proven; client unproven |
| 9 | No customer-visible change | ✅ | flag unset ⇒ legacy path serves everyone |
| 10 | No additional AI calls | ✅ | replay makes none |
| 11 | Documentation updated | ✅ | REPLAY-SPEC, ADR 0003/0004/0005, this tracker |
| 12 | Progress tracker updated | ✅ | this file |

**1C is NOT accepted — approximately 65% complete.** Criteria 4, 5 await
production samples; 1, 7, 8 partial pending S4-S6.

**Target architecture** (unchanged; ADR 0003 records the one temporary deviation):
```
Webhook → Adapter → BrainRequest → Brain → Policy → Tool Registry
        → Business Function → BrainResponse → Adapter → WhatsApp
```
Every flow should eventually return a `BrainResponse`. No flow should
permanently send messages directly.

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
