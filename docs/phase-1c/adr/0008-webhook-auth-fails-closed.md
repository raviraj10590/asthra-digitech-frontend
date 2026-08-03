# ADR 0008 — Webhook authentication: measure, then enforce

**Status:** Accepted · 2026-08-03 · **Relates to:** audit finding C-1

## Context

Signature verification was conditional:

```
app_secret = os.environ.get("META_APP_SECRET", "")
if app_secret:          # unset ⇒ verification skipped ENTIRELY
```

The 2026-08-03 independent audit probed production directly rather than
reading the code, and found the secret unset. An unsigned POST returned **200**.

The consequence runs through the whole architecture. Identity is resolved from
`payload…messages[0].from`. That payload was unauthenticated. A bootstrap owner
number appears in this repository, in the docs and in the deployment config, so
anyone holding the webhook URL could:

1. Forge a message claiming to be that owner
2. Be resolved as OWNER — correctly, through the intended code path
3. Have the Policy Gate authorize it, the Tool Registry execute it, and the
   audit trail record it as a genuine owner action
4. Run `#addowner` and mint themselves a permanent OWNER

**Every control built in Slices 1B and 1C worked exactly as designed.** They
faithfully authorized a forged principal. Article II.1 requires identity to come
from the transport's *verified* payload; the payload was not verified.

Three prior code reviews missed this, including one that reported eight
acceptance criteria as passing. All three read artefacts. None probed the
running system.

## ⚠️ Amended before deployment — the router

The first version of this decision was "fail closed, immediately". Investigating
the Meta app configuration **before** deploying it found that would have been an
outage.

**Meta does not deliver to this endpoint directly.** Of eight Meta apps, exactly
one has WhatsApp configured — "N8N messages" (`1096228049110325`, the only app in
Live mode) — and its callback URL is:

```
https://whatsapp-router-flame.vercel.app/webhook
```

That router (confirmed by the owner as theirs) forwards to this endpoint. Our
HMAC is computed over the **raw body** with Meta's app secret, so it can only
validate if the router forwards *both* the original bytes *and* the original
`X-Hub-Signature-256` header. A forwarder that re-serialises the JSON — the
default behaviour of most HTTP proxies and of `requests`/`fetch` round-trips —
changes the bytes and breaks the hash silently.

**Enforcing blind would have rejected 100% of legitimate traffic and taken the
bot dark, with the cause invisible in the logs.** The audit that found the
vulnerability did not find the router; only reading the Meta config did.

## Decision

**Measure first, enforce second.**

Ship signature verification in OBSERVE mode: compute the signature, log whether
it would have validated, reject nothing. `WEBHOOK_AUTH_ENFORCE=true` flips it to
fail closed once evidence shows a valid signature survives the router hop.

This is the same pattern that made the Decision Replay migration safe, and it
replaces an assumption about the router with a measurement of it.

**The observation window is a deliberate, time-boxed period in which the
vulnerability remains open.** One real message produces the evidence. It must be
closed on that evidence, not left running because nothing is visibly broken.

When enforcing: an unconfigured secret rejects **all** traffic.

**503, not 403,** when the secret is missing: this is our misconfiguration, not
a caller failure, and Meta retries 5xx — so genuine messages are redelivered
once the secret is set rather than being silently discarded. A signature that is
present and wrong still gets 403.

## Measured — the router preserves everything (2026-08-03)

Observe mode answered the question the same day, **without needing the app
secret**, because `signature_present` does not depend on it.

Four real WhatsApp messages (561, 691, 696, 727 bytes) all arrived with
`signature_present: true`. A controlled probe settled the byte question:

| | |
|---|---|
| Bytes sent to the router | **221** |
| Bytes received by the bot | **221** |
| Bytes if it had re-serialised (`json.dumps`) | 241 |

The router forwards the raw body **byte-for-byte** and passes
`X-Hub-Signature-256` through untouched. Its user agent is
`python-requests/2.32.3` — a straight pass-through, not a re-encode.

**Therefore HMAC verification works on this path, and enforcement is safe once
`META_APP_SECRET` is configured.** The original fail-closed decision was right;
what was missing was evidence, not correctness. Shipping it on the assumption
would have been reckless even though the assumption happened to hold.

Method worth repeating: two `curl` calls and one log read replaced a guess that
could have blacked out production. The audit found the vulnerability; only
reading the Meta config found the router; only observe mode proved the router
was harmless.

## Consequences

**This changes behaviour, and it can take the bot offline.** With the secret
unset, every Meta delivery is now rejected. That is the correct failure
direction — an authenticated-but-down bot is recoverable, an unauthenticated
one is a standing privilege-escalation path — but it makes deployment ordering
load-bearing:

1. Set `META_APP_SECRET` in the deployment environment (Meta App Dashboard →
   App Settings → Basic → App Secret)
2. Verify: an unsigned POST returns **403**, not 200
3. Only then deploy this change
4. Re-verify, and confirm a real message still round-trips

Reversed, the bot goes dark and Meta may disable the webhook subscription after
sustained 5xx.

## Alternatives rejected

- **Keep it conditional, document the requirement.** Rejected: it was already
  documented in a code comment naming this exact risk, and the risk shipped
  anyway. A comment is not a control.
- **Warn loudly but continue.** Rejected: a warning in a serverless log nobody
  reads is indistinguishable from silence.
- **403 when unconfigured.** Rejected: 4xx tells Meta the request was bad and
  discourages retry, so messages received during the misconfiguration window
  would be lost rather than redelivered.

## Verification

`tests/test_http_integration.py::SignatureVerification` — 7 tests, the first in
this repository to execute `do_POST`. Covers unconfigured, unsigned, wrong
signature, wrong secret, body tampering (sender escalation after signing), valid
signature, and the concrete forged-owner attack.

Mutation-verified: reverting to fail-open, disabling the comparison, forcing the
signature to match, and returning 200 when unconfigured all fail the suite.
