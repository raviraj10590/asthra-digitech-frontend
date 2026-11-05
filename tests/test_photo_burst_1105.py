"""Asthra customer photos are answered inside the chat, once per burst.

2026-11-05, live: a Meta lead (manufacturing, Belagavi) sent his visiting card
and logo right after the bot's first reply. He got three messages in a minute:
a generic "type your question" for an unreadable part of the burst, then one
standalone vision reply per photo. Neither reply knew the chat, and the next
reply asked "what do you want to promote?" with the card's four businesses
already in hand.

Now a photo becomes a transcript line, the normal pipeline replies, only the
newest photo of a burst replies, and the unreadable-type ack is skipped
mid-conversation.
"""

import datetime as dt
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                     # noqa: E402
from tests.test_webhook_lifecycle import (              # noqa: E402
    Base, CUSTOMER, media_msg, unreadable_msg)

CARD = "Visiting card of Shakti Devi Groups: truck-trailer, auto steels, tyre alignment, restaurant."


def _now_iso(minutes_ago=0):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return t.isoformat()


class Helpers(unittest.TestCase):

    def test_turn_text_carries_facts_and_caption(self):
        line = w.image_turn_text(CARD, " rate? ")
        self.assertIn("ಫೋಟೋದಲ್ಲಿ: " + CARD, line)
        self.assertTrue(line.endswith("rate?"))

    def test_superseded_only_by_a_different_newer_line(self):
        own = w.image_turn_text(CARD)
        self.assertFalse(w.superseded_by_newer({"last_user": {"content": own}}, own))
        self.assertTrue(w.superseded_by_newer({"last_user": {"content": "[logo]"}}, own))
        self.assertFalse(w.superseded_by_newer({"last_user": {}}, own))

    def test_drop_own_line_keeps_sibling_photos(self):
        own = w.image_turn_text(CARD)
        hist = [{"role": "user", "content": "[logo]"}, {"role": "user", "content": own}]
        self.assertEqual(w.drop_own_line(hist, own), [{"role": "user", "content": "[logo]"}])

    def test_chat_active_window(self):
        self.assertTrue(w.chat_active([{"created_at": _now_iso(1)}]))
        self.assertFalse(w.chat_active([{"created_at": _now_iso(30)}]))
        self.assertFalse(w.chat_active([]))

    def test_prompt_tells_model_to_use_the_photo(self):
        self.assertIn("ಗ್ರಾಹಕರು ಫೋಟೋ ಕಳುಹಿಸಿದ್ದಾರೆ", w.SYSTEM_PROMPT if hasattr(w, "SYSTEM_PROMPT")
                      else open(w.__file__, encoding="utf-8").read())


class PhotoFlow(Base):

    def setUp(self):
        super().setUp()
        self.pipeline = []
        self.saved = []
        self.ctx = {"history": [], "last_user": {}}
        for p in [
            mock.patch.object(w, "download_wa_media", lambda *a, **k: (b"jpg", "image/jpeg")),
            mock.patch.object(w, "describe_image_facts", lambda *a, **k: CARD),
            mock.patch.object(w, "IMAGE_BURST_WAIT_S", 0),
            mock.patch.object(w, "get_role", lambda s: ("customer", "")),
            mock.patch.object(w, "fetch_context", lambda *a, **k: self.ctx),
            mock.patch.object(w, "save_messages", lambda items: self.saved.extend(items)),
            mock.patch.object(w, "run_client_pipeline",
                              lambda s, t, c, **k: self.pipeline.append((t, c["history"]))),
        ]:
            p.start()
            self._p.append(p)

    def test_photo_goes_through_the_chat_pipeline(self):
        own = w.image_turn_text(CARD)
        self.ctx = {"history": [{"role": "user", "content": own}],
                    "last_user": {"content": own}}
        self.post(media_msg("image"))
        self.assertEqual(self.sent, [], "no standalone vision reply")
        self.assertEqual(len(self.pipeline), 1)
        text, hist = self.pipeline[0]
        self.assertEqual(text, own)
        self.assertEqual(hist, [], "own line is the message, not history")
        self.assertEqual(sum(1 for i in self.saved if i[2] == own), 1, "saved once")

    def test_older_photo_of_a_burst_stays_quiet(self):
        self.ctx = {"history": [], "last_user": {"content": "[a newer photo]"}}
        self.post(media_msg("image"))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.pipeline, [])

    def test_unreadable_mid_chat_gets_no_generic_ack(self):
        self.ctx = {"history": [{"role": "assistant", "content": "Hi sir",
                                 "created_at": _now_iso(0)}], "last_user": {}}
        self.post(unreadable_msg())
        self.assertEqual(self.sent, [])

    def test_unreadable_out_of_the_blue_still_acked(self):
        self.post(unreadable_msg())
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], CUSTOMER)


if __name__ == "__main__":
    unittest.main()
