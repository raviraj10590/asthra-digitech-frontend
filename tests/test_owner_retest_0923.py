"""Four defects from the owner's own test conversation after b30c8c6 went
live, 2026-09-23 16:39 onward. Every string is what they actually typed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b                                            # noqa: E402
import webhook as w                                            # noqa: E402

DELIVERY = (b.AWAITING_DELIVERY,)
PURPOSE = (b.AWAITING_PURPOSE,)
IN_FLOW = [{"role": "assistant", "content": b.flow_marker(DELIVERY)}]


class EvAsAWholeWord(unittest.TestCase):
    """"Ev ge" (for EV) was not read as a purpose."""

    def test_the_production_message(self):
        self.assertEqual(b.parse_followup("Ev ge", awaiting=PURPOSE)
                         ["application"], "EV_CHARGING")

    def test_other_ways_of_saying_it(self):
        for text in ("EV", "ev charging", "for ev", "EV ge beku"):
            with self.subTest(text=text):
                self.assertEqual(b.parse_followup(text)["application"],
                                 "EV_CHARGING")

    def test_places_that_contain_ev_are_still_places(self):
        """Why it is whole-word only."""
        for place in ("Devanahalli", "Bevinahalli", "Nelamangala Devanahalli taluk"):
            with self.subTest(place=place):
                self.assertEqual(
                    b.parse_followup(place, awaiting=DELIVERY)["delivery_location"],
                    place)

    def test_ordinary_words_that_contain_ev_are_not_ev(self):
        for text in ("every", "never", "level", "development"):
            with self.subTest(text=text):
                self.assertIsNone(b._application_of(text))

    def test_one_reader_serves_every_caller(self):
        import inspect
        for fn in (b._parse_followup, b._is_place_like, b._form_location):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_application_of", inspect.getsource(fn))


class AbuseIsNotAnAddress(unittest.TestCase):
    """"Ninage huccha" (you are mad) was stored as the delivery address — and
    because established facts never erase, the bot stopped asking where to
    deliver for the rest of that conversation."""

    def test_the_production_message(self):
        self.assertIsNone(b.parse_followup("Ninage huccha", awaiting=DELIVERY)
                          ["delivery_location"])

    def test_the_informal_second_person(self):
        for text in ("ninage gottilla", "neenu yaaru", "ninna hesaru",
                     "nin number kodi"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text, awaiting=DELIVERY)
                                  ["delivery_location"], text)

    def test_abuse_as_the_whole_answer(self):
        for text in ("huccha", "ಹುಚ್ಚ", "stupid", "fraud", "fake"):
            with self.subTest(text=text):
                self.assertIsNone(b.parse_followup(text, awaiting=DELIVERY)
                                  ["delivery_location"], text)

    def test_the_poisoned_history_now_heals(self):
        """The replay re-reads every turn with the current rules, so the old
        insult drops out and delivery becomes outstanding again."""
        history = [{"role": "assistant", "content": b.flow_marker(DELIVERY)},
                   {"role": "user", "content": "Ninage huccha"}]
        known = b.established_from_history(history)
        self.assertIsNone(known["delivery_location"])
        # Asked with no new turn: "ok" would now be a second ignored ask,
        # and after two the owner's 2026-09-30 ruling moves on.
        self.assertIn(b.AWAITING_DELIVERY, b.outstanding({}, known))


class AGreetingDoesNotLeaveTheTransformerConversation(unittest.TestCase):
    """A Bairavi lead said "Hi" and got "ನಾನು ಆಸ್ತ್ರ AI — ನಿಮ್ಮ ಡಿಜಿಟಲ್
    ಮಾರ್ಕೆಟಿಂಗ್ ಸಹಾಯಕ" — the original failure this flow exists to prevent."""

    def test_greetings_stay_in_the_transformer_flow(self):
        for text in ("Hi", "hello", "ಹಾಯ್", "ನಮಸ್ಕಾರ"):
            with self.subTest(text=text):
                self.assertFalse(w.menu_reset_wanted(text, IN_FLOW))

    def test_ordinary_answers_that_are_menu_keywords_stay_too(self):
        """"home" is a menu keyword and also a transformer customer's answer."""
        for text in ("home", "services", "start"):
            with self.subTest(text=text):
                self.assertFalse(w.menu_reset_wanted(text, IN_FLOW))

    def test_an_explicit_menu_request_still_resets(self):
        for text in ("menu", "ಮೆನು", "main menu", "restart"):
            with self.subTest(text=text):
                self.assertTrue(w.menu_reset_wanted(text, IN_FLOW))

    def test_outside_the_flow_nothing_changes(self):
        for text in ("Hi", "hello", "menu", "home"):
            with self.subTest(text=text):
                self.assertEqual(w.menu_reset_wanted(text, []),
                                 w.is_menu_request(text))

    def test_the_webhook_uses_it(self):
        import inspect
        self.assertIn("menu_reset_wanted(user_text, ctx[\"history\"])",
                      inspect.getsource(w.run_client_pipeline))


class SizingIsTheEngineersCall(unittest.TestCase):
    """The model told the owner "100 kVA ... EV charging ಗೆ suitable ಆಗಿದೆ".
    Whether a rating carries a load depends on the load."""

    def test_the_production_reply_is_refused(self):
        self.assertEqual(b.reply_violates_evidence(
            "ನಮಸ್ಕಾರ ರವಿರಾಜ್, 100 kVA transformer ಲಭ್ಯವಿದೆ, EV charging ಗೆ "
            "suitable ಆಗಿದೆ."), "a sizing claim")

    def test_every_form_of_the_claim(self):
        for text in ("100 kVA is sufficient", "enough for your pump",
                     "ನಿಮ್ಮ 100 HP ಪಂಪ್‌ಗೆ ಸೂಕ್ತ", "25 kVA ಸಾಕಾಗುತ್ತದೆ"):
            with self.subTest(text=text):
                self.assertEqual(b.reply_violates_evidence(text),
                                 "a sizing claim")

    def test_the_brief_says_so(self):
        self.assertIn("engineer", b.model_brief_kn().split("11.")[1])


if __name__ == "__main__":
    unittest.main()
