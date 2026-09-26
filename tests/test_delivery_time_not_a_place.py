"""A delivery-TIME question is not a delivery PLACE (live defect, audit 2026-09-27).

"delivery yavaga" / "Ayitu delivery yavaga kodtira", sent while the bot was
waiting for the delivery place, were answered as a time question AND stored
as the delivery address — permanently, by the never-erase rule, and onward
into owner alerts. The live parser (bairavi.parse_followup, called by
api/webhook.py) now skips the bare-answer reader for a delivery-time question.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

D = (b.AWAITING_DELIVERY,)
KNOWN = {"location": "Sira", "capacity_kva": 63}
TIME_QUESTIONS = ("delivery yavaga", "Ayitu delivery yavaga kodtira",
                  "ಡೆಲಿವರಿ ಯಾವಾಗ", "when will you deliver", "delivery estu dina alli")


class ATimeQuestionIsNotAPlace(unittest.TestCase):
    def test_the_exact_audit_examples(self):
        for t in ("delivery yavaga", "Ayitu delivery yavaga kodtira"):
            f = b.parse_followup(t, D, known=KNOWN)
            self.assertEqual(f["customer_question"], b.QUESTION_DELIVERY_TIME, t)
            self.assertIsNone(f["delivery_location"], t)

    def test_kannada_and_english_variants(self):
        for t in TIME_QUESTIONS:
            f = b.parse_followup(t, D, known=KNOWN)
            self.assertEqual(f["customer_question"], b.QUESTION_DELIVERY_TIME, t)
            self.assertIsNone(f["delivery_location"], t)

    def test_also_when_not_awaiting(self):
        for t in TIME_QUESTIONS:
            self.assertIsNone(b.parse_followup(t, (), known=KNOWN)["delivery_location"], t)

    def test_the_question_is_still_answered(self):
        for t in TIME_QUESTIONS:
            f = b.parse_followup(t, D, known=KNOWN)
            reply = b.compose_followup_reply(f, KNOWN)
            self.assertIn(b._DELIVERY_TIME_KN, reply, t)


class LegitimatePlacesStillWork(unittest.TestCase):
    """Existing repository examples, unchanged."""

    def test_bare_answers_to_where(self):
        for t in ("Hirekerur", "Sira taluk", "Mysuru", "Sulekere village",
                  "Hiladahalli. Ranibennur. Agriculture purpus."):
            self.assertIsNotNone(b.parse_followup(t, D, known=KNOWN)["delivery_location"], t)

    def test_an_address_that_names_its_taluk(self):
        t = "ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು,ಚಿತ್ರದುರ್ಗ ಜಿಲ್ಲೆ"
        self.assertIsNotNone(b.parse_followup(t, (), known=KNOWN)["delivery_location"])

    def test_explicit_deliver_to_is_unchanged(self):
        self.assertEqual(b.parse_followup("deliver to Hubli", (), known={})["delivery_location"],
                         "Hubli")


class AnEstablishedPlaceIsNeverErased(unittest.TestCase):
    def test_merge_keeps_the_place(self):
        known = {**KNOWN, "delivery_location": "Hirekerur"}
        for t in TIME_QUESTIONS:
            f = b.parse_followup(t, D, known=known)
            self.assertEqual(b.merged_state(known, f)["delivery_location"], "Hirekerur", t)

    def test_across_the_conversation_history(self):
        """The same replay the live webhook uses (established_from_history)."""
        history = [
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_DELIVERY,))},
            {"role": "user", "content": "Hirekerur"},
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_DELIVERY,))},
            {"role": "user", "content": "Ayitu delivery yavaga kodtira"},
        ]
        self.assertEqual(b.established_from_history(history)["delivery_location"], "Hirekerur")

    def test_a_time_question_alone_establishes_no_place(self):
        history = [
            {"role": "assistant", "content": b.flow_marker((b.AWAITING_DELIVERY,))},
            {"role": "user", "content": "delivery yavaga"},
        ]
        self.assertIsNone(b.established_from_history(history)["delivery_location"])


class ThroughTheLiveWebhook(unittest.TestCase):
    """The real run_client_pipeline, every side effect captured, no network."""

    def test_place_then_time_question(self):
        from test_interpretation_shadow import FORM, run_conversation
        run = run_conversation([FORM, "Hirekerur", "Ayitu delivery yavaga kodtira"])
        state = b.established_from_history(run.history)
        self.assertEqual(state["delivery_location"], "Hirekerur")
        self.assertIn(b._DELIVERY_TIME_KN, run.sent[-1])
        self.assertTrue(all("Ayitu delivery yavaga" not in a.split("Their words:")[0]
                            for a in run.owner))

    def test_time_question_while_asked_where(self):
        from test_interpretation_shadow import FORM, run_conversation
        run = run_conversation([FORM, "delivery yavaga"])
        state = b.established_from_history(run.history)
        self.assertIsNone(state["delivery_location"])
        self.assertIn(b._DELIVERY_TIME_KN, run.sent[-1])


class TimePhrasesAsPlaces(unittest.TestCase):
    """DEFECT 2 — NOT FIXED: needs the owner's decision.

    No existing table defines "next week" or "month end" as time
    (_TIMING_URGENCY, the whole-word _NOT_A_PLACE_EXACT list and
    _REPLY_LEADTIME_RE, which needs a number, all miss them), so rejecting
    them means adding new vocabulary. Marked expectedFailure: this documents
    the wanted behaviour without inventing the rule. When the owner approves a
    vocabulary, remove the marker.
    """

    @unittest.expectedFailure
    def test_next_week_is_not_a_place(self):
        self.assertIsNone(b.parse_followup("next week", D, known=KNOWN)["delivery_location"])

    @unittest.expectedFailure
    def test_month_end_is_not_a_place(self):
        self.assertIsNone(b.parse_followup("month end", D, known=KNOWN)["delivery_location"])

    def test_already_covered_time_words_stay_rejected(self):
        for t in ("tomorrow", "later", "soon", "today", "ನಾಳೆ", "ತಕ್ಷಣ", "urgent"):
            self.assertIsNone(b.parse_followup(t, D, known=KNOWN)["delivery_location"], t)


if __name__ == "__main__":
    unittest.main()
