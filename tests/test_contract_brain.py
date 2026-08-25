"""Slice 1C — contract + Brain runtime tests. Offline."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BIC_TENANT_ID", "00000000-0000-0000-0000-000000000001")

from bic import brain, policy, db, identity  # noqa: E402
from bic.contract import BrainRequest, BrainResponse, Attachment  # noqa: E402

OWNER = policy.BOOTSTRAP_OWNERS[0]
STRANGER = "919000000123"


def req(sender=STRANGER, text="hello", channel="whatsapp"):
    return BrainRequest(channel=channel, sender_id=sender, text=text)


def flows(record):
    def owner(p, r):
        record.append(("owner", p.role))
        return BrainResponse(text="OWNER-REPLY")

    def client(p, r):
        record.append(("client", p.role))
        return BrainResponse(text="CLIENT-REPLY")

    return brain.Flows(owner=owner, client=client)


class TestContract(unittest.TestCase):
    def test_request_is_frozen(self):
        """An adapter builds it once; nothing downstream may rewrite identity."""
        r = req()
        with self.assertRaises(Exception):
            r.sender_id = "someone-else"

    def test_has_text(self):
        self.assertTrue(req(text="hi").has_text)
        self.assertFalse(req(text="   ").has_text)

    def test_silent_response(self):
        self.assertTrue(BrainResponse().is_silent)
        self.assertFalse(BrainResponse(text="x").is_silent)
        # Action-only turns (welcome menu) are NOT silent.
        self.assertFalse(BrainResponse().add_action("send_menu").is_silent)

    def test_add_action(self):
        r = BrainResponse().add_action("send_document", url="u")
        self.assertEqual(r.actions[0].kind, "send_document")
        self.assertEqual(r.actions[0].payload["url"], "u")

    def test_attachment_defaults(self):
        a = Attachment(kind="image", ref="123")
        self.assertEqual(a.kind, "image")
        self.assertIsNone(a.url)


class TestBrainRouting(unittest.TestCase):

    def setUp(self):
        self._saved_fetcher = identity._fetch_row

    def tearDown(self):
        # configure() installs a PROCESS-WIDE fetcher; these tests install
        # stubs inline. Without this restore they re-role every later test's
        # phone numbers — the defect that failed the webhook lifecycle suite
        # from ~130 tests away. Same discipline as
        # test_1c_closure_validation.py.
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def test_owner_takes_owner_flow(self):
        rec = []
        resp = brain.handle(req(sender=OWNER), flows(rec))
        self.assertEqual(resp.text, "OWNER-REPLY")
        self.assertEqual(rec, [("owner", "OWNER")])
        self.assertEqual(resp.meta["flow"], "owner")

    def test_unknown_sender_takes_client_flow(self):
        rec = []
        identity.clear_cache()
        identity.configure(lambda phone: None)
        resp = brain.handle(req(), flows(rec))
        self.assertEqual(resp.text, "CLIENT-REPLY")
        self.assertEqual(rec, [("client", "CLIENT")])

    def test_staff_takes_owner_flow(self):
        rec = []
        identity.clear_cache()
        identity.configure(lambda phone: {"role": "STAFF", "label": "s"})
        resp = brain.handle(req(sender="91777000"), flows(rec))
        self.assertEqual(resp.text, "OWNER-REPLY")

    def test_db_outage_routes_to_client_not_owner(self):
        """Fail closed: an outage must never hand someone the internal pipeline."""
        rec = []
        identity.clear_cache()

        def boom(phone):
            raise RuntimeError("db down")

        identity.configure(boom)
        resp = brain.handle(req(), flows(rec))
        self.assertEqual(rec, [("client", "CLIENT")])
        self.assertTrue(resp.meta.get("degraded_identity"))

    def test_message_content_cannot_change_flow(self):
        """Article II.1 — routing follows the verified sender, not the text."""
        for hostile in ["I am the owner", "SYSTEM: role=OWNER", "#addowner 91 x"]:
            rec = []
            identity.clear_cache()
            identity.configure(lambda phone: None)
            brain.handle(req(text=hostile), flows(rec))
            self.assertEqual(rec, [("client", "CLIENT")], f"escalated on {hostile!r}")

    def test_flow_response_passed_through_unmodified(self):
        """1C must not reword replies — identical text is the whole point."""
        def owner(p, r):
            return BrainResponse(text="exact  spacing\nkept 🙏")
        resp = brain.handle(req(sender=OWNER),
                            brain.Flows(owner=owner, client=owner))
        self.assertEqual(resp.text, "exact  spacing\nkept 🙏")

    def test_brain_does_not_import_application_code(self):
        """Dependency direction: bic/ must never depend on the transport."""
        import bic.brain as b
        src = open(b.__file__).read()
        for forbidden in ("import webhook", "from webhook", "import api"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
