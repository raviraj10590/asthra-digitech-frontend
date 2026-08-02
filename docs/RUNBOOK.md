# Runbook — Asthra WhatsApp Bot / Business Intelligence Core

One page. What to check, in what order, when something is wrong.

---

## Is it alive?

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://asthra-digitech-frontend.vercel.app/api/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=test"
```
**403 = healthy** (rejecting a bad verify token is correct). Anything else = down.

---

## Bot replies but answers are wrong / generic

Check provider health first — the bot silently falls back OpenAI → Gemini.

```bash
vercel logs asthra-digitech-frontend.vercel.app --since 30m --expand | grep -iE "openai error|gemini|fallback|quota"
```

- `insufficient_quota` → OpenAI billing exhausted. **Fix in the OpenAI dashboard
  (billing), not in code.** A negative credit balance blocks even the free
  complimentary tier.
- `both providers failed` → the owner/customer saw an apology message. Check
  Gemini status too.
- Flip primary provider without deploying: set `AI_PROVIDER_PRIMARY=gemini|openai`
  in Vercel env.

From WhatsApp as OWNER, `#aitest` probes both providers directly.

---

## Migrations

Always dry-run first.

```bash
export SUPABASE_ACCESS_TOKEN="$(cat ~/.supabase/access-token)"
npx supabase@latest db push --dry-run --linked   # preview
npx supabase@latest db push --linked             # apply
npx supabase@latest migration list --linked      # verify: local ✓ / remote ✓
```

### ⛔ Never run these

| Command | Why |
|---|---|
| `supabase db reset` | **Drops the production database.** |
| `supabase db pull` | Rewrites migration history this repo does not own. |

This database is shared with the ai-kannada app and carries 24 pre-BIC
migrations represented locally as **empty placeholders** (see ADR 0001).
Consequence: **this repo cannot rebuild the DB from scratch.** BIC migrations
are additive only and never touch another system's tables.

**A failed migration rolls back cleanly** (per-file transaction). Verify with
`migration list` — a failed version shows `remote` empty. Fix the SQL and re-push.

---

## Rollback

| Layer | How |
|---|---|
| Code | `git revert <sha>` → `vercel --prod --yes` |
| Slice 1D behaviour | set `BIC_KNOWLEDGE_READ=off` (no deploy needed) |
| Migration | Write a NEW forward migration that drops/reverts. Never edit an applied file. |

BIC tables are additive and unread by application code until Slice 1D, so
reverting code alone is sufficient through 1A–1C.

---

## Data growth (Article II.7)

Free tier is 500MB. Retention functions exist but must be **invoked by the
scheduler** — they do not self-run.

```sql
select * from bic_rollup_tool_invocations(30);  -- roll up + delete raw >30d
select bic_prune_superseded_facts(180);         -- drop unreferenced dead facts
```

Check size: `npx supabase@latest inspect db table-stats --linked`

⚠️ If `bic_tool_invocations` is growing without rollup, the free tier dies in
months and **writes start failing silently**.

---

## Known silent-failure modes

This system has a history of failing quietly. Check these explicitly:

1. **GitHub Actions green ≠ working.** Workflows use `curl` without `-f`, so an
   HTTP 401/500 still exits 0. Read the printed status codes, not the ✅.
2. **Vercel log retention is ~1 hour.** `bic_tool_invocations` is the durable
   record — that is a primary reason it exists.
3. **Admin UI showing empty ≠ no data.** A 401 renders blank because
   `Promise.allSettled` swallows rejections. Check the network tab / status code.

---

## Escalation

Credentials, billing, key rotation, and WhatsApp template approval are
**owner-only** actions. Do not attempt them from code or automation.
