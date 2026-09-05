"""The extraction cadence dead zone — measured on progress, not on the window.

THE DEFECT
----------
fetch_context caps ctx["history"] at [-20:]. run_client_pipeline appends the
current user and assistant messages, so len(history) pins at exactly 22 for
every established chat. The rule was:

    if len(history) >= 4 and (len(history) < 8 or (len(history) // 2) % 2 == 0)

and (22 // 2) % 2 == 1, so 22 evaluated to SKIP — forever. Extraction was
permanently dead for exactly the mature conversations most likely to hold a
real lead. Production confirmed it: 17 upsert_lead executions, every one from
a menu tap, none from this path.

THE CORRECTION
--------------
The RULE is unchanged — same thresholds, same modulo, same intent ("every turn
while the chat is short, then every 2nd turn once established"). Only the
NUMBER it reads changed: from the truncated window to the unbounded count of
rows this chat actually has, which PostgREST already returns for free in
Content-Range on the query fetch_context was making anyway.

WHY ALTERNATION SURVIVES
------------------------
Each turn stores exactly two rows, so depth // 2 advances by exactly one per
turn and its parity flips every turn — precisely "every 2nd turn". A system
marker adds one row and can shift the PHASE once; it cannot break alternation.

Offline: no network, no provider, no database.
"""

import io
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

HISTORY_CAP = 20        # fetch_context's [-20:]
SATURATED = HISTORY_CAP + 2   # what len(history) pins at: 22


def old_rule(n):
    """The pre-fix expression, kept verbatim so the dead zone can be
    demonstrated rather than asserted from memory."""
    return n >= 4 and (n < 8 or (n // 2) % 2 == 0)


class Pipeline:
    """Drives the REAL run_client_pipeline over successive turns against an
    in-memory message store, so the cadence is observed end to end rather
    than computed from the guard in isolation.
    """

    def __init__(self, count_available=True):
        self.rows = []                 # every stored message row
        self.count_available = count_available
        self.extractions = []          # turn index of each extraction
        self.guard_rows = []

    def ctx(self):
        """Mirrors fetch_context: window capped at 20, plus the total count."""
        convo = [r for r in self.rows if r["role"] in ("user", "assistant")]
        return {
            "history": [{"role": r["role"], "content": r["content"]}
                        for r in convo][-HISTORY_CAP:],
            "paused": False, "vip_alerted": False, "lead_alerted": False,
            "recent_sys": [], "last_user": {},
            "stored_messages": len(self.rows) if self.count_available else None,
        }

    def run(self, turns):
        """Patches are entered ONCE for the whole run, not per turn.

        Entering ~18 mock patches per turn made a 60-turn test cost seconds
        and inflated the full suite from ~19s to ~86s. The cost was entirely
        in this harness, not in the code under test.
        """
        def fake_save(items):
            for _p, role, content in items:
                self.rows.append({"role": role, "content": content})

        def fake_insert(table, row, timeout=None):
            if row.get("tool") == "lead_extraction_guard":
                self.guard_rows.append(row["args_redacted"])

        with ExitStack() as st:
            p = st.enter_context
            p(mock.patch.object(w, "save_messages", fake_save))
            p(mock.patch.object(w, "save_message", lambda *a, **k: None))
            # BIC on, so _record_extraction_guard actually writes telemetry.
            p(mock.patch.object(w, "BIC_AVAILABLE", True))
            p(mock.patch.object(w.bic_config, "is_configured", lambda: True))
            p(mock.patch.object(w.bic_db, "insert", fake_insert))
            # ...but the Brain DECIDE path is stubbed to the legacy branch.
            # The cadence block sits AFTER the decide/legacy if-else and runs
            # identically in both, so driving the full 3A stack per turn would
            # buy no coverage — it only made these tests ~15x slower and
            # coupled a cadence test to the whole Brain.
            p(mock.patch.object(w, "_bic_decide_and_record",
                                lambda *a, **k: None))
            p(mock.patch.object(w.bic_outcome_producers,
                                "observe_customer_reply", lambda *a, **k: None))
            p(mock.patch.object(w.bic_outcome_producers,
                                "expect_customer_reply", lambda *a, **k: None))
            p(mock.patch.object(w.bic_decision, "is_open", lambda: False))
            p(mock.patch.object(w, "send_text", lambda *a, **k: None))
            p(mock.patch.object(w, "generate_reply", lambda *a, **k: "REPLY"))
            p(mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None))
            p(mock.patch.object(w, "maybe_alert_lead", lambda *a, **k: None))
            p(mock.patch.object(w, "notify_owner", lambda *a, **k: None))
            p(mock.patch.object(w, "run_workflows", lambda *a, **k: None))
            p(mock.patch.object(w, "update_memory", lambda *a, **k: None))
            p(mock.patch.object(w, "upsert_lead", lambda *a, **k: None))
            p(mock.patch.object(w, "after_hours_note", lambda: ""))
            p(mock.patch.object(w, "is_menu_request", lambda t: False))
            p(mock.patch.object(w, "is_off_topic", lambda t: False))
            p(mock.patch.object(w, "is_brochure_request", lambda t: False))
            p(mock.patch.object(w, "send_welcome_menu", lambda *a, **k: None))
            p(mock.patch.object(w, "record_first_seen", lambda *a, **k: None))
            p(redirect_stdout(io.StringIO()))

            turn_no = {"n": 0}

            def fake_extract(history):
                self.extractions.append(turn_no["n"])
                return {}
            p(mock.patch.object(w, "extract_lead_info", fake_extract))

            for n in range(1, turns + 1):
                turn_no["n"] = n
                w.run_client_pipeline("919555555555", f"msg {n}", self.ctx())
        return self


# ══════════════════════════════════════════════════════════════════════════
# 1 · the dead zone, demonstrated and then removed
# ══════════════════════════════════════════════════════════════════════════

class TheDeadZone(unittest.TestCase):

    def test_the_old_rule_rejects_the_saturated_value_forever(self):
        """Demonstrates the defect rather than asserting it: 22 is what
        len(history) pins at, and the old rule said SKIP on it."""
        self.assertFalse(old_rule(SATURATED))
        self.assertEqual(SATURATED, 22)

    def test_a_mature_conversation_still_gets_extractions(self):
        """THE FIX. 40 turns is far past the 20-message cap."""
        p = Pipeline().run(40)
        late = [t for t in p.extractions if t > 12]
        self.assertTrue(late, "extraction is still dead after saturation")

    def test_history_len_saturates_while_depth_keeps_climbing(self):
        """The divergence IS the fix, and both numbers are recorded."""
        p = Pipeline().run(30)
        tail = p.guard_rows[-6:]
        self.assertTrue(all(g["history_len"] == SATURATED for g in tail),
                        "the window should be pinned at 22")
        depths = [g["depth"] for g in tail]
        self.assertEqual(depths, sorted(depths))
        self.assertTrue(depths[-1] > depths[0], "depth must keep climbing")

    def test_extraction_never_stops_over_a_long_conversation(self):
        """No trailing dead stretch: the last quarter must contain runs."""
        p = Pipeline().run(60)
        self.assertTrue([t for t in p.extractions if t > 45])


# ══════════════════════════════════════════════════════════════════════════
# 2 · the cadence itself is preserved
# ══════════════════════════════════════════════════════════════════════════

class CadencePreserved(unittest.TestCase):

    def test_short_conversations_extract_on_every_eligible_turn(self):
        """"EVERY turn while the chat is short" — unchanged."""
        p = Pipeline().run(3)
        # turn 1 is a new contact (empty history -> welcome menu, no guard)
        self.assertEqual(p.extractions, [2, 3])

    def test_early_behaviour_is_identical_to_the_old_rule(self):
        """While under the cap the two measures are equal, so nothing about
        early conversations can have changed."""
        p = Pipeline().run(9)
        for g in p.guard_rows:
            self.assertEqual(g["depth"], g["history_len"])

    def test_extraction_does_not_run_on_every_mature_turn(self):
        """The cadence must not degrade into "always"."""
        p = Pipeline().run(40)
        mature = [t for t in p.extractions if t >= 10]
        turns_mature = [t for t in range(10, 41)]
        self.assertLess(len(mature), len(turns_mature),
                        "extraction ran on every mature turn")

    def test_mature_cadence_is_every_second_turn(self):
        """Alternation, exactly: consecutive extraction turns differ by 2."""
        p = Pipeline().run(40)
        mature = [t for t in p.extractions if t >= 12]
        gaps = {b - a for a, b in zip(mature, mature[1:])}
        self.assertEqual(gaps, {2}, f"expected strict every-2nd-turn, got {gaps}")

    def test_roughly_half_of_mature_turns_extract(self):
        p = Pipeline().run(60)
        mature = [t for t in p.extractions if t >= 12]
        self.assertAlmostEqual(len(mature) / 49, 0.5, delta=0.08)

    def test_a_new_contact_never_reaches_the_guard(self):
        p = Pipeline().run(1)
        self.assertEqual(p.extractions, [])
        self.assertEqual(p.guard_rows, [])


# ══════════════════════════════════════════════════════════════════════════
# 3 · the fallback, and the count parser
# ══════════════════════════════════════════════════════════════════════════

class FallbackWhenCountUnknown(unittest.TestCase):

    def test_without_the_count_the_old_windowed_value_is_used(self):
        """No worse than today — never a guess, never a zero."""
        p = Pipeline(count_available=False).run(30)
        tail = p.guard_rows[-5:]
        self.assertTrue(all(g["depth_source"] == w.GUARD_SOURCE_HISTORY
                            for g in tail))
        self.assertTrue(all(g["depth"] == SATURATED for g in tail))

    def test_the_count_source_is_labelled_when_available(self):
        p = Pipeline().run(6)
        self.assertTrue(all(g["depth_source"] == w.GUARD_SOURCE_STORED
                            for g in p.guard_rows))

    def test_content_range_parsing(self):
        self.assertEqual(w._content_range_total("0-44/2226"), 2226)
        self.assertEqual(w._content_range_total("0-0/1"), 1)
        for bad in (None, "", "*/*", "0-44/*", "garbage", 7.5, []):
            self.assertIsNone(w._content_range_total(bad), bad)

    def test_an_unknown_count_is_never_treated_as_zero(self):
        """Zero would read as "brand new conversation" for someone
        mid-negotiation, and would restart the every-turn cadence."""
        self.assertIsNone(w._content_range_total("*/*"))

    def test_fetch_context_requests_the_count(self):
        import inspect
        src = inspect.getsource(w.fetch_context)
        self.assertIn('_supa_headers("count=exact")', src)
        self.assertIn("Content-Range", src)


# ══════════════════════════════════════════════════════════════════════════
# 4 · telemetry, and everything that must not have changed
# ══════════════════════════════════════════════════════════════════════════

class TelemetryStillAccurate(unittest.TestCase):

    def test_every_guard_row_reports_a_reason_and_matches_eligibility(self):
        p = Pipeline().run(30)
        for g in p.guard_rows:
            expected = w._extraction_guard_reason(g["depth"])
            self.assertEqual((g["reason"], g["eligible"]), expected)

    def test_eligible_rows_correspond_to_actual_extractions(self):
        """Telemetry must describe what really happened, not what was
        intended: one eligible row per extraction."""
        p = Pipeline().run(30)
        self.assertEqual(len([g for g in p.guard_rows if g["eligible"]]),
                         len(p.extractions))

    def test_one_guard_row_per_turn_that_reaches_the_guard(self):
        p = Pipeline().run(12)
        self.assertEqual(len(p.guard_rows), 11)   # turn 1 is the new contact

    def test_no_pii_in_the_telemetry(self):
        p = Pipeline().run(12)
        blob = str(p.guard_rows)
        for secret in ("919555555555", "msg ", "REPLY", "content"):
            self.assertNotIn(secret, blob, secret)
        for g in p.guard_rows:
            self.assertEqual(sorted(g), ["depth", "depth_source", "eligible",
                                         "history_len", "reason"])
            self.assertIsInstance(g["depth"], int)
            self.assertIsInstance(g["history_len"], int)


class UnrelatedPathsUnchanged(unittest.TestCase):

    def test_the_rule_thresholds_and_modulo_are_unchanged(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      src)

    def test_extraction_is_still_inside_the_guard(self):
        """Moving the call outside would make it run every turn."""
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        i_guard = src.index("if depth >= 4 and (depth < 8")
        i_call = src.index("lead = extract_lead_info(history)")
        self.assertLess(i_guard, i_call)

    def test_extract_lead_info_provider_config_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.extract_lead_info)
        self.assertIn('model="gpt-4o-mini"', src)
        self.assertIn("max_tokens=380", src)
        self.assertIn("temperature=0", src)
        self.assertIn("generate_reply_gemini", src)
        self.assertIn("if len(history) < 3:", src)

    def test_the_service_role_lead_write_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.upsert_lead)
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")', src)
        self.assertNotIn("_supa_headers", src)

    def test_the_menu_list_reply_path_is_unchanged(self):
        """handle_list_reply upserts on a menu tap and never consults the
        cadence guard — the one path that kept working."""
        import inspect
        src = inspect.getsource(w.handle_list_reply)
        self.assertIn('upsert_lead(to, {"service_needed": service})', src)
        self.assertNotIn("depth", src)

    def test_the_owner_path_is_unchanged(self):
        import inspect
        src = inspect.getsource(w.handle_owner_text)
        for banned in ("depth", "extract_lead_info", "stored_messages"):
            self.assertNotIn(banned, src)

    def test_the_shared_supabase_helper_is_still_anon(self):
        import inspect
        src = inspect.getsource(w._supa_headers)
        self.assertIn("SUPABASE_KEY", src)
        self.assertNotIn("SERVICE_ROLE", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
