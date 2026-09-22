"""The model may answer, and every word it returns is checked first.

THE OWNER, 2026-09-22: "adru check maadidaga sariyagi uttara kodtilla munche
asthra ge clear answers bartittu" -- it still does not answer properly; Asthra
used to give clear answers. Asked twice, so the model comes into this flow.

WHAT MADE THAT UNSAFE BEFORE was not the model's fluency. It was that nothing
checked what came back. The model answered fifteen of sixteen transformer
buyers with Asthra's digital-marketing menu, and the rule at the top of
bairavi.py lists what has no evidence behind it: price, lead time, BEE
rating, certifications, losses, impedance, dimensions, conductor sizes, any
GTP value.

So this adds the missing half. The model is asked ONLY where the
deterministic composer has nothing, and a reply that states any of those
things is DISCARDED WHOLE -- not edited, because a sentence with the claim
removed is a sentence whose meaning nobody checked. The composed reply goes
out instead, so a refusal is never a worse conversation than before.

Offline: the provider is stubbed. No network.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402

ASKED = (b.AWAITING_DELIVERY,)
KNOWN = {"name": "Manju", "capacity_kva": 100, "location": "kushtagi"}


def parse(text):
    return b.parse_followup(text, awaiting=ASKED)


class TheGuardRefusesUnevidencedClaims(unittest.TestCase):

    def test_a_price_is_refused(self):
        for text in ("25 kVA ಗೆ ₹68,244 ಆಗುತ್ತದೆ", "Price is Rs 45000",
                     "45000 rupees", "Rs. 45000", "INR 50000", "about 2 lakh",
                     "ಸುಮಾರು 50000 ರೂ"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text), "a price")

    def test_a_delivery_time_is_refused(self):
        for text in ("delivery in 15 days", "ready in 3 weeks",
                     "3 ವಾರದಲ್ಲಿ ಡೆಲಿವರಿ", "2 ತಿಂಗಳಲ್ಲಿ ಸಿಗುತ್ತದೆ",
                     "takes 45 days"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a delivery time")

    def test_a_certification_is_refused(self):
        for text in ("we are ISO 9001 certified", "BIS approved",
                     "BEE 5 star rated", "IS 1180 compliant", "CE mark"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a certification")

    def test_a_warranty_is_refused(self):
        for text in ("2 year warranty", "we guarantee performance",
                     "ನಮಗೆ ಗ್ಯಾರಂಟಿ ಇದೆ", "ವಾರಂಟಿ ಇದೆ"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text), "a warranty")

    def test_a_specification_is_refused(self):
        for text in ("impedance is 4.5%", "no-load loss is 200W",
                     "load loss 1200W", "as per the GTP"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a specification")

    def test_a_commercial_term_is_refused(self):
        for text in ("we can give a discount", "ರಿಯಾಯಿತಿ ಕೊಡುತ್ತೇವೆ"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a commercial term")

    def test_a_rating_we_do_not_offer_is_refused(self):
        """The catalogue is the authority, so a fluent "we also make 400 kVA"
        cannot get out."""
        for text in ("we make 400 kVA also", "630 kva available",
                     "we supply 1000 kVA units"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a rating we do not offer")

    def test_an_empty_reply_is_refused(self):
        for text in ("", "   ", None):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text), "empty")


class TheGuardDoesNotRefuseOrdinaryAnswers(unittest.TestCase):
    """A guard that blocks real answers is a guard that gets switched off."""

    def test_an_ordinary_reply_passes(self):
        for text in ("ನಮಸ್ಕಾರ 🙏 ನಾವು Kadaba ನಲ್ಲಿ transformer ತಯಾರಿಸುತ್ತೇವೆ.",
                     "This is our business, we serve farmers.",
                     "ನಿಮ್ಮ ಸ್ಥಳಕ್ಕೆ ಸಾಧ್ಯವೇ ಎಂದು engineer ತಿಳಿಸುತ್ತಾರೆ.",
                     "Call us on +91 88844 48141",
                     "ಹೌದು 🙏 ನಿಮ್ಮ ಹೆಸರು Manju."):
            with self.subTest(text=text):
                self.assertIsNone(b.reply_violates_evidence(text), text)

    def test_the_catalogue_may_be_stated(self):
        for kva in b.CATALOGUE_KVA:
            with self.subTest(kva=kva):
                self.assertIsNone(
                    b.reply_violates_evidence(f"ಹೌದು, {kva} kVA ನಮ್ಮಲ್ಲಿ ಇದೆ."))

    def test_a_planned_rating_may_be_mentioned(self):
        for kva in b.PLANNED_KVA:
            with self.subTest(kva=kva):
                self.assertIsNone(
                    b.reply_violates_evidence(f"{kva} kVA ಯೋಜನೆಯಲ್ಲಿದೆ."))

    def test_the_word_for_price_alone_is_allowed(self):
        """"ಬೆಲೆ engineer ತಿಳಿಸುತ್ತಾರೆ" says no figure and is the answer we
        want. A NUMBER beside it is the claim."""
        for text in ("ಬೆಲೆ ನಮ್ಮ engineer ತಿಳಿಸುತ್ತಾರೆ.",
                     "ದರ engineer ಕೊಡುತ್ತಾರೆ.",
                     "The price will be quoted by our engineer."):
            with self.subTest(text=text):
                self.assertIsNone(b.reply_violates_evidence(text), text)

    def test_an_ordinary_word_does_not_trip_a_banned_term(self):
        """ASCII terms are matched on WORD BOUNDARIES, and this is the case
        that proves it matters.

        A first version of this test used "business" for "bis" -- but
        "business" does not contain "bis", so the assertion held either way
        and a mutation widening the match to a substring escaped. "been"
        does contain "bee", and a bot that cannot say "we have been making
        transformers" is a bot with a broken guard.
        """
        for text in ("We have been making transformers for years.",
                     "There has been no problem so far.",
                     "We would like to know more about your business."):
            with self.subTest(text=text):
                self.assertIsNone(b.reply_violates_evidence(text), text)

    def test_the_banned_term_still_matches_as_a_whole_word(self):
        self.assertEqual(b.reply_violates_evidence("BEE 5 star rated"),
                         "a certification")

    def test_a_phone_number_is_not_a_price(self):
        self.assertIsNone(b.reply_violates_evidence("ಕರೆ ಮಾಡಿ 8884448141"))


class TheModelIsAskedOnlyWhereThereIsNothingToSay(unittest.TestCase):

    def test_a_price_question_never_reaches_the_model(self):
        """A fluent paraphrase of "we cannot quote a figure" is a chance to
        quote one."""
        for text in ("ಬೆಲೆ ಎಷ್ಟು?", "rate?", "Amount?", "quotation beku"):
            with self.subTest(text=text):
                self.assertFalse(b.should_ask_model(parse(text), KNOWN), text)

    def test_an_approval_question_never_reaches_the_model(self):
        self.assertFalse(b.should_ask_model(parse("mescom approval?"), KNOWN))

    def test_a_qualification_answer_never_reaches_the_model(self):
        """The reply already has real content and the flow is progressing."""
        for text in ("agriculture", "kushtagi", "2 units", "25 kVA", "ಸೇಮ್"):
            with self.subTest(text=text):
                self.assertFalse(b.should_ask_model(parse(text), KNOWN), text)

    def test_a_real_question_does_reach_the_model(self):
        for text in ("ನಿಮ್ಮ ಕಂಪನಿ ಎಷ್ಟು ವರ್ಷದಿಂದ ಇದೆ?", "who are you?",
                     "what about warranty?", "ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?",
                     "transformer nalli en difference?"):
            with self.subTest(text=text):
                self.assertTrue(b.should_ask_model(parse(text), KNOWN), text)


class HowManyIsNotHowMuch(unittest.TestCase):
    """A pre-existing over-broad term, found through this work.

    _PRICE_ASK carried a bare "ಎಷ್ಟು", which is also the word for HOW MANY --
    and this module's own question is "ಎಷ್ಟು *units* ಬೇಕು?". So every counting
    question read as a request for a price: it answered a question nobody
    asked and blocked the answer to the real one.
    """

    def test_a_counting_question_is_not_a_price_question(self):
        for text in ("ನಿಮ್ಮ ಕಂಪನಿ ಎಷ್ಟು ವರ್ಷದಿಂದ ಇದೆ?", "ಎಷ್ಟು units ಬೇಕು",
                     "ಎಷ್ಟು ದಿನ", "eshtu units"):
            with self.subTest(text=text):
                self.assertFalse(parse(text)["asked_price"], text)

    def test_a_real_price_question_still_is_one(self):
        for text in ("ಬೆಲೆ ಎಷ್ಟು?", "ದರ ಎಷ್ಟು", "rate eshtu?", "price?",
                     "ಎಷ್ಟಾಗುತ್ತೆ?", "Amount?", "how much",
                     "ಎಷ್ಟು ರೂ ಆಗುತ್ತದೆ", "cost?"):
            with self.subTest(text=text):
                self.assertTrue(parse(text)["asked_price"], text)


class TheComposedReplyIsTheFallback(unittest.TestCase):

    def _run(self, text, model_says):
        followup = parse(text)
        with mock.patch.object(w, "_generate_ai_reply",
                               return_value=model_says):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = w.bairavi_model_reply("919000000000", text, [],
                                            followup, KNOWN)
            return out, buf.getvalue()

    def test_a_passing_reply_is_used(self):
        out, _ = self._run("who are you?",
                           "We are Bairavi Trans Solutions, Kadaba.")
        self.assertIn("Bairavi Trans Solutions", out)

    def test_the_outstanding_question_is_still_asked(self):
        """The model answers what was asked; the flow still gets what it
        needs, so one off-topic turn does not stall the qualification."""
        out, _ = self._run("who are you?", "We are Bairavi, Kadaba.")
        self.assertIn(b.question_for(b.AWAITING_DELIVERY, KNOWN), out)

    def test_a_refused_reply_yields_nothing(self):
        out, _ = self._run("what about warranty?", "We give a 2 year warranty.")
        self.assertEqual(out, "")

    def test_the_refusal_is_logged_with_a_reason(self):
        _, log = self._run("what about warranty?", "We give a 2 year warranty.")
        self.assertIn("BAIRAVI_MODEL_REFUSED", log)
        self.assertIn("a warranty", log)

    def test_the_refusal_log_never_carries_the_phone_or_the_text(self):
        _, log = self._run("what about warranty?",
                           "We give a 2 year warranty on all units.")
        self.assertNotIn("919000000000", log)
        self.assertIn("0000", log)
        self.assertNotIn("2 year warranty", log)

    def test_a_provider_failure_yields_nothing(self):
        out, log = self._run("who are you?", "")
        self.assertEqual(out, "")
        self.assertIn("BAIRAVI_MODEL_NO_REPLY", log)

    def test_the_model_is_not_called_when_the_gate_is_closed(self):
        followup = parse("agriculture")
        with mock.patch.object(w, "_generate_ai_reply") as ai:
            out = w.bairavi_model_reply("919000000000", "agriculture", [],
                                        followup, KNOWN)
        self.assertEqual(out, "")
        self.assertEqual(ai.call_count, 0)


class TheBriefCarriesOnlyEstablishedFacts(unittest.TestCase):

    def test_it_is_built_from_the_same_tables(self):
        brief = b.model_brief_kn()
        for kva in b.CATALOGUE_KVA:
            with self.subTest(kva=kva):
                self.assertIn(f"{kva} kVA", brief)
        self.assertIn("MESCOM", brief)
        self.assertIn("Kadaba", brief)

    def test_it_forbids_every_class_the_guard_refuses(self):
        brief = b.model_brief_kn()
        for rule in ("ಬೆಲೆ", "ISO", "BIS", "warranty", "GTP"):
            with self.subTest(rule=rule):
                self.assertIn(rule, brief)

    def test_it_states_no_price_and_no_deadline(self):
        """The brief must not hand the model a figure to repeat.

        Asserted against the specific claim classes, NOT by running the brief
        through reply_violates_evidence -- the brief NAMES ISO, BIS, BEE and
        warranty precisely in order to forbid them, so its own guard would
        always refuse it. A first version tried that and was measuring the
        wrong thing.
        """
        brief = b.model_brief_kn()
        self.assertNotIn("₹", brief)
        self.assertNotIn("68,244", brief)
        self.assertIsNone(b._REPLY_MONEY_RE.search(brief))
        self.assertIsNone(b._REPLY_LEADTIME_RE.search(brief))

    def test_it_forbids_talking_about_asthra(self):
        """The original failure: fifteen of sixteen transformer buyers were
        sent Asthra's digital-marketing menu."""
        self.assertIn("Asthra", b.model_brief_kn())


class TheGuardRunsBeforeAnythingIsSent(unittest.TestCase):

    def test_compose_model_reply_checks_first(self):
        reply, reason = b.compose_model_reply("It costs ₹50000", parse("hi?"),
                                              KNOWN)
        self.assertIsNone(reply)
        self.assertEqual(reason, "a price")

    def test_a_refused_reply_is_discarded_whole_not_edited(self):
        """A sentence with the claim removed is a sentence whose meaning
        nobody checked."""
        reply, _ = b.compose_model_reply(
            "Our 25 kVA is good and costs ₹50000", parse("hi?"), KNOWN)
        self.assertIsNone(reply)

    def test_the_webhook_path_cannot_skip_the_guard(self):
        import inspect
        src = inspect.getsource(w.bairavi_model_reply)
        self.assertIn("compose_model_reply", src)
        self.assertNotIn("send_text", src)


if __name__ == "__main__":
    unittest.main()
