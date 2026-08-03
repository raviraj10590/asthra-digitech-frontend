# ADR 0001 — BIC migration tooling and history ownership

**Status:** Accepted · **Date:** 2026-08-02 · **Slice:** Phase 1A

## Context

BIC v1.0 Article IV places BIC tables in the AI ಕನ್ನಡ Supabase project
(`kpzprllzgqlqkqgcgrbp`). That database is **shared**: the ai-kannada Next.js app
owns `articles`/`netas`/`rss`/`govt`; the WhatsApp bot owns `whatsapp_messages`/
`leads`/`bot_roles` and now all `bic_*` tables.

Owner approved Supabase CLI for migrations (version controlled, repeatable,
rollback-friendly) over manual SQL.

On first `db push` the CLI refused:

```
LegacyDbPushMissingLocalError: Remote migration versions not found in local
migrations directory.  (24 versions: 001 … 20260630145205)
```

The remote database already carried 24 tracked migrations with no local
counterpart in this repo. They predate BIC.

## Decision

**BIC migrations live in the bot repo** (`supabase/migrations/`), prefixed
`bic_`, strictly additive. History is aligned by committing **empty placeholder
files** for the 24 pre-existing versions.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| `supabase db pull` | Dumps another system's entire schema into this repo and rewrites a history this repo does not own. Explicitly forbidden in `supabase/config.toml`. |
| `migration repair --status reverted` | Records 24 migrations as *reverted* when they were not. Falsifies the audit trail — unacceptable under Article II.10. |
| Put BIC migrations in the ai-kannada repo | Splits BIC schema from BIC code across repos. Worse coupling; the bot repo is the BIC implementation. |
| Manual SQL | Owner explicitly rejected except for emergency recovery. |

## Consequences

**Positive** — CLI push works; only new BIC files apply; nothing destructive;
audit trail stays truthful; migrations are version-controlled and reviewable.

**Negative — accept knowingly:**
- ⚠️ **This repo cannot rebuild the database from scratch.** The placeholders are
  empty, so a fresh-DB replay produces only BIC tables. Accepted: this is a live
  production database that is never recreated from migrations.
- Two systems write to one database. Mitigated by the `bic_` prefix and the rule
  that BIC migrations never ALTER or DROP another system's tables.

## Guardrails

Recorded in `supabase/config.toml` and `docs/RUNBOOK.md`:

- ✅ `supabase db push`, `supabase migration list --linked`
- ❌ **`supabase db reset`** — would drop the production database
- ❌ **`supabase db pull`** — would rewrite history this repo does not own

## Implementation notes (two failures worth recording)

1. **`symmetric` is a reserved word in Postgres** → column renamed
   `is_symmetric`. Rejected quoting the identifier; quoted names are a permanent
   maintenance tax.
2. **`extensions.gin_trgm_ops` did not resolve.** `create extension if not
   exists` is a *no-op* when the extension already exists in a different schema,
   so hard-qualifying broke. Fixed with `set local search_path = public,
   extensions` and unqualified operator names — portable regardless of where the
   extension actually lives.

Both migrations rolled back cleanly on failure (verified: `remote` column empty
in `migration list` after each failure), confirming per-file transactionality.
