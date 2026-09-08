"""The second BUSINESS-level evidence producer (2A/2C) — conversion rate.

    biz.pipeline.conversion_rate@1
    "Of the distinct parties whose first contact fell in one calendar month,
     the fraction whose FIRST PAYMENT arrived within 30 days of that party's
     own first contact."

THE OWNER RULING THIS IMPLEMENTS (2026-09-07)
---------------------------------------------
    conversion event   first payment received
    window             30 calendar days from the party's first enquiry
    basis              ENQUIRY COHORT

Every rule below follows from those three lines, and the ones that could have
been guessed are the ones written down hardest.

COHORT, NOT CALENDAR PERIOD — AND THE DIFFERENCE IS THE WHOLE POINT
-------------------------------------------------------------------
The tempting arithmetic is "payments this month / enquiries this month". It
is cheap, it always produces a number, and it compares two unrelated
populations: the people who paid in September mostly enquired earlier, so the
ratio describes nobody. A cohort follows ONE group of parties forward through
their own 30 days and asks what happened to THEM.

The cost is that a cohort is not knowable immediately, which is the next
section.

PROVISIONAL UNTIL THE WINDOW CLOSES
-----------------------------------
A September cohort cannot be final on October 1. Parties who enquired on
September 25 still have until October 25 to pay. Reporting the ratio then
would report a number that can only go up, as though it were finished — the
most misleading possible presentation, because it looks precise.

So a cohort carries a STATE, and only a FINAL cohort is ever asserted as a
claim. A PROVISIONAL cohort is computed and returned — the observed count so
far is real and useful — but it is labelled, never stored as the metric.

MISSING NUMERATOR IS NOT ZERO. THIS IS THE EASIEST WAY TO LIE HERE
-------------------------------------------------------------------
core.party.became_client_at@1 was created on 2026-09-07 and NOTHING was
backfilled: 27 parties already hold first_seen_at and an unknown number of
them have already paid. We do not know which.

So for any cohort that opened before the event existed, "0 conversions
recorded" means "we were not recording", not "nobody paid". Dividing anyway
would produce a confident 0% for months in which the business may have done
perfectly well.

The epoch is READ FROM THE REGISTRY (`activated_at` on the concept), not
hardcoded here. A constant would be a second source of truth that drifts the
moment the concept is re-registered, and it would let a test pass while
production divided by a different date.

A cohort is measurable only if the capability existed for the WHOLE of it —
epoch <= cohort start. A party who enquired and paid on day 3 of a cohort
that opened before the epoch is invisible, and one invisible conversion is
enough to make the ratio wrong.

DIVISION BY ZERO IS AN UNKNOWN, NOT A ZERO
------------------------------------------
A month with no enquiries has no conversion rate. Not 0%, not 100% — the
question does not apply. rate is None and the reason says which case it is.

NO MODEL. NO NETWORK BEYOND bic.db. NO PII — cohorts are sets of opaque
knowledge_ids and no phone, name or amount is ever read or written.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from . import claims, config, registry
from .db import DbError
from .pipeline_evidence import (IST, month_window, business_subject,
                                find_business_subject, _coerce)

# The metric and the two predicates it derives from. Version is part of the
# identity: reading @1 with @2's meaning is what the registry exists to stop.
PREDICATE = "biz.pipeline.conversion_rate@1"
ENQUIRY_PREDICATE = "core.party.first_seen_at@1"
CONVERSION_PREDICATE = "core.party.became_client_at@1"

# OWNER RULING: 30 calendar days from the party's own first enquiry.
# INCLUSIVE at the boundary — a payment at exactly first_seen + 30 days
# COUNTS. Stated explicitly because `<` and `<=` are one character apart and
# the difference silently moves every day-30 conversion out of the numerator.
WINDOW_DAYS = 30

# 2C §6: rule-based inference over tier 0-2 facts. first_seen_at is tier 1 and
# became_client_at is tier 1, so a deterministic count over both is tier 3,
# capped at 0.70. A derived fact may never be more certain than the evidence
# under it, however exact the arithmetic.
PROVENANCE_TIER = 3

SOURCE = "bic.claims/first_seen_at+became_client_at"
ASSERTED_BY = "agent:brain"

PROVISIONAL = "PROVISIONAL"
FINAL = "FINAL"

# Why a cohort could not be measured. Each is a genuinely different answer and
# collapsing them into "no data" is what sends someone looking for a broken
# query that never existed.
NO_ENQUIRIES = "no enquiries in this cohort"
BEFORE_EPOCH = ("the conversion event did not exist for the whole of this "
                "cohort, so unrecorded conversions cannot be distinguished "
                "from absent ones")


class ConversionEvidenceError(RuntimeError):
    """A CALLER violated this producer's contract."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def capability_epoch() -> Optional[datetime]:
    """When became_client_at became assertable, from the REGISTRY.

    None when the concept is not registered at all — in which case nothing is
    measurable and the caller must say UNKNOWN rather than assume anything.
    """
    row = registry.lookup_ref(CONVERSION_PREDICATE)
    if not row:
        return None
    return _coerce(row.get("activated_at"))


def window_end_for(first_seen: datetime) -> datetime:
    """The last instant a payment may arrive and still count, INCLUSIVE."""
    return first_seen + timedelta(days=WINDOW_DAYS)


def cohort(tenant_id: str = None, *, at=None, now=None) -> dict:
    """Measure the enquiry cohort of the calendar month containing `at`.

    Returns the measurement WITHOUT writing it, so the arithmetic is testable
    and inspectable on its own — record() is what commits it, and only ever
    for a FINAL cohort.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    moment = _coerce(now) or _now()
    start, end = month_window(at)

    # DENOMINATOR — distinct parties, by construction. first_seen_at is
    # `single` cardinality, so a party who enquires ten times still holds one
    # claim and appears once. Repeat enquiries cannot inflate this.
    enquired = claims.valid_from_by_subject(
        tenant, ENQUIRY_PREDICATE, window_start=start, window_end=end)

    result = {
        "tenant_id": tenant,
        "cohort_start": start,
        "cohort_end": end,
        "denominator": len(enquired),
        "numerator": None,
        "rate": None,
        "state": PROVISIONAL,
        "measurable": False,
        "reason": None,
        "window_closes_at": None,
        "denominator_evidence": sorted(enquired),
        "numerator_evidence": [],
    }

    # The cohort is closed once the LAST enquirer's own 30 days have elapsed.
    # Computed from the real maximum rather than from the month end, so a
    # cohort whose enquiries all landed early closes as soon as it truly has.
    if enquired:
        latest = max(_coerce(v) for v in enquired.values())
        result["window_closes_at"] = window_end_for(latest)
    else:
        result["window_closes_at"] = window_end_for(end)
    result["state"] = FINAL if moment >= result["window_closes_at"] else PROVISIONAL

    epoch = capability_epoch()
    if epoch is None or epoch > start:
        # NOT measurable, and the numerator stays None. See the module
        # docstring: 0 recorded conversions before the epoch means "we were
        # not recording", which is not the same fact as "nobody paid".
        result["reason"] = BEFORE_EPOCH
        return result

    result["measurable"] = True

    if not enquired:
        # No denominator. The question does not apply — it is not 0%.
        result["reason"] = NO_ENQUIRIES
        return result

    # NUMERATOR — only parties FROM THIS COHORT, and only their own window.
    paid = claims.valid_from_by_subject(
        tenant, CONVERSION_PREDICATE, subjects=list(enquired))

    converted = []
    for subject, seen_raw in enquired.items():
        when = paid.get(subject)
        if not when:
            continue
        seen, paid_at = _coerce(seen_raw), _coerce(when)
        # ON OR AFTER first contact, and no later than day 30 INCLUSIVE.
        # A payment BEFORE the first enquiry is not this cohort's conversion:
        # it means the party was already a client, and counting it would
        # credit an enquiry that did not cause anything.
        if seen <= paid_at <= window_end_for(seen):
            converted.append(subject)

    result["numerator"] = len(converted)
    result["numerator_evidence"] = sorted(converted)
    result["rate"] = round(len(converted) / len(enquired), 4)
    return result


def _next_month(start: datetime) -> datetime:
    """The first instant of the following calendar month, in IST.

    Stepping by construction rather than by adding 30/31 days, so long months,
    short months, leap Februaries and year rollovers are all one code path —
    the same reasoning month_window() already applies.
    """
    local = start.astimezone(IST)
    if local.month == 12:
        nxt = datetime(local.year + 1, 1, 1, tzinfo=IST)
    else:
        nxt = datetime(local.year, local.month + 1, 1, tzinfo=IST)
    return nxt.astimezone(timezone.utc)


def finalize(tenant_id: str = None, *, now=None) -> dict:
    """Find every cohort that has CLOSED and not yet been recorded, and record it.

    THE BRAIN OWNS THE MEASUREMENT LIFECYCLE. cohort() could already measure
    one named month and record() could already persist a FINAL one, but nothing
    ever ASKED. A human would have had to know which month had just closed and
    invoke it on the right day — which is not a measurement system, it is a
    reminder. This is the piece that makes the metric self-maintaining.

    WHAT THIS DELIBERATELY DOES NOT DO
    ----------------------------------
    It re-implements no arithmetic. Denominator, numerator, the 30-day window,
    closure, the epoch rule and NULL-vs-zero all stay in cohort(); persistence
    stays in record(). This function only decides WHICH months to ask about,
    and refuses to ask twice.

    THE SEARCH RANGE IS THE EPOCH, NOT A LOOKBACK CONSTANT
    ------------------------------------------------------
    A cohort that opened before became_client_at existed is unmeasurable
    forever, so there is no reason to consider one — and no reason to invent an
    arbitrary "last 12 months" window that would silently drop a cohort if the
    job stopped running for a while. The first candidate is the first calendar
    month that STARTS on or after the registry epoch; the last is the current
    month. The range is self-limiting and self-healing: an outage of any length
    is repaired on the next run, because the range is derived from evidence
    rather than from when this last ran.

    IDEMPOTENT PER COHORT, NOT MERELY PER INSTANT
    ---------------------------------------------
    record() alone guards only against two writes at the SAME measurement
    instant. Running daily, it would rewrite every closed cohort every day
    forever — each superseding the last, each identical, burying the real
    measurement in noise. A cohort is identified by its `valid_until`, which
    pins which month a claim describes, so a cohort that already has a claim is
    never asked again.

    A RETRACTED CLAIM STILL COUNTS AS ANSWERED. Retraction is a human saying
    "this is wrong"; a scheduler that immediately re-asserted the same number
    would silently overrule that judgement, and if the underlying evidence had
    not changed it would do so forever. Re-finalising after a retraction is a
    deliberate human act, not an automatic one.

    Never raises. Evidence production must not be able to break its caller.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    moment = _coerce(now) or _now()
    out = {"tenant_id": tenant, "considered": 0, "recorded": [],
           "provisional": [], "unmeasurable": [], "empty": [],
           "already_final": [], "reason": None}
    try:
        epoch = capability_epoch()
        if epoch is None:
            # The conversion event is not registered. Nothing is measurable,
            # and saying so is not the same as measuring zero cohorts.
            out["reason"] = "conversion event predicate is not registered"
            return out

        # READER, NEVER A CREATOR. business_subject() mints the org party on
        # first use, which is correct for record() — it is about to assert a
        # fact and needs somewhere to put it. Deciding what to ask must not
        # create anything, so this uses the lookup-only form. None simply means
        # no conversion claim has ever been written.
        subject = find_business_subject(tenant)
        already = set()
        if subject:
            for claim in claims.history(tenant, subject, PREDICATE) or []:
                if claim.get("valid_until"):
                    already.add(str(claim["valid_until"]))

        # The first candidate is the month CONTAINING the epoch, not the one
        # after it. A mid-month epoch means that month opened before the
        # capability existed — but the rule that decides this lives in
        # cohort(), which already refuses any cohort whose start precedes the
        # epoch. Re-deciding it here would put the same rule in two places, and
        # a mutation that deleted the duplicate changed nothing, which is how
        # the redundancy was found. The month is still WALKED so it is reported
        # as unmeasurable rather than silently omitted.
        start, _ = month_window(epoch)
        current_start, _ = month_window(moment)

        # Defensive bound. The loop is already bounded by the epoch, but a
        # corrupt activated_at far in the past must not spin.
        for _ in range(120):
            if start > current_start:
                break
            out["considered"] += 1
            _, cohort_end = month_window(start)
            label = start.astimezone(IST).strftime("%Y-%m")

            if str(cohort_end.isoformat()) in already or \
                    cohort_end.isoformat() in already:
                out["already_final"].append(label)
                start = _next_month(start)
                continue

            measured = cohort(tenant, at=start, now=moment)
            if not measured["measurable"]:
                out["unmeasurable"].append(label)
            elif measured["rate"] is None:
                # No enquiries. NULL, not zero — nothing to assert.
                out["empty"].append(label)
            elif measured["state"] != FINAL:
                out["provisional"].append(label)
            else:
                claim = record(tenant, at=start, observed_at=moment)
                if claim is not None:
                    out["recorded"].append(
                        {"cohort": label, "rate": measured["rate"],
                         "denominator": measured["denominator"],
                         "numerator": measured["numerator"]})
            start = _next_month(start)
        return out
    except Exception as e:
        # Type only — a store error body can echo an identifier.
        print(f"conversion_evidence: finalize failed (ignored): {type(e).__name__}")
        out["reason"] = type(e).__name__
        return out


def record(tenant_id: str = None, *, at=None, observed_at=None) -> Optional[dict]:
    """Assert a cohort's conversion rate — FINAL cohorts only.

    Declines silently for anything else. A PROVISIONAL cohort is real
    information but it is not this metric: storing it would put a number that
    can still rise into the same predicate a reader trusts as settled, and no
    label on the claim would survive being read as "the conversion rate".

    Never raises on a store failure: evidence production must not be able to
    break a caller.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    measured_at = _coerce(observed_at) or _now()
    try:
        measured = cohort(tenant, at=at, now=measured_at)
        if not measured["measurable"] or measured["rate"] is None:
            return None
        if measured["state"] != FINAL:
            return None

        subject = business_subject(tenant)

        # IDEMPOTENT AT THE SAME INSTANT, for the reason pipeline_evidence
        # documents at length: supersession is keyed on valid_from, so two
        # runs sharing a measurement instant would leave two live claims on a
        # `single` predicate and the fact would read as contested forever.
        try:
            live = claims.current(tenant, subject, PREDICATE, as_of=measured_at)
            for existing in live.get("claims") or []:
                if (str(existing.get("valid_from")) == measured_at.isoformat()
                        and str(existing.get("valid_until"))
                        == measured["cohort_end"].isoformat()):
                    return existing
        except (DbError, claims.ClaimError):
            pass

        return claims.assert_claim(
            tenant, subject, PREDICATE, measured["rate"],
            source=SOURCE,
            provenance_tier=PROVENANCE_TIER,
            asserted_by=ASSERTED_BY,
            # valid_from is the MEASUREMENT INSTANT so a later reading
            # supersedes cleanly; valid_until pins WHICH cohort it describes.
            valid_from=measured_at,
            valid_until=measured["cohort_end"],
            observed_at=measured_at,
        )
    except (DbError, claims.ClaimError, ConversionEvidenceError) as e:
        print(f"conversion_evidence: record failed (ignored): {type(e).__name__}")
        return None
    except Exception as e:  # party/registry failures must not break a caller
        print(f"conversion_evidence: record failed (ignored): {type(e).__name__}")
        return None
