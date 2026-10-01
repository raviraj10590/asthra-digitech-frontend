"""A simple question gets a real answer -- from evidence, not from a model.

THE OWNER'S COMPLAINT, 2026-09-22, after testing the bot as a customer:
"namma brain saakstu buddivantike irodu yaake simple question gu answer
madoke oddadtide?" -- the Brain has plenty of intelligence, so why does it
struggle with a simple question? They had asked "ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?" and got
"✅ ಧನ್ಯವಾದ — ನಿಮ್ಮ ಸಂದೇಶ ಸಿಕ್ಕಿದೆ" and the form questions again.

THE CAUSE is in api/webhook.py: once in_transformer_flow() is true, every
message goes to this module's deterministic composer and generate_reply is
never reached.

WHY THE FIX IS NOT "LET THE MODEL ANSWER". That gate exists because the
model answered fifteen of sixteen transformer buyers with Asthra's
digital-marketing menu, and because there is no authoritative Bairavi price
or specification source. An intelligent answer with no evidence behind it is
the ₹68,244 failure this module was built to prevent. So the flow was given
real facts instead: already-approved customer-facing copy, owner-stated
evidence, and the customer's own name, which the ad form always carried and
which was being extracted and then dropped.

A question with no evidence behind it is answered honestly AND flagged to
the owner, which is strictly better than the receipt production sent.
"""
import unittest
import bairavi as b
from _price_policy import assert_only_owner_prices  # noqa: E402

ASKED = (b.AWAITING_DELIVERY,)
KNOWN = {"name": "Manju", "capacity_kva": 100, "location": "kushtagi"}


def parse(text):
    return b.parse_followup(text, awaiting=ASKED)


class TheQuestionIsClassified(unittest.TestCase):

    def test_the_owners_own_question(self):
        self.assertEqual(b.customer_question("ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?"),
                         b.QUESTION_NAME)

    def test_who_and_where_we_are(self):
        for text in ("who are you?", "your company details",
                     "where are you located", "ನೀವು ಯಾರು?", "ನಿಮ್ಮ ಕಂಪನಿ?"):
            with self.subTest(text=text):
                self.assertEqual(b.customer_question(text), b.QUESTION_WHO)

    def test_what_we_make(self):
        for text in ("what do you make?", "which models do you have",
                     "what kva do you have?", "your products?"):
            with self.subTest(text=text):
                self.assertEqual(b.customer_question(text), b.QUESTION_RANGE)

    def test_where_we_deliver(self):
        for text in ("do you deliver to Bengaluru?", "can you deliver",
                     "do you supply outside karnataka?", "ಡೆಲಿವರಿ ಇದೆಯಾ?"):
            with self.subTest(text=text):
                self.assertEqual(b.customer_question(text),
                                 b.QUESTION_DELIVERY_AREA)

    def test_a_question_with_no_evidence_is_marked_unanswered(self):
        """A different outcome from None, and the one the owner must see."""
        for text in ("what about warranty?", "how many years guarantee?"):
            with self.subTest(text=text):
                self.assertEqual(b.customer_question(text),
                                 b.QUESTION_UNANSWERED)

    def test_a_qualification_answer_is_not_a_question(self):
        """None, so every ordinary reply is byte-identical to before."""
        for text in ("kushtagi", "agriculture", "2 units", "ಬೆಂಗಳೂರು",
                     "25 kVA", "ಸೇಮ್", ""):
            with self.subTest(text=text):
                self.assertIsNone(b.customer_question(text), text)

    def test_detection_under_reports_rather_than_guessing(self):
        """A question mark is the only general signal, and Kannada questions
        often carry none. A missed question falls through to the reply it
        would have received anyway -- no worse than before."""
        self.assertIsNone(b.customer_question("ಎಷ್ಟು ದಿನ ಆಗುತ್ತದೆ"))


class EveryAnswerComesFromEvidence(unittest.TestCase):

    def test_the_name_comes_from_what_we_already_hold(self):
        self.assertIn("Manju", b.answer_question_kn(b.QUESTION_NAME, KNOWN))

    def test_an_unknown_name_is_admitted_not_invented(self):
        answer = b.answer_question_kn(b.QUESTION_NAME, {})
        self.assertNotIn("Manju", answer)
        self.assertIn("ಕ್ಷಮಿಸಿ", answer)

    def test_the_range_is_built_from_the_catalogue(self):
        """So the sentence cannot drift from the code that defines the SKUs."""
        answer = b.answer_question_kn(b.QUESTION_RANGE)
        for kva in b.CATALOGUE_KVA:
            with self.subTest(kva=kva):
                self.assertIn(f"{kva} kVA", answer)

    def test_a_planned_rating_is_marked_as_planned(self):
        answer = b.answer_question_kn(b.QUESTION_RANGE)
        for kva in b.PLANNED_KVA:
            self.assertIn(f"{kva} kVA", answer)
        self.assertIn("ಯೋಜನೆ", answer)

    def test_a_rating_we_do_not_offer_is_never_listed(self):
        answer = b.answer_question_kn(b.QUESTION_RANGE)
        for kva in (10, 16, 40, 160, 315, 400, 630, 1000):
            with self.subTest(kva=kva):
                self.assertNotIn(f"{kva} kVA", answer)

    def test_who_we_are_repeats_the_copy_already_sent(self):
        answer = b.answer_question_kn(b.QUESTION_WHO)
        self.assertIn("Bairavi Trans Solutions", answer)
        self.assertIn("Kadaba", answer)

    def test_delivery_reach_states_today_and_defers_the_specific_place(self):
        answer = b.answer_question_kn(b.QUESTION_DELIVERY_AREA)
        self.assertIn("MESCOM", answer)
        self.assertIn("engineer", answer)

    def test_the_month_count_is_NOT_quoted_to_the_customer(self):
        """The owner said "two months" on 2026-09-20. True that day, a false
        promise once it is still being sent a year later with nothing in the
        code to notice. The serving area does not decay; the deadline does."""
        answer = b.answer_question_kn(b.QUESTION_DELIVERY_AREA)
        for claim in ("2 month", "two month", "2 ತಿಂಗಳ", "ಎರಡು ತಿಂಗಳ"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, answer)

    def test_no_answer_ever_states_a_forbidden_fact(self):
        """The module's standing rule: no price, lead time, certification,
        loss, impedance or dimension leaves this layer."""
        for tag in (b.QUESTION_NAME, b.QUESTION_WHO, b.QUESTION_RANGE,
                    b.QUESTION_DELIVERY_AREA, b.QUESTION_UNANSWERED):
            answer = b.answer_question_kn(tag, KNOWN)
            for banned in ("₹", "68,244", "68244", "ISO", "BIS", "BEE",
                           "warranty", "guarantee", "impedance", "days",
                           "ವಾರಂಟಿ"):
                with self.subTest(tag=tag, banned=banned):
                    self.assertNotIn(banned, answer)

    def test_no_model_is_consulted(self):
        """The whole point: these answers are code, not generation."""
        import inspect
        src = (inspect.getsource(b.answer_question_kn)
               + inspect.getsource(b.customer_question))
        for provider in ("openai", "gemini", "deepseek", "generate",
                         "requests", "prompt"):
            with self.subTest(provider=provider):
                self.assertNotIn(provider, src.lower())


class TheCustomerGetsTheAnswer(unittest.TestCase):

    def test_the_name_question_is_answered_in_the_reply(self):
        reply = b.compose_followup_reply(parse("ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?"), KNOWN)
        self.assertIn("Manju", reply)

    def test_the_reply_is_no_longer_only_a_receipt(self):
        """The exact production failure."""
        reply = b.compose_followup_reply(parse("who are you?"), KNOWN)
        self.assertIn("Bairavi Trans Solutions", reply)
        self.assertIn("Kadaba", reply)

    def test_the_reply_still_re_asks_what_is_outstanding(self):
        """Answering the question must not abandon the qualification."""
        reply = b.compose_followup_reply(parse("who are you?"), KNOWN)
        self.assertIn("ಡೆಲಿವರಿ", reply)

    def test_an_ordinary_reply_is_unchanged(self):
        """Additive: no question, no new text."""
        reply = b.compose_followup_reply(parse("agriculture"), KNOWN)
        self.assertNotIn("Kadaba", reply)
        self.assertNotIn("ತಲುಪಿಸಿದ್ದೇವೆ", reply)

    def test_a_price_question_is_not_answered_twice(self):
        """"rate eshtu?" carries a question mark, so it is also tagged
        unanswered. The price referral already answers it, and a customer
        asking one thing must not be answered two ways."""
        reply = b.compose_followup_reply(parse("rate eshtu?"), KNOWN)
        self.assertIn("+ GST", reply)
        self.assertEqual(reply.count("+ GST"), 1)
        self.assertNotIn("ತಲುಪಿಸಿದ್ದೇವೆ", reply)

    def test_an_approval_question_is_not_answered_twice(self):
        reply = b.compose_followup_reply(parse("mescom approval?"), KNOWN)
        self.assertIn("MESCOM", reply)
        self.assertNotIn("ತಲುಪಿಸಿದ್ದೇವೆ", reply)

    def test_warranty_is_answered_from_the_owners_terms(self):
        """Owner's ruling 2026-09-24: 1 year warranty, service after."""
        reply = b.compose_followup_reply(parse("what about warranty?"), KNOWN)
        self.assertIn("1 ವರ್ಷ warranty", reply)
        assert_only_owner_prices(self, reply)

    def test_a_truly_unknown_question_still_gets_an_honest_referral(self):
        reply = b.compose_followup_reply(parse("what is the impedance?"), KNOWN)
        self.assertIn("engineer", reply)


class TheOwnerIsToldWhenWeCouldNotAnswer(unittest.TestCase):

    def _alert(self, text):
        return b.compose_followup_alert("910000000000", parse(text), text,
                                        KNOWN)

    def test_an_unanswerable_question_raises_the_flag(self):
        self.assertIn("could not answer", self._alert("what is the impedance?"))

    def test_an_answered_question_does_not(self):
        for text in ("rate eshtu?", "mescom approval?", "who are you?",
                     "ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?"):
            with self.subTest(text=text):
                self.assertNotIn("could not answer", self._alert(text))

    def test_an_ordinary_answer_does_not(self):
        self.assertNotIn("could not answer", self._alert("agriculture"))

    def test_the_predicate_is_shared_by_both_readers(self):
        """They disagreed at first: "rate eshtu?" was answered in the reply
        and simultaneously reported to the owner as unanswered."""
        import inspect
        self.assertIn("unanswered_question",
                      inspect.getsource(b._compose_followup_reply))
        self.assertIn("unanswered_question",
                      inspect.getsource(b.compose_followup_alert))


class TheNameNowSurvivesTheConversation(unittest.TestCase):

    def test_name_is_a_persistent_field(self):
        self.assertIn("name", b._PERSISTENT_FIELDS)

    def test_the_ad_form_name_is_recalled_turns_later(self):
        form = ("Hello! I filled out your form and would like to know more.\n\n"
                "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
                "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: Sorab\n"
                "Full name: Test Person\n"
                "Phone number: +910000000000")
        history = [{"role": "user", "content": form},
                   {"role": "assistant",
                    "content": b.flow_marker((b.AWAITING_DELIVERY,))},
                   {"role": "user", "content": "agriculture"}]
        known = b.established_from_history(history)
        self.assertEqual(known.get("name"), "Test Person")
        self.assertIn("Test Person",
                      b.answer_question_kn(b.QUESTION_NAME, known))

    def test_a_name_is_never_erased_by_a_later_turn(self):
        """The monotonicity invariant applies to it like any other field."""
        state = b.merged_state({"name": "Test Person"},
                               b.parse_followup("agriculture"))
        self.assertEqual(state["name"], "Test Person")


if __name__ == "__main__":
    unittest.main()
