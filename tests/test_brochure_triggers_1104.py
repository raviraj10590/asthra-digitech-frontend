"""Owner, 2026-11-04: send the brochure only when the customer asks for it,
or asks what the company does. Asking us to DESIGN a brochure / pamphlet is a
service enquiry, and a generic "details kalisi" is not a brochure request."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w  # noqa: E402


class BrochureTriggers(unittest.TestCase):
    def test_asking_for_the_brochure(self):
        for t in ("send brochure", "brochure kalisi", "brochure beku", "company profile",
                  "pdf kodi", "ಬ್ರೋಚರ್ ಕಳಿಸಿ", "brochre", "catalogue kalisi"):
            self.assertTrue(w.is_brochure_request(t), t)

    def test_asking_what_the_company_does(self):
        for t in ("nimma company enu kelsa madutte", "nimma company en work madutte",
                  "what does your company do", "what do you do?", "what are your services",
                  "ನಿಮ್ಮ ಕಂಪನಿ ಏನು ಕೆಲಸ ಮಾಡುತ್ತೆ", "ನೀವು ಏನು ಕೆಲಸ ಮಾಡ್ತೀರಾ",
                  "company bagge heli", "tell me about your company", "ನಿಮ್ಮ ಸೇವೆಗಳು ಏನು"):
            self.assertTrue(w.is_brochure_request(t), t)
            self.assertTrue(w.is_company_overview(t), t)

    def test_not_a_brochure_request(self):
        for t in ("what is your price", "brochure design beku", "brochure design maadtira",
                  "pamphlet beku", "flyer design", "details kalisi", "info kodi",
                  "price details kalisi", "my profile", "catalogue design maadi kodi",
                  "ಬ್ರೋಚರ್ ಡಿಸೈನ್ ಮಾಡ್ತೀರಾ", "website beku", "nimma office yelli ide"):
            self.assertFalse(w.is_brochure_request(t), t)

    def test_an_ad_form_is_not_the_question(self):
        form = ("Hello! I filled out your form and would like to know more about your business.\n\n"
                "What is your monthly budget?: Under ₹10,000\nನಿಮ್ಮ ವ್ಯಾಪಾರ ಯಾವುದು?: Other business")
        self.assertFalse(w.is_brochure_request(form))

    def test_the_overview_question_gets_a_line_before_the_pdf(self):
        self.assertIn("brochure", w.BROCHURE_OVERVIEW_KN)
        self.assertIn("AI WhatsApp bot", w.BROCHURE_OVERVIEW_KN)


if __name__ == "__main__":
    unittest.main()
