"""Bairavi transformer enquiries — the layer that stopped answering as Asthra.

WHAT PRODUCTION PROVED (2026-09-12 → 2026-09-15)
------------------------------------------------
Sixteen Meta Lead Ads handoffs about transformers arrived on this number.
FIFTEEN were answered with Asthra DigiTech's digital-marketing services menu.
The one correct reply went to the owner's own number, because the OWNER path
already recognised transformer enquiries as out of scope and the customer path
did not.

The ad form had already answered the qualification questions — capacity,
timeline, location, full name, all five fields present in all sixteen — and
every answer was discarded. Only five were persisted as leads.

And it corrupted the metric: 15 of Asthra's 36 September "enquiries" were
Bairavi transformer leads, about 42% of the headline number.

So the tests here are weighted towards three failure modes, in order of how
expensive they are:

  1. quoting something that does not exist (price, certificate, lead time)
  2. stealing an Asthra marketing lead into the transformer path
  3. counting Bairavi demand as Asthra demand

The FIXTURES below reproduce the exact production form STRUCTURE with
synthetic names and locations. The structure is what the parser contracts
with; no real customer data is in this file.

Offline: no network, no provider, no database.
"""

import io
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402

CAP_Q = "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?"
WHEN_Q = "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?"
LOC_Q = "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?"

# The exact option strings the live form emits, verified against all 16.
CAP_OPTIONS = ("A. 25 kVA", "B. 63 kVA", "C. 100 kVA", "D.500 kVA")
WHEN_OPTIONS = ("A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ", "B.  1 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ",
                "C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ", "E. ಮಾಹಿತಿ ಮತ್ತು ದರಪಟ್ಟಿಗಾಗಿ")


def form(capacity="A. 25 kVA", when="E. ಮಾಹಿತಿ ಮತ್ತು ದರಪಟ್ಟಿಗಾಗಿ",
         location="Testpura", name="Test Person", opener="filled out"):
    return (f"Hello! I {opener} your form and would like to know more "
            f"about your business.\n\n"
            f"{WHEN_Q}: {when}\n"
            f"{CAP_Q}: {capacity}\n"
            f"{LOC_Q}: {location}\n"
            f"Full name: {name}\n"
            f"Phone number: 910000000000")


def executable_only(fn):
    import inspect, tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(fn)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


# ══════════════════════════════════════════════════════════════════════════
# 1 · THE EXPENSIVE FAILURE — quoting evidence that does not exist
# ══════════════════════════════════════════════════════════════════════════

class NothingUndocumentedIsEverQuoted(unittest.TestCase):
    """AC-05: status permits a quotation, documented evidence enables it.

    Only BTS-100 has a GTP. BTS-250 is in active production with no technical
    attribute documented at all. No certificate exists in the workspace. And
    11 of the 16 leads asked for a price list, so this pressure is constant.
    """

    def every_reply(self):
        out = []
        for cap in CAP_OPTIONS + ("", "Z. 9999 kVA"):
            for when in WHEN_OPTIONS:
                out.append(b.compose_reply(b.parse(form(capacity=cap, when=when))))
        out.append(b.compose_reply(b.parse("transformer repair beku")))
        out.append(b.compose_reply(b.parse("100 kva price?")))
        return out

    def test_no_price_figure_ever_appears(self):
        for txt in self.every_reply():
            self.assertNotIn("68244", txt.replace(",", ""))
            self.assertNotIn("₹", txt)
            self.assertNotIn("rs.", txt.lower())
            self.assertNotIn("lakh", txt.lower())
            # no bare rupee-ish number: kVA figures are the only digits allowed
            for m in re.finditer(r"\d[\d,]{2,}", txt):
                near = txt[m.start():m.start() + 24].lower()
                self.assertTrue("kva" in near or "910000000000" in near,
                                f"unexplained number in reply: {near!r}")

    def test_no_delivery_or_lead_time_is_promised(self):
        for txt in self.every_reply():
            low = txt.lower()
            for banned in ("days", "weeks", "ವಾರ", "delivery in",
                           "within 2", "within 3 week"):
                self.assertNotIn(banned, low, banned)

    def test_no_certification_is_claimed(self):
        """None exist in the workspace. Claiming one to a tender buyer is the
        worst thing this layer could do."""
        for txt in self.every_reply():
            up = txt.upper()
            for banned in ("BIS", "BEE", "ISO", "MESCOM", "STAR RATING",
                           "CERTIFIED", "ISI"):
                self.assertNotIn(banned, up, banned)

    def test_no_gtp_level_technical_value_appears(self):
        for txt in self.every_reply():
            low = txt.lower()
            for banned in ("impedance", "no-load loss", "load loss", "losses",
                           "clearance", "conductor", "winding", "flux"):
                self.assertNotIn(banned, low, banned)

    def test_dry_type_is_never_mentioned(self):
        """AC-03: no dry-type SKU may be created, not even as a placeholder."""
        for txt in self.every_reply():
            self.assertNotIn("dry", txt.lower())
        self.assertEqual(b.FAMILY, "OIL_IMMERSED")

    def test_the_catalogue_is_exactly_the_four_manufactured_sizes(self):
        self.assertEqual(b.CATALOGUE_KVA, (25, 63, 100, 250))

    def test_the_no_price_sentence_is_present_on_every_sales_reply(self):
        """A customer who asked for a price must get a real next step, not
        silence about it."""
        for cap in CAP_OPTIONS:
            txt = b.compose_reply(b.parse(form(capacity=cap)))
            self.assertIn("engineer", txt.lower())


# ══════════════════════════════════════════════════════════════════════════
# 2 · DETECTION — and never stealing an Asthra lead
# ══════════════════════════════════════════════════════════════════════════

class Detection(unittest.TestCase):

    def test_every_production_form_shape_is_detected(self):
        for cap in CAP_OPTIONS:
            for when in WHEN_OPTIONS:
                for opener in ("filled out", "filled in"):
                    t = form(capacity=cap, when=when, opener=opener)
                    self.assertTrue(b.looks_like_transformer_enquiry(t))
                    self.assertTrue(b.is_lead_form(t))

    def test_free_text_and_misspellings_are_detected(self):
        for t in ("transformer beku", "100 kva price eshtu?",
                  "need a tranformer", "transfarmer quote",
                  "ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಬೇಕು", "25KVA transformer",
                  "Transformer heat agta ide, engineer beku"):
            self.assertTrue(b.looks_like_transformer_enquiry(t), t)

    def test_asthra_marketing_messages_are_NEVER_captured(self):
        """The second most expensive failure: a real Asthra lead diverted into
        the transformer path never reaches the services menu at all."""
        for t in ("website beku", "social media management bekagide",
                  "[ಆಯ್ಕೆ: 📢 Digital Ads]", "election campaign ge help beku",
                  "instagram ads madbeku", "app development cost?",
                  "ನಮಸ್ಕಾರ", "hi", "menu", "brochure kalsi",
                  "chatbot beku nam business ge",
                  "Hello! I filled out your form and would like to know "
                  "more about your business.\n\nWhat service?: Social Media"):
            self.assertFalse(b.looks_like_transformer_enquiry(t), t)

    def test_an_empty_or_junk_message_is_not_an_enquiry(self):
        for t in ("", "   ", None, "👍", "ok"):
            self.assertFalse(b.looks_like_transformer_enquiry(t))

    def test_kva_needs_a_number_and_a_boundary(self):
        self.assertTrue(b.looks_like_transformer_enquiry("63 kva"))
        self.assertFalse(b.looks_like_transformer_enquiry("kva"))
        self.assertFalse(b.looks_like_transformer_enquiry("bhakvat"))


# ══════════════════════════════════════════════════════════════════════════
# 3 · PARSING — a blank field is correct, a wrong capacity is not (AC-07)
# ══════════════════════════════════════════════════════════════════════════

class Parsing(unittest.TestCase):

    def test_each_live_capacity_option_is_read_correctly(self):
        for opt, kva in zip(CAP_OPTIONS, (25, 63, 100, 500)):
            self.assertEqual(b.parse(form(capacity=opt))["capacity_kva"], kva)

    def test_an_unreadable_capacity_is_None_not_a_guess(self):
        for cap in ("", "don't know", "big one", "ಗೊತ್ತಿಲ್ಲ"):
            p = b.parse(form(capacity=cap))
            self.assertIsNone(p["capacity_kva"], cap)
            self.assertIsNone(p["sku"])

    def test_a_capacity_is_never_mapped_to_a_nearby_size(self):
        """AC-04 is a gate, not a filter. 500 must not become 250."""
        p = b.parse(form(capacity="D.500 kVA"))
        self.assertEqual(p["capacity_kva"], 500)
        self.assertIsNone(p["sku"])
        self.assertFalse(p["in_catalogue"])

    def test_500_is_ROADMAP_not_an_error(self):
        """The ad offers it on purpose — Bairavi plans to build it. Treating
        it as out-of-range was the defect this replaced."""
        p = b.parse(form(capacity="D.500 kVA"))
        self.assertEqual(p["sku_status"], b.ROADMAP)
        self.assertTrue(p["planned"])

    def test_an_unrecognised_capacity_is_VERIFY_not_ROADMAP(self):
        """The distinction that was missing: a planned capacity and a typo
        got identical handling."""
        p = b.parse(form(capacity="Z. 9999 kVA"))
        self.assertEqual(p["sku_status"], b.VERIFY)
        self.assertFalse(p["planned"])
        self.assertFalse(p["in_catalogue"])

    def test_planned_and_unrecognised_are_distinguishable(self):
        planned = b.parse(form(capacity="D.500 kVA"))
        junk = b.parse(form(capacity="Z. 9999 kVA"))
        self.assertNotEqual(planned["sku_status"], junk["sku_status"])
        self.assertNotEqual(b.compose_reply(planned), b.compose_reply(junk))

    def test_the_status_vocabulary_is_ac04s_own(self):
        """AC-04 declares SUPPORTED_PRODUCT / VERIFY / ROADMAP / NOT_OFFERED.
        The first version invented a label that was actually AC-03's
        family-level status — a different axis."""
        self.assertEqual(b.SUPPORTED, "SUPPORTED_PRODUCT")
        self.assertEqual(b.ROADMAP, "ROADMAP")
        self.assertEqual(b.VERIFY, "VERIFY")

    def test_planned_is_not_in_the_manufactured_catalogue(self):
        """Adding 500 to CATALOGUE_KVA would advertise a transformer that
        cannot be delivered."""
        self.assertEqual(b.PLANNED_KVA, (500,))
        for kva in b.PLANNED_KVA:
            self.assertNotIn(kva, b.CATALOGUE_KVA)

    def test_catalogue_sizes_pass_the_status_gate(self):
        for kva in b.CATALOGUE_KVA:
            p = b.parse(form(capacity=f"X. {kva} kVA"))
            self.assertEqual(p["sku"], f"BTS-{kva}")
            self.assertEqual(p["sku_status"], b.SUPPORTED)
            self.assertTrue(p["in_catalogue"])

    def test_a_blank_location_stays_None(self):
        """Four of the sixteen left it blank. TBD is the right answer."""
        self.assertIsNone(b.parse(form(location=""))["location"])

    def test_name_and_location_are_read_when_present(self):
        p = b.parse(form(location="Somewhere", name="A Person"))
        self.assertEqual(p["location"], "Somewhere")
        self.assertEqual(p["name"], "A Person")

    def test_the_original_text_is_always_preserved_verbatim(self):
        t = form(capacity="garbage")
        self.assertEqual(b.parse(t)["raw"], t)

    def test_quantity_is_never_invented(self):
        """It is not in the ad form at all, so it must come back unset and be
        asked in the reply."""
        for cap in CAP_OPTIONS:
            self.assertIsNone(b.parse(form(capacity=cap))["quantity"])
        self.assertIn("units", b.compose_reply(b.parse(form())))

    def test_urgency_comes_from_the_form_option_only(self):
        for when, expect in (("A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ", "IMMEDIATE"),
                             ("B.  1 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ", "WITHIN_1_MONTH"),
                             ("C. 1–3 ತಿಂಗಳೊಳಗೆ ಅಗತ್ಯವಿದೆ", "WITHIN_3_MONTHS"),
                             ("E. ಮಾಹಿತಿ ಮತ್ತು ದರಪಟ್ಟಿಗಾಗಿ", "INFORMATION_ONLY")):
            self.assertEqual(b.parse(form(when=when))["urgency"], expect, when)

    def test_urgency_is_NEVER_inferred_from_prose(self):
        """§6.2a: a loose description is not a diagnosis. A wrong urgency
        either dispatches needlessly or delays a real fault."""
        for t in ("transformer burnt URGENT emergency immediately!!",
                  "ತಕ್ಷಣ transformer beku", "transformer failed, very urgent"):
            self.assertIsNone(b.parse(t)["urgency"], t)


# ══════════════════════════════════════════════════════════════════════════
# 4 · REQUIREMENT TYPE (AC-02)
# ══════════════════════════════════════════════════════════════════════════

class RequirementType(unittest.TestCase):

    def test_a_lead_form_is_always_a_purchase(self):
        for cap in CAP_OPTIONS:
            self.assertEqual(b.parse(form(capacity=cap))["requirement"],
                             b.NEW_UNIT)

    def test_a_lead_form_stays_NEW_UNIT_even_with_a_repair_word_in_it(self):
        """A capacity-and-timeline form is a purchase by construction."""
        t = form(location="near the failed transformer site")
        self.assertEqual(b.parse(t)["requirement"], b.NEW_UNIT)

    def test_repair_signals_produce_REPAIR(self):
        for t in ("transformer repair beku", "our transformer has failed",
                  "transformer burnt", "Transformer heat agta ide",
                  "ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಕೆಟ್ಟು ಹೋಗಿದೆ"):
            self.assertEqual(b.parse(t)["requirement"], b.REPAIR, t)

    def test_a_plain_purchase_enquiry_is_NEW_UNIT(self):
        for t in ("100 kva transformer beku", "need 25 kVA transformer"):
            self.assertEqual(b.parse(t)["requirement"], b.NEW_UNIT, t)

    def test_the_service_reply_asks_urgency_rather_than_assuming_it(self):
        txt = b.compose_reply(b.parse("transformer burnt"))
        self.assertIn("breakdown", txt.lower())
        self.assertIn("planned", txt.lower())


# ══════════════════════════════════════════════════════════════════════════
# 5 · THE REPLY CONFIRMS WHAT THEY ALREADY TOLD US
# ══════════════════════════════════════════════════════════════════════════

class ReplyQuality(unittest.TestCase):

    def test_it_identifies_as_bairavi_not_asthra(self):
        txt = b.compose_reply(b.parse(form()))
        self.assertIn("Bairavi", txt)
        self.assertNotIn("Asthra", txt)

    def test_it_never_offers_asthra_services(self):
        txt = b.compose_reply(b.parse(form()))
        for banned in ("social media", "website", "election", "chatbot",
                       "instagram", "seo"):
            self.assertNotIn(banned, txt.lower(), banned)

    def test_it_echoes_the_capacity_instead_of_asking_again(self):
        """The fifteen mishandled leads were each asked to start over."""
        txt = b.compose_reply(b.parse(form(capacity="C. 100 kVA")))
        self.assertIn("100 kVA", txt)

    def test_it_echoes_the_location_when_given(self):
        txt = b.compose_reply(b.parse(form(location="Moodbidri")))
        self.assertIn("Moodbidri", txt)

    def test_it_omits_the_location_line_when_blank(self):
        txt = b.compose_reply(b.parse(form(location="")))
        self.assertNotIn("📍", txt)

    def test_a_planned_capacity_reply_says_BOTH_halves_of_the_truth(self):
        """Planned, AND not manufactured today. Either half alone is a lie:
        one promises an undeliverable unit, the other rejects a real lead."""
        txt = b.compose_reply(b.parse(form(capacity="D.500 kVA")))
        self.assertIn("500 kVA", txt)
        self.assertIn("ಮುಂದಿನ ಯೋಜನೆ", txt)        # it is planned
        self.assertIn("ಸದ್ಯಕ್ಕೆ ತಯಾರಿಸುತ್ತಿಲ್ಲ", txt)   # not made today
        self.assertIn("engineering", txt.lower())  # routed for assessment
        self.assertIn("250 kVA", txt)              # the real range is stated
        self.assertNotIn("ಕ್ಷಮಿಸಿ", txt)            # not a refusal

    def test_a_planned_capacity_is_never_claimed_as_available(self):
        txt = b.compose_reply(b.parse(form(capacity="D.500 kVA")))
        # the ✅ "in our standard range" confirmation is for made sizes only
        self.assertNotIn("✅", txt)
        self.assertNotIn("standard range ನಲ್ಲಿದೆ", txt)

    def test_the_standard_range_never_advertises_an_unmade_size(self):
        txt = b.compose_reply(b.parse(form(capacity="")))
        self.assertIn("250 kVA", txt)
        self.assertNotIn("500 kVA", txt)


# ══════════════════════════════════════════════════════════════════════════
# 6 · OWNER ALERT
# ══════════════════════════════════════════════════════════════════════════

class OwnerAlert(unittest.TestCase):

    def test_unresolved_fields_print_TBD_rather_than_vanishing(self):
        a = b.compose_owner_alert("910000000000",
                                  b.parse(form(capacity="", location="")))
        self.assertIn("Capacity: TBD", a)
        self.assertIn("Location: TBD", a)
        self.assertIn("Quantity: TBD", a)

    def test_a_planned_capacity_is_flagged_as_an_assessment_not_an_anomaly(self):
        a = b.compose_owner_alert("910000000000",
                                  b.parse(form(capacity="D.500 kVA")))
        self.assertIn("PLANNED CAPACITY", a)
        self.assertIn("ROADMAP", a)
        self.assertNotIn("NOT RECOGNISED", a)

    def test_an_unrecognised_capacity_is_flagged_differently(self):
        a = b.compose_owner_alert("910000000000",
                                  b.parse(form(capacity="Z. 9999 kVA")))
        self.assertIn("NOT RECOGNISED", a)
        self.assertNotIn("PLANNED CAPACITY", a)

    def test_it_states_that_nothing_was_quoted(self):
        a = b.compose_owner_alert("910000000000", b.parse(form()))
        self.assertIn("No price", a)

    def test_it_distinguishes_a_sale_from_a_service_call(self):
        self.assertIn("TRANSFORMER LEAD",
                      b.compose_owner_alert("9", b.parse(form())))
        self.assertIn("SERVICE CALL",
                      b.compose_owner_alert("9", b.parse("transformer burnt")))


# ══════════════════════════════════════════════════════════════════════════
# 7 · SEGREGATION — Bairavi demand is not Asthra demand
# ══════════════════════════════════════════════════════════════════════════

class Segregation(unittest.TestCase):
    """Measured: 15 of Asthra's 36 September enquiries were transformer leads.
    October is the first cohort that can produce a durable FINAL conversion
    claim, so this must hold before it closes."""

    def drive(self, text):
        calls = {"first_seen": [], "sent": [], "leads": [], "owner": [],
                 "menu": [], "saved": []}
        ctx = {"history": [], "recent_sys": [], "paused": False,
               "vip_alerted": False, "lead_alerted": False, "last_user": {}}
        with mock.patch.object(w, "fetch_memory", lambda s: {}), \
             mock.patch.object(w, "record_first_seen",
                               lambda *a, **k: calls["first_seen"].append(a)), \
             mock.patch.object(w, "send_text",
                               lambda to, t, **k: calls["sent"].append(t)), \
             mock.patch.object(w, "send_welcome_menu",
                               lambda to: calls["menu"].append(to)), \
             mock.patch.object(w, "upsert_lead",
                               lambda p, d: calls["leads"].append(d)), \
             mock.patch.object(w, "notify_owner",
                               lambda m, **k: calls["owner"].append(m)), \
             mock.patch.object(w, "save_messages",
                               lambda rows: calls["saved"].extend(rows)), \
             mock.patch.object(w, "save_message", lambda *a, **k: None), \
             mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None), \
             mock.patch.object(w, "BIC_AVAILABLE", False):
            w.run_client_pipeline("910000000000", text, ctx)
        return calls

    def test_a_transformer_lead_never_asserts_first_seen_at(self):
        c = self.drive(form())
        self.assertEqual(c["first_seen"], [],
                         "a transformer buyer must not count as an Asthra enquiry")

    def test_a_transformer_lead_never_gets_the_asthra_services_menu(self):
        c = self.drive(form())
        self.assertEqual(c["menu"], [])

    def test_it_replies_as_bairavi(self):
        c = self.drive(form())
        self.assertEqual(len(c["sent"]), 1)
        self.assertIn("Bairavi", c["sent"][0])

    def test_the_lead_is_still_captured_so_segregation_costs_nothing(self):
        c = self.drive(form(capacity="B. 63 kVA"))
        self.assertEqual(len(c["leads"]), 1)
        self.assertEqual(c["leads"][0]["source"], "bairavi-transformer")
        self.assertIn("63", c["leads"][0]["service_needed"])
        self.assertEqual(len(c["owner"]), 1)
        self.assertIn("BAIRAVI", c["owner"][0])

    def test_an_asthra_new_contact_still_gets_the_menu_and_the_claim(self):
        """The control. Without this, the tests above could pass with the
        whole pipeline broken."""
        c = self.drive("website beku")
        self.assertEqual(len(c["menu"]), 1)
        self.assertEqual(len(c["first_seen"]), 1)
        self.assertEqual(c["leads"], [])

    def test_the_transcript_records_the_reply_without_pii(self):
        c = self.drive(form(name="Someone Real", location="Somewhere"))
        assistant = [t for who, role, t in c["saved"] if role == "assistant"]
        self.assertEqual(assistant, ["[Bairavi transformer reply]"])
        self.assertNotIn("Someone Real", " ".join(assistant))


# ══════════════════════════════════════════════════════════════════════════
# 8 · STRUCTURE — and nothing else moved
# ══════════════════════════════════════════════════════════════════════════

class Structure(unittest.TestCase):

    def test_the_branch_sits_before_the_off_topic_guard(self):
        """A transformer message IS off-topic for Asthra, so the guard would
        redirect it to 'website, social media, ads' — the same mistake."""
        src = io.open(os.path.join(os.path.dirname(__file__), "..", "api",
                                   "webhook.py"), encoding="utf-8").read()
        body = src[src.index("def run_client_pipeline"):]
        self.assertLess(body.index("bairavi.looks_like_transformer_enquiry"),
                        body.index("if is_off_topic(user_text):"))

    def test_the_branch_sits_before_the_new_contact_menu(self):
        src = io.open(os.path.join(os.path.dirname(__file__), "..", "api",
                                   "webhook.py"), encoding="utf-8").read()
        body = src[src.index("def run_client_pipeline"):]
        self.assertLess(body.index("bairavi.looks_like_transformer_enquiry"),
                        body.index("elif is_new_contact:"))

    def test_the_module_does_no_io(self):
        """Pure text handling, so what a customer sees is decided by code that
        can be read — not generated, not fetched."""
        code = executable_only(b.compose_reply) + executable_only(b.parse)
        mod = io.open(os.path.join(os.path.dirname(__file__), "..",
                                   "bairavi.py"), encoding="utf-8").read()
        import ast
        tree = ast.parse(mod)
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imports.add((n.module or "").split(".")[0])
        self.assertEqual(imports, {"re"},
                         f"bairavi.py must stay pure; got {imports}")

    def test_no_provider_call_is_involved(self):
        mod = io.open(os.path.join(os.path.dirname(__file__), "..",
                                   "bairavi.py"), encoding="utf-8").read()
        for banned in ("openai", "deepseek", "gemini", "requests",
                       "_generate_ai_reply"):
            self.assertNotIn(banned, mod.lower(), banned)

    def test_asthra_config_is_untouched(self):
        import inspect
        self.assertEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 35)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      inspect.getsource(w.run_client_pipeline))
        self.assertEqual(w.REASONING_GOAL, "business_operating_review")

    def test_the_conversion_stack_is_untouched(self):
        from bic import conversion_evidence as ce
        self.assertEqual(ce.WINDOW_DAYS, 30)
        self.assertEqual(ce.PREDICATE, "biz.pipeline.conversion_rate@1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
