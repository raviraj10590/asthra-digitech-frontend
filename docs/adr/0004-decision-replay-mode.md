# ADR 0004 — Decision Replay Mode (supersedes "Shadow Mode")

**Status:** Accepted · **Date:** 2026-08-02 · **Slice:** 1C

## Context

The original plan was Shadow Mode: run both pipelines per message, compare,
give the customer the legacy reply. **Rejected — neither pipeline is a pure
function.** Executing the new path a second time would re-run its effects:
2× AI calls on a provider already at quota, duplicate rows in a live CRM,
memory rolled forward twice, duplicate owner alerts, and the customer receiving
the message twice. On the first live message that produces exactly the
"customer notices the migration" outcome the plan exists to prevent.

## Decision

**Decision Replay Mode.** The legacy path stays the ONLY production path. The
new pipeline **predicts what it would do and does not execute.**

Analysis mode forbids, without exception:
- WhatsApp sends · CRM writes · memory writes · any database mutation
- lead sync · brochure sends · any tool execution with side effects

Instead, intended operations are **recorded**:

```
legacy:  send_brochure(client)
replay:  record {tool: "send_brochure", arguments: {...}}   # no execution
```

## How

Flows already receive their collaborators by injection (the Brain never imports
application code — ADR from 1C). Replay mode passes **recorders** in place of
the real sender / CRM writer / memory writer / `save_messages`. Each recorder
appends `{operation, arguments}` to a list and returns a benign default.

**The safety property is structural, not disciplinary:** in replay mode the
flow holds no reference to anything that can mutate state. It cannot write even
if a future edit tries to — the same reasoning that makes the Tool Registry's
no-bypass guarantee hold.

## Compared

- Selected route (owner vs client flow)
- Selected tools
- Intended side effects (recorded, not performed)
- Reply text — **with the caveat below**

Explicitly NOT compared: actual side effects. There are none to compare.

## ⚠️ Reply text cannot be compared naively

**LLM output is non-deterministic.** Two independent calls with an identical
prompt routinely return different wording. If both pipelines generate their own
reply, comparison reports differences on every message even when both paths are
perfectly correct — the harness would produce constant false failures and be
abandoned, which is worse than not having it.

Compare the **inputs to the model**, not its output:

1. **Assembled prompt/context** — system prompt, retrieved memory, history
   window, injected snapshot. Deterministic, free to compare, and it is the
   real question: *does the new pipeline hand the model the same thing?*
2. **The decision to call the model at all** — and with which provider chain.
3. In replay mode the AI call itself is **stubbed** and returns a sentinel. No
   extra tokens, no extra cost, no quota impact.

If both pipelines assemble an identical prompt and route identically, any
difference in generated text is the model's non-determinism, not a migration
defect. That is the only comparison that can actually pass.

## Acceptance

Enable `BIC_POLICY_ENABLED` when both pipelines consistently produce equivalent
**decisions** — route, tools, intended effects and assembled prompt — across a
representative sample. Never on the basis of matching generated text.

## Consequences

**Positive** — production state is provably unchanged during comparison; zero
added AI cost; no duplicate CRM rows; the comparison can actually pass rather
than drowning in false differences.

**Negative** — replay does not exercise the real write paths, so a bug that only
appears on execution (a malformed CRM payload, say) survives until the flag
flips. Mitigation: the flag is per-deployment and instantly reversible, and the
5 wrapped tools already have unit coverage.
