# ADR 0005 — One source of truth for role resolution

**Status:** PROPOSED — needs owner approval (touches closed Slice 1B)
**Date:** 2026-08-02 · **Raised by:** owner review of Slice 1C, point 4

## Problem

Role resolution exists **twice**, with independent caches:

| | `webhook.get_role()` | `bic.policy.resolve_principal()` |
|---|---|---|
| Introduced | pre-BIC | Slice 1B |
| Reads | `bot_roles` | `bot_roles` |
| Credential | `SUPABASE_KEY` (anon) | `SUPABASE_SERVICE_ROLE_KEY` via `bic.db` |
| Cache | `webhook._role_cache`, 300 s | `bic.policy._role_cache`, 300 s |
| Bootstrap owners | `OWNER_PHONE` env | `OWNER_PHONE` env |

Two independent caches with independent TTLs can disagree for up to 5 minutes
after a role change. More seriously, the two paths can disagree *permanently*
whenever their credentials differ in what they can read — which is the case
today, because `SUPABASE_SERVICE_ROLE_KEY` is not set (deployment item D3).

This violates the intent of Article II: there should be exactly one place that
decides who someone is.

## Consequence today

`bic.policy` cannot read `bot_roles` at all, so it fails closed to CLIENT.
That makes the Slice 1C replay comparison **vacuous for unknown senders** —
both sides say CLIENT, for different reasons. Detailed in `docs/REPLAY-SPEC.md`.

## Options

| Option | Description | Assessment |
|---|---|---|
| **A** | Set D3, keep both implementations | Fixes the symptom, leaves two caches and two code paths. Rejected. |
| **B** | `bic.policy` reads `bot_roles` with the anon key; service-role reserved for `bic_*` tables | Correct on least-privilege grounds — `bot_roles` is a pre-BIC table with anon-select policies and does not need service-role. Requires `bic/db.py` to support a second credential. **Touches closed 1B.** |
| **C** | `webhook.get_role()` delegates to `bic.policy` | Achieves ONE source of truth. Requires B first (otherwise role resolution breaks the moment it depends on an unset key). |

## Recommendation

**B then C**, in that order, as the first work of a slice — not bolted onto 1C.

- **B** gives `bic/db.py` an explicit `public_select()` for pre-BIC tables that
  carry their own RLS policies, leaving `select()` service-role-only for
  `bic_*`. Least privilege, and it removes the hidden dependency on D3.
- **C** then makes `webhook.get_role()` a thin delegate, deleting the second
  cache and leaving exactly one implementation.

C must not land before B, and neither should land mid-1C: changing role
resolution while a routing migration is in flight would make any replay
mismatch ambiguous — was it the routing change or the role change?

## Sequencing

1. Finish 1C on the current split (documented, reversible).
2. Land B + C as a small dedicated change with the characterization suite as
   the safety net.
3. Re-run replay; only then does a client-path `MATCH` count as evidence.

## Consequences if not done

Two authorities on identity, drifting independently. The security boundary
built in 1B is only meaningful if it is the one that actually decides — a
second resolver that production trusts instead makes 1B decorative.

## Status

Awaiting approval. **No code written for this ADR.**
