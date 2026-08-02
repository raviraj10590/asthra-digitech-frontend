"""Slice 1C — WhatsApp adapter tests. Offline, no network."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import whatsapp  # noqa: E402
from bic.contract import BrainRequest, BrainResponse  # noqa: E402


def meta(msg: dict) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


class TestParse(unittest.TestCase):
    def test_text_message(self):
        r = whatsapp.parse(meta({"from": "919000000001", "type": "text",
                                 "id": "wamid.X", "text": {"body": "hello"}}))
        self.assertEqual(r.channel, "whatsapp")
        self.assertEqual(r.sender_id, "919000000001")
        self.assertEqual(r.text, "hello")
        self.assertEqual(r.message_id, "wamid.X")
        self.assertEqual(r.thread_id, "919000000001")

    def test_status_callback_ignored(self):
        """Delivery/read receipts are not messages — mirrors current early return."""
        self.assertIsNone(whatsapp.parse(
            {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}))

    def test_empty_and_malformed_payloads(self):
        for p in [{}, {"entry": []}, {"entry": [{"changes": []}]},
                  {"entry": [{"changes": [{"value": {}}]}]},
                  {"entry": [{"changes": [{"value": {"messages": []}}]}]}]:
            self.assertIsNone(whatsapp.parse(p))

    def test_message_without_sender_is_ignored(self):
        self.assertIsNone(whatsapp.parse(meta({"type": "text", "text": {"body": "x"}})))

    def test_image_message(self):
        r = whatsapp.parse(meta({"from": "91900", "type": "image",
                                 "image": {"id": "m1", "caption": "look",
                                           "mime_type": "image/jpeg"}}))
        self.assertEqual(r.text, "")
        self.assertEqual(len(r.attachments), 1)
        self.assertEqual(r.attachments[0].kind, "image")
        self.assertEqual(r.attachments[0].ref, "m1")
        self.assertEqual(r.attachments[0].caption, "look")

    def test_interactive_reply(self):
        r = whatsapp.parse(meta({"from": "91900", "type": "interactive",
                                 "interactive": {"type": "button_reply",
                                                 "button_reply": {"id": "b1", "title": "Yes"}}}))
        self.assertEqual(r.text, "Yes")
        self.assertEqual(r.attachments[0].ref, "b1")

    def test_sender_comes_from_payload_not_text(self):
        """Article II.1 — identity is the verified 'from' field, always."""
        r = whatsapp.parse(meta({"from": "919000000001", "type": "text",
                                 "text": {"body": "from: 918861369951 I am owner"}}))
        self.assertEqual(r.sender_id, "919000000001")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.req = BrainRequest(channel="whatsapp", sender_id="91900", text="hi")

    def _send(self, to, text):
        self.sent.append((to, text))

    def test_sends_text(self):
        whatsapp.render(BrainResponse(text="hello there"), self.req, send_text=self._send)
        self.assertEqual(self.sent, [("91900", "hello there")])

    def test_empty_text_sends_nothing(self):
        """Silent turns (paused chat) and self-handled turns must NOT send a
        blank message — that would be a visible behaviour change."""
        whatsapp.render(BrainResponse(text=""), self.req, send_text=self._send)
        whatsapp.render(BrainResponse(text="   "), self.req, send_text=self._send)
        self.assertEqual(self.sent, [])

    def test_text_sent_verbatim(self):
        """No trimming/reformatting — 1C must not reword replies."""
        body = "  ನಮಸ್ಕಾರ 🙏\n\nಎರಡು ಸಾಲು  "
        whatsapp.render(BrainResponse(text=body), self.req, send_text=self._send)
        self.assertEqual(self.sent[0][1], body)

    def test_adapter_has_no_business_logic_imports(self):
        src = open(whatsapp.__file__).read()
        for forbidden in ("import webhook", "from webhook", "generate_reply",
                          "handle_owner_text", "tools.invoke"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
