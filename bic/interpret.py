"""Stage ③ INTERPRET — message text → a structured, bounded interpretation.

WHAT THIS IS FOR (IDD-3A §0.3 C3)
---------------------------------
    "Intent → Goal → Context → Sufficiency → Plan. Intent and goal determine
     WHICH SLOTS ARE REQUIRED; context fills them."

So interpretation runs BEFORE goal admission and decides only one thing: is
there a goal candidate here at all, and is it unambiguous enough to admit?
It never decides what is TRUE about the customer — that is 2C/2H's job, from
recorded evidence.

NO MODEL RUNS HERE, EVER
------------------------
A model choosing the goal would let a customer's phrasing select which facts
are required and how good they must be (2H §4.4 — sufficiency is a property
of the (evidence, action) pair). Admission would become negotiable by
whoever wrote the message. This module therefore imports no provider, and
its tests assert that it cannot.

INTERPRETATION IS NOT EVIDENCE
------------------------------
`slots` below records what the MESSAGE mentioned — an unverified observation
of the customer's own words. It is deliberately NOT fed into the Context
Packet: doing so would let a customer fill their own evidence slot by
asserting it, which is exactly the failure 2H's gate exists to prevent. The
field exists so the interpretation is explainable, not so it can be believed.

BOUNDED UNCERTAINTY
-------------------
Confidence is capped at CONFIDENCE_CAP. Everything this module can ever know
comes from the customer's own message, which is a tier-5 self-declaration
(2C provenance tiers, Article II.6, capped 0.50). An interpretation cannot
be more trustworthy than the single source it is derived from.

UNDER-ADMISSION IS THE SAFE DIRECTION
-------------------------------------
UNSUPPORTED and AMBIGUOUS both mean "this slice does not cover the request",
and the caller keeps its existing behaviour (IDD-3A ④: "not every intent
becomes a goal"). A false negative costs one legacy reply. A false positive
puts a turn through a goal whose evidence bar was chosen for a different
question — so when the two are in tension, this module refuses to admit.
"""

import re
from typing import Optional

# ── Interpretation states ──────────────────────────────────────────────────
CLEAR = "CLEAR"                # one supported intent, safe to admit
AMBIGUOUS = "AMBIGUOUS"        # a supported marker fired, but not decisively
UNSUPPORTED = "UNSUPPORTED"    # nothing this slice covers
STATES = (CLEAR, AMBIGUOUS, UNSUPPORTED)

# ── Why an interpretation was not CLEAR. Bounded set, never free text ──────
MULTI_INTENT = "MULTI_INTENT"    # another service named alongside this one
NEGATED = "NEGATED"              # the marker appears under a negation
INCIDENTAL = "INCIDENTAL"        # the word is present but not as a service ask
AMBIGUITY_KINDS = (MULTI_INTENT, NEGATED, INCIDENTAL)

# 2C tier 5 / Article II.6 — a party telling us something is worth 0.50,
# however emphatically they tell us. An interpretation derived from that one
# source cannot exceed it.
CONFIDENCE_CAP = 0.50

GOAL_SOCIAL = "social_media_enquiry"

# ── Vocabulary ─────────────────────────────────────────────────────────────
# Taken from the service row this bot ALREADY uses for social media (its own
# menu description: "Instagram, FB, YouTube ನಿರ್ವಹಣೆ" / "Social Media
# ನಿರ್ವಹಣೆ"). Not expanded beyond terms already in the repository.
_SOCIAL_MARKERS = (
    "social media", "socialmedia", "instagram", "insta", "facebook",
    "youtube", "linkedin", "ಸೋಶಿಯಲ್", "ಇನ್ಸ್ಟಾಗ್ರಾಂ", "ಫೇಸ್‌ಬುಕ್",
)

# The OTHER services on the same menu. Used only to detect a competing
# intent — never to admit one, since no other goal has registered predicates.
_OTHER_SERVICE_MARKERS = (
    "website", "web site", "app", "mobile app", "e-commerce", "ecommerce",
    "election", "campaign", "mla", "mp", "chatbot", "bot", "automation",
    "google ads", "digital ads", "advertisement", "govt", "government",
    "scheme", "logo", "poster", "brochure", "branding", "design",
    "ವೆಬ್‌ಸೈಟ್", "ಚುನಾವಣಾ", "ಜಾಹೀರಾತು", "ಸರ್ಕಾರಿ",
)

# "install instagram" is a phone-support question, not a service enquiry.
_INCIDENTAL_MARKERS = (
    "install", "installing", "installation", "download", "downloading",
    "uninstall", "app store", "play store", "password", "hack", "hacked",
    "login", "log in", "recover",
)

# Negation scoped to the same message. Deliberately small and literal: a
# general negation parser would be a guess engine, and guessing is the one
# thing this module must not do.
_NEGATIONS = (
    "don't need", "dont need", "do not need", "not need", "don't want",
    "dont want", "do not want", "not interested", "no need", "not looking",
    "already have", "ಬೇಡ",
)


def _boundary_re(markers):
    """Word-boundary matcher. A bare `in` test made "insta" match "install",
    "instant" and "instantly". `(?<!\\w)…(?!\\w)` rather than `\\b` because
    the Kannada markers are \\w runs too, and \\b behaves differently around
    them than around ASCII."""
    return re.compile("|".join(rf"(?<!\w){re.escape(m)}(?!\w)" for m in markers))


_SOCIAL_RE = _boundary_re(_SOCIAL_MARKERS)
_OTHER_RE = _boundary_re(_OTHER_SERVICE_MARKERS)
_INCIDENTAL_RE = _boundary_re(_INCIDENTAL_MARKERS)


def _normalise(text: str) -> str:
    """Lowercase and collapse internal whitespace.

    NORMALISATION, NOT VOCABULARY. "social  media" (a stray double space, or
    a line break) is the same two words as "social media" and must interpret
    identically; without this it silently fell to UNSUPPORTED. This adds no
    terms and changes no meaning — it only stops typography from deciding
    whether a goal is admitted.
    """
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _found(pattern, text) -> list:
    return sorted(set(m.group(0) for m in pattern.finditer(text)))


def _negated(text: str) -> bool:
    return any(n in text for n in _NEGATIONS)


def _result(state, *, intent=None, goal_candidate=None, slots=None,
            ambiguity=None, confidence=0.0, evidence=()) -> dict:
    return {
        "interpretation_state": state,
        "intent": intent,
        "goal_candidate": goal_candidate,
        # What the MESSAGE mentioned. An unverified observation of the
        # customer's own words — never evidence, never sent to 2H.
        "slots": dict(slots or {}),
        "ambiguity": ambiguity,
        "confidence": round(min(confidence, CONFIDENCE_CAP), 4),
        # The bounded markers that fired, so the interpretation explains
        # itself from its own vocabulary rather than echoing the message.
        "evidence": list(evidence),
    }


def interpret(text: str) -> dict:
    """Deterministic. Same input, same output, no I/O, no model.

    Returns the interpretation packet described in this module's docstring.
    Only ever proposes `social_media_enquiry` — the one goal whose
    predicates are actually registered.
    """
    t = _normalise(text)
    social = _found(_SOCIAL_RE, t)
    if not social:
        return _result(UNSUPPORTED)

    # ── Not a service enquiry at all ────────────────────────────────────
    if _negated(t):
        return _result(AMBIGUOUS, ambiguity=NEGATED, evidence=social)
    incidental = _found(_INCIDENTAL_RE, t)
    if incidental:
        return _result(UNSUPPORTED, ambiguity=INCIDENTAL, evidence=social)

    # ── A competing service named in the same breath ────────────────────
    # "website and instagram" names two services; picking one would be a
    # guess, and the other has no registered predicates to admit anyway.
    other = _found(_OTHER_RE, t)
    if other:
        return _result(AMBIGUOUS, ambiguity=MULTI_INTENT, evidence=social)

    # ── CLEAR ───────────────────────────────────────────────────────────
    # `service_interest` is the one required slot of this goal that a
    # message can even mention. `first_contact` is a retrieval fact about
    # our own records and is unknowable from text — it is reported missing
    # rather than guessed.
    slots = {
        "service_interest": {"observed": True, "source": "message_text",
                             "verified": False},
        "first_contact": {"observed": False, "source": None,
                          "verified": False},
    }
    return _result(CLEAR, intent=GOAL_SOCIAL, goal_candidate=GOAL_SOCIAL,
                   slots=slots, confidence=CONFIDENCE_CAP, evidence=social)


def goal_candidate_of(text: str) -> Optional[str]:
    """The goal id to admit, or None. CLEAR is the only admitting state —
    AMBIGUOUS and UNSUPPORTED both mean 'not this slice'."""
    r = interpret(text)
    return r["goal_candidate"] if r["interpretation_state"] == CLEAR else None
