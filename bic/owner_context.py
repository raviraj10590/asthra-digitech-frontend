"""Which customer is the OWNER currently dealing with?

WHY THIS EXISTS
---------------
`#why` proved out in production and returned "cannot identify a customer" —
correctly. It resolved the party bound to the CURRENT CONVERSATION, and for an
owner that is the owner's own party, which does not exist and never will:
owners do not tap the customer welcome menu. A capability with no reachable
subject is a capability nobody uses.

WHAT THIS IS NOT
----------------
Not a new store, not a new event, not a new table. Every fact below is already
recorded by something else for its own reasons. This module only READS.

Not conversation-text matching, not fuzzy matching, not AI inference, and not
2D identity resolution. There is exactly one lookup by exact identifier value,
through the same `party.find_by_identifier` every other caller uses.

THE TWO SOURCES, IN DECLARED PRECEDENCE
---------------------------------------
1. OWNER_ACTION — the most recent `chat_pause` / `chat_resume` invocation by an
   OWNER. These are `min_role='OWNER'`, `audit_level='full'`, and the argument
   allowlist deliberately records `target` ("`target` and `role` ARE the
   audit"). So the row means precisely: *this owner took over this customer's
   conversation*. That is an explicit selection, not a guess.

2. RECENT_ACTIVITY — the party whose most recent claim was observed. This is a
   WEAKER signal and is never presented as an explicit selection: any
   customer's activity changes it. It exists so the capability has a reachable
   subject before the owner has paused anyone, and the caller is told which
   source answered so it can say so.

The precedence is DECLARED, not silent. A caller can always see `state` and
`source` and render them differently, which is the whole point of returning a
context object rather than a bare id.

EXPIRY IS BORROWED, NOT INVENTED
--------------------------------
An OWNER_ACTION context lives 24 hours, because `chat_pause` already means
"silence the bot for this conversation, auto-resumes in 24h". The window in
which the owner is handling that customer personally is the window the product
already defines. Picking a different number here would be inventing a second,
competing notion of the same thing.

RECENT_ACTIVITY does not expire. A cutoff would be a number nobody chose, and
the honest alternative is cheaper: report the age and let the reader judge.

AMBIGUITY IS SURFACED, NEVER RESOLVED
-------------------------------------
If two customers are equally current — two owner actions at the same instant,
or two parties whose newest claim shares a timestamp — this returns AMBIGUOUS
with both candidates and picks NEITHER. Choosing one would be indistinguishable
from knowing which the owner meant.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config
from . import party as party_mod
from .db import select

INVOCATIONS_TABLE = "bic_tool_invocations"
CLAIMS_TABLE = "bic_claims"

# The two invocations that mean "an owner took this customer's conversation".
OWNER_ACTION_TOOLS = ("chat_pause", "chat_resume")

# Borrowed from chat_pause's own 24h auto-resume, not chosen here.
OWNER_ACTION_TTL = timedelta(hours=24)

# Bounded scan. An owner action older than these rows is older than the TTL in
# any realistic volume, and an unbounded read of an append-only audit table
# would grow without limit.
_SCAN_LIMIT = 20

# ── States ─────────────────────────────────────────────────────────────────
OWNER_ACTION = "OWNER_ACTION"      # explicit: the owner took this customer
RECENT_ACTIVITY = "RECENT_ACTIVITY"  # weaker: most recently active customer
AMBIGUOUS = "AMBIGUOUS"            # two equally current; nothing chosen
NONE = "NONE"                      # no customer context at all
STATES = (OWNER_ACTION, RECENT_ACTIVITY, AMBIGUOUS, NONE)

# ── Why there is no usable context ─────────────────────────────────────────
R_NO_ACTION_NO_CLAIMS = "no_owner_action_and_no_claims"
R_SELECTED_HAS_NO_PARTY = "selected_customer_has_no_knowledge_record"
R_TWO_OWNER_ACTIONS = "two_owner_actions_at_the_same_instant"
R_TWO_ACTIVE_PARTIES = "two_parties_share_the_newest_observation"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp) -> Optional[datetime]:
    if isinstance(stamp, datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _context(state, party_id=None, selected_at=None, source=None,
             reason=None, candidates=None, now=None) -> dict:
    stamp = _parse(selected_at)
    now = now or _now()
    return {
        "state": state,
        "party_id": party_id,
        "source": source,
        "selected_at": stamp.isoformat() if stamp else None,
        "age_seconds": int(max((now - stamp).total_seconds(), 0)) if stamp else None,
        "expires_after_seconds": (int(OWNER_ACTION_TTL.total_seconds())
                                  if state == OWNER_ACTION else None),
        "reason": reason,
        # Only ever populated for AMBIGUOUS, and never reduced to one.
        "candidates": candidates or [],
    }


def resolve(tenant_id: str, now=None) -> dict:
    """The customer this OWNER is currently dealing with, or an honest None.

    Raises DbError if the audit trail cannot be read — the caller must be able
    to tell "no customer selected" from "could not look", because rendering an
    outage as an absence is how a system lies without anyone writing a lie.
    """
    now = now or _now()
    tenant = tenant_id or config.DEFAULT_TENANT_ID

    action = _latest_owner_action(tenant, now)
    if action is not None:
        return action

    return _most_recent_activity(tenant, now)


# ── 1. The explicit signal ─────────────────────────────────────────────────

def _latest_owner_action(tenant: str, now):
    """Most recent in-window OWNER chat_pause / chat_resume, or None.

    Returns None ONLY when there is no in-window owner action at all. If there
    is one but its customer has no knowledge record, that is reported rather
    than skipped: falling through to an older action would silently answer
    about a DIFFERENT customer than the one the owner last chose.
    """
    rows = select(INVOCATIONS_TABLE, {
        "tenant_id": f"eq.{tenant}",
        "tool": f"in.({','.join(OWNER_ACTION_TOOLS)})",
        "role": "eq.OWNER",
        "ok": "is.true",
        "order": "created_at.desc",
        "limit": str(_SCAN_LIMIT),
        "select": "tool,args_redacted,created_at",
    }, timeout=5)

    live = []
    for row in rows:
        target = (row.get("args_redacted") or {}).get("target")
        stamp = _parse(row.get("created_at"))
        if not target or stamp is None:
            continue
        if now - stamp > OWNER_ACTION_TTL:
            continue
        live.append((stamp, target, row.get("tool")))
    if not live:
        return None

    live.sort(key=lambda x: x[0], reverse=True)
    newest_at = live[0][0]
    tied = {t for stamp, t, _ in live if stamp == newest_at}
    if len(tied) > 1:
        # Two customers taken over in the same instant. Nothing is chosen.
        return _context(AMBIGUOUS, selected_at=newest_at, source="owner_action",
                        reason=R_TWO_OWNER_ACTIONS,
                        candidates=_parties_for(tenant, sorted(tied)), now=now)

    stamp, target, tool = live[0]
    party_id = party_mod.find_by_identifier(tenant, party_mod.WHATSAPP, target)
    if not party_id:
        return _context(NONE, selected_at=stamp, source=tool,
                        reason=R_SELECTED_HAS_NO_PARTY, now=now)
    return _context(OWNER_ACTION, party_id=party_id, selected_at=stamp,
                    source=tool, now=now)


def _parties_for(tenant: str, targets: list) -> list:
    """Candidate knowledge_ids for an ambiguous selection. Opaque ids only —
    the phone that resolved each one is never returned."""
    out = []
    for target in targets:
        party_id = party_mod.find_by_identifier(tenant, party_mod.WHATSAPP, target)
        if party_id:
            out.append(party_id)
    return sorted(set(out))


# ── 2. The weaker fallback ─────────────────────────────────────────────────

def _most_recent_activity(tenant: str, now):
    """The party whose newest claim was observed. Never an explicit selection."""
    rows = select(CLAIMS_TABLE, {
        "tenant_id": f"eq.{tenant}",
        "order": "observed_at.desc",
        "limit": "10",
        "select": "subject,observed_at",
    }, timeout=5)
    if not rows:
        return _context(NONE, reason=R_NO_ACTION_NO_CLAIMS, now=now)

    newest = _parse(rows[0].get("observed_at"))
    tied = {r.get("subject") for r in rows
            if _parse(r.get("observed_at")) == newest and r.get("subject")}
    if len(tied) > 1:
        return _context(AMBIGUOUS, selected_at=newest, source="claim",
                        reason=R_TWO_ACTIVE_PARTIES,
                        candidates=sorted(tied), now=now)
    return _context(RECENT_ACTIVITY, party_id=rows[0].get("subject"),
                    selected_at=newest, source="claim", now=now)
