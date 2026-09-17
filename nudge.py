"""Ask again, once, when a customer never answered.

WHY THIS EXISTS
---------------
Owner's ruling, 2026-09-17: "if they not replied your question you ask them
one hour later again."

The 2026-09-17 Mangalore enquiry is the case. The reply asked what the
transformer was for; the customer answered something the parser could not
read; the bot acknowledged and went quiet. Nobody asked again, and the
enquiry sat at status 'new' with a quotation request in it.

A question that goes unanswered costs nothing to repeat and everything to
forget.

WHAT THIS IS NOT
----------------
It is not a drip campaign. ONE nudge per unanswered question, and a customer
who says anything at all — even something unreadable — has replied, so they
are never nudged for that turn again. Six guards below exist to keep a
helpful nudge from becoming the reason someone blocks the number.

NO I/O AND NO CLOCK OF ITS OWN. Pure functions over values the caller has
already fetched, so every rule is testable without a network, a database or
a fixed system time.
"""

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# The owner's interval.
NUDGE_AFTER_MINUTES = 60

# ONE. A second nudge on the same unanswered question is a bot pestering
# somebody, and the owner already gets the lead either way.
MAX_NUDGES_PER_TURN = 1

# Daytime only, on the traffic actually measured for this number: 43 of 54
# inbound messages fall in 09:00-19:00 IST and 01:00-08:00 had zero every
# night. A nudge at 03:00 would be read as spam by someone who was asleep,
# and it is the same reasoning health.py uses for silence alarms.
DAY_START_IST = 9
DAY_END_IST = 19

# Meta rejects free-form messages outside the 24-hour customer-service
# window, so a nudge sent late is not merely unwelcome — it is refused, and
# the refusal is invisible unless somebody checks. Two hours of margin keeps
# a delayed run from spending the attempt on a message that cannot arrive.
WINDOW_HOURS = 22

SEND = "SEND"
TOO_SOON = "TOO_SOON"
NOTHING_OUTSTANDING = "NOTHING_OUTSTANDING"
CUSTOMER_REPLIED = "CUSTOMER_REPLIED"
ALREADY_NUDGED = "ALREADY_NUDGED"
CHAT_PAUSED = "CHAT_PAUSED"
OUTSIDE_DAYTIME = "OUTSIDE_DAYTIME"
WINDOW_CLOSED = "WINDOW_CLOSED"

# Written to the transcript so a nudge is visible as a nudge, and so the next
# run can tell it already happened. Same no-new-storage trick as FLOW_MARKER.
NUDGE_MARKER = "[Bairavi nudge]"


def in_daytime(now) -> bool:
    """True when it is a civil hour to message somebody in Karnataka."""
    hour = now.astimezone(IST).hour
    return DAY_START_IST <= hour < DAY_END_IST


def decide(*, awaiting, asked_at, customer_replied_since,
           nudges_since, paused, now=None) -> str:
    """Whether to nudge this conversation, and if not, exactly why not.

    Returns one reason string rather than a bool: every skip is a decision
    somebody may need to explain later, and "it just didn't send" is the
    hardest kind of silence to debug.

    Order matters. The cheap, certain reasons come first so a log line names
    the real cause instead of whichever guard happened to fire.
    """
    if paused:
        # An owner who took the chat over with #stop outranks everything. A
        # bot nudging into a human handoff is the pause bug again, in a new
        # place.
        return CHAT_PAUSED
    if not awaiting:
        return NOTHING_OUTSTANDING
    if customer_replied_since:
        # They said SOMETHING. Whether it parsed is our problem, not theirs.
        return CUSTOMER_REPLIED
    if nudges_since >= MAX_NUDGES_PER_TURN:
        return ALREADY_NUDGED
    if asked_at is None:
        # No timestamp means no basis for a decision. Skipping is the safe
        # direction: a missed nudge costs a follow-up, a wrong one costs
        # trust.
        return TOO_SOON

    moment = now or datetime.now(timezone.utc)
    elapsed = moment - asked_at
    if elapsed < timedelta(minutes=NUDGE_AFTER_MINUTES):
        return TOO_SOON
    if elapsed >= timedelta(hours=WINDOW_HOURS):
        return WINDOW_CLOSED
    if not in_daytime(moment):
        return OUTSIDE_DAYTIME
    return SEND


def compose(awaiting, question_for, known=None) -> str:
    """The nudge itself.

    `question_for` is passed in rather than imported so this module stays
    free of the product vocabulary — the questions live with the business
    rules in bairavi.py, and this file only decides when to ask them.

    It says why it is asking again. A bare repeat of the question reads like
    a bot that forgot it already asked; naming the reason makes it a person
    following up.
    """
    if not awaiting:
        raise ValueError("nothing to nudge about")

    lines = ["ನಮಸ್ಕಾರ 🙏 *Bairavi Trans Solutions* — ನಿಮ್ಮ transformer "
             "requirement ಬಗ್ಗೆ ಒಂದು ವಿಷಯ ಬಾಕಿ ಇದೆ."]
    numerals = ("1️⃣", "2️⃣")
    for numeral, field in zip(numerals, awaiting):
        lines.append(f"{numeral} {question_for(field, known)}")
    lines.append("\nಇದು ತಿಳಿದರೆ ನಮ್ಮ engineer ನಿಖರವಾದ quotation ಕೊಡಲು ಸಾಧ್ಯ. "
                 "ಬೇಡವಾದರೆ ತೊಂದರೆ ಇಲ್ಲ — ತಿಳಿಸಿ ಸಾಕು 🙏")
    return "\n".join(lines)


def summarise(counts: dict) -> str:
    """One greppable line for the run. No phone number, no message text."""
    parts = [f"{k.lower()}={v}" for k, v in sorted(counts.items()) if v]
    return "BAIRAVI_NUDGE_RUN " + (" ".join(parts) or "considered=0")
