"""Unit tests for the hierarchical memory system (webhook.py).

Covers requirement #9: creation, retrieval, updates, and summary compression,
plus the freshness/staleness rules (#7, #8). Pure-function tests — no network.

Run:  python3 api/test_memory.py
"""
import importlib.util
from datetime import datetime, timezone, timedelta

spec = importlib.util.spec_from_file_location("wh", "api/webhook.py")
wh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wh)

NOW = "2026-07-19T12:00:00+00:00"
def days_ago(n):
    return (datetime.fromisoformat(NOW) - timedelta(days=n)).isoformat()

passed = 0
def check(name, cond):
    global passed
    assert cond, f"FAILED: {name}"
    passed += 1
    print(f"  ✓ {name}")

# ── 1. CREATION: empty profile + first facts ──────────────────────────────────
print("creation:")
p = wh.merge_profile({}, {"name": "Suresh", "budget": "30k", "service_needed": "Website"}, now=NOW)
check("stores value+ts", p["name"] == {"value": "Suresh", "ts": NOW})
check("captures budget", wh.profile_value(p, "budget") == "30k")
check("ignores absent fields", "company" not in p)
check("skips empty strings", wh.merge_profile({}, {"name": "  "}, now=NOW) == {})

# ── 2. RETRIEVAL: context rendering, never re-ask fresh facts ──────────────────
print("retrieval:")
mem = {"profile": p, "summary": "Wants an e-commerce site.", "history": ["Bought logo 2025"]}
ctx = wh.build_memory_context(mem, now=NOW)
check("marks known facts do-not-ask", "do NOT ask again" in ctx and "budget=30k" in ctx)
check("includes prior summary", "e-commerce" in ctx)
check("includes business history", "Bought logo 2025" in ctx)
check("empty memory → empty string", wh.build_memory_context({}) == "")
check("profile-only, no summary still renders", "KNOWN" in wh.build_memory_context({"profile": p}, now=NOW))

# ── 3. UPDATE / FRESHNESS: newer budget overwrites, identity fills once (#8) ───
print("updates & freshness:")
old = {"budget": {"value": "20k", "ts": days_ago(2)}, "name": {"value": "Suresh", "ts": days_ago(2)}}
upd = wh.merge_profile(old, {"budget": "50k", "name": "Ravi"}, now=NOW)
check("refreshable budget overwrites", wh.profile_value(upd, "budget") == "50k")
check("budget ts bumped", upd["budget"]["ts"] == NOW)
check("identity name does NOT overwrite", wh.profile_value(upd, "name") == "Suresh")
same = wh.merge_profile(old, {"budget": "20k"}, now=NOW)
check("unchanged value keeps old ts", same["budget"]["ts"] == days_ago(2))

# ── 4. STALENESS: fresh=keep quiet, old=may re-confirm, missing=ask (#7) ───────
print("staleness:")
fresh = {"budget": {"value": "30k", "ts": days_ago(5)}}
stale = {"budget": {"value": "30k", "ts": days_ago(40)}}
check("fresh fact not stale", wh.is_stale(fresh, "budget", now=NOW) is False)
check("40-day fact is stale", wh.is_stale(stale, "budget", now=NOW) is True)
check("missing fact is stale", wh.is_stale({}, "budget", now=NOW) is True)
sc = wh.build_memory_context({"profile": stale}, now=NOW)
check("stale fact offered for re-confirm", "MAY re-confirm" in sc)

# ── 5. COMPRESSION: long history folds into summary (#6) ───────────────────────
print("compression:")
short = [{"role": "user", "content": "hi"}] * 4
long = [{"role": "user", "content": "x"}] * 20
s1, keep1 = wh.compress_history(short, "", "New summary")
check("short chat kept raw", keep1 == 4)
check("summary stored even when short", s1 == "New summary")
s2, keep2 = wh.compress_history(long, "old", "fresh summary")
check("long chat compressed to cap", keep2 == wh.MEMORY_HISTORY_COMPRESS_AT)
check("prefers newest summary", s2 == "fresh summary")
s3, _ = wh.compress_history(long, "old summary", "")
check("falls back to prior summary", s3 == "old summary")

# ── 6. GATING: no table → pure no-ops (existing behaviour preserved) ──────────
print("env gating:")
wh.MEMORY_TABLE = ""
check("fetch_memory no-op without table", wh.fetch_memory("91999") == {})
check("update_memory no-op without table", wh.update_memory("91999", {}, "", [], {}) is None)

print(f"\n✅ ALL {passed} MEMORY TESTS PASSED")
