# ADR 0002 — Database verification via the Management API

**Status:** Accepted · **Date:** 2026-08-02 · **Slice:** Phase 1A

## Context

Slice 1A needed behavioural verification — proving the schema *enforces* its
constraints, not merely that tables exist. "The tables were created" is not
verification when the whole point of the review was the constraints.

The Supabase dashboard SQL editor proved unreliable across the entire session:
blank renders, hung script injection, stale cached content. Time was being spent
proving the editor works rather than proving the database works.

## Options evaluated

| Method | Result |
|---|---|
| Dashboard SQL editor | ❌ Unreliable — repeated hangs and blank renders |
| `supabase db push` (CLI) | ✅ Works, but applies migrations only — no ad-hoc query |
| `supabase inspect db` | ⚠️ Fixed reports only (table/index stats); cannot assert behaviour |
| **psql** | ❌ Not installed; no package manager (`brew` absent) |
| **psycopg + pooler URL** | ❌ `supabase/.temp/pooler-url` carries **no password** — the CLI mints a temporary login role via the API, which is why `db push` needs no credential. Not reproducible outside the CLI. |
| Python `urllib` → Management API | ❌ Cloudflare 403 (error 1010) — TLS fingerprint rejected |
| **curl → Management API** | ✅ **Chosen** |

## Decision

Verify via the Supabase **Management API**:

```
POST https://api.supabase.com/v1/projects/{ref}/database/query
Authorization: Bearer $(cat ~/.supabase/access-token)
```

Payloads are built with `python3 -c "json.dumps(...)"` reading SQL from a file.
Building JSON inline in the shell corrupts SQL string literals — quoting
silently stripped every `'...'`, producing `trailing junk after numeric
literal`. Never hand-assemble the JSON.

## Verification design

Structural checks alone were rejected as insufficient. The suite asserts
behaviour, including **negative tests** — constraints that must *reject*:

- trigger derives `cardinality_hint` from the registry (app never sets it)
- `multi` predicates **accumulate** (review finding C2 — the silent data-loss bug)
- `customer_claim` confidence > 0.5 is **rejected** (Article II.6)
- unregistered predicate is **rejected**
- duplicate `single`-cardinality fact is **rejected**

All write tests run inside `begin; … rollback;`. Confirmed afterwards that all
BIC tables remain at **0 rows** — no test residue in production.

## Consequences

**Positive** — reliable, scriptable, repeatable, no dashboard dependency; the
same method serves future slices; negative tests give real assurance that
constraints hold rather than merely existing.

**Negative** — depends on `~/.supabase/access-token`; the Management API is
rate-limited and not intended for bulk data work (fine for verification).
Cloudflare rejects some HTTP clients, so **curl specifically** is required.
