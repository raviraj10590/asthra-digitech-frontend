"""Phase 2B — safe recovery and re-drive (api/redrive.py).

Drives the REAL send_text, save_messages, _finalize_delivery and (for the
Bairavi cases) the real run_client_pipeline against an in-memory world:

  events  bic_webhook_events, enforcing its CHECK constraints and applying a
          conditional PATCH exactly once (the compare-and-swap)
  brain   the Brain transcript (whatsapp_messages)
  crm     the CRM conversation, which send_text's mirror writes into — so the
          evidence a later sweep reads is the evidence a real send produced

Tests A-N are named for the case they cover. The NEGATIVE CONTROLS switch one
guard off and show the unsafe outcome then happens, so each guard is proven to
be the thing preventing it. Offline: no network, no AI, no database.
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

import requests                                         # noqa: E402
import webhook as w                                     # noqa: E402
import redrive                                          # noqa: E402
import bairavi                                          # noqa: E402
from bic import webhook_events as ev                    # noqa: E402
from bic.db import DbError                              # noqa: E402
from conversation import lead_form                      # noqa: E402

CUSTOMER = "919999000888"
OWNER = "919999000001"
WAMID = "wamid.HBgMRECOVERYTEST+/="
BRAIN = "https://brain.test"
CRM = "https://crm.test"
OWNER_UID = "owner-user"
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def ago(**kw):
    return iso(NOW - timedelta(**kw))


def _ts(v):
    return redrive._parse_ts(v)


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.ok = status, 200 <= status < 300
        self._body = body if body is not None else []
        self.text = ""
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(str(self.status_code))


class Events:
    """bic_webhook_events with its real constraints."""

    def __init__(self):
        self.rows = {}
        self.fail = False

    def put(self, wamid, state, failure_class=None, created=None, updated=None):
        terminal = state in (ev.COMPLETED, ev.FAILED)
        self.rows[wamid] = {"wamid": wamid, "state": state,
                            "failure_class": failure_class,
                            "created_at": created or ago(minutes=30),
                            "updated_at": updated or ago(minutes=20),
                            "completed_at": ago(minutes=20) if terminal else None,
                            "brain_message_id": "00000000-0000-0000-0000-00000000b0b0"}

    def _check(self, row):
        assert row["state"] in ev.STATES
        assert (row["state"] in (ev.COMPLETED, ev.FAILED)) == (row["completed_at"] is not None), row
        assert row["failure_class"] is None or row["state"] == ev.FAILED, row
        assert row["failure_class"] in (None,) + ev.FAILURE_CLASSES, row

    def select(self, table, params, timeout=None):
        if self.fail:
            raise DbError("events select 503")
        rows = list(self.rows.values())
        if "wamid" in params:
            rows = [r for r in rows if r["wamid"] == params["wamid"][3:]]
        if "state" in params:
            allowed = params["state"][len("in.("):-1].split(",")
            rows = [r for r in rows if r["state"] in allowed]
        if "created_at" in params:
            rows = [r for r in rows if _ts(r["created_at"]) >= _ts(params["created_at"][4:])]
        if "updated_at" in params:
            rows = [r for r in rows if _ts(r["updated_at"]) < _ts(params["updated_at"][3:])]
        return [dict(r) for r in sorted(rows, key=lambda r: r["created_at"])]

    def update(self, table, params, patch, timeout=None, returning=False):
        if self.fail:
            raise DbError("events update 503")
        out = []
        for r in self.rows.values():
            if r["wamid"] != params["wamid"][3:]:
                continue
            if "state" in params and r["state"] != params["state"][3:]:
                continue
            if "updated_at" in params and r["updated_at"] != params["updated_at"][3:]:
                continue
            new = dict(r, **patch)
            if new["state"] != ev.FAILED:
                new.setdefault("failure_class", None)
            self._check(new)
            r.update(new)
            out.append(dict(r))
        return out if returning else None


class World(unittest.TestCase):
    send_results = None      # list consumed per send; default ACCEPTED

    def setUp(self):
        self.events = Events()
        self.brain = []      # {"phone","role","content","created_at"}
        self.crm = []
        self.sends = []
        self.owner_alerts = []
        self.crm_fail = False
        self.brain_fail = False
        self.results = list(self.send_results or [])
        self._n = 0

        def wa_post(payload):
            to = payload.get("to")
            self.sends.append((to, (payload.get("text") or {}).get("body")))
            res = self.results.pop(0) if self.results else "ok"
            if isinstance(res, BaseException):
                raise res
            if res == "ok":
                self._n += 1
                return Resp(200, {"messages": [{"id": f"wamid.OUT{self._n}"}]})
            return Resp(res, {"error": {}})

        def post(url, headers=None, json=None, params=None, timeout=None, **k):
            if url == f"{BRAIN}/rest/v1/whatsapp_messages":
                if self.brain_fail:
                    raise requests.exceptions.ConnectionError("brain down")
                for r in json:
                    self.brain.append(dict(r, created_at=self.tick()))
                return Resp(201)
            if url == f"{CRM}/rest/v1/whatsapp_messages":
                self.crm.append(dict(json, created_at=self.tick()))
                return Resp(201)
            raise requests.exceptions.ConnectionError("blocked")

        def get(url, headers=None, params=None, timeout=None, **k):
            params = params or {}
            if url == f"{CRM}/rest/v1/whatsapp_messages":
                if self.crm_fail:
                    raise requests.exceptions.ConnectionError("crm down")
                rows = [r for r in self.crm if r.get("user_id") == OWNER_UID]
                if "wa_message_id" in params:
                    rows = [r for r in rows if r.get("wa_message_id") == params["wa_message_id"][3:]
                            and r["direction"] == params["direction"][3:]]
                if "phone" in params:
                    rows = [r for r in rows if r["phone"] == params["phone"][3:]
                            and _ts(r["created_at"]) > _ts(params["created_at"][3:])]
                return Resp(200, sorted(rows, key=lambda r: r["created_at"]))
            if url == f"{BRAIN}/rest/v1/whatsapp_messages":
                if self.brain_fail:
                    raise requests.exceptions.ConnectionError("brain down")
                prefix = params["content"][len("like."):-1]
                return Resp(200, [{"content": r["content"]} for r in self.brain
                                  if r["phone"] == params["phone"][3:] and r["role"] == "system"
                                  and r["content"].startswith(prefix)])
            raise requests.exceptions.ConnectionError("blocked")

        def fetch_context(phone):
            if self.brain_fail:
                return {"history": [], "last_user": {}, "degraded": True,
                        "recent_sys": [], "paused": False, "stored_messages": None}
            rows = [r for r in self.brain if r["phone"] == phone]
            convo = [r for r in rows if r["role"] in ("user", "assistant")]
            return {"history": [{"role": r["role"], "content": r["content"],
                                 "created_at": r["created_at"]} for r in convo][-20:],
                    "last_user": {}, "paused": False, "vip_alerted": False,
                    "lead_alerted": False, "recent_sys": [], "degraded": False,
                    "stored_messages": len(rows)}

        self._p = [
            mock.patch.object(w, "SUPABASE_URL", BRAIN),
            mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "test-server-key"),
            mock.patch.object(w, "CRM_SUPABASE_URL", CRM),
            mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "test-crm-key"),
            mock.patch.object(w, "CRM_OWNER_USER_ID", OWNER_UID),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w, "_bic_enabled", lambda: False),
            mock.patch.object(w, "get_role",
                              lambda p: ("OWNER", "Owner") if p == OWNER else ("CLIENT", None)),
            mock.patch.object(w, "_wa_post", wa_post),
            mock.patch.object(w, "fetch_context", fetch_context),
            mock.patch.object(w, "notify_owner", lambda m, **k: self.owner_alerts.append(m)),
            mock.patch.object(requests, "post", post),
            mock.patch.object(requests, "get", get),
            mock.patch.object(ev, "select", self.events.select),
            mock.patch.object(ev, "update", self.events.update),
            mock.patch.object(ev.config, "is_configured", lambda: True),
            mock.patch.object(redrive, "_now", lambda: NOW),
        ]
        for p in self._p:
            p.start()
        # The default pipeline: one reply, then the usual turn save.
        self.pipeline_runs = []

        def pipeline(sender, text, ctx, message_id=None):
            self.pipeline_runs.append({"text": text, "history": list(ctx["history"]),
                                       "stored": ctx.get("stored_messages")})
            w.send_text(sender, "reply to " + text)
            w.save_messages([(sender, "user", text), (sender, "assistant", "reply to " + text)])
        self.pipeline = mock.patch.object(w, "run_client_pipeline", pipeline)
        self.pipeline.start()
        w._TURN_EXTRAS.clear()

    def tearDown(self):
        self.pipeline.stop()
        for p in reversed(self._p):
            p.stop()
        w._TURN_EXTRAS.clear()

    # ── world helpers ──────────────────────────────────────────────────
    _clock = 0

    def tick(self):
        self._clock += 1
        return iso(NOW - timedelta(minutes=29) + timedelta(seconds=self._clock))

    def inbound(self, body="25 kva rate?", wamid=WAMID, phone=CUSTOMER, minutes=30,
                saved_first=True, message_type="text"):
        self.crm.append({"user_id": OWNER_UID, "phone": phone, "direction": "inbound",
                         "message_type": message_type, "body": body, "status": "received",
                         "wa_message_id": wamid, "created_at": ago(minutes=minutes)})
        if saved_first:   # Phase 2A saves the customer's message before dispatch
            self.brain.append({"phone": phone, "role": "user", "content": body,
                               "created_at": ago(minutes=minutes)})

    def outbound(self, status, phone=CUSTOMER, minutes=29, wamid="wamid.EARLIER"):
        self.crm.append({"user_id": OWNER_UID, "phone": phone, "direction": "outbound",
                         "message_type": "text", "body": "x", "status": status,
                         "wa_message_id": wamid if status != "failed" else None,
                         "created_at": ago(minutes=minutes)})

    def recover(self, wamid=WAMID):
        with redirect_stdout(io.StringIO()) as out:
            res = redrive.recover_one(dict(self.events.rows[wamid]))
        self.log = out.getvalue()
        return res

    def sweep(self):
        with redirect_stdout(io.StringIO()) as out:
            res = redrive.run(NOW)
        self.log = out.getvalue()
        return res

    def customer_sends(self):
        return [b for to, b in self.sends if to == CUSTOMER]

    def state(self, wamid=WAMID):
        return self.events.rows[wamid]["state"]


# ── A · stale PROCESSING, no reply ──────────────────────────────────────────

class A_StaleProcessing(World):
    def test_recovered_once_and_completed(self):
        self.inbound()
        self.events.put(WAMID, ev.PROCESSING, updated=ago(minutes=15))
        self.assertEqual(self.sweep(), {redrive.REDRIVEN: 1})
        self.assertEqual(self.customer_sends(), ["reply to 25 kva rate?"])
        self.assertEqual(self.state(), ev.COMPLETED)
        self.assertIn("prev_state=PROCESSING", self.log)
        self.assertIn("reason=stale_processing", self.log)

    def test_a_processing_row_younger_than_the_threshold_is_left_alone(self):
        """It may still be running: 9 minutes < the 600 s threshold."""
        self.inbound()
        self.events.put(WAMID, ev.PROCESSING, updated=ago(minutes=9))
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.sends, [])
        self.assertEqual(self.state(), ev.PROCESSING)

    def test_the_threshold_exceeds_every_observed_and_possible_run(self):
        self.assertGreaterEqual(redrive.STALE_PROCESSING_SECONDS, 2 * 300)


# ── B · FAILED, no reply ────────────────────────────────────────────────────

class B_Failed(World):
    def test_recovered(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.assertEqual(self.recover(), redrive.REDRIVEN)
        self.assertEqual(self.customer_sends(), ["reply to 25 kva rate?"])
        self.assertEqual(self.state(), ev.COMPLETED)
        self.assertIsNone(self.events.rows[WAMID]["failure_class"])

    def test_the_original_wamid_phone_and_text_are_used(self):
        self.inbound(body="ನಮಗೆ 63 kVA ಬೇಕು")
        self.events.put(WAMID, ev.FAILED, "VALUE")
        self.recover()
        self.assertEqual(self.pipeline_runs[0]["text"], "ನಮಗೆ 63 kVA ಬೇಕು")
        self.assertEqual(self.sends[0][0], CUSTOMER)
        self.assertIn(WAMID, self.events.rows)                    # same row, no new one
        self.assertEqual(len(self.events.rows), 1)


# ── C · an accepted reply already exists ────────────────────────────────────

class C_ReplyAlreadyAccepted(World):
    def test_not_resent_and_reconciled(self):
        for i, status in enumerate(("sent", "delivered", "read")):
            with self.subTest(status=status):
                wid, phone = f"wamid.C{i}", f"9199990010{i:02d}"
                self.inbound(wamid=wid, phone=phone)
                self.outbound(status, phone=phone)
                self.events.put(wid, ev.FAILED, "UNKNOWN")
                self.assertEqual(self.recover(wid), redrive.RECONCILED)
                self.assertEqual(self.sends, [])
                self.assertEqual(self.state(wid), ev.COMPLETED)
                self.assertIn("outbound=accepted", self.log)

    def test_a_manual_owner_reply_in_the_crm_also_blocks_it(self):
        self.inbound()
        self.crm.append({"user_id": OWNER_UID, "phone": CUSTOMER, "direction": "outbound",
                         "message_type": "text", "body": "typed by owner", "status": "delivered",
                         "wa_message_id": "wamid.MANUAL", "created_at": ago(minutes=25)})
        self.events.put(WAMID, ev.FAILED, "TIMEOUT")
        self.assertEqual(self.recover(), redrive.RECONCILED)
        self.assertEqual(self.sends, [])

    def test_NEGATIVE_CONTROL_without_the_guard_the_customer_is_answered_twice(self):
        self.inbound()
        self.outbound("sent")
        self.events.put(WAMID, ev.FAILED, "UNKNOWN")
        with mock.patch.object(redrive, "reply_evidence", lambda after: "NONE"):
            self.recover()
        self.assertEqual(len(self.customer_sends()), 1, "the guard is what prevents this")


# ── D · concurrent workers ──────────────────────────────────────────────────

class D_Concurrency(World):
    def test_two_workers_with_the_same_snapshot_process_it_once(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        snapshot = dict(self.events.rows[WAMID])
        with redirect_stdout(io.StringIO()):
            first = redrive.recover_one(dict(snapshot))
            second = redrive.recover_one(dict(snapshot))
        self.assertEqual((first, second), (redrive.REDRIVEN, redrive.LOST_RACE))
        self.assertEqual(len(self.customer_sends()), 1)

    def test_a_worker_that_lost_the_race_mid_flight_does_nothing(self):
        """Another worker claimed it between this worker's read and its claim."""
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        snapshot = dict(self.events.rows[WAMID])
        self.assertTrue(ev.reclaim(WAMID, ev.FAILED, snapshot["updated_at"]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(redrive.recover_one(snapshot), redrive.LOST_RACE)
        self.assertEqual(self.sends, [])

    def interleaved(self):
        """Worker 2 starts from the same snapshot while worker 1 is about to
        send — before worker 1's reply exists anywhere. Every check worker 2
        can make passes, except the claim."""
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        snapshot = dict(self.events.rows[WAMID])
        orig, second = w._wa_post, []

        def send(payload):
            if not second:
                second.append(redrive.recover_one(dict(snapshot)))
            return orig(payload)
        with mock.patch.object(w, "_wa_post", send), redirect_stdout(io.StringIO()):
            first = redrive.recover_one(dict(snapshot))
        return first, second[0]

    def test_a_second_worker_racing_the_first_mid_send_does_nothing(self):
        self.assertEqual(self.interleaved(), (redrive.REDRIVEN, redrive.LOST_RACE))
        self.assertEqual(len(self.customer_sends()), 1)

    def test_NEGATIVE_CONTROL_without_the_claim_both_workers_send(self):
        with mock.patch.object(ev, "reclaim", lambda *a: True):
            self.interleaved()
        self.assertEqual(len(self.customer_sends()), 2)


# ── E · bounded attempts ────────────────────────────────────────────────────

class E_AttemptLimit(World):
    send_results = [400, 400, 400, 400, 400]

    def test_stops_after_the_limit_and_tells_the_owner_once(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "VALUE")
        results = []
        for _ in range(4):
            row = self.events.rows[WAMID]
            row["updated_at"] = ago(minutes=10)   # let it look settled again
            results.append(self.recover())
        self.assertEqual(results, [redrive.REDRIVEN, redrive.REDRIVEN,
                                   redrive.EXHAUSTED, redrive.EXHAUSTED])
        self.assertEqual(len(self.customer_sends()), redrive.MAX_ATTEMPTS)
        self.assertEqual(sum("gave up" in m for m in self.owner_alerts), 1)
        self.assertEqual(self.state(), ev.FAILED)

    def test_the_attempt_is_durable_before_the_send(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "VALUE")
        seen = []
        orig = w._wa_post

        def spy(payload):
            seen.append([r["content"] for r in self.brain if r["role"] == "system"])
            return orig(payload)
        with mock.patch.object(w, "_wa_post", spy):
            self.recover()
        self.assertTrue(any("::attempt=1::" in c for c in seen[0]))

    def test_no_attempt_record_means_no_send(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "VALUE")
        with mock.patch.object(w, "save_message", lambda *a, **k: w.SAVE_NETWORK_FAILURE):
            self.assertEqual(self.recover(), redrive.STORE_UNAVAILABLE)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.state(), ev.FAILED)

    def test_NEGATIVE_CONTROL_without_the_limit_it_keeps_sending(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "VALUE")
        with mock.patch.object(redrive, "MAX_ATTEMPTS", 99):
            for _ in range(4):
                self.events.rows[WAMID]["updated_at"] = ago(minutes=10)
                self.recover()
        self.assertEqual(len(self.customer_sends()), 4)


# ── F · rejected reply ──────────────────────────────────────────────────────

class F_RejectedStaysRecoverable(World):
    def test_a_rejected_reply_is_re_driven(self):
        """2A: a rejected Asthra reply is mirrored 'failed' and its assistant
        row is still saved. Rejected means it did not go out — re-drive."""
        self.inbound()
        self.outbound("failed")
        self.brain.append({"phone": CUSTOMER, "role": "assistant",
                           "content": "reply that never arrived", "created_at": ago(minutes=29)})
        self.events.put(WAMID, ev.FAILED, "VALUE")
        self.assertEqual(self.recover(), redrive.REDRIVEN)
        self.assertEqual(len(self.customer_sends()), 1)
        # The undelivered reply is not presented to the pipeline as said.
        self.assertNotIn("reply that never arrived",
                         [m["content"] for m in self.pipeline_runs[0]["history"]])


# ── G · unknown ─────────────────────────────────────────────────────────────

class G_Unknown(World):
    def test_a_timeout_before_any_send_is_re_driven(self):
        """failure_class TIMEOUT with no outbound at all: nothing went out."""
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "TIMEOUT")
        self.assertEqual(self.recover(), redrive.REDRIVEN)
        self.assertEqual(len(self.customer_sends()), 1)

    def test_an_unknown_delivery_goes_to_the_owner_and_is_never_resent(self):
        """A 'pending' outbound (2A: UNKNOWN verdict) may well have arrived.
        I13: never auto-retried. Recovery resolves it to a human, once."""
        self.inbound()
        self.outbound("pending")
        self.events.put(WAMID, ev.FAILED, "TIMEOUT")
        self.assertEqual(self.recover(), redrive.HUMAN_REVIEW)
        self.assertEqual(self.sends, [])
        self.assertEqual(len(self.owner_alerts), 1)
        self.assertEqual(self.state(), ev.FAILED)
        self.events.rows[WAMID]["updated_at"] = ago(minutes=10)
        self.assertEqual(self.recover(), redrive.EXHAUSTED)
        self.assertEqual(len(self.owner_alerts), 1)

    def test_an_assistant_row_without_any_crm_record_is_ambiguous(self):
        """The mirror may have failed after a real send."""
        self.inbound()
        self.brain.append({"phone": CUSTOMER, "role": "assistant", "content": "maybe sent",
                           "created_at": ago(minutes=29)})
        self.events.put(WAMID, ev.FAILED, "UNKNOWN")
        self.assertEqual(self.recover(), redrive.HUMAN_REVIEW)
        self.assertEqual(self.sends, [])


# ── H · successful deliveries are untouched ─────────────────────────────────

class H_CompletedUntouched(World):
    def test_completed_rows_are_never_candidates(self):
        self.inbound()
        self.events.put(WAMID, ev.COMPLETED)
        before = dict(self.events.rows[WAMID])
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.events.rows[WAMID], before)
        self.assertEqual(self.sends, [])

    def test_recover_one_refuses_a_completed_row(self):
        self.inbound()
        self.events.put(WAMID, ev.COMPLETED)
        self.assertEqual(self.recover(), redrive.SKIPPED)
        self.assertEqual(self.sends, [])


# ── I · the customer's message is not duplicated ────────────────────────────

class I_NoDuplicateCustomerRow(World):
    def test_the_row_phase_2a_saved_is_reused(self):
        self.inbound(body="2 units beku")
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.recover()
        users = [r for r in self.brain if r["role"] == "user" and r["content"] == "2 units beku"]
        self.assertEqual(len(users), 1)
        self.assertNotIn("2 units beku",
                         [m["content"] for m in self.pipeline_runs[0]["history"]],
                         "the message is the turn, not part of its history")

    def test_a_message_that_was_never_saved_is_saved_once(self):
        self.inbound(body="2 units beku", saved_first=False)
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.recover()
        users = [r for r in self.brain if r["role"] == "user" and r["content"] == "2 units beku"]
        self.assertEqual(len(users), 1)

    def test_the_stored_count_matches_what_the_live_turn_saw(self):
        self.brain.append({"phone": CUSTOMER, "role": "user", "content": "older",
                           "created_at": ago(hours=2)})
        self.inbound(body="2 units beku")
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.recover()
        self.assertEqual(self.pipeline_runs[0]["stored"], 1)


# ── J / M · Bairavi, through the real pipeline ──────────────────────────────

class BairaviWorld(World):
    def setUp(self):
        super().setUp()
        self.pipeline.stop()
        self.leads = []
        self._b = [
            mock.patch.object(w, "upsert_lead", lambda p, d: self.leads.append(d)),
            mock.patch.object(w, "record_first_seen", lambda *a, **k: None),
            mock.patch.object(w, "fetch_memory", lambda s: {}),
            mock.patch.object(w, "send_welcome_menu", lambda *a, **k: None),
            mock.patch.object(w, "send_followup_buttons", lambda *a, **k: None),
            mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None),
            mock.patch.object(w, "generate_reply", lambda *a, **k: "ASTHRA_AI_REPLY"),
            mock.patch.object(w, "bairavi_model_reply", lambda *a, **k: ""),
            mock.patch.object(w, "shadow_interpret", lambda *a, **k: None),
        ]
        for p in self._b:
            p.start()
        # The real run_client_pipeline from here; keep tearDown symmetric.
        self.pipeline = mock.patch.object(w, "BROCHURE_URL", w.BROCHURE_URL)
        self.pipeline.start()

    def tearDown(self):
        for p in reversed(self._b):
            p.stop()
        super().tearDown()

    def markers(self):
        return [r for r in self.brain if r["role"] == "assistant"
                and r["content"].startswith(bairavi.FLOW_MARKER)]

    def live_turn(self, text, wamid, result="ok"):
        """The live path for one message, as do_POST runs it."""
        self.results.append(result)
        self.inbound(body=text, wamid=wamid, saved_first=False)
        self.events.put(wamid, ev.PROCESSING, updated=ago(minutes=30))
        w._TURN_EXTRAS.clear()
        w._TURN_EXTRAS["turn_sender"] = CUSTOMER
        with redirect_stdout(io.StringIO()):
            ctx = w.fetch_context(CUSTOMER)
            w._save_incoming_first(CUSTOMER, text)
            lc = {"wamid": wamid, "claimed": True, "terminal": False}
            w.run_client_pipeline(CUSTOMER, text, ctx)
            w._finalize_delivery(lc)
        w._TURN_EXTRAS.clear()
        self.events.rows[wamid]["updated_at"] = ago(minutes=10)


class J_BairaviMarker(BairaviWorld):
    def test_a_rejected_opening_is_recovered_with_exactly_one_marker(self):
        self.live_turn(lead_form(), WAMID, result=400)
        self.assertEqual(self.state(), ev.FAILED)
        self.assertEqual(self.markers(), [], "2A: no marker for an undelivered reply")
        self.assertEqual(self.recover(), redrive.REDRIVEN)
        self.assertEqual(len(self.markers()), 1)
        self.assertEqual(self.state(), ev.COMPLETED)
        users = [r for r in self.brain if r["role"] == "user"]
        self.assertEqual(len(users), 1)

    def test_an_accepted_opening_is_not_recovered_and_gains_no_marker(self):
        self.live_turn(lead_form(), WAMID)
        # Simulate a crash after the reply: the row was left PROCESSING.
        self.events.rows[WAMID].update(state=ev.PROCESSING, completed_at=None,
                                       failure_class=None, updated_at=ago(minutes=15))
        self.assertEqual(self.recover(), redrive.RECONCILED)
        self.assertEqual(len(self.markers()), 1)
        self.assertEqual(len(self.customer_sends()), 1)


class M_BairaviTruthUnchanged(BairaviWorld):
    def test_the_recovered_reply_is_the_live_reply(self):
        """Recovery replays the existing decision path; it has no Bairavi
        logic of its own to diverge."""
        self.live_turn(lead_form(capacity="B. 63 kVA"), WAMID, result=400)
        undelivered = self.customer_sends()[0]
        self.recover()
        self.assertEqual(self.customer_sends()[1], undelivered)
        self.assertEqual(undelivered,
                         bairavi.compose_reply(bairavi.parse(lead_form(capacity="B. 63 kVA"))))

    def test_the_worker_holds_no_product_rules(self):
        import inspect
        src = inspect.getsource(redrive)
        for word in ("kVA", "kva", "price", "MESCOM", "compose_reply", "import bairavi"):
            self.assertNotIn(word, src, word)

    def test_a_lead_is_not_duplicated(self):
        """upsert_lead merges on phone; recovery calls it through the same
        path, so the second call updates the same lead."""
        self.live_turn(lead_form(), WAMID, result=400)
        self.recover()
        self.assertEqual({d.get("source") for d in self.leads}, {"bairavi-transformer"})
        src = open(os.path.join(ROOT, "api", "webhook.py"), encoding="utf-8").read()
        self.assertIn('_leads_write_headers("resolution=merge-duplicates")', src)


# ── K · store failures fail closed ──────────────────────────────────────────

class K_FailClosed(World):
    def test_event_store_down_sweeps_nothing(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.events.fail = True
        self.assertEqual(self.sweep(), {redrive.STORE_UNAVAILABLE: 1})
        self.assertEqual(self.sends, [])

    def test_claim_failure_sends_nothing(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        row = dict(self.events.rows[WAMID])
        self.events.fail = True
        with redirect_stdout(io.StringIO()):
            self.assertEqual(redrive.recover_one(row), redrive.LOST_RACE)
        self.assertEqual(self.sends, [])

    def test_crm_down_sends_nothing(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.crm_fail = True
        self.assertEqual(self.recover(), redrive.STORE_UNAVAILABLE)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.state(), ev.FAILED)

    def test_brain_down_sends_nothing(self):
        self.inbound()
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.brain_fail = True
        self.assertEqual(self.recover(), redrive.STORE_UNAVAILABLE)
        self.assertEqual(self.sends, [])

    def test_a_delivery_processed_without_a_claim_is_invisible_to_recovery(self):
        """The live claim fails open: such a turn has no event row, so the
        worker has nothing to re-drive and cannot duplicate it."""
        self.inbound()
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.sends, [])

    def test_recovery_never_inserts_a_claim(self):
        import inspect
        self.assertNotIn("claim(", inspect.getsource(redrive).replace("reclaim(", ""))


# ── L · historical ACCEPTED rows ────────────────────────────────────────────

class L_AcceptedUntouched(World):
    def test_old_accepted_rows_are_not_replayed(self):
        self.inbound(minutes=60 * 24 * 42)
        self.events.put(WAMID, ev.ACCEPTED, created=ago(days=42), updated=ago(days=42))
        before = dict(self.events.rows[WAMID])
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.events.rows[WAMID], before)
        self.assertEqual(self.sends, [])

    def test_even_a_recent_accepted_row_is_not_replayed(self):
        self.inbound()
        self.events.put(WAMID, ev.ACCEPTED, updated=ago(minutes=30))
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.recover(), redrive.SKIPPED)
        self.assertEqual(self.sends, [])

    def test_rows_outside_the_reply_window_are_not_candidates(self):
        self.inbound(minutes=60 * 25)
        self.events.put(WAMID, ev.FAILED, "DATABASE", created=ago(hours=25), updated=ago(hours=25))
        self.assertEqual(self.sweep(), {})
        self.assertEqual(self.sends, [])


# ── N · no endpoint ─────────────────────────────────────────────────────────

class N_NoEndpoint(unittest.TestCase):
    """No secure cron mechanism exists, so no route reaches the worker."""

    def test_no_route_or_build_reaches_the_worker(self):
        cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
        text = json.dumps(cfg)
        self.assertNotIn("redrive", text)
        self.assertNotIn("recover", text.lower())

    def test_the_worker_is_not_an_http_handler_and_webhook_does_not_import_it(self):
        self.assertFalse(hasattr(redrive, "handler"))
        src = open(os.path.join(ROOT, "api", "webhook.py"), encoding="utf-8").read()
        self.assertNotIn("redrive", src)


# ── Scope edges ─────────────────────────────────────────────────────────────

class Edges(World):
    def test_a_newer_customer_message_supersedes_the_old_one(self):
        self.inbound(body="old")
        self.crm.append({"user_id": OWNER_UID, "phone": CUSTOMER, "direction": "inbound",
                         "message_type": "text", "body": "newer", "status": "received",
                         "wa_message_id": "wamid.NEWER", "created_at": ago(minutes=20)})
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.assertEqual(self.recover(), redrive.SUPERSEDED)
        self.assertEqual(self.sends, [])
        self.assertEqual(len(self.owner_alerts), 1)

    def test_owner_chats_are_not_re_driven(self):
        self.inbound(phone=OWNER)
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.assertEqual(self.recover(), redrive.SKIPPED)
        self.assertEqual(self.sends, [])

    def test_media_is_not_re_driven(self):
        self.inbound(message_type="media")
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.assertEqual(self.recover(), redrive.SKIPPED)
        self.assertEqual(self.sends, [])

    def test_one_wamid_at_a_time_and_a_bounded_batch(self):
        for i in range(8):
            wid = f"wamid.BATCH{i}"
            self.inbound(body=f"m{i}", wamid=wid, phone=f"91999900{i:04d}")
            self.events.put(wid, ev.FAILED, "DATABASE")
        res = self.sweep()
        self.assertEqual(sum(res.values()), redrive.BATCH)

    def test_the_log_carries_no_customer_text_phone_or_full_wamid(self):
        self.inbound(body="very private words")
        self.events.put(WAMID, ev.FAILED, "DATABASE")
        self.recover()
        line = [l for l in self.log.splitlines() if l.startswith("RECOVERY ")][0]
        for leak in ("very private words", CUSTOMER, WAMID):
            self.assertNotIn(leak, line)
        for field in ("wamid_ref=", "prev_state=FAILED", "reason=failed:DATABASE",
                      "attempt=1", "outbound=", "result=REDRIVEN"):
            self.assertIn(field, line)


if __name__ == "__main__":
    unittest.main()
