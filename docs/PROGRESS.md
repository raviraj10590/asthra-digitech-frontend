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
| D1 | Run `#aitest` from WhatsApp — confirm DeepSeek live | nothing (verification) | ✅ 2026-08-03, 7.3 s |
| D2 | Rotate the exposed DeepSeek API key | nothing (security hygiene) | ⬜ |
| D3 | Add `SUPABASE_SERVICE_ROLE_KEY` to bot Vercel env | **1B deploy** | ✅ audit + replay writes landing |

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
| **S3** ✅ | Replay produces genuine evidence | durable table; 15 samples, 0 diffs |
| **S4** ✅ | `BIC_POLICY_ENABLED=true` for OWNER | replies verified identical |
| **S4.5** ✅ | **Tool Registry bypass closed** | owner tools verified live, 7/7 audited |
| **S4.6** ✅ | **Engineering review findings resolved** | 2 Critical + 4 High closed, 21 mutations caught |
| **S4.7** 🟡 | **Closure validation** | replay + rollback + no-regression proven offline; privileged tools await one live command |
| **S4.8** 🟡 | **Audit hardening** | 8 of 10 free tasks done; 2 need live traffic |
| **S5** ⬜ | CLIENT path wrapped and routed through Brain | characterization green |
| **S6** ⬜ | Split removed — one pipeline | ADR 0003 superseded |

**1C is complete only at S6.** Stages S1–S5 are reversible by flag or
`git revert`. If S5 proves unsafe, the split must be removed by moving CLIENT
forward — never by making the split permanent.

---

#### S4.5 — Closing the Tool Registry bypass

**The defect.** After S4 the owner path served through the Brain, five handlers
were registered, and `bic_tool_invocations` held **0 rows**. Tools were running;
none of them ran *through the registry*. Registration had been mistaken for
execution. Eleven dispatch sites still called `tool_*()` directly:

| Site | Count | Path |
|---|---|---|
| `try_owner_command` — `#` commands | 7 | owner |
| `handle_owner_text` — NL fallbacks | 4 | owner |
| `run_client_pipeline` — `send_brochure` | 1 | client |
| `upsert_lead` — `sync_lead_to_crm` | 1 | client (side effect) |

Every one bypassed the Policy Gate. The security boundary built in 1B was
**real but unreached** — a boundary nothing is required to pass through is
decoration.

**The fix.** One dispatcher, `webhook.run_tool(sender, code, _fallback, **args)`:

```
run_tool → identity.resolve → tools.invoke → policy.may_invoke
         → handler → business function → audit
```

Four tools were added to make full routing possible: `aitest`, `memory_show`,
`memory_clear` (all `min_role=STAFF`, matching the fact that
`try_owner_command` applies **no** role gate today, so STAFF preserves current
behaviour exactly), plus `crm_capture_self`.

**Why `crm_capture_self` exists.** `upsert_lead` runs inside the CLIENT pipeline
and must record the conversing customer's details. Routing that through
`crm_sync_lead` (STAFF) would be denied and would silently break lead capture.
The wrong fix is to mark `crm_sync_lead` customer-safe. Two operations share one
implementation but have different exposure:

| Tool | Role | Meaning |
|---|---|---|
| `crm_sync_lead` | STAFF | sync an arbitrary lead — administrative |
| `crm_capture_self` | CLIENT | record MY OWN details — data capture |

`crm_capture_self` is safe by construction: its handler always uses
`principal.sender_id`, authenticated by the transport. A customer cannot name
another subject, and can only persist data they already supplied by talking —
no capability they did not already have. **No change to `bic/policy.py` was
required, so closed Slice 1B stays closed and no ACP is owed.**

**Two subtleties worth recording:**

1. **`#status` is a composite COMMAND, not a composite tool.** It was first
   built as a `status` tool that invoked `leads_today` and `crm_list_clients`.
   That is wrong: `tools.invoke()` calls `db.reset_query_count()` on a single
   thread-local, so a nested invocation resets the outer counter and the outer
   audit row under-reports `db_queries`. An audit table with silently wrong
   numbers is worse than one with none.

   Making `invoke()` nest-safe means editing `bic/tools.py` — **closed Slice
   1B, which requires an ACP**. Composing at the dispatch site
   (`webhook.compose_status`) requires neither, and is arguably the better
   design anyway: each constituent tool is gated by policy on its own terms,
   and joining their output is presentation, which belongs to the transport
   layer. The `status` registry row is deactivated, not deleted, so the
   decision survives in the registry.

   **Standing rule, test-enforced:** no registered handler may call
   `run_tool()`. Composite tools need an ACP first.
2. **Denial never falls back to the direct call.** The `_fallback` argument
   exists for the `bic` package failing to import, and for nothing else.
   Falling back on a policy denial would restore the exact bypass being closed.

**Enforcement.** `tests/test_registry_no_bypass.py` parses `webhook.py` and
fails if any business tool is called outside a registered handler. There are
**zero exceptions**: `tool_status` was the only one, it became dead code when
`#status` moved to `compose_status()`, and it was deleted rather than kept as a
fallback — dead code that calls business functions directly is exactly the trap
the check exists to prevent.

Verified by mutation (a check that cannot fail is not a check):

| Mutation | Result |
|---|---|
| owner dispatch → direct call | ✅ caught |
| client brochure → direct call | ✅ caught |
| CRM capture → direct call | ✅ caught |
| denial falls back to direct call | ✅ caught (2 tests) |
| `compose_status` reverted to direct calls | ✅ caught |
| a handler nests an invocation | ✅ caught (2 tests) |

**Cost.** The audit write in `tools.invoke()` is synchronous, so each invocation
adds one Supabase round-trip. `#status` now costs two.

**Production evidence — 2026-08-03, six owner commands:**

```
#leads   → leads_today                        142 ms
#clients → crm_list_clients                   421 ms
#status  → leads_today + crm_list_clients   50 + 348 ms   ← composite, 2 rows
#roles   → roles_list                          53 ms
#memory  → memory_show                         87 ms
#aitest  → aitest                            7347 ms
```

7 invocations, 7 audited, 0 failures, 0 denials, every tool inside its declared
latency. `bic_tool_invocations` went 0 → 7: the registry is now on the execution
path, not beside it.

Two audit-quality defects were found in this data and fixed rather than
accepted:

- **`aitest` expectation was 2.4× optimistic** (declared 3000 ms, measured
  7347 ms). It passed only because the SLOW check uses a 3× threshold. A
  declared expectation that a *healthy* run nearly breaches is a future false
  alarm, not a baseline. Corrected to 8000 ms — declarations are corrected from
  measurement, never the reverse.
- **`db_queries` reads 0 on every row.** Accurate but misleading: `bic/db.py`
  counts queries made *through it*, and every handler wraps a legacy function
  that calls Supabase with `requests` directly. Documented on the column so
  nobody later reads 0 as "no database work".
Acceptable against a WhatsApp reply budget, but it is the reason S4.5 carries a
production latency check rather than only offline tests. If it proves too slow,
the fix is batching the audit write — not skipping it.

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

**Tests:** 218 offline, green.

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
| 0 | **Every tool executes via the registry** | 🟡 | owner path proven live (7/7); client tools untested in production |
| 1 | Adapter wired | 🟡 OWNER only | S5 completes it |
| 2 | Feature flag operational | ✅ | verified unset/false/true/TRUE/1/off/garbage |
| 3 | Decision Replay implemented | ✅ | `bic/replay.py` + structured logging |
| 4 | Replay accuracy evidence | ✅ | 23 samples, 0 diffs, 0 degraded, 1 decision hash — bar was 20 |
| 5 | Latency verified in production | ✅ | replay mean 0.063 ms; all 7 tools inside declared expectation |
| 6 | Zero regressions | ✅ | 133 tests green; no-bypass + characterization + cache mutation-verified |
| 7 | Rollback verified | 🟡 | flag logic verified; not yet exercised in production |
| 8 | Routing correctness | 🟡 | owner proven; client unproven |
| 9 | No customer-visible change | ✅ | flag unset ⇒ legacy path serves everyone |
| 10 | No additional AI calls | ✅ | replay makes none |
| 11 | Documentation updated | ✅ | REPLAY-SPEC, ADR 0003/0004/0005, this tracker |
| 12 | Progress tracker updated | ✅ | this file |

**1C is NOT accepted — approximately 90% complete.** The registry invariant is
satisfied for the owner path with production evidence. Remaining: live CLIENT
tool evidence, then S5 (client path through the Brain) and S6 (split removed).

**Owner-defined acceptance for the bypass fix (2026-08-03):**

| # | Test | Status |
|---|---|---|
| 1 | `bic_tool_invocations` increases per tool execution | ✅ 0 → 7, one row per execution |
| 2 | Authorization still works | 🟡 7/7 OWNER allowed; **no live non-owner sample** |
| 3 | Existing responses byte-identical | ✅ handlers wrap, never reimplement; owner reported no change |
| 4 | Zero additional AI calls | ✅ `test_no_ai_call_in_the_dispatch_path` |
| 5 | Characterization tests green | ✅ 186/186 |
| 6 | Registry failure fails safely | ✅ empty registry ⇒ deny-all; import failure or flag off ⇒ legacy |
| 7 | Policy denial prevents execution | ✅ mutation-verified, no fallback on denial |
| 8 | Latency within target | ✅ every tool inside declared expectation |

**Honest gap on criteria 2 and 3.** Both owner phones are bootstrap OWNERs, so
no live sample exercises a CLIENT principal. `send_brochure` and
`crm_capture_self` are wired, registered and unit-tested, but have **not
executed in production**. Until an organic customer conversation lands, the
client half of the invariant rests on tests, not evidence. This is a real gap,
recorded rather than rounded up.

**Target architecture** (unchanged; ADR 0003 records the one temporary deviation):
```
Webhook → Adapter → BrainRequest → Brain → Policy → Tool Registry
        → Business Function → BrainResponse → Adapter → WhatsApp
```
Every flow should eventually return a `BrainResponse`. No flow should
permanently send messages directly.

#### S4.6 — Engineering review (2026-08-03)

A strict 20-point review was run against the architecture documents *after*
S4.5 reported success. It found **2 Critical and 4 High** defects in code that
had 134 green, mutation-verified tests.

**The Critical finding is the lesson.** `_tool_add_role` — the function that can
mint an OWNER — bypassed the Policy Gate entirely, produced no audit row, and
was guarded only by an inline string compare evaluated at *staging* time. The
no-bypass test missed it because the test enumerated functions named `tool_*`
and these are named `_tool_*`. **A leading underscore exempted the two most
dangerous functions in the file, and the suite was green the whole time.**

The invariant set is now DERIVED from the source (`_?tool_(?!h_)[a-z_]+`)
rather than hand-listed, so a function cannot opt out by being named a certain
way, and nobody has to remember to add it.

| ID | Finding | Fix |
|---|---|---|
| C1 | `add_role`/`remove_role` bypass the registry | routed; `min_role=OWNER`, `risk_tier=4`, `audit_level=full` |
| C2 | `#confirm` never re-checks authorization | re-resolved at confirm time, on the legacy path too |
| H1 | failed brochure recorded and reported as sent | `invoke_tool()` returns `(ok, text)`; caller branches |
| H2 | `timeout_seconds` decorative | threaded into the `requests` calls |
| H3 | `config.POLICY_ENABLED` dead, inverted, `"false" != "off"` | deleted; one flag reader |
| H4 | `#stop`/`#start` ungated, unaudited | `chat_pause`/`chat_resume`, OWNER |
| M1 | `INTERNAL_ROLES` defined twice, MANAGER divergent | one definition; MANAGER not routed (1C = byte-identical) |
| M3 | `audit_level='full'` tools recorded no args | allowlist entries added |
| M5 | outage presented as authorization failure | distinguished in `invoke_tool` |
| L1 | audit fallback printed full phone to stdout | truncated to last 4 |
| L5 | `run_tool` return not coerced | `_coerce_tool_text` at the boundary |

**Tests: 186 green (forward and reverse module order). 21 mutations, all caught.**

**Two defects were found while writing the closure-validation suite — both in
the verification apparatus, not the production fix:**

1. **The C1 invariant regex shipped narrowed.** The mutation harness used in
   `185bc64` restored `api/` and `bic/` but not `tests/`, so the mutation
   *"narrow the pattern back to exclude `_tool_*`"* was left applied and
   committed. The routing fix itself was real — an independent AST scan showed
   0 violations throughout — but **the test locking it was not in force**, and
   the acceptance report that said "15 mutations caught" was reporting on a
   harness that had corrupted its own subject. The harness now snapshots via
   `git checkout -- .`, so restore is total by construction rather than by an
   enumerated list of paths.
2. **`identity.configure()` leaked across test modules.** It installs
   module-level state and several suites never restored it; an OWNER-returning
   stub made three characterization tests report that an unknown number
   resolved as OWNER. Every class now snapshots and restores, and a guard
   drives `setUp`/`tearDown` directly rather than asserting global state
   (which would be order-dependent, i.e. flaky).

Both are recorded because they are the same lesson as C1 itself: **a green
suite is evidence about the suite, not about the system.**

**ADRs written where behaviour actually changed:** 0006 (brochure failure is
reported — the single deliberate behaviour change in 1C) and 0007 (MANAGER is a
rank, not a pipeline). No ADR for C1/C2/H2/H3/H4/M3/M5/L1/L5: those restore
intended behaviour rather than change it.

---

#### S4.8 — Independent audit hardening (2026-08-03)

An independent audit **probed production rather than reading code** and found a
Critical defect three prior reviews had missed: webhook signature verification
was disabled (`META_APP_SECRET` unset), so the `from` field feeding the entire
identity chain was unauthenticated. See ADR 0008.

| Task | Status | Evidence |
|---|---|---|
| 1 · Webhook auth (observe mode) | ✅ **deployed** | 24 HTTP tests, 7 mutations caught. Router proven to preserve body + signature. Enforcement awaits `META_APP_SECRET` |
| 2 · Execute every handler once | ⬜ **blocked** | Needs live WhatsApp traffic — 6 of 13 handlers still unproven |
| 3 · Replay OWNER/STAFF/CLIENT | ⬜ **blocked** | Needs live traffic; 32 records span 1 role |
| 4 · Explicit maxDuration | ✅ | 30 s via `builds[].config`; 4 tests |
| 5 · Registry circuit breaker | ✅ | 5 tests, 2 mutations caught |
| 6 · Enable retention | ✅ | RPC verified against production; 4 tests |
| 7 · HTTP integration tests | ✅ | 12 routing/flag/legacy/brain tests |
| 8 · Message-ID dedup | ⛔ **cannot be done** | See below |
| 9 · Mark dead code | ✅ | Marked, not removed — reasons recorded |
| 10 · Documentation | ✅ | ADR 0008, this section |

**Task 8 — why message-ID deduplication cannot be implemented yet.**
`whatsapp_messages` has exactly five columns: `id`, `phone`, `role`, `content`,
`created_at`. There is **no column to hold a WhatsApp message id**, and adding
one is a schema change, which this work explicitly excludes.

The one alternative within the constraints — encoding `WAMID::<id>` as a system
marker in `content`, the channel `BOT_PAUSED` and `PENDING_CONFIRM` already use
— was rejected: it adds a write to every inbound message on the hot path, and
storing an identifier inside a free-text column is the kind of shortcut that
becomes permanent.

The existing text-plus-60-seconds dedup therefore stands. Its known defect is
unchanged and recorded: **a customer who legitimately sends the same text twice
within a minute is silently ignored.** `message_id` is already threaded through
the adapter and `BrainRequest`, so the consuming side is ready; only the storage
column is missing.

**Two process defects were found during this work, both in the verification
apparatus rather than the product:**

1. **The mutation harness destroyed uncommitted work — twice.** It restores with
   `git checkout -- .`, which reverts to HEAD. Run while holding uncommitted
   changes, it silently discarded the fix under test. The first occurrence
   shipped a narrowed invariant regex; the second produced a commit whose
   message described an auth fix it did not contain, caught only because the new
   tests failed. **Rule now: commit before mutating, and verify the tree is
   clean first.**
2. **A test matched prose instead of behaviour.** `assertIn("bic_rollup_tool_invocations", src)`
   passed when the call was removed but a comment naming it remained. Tightened
   to assert the RPC URL. Found by mutation, not by review.

---

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
