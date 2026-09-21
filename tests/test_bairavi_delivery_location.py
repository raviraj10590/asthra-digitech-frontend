"""A bare place name is an answer when we just asked where to deliver.

THE PRODUCTION FAILURE THIS CLOSES (2026-09-20)
-----------------------------------------------
The bot asked where to deliver. The customer answered "ಗುಜರಾತ್". Then
"Gujarat". Neither registered, because _DELIVERY_STRICT_RE requires either a
colon ("ಡೆಲಿವರಿ: ಗುಜರಾತ್") or an English preposition ("delivery to Gujarat").
A one-word reply — the way people actually answer a question — read as
nothing, so the question was asked a fourth time and the customer wrote
"You mad".

THE CONTEXT COMES FROM THE TRANSCRIPT, NOT FROM A LIST OF PLACES
----------------------------------------------------------------
The reply that asks the question already records what it is waiting for:
flow_marker() writes "awaiting=delivery" and marker_awaiting() reads it back —
machinery that already existed for the hourly nudge. So "was the previous turn
a delivery question?" is a fact this module can consult, and no gazetteer is
needed to answer it.

That is deliberate. The ONLY geography the Brain owns is the Karnataka
`constituencies` table (webhook.py `_constituency_list`): a political dataset
behind a network call with a 6-hour cache, holding 224 constituency names plus
districts. It has no Gujarat in it — Gujarat is a different state — and using
it would turn this pure, offline module into one that needs a database to read
a message. It is not used here, and a hardcoded list of Indian states was not
added either.

NO NORMALIZATION — AND THAT IS A REPORTED GAP, NOT AN OVERSIGHT
---------------------------------------------------------------
The place is stored VERBATIM. "ಗುಜರಾತ್" stays "ಗುಜರಾತ್"; it does not become
"Gujarat". "ಮೈಸೂರು" stays "ಮೈಸೂರು"; it does not become "Mysuru".

There is no place-name mapping anywhere in the Brain to canonicalise against —
no Kannada-to-English transliteration, no city or state vocabulary, no alias
table. Inventing one here would be a geography policy nobody has decided, and
would immediately raise questions this code cannot answer: is "Mysore" the
same place as "Mysuru"? Is "Bangalore" "Bengaluru"? Which spelling does the
lorry paperwork use? Those are business decisions.

So the tests below assert the verbatim value, and the missing decision is
reported rather than guessed. This is also consistent with how the existing
strict shapes already behave: "ಡೆಲಿವರಿ: ಗುಜರಾತ್" has always returned "ಗುಜರಾತ್".

CONSERVATIVE BY DESIGN (AC-07)
------------------------------
Even inside the delivery context, anything that cannot be confidently read as
an answer returns None and the question is asked again. A rejected answer
costs one more question; a wrong one sends a lorry to the wrong district.

Offline: no network, no provider, no database.
"""

import ast
import inspect
import io as _io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402


def _module_source():
    return inspect.getsource(b)


def executable_code() -> str:
    """The module's source with comments AND string literals removed.

    Needed because this file's assertions are about the module's SUBJECT
    MATTER, and the module's own comments discuss it: the delivery fix
    explains that it deliberately avoids transliteration and the Karnataka
    `constituencies` table, so a raw search for "translit" or "constituenc"
    matches the rationale for not doing the thing. Twice already in this
    project a prohibition has been satisfied or violated by prose rather than
    by behaviour.
    """
    out = []
    for tok in tokenize.generate_tokens(
            _io.StringIO(_module_source()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def literal_strings() -> str:
    """Every string CONSTANT in the module except docstrings.

    The mirror image of executable_code(): a hardcoded gazetteer of places
    would live in string literals, so stripping all strings would make that
    assertion vacuous. Docstrings are excluded because they are prose.
    """
    tree = ast.parse(_module_source())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return "\n".join(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings)

# The context the bot itself records after asking where to deliver.
ASKED_DELIVERY = (b.AWAITING_DELIVERY,)
ASKED_BOTH = (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE)
ASKED_PURPOSE_ONLY = (b.AWAITING_PURPOSE,)


PHONE = "910000000000"


def delivery(text, awaiting=ASKED_DELIVERY):
    return b.parse_followup(text, awaiting)["delivery_location"]


def conversation(*messages):
    """Replay a thread through the real history shape, with the assistant's
    flow marker between turns exactly as the webhook writes it.

    One implementation, used by every class below — the replay was previously
    inline in a single setUp, and a second copy would be a second truth about
    how a turn is computed.
    """
    hist, turns = [], []
    for text in messages:
        asked = b.awaiting_from_history(hist)
        known = b.established_from_history(hist)
        followup = b.parse_followup(text, asked)
        awaiting = b.outstanding(followup, known)
        turns.append({"text": text, "asked": asked, "known": known,
                      "followup": followup, "awaiting": awaiting,
                      "state": b.merged_state(known, followup)})
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": b.flow_marker(awaiting)})
    return turns


# ══════════════════════════════════════════════════════════════════════════
# 1 · REAL CUSTOMER SHAPES — the answers people actually send
# ══════════════════════════════════════════════════════════════════════════

class ABarePlaceNameIsAnAnswer(unittest.TestCase):

    def test_english_state(self):
        self.assertEqual(delivery("Gujarat"), "Gujarat")

    def test_english_city(self):
        self.assertEqual(delivery("Mysuru"), "Mysuru")

    def test_english_city_bengaluru(self):
        self.assertEqual(delivery("Bengaluru"), "Bengaluru")

    def test_kannada_state(self):
        self.assertEqual(delivery("ಗುಜರಾತ್"), "ಗುಜರಾತ್")

    def test_kannada_city(self):
        self.assertEqual(delivery("ಮೈಸೂರು"), "ಮೈಸೂರು")

    def test_kannada_city_bengaluru(self):
        self.assertEqual(delivery("ಬೆಂಗಳೂರು"), "ಬೆಂಗಳೂರು")

    def test_it_works_when_purpose_was_also_outstanding(self):
        """The real sequence asked for both at once."""
        self.assertEqual(delivery("ಗುಜರಾತ್", ASKED_BOTH), "ಗುಜರಾತ್")

    def test_a_two_word_place_is_an_answer(self):
        self.assertEqual(delivery("Hubli Dharwad"), "Hubli Dharwad")

    def test_trailing_punctuation_is_trimmed_not_stored(self):
        self.assertEqual(delivery("Gujarat."), "Gujarat")
        self.assertEqual(delivery("Gujarat,"), "Gujarat")

    def test_the_value_is_stored_VERBATIM_not_transliterated(self):
        """No place mapping exists to canonicalise against — see the module
        docstring. The Kannada spelling is preserved as the customer wrote
        it."""
        self.assertEqual(delivery("ಮೈಸೂರು"), "ಮೈಸೂರು")
        self.assertNotEqual(delivery("ಮೈಸೂರು"), "Mysuru")
        self.assertEqual(delivery("ಗುಜರಾತ್"), "ಗುಜರಾತ್")
        self.assertNotEqual(delivery("ಗುಜರಾತ್"), "Gujarat")


# ══════════════════════════════════════════════════════════════════════════
# 2 · THE SHAPES THAT ALWAYS WORKED MUST KEEP WORKING
# ══════════════════════════════════════════════════════════════════════════

class TheExistingStrictShapesAreUnchanged(unittest.TestCase):

    def test_english_preposition_form(self):
        self.assertEqual(delivery("delivery to Gujarat"), "Gujarat")

    def test_kannada_colon_form(self):
        self.assertEqual(delivery("ಡೆಲಿವರಿ: ಗುಜರಾತ್"), "ಗುಜರಾತ್")

    def test_the_strict_shapes_work_with_NO_context_at_all(self):
        """They never needed the context and must not start needing it."""
        self.assertEqual(b.parse_followup("delivery to Gujarat")[
            "delivery_location"], "Gujarat")
        self.assertEqual(b.parse_followup("ಡೆಲಿವರಿ: ಗುಜರಾತ್")[
            "delivery_location"], "ಗುಜರಾತ್")

    def test_the_strict_shape_still_wins_over_the_bare_reading(self):
        """A message carrying both must yield the explicitly marked place."""
        self.assertEqual(delivery("delivery to Hubli"), "Hubli")

    def test_same_place_is_still_a_confirmation_not_an_address(self):
        """'ಅದೇ' answers the question without naming anywhere. Recording it
        as an address would point a lorry at the word 'same'."""
        for word in ("same", "ಅದೇ", "same place", "ಹೌದು"):
            parsed = b.parse_followup(word, ASKED_DELIVERY)
            self.assertIsNone(parsed["delivery_location"], word)
            self.assertTrue(parsed["delivery_same"], word)

    def test_same_place_inside_a_longer_reply_is_also_not_an_address(self):
        """The exact-match branch above catches a bare "same"; this needs the
        SUBSTRING branch. Without it "yes same place" is stored as a place."""
        for phrase in ("yes same place", "ಅದೇ ಸ್ಥಳ ಸರಿ"):
            parsed = b.parse_followup(phrase, ASKED_DELIVERY)
            self.assertIsNone(parsed["delivery_location"], phrase)

    def test_a_delivery_mention_without_a_place_is_still_just_a_mention(self):
        parsed = b.parse_followup("ಡೆಲಿವರಿ ಬೇಕು", ASKED_DELIVERY)
        self.assertTrue(parsed["delivery_mentioned"])


# ══════════════════════════════════════════════════════════════════════════
# 3 · NEGATIVE AND CONTEXT CASES
# ══════════════════════════════════════════════════════════════════════════

class ContextDecidesWhetherItIsAnAnswer(unittest.TestCase):

    def test_a_bare_name_with_NO_delivery_question_is_not_an_address(self):
        """The whole point of the gate. 'Gujarat' mid-conversation about
        capacity is not a delivery instruction."""
        self.assertIsNone(delivery("Gujarat", ()))
        self.assertIsNone(delivery("ಗುಜರಾತ್", ()))

    def test_a_bare_name_when_only_PURPOSE_was_asked_is_not_an_address(self):
        self.assertIsNone(delivery("Gujarat", ASKED_PURPOSE_ONLY))

    def test_I_am_from_Gujarat_is_not_a_delivery_address(self):
        """Where the customer is and where the transformer goes are routinely
        different — this is exactly the confidently-wrong field AC-07
        forbids."""
        self.assertIsNone(delivery("I am from Gujarat"))
        self.assertIsNone(delivery("i'm from Gujarat"))
        self.assertIsNone(delivery("we are from Gujarat"))
        self.assertIsNone(delivery("from Gujarat"))

    def test_a_kannada_origin_statement_is_not_an_address(self):
        self.assertIsNone(delivery("ನಾನು ಗುಜರಾತ್"))
        self.assertIsNone(delivery("ನಮ್ಮ ಗುಜರಾತ್"))

    def test_a_price_question_is_not_an_address(self):
        self.assertIsNone(delivery("Gujarat price?"))
        self.assertIsNone(delivery("Gujarat rate"))
        self.assertIsNone(delivery("ಗುಜರಾತ್ ದರ"))

    def test_any_question_is_not_an_address(self):
        self.assertIsNone(delivery("Gujarat?"))
        self.assertIsNone(delivery("why Gujarat?"))

    def test_an_acknowledgement_is_not_an_address(self):
        """The most dangerous case: a short reply that is not a place at all.
        Recording it would dispatch a lorry to 'ok'."""
        for word in ("ok", "OK", "okay", "ಸರಿ", "thanks", "ಧನ್ಯವಾದ",
                     "hmm", "fine", "sure", "ಇಲ್ಲ", "no"):
            self.assertIsNone(delivery(word), word)

    def test_another_fields_answer_is_not_an_address(self):
        """Purpose, capacity and quantity have their own extractors."""
        for word in ("ಕೃಷಿ", "agriculture", "industry", "solar",
                     "100 kva", "೨೪ kv", "3 units", "2"):
            self.assertIsNone(delivery(word), word)

    def test_a_long_sentence_mentioning_a_place_is_not_an_address(self):
        self.assertIsNone(delivery(
            "our line is far from the town so we need a TC in Gujarat"))

    def test_too_many_words_is_not_an_address_EVEN_WITH_NO_STOPWORDS(self):
        """Isolates the word limit. Every token here is a plausible place and
        none is a disqualifying word, so only _BARE_ANSWER_MAX_WORDS can
        reject it — the sentence test above is also caught by "from"/"we",
        which left this guard unverified."""
        five_short_words = "Hubli Dharwad Bijapur Bidar Gadag"
        self.assertEqual(len(five_short_words.split()), 5)
        self.assertLessEqual(len(five_short_words), b._BARE_ANSWER_MAX_CHARS)
        self.assertIsNone(delivery(five_short_words))

    def test_too_many_characters_is_not_an_address(self):
        """Isolates the character limit: within the word limit, over the
        character limit, and carrying no disqualifying word."""
        long_but_few_words = "Gandhinagar Ahmedabad Gandhinagar Ahmedabad"
        self.assertLessEqual(len(long_but_few_words.split()),
                             b._BARE_ANSWER_MAX_WORDS)
        self.assertGreater(len(long_but_few_words), b._BARE_ANSWER_MAX_CHARS)
        self.assertIsNone(delivery(long_but_few_words))

    def test_the_two_limits_are_genuinely_different_guards(self):
        """Guards the two tests above against being accidentally redundant."""
        self.assertLess(b._BARE_ANSWER_MAX_WORDS, 10)
        self.assertLess(b._BARE_ANSWER_MAX_CHARS, 100)

    def test_digits_or_emoji_alone_are_not_an_address(self):
        for word in ("123", "👍", "⛽", "..."):
            self.assertIsNone(delivery(word), word)

    def test_an_empty_or_blank_message_is_not_an_address(self):
        for word in ("", "   ", None):
            self.assertIsNone(delivery(word), repr(word))

    def test_the_purpose_answer_is_still_read_in_the_delivery_context(self):
        """Rejecting 'ಕೃಷಿ' as a place must not stop it being read as the
        purpose."""
        parsed = b.parse_followup("ಕೃಷಿ", ASKED_BOTH)
        self.assertEqual(parsed["application"], "AGRICULTURE")
        self.assertIsNone(parsed["delivery_location"])


# ══════════════════════════════════════════════════════════════════════════
# 4 · THE REAL CONVERSATION, END TO END
# ══════════════════════════════════════════════════════════════════════════

class TheProductionConversationCompletes(unittest.TestCase):
    """The verbatim sequence, replayed through the real history shape with the
    assistant's flow marker between turns — the same machinery the webhook
    uses."""

    SEQUENCE = ("೨೪ kv", "೧ beku", "ಕೃಷಿ", "ಗುಜರಾತ್", "Gujarat")

    def setUp(self):
        self.turns = conversation(*self.SEQUENCE)

    def test_delivery_was_being_asked_when_the_place_arrived(self):
        self.assertIn(b.AWAITING_DELIVERY, self.turns[3]["asked"])

    def test_the_kannada_place_is_established(self):
        self.assertEqual(self.turns[3]["state"]["delivery_location"], "ಗುಜರಾತ್")

    def test_purpose_and_quantity_are_NOT_disturbed_by_the_new_field(self):
        """Fix #1's invariant must still hold through fix #2."""
        state = self.turns[3]["state"]
        self.assertEqual(state["application"], "AGRICULTURE")
        self.assertEqual(state["quantity"], 1)

    def test_nothing_is_outstanding_once_the_place_is_given(self):
        self.assertEqual(self.turns[3]["awaiting"], ())

    def test_the_repeated_latin_spelling_changes_nothing_harmfully(self):
        """'Gujarat' arrives after the question has stopped being asked, so
        it is no longer read as an address — and the established Kannada
        value is NOT overwritten by it."""
        self.assertEqual(self.turns[4]["asked"], ())
        self.assertEqual(self.turns[4]["state"]["delivery_location"], "ಗುಜರಾತ್")
        self.assertEqual(self.turns[4]["awaiting"], ())

    def test_the_bot_asks_for_nothing_further(self):
        last = self.turns[3]
        reply = b.compose_followup_reply(last["followup"], last["known"])
        self.assertNotIn(b.question_for(b.AWAITING_PURPOSE), reply)
        self.assertNotIn("ಯಾವ ಸ್ಥಳಕ್ಕೆ ಬೇಕು", reply)

    def test_the_reply_confirms_the_place_back_to_the_customer(self):
        last = self.turns[3]
        reply = b.compose_followup_reply(last["followup"], last["known"])
        self.assertIn("ಗುಜರಾತ್", reply)

    def test_the_owner_alert_carries_the_place(self):
        last = self.turns[3]
        alert = b.compose_followup_alert("910000000000", last["followup"],
                                         last["text"], last["known"])
        self.assertIn("Delivery to: ಗುಜರಾತ್", alert)
        self.assertIn("Application: AGRICULTURE", alert)

    def test_an_explicit_new_place_DOES_update_an_established_one(self):
        """Fix #1 made state monotonic, not frozen. A customer who corrects
        the address must be able to: "actually delivery to Mysuru" supersedes
        an earlier Hubli. Without this the merge could special-case delivery
        into being unchangeable and no test would notice."""
        hist = [
            {"role": "assistant",
             "content": b.flow_marker((b.AWAITING_DELIVERY,))},
            {"role": "user", "content": "delivery to Hubli"},
            {"role": "assistant", "content": b.flow_marker(())},
            {"role": "user", "content": "delivery to Mysuru"},
        ]
        self.assertEqual(
            b.established_from_history(hist)["delivery_location"], "Mysuru")

    def test_the_transcript_marker_stops_asking_for_anything(self):
        """What the hourly nudge reads — it must not chase a completed
        qualification."""
        self.assertEqual(b.marker_awaiting(
            b.flow_marker(self.turns[3]["awaiting"])), ())


# ══════════════════════════════════════════════════════════════════════════
# 5 · THE CONTEXT READER
# ══════════════════════════════════════════════════════════════════════════

class AwaitingIsReadFromTheTranscript(unittest.TestCase):

    def test_it_reads_the_marker_the_flow_wrote(self):
        hist = [{"role": "user", "content": "x"},
                {"role": "assistant",
                 "content": b.flow_marker((b.AWAITING_DELIVERY,))}]
        self.assertEqual(b.awaiting_from_history(hist),
                         (b.AWAITING_DELIVERY,))

    def test_it_reads_the_MOST_RECENT_bairavi_reply(self):
        hist = [
            {"role": "assistant", "content": b.flow_marker(
                (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE))},
            {"role": "user", "content": "ಕೃಷಿ"},
            {"role": "assistant", "content": b.flow_marker(
                (b.AWAITING_DELIVERY,))},
        ]
        self.assertEqual(b.awaiting_from_history(hist),
                         (b.AWAITING_DELIVERY,))

    def test_a_completed_flow_awaits_nothing(self):
        hist = [{"role": "assistant", "content": b.flow_marker(())}]
        self.assertEqual(b.awaiting_from_history(hist), ())

    def test_a_conversation_with_no_bairavi_reply_awaits_nothing(self):
        hist = [{"role": "user", "content": "hello"},
                {"role": "assistant", "content": "ನಮಸ್ಕಾರ"}]
        self.assertEqual(b.awaiting_from_history(hist), ())

    def test_empty_and_none_history_are_safe(self):
        self.assertEqual(b.awaiting_from_history([]), ())
        self.assertEqual(b.awaiting_from_history(None), ())

    def test_a_customer_message_cannot_forge_the_context(self):
        """A user turn quoting the marker must not grant delivery context —
        otherwise a customer could make any word an address."""
        hist = [{"role": "user",
                 "content": b.flow_marker((b.AWAITING_DELIVERY,))}]
        self.assertEqual(b.awaiting_from_history(hist), ())

    def test_history_replay_uses_the_same_context_as_the_live_turn(self):
        """established_from_history must reach the same conclusion about a
        past bare answer that the live turn reached — otherwise the two
        disagree about the same conversation."""
        hist = [
            {"role": "assistant", "content": b.flow_marker(
                (b.AWAITING_DELIVERY,))},
            {"role": "user", "content": "ಗುಜರಾತ್"},
        ]
        self.assertEqual(
            b.established_from_history(hist)["delivery_location"], "ಗುಜರಾತ್")

    def test_history_replay_does_NOT_invent_context_that_was_absent(self):
        hist = [{"role": "assistant", "content": b.flow_marker(())},
                {"role": "user", "content": "ಗುಜರಾತ್"}]
        self.assertIsNone(
            b.established_from_history(hist)["delivery_location"])


# ══════════════════════════════════════════════════════════════════════════
# 6 · NO GEOGRAPHY WAS HARDCODED OR FETCHED
# ══════════════════════════════════════════════════════════════════════════

class ABareAnswerMustActUALLYLookLikeAPlace(unittest.TestCase):
    """THE REVIEW BLOCKER, closed.

    The first version of this filter rejected acknowledgements, pronouns and
    other parsed fields, and let through every OTHER kind of non-answer. Asked
    where to deliver, a customer replying "ತಕ್ಷಣ" (immediately), "call me",
    "idk", "later" or "sir" had it recorded as the delivery ADDRESS. The
    monotonicity invariant then made it permanent and the quotation signal
    declared the requirement set complete with "Delivery to: ತಕ್ಷಣ" — AC-07's
    confidently-wrong field in one turn, and a regression against production,
    which simply kept asking.

    "You mad" — the customer's actual words on 2026-09-20, the message that
    started this whole workstream — was being stored as a delivery address.

    Three of the rejected classes are consulted through tables that already
    existed (_TIMING_URGENCY, _PRICE_ASK, _ASTHRA_EXIT); only four needed new
    vocabulary, and those are linguistic categories, not business policy. No
    gazetteer, transliteration or canonical form was introduced.
    """

    # Every case the review enumerated, as data so none can be quietly
    # dropped from the suite.
    NOT_PLACES = ("ತಕ್ಷಣ", "urgent", "soon", "asap", "call me", "ಕರೆ ಮಾಡಿ",
                  "later", "ಗೊತ್ತಿಲ್ಲ", "sir", "hello", "idk", "You mad",
                  "quotation ಬೇಕು")

    def test_none_of_the_reported_non_places_becomes_an_address(self):
        for word in self.NOT_PLACES:
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_the_whole_reported_list_is_covered(self):
        """Guards the list above against being trimmed."""
        self.assertEqual(len(self.NOT_PLACES), 13)

    # ── by semantic class, so a partial fix cannot pass ──────────────────
    def test_urgency_is_not_a_place(self):
        """Answers "when", not "where". ತಕ್ಷಣ and urgent come from
        _TIMING_URGENCY, which already defined them."""
        for word in ("ತಕ್ಷಣ", "urgent", "immediate", "soon", "asap", "later",
                     "today", "tomorrow", "ಇವತ್ತು", "ನಾಳೆ"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_a_request_to_be_contacted_is_not_a_place(self):
        for word in ("call me", "call back", "callback", "ಕರೆ ಮಾಡಿ",
                     "phone me", "whatsapp me", "ಫೋನ್ ಮಾಡಿ"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_uncertainty_is_not_a_place(self):
        """A refusal to answer is not an answer."""
        for word in ("idk", "dunno", "maybe", "not sure", "no idea",
                     "dont know", "don't know", "ಗೊತ್ತಿಲ್ಲ", "ತಿಳಿದಿಲ್ಲ"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_a_greeting_or_term_of_address_is_not_a_place(self):
        for word in ("hi", "hello", "hey", "ನಮಸ್ಕಾರ", "sir", "madam", "sar",
                     "bro", "boss", "anna", "ಸರ್"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_a_second_person_statement_is_not_a_place(self):
        for phrase in ("You mad", "you there", "your office", "u ok"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(delivery(phrase), phrase)

    def test_a_price_or_quotation_ask_is_not_a_place(self):
        for word in ("quotation ಬೇಕು", "rate", "ದರ", "quote", "price list"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_another_asthra_service_is_not_a_place(self):
        """A transformer buyer asking about a website is not naming a site."""
        for word in ("website", "logo", "ವೆಬ್‌ಸೈಟ್"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_the_same_classes_as_BARE_SINGLE_WORDS_are_rejected(self):
        """Found by a mutation that widened the phrase test and did not fail:
        "call me" was rejected while a bare "call" became an address. "ಕಳಿಸಿ"
        (send) was the worst — already a _DELIVERY_MENTION_RE word, so it set
        delivery_mentioned AND delivery_location to the verb itself."""
        for word in ("call", "phone", "message", "whatsapp", "contact",
                     "meet", "visit", "send", "ಕರೆ", "ಫೋನ್", "ಕಳಿಸಿ",
                     "done", "ready", "fast", "any", "yes sir"):
            with self.subTest(word=word):
                self.assertIsNone(delivery(word), word)

    def test_a_delivery_VERB_alone_never_becomes_the_address(self):
        """ಕಳಿಸಿ means "send". It answers that they want delivery, not where.
        It may still set delivery_mentioned — that is the correct channel for
        "they responded but named no place"."""
        parsed = b.parse_followup("ಕಳಿಸಿ", ASKED_DELIVERY)
        self.assertIsNone(parsed["delivery_location"])
        self.assertTrue(parsed["delivery_mentioned"])

    # ── the guard must not eat real places ──────────────────────────────
    def test_real_places_still_pass_the_new_guard(self):
        for place in ("ಗುಜರಾತ್", "Mysuru", "ಮೈಸೂರು", "Bengaluru", "ಬೆಂಗಳೂರು",
                      "Gujarat", "Hubli", "Hubli Dharwad", "Belgaum",
                      "Gandhinagar", "Tumkur", "ಪುತ್ತೂರು"):
            with self.subTest(place=place):
                self.assertEqual(delivery(place), place, place)

    def test_place_names_CONTAINING_a_rejected_word_still_pass(self):
        """Why the single words are compared against the WHOLE message and
        not matched as substrings: word-boundary matching on "anna" would
        reject Anna Nagar, and on "hi" would reject Hirekerur."""
        for place in ("Anna Nagar", "Hirekerur", "Sirsi", "Hospet",
                      "Kalaburagi"):
            with self.subTest(place=place):
                self.assertEqual(delivery(place), place, place)

    def test_the_strict_shapes_are_untouched_by_the_guard(self):
        self.assertEqual(b.parse_followup("delivery to Hubli")[
            "delivery_location"], "Hubli")
        self.assertEqual(b.parse_followup("ಡೆಲಿವರಿ: ಗುಜರಾತ್")[
            "delivery_location"], "ಗುಜರಾತ್")

    def test_a_strict_shape_naming_an_urgency_word_is_still_honoured(self):
        """The guard applies to BARE answers only. If the customer explicitly
        writes "delivery to <x>", they have told us x is the place."""
        self.assertEqual(delivery("delivery to soon"), "soon")

    # ── the end-to-end regression the review demanded ───────────────────
    def test_the_full_chain_no_longer_poisons_the_qualification(self):
        turns = conversation("100 kva", "2 units", "ಕೃಷಿ", "ತಕ್ಷಣ",
                             "quotation ಬೇಕು")
        final = turns[-1]
        self.assertEqual(final["state"]["capacity_kva"], 100)
        self.assertEqual(final["state"]["quantity"], 2)
        self.assertEqual(final["state"]["application"], "AGRICULTURE")
        self.assertIsNone(final["state"]["delivery_location"])
        self.assertIn(b.AWAITING_DELIVERY, final["awaiting"])

    def test_the_requirement_set_is_NOT_declared_complete(self):
        from bic import goals as _g
        goal = _g.lookup(b.QUOTATION_GOAL_ID)
        turns = conversation("100 kva", "2 units", "ಕೃಷಿ", "ತಕ್ಷಣ",
                             "quotation ಬೇಕು")
        final = turns[-1]
        self.assertIn(b.AWAITING_DELIVERY,
                      b.missing_requirements(goal, final["state"]))
        signal = b.compose_quotation_signal(
            PHONE, final["followup"], final["text"], final["known"], goal)
        self.assertIn("Still missing", signal)
        self.assertNotIn("Every requirement this bot can collect", signal)

    def test_the_owner_is_never_told_the_urgency_word_is_the_address(self):
        from bic import goals as _g
        goal = _g.lookup(b.QUOTATION_GOAL_ID)
        turns = conversation("100 kva", "2 units", "ಕೃಷಿ", "ತಕ್ಷಣ",
                             "quotation ಬೇಕು")
        final = turns[-1]
        signal = b.compose_quotation_signal(
            PHONE, final["followup"], final["text"], final["known"], goal)
        self.assertNotIn("Delivery to: ತಕ್ಷಣ", signal)
        self.assertIn("TBD", signal)

    def test_the_bot_asks_for_the_delivery_place_again(self):
        """The whole point: a non-answer must re-ask, not be accepted."""
        turns = conversation("100 kva", "2 units", "ಕೃಷಿ", "ತಕ್ಷಣ")
        reply = b.compose_followup_reply(turns[-1]["followup"],
                                         turns[-1]["known"])
        self.assertIn(b.question_for(b.AWAITING_DELIVERY), reply)

    def test_the_original_production_sequence_is_unaffected(self):
        """The guard must not undo fix #2's actual win."""
        turns = conversation("24 kVA", "1 beku", "ಕೃಷಿ", "ಗುಜರಾತ್", "Gujarat")
        final = turns[-1]["state"]
        self.assertEqual(final["capacity_kva"], 24)
        self.assertEqual(final["quantity"], 1)
        self.assertEqual(final["application"], "AGRICULTURE")
        self.assertEqual(final["delivery_location"], "ಗುಜರಾತ್")
        self.assertEqual(b.sku_status(final["capacity_kva"]), b.VERIFY)
        self.assertEqual(turns[-1]["awaiting"], ())

    def test_no_place_vocabulary_was_introduced_by_the_guard(self):
        """The fix adds semantic classes, not a gazetteer."""
        literals = literal_strings()
        for place in ("Gujarat", "Mysuru", "Bengaluru", "Hubli", "Mysore",
                      "Bangalore", "ಗುಜರಾತ್", "ಮೈಸೂರು", "Karnataka"):
            self.assertNotIn(place, literals, f"{place} was hardcoded")

    def test_the_urgency_class_is_read_from_the_EXISTING_table(self):
        """Not duplicated. If _TIMING_URGENCY changes, this guard follows."""
        self.assertTrue(any(n == "ತಕ್ಷಣ" for n, _ in b._TIMING_URGENCY))
        self.assertNotIn("ತಕ್ಷಣ", b._NOT_A_PLACE_EXACT)
        self.assertNotIn("urgent", b._NOT_A_PLACE_EXACT)


class TheWebhookActuallyPassesTheContext(unittest.TestCase):
    """The extraction is correct only if the caller supplies the context.
    Nothing else in this file exercises api/webhook.py, so a call site that
    dropped the argument would leave every test above passing while
    production went on asking four times."""

    def _followup_call(self):
        import ast as _ast
        src = _io.open(os.path.join(os.path.dirname(__file__), "..",
                                    "api", "webhook.py"),
                       encoding="utf-8").read()
        calls = []
        for node in _ast.walk(_ast.parse(src)):
            if not isinstance(node, _ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, _ast.Attribute) and fn.attr == "parse_followup"
                    and isinstance(fn.value, _ast.Name)
                    and fn.value.id == "bairavi"):
                calls.append(node)
        return calls

    def test_the_branch_calls_parse_followup_exactly_once(self):
        self.assertEqual(len(self._followup_call()), 1)

    def test_it_passes_the_conversational_context_as_the_second_argument(self):
        call = self._followup_call()[0]
        self.assertEqual(len(call.args), 2,
                         "parse_followup was called without the awaiting "
                         "context — a bare place name will not be read")

    def test_that_context_comes_from_awaiting_from_history(self):
        import ast as _ast
        second = self._followup_call()[0].args[1]
        self.assertIsInstance(second, _ast.Call)
        self.assertEqual(second.func.attr, "awaiting_from_history")


class NoPlaceVocabularyWasIntroduced(unittest.TestCase):

    def test_no_indian_state_or_city_list_was_added(self):
        """The fix is a context gate, not a gazetteer. A place list would go
        stale, would miss the next state, and would need a business owner.

        Searched over the module's STRING LITERALS, which is where such a list
        would live — not over the stripped code, which would make this
        vacuous."""
        literals = literal_strings()
        for place in ("Gujarat", "Maharashtra", "Tamil Nadu", "Kerala",
                      "Mysuru", "Bengaluru", "Hubli", "ಗುಜರಾತ್", "ಮೈಸೂರು",
                      "Mysore", "Bangalore"):
            self.assertNotIn(place, literals, f"{place} was hardcoded")

    def test_the_module_needs_no_network_and_no_database(self):
        """bairavi.py is pure. The only geography the Brain owns is the
        Karnataka constituencies table, behind a network call — using it here
        would put a database on the reply path.

        Over the EXECUTABLE code: the module's comments name that table in
        order to explain why it is not used."""
        code = executable_code()
        for token in ("requests", "constituenc", "SUPABASE", "urlopen"):
            self.assertNotIn(token, code, token)

    def test_no_transliteration_is_performed(self):
        """Reported as a business decision instead — see the module
        docstring. Asserted behaviourally, because the word "transliteration"
        appears in the code's own explanation of why it does none."""
        self.assertEqual(delivery("ಮೈಸೂರು"), "ಮೈಸೂರು")
        self.assertEqual(delivery("ಬೆಂಗಳೂರು"), "ಬೆಂಗಳೂರು")
        self.assertEqual(delivery("Mysuru"), "Mysuru")

    def test_the_helper_views_are_not_trivially_empty(self):
        """Guards the two helpers above: an empty view would make every
        assertion in this class pass for the wrong reason."""
        self.assertIn("_bare_delivery_answer", executable_code())
        self.assertIn("ok", literal_strings())


if __name__ == "__main__":
    unittest.main(verbosity=2)
