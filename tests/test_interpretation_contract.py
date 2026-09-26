"""Step 1 — the interpretation contract and its validator (2026-09-25).

No LLM is called. `from_parse` stands in for a future interpreter; `validate`
is the Brain's gate. The acceptance bar: for every message the test-suite
already feeds parse_followup, under every awaiting state,

    validate(from_parse(parse_followup(x))) == parse_followup(x)

except for the DOCUMENTED divergences below, each of which is deliberate.
"""
import ast
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402
import interpretation as I  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
AWAITINGS = [(), (b.AWAITING_DELIVERY,), (b.AWAITING_PURPOSE,), (b.AWAITING_QUANTITY,),
             (b.AWAITING_CALLBACK,), (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE)]
KNOWNS = [{}, {"location": "Sira", "capacity_kva": 63, "name": "R"},
          {"location": "Sira", "capacity_kva": 25, "application": "AGRICULTURE",
           "delivery_same": True}]
AUDIT_MESSAGES = ("Hii namaste", "Krushi", "Krusshi", "ಕೃಷಿ", "63 kVA", "2",
                  "delivery yavaga", "Ayitu delivery yavaga kodtira", "Nijanna?",
                  "Hirekerur", "ತಕ್ಷಣ", "actually 100 kVA beku")

# (key, message) -> why the validator deliberately differs from today's parser.
DOCUMENTED_DIVERGENCE = {
    ("quantity", "1"): "a bare number answering WHERE is ambiguous, not a quantity",
    ("quantity", "2"): "a bare number answering WHERE is ambiguous, not a quantity",
    ("delivery_location", "Ayitu delivery yavaga kodtira"): "a delivery-TIME question is not a place",
    ("delivery_location", "delivery yavaga"): "a delivery-TIME question is not a place",
    ("customer_question", "nanna hesaru gotta"): "their_name is not in the closed question list",
}


def corpus():
    msgs = set(AUDIT_MESSAGES)
    for f in glob.glob(os.path.join(ROOT, "tests", "*.py")):
        for m in re.finditer(r'parse_followup\(\s*"((?:[^"\\]|\\.)*)"', open(f).read()):
            msgs.add(m.group(1))
    msgs |= {"ok", "kk", "rate?", "quotation beku", "warranty ide?", "CALL", "1",
             "3 units for industry", "mescom approval?", "who are you?", "nanna hesaru gotta"}
    return sorted(msgs)


def roundtrip(text, awaiting=(), known=None):
    known = known or {}
    parsed = b.parse_followup(text, awaiting, known=known)
    return parsed, I.validate(I.from_parse(parsed, text, known), text, awaiting, known)


# ══════════════════════════════════════════════════════════════════════════
# THE ACCEPTANCE BAR
# ══════════════════════════════════════════════════════════════════════════

class CompatibilityWithTheExistingParser(unittest.TestCase):

    def test_the_round_trip_equals_the_parser_except_where_documented(self):
        seen, cases = set(), 0
        for text in corpus():
            for awaiting in AWAITINGS:
                for known in KNOWNS:
                    cases += 1
                    parsed, v = roundtrip(text, awaiting, known)
                    view = I.state_view(v)
                    self.assertEqual(set(view), set(parsed), text)
                    for key in parsed:
                        if parsed[key] != view[key]:
                            self.assertIn((key, text), DOCUMENTED_DIVERGENCE,
                                          f"undocumented divergence: {key} for {text!r} "
                                          f"awaiting={awaiting} parser={parsed[key]!r} "
                                          f"validator={view[key]!r}")
                            seen.add((key, text))
        self.assertGreater(cases, 1500)
        # every documented divergence is real — none is stale
        self.assertEqual(seen, set(DOCUMENTED_DIVERGENCE))

    def test_the_output_has_exactly_the_parsers_keys(self):
        parsed, v = roundtrip("63 kVA 2 units agriculture")
        self.assertEqual(set(I.state_view(v)), set(parsed))
        self.assertEqual(set(v) - set(parsed), {"_rejected", "_ambiguous"})


# ══════════════════════════════════════════════════════════════════════════
# THE AUDIT MESSAGES
# ══════════════════════════════════════════════════════════════════════════

def interp(intent="answer", questions=(), correction=False, ambiguous=False, **fields):
    return {"intent": intent, "questions": list(questions), "is_correction": correction,
            "ambiguous": ambiguous,
            "fields": {k: {"value": v[0], "evidence": v[1]} for k, v in fields.items()}}


class TheAuditMessages(unittest.TestCase):
    def test_greeting(self):
        _, v = roundtrip("Hii namaste")
        self.assertTrue(v["is_greeting"] and v["is_ack"])

    def test_krushi_in_every_script(self):
        for t in ("Krushi", "Krusshi", "ಕೃಷಿ"):
            _, v = roundtrip(t, (b.AWAITING_PURPOSE,))
            self.assertEqual(v["application"], "AGRICULTURE", t)

    def test_capacity(self):
        _, v = roundtrip("63 kVA")
        self.assertEqual(v["capacity_kva"], 63)

    def test_delivery_time_questions_are_questions_not_places(self):
        for t in ("delivery yavaga", "Ayitu delivery yavaga kodtira"):
            _, v = roundtrip(t, (b.AWAITING_DELIVERY,))
            self.assertEqual(v["customer_question"], b.QUESTION_DELIVERY_TIME, t)
            self.assertIsNone(v["delivery_location"], t)

    def test_nijanna_is_an_open_question(self):
        _, v = roundtrip("Nijanna?")
        self.assertEqual(v["customer_question"], b.QUESTION_UNANSWERED)

    def test_hirekerur_is_a_place_when_asked_where(self):
        _, v = roundtrip("Hirekerur", (b.AWAITING_DELIVERY,))
        self.assertEqual(v["delivery_location"], "Hirekerur")

    def test_hirekerur_is_not_a_place_when_nobody_asked(self):
        v = I.validate(interp(delivery_place=("Hirekerur", "Hirekerur")), "Hirekerur", ())
        self.assertIsNone(v["delivery_location"])
        self.assertIn(("delivery_place", I.R_CONTEXT), v["_rejected"])

    def test_takshana_is_never_a_place(self):
        v = I.validate(interp(delivery_place=("ತಕ್ಷಣ", "ತಕ್ಷಣ")), "ತಕ್ಷಣ", (b.AWAITING_DELIVERY,))
        self.assertIsNone(v["delivery_location"])

    def test_other_non_places_are_rejected_by_the_existing_rules(self):
        for t in ("urgent", "soon", "later", "call me", "immediately", "asap"):
            v = I.validate(interp(delivery_place=(t, t)), t, (b.AWAITING_DELIVERY,))
            self.assertIsNone(v["delivery_location"], t)

    def test_actually_100_kva_is_a_correction(self):
        known = {"capacity_kva": 63, "quantity": 2}
        parsed, v = roundtrip("actually 100 kVA beku", (), known)
        self.assertEqual(v["capacity_kva"], 100)
        merged = b.merged_state(known, I.state_view(v))
        self.assertEqual((merged["capacity_kva"], merged["quantity"]), (100, 2))


# ══════════════════════════════════════════════════════════════════════════
# CONTEXTUAL "2"
# ══════════════════════════════════════════════════════════════════════════

class TheContextualTwo(unittest.TestCase):
    PROPOSED = interp(quantity=(2, "2"))

    def test_awaiting_quantity_it_is_a_quantity(self):
        v = I.validate(self.PROPOSED, "2", (b.AWAITING_QUANTITY,))
        self.assertEqual(v["quantity"], 2)

    def test_awaiting_callback_it_is_the_callback_choice(self):
        parsed, v = roundtrip("2", (b.AWAITING_CALLBACK,), {})
        self.assertEqual(v["callback"], b.CALLBACK_EVENING)
        self.assertIsNone(v["quantity"])
        # and an interpreter that calls it a quantity is overruled
        v2 = I.validate(self.PROPOSED, "2", (b.AWAITING_CALLBACK,))
        self.assertIsNone(v2["quantity"])
        self.assertIn(("quantity", I.R_CONTEXT), v2["_rejected"])

    def test_awaiting_delivery_it_is_ambiguous_not_a_quantity(self):
        v = I.validate(self.PROPOSED, "2", (b.AWAITING_DELIVERY,))
        self.assertIsNone(v["quantity"])
        self.assertEqual(v["_ambiguous"], "quantity")

    def test_with_a_unit_word_it_is_a_quantity_even_when_asked_where(self):
        v = I.validate(interp(quantity=(2, "2 units")), "2 units", (b.AWAITING_DELIVERY,))
        self.assertEqual(v["quantity"], 2)

    def test_the_repeated_kva_is_not_a_quantity(self):
        v = I.validate(interp(quantity=(25, "25")), "25", (b.AWAITING_PURPOSE,),
                       {"capacity_kva": 25})
        self.assertIsNone(v["quantity"])


# ══════════════════════════════════════════════════════════════════════════
# THE GATE
# ══════════════════════════════════════════════════════════════════════════

class NothingIsInvented(unittest.TestCase):
    def test_evidence_must_be_in_the_message(self):
        v = I.validate(interp(capacity_kva=(100, "100 kVA")), "hello", ())
        self.assertIsNone(v["capacity_kva"])
        self.assertIn(("capacity_kva", I.R_NO_EVIDENCE), v["_rejected"])

    def test_the_value_must_be_in_its_evidence(self):
        v = I.validate(interp(capacity_kva=(100, "63 kVA")), "63 kVA", ())
        self.assertIsNone(v["capacity_kva"])

    def test_missing_evidence_is_dropped(self):
        v = I.validate({"intent": "answer", "fields": {"quantity": {"value": 2}},
                        "questions": [], "is_correction": False, "ambiguous": False},
                       "2 units", ())
        self.assertIsNone(v["quantity"])

    def test_no_nearby_size_is_substituted(self):
        v = I.validate(interp(capacity_kva=(63, "60 kva")), "60 kva", ())
        self.assertIsNone(v["capacity_kva"])

    def test_an_uncatalogued_rating_keeps_the_existing_verify_path(self):
        parsed, v = roundtrip("500 kva")
        self.assertEqual(v["capacity_kva"], parsed["capacity_kva"])
        self.assertNotIn(v["capacity_kva"], b.CATALOGUE_KVA)

    def test_applications_come_from_the_existing_list(self):
        v = I.validate(interp(application=("MINING", "mining")), "mining", ())
        self.assertIsNone(v["application"])
        self.assertEqual(set(I.APPLICATIONS),
                         {"AGRICULTURE", "COMMERCIAL", "CONSTRUCTION", "DOMESTIC",
                          "EV_CHARGING", "INDUSTRY", "SOLAR", "TENDER"})

    def test_callback_outside_an_offer_needs_a_whole_call_request(self):
        v = I.validate(interp(callback=("evening", "evening")), "call me this evening pls", ())
        self.assertIsNone(v["callback"])
        v = I.validate(interp(callback=("now", "CALL")), "CALL", ())
        self.assertEqual(v["callback"], "now")


class TheNeverEraseRule(unittest.TestCase):
    KNOWN = {"capacity_kva": 63, "quantity": 2, "application": "AGRICULTURE"}

    def test_a_different_value_without_correction_is_refused(self):
        v = I.validate(interp(capacity_kva=(100, "100")), "100", (), self.KNOWN)
        self.assertIsNone(v["capacity_kva"])
        self.assertIn(("capacity_kva", I.R_ESTABLISHED), v["_rejected"])

    def test_an_explicit_correction_with_evidence_is_accepted(self):
        v = I.validate(interp(intent="correction", correction=True,
                              capacity_kva=(100, "100 kVA")),
                       "actually 100 kVA beku", (), self.KNOWN)
        self.assertEqual(v["capacity_kva"], 100)

    def test_other_facts_survive_the_merge(self):
        v = I.validate(interp(quantity=(2, "2 units")), "2 units beku", (), self.KNOWN)
        merged = b.merged_state(self.KNOWN, I.state_view(v))
        self.assertEqual(merged["capacity_kva"], 63)
        self.assertEqual(merged["application"], "AGRICULTURE")

    def test_the_same_value_again_is_fine(self):
        v = I.validate(interp(capacity_kva=(63, "63")), "63", (), self.KNOWN)
        self.assertEqual(v["capacity_kva"], 63)


class TheSchemaIsClosed(unittest.TestCase):
    def test_the_lists_are_exactly_as_approved(self):
        self.assertEqual(I.INTENTS, ("answer", "question", "greeting", "ack", "correction",
                                     "price_request", "quotation_request", "callback_choice",
                                     "off_topic", "unclear"))
        self.assertEqual(I.QUESTIONS, ("delivery_time", "delivery_area", "warranty", "payment",
                                       "transport", "who_are_you", "range",
                                       "discom_approval", "other"))
        self.assertEqual(I.FIELDS, ("capacity_kva", "quantity", "application",
                                    "delivery_place", "callback"))

    def test_malformed_input_is_trusted_in_no_part(self):
        for bad in (None, "text", [], {"intent": "buy_now", "fields": {}},
                    {"intent": "answer", "fields": {"price": {"value": 1, "evidence": "1"}}},
                    {"intent": "answer", "fields": {}, "extra": 1},
                    {"intent": "answer", "fields": {}, "questions": ["discount"]}):
            v = I.validate(bad, "63 kVA 2 units", ())
            self.assertIn(("*", I.R_SCHEMA), v["_rejected"], bad)
            self.assertIsNone(v["capacity_kva"])
            self.assertIsNone(v["quantity"])

    def test_brain_owned_signals_ignore_the_interpreter(self):
        """delivery_same / discom / callback_offered come from the Brain."""
        known = {"location": "Sira"}
        v = I.validate(I.empty(), "ok", (b.AWAITING_DELIVERY,), known)
        self.assertTrue(v["delivery_same"])
        v = I.validate(I.empty(), "mescom approval ide?", (), {})
        self.assertEqual(v["discom_approval_ask"], b.parse_followup("mescom approval ide?")["discom_approval_ask"])


class NoCustomerTextAndNoNetwork(unittest.TestCase):
    def test_the_module_imports_only_pure_modules(self):
        """json joined in Step 2 (reading the interpreter's JSON). Still no
        network, no database, no provider."""
        tree = ast.parse(open(os.path.join(ROOT, "interpretation.py")).read())
        mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(mods, {"json", "re", "bairavi"})

    def test_no_output_value_is_customer_text(self):
        _, v = roundtrip("warranty ide? 63 kva", (b.AWAITING_DELIVERY,))
        for key, val in v.items():
            if isinstance(val, str):
                self.assertLess(len(val), 40, f"{key} looks like prose: {val!r}")

    def test_the_webhook_uses_it_only_inside_shadow_mode(self):
        """Step 1 forbade any use. Step 2 (2026-09-27) allows exactly one:
        the shadow functions. Nothing else in the webhook may touch it."""
        tree = ast.parse(open(os.path.join(ROOT, "api", "webhook.py")).read())
        allowed = {"shadow_interpret", "_shadow_interpret"}
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            uses = any(isinstance(x, ast.Name) and x.id == "interpretation"
                       for x in ast.walk(fn))
            if uses:
                self.assertIn(fn.name, allowed, f"{fn.name} uses interpretation")


class GapsFoundByMutation(unittest.TestCase):
    """Three validator rules no test pinned (mutation run, 2026-09-27)."""

    def test_an_invented_place_with_real_evidence_is_refused(self):
        v = I.validate(interp(delivery_place=("Mysuru", "Hirekerur")), "Hirekerur",
                       (b.AWAITING_DELIVERY,))
        self.assertIsNone(v["delivery_location"])
        self.assertIn(("delivery_place", I.R_VALUE_NOT_IN_EVIDENCE), v["_rejected"])

    def test_call_inside_a_sentence_is_not_a_booking(self):
        v = I.validate(interp(callback=("now", "call")), "I will call you later", ())
        self.assertIsNone(v["callback"])
        self.assertIn(("callback", I.R_CONTEXT), v["_rejected"])

    def test_a_callback_outside_the_three_options_is_refused(self):
        v = I.validate(interp(callback=("midnight", "2")), "2", (b.AWAITING_CALLBACK,))
        self.assertIsNone(v["callback"])
        self.assertIn(("callback", I.R_NOT_IN_CATALOGUE_ENUM), v["_rejected"])


if __name__ == "__main__":
    unittest.main()
