# Decision Replay Mode — Specification

**Governs:** BIC v1.0 Slice 1C · **Supersedes:** "Shadow Mode" · **See:** ADR 0004

---

## Purpose

Prove the new pipeline would make the SAME decisions as the legacy pipeline,
without touching production state.

The new pipeline **predicts**. It does not execute.

---

## Absolute prohibitions

Replay MUST NEVER:

| Forbidden | Why |
|---|---|
| Call an AI provider | Cost, quota, and output is non-deterministic |
| Write to any database | Production state must be unchanged |
| Write CRM data | Duplicate rows in a live customer database |
| Update memory | Second pass would read the first's output |
| Send a WhatsApp message | Customer would receive duplicates |
| Execute a tool with side effects | Same as above |
| Trigger notifications | Duplicate owner alerts |

Replay MAY perform **read-only** lookups required to reach a decision (e.g.
resolving a role). Reads are permitted; every form of mutation is not.

## How the prohibition is enforced

**Structurally, not by discipline.** A flow in replay mode is handed
`Recorder.stub()` callables in place of the real sender and writers, so it
holds **no reference** to anything that can mutate state. It cannot write even
if a future edit tries to.

`bic/replay.py` is additionally asserted by test to contain no I/O capability
at all — no `requests`, no supabase client, no webhook import.

---

## What is compared

| Compared | Not compared |
|---|---|
| Route selected (owner / client) | ❌ Generated reply text |
| Policy result (allow / deny + reason) | ❌ Actual side effects (there are none) |
| Tool selection | ❌ Latency of the AI provider |
| Tool arguments | |
| Intended side effects (recorded) | |
| Assembled prompt fingerprint | |

### Why generated text is excluded

LLM output is **non-deterministic**. Two calls with an identical prompt
routinely differ in wording. Comparing generated text would report a
difference on essentially every message even when both pipelines are correct.
A harness that always fails gets ignored, then switched off — worse than no
harness, because it manufactures confidence while it is still trusted.

We compare the **inputs** to the model instead. Identical prompt + identical
route means the pipelines agree; any remaining difference is the model's
non-determinism, not a migration defect.

---

## ⚠️ Current limitation — the comparison is presently VACUOUS

**Status: replay is deployed but its client-path result is not yet meaningful.**

Root cause: the two role lookups use different credentials.

| Path | Reads `bot_roles` with | Works today? |
|---|---|---|
| `webhook.get_role()` | `SUPABASE_KEY` (anon) | ✅ yes |
| `bic.policy.resolve_principal()` | `SUPABASE_SERVICE_ROLE_KEY` via `bic.db` | ❌ **key not set (D3)** |

Consequence, per sender type:

| Sender | Legacy result | Replay result | Verdict |
|---|---|---|---|
| Bootstrap owner | OWNER (env, no DB) | OWNER (env, no DB) | ✅ real match |
| Number in `bot_roles` as STAFF | STAFF | CLIENT (lookup failed → degraded) | ✅ real DIFF, correctly flagged |
| Unknown number | CLIENT | CLIENT (**because the lookup failed**) | ⚠️ **FALSE MATCH** |

The unknown-number case — by far the most common — agrees **by accident**, not
by verification. Both sides land on CLIENT for different reasons.

**Therefore `BIC_REPLAY_MATCH` on client traffic is currently not evidence.**
It must not be counted toward acceptance until the credential issue is resolved
(see ADR 0005).

`Principal.degraded` is set on the failing path, so degraded samples are
identifiable and must be **excluded** from any acceptance tally.

---

## Acceptance evidence required before `BIC_POLICY_ENABLED=true`

1. **Replay accuracy** — N ≥ 20 non-degraded samples with zero `BIC_REPLAY_DIFF`,
   covering owner, staff and unknown senders.
2. **Latency** — added replay overhead measured and bounded (target < 50 ms p95).
3. **Zero regressions** — full characterization suite green.
4. **Rollback** — flag flip verified to restore the legacy path with no deploy.
5. **Feature flag** — verified fail-safe across unset/false/true/garbage.
6. **Routing correctness** — owner, staff and client senders each provably
   reach the intended pipeline.

Evidence is recorded in `docs/PROGRESS.md` before the flag is flipped.

---

## Log format

```
BIC_REPLAY_MATCH route=<owner|client> role=<ROLE>
BIC_REPLAY_DIFF  sender=<last4> [field: legacy=… replay=…]
```

Replay failures are swallowed and logged; they must never affect a live turn.
