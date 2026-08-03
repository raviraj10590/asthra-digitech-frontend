# ADR 0007 — MANAGER is an authorization rank, not yet a pipeline

**Status:** Accepted · 2026-08-03 · **Relates to:** review finding M1

## Context

Two definitions of "who gets the internal pipeline" existed:

| Location | Value |
|---|---|
| `webhook.do_POST` | `("OWNER", "STAFF")` |
| `brain.INTERNAL_ROLES` | `("OWNER", "STAFF", "MANAGER")` |

A MANAGER therefore received the **customer sales pipeline** with
`BIC_POLICY_ENABLED` off and the **internal executive assistant** with it on.
The pipeline a person got depended on the rollback lever — precisely what 1C
promised not to introduce, and a data-exposure difference: the internal
assistant discusses business context that the standing data-safety rule keeps
away from non-owners.

It was invisible because production has **zero MANAGER rows**. It is also why 23
replay samples showed 0 diffs: the divergence existed but nothing exercised it.

## Decision

One definition. `brain.INTERNAL_ROLES` is authoritative; `webhook` imports it
and `do_POST` forks on it.

**MANAGER is removed from it.** 1C's mandate is byte-identical behaviour and
legacy never routed MANAGER internally, so preserving the legacy value is the
conservative resolution.

MANAGER remains a full rank in `policy.ROLE_ORDER` and still authorizes tools at
`min_role` STAFF or MANAGER. Only the **pipeline** choice excludes it.

`get_role`'s BIC-unavailable fallback keeps its own narrower list
(`("OWNER","STAFF")`) and was deliberately **not** unified: that is role
*validation*, not routing. With BIC unavailable there is no registry and no
policy gate, so the degraded path recognises only the two roles the legacy bot
ever understood and treats anything else as CLIENT. Widening privilege in the
mode with the fewest working safeguards would be the wrong direction.

## Consequences

A MANAGER added today gets the customer pipeline while holding STAFF-level tool
privileges. That is odd but it is the pre-existing behaviour, and it is now odd
*consistently* rather than depending on a feature flag.

**Open owner decision, deferred to 1D:** should MANAGER receive the internal
pipeline? That is a behaviour change requiring approval, not a bug fix.

## Verification

`tests/test_review_fixes.py::M1_OneInternalRolesDefinition` asserts webhook uses
the Brain's object identically, that MANAGER is absent from routing but present
in `ROLE_ORDER`, and — by AST — that `do_POST` has not re-inlined the tuple.
Both mutations fail the suite.
