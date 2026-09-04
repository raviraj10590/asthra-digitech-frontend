"""The first BUSINESS-level evidence producer (2A/2C).

Every predicate before this one describes a COUNTERPARTY. This one describes
Asthra itself:

    biz.pipeline.new_enquiries_per_month@1
    "Distinct parties known to the Brain whose first_seen_at falls inside one
     calendar month, measured in IST."

WHY first_seen_at AND NOTHING ELSE
----------------------------------
It is the only source in the system that is complete by construction over the
population it covers: the Brain writes it itself, on its own transport, at
provenance tier 1. The `leads` table was rejected — it is EMPTY in production
while the business demonstrably has clients, so a metric derived from it would
be literally true about the table and substantively false about the business.
Seeding the first business fact from a source like that would poison the
evidence warehouse at its foundation, and a deterministic high-confidence
claim is exactly what the rest of the Brain is built to trust.

THE COMPLETENESS BOUNDARY IS PART OF THE MEANING
------------------------------------------------
This counts what the BRAIN OBSERVED. It is not total business demand, not all
leads, and not the CRM client count. The registered label and description say
so, and describe() carries them, so a reader who only ever sees the fact still
sees the boundary.

CALENDAR MONTH, IST — AN OWNER RULING (2026-08-27)
--------------------------------------------------
Not a rolling 30 days. The business already reports on calendar months and
that is what "this month" means to the owner. The consequence is accepted
rather than hidden: the value legitimately resets on the 1st.

WHY THE MATH IS HERE AND THE STORAGE IS NOT
-------------------------------------------
No metrics table. The aggregate is asserted through bic.claims like any other
fact, so it inherits retraction, bitemporality, versioning and the registry
gate for free. A second store would be a second truth.

NO MODEL. NO NETWORK BEYOND bic.db. NO PII — the count is derived from opaque
knowledge_ids and never touches a phone, an email or a wamid.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from . import claims, config, party
from .db import DbError

# The metric, exactly as registered in 2A. Version is part of the identity:
# reading @1 with @2's meaning is the failure the registry exists to prevent.
PREDICATE = "biz.pipeline.new_enquiries_per_month@1"
SOURCE_PREDICATE = "core.party.first_seen_at@1"

# IST. Declared here rather than imported from api/ so this module has no
# dependency on the web layer; the offset is fixed and has no DST.
IST = timezone(timedelta(hours=5, minutes=30))

# 2C §6: "Rule-based inference | 0.70 | Deterministic derivation from tier 0-2
# facts." first_seen_at is tier 1, so a deterministic count over it is tier 3.
# The cap is the point — a derived fact may never be more certain than the
# evidence under it, however exact the arithmetic.
PROVENANCE_TIER = 3

# The channel that binds the tenant's own ORGANIZATION party. Not a contact
# channel — the business does not message itself — but the existing identifier
# machinery is what keeps identity in one place, so it is reused rather than
# duplicated.
SELF_CHANNEL = "tenant-self"

SOURCE = "bic.claims/first_seen_at"
ASSERTED_BY = "agent:brain"


class PipelineEvidenceError(RuntimeError):
    """A CALLER violated this producer's contract."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def month_window(at=None) -> tuple:
    """The calendar month containing `at`, in IST, as aware UTC instants.

    Returns (start, end) HALF-OPEN: start <= t < end. Consecutive months
    therefore partition time exactly — no instant belongs to two months and
    none to neither, which is what makes the counts add up.

    The arithmetic is done in IST and only then converted, so the boundary is
    midnight in Bengaluru rather than midnight in UTC. Those are 5.5 hours
    apart, and getting it wrong silently moves every enquiry between 18:30 and
    midnight IST into the wrong month.
    """
    moment = _coerce(at) or _now()
    local = moment.astimezone(IST)
    start_local = datetime(local.year, local.month, 1, tzinfo=IST)
    # Month arithmetic without a calendar library: step into the next month by
    # construction rather than by adding 30/31 days, so long months, short
    # months, leap Februaries and year rollovers are all the same code path.
    if local.month == 12:
        end_local = datetime(local.year + 1, 1, 1, tzinfo=IST)
    else:
        end_local = datetime(local.year, local.month + 1, 1, tzinfo=IST)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _iso(v: datetime) -> str:
    return v.isoformat()


def _coerce(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise PipelineEvidenceError(f"unparseable instant {value!r}")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def business_subject(tenant_id: str = None) -> str:
    """The ORGANIZATION party standing for the tenant's own business.

    bic_claims.subject is foreign-keyed to bic_parties, so a business-level
    fact needs a business-level party. 2B already models this — "if they
    represent a firm, that firm is a SEPARATE Organization party" — so this
    reuses bic.party rather than inventing a second identity concept.

    Deterministic: the identifier is the tenant id itself, so the same tenant
    always resolves to the same party and a second call never mints a rival.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    return party.resolve_or_create(tenant, SELF_CHANNEL, tenant,
                                   kind=party.ORGANIZATION)


def find_business_subject(tenant_id: str = None) -> Optional[str]:
    """The business party if it already exists, else None. NEVER creates one.

    business_subject() above calls party.resolve_or_create, which WRITES the
    first time it is ever called — correct for the producer, which is
    asserting a fact and must have somewhere to put it. A READER must not be
    able to mint an identity as a side effect of a question, so context
    assembly and the OWNER read path use this instead.

    None means the producer has never run for this tenant. That is genuine
    absence of evidence and the sufficiency gate should say so — not an
    outage, and not a reason to fabricate a party.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    return party.find_by_identifier(tenant, SELF_CHANNEL, tenant)


def count_new_enquiries(tenant_id: str = None, *, at=None) -> dict:
    """Deterministic count for the calendar month containing `at`.

    Returns the measurement WITHOUT writing it, so the arithmetic is testable
    and inspectable on its own. record() is what commits it.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    start, end = month_window(at)
    subjects = claims.distinct_subjects_in_window(
        tenant, SOURCE_PREDICATE, start, end)
    return {
        "tenant_id": tenant,
        "value": len(subjects),
        "window_start": start,
        "window_end": end,
        # Kept for callers that want to audit the count; deliberately NOT
        # written into the claim, which stores the aggregate only.
        "subjects": subjects,
    }


def record(tenant_id: str = None, *, at=None, observed_at=None) -> Optional[dict]:
    """Compute the month's count and assert it as a 2C claim.

    Never raises on a store failure: evidence production must not be able to
    break a caller. Returns None when the claim could not be written.

    `valid_from`/`valid_until` pin the claim to the month it measures, so a
    reader years later knows WHICH month this number describes without having
    to infer it from when the row was written.
    """
    tenant = tenant_id or config.DEFAULT_TENANT_ID
    measured_at = _coerce(observed_at) or _now()
    try:
        measured = count_new_enquiries(tenant, at=at)
        start, end = measured["window_start"], measured["window_end"]

        # SUPERSESSION IS KEYED ON valid_from, AND THAT DECIDES THE MODEL.
        # claims.current() buckets a `single` predicate by predicate and keeps
        # the claim with the LATEST valid_from; anything else that survives is
        # a genuine contradiction it refuses to resolve. An earlier version of
        # this producer set valid_from to the month START, which felt right
        # ("this claim is about August") and was wrong: every recomputation
        # wrote an IDENTICAL valid_from, so nothing superseded, two live claims
        # remained, and the fact went permanently `contested` — CLARIFY, and a
        # metric no decision could use. Caught against real Postgres, not in
        # review.
        #
        # So valid_from is the MEASUREMENT INSTANT: "as of now, August stands
        # at N". A later reading is genuinely later and supersedes cleanly,
        # while valid_until still pins which month the number describes.
        if not (start <= measured_at < end):
            # Backfilling a closed month would need a valid_from inside a
            # window that has already passed, and two backfills would collide
            # on it exactly as above. The honest move is to decline rather
            # than mint a claim whose month cannot be read off its own dates.
            raise PipelineEvidenceError(
                "record() measures the CURRENT month only; observed_at "
                f"{measured_at.isoformat()} lies outside "
                f"[{start.isoformat()}, {end.isoformat()})")

        subject = business_subject(tenant)

        # IDEMPOTENT AT THE SAME INSTANT. Supersession is keyed on valid_from,
        # so two runs that share a measurement instant produce two claims that
        # neither supersedes the other — two live claims on a `single`
        # predicate, which claims.current() reports as contested. Different
        # instants are already safe; this closes the identical-instant case
        # (a cron retry, or a manual ?key= call landing in the same tick).
        #
        # Re-reading before writing costs one query on a once-daily job and is
        # the difference between "ran twice" and "permanently unusable".
        try:
            live = claims.current(tenant, subject, PREDICATE, as_of=measured_at)
            for existing in live.get("claims") or []:
                if str(existing.get("valid_from")) == _iso(measured_at):
                    # Same instant, same source data, same answer. Returning
                    # the existing claim is the honest no-op — writing a second
                    # identical row would only manufacture the conflict.
                    return existing
        except (DbError, claims.ClaimError):
            # A failed pre-check must not block the measurement; the worst case
            # is the duplicate this guard exists to avoid, which is still
            # better than recording nothing.
            pass

        return claims.assert_claim(
            tenant, subject, PREDICATE, measured["value"],
            source=SOURCE,
            provenance_tier=PROVENANCE_TIER,
            asserted_by=ASSERTED_BY,
            valid_from=measured_at,
            valid_until=end,
            observed_at=measured_at,
        )
    except (DbError, claims.ClaimError, party.PartyError) as e:
        # Type only — a store error body can echo an identifier.
        print(f"pipeline_evidence: record failed (ignored): {type(e).__name__}")
        return None
