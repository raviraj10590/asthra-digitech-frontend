"""The first real lead after efeee4a went live, 2026-09-23 16:58.

The form gave 25 kVA and "bammanjogi". The customer answered "Agriculture"
(read correctly), then "Ok" to "ಡೆಲಿವರಿ ಇದೇ ಸ್ಥಳಕ್ಕೆ ಆ — bammanjogi?". That "Ok"
was not understood: the model re-introduced the company in English and asked
the identical question again. The customer said "Ok" once more, eighteen
seconds later, and got no reply at all — the duplicate-webhook check read a
person repeating a word as a Meta retry.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
KNOWN = {"location": "bammanjogi", "capacity_kva": 25, "application": "AGRICULTURE"}


class OkMeansYesToTheSamePlace(unittest.TestCase):

    def test_the_production_answer(self):
        f = b.parse_followup("Ok", awaiting=DELIVERY, known=KNOWN)
        self.assertTrue(f["delivery_same"])
        self.assertIsNone(f["delivery_location"])

    def test_every_affirmation(self):
        for text in ("ok", "Okay", "yes", "Haan", "ಸರಿ", "ಆಯ್ತು", "👍", "Ok."):
            with self.subTest(text=text):
                self.assertTrue(b.parse_followup(text, awaiting=DELIVERY,
                                                 known=KNOWN)["delivery_same"])

    def test_delivery_is_then_settled(self):
        """The next reply moves on instead of asking the same thing."""
        f = b.parse_followup("Ok", awaiting=DELIVERY, known=KNOWN)
        self.assertNotIn(b.AWAITING_DELIVERY, b.outstanding(f, KNOWN))

    def test_not_when_there_is_no_place_to_be_the_same_as(self):
        """Without a project location the question was "which place?", and
        "Ok" answers nothing."""
        self.assertFalse(b.parse_followup("Ok", awaiting=DELIVERY, known={})
                         ["delivery_same"])
        self.assertFalse(b.parse_followup("Ok", awaiting=DELIVERY)["delivery_same"])

    def test_not_when_delivery_was_not_asked(self):
        self.assertFalse(b.parse_followup("Ok", awaiting=(b.AWAITING_PURPOSE,),
                                          known=KNOWN)["delivery_same"])

    def test_only_as_the_whole_answer(self):
        self.assertFalse(b.parse_followup("ok but deliver to Mysuru later?",
                                          awaiting=DELIVERY, known=KNOWN)
                         ["delivery_same"])

    def test_the_replay_agrees_with_the_live_turn(self):
        """established_from_history passes its accumulated state, so the
        transcript reads "Ok" the same way the live turn did."""
        form = ("Hello! I filled out your form.\n\n"
                "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
                "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: bammanjogi\n"
                "Full name: Test Person\nPhone number: +910000000000")
        history = [{"role": "user", "content": form},
                   {"role": "assistant", "content": b.flow_marker(DELIVERY)},
                   {"role": "user", "content": "Ok"}]
        self.assertTrue(b.established_from_history(history)["delivery_same"])

    def test_the_webhook_passes_known(self):
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("known=known)", src)
        self.assertLess(src.index("known = bairavi.established_from_history"),
                        src.index("followup = bairavi.parse_followup("))


class ABareAcknowledgementDoesNotGoToTheModel(unittest.TestCase):
    """The model answered "Ok" with a paragraph re-introducing the company."""

    def test_acknowledgements_and_greetings(self):
        for text in ("Ok", "ok sir", "Thanks", "ಸರಿ", "Hi", "Namaste", "👍"):
            with self.subTest(text=text):
                f = b.parse_followup(text)
                self.assertTrue(f["is_ack"])
                self.assertFalse(b.should_ask_model(f, {}))

    def test_a_real_question_still_does(self):
        f = b.parse_followup("ನಿಮ್ಮ ಕಂಪನಿ ಎಷ್ಟು ವರ್ಷದಿಂದ ಇದೆ?")
        self.assertFalse(f["is_ack"])
        self.assertTrue(b.should_ask_model(f, {}))


class APersonRepeatingAWordIsNotARetry(unittest.TestCase):

    def _ctx(self, text):
        return {"last_user": {"content": text,
                              "created_at": datetime.now(timezone.utc).isoformat()}}

    def test_the_production_repeat(self):
        self.assertFalse(w.is_duplicate_webhook(self._ctx("Ok"), "Ok"))

    def test_the_threshold(self):
        at = "x" * w._DEDUPE_MIN_CHARS
        over = "x" * (w._DEDUPE_MIN_CHARS + 1)
        self.assertFalse(w.is_duplicate_webhook(self._ctx(at), at))
        self.assertTrue(w.is_duplicate_webhook(self._ctx(over), over))

    def test_a_long_resend_is_still_suppressed(self):
        long = "Hello! I filled out your form and would like to know more."
        self.assertTrue(w.is_duplicate_webhook(self._ctx(long), long))


if __name__ == "__main__":
    unittest.main()
