"""The Brain's health, as one small aggregate the CRM can show (2026-10-01).

Owner request: "can you create complete health of brain in crm?"

The CRM cannot read the Brain database — since Phase 1B its tables are
service-role only, and that key must never reach a browser. The Brain already
holds the CRM's service key server-side, so it PUSHES: after each scheduled
recovery sweep, api/health_snapshot.py collects rows, this module turns them
into counts, and one snapshot row lands in the CRM's brain_health_snapshots.

WHAT A SNAPSHOT MAY CONTAIN — AND WHAT IT NEVER DOES
----------------------------------------------------
Counts, durations, states, failure classes, the deployed commit, and the
daily health check's verdict (probe / token / silence / ads), which
health.compose_record already guarantees holds no token, phone or text.

Never: a phone number, a WAMID, a name, message text, or an error body.
summarise() takes only the fields it counts, and the test suite asserts the
output contains no digits-run that could be a phone and no "wamid".

Pure: no network, no clock unless one is passed.
"""
import re
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = 1
STALE_PROCESSING_SECONDS = 600     # matches api/redrive.py
_HEALTH_KEYS = ("at", "probe", "token", "days_left", "quiet_daytime_hours",
                "silence_alarm", "ads")


def _ts(value):
    """Postgres timestamps on Python 3.9 (5-digit fractions, '+00')."""
    m = re.match(r"^(.*?T?\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}(?::?\d{2})?)?$",
                 str(value or "").replace(" ", "T"))
    if not m:
        return None
    base, frac, tz = m.groups()
    if tz in (None, "Z"):
        tz = "+00:00"
    elif len(tz) == 3:
        tz += ":00"
    elif ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    try:
        return datetime.fromisoformat(f"{base}.{(frac or '0')[:6].ljust(6, '0')}{tz}")
    except ValueError:
        return None


def _pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def parse_health_record(value):
    """'at=… probe=OK token=OK days_left=45 …' -> dict of the known keys only."""
    out = {}
    for part in str(value or "").split():
        k, sep, v = part.partition("=")
        if sep and k in _HEALTH_KEYS:
            out[k] = (int(v) if k in ("days_left", "quiet_daytime_hours") and v.lstrip("-").isdigit()
                      else v == "True" if k == "silence_alarm" else v)
    return out


def summarise_events(rows, now):
    """bic_webhook_events rows from the last 24 h -> counts and timings."""
    states, failures, durations = {}, {}, []
    stuck = 0
    for r in rows:
        st = r.get("state") or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
        if st == "FAILED":
            fc = r.get("failure_class") or "UNKNOWN"
            failures[fc] = failures.get(fc, 0) + 1
        c, d = _ts(r.get("created_at")), _ts(r.get("completed_at"))
        if c and d:
            durations.append((d - c).total_seconds())
        u = _ts(r.get("updated_at"))
        if st == "PROCESSING" and u and (now - u).total_seconds() > STALE_PROCESSING_SECONDS:
            stuck += 1
    return {"total": len(rows), "by_state": states, "failed_by_class": failures,
            "stuck_processing": stuck,
            "duration_s": {"p50": _pct(durations, 0.5), "p90": _pct(durations, 0.9),
                           "max": round(max(durations), 1) if durations else None}}


def summarise_recovery(contents):
    """RECOVERY:: system rows (last 7 days) -> attempts and final results."""
    attempts, finals = 0, {}
    for c in contents:
        if "::attempt=" in c:
            attempts += 1
        m = re.search(r"::final=([A-Z_]+)", c or "")
        if m:
            finals[m.group(1)] = finals.get(m.group(1), 0) + 1
    return {"attempts_7d": attempts, "final_7d": finals}


def build(*, now, events_24h, last_event_at, accepted_total, recovery_contents,
          health_value, sweep, commit, source):
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "deployment": {"commit": (commit or "")[:7] or None},
        "events": dict(summarise_events(events_24h, now),
                       last_event_at=last_event_at, accepted_unresolved=accepted_total),
        "recovery": dict(summarise_recovery(recovery_contents),
                         last_sweep={str(k): int(v) for k, v in (sweep or {}).items()}),
        "health_check": parse_health_record(health_value),
        # NOT the shadow interpreter: its table has no production reader by
        # design (tests/test_shadow_persistence.py), so its numbers stay in
        # the weekly offline learning report.
    }


def since(now, **kw):
    return (now - timedelta(**kw)).astimezone(timezone.utc).isoformat()
