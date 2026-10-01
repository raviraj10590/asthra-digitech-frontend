"""The same reply must not be sent twice in a row.

MEASURED, 2026-09-22. In the 21 days to that date, six conversations
received a byte-identical bot reply twice within 65 seconds -- one of them
three times in about 30 seconds, another the full 324-character block twice.

WHY IT HAPPENS. The module is stateless by design and its docstring chose
this on purpose: "a customer who twice says something unreadable is
therefore asked twice -- which is the right failure, because the alternative
is the silence that lost this enquiry." For the QUESTION that reasoning
holds. For the 324-character block around it, it does not: the customer
already has that text on screen, and a bot that repeats itself verbatim
reads as broken.

SO THE QUESTION IS STILL ASKED, AND ONLY THE QUESTION. Nothing is
suppressed -- silence would be worse than repetition, and after the CRM
insert-ordering confusion of this same review it would also be invisible.

NOT A NEW STORE. The reply's identity rides in the flow marker the
transcript already carries, like awaiting= and quote_signalled=1 before it.
A serverless function keeps no memory between invocations, so in-process
state was never an option.
"""
import unittest
import bairavi as b

KNOWN = {"capacity_kva": 100, "location": "kushtagi"}


class TheFingerprintIdentifiesAReply(unittest.TestCase):

    def test_it_is_stable(self):
        self.assertEqual(b.reply_fingerprint("hello"),
                         b.reply_fingerprint("hello"))

    def test_it_ignores_only_surrounding_whitespace(self):
        self.assertEqual(b.reply_fingerprint(" hello "),
                         b.reply_fingerprint("hello"))

    def test_two_replies_differing_by_one_field_are_different(self):
        """The case that must not collide: the same block asking for one
        field versus two is a genuinely different reply."""
        one = b.compose_followup_reply(
            b.parse_followup("agriculture", awaiting=(b.AWAITING_DELIVERY,)),
            KNOWN)
        two = b.compose_followup_reply(
            b.parse_followup("blah", awaiting=(b.AWAITING_DELIVERY,)), KNOWN)
        self.assertNotEqual(b.reply_fingerprint(one), b.reply_fingerprint(two))

    def test_empty_and_none_do_not_crash(self):
        self.assertEqual(b.reply_fingerprint(""), b.reply_fingerprint(None))

    def test_it_is_long_enough_that_collisions_do_not_matter(self):
        """A short fingerprint collides, and a collision sends the terse
        reply when the full one was due. Ten hex characters is ~10^12
        values; a single character would be sixteen."""
        self.assertEqual(len(b.reply_fingerprint("anything")), 10)


class TheMarkerCarriesIt(unittest.TestCase):

    def test_the_marker_records_the_reply(self):
        marker = b.flow_marker((b.AWAITING_DELIVERY,), False, "some reply")
        self.assertIn("reply=" + b.reply_fingerprint("some reply"), marker)

    def test_it_is_read_back(self):
        marker = b.flow_marker((b.AWAITING_DELIVERY,), False, "some reply")
        self.assertEqual(b.marker_reply(marker),
                         b.reply_fingerprint("some reply"))

    def test_a_marker_without_one_reads_as_none(self):
        """Every marker written before this change, and the nudge sweep's."""
        self.assertIsNone(b.marker_reply(b.flow_marker((b.AWAITING_DELIVERY,))))
        self.assertIsNone(b.marker_reply("not a marker at all"))
        self.assertIsNone(b.marker_reply(""))

    def test_a_reply_token_without_a_flow_marker_is_not_trusted(self):
        """Both conditions are required. A customer can type anything,
        including "reply=deadbeef01", and it must not be read as the bot's
        own last reply -- which would silence the next real question."""
        self.assertIsNone(b.marker_reply("reply=deadbeef01"))
        self.assertIsNone(b.marker_reply("my address is reply=abc123"))

    def test_the_existing_readers_are_unaffected(self):
        """awaiting= and quote_signalled=1 must survive the new token, since
        the hourly nudge and the duplicate-alert guard both read them."""
        marker = b.flow_marker((b.AWAITING_DELIVERY, b.AWAITING_PURPOSE),
                               True, "some reply")
        self.assertEqual(b.marker_awaiting(marker),
                         (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE))
        self.assertTrue(b.quote_already_signalled(
            [{"role": "assistant", "content": marker}]))

    def test_the_fingerprint_comes_from_the_latest_reply(self):
        history = [
            {"role": "assistant",
             "content": b.flow_marker((b.AWAITING_DELIVERY,), False, "older")},
            {"role": "user", "content": "something"},
            {"role": "assistant",
             "content": b.flow_marker((b.AWAITING_DELIVERY,), False, "newer")},
        ]
        self.assertEqual(b.last_reply_fingerprint(history),
                         b.reply_fingerprint("newer"))

    def test_only_assistant_rows_are_consulted(self):
        """A customer who pastes the marker text back must not be read as the
        bot's own reply -- the same rule awaiting_from_history already has."""
        forged = b.flow_marker((b.AWAITING_DELIVERY,), False, "forged")
        self.assertIsNone(b.last_reply_fingerprint(
            [{"role": "user", "content": forged}]))

    def test_an_empty_history_is_none(self):
        for history in ([], None, [{"role": "user", "content": "hi"}]):
            with self.subTest(history=history):
                self.assertIsNone(b.last_reply_fingerprint(history))


class ARepeatBecomesTheQuestionAlone(unittest.TestCase):

    def setUp(self):
        self.followup = b.parse_followup("blah", awaiting=(b.AWAITING_DELIVERY,))
        self.full = b.compose_followup_reply(self.followup, KNOWN)

    def test_without_a_fingerprint_nothing_changes(self):
        """Additive: every existing caller keeps its exact behaviour."""
        self.assertEqual(b.compose_followup_reply(self.followup, KNOWN),
                         self.full)
        self.assertEqual(
            b.compose_followup_reply(self.followup, KNOWN, None, None),
            self.full)

    def test_a_different_previous_reply_still_sends_the_full_one(self):
        self.assertEqual(
            b.compose_followup_reply(self.followup, KNOWN, None,
                                     b.reply_fingerprint("something else")),
            self.full)

    def test_an_identical_previous_reply_sends_the_short_one(self):
        short = b.compose_followup_reply(self.followup, KNOWN, None,
                                         b.reply_fingerprint(self.full))
        self.assertNotEqual(short, self.full)
        self.assertLess(len(short), len(self.full))

    def test_the_short_reply_still_asks_the_question(self):
        """Nothing is suppressed. The outstanding field is still asked, in the
        wording question_for() already owns."""
        short = b.compose_followup_reply(self.followup, KNOWN, None,
                                         b.reply_fingerprint(self.full))
        outstanding = b.outstanding(self.followup, KNOWN)
        self.assertTrue(outstanding)
        self.assertIn(b.question_for(outstanding[0], KNOWN), short)

    def test_the_short_reply_is_never_empty(self):
        """Silence would be worse than repetition, and after this review's
        CRM insert-ordering confusion it would also look like a dead bot."""
        for followup in (b.parse_followup("blah", awaiting=(b.AWAITING_DELIVERY,)),
                         b.parse_followup("kushtagi", awaiting=(b.AWAITING_DELIVERY,)),
                         b.parse_followup("", awaiting=())):
            with self.subTest(followup=followup):
                reply = b.compose_short_reask(followup, KNOWN)
                self.assertTrue(reply.strip())

    def test_nothing_outstanding_still_gets_a_courteous_close(self):
        complete = b.parse_followup("kushtagi", awaiting=(b.AWAITING_DELIVERY,))
        known = dict(KNOWN, application="AGRICULTURE", quantity=2,
                     delivery_location="kushtagi")
        reply = b.compose_short_reask(complete, known)
        self.assertIn("Bairavi", reply)

    def test_the_short_reply_quotes_no_price_or_certificate(self):
        short = b.compose_short_reask(self.followup, KNOWN)
        for banned in ("₹", "68,244", "ISO", "BIS", "MESCOM approval"):
            self.assertNotIn(banned, short)


class TheGuardLivesInOnePlace(unittest.TestCase):

    def test_the_check_is_inside_the_composer(self):
        """So no caller can send a repeat by forgetting to ask."""
        import inspect
        src = inspect.getsource(b._compose_followup_reply)
        self.assertIn("last_fingerprint", src)
        self.assertIn("compose_short_reask", src)

    def test_the_webhook_passes_the_previous_fingerprint(self):
        """Asserted at the call site: a mutation that stops passing it
        changes nothing any unit test of this module can see."""
        import ast, io as _io, os
        path = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")
        tree = ast.parse(_io.open(path, encoding="utf-8").read())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "compose_followup_reply"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[3].func.attr, "last_reply_fingerprint")

    def test_the_webhook_records_the_reply_that_went_out(self):
        """The marker must carry the reply actually sent, or the next turn
        compares against the wrong thing."""
        import ast, io as _io, os
        path = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")
        tree = ast.parse(_io.open(path, encoding="utf-8").read())
        markers = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "flow_marker"
                   and any(k.arg == "reply" for k in n.keywords)]
        self.assertEqual(len(markers), 1)
        self.assertEqual(
            [k.value.id for k in markers[0].keywords if k.arg == "reply"],
            ["_reply"])


if __name__ == "__main__":
    unittest.main()
