"""Stage ⑮ execution recovery — what the Brain does about a failed action.

    "⑮ Respond | Brain → Channel | Send fails | Retry idempotently; queue for
     human" (IDD-3A §1.2)

THE INVARIANT THAT DECIDES EVERY CASE HERE
------------------------------------------
    I13 — "Non-idempotent actions are never auto-retried."
    Criterion 15 — "Non-idempotent write fails ambiguously →
                    ESCALATED, NEVER AUTO-RETRIED."

A WhatsApp send is NOT idempotent: sending twice delivers two messages. So
"retry idempotently" cannot mean "retry the send because it looked like it
failed". It may only mean: retry when the channel PROVED nothing was
delivered. Everything else escalates.

§9.1 names I13 as one of the four invariants that will come under pressure,
and the exact pressure is *"It probably didn't go through, just retry it."*
That sentence is the bug. "Probably" is the ambiguity the invariant forbids.

SO THE WHOLE CLASSIFIER TURNS ON ONE QUESTION
---------------------------------------------
Did the channel answer us?

  answered + rejected (429, 5xx)  the channel told us it did NOT accept the
                                  message. No delivery happened, so a retry
                                  cannot duplicate one.  → SAFE_TO_RETRY
  answered + refused (4xx)        malformed or unauthorised. A byte-identical
                                  retry fails identically.  → TERMINAL_FAILURE
  never answered (timeout, conn)  the request may have reached the channel and
                                  the reply was lost. Delivery is UNKNOWABLE
                                  from here.  → HUMAN_REVIEW, never a retry
  unreadable result               same ambiguity.  → HUMAN_REVIEW

WHY THE BOUND IS TWO ATTEMPTS
-----------------------------
§5.1 sets per-turn budgets but names no send-retry budget. The only
"try again" allowance the IDD does state is AI consultations: **2** — "one
primary, one fallback". This reuses that number rather than inventing one, and
two attempts sit far inside the 25 s wall-clock budget with no sleep between
them. Stated as a derivation, not as a rule the IDD contains.

NOT AN OUTCOME, AND NOT A NEW QUEUE
-----------------------------------
Recovery is what the BRAIN did about an execution result. 2I is what the WORLD
did afterwards. This module writes no outcome, no claim, and no row anywhere —
it returns a decision and lets the caller act on it through mechanisms that
already exist.
"""

from typing import Optional

from . import observe as obs_mod

# ── Recovery decisions ─────────────────────────────────────────────────────
NONE = "NONE"                          # nothing to recover — it worked
SAFE_TO_RETRY = "SAFE_TO_RETRY"        # channel proved no delivery occurred
HUMAN_REVIEW = "HUMAN_REVIEW"          # delivery uncertain — escalate, never retry
TERMINAL_FAILURE = "TERMINAL_FAILURE"  # a retry cannot succeed
NOT_APPLICABLE = "NOT_APPLICABLE"      # nothing was attempted
DECISIONS = (NONE, SAFE_TO_RETRY, HUMAN_REVIEW, TERMINAL_FAILURE,
             NOT_APPLICABLE)

# Derived from §5.1's only stated try-again budget (AI consultations: 2 —
# "one primary, one fallback"). One original attempt plus at most one retry.
MAX_ATTEMPTS = 2

# Failure classes the channel reports when it has explicitly NOT accepted the
# message. Reuses the Decision Record's vocabulary — no second taxonomy.
_RETRYABLE_WHEN_ANSWERED = ("CONNECTION",)


class RecoveryError(RuntimeError):
    """A CALLER violated the recovery contract."""


def classify(observation: Optional[dict], *, attempt: int = 1) -> dict:
    """Deterministic. Returns the recovery decision for one observation.

    `attempt` is 1-based and counts attempts already MADE. Returns
    HUMAN_REVIEW once the bound is reached, so exhaustion escalates rather
    than silently giving up (§6.2 T4: "never silence").
    """
    if observation is None:
        raise RecoveryError("recovery needs an observation to classify")
    if not isinstance(attempt, int) or attempt < 1:
        raise RecoveryError("attempt must be a positive integer")

    if not observation.get("attempted"):
        return _result(NOT_APPLICABLE, "no execution was attempted", attempt)

    if obs_mod.delivered(observation):
        return _result(NONE, "delivered", attempt)

    answered = bool(observation.get("channel_responded"))
    failure = observation.get("failure_class")

    if not answered:
        # I13 / criterion 15. The request may have landed; we cannot know.
        # Retrying here is the one move that can double-send a customer.
        return _result(HUMAN_REVIEW,
                       "channel never answered — delivery is ambiguous and a "
                       "non-idempotent send may not be auto-retried",
                       attempt)

    if failure in _RETRYABLE_WHEN_ANSWERED:
        if attempt >= MAX_ATTEMPTS:
            return _result(HUMAN_REVIEW,
                           f"retry budget of {MAX_ATTEMPTS} attempts exhausted",
                           attempt)
        return _result(SAFE_TO_RETRY,
                       "channel answered and did not accept the message, so "
                       "no delivery occurred and a retry cannot duplicate one",
                       attempt)

    # PERMISSION / VALUE / anything else the channel actively refused.
    return _result(TERMINAL_FAILURE,
                   f"channel refused with {failure}; an identical retry fails "
                   f"identically", attempt)


def _result(decision: str, reason: str, attempt: int) -> dict:
    return {"recovery": decision, "reason": reason, "attempt": attempt,
            "max_attempts": MAX_ATTEMPTS,
            "may_retry": decision == SAFE_TO_RETRY,
            "needs_human": decision == HUMAN_REVIEW}


def should_retry(observation: Optional[dict], *, attempt: int = 1) -> bool:
    """The single question the caller may ask before sending again."""
    return classify(observation, attempt=attempt)["recovery"] == SAFE_TO_RETRY


def describe(result: dict) -> dict:
    """Bounded, non-PII view for tracing."""
    return {"recovery": result.get("recovery"), "attempt": result.get("attempt"),
            "max_attempts": result.get("max_attempts"),
            "needs_human": result.get("needs_human")}
