"""The first real Brain decision loop (IDD-3A stage ⑨, smallest possible slice).

SCOPE. This is NOT the 3C DecisionEngine, NOT a planner (3B), NOT the full 3A
orchestrator. It is the smallest function that makes one thing true for one
real decision point: **the LLM's proposal is not the final decision.**

Stages this module owns, in IDD-3A's own numbering:
  ④ GOAL        — admit_goal(): looks up the candidate that stage ③
                   (bic/interpret.py) proposed. bic/goals.py stays the
                   source of goal data; only CLEAR interpretations admit,
                   and anything else keeps the caller's existing behaviour.
  ⑤ CONTEXT     — assemble_context(): a thin pass-through to the existing
                   bic.context engine. Not duplicated, not modified.
  ⑥ SUFFICIENCY — read from the packet bic.context already computed.
  ⑨ DECIDE      — decide(): adjudicates the (sufficiency, LLM proposal) pair.
  ⑩ AUTHORIZE   — authorize(): reuses bic.policy's role ordering and 2H's own
                   tier-ceiling verdict. No new authorization system, no new
                   registry row.

Stage ⑧ CONSULT (the LLM call itself) is NOT here — the caller (api/webhook.py)
still owns provider selection and prompting, unchanged. This module only ever
receives the LLM's proposal as a plain string; it never calls a provider.

Stage ⑦ PLAN is intentionally absent (IDD-3B §0.1: most turns are
single-action and skip planning; this is exactly that case).
"""

from typing import Optional

from . import context as ctx_mod
from . import goals
from . import interpret as interpret_mod

GOAL_ID = "social_media_enquiry"

PROCEED, CLARIFY, REFUSE, ESCALATE = "PROCEED", "CLARIFY", "REFUSE", "ESCALATE"
OUTCOMES = (PROCEED, CLARIFY, REFUSE, ESCALATE)

# 2H's RETRIEVE means "the SYSTEM should fetch or re-confirm the item" (IDD-2H
# §4.2) — no automated retrieval capability is wired in this slice, and
# guessing or asking the CUSTOMER for something the system was supposed to go
# get would misattribute whose job it is. Mapped to REFUSE: the conservative,
# no-guessing choice. Known limitation, not a hidden bug — see the task
# report for the concrete case (a returning customer whose first-contact
# claim was never backfilled) this can affect.
_SUFFICIENCY_TO_OUTCOME = {
    ctx_mod.PROCEED: PROCEED,
    ctx_mod.CLARIFY: CLARIFY,
    ctx_mod.RETRIEVE: REFUSE,
    ctx_mod.ESCALATE: ESCALATE,
    ctx_mod.REFUSE: REFUSE,
}

REFUSAL_TEXT = ("ಕ್ಷಮಿಸಿ 🙏 ಈ ಸಂದೇಶಕ್ಕೆ ಸುರಕ್ಷಿತವಾಗಿ ಮುಂದುವರಿಯಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ. "
              "ನಮ್ಮ ತಂಡ ಶೀಘ್ರದಲ್ಲೇ ಸಂಪರ್ಕಿಸುತ್ತದೆ 🙏")
ESCALATE_TEXT = ("ಇದು ನಮ್ಮ ತಂಡದ ಗಮನ ಬಯಸುತ್ತದೆ 🙏 ಶೀಘ್ರದಲ್ಲೇ ಒಬ್ಬರು ನಿಮ್ಮನ್ನು "
                 "ಸಂಪರ್ಕಿಸುತ್ತಾರೆ.")


def recognize_goal(goal_id: str = GOAL_ID) -> Optional[dict]:
    """④ GOAL by NAME. The caller names the goal; None for anything
    unregistered — 'unknown', never a guess or a default.
    """
    return goals.lookup(goal_id)


# ── ④ GOAL admission ───────────────────────────────────────────────────────
UNSUPPORTED = "UNSUPPORTED"


def admit_goal(text: str) -> Optional[dict]:
    """④ — the admission gate. Stage ③ INTERPRET proposes a goal candidate;
    this looks it up in the registry, which stays the source of goal data.

    Returns the registered goal definition, or None. None is NOT a failure
    and NOT a refusal: it means this first Brain slice does not cover the
    request (UNSUPPORTED or AMBIGUOUS), and the caller must fall back to its
    existing safe behaviour (IDD-3A ④ "not every intent becomes a goal").
    Refusing every unmatched message would replace the whole bot in one step,
    which this slice explicitly must not do.

    SAFE BY TIER. social_media_enquiry is risk tier 1, the LOWEST — so even a
    false-positive admission takes the least demanding goal that exists and
    can never escalate a turn. Admitting any tier >= 2 goal from text would
    be a different decision, out of scope here (transformer/real-estate stay
    unreachable — their predicates are not registered).
    """
    candidate = interpret_mod.goal_candidate_of(text)
    if candidate is None:
        return None
    return goals.lookup(candidate)


def assemble_context(tenant_id: str, request_text: str, principal, goal_def: dict,
                     subject: str, *, describe) -> dict:
    """⑤ CONTEXT. Delegates entirely to the existing engine — this function
    exists only to name the stage, not to add logic.
    """
    return ctx_mod.assemble(tenant_id, request_text, principal, goal_def,
                            subject, describe=describe)


def refusal_result(reason: str) -> dict:
    """The one deterministic refusal shape, shared by every REFUSE path
    (insufficient evidence, denied authorization, missing proposal) so a
    caller never has to construct refusal text itself.
    """
    return {"outcome": REFUSE, "text": REFUSAL_TEXT, "reason": reason}


def decide(goal_def: dict, packet: dict, llm_proposal: Optional[str]) -> dict:
    """⑨ DECIDE. The smallest function that makes LLM proposal != final
    decision: it adjudicates the ALREADY-COMPUTED 2H sufficiency verdict, and
    the LLM is never asked whether the system should act — only what to say
    when the answer is yes.

    Returns {"outcome": one of OUTCOMES, "text": str, "reason": str}.
    """
    verdict = packet["epistemic"]["sufficiency"]["verdict"]
    outcome = _SUFFICIENCY_TO_OUTCOME[verdict]

    if outcome == PROCEED:
        if not llm_proposal:
            # Sufficiency said PROCEED but there is nothing safe to send.
            # Never invent a reply — same rule as a missing fact.
            return refusal_result("sufficiency PROCEED but no LLM proposal "
                                  "was available")
        return {"outcome": PROCEED, "text": llm_proposal,
               "reason": "sufficiency PROCEED; proposal authorised for execution"}

    if outcome == CLARIFY:
        # Deterministic. The missing slot NAME comes from the packet, which
        # bic.context computed without any model. The LLM proposal is never
        # used here — it cannot know which fact is missing without guessing
        # one, and a guessed fact is exactly what this gate exists to refuse.
        gaps = packet["epistemic"]["sufficiency"]["gaps"]
        names = ", ".join(g["slot"] for g in gaps) or "a required detail"
        text = f"ಇದಕ್ಕೆ ಸಹಾಯ ಮಾಡಲು, ದಯವಿಟ್ಟು ತಿಳಿಸಿ: {names} 🙏"
        return {"outcome": CLARIFY, "text": text, "reason": f"missing: {names}"}

    if outcome == ESCALATE:
        return {"outcome": ESCALATE, "text": ESCALATE_TEXT,
               "reason": packet["epistemic"]["sufficiency"]["reason"]}

    return refusal_result(packet["epistemic"]["sufficiency"]["reason"])


def authorize(principal, packet: dict, goal_def: dict, tenant_id: str,
              expected_role: str = "CLIENT") -> dict:
    """⑩ AUTHORIZE. Reuses what already exists — bic.policy's role ordering
    (via the Principal the caller resolved) and 2H's own tier-ceiling verdict
    (already computed inside the packet). No new authorization system, no
    new registry row, no new descriptor.

    `expected_role` DEFAULTS TO CLIENT, so every existing caller behaves
    byte-identically. It exists because the role was previously a literal in
    the comparison below, which made this function structurally unusable for
    any principal other than a customer — a future OWNER action path would
    have had to either loosen this check for everyone or write a second one.
    Naming the expectation is the smallest change that leaves both options
    open without taking either.

    NOTHING PASSES OWNER TODAY, DELIBERATELY. The OWNER business status
    command is advisory: it authorizes no action and therefore never calls
    this function. Enabling OWNER action authorization is a separate decision
    with its own risk tier and its own approval, and adding the parameter
    must not be mistaken for having made it.

    Returns {"allowed": bool, "reason": str}.
    """
    if packet.get("tenant_id") != tenant_id:
        return {"allowed": False, "reason": "tenant mismatch"}
    if packet.get("goal_ref") != goal_def["goal_id"]:
        return {"allowed": False, "reason": "goal mismatch"}
    role = getattr(principal, "role", None)
    if role != expected_role:
        return {"allowed": False,
               "reason": f"not a customer-facing principal (role={role!r})"}
    ceiling = packet["principal"]["risk_tier_ceiling"]
    if ceiling is not None and goal_def["risk_tier"] > ceiling:
        return {"allowed": False,
               "reason": "goal risk tier exceeds principal's ceiling"}
    return {"allowed": True,
           "reason": "tenant, goal, role and tier ceiling all hold"}
