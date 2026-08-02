# ADR 0005 — One source of truth for role resolution

**Status:** ✅ IMPLEMENTED — owner-approved 2026-08-02
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

## Consequence at the time (now RESOLVED)

`bic.policy` could not read `bot_roles` at all, so it failed closed to CLIENT.
That made the Slice 1C replay comparison **vacuous for unknown senders** — both
sides said CLIENT for different reasons. Fixed by this ADR: the fetcher is now
injected, so both paths perform the same real lookup.

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

## What was implemented

`bic/identity.py` — a NEW module (1C integration; 1B untouched):

- **Reuses** `Principal`, `ROLE_ORDER` and `BOOTSTRAP_OWNERS` from `bic.policy`;
  bootstrap logic is imported, never redefined.
- Holds **the** cache. `webhook._role_cache` is deleted.
- Takes an **injected row fetcher**, so `bot_roles` is read with the anon key
  its own RLS policy already permits (option B), removing the hidden
  service-role dependency.
- `resolve_legacy()` returns `(role, label)` so `webhook.get_role()` delegates
  without changing its signature or semantics (option C).
- `bic.brain` resolves through it too, so BOTH paths share one implementation.

`bic.policy.resolve_principal()` is marked `@deprecated` with explicit removal
conditions. It is not called in production, so its cache is never populated.

**Deviation from the original sequencing:** the ADR proposed doing this AFTER
1C. The owner directed it be done as 1C integration instead, because the replay
evidence 1C depends on is meaningless until the duplication is gone. The
concern that motivated the original ordering — ambiguous replay mismatches
during a routing migration — does not apply, since no routing has migrated yet.

**Caught during implementation:** `#addstaff` / `#removerole` still referenced
the deleted `webhook._role_cache` and would have raised `NameError` on any role
grant. Both now call `_invalidate_role()`.

## Verification

11 equivalence tests prove legacy == Brain for bootstrap owner, staff, unknown
sender and DB-unavailable (both degrade to CLIENT; neither escalates), plus one
shared cache, correct invalidation, and degraded results not being cached.
Mutation-tested: disabling the shared cache fails 2 tests.

## Removal of the deprecated function

See the `@deprecated` docstring in `bic/policy.py` for the three conditions.
Summary: 1C accepted, no callers remain, and a slice is open that may modify
`bic/policy.py` — 1B is closed, so removal needs an explicit phase.
