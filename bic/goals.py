"""Registered business goals — DATA, not logic (IDD-2H §2, §9.1).

WHY THIS FILE IS SEPARATE FROM bic/context.py
----------------------------------------------
The Context Plane must contain no industry vocabulary. Acceptance criterion 32
is "count packet-structure changes when adding a vertical: exactly zero", and a
`transformer` branch inside the engine would break that on the first vertical
and every one after.

So the split is deliberate and load-bearing:

    bic/context.py   the mechanism   — generic, vertical-free, tested to be so
    bic/goals.py     the vocabulary  — every industry word lives HERE

Adding a vertical adds entries below. It touches no engine code, changes no
packet structure, and needs no migration.

WHY A CLOSED SET, AND NOT INFERRED FROM TEXT
--------------------------------------------
A goal decides which facts are REQUIRED and, through its risk tier, how good
those facts must be. Inferring it from free text would let a customer's
phrasing lower the evidence bar for a quotation — the gate would be
negotiable by whoever wrote the message. The caller names the goal, or there
is no goal.

RISK TIERS ARE THE POINT, NOT A LABEL
-------------------------------------
§4.4: sufficiency is a property of the (evidence, action) pair. The tier here
is what makes the SAME customer fact sufficient to answer an enquiry and
insufficient to price a transformer.
"""

from .context import (BUSINESS, OBTAINABLE_BY_ASKING, OBTAINABLE_BY_RETRIEVAL,
                      goal, slot)

# Predicates already live and registered in production (2A).
INTEREST = "core.party.declared_service_interest@1"
FIRST_SEEN = "core.party.first_seen_at@1"
# The first BUSINESS-scoped predicate — about Asthra, not about a
# counterparty. Registered by 20260827000020 with applies_to ORGANIZATION.
NEW_ENQUIRIES = "biz.pipeline.new_enquiries_per_month@1"

# ── The registry ───────────────────────────────────────────────────────────
# NOTE ON THE VERTICAL PREDICATES BELOW. `mfg.*` and `realestate.*` are NOT
# registered in the semantic registry today, and that is not an oversight —
# registering a predicate is a deliberate 2A act with a frozen meaning. Until
# they are, knowledge.describe reports them as unregistered and the gate
# reports the slot as unfillable, WITH THAT REASON. A goal that names a
# predicate nobody can record is exactly the kind of gap this layer exists to
# make visible rather than to paper over.
def _with_lifecycle(goal_def: dict, *, completion: str, goal_type: str) -> dict:
    """Attach the 3B lifecycle declaration to a 2H goal definition.

    Added HERE rather than inside context.goal() on purpose: the completion
    condition is goal DATA, and this file is where goal data lives. 2H's
    builder stays a pure sufficiency concern and ignores these keys, so the
    two contracts do not grow into each other.

    §1.4: a goal with no completion condition may not be admitted. Declaring
    it beside the goal — not in the engine — is what keeps that gate a
    property of the goal rather than a special case in code.
    """
    return {**goal_def, "completion": completion, "goal_type": goal_type}


GOALS = {
    # EPHEMERAL (§1.2): one turn, working memory, no persistence — the IDD's
    # own example of this type is "answer a question". Completion is
    # RESPONSE_DELIVERED: the enquiry was actually answered. Deliberately NOT
    # "became a customer" — that is a business outcome with no observable
    # source today, and asserting it from a reply would be inventing a result.
    "social_media_enquiry": _with_lifecycle(goal(
        "social_media_enquiry", 1,
        [slot("service_interest", INTEREST, OBTAINABLE_BY_ASKING),
         slot("first_contact", FIRST_SEEN, OBTAINABLE_BY_RETRIEVAL)],
        "Answer a social-media marketing enquiry"),
        completion="RESPONSE_DELIVERED", goal_type="EPHEMERAL"),

    "real_estate_enquiry": goal(
        "real_estate_enquiry", 2,
        [slot("service_interest", INTEREST, OBTAINABLE_BY_ASKING),
         slot("budget", "realestate.enquiry.budget@1", OBTAINABLE_BY_ASKING),
         slot("locality", "realestate.enquiry.locality@1",
              OBTAINABLE_BY_ASKING)],
        "Qualify a real-estate enquiry"),

    # ── The first BUSINESS-scoped goal ─────────────────────────────────────
    # "What should I focus on this month?" — a question about Asthra, not
    # about a counterparty. It exists to ASSEMBLE AND ASSESS, nothing more:
    # no recommendation is produced anywhere in this slice, so the goal
    # deliberately declares no completion condition and no goal_type. Those
    # are 3B lifecycle concerns and adding them here would claim a goal that
    # can be worked, which nothing yet can do.
    #
    # TIER 2, not 1. The owner acts on the answer — a wrong monthly figure
    # redirects real spend — so it clears the 0.60 floor rather than tier 1's
    # 0.50. Deliberately NOT tier 3: that would demand 0.80, above the 0.70
    # cap a tier-3 derived fact can ever carry (2C §6), so the goal could
    # never be satisfiable by its own evidence however healthy the pipeline.
    #
    # OBTAINABLE_BY_RETRIEVAL, not ASKING: nobody can answer "how many new
    # enquiries" by being asked — the number is measured from first_seen_at
    # by the daily producer. If it is missing the fix is a refresh, not a
    # conversation, and the gate should say RETRIEVE.
    "business_month_review": goal(
        "business_month_review", 2,
        [slot("new_enquiries", NEW_ENQUIRIES, OBTAINABLE_BY_RETRIEVAL)],
        "Assemble what the Brain knows about the business this month",
        scope=BUSINESS),

    "transformer_quotation": goal(
        "transformer_quotation", 4,
        [slot("kva_rating", "mfg.transformer.kva_rating@1",
              OBTAINABLE_BY_ASKING),
         slot("quantity", "mfg.transformer.quantity@1", OBTAINABLE_BY_ASKING),
         slot("voltage", "mfg.transformer.voltage@1", OBTAINABLE_BY_ASKING),
         slot("delivery_location", "mfg.transformer.delivery_location@1",
              OBTAINABLE_BY_ASKING)],
        "Prepare a transformer quotation"),
}


def lookup(goal_id: str):
    """A registered goal, or None. Never a guess and never a default.

    Falling back to a 'general' goal would silently answer a different
    question than the one asked, at whatever risk tier that default carried.
    """
    return GOALS.get((goal_id or "").strip().lower()) or None


def known_ids() -> list:
    return sorted(GOALS)
