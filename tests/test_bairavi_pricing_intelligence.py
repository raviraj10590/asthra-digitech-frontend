"""Pricing Intelligence v1, Phase A — reason about the ask, never invent a price.

THE OWNER'S RULING THIS ENCODES (D3 = A, 2026-09-20)
----------------------------------------------------
The Brain MAY collect and qualify a transformer requirement. It may NOT issue
a quotation or return a commercial price. Issuing one stays a human process
until the business decides otherwise.

WHY NO PRICE CAN BE EMITTED, AS A MATTER OF EVIDENCE
----------------------------------------------------
There is no authoritative Bairavi price source. The GTM source inventory
records "Price list or costing method" as `TBD`; contradiction C-07 rules the
₹68,244 in the design package "not a confirmed commercial price… all price,
cost, margin and discount fields stay TBD"; and §10 of the design reference is
a FORMULA — factory cost × (1 + margin) + GST — whose material rates change
daily and whose margin is a 10–18% range chosen per tender. Any number this
code produced would be an invention with a decimal point in it.

So Phase A changes WHO ACTS and WHAT IS ASKED, never what is quoted:

    PRICE_REQUEST      truthful no-price + collect what a quotation needs
    QUOTATION_REQUEST  the same, plus ONE sales signal for a human

WHAT MAKES THIS A BRAIN CHANGE RATHER THAN A CHATBOT PATCH
----------------------------------------------------------
The requirement list is READ FROM bic/goals.py — the `transformer_quotation`
goal's own required_slots — not restated here. Two lists would drift the first
time the business changed one. The goal is injected as plain data, so
bairavi.py keeps no dependency on the bic package and a BIC outage degrades to
the previous reply instead of failing.

WHAT PHASE A DELIBERATELY DOES NOT DO
-------------------------------------
No predicate is registered, no goal is admitted, no completion condition is
invented, no sufficiency gate is called, and voltage is neither asked nor
satisfied — those wait on business decisions D2, D5 and D6.

Offline: no network, no provider, no database.
"""

import inspect
import io as _io
import os
import re
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b
from _price_policy import assert_only_owner_prices, owner_price_violations  # noqa: E402                                            # noqa: E402

PHONE = "910000000000"

# The real goal definition, so these tests break if the business changes it.
from bic import goals as bic_goals                             # noqa: E402
GOAL = bic_goals.lookup(b.QUOTATION_GOAL_ID)

# A digit adjacent to a currency marker, or an Indian-grouped figure with at
# least two groups (1,00,000 — a lakh, the smallest plausible transformer
# price). The one pattern no customer-facing reply may ever match.
#
# TWO groups, not one, deliberately: `{2,60}` inside a regex literal matches
# a single-group pattern, and the source scan below reads the module's own
# string literals — where _DELIVERY_STRICT_RE's `(.{2,60})` lives. A quantifier
# is not a price, and a test that cannot tell them apart fails for the wrong
# reason.
_LOOKS_LIKE_MONEY = re.compile(
    r"₹\s*[\d,]+"
    r"|[\d,]+\s*(?:₹|rs\b|rupees|inr)"
    r"|\b\d{1,3}(?:,\d{2,3}){2,}\b",
    re.IGNORECASE)


def conversation(*messages):
    """Replay through the real history shape, as the webhook does."""
    hist, turns = [], []
    for text in messages:
        awaiting_before = b.awaiting_from_history(hist)
        known = b.established_from_history(hist)
        followup = b.parse_followup(text, awaiting_before)
        awaiting = b.outstanding(followup, known)
        state = b.merged_state(known, followup)
        turns.append({
            "text": text, "followup": followup, "known": known,
            "state": state, "awaiting": awaiting,
            "intent": followup.get("commercial_intent"),
            "reply": b.compose_followup_reply(followup, known, GOAL),
            "missing": b.missing_requirements(GOAL, state),
            "signalled_before": b.quote_already_signalled(hist),
        })
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": b.flow_marker(
            awaiting,
            quote_signalled=(turns[-1]["intent"] == b.QUOTATION_REQUEST
                             or turns[-1]["signalled_before"]))})
    return turns


# ══════════════════════════════════════════════════════════════════════════
# THE ABSOLUTE RULE
# ══════════════════════════════════════════════════════════════════════════

class NoReplyMayEverContainAPrice(unittest.TestCase):

    ASKS = ("price?", "rate ಎಷ್ಟು?", "24 kVA price?", "quotation ಬೇಕು",
            "price list ಕಳುಹಿಸಿ", "ಒಂದು transformer ಎಷ್ಟು?", "cost?",
            "100 kva 2 units delivery to Hubli rate enide")

    def test_no_customer_reply_contains_money_other_than_list_prices(self):
        for ask in self.ASKS:
            reply = conversation(ask)[0]["reply"]
            assert_only_owner_prices(self, reply, ask)

    def test_no_reply_contains_the_design_package_figure(self):
        for ask in self.ASKS:
            reply = conversation(ask)[0]["reply"]
            for forbidden in ("68,244", "68244"):
                self.assertNotIn(forbidden, reply, ask)

    def test_no_costing_vocabulary_reaches_the_customer(self):
        """margin and material rates are the inputs to the formula that must
        never be run. "+ GST" is allowed since 2026-09-24 — it is how the
        owner states his list prices — but never a GST rate or a total."""
        for ask in self.ASKS:
            low = conversation(ask)[0]["reply"].lower()
            for word in ("margin", "per kg", "₹/kg", "factory cost", "18%", "gst included"):
                self.assertNotIn(word, low, ask)

    def test_no_reply_claims_a_quotation_WAS_generated(self):
        for ask in self.ASKS:
            low = conversation(ask)[0]["reply"].lower()
            for claim in ("quotation attached", "here is your quotation",
                          "quotation generated", "quotation ready"):
                self.assertNotIn(claim, low, ask)

    def test_the_module_emits_no_price_source_of_its_own(self):
        """No table, no formula, no constant. Asserted over string literals,
        where such a thing would live."""
        import ast
        tree = ast.parse(inspect.getsource(b))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef,
                                        ast.FunctionDef))
                      and getattr(n, "body", None)
                      and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant)
                      and isinstance(n.body[0].value.value, str)}
        literals = "\n".join(
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings)
        self.assertNotIn("68244", literals)
        self.assertNotIn("68,244", literals)
        self.assertIsNone(_LOOKS_LIKE_MONEY.search(literals))


# ══════════════════════════════════════════════════════════════════════════
# THE TEST MATRIX · A–L
# ══════════════════════════════════════════════════════════════════════════

class TheMatrix(unittest.TestCase):

    def test_A_price_with_no_product_known(self):
        t = conversation("price?")[0]
        self.assertEqual(t["intent"], b.PRICE_REQUEST)
        self.assertIn(b.AWAITING_CAPACITY, t["missing"])
        self.assertIn(b.question_for(b.AWAITING_CAPACITY), t["reply"])

    def test_B_capacity_known_so_capacity_is_not_re_asked(self):
        t = conversation("24 kVA price?")[0]
        self.assertEqual(t["state"]["capacity_kva"], 24)
        self.assertNotIn(b.AWAITING_CAPACITY, t["missing"])
        self.assertNotIn(b.question_for(b.AWAITING_CAPACITY), t["reply"])
        self.assertIn(b.AWAITING_QUANTITY, t["missing"])

    def test_C_capacity_and_quantity_known(self):
        t = conversation("24 kVA 1 ಬೇಕು price?")[0]
        self.assertEqual(t["state"]["capacity_kva"], 24)
        self.assertEqual(t["state"]["quantity"], 1)
        self.assertEqual(t["missing"], (b.AWAITING_DELIVERY,))

    def test_D_price_after_purpose_and_capacity_established(self):
        turns = conversation("100 kva ಕೃಷಿ", "rate ಎಷ್ಟು?")
        t = turns[1]
        self.assertEqual(t["state"]["application"], "AGRICULTURE")
        self.assertEqual(t["state"]["capacity_kva"], 100)
        self.assertNotIn(b.AWAITING_CAPACITY, t["missing"])
        self.assertNotIn(b.question_for(b.AWAITING_PURPOSE), t["reply"])

    def test_E_price_after_delivery_established(self):
        turns = conversation("100 kva 2 units ಕೃಷಿ delivery to Hubli",
                             "rate enide")
        t = turns[1]
        self.assertEqual(t["missing"], ())
        self.assertNotIn("ಇಷ್ಟು ತಿಳಿಸಿದರೆ ಸಾಕು", t["reply"])
        self.assertNotIn("ಇನ್ನೊಂದು ವಿಷಯ ತಿಳಿಸಿ", t["reply"])

    def test_F_quotation_request(self):
        t = conversation("quotation ಬೇಕು")[0]
        self.assertEqual(t["intent"], b.QUOTATION_REQUEST)
        self.assertIn("ವಿನಂತಿ", t["reply"])       # a REQUEST, not a quotation

    def test_G_a_repeated_request_raises_no_second_signal(self):
        turns = conversation("quotation ಬೇಕು", "quotation ಬೇಕು")
        self.assertFalse(turns[0]["signalled_before"])
        self.assertTrue(turns[1]["signalled_before"])

    def test_H_intent_does_NOT_survive_an_unrelated_turn(self):
        turns = conversation("rate ಎಷ್ಟು?", "ಕೃಷಿ")
        self.assertEqual(turns[0]["intent"], b.PRICE_REQUEST)
        self.assertIsNone(turns[1]["intent"])
        self.assertNotIn("ದರದ ಬಗ್ಗೆ", turns[1]["reply"])

    def test_I_no_stale_price_can_be_used_because_none_is_stored(self):
        """Case I in the matrix degenerates: with no price source there is no
        stale price either. Asserted so it cannot quietly appear."""
        self.assertNotIn("price", {s["name"] for s in GOAL["required_slots"]})
        self.assertFalse(any("price" in s["predicate"]
                             for s in GOAL["required_slots"]))

    def test_J_a_price_question_gets_the_list_prices(self):
        t = conversation("price?")[0]
        self.assertIn("+ GST", t["reply"])
        assert_only_owner_prices(self, t["reply"])

    def test_K_a_bare_commercial_word_is_still_an_intent(self):
        """One word, no sentence, no capacity — still a price question."""
        for text, expected in (("price", b.PRICE_REQUEST),
                               ("ದರ", b.PRICE_REQUEST),
                               ("quote", b.QUOTATION_REQUEST)):
            t = conversation(text)[0]
            self.assertEqual(t["intent"], expected, text)
            self.assertTrue(t["reply"])

    def test_K2_an_ambiguous_message_gets_NO_commercial_intent(self):
        """"???" carries no commercial word. Inventing an intent for it would
        put a sales signal behind a shrug — the reply still has to work."""
        for text in ("???", "...", "👍", "ok"):
            t = conversation(text)[0]
            self.assertIsNone(t["intent"], text)
            self.assertTrue(t["reply"], text)
            self.assertNotIn("ದರದ ಬಗ್ಗೆ", t["reply"], text)

    def test_L_kannada_and_english_mixed(self):
        for text, expected in (
                ("rate ಎಷ್ಟು?", b.PRICE_REQUEST),
                ("ಬೆಲೆ ಎಷ್ಟು", b.PRICE_REQUEST),
                ("price ಎಷ್ಟು", b.PRICE_REQUEST),
                ("ಕೋಟೇಶನ್ ಬೇಕು", b.QUOTATION_REQUEST),
                ("quotation ಕೊಡಿ", b.QUOTATION_REQUEST)):
            self.assertEqual(b.commercial_intent(text), expected, text)


# ══════════════════════════════════════════════════════════════════════════
# INTENT: TWO ASKS, NOT ONE
# ══════════════════════════════════════════════════════════════════════════

class PriceAndQuotationAreDifferentActs(unittest.TestCase):

    def test_quotation_outranks_price_when_both_appear(self):
        """The stronger act decides — the reverse would downgrade a sales
        signal to a price answer."""
        self.assertEqual(b.commercial_intent("quotation ಬೇಕು, rate ಎಷ್ಟು?"),
                         b.QUOTATION_REQUEST)

    def test_a_non_commercial_message_has_no_intent(self):
        for text in ("ಕೃಷಿ", "Gujarat", "100 kva", "ok", ""):
            self.assertIsNone(b.commercial_intent(text), text)

    def test_asked_price_keeps_its_original_meaning(self):
        """Existing readers depend on it: 'did they raise money at all'."""
        for text in ("rate?", "quotation ಬೇಕು"):
            self.assertTrue(b.parse_followup(text)["asked_price"], text)
        self.assertFalse(b.parse_followup("ಕೃಷಿ")["asked_price"])

    def test_only_a_quotation_request_gets_the_request_recorded_line(self):
        self.assertIn("ವಿನಂತಿ", conversation("quotation ಬೇಕು")[0]["reply"])
        self.assertNotIn("ವಿನಂತಿ", conversation("rate?")[0]["reply"])


# ══════════════════════════════════════════════════════════════════════════
# COMMERCIAL INTENT IS PER-TURN, NEVER STATE
# ══════════════════════════════════════════════════════════════════════════

class IntentMustNotBecomePersistentState(unittest.TestCase):

    def test_it_is_not_a_persistent_field(self):
        self.assertNotIn("commercial_intent", b._PERSISTENT_FIELDS)

    def test_the_merge_never_carries_it(self):
        merged = b.merged_state({}, {"commercial_intent": b.PRICE_REQUEST})
        self.assertNotIn("commercial_intent", merged)

    def test_history_replay_never_establishes_it(self):
        state = b.established_from_history(
            [{"role": "user", "content": "rate ಎಷ್ಟು?"}])
        self.assertNotIn("commercial_intent", state)

    def test_three_unrelated_turns_after_a_price_ask_stay_unrelated(self):
        turns = conversation("rate?", "ಕೃಷಿ", "100 kva", "ok")
        for t in turns[1:]:
            self.assertIsNone(t["intent"], t["text"])
            self.assertNotIn("ದರದ ಬಗ್ಗೆ", t["reply"], t["text"])


# ══════════════════════════════════════════════════════════════════════════
# ESTABLISHED FACTS SURVIVE A PRICE TURN
# ══════════════════════════════════════════════════════════════════════════

class APriceAskErasesNothing(unittest.TestCase):

    def test_every_established_fact_survives(self):
        turns = conversation("100 kva 3 units ಕೃಷಿ delivery to Hubli",
                             "rate ಎಷ್ಟು?", "quotation ಬೇಕು")
        for t in turns[1:]:
            self.assertEqual(t["state"]["capacity_kva"], 100, t["text"])
            self.assertEqual(t["state"]["quantity"], 3, t["text"])
            self.assertEqual(t["state"]["application"], "AGRICULTURE", t["text"])
            self.assertEqual(t["state"]["delivery_location"], "Hubli", t["text"])

    def test_nothing_established_is_ever_asked_again(self):
        turns = conversation("100 kva 3 units delivery to Hubli", "rate?")
        reply = turns[1]["reply"]
        for ask in (b.AWAITING_CAPACITY, b.AWAITING_QUANTITY,
                    b.AWAITING_DELIVERY):
            self.assertNotIn(b.question_for(ask), reply, ask)

    def test_the_delivery_context_still_works_after_a_price_turn(self):
        """Fix #2 must survive: a bare place name is still readable when the
        previous reply asked for delivery."""
        turns = conversation("100 kva 1 unit", "rate?", "ಗುಜರಾತ್")
        self.assertIn(b.AWAITING_DELIVERY, turns[1]["awaiting"])
        self.assertEqual(turns[2]["state"]["delivery_location"], "ಗುಜರಾತ್")


# ══════════════════════════════════════════════════════════════════════════
# CAPACITY: 25 kVA vs AN UNSUPPORTED 24 kVA
# ══════════════════════════════════════════════════════════════════════════

class CapacityFollowsTheExistingSkuRules(unittest.TestCase):

    def test_the_supported_ratings_are_kVA_and_unchanged(self):
        self.assertEqual(b.CATALOGUE_KVA, (25, 63, 100, 250))
        self.assertEqual(b.PLANNED_KVA, (500,))

    def test_24_is_NEVER_rounded_to_25(self):
        """The owner's correction, asserted. A silently promoted capacity is
        a transformer that cannot be delivered."""
        self.assertEqual(b.capacity_kva("24 kVA"), 24)
        self.assertNotEqual(b.capacity_kva("24 kVA"), 25)
        t = conversation("24 kVA price?")[0]
        self.assertEqual(t["state"]["capacity_kva"], 24)

    def test_an_unsupported_capacity_is_VERIFY_not_supported(self):
        self.assertEqual(b.sku_status(24), b.VERIFY)
        self.assertEqual(b.sku_status(25), b.SUPPORTED)
        self.assertEqual(b.sku_status(500), b.ROADMAP)

    def test_24_is_established_so_it_is_not_re_asked(self):
        """VERIFY means 'a human confirms it', not 'we did not hear you'."""
        t = conversation("24 kVA price?")[0]
        self.assertNotIn(b.AWAITING_CAPACITY, t["missing"])

    def test_the_customer_is_never_told_an_unsupported_rating_is_available(self):
        reply = conversation("24 kVA price?")[0]["reply"]
        self.assertNotIn("24 kVA ಲಭ್ಯ", reply)
        self.assertNotIn("in stock", reply.lower())

    def test_the_capacity_question_shows_the_manufactured_range(self):
        q = b.question_for(b.AWAITING_CAPACITY)
        for kva in b.CATALOGUE_KVA:
            self.assertIn(str(kva), q)
        self.assertIn("kVA", q)


# ══════════════════════════════════════════════════════════════════════════
# THE REQUIREMENT LIST COMES FROM THE GOAL
# ══════════════════════════════════════════════════════════════════════════

class RequirementsAreReadFromTheBrainsGoalRegistry(unittest.TestCase):

    def test_the_goal_is_the_real_registered_one(self):
        self.assertEqual(GOAL["goal_id"], "transformer_quotation")
        self.assertEqual(GOAL["risk_tier"], 4)

    def test_the_asks_follow_the_goals_slot_order(self):
        self.assertEqual(b.requirement_asks(GOAL),
                         (b.AWAITING_CAPACITY, b.AWAITING_QUANTITY,
                          b.AWAITING_DELIVERY))

    def test_no_second_requirement_list_is_hardcoded(self):
        """A restated list would drift from the goal the first time the
        business changed one. Only the slot→ask MAPPING lives here."""
        self.assertEqual(
            set(b._SLOT_TO_ASK),
            {s["name"] for s in GOAL["required_slots"]}
            - set(b.unaskable_slots(GOAL)))

    def test_a_goal_with_no_slots_asks_nothing_and_does_not_raise(self):
        self.assertEqual(b.requirement_asks({}), ())
        self.assertEqual(b.requirement_asks(None), ())
        self.assertEqual(b.missing_requirements(None, {}), ())

    def test_the_reply_degrades_safely_with_no_goal(self):
        """A BIC outage must not break a customer reply."""
        followup = b.parse_followup("rate?")
        reply = b.compose_followup_reply(followup, {}, None)
        self.assertIn("+ GST", reply)

    def test_missing_requirements_reads_MERGED_state(self):
        self.assertEqual(
            b.missing_requirements(GOAL, {"capacity_kva": 100, "quantity": 2,
                                          "delivery_location": "Hubli"}), ())
        self.assertEqual(b.missing_requirements(GOAL, {}),
                         (b.AWAITING_CAPACITY, b.AWAITING_QUANTITY,
                          b.AWAITING_DELIVERY))

    def test_delivery_is_satisfied_by_the_same_signals_as_outstanding(self):
        for key in ("delivery_location", "delivery_same", "delivery_mentioned"):
            state = {"capacity_kva": 1, "quantity": 1, key: True}
            self.assertEqual(b.missing_requirements(GOAL, state), (), key)


# ══════════════════════════════════════════════════════════════════════════
# VOLTAGE — UNDECIDED, AND VISIBLY SO
# ══════════════════════════════════════════════════════════════════════════

class VoltageIsNeitherAskedNorSatisfied(unittest.TestCase):
    """The goal requires it; the product knowledge base calls it a SKU
    attribute. Business decision D6 is open, so this module does neither."""

    def test_the_goal_does_require_voltage(self):
        self.assertIn("voltage", {s["name"] for s in GOAL["required_slots"]})

    def test_it_is_reported_as_unaskable(self):
        self.assertEqual(b.unaskable_slots(GOAL), ("voltage",))

    def test_the_customer_is_never_asked_for_it(self):
        for ask in b.requirement_asks(GOAL):
            self.assertNotIn("voltage", b.question_for(ask).lower())
        for text in ("price?", "quotation ಬೇಕು", "24 kVA price?"):
            low = conversation(text)[0]["reply"].lower()
            self.assertNotIn("voltage", low, text)
            self.assertNotIn("ವೋಲ್ಟೇಜ್", conversation(text)[0]["reply"], text)

    def test_no_voltage_extractor_was_added(self):
        self.assertNotIn("voltage", b.parse_followup("11 kV / 433 V"))

    def test_the_owner_signal_DISCLOSES_the_gap(self):
        """Silently short of a required slot would look answered."""
        t = conversation("quotation ಬೇಕು")[0]
        signal = b.compose_quotation_signal(PHONE, t["followup"], t["text"],
                                            t["known"], GOAL)
        self.assertIn("voltage", signal)
        self.assertIn("NOT asked", signal)


# ══════════════════════════════════════════════════════════════════════════
# THE SALES SIGNAL
# ══════════════════════════════════════════════════════════════════════════

class TheQuotationSignalAsksAHumanToAct(unittest.TestCase):

    def _signal(self, *messages):
        t = conversation(*messages)[-1]
        return b.compose_quotation_signal(PHONE, t["followup"], t["text"],
                                          t["known"], GOAL)

    def test_it_never_contains_a_price(self):
        s = self._signal("100 kva 2 units delivery to Hubli quotation ಬೇಕು")
        self.assertIsNone(_LOOKS_LIKE_MONEY.search(s))
        self.assertNotIn("₹", s)

    def test_it_never_claims_a_quotation_was_generated(self):
        s = self._signal("quotation ಬೇಕು")
        self.assertIn("no quotation has been generated", s)

    def test_it_names_what_is_still_missing(self):
        s = self._signal("quotation ಬೇಕು")
        self.assertIn("Still missing", s)
        self.assertIn(b.AWAITING_CAPACITY, s)

    def test_it_says_so_when_nothing_is_missing(self):
        s = self._signal("100 kva 2 units delivery to Hubli quotation ಬೇಕು")
        self.assertIn("Every requirement this bot can collect", s)

    def test_it_carries_the_SKU_STATUS_so_24_is_not_worked_as_25(self):
        s = self._signal("24 kVA 1 unit delivery to Hubli quotation ಬೇಕು")
        self.assertIn("SKU status: VERIFY", s)
        self.assertIn("not a currently manufactured rating", s)

    def test_a_supported_rating_carries_no_confirmation_warning(self):
        s = self._signal("100 kva 1 unit delivery to Hubli quotation ಬೇಕು")
        self.assertIn("SKU status: SUPPORTED_PRODUCT", s)
        self.assertNotIn("not a currently manufactured rating", s)

    def test_an_assumed_quantity_is_labelled(self):
        s = self._signal("100 kva delivery to Hubli quotation ಬೇಕು")
        self.assertIn("assumed — not stated", s)

    def test_a_stated_quantity_is_not_labelled_assumed(self):
        s = self._signal("100 kva 4 units delivery to Hubli quotation ಬೇಕು")
        self.assertIn("Quantity: 4", s)
        self.assertNotIn("assumed", s)

    def test_it_carries_the_customers_own_words(self):
        s = self._signal("quotation ಬೇಕು")
        self.assertIn("quotation ಬೇಕು", s)

    def test_dedup_is_read_from_the_transcript_not_a_new_store(self):
        hist = [{"role": "assistant",
                 "content": b.flow_marker((), quote_signalled=True)}]
        self.assertTrue(b.quote_already_signalled(hist))
        self.assertFalse(b.quote_already_signalled(
            [{"role": "assistant", "content": b.flow_marker(())}]))

    def test_a_customer_cannot_forge_the_dedup_flag(self):
        hist = [{"role": "user",
                 "content": b.flow_marker((), quote_signalled=True)}]
        self.assertFalse(b.quote_already_signalled(hist))

    def test_the_marker_still_round_trips_awaiting_alongside_the_flag(self):
        m = b.flow_marker((b.AWAITING_DELIVERY,), quote_signalled=True)
        self.assertEqual(b.marker_awaiting(m), (b.AWAITING_DELIVERY,))
        self.assertTrue(b.quote_already_signalled(
            [{"role": "assistant", "content": m}]))

    def test_the_marker_round_trips_the_NEW_asks_too(self):
        """capacity and quantity are new awaiting values. If marker_awaiting
        does not accept them, the hourly nudge silently forgets what the
        reply asked for."""
        for ask in (b.AWAITING_CAPACITY, b.AWAITING_QUANTITY):
            m = b.flow_marker((ask,))
            self.assertEqual(b.marker_awaiting(m), (ask,), ask)
        m = b.flow_marker((b.AWAITING_CAPACITY, b.AWAITING_QUANTITY,
                           b.AWAITING_DELIVERY))
        self.assertEqual(b.marker_awaiting(m),
                         (b.AWAITING_CAPACITY, b.AWAITING_QUANTITY,
                          b.AWAITING_DELIVERY))

    def test_the_marker_is_still_recognised_as_the_bairavi_flow(self):
        m = b.flow_marker((b.AWAITING_CAPACITY,), quote_signalled=True)
        self.assertTrue(b.in_transformer_flow(
            [{"role": "assistant", "content": m}]))


# ══════════════════════════════════════════════════════════════════════════
# PHASE B WAS NOT IMPLEMENTED
# ══════════════════════════════════════════════════════════════════════════

class TheWebhookRaisesTheSignalCorrectly(unittest.TestCase):
    """Nothing else in this file exercises api/webhook.py, so a call site that
    fired the sales signal for every price question — or never fired it, or
    lost its dedup — would leave every test above green while the owner
    drowned in alerts or saw none."""

    def _webhook_tree(self):
        import ast
        src = _io.open(os.path.join(os.path.dirname(__file__), "..",
                                    "api", "webhook.py"),
                       encoding="utf-8").read()
        return ast.parse(src), src

    def _signal_calls(self):
        import ast
        tree, _ = self._webhook_tree()
        return [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "compose_quotation_signal"]

    def test_the_signal_is_composed_exactly_once(self):
        self.assertEqual(len(self._signal_calls()), 1)

    def test_it_is_guarded_by_the_quote_now_flag(self):
        import ast
        tree, _ = self._webhook_tree()
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if not (isinstance(node.test, ast.Name)
                    and node.test.id == "_quote_now"):
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if "compose_quotation_signal" in body:
                guarded = True
        self.assertTrue(guarded,
                        "the sales signal is not guarded by _quote_now")

    def test_the_flag_requires_a_QUOTATION_request(self):
        """A PRICE question must not raise a sales task — it is already
        carried by the follow-up alert's 'Asked for price: YES' line."""
        import ast
        tree, _ = self._webhook_tree()
        assigns = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "_quote_now"
                           for t in n.targets)]
        self.assertEqual(len(assigns), 1)
        src = ast.dump(assigns[0])
        self.assertIn("QUOTATION_REQUEST", src)
        self.assertNotIn("PRICE_REQUEST", src)

    def test_the_flag_also_requires_that_no_signal_went_out_before(self):
        import ast
        tree, _ = self._webhook_tree()
        assigns = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "_quote_now"
                           for t in n.targets)]
        src = ast.dump(assigns[0])
        self.assertIn("quote_already_signalled", src)
        self.assertIn("UnaryOp", src)        # the `not`

    def test_the_transcript_records_the_flag_so_dedup_survives_a_restart(self):
        import ast
        tree, _ = self._webhook_tree()
        markers = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "flow_marker"
                   and any(k.arg == "quote_signalled" for k in n.keywords)]
        self.assertTrue(markers,
                        "flow_marker is never called with quote_signalled, "
                        "so the dedup flag is never persisted")

    def test_the_goal_is_injected_into_the_reply(self):
        import ast
        tree, _ = self._webhook_tree()
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "compose_followup_reply"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 4,
                         "the goal definition is not passed to the reply")
        # ARG 3 IS THE GOAL, ARG 4 THE PREVIOUS REPLY'S FINGERPRINT. Both are
        # asserted at the call site because a mutation that drops either one
        # changes nothing any unit test of bairavi.py can see -- the reply
        # composes fine without them, it is simply worse.
        self.assertEqual(calls[0].args[2].id, "_quote_goal")
        self.assertEqual(calls[0].args[3].func.attr, "last_reply_fingerprint")


class PhaseBIsAbsent(unittest.TestCase):

    def _code(self):
        out = []
        for tok in tokenize.generate_tokens(
                _io.StringIO(inspect.getsource(b)).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
        return " ".join(out)

    def test_bairavi_still_imports_no_bic_package(self):
        """The goal arrives as injected data. A direct import would couple the
        vertical to the Brain package and break offline purity."""
        code = self._code()
        self.assertNotIn("import bic", code)
        self.assertNotIn("from bic", code)

    def test_no_sufficiency_gate_is_called_from_the_vertical(self):
        code = self._code()
        for token in ("assemble", "PROCEED", "CLARIFY", "ESCALATE", "REFUSE"):
            self.assertNotIn(token, code, token)

    def test_no_predicate_is_registered_by_this_change(self):
        import subprocess
        root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run(["git", "status", "--porcelain",
                              "supabase/migrations"],
                             cwd=root, capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "", "a migration was added")

    def test_no_completion_condition_was_invented(self):
        self.assertNotIn("completion", GOAL)

    def test_the_goals_risk_tier_was_not_lowered(self):
        """D3=A keeps issuance human. Lowering tier 4 would be implementing
        D3=B by the back door."""
        self.assertEqual(GOAL["risk_tier"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
# THE WORDS CUSTOMERS ACTUALLY USE FOR MONEY  (added 2026-09-22)
# ══════════════════════════════════════════════════════════════════════════

class TheVocabularyCoversHowPeopleAsk(unittest.TestCase):
    """On 2026-09-21 a customer asked for the "Amount" and it was not read as
    a price question at all.

    "ಎಷ್ಟು" was already in the table but does not cover "ಎಷ್ಟಾಗುತ್ತೆ": the two
    diverge after "ಟ", so the substring test never matched the form people
    actually type.
    """

    def test_amount_is_a_price_question(self):
        for text in ("Amount?", "what is the amount", "amount sir",
                     "ಮೊತ್ತ ಎಷ್ಟು"):
            with self.subTest(text=text):
                self.assertTrue(b.parse_followup(text)["asked_price"], text)

    def test_how_much_is_a_price_question(self):
        for text in ("how much", "How much sir?", "howmuch"):
            with self.subTest(text=text):
                self.assertTrue(b.parse_followup(text)["asked_price"], text)

    def test_hindi_kitna_is_a_price_question(self):
        for text in ("kitna hai", "kitne rupees"):
            with self.subTest(text=text):
                self.assertTrue(b.parse_followup(text)["asked_price"], text)

    def test_the_kannada_forms_are_price_questions(self):
        for text in ("ಎಷ್ಟಾಗುತ್ತೆ?", "ಎಷ್ಟಾಗುತ್ತದೆ", "ಎಷ್ಟು ರೂ ಆಗುತ್ತದೆ"):
            with self.subTest(text=text):
                self.assertTrue(b.parse_followup(text)["asked_price"], text)

    def test_these_are_a_price_ask_not_a_quotation_request(self):
        """A price question wants a number; a quotation request starts a
        document. The distinction drives the owner signal, so the new terms
        must land on the right side of it."""
        for text in ("Amount?", "how much", "ಎಷ್ಟಾಗುತ್ತೆ"):
            with self.subTest(text=text):
                self.assertEqual(b.commercial_intent(text), b.PRICE_REQUEST)

    def test_no_price_figure_is_ever_produced(self):
        """The reason the vocabulary can be widened safely: recognising the
        question changes only which answer is given, and that answer still
        contains no number."""
        reply = b.compose_followup_reply(b.parse_followup("Amount?"), {})
        assert_only_owner_prices(self, reply)
        for token in ("68,244", "68244"):
            self.assertNotIn(token, reply)

    def test_a_qualification_answer_is_not_a_price_question(self):
        for text in ("agriculture", "kushtagi", "2 units", "Kadaba near tumkur",
                     "ತುಮಕೂರು ಜಿಲ್ಲೆ ಗುಬ್ಬಿ ತಾಲ್ಲೂಕು", "Mount Road Chennai"):
            with self.subTest(text=text):
                self.assertFalse(b.parse_followup(text)["asked_price"], text)

    def test_an_address_still_reads_after_the_vocabulary_grew(self):
        """A price word anywhere in the text disqualifies it as an address, so
        widening the table could have cost real addresses. It did not."""
        asked = (b.AWAITING_DELIVERY,)
        for text in ("kushtagi", "Kadaba near tumkur", "Mount Road Chennai",
                     "ತುಮಕೂರು ಜಿಲ್ಲೆ ಗುಬ್ಬಿ ತಾಲ್ಲೂಕು"):
            with self.subTest(text=text):
                self.assertEqual(
                    b.parse_followup(text, awaiting=asked)["delivery_location"],
                    text)

    def test_the_substring_collision_is_known_and_accepted(self):
        """DOCUMENTED, not desirable. _PRICE_ASK is matched as a substring on
        purpose -- that is what makes "pricing" match "price" -- so a place
        name containing one of these words reads as a price question. No
        Indian place name is known to collide, and missing every real
        "Amount?" is the worse trade. Recorded here so the behaviour is not
        rediscovered as a surprise."""
        self.assertTrue(b.parse_followup("Amount Road")["asked_price"])
        # The upside of the same rule: plurals and inflections come free.
        self.assertTrue(b.parse_followup("prices")["asked_price"])
        self.assertTrue(b.parse_followup("rates")["asked_price"])
        # And the limit of it: "pricing" does NOT contain "price".
        self.assertFalse(b.parse_followup("pricing")["asked_price"])
