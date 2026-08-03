# ADR 0006 — A failed brochure is reported, not recorded as sent

**Status:** Accepted · 2026-08-03
**Supersedes:** nothing · **Relates to:** review finding H1

## Context

Slice 1C routed `send_brochure` through the Tool Registry. That introduced a
failure mode the code had never had before — **policy denial** — into the
customer hot path, and the call site discarded the result:

```python
send_text(sender, "ಖಂಡಿತ! ನಮ್ಮ ಕಂಪನಿ ಪ್ರೊಫೈಲ್ ಇಲ್ಲಿದೆ 🙏")
run_tool(sender, "send_brochure", _fallback=send_brochure)   # discarded
send_followup_buttons(sender)
save_messages([... "[ಬ್ರೋಚರ್ PDF ಕಳಿಸಲಾಯಿತು]"])              # "PDF was sent"
notify_owner(f"📄 Brochure sent to wa.me/{sender}")
```

A denial produced: a customer promised a document that never arrived, a
transcript asserting it had been sent, and an owner notified of a success that
never happened. Nothing in the logs contradicted any of it.

`_load_registry()` fails **closed** to an empty registry — correct for a
security boundary. Combined with the above, a Supabase blip would have turned
every brochure request into a silent lost lead with a fabricated success record.

## Decision

The dispatcher gained `invoke_tool()` returning `(ok, text)`; `run_tool()` is
the string-only wrapper over it. The brochure call site branches on `ok`:

- **success** — unchanged: buttons, `[ಬ್ರೋಚರ್ PDF ಕಳಿಸಲಾಯಿತು]`, owner notified.
- **failure** — the customer is told there was a technical problem and the team
  will follow up; the transcript records `[ಬ್ರೋಚರ್ ಕಳಿಸಲು ವಿಫಲವಾಯಿತು]`; the
  owner is told **"send it manually"**.

`send_brochure()` now returns a bool. The no-`BROCHURE_URL` branch returns
`False`, because it sends an apology rather than a brochure.

The same pattern is applied to `crm_capture_self` in `upsert_lead`, with a
greppable `LEAD_CRM_SYNC_FAILED` marker instead of a WhatsApp alert — the lead
is still in the `leads` table, so that path is recoverable rather than lost, and
an alert per sync would be noise.

## Consequences

**This is the one place Slice 1C deliberately changes customer-visible
behaviour.** 1C's mandate is byte-identical behaviour, and this breaks it.

That was the right call: what the old text preserved was a lie. "Byte-identical"
protects a customer from an unannounced change; it does not oblige us to keep
telling them a document arrived when it did not. The change is strictly in the
direction of truth, it only fires on a path that previously produced a silent
failure, and it converts an invisible lost lead into an owner action item.

The success path — the overwhelmingly common one — is untouched, so the
characterization tests that assert normal behaviour still pass unmodified.

## Alternatives rejected

- **Keep discarding the result.** Rejected: it is the defect.
- **Retry inline.** Rejected: a synchronous retry on a serverless request path
  risks the platform timeout, which triggers a Meta webhook retry and duplicate
  processing. Failing loudly is cheaper and more honest.
- **Sniff `run_tool`'s string for an emoji prefix.** Rejected: encoding control
  flow in user-facing copy means the next translation silently breaks the check.

## Verification

`tests/test_review_fixes.py::H1_NoFalseSuccessRecords` — four tests. Mutation:
forcing `if True:` at the branch, and making `send_brochure` return `True` with
no URL, both fail the suite.
