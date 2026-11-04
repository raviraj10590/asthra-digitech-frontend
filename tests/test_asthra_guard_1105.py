"""Asthra reply guard (owner 2026-11-05: "astra tappu sari maadu, bot tulu matadalla"),
built from the 2026-11-05 customer-vs-bot debate."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import asthra_deal as d  # noqa: E402

ELECTION = "ನಾನು 2 ತಿಂಗಳ ಕಾಲ ಜಿಲಾ ಪಂಚಾಯತ್ ಚುನಾವಣೆಗೆ ಹೋದಿರುತ್ತೇನೆ. ಎಷ್ಟು ವೆಚ್ಚ?"


class Politics(unittest.TestCase):
    def test_a_priced_campaign_becomes_the_quotation_reply(self):
        r, why = d.guard_reply("1. ಪೇಜ್ ಸೆಟಪ್ – ₹2,000\n2. Starter – ₹30,000 / ತಿಂಗಳು", [ELECTION])
        self.assertEqual((r, why), (d.POLITICS_REPLY, ["political price"]))
        self.assertNotIn("₹", d.POLITICS_REPLY)

    def test_no_price_no_change(self):
        t = "ಸರಿ sir, ಯಾವ ಕ್ಷೇತ್ರ? ಚುನಾವಣೆ ಯಾವಾಗ?"
        self.assertEqual(d.guard_reply(t, [ELECTION]), (t, []))

    def test_a_shop_campaign_is_not_politics(self):
        t = "Social media ತಿಂಗಳಿಗೆ ₹30,000 ರಿಂದ ಶುರು sir."
        for said in ("ನನ್ನ ಅಂಗಡಿ ಪ್ರಚಾರ ಬೇಕು", "ad campaign maadi", "party hall business"):
            self.assertEqual(d.guard_reply(t, [said])[0], t, said)


class Results(unittest.TestCase):
    def test_a_follower_promise_goes(self):
        t = "ನಿಯಮಿತ ಪೋಸ್ಟ್ ಮಾಡ್ತೀವಿ.\n2 ತಿಂಗಳಲ್ಲಿ 1,000–5,000 ಹೊಸ ಫಾಲೋವರ್ಸ್‌ಗಳನ್ನು ಪಡೆಯಲು ಸಾಧ್ಯ.\nಬಜೆಟ್ ಎಷ್ಟು?"
        r, why = d.guard_reply(t, ["followers eshtu barutte?"])
        self.assertNotIn("1,000–5,000", r)
        self.assertIn(d.RESULT_LINE, r)
        self.assertIn("ಬಜೆಟ್ ಎಷ್ಟು?", r)
        self.assertEqual(why, ["result promise"])

    def test_saying_it_cannot_be_promised_stays(self):
        t = "₹5,000 ಜಾಹೀರಾತಿಗೆ 15–20 ಲೀಡ್ಸ್ ಎಂದು ಖಾತರಿಪಡಿಸುವುದು ಸಾಧ್ಯವಿಲ್ಲ."
        self.assertEqual(d.guard_reply(t, ["15 leads kodtira?"]), (t, []))

    def test_package_contents_are_not_results(self):
        t = "Starter ₹30,000 (12 posts + 4 reels)"
        self.assertEqual(d.guard_reply(t, ["packages enu?"]), (t, []))


class Tulu(unittest.TestCase):
    def test_a_tulu_promise_is_corrected(self):
        t = "₹9,999 ಈಗ, ₹1,499 ತಿಂಗಳಿಗೆ.\nTulu ಮತ್ತು English ಎರಡನ್ನೂ ಬೆಂಬಲಿಸುವಂತೆ ಮಾಡಬಹುದು."
        r, why = d.guard_reply(t, ["Tulu matadutta?"])
        self.assertIn(d.TULU_LINE, r)
        self.assertNotIn("ಬೆಂಬಲಿಸುವಂತೆ", r)
        self.assertIn("₹9,999", r)

    def test_saying_no_tulu_stays(self):
        t = "ತುಳು ಸದ್ಯ ಇಲ್ಲ sir."
        self.assertEqual(d.guard_reply(t, []), (t, []))


class AfterHoursOnce(unittest.TestCase):
    def test_once_a_night(self):
        import webhook as w
        now = datetime.now(timezone.utc)
        with mock.patch.object(w, "after_hours_note", return_value="\n\n🕐 x"):
            self.assertEqual(w.after_hours_once([]), "\n\n🕐 x")
            recent = [{"role": "assistant", "content": "hi", "created_at": (now - timedelta(minutes=20)).isoformat()}]
            self.assertEqual(w.after_hours_once(recent), "")
            old = [{"role": "assistant", "content": "hi", "created_at": (now - timedelta(hours=9)).isoformat()}]
            self.assertEqual(w.after_hours_once(old), "\n\n🕐 x")
        with mock.patch.object(w, "after_hours_note", return_value=""):
            self.assertEqual(w.after_hours_once([]), "")


class NotOffTopic(unittest.TestCase):
    def test_business_words_are_not_off_topic(self):
        import webhook as w
        for t in ("₹1,499 ಮಾಸಿಕ ಶುಲ್ಕವನ್ನು ಯಾವ ದಿನಕ್ಕೆ ಪಾವತಿಸಬೇಕು?", "Instagram story beku",
                  "video script neeve bareetira?", "UPI QR code kalisi", "html website beku",
                  "event program ge poster", "ನಮ್ಮ ಕಥೆ ವಿಡಿಯೋ ಮಾಡಿ", "QR ಕೋಡ್ ಕಳಿಸಿ"):
            self.assertFalse(w.is_off_topic(t), t)

    def test_real_off_topic_still_caught(self):
        import webhook as w
        for t in ("python code bareyiri", "ondu joke heli", "ಕವನ ಬರೆದು ಕೊಡಿ", "capital of France?"):
            self.assertTrue(w.is_off_topic(t), t)


if __name__ == "__main__":
    unittest.main()
