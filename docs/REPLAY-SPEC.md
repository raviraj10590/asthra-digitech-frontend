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

## Identity resolution — ONE canonical resolver

Both pipelines resolve identity through **`bic.identity.resolve()`**
(ADR 0005). One resolver, one cache, one lookup query, one bootstrap list.

```
                    ┌──────────────────────┐
webhook.get_role() ─┤                      │
                    │  bic.identity        │──► injected fetcher ──► bot_roles
bic.brain.handle() ─┤  (THE cache)         │      (anon key)
                    └──────────────────────┘
```

This is what makes replay meaningful. A disagreement can now only indicate a
**real logic difference** — never two lookup implementations differing.

| Sender | Legacy | Replay | Verdict |
|---|---|---|---|
| Bootstrap owner | OWNER (env, no lookup) | OWNER (same path) | ✅ genuine |
| Staff in `bot_roles` | STAFF | STAFF (same lookup) | ✅ genuine |
| Unknown number | CLIENT (real lookup, no row) | CLIENT (same lookup) | ✅ genuine |
| DB unavailable | CLIENT, degraded | CLIENT, degraded | ✅ identical degradation |

**Consequence to be honest about:** route comparison is now *tautological* —
both sides call the same function, so route can never disagree. That is the
intended end state, not a weakness in the harness, but it means route matches
are **not independent evidence**. Real divergence must come from tool selection
and intended side effects, which arrive when the handlers are wrapped (S5).

Degraded resolutions are flagged (`Principal.degraded`, `"degraded": true` in
the log) and must be excluded from any acceptance tally.

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

One structured JSON line per turn, greppable and machine-parseable:

```
BIC_REPLAY_MATCH {"route":"owner","role":"OWNER","flow":"owner","tools":[],
                  "decision_hash":"a1b2…","degraded":false,"sender":"9951"}
BIC_REPLAY_DIFF  {…same fields…, "diffs":["route: legacy='client' replay='owner'"]}
```

`decision_hash` is a stable hash of the whole Decision, so "did anything
change?" is answerable without diffing fields, and an accepted baseline is
citable as a single value.

`tools` is present but empty until the handlers are wrapped (S5) — the field
exists now so the log shape does not change when they arrive.

Replay failures are swallowed and logged; they must never affect a live turn.
