"""An established qualification fact must never become unestablished.

THE PRODUCTION FAILURE THIS CLOSES (2026-09-20)
-----------------------------------------------
A real transformer enquiry, in order:

    customer  "೨೪ kv"       -> awaiting = delivery, purpose
    customer  "೧ beku"      -> awaiting = delivery, purpose
    customer  "ಕೃಷಿ"        -> awaiting = delivery          ← purpose READ
    customer  "ಗುಜರಾತ್"      -> awaiting = delivery, purpose  ← purpose LOST
    customer  "Gujarat"     -> awaiting = delivery, purpose
    customer  "You mad"

The extractor was never at fault: it read ಕೃಷಿ as AGRICULTURE correctly, and
the flow narrowed to awaiting=delivery to prove it. One message later — a
place name, carrying nothing about purpose — the purpose was gone and the bot
asked for it again. The customer answered twice more, then gave up.

THE CAUSE. `outstanding()` read `application` from the CURRENT message only.
`established_from_history()` returned just location and delivery_location, and
only from the most recent LEAD FORM, so a fact given in a chat message had
nowhere to live. It survived exactly one turn. The delivery test already
consulted history; the purpose test did not.

THE INVARIANT, now enforced by merged_state():

    UNKNOWN -> ESTABLISHED           always allowed
    ESTABLISHED -> ESTABLISHED'      only on an explicit new value
    ESTABLISHED -> UNKNOWN           NEVER

Deliberately field-agnostic. There is no `if field == "purpose"` anywhere,
because the next field to be forgotten would not have been purpose.

SCOPE — one defect at a time
----------------------------
This file owns the STATE invariant. Bare-place-name recognition was a second,
separate defect and is fixed in test_bairavi_delivery_location.py.

While that defect was open, this file pinned its behaviour
(`parse_followup("ಗುಜರಾತ್")["delivery_location"] is None`) with a note saying
the test SHOULD fail once bare names became readable. It did exactly that, on
the first run after fix #2, and was replaced by the positive assertion — which
is the whole reason for pinning current behaviour rather than omitting it.

  * ReplayOfTheProductionFailure replays the verbatim messages and asserts
    the state invariant: purpose and quantity must never return to
    outstanding. It now also asserts the conversation completes.
  * DeliveryUsesTheExistingMechanism uses the colon/preposition shapes that
    always worked, so monotonicity for delivery is proven independently of
    the bare-answer path.

Offline: no network, no provider, no database.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402


def conversation(*messages):
    """The history shape fetch_context returns, with the assistant's flow
    marker between turns exactly as the webhook writes it."""
    hist = []
    states = []
    for text in messages:
        hist.append({"role": "user", "content": text})
        known = b.established_from_history(hist)
        followup = b.parse_followup(text)
        awaiting = b.outstanding(followup, known)
        states.append({
            "text": text,
            "known": known,
            "followup": followup,
            "awaiting": awaiting,
            "state": b.merged_state(known, followup),
        })
        hist.append({"role": "assistant", "content": b.flow_marker(awaiting)})
    return states


# ══════════════════════════════════════════════════════════════════════════
# 1 · THE VERBATIM PRODUCTION SEQUENCE
# ══════════════════════════════════════════════════════════════════════════

class ReplayOfTheProductionFailure(unittest.TestCase):

    SEQUENCE = ("೨೪ kv", "೧ beku", "ಕೃಷಿ", "ಗುಜರಾತ್", "Gujarat")

    def setUp(self):
        self.turns = conversation(*self.SEQUENCE)

    def test_the_purpose_is_read_from_the_kannada_word(self):
        """Turn 3. If this fails the defect is in extraction, not state."""
        self.assertEqual(self.turns[2]["followup"]["application"],
                         "AGRICULTURE")

    def test_the_purpose_leaves_outstanding_when_it_is_answered(self):
        self.assertNotIn(b.AWAITING_PURPOSE, self.turns[2]["awaiting"])

    def test_the_purpose_SURVIVES_the_next_unrelated_message(self):
        """THE BUG. 'ಗುಜರಾತ್' says nothing about purpose, and used to erase
        it."""
        self.assertEqual(self.turns[3]["state"]["application"], "AGRICULTURE")
        self.assertNotIn(b.AWAITING_PURPOSE, self.turns[3]["awaiting"])

    def test_the_purpose_survives_the_message_after_that_too(self):
        self.assertEqual(self.turns[4]["state"]["application"], "AGRICULTURE")
        self.assertNotIn(b.AWAITING_PURPOSE, self.turns[4]["awaiting"])

    def test_the_purpose_NEVER_returns_to_outstanding_once_answered(self):
        """The invariant, over the whole conversation rather than turn by
        turn: once purpose leaves the outstanding set it may not reappear."""
        seen_answered = False
        for turn in self.turns:
            answered = b.AWAITING_PURPOSE not in turn["awaiting"]
            if seen_answered:
                self.assertTrue(
                    answered,
                    f"purpose regressed at {turn['text']!r}: "
                    f"awaiting={turn['awaiting']}")
            seen_answered = seen_answered or answered
        self.assertTrue(seen_answered, "purpose was never answered at all")

    def test_the_quantity_from_turn_two_also_survives_to_the_end(self):
        """'೧ beku' is Kannada numeral one. It was read, and every later turn
        must still know it."""
        self.assertEqual(self.turns[1]["state"]["quantity"], 1)
        for turn in self.turns[1:]:
            self.assertEqual(turn["state"]["quantity"], 1, turn["text"])

    def test_a_stated_quantity_is_never_later_reported_as_assumed(self):
        """The owner-facing half of the same bug: printing
        '1 (assumed — not stated)' for a customer who did state it sends the
        salesperson to confirm an answered question."""
        last = self.turns[-1]
        qty, assumed = b.effective_quantity(last["followup"], last["known"])
        self.assertEqual(qty, 1)
        self.assertIs(assumed, False)

    def test_the_customer_is_not_asked_for_the_purpose_again(self):
        """What the customer actually sees — the reply must not re-ask."""
        last = self.turns[-1]
        reply = b.compose_followup_reply(last["followup"], last["known"])
        self.assertNotIn(b.question_for(b.AWAITING_PURPOSE), reply)

    def test_the_owner_alert_reports_the_established_purpose(self):
        last = self.turns[-1]
        alert = b.compose_followup_alert("910000000000", last["followup"],
                                         last["text"], last["known"])
        self.assertIn("Application: AGRICULTURE", alert)
        self.assertNotIn("Application: TBD", alert)

    def test_the_owner_alert_reports_the_quantity_as_STATED(self):
        """Through the alert, not through effective_quantity directly — the
        line the salesperson actually reads. '(assumed — not stated)' here
        would send them to confirm the '೧ beku' the customer already sent."""
        last = self.turns[-1]
        alert = b.compose_followup_alert("910000000000", last["followup"],
                                         last["text"], last["known"])
        self.assertIn("Quantity: 1", alert)
        self.assertNotIn("assumed", alert)

    def test_the_alert_DOES_say_assumed_when_nothing_was_ever_stated(self):
        """The flag must still work — otherwise the test above would pass by
        removing the parenthetical altogether."""
        turns = conversation("ಕೃಷಿ")
        alert = b.compose_followup_alert("910000000000", turns[0]["followup"],
                                         turns[0]["text"], turns[0]["known"])
        self.assertIn("Quantity: 1 (assumed — not stated)", alert)

    def test_the_transcript_marker_stops_claiming_purpose_is_awaited(self):
        """The marker is what the hourly nudge reads, so a regression here
        would make the nudge chase an answered question."""
        marker = b.flow_marker(self.turns[-1]["awaiting"])
        self.assertNotIn(b.AWAITING_PURPOSE, b.marker_awaiting(marker))

    # ── the second defect, now FIXED — this test was pinned to the old
    #    behaviour and fired the moment it changed, exactly as intended ────
    def test_the_bare_place_name_NOW_establishes_delivery(self):
        """Fix #2. The bare answer is read because the previous reply's
        transcript marker said it had asked for delivery.

        Verbatim, not transliterated: the Brain owns no place-name mapping,
        so 'ಗುಜರಾತ್' stays 'ಗುಜರಾತ್'. See the module note in
        test_bairavi_delivery_location.py.
        """
        self.assertEqual(self.turns[3]["state"]["delivery_location"], "ಗುಜರಾತ್")
        self.assertNotIn(b.AWAITING_DELIVERY, self.turns[3]["awaiting"])

    def test_without_the_delivery_context_a_bare_name_is_still_unread(self):
        """The gate, not a gazetteer: out of context it means nothing."""
        self.assertIsNone(b.parse_followup("ಗುಜರಾತ್")["delivery_location"])
        self.assertIsNone(b.parse_followup("Gujarat")["delivery_location"])

    def test_the_whole_production_sequence_now_completes(self):
        """The conversation that produced 'You mad' now asks for nothing by
        the time the place is given."""
        self.assertEqual(self.turns[3]["awaiting"], ())
        self.assertEqual(self.turns[4]["awaiting"], ())
        final = self.turns[-1]["state"]
        self.assertEqual(final["application"], "AGRICULTURE")
        self.assertEqual(final["quantity"], 1)
        self.assertEqual(final["delivery_location"], "ಗುಜರಾತ್")


# ══════════════════════════════════════════════════════════════════════════
# 2 · DELIVERY, THROUGH THE MECHANISM THAT ALREADY WORKS
# ══════════════════════════════════════════════════════════════════════════

class DeliveryUsesTheExistingMechanism(unittest.TestCase):
    """The same sequence, with a delivery shape the extractor already reads,
    so monotonicity is proven for delivery without touching extraction."""

    def setUp(self):
        self.turns = conversation("೨೪ kv", "೧ beku", "ಕೃಷಿ",
                                  "delivery to Gujarat", "rate enide")

    def test_delivery_is_established_when_stated_readably(self):
        self.assertEqual(self.turns[3]["state"]["delivery_location"],
                         "Gujarat")

    def test_purpose_and_delivery_are_BOTH_established_together(self):
        state = self.turns[3]["state"]
        self.assertEqual(state["application"], "AGRICULTURE")
        self.assertEqual(state["delivery_location"], "Gujarat")
        self.assertEqual(self.turns[3]["awaiting"], ())

    def test_nothing_is_outstanding_and_it_stays_that_way(self):
        """The following turn asks about price and mentions neither field."""
        self.assertEqual(self.turns[4]["awaiting"], ())
        self.assertEqual(self.turns[4]["state"]["application"], "AGRICULTURE")
        self.assertEqual(self.turns[4]["state"]["delivery_location"],
                         "Gujarat")

    def test_the_reply_asks_for_nothing_further(self):
        last = self.turns[-1]
        reply = b.compose_followup_reply(last["followup"], last["known"])
        self.assertNotIn(b.question_for(b.AWAITING_PURPOSE), reply)
        self.assertNotIn("ಯಾವ ಸ್ಥಳಕ್ಕೆ ಬೇಕು", reply)

    def test_the_price_question_is_still_answered_as_its_own_turn(self):
        """asked_price is a per-turn intent, NOT an established fact — it must
        not persist, or every later reply becomes a price reply."""
        self.assertTrue(self.turns[4]["followup"]["asked_price"])
        self.assertNotIn("asked_price", b._PERSISTENT_FIELDS)
        later = conversation("೨೪ kv", "rate enide", "ಕೃಷಿ")
        self.assertNotIn("asked_price", later[2]["known"])


# ══════════════════════════════════════════════════════════════════════════
# 3 · MONOTONICITY, FIELD BY FIELD
# ══════════════════════════════════════════════════════════════════════════

class EveryEstablishedFieldSurvivesAnUnrelatedMessage(unittest.TestCase):
    """One case per qualification field the module already supports. No new
    field is invented — these are exactly the keys parse/parse_followup
    already return."""

    UNRELATED = "ಸರಿ"          # "ok" — carries no qualification information

    def _survives(self, establishing, field, expected):
        turns = conversation(establishing, self.UNRELATED, self.UNRELATED)
        self.assertEqual(turns[0]["state"].get(field), expected,
                         f"{field} was not established by {establishing!r}")
        for turn in turns[1:]:
            self.assertEqual(
                turn["state"].get(field), expected,
                f"{field} was lost at {turn['text']!r}")

    def test_A_purpose_survives(self):
        self._survives("ಕೃಷಿ", "application", "AGRICULTURE")

    def test_B_capacity_survives(self):
        self._survives("100 kva beku", "capacity_kva", 100)

    def test_C_quantity_survives(self):
        self._survives("3 units beku", "quantity", 3)

    def test_D_delivery_survives(self):
        self._survives("delivery to Hubli", "delivery_location", "Hubli")

    def test_D2_a_delivery_mention_also_survives(self):
        """A mention answers the question without naming a place. It must
        persist too, or the customer is asked again."""
        self._survives("ಡೆಲಿವರಿ ಬೇಕು", "delivery_mentioned", True)

    # The expected value is read from the module's OWN table rather than
    # written as a literal, so renaming a purpose cannot leave this test
    # asserting a value the code no longer produces.
    INDUSTRY = dict(b._APPLICATIONS)["industr"]

    def test_E_an_explicit_contradiction_DOES_update_the_field(self):
        """Monotonic does not mean frozen. A new explicit value supersedes."""
        turns = conversation("ಕೃಷಿ", "actually industrial use")
        self.assertEqual(turns[0]["state"]["application"], "AGRICULTURE")
        self.assertEqual(turns[1]["state"]["application"], self.INDUSTRY)

    def test_E2_a_contradiction_does_not_disturb_other_fields(self):
        turns = conversation("100 kva 3 units ಕೃಷಿ", "actually industrial use")
        self.assertEqual(turns[1]["state"]["application"], self.INDUSTRY)
        self.assertEqual(turns[1]["state"]["capacity_kva"], 100)
        self.assertEqual(turns[1]["state"]["quantity"], 3)

    def test_E3_the_contradiction_case_uses_two_DIFFERENT_purposes(self):
        """Guards the test above: if both messages mapped to the same value
        it would pass while proving nothing about superseding."""
        self.assertNotEqual(self.INDUSTRY, "AGRICULTURE")

    def test_F_several_established_fields_survive_one_new_field(self):
        turns = conversation("100 kva beku", "3 units", "ಕೃಷಿ",
                             "delivery to Hubli")
        final = turns[-1]["state"]
        self.assertEqual(final["capacity_kva"], 100)
        self.assertEqual(final["quantity"], 3)
        self.assertEqual(final["application"], "AGRICULTURE")
        self.assertEqual(final["delivery_location"], "Hubli")
        self.assertEqual(turns[-1]["awaiting"], ())

    def test_the_fix_is_not_special_cased_to_one_field(self):
        """Guards the abstraction: a per-field branch would pass the tests
        above while leaving the next field exposed."""
        import inspect
        src = inspect.getsource(b.merged_state) + inspect.getsource(
            b.established_from_history)
        for field in b._PERSISTENT_FIELDS:
            self.assertNotIn(f'== "{field}"', src)
            self.assertNotIn(f"== '{field}'", src)


# ══════════════════════════════════════════════════════════════════════════
# 4 · LANGUAGE INDEPENDENCE
# ══════════════════════════════════════════════════════════════════════════

class FactsSurviveAcrossLanguages(unittest.TestCase):
    """The merge is language-agnostic by construction — it never inspects the
    text — but the EXTRACTORS are bilingual, so the pairs are exercised."""

    def _pair(self, first, second, field, expected):
        turns = conversation(first, second)
        self.assertEqual(turns[0]["state"].get(field), expected,
                         f"{first!r} did not establish {field}")
        self.assertEqual(turns[1]["state"].get(field), expected,
                         f"{field} lost when {second!r} followed {first!r}")

    def test_kannada_then_kannada(self):
        self._pair("ಕೃಷಿ", "ಸರಿ", "application", "AGRICULTURE")

    def test_kannada_then_english(self):
        """The production case: ಕೃಷಿ followed by a Latin-script place."""
        self._pair("ಕೃಷಿ", "Gujarat", "application", "AGRICULTURE")

    def test_english_then_kannada(self):
        self._pair("agriculture", "ಗುಜರಾತ್", "application", "AGRICULTURE")

    def test_english_then_english(self):
        self._pair("agriculture", "ok thanks", "application", "AGRICULTURE")

    def test_a_kannada_numeral_quantity_survives_an_english_message(self):
        self._pair("೧ beku", "Gujarat", "quantity", 1)

    def test_delivery_stated_in_kannada_survives_an_english_message(self):
        self._pair("ಡೆಲಿವರಿ: ಗುಜರಾತ್", "ok", "delivery_location", "ಗುಜರಾತ್")


# ══════════════════════════════════════════════════════════════════════════
# 5 · THE MERGE RULE ITSELF
# ══════════════════════════════════════════════════════════════════════════

class TheMergeRule(unittest.TestCase):

    def test_silence_never_erases(self):
        known = {"application": "AGRICULTURE", "quantity": 2}
        merged = b.merged_state(known, {"application": None, "quantity": None})
        self.assertEqual(merged["application"], "AGRICULTURE")
        self.assertEqual(merged["quantity"], 2)

    def test_false_never_erases(self):
        """delivery_mentioned is a boolean; False means 'this turn did not
        mention it', not 'it was never mentioned'."""
        merged = b.merged_state({"delivery_mentioned": True},
                                {"delivery_mentioned": False})
        self.assertIs(merged["delivery_mentioned"], True)

    def test_an_empty_string_never_erases(self):
        merged = b.merged_state({"delivery_location": "Hubli"},
                                {"delivery_location": ""})
        self.assertEqual(merged["delivery_location"], "Hubli")

    def test_an_explicit_value_supersedes(self):
        merged = b.merged_state({"application": "AGRICULTURE"},
                                {"application": "INDUSTRIAL"})
        self.assertEqual(merged["application"], "INDUSTRIAL")

    def test_it_does_not_mutate_its_input(self):
        known = {"application": "AGRICULTURE"}
        b.merged_state(known, {"application": "INDUSTRIAL"})
        self.assertEqual(known["application"], "AGRICULTURE")

    def test_it_copies_nothing_outside_the_persistent_set(self):
        """asked_price must not leak into state through the merge."""
        merged = b.merged_state({}, {"asked_price": True, "raw": "x"})
        self.assertNotIn("asked_price", merged)
        self.assertNotIn("raw", merged)

    def test_both_arguments_are_optional(self):
        self.assertEqual(b.merged_state(None), {})
        self.assertEqual(b.merged_state(None, None), {})

    def test_history_of_only_assistant_turns_establishes_nothing(self):
        hist = [{"role": "assistant", "content": "ಕೃಷಿ agriculture 100 kva"}]
        state = b.established_from_history(hist)
        self.assertIsNone(state["application"])
        self.assertIsNone(state["capacity_kva"])

    def test_empty_history_returns_every_field_as_unknown(self):
        state = b.established_from_history([])
        self.assertEqual(set(state), set(b._PERSISTENT_FIELDS))
        self.assertTrue(all(v is None for v in state.values()))

    def test_none_history_does_not_raise(self):
        self.assertTrue(all(v is None
                            for v in b.established_from_history(None).values()))

    def test_outstanding_still_works_with_no_history_at_all(self):
        """Backward compatibility: every existing caller passes only a
        followup, or a followup plus the old two-key dict."""
        self.assertEqual(b.outstanding({}), (b.AWAITING_DELIVERY,
                                             b.AWAITING_PURPOSE))
        self.assertEqual(
            b.outstanding({}, {"location": "Mysore",
                               "delivery_location": "Mysore"}),
            (b.AWAITING_PURPOSE,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
