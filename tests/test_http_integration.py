"""HTTP integration tests for the webhook entry point.

WHY THIS FILE EXISTS
--------------------
The 2026-08-03 audit found that `do_POST` — the actual front door — was
executed by ZERO of 186 tests. Every prior test called `run_client_pipeline`
or `_bic_owner_turn` directly, bypassing the boundary.

The critical defect lived exactly there: signature verification was skipped
when META_APP_SECRET was unset, so an unsigned POST was processed as genuine.
Three code reviews missed it because they read artefacts instead of exercising
behaviour.

These tests drive the real handler with a real request body and assert on the
real HTTP status. They are still offline: every network effect is stubbed.
"""

import hashlib
import hmac
import io
import json
import os
import sys
import unittest
from contextlib import ExitStack
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("OWNER_PHONE", "918884448141,918861369951")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                # noqa: E402
from bic import identity                           # noqa: E402

OWNER = "918861369951"
CLIENT = "919555555555"
SECRET = "test-app-secret"


def wa_payload(sender=CLIENT, text="hello", msg_id="wamid.TEST1"):
    """A minimally valid Meta inbound text message."""
    return {"entry": [{"changes": [{"value": {
        "messages": [{"from": sender, "id": msg_id, "type": "text",
                      "text": {"body": text}}]}}]}]}


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _Response:
    """Captures what the handler wrote back."""

    def __init__(self):
        self.status = None
        self.headers = []
        self.body = b""


def post(payload, *, secret=SECRET, signature="valid", stubs=None, enforce=True):
    """Drive the REAL do_POST with a real body. Returns (_Response, effects).

    `signature`: "valid" | "invalid" | "missing"
    """
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload

    hdrs = Message()
    hdrs["Content-Length"] = str(len(body))
    hdrs["Content-Type"] = "application/json"
    if signature == "valid":
        hdrs["X-Hub-Signature-256"] = sign(body, secret or SECRET)
    elif signature == "invalid":
        hdrs["X-Hub-Signature-256"] = "sha256=" + "0" * 64

    # BaseHTTPRequestHandler does its work in __init__, so construct bare and
    # install only what do_POST actually touches.
    h = object.__new__(w.handler)
    h.headers = hdrs
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()

    resp = _Response()
    h.send_response = lambda code, *a: setattr(resp, "status", code)
    h.send_header = lambda k, v: resp.headers.append((k, v))
    h.end_headers = lambda: None

    effects = {"sent": [], "saved": [], "typing": []}
    env = {"WEBHOOK_AUTH_ENFORCE": "true" if enforce else "false"}
    if secret is not None:
        env["META_APP_SECRET"] = secret

    with ExitStack() as st:
        st.enter_context(mock.patch.dict(os.environ, env, clear=False))
        if secret is None:
            os.environ.pop("META_APP_SECRET", None)
        st.enter_context(mock.patch.object(w, "send_typing",
                                           lambda mid: effects["typing"].append(mid)))
        st.enter_context(mock.patch.object(w, "send_text",
                                           lambda to, t: effects["sent"].append((to, t))))
        st.enter_context(mock.patch.object(w, "save_messages",
                                           lambda i: effects["saved"].extend(i)))
        st.enter_context(mock.patch.object(w, "save_message", lambda *a: None))
        # history non-empty ⇒ a RETURNING customer. An empty history is first
        # contact, which correctly gets the welcome menu instead of an AI reply
        # — covered explicitly by test_first_contact_gets_the_welcome_menu.
        st.enter_context(mock.patch.object(w, "fetch_context", lambda s: {
            "history": [{"role": "user", "content": "prior"}],
            "paused": False, "vip_alerted": False,
            "lead_alerted": False, "recent_sys": [], "last_user": {}}))
        st.enter_context(mock.patch.object(w, "fetch_memory", lambda s: {}))
        st.enter_context(mock.patch.object(w, "maybe_alert_vip", lambda *a: None))
        st.enter_context(mock.patch.object(w, "notify_owner", lambda *a, **k: None))
        st.enter_context(mock.patch.object(w, "generate_reply", lambda *a, **k: "AI-REPLY"))
        st.enter_context(mock.patch.object(w, "generate_owner_reply",
                                           lambda *a, **k: "OWNER-REPLY"))
        st.enter_context(mock.patch.object(w, "extract_lead_info", lambda h: {}))
        st.enter_context(mock.patch.object(w, "after_hours_note", lambda: ""))
        st.enter_context(mock.patch.object(w, "send_welcome_menu",
                                           lambda s: effects["sent"].append((s, "<MENU>"))))
        st.enter_context(mock.patch.object(w, "_bic_replay_compare", lambda *a: None))
        for extra in (stubs or []):
            st.enter_context(extra)
        h.do_POST()

    return resp, effects


# ══════════════════════════════════════════════════════════════════════════
# TASK 1 — signature verification, fail closed
# ══════════════════════════════════════════════════════════════════════════
class SignatureVerification(unittest.TestCase):
    """The audit's Critical finding. Each test here would have caught it."""

    def setUp(self):
        self._saved = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)

    def tearDown(self):
        identity.configure(self._saved)
        identity.clear_cache()

    def test_unconfigured_secret_REJECTS_all_traffic(self):
        """THE regression lock. Previously `if app_secret:` skipped verification
        entirely when unset, and an unsigned POST was processed as genuine."""
        resp, effects = post(wa_payload(), secret=None, signature="missing")
        self.assertEqual(resp.status, 503,
                         "unconfigured secret must REJECT, not accept")
        self.assertEqual(effects["sent"], [], "a message was processed unauthenticated")

    def test_unsigned_request_is_rejected(self):
        resp, effects = post(wa_payload(), signature="missing")
        self.assertEqual(resp.status, 403)
        self.assertEqual(effects["sent"], [])

    def test_wrong_signature_is_rejected(self):
        resp, effects = post(wa_payload(), signature="invalid")
        self.assertEqual(resp.status, 403)
        self.assertEqual(effects["sent"], [])

    def test_signature_from_a_different_secret_is_rejected(self):
        body = json.dumps(wa_payload()).encode()
        hdrs = Message()
        hdrs["Content-Length"] = str(len(body))
        hdrs["X-Hub-Signature-256"] = sign(body, "attacker-secret")
        h = object.__new__(w.handler)
        h.headers, h.rfile, h.wfile = hdrs, io.BytesIO(body), io.BytesIO()
        resp = _Response()
        h.send_response = lambda c, *a: setattr(resp, "status", c)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        with mock.patch.dict(os.environ, {"META_APP_SECRET": SECRET,
                                          "WEBHOOK_AUTH_ENFORCE": "true"}):
            h.do_POST()
        self.assertEqual(resp.status, 403)

    def test_tampered_body_is_rejected(self):
        """Signature covers the body. Changing the sender after signing must fail."""
        original = json.dumps(wa_payload(sender=CLIENT)).encode()
        good_sig = sign(original)
        tampered = json.dumps(wa_payload(sender=OWNER)).encode()   # escalation attempt

        hdrs = Message()
        hdrs["Content-Length"] = str(len(tampered))
        hdrs["X-Hub-Signature-256"] = good_sig
        h = object.__new__(w.handler)
        h.headers, h.rfile, h.wfile = hdrs, io.BytesIO(tampered), io.BytesIO()
        resp = _Response()
        h.send_response = lambda c, *a: setattr(resp, "status", c)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        with mock.patch.dict(os.environ, {"META_APP_SECRET": SECRET,
                                          "WEBHOOK_AUTH_ENFORCE": "true"}):
            h.do_POST()
        self.assertEqual(resp.status, 403, "body tampering not detected")

    def test_valid_signature_is_accepted(self):
        resp, effects = post(wa_payload(), signature="valid")
        self.assertEqual(resp.status, 200)

    # ── OBSERVE MODE (the shipped default) ────────────────────────────────
    # Meta delivers via whatsapp-router-flame, so we do not yet know whether a
    # valid signature survives the hop. Until one real message proves it,
    # enforcement stays OFF and the endpoint only measures.

    def test_observe_mode_does_not_reject_unsigned(self):
        """The whole point: measuring must not break production."""
        resp, effects = post(wa_payload(CLIENT, "website price?"),
                             signature="missing", enforce=False)
        self.assertEqual(resp.status, 200)
        self.assertNotEqual(effects["sent"], [],
                            "observe mode must still serve the customer")

    def test_observe_mode_does_not_reject_an_unconfigured_secret(self):
        resp, effects = post(wa_payload(CLIENT, "website price?"),
                             secret=None, signature="missing", enforce=False)
        self.assertEqual(resp.status, 200)

    def test_observe_mode_emits_evidence(self):
        """Evidence is the only reason observe mode exists. If it stops being
        logged, the window can never be closed on data."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            post(wa_payload(CLIENT, "hi"), signature="valid", enforce=False)
        out = buf.getvalue()
        self.assertIn("WEBHOOK_AUTH", out, "no auth evidence emitted")
        line = [l for l in out.splitlines() if l.startswith("WEBHOOK_AUTH")][0]
        rec = json.loads(line[len("WEBHOOK_AUTH "):])
        for k in ("secret_configured", "signature_present", "signature_valid",
                  "enforcing", "body_bytes"):
            self.assertIn(k, rec, f"evidence missing {k}")
        self.assertTrue(rec["signature_valid"])
        self.assertFalse(rec["enforcing"])

    def test_evidence_carries_no_payload_content(self):
        """It is logged on every request. It must never leak message text."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            post(wa_payload(CLIENT, "SECRET-CUSTOMER-TEXT"), enforce=False)
        line = [l for l in buf.getvalue().splitlines()
                if l.startswith("WEBHOOK_AUTH")][0]
        self.assertNotIn("SECRET-CUSTOMER-TEXT", line)
        self.assertNotIn(CLIENT, line, "phone number in auth evidence")

    def test_enforcement_is_opt_in_not_default(self):
        """Shipping with enforcement ON would take the bot dark, because we do
        not yet know whether the router preserves the signature.

        NOTE: this must exercise the ACTUAL default — the env var ABSENT. The
        first version passed `enforce=False`, which sets the variable to
        "false" and therefore never tested the default at all. The mutation
        run flipped the default to "true" and the suite stayed green.
        """
        body = json.dumps(wa_payload(CLIENT, "hi")).encode()
        hdrs = Message()
        hdrs["Content-Length"] = str(len(body))
        # deliberately NO signature header
        h = object.__new__(w.handler)
        h.headers, h.rfile, h.wfile = hdrs, io.BytesIO(body), io.BytesIO()
        resp = _Response()
        h.send_response = lambda c, *a: setattr(resp, "status", c)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None

        with ExitStack() as st:
            st.enter_context(mock.patch.dict(os.environ, {}, clear=False))
            os.environ.pop("WEBHOOK_AUTH_ENFORCE", None)   # the real default
            os.environ.pop("META_APP_SECRET", None)
            for name, val in (("send_typing", lambda m: None),
                              ("send_text", lambda t, x: None),
                              ("save_messages", lambda i: None),
                              ("save_message", lambda *a: None),
                              ("fetch_memory", lambda s2: {}),
                              ("maybe_alert_vip", lambda *a: None),
                              ("notify_owner", lambda *a, **k: None),
                              ("generate_reply", lambda *a, **k: "R"),
                              ("extract_lead_info", lambda hh: {}),
                              ("after_hours_note", lambda: ""),
                              ("send_welcome_menu", lambda s2: None),
                              ("_bic_replay_compare", lambda *a: None)):
                st.enter_context(mock.patch.object(w, name, val))
            st.enter_context(mock.patch.object(w, "fetch_context", lambda s2: {
                "history": [{"role": "user", "content": "p"}], "paused": False,
                "vip_alerted": False, "lead_alerted": False,
                "recent_sys": [], "last_user": {}}))
            h.do_POST()

        self.assertEqual(resp.status, 200,
                         "default must OBSERVE, not enforce — enforcing by "
                         "default would black out production")

    def test_forged_owner_identity_cannot_reach_the_pipeline_unsigned(self):
        """The concrete attack: claim to be a bootstrap OWNER without a signature."""
        resp, effects = post(wa_payload(sender=OWNER, text="#roles"),
                             secret=None, signature="missing")
        self.assertEqual(resp.status, 503)
        self.assertEqual(effects["sent"], [], "forged owner command was executed")


# ══════════════════════════════════════════════════════════════════════════
# TASK 7 — routing, flag, legacy path, brain path, at the HTTP boundary
# ══════════════════════════════════════════════════════════════════════════
class HttpRouting(unittest.TestCase):

    def setUp(self):
        self._saved = identity._fetch_row
        identity.clear_cache()
        identity.configure(lambda p: None)       # unknown ⇒ CLIENT

    def tearDown(self):
        identity.configure(self._saved)
        identity.clear_cache()

    def _flag(self, on):
        return mock.patch.object(w, "_bic_enabled", lambda: on)

    def test_client_legacy_path(self):
        resp, e = post(wa_payload(CLIENT, "website price?"), stubs=[self._flag(False)])
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [(CLIENT, "AI-REPLY")])

    def test_client_brain_path(self):
        resp, e = post(wa_payload(CLIENT, "website price?"), stubs=[self._flag(True)])
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [(CLIENT, "AI-REPLY")])

    def test_client_paths_are_identical_across_the_flag(self):
        _, legacy = post(wa_payload(CLIENT, "website price?"), stubs=[self._flag(False)])
        _, brain = post(wa_payload(CLIENT, "website price?"), stubs=[self._flag(True)])
        self.assertEqual(legacy["sent"], brain["sent"])
        self.assertEqual(legacy["saved"], brain["saved"])

    def test_owner_legacy_path(self):
        resp, e = post(wa_payload(OWNER, "hello there"), stubs=[self._flag(False)])
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [(OWNER, "OWNER-REPLY")])

    def test_owner_brain_path(self):
        resp, e = post(wa_payload(OWNER, "hello there"), stubs=[self._flag(True)])
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [(OWNER, "OWNER-REPLY")])

    def test_owner_paths_are_identical_across_the_flag(self):
        _, legacy = post(wa_payload(OWNER, "hello there"), stubs=[self._flag(False)])
        _, brain = post(wa_payload(OWNER, "hello there"), stubs=[self._flag(True)])
        self.assertEqual(legacy["sent"], brain["sent"])

    def test_owner_and_client_fork_correctly(self):
        _, owner = post(wa_payload(OWNER, "hello there"), stubs=[self._flag(True)])
        _, client = post(wa_payload(CLIENT, "website price?"), stubs=[self._flag(True)])
        self.assertEqual(owner["sent"], [(OWNER, "OWNER-REPLY")])
        self.assertEqual(client["sent"], [(CLIENT, "AI-REPLY")])

    def test_first_contact_gets_the_welcome_menu(self):
        """Empty history is a new customer. Both paths must agree."""
        empty = mock.patch.object(w, "fetch_context", lambda s: {
            "history": [], "paused": False, "vip_alerted": False,
            "lead_alerted": False, "recent_sys": [], "last_user": {}})
        _, legacy = post(wa_payload(CLIENT, "hi"),
                         stubs=[self._flag(False), empty])
        empty2 = mock.patch.object(w, "fetch_context", lambda s: {
            "history": [], "paused": False, "vip_alerted": False,
            "lead_alerted": False, "recent_sys": [], "last_user": {}})
        _, brain = post(wa_payload(CLIENT, "hi"),
                        stubs=[self._flag(True), empty2])
        self.assertEqual(legacy["sent"], [(CLIENT, "<MENU>")])
        self.assertEqual(legacy["sent"], brain["sent"])

    def test_status_callback_is_ignored(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}
        resp, e = post(payload)
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [])

    def test_malformed_payload_does_not_crash(self):
        resp, e = post(b'{"not":"a webhook"}')
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [])

    def test_empty_message_list_is_ignored(self):
        payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
        resp, e = post(payload)
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [])

    def test_duplicate_delivery_is_suppressed(self):
        """Meta retries. The same text within the window must not be answered twice."""
        ctx = {"history": [], "paused": False, "vip_alerted": False,
               "lead_alerted": False, "recent_sys": [],
               "last_user": {"content": "website price?",
                             "created_at": "2099-01-01T00:00:00+00:00"}}
        resp, e = post(wa_payload(CLIENT, "website price?"),
                       stubs=[mock.patch.object(w, "fetch_context", lambda s: ctx)])
        self.assertEqual(resp.status, 200)
        self.assertEqual(e["sent"], [], "duplicate webhook was answered twice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
