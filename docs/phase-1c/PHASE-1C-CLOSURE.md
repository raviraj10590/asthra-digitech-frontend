# Phase 1C — Closure Document

**Status:** 🔒 **FROZEN** · 2026-08-03
**Frozen at:** `0cb4ec8` · production serving `0cb4ec8`
**Change policy:** no further implementation except a **critical production bug**.
Anything else is Phase 2 or later.

---

## Snapshot

| | |
|---|---|
| Tests | **226**, 12 files, offline, order-independent |
| `bic/` package | 1,061 lines, 9 modules |
| Migrations | 36 applied |
| `api/webhook.py` | 2,958 lines |
| Registered tools | 13 (12 dispatchable) |
| Mutations verified | 30+ across the slice, all caught |

---

## 1 · Completed Implementation

Built, tested, deployed. No outstanding work.

| Component | Where |
|---|---|
| **Policy layer** — fail-closed authorization, frozen `Principal`, CLIENT allowlist | `bic/policy.py` |
| **Tool Registry** — private handler map, `invoke()` as sole entry point, audit on every path including denials | `bic/tools.py` |
| **Identity resolution** — one resolver, one cache, one query; bootstrap owners survive total DB outage | `bic/identity.py` |
| **Brain runtime** — transport-independent, flows injected, never imports application code | `bic/brain.py` |
| **Request contract** — `BrainRequest` / `BrainResponse` | `bic/contract.py` |
| **WhatsApp adapter** — translation only, no logic, no policy | `adapters/whatsapp.py` |
| **Decision Replay** — compares decisions, never generated text | `bic/replay.py` |
| **Durable replay store** — PII-free, 30-day retention, saturation skip | migrations + `webhook._bic_persist_replay` |
| **Webhook authentication** — measure-then-enforce, fail-closed when unconfigured | `webhook.do_POST` |
| **Registry circuit breaker** — 30 s back-off on failed loads | `bic/tools.py` |
| **Audit retention** — daily rollup into `bic_tool_stats_daily`, wired to existing cron | `api/digest.py` |
| **Function timeout** — explicit 30 s | `vercel.json` |
| **No-bypass invariant** — AST-derived, cannot be evaded by naming | `tests/test_registry_no_bypass.py` |
| **HTTP integration suite** — 24 tests executing the real entry point | `tests/test_http_integration.py` |

**Structural invariant, re-verified at freeze:** 12 business tools · 13 handlers · **0 bypass violations**.

---

## 2 · Production-Verified Items

Every row below has real production evidence, not inference.

| # | Item | Evidence |
|---|---|---|
| 1 | Webhook rejects unsigned requests | `POST` unsigned → **403**; bad signature → **403** |
| 2 | Webhook accepts genuine Meta traffic | Real message **12:58:24 UTC**, 86 s after enforcement went live, processed and replied |
| 3 | `META_APP_SECRET` correct | 22 consecutive real messages, `signature_valid: true`, clean `false→true` boundary at deploy |
| 4 | `WEBHOOK_AUTH_ENFORCE=true` | Vercel env (visible) + behavioural 403s |
| 5 | Router preserves signature | 221 bytes in → 221 bytes out (re-serialisation would be 241); header forwarded |
| 6 | Tool Registry is the execution path | 8 tools, one `bic_tool_invocations` row each, zero bypasses |
| 7 | Tier-4 privilege ops audited | `add_role` / `remove_role` with role, channel, target, latency, actor |
| 8 | Argument allowlist works | `add_role` recorded `{role, target}`; free-text `label` correctly excluded |
| 9 | Replay produces genuine evidence | 48 records, **0 diffs**, **0 degraded**, 0.061 ms avg, 0.099 ms max |
| 10 | Retention executes | Digest cron returned `ok:true`; rollup ran; rows intact |
| 11 | **Rollback works** | `0cb4ec8`→`44d892e` in **< 2 s**; recovery in **1 s** |
| 12 | Rollback causes no outage | **183/183 availability samples (100.00%)**, zero 5xx |
| 13 | Rollback causes no side effects | **0** tool invocations during the drill |
| 14 | Function timeout accepted | Deploy succeeded; Vercel rejects invalid `builds[].config` |

**Rollback procedure — verified, not assumed:**
Vercel → Deployments → target → Instant Rollback → Confirm. Roll forward via Promote.
Environment variables come from the *original build*, so a rollback also reverts env-driven behaviour.

**Newly documented during the drill:** promoting forward produced ~8 s of mixed edge state (some nodes old, some new) before settling. Zero downtime, but enforcement is briefly inconsistent during any roll-forward.

---

## 3 · Environment-Limited Validation

> ### BLOCKED – Production Environment
>
> **These are not implementation failures.** Every item below is built, unit-tested,
> mutation-verified and deployed. Each requires a production condition that cannot
> be created from the engineering environment.

| Item | Blocking condition | Evidence that will satisfy it |
|---|---|---|
| `chat_resume` execution | Requires `#start` sent from an owner WhatsApp number | `bic_tool_invocations` row, `tool='chat_resume'` |
| `memory_clear` execution | Requires `#forget` from an owner number | row, `tool='memory_clear'` |
| `send_brochure` execution | Requires a message from a **non-owner** phone | row with `role='CLIENT'` |
| `crm_capture_self` execution | Same — client-path only | row with `role='CLIENT'` |
| CLIENT replay evidence | Same | `bic_replay_records` with `role='CLIENT'` + a second `decision_hash` |
| STAFF replay evidence | Requires a third number granted STAFF that then messages | records with `role='STAFF'` |

**Why the engineering environment cannot satisfy these:**

1. **No WhatsApp send capability** — messages must originate from a real handset.
2. **Both owner numbers are bootstrap OWNERs.** `918884448141` and `918861369951` resolve to OWNER before any database lookup, so neither can act as a CLIENT. A third phone is structurally required.
3. **Signature enforcement is now live** — synthetic requests can no longer be injected. This is the control working correctly; it also closes the last workaround.

Item 3 is worth stating plainly: **closing the Critical security finding removed the only mechanism by which these could have been forced.** That is the correct trade.

---

## 4 · Deferred Validation

Known, recorded, deliberately out of 1C scope.

| ID | Item | Reason | Target |
|---|---|---|---|
| **D1** | `crm_sync_lead` has no dispatch site | Registered with a handler, but no command or code path reaches it. The client path uses `crm_capture_self` by design (the C-1 fix). Executing it needs a new dispatch site = new feature | Phase 2 — either give it a command or retire the tool. **Owner decision required** |
| **D2** | M-7 — `do_POST` returns 200 on internal error | Meta never retries genuine failures; dropped messages are invisible | Phase 2 |
| **D3** | Raw JSON leaked to owner | Observed 12:58:24: reply began ` ```json {"reply": "Done, OWNER…`. Pre-existing, outside 1C scope | Phase 2 — **highest-priority deferred defect** |
| **D4** | `webhook.py` at 2,958 lines | Maintainability drag; no correctness impact | Phase 2+ |
| **D5** | `bic_tool_defs` has no `tenant_id` | Article II.5 readiness gap; single tenant today | Phase 2 knowledge work |
| **D6** | Cross-module test pollution | Contained by an order-independent guard; not individually fixed | Phase 2 |
| **D7** | `policy.resolve_principal` + `_role_cache` dead | Marked `@deprecated`; removal needs a slice permitted to touch closed 1B | Phase 2 |
| **D8** | S5 / S6 — client path through the Brain, split removed | ADR 0003's bridge remains | Phase 2 |
| **D9** | `919999999999` paused 24 h | `#start` never sent; not a real number | Expires on its own |
| **D10** | DeepSeek API key rotation | Key was exposed in a transcript | **Security hygiene — do soon** |

---

## Lessons carried into Phase 2

Recorded because they changed outcomes here, not as platitudes.

1. **Verify the running system, not the artefact.** Three code reviews passed a webhook that accepted unsigned requests. One `curl` found it. *Every future phase must include a live probe of the deployed system.*
2. **Measure before enforcing.** The first auth fix would have caused an outage — Meta delivers via a router nobody had documented. Observe mode turned a guess into 22 measurements. *Any change to a request-path control ships in observe mode first.*
3. **A green suite is evidence about the suite.** The no-bypass test was green while the two functions that can mint an OWNER bypassed the gate — they were named `_tool_*` and the pattern matched `tool_*`. *Derive invariant sets from source; never hand-maintain them.*
4. **Commit before mutating.** The mutation harness destroyed uncommitted work twice, once producing a commit whose message described a fix it did not contain. *Verify a clean tree before any destructive restore.*
5. **Tests must match behaviour, not prose.** An assertion matched a tool name inside a *comment* and passed after the call was deleted.
6. **Plan environment-dependent validation up front.** Six criteria are blocked on a third phone number. That was foreseeable at design time and would have cost nothing to arrange early.

---

## Freeze declaration

Phase 1C is **FROZEN** at `0cb4ec8`.

**Not accepted** — six criteria remain BLOCKED – Production Environment and one (D1) needs an owner decision. **No criterion failed for implementation reasons.**

The system moved from *unsafe* to *incompletely verified* during this phase. That distinction is the phase's substantive outcome: the Critical authentication finding is closed with production evidence, both tier-4 privilege operations are audited, and rollback is measured rather than hypothetical.
