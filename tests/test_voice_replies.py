"""Kannada voice replies (owner request 2026-10-01)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402
import webhook as w  # noqa: E402

REPLY = ("ಸರಿ Sudarshan Gowda ಅವರೇ. ನಮ್ಮ engineer *ಈಗಲೇ* ನಿಮಗೆ ಕರೆ ಮಾಡಿ.\n"
         "ಧನ್ಯವಾದಗಳು 🙏")


class SpeechText(unittest.TestCase):
    def test_formatting_and_emoji_are_not_read_aloud(self):
        self.assertEqual(b.speech_text(REPLY),
                         "ಸರಿ Sudarshan Gowda ಅವರೇ. ನಮ್ಮ engineer ಈಗಲೇ ನಿಮಗೆ ಕರೆ ಮಾಡಿ. ಧನ್ಯವಾದಗಳು.")

    def test_choices_read_as_numbers(self):
        self.assertEqual(b.speech_text("ಯಾವಾಗ ಅನುಕೂಲ?\n1️⃣ ಈಗಲೇ\n2️⃣ ಇಂದು ಸಂಜೆ\n\n3️⃣ ನಾಳೆ"),
                         "ಯಾವಾಗ ಅನುಕೂಲ? 1. ಈಗಲೇ. 2. ಇಂದು ಸಂಜೆ. 3. ನಾಳೆ.")

    def test_links_dropped_and_length_capped(self):
        self.assertNotIn("http", b.speech_text("ನೋಡಿ https://example.com ಇಲ್ಲಿ"))
        long = b.speech_text("ಪದ " * 400)
        self.assertLessEqual(len(long), b.VOICE_MAX_CHARS)

    def test_empty(self):
        self.assertEqual(b.speech_text("🙏"), "")


class WhenAVoiceNoteIsSent(unittest.TestCase):
    def run_voice(self, voice=True, flag="on", seconds=20.0, tts=b"OggS...", sent_ok=True):
        calls = []
        with mock.patch.dict(os.environ, {"VOICE_REPLIES": flag}), \
             mock.patch.dict(w._TURN_EXTRAS, {"voice": voice}, clear=True), \
             mock.patch.object(w, "ai_seconds_left", lambda *a: seconds), \
             mock.patch.object(w, "synthesize_kannada", lambda t: calls.append(("tts", t)) or tts), \
             mock.patch.object(w, "send_voice_note", lambda to, a: calls.append(("send", to)) or sent_ok):
            return w.maybe_voice_reply("919000005711", REPLY), calls

    def test_sent_when_everything_holds(self):
        ok, calls = self.run_voice()
        self.assertTrue(ok)
        self.assertEqual(calls[0], ("tts", b.speech_text(REPLY)))
        self.assertEqual(calls[1], ("send", "919000005711"))

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VOICE_REPLIES", None)
            self.assertFalse(w.voice_replies_on())
        self.assertEqual(self.run_voice(flag="")[1], [])

    def test_only_for_customers_who_spoke(self):
        self.assertEqual(self.run_voice(voice=False)[1], [])

    def test_never_past_the_turn_deadline(self):
        self.assertEqual(self.run_voice(seconds=5.0)[1], [])

    def test_a_failed_synthesis_sends_nothing(self):
        ok, calls = self.run_voice(tts=b"")
        self.assertFalse(ok)
        self.assertEqual([c[0] for c in calls], ["tts"])


class TheVoiceTestCommand(unittest.TestCase):
    def test_goes_to_the_requester_only(self):
        sent = []
        with mock.patch.object(w, "synthesize_kannada", lambda t: b"OggS"), \
             mock.patch.object(w, "send_voice_note", lambda to, a: sent.append(to) or True), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None), \
             mock.patch.object(w, "_bic_enabled", lambda: False):
            out = w.handle_owner_text("918861369951", "OWNER", "Owner", "#voicetest ನಮಸ್ಕಾರ", {})
        self.assertEqual(sent, ["918861369951"])
        self.assertIn("Sample sent", out)


class TheDispatcher(unittest.TestCase):
    def test_voice_turns_are_marked_and_replied_after_the_writes(self):
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn('_TURN_EXTRAS["voice"] = True', src)
        pipe = inspect.getsource(w.run_client_pipeline)
        self.assertLess(pipe.index("notify_owner(alert)"), pipe.index("maybe_voice_reply(sender, _reply)"))

    def test_whisper_hears_transformer_words(self):
        import inspect
        self.assertIn("ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್, 25 kVA", inspect.getsource(w.transcribe_audio))


if __name__ == "__main__":
    unittest.main()
