"""Owner rulings 2026-09-30, from the last-10 review of 2026-09-29.

  1. "ರೇಟ್ ಕಡಿಮೆ madabeku" got the same price again  -> sales will call + 💰🔥 alert
  2. "which place?" asked five times (...4996)         -> ignored twice, move on
  3. "ನನಗೆ ಬೇಕಾ ಆಗಿದಿ" in the place slot (...3476)      -> not a place, ask where
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

FORM = ("Hello! I filled out your form and would like to know more about your business.\n\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {loc}\n"
        "Full name: Test Person\nPhone number: +910000000000\n"
        "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?: A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ")
K = {"capacity_kva": 63, "name": "Test Person"}
D = (b.AWAITING_DELIVERY,)


class AskingForALowerPrice(unittest.TestCase):
    def test_the_real_message(self):
        f = b.parse_followup("ರೇಟ್ ಕಡಿಮೆ madabeku", D, known=K)
        self.assertTrue(f["asked_discount"])
        reply = b.compose_followup_reply(f, K)
        self.assertIn("ದರದ ಬಗ್ಗೆ ನಮ್ಮ sales ತಂಡ ನಿಮಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ", reply)
        self.assertNotIn("₹", reply)                         # not the same price again
        alert = b.compose_followup_alert("910000000000", f, "ರೇಟ್ ಕಡಿಮೆ madabeku", K)
        self.assertTrue(alert.startswith("💰🔥 *PRICE NEGOTIATION*"))

    def test_other_ways_of_asking(self):
        for t in ("discount ide?", "any discount", "best price", "final price sir",
                  "price kammi madi", "rate less madi", "ಡಿಸ್ಕೌಂಟ್ ಕೊಡಿ", "negotiable?"):
            self.assertTrue(b.asked_discount(t), t)

    def test_not_a_discount(self):
        for t in ("less than 1 month", "kadime", "rate eshtu", "price", "Sira",
                  "ಕಡಿಮೆ ಸಮಯದಲ್ಲಿ ಬೇಕು", "reduce", "unless"):
            self.assertFalse(b.asked_discount(t), t)

    def test_a_plain_price_question_still_gets_the_price(self):
        f = b.parse_followup("rate eshtu", D, known=K)
        self.assertIn("₹2,00,000 + GST", b.compose_followup_reply(f, K))
        self.assertNotIn("PRICE NEGOTIATION", b.compose_followup_alert("9", f, "rate eshtu", K))

    def test_no_discount_is_ever_offered(self):
        f = b.parse_followup("best price please", D, known=K)
        reply = b.compose_followup_reply(f, K)
        for w in ("discount", "ರಿಯಾಯಿತಿ", "%", "₹"):
            self.assertNotIn(w, reply)


def history_of(turns):
    """Form, then each customer message, with the flow marker the live bot writes."""
    from test_interpretation_shadow import run_conversation
    return run_conversation(turns)


class IgnoredTwiceMoveOn(unittest.TestCase):
    def test_the_real_conversation(self):
        run = history_of([FORM.format(loc="land"), "ರೇಟ್ ಹೇಳಿ", "2 units",
                          "ರೇಟ್ ಕಡಿಮೆ madabeku", "No"])
        where = [s for s in run.sent if "ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು" in s]
        self.assertLessEqual(len(where), 3)                  # was 5
        self.assertIn(b.question_for(b.AWAITING_PURPOSE), run.sent[-1])

    def test_a_customer_answering_other_questions_is_not_ignoring(self):
        """The "ಗುಜರಾತ್" replay: size, units, purpose, then the place."""
        run = history_of([FORM.format(loc=""), "25 kva", "1 beku", "ಕೃಷಿ", "ಗುಜರಾತ್"])
        self.assertEqual(b.established_from_history(run.history)["delivery_location"], "ಗುಜರಾತ್")

    def test_one_ignored_ask_is_asked_again(self):
        run = history_of([FORM.format(loc=""), "ok"])
        self.assertIn("ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು", run.sent[-1])

    def test_rule(self):
        m = {"role": "assistant", "content": b.flow_marker(D)}
        h = [m, {"role": "user", "content": "hmm"}, m, {"role": "user", "content": "hmm"}]
        self.assertEqual(b.established_from_history(h)["ignored_asks"], {b.AWAITING_DELIVERY: 2})
        self.assertNotIn(b.AWAITING_DELIVERY, b.outstanding({}, b.established_from_history(h)))
        one = b.established_from_history(h[:2])
        self.assertIn(b.AWAITING_DELIVERY, b.outstanding({}, one))
        # one ignored before + this reply ignored too = two: move on now
        self.assertNotIn(b.AWAITING_DELIVERY,
                         b.outstanding(b.parse_followup("hmm", D, known=one), one))
        # ...but a reply with news is not ignoring
        self.assertIn(b.AWAITING_DELIVERY,
                      b.outstanding(b.parse_followup("2 units", D, known=one), one))


class PurposeIgnoredTwiceMoveOn(unittest.TestCase):
    """Owner, 2026-10-01: the same limit for the purpose question."""

    def test_rule(self):
        m = {"role": "assistant", "content": b.flow_marker((b.AWAITING_PURPOSE,))}
        base = {"role": "user", "content": FORM.format(loc="Sira")}
        yes = [{"role": "assistant", "content": b.flow_marker(D)},
               {"role": "user", "content": "yes"}]
        h1 = [base] + yes + [m, {"role": "user", "content": "hmm"}]
        known = b.established_from_history(h1)
        self.assertIn(b.AWAITING_PURPOSE, b.outstanding({}, known))
        self.assertNotIn(b.AWAITING_PURPOSE,
                         b.outstanding(b.parse_followup("hmm", (b.AWAITING_PURPOSE,), known=known), known))
        self.assertIn(b.AWAITING_PURPOSE,
                      b.outstanding(b.parse_followup("2 units", (b.AWAITING_PURPOSE,), known=known), known))

    def test_the_ravi_replay_ends_with_the_call_question(self):
        run = history_of([FORM.format(loc="land"), "ರೇಟ್ ಹೇಳಿ", "2 units",
                          "ರೇಟ್ ಕಡಿಮೆ madabeku", "No", "No"])
        self.assertIn("1️⃣ ಈಗಲೇ", run.sent[-1])
        purpose = [s for s in run.sent if b.question_for(b.AWAITING_PURPOSE) in s]
        self.assertLessEqual(len(purpose), 2)

    def test_delivery_ignores_do_not_count_against_purpose(self):
        m = {"role": "assistant", "content": b.flow_marker(D)}
        h = [m, {"role": "user", "content": "hmm"}, m, {"role": "user", "content": "hmm"}]
        known = b.established_from_history(h)
        self.assertIn(b.AWAITING_PURPOSE, b.outstanding({}, known))


class AQuotationStillNeedsThePlace(unittest.TestCase):
    def test_asked_even_after_two_ignored(self):
        m = {"role": "assistant", "content": b.flow_marker(D)}
        h = [m, {"role": "user", "content": "hmm"}, m, {"role": "user", "content": "hmm"}]
        known = b.established_from_history(h)
        f = b.parse_followup("quotation beku", D, known=known)
        self.assertIn(b.AWAITING_DELIVERY, b.outstanding(f, known))


class INeedItIsNotAPlace(unittest.TestCase):
    def test_the_real_form(self):
        p = b.parse(FORM.format(loc="ನನಗೆ ಬೇಕಾ ಆಗಿದಿ"))
        self.assertIsNone(p["location"])
        self.assertIn("ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು", b.compose_reply(p))

    def test_other_need_answers(self):
        for loc in ("ಬೇಕು", "ಬೇಕಾಗಿದೆ", "need", "Required", "i need 25 kva", "ನಮಗೆ ಬೇಕಾಗಿದೆ",
                    "nanage beku"):
            self.assertIsNone(b.parse(FORM.format(loc=loc))["location"], loc)

    def test_real_places_still_read(self):
        for loc in ("Sira", "Belur", "Bekal", "Mudigere Ajjampura", "TQ Sira Dist Tumkur"):
            self.assertEqual(b.parse(FORM.format(loc=loc))["location"], loc, loc)


if __name__ == "__main__":
    unittest.main()
