"""Decision Record diagnostics — READ ONLY.

    python3 -m bic.decisions_cli --help

WHY THIS EXISTS
---------------
Verifying the Brain in production meant driving the Supabase dashboard by hand:
blank pages, lost editor focus, stale results, columns that scroll off the
right edge. The verification loop repeats for every slice, so the loop itself
was worth fixing.

READ-ONLY IS STRUCTURAL, NOT DISCIPLINARY
-----------------------------------------
This module imports `select` BY NAME. `db.insert` never enters its namespace,
so there is no reference through which this tool could write — the same
reasoning as IDD-3D C3, where the Replay Engine has no path to execution
rather than a disabled one. A flag can be flipped; a missing reference cannot.

NO PII, BY CONSTRUCTION
-----------------------
COLUMNS below is an ALLOWLIST and the query never asks for `*`. If a column
carrying customer data is ever added to the table (it should not be — see the
migration), this tool still cannot print it, because it can only request
columns it names here.

The table itself holds no phone number, message text, prompt, model output or
raw evidence value. This is the second line of defence, not the first.
"""

import argparse
import json
import sys
from collections import Counter
from typing import Optional

from .config import DEFAULT_TENANT_ID, SUPABASE_URL  # noqa: F401  (diagnostics)
from .db import DbError, select                      # NOTE: `select` only.

TABLE = "bic_decision_records"

# Explicit allowlist. Never `select=*` — see the module docstring.
COLUMNS = (
    "decided_at", "turn_id", "brain_version", "route", "role",
    "identity_degraded", "decisive_rung", "ai_consulted",
    "ai_consultation_reason", "ai_provider", "selected_tools",
    "denied_tools", "latency_ms", "schema_version", "gate_results",
)

# Display abbreviations. Full values are always preserved in --json output;
# these exist only so a row fits an 80-column terminal.
_RUNG_SHORT = {
    "RUNG_1_CONSTITUTIONAL": "R1_CONST",
    "RUNG_2_POLICY": "R2_POLICY",
    "RUNG_3_DETERMINISTIC": "R3_DETERM",
    "RUNG_4_PRECEDENT": "R4_PRECED",
    "RUNG_5_MODEL_ADVISORY": "R5_MODEL",
    "NOT_EVALUATED": "NOT_EVAL",
}


# ── Query construction (pure) ──────────────────────────────────────────────

def build_params(limit: int = 20, since: Optional[str] = None,
                 until: Optional[str] = None, rung: Optional[str] = None,
                 ai: Optional[bool] = None, route: Optional[str] = None,
                 role: Optional[str] = None) -> dict:
    """PostgREST query parameters. Pure — no I/O, so it is testable offline."""
    params = {
        "select": ",".join(COLUMNS),
        "order": "decided_at.desc",
        "limit": str(limit),
    }
    if since is not None:
        params["decided_at"] = f"gte.{since}"
    if until is not None:
        # PostgREST takes repeated filters on one column as a list.
        params["decided_at"] = (
            [params["decided_at"], f"lte.{until}"] if "decided_at" in params
            else f"lte.{until}"
        )
    if rung is not None:
        params["decisive_rung"] = f"eq.{rung}"
    if ai is not None:
        params["ai_consulted"] = f"is.{str(ai).lower()}"
    if route is not None:
        params["route"] = f"eq.{route}"
    if role is not None:
        params["role"] = f"eq.{role}"
    return params


def fetch(params: dict, timeout: Optional[float] = None) -> list:
    """The ONLY I/O in this module. Raises DbError; main() maps it to exit 1."""
    return select(TABLE, params, timeout=timeout)


# ── Analysis (pure) ────────────────────────────────────────────────────────

def find_duplicates(rows: list) -> list:
    """turn_ids appearing more than once.

    Scope note: this examines only the rows FETCHED. It is a spot check over a
    window, not a proof about the whole table — raise --limit to widen it.
    Saying so matters: a duplicate check that quietly bounds itself would
    report "clean" on a table it never looked at.
    """
    counts = Counter(r.get("turn_id") for r in rows if r.get("turn_id"))
    return sorted((t, n) for t, n in counts.items() if n > 1)


def provider_summary(rows: list) -> list:
    """(provider, count), most frequent first.

    Turns where no model ran are counted as `<none>` rather than dropped —
    non-consultation is a recorded fact (IDD-3D §4.2), not an absence.
    """
    counts = Counter(
        (r.get("ai_provider") or "<none>") if r.get("ai_consulted")
        else "<none>"
        for r in rows
    )
    return counts.most_common()


def rung_summary(rows: list) -> list:
    counts = Counter(r.get("decisive_rung") or "?" for r in rows)
    return counts.most_common()


# ── Rendering (pure) ───────────────────────────────────────────────────────

def _fmt_time(value: str) -> str:
    """`2026-08-15T05:26:33.523682+00:00` → `08-15 05:26:33`."""
    if not value:
        return "?"
    v = value.replace("T", " ")
    return v[5:19] if len(v) >= 19 else v


def _fmt_list(value) -> str:
    if not value:
        return "-"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def render_table(rows: list) -> str:
    if not rows:
        return "no decision records matched"
    head = (f"{'when':<15} {'rung':<10} {'ai':<4} {'provider':<9} "
            f"{'tools':<16} {'denied':<10} {'ms':>8}")
    lines = [head, "-" * len(head)]
    for r in rows:
        rung = _RUNG_SHORT.get(r.get("decisive_rung"), r.get("decisive_rung") or "?")
        latency = r.get("latency_ms")
        lines.append(
            f"{_fmt_time(r.get('decided_at')):<15} "
            f"{rung:<10} "
            f"{('yes' if r.get('ai_consulted') else 'no'):<4} "
            f"{(r.get('ai_provider') or '-'):<9} "
            f"{_fmt_list(r.get('selected_tools')):<16} "
            f"{_fmt_list(r.get('denied_tools')):<10} "
            f"{(f'{float(latency):.0f}' if latency is not None else '-'):>8}"
        )
    lines.append("")
    lines.append(f"{len(rows)} record(s)")
    return "\n".join(lines)


def render_json(rows: list) -> str:
    return json.dumps(rows, indent=2, default=str, ensure_ascii=False)


def render_duplicates(dupes: list, scanned: int) -> str:
    if not dupes:
        return f"no duplicate turn_id in {scanned} record(s) scanned"
    out = [f"DUPLICATE turn_id found in {scanned} record(s) scanned:"]
    out += [f"  {turn_id}  x{n}" for turn_id, n in dupes]
    return "\n".join(out)


def render_summary(rows: list) -> str:
    if not rows:
        return "no decision records matched"
    out = [f"scanned {len(rows)} record(s)", "", "by provider:"]
    out += [f"  {name:<12} {n:>5}" for name, n in provider_summary(rows)]
    out += ["", "by decisive rung:"]
    out += [f"  {name:<24} {n:>5}" for name, n in rung_summary(rows)]
    return "\n".join(out)


# ── Entry point ────────────────────────────────────────────────────────────

def _parse_ai(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "yes", "1"):
        return True
    if v in ("false", "no", "0"):
        return False
    raise ValueError(f"--ai expects true or false, got {value!r}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m bic.decisions_cli",
        description="Read-only diagnostics for bic_decision_records. "
                    "Never writes. Never prints customer data.",
    )
    p.add_argument("-n", "--limit", type=int, default=20,
                   help="how many records to fetch (default 20)")
    p.add_argument("--since", help="ISO timestamp, e.g. 2026-08-15T05:00:00Z")
    p.add_argument("--until", help="ISO timestamp")
    p.add_argument("--rung", help="e.g. RUNG_5_MODEL_ADVISORY")
    p.add_argument("--ai", help="true | false")
    p.add_argument("--route", help="client | owner")
    p.add_argument("--role", help="CLIENT | STAFF | MANAGER | OWNER")
    p.add_argument("--duplicates", action="store_true",
                   help="report duplicate turn_id within the fetched window")
    p.add_argument("--providers", action="store_true",
                   help="summarise providers and rungs instead of listing rows")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv=None) -> int:
    """Returns a process exit code. 0 = ok, 1 = query/connection/usage error."""
    args = build_arg_parser().parse_args(argv)
    try:
        ai = _parse_ai(args.ai)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    params = build_params(limit=args.limit, since=args.since, until=args.until,
                          rung=args.rung, ai=ai, route=args.route, role=args.role)
    try:
        rows = fetch(params)
    except DbError as e:
        # Includes the missing-service-role-key case, which is the most common
        # reason this fails on a fresh machine.
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.duplicates:
        dupes = find_duplicates(rows)
        print(json.dumps({"scanned": len(rows), "duplicates": dupes}, indent=2)
              if args.json else render_duplicates(dupes, len(rows)))
    elif args.providers:
        print(json.dumps({"scanned": len(rows),
                          "providers": provider_summary(rows),
                          "rungs": rung_summary(rows)}, indent=2)
              if args.json else render_summary(rows))
    else:
        print(render_json(rows) if args.json else render_table(rows))
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
