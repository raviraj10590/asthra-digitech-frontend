"""A DISCOM approval question gets an answer.

WHAT PRODUCTION DID. On 2026-09-22 a customer enquiring about a 100 kVA
transformer wrote:

    "Sir, you have GESCOM approvel."

and was answered with "✅ ಧನ್ಯವಾದ — ನಿಮ್ಮ ಸಂದೇಶ ಸಿಕ್ಕಿದೆ" and the same two
form questions again. The question was never answered and the owner was
never told it had been asked.

WHY IT MATTERS. An unapproved transformer cannot be energised on that
utility's network, so this is the question a serious buyer asks -- and this
buyer had already stated a capacity and a location.

THE STATUS IS OWNER-STATED, 2026-09-22: MESCOM approval is done; GESCOM and
BESCOM are expected within three months. Nothing else has a stated status,
and nothing is extrapolated -- a question about any other utility is routed
to a human. That is the same evidence discipline that keeps a price out of
this module: the bot may repeat what the owner has said and no more.
"""
import unittest
import bairavi as b
from _price_policy import assert_only_owner_prices  # noqa: E402


class TheQuestionIsRecognised(unittest.TestCase):

    def test_the_production_message_verbatim(self):
        """Including the customer's spelling of "approvel"."""
        self.assertEqual(b.discom_approval_ask("Sir, you have GESCOM approvel."),
                         ("gescom",))

    def test_the_stem_covers_the_real_spellings(self):
        for text in ("gescom approval", "gescom approved", "gescom approve",
                     "gescom approvel", "GESCOM Approval?"):
            with self.subTest(text=text):
                self.assertEqual(b.discom_approval_ask(text), ("gescom",))

    def test_kannada_phrasing(self):
        self.assertIsNotNone(b.discom_approval_ask("ಅನುಮೋದನೆ ಇದೆಯಾ?"))
        self.assertIsNotNone(b.discom_approval_ask("ಅಪ್ರೂವಲ್ ಇದೆಯಾ"))

    def test_an_approval_question_naming_nobody(self):
        """An empty tuple -- asked, but no utility named. Distinct from None."""
        self.assertEqual(b.discom_approval_ask("do you have approval?"), ())

    def test_several_utilities_in_one_question(self):
        self.assertEqual(b.discom_approval_ask("bescom and gescom approval"),
                         ("bescom", "gescom"))

    def test_an_ordinary_message_is_not_an_approval_question(self):
        """None, so every other reply is left exactly as it was."""
        for text in ("what is the price?", "kushtagi", "2 units", "",
                     "100 kva agriculture", "ಸೇಮ್"):
            with self.subTest(text=text):
                self.assertIsNone(b.discom_approval_ask(text))

    def test_a_utility_name_alone_is_not_an_approval_question(self):
        """"MESCOM area" is not asking about approval."""
        self.assertIsNone(b.discom_approval_ask("mescom area"))

    def test_the_broad_names_do_not_double_count(self):
        """"cesc" is inside "cescom", and "escom" inside all of them."""
        self.assertEqual(b.discom_approval_ask("cescom approval"), ("cescom",))
        self.assertEqual(b.discom_approval_ask("mescom approval"), ("mescom",))


class OnlyWhatTheOwnerSaid(unittest.TestCase):

    def test_mescom_is_stated_as_approved(self):
        answer = b.approval_answer_kn(("mescom",))
        self.assertIn("MESCOM", answer)
        self.assertIn("ಆಗಿದೆ", answer)

    def test_gescom_and_bescom_are_stated_as_expected_within_three_months(self):
        for d in ("gescom", "bescom"):
            with self.subTest(d=d):
                answer = b.approval_answer_kn((d,))
                self.assertIn(d.upper(), answer)
                self.assertIn("3 ತಿಂಗಳ", answer)
                # Expected, not done. The distinction is the whole point.
                self.assertNotIn("ಆಗಿದೆ", answer)

    def test_an_unstated_utility_is_routed_to_a_human(self):
        """The evidence rule. No status exists for these, so none is claimed.
        (HESCOM and CESCOM moved out of this list with the owner's
        2026-10-01 ruling; KPTCL is transmission, not a supply company.)"""
        for d in ("kptcl",):
            with self.subTest(d=d):
                answer = b.approval_answer_kn((d,))
                self.assertIn(d.upper(), answer)
                self.assertIn("engineer", answer)
                self.assertNotIn("ಆಗಿದೆ", answer)
                self.assertNotIn("3 ತಿಂಗಳ", answer)

    def test_an_unnamed_question_states_everything_that_has_a_status(self):
        answer = b.approval_answer_kn(())
        self.assertIn("MESCOM", answer)
        self.assertIn("GESCOM", answer)
        self.assertIn("BESCOM", answer)

    def test_no_approval_is_ever_claimed_for_an_unstated_utility(self):
        """Asserted over every recognised name, so adding one to the
        recognition list can never silently grant it an approval."""
        for d in b._DISCOM_NAMES:
            with self.subTest(d=d):
                if b._DISCOM_APPROVAL_STATED.get(d) == "APPROVED":
                    continue
                self.assertNotIn("ಆಗಿದೆ", b.approval_answer_kn((d,)))

    def test_the_status_table_is_the_only_source(self):
        """The reply is generated from the table, so the owner's position is
        stated in exactly one place."""
        # Owner 2026-09-22, then 2026-10-01: "other than mscom whithin three
        # month we get permission for all others".
        self.assertEqual(b._DISCOM_APPROVAL_STATED,
                         {"mescom": "APPROVED",
                          "gescom": "IN_PROGRESS",
                          "bescom": "IN_PROGRESS",
                          "hescom": "IN_PROGRESS",
                          "cesc": "IN_PROGRESS",
                          "cescom": "IN_PROGRESS"})

    def test_the_2026_10_01_ruling(self):
        for d in ("hescom", "cesc", "cescom", "bescom", "gescom"):
            answer = b.approval_answer_kn((d,))
            self.assertIn("3 ತಿಂಗಳೊಳಗೆ", answer, d)
            self.assertNotIn("ಆಗಿದೆ", answer, d)          # pending never reads as done
        self.assertIn("✅ *MESCOM* approval ಆಗಿದೆ.", b.approval_answer_kn(("mescom",)))
        self.assertEqual(b.approval_answer_kn(()).count("CESC"), 1)   # one company, one mention

    def test_no_price_or_certificate_is_ever_quoted(self):
        """An approval answer must not become a place where other unevidenced
        claims leak out."""
        for asked in ((), ("mescom",), ("gescom",), ("hescom",)):
            answer = b.approval_answer_kn(asked)
            with self.subTest(asked=asked):
                self.assertNotIn("₹", answer)
                self.assertNotIn("ISO", answer)
                self.assertNotIn("BIS", answer)


class TheCustomerGetsTheAnswer(unittest.TestCase):

    def setUp(self):
        self.text = "Sir, you have GESCOM approvel."
        self.followup = b.parse_followup(self.text,
                                         awaiting=(b.AWAITING_DELIVERY,))
        self.known = {"capacity_kva": 100, "location": "kushtagi"}

    def test_the_parse_carries_the_question(self):
        self.assertEqual(self.followup["discom_approval_ask"], ("gescom",))

    def test_the_reply_answers_it(self):
        reply = b.compose_followup_reply(self.followup, self.known)
        self.assertIn("GESCOM", reply)
        self.assertIn("3 ತಿಂಗಳ", reply)

    def test_the_reply_is_no_longer_only_a_receipt(self):
        """The exact production failure: acknowledged and re-asked, with the
        question itself left unanswered."""
        reply = b.compose_followup_reply(self.followup, self.known)
        self.assertNotEqual(
            reply.strip().splitlines()[0],
            "✅ ಧನ್ಯವಾದ — ನಿಮ್ಮ ಸಂದೇಶ ಸಿಕ್ಕಿದೆ.\n")
        self.assertIn("DISCOM", reply)

    def test_the_reply_still_re_asks_what_is_outstanding(self):
        """Answering the question must not stop the qualification."""
        reply = b.compose_followup_reply(self.followup, self.known)
        self.assertIn("ಡೆಲಿವರಿ", reply)

    def test_an_ordinary_followup_reply_is_unchanged(self):
        """The feature is additive: no approval question, no new text."""
        plain = b.parse_followup("agriculture", awaiting=(b.AWAITING_DELIVERY,))
        reply = b.compose_followup_reply(plain, self.known)
        self.assertNotIn("DISCOM", reply)


class TheOwnerIsTold(unittest.TestCase):

    def test_the_alert_names_the_utility(self):
        text = "Sir, you have GESCOM approvel."
        f = b.parse_followup(text, awaiting=(b.AWAITING_DELIVERY,))
        alert = b.compose_followup_alert("910000000000", f, text, {})
        self.assertIn("Asked about DISCOM approval: GESCOM", alert)

    def test_an_unnamed_question_still_reaches_the_owner(self):
        text = "do you have approval?"
        f = b.parse_followup(text, awaiting=(b.AWAITING_DELIVERY,))
        alert = b.compose_followup_alert("910000000000", f, text, {})
        self.assertIn("Asked about DISCOM approval: not named", alert)

    def test_the_line_is_absent_when_nothing_was_asked(self):
        """It would otherwise read "no" in almost every conversation."""
        f = b.parse_followup("agriculture", awaiting=(b.AWAITING_DELIVERY,))
        alert = b.compose_followup_alert("910000000000", f, "agriculture", {})
        self.assertNotIn("DISCOM", alert)

    def test_the_alert_still_says_nothing_was_quoted(self):
        text = "mescom approval?"
        f = b.parse_followup(text, awaiting=(b.AWAITING_DELIVERY,))
        alert = b.compose_followup_alert("910000000000", f, text, {})
        self.assertIn("No delivery date, discount or certificate", alert)


if __name__ == "__main__":
    unittest.main()
