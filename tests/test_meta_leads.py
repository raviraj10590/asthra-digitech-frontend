"""Meta form leads who never messaged (meta_leads.py + api/meta_leads_sync.py).

Offline: Meta, the CRM and the Brain transcript are faked. The fake Meta
returns leads in the real Lead Ads shape (field_data name/values, the form's
own Kannada question text with underscores).
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, ROOT)

import requests                                       # noqa: E402
import bairavi                                        # noqa: E402
import meta_leads as ml                               # noqa: E402
import meta_leads_sync as sync                        # noqa: E402
import webhook as w                                   # noqa: E402
import fake_send                                      # noqa: E402

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
CRM = "https://crm.test"
BRAIN = "https://brain.test"
TOKEN = "test-meta-token-never-logged"


def meta_time(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def lead(lid, phone="+919448650033", minutes_ago=45, name="Prakash Monappa", kva="B. 63 kVA",
         place="nadi sinur", when="A.ತಕ್ಷಣ_ಅಗತ್ಯವಿದೆ"):
    fields = [
        {"name": "ನಿಮಗೆ_ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್_ಯಾವಾಗ_ಅಗತ್ಯವಿದೆ?", "values": [when]},
        {"name": "ನಿಮಗೆ_ಅಗತ್ಯವಿರುವ_ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್_ಸಾಮರ್ಥ್ಯ_ಯಾವುದು?", "values": [kva]},
        {"name": "ನಿಮ್ಮ_ಪ್ರಾಜೆಕ್ಟ್_ಯಾವ_ಸ್ಥಳದಲ್ಲಿದೆ?", "values": [place]},
        {"name": "full_name", "values": [name]},
        {"name": "phone_number", "values": [phone]},
    ]
    return {"id": lid, "created_time": meta_time(minutes_ago), "field_data": fields}


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.ok = status, 200 <= status < 300
        self._b = body if body is not None else {}
        self.text = ""

    def json(self):
        return self._b

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


# ── Pure rules ──────────────────────────────────────────────────────────────

class Phones(unittest.TestCase):
    def test_normalize(self):
        for raw, want in (("+919448650033", "919448650033"), ("9448650033", "919448650033"),
                          ("+91 94486 50033", "919448650033"), ("09448650033", "919448650033"),
                          ("12345", None), ("+14155550100", None), ("", None), (None, None)):
            with self.subTest(raw=raw):
                self.assertEqual(ml.normalize_phone(raw), want)


class TheFormBecomesTheHandoff(unittest.TestCase):
    def test_bairavi_reads_the_rebuilt_form(self):
        p = bairavi.parse(ml.form_text(lead("L1")))
        self.assertTrue(p["from_lead_form"])
        self.assertEqual((p["capacity_kva"], p["name"], p["urgency"]),
                         (63, "Prakash Monappa", "IMMEDIATE"))
        self.assertEqual(p["location"], "nadi sinur")

    def test_its_origin_is_visible(self):
        self.assertTrue(ml.form_text(lead("L1")).startswith("[Meta form]"))


class TheLiveFormsFieldNames(unittest.TestCase):
    """The first production dry run (2026-10-03) logged these names; every
    lead was skipped because the phone arrives as "phone"."""
    LIVE = ["full_name", "phone", "ನಿಮಗೆ_ಅಗತ್ಯವಿರುವ_ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್_ಸಾಮರ್ಥ್ಯ_ಯಾವುದು?",
            "ನಿಮಗೆ_ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್_ಯಾವಾಗ_ಅಗತ್ಯವಿದೆ?", "ನಿಮ್ಮ_ಪ್ರಾಜೆಕ್ಟ್_ಯಾವ_ಸ್ಥಳದಲ್ಲಿದೆ?"]

    def live_lead(self):
        values = ["Jackson", "+919480004560", "A._25_kVA", "A.ತಕ್ಷಣ_ಅಗತ್ಯವಿದೆ", "Puttur"]
        return {"id": "LIVE1", "created_time": meta_time(45),
                "field_data": [{"name": n, "values": [v]} for n, v in zip(self.LIVE, values)]}

    def test_the_phone_field_is_read(self):
        self.assertEqual(ml.normalize_phone(ml.phone_of(self.live_lead())), "919480004560")
        self.assertEqual(ml.decide(self.live_lead(), NOW, wrote_before=False, handled=False,
                                   internal=False), ml.CONTACT)

    def test_the_whole_form_reads(self):
        p = bairavi.parse(ml.form_text(self.live_lead()))
        self.assertEqual((p["name"], p["capacity_kva"], p["urgency"], p["location"]),
                         ("Jackson", 25, "IMMEDIATE", "Puttur"))


class Template(unittest.TestCase):
    def test_params_and_fallbacks(self):
        self.assertEqual(ml.template_params({"name": "Prakash Monappa", "capacity_kva": 63}),
                         ("Prakash Monappa", "63 kVA"))
        self.assertEqual(ml.template_params({}), (ml.NAME_FALLBACK, ml.CAPACITY_FALLBACK))

    def test_rendered_has_no_placeholders_and_offers_stop(self):
        text = ml.rendered(("Ravi", "25 kVA"))
        self.assertNotIn("{{", text)
        self.assertIn("Ravi", text)
        self.assertIn("STOP", text)

    def test_the_template_makes_no_claim_the_guard_forbids(self):
        self.assertIsNone(bairavi.reply_violates_evidence(ml.rendered(("Ravi", "25 kVA"))))

    def test_stop_is_a_decline_but_bus_stop_is_not(self):
        self.assertTrue(bairavi.is_decline("STOP"))
        self.assertTrue(bairavi.is_decline("stop"))
        self.assertFalse(bairavi.is_decline("near bus stop Kadaba"))


class Decide(unittest.TestCase):
    def d(self, l, **kw):
        base = dict(wrote_before=False, handled=False, internal=False)
        base.update(kw)
        return ml.decide(l, NOW, **base)

    def test_each_reason(self):
        self.assertEqual(self.d(lead("a", minutes_ago=5)), ml.SKIP_TOO_NEW)
        self.assertEqual(self.d(lead("a", minutes_ago=25 * 60)), ml.SKIP_TOO_OLD)
        self.assertEqual(self.d(lead("a", phone="123")), ml.SKIP_NO_PHONE)
        self.assertEqual(self.d(lead("a"), internal=True), ml.SKIP_INTERNAL)
        self.assertEqual(self.d(lead("a"), handled=True), ml.SKIP_ALREADY_HANDLED)
        self.assertEqual(self.d(lead("a"), wrote_before=True), ml.SKIP_ALREADY_WROTE)
        self.assertEqual(self.d(lead("a")), ml.CONTACT)

    def test_an_unreadable_time_is_never_contacted(self):
        bad = lead("a")
        bad["created_time"] = "yesterday"
        self.assertEqual(self.d(bad), ml.SKIP_TOO_OLD)


# ── The job, against a fake world ───────────────────────────────────────────

class World(unittest.TestCase):
    MODE = "send"

    def setUp(self):
        self.leads = [lead("L1")]
        self.crm_inbound = set()          # phones that wrote to us
        self.crm_bodies = []              # inbound message texts
        self.transcript = []              # (phone, role, content)
        self.sent = []
        self.mirrored = []
        self.crm_synced = []
        self.owner = []
        self.graph_error = None
        self.graph_calls = 0
        self.template = "APPROVED"
        self.send_result = fake_send.Accepted()
        self.save_ok = True

        def get(url, params=None, headers=None, timeout=None):
            params = params or {}
            if url.startswith(sync.GRAPH):
                self.assertEqual(headers, {"Authorization": f"Bearer {TOKEN}"})
                if self.graph_error:
                    return Resp(400, {"error": {"code": self.graph_error,
                                                "message": f"bad token {TOKEN}"}})
                if url.endswith("/PHONE1"):
                    return Resp(200, {"health_status": {"entities": [
                        {"entity_type": "PHONE_NUMBER", "id": "PHONE1"},
                        {"entity_type": "WABA", "id": "WABA5171"}]}})
                if url.endswith("WABA5171/message_templates"):
                    self.assertEqual(params["name"], ml.TEMPLATE_NAME)
                    if self.template is None:
                        return Resp(200, {"data": []})
                    return Resp(200, {"data": [{"name": ml.TEMPLATE_NAME, "language": "kn",
                                                "status": self.template}]})
                self.graph_calls += 1
                if url.endswith("/ads"):
                    # Field expansion: each ad with its leads nested; the same
                    # lead under two ads, and one lead from before the window.
                    old = lead("OLD", minutes_ago=30 * 60)
                    return Resp(200, {"data": [
                        {"id": "AD1", "leads": {"data": self.leads + [old]}},
                        {"id": "AD2", "leads": {"data": self.leads[:1]}},
                        {"id": "AD3"}]})
                raise AssertionError(f"unexpected Graph call {url}")
            if url == f"{CRM}/rest/v1/whatsapp_messages":
                if "phone" in params:
                    return Resp(200, [{"id": 1}] if params["phone"][3:] in self.crm_inbound else [])
                needle = params["body"][len("ilike.*"):-1]
                return Resp(200, [{"id": 1}] if any(needle in b for b in self.crm_bodies) else [])
            if url == f"{BRAIN}/rest/v1/whatsapp_messages":
                prefix = params["content"][len("like."):-1]
                hit = [c for p, r, c in self.transcript
                       if p == params["phone"][3:] and r == "system" and c.startswith(prefix)]
                return Resp(200, [{"id": 1}] if hit else [])
            raise requests.ConnectionError("blocked")

        def save_message(phone, role, content):
            if not self.save_ok:
                return w.SAVE_NETWORK_FAILURE
            self.transcript.append((phone, role, content))
            return w.SAVE_OK

        def save_messages(items):
            for it in items:
                self.transcript.append(it)
            return w.SAVE_OK

        def wa_post(payload):
            self.sent.append(payload)
            r = self.send_result
            if isinstance(r, BaseException):
                raise r
            return r

        self._p = [
            mock.patch.dict(os.environ, {"META_LEADS_MODE": self.MODE,
                                         "FACEBOOK_ACCESS_TOKEN": TOKEN}),
            mock.patch.object(w, "WHATSAPP_TOKEN", TOKEN),
            mock.patch.object(w, "PHONE_NUMBER_ID", "PHONE1"),
            mock.patch.object(requests, "get", get),
            mock.patch.object(w, "CRM_SUPABASE_URL", CRM),
            mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "crm-key"),
            mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"),
            mock.patch.object(w, "SUPABASE_URL", BRAIN),
            mock.patch.object(w, "get_role", lambda p: ("OWNER", "x") if p == "919999000001" else ("CLIENT", None)),
            mock.patch.object(w, "save_message", save_message),
            mock.patch.object(w, "save_messages", save_messages),
            mock.patch.object(w, "_wa_post", wa_post),
            mock.patch.object(w, "_mirror_outbound_to_crm",
                              lambda phone, **k: self.mirrored.append((phone, k))),
            mock.patch.object(w, "sync_lead_to_crm", lambda phone, d: self.crm_synced.append((phone, d))),
            mock.patch.object(w, "notify_owner", lambda m, **k: self.owner.append(m)),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def run_job(self):
        with redirect_stdout(io.StringIO()) as out:
            res = sync.run(NOW)
        self.log = out.getvalue()
        return res


class SendMode(World):
    def test_a_silent_lead_is_contacted_once_with_the_template(self):
        res = self.run_job()
        self.assertEqual(res["contacted"], 1)
        self.assertEqual(len(self.sent), 1, "same lead under two ads is one lead")
        t = self.sent[0]
        self.assertEqual((t["to"], t["type"]), ("919448650033", "template"))
        self.assertEqual(t["template"]["name"], ml.TEMPLATE_NAME)
        self.assertEqual(t["template"]["language"], {"code": "kn"})
        self.assertEqual([x["text"] for x in t["template"]["components"][0]["parameters"]],
                         ["Prakash Monappa", "63 kVA"])

    def test_the_claim_is_written_before_anything_else(self):
        order = []
        orig_post = w._wa_post
        with mock.patch.object(w, "_wa_post", lambda p: (order.append(
                [c for _, r, c in self.transcript if r == "system"]), orig_post(p))[1]):
            self.run_job()
        self.assertEqual(order[0], [ml.marker("L1", "claimed")])

    def test_crm_lead_mirror_and_transcript(self):
        self.run_job()
        self.assertEqual(self.crm_synced[0][0], "919448650033")
        self.assertEqual(self.crm_synced[0][1]["source"], "bairavi-transformer")
        phone, kw = self.mirrored[0]
        self.assertEqual((kw["message_type"], kw["status"]), ("template", "sent"))
        self.assertEqual(kw["wa_message_id"], "wamid.TEST_ACCEPTED")
        roles = [(r, c[:11]) for p, r, c in self.transcript if r != "system"]
        self.assertEqual(roles, [("user", "[Meta form]"), ("assistant", bairavi.FLOW_MARKER[:11])])
        self.assertIn(ml.marker("L1", "sent"), [c for _, r, c in self.transcript])

    def test_the_bot_continues_the_conversation_when_they_reply(self):
        self.run_job()
        history = [{"role": r, "content": c} for p, r, c in self.transcript if r != "system"]
        self.assertTrue(bairavi.in_transformer_flow(history))

    def test_a_second_run_sends_nothing(self):
        self.run_job()
        res = self.run_job()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(res.get(ml.SKIP_ALREADY_HANDLED), 1)

    def test_someone_who_already_wrote_is_left_alone(self):
        self.crm_inbound.add("919448650033")
        res = self.run_job()
        self.assertEqual(self.sent, [])
        self.assertEqual(res.get(ml.SKIP_ALREADY_WROTE), 1)
        self.assertEqual(self.crm_synced, [])

    def test_a_handoff_from_another_number_counts_as_already_wrote(self):
        """Live 2026-10-03: form number 9194…0033, WhatsApp number 9195…0033;
        the handoff body carried the form number."""
        self.crm_bodies.append("Hello! I filled out your form ... Full name: Prakash Monappa "
                               "Phone number: +919448650033 ...")
        res = self.run_job()
        self.assertEqual(self.sent, [])
        self.assertEqual(res.get(ml.SKIP_ALREADY_WROTE), 1)

    def test_owner_and_staff_are_never_messaged(self):
        self.leads = [lead("L9", phone="+919999000001")]
        res = self.run_job()
        self.assertEqual(self.sent, [])
        self.assertEqual(res.get(ml.SKIP_INTERNAL), 1)

    def test_a_rejected_template_saves_no_conversation_and_tells_the_owner(self):
        self.send_result = fake_send.Rejected(400)
        self.run_job()
        self.assertFalse([1 for _, r, _c in self.transcript if r in ("user", "assistant")])
        self.assertIn(ml.marker("L1", "rejected_rejected"), [c for _, r, c in self.transcript])
        self.assertEqual(self.mirrored[0][1]["status"], "failed")
        self.assertIn("NOT delivered", self.owner[0])

    def test_no_claim_no_send(self):
        self.save_ok = False
        res = self.run_job()
        self.assertEqual(self.sent, [])
        self.assertEqual(res.get("claim_failed"), 1)

    def test_a_bounded_number_per_run(self):
        self.leads = [lead(f"L{i}", phone=f"+9194486500{i:02d}") for i in range(ml.MAX_PER_RUN + 3)]
        res = self.run_job()
        self.assertEqual(len(self.sent), ml.MAX_PER_RUN)
        self.assertEqual(res["deferred"], 3)

    def test_the_owner_gets_one_summary(self):
        self.leads = [lead("L1"), lead("L2", phone="+919448650099", name="Jackson", kva="A. 25 kVA")]
        self.run_job()
        self.assertEqual(len(self.owner), 1)
        self.assertIn("2 contacted", self.owner[0])

    def test_meta_permission_errors_are_counted_not_raised_and_no_token_leaks(self):
        self.graph_error = 200
        res = self.run_job()
        self.assertEqual(res["error"], "meta_fetch_failed")
        self.assertIn("code=200", self.log)
        self.assertNotIn(TOKEN, self.log + json.dumps(res))

    def test_logs_and_result_carry_no_names_or_phones(self):
        res = self.run_job()
        blob = self.log + json.dumps(res)
        for leak in ("Prakash", "919448650033", "nadi sinur"):
            self.assertNotIn(leak, blob)


class TheTemplateMustBeApprovedWhereTheBotSends(World):
    """2026-10-03: the template was created in the CRM's configured account;
    the bot's number belongs to another, where it did not exist at all."""

    def test_missing_in_the_bots_account_blocks_every_send(self):
        self.template = None
        res = self.run_job()
        self.assertEqual((res["template"], res["blocked"]), ("MISSING", "template_not_approved"))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.transcript, [], "nothing claimed — the lead stays contactable")
        self.assertEqual(self.crm_synced, [])

    def test_pending_or_rejected_block_too(self):
        for status in ("PENDING", "REJECTED", "PAUSED"):
            with self.subTest(status=status):
                self.template = status
                self.sent.clear()
                res = self.run_job()
                self.assertEqual(self.sent, [])
                self.assertEqual(res["template"], status)

    def test_approved_sends_and_reports_the_account(self):
        res = self.run_job()
        self.assertEqual((res["template"], res["waba"]), ("APPROVED", "5171"))
        self.assertEqual(len(self.sent), 1)

    def test_a_blocked_lead_is_contacted_once_approval_arrives(self):
        self.template = "PENDING"
        self.run_job()
        self.template = "APPROVED"
        self.run_job()
        self.assertEqual(len(self.sent), 1)


class OneRequest(World):
    def test_the_lead_fetch_is_a_single_graph_request(self):
        """Production run 2: Meta error 17 after one request per ad."""
        self.leads = [lead(f"L{i}", phone=f"+9194486500{i:02d}") for i in range(5)]
        res = self.run_job()
        self.assertEqual(self.graph_calls, 1)
        self.assertEqual(res["fetched"], 5, "duplicates and the old lead are dropped")

    def test_the_request_asks_for_nested_leads(self):
        captured = {}
        real = requests.get

        def spy(url, params=None, **k):
            if url.startswith(sync.GRAPH) and url.endswith("/ads"):
                captured.update(params or {})
            return real(url, params=params, **k)
        with mock.patch.object(requests, "get", spy):
            self.run_job()
        self.assertIn("leads.limit(", captured["fields"])
        self.assertIn("field_data", captured["fields"])


class CrmMode(World):
    MODE = "crm"

    def test_adds_to_the_crm_but_sends_nothing(self):
        res = self.run_job()
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.crm_synced), 1)
        self.assertEqual(res["contacted"], 1)
        self.assertIn(ml.marker("L1", "crm"), [c for _, r, c in self.transcript])


class DryRun(World):
    MODE = "dry_run"

    def test_reads_and_counts_only(self):
        res = self.run_job()
        self.assertEqual((self.sent, self.crm_synced, self.transcript, self.owner), ([], [], [], []))
        self.assertEqual(res[ml.CONTACT], 1)
        self.assertIn("META_LEADS field_names", self.log)
        self.assertNotIn("Prakash", self.log)


class Off(World):
    MODE = "off"

    def test_does_nothing_at_all(self):
        calls = []
        with mock.patch.object(requests, "get", lambda *a, **k: calls.append(a)):
            self.assertEqual(self.run_job(), {"mode": "off"})
        self.assertEqual(calls, [])

    def test_off_is_the_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sync.mode(), "off")
        with mock.patch.dict(os.environ, {"META_LEADS_MODE": "SEND-ALL"}):
            self.assertEqual(sync.mode(), "off")


class TheEndpoint(unittest.TestCase):
    def test_a_failing_lead_job_never_fails_the_sweep(self):
        import recovery
        import redrive
        tok = "s" * 48
        h = recovery.handler.__new__(recovery.handler)
        h.headers = {"Authorization": f"Bearer {tok}"}
        h.path, h.rfile, h.wfile = "/api/recovery", io.BytesIO(b""), io.BytesIO()
        sent = {}
        h.send_response = lambda c, *a: sent.setdefault("code", c)
        h.send_header = lambda *a: None
        h.end_headers = lambda: None
        boom = mock.Mock(side_effect=RuntimeError("meta 919448650033 down"))
        with mock.patch.dict(os.environ, {"CRON_SECRET": tok}), \
             mock.patch.object(redrive, "run", lambda: {}), \
             mock.patch.object(sync, "run", boom), \
             mock.patch.object(recovery, "publish_health", lambda c: "ok"), \
             mock.patch.object(recovery, "call_reminders", lambda now=None: {"mode": "off"}), \
             redirect_stdout(io.StringIO()) as out:
            h.do_POST()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(sent["code"], 200)
        self.assertEqual(body["meta_leads"], {"error": "meta_leads_failed"})
        self.assertNotIn("919448650033", out.getvalue())


if __name__ == "__main__":
    unittest.main()
