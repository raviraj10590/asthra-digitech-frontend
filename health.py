"""Is the bot actually alive? — the question that has cost real money twice.

WHY THIS EXISTS
---------------
2026-09-08: the WhatsApp access token expired at its 60-day mark. Every send
returned 401. The bot went silent, nobody knew, and the only evidence was a
Vercel log line with roughly one hour of retention. The owner discovered it by
noticing he had not been replied to.

2026-09-15: transformer enquiries had been answered as the wrong company for
three days. Found by the owner reading his own WhatsApp, not by any alarm.

2026-09-16: answering "is it broken, or just quiet?" took four queries against
raw message history and a reconstruction of the hourly traffic pattern. The
answer was "quiet" — but it should not take a forensic session to establish
that.

Every one of those is the same missing capability: nothing watches, and
absence of traffic is indistinguishable from absence of service.

THE CIRCULARITY, STATED PLAINLY
-------------------------------
The alert channel is WhatsApp. When WhatsApp is the broken thing, no WhatsApp
alert can be delivered. That cannot be engineered away on this stack — there
is no second channel and no budget for one.

So this does the two things that ARE possible:

  1. Make the failure DURABLE. The verdict is written to app_settings, which
     outlives the ~1h log retention, so the answer to "when did it break?" is
     a row rather than an archaeology session.
  2. Make the healthy case VISIBLE. The verdict rides the daily digest the
     owner already receives. A digest that arrives WITHOUT a health line, or
     does not arrive at all, is itself the signal — and absence is much easier
     to notice on something you read every day than in a log nobody opens.

WARN BEFORE, NOT AFTER
----------------------
The token died at exactly 60 days. Meta's debug_token reports `expires_at`,
and 0 means a permanent System User token. That single field answers the
question the owner has actually been asking — "will this happen again?" — and
it is checked every day rather than remembered once.

NO SEND IS USED AS A PROBE. Liveness is checked with a read-only GET on the
phone-number object. Probing by messaging someone would mean the health check
itself becomes traffic, and a daily message to prove the bot works is spam the
owner would learn to ignore.

SILENCE IS JUDGED IN IST, AGAINST THE REAL PATTERN
--------------------------------------------------
Measured over 7 days: 43 of 54 inbound messages fall in 09:00-19:00 IST, and
01:00-08:00 IST had ZERO every single night. A fixed "no traffic for 6 hours"
rule would therefore page every morning at 6am and teach the owner to ignore
it. Only DAYTIME quiet counts, which is why this module does calendar
arithmetic instead of subtracting two timestamps.

NO I/O. Pure functions over values the caller has already fetched, so the
decision can be tested without a network, a clock, or a database.
"""

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# The window in which silence is meaningful. Derived from measured traffic
# (see the docstring), not chosen for roundness.
DAY_START_IST = 9
DAY_END_IST = 19

# Consecutive EMPTY DAYTIME hours before silence is called abnormal. The
# observed daytime rate is ~6 messages per 10-hour window, so six empty
# daytime hours is a genuine anomaly rather than an unlucky gap.
SILENCE_ALARM_HOURS = 6

# Days of remaining token life below which the owner is warned. Comfortably
# more than one weekend, so a warning that lands on a Friday still leaves time
# to act on Monday.
EXPIRY_WARN_DAYS = 10

OK = "OK"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"

PERMANENT = "PERMANENT"
EXPIRING = "EXPIRING"
EXPIRED = "EXPIRED"


def classify_probe(status_code, ok: bool) -> str:
    """What a read-only Graph API GET means for the credential.

    401/403 is the exact signature of the 2026-09-08 outage and is reported as
    DEAD. Anything else that merely failed is UNKNOWN, NOT dead: a timeout or
    a 500 at Meta's end is not a reason to tell the owner his token expired,
    and crying wolf is how an alarm gets muted.
    """
    if ok:
        return OK
    if status_code in (401, 403):
        return DEAD
    return UNKNOWN


def classify_expiry(expires_at, now=None) -> tuple:
    """(state, days_left) from debug_token's expires_at.

    0 means never — a permanent System User token, which is the answer the
    owner wants. None means Meta did not tell us, which is UNKNOWN rather than
    an assumption in either direction.
    """
    if expires_at is None:
        return UNKNOWN, None
    try:
        ts = int(expires_at)
    except (TypeError, ValueError):
        return UNKNOWN, None
    if ts == 0:
        return PERMANENT, None
    moment = now or datetime.now(timezone.utc)
    left = datetime.fromtimestamp(ts, timezone.utc) - moment
    days = int(left.total_seconds() // 86400)
    if left.total_seconds() <= 0:
        return EXPIRED, days
    return (EXPIRING if days <= EXPIRY_WARN_DAYS else OK), days


def daytime_hours_between(start, end) -> int:
    """Whole hours inside 09:00-19:00 IST between two instants.

    The reason this is not `(end - start).hours`: the bot is legitimately
    silent all night, and treating that as downtime would produce a false
    alarm every single morning.
    """
    # `not start or not end` is load-bearing: None would crash astimezone.
    #
    # An `end <= start` clause used to sit here too and was REMOVED — a
    # mutation that deleted it changed no observable behaviour, because the
    # `while cursor < b` loop below already yields 0 for a reversed or empty
    # span. A guard no test can distinguish is dead weight, and the loop is
    # the clearer statement of the same rule.
    if not start or not end:
        return 0
    a = start.astimezone(IST)
    b = end.astimezone(IST)
    hours = 0
    cursor = a.replace(minute=0, second=0, microsecond=0)
    while cursor < b:
        if DAY_START_IST <= cursor.hour < DAY_END_IST:
            hours += 1
        cursor += timedelta(hours=1)
    return hours


def classify_silence(last_inbound, now=None) -> tuple:
    """(is_abnormal, quiet_daytime_hours).

    `last_inbound` None means nothing has EVER arrived, which is not silence to
    alarm about — it is a bot that has not been used yet, and the caller says
    so differently.
    """
    if last_inbound is None:
        return False, 0
    moment = now or datetime.now(timezone.utc)
    quiet = daytime_hours_between(last_inbound, moment)
    return quiet >= SILENCE_ALARM_HOURS, quiet


def compose_health_line(probe: str, expiry: tuple, silence: tuple,
                        last_inbound=None) -> str:
    """One line for the daily digest. Healthy is boring on purpose.

    A health report the owner skims past is worthless, so the OK case is a
    single short line and only a real problem gets emphasis and an instruction.
    """
    state, days = expiry
    abnormal, quiet = silence

    if probe == DEAD:
        # The one case the owner cannot discover any other way until a
        # customer complains — and the one this file was written for.
        return ("🚨 *WhatsApp token is REJECTED (401)* — the bot cannot reply "
                "to anyone. Rotate WHATSAPP_TOKEN in Vercel and redeploy. "
                "Nothing sent since this started.")

    bits = []
    if probe == OK:
        bits.append("WhatsApp ✅")
    else:
        bits.append("WhatsApp ⚠️ unverified (Meta did not answer)")

    if state == PERMANENT:
        bits.append("token permanent")
    elif state == EXPIRED:
        bits.append("🚨 token EXPIRED")
    elif state == EXPIRING:
        bits.append(f"⚠️ token expires in {days}d — rotate it")
    elif days is not None:
        bits.append(f"token {days}d left")

    if abnormal:
        bits.append(f"🚨 no enquiry for {quiet} daytime hours")
    elif last_inbound is not None:
        bits.append(f"last enquiry {quiet}h of daytime ago")

    return "🩺 " + " · ".join(bits)


def compose_record(probe: str, expiry: tuple, silence: tuple, now=None) -> str:
    """The durable value written to app_settings.

    Deliberately a flat, greppable string rather than JSON: its only reader is
    a human asking "what happened and when", usually in a hurry, and it has to
    survive being pasted into a message. NO TOKEN, no phone number, no
    customer data — a health row must never become a place credentials leak.
    """
    state, days = expiry
    abnormal, quiet = silence
    moment = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return (f"at={moment} probe={probe} token={state}"
            f"{'' if days is None else f' days_left={days}'}"
            f" quiet_daytime_hours={quiet} silence_alarm={abnormal}")
