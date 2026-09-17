"""Ask again, once — and never at the wrong moment.

Owner's ruling, 2026-09-17: "if they not replied your question you ask them
one hour later again."

The case behind it: the Mangalore enquiry was asked what the transformer was
for, answered with something the parser could not read, got an
acknowledgement, and was never asked again — while carrying an explicit
request for a quotation.

A nudge is one message into somebody's personal WhatsApp, so most of these
tests are about the six occasions when it must NOT be sent. Offline: no
network, no database, no real clock.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                          # noqa: E402
import nudge as n                                            # noqa: E402

# 12:00 IST — inside the daytime window, so a test that means to check the
# interval is not accidentally checking the hour.
NOON = datetime(2026, 9, 18, 6, 30, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 18, 21, 30, tzinfo=timezone.utc)    # 03:00 IST


def state(minutes_ago=90, awaiting=("purpose",), replied=False,
          nudges=0, paused=False):
    return dict(awaiting=awaiting,
                asked_at=NOON - timedelta(minutes=minutes_ago),
                customer_replied_since=replied, nudges_since=nudges,
                paused=paused)


class ItAsksAgainAfterAnHour(unittest.TestCase):

    def test_the_interval_is_the_owners_one_hour(self):
        self.assertEqual(n.NUDGE_AFTER_MINUTES, 60)

    def test_an_unanswered_question_is_nudged(self):
        self.assertEqual(n.decide(now=NOON, **state(90)), n.SEND)

    def test_exactly_at_the_hour_it_sends(self):
        self.assertEqual(n.decide(now=NOON, **state(60)), n.SEND)

    def test_a_minute_early_it_waits(self):
        self.assertEqual(n.decide(now=NOON, **state(59)), n.TOO_SOON)

    def test_it_nudges_for_either_field_or_both(self):
        for awaiting in (("delivery",), ("purpose",), ("delivery", "purpose")):
            self.assertEqual(n.decide(now=NOON, **state(awaiting=awaiting)),
                             n.SEND, awaiting)


class TheSixReasonsNotTo(unittest.TestCase):

    def test_nothing_outstanding(self):
        self.assertEqual(n.decide(now=NOON, **state(awaiting=())),
                         n.NOTHING_OUTSTANDING)

    def test_the_customer_already_replied(self):
        """They said SOMETHING. Whether it parsed is our problem, not theirs
        — and nudging someone who answered is the fastest way to be blocked.
        """
        self.assertEqual(n.decide(now=NOON, **state(replied=True)),
                         n.CUSTOMER_REPLIED)

    def test_it_never_nudges_twice(self):
        self.assertEqual(n.MAX_NUDGES_PER_TURN, 1)
        self.assertEqual(n.decide(now=NOON, **state(nudges=1)),
                         n.ALREADY_NUDGED)
        self.assertEqual(n.decide(now=NOON, **state(nudges=5)),
                         n.ALREADY_NUDGED)

    def test_a_paused_chat_outranks_everything(self):
        """An owner who took the chat over with #stop must not have a bot
        messaging into the handoff. This is the pause bug again, in a new
        place, so it is checked FIRST and cannot be overridden."""
        self.assertEqual(n.decide(now=NOON, **state(paused=True)),
                         n.CHAT_PAUSED)
        # Even when everything else says send.
        self.assertEqual(
            n.decide(now=NOON, **state(minutes_ago=600, paused=True)),
            n.CHAT_PAUSED)

    def test_it_stays_quiet_at_night(self):
        """03:00 IST. A nudge someone reads when they wake up is spam."""
        night = dict(state(90), asked_at=NIGHT - timedelta(minutes=90))
        self.assertEqual(n.decide(now=NIGHT, **night), n.OUTSIDE_DAYTIME)

    def test_it_does_not_try_outside_the_whatsapp_window(self):
        """Meta REJECTS free-form messages after 24 hours. A nudge sent late
        is not merely unwelcome, it is refused — and the refusal is invisible
        unless somebody goes looking."""
        self.assertEqual(n.decide(now=NOON, **state(minutes_ago=23 * 60)),
                         n.WINDOW_CLOSED)
        self.assertLess(n.WINDOW_HOURS, 24)

    def test_a_missing_timestamp_does_not_send(self):
        s = dict(state(), asked_at=None)
        self.assertEqual(n.decide(now=NOON, **s), n.TOO_SOON)


class TheDaytimeWindow(unittest.TestCase):

    def test_it_matches_the_hours_health_checks_use(self):
        import health
        self.assertEqual((n.DAY_START_IST, n.DAY_END_IST),
                         (health.DAY_START_IST, health.DAY_END_IST))

    def test_the_boundaries(self):
        def at(hour_ist):
            return datetime(2026, 9, 18, 0, 0, tzinfo=n.IST).replace(hour=hour_ist)
        self.assertFalse(n.in_daytime(at(8)))
        self.assertTrue(n.in_daytime(at(9)))
        self.assertTrue(n.in_daytime(at(18)))
        self.assertFalse(n.in_daytime(at(19)))
        self.assertFalse(n.in_daytime(at(3)))


class WhatTheNudgeSays(unittest.TestCase):

    KNOWN = {"location": "Mangalore", "delivery_location": None}

    def msg(self, awaiting=("purpose",), known=None):
        return n.compose(awaiting, b.question_for,
                         known if known is not None else self.KNOWN)

    def test_it_identifies_as_bairavi_never_as_asthra(self):
        r = self.msg()
        self.assertIn("Bairavi Trans Solutions", r)
        self.assertNotIn("Asthra", r)

    def test_it_repeats_the_actual_question(self):
        self.assertIn("ಉದ್ದೇಶ", self.msg(("purpose",)))
        self.assertIn("ಡೆಲಿವರಿ", self.msg(("delivery",)))

    def test_it_confirms_the_known_location_rather_than_asking_cold(self):
        self.assertIn("Mangalore", self.msg(("delivery",)))

    def test_it_quotes_no_price_date_or_certificate(self):
        for awaiting in (("purpose",), ("delivery",), ("delivery", "purpose")):
            r = self.msg(awaiting)
            for claim in ("₹", "days", "week", "ISO", "BIS", "certified"):
                self.assertNotIn(claim, r, awaiting)

    def test_it_gives_the_customer_a_way_out(self):
        """A follow-up that cannot be declined is harassment. Saying "no
        trouble if not" costs one line and makes the nudge answerable."""
        self.assertIn("ತೊಂದರೆ ಇಲ್ಲ", self.msg())

    def test_it_says_why_it_is_asking_again(self):
        self.assertIn("quotation", self.msg())

    def test_it_refuses_to_compose_with_nothing_to_ask(self):
        with self.assertRaises(ValueError):
            n.compose((), b.question_for, self.KNOWN)

    def test_it_numbers_both_questions_with_whole_keycaps(self):
        r = self.msg(("delivery", "purpose"))
        self.assertIn("1️⃣", r)
        self.assertIn("2️⃣", r)


class TheMarkerCarriesTheStateWithNoNewTables(unittest.TestCase):

    def test_what_is_awaited_survives_a_round_trip(self):
        for awaiting in ((), ("delivery",), ("purpose",),
                         ("delivery", "purpose")):
            self.assertEqual(
                b.marker_awaiting(b.flow_marker(awaiting)), awaiting)

    def test_the_marker_still_keeps_the_conversation_sticky(self):
        """The stickiness fix reads FLOW_MARKER out of history. If the
        suffix broke that match, every follow-up would fall through to
        Asthra's off-topic guard again — the 2026-09-15 defect."""
        for awaiting in ((), ("delivery", "purpose")):
            row = {"role": "assistant", "content": b.flow_marker(awaiting)}
            self.assertTrue(b.in_transformer_flow([row]), awaiting)

    def test_an_unknown_field_name_is_ignored_not_trusted(self):
        self.assertEqual(
            b.marker_awaiting(b.FLOW_MARKER + " awaiting=purpose,nonsense"),
            ("purpose",))

    def test_a_plain_marker_awaits_nothing(self):
        self.assertEqual(b.marker_awaiting(b.FLOW_MARKER), ())
        self.assertEqual(b.marker_awaiting("just some text"), ())
        self.assertEqual(b.marker_awaiting(None), ())

    def test_the_nudge_marker_is_distinguishable_from_a_reply(self):
        self.assertNotIn(n.NUDGE_MARKER, b.FLOW_MARKER)
        self.assertNotIn(b.FLOW_MARKER, n.NUDGE_MARKER)


class WhatIsOutstandingIsDecidedInOnePlace(unittest.TestCase):

    def test_an_answered_purpose_is_not_awaited(self):
        f = b.parse_followup("Agriculture")
        self.assertNotIn(b.AWAITING_PURPOSE, b.outstanding(f))

    def test_an_answered_delivery_is_not_awaited(self):
        for text in ("delivery: Puttur", "same place", "deliver to Sullia"):
            self.assertNotIn(b.AWAITING_DELIVERY,
                             b.outstanding(b.parse_followup(text)), text)

    def test_quantity_is_never_awaited(self):
        """The owner ruled it is not important and defaults to one, so it is
        asked once and never chased — including by the nudge."""
        f = b.parse_followup("Agriculture and delivery: Puttur")
        self.assertEqual(b.outstanding(f), ())

    def test_a_form_supplied_delivery_settles_it(self):
        f = b.parse_followup("Agriculture")
        self.assertEqual(
            b.outstanding(f, {"delivery_location": "Puttur"}), ())

    def test_an_unknown_field_refuses_rather_than_asking_nothing(self):
        """Returning "" would render a numbered bullet with no question in
        it — a message that looks broken to the customer and says nothing.
        Failing loudly keeps a new field from shipping half-wired."""
        with self.assertRaises(ValueError):
            b.question_for("colour")
        for field in (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE):
            self.assertTrue(b.question_for(field).strip())

    def test_the_reply_and_the_marker_cannot_disagree(self):
        """Both derive from outstanding(). If they diverged, the bot would
        ask for one thing and the sweep would chase another."""
        for text in ("Agriculture", "hmm ok", "delivery: Puttur", "100kv"):
            f = b.parse_followup(text)
            awaiting = b.outstanding(f)
            reply = b.compose_followup_reply(f)
            for field in awaiting:
                token = "ಡೆಲಿವರಿ" if field == b.AWAITING_DELIVERY else "ಉದ್ದೇಶ"
                self.assertIn(token, reply, f"{text} / {field}")


class TheRunIsObservableAndCarriesNoPII(unittest.TestCase):

    def test_the_summary_names_every_outcome(self):
        line = n.summarise({"considered": 9, "sent": 2, n.TOO_SOON: 5,
                            n.CHAT_PAUSED: 1, "send_failed": 1})
        self.assertIn("considered=9", line)
        self.assertIn("sent=2", line)
        self.assertIn("too_soon=5", line)
        self.assertIn("chat_paused=1", line)

    def test_an_empty_run_still_says_so(self):
        self.assertIn("considered=0", n.summarise({}))

    def test_zero_counts_are_omitted_so_the_line_stays_readable(self):
        self.assertNotIn("sent=0", n.summarise({"considered": 3, "sent": 0}))
