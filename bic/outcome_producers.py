"""The first 2I producer — customer reply after an outbound AI turn.

SCOPE (smallest safe set, IDD-2I §3.1/I6): exactly one eligible action —
the AI-generated reply in `run_client_pipeline`'s normal-turn branch. Menu
echoes, off-topic redirects, brochure sends and the new-contact welcome are
deliberately NOT wired here; they are procedural, not the business decision
the IDD-2I test fixtures (`RealBusinessEvents`) were written against.

This module is the ONLY place production code calls into `bic.outcomes`.
`bic/outcomes.py` itself is untouched — every guard below lives here, using
only outcomes.py's existing public functions (`expect`, `observe`, `current`,
`due_for_timeout`, `time_out`). Best-effort throughout, matching
`bic/decision.py`'s own rule: evidence collection must never affect the
customer's turn.
"""

from typing import Optional

from . import config, party
from . import outcomes as oc
from .db import DbError

CUSTOMER_REPLY_KIND = "customer_reply"

# IDD-2I §10.1: the window is a per-decision-type declaration, not a global
# constant. This is the one declared parameter for the one kind wired so far.
# 24h matches how the test fixtures (tests/test_outcomes.py::RealBusinessEvents)
# already model this outcome kind.
CUSTOMER_REPLY_WINDOW_SECONDS = 86400


def _tenant(tenant_id: Optional[str]) -> str:
    return tenant_id or config.DEFAULT_TENANT_ID


def _subject(tenant_id: str, sender: str) -> Optional[str]:
    """Phone -> opaque 2B knowledge_id. Never the phone itself (I4/2B §4.3)."""
    try:
        return party.resolve_or_create(tenant_id, party.WHATSAPP, sender)
    except DbError as e:
        print(f"outcome_producers: party resolution failed (ignored): {e}")
        return None


def expect_customer_reply(sender: str, decision_ref: str,
                          tenant_id: Optional[str] = None,
                          goal_ref: Optional[str] = None) -> None:
    """Open the observation window at DECISION time (I6), right after the
    eligible outbound send. Never raises — a failed expectation write must
    not affect the reply the customer already received.
    """
    if not decision_ref:
        return
    tenant = _tenant(tenant_id)
    subject = _subject(tenant, sender)
    if not subject:
        return
    try:
        oc.expect(tenant, subject, decision_ref,
                  outcome_kind=CUSTOMER_REPLY_KIND,
                  window_seconds=CUSTOMER_REPLY_WINDOW_SECONDS,
                  goal_ref=goal_ref)
    except (DbError, oc.OutcomeError) as e:
        print(f"outcome_producers: expect_customer_reply failed (ignored): {e}")


def _latest_outcome_row(tenant_id: str, subject: str, kind: str) -> Optional[dict]:
    """Most recent row for this subject+kind, regardless of its own stored
    lifecycle. Read-only helper local to this module — not a change to
    outcomes.py's public surface.
    """
    rows = oc.select(oc.TABLE, {
        "tenant_id": f"eq.{tenant_id}", "subject": f"eq.{subject}",
        "outcome_kind": f"eq.{kind}", "order": "recorded_at.desc",
        "limit": "1",
    }, timeout=5)
    return rows[0] if rows else None


def observe_customer_reply(sender: str,
                           tenant_id: Optional[str] = None) -> None:
    """Called once per genuine inbound customer turn (webhook-level wamid
    dedup already gates entry here — no second dedupe system added, IDD-2I
    Step 6).

    Deterministic chronology only: the most recent customer_reply expectation
    for this subject, if still open, is what this inbound message answers.
    No AI, no content inspection (IDD-2I Step 4).

    Idempotent by construction: only fires when the DERIVED lifecycle
    (oc.current(), not the row's own immutable stored field) is EXPECTED or
    CLOSED-but-unobserved. A second inbound message, a cron timeout that
    already ran, or a webhook retry that slipped through all read as already
    handled and are skipped.
    """
    tenant = _tenant(tenant_id)
    subject = _subject(tenant, sender)
    if not subject:
        return
    try:
        latest = _latest_outcome_row(tenant, subject, CUSTOMER_REPLY_KIND)
        if not latest:
            return  # no expectation ever opened for this subject — unrelated
        decision_ref = latest.get("decision_ref")
        view = oc.current(tenant, decision_ref)
        entry = view.get(CUSTOMER_REPLY_KIND)
        if not entry or entry["lifecycle"] not in (oc.EXPECTED, oc.CLOSED):
            return  # already observed/confirmed/retracted — nothing to do
        oc.observe(tenant, entry["record"], oc.RESOLVED, oc.OBSERVED,
                  observed_by="whatsapp:inbound_message")
    except (DbError, oc.OutcomeError) as e:
        print(f"outcome_producers: observe_customer_reply failed (ignored): {e}")


def sweep_customer_reply_timeouts(tenant_id: Optional[str] = None) -> dict:
    """For the daily cron (IDD-2I Step 5). Reports data, never silently
    discards (I7): every window that closed with no reply becomes a
    NO_RESPONSE/TIMED_OUT record.

    Idempotent across repeated cron runs: due_for_timeout() matches on the
    row's own immutable stored lifecycle, which never changes once written —
    so a naive second call would re-timeout the same window. The derived
    oc.current() check below is the guard: after the first successful
    time_out(), the chain's derived lifecycle becomes OBSERVED, and a repeat
    run skips it.
    """
    tenant = _tenant(tenant_id)
    swept, skipped, failed = 0, 0, 0
    try:
        due = oc.due_for_timeout(tenant)
    except DbError as e:
        print(f"outcome_producers: due_for_timeout failed (ignored): {e}")
        return {"swept": 0, "skipped": 0, "failed": 0}

    for row in due:
        if row.get("outcome_kind") != CUSTOMER_REPLY_KIND:
            continue  # smallest safe set — sweep only the kind this module produces
        try:
            view = oc.current(tenant, row.get("decision_ref"))
            entry = view.get(CUSTOMER_REPLY_KIND)
            if not entry or entry["lifecycle"] != oc.CLOSED:
                skipped += 1
                continue
            oc.time_out(tenant, entry["record"])
            swept += 1
        except (DbError, oc.OutcomeError) as e:
            failed += 1
            print(f"outcome_producers: timeout sweep failed for one row "
                 f"(ignored, others continue): {e}")
    return {"swept": swept, "skipped": skipped, "failed": failed}
