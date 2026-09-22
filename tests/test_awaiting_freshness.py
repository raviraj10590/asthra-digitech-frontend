"""A pending question goes stale.

THE PRODUCTION FAILURE, 2026-09-22. The owner messaged the bot as a customer.
A delivery question the bot had asked TWO DAYS earlier was still treated as
live, so "Hii" -- the greeting opening a brand-new conversation -- was read as
the answer to it and stored as the delivery address.

The damage then compounded: with delivery established, nothing was
outstanding, so every reply for the rest of that conversation was a receipt
with no question in it, and a real "ಬೆಂಗಳೂರು" two turns later was ignored
because the bot was no longer waiting for anywhere.

TWELVE HOURS, AND THE NUMBER IS A TRADE. A real answer to "where should we
deliver?" arrives the same day or the next morning, so the window has to
cover an overnight gap. Past that, a bare word is far more likely to be
someone starting a fresh conversation.

WHEN IT IS WRONG IT COSTS ONE TURN. An expired question is not forgotten --
it is still outstanding, so the reply asks it again and the next message is
read normally. That is the cheap direction. The expensive direction is what
production did.

FLOW MEMBERSHIP IS NOT BOUNDED BY THIS. Someone who enquired about a
transformer is still a transformer lead tomorrow; only the pending QUESTION
expires.

Offline: no network, no database.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402


def marker(hours_ago, awaiting=(b.AWAITING_DELIVERY,)):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"role": "assistant", "content": b.flow_marker(awaiting),
            "created_at": ts}


class TheWindowIsTwelveHours(unittest.TestCase):

    def test_the_window_is_declared_once(self):
        self.assertEqual(w.AWAITING_MAX_AGE_HOURS, 12)

    def test_a_recent_question_is_live(self):
        for hours in (0, 0.1, 1, 6, 11.5):
            with self.subTest(hours=hours):
                self.assertEqual(w.bairavi_awaiting([marker(hours)]),
                                 (b.AWAITING_DELIVERY,))

    def test_an_old_question_is_stale(self):
        for hours in (12.5, 24, 48, 24 * 30):
            with self.subTest(hours=hours):
                self.assertEqual(w.bairavi_awaiting([marker(hours)]), ())

    def test_the_boundary_is_the_declared_window(self):
        just_inside = w.AWAITING_MAX_AGE_HOURS - 0.05
        just_outside = w.AWAITING_MAX_AGE_HOURS + 0.05
        self.assertTrue(w.bairavi_awaiting([marker(just_inside)]))
        self.assertFalse(w.bairavi_awaiting([marker(just_outside)]))


class StaleFailsSafe(unittest.TestCase):

    def test_a_missing_timestamp_is_stale(self):
        """The cost of being wrong here is one extra question."""
        row = {"role": "assistant",
               "content": b.flow_marker((b.AWAITING_DELIVERY,))}
        self.assertEqual(w.bairavi_awaiting([row]), ())

    def test_an_unparseable_timestamp_is_stale(self):
        for ts in ("", "not a date", "0000", None):
            with self.subTest(ts=ts):
                row = {"role": "assistant", "created_at": ts,
                       "content": b.flow_marker((b.AWAITING_DELIVERY,))}
                self.assertEqual(w.bairavi_awaiting([row]), ())

    def test_an_empty_history_is_empty(self):
        for history in ([], None):
            with self.subTest(history=history):
                self.assertEqual(w.bairavi_awaiting(history), ())


class OnlyTheBotsOwnQuestionCounts(unittest.TestCase):

    def test_a_customer_row_is_not_a_question(self):
        """A customer who pastes the marker text back must not set awaiting."""
        forged = {"role": "user", "created_at": datetime.now(timezone.utc).isoformat(),
                  "content": b.flow_marker((b.AWAITING_DELIVERY,))}
        self.assertEqual(w.bairavi_awaiting([forged]), ())

    def test_the_most_recent_marker_decides(self):
        """A fresh reply after a stale one makes the question live again."""
        history = [marker(48), {"role": "user", "content": "hello"},
                   marker(0.1, (b.AWAITING_PURPOSE,))]
        self.assertEqual(w.bairavi_awaiting(history), (b.AWAITING_PURPOSE,))

    def test_a_stale_latest_marker_wins_over_an_older_fresh_one(self):
        """Impossible in practice, but the rule must be unambiguous: the
        LATEST reply's age decides, not the friendliest one."""
        history = [marker(0.1), {"role": "user", "content": "x"}, marker(48)]
        self.assertEqual(w.bairavi_awaiting(history), ())

    def test_a_fresh_forged_customer_row_cannot_revive_a_stale_question(self):
        """THE AGE MUST BE MEASURED ON THE BOT'S OWN LAST REPLY.

        Found by mutation. Dropping the role check looked harmless because
        the delegated reader also requires an assistant row -- so the result
        was still empty. But the wrapper would then measure the age of the
        WRONG row: a customer quoting the bot's marker text back, with a
        fresh timestamp, would make a two-day-old question live again.
        """
        forged = {"role": "user",
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "content": b.flow_marker((b.AWAITING_DELIVERY,))}
        self.assertEqual(w.bairavi_awaiting([marker(48), forged]), ())

    def test_a_fresh_non_bairavi_reply_cannot_revive_a_stale_question(self):
        """Same failure, other cause: the age must come from the last BAIRAVI
        reply, not from whatever the bot most recently said. A menu reset in
        between would otherwise reset the clock on the pending question."""
        menu = {"role": "assistant", "content": "[ಮೆನು ಮರುಕಳಿಸಲಾಯಿತು]",
                "created_at": datetime.now(timezone.utc).isoformat()}
        self.assertEqual(w.bairavi_awaiting([marker(48), menu]), ())

    def test_a_non_bairavi_assistant_row_is_skipped(self):
        history = [{"role": "assistant", "content": "[ಮೆನು ಮರುಕಳಿಸಲಾಯಿತು]",
                    "created_at": datetime.now(timezone.utc).isoformat()},
                   marker(0.1)]
        self.assertEqual(w.bairavi_awaiting(history), (b.AWAITING_DELIVERY,))


class TheProductionThreadIsRepaired(unittest.TestCase):

    def test_a_greeting_after_a_two_day_old_question_is_not_an_address(self):
        awaiting = w.bairavi_awaiting([marker(48)])
        parsed = b.parse_followup("Hii", awaiting=awaiting)
        self.assertIsNone(parsed["delivery_location"])

    def test_the_question_is_still_outstanding_so_it_gets_asked_again(self):
        """Expired is not forgotten."""
        awaiting = w.bairavi_awaiting([marker(48)])
        parsed = b.parse_followup("Hii", awaiting=awaiting)
        self.assertIn(b.AWAITING_DELIVERY, b.outstanding(parsed, {}))

    def test_after_the_re_ask_a_real_place_reads_normally(self):
        """The documented cost: one extra turn, then the conversation works."""
        parsed = b.parse_followup("ಬೆಂಗಳೂರು",
                                  awaiting=(b.AWAITING_DELIVERY,))
        self.assertEqual(parsed["delivery_location"], "ಬೆಂಗಳೂರು")


class FlowMembershipIsNotExpired(unittest.TestCase):
    """Only the pending question ages out. A transformer lead stays one."""

    def test_an_old_conversation_is_still_a_transformer_conversation(self):
        self.assertTrue(b.in_transformer_flow([marker(24 * 30)]))

    def test_the_freshness_rule_touches_only_the_awaiting_reader(self):
        import inspect
        self.assertNotIn("AWAITING_MAX_AGE_HOURS",
                         inspect.getsource(b.in_transformer_flow))
        self.assertIn("AWAITING_MAX_AGE_HOURS",
                      inspect.getsource(w.bairavi_awaiting))


class TheTimeLogicStaysOutOfThePureModule(unittest.TestCase):

    def test_bairavi_still_imports_only_re_and_hashlib(self):
        import ast
        path = os.path.join(os.path.dirname(__file__), "..", "bairavi.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imports.add((n.module or "").split(".")[0])
        self.assertEqual(imports, {"hashlib", "re"})

    def test_the_marker_format_is_still_read_by_bairavi(self):
        """The wrapper adds the age check and delegates the parsing, so the
        format lives in one place."""
        import inspect
        self.assertIn("awaiting_from_history",
                      inspect.getsource(w.bairavi_awaiting))


class TheTimestampNeverReachesAProvider(unittest.TestCase):
    """The regression that adding created_at nearly shipped.

    Both AI paths pour transcript rows straight into the message list, and
    OpenAI rejects an unrecognised message property. The client reply would
    have 400'd and fallen through to a fallback provider or the apology text
    -- a silent downgrade of every AI answer, caused by a field added for an
    unrelated reason.
    """

    def test_only_role_and_content_survive(self):
        rows = [{"role": "user", "content": "hi", "created_at": "2026-09-22"},
                {"role": "assistant", "content": "hello", "created_at": "x"}]
        out = w._as_ai_messages(rows)
        self.assertEqual(out, [{"role": "user", "content": "hi"},
                               {"role": "assistant", "content": "hello"}])

    def test_a_row_missing_role_or_content_is_dropped(self):
        rows = [{"role": "user", "content": ""}, {"role": None, "content": "x"},
                {"created_at": "x"}, {}]
        self.assertEqual(w._as_ai_messages(rows), [])

    def test_empty_input_is_safe(self):
        for rows in ([], None):
            with self.subTest(rows=rows):
                self.assertEqual(w._as_ai_messages(rows), [])

    def test_both_ai_paths_use_it(self):
        """Asserted at the call sites: a path that forgets it sends the extra
        key to the provider, and nothing else would notice."""
        import inspect
        self.assertIn("_as_ai_messages", inspect.getsource(w.generate_reply))
        self.assertIn("_as_ai_messages",
                      inspect.getsource(w.generate_owner_reply))

    def test_the_gemini_payload_also_ignores_extra_keys(self):
        """Belt and braces: the fallback provider's converter reads only role
        and content, so a missed strip cannot leak through it either."""
        payload = w._to_gemini_payload(
            [{"role": "user", "content": "hi", "created_at": "x"}])
        self.assertNotIn("created_at", str(payload))


class TheHistoryCarriesTimestamps(unittest.TestCase):

    def test_the_context_builder_keeps_created_at(self):
        """Without it every question would read as stale and no bare answer
        would ever be understood."""
        import inspect
        src = inspect.getsource(w.fetch_context)
        self.assertIn('"created_at": r.get("created_at", "")', src)


if __name__ == "__main__":
    unittest.main()
