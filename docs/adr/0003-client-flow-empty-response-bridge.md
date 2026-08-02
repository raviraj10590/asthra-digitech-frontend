# ADR 0003 — The empty-BrainResponse client bridge is TEMPORARY

**Status:** Accepted, explicitly time-limited · **Date:** 2026-08-02 · **Slice:** 1C

## Context

The two pipelines have different shapes today:

- **OWNER path** — `handle_owner_text()` **returns** text. It maps directly onto
  the contract: the flow returns `BrainResponse(text=...)`, the adapter sends it.
- **CLIENT path** — sends its own messages inline inside `do_POST`
  (`send_welcome_menu`, `send_brochure`, follow-up buttons, the AI reply),
  interleaved with saves and owner alerts.

So when the client flow is wrapped, it will **send its own messages and return
`BrainResponse(text="")`**. The adapter's send step is a deliberate no-op for it,
which is why `render()` treats empty text as valid rather than an error.

## Decision

Accept the empty-response bridge **for Phase 1C only**.

Behaviour preservation outranks architectural purity here (owner directive).
Reshaping the client handlers to return text instead of sending would mean
rewriting business functions — explicitly forbidden in 1C, and the single most
likely way to introduce a customer-visible regression.

## ⚠️ This is NOT the target architecture

The target, unchanged:

```
Webhook → Adapter → BrainRequest → Brain → Policy → Tool Registry
        → Business Function → BrainResponse → Adapter → WhatsApp
```

**Every flow should eventually return a BrainResponse. No flow should
permanently send messages directly.**

## Constraints on future phases

1. **Do not build on this bridge.** No later phase may assume a flow can send
   its own messages. Anything depending on that inherits a defect.
2. **Do not treat empty-text as meaningful** beyond "the flow already handled
   output". It is not a signal, a status, or an extension point.
3. When client handlers are normalised to return text, `render()` becomes the
   single output path and this ADR should be superseded — not quietly forgotten.
4. New flows written from scratch **must** return a populated `BrainResponse`.
   The bridge is a concession to existing code, never a pattern to copy.

## Consequences

**Positive** — zero behaviour change; no business function rewritten; the
riskiest possible 1C change is avoided.

**Negative** — the two flows are asymmetric, so reading the code requires
knowing why. Output is temporarily split across two places (the flow and the
adapter), which is exactly the coupling the contract exists to remove. Left
unaddressed, it becomes permanent by default — hence this ADR.
