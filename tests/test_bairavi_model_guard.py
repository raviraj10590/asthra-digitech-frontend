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
                     "what is the impedance?", "ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?",
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
        out, _ = self._run("how many years is your company running?", "We give a 2 year warranty.")
        self.assertEqual(out, "")

    def test_the_refusal_is_logged_with_a_reason(self):
        _, log = self._run("how many years is your company running?", "We give a 2 year warranty.")
        self.assertIn("BAIRAVI_MODEL_REFUSED", log)
        self.assertIn("a warranty", log)

    def test_the_refusal_log_never_carries_the_phone_or_the_text(self):
        _, log = self._run("how many years is your company running?",
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


# ══════════════════════════════════════════════════════════════════════════
# THE OWNER'S SECOND TEST THREAD, 2026-09-22 23:56 onward  (first real
# traffic on the model path)
# ══════════════════════════════════════════════════════════════════════════

class APhoneNumberIsNotAQuantity(unittest.TestCase):
    """The worst of that thread. The owner sent their own number and the bot
    replied "✅ ದಾಖಲಿಸಿದ್ದೇವೆ: *888 units*" -- the pattern takes at most three
    digits and nothing stopped it biting the front off a ten-digit number.

    Compounding: the model had just ASKED for a mobile number, while replying
    to that very number. Rule 9 of the brief now forbids that ask.
    """

    def test_the_owners_own_number(self):
        self.assertIsNone(b.parse_followup("8884448141")["quantity"])

    def test_any_long_digit_run(self):
        for text in ("9632934468", "+91 88844 48141", "+919632934468",
                     "8217842452", "919964979374"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text)["quantity"], text)

    def test_a_figure_after_a_plus_is_not_a_count(self):
        self.assertIsNone(b.parse_followup("+91")["quantity"])

    def test_a_real_quantity_still_reads(self):
        for text, want in (("2 units", 2), ("888", 888), ("3", 3),
                           ("100kv 2", 2), ("5 nos", 5)):
            with self.subTest(text=text):
                self.assertEqual(b.parse_followup(text)["quantity"], want)


class ASentenceIsNotAnAddress(unittest.TestCase):
    """Also from that thread: "Nimma company estu varshadinda ide" (how many
    years has your company existed) was recorded as the delivery address.

    Two causes, both fixed. The Latin spellings of pronouns and question
    words that already existed in Kannada script were missing from
    _NOT_A_BARE_ANSWER; and removing the length caps entirely left nothing to
    stop a long sentence with no recognised word in it.
    """

    def test_the_three_production_sentences(self):
        for text in ("Nanna hesaru gotta",
                     "Nim boss jote matadbekuttu",
                     "Nimma company estu varshadinda ide"):
            with self.subTest(text=text):
                self.assertIsNone(
                    b.parse_followup(text, awaiting=ASKED)["delivery_location"],
                    text)

    def test_a_long_sentence_with_no_recognised_word_is_refused(self):
        self.assertIsNone(b.parse_followup(
            "100 hp pump ide yaava transformer hakbeku",
            awaiting=ASKED)["delivery_location"])

    def test_a_long_answer_with_an_address_marker_is_kept(self):
        for text in ("Tumkur district Gubbi taluk Chelur hobli",
                     "ತುಮಕೂರು ಜಿಲ್ಲೆ ಗುಬ್ಬಿ ತಾಲ್ಲೂಕು ಚೇಳೂರು ಹೋಬಳಿ ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"):
            with self.subTest(text=text):
                self.assertIsNotNone(
                    b.parse_followup(text, awaiting=ASKED)["delivery_location"],
                    text)

    def test_the_shorter_real_addresses_are_untouched(self):
        for text in ("Kadaba", "ಬೆಂಗಳೂರು", "Kadaba near tumkur",
                     "Kadur (T) Turuvanahalli", "1st main road Rajajinagar",
                     "Chelur inda 5 km Kulumegudlu",
                     "Hubli Dharwad Bijapur Bidar Gadag"):
            with self.subTest(text=text):
                self.assertEqual(
                    b.parse_followup(text, awaiting=ASKED)["delivery_location"],
                    text)

    def test_the_long_answer_net_ISOLATED(self):
        """Long, no address marker, and no word from any other list.

        Mutation testing showed the three production sentences are each
        caught TWICE -- once by the Latin pronoun/question words and once by
        this net -- so removing either defence alone changed nothing. That
        overlap is worth having, but it means the mechanisms have to be
        tested apart from each other. This sentence is caught by the net and
        by nothing else.
        """
        text = "please arrange good quality transformer soon for the farm"
        self.assertGreater(len(text.split()), b._LONG_ANSWER_WORDS)
        self.assertFalse(b._has_address_marker(text.lower()))
        self.assertIsNone(
            b.parse_followup(text, awaiting=ASKED)["delivery_location"])

    def test_the_latin_pronouns_ISOLATED(self):
        """Short enough that the long-answer net never runs, and carrying a
        pronoun as its only listed word."""
        for text in ("Nanna address", "Nimma address", "Naanu bartini",
                     "Namma jaga", "Neevu heli"):
            with self.subTest(text=text):
                self.assertLessEqual(len(text.split()), b._LONG_ANSWER_WORDS)
                self.assertIsNone(
                    b.parse_followup(text, awaiting=ASKED)["delivery_location"],
                    text)

    def test_the_latin_question_words_ISOLATED(self):
        """Same, for a question word."""
        for text in ("Yaava transformer", "Estu aguttade"):
            with self.subTest(text=text):
                self.assertLessEqual(len(text.split()), b._LONG_ANSWER_WORDS)
                self.assertIsNone(
                    b.parse_followup(text, awaiting=ASKED)["delivery_location"],
                    text)

    def test_the_address_markers_are_structure_not_places(self):
        """No gazetteer: the markers name the PARTS of an address."""
        for place in ("tumkur", "bengaluru", "kadaba", "mysuru", "hubli",
                      "ತುಮಕೂರು", "ಬೆಂಗಳೂರು", "ಕಡಬ"):
            with self.subTest(place=place):
                self.assertNotIn(place, b._ADDRESS_MARKER)

    def test_a_marker_must_be_a_whole_word(self):
        """"main" must not be found inside "remaining"."""
        self.assertFalse(b._has_address_marker("remaining quantity pending"))
        self.assertTrue(b._has_address_marker("1st main road"))


class TheBriefStatesWhatWeAlreadyKnow(unittest.TestCase):

    def test_it_forbids_asking_for_the_phone_number(self):
        """The customer is speaking FROM the number. Asking for it produced
        the 888-units defect."""
        brief = b.model_brief_kn()
        self.assertIn("ಫೋನ್ ನಂಬರ್ ಕೇಳಬೇಡಿ", brief)

    def test_it_lists_the_established_facts(self):
        brief = b.model_brief_kn({"name": "Raviraj", "capacity_kva": 25,
                                  "application": "AGRICULTURE",
                                  "location": "Kadaba"})
        for value in ("Raviraj", "25", "AGRICULTURE", "Kadaba"):
            with self.subTest(value=value):
                self.assertIn(value, brief)

    def test_an_unset_field_is_not_offered_as_a_blank(self):
        brief = b.model_brief_kn({"name": "Raviraj"})
        self.assertIn("Raviraj", brief)
        self.assertNotIn("TBD", brief)
        self.assertNotIn("None", brief)

    def test_nothing_known_says_so_plainly(self):
        self.assertIn("ಇನ್ನೂ ಏನೂ ತಿಳಿದಿಲ್ಲ", b.model_brief_kn())

    def test_it_is_still_callable_with_no_argument(self):
        """Additive: the signature change must not break any caller."""
        self.assertTrue(b.model_brief_kn())

    def test_the_known_facts_do_not_smuggle_a_forbidden_claim(self):
        """A delivery_location is free text the customer wrote, so it reaches
        the brief -- it must not be able to carry a price into it."""
        brief = b.model_brief_kn({"delivery_location": "Kadaba"})
        self.assertIsNone(b._REPLY_MONEY_RE.search(brief))


class TheModelSeesConversationNotMarkers(unittest.TestCase):
    """Every Bairavi assistant row in the transcript is a marker, not the
    reply the customer received. Passing those as the model's own past turns
    gave it internal tokens instead of memory: on 2026-09-22 it answered "I
    do not know your name" three turns after the customer gave it.
    """

    def _messages_sent(self, history):
        followup = parse("who are you?")
        captured = {}

        def fake(messages, apology, max_tokens=None):
            captured["messages"] = messages
            return "We are Bairavi Trans Solutions, Kadaba."

        with mock.patch.object(w, "_generate_ai_reply", side_effect=fake):
            w.bairavi_model_reply("919000000000", "who are you?", history,
                                  followup, KNOWN)
        return captured.get("messages", [])

    def test_marker_rows_are_not_sent(self):
        history = [{"role": "user", "content": "Raviraj"},
                   {"role": "assistant",
                    "content": b.flow_marker((b.AWAITING_DELIVERY,))}]
        sent = self._messages_sent(history)
        self.assertNotIn(b.FLOW_MARKER, str(sent))

    def test_the_customers_own_words_are_kept(self):
        history = [{"role": "user", "content": "Raviraj"},
                   {"role": "assistant",
                    "content": b.flow_marker((b.AWAITING_DELIVERY,))}]
        self.assertIn("Raviraj", str(self._messages_sent(history)))

    def test_the_brief_is_the_first_message(self):
        sent = self._messages_sent([])
        self.assertEqual(sent[0]["role"], "system")
        self.assertIn("Bairavi", sent[0]["content"])

    def test_the_brief_carries_the_known_state(self):
        sent = self._messages_sent([])
        self.assertIn("kushtagi", sent[0]["content"])
