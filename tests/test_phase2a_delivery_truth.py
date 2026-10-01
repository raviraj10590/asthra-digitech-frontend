"""Phase 2A — WhatsApp delivery truth and message persistence (2026-10-01).

Before this phase:
  * _wa_post returned a 4xx without raising, so a rejected reply was a
    COMPLETED delivery and was mirrored to the CRM as status "sent";
  * the Bairavi path wrote a FLOW_MARKER for a reply that may never have
    reached the customer, so their next message was read against a question
    they never saw;
  * the customer's own message was saved only AFTER the reply, together with
    it, in one un-retried write.

Tests A-I, each named for the case it covers. Offline: no network, no AI, no
database. Every key below is a fixture.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import requests                                         # noqa: E402
import webhook as w                                     # noqa: E402
import fake_send                                        # noqa: E402
from bic import webhook_events as ev                    # noqa: E402
from conversation import Conversation, lead_form        # noqa: E402
from tests.test_webhook_dedupe import FakeEventsDb      # noqa: E402

CUSTOMER = "919999000777"
OWNER = "919999000001"
WAMID = "wamid.PHASE2A_TEST_0001"
BRAIN = "https://brain.test"
CRM = "https://crm.test"


class Http:
    """Fake requests.post: records Brain transcript writes and CRM mirror
    rows; anything else is unreachable, as in the other offline suites."""

    def __init__(self, brain_results=None):
        self.brain_saves = []      # list of row lists
        self.crm_rows = []
        self.order = []            # ("save", rows) / ("send", to)
        # Each Brain save consumes one result: an int status or an exception.
        self.brain_results = list(brain_results or [])

    def post(self, url, headers=None, json=None, timeout=None, **_k):
        if url.startswith(BRAIN) and url.endswith("/rest/v1/whatsapp_messages"):
            self.brain_saves.append(json)
            self.order.append(("save", [(r["role"], r["content"]) for r in json]))
            res = self.brain_results.pop(0) if self.brain_results else 201
            if isinstance(res, BaseException):
                raise res
            return _Resp(res)
        if url.startswith(CRM) and url.endswith("/rest/v1/whatsapp_messages"):
            self.crm_rows.append(json)
            return _Resp(201)
        raise requests.exceptions.ConnectionError("network blocked in tests")

    def get(self, *a, **k):
        raise requests.exceptions.ConnectionError("network blocked in tests")


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = ""
        self._body = body or {}

    def json(self):
        return self._body


def meta_ok(wamid="wamid.OUT_1"):
    return _Resp(200, {"messages": [{"id": wamid}]})


class Env(unittest.TestCase):
    """Common patches: Brain/CRM URLs, roles, and the fake network."""

    wa_result = None           # what _wa_post returns, or an exception to raise

    def setUp(self):
        self.http = Http()
        self.wa_calls = []

        def _wa_post(payload):
            self.wa_calls.append(payload)
            self.http.order.append(("send", payload.get("to")))
            res = self.wa_result if self.wa_result is not None else meta_ok()
            if isinstance(res, BaseException):
                raise res
            return res

        self._p = [
            mock.patch.object(w, "SUPABASE_URL", BRAIN),
            mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "test-server-key"),
            mock.patch.object(w, "CRM_SUPABASE_URL", CRM),
            mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "test-crm-key"),
            mock.patch.object(w, "CRM_OWNER_USER_ID", "owner-user"),
            mock.patch.object(w, "get_role",
                              lambda p: ("OWNER", "Owner") if p == OWNER else ("CLIENT", None)),
            mock.patch.object(w, "_wa_post", _wa_post),
            mock.patch.object(requests, "post", self.http.post),
            mock.patch.object(requests, "get", self.http.get),
        ]
        for p in self._p:
            p.start()
        w._TURN_EXTRAS.clear()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()
        w._TURN_EXTRAS.clear()

    def quiet(self, fn, *a, **k):
        with redirect_stdout(io.StringIO()) as out:
            try:
                return fn(*a, **k), out.getvalue()
            except Exception as e:      # returned, not swallowed silently
                return e, out.getvalue()


# ── A · accepted ────────────────────────────────────────────────────────────

class A_Accepted(Env):
    def test_a_2xx_with_an_id_is_accepted(self):
        d = w.classify_delivery(meta_ok("wamid.X"))
        self.assertEqual(d["verdict"], w.DELIVERY_ACCEPTED)
        self.assertEqual(d["wamid"], "wamid.X")
        self.assertIsNone(d["failure_class"])

    def test_the_crm_row_is_sent_with_the_real_id(self):
        self.wa_result = meta_ok("wamid.REAL")
        (d, _out) = self.quiet(w.send_text_checked, CUSTOMER, "hello")
        self.assertEqual(d["verdict"], w.DELIVERY_ACCEPTED)
        self.assertEqual(len(self.http.crm_rows), 1)
        self.assertEqual(self.http.crm_rows[0]["status"], "sent")
        self.assertEqual(self.http.crm_rows[0]["wa_message_id"], "wamid.REAL")

    def test_a_2xx_without_an_id_is_not_called_accepted(self):
        d = w.classify_delivery(_Resp(200, {}))
        self.assertEqual(d["verdict"], w.DELIVERY_UNKNOWN)


# ── B · HTTP rejection ──────────────────────────────────────────────────────

class B_Rejected(Env):
    def test_4xx_is_rejected_with_its_status(self):
        for code, fc in ((400, "VALUE"), (401, "PERMISSION"), (403, "PERMISSION"),
                         (404, "VALUE"), (429, "UNKNOWN")):
            d = w.classify_delivery(_Resp(code, {"error": {}}))
            self.assertEqual(d["verdict"], w.DELIVERY_REJECTED, code)
            self.assertEqual(d["status"], code)
            self.assertEqual(d["failure_class"], fc, code)
            self.assertIn(fc, ev.FAILURE_CLASSES)

    def test_5xx_is_unknown_not_rejected(self):
        """Meta may have taken a message it then failed to acknowledge."""
        d = w.classify_delivery(_Resp(503))
        self.assertEqual(d["verdict"], w.DELIVERY_UNKNOWN)

    def test_a_rejected_reply_is_mirrored_as_failed_without_an_id(self):
        self.wa_result = _Resp(400, {"error": {"code": 131047}})
        (d, _out) = self.quiet(w.send_text_checked, CUSTOMER, "hello")
        self.assertEqual(d["verdict"], w.DELIVERY_REJECTED)
        row = self.http.crm_rows[0]
        self.assertEqual(row["status"], "failed")
        self.assertNotIn("wa_message_id", row)

    def test_the_crm_status_values_are_the_crms_own(self):
        """CRM whatsapp_messages.status allows pending, sent, delivered, read,
        failed, received, deleted — nothing invented."""
        allowed = {"pending", "sent", "delivered", "read", "failed", "received", "deleted"}
        self.assertLessEqual(set(w._CRM_STATUS.values()), allowed)

    def test_send_text_still_returns_the_response_and_does_not_raise(self):
        self.wa_result = _Resp(400)
        (r, _out) = self.quiet(w.send_text, CUSTOMER, "hello")
        self.assertIs(r, self.wa_result)

    def test_the_delivery_log_line_carries_no_token_or_text(self):
        self.wa_result = _Resp(401)
        with mock.patch.object(w, "WHATSAPP_TOKEN", "test-token-must-not-appear"):
            (_d, out) = self.quiet(w.send_text_checked, CUSTOMER, "private words")
        line = [l for l in out.splitlines() if l.startswith("DELIVERY ")][0]
        self.assertNotIn("test-token-must-not-appear", out)
        self.assertNotIn("private words", line)
        self.assertNotIn(CUSTOMER, line)


# ── C · timeout ─────────────────────────────────────────────────────────────

class C_Timeout(Env):
    def test_a_timeout_is_unknown_with_class_timeout_and_is_not_retried(self):
        self.wa_result = requests.exceptions.ReadTimeout("slow")
        (d, _out) = self.quiet(w.send_text_checked, CUSTOMER, "hello")
        self.assertEqual(d["verdict"], w.DELIVERY_UNKNOWN)
        self.assertEqual(d["failure_class"], "TIMEOUT")
        self.assertEqual(len(self.wa_calls), 1, "UNKNOWN must not be retried")
        self.assertEqual(self.http.crm_rows[0]["status"], "pending")

    def test_a_connect_timeout_is_a_timeout(self):
        d = w.classify_delivery(exc=requests.exceptions.ConnectTimeout("x"))
        self.assertEqual(d["failure_class"], "TIMEOUT")

    def test_a_connection_error_is_unknown_class_connection(self):
        d = w.classify_delivery(exc=requests.exceptions.ConnectionError("x"))
        self.assertEqual((d["verdict"], d["failure_class"]),
                         (w.DELIVERY_UNKNOWN, "CONNECTION"))

    def test_send_text_still_raises_for_its_existing_callers(self):
        self.wa_result = requests.exceptions.ReadTimeout("slow")
        (r, _out) = self.quiet(w.send_text, CUSTOMER, "hello")
        self.assertIsInstance(r, requests.exceptions.ReadTimeout)

    def test_a_bug_in_our_code_is_not_called_a_channel_outcome(self):
        self.wa_result = KeyError("ours")
        (r, _out) = self.quiet(w.send_text_checked, CUSTOMER, "hello")
        self.assertIsInstance(r, KeyError)


# ── E / F · bounded transcript-save retry ──────────────────────────────────

class E_SaveRetrySucceeds(Env):
    def test_one_network_failure_then_success(self):
        self.http.brain_results = [requests.exceptions.ConnectionError("blip"), 201]
        (out, log) = self.quiet(w.save_messages, [(CUSTOMER, "user", "hi")])
        self.assertEqual(out, w.SAVE_OK)
        self.assertEqual(len(self.http.brain_saves), 2)
        self.assertIn("SAVE_MESSAGES_RETRY_OK", log)

    def test_a_5xx_is_retried(self):
        self.http.brain_results = [503, 201]
        (out, _log) = self.quiet(w.save_messages, [(CUSTOMER, "user", "hi")])
        self.assertEqual(out, w.SAVE_OK)
        self.assertEqual(len(self.http.brain_saves), 2)


class F_SaveFailsTwice(Env):
    def test_two_network_failures_return_the_failure_after_exactly_two_tries(self):
        self.http.brain_results = [requests.exceptions.ConnectionError("a"),
                                   requests.exceptions.ReadTimeout("b"), 201]
        (out, log) = self.quiet(w.save_messages, [(CUSTOMER, "user", "hi")])
        self.assertEqual(out, w.SAVE_NETWORK_FAILURE)
        self.assertEqual(len(self.http.brain_saves), 2, "maximum ONE retry")
        self.assertIn("attempt=2", log)

    def test_two_5xx_return_persistence_failure(self):
        self.http.brain_results = [500, 502, 201]
        (out, _log) = self.quiet(w.save_messages, [(CUSTOMER, "user", "hi")])
        self.assertEqual(out, w.SAVE_PERSISTENCE_FAILURE)
        self.assertEqual(len(self.http.brain_saves), 2)

    def test_a_4xx_is_not_retried(self):
        """Our request is wrong; sending it again cannot fix it."""
        self.http.brain_results = [401, 201]
        (out, _log) = self.quiet(w.save_messages, [(CUSTOMER, "user", "hi")])
        self.assertEqual(out, w.SAVE_PERSISTENCE_FAILURE)
        self.assertEqual(len(self.http.brain_saves), 1)

    def test_the_failure_is_still_visible_to_the_owner_on_bairavi_paths(self):
        alerts = []
        with mock.patch.object(w, "notify_owner", lambda m, **k: alerts.append(m)):
            w.warn_if_transcript_lost(CUSTOMER, w.SAVE_NETWORK_FAILURE, "Bairavi opening reply")
        self.assertTrue(alerts and "Transcript not saved" in alerts[0])


# ── D / H / I · through the real do_POST ───────────────────────────────────

class ThroughDoPost(Env):
    """Real do_POST, real send_text and save_messages; branch bodies stubbed."""

    def setUp(self):
        super().setUp()
        self.db = FakeEventsDb()
        self.pipeline_calls = []

        def pipeline(sender, text, ctx, message_id=None):
            self.pipeline_calls.append(text)
            w.send_text(sender, "reply")
            w.save_messages([(sender, "user", text), (sender, "assistant", "reply")])

        self._p2 = [
            mock.patch.object(ev, "insert", self.db.insert),
            mock.patch.object(ev, "update", self.db.update),
            mock.patch.object(ev, "select", self.db.select),
            mock.patch.object(ev.config, "is_configured", lambda: True),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w, "send_typing", lambda *a, **k: None),
            mock.patch.object(w, "notify_owner", lambda *a, **k: None),
            mock.patch.object(w, "fetch_context",
                              lambda *a, **k: {"history": [], "last_user": {}}),
            mock.patch.object(w, "run_client_pipeline", pipeline),
            mock.patch.object(w, "_bic_enabled", lambda: False),
            mock.patch.object(w, "_bic_replay_compare", lambda *a, **k: None),
            mock.patch.object(w, "_decision_open", lambda *a, **k: None),
            mock.patch.object(w, "_decision_flush", lambda *a, **k: None),
        ]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in reversed(self._p2):
            p.stop()
        super().tearDown()

    def post(self, text, sender=CUSTOMER, wamid=WAMID):
        msg = {"id": wamid, "from": sender, "type": "text", "text": {"body": text}}
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()
        h = w.handler.__new__(w.handler)
        h.headers = {"Content-Length": str(len(body)), "X-Hub-Signature-256": "sig"}
        h.rfile = io.BytesIO(body)
        h.wfile = io.BytesIO()
        h.send_response = lambda *a, **k: None
        h.send_header = lambda *a, **k: None
        h.end_headers = lambda *a, **k: None
        with redirect_stdout(io.StringIO()) as out:
            try:
                h.do_POST()
            except Exception:
                pass
        return out.getvalue()

    def state(self, wamid=WAMID):
        row = self.db.rows.get(wamid)
        return row and row["state"]


class D_IncomingPersistedFirst(ThroughDoPost):
    def test_the_customer_message_is_saved_before_the_reply_is_sent(self):
        self.post("25 kva transformer beku")
        kinds = [k for k, _ in self.http.order]
        self.assertEqual(self.http.order[0], ("save", [("user", "25 kva transformer beku")]))
        self.assertLess(kinds.index("save"), kinds.index("send"))

    def test_the_branch_save_does_not_write_the_customer_row_twice(self):
        self.post("25 kva transformer beku")
        rows = [r for save in self.http.brain_saves for r in save]
        self.assertEqual([(r["role"], r["content"]) for r in rows],
                         [("user", "25 kva transformer beku"), ("assistant", "reply")])

    def test_if_the_early_save_fails_the_branch_save_still_carries_it(self):
        self.http.brain_results = [requests.exceptions.ConnectionError("a"),
                                   requests.exceptions.ConnectionError("b"), 201]
        self.post("hello there")
        last = self.http.brain_saves[-1]
        self.assertEqual([(r["role"], r["content"]) for r in last],
                         [("user", "hello there"), ("assistant", "reply")])

    def test_accepted_reply_completes_the_event(self):
        self.post("hello there")
        self.assertEqual(self.state(), ev.COMPLETED)
        self.assertIsNone(self.db.rows[WAMID].get("failure_class"))

    def test_a_rejected_reply_fails_the_event(self):
        """COMPLETED no longer means 'no exception'."""
        self.wa_result = _Resp(400, {"error": {}})
        self.post("hello there")
        self.assertEqual(self.state(), ev.FAILED)
        self.assertEqual(self.db.rows[WAMID]["failure_class"], "VALUE")

    def test_an_unknown_reply_fails_the_event_with_timeout(self):
        self.wa_result = requests.exceptions.ReadTimeout("slow")
        self.post("hello there")
        self.assertEqual(self.state(), ev.FAILED)
        self.assertEqual(self.db.rows[WAMID]["failure_class"], "TIMEOUT")
        self.assertEqual(len(self.wa_calls), 1)

    def test_a_deliberate_no_reply_is_completed(self):
        with mock.patch.object(w, "run_client_pipeline", lambda *a, **k: None):
            self.post("ok")
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_an_owner_alert_does_not_decide_the_customers_turn(self):
        """Only sends to the turn's sender count."""
        def pipeline(sender, text, ctx, message_id=None):
            w.send_text(sender, "reply")           # accepted
            self.wa_result = _Resp(400)
            w.send_text(OWNER, "alert")            # rejected, but not the reply
        with mock.patch.object(w, "run_client_pipeline", pipeline):
            self.post("hello there")
        self.assertEqual(self.state(), ev.COMPLETED)


class H_DuplicateWamid(ThroughDoPost):
    def test_a_redelivered_wamid_sends_and_saves_nothing(self):
        self.post("hello there")
        saves, sends = len(self.http.brain_saves), len(self.wa_calls)
        self.post("hello there")
        self.assertEqual(len(self.pipeline_calls), 1)
        self.assertEqual(len(self.http.brain_saves), saves)
        self.assertEqual(len(self.wa_calls), sends)
        self.assertEqual(self.state(), ev.COMPLETED)


class I_OwnerCallsRegression(ThroughDoPost):
    def test_owner_calls_still_answers_and_saves_once(self):
        with mock.patch.object(w, "handle_owner_text",
                               lambda s, r, l, t, c: "📞 2 leads to call" if t == "#calls" else "?"):
            self.post("#calls", sender=OWNER)
        self.assertEqual([p["to"] for p in self.wa_calls], [OWNER])
        self.assertEqual(self.wa_calls[0]["text"]["body"], "📞 2 leads to call")
        # No early save for an owner turn: exactly the legacy single write.
        self.assertEqual(len(self.http.brain_saves), 1)
        self.assertEqual([(r["role"], r["content"]) for r in self.http.brain_saves[0]],
                         [("user", "#calls"), ("assistant", "📞 2 leads to call")])
        self.assertEqual(self.http.crm_rows, [], "owner replies are never mirrored")
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_the_real_calls_command_still_routes_to_its_tool(self):
        with mock.patch.object(w, "run_tool", lambda s, name, **k: f"TOOL:{name}"):
            reply = w.handle_owner_text(OWNER, "OWNER", "Owner", "#calls",
                                        {"history": [], "last_user": {}})
        self.assertEqual(reply, "TOOL:crm_calls_to_make")


# ── G · Bairavi send-result handling ───────────────────────────────────────

def markers(turn):
    return [c for _p, role, c in turn["saved"]
            if role == "assistant" and c.startswith(w.bairavi.FLOW_MARKER)]


class G_BairaviMarker(unittest.TestCase):
    def test_an_accepted_opening_writes_the_marker(self):
        t = Conversation().send(lead_form())
        self.assertEqual(len(markers(t)), 1)
        self.assertFalse(any("NOT delivered" in m for m in t["owner"]))

    def test_a_rejected_opening_writes_no_marker_and_tells_the_owner(self):
        t = Conversation(send_result=fake_send.Rejected(400)).send(lead_form())
        self.assertEqual(markers(t), [])
        self.assertIn(("910000000000", "user", lead_form()), t["saved"])
        self.assertTrue(any("Reply NOT delivered" in m and "HTTP 400" in m
                            for m in t["owner"]), t["owner"])
        self.assertTrue(t["leads"], "the enquiry is still recorded as a lead")

    def test_a_timed_out_opening_is_unknown_not_rejected_and_not_resent(self):
        t = Conversation(send_result=requests.exceptions.ReadTimeout("slow")).send(lead_form())
        self.assertEqual(markers(t), [])
        self.assertEqual(len(t["sent"]), 1, "UNKNOWN is never retried")
        self.assertTrue(any("delivery UNKNOWN" in m for m in t["owner"]), t["owner"])

    def test_a_rejected_followup_writes_no_marker_and_alerts(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("1 unit", send_result=fake_send.Rejected(403))
        self.assertTrue(t["sent"], "the follow-up reply was attempted")
        self.assertEqual(markers(t), [])
        self.assertIn(("910000000000", "user", "1 unit"), t["saved"])
        self.assertTrue(any(m.startswith("🚫 *Reply NOT delivered*") for m in t["owner"]),
                        t["owner"])

    def test_an_accepted_followup_still_writes_the_marker(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("1 unit")
        self.assertEqual(len(markers(t)), 1)

    def test_the_conversation_stays_bairavi_after_one_failed_reply(self):
        """The opening marker survives, so the next message is still read as
        a transformer follow-up, not answered as Asthra."""
        c = Conversation()
        c.send(lead_form())
        c.send("1 unit", send_result=fake_send.Rejected(400))
        t = c.send("Agricultural")
        self.assertNotIn("ASTHRA_AI_REPLY", " ".join(t["sent"]))
        self.assertEqual(len(markers(t)), 1)


if __name__ == "__main__":
    unittest.main()
