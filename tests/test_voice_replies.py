"""Voice notes, 2026-10-01: OpenAI removed (not recharged).

Voice notes IN are transcribed by Gemini's free tier; voice replies OUT are
switched off (no free text-to-speech that WhatsApp accepts here).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import webhook as w  # noqa: E402


class R:
    def __init__(self, data, ok=True, status=200):
        self._d, self.ok, self.status_code = data, ok, status

    def json(self):
        return self._d


class TranscriptionWithGemini(unittest.TestCase):
    def run_t(self, media=(b"OggS-bytes", "audio/ogg; codecs=opus"), resp=None, key="k"):
        sent = {}

        def post(url, json=None, timeout=None):
            sent.update(url=url, body=json, timeout=timeout)
            return resp or R({"candidates": [{"content": {"parts": [{"text": " 25 kVA ಬೇಕು "}]}}]})
        with mock.patch.object(w, "GEMINI_API_KEY", key), \
             mock.patch.object(w, "download_wa_media", lambda mid, max_bytes=0: media), \
             mock.patch.object(w.requests, "post", post):
            return w.transcribe_audio("media-1"), sent

    def test_the_transcript(self):
        text, sent = self.run_t()
        self.assertEqual(text, "25 kVA ಬೇಕು")
        self.assertIn("gemini-2.5-flash:generateContent", sent["url"])
        part = sent["body"]["contents"][0]["parts"][1]["inline_data"]
        self.assertEqual(part["mime_type"], "audio/ogg")          # codecs parameter dropped
        self.assertIn("ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್", sent["body"]["contents"][0]["parts"][0]["text"])
        self.assertEqual(sent["body"]["generationConfig"]["temperature"], 0)

    def test_failures_are_empty_so_the_customer_is_asked_to_type(self):
        self.assertEqual(self.run_t(media=(None, None))[0], "")
        self.assertEqual(self.run_t(resp=R({}, ok=False, status=429))[0], "")
        self.assertEqual(self.run_t(resp=R({"candidates": []}))[0], "")
        self.assertEqual(self.run_t(key="")[0], "")


class VoiceRepliesAreOff(unittest.TestCase):
    def test_voicetest_says_so_and_sends_nothing(self):
        with mock.patch.object(w, "_wa_post", side_effect=AssertionError("sent")), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None), \
             mock.patch.object(w, "_bic_enabled", lambda: False):
            out = w.handle_owner_text("918861369951", "OWNER", "Owner", "#voicetest", {})
        self.assertIn("Voice replies are switched off", out)

    def test_no_reply_path_remains(self):
        for name in ("maybe_voice_reply", "synthesize_kannada", "send_voice_note"):
            self.assertFalse(hasattr(w, name), name)

    def test_voice_turns_still_marked(self):
        import inspect
        self.assertIn('_TURN_EXTRAS["voice"] = True', inspect.getsource(w.handler.do_POST))


if __name__ == "__main__":
    unittest.main()


class BairaviPhotos(unittest.TestCase):
    """A transformer lead's photo gets a transformer answer, not Asthra's pitch."""

    def reply(self, bairavi_lead, model_text="ಫೋಟೋದಲ್ಲಿ 25 kVA transformer nameplate ಕಾಣುತ್ತಿದೆ. ಧನ್ಯವಾದಗಳು — ನಮ್ಮ engineer ಕರೆಯಲ್ಲಿ ಪರಿಶೀಲಿಸುತ್ತಾರೆ."):
        sent = {}

        def post(url, json=None, timeout=None):
            sent["prompt"] = json["contents"][0]["parts"][0]["text"]
            return R({"candidates": [{"content": {"parts": [{"text": model_text}]}}]})
        with mock.patch.object(w, "GEMINI_API_KEY", "k"), mock.patch.object(w.requests, "post", post):
            return w.analyze_image_with_gemini(b"jpg", "image/jpeg", "", bairavi_lead=bairavi_lead), sent

    def test_bairavi_prompt(self):
        out, sent = self.reply(True)
        self.assertIn("Bairavi Trans Solutions", sent["prompt"])
        self.assertNotIn("social media", sent["prompt"])
        self.assertIn("nameplate", out)

    def test_asthra_prompt_unchanged(self):
        _, sent = self.reply(False)
        self.assertIn("Asthra DigiTech", sent["prompt"])

    def test_a_price_in_a_bairavi_photo_reply_is_refused(self):
        out, _ = self.reply(True, model_text="ಇದು 25 kVA. ಬೆಲೆ ₹95,000 ಆಗುತ್ತದೆ.")
        self.assertEqual(out, "")

    def test_the_dispatcher_asks_which_flow(self):
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn("bairavi_lead=_bairavi_photo", src)
        self.assertIn('_bairavi_photo = bairavi.in_transformer_flow(fetch_context(sender)["history"])', src)
