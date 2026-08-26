"""Delivery lifecycle: every claimed webhook reaches a terminal state.

THE BUG
-------
`claim()` wrote ACCEPTED at the earliest point the wamid is known. The old
`mark(PROCESSING)` sat 125 lines further down, past SIX ordinary early-return
branches — interactive tap, failed transcription, image, video/document,
unreadable type, legacy duplicate text. Every one of them returned before the
lifecycle advanced, stranding the row at ACCEPTED permanently.

Production proved it rather than suggested it: three stuck rows, all with
`updated_at == created_at`, and ZERO rows in PROCESSING. Since PROCESSING is
written before dispatch, a crash or timeout would have left PROCESSING — so
the cause was a call that never happened, not work that died.

THE FIX UNDER TEST
------------------
PROCESSING is now marked immediately after a successful claim, before any
branch can return. Terminal state comes from `_finalize_delivery`, invoked
from do_POST's existing `finally` — which already ran on every exit path,
including the `return`s inside the try. A branch added tomorrow is covered
without anyone remembering to cover it.

These tests drive REAL payloads through do_POST. A source grep would not have
caught the original bug, because the code looked correct at every individual
site; only the reachability of the marks was wrong.

Offline: no network, no AI, no database.
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

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import requests                                         # noqa: E402
import webhook as w                                     # noqa: E402
from bic import webhook_events as ev                    # noqa: E402
from bic.db import DbError                              # noqa: E402
from tests.test_webhook_dedupe import FakeEventsDb      # noqa: E402

CUSTOMER = "919999000555"
WAMID = "wamid.HBgMOTE5OTk5MDAwNTU1FQIAEhgg"


def envelope(msg: dict) -> bytes:
    return json.dumps({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}).encode()


def text_msg(body="hello", wamid=WAMID):
    return {"id": wamid, "from": CUSTOMER, "type": "text", "text": {"body": body}}


def interactive_msg(wamid=WAMID):
    return {"id": wamid, "from": CUSTOMER, "type": "interactive",
            "interactive": {"type": "list_reply",
                            "list_reply": {"id": "svc_website", "title": "Website"}}}


def media_msg(kind, wamid=WAMID):
    return {"id": wamid, "from": CUSTOMER, "type": kind, kind: {"id": "media-1"}}


def unreadable_msg(wamid=WAMID):
    return {"id": wamid, "from": CUSTOMER, "type": "sticker", "sticker": {"id": "s1"}}


class Base(unittest.TestCase):
    """Drives do_POST with the outbound side fully stubbed."""

    def setUp(self):
        # OFFLINE, ENFORCED. Without this the text path reaches the real
        # production Supabase URL — bot_roles lookups plus decision-record and
        # replay writes. The fake key made every write 401, so nothing was
        # created, but a suite that dials production at all is one credential
        # away from writing to it. Everything downstream is written to degrade
        # when the store is unreachable, so blocking here also exercises that.
        def _blocked(*a, **k):
            raise requests.exceptions.ConnectionError("network blocked in tests")

        self.db = FakeEventsDb()
        self.sent = []
        self.leads = []
        self.claims = []
        self._p = [
            mock.patch.object(ev, "insert", self.db.insert),
            mock.patch.object(ev, "update", self.db.update),
            mock.patch.object(ev, "select", self.db.select),
            mock.patch.object(ev.config, "is_configured", lambda: True),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w, "send_text",
                              lambda to, t, **k: self.sent.append((to, t))),
            mock.patch.object(w, "send_typing", lambda *a, **k: None),
            mock.patch.object(w, "save_message", lambda *a, **k: None),
            mock.patch.object(w, "save_messages", lambda *a, **k: None),
            mock.patch.object(w, "notify_owner", lambda *a, **k: None),
            mock.patch.object(w, "upsert_lead",
                              lambda p, d: self.leads.append((p, d))),
            mock.patch.object(w, "fetch_context",
                              lambda *a, **k: {"history": [], "last_user": {}}),
            mock.patch.object(w, "handle_list_reply",
                              lambda *a, **k: self.claims.append(a)),
            mock.patch.object(w, "handle_button_reply", lambda *a, **k: None),
            mock.patch.object(w, "transcribe_audio", lambda *a, **k: ""),
            mock.patch.object(w, "download_wa_media", lambda *a, **k: (b"", "image/jpeg")),
            mock.patch.object(w, "analyze_image_with_gemini", lambda *a, **k: ""),
            mock.patch.object(w, "gemini_one_liner", lambda *a, **k: ""),
            mock.patch.object(w, "run_client_pipeline", lambda *a, **k: None),
            mock.patch.object(w, "_bic_client_turn", lambda *a, **k: None),
            mock.patch.object(w, "_bic_owner_turn", lambda *a, **k: None),
            mock.patch.object(w, "_bic_enabled", lambda: False),
            mock.patch.object(requests, "get", _blocked),
            mock.patch.object(requests, "post", _blocked),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in reversed(self._p):
            p.stop()

    def post(self, msg):
        """One webhook delivery through the real do_POST."""
        h = w.handler.__new__(w.handler)
        body = envelope(msg)
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
        return row["state"] if row else None

    def row(self, wamid=WAMID):
        return self.db.rows.get(wamid)


# ── 1-2 · every branch reaches PROCESSING then COMPLETED ───────────────────

class EveryBranchTerminates(Base):

    def test_interactive_menu_tap(self):
        self.post(interactive_msg())
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_audio_transcription_failure(self):
        """The customer GOT a reply, so the turn worked. Marking it FAILED
        because no AI ran would make the failure rate a measure of message
        type rather than of failure."""
        self.post(media_msg("audio"))
        self.assertEqual(self.state(), ev.COMPLETED)
        self.assertIsNone(self.row().get("failure_class"))

    def test_image(self):
        self.post(media_msg("image"))
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_video(self):
        self.post(media_msg("video"))
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_document(self):
        self.post(media_msg("document"))
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_unreadable_type(self):
        self.post(unreadable_msg())
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_legacy_duplicate_text(self):
        """A genuine re-send that Meta gave a NEW wamid: the content check
        catches it and returns early. That row must still terminate."""
        with mock.patch.object(w, "is_duplicate_webhook", lambda *a, **k: True):
            self.post(text_msg())
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_normal_text_turn(self):
        self.post(text_msg())
        self.assertEqual(self.state(), ev.COMPLETED)

    def test_no_branch_leaves_a_row_at_accepted(self):
        """The bug, stated as one assertion over every branch."""
        for i, msg in enumerate([interactive_msg(), media_msg("audio"),
                                 media_msg("image"), media_msg("video"),
                                 media_msg("document"), unreadable_msg(),
                                 text_msg()]):
            msg["id"] = f"wamid.branch{i}"
            self.post(msg)
        stuck = [k for k, r in self.db.rows.items() if r["state"] == ev.ACCEPTED]
        self.assertEqual(stuck, [], f"rows stranded at ACCEPTED: {len(stuck)}")

    def test_every_row_reaches_a_terminal_state(self):
        for i, msg in enumerate([interactive_msg(), media_msg("image"),
                                 unreadable_msg(), text_msg()]):
            msg["id"] = f"wamid.term{i}"
            self.post(msg)
        for wamid, row in self.db.rows.items():
            self.assertIn(row["state"], (ev.COMPLETED, ev.FAILED), wamid)


# ── 3-4 · failure semantics ────────────────────────────────────────────────

class FailureSemantics(Base):

    def test_dispatch_exception_marks_failed(self):
        with mock.patch.object(w, "run_client_pipeline",
                               side_effect=RuntimeError("boom")):
            self.post(text_msg())
        self.assertEqual(self.state(), ev.FAILED)

    def test_failed_carries_a_bounded_class(self):
        with mock.patch.object(w, "run_client_pipeline",
                               side_effect=TimeoutError("slow")):
            self.post(text_msg())
        self.assertIn(self.row().get("failure_class"), ev.FAILURE_CLASSES)

    def test_exception_after_processing_still_terminates(self):
        with mock.patch.object(w, "run_client_pipeline",
                               side_effect=RuntimeError("boom")):
            self.post(text_msg())
        self.assertNotEqual(self.state(), ev.ACCEPTED)
        self.assertNotEqual(self.state(), ev.PROCESSING)

    def test_media_handling_is_not_called_a_failure(self):
        for kind in ("image", "video", "document", "audio"):
            self.db.rows.clear()
            self.post(media_msg(kind))
            self.assertEqual(self.state(), ev.COMPLETED, kind)
            self.assertIsNone(self.row().get("failure_class"), kind)

    def test_no_duplicate_terminal_transition(self):
        """A second terminal write would make the audit trail lie about when
        the turn ended."""
        marks = []
        real = ev.mark

        def spy(wamid, state, failure_class=None):
            marks.append(state)
            return real(wamid, state, failure_class)

        with mock.patch.object(w.bic_events, "mark", spy):
            self.post(text_msg())
        terminals = [m for m in marks if m in (ev.COMPLETED, ev.FAILED)]
        self.assertEqual(len(terminals), 1, marks)

    def test_failure_path_also_marks_exactly_once(self):
        marks = []
        real = ev.mark

        def spy(wamid, state, failure_class=None):
            marks.append(state)
            return real(wamid, state, failure_class)

        with mock.patch.object(w.bic_events, "mark", spy), \
             mock.patch.object(w, "run_client_pipeline",
                               side_effect=RuntimeError("boom")):
            self.post(text_msg())
        self.assertEqual([m for m in marks if m in (ev.COMPLETED, ev.FAILED)],
                         [ev.FAILED])


# ── 5-6, 14 · duplicates and concurrency ───────────────────────────────────

class Duplicates(Base):

    def test_second_delivery_of_the_same_wamid_is_a_duplicate(self):
        self.post(text_msg())
        before = dict(self.row())
        self.post(text_msg())
        self.assertEqual(self.db.inserts, 2)          # both tried
        self.assertEqual(len(self.db.rows), 1)        # one row exists

    def test_duplicate_does_not_alter_the_existing_event(self):
        self.post(text_msg())
        first = dict(self.row())
        self.post(text_msg())
        after = self.row()
        self.assertEqual(after["state"], first["state"])
        self.assertEqual(after.get("completed_at"), first.get("completed_at"))

    def test_duplicate_sends_no_second_reply(self):
        with mock.patch.object(w, "run_client_pipeline",
                               lambda to, *a, **k: self.sent.append((to, "reply"))):
            self.post(text_msg())
            count_after_first = len(self.sent)
            self.post(text_msg())
        self.assertEqual(len(self.sent), count_after_first)

    def test_concurrent_retries_have_exactly_one_winner(self):
        """The claim is an INSERT on a PRIMARY KEY — the unique violation IS
        the duplicate answer. Two workers cannot both win."""
        results = [ev.claim(WAMID) for _ in range(5)]
        self.assertEqual(results.count(ev.ACCEPTED), 1)
        self.assertEqual(results.count(ev.DUPLICATE), 4)

    def test_no_select_then_update_race_in_the_claim(self):
        import inspect
        src = inspect.getsource(ev.claim)
        self.assertIn("insert(", src)
        self.assertNotIn("select(", src)

    def test_duplicate_path_never_marks(self):
        marks = []
        with mock.patch.object(w.bic_events, "mark",
                               lambda *a, **k: marks.append(a[1])):
            self.post(text_msg())
            first = len(marks)
            self.post(text_msg())
        self.assertEqual(len(marks), first, "duplicate touched the winner's row")


# ── 7-10 · existing behaviour preserved ────────────────────────────────────

class NoRegression(Base):

    def test_interactive_menu_still_handled(self):
        self.post(interactive_msg())
        self.assertEqual(len(self.claims), 1)

    def test_media_still_replies_to_the_customer(self):
        self.post(media_msg("image"))
        self.assertTrue(self.sent)

    def test_normal_turn_still_dispatches(self):
        called = []
        with mock.patch.object(w, "run_client_pipeline",
                               lambda *a, **k: called.append(a)):
            self.post(text_msg())
        self.assertEqual(len(called), 1)

    def test_claims_module_untouched(self):
        import inspect
        from bic import claims
        self.assertNotIn("_finalize_delivery", inspect.getsource(claims))

    def test_decision_record_module_untouched(self):
        import inspect
        from bic import decision
        self.assertNotIn("_finalize_delivery", inspect.getsource(decision))

    def test_replay_module_untouched(self):
        import inspect
        from bic import replay
        self.assertNotIn("_finalize_delivery", inspect.getsource(replay))

    def test_webhook_events_module_unchanged_by_this_slice(self):
        """The fix is entirely in the CALLER. mark() stays unconditional on
        purpose — see the concurrency note in the report."""
        import inspect
        src = inspect.getsource(ev.mark)
        self.assertNotIn("eq.ACCEPTED", src)
        self.assertNotIn("state=eq.", src)


# ── 11-12 · no PII, no raw exception text ──────────────────────────────────

class NoPii(Base):

    def test_failure_row_carries_no_exception_text(self):
        with mock.patch.object(w, "run_client_pipeline",
                               side_effect=RuntimeError(f"boom {CUSTOMER} secret")):
            self.post(text_msg())
        blob = repr(self.row())
        self.assertNotIn(CUSTOMER, blob)
        self.assertNotIn("secret", blob)
        self.assertNotIn("boom", blob)

    def test_failure_class_is_from_the_bounded_vocabulary(self):
        with mock.patch.object(w, "run_client_pipeline",
                               side_effect=RuntimeError("x")):
            self.post(text_msg())
        self.assertIn(self.row().get("failure_class"), ev.FAILURE_CLASSES)

    def test_the_turn_log_never_carries_the_wamid(self):
        """WEBHOOK_TURN is printed on every request; a delivery identifier
        does not belong in it."""
        out = self.post(text_msg())
        line = [l for l in out.splitlines() if l.startswith("WEBHOOK_TURN")]
        self.assertTrue(line)
        self.assertNotIn(WAMID, line[0])
        self.assertNotIn(CUSTOMER, line[0])

    def test_lifecycle_state_is_not_part_of_the_logged_turn(self):
        import inspect
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn("lifecycle = _new_lifecycle()", src)
        self.assertNotIn('turn["wamid"]', src)


# ── 15 · historical rows ───────────────────────────────────────────────────

class HistoricalRows(Base):

    def test_nothing_sweeps_or_rewrites_old_rows(self):
        """Reconciliation of the three production ACCEPTED rows is a separate
        decision. This slice must not quietly make it."""
        import inspect
        for fn in (w._finalize_delivery, w.handler.do_POST):
            src = inspect.getsource(fn)
            for smell in ("sweep", "reconcile", "backfill", "state=eq.ACCEPTED"):
                self.assertNotIn(smell, src)

    def test_a_pre_existing_accepted_row_is_never_touched(self):
        self.db.rows["wamid.historical"] = {
            "wamid": "wamid.historical", "state": ev.ACCEPTED,
            "failure_class": None, "completed_at": None}
        before = dict(self.db.rows["wamid.historical"])
        self.post(text_msg())
        self.assertEqual(self.db.rows["wamid.historical"], before)

    def test_no_migration_touches_the_event_table(self):
        """The lifecycle fix is entirely in the caller — migration 13's schema
        already carried every state used.

        This asserted "no migration exists anywhere" to prove "this slice adds
        none", which was over-broad: it failed the moment an unrelated slice
        added one. The real claim is that nothing re-shapes or rewrites
        bic_webhook_events, so that is what it now checks.
        """
        import glob
        root = os.path.join(os.path.dirname(__file__), "..")
        offenders = []
        for path in glob.glob(os.path.join(root, "supabase", "migrations", "*.sql")):
            raw = open(path).read()
            # Comments stripped first. A later migration may legitimately
            # MENTION this table in prose — migration 17 explains that
            # execution telemetry is not an outcome — and matching that
            # reports a mutation which does not exist.
            sql = "\n".join(line.split("--", 1)[0] for line in raw.splitlines())
            if "bic_webhook_events" not in sql:
                continue
            name = os.path.basename(path)
            # Migration 13 CREATED the table; nothing after it may alter,
            # delete from, or update it.
            if name.startswith("20260816000013"):
                continue
            offenders.append(name)
        self.assertEqual(offenders, [],
                         f"a later migration touches bic_webhook_events: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
