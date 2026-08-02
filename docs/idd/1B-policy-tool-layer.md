# IDD — Slice 1B: Policy Gate + Tool Registry + Invocation Logging

**Status:** Awaiting approval · **Governs:** BIC v1.0 Articles II, VI, VIII
**Prerequisite:** Slice 1A COMPLETE ✅ · Deployment item D3 required before release

---

## Objective

Establish the **deterministic security boundary** of the BIC: one place that
resolves who is asking, one place that decides what they may invoke, and one
place that records what happened.

This is the most security-critical slice in Phase 1. It contains **zero AI**.
Article II.2 — *security never depends on model behaviour* — is implemented
here or nowhere.

**No behaviour change.** Replies must stay byte-identical.

---

## Scope

**In**
- `bic/policy.py` — role resolution + grant sets (absorbs today's `get_role`)
- `bic/tools.py` — registry, guarded execution, invocation logging
- `bic/db.py` — single Supabase access point (Engineering Rule: never duplicate DB logic)
- `bic/config.py` — env-driven config, no hardcoded values
- Register a **small, real** set of existing capabilities as tools
- Characterization tests locking current behaviour

**Out**
- Orchestrator loop, AI tool-*selection* (Phase 2) — 1B builds the registry the
  loop will later call, not the loop
- Converting every existing function to a tool (deliberate: prove the mechanism
  on ~5 tools, migrate the rest incrementally)
- `action_queue` / approvals (Phase 3)
- Knowledge reads/writes (Slice 1D)

**Non-goal:** changing what any user sees.

---

## Design

### Role resolution
Today `get_role()` in `webhook.py` checks `OWNER_PHONES` (env) then the
`bot_roles` table. That logic **moves** to `bic/policy.py` unchanged in
behaviour, gaining:

- a `Principal` value object: `{sender_id, role, tenant_id, label, grants}`
- `tenant_id` from `BIC_TENANT_ID` (single tenant today; the column exists so
  multi-tenant is later a config change, not a migration — Article II.5)
- `MANAGER` accepted as a role (risk tier 4, Article VI) even though unused today

`webhook.get_role()` remains as a thin delegating shim so nothing else breaks.

### Grants
A grant set is derived from role, **not** hand-written per call site:

```
OWNER   → all active tools
MANAGER → risk_tier <= 4
STAFF   → risk_tier <= 3
CLIENT  → customer_safe = true ONLY   (allowlist, never denylist — Article VI)
```

Source of truth is `bic_tool_defs` (seeded in 1A). Adding a tool is a row plus a
handler; no policy code changes (Article VIII).

### Tool execution
Single entry point:

```
tools.invoke(principal, tool_code, **args) -> ToolResult
```

Every call, in order: resolve def → **check grant** → execute handler →
record invocation. There is no unguarded path; handlers are private and only
reachable through `invoke`.

### Logging
Writes `bic_tool_invocations`: tool, caller role, channel, redacted args,
ok/error, `latency_ms`, `db_queries`, `source_ref` (originating message →
Article II.10). Token counts stay null until Phase 2 (no AI in this slice).

**Args are allowlist-redacted**, never raw — they can carry phone numbers and
free text.

Logging is **best-effort**: a logging failure is printed and swallowed. A tool
must never fail because its audit write failed. Accepted trade-off — under
Supabase outage we lose audit rows rather than functionality.

---

## Files affected

```
NEW   bic/__init__.py
NEW   bic/config.py          env config incl. BIC_TENANT_ID, feature flag
NEW   bic/db.py              Supabase REST wrapper + query counter
NEW   bic/policy.py          Principal, resolve_principal(), grants
NEW   bic/tools.py           registry, invoke(), redaction, logging
NEW   tests/test_policy.py
NEW   tests/test_tools.py
NEW   tests/test_characterization.py
EDIT  api/webhook.py         get_role() → delegating shim; ~5 call sites route
                             through tools.invoke(). No other logic touched.
```

`webhook.py` shrinks. Per Owner Rule 5 it is becoming a transport adapter —
1B is a step toward that, completed in 1C.

**Tools registered in 1B** (existing behaviour, now guarded + logged):

| tool | min_role | risk | customer_safe |
|---|---|---|---|
| `crm_sync_lead` | STAFF | 3 | no |
| `crm_list_clients` | STAFF | 2 | no |
| `leads_today` | STAFF | 2 | no |
| `roles_list` | OWNER | 2 | no |
| `send_brochure` | CLIENT | 2 | **yes** |

`send_brochure` is deliberately included: it is the only customer-reachable tool,
so it exercises the allowlist path in production rather than only in tests.

---

## Database migrations

**None.** 1A created every table 1B needs. One seed migration adds the five
`bic_tool_defs` rows — data, not schema:

```
20260803000001_bic_tool_seed.sql   -- INSERT ... ON CONFLICT DO NOTHING
```

Article VIII holds: registering tools is an INSERT.

---

## APIs affected

| Surface | Change |
|---|---|
| `/api/webhook` | Internal only. Same Meta contract, same replies. |
| `/api/lead` | `sync_lead_to_crm` invoked via registry. Same HTTP contract. |
| New internal | `tools.invoke(...)`, `policy.resolve_principal(...)` — not HTTP-exposed |

**No public API changes.**

---

## Risks

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| R1 | Refactoring role resolution breaks owner/client routing — the bot's most important branch | 🔴 High | Characterization tests written **first**; `get_role()` shim keeps the old signature; `BIC_POLICY_ENABLED=off` reverts at runtime without deploy |
| R2 | `SUPABASE_SERVICE_ROLE_KEY` on Vercel is a powerful credential | 🟠 Med | Server-side only, never in source, never sent to a model. This project has a prior key-leak incident — treat with care. |
| R3 | Logging adds a DB write per tool call (latency) | 🟠 Med | Best-effort with short timeout; measured in tests; revisit if p95 regresses |
| R4 | Redaction misses a field and PII lands in logs | 🟠 Med | **Allowlist**, not denylist — unknown keys are dropped by default |
| R5 | Tool defs and handlers drift (row exists, handler missing) | 🟡 Low | Startup consistency check; unknown tool → explicit error, never silent pass |
| R6 | D3 not done → all BIC writes fail in prod | 🟡 Low | Fail loudly at boot with a clear message; logging degrades, tools still run |

R1 is the one that matters. Everything else is recoverable; a routing regression
means a customer gets owner-mode replies.

---

## Rollback

| Level | Action | Data loss |
|---|---|---|
| Runtime | `BIC_POLICY_ENABLED=off` → inline legacy path | none |
| Code | `git revert <sha>` → redeploy | none |
| Data | none — logging is additive | none |

The runtime kill-switch exists because this slice touches the security path;
a `git revert` needs a deploy, and a routing bug needs to be stoppable *now*.

---

## Testing plan

Stdlib `unittest`, network mocked, must pass offline. No new dependencies.

**Characterization (written FIRST — these define "no behaviour change"):**
capture current replies/routing for ~15 inputs across OWNER, STAFF, CLIENT,
unknown numbers, `#` commands, and off-topic. Must stay green throughout.

**Policy**
- OWNER/STAFF/CLIENT resolve correctly; unknown → CLIENT
- a message *claiming* owner role does **not** escalate (Article II.1)
- `bot_roles` unreachable → degrades to CLIENT, never to OWNER *(fail closed)*
- bootstrap `OWNER_PHONES` works with the DB down

**Tools**
- below-`min_role` → denied, denial logged, handler never entered
- CLIENT can invoke only `customer_safe` tools
- unknown tool → explicit error
- handler raises → `ToolResult.ok == False`, invocation still logged
- redaction: unknown arg keys dropped; phone/message never stored raw
- logging failure does not fail the tool

**Measurement** (Performance Rules): assert `latency_ms` and `db_queries` are
populated; record p95 for the 5 tools as a baseline for later slices.

---

## Deployment plan

1. PR → self-review → tests green
2. Merge → `vercel --prod --yes`
3. Verify webhook alive (403 on bad token)
4. Send one real WhatsApp message as OWNER, one as CLIENT
5. Confirm `bic_tool_invocations` has rows with latency + role (Management API)
6. Confirm replies match characterization output
7. **24h soak before 1C**

⚠️ **D3 (`SUPABASE_SERVICE_ROLE_KEY`) must be set before step 2.** Without it
every BIC write fails; tools still function but nothing is audited.

---

## Success criteria

- [ ] Characterization tests green — replies unchanged
- [ ] All 5 tools invoke only through `tools.invoke`; no unguarded path
- [ ] Every invocation writes a row with `latency_ms` + `db_queries`
- [ ] CLIENT denied non-customer-safe tools (verified in prod, not only tests)
- [ ] Claimed-role escalation attempt fails
- [ ] Zero AI calls added
- [ ] No public API change
- [ ] `BIC_POLICY_ENABLED=off` cleanly restores legacy path
- [ ] p95 latency recorded for all 5 tools

---

## Estimate

~1 day. Characterization tests are roughly a third of it and are the reason the
rest is safe.

---

## Approval requested

1. Accept the 5-tool starting set, or adjust?
2. Accept best-effort logging (audit rows lost during a DB outage, tools keep working)?
3. Confirm single tenant via `BIC_TENANT_ID` for now?
