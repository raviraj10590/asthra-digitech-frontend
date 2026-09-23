"""Seven defects from the last ten client conversations, reviewed 2026-09-23.

Every string below is a real customer message from production. Each class
of defect was confirmed on the tree AFTER the previous fixes (e0bedf6), so
none of these is a duplicate of work already done.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
PURPOSE = (b.AWAITING_PURPOSE,)
ALL = (b.AWAITING_DELIVERY, b.AWAITING_PURPOSE, b.AWAITING_QUANTITY)


def form(location):
    return ("Hello! I filled out your form and would like to know more.\n\n"
            "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: A. 25 kVA\n"
            f"ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: {location}\n"
            "Full name: Test Person\nPhone number: +910000000000")


class A_ABorewellIsAPurpose(unittest.TestCase):
    """"ಬೋರ್ ವೆಲ್ ಉದ್ದೇಶ" (borewell purpose) was stored as the DELIVERY
    address, and the purpose was then asked for again."""

    def test_the_production_message(self):
        f = b.parse_followup("ಬೋರ್ ವೆಲ್ ಉದ್ದೇಶ", awaiting=ALL)
        self.assertEqual(f["application"], "AGRICULTURE")
        self.assertIsNone(f["delivery_location"])

    def test_every_spelling(self):
        for text in ("borewell", "bore well", "ಬೋರ್ ವೆಲ್", "ಬೋರ್‌ವೆಲ್",
                     "ಬೋರ್ವೆಲ್", "ಕೊಳವೆ ಬಾವಿ", "ಕೊಳವೆಬಾವಿ", "ಪಂಪ್ ಸೆಟ್",
                     "ನೀರಾವರಿ", "irrigation"):
            with self.subTest(text=text):
                self.assertEqual(b.parse_followup(text)["application"],
                                 "AGRICULTURE")


class B_KannadaScriptLoanWords(unittest.TestCase):
    """"ಅಗ್ರಿಕಲ್ಚರ್" was not read, so a customer who had given the purpose
    twice was asked for it a third time."""

    def test_the_production_message(self):
        self.assertEqual(
            b.parse_followup("ಅಗ್ರಿಕಲ್ಚರ್", awaiting=PURPOSE)["application"],
            "AGRICULTURE")

    def test_the_other_loan_words(self):
        for text, want in (("ಇಂಡಸ್ಟ್ರಿ", "INDUSTRY"), ("ಫ್ಯಾಕ್ಟರಿ", "INDUSTRY"),
                           ("ಕಮರ್ಷಿಯಲ್", "COMMERCIAL"), ("ಶಾಪ್", "COMMERCIAL"),
                           ("ಕನ್ಸ್ಟ್ರಕ್ಷನ್", "CONSTRUCTION"),
                           ("ವ್ಯವಸಾಯ", "AGRICULTURE")):
            with self.subTest(text=text):
                self.assertEqual(b.parse_followup(text)["application"], want)

    def test_agrahara_is_not_agriculture(self):
        """"ಅಗ್ರಿ" must not swallow "ಅಗ್ರಹಾರ", one of the commonest place
        endings in Karnataka. They diverge after "ರ"."""
        self.assertIsNone(b.parse_followup("ಅಗ್ರಹಾರ")["application"])
        self.assertEqual(
            b.parse_followup("ಬಸವನಗುಡಿ ಅಗ್ರಹಾರ", awaiting=DELIVERY)
            ["delivery_location"], "ಬಸವನಗುಡಿ ಅಗ್ರಹಾರ")


class C_KvInKannadaLetters(unittest.TestCase):
    """"25 ಕೆವಿ ದರ ಏನಿದೆ" (what is the 25 kV rate?) was read as a quantity of
    TWENTY-FIVE units and no capacity."""

    def test_the_production_message(self):
        f = b.parse_followup("25 ಕೆವಿ ದರ ಏನಿದೆ", awaiting=ALL)
        self.assertIsNone(f["quantity"])
        self.assertEqual(f["capacity_kva"], 25)
        self.assertTrue(f["asked_price"])

    def test_every_spelling_is_a_capacity_and_never_a_count(self):
        for text in ("25 ಕೆವಿ", "25 ಕೆ.ವಿ", "25 ಕೆವಿಎ", "25 ಕೆ.ವಿ.ಎ",
                     "63 ಕೆವಿಎ", "100 ಕೆ ವಿ"):
            with self.subTest(text=text):
                self.assertIsNotNone(b.capacity_kva(text))
                self.assertIsNone(b.parse_followup(text)["quantity"])

    def test_a_voltage_in_kannada_is_not_a_count_either(self):
        """The case where the measurement entry is the ONLY defence. 11 kV is
        not a product, so no capacity is read and the capacity-equality skip
        never runs — without "ಕೆವಿ" in the measurement table, "11" became a
        quantity of eleven. Found by mutation: every catalogue case passed
        without it."""
        self.assertIsNone(b.parse_followup("11 ಕೆವಿ ಲೈನ್")["quantity"])
        self.assertIsNone(b.parse_followup("33 ಕೆ.ವಿ line")["quantity"])

    def test_the_voltage_rule_still_holds(self):
        """11 kV is a line voltage, not an 11 kVA transformer — in either
        script."""
        self.assertIsNone(b.capacity_kva("11 ಕೆವಿ ಲೈನ್"))
        self.assertIsNone(b.capacity_kva("11kv line"))

    def test_the_longest_spelling_is_rewritten_first(self):
        self.assertEqual(b._latin_kv("25 ಕೆವಿಎ"), "25 kva")
        self.assertEqual(b._latin_kv("25 ಕೆ.ವಿ.ಎ"), "25 kva")


class D_TheFormsLocationField(unittest.TestCase):
    """The ad form's location answer is free text, and customers answer a
    different question in it. "home" and "ಅಗ್ರಿಕಲ್ಚರ್" were echoed back as
    the location and offered as the delivery place."""

    def test_home_is_not_a_location(self):
        self.assertIsNone(b.parse(form("home"))["location"])

    def test_a_purpose_in_the_location_field_becomes_the_purpose(self):
        p = b.parse(form("ಅಗ್ರಿಕಲ್ಚರ್"))
        self.assertIsNone(p["location"])
        self.assertEqual(p["application"], "AGRICULTURE")

    def test_real_locations_are_untouched(self):
        for loc in ("kadur", "Sorab", "kushtagi", "tumkur",
                    "Tumkur ..Gubbi.Tq. Chelur"):
            with self.subTest(loc=loc):
                self.assertEqual(b.parse(form(loc))["location"], loc)

    def test_a_dropped_location_does_not_mark_the_form_unreadable(self):
        """form_unreadable means the LABELS changed. A junk answer is not
        that, so it is judged on the raw field."""
        self.assertFalse(b.parse(form("home"))["form_unreadable"])

    def test_unreadable_is_judged_on_the_raw_answer(self):
        """A form with no capacity, no timing and a junk location is still a
        form whose labels were read. The first version of the test above
        carried a capacity, which made this condition untestable."""
        bare = ("Hello! I filled out your form.\n\n"
                "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: home\n"
                "Full name: Test Person\nPhone number: +910000000000")
        p = b.parse(bare)
        self.assertIsNone(p["location"])
        self.assertFalse(p["form_unreadable"])

    def test_the_opening_reply_does_not_confirm_nonsense(self):
        reply = b.compose_reply(b.parse(form("home")))
        self.assertNotIn("home", reply)


class E_AnAddressThatNamesItsDistrict(unittest.TestCase):
    """"ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು,ಚಿತ್ರದುರ್ಗ ಜಿಲ್ಲೆ" arrived when the bot was
    not waiting for a place, was not read, and the next reply asked where to
    deliver. The customer then sent it again."""

    TEXT = "ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು,ಚಿತ್ರದುರ್ಗ ಜಿಲ್ಲೆ"

    def test_read_even_when_delivery_was_not_asked(self):
        self.assertEqual(
            b.parse_followup(self.TEXT, awaiting=PURPOSE)["delivery_location"],
            self.TEXT)

    def test_english_administrative_words_too(self):
        text = "Hiriyur taluk Chitradurga district"
        self.assertEqual(b.parse_followup(text)["delivery_location"], text)

    def test_a_bare_place_name_still_needs_the_question(self):
        """The rule is unchanged for text that does not say it is an
        address — "Gokak" mid-conversation could be anything."""
        self.assertIsNone(b.parse_followup("Gokak", awaiting=PURPOSE)
                          ["delivery_location"])
        self.assertEqual(b.parse_followup("Gokak", awaiting=DELIVERY)
                         ["delivery_location"], "Gokak")

    def test_only_administrative_markers_count_without_the_question(self):
        """"road" or "main" alone are not enough to call something an
        address when nobody asked for one."""
        self.assertIsNone(b.parse_followup("main road", awaiting=PURPOSE)
                          ["delivery_location"])

    def test_a_marker_must_be_a_whole_word(self):
        """"dist" sits inside "distributor"; "village" inside "villages" is
        not the marker either. Matched as substrings, "Kadaba distributor"
        became a delivery address."""
        for text in ("Kadaba distributor", "tqm certified"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text, awaiting=PURPOSE)
                                  ["delivery_location"], text)

    def test_a_sentence_with_a_marker_is_still_refused(self):
        self.assertIsNone(b.parse_followup(
            "nimma district yaavudu", awaiting=PURPOSE)["delivery_location"])


class F_ATruncatedReplyIsNotSent(unittest.TestCase):
    """Two customers were sent sentences that simply stop: "ನಮಸ್ತೆ Kariyanna
    ಅವರೇ, ನಿಮ್ಮ 25" and "ಗೋಕಾಕ್‌ನಲ್ಲಿರುವ ನಿಮ್ಮ ಅಗ್ರಿಕಲ್ಚರ್ ಪ್ರಾಜೆಕ್ಟ್‌". The
    providers printed a warning and returned the fragment anyway."""

    def _run(self, reply, truncated):
        f = b.parse_followup("who are you?", awaiting=DELIVERY)

        def fake(messages, apology, max_tokens=None):
            w._LAST_AI_TRUNCATED["value"] = truncated
            return reply

        with mock.patch.object(w, "_generate_ai_reply", side_effect=fake):
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = w.bairavi_model_reply("919000000000", "who are you?",
                                            [], f, {})
        return out, buf.getvalue()

    def test_a_cut_reply_is_refused_whole(self):
        out, log = self._run("ನಮಸ್ತೆ Kariyanna ಅವರೇ, ನಿಮ್ಮ 25", truncated=True)
        self.assertEqual(out, "")
        self.assertIn("reason='truncated'", log)

    def test_the_refusal_log_carries_neither_phone_nor_text(self):
        _, log = self._run("ನಮಸ್ತೆ Kariyanna ಅವರೇ, ನಿಮ್ಮ 25", truncated=True)
        self.assertNotIn("919000000000", log)
        self.assertNotIn("Kariyanna", log)

    def test_a_finished_reply_still_goes_out(self):
        out, _ = self._run("We are Bairavi Trans Solutions, Kadaba.",
                           truncated=False)
        self.assertIn("Bairavi", out)

    def test_the_flag_is_reset_on_every_call(self):
        """A truncation on one turn must not poison the next."""
        w._LAST_AI_TRUNCATED["value"] = True
        with mock.patch.object(w, "_provider_chain",
                               return_value=[("x", lambda m, t: "done.")]):
            w._generate_ai_reply([{"role": "user", "content": "hi"}], "")
        self.assertFalse(w._LAST_AI_TRUNCATED["value"])

    def test_every_provider_raises_the_flag(self):
        import inspect
        for fn in (w._call_deepseek, w._call_openai, w.generate_reply_gemini):
            with self.subTest(fn=fn.__name__):
                self.assertIn('_LAST_AI_TRUNCATED["value"] = True',
                              inspect.getsource(fn))

    def test_the_budget_leaves_room_to_finish(self):
        self.assertGreaterEqual(w.BAIRAVI_MODEL_MAX_TOKENS, 1000)


class G_RowsWrittenInTheSameInstant(unittest.TestCase):
    """save_messages writes the customer's row and the reply's marker in one
    insert, so they share created_at to the millisecond. Ordered by time
    alone, the marker sometimes came first, and the replay read the answer
    against the NEXT question: "Gokak" was acknowledged as the delivery place
    and then asked for again one turn later."""

    def test_the_history_query_breaks_ties_by_id(self):
        import inspect
        self.assertIn('"order":  "created_at.desc,id.desc"',
                      inspect.getsource(w.fetch_context))

    def test_why_order_matters(self):
        """The mechanism, shown directly: the same two rows, the same facts,
        opposite outcomes depending only on their order."""
        asked = {"role": "assistant",
                 "content": b.flow_marker((b.AWAITING_DELIVERY,))}
        answer = {"role": "user", "content": "Gokak"}
        after = {"role": "assistant",
                 "content": b.flow_marker((b.AWAITING_PURPOSE,))}
        right = b.established_from_history([asked, answer, after])
        wrong = b.established_from_history([asked, after, answer])
        self.assertEqual(right["delivery_location"], "Gokak")
        self.assertIsNone(wrong["delivery_location"])


if __name__ == "__main__":
    unittest.main()
