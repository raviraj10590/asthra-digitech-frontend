"""Call hours, 9 am – 9 pm IST (owner, 2026-10-03: "morning 9 to night 9 varege").

Live: two leads chose "call now" at 8–9 pm, were promised *ಈಗಲೇ*, and nobody
called. Outside the hours "now" is promised as the next morning.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import bairavi as b                                    # noqa: E402
import webhook as w                                    # noqa: E402
from conversation import Conversation, lead_form       # noqa: E402

# Captured at import, before the suite-wide midday fixture replaces it.
REAL_IST_HOUR = w._ist_hour

KNOWN = {"capacity_kva": 25, "name": "Muttu", "location": "Hosakeri",
         "application": "AGRICULTURE"}


def choose(option, hour):
    f = b.parse_followup(option, (b.AWAITING_CALLBACK,), KNOWN)
    f["call_hour"] = hour
    return (b.compose_followup_reply(f, KNOWN, None, None),
            b.compose_followup_alert("919000000000", f, option, KNOWN))


class ThePromise(unittest.TestCase):
    def test_now_inside_the_hours_is_now(self):
        for hour in (9, 12, 20):
            with self.subTest(hour=hour):
                reply, alert = choose("1", hour)
                self.assertIn("*ಈಗಲೇ*", reply)
                self.assertIn("CALL NOW", alert)

    def test_now_at_night_is_tomorrow_morning(self):
        for hour in (21, 22, 23):
            with self.subTest(hour=hour):
                reply, alert = choose("1", hour)
                self.assertIn("ನಾಳೆ ಬೆಳಿಗ್ಗೆ 10 ಗಂಟೆಯ ಒಳಗೆ", reply)
                self.assertNotIn("ಈಗಲೇ", reply)
                self.assertIn("TOMORROW BY 10 AM", alert)

    def test_now_before_nine_is_this_morning(self):
        for hour in (0, 5, 8):
            with self.subTest(hour=hour):
                reply, alert = choose("1", hour)
                self.assertIn("ಇಂದು ಬೆಳಿಗ್ಗೆ 10 ಗಂಟೆಯ ಒಳಗೆ", reply)
                self.assertIn("TODAY BY 10 AM", alert)

    def test_this_evening_after_nine_pm_is_tomorrow_evening(self):
        self.assertIn("*ಇಂದು ಸಂಜೆ*", choose("2", 18)[0])
        self.assertIn("*ನಾಳೆ ಸಂಜೆ*", choose("2", 22)[0])

    def test_tomorrow_is_always_tomorrow(self):
        for hour in (3, 12, 23):
            self.assertIn("*ನಾಳೆ*", choose("3", hour)[0])

    def test_unknown_hour_keeps_the_old_promise(self):
        self.assertIn("*ಈಗಲೇ*", choose("1", None)[0])

    def test_the_bounds_are_the_owners(self):
        self.assertEqual(b.CALL_HOURS, (9, 21))


class ThroughTheLivePipeline(unittest.TestCase):
    def test_the_webhook_passes_the_india_hour(self):
        """Every Bairavi follow-up reaches the composer with call_hour set
        from webhook._ist_hour()."""
        seen = []
        real = b.compose_followup_reply

        def spy(followup, *a, **k):
            seen.append(followup.get("call_hour"))
            return real(followup, *a, **k)
        c = Conversation()
        c.send(lead_form())
        with mock.patch.object(w, "_ist_hour", lambda: 22), \
             mock.patch.object(b, "compose_followup_reply", spy):
            c.send("Agriculture")
        self.assertEqual(seen, [22])

    def test_the_clock_is_india_time(self):
        """16:00 UTC is 21:30 in India: hour 21, past the call hours."""
        from datetime import datetime, timezone
        fixed = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed
        with mock.patch.object(w, "datetime", FakeDT):
            self.assertEqual(REAL_IST_HOUR(), 21)


if __name__ == "__main__":
    unittest.main()


class CallNowAlert(unittest.TestCase):
    """#1 (2026-10-04): 'call now' and 'the call never came' get their own short alert."""

    def test_now_in_hours(self):
        a = b.compose_call_now_alert("919000000001", {"callback": b.CALLBACK_NOW, "call_hour": 12},
                                     {"name": "Ravi", "capacity_kva": 63, "delivery_location": "Mandya"})
        self.assertEqual(a, "🔥📞 *CALL NOW*\nRavi · 63 kVA · Mandya\nwa.me/919000000001")

    def test_now_at_night_says_the_morning_promise(self):
        a = b.compose_call_now_alert("919000000001", {"callback": b.CALLBACK_NOW, "call_hour": 22}, {})
        self.assertTrue(a.startswith("🔥📞 *CALL TOMORROW BY 10 AM"))
        self.assertIn("Bairavi lead", a)

    def test_missed_call_complaint(self):
        a = b.compose_call_now_alert("919000000001", {"call_missed": True}, {"name": "Ravi"})
        self.assertTrue(a.startswith("📵🔥 *CALL NOW — the promised call did not come*"))

    def test_nothing_for_other_messages(self):
        for f in ({}, {"callback": b.CALLBACK_EVENING}, {"callback": b.CALLBACK_TOMORROW}, {"asked_price": True}):
            self.assertEqual(b.compose_call_now_alert("919000000001", f, {}), "")
