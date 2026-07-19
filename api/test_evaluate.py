"""Unit tests for the AI Evaluation Engine (evaluate.py).

Covers the pure logic: grouping, completion detection, transcript building,
score normalization/clamping, and report formatting. The GPT call itself is
network and not tested here.

Run:  python3 api/test_evaluate.py
"""
import importlib.util
from datetime import datetime, timezone, timedelta

spec = importlib.util.spec_from_file_location("ev", "api/evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
def ago(mins):
    return (NOW - timedelta(minutes=mins)).isoformat()

passed = 0
def check(name, cond):
    global passed
    assert cond, f"FAILED: {name}"
    passed += 1
    print(f"  ✓ {name}")

# ── grouping ──────────────────────────────────────────────────────────────────
print("grouping:")
rows = [
    {"phone": "91A", "role": "user", "content": "hi", "created_at": ago(120)},
    {"phone": "91B", "role": "user", "content": "price?", "created_at": ago(30)},
    {"phone": "91A", "role": "assistant", "content": "namaskara", "created_at": ago(119)},
]
g = ev.group_conversations(rows)
check("groups by phone", set(g) == {"91A", "91B"})
check("sorts oldest-first", g["91A"][0]["content"] == "hi" and g["91A"][1]["content"] == "namaskara")

# ── completion detection ──────────────────────────────────────────────────────
print("completion:")
check("quiet 120min chat is completed", ev.is_completed(g["91A"], NOW, 60) is True)
check("active 30min chat NOT completed", ev.is_completed(g["91B"], NOW, 60) is False)
check("empty chat not completed", ev.is_completed([], NOW, 60) is False)

# ── transcript ────────────────────────────────────────────────────────────────
print("transcript:")
msgs = [
    {"role": "user", "content": "website beku", "created_at": ago(100)},
    {"role": "system", "content": "LEAD_ALERTED", "created_at": ago(99)},
    {"role": "assistant", "content": "yaava type?", "created_at": ago(98)},
]
t = ev.build_transcript(msgs)
check("tags roles", "CUSTOMER: website beku" in t and "BOT: yaava type?" in t)
check("skips system markers", "LEAD_ALERTED" not in t)

# ── score normalization / clamping ────────────────────────────────────────────
print("normalization:")
raw = {"response_quality": "90", "lead_qualification": 85, "buying_intent_detection": "88%",
       "objection_handling": 200, "conversation_flow": -10, "repeated_questions": 100,
       "hallucination_risk": 95, "policy_compliance": 100, "meeting_conversion": 40,
       "overall_score": 91, "strengths": ["good qualification", "  ", "correct objection handling", "x4", "x5"],
       "weaknesses": ["missed meeting ask"], "improvement": " Ask for a meeting after budget. "}
n = ev.normalize_eval(raw)
check("string→int", n["response_quality"] == 90)
check("percent stripped", n["buying_intent_detection"] == 88)
check("clamps over 100", n["objection_handling"] == 100)
check("clamps under 0", n["conversation_flow"] == 0)
check("strengths trimmed + capped at 3", n["strengths"] == ["good qualification", "correct objection handling", "x4"])
check("improvement trimmed", n["improvement"] == "Ask for a meeting after budget.")
check("overall preserved", n["overall_score"] == 91)

# overall fallback = mean of the nine when omitted
raw2 = {k: 80 for k in ev.DIMENSIONS[:-1]}
n2 = ev.normalize_eval(raw2)
check("overall falls back to mean", n2["overall_score"] == 80)

# garbage inputs degrade to None, not crash
n3 = ev.normalize_eval({"response_quality": "banana", "strengths": "notalist"})
check("garbage score → None", n3["response_quality"] is None)
check("non-list strengths → []", n3["strengths"] == [])

# ── report formatting (matches the requested example shape) ───────────────────
print("report:")
report = ev.format_report(n)
check("has score line", report.startswith("Conversation Score: 91/100"))
check("has Strengths section", "Strengths:\n- good qualification" in report)
check("has Weaknesses section", "Weaknesses:\n- missed meeting ask" in report)
check("has Recommended Improvement", "Recommended Improvement:\nAsk for a meeting after budget." in report)

# ── gating ────────────────────────────────────────────────────────────────────
print("env gating:")
ev.EVAL_TABLE = ""
check("already_evaluated no-op without table", ev.already_evaluated("91A", NOW.isoformat()) is False)
check("store_eval no-op without table", ev.store_eval("91A", "t", {}, "r") is None)

print(f"\n✅ ALL {passed} EVALUATION TESTS PASSED")
print("\n── sample report ──")
print(report)
