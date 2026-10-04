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

    # OPTION B (owner, 2026-10-04: "naave ondu time fix madodu sari alla"):
    # outside call hours the customer is ASKED for a time, none is invented.
    def test_now_at_night_asks_them_for_a_time_tomorrow(self):
        for hour in (21, 22, 23):
            with self.subTest(hour=hour):
                reply, alert = choose("1", hour)
                self.assertIn("ನಾಳೆ ಯಾವ ಸಮಯಕ್ಕೆ call ಮಾಡಲಿ", reply)
                self.assertNotIn("ಈಗಲೇ", reply)
                self.assertNotIn("ಗಂಟೆಯ ಒಳಗೆ", reply)
                self.assertIn("TOMORROW MORNING", alert)

    def test_now_before_nine_asks_them_for_a_time_today(self):
        for hour in (0, 5, 8):
            with self.subTest(hour=hour):
                reply, alert = choose("1", hour)
                self.assertIn("ಇಂದು ಯಾವ ಸಮಯಕ್ಕೆ call ಮಾಡಲಿ", reply)
                self.assertIn("TODAY MORNING", alert)

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
        self.assertTrue(a.startswith("🔥📞 *CALL TOMORROW MORNING"))
        self.assertIn("Bairavi lead", a)

    def test_missed_call_complaint(self):
        a = b.compose_call_now_alert("919000000001", {"call_missed": True}, {"name": "Ravi"})
        self.assertTrue(a.startswith("📵🔥 *CALL NOW — the promised call did not come*"))

    def test_nothing_for_other_messages(self):
        for f in ({}, {"callback": b.CALLBACK_EVENING}, {"callback": b.CALLBACK_TOMORROW}, {"asked_price": True}):
            self.assertEqual(b.compose_call_now_alert("919000000001", f, {}), "")


class TheirOwnTime(unittest.TestCase):
    """Option B end to end: night 'now' -> question -> their answer -> the promise."""

    def night_turns(self, answer, answer_hour=22):
        first = b.parse_followup("1", (b.AWAITING_CALLBACK,), KNOWN)
        first["call_hour"] = 22
        q_reply = b.compose_followup_reply(first, KNOWN, None, None)
        awaiting = b.awaiting_after(first, KNOWN)
        known = b.merged_state(KNOWN, first)
        second = b.parse_followup(answer, awaiting, known)
        second["call_hour"] = answer_hour
        return q_reply, awaiting, second, b.compose_followup_reply(second, known, None, None), known

    def test_their_hour_becomes_the_promise(self):
        q, awaiting, f, reply, known = self.night_turns("11")
        self.assertIn("ನಾಳೆ ಯಾವ ಸಮಯಕ್ಕೆ call ಮಾಡಲಿ", q)
        self.assertEqual(awaiting, (b.AWAITING_CALL_TIME,))
        self.assertIsNone(f["quantity"])                      # "11" is eleven o'clock, not 11 units
        self.assertEqual(f["call_time"]["hour"], 11)
        self.assertIn("engineer *ನಾಳೆ ಬೆಳಿಗ್ಗೆ 11 ಗಂಟೆಗೆ*", reply)
        alert = b.compose_call_now_alert("919000000000", f, known)
        self.assertTrue(alert.startswith("🕙📞 *CALL TOMORROW 11 AM* — the customer's own time"))

    def test_evening_word(self):
        _, _, f, reply, _ = self.night_turns("sanje")
        self.assertIn("engineer *ನಾಳೆ ಸಂಜೆ*", reply)
        self.assertIsNone(f["callback"])                      # a time, not a new "this evening" choice

    def test_answered_next_morning_means_today(self):
        _, _, f, reply, _ = self.night_turns("4 ಕ್ಕೆ", answer_hour=8)
        self.assertIn("engineer *ಇಂದು ಸಂಜೆ 4 ಗಂಟೆಗೆ*", reply)

    def test_remembered_from_history(self):
        hist = [{"role": "assistant", "content": b.flow_marker((b.AWAITING_CALL_TIME,))},
                {"role": "user", "content": "11 ಗಂಟೆಗೆ"}]
        self.assertEqual(b.established_from_history(hist).get("call_time", {}).get("hour"), 11)

    def test_not_a_time_is_left_alone(self):
        _, _, f, _, _ = self.night_turns("Krishi")
        self.assertIsNone(f["call_time"])
