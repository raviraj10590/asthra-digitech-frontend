"""The first real Brain decision loop (IDD-3A stage ⑨, smallest possible slice).

SCOPE. This is NOT the 3C DecisionEngine, NOT a planner (3B), NOT the full 3A
orchestrator. It is the smallest function that makes one thing true for one
real decision point: **the LLM's proposal is not the final decision.**

Stages this module owns, in IDD-3A's own numbering:
  ③/④ INTERPRET/GOAL — admit_goal(): deterministic keyword admission for the
                   ONE registered goal whose predicates actually exist
                   (social_media_enquiry). No model, no classifier, no
                   guessing; anything unmatched is UNSUPPORTED and the caller
                   keeps its existing behaviour.
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


# ── ③/④ INTERPRET → GOAL admission ─────────────────────────────────────────
# Deterministic markers for the ONE supported goal, taken from the service
# vocabulary the bot ALREADY uses for this row (its own menu description:
# "Instagram, FB, YouTube ನಿರ್ವಹಣೆ" / "Social Media ನಿರ್ವಹಣೆ"). Inventing a
# fresh vocabulary here would create a second, drifting definition of what
# counts as this service.
#
# WHY A CLOSED KEYWORD SET AND NOT A CLASSIFIER (IDD-3B §0.1, 2H goals.py):
# a model deciding WHICH goal applies would let a customer's phrasing select
# the goal — and the goal decides which facts are required and how good they
# must be. Admission must not be negotiable by whoever wrote the message.
#
# SAFE BY TIER, NOT ONLY BY MATCH. social_media_enquiry is risk tier 1, the
# LOWEST. A false positive therefore admits the least demanding goal that
# exists; it can never escalate a turn into a higher-risk action. Admitting
# any tier >= 2 goal from text would be a different decision and is out of
# scope for this slice (transformer/real-estate stay unreachable — their
# predicates are not registered).
_SOCIAL_MARKERS = (
    "social media", "socialmedia", "instagram", "insta", "facebook",
    "youtube", "linkedin", "ಸೋಶಿಯಲ್", "ಇನ್ಸ್ಟಾಗ್ರಾಂ", "ಫೇಸ್‌ಬುಕ್",
)

UNSUPPORTED = "UNSUPPORTED"


def admit_goal(text: str) -> Optional[dict]:
    """③/④ — the admission gate for this slice. Returns the registered goal
    definition, or None meaning UNSUPPORTED.

    None is NOT a failure and NOT a refusal: it means this first Brain slice
    does not cover the request, and the caller must fall back to its existing
    safe behaviour (IDD-3A ④ "not every intent becomes a goal"). Refusing
    every unmatched message would replace the whole bot in one step, which
    this slice explicitly must not do.
    """
    t = (text or "").lower()
    if not any(marker in t for marker in _SOCIAL_MARKERS):
        return None
    return goals.lookup(GOAL_ID)


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


def authorize(principal, packet: dict, goal_def: dict, tenant_id: str) -> dict:
    """⑩ AUTHORIZE. Reuses what already exists — bic.policy's role ordering
    (via the Principal the caller resolved) and 2H's own tier-ceiling verdict
    (already computed inside the packet). No new authorization system, no
    new registry row, no new descriptor.

    Returns {"allowed": bool, "reason": str}.
    """
    if packet.get("tenant_id") != tenant_id:
        return {"allowed": False, "reason": "tenant mismatch"}
    if packet.get("goal_ref") != goal_def["goal_id"]:
        return {"allowed": False, "reason": "goal mismatch"}
    role = getattr(principal, "role", None)
    if role != "CLIENT":
        return {"allowed": False,
               "reason": f"not a customer-facing principal (role={role!r})"}
    ceiling = packet["principal"]["risk_tier_ceiling"]
    if ceiling is not None and goal_def["risk_tier"] > ceiling:
        return {"allowed": False,
               "reason": "goal risk tier exceeds principal's ceiling"}
    return {"allowed": True,
           "reason": "tenant, goal, role and tier ceiling all hold"}
