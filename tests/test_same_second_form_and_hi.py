"""Form + "Hi" in the same second (live: ...3450, 2026-09-27).

Two parallel invocations: the form's got the Bairavi reply, the "Hi" saw an
empty history and sent the Asthra welcome menu too. The "Hi" now looks once
more before greeting; any doubt keeps today's behaviour (menu).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402
import webhook as w  # noqa: E402
from test_review_0927 import FORM  # noqa: E402

FORM_ROW = {"role": "user", "content": FORM.format(loc="Sira")}
MARKER_ROW = {"role": "assistant", "content": b.flow_marker((b.AWAITING_DELIVERY,))}


def check(ctx=None, error=None, seconds_left=25.0):
    def fetch(phone):
        if error:
            raise error
        return ctx
    slept = []
    with mock.patch.object(w, "fetch_context", fetch), \
         mock.patch.object(w.time, "sleep", slept.append), \
         mock.patch.object(w, "ai_seconds_left", lambda *a: seconds_left):
        return w.bairavi_arrived_meanwhile("910000000000"), slept


class LookAgainBeforeTheMenu(unittest.TestCase):
    def test_the_real_case_form_already_there(self):
        self.assertTrue(check({"history": [FORM_ROW, MARKER_ROW]})[0])

    def test_form_saved_reply_not_yet(self):
        self.assertTrue(check({"history": [FORM_ROW]})[0])

    def test_marker_alone(self):
        self.assertTrue(check({"history": [MARKER_ROW]})[0])

    def test_a_real_new_contact_still_gets_the_menu(self):
        found, slept = check({"history": []})
        self.assertFalse(found)
        self.assertEqual(slept, [w.NEW_CONTACT_RECHECK_SECONDS])

    def test_other_history_is_not_bairavi(self):
        self.assertFalse(check({"history": [{"role": "user", "content": "hello"},
                                            {"role": "assistant", "content": "ನಮಸ್ಕಾರ"}]})[0])

    def test_failed_reread_sends_the_menu(self):
        self.assertFalse(check(error=RuntimeError("down"))[0])

    def test_degraded_reread_sends_the_menu(self):
        self.assertFalse(check({"history": [FORM_ROW], "degraded": True})[0])

    def test_short_deadline_skips_the_wait(self):
        found, slept = check({"history": [FORM_ROW]}, seconds_left=5.0)
        self.assertFalse(found)
        self.assertEqual(slept, [])


class ThroughThePipeline(unittest.TestCase):
    def run_hi(self, arrived):
        sent, saved = [], []
        with mock.patch.object(w, "bairavi_arrived_meanwhile", lambda p: arrived), \
             mock.patch.object(w, "send_welcome_menu", lambda to: sent.append("<MENU>")), \
             mock.patch.object(w, "save_message", lambda *a, **k: (saved.append(a), w.SAVE_OK)[1]):
            from test_interpretation_shadow import run_conversation
            run = run_conversation(["Hi"])
        return run, sent, saved

    def test_hi_after_parallel_form_gets_no_menu(self):
        run, sent, saved = self.run_hi(True)
        self.assertNotIn("<MENU>", sent + run.sent)
        self.assertIn({"role": "user", "content": "Hi"},
                      [{"role": h["role"], "content": h["content"]} for h in run.history])

    def test_genuine_hi_gets_the_menu(self):
        run, sent, _ = self.run_hi(False)
        self.assertIn("<MENU>", sent + run.sent)


if __name__ == "__main__":
    unittest.main()
