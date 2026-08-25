"""Stage ⑮ escalation — an unrecoverable send becomes a durable obligation.

    "⑮ Respond | Brain → Channel | Send fails | Retry idempotently; QUEUE FOR
     HUMAN" (IDD-3A §1.2)
    "T4 Severe | Acknowledge, QUEUE, notify a human. Never silence." (§6.2)

WHAT "QUEUE" MEANS HERE, AND WHY IT IS NOT A QUEUE
--------------------------------------------------
IDD-3B §1.2 types goals by lifespan and sends the persistent ones to 2B:

    "Persistent goals ARE Commitments. A goal the business holds itself to is
     a commitment with the business as counterparty. One concept, two vantage
     points — NO DUPLICATE STORE, NO RECONCILIATION."

Work that outlives the turn is therefore a Commitment, not a queue row. This
module is only the SEAM between two things that already exist: bic.recovery
decides that a human is needed, and bic.commitment records what we now owe.

WHY THIS IS NOT IN bic/recovery.py
----------------------------------
recovery.py states it "writes no outcome, no claim, and no row anywhere", and
its tests enforce that by scanning the source for `insert(`, `select(` and
`db.`. That separation is worth keeping: classification is a pure function of
one observation and must stay trivially testable and replayable. Persisting a
consequence is a different job, so it lives behind a different door.

THE DEADLINE IS THE OPEN QUESTION, AND IT IS NOT ANSWERED HERE
--------------------------------------------------------------
2B makes due_on part of a Commitment's IDENTITY and part of its purpose:

    "Commitment | Any promise with a party, obligation and deadline |
     subject + party + due_on"
    "...so that 'what have we promised and are we about to MISS IT?' is
     answerable."

A deadline is therefore not a formality this module may fill in. **There is no
approved business SLA for an undelivered customer reply** — not in 2B, not in
3A §1.2/§6.2, not in bic/policy.py (which is role authorization, not business
policy), and not in config. See due_on_policy() for the exact missing ruling.

So an invented deadline would not be a small convenience. It would fabricate
the very field that decides when the business is judged late, write it into
the identity key, and make every "are we about to miss it?" answer a
restatement of a number nobody approved. Without a policy this module records
NOTHING and escalates loudly instead — §6.3: "a degraded answer that looks
normal is worse than a refusal."

NOT AN OUTCOME AND NOT A CLAIM
------------------------------
Creating a Commitment says what WE now owe. 2I says what the WORLD did, and
only ⑯ — asynchronous, hours to months later — may write that. This module
imports neither bic.outcomes nor bic.claims and asserts no knowledge.

THE LLM REACHES NONE OF THIS
----------------------------
I5 — "the LLM proposes; the state machine decides". escalate() takes no
proposal, no prompt and no free text. The obligation comes from a closed set
keyed by the recovery decision, the owner from the existing identity
convention, the deadline from policy, and the lifecycle from 2B. There is no
argument through which generated text could reach any of them.
"""

from typing import Optional

from . import commitment as commitment_mod
from . import goal_lifecycle
from . import recovery as recovery_mod
from .db import DbError

# ── Escalation results ─────────────────────────────────────────────────────
RECORDED = "RECORDED"                    # a Commitment now exists
ALREADY_RECORDED = "ALREADY_RECORDED"    # this identity was already recorded
POLICY_REQUIRED = "INTERNAL_POLICY_REQUIRED"   # no approved due_on — see below
OWNER_UNRESOLVED = "OWNER_UNRESOLVED"    # 2B: owner is an AGENT, never null
ATTRIBUTION_MISSING = "ATTRIBUTION_MISSING"    # no party or no decision_ref
PERSISTENCE_FAILED = "PERSISTENCE_FAILED"      # the store refused or was down
NOT_APPLICABLE = "NOT_APPLICABLE"        # this recovery decision owes nothing

RESULTS = (RECORDED, ALREADY_RECORDED, POLICY_REQUIRED, OWNER_UNRESOLVED,
           ATTRIBUTION_MISSING, PERSISTENCE_FAILED, NOT_APPLICABLE)

# States in which the obligation is NOT durably recorded, so the owner alert
# is the only thing standing between the customer and silence.
UNRECORDED = (POLICY_REQUIRED, OWNER_UNRESOLVED, ATTRIBUTION_MISSING,
              PERSISTENCE_FAILED)

# ── Obligations — a CLOSED set, keyed by what actually failed ──────────────
# 2B lists `obligation` as a required assertion but does not enumerate values,
# so this stays as narrow as the one consumer needs. It is an identifier, not
# a sentence: free text here would become an unqueryable description column
# within a year, and generated free text would put model output in the field
# that says what the business owes.
DELIVER_PENDING_REPLY = "DELIVER_PENDING_REPLY"
OBLIGATIONS = (DELIVER_PENDING_REPLY,)

# The single recovery decision that leaves work outstanding. SAFE_TO_RETRY is
# still in flight, TERMINAL_FAILURE refused a specific message rather than
# leaving a promise open, NONE was delivered, and NOT_APPLICABLE never ran.
_OBLIGATION_FOR = {recovery_mod.HUMAN_REVIEW: DELIVER_PENDING_REPLY}


class EscalationError(RuntimeError):
    """A CALLER violated the escalation contract."""


def due_on_policy(obligation: str, *, now=None) -> Optional[None]:
    """The approved deadline for `obligation`. **There is none. Returns None.**

    THIS FUNCTION IS THE DOCUMENTED POLICY BOUNDARY, NOT A STUB TO FILL IN
    CASUALLY. The missing ruling is precise:

        "When the Brain cannot confirm that a reply reached a customer, by
         when must a human have resolved it?"

    Every candidate answer — one hour, four hours, next business day, 24h,
    48h — is a business commitment with consequences: it decides when Asthra
    is recorded as having MISSED a promise to a client, and 2B calls missed
    commitments "the reliability signal". Picking one here would mean this
    module had quietly authored the firm's service-level agreement.

    It is also not merely a duration. A real ruling has to settle whether the
    clock runs overnight and at weekends, whether a political client in an
    active campaign differs from a routine enquiry (2B offers `criticality`
    for exactly this), and who may waive it.

    Until an owner rules, this returns None and escalate() records nothing.
    A caller that HAS an approved deadline passes it explicitly — that path
    is live and tested, so the day the ruling exists it is one call away.
    """
    if obligation not in OBLIGATIONS:
        raise EscalationError(f"unknown obligation {obligation!r}")
    return None


def resolve_owner() -> str:
    """The accountable AGENT for autonomous Brain work.

    2B: "Every Commitment has an accountable owner (an AGENT). Never null."
    3B §1.5: for autonomous goals the owner is the human who authorised the
    automation, "inherited exactly as accountability is inherited on
    autonomous decisions".

    This REUSES bic.goal_lifecycle.AUTONOMOUS_OWNER rather than introducing a
    second owner vocabulary. That constant already carries this exact ruling
    for goals, including the deliberate choice not to copy a person's phone
    number into the record — accountability is resolved through the tenant,
    so no PII lands in a commitment row.
    """
    return goal_lifecycle.AUTONOMOUS_OWNER


def obligation_for(recovery_result: dict) -> Optional[str]:
    """The deterministic obligation implied by a recovery decision, or None.

    Deterministic and total: the same recovery decision always yields the same
    obligation, and a decision that leaves nothing outstanding yields None.
    """
    if not isinstance(recovery_result, dict):
        return None
    return _OBLIGATION_FOR.get(recovery_result.get("recovery"))


def escalate(recovery_result: dict, *, tenant_id: str, party: str,
             decision_ref: str, owner: str, subject: str = None,
             goal_ref: str = None, due_on=None, now=None) -> dict:
    """HUMAN_REVIEW → a durable 2B Commitment, when and only when it is safe.

    Returns a result dict; it does NOT raise on a store failure. An escalation
    path that can throw would turn "the reply may not have been delivered"
    into a 500 on a live customer webhook, and the customer would lose both
    the reply and the escalation.

    `subject` is the OBJECT of the promise and is legitimately absent here:
    what is owed is a reply to `party`, not something with its own identity.
    2B's identity is (tenant, subject, party, due_on) with NULLS NOT DISTINCT,
    so an absent subject is a VALUE — one open obligation per party per
    deadline, which is the dedupe this path wants.
    """
    obligation = obligation_for(recovery_result)
    if obligation is None:
        # NONE / SAFE_TO_RETRY / TERMINAL_FAILURE / NOT_APPLICABLE: nothing is
        # outstanding, so there is nothing to promise.
        return _result(NOT_APPLICABLE, recovery_result,
                       "this recovery decision leaves no outstanding obligation")

    # §7 — one attribution edge back to the Decision Record that created the
    # obligation, and a party to owe it to. Neither is inferable later.
    if not tenant_id or not party or not decision_ref:
        return _result(ATTRIBUTION_MISSING, recovery_result,
                       "a commitment needs a tenant, a party and the decision "
                       "that created the obligation")

    if not owner:
        return _result(OWNER_UNRESOLVED, recovery_result,
                       "2B requires an accountable owner (an AGENT), never null")

    deadline = due_on if due_on is not None else due_on_policy(obligation, now=now)
    if deadline is None:
        return _result(POLICY_REQUIRED, recovery_result,
                       "no approved due_on policy for an undelivered customer "
                       "reply — recording a commitment would invent the "
                       "deadline the business is later judged against")

    try:
        c = commitment_mod.make(
            tenant_id=tenant_id, party=party, obligation=obligation,
            due_on=deadline, owner=owner, subject=subject,
            decision_ref=decision_ref, goal_ref=goal_ref, at=now)
    except commitment_mod.CommitmentError as e:
        # Everything make() validates except the deadline has been checked
        # above, so a failure here is an unusable due_on — a policy that
        # supplied a past or unparseable date supplied no valid deadline.
        return _result(POLICY_REQUIRED, recovery_result,
                       f"supplied due_on is not usable: {e}")

    try:
        commitment_mod.save(c)
    except commitment_mod.CommitmentError:
        # save() raises this for a duplicate identity. Confirm by reading it
        # back rather than matching on the message text: the DATABASE's unique
        # index is the dedupe mechanism (§10), and this is just how the answer
        # gets back here.
        existing = _existing(tenant_id, party, deadline, subject)
        if existing is not None:
            # Report the STORED row, never the one just built: `c` carries a
            # fresh commitment_id that was never persisted, and handing it
            # back would name an obligation that does not exist.
            return _result(ALREADY_RECORDED, recovery_result,
                           "this obligation was already recorded", existing)
        return _result(PERSISTENCE_FAILED, recovery_result,
                       "commitment rejected by the store")
    except DbError:
        # Type only — a store error body can echo an identifier.
        return _result(PERSISTENCE_FAILED, recovery_result,
                       "commitment store unavailable")

    return _result(RECORDED, recovery_result, "obligation recorded", c)


def _existing(tenant_id, party, due_on, subject) -> Optional[dict]:
    """Read back by the 2B identity tuple. The DATABASE's unique index is the
    dedupe mechanism (§10); this is only how its answer gets back here."""
    try:
        return commitment_mod.find(tenant_id, party=party, due_on=due_on,
                                   subject=subject)
    except (commitment_mod.CommitmentError, DbError):
        return None


def _result(state: str, recovery_result, reason: str, c: dict = None) -> dict:
    rec = (recovery_result or {}).get("recovery")
    return {
        "escalation": state,
        # The recovery decision is PRESERVED, never replaced. A commitment
        # that could not be recorded does not stop a human being needed.
        "recovery": rec,
        "needs_human": rec == recovery_mod.HUMAN_REVIEW,
        "recorded": state in (RECORDED, ALREADY_RECORDED),
        "reason": reason,
        "obligation": (c or {}).get("obligation"),
        "commitment_id": (c or {}).get("commitment_id"),
    }


def owner_note(result: dict) -> str:
    """One deterministic line for the EXISTING owner alert (§13).

    Carries no commitment_id, no decision_ref, no party id and no packet id:
    3A's owner-facing convention in this codebase is a phone link and a plain
    instruction, and an internal UUID in a WhatsApp message is unusable to the
    person reading it and a disclosure if the phone is shared.
    """
    return _NOTES.get(result.get("escalation"), "")


_NOTES = {
    RECORDED: "📌 Recorded as an open commitment — it will appear in the "
              "daily digest until it is closed.",
    ALREADY_RECORDED: "📌 Already recorded as an open commitment.",
    POLICY_REQUIRED: "⛔ NOT recorded: no approved deadline policy exists for "
                     "an undelivered reply, so this is not tracked anywhere. "
                     "Handle it now, then set the policy.",
    OWNER_UNRESOLVED: "⛔ NOT recorded: no accountable owner could be "
                      "resolved. Handle it now.",
    ATTRIBUTION_MISSING: "⛔ NOT recorded: the originating decision could not "
                         "be identified. Handle it now.",
    PERSISTENCE_FAILED: "⛔ NOT recorded: the commitment store did not accept "
                        "it. Handle it now.",
    NOT_APPLICABLE: "",
}


def describe(result: dict) -> dict:
    """Bounded, non-PII view for tracing. No ids of any kind."""
    return {"escalation": result.get("escalation"),
            "recovery": result.get("recovery"),
            "recorded": result.get("recorded"),
            "obligation": result.get("obligation"),
            "needs_human": result.get("needs_human")}
