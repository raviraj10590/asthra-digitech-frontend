"""The AI-extraction eligibility decision, made observable.

THE AMBIGUITY THIS CLOSES
-------------------------
The guard that decides whether extraction runs lives at the CALL SITE,
outside extract_lead_info:

    history = ctx["history"] + [user_msg, assistant_msg]
    if len(history) >= 4 and (len(history) < 8 or (len(history) // 2) % 2 == 0):
        lead = extract_lead_info(history)

So a guard-SKIP writes nothing anywhere — the lead_extraction recorder sits
inside the function that was never entered. "The guard said no" and "the
function was never called" were therefore indistinguishable in the data,
which is why the root cause had to be reconstructed by reading source.

WHAT THIS SLICE IS, AND IS NOT
------------------------------
It records the decision. It does not make one, change one, or change how
often extraction runs. The `if` is untouched byte for byte; the recorder
sits above it and observes the length it is about to test.

THE STRUCTURAL FACT THE DATA WILL NOW SHOW
------------------------------------------
fetch_context caps ctx["history"] at [-20:], so any conversation with >= 20
user/assistant messages yields len(history) == 22 forever, and
(22 // 2) % 2 == 1 -> periodic_skip. Extraction is permanently disabled for
mature conversations. That is NOT fixed here and NOT special-cased — 22
falls out of the formula like every other length.

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

# The lengths the task names, plus the boundaries either side of each rung.
LENGTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23]


def actual_guard(n):
    """The call-site expression, copied verbatim from api/webhook.py.

    Kept as a literal so the cross-check below compares the classifier
    against the REAL rule rather than against itself.
    """
    return n >= 4 and (n < 8 or (n // 2) % 2 == 0)


def record(history_len, audit_raises=None, bic=True, configured=True):
    """Drive the REAL recorder. Returns (rows, stdout)."""
    rows = []

    def fake_insert(table, row, timeout=None):
        rows.append({"table": table, "row": row})
        if audit_raises is not None:
            raise audit_raises

    buf = io.StringIO()
    with mock.patch.object(w, "BIC_AVAILABLE", bic), \
         mock.patch.object(w.bic_config, "is_configured", lambda: configured), \
         mock.patch.object(w.bic_db, "insert", fake_insert), \
         redirect_stdout(buf):
        w._record_extraction_guard(history_len)
    return [r["row"] for r in rows], buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# 1 · the classification, exactly as the existing guard behaves
# ══════════════════════════════════════════════════════════════════════════

class Classification(unittest.TestCase):

    EXPECTED = {
        0: (w.GUARD_SHORT_HISTORY, False),
        2: (w.GUARD_SHORT_HISTORY, False),
        3: (w.GUARD_SHORT_HISTORY, False),
        4: (w.GUARD_EARLY_PASS, True),
        6: (w.GUARD_EARLY_PASS, True),
        7: (w.GUARD_EARLY_PASS, True),
        8: (w.GUARD_PERIODIC_PASS, True),
        10: (w.GUARD_PERIODIC_SKIP, False),
        12: (w.GUARD_PERIODIC_PASS, True),
        20: (w.GUARD_PERIODIC_PASS, True),
        22: (w.GUARD_PERIODIC_SKIP, False),
    }

    def test_every_required_length_classifies_correctly(self):
        for n, expected in self.EXPECTED.items():
            with self.subTest(history_len=n):
                self.assertEqual(w._extraction_guard_reason(n), expected)

    def test_the_recorded_row_carries_reason_and_eligible(self):
        for n, (reason, eligible) in self.EXPECTED.items():
            with self.subTest(history_len=n):
                rows, _ = record(n)
                a = rows[0]["args_redacted"]
                self.assertEqual(a["history_len"], n)
                self.assertEqual(a["reason"], reason)
                self.assertIs(a["eligible"], eligible)

    def test_saturated_length_22_is_periodic_skip(self):
        """The production case: ctx['history'] caps at 20, so len is 22 for
        every mature conversation, forever."""
        rows, _ = record(22)
        a = rows[0]["args_redacted"]
        self.assertEqual(a["reason"], w.GUARD_PERIODIC_SKIP)
        self.assertFalse(a["eligible"])

    def test_22_is_not_special_cased_in_the_source(self):
        """It must fall out of the formula, not be hardcoded — a magic 22
        would hide the structural cause."""
        import inspect
        src = inspect.getsource(w._extraction_guard_reason)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#")).split('"""')[-1]
        self.assertNotIn("22", code)

    def test_the_four_reasons_are_the_only_ones(self):
        seen = {w._extraction_guard_reason(n)[0] for n in range(0, 200)}
        self.assertEqual(seen, {w.GUARD_SHORT_HISTORY, w.GUARD_EARLY_PASS,
                                w.GUARD_PERIODIC_PASS, w.GUARD_PERIODIC_SKIP})


class ClassifierMatchesTheRealGuard(unittest.TestCase):
    """THE ANTI-DRIFT TEST. The classifier is a second expression of the same
    rule; this pins it against the actual call-site expression so a change to
    either is caught."""

    def test_eligible_agrees_with_the_guard_expression_everywhere(self):
        for n in range(0, 300):
            with self.subTest(history_len=n):
                self.assertEqual(w._extraction_guard_reason(n)[1],
                                 actual_guard(n))

    def test_pass_reasons_imply_eligible_and_skip_reasons_do_not(self):
        for n in range(0, 300):
            reason, eligible = w._extraction_guard_reason(n)
            if reason in (w.GUARD_EARLY_PASS, w.GUARD_PERIODIC_PASS):
                self.assertTrue(eligible, n)
            else:
                self.assertFalse(eligible, n)

    def test_the_call_site_guard_source_is_unchanged(self):
        """Byte-level: the exact expression must still be present."""
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn(
            "if len(history) >= 4 and (len(history) < 8 or "
            "(len(history) // 2) % 2 == 0):", src)


# ══════════════════════════════════════════════════════════════════════════
# 2 · the row shape, and what it must never contain
# ══════════════════════════════════════════════════════════════════════════

class RowShape(unittest.TestCase):

    def test_it_is_recorded_as_an_observation_not_a_failure(self):
        """periodic_skip is the guard working as written. Recording it as a
        failed call would fill the failure index with correct behaviour."""
        for n in (3, 10, 22):
            rows, _ = record(n)
            self.assertTrue(rows[0]["ok"], n)
            self.assertIsNone(rows[0]["error"], n)

    def test_the_fixed_fields_match_the_contract(self):
        row = record(22)[0][0]
        self.assertEqual(row["tool"], "lead_extraction_guard")
        self.assertEqual(row["role"], "CLIENT")
        self.assertEqual(row["channel"], "whatsapp")
        self.assertEqual(row["latency_ms"], 0)
        self.assertIsNone(row["tokens_in"])
        self.assertIsNone(row["tokens_out"])
        self.assertIsNone(row["source_ref"])
        self.assertIn("started_at", row)
        self.assertIn("finished_at", row)

    def test_args_redacted_holds_exactly_three_keys(self):
        a = record(12)[0][0]["args_redacted"]
        self.assertEqual(sorted(a), ["eligible", "history_len", "reason"])

    def test_history_len_is_a_count_never_content(self):
        a = record(22)[0][0]["args_redacted"]
        self.assertIsInstance(a["history_len"], int)

    def test_it_targets_the_existing_audit_table(self):
        rows = []
        with mock.patch.object(w, "BIC_AVAILABLE", True), \
             mock.patch.object(w.bic_config, "is_configured", lambda: True), \
             mock.patch.object(w.bic_db, "insert",
                               lambda t, r, timeout=None: rows.append(t)):
            w._record_extraction_guard(22)
        self.assertEqual(rows, ["bic_tool_invocations"])

    def test_the_event_is_not_a_registered_tool(self):
        mig = os.path.join(os.path.dirname(__file__), "..", "supabase",
                           "migrations")
        for name in os.listdir(mig):
            with open(os.path.join(mig, name)) as fh:
                sql = "\n".join(l for l in fh if not l.strip().startswith("--"))
            self.assertNotIn(f"'{w.LEAD_EXTRACTION_GUARD_EVENT}'", sql, name)


class NoPiiIsPersisted(unittest.TestCase):

    def test_no_transcript_prompt_phone_or_lead_values_in_the_row(self):
        row = record(22)[0][0]
        blob = str(row)
        for secret in ("Ravi Kumar", "Acme Traders", "919999000444",
                       "sales analyst", "budget", "Bengaluru", "content"):
            self.assertNotIn(secret, blob, secret)

    def test_the_recorder_takes_only_an_integer(self):
        """STRUCTURAL: it cannot leak a transcript because it is never given
        one. The signature is the guarantee."""
        import inspect
        params = list(inspect.signature(w._record_extraction_guard).parameters)
        self.assertEqual(params, ["history_len"])


# ══════════════════════════════════════════════════════════════════════════
# 3 · best-effort — the customer path is never affected
# ══════════════════════════════════════════════════════════════════════════

class BestEffort(unittest.TestCase):

    def test_an_audit_failure_does_not_raise(self):
        _, out = record(22, audit_raises=RuntimeError("store down"))
        self.assertIn("LEAD_EXTRACTION_GUARD_AUDIT_FAILED", out)

    def test_an_audit_failure_logs_the_type_only(self):
        _, out = record(22, audit_raises=RuntimeError("phone 919999000444"))
        self.assertIn("RuntimeError", out)
        self.assertNotIn("919999000444", out)

    def test_nothing_is_recorded_when_bic_is_unavailable(self):
        rows, _ = record(22, bic=False)
        self.assertEqual(rows, [])

    def test_nothing_is_recorded_when_bic_is_unconfigured(self):
        rows, _ = record(22, configured=False)
        self.assertEqual(rows, [])


# ══════════════════════════════════════════════════════════════════════════
# 4 · the customer path, end to end, is byte-for-byte equivalent
# ══════════════════════════════════════════════════════════════════════════

class CustomerPathUnchanged(unittest.TestCase):
    """Drives the REAL run_client_pipeline and asserts the recorder changed
    neither whether extraction ran nor how often."""

    def pipeline(self, ctx_history_len, bic=True, audit_raises=None):
        calls = {"extract": 0, "guard_rows": []}
        ctx = {"history": [{"role": "user", "content": "x"}
                           for _ in range(ctx_history_len)],
               "paused": False, "vip_alerted": False, "lead_alerted": False,
               "recent_sys": [], "last_user": {}}

        def fake_insert(table, row, timeout=None):
            if row.get("tool") == "lead_extraction_guard":
                calls["guard_rows"].append(row["args_redacted"])
            if audit_raises is not None:
                raise audit_raises

        def fake_extract(history):
            calls["extract"] += 1
            return {}

        with ExitStack() as st:
            p = st.enter_context
            p(mock.patch.object(w, "extract_lead_info", fake_extract))
            p(mock.patch.object(w, "BIC_AVAILABLE", bic))
            p(mock.patch.object(w.bic_config, "is_configured", lambda: True))
            p(mock.patch.object(w.bic_db, "insert", fake_insert))
            p(mock.patch.object(w, "send_text", lambda *a, **k: None))
            p(mock.patch.object(w, "save_messages", lambda *a, **k: None))
            p(mock.patch.object(w, "save_message", lambda *a, **k: None))
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
            # The new-contact branch (ctx history empty) sends the welcome
            # menu and records first_seen. Both reach the network; stubbed so
            # this suite can never make an outbound request.
            p(mock.patch.object(w, "send_welcome_menu", lambda *a, **k: None))
            p(mock.patch.object(w, "record_first_seen", lambda *a, **k: None))
            p(mock.patch.object(w, "send_brochure", lambda *a, **k: True))
            p(mock.patch.object(w, "send_typing", lambda *a, **k: None))
            p(redirect_stdout(io.StringIO()))
            w.run_client_pipeline("919555555555", "hello", ctx)
        return calls

    def test_mature_conversation_skips_extraction_and_records_the_skip(self):
        """ctx history 20 -> len(history) 22 -> periodic_skip. The production
        case, end to end."""
        calls = self.pipeline(20)
        self.assertEqual(calls["extract"], 0)
        self.assertEqual(calls["guard_rows"][0]["history_len"], 22)
        self.assertEqual(calls["guard_rows"][0]["reason"], w.GUARD_PERIODIC_SKIP)

    def test_an_eligible_conversation_still_runs_extraction(self):
        calls = self.pipeline(10)          # len(history) == 12 -> pass
        self.assertEqual(calls["extract"], 1)
        self.assertEqual(calls["guard_rows"][0]["reason"], w.GUARD_PERIODIC_PASS)

    def test_extraction_count_matches_the_guard_across_lengths(self):
        """The decisive equivalence: the recorder must not have changed WHEN
        extraction runs, for any history length."""
        for ctx_len in range(0, 24):
            with self.subTest(ctx_history=ctx_len):
                calls = self.pipeline(ctx_len)
                expected = 1 if actual_guard(ctx_len + 2) else 0
                self.assertEqual(calls["extract"], expected)

    def test_exactly_one_guard_row_per_turn(self):
        """One row per turn that REACHES the guard — i.e. the normal-AI-reply
        branch. ctx history 0 is excluded deliberately: an empty history means
        is_new_contact, which takes the welcome-menu branch and never reaches
        the extraction block at all."""
        for ctx_len in (5, 10, 20):
            calls = self.pipeline(ctx_len)
            self.assertEqual(len(calls["guard_rows"]), 1, ctx_len)

    def test_a_new_contact_never_reaches_the_guard(self):
        """is_new_contact = not ctx["history"], so a first-ever message goes
        to the welcome menu. No extraction, and no guard row — existing
        behaviour, pinned so the recorder cannot have widened the branch."""
        calls = self.pipeline(0)
        self.assertEqual(calls["extract"], 0)
        self.assertEqual(calls["guard_rows"], [])

    def test_bic_unavailable_does_not_change_the_customer_path(self):
        for ctx_len in (2, 10, 20):
            with self.subTest(ctx_history=ctx_len):
                on = self.pipeline(ctx_len, bic=True)
                off = self.pipeline(ctx_len, bic=False)
                self.assertEqual(on["extract"], off["extract"])
                self.assertEqual(off["guard_rows"], [])

    def test_an_audit_failure_does_not_change_the_customer_path(self):
        clean = self.pipeline(10)
        broken = self.pipeline(10, audit_raises=RuntimeError("store down"))
        self.assertEqual(clean["extract"], broken["extract"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
