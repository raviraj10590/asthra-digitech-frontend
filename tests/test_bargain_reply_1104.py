"""Owner 2026-11-04: "bargain maadidaga sariyada uttara needi custemr man olisbeku bot".

Live ...9249 (100 kVA) wrote "25000₹nane kodayhni" — I will give only ₹25,000 —
and the bot stored it as the delivery PLACE. A rupee figure is now a counter-offer,
and every lower-price ask gets the reasons behind the price plus a sales call.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402

D = (b.AWAITING_DELIVERY,)
K100 = {"capacity_kva": 100, "name": "Mohan Hulakund"}
K25 = {"capacity_kva": 25, "name": "Test Person"}


class ARupeeFigureIsAnOffer(unittest.TestCase):
    def test_the_live_message(self):
        f = b.parse_followup("25000₹nane kodayhni", D, known=K100)
        self.assertTrue(f["asked_discount"])
        self.assertEqual(f["offer"], 25000)
        self.assertIsNone(f["delivery_location"])
        self.assertIsNone(f["quantity"])

    def test_other_offers(self):
        for t, n in (("25000 kodtini", 25000), ("₹70,000 ge kodi", 70000), ("70000 aagutta", 70000),
                     ("Rs 1,50,000 final", 150000), ("80000/- ge kodi", 80000)):
            self.assertEqual(b.offered_amount(t), n, t)
            self.assertTrue(b.asked_discount(t), t)

    def test_not_offers(self):
        for t in ("99727 15155 ಕರೆ ಮಾಡಿ", "+91 98765 43210", "Rs 5000 advance kodtini", "85,000 alva",
                  "85000 + gst aa?", "2,50,000 alva", "2026 ge beku", "Pin code:581102", "10 units beku",
                  "100 kva beku", "rate eshtu", "Hassan"):
            self.assertIsNone(b.offered_amount(t), t)


class TheReplyWinsTheCustomerOver(unittest.TestCase):
    def reply(self, text, known):
        f = b.parse_followup(text, D, known=known)
        return f, b.compose_followup_reply(f, known)

    def test_says_why_the_price_is_what_it_is(self):
        _, r = self.reply("25000₹nane kodayhni", K100)
        for part in ("quality", "*5 Star*", "aluminium winding", "Transport ಸೇರಿದೆ", "*1 ವರ್ಷ warranty*",
                     "ರೇಟ್ ಬಗ್ಗೆ ನಮ್ಮ sales ತಂಡ ನಿಮಗೆ call ಮಾಡಿ"):
            self.assertIn(part, r)

    def test_a_far_too_low_offer_is_told_honestly(self):
        _, r = self.reply("25000₹nane kodayhni", K100)
        self.assertIn("ಹೊಸ 100 kVA transformer ಬರೋದು ಕಷ್ಟ", r)
        _, r = self.reply("2 lakh ge kodi", K100)                   # close to ₹2.5 L: no such line
        self.assertNotIn("ಬರೋದು ಕಷ್ಟ", r)

    def test_a_smaller_size_is_offered_only_where_one_exists(self):
        _, r = self.reply("price kammi madi", K100)
        self.assertIn("ಚಿಕ್ಕ size", r)
        _, r = self.reply("price kammi madi", K25)
        self.assertNotIn("ಚಿಕ್ಕ size", r)
        self.assertIn("*4 Star*", r)

    def test_the_reply_passes_the_evidence_guard(self):
        for text, k in (("25000₹nane kodayhni", K100), ("price kammi madi", K25)):
            _, r = self.reply(text, k)
            self.assertIsNone(b.reply_violates_evidence(r.replace("5 Star", "").replace("4 Star", "")
                                                     .replace("*1 ವರ್ಷ warranty*, ನಂತರವೂ service", "")), text)

    def test_never_a_discount_or_a_figure(self):
        for text in ("25000₹nane kodayhni", "best price please", "price kammi madi", "45k"):
            _, r = self.reply(text, K100)
            for w in ("discount", "ರಿಯಾಯಿತಿ", "%", "₹"):
                self.assertNotIn(w, r, (text, w))

    def test_the_owner_sees_the_offer(self):
        f, _ = self.reply("25000₹nane kodayhni", K100)
        alert = b.compose_followup_alert("918494979249", f, "25000₹nane kodayhni", K100)
        self.assertTrue(alert.startswith("💰🔥 *PRICE NEGOTIATION*"))
        self.assertIn("offered ₹25,000", alert)


if __name__ == "__main__":
    unittest.main()
