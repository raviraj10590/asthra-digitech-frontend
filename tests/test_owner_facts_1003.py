"""Owner facts, 2026-10-03: installation, scope of supply, photos, documents.

Owner (Kanglish, verbatim in bairavi.py): we make the TC and do not install
it; installation is by a local electrical contractor at extra cost — "talk to
the engineer"; the price is for the TC only, poles / DP structure /
installation are priced after a site estimate; photos — the engineer sends
them; documents — ask the engineer.

Each message below is real (replay of 14 days); each went to the model.
"""
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                    # noqa: E402
import interpretation as I                             # noqa: E402
from _price_policy import assert_only_owner_prices      # noqa: E402

KNOWN = {"capacity_kva": 25, "name": "Sudarshan", "location": "Kulumegudlu",
         "application": "AGRICULTURE", "callback": "now"}


def turn(text, known=KNOWN, awaiting=()):
    f = b.parse_followup(text, awaiting, known)
    f["call_hour"] = 12
    return f, b.compose_followup_reply(f, known, None, None)


class ScopeOfSupply(unittest.TestCase):
    LIVE = ("Kamba yalla bantha", "Full tc setup barutha only tc na",
            "ನಾವು ಟಿಸಿ ಬತ್ತಲೆ ಮಾತ್ರ ಕೇಳುತ್ತೇವೆ", "DP structure ide na")

    def test_answered_tc_only_and_site_estimate(self):
        for t in self.LIVE:
            with self.subTest(t=t):
                f, reply = turn(t)
                self.assertTrue(f["asks_scope"])
                self.assertFalse(b.should_ask_model(f, KNOWN))
                self.assertIn("TC (transformer) ಮಾತ್ರ", reply)
                self.assertIn("estimate", reply)
                self.assertNotIn("₹", reply, "no figure for poles / DP / installation")

    def test_never_stored_as_the_delivery_place(self):
        for t in self.LIVE + ("DP structure",):
            with self.subTest(t=t):
                f, _ = turn(t, {"capacity_kva": 25, "location": "x"}, (b.AWAITING_DELIVERY,))
                self.assertIsNone(f["delivery_location"])

    def test_the_owner_hears_about_it(self):
        f, _ = turn("Kamba yalla bantha")
        self.assertIn("POLES / DP / SETUP", b.compose_followup_alert("919000000000", f, "x", KNOWN))


class EveryPriceSaysWhatItIsFor(unittest.TestCase):
    def test_the_price_reply_says_tc_only(self):
        _, reply = turn("Dar heli")
        self.assertIn(b.PRICE_SCOPE_KN, reply)
        assert_only_owner_prices(self, reply)

    def test_the_full_list_and_the_terms_card_say_it_too(self):
        self.assertIn(b.PRICE_SCOPE_KN, b.price_short_kn(None))
        self.assertIn("ದರ TC (transformer) ಮಾತ್ರ", b._SALES_TERMS)


class Installation(unittest.TestCase):
    def test_we_do_not_install_a_contractor_does_at_extra_cost(self):
        f, reply = turn("Installation charge yestaguthe")
        for must in ("Installation ನಾವು ಮಾಡುವುದಿಲ್ಲ", "local electrical", "ಹೆಚ್ಚುವರಿ ವೆಚ್ಚ",
                     "Installation charges ಬಗ್ಗೆ ನಮ್ಮ engineer ಜೊತೆ ಮಾತನಾಡಿ"):
            self.assertIn(must, reply)
        self.assertNotIn("₹", reply)


class Photos(unittest.TestCase):
    def test_the_engineer_sends_them_and_the_owner_is_told(self):
        f, reply = turn("T c photo send madi")
        self.assertTrue(f["asks_photo"])
        self.assertFalse(b.should_ask_model(f, KNOWN))
        self.assertIn(b.PHOTO_KN, reply)
        self.assertIn("PHOTOS REQUESTED", b.compose_followup_alert("919000000000", f, "x", KNOWN))


class Documents(unittest.TestCase):
    def test_ask_the_engineer_and_the_owner_is_told(self):
        f, reply = turn("ಬೇಕಾದ ದಾಖಲೆಗಳು ವಿವರವನ್ನು ನೀಡಿ")
        self.assertTrue(f["asks_documents"])
        self.assertFalse(b.should_ask_model(f, KNOWN))
        self.assertIn(b.DOCUMENTS_KN, reply)
        self.assertIn("DOCUMENTS", b.compose_followup_alert("919000000000", f, "x", KNOWN))


class NothingElseChanges(unittest.TestCase):
    def test_ordinary_answers_raise_none_of_the_new_flags(self):
        for t in ("bus stand hattira", "Solar", "Kadaba", "near bus stop", "25 kVA beku",
                  "Agriculture", "1", "ok", "[ಚಿತ್ರ ಕಳುಹಿಸಿದ್ದಾರೆ: photo]"):
            with self.subTest(t=t):
                f = b.parse_followup(t, (), KNOWN)
                self.assertFalse(f["asks_scope"] or f["asks_photo"] or f["asks_documents"])


class TheModelsBrief(unittest.TestCase):
    def test_it_no_longer_tells_the_model_a_system_sends_the_rate_list(self):
        """Rule 1 used to say 'ದರಪಟ್ಟಿಯನ್ನು ನಮ್ಮ ವ್ಯವಸ್ಥೆ ಕಳುಹಿಸುತ್ತದೆ' — and the
        model repeated it to customers."""
        brief = b.model_brief_kn()
        self.assertNotIn("ದರಪಟ್ಟಿಯನ್ನು ನಮ್ಮ ವ್ಯವಸ್ಥೆ ಕಳುಹಿಸುತ್ತದೆ", brief)

    def test_it_carries_the_owner_facts(self):
        brief = b.model_brief_kn()
        for must in ("Installation ನಾವು ಮಾಡುವುದಿಲ್ಲ", "TC (transformer) ಮಾತ್ರ",
                     "TC photo", "ದಾಖಲೆಗಳು"):
            self.assertIn(must, brief)


class TheShadowContract(unittest.TestCase):
    def test_brain_owned(self):
        v = I.state_view(I.validate(I.empty(), "Kamba yalla bantha"))
        self.assertTrue(v["asks_scope"])
        self.assertTrue(I.state_view(I.validate(I.empty(), "T c photo send madi"))["asks_photo"])


if __name__ == "__main__":
    unittest.main()
