"""Asthra ad leads got silence (live: 7 of 8, 2026-10-26..28).

The Asthra "Lead Plan Call" form arrives as Meta's handoff ("Hello! I filled
out your form ...") with business, budget, name, phone and city. Two things
went wrong with it:

1. bairavi_arrived_meanwhile() matched ANY lead form in the re-read history,
   and the turn's own message is saved before that re-read — so every Asthra
   form looked like "a Bairavi form is being answered in parallel" and the
   turn only saved the words. No reply, no owner alert.
2. Without that, a form from a new contact would have got the services menu,
   which ignores everything the form already says.

Now a non-Bairavi form goes to the AI reply, and the first contact is still
claimed. Bairavi forms are routed before any of this and are unchanged.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402
import webhook as w  # noqa: E402
from conversation import Conversation  # noqa: E402
from test_review_0927 import FORM  # noqa: E402

# Verbatim shape of the live handoff (...6148, 2026-10-28 20:28).
ASTHRA_FORM = (
    "Hello! I filled out your form and would like to know more about your business.\n\n"
    "ನಿಮ್ಮ ವ್ಯಾಪಾರ ಯಾವುದು?: Other business\n"
    "ತಿಂಗಳಿಗೆ ad ಗೆ ಎಷ್ಟು ಖರ್ಚು ಮಾಡಬಹುದು?: Under ₹10,000\n"
    "Full name: Manu Kumar\nPhone number: +918496046148\nCity: Bangalore")
# Fields in another order (...3993, 2026-10-28 08:31).
ASTHRA_FORM_2 = (
    "Hello! I filled out your form and would like to know more about your business.\n\n"
    "Full name: Kumar Kumar\nCity: Bangalore\n"
    "ತಿಂಗಳಿಗೆ ad ಗೆ ಎಷ್ಟು ಖರ್ಚು ಮಾಡಬಹುದು?: Under ₹10,000\n"
    "Phone number: +917411783993\nನಿಮ್ಮ ವ್ಯಾಪಾರ ಯಾವುದು?: Real estate")


def arrived(history):
    with mock.patch.object(w, "fetch_context", lambda p: {"history": history}), \
         mock.patch.object(w.time, "sleep", lambda s: None), \
         mock.patch.object(w, "ai_seconds_left", lambda *a: 25.0):
        return w.bairavi_arrived_meanwhile("910000000000")


class TheOwnMessageIsNotAParallelBairaviReply(unittest.TestCase):
    def test_asthra_form_alone_is_not_bairavi(self):
        self.assertFalse(arrived([{"role": "user", "content": ASTHRA_FORM}]))

    def test_bairavi_form_still_is(self):
        self.assertTrue(arrived([{"role": "user", "content": FORM.format(loc="Sira")}]))

    def test_the_forms_are_told_apart(self):
        self.assertTrue(b.is_lead_form(ASTHRA_FORM))
        self.assertFalse(b.looks_like_transformer_enquiry(ASTHRA_FORM))
        self.assertFalse(b.looks_like_transformer_enquiry(ASTHRA_FORM_2))


class AnAsthraFormGetsAnAnswer(unittest.TestCase):
    def check(self, form):
        t = Conversation(phone="918496046148").send(form)
        self.assertEqual(t["sent"], ["ASTHRA_AI_REPLY"])
        self.assertEqual(t["menu"], [])
        self.assertEqual([p for p, *_ in t["first_seen"]], ["918496046148"])
        return t

    def test_the_live_form(self):
        self.check(ASTHRA_FORM)

    def test_fields_in_another_order(self):
        self.check(ASTHRA_FORM_2)

    def test_a_plain_hi_still_gets_the_menu(self):
        t = Conversation(phone="918496046148").send("Hi")
        self.assertEqual(t["menu"], ["918496046148"])
        self.assertEqual(t["sent"], [])


if __name__ == "__main__":
    unittest.main()
