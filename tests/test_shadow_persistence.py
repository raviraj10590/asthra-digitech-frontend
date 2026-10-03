"""Persistent shadow telemetry — Design B (owner-approved 2026-09-27).

Turn key, PII, versioning, the bounded writer, the migration's structure,
the daily prune, and isolation from every production memory. No network and
no database are touched: requests is mocked, and the migration is checked as
text here (it was additionally exercised in a throwaway local Postgres; see
the commit message).
"""
import ast
import hashlib
import hmac
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402
import interpretation as I  # noqa: E402
import webhook as w  # noqa: E402
from test_interpretation_shadow import (THREAD, TEST_TURN_KEY, adversarial,  # noqa: E402
                                        contract, run_conversation)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIGRATION = os.path.join(ROOT, "supabase", "migrations",
                         "20260927000001_bairavi_shadow_interpretations.sql")
SQL = open(MIGRATION).read()
SQL_CODE = "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def keyed(env_key=TEST_TURN_KEY):
    return mock.patch.dict(os.environ, {"SHADOW_TURN_KEY": env_key})


# ══════════════════════════════════════════════════════════════════════════
# TURN KEY
# ══════════════════════════════════════════════════════════════════════════

class TheTurnKey(unittest.TestCase):
    def test_deterministic_hmac(self):
        with keyed():
            k1, k2 = w.shadow_turn_key("wamid.ABC"), w.shadow_turn_key("wamid.ABC")
        expected = hmac.new(TEST_TURN_KEY.encode(), b"wamid.ABC", hashlib.sha256).hexdigest()[:32]
        self.assertEqual(k1, k2)
        self.assertEqual(k1, expected)
        self.assertRegex(k1, r"^[0-9a-f]{32}$")

    def test_different_wamid_different_key(self):
        with keyed():
            self.assertNotEqual(w.shadow_turn_key("wamid.A"), w.shadow_turn_key("wamid.B"))

    def test_different_secret_different_key(self):
        with keyed("one-" + os.urandom(4).hex()):
            a = w.shadow_turn_key("wamid.A")
        with keyed("two-" + os.urandom(4).hex()):
            c = w.shadow_turn_key("wamid.A")
        self.assertNotEqual(a, c)

    def test_no_wamid_or_no_secret_means_no_key(self):
        with keyed():
            self.assertIsNone(w.shadow_turn_key(None))
            self.assertIsNone(w.shadow_turn_key(""))
        with keyed(""):
            self.assertIsNone(w.shadow_turn_key("wamid.A"))
        with keyed("   "):
            self.assertIsNone(w.shadow_turn_key("wamid.A"))

    def test_phone_and_text_cannot_reproduce_it(self):
        phone, text = "910000000077", "2 beku"
        with keyed():
            key = w.shadow_turn_key("wamid.X")
        for guess in (hashlib.sha256(f"{phone}|{text}".encode()).hexdigest(),
                      hashlib.sha256(b"wamid.X").hexdigest(),
                      hmac.new(phone.encode(), text.encode(), hashlib.sha256).hexdigest()):
            self.assertNotEqual(key, guess[:32])

    def test_the_phone_text_fallback_is_gone(self):
        src = open(os.path.join(ROOT, "api", "webhook.py")).read()
        self.assertNotIn('f"{sender}|{user_text}"', src)
        self.assertNotIn("turn_ref", src)

    def test_without_wamid_there_is_no_record_and_no_model_call(self):
        called, recs = [], []
        with mock.patch.dict(os.environ, {"SHADOW_INTERPRETATION": "on",
                                          "SHADOW_TURN_KEY": TEST_TURN_KEY}), \
             mock.patch.object(w, "_provider_chain",
                               lambda: [("deepseek", lambda m, t=None: called.append(1) or "")]), \
             mock.patch.object(w, "_shadow_sink", recs.append):
            w.start_turn_clock()
            w.shadow_interpret("910000000077", "2 beku", [], b.parse_followup("2 beku"), {}, None)
        w._TURN_CLOCK["deadline"] = None
        self.assertEqual((called, recs), ([], []))

    def test_without_the_secret_there_is_no_record(self):
        recs = []
        with mock.patch.dict(os.environ, {"SHADOW_INTERPRETATION": "on", "SHADOW_TURN_KEY": ""}), \
             mock.patch.object(w, "_shadow_sink", recs.append):
            w.shadow_interpret("9100", "2 beku", [], b.parse_followup("2 beku"), {}, "wamid.X")
        self.assertEqual(recs, [])

    def test_the_secret_never_appears_in_records_or_logs(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf), \
             mock.patch.object(w.requests, "post", side_effect=RuntimeError("down")):
            run = run_conversation(THREAD, shadow=True, provider=adversarial)
        blob = json.dumps(run.shadow, ensure_ascii=False) + buf.getvalue()
        self.assertTrue(run.shadow)
        self.assertNotIn(TEST_TURN_KEY, blob)

    def test_the_secret_is_not_in_the_repository(self):
        self.assertNotIn("SHADOW_TURN_KEY=", open(os.path.join(ROOT, "api", "webhook.py")).read())


# ══════════════════════════════════════════════════════════════════════════
# PII — Design B
# ══════════════════════════════════════════════════════════════════════════

class NoCustomerWordsArePersisted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def everything(messages, t=None):
            text = messages[-1]["content"]
            return json.dumps(contract(
                delivery_place=(text, text), quantity=(2, text), application=("AGRICULTURE", text),
                capacity_kva=(63, text), callback=("now", text)))
        cls.result = run_conversation(THREAD + ["Sulekere village, call 9845012345"],
                                   shadow=True, provider=everything)

    def test_records_have_exactly_the_table_columns(self):
        for rec in self.result.shadow:
            self.assertEqual(set(rec), set(I.RECORD_COLUMNS))

    def test_no_phone_body_wamid_evidence_place_or_raw_output(self):
        for rec in self.result.shadow:
            blob = json.dumps(rec, ensure_ascii=False)
            for banned in ("910000000077", "9845012345", "Sulekere", "ಗುಜರಾತ್", "quotation beku",
                           "2 beku", "wamid.", "Sira", '"evidence":', "Hello! I filled"):
                self.assertNotIn(banned, blob, banned)

    def test_delivery_place_is_an_outcome_only(self):
        seen = False
        for rec in self.result.shadow:
            slot = (rec.get("proposed") or {}).get("delivery_place")
            if slot:
                seen = True
                self.assertIsNone(slot["value"])
                self.assertIn(slot["outcome"], ("accepted", "not_a_place", "context",
                                                 "no_evidence", "rejected"))
            self.assertNotIn("delivery_place", rec.get("diffs") or {})
            self.assertNotIn("delivery_location", rec.get("accepted") or {})
        self.assertTrue(seen)

    def test_only_vocabulary_values_are_kept(self):
        rep = I.field_report(contract(application=("free text here", "x"),
                                      callback=("whenever", "x")), "x", {"_rejected": ()})
        self.assertIsNone(rep["application"]["value"])
        self.assertIsNone(rep["callback"]["value"])


# ══════════════════════════════════════════════════════════════════════════
# VERSIONING
# ══════════════════════════════════════════════════════════════════════════

class Versions(unittest.TestCase):
    def test_contract_version_is_deterministic_and_tracks_the_schema(self):
        v = I.contract_version()
        self.assertEqual(v, I.contract_version())
        self.assertRegex(v, r"^c1-[0-9a-f]{8}$")
        with mock.patch.object(I, "QUESTIONS", I.QUESTIONS + ("their_name",)):
            self.assertNotEqual(I.contract_version(), v)
        with mock.patch.object(I, "APPLICATIONS", I.APPLICATIONS + ("MINING",)):
            self.assertNotEqual(I.contract_version(), v)

    def test_validator_version_is_an_explicit_constant(self):
        # v4 (2026-10-03): call_missed, asks_info, asks_scope/photo/documents
        # passed through, Brain-owned.
        self.assertEqual(I.VALIDATOR_VERSION, "v4")
        src = open(os.path.join(ROOT, "interpretation.py")).read()
        self.assertIn('VALIDATOR_VERSION = "v4"', src)

    def test_prompt_version_is_the_template_not_the_context(self):
        self.assertRegex(I.prompt_version(), r"^[0-9a-f]{12}$")
        self.assertEqual(I.prompt_version(),
                         hashlib.sha256(I._BRIEF_TEMPLATE.encode()).hexdigest()[:12])
        with mock.patch.object(I, "_BRIEF_TEMPLATE", I._BRIEF_TEMPLATE + " "):
            self.assertNotEqual(I.prompt_version(), hashlib.sha256(
                I._BRIEF_TEMPLATE.strip().encode()).hexdigest()[:12] + "x")

    def test_the_prompt_is_never_stored(self):
        rec = I.shadow_record(status=I.S_SKIPPED_DEADLINE, turn_key="a" * 32, awaiting=())
        blob = json.dumps(rec)
        self.assertNotIn("WhatsApp message", blob)
        self.assertNotIn("Already known", blob)
        self.assertEqual((rec["record_version"], rec["validator_version"]),
                         (I.RECORD_VERSION, I.VALIDATOR_VERSION))


# ══════════════════════════════════════════════════════════════════════════
# THE WRITER
# ══════════════════════════════════════════════════════════════════════════

REC = I.shadow_record(status=I.S_SKIPPED_DEADLINE, turn_key="a" * 32, awaiting=())


class TheWriter(unittest.TestCase):
    def tearDown(self):
        w._TURN_CLOCK["deadline"] = None

    def _post(self, **kw):
        calls = []

        def fake(url, **k):
            calls.append((url, k))
            if "exc" in kw:
                raise kw["exc"]
            return mock.Mock(status_code=kw.get("status", 201), text="SECRET-BODY")
        return calls, fake

    def test_service_role_bounded_idempotent_single_call(self):
        calls, fake = self._post()
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "svc-key"), \
             mock.patch.object(w.requests, "post", fake):
            w.start_turn_clock()
            w._shadow_insert(REC)
        self.assertEqual(len(calls), 1)
        url, k = calls[0]
        self.assertTrue(url.endswith("/rest/v1/bairavi_shadow_interpretations"))
        self.assertEqual(k["params"], {"on_conflict": "turn_key,contract_version,validator_version"})
        self.assertIn("resolution=ignore-duplicates", k["headers"]["Prefer"])
        self.assertEqual(k["headers"]["Authorization"], "Bearer svc-key")
        self.assertNotEqual(k["headers"]["apikey"], w.SUPABASE_KEY)          # never the anon key
        self.assertLessEqual(k["timeout"], 2.0)
        self.assertEqual(k["json"], REC)

    def test_the_conflict_key_is_the_migrations_unique_constraint(self):
        self.assertIn("unique (turn_key, contract_version, validator_version)", SQL_CODE)
        self.assertEqual(w.SHADOW_CONFLICT_KEY, "turn_key,contract_version,validator_version")

    def test_no_credential_no_write_no_anon_fallback(self):
        calls, fake = self._post()
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", ""), \
             mock.patch.object(w.requests, "post", fake):
            w._shadow_insert(REC)
        self.assertEqual(calls, [])

    def test_failures_never_raise_never_retry_never_log_the_body(self):
        import io
        from contextlib import redirect_stdout
        for kw in ({"status": 500}, {"status": 409}, {"exc": TimeoutError("t")},
                   {"exc": ConnectionError("c")}):
            calls, fake = self._post(**kw)
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "svc-key"), \
                 mock.patch.object(w.requests, "post", fake):
                w.start_turn_clock()
                w._shadow_insert(REC)
            self.assertEqual(len(calls), 1, kw)
            self.assertNotIn("SECRET-BODY", buf.getvalue())
            self.assertNotIn("svc-key", buf.getvalue())

    def test_the_insert_never_eats_the_functions_last_second(self):
        calls, fake = self._post()
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "svc-key"), \
             mock.patch.object(w.requests, "post", fake):
            w._TURN_CLOCK["deadline"] = w.time.monotonic() - w.POST_AI_RESERVE_SECONDS + 1.2
            w._shadow_insert(REC)                     # ~1.2s to the hard limit: skipped
            self.assertEqual(calls, [])
            w._TURN_CLOCK["deadline"] = w.time.monotonic() - w.POST_AI_RESERVE_SECONDS + 2.0
            w._shadow_insert(REC)                     # ~2s left: at most 1s allowed
            self.assertLessEqual(calls[0][1]["timeout"], 1.01)

    def test_a_database_failure_changes_nothing_for_the_customer(self):
        """The real sink + writer, with the database down."""
        off = run_conversation(THREAD)
        with mock.patch.object(w, "SUPABASE_SERVICE_ROLE_KEY", "svc-key"):
            down = self._run_with_real_sink(RuntimeError("db down"))
        self.assertEqual(down["sent"], off.sent)
        self.assertEqual(down["saved"], off.saved)
        self.assertEqual(down["owner"], off.owner)
        self.assertEqual(down["leads"], off.leads)
        self.assertGreater(down["inserts"], 0)

    def _run_with_real_sink(self, exc):
        """run_conversation, but the sink is the real one and requests.post fails."""
        import test_interpretation_shadow as T
        inserts = []

        def post(url, **k):
            inserts.append(url)
            raise exc
        real_sink = w._shadow_sink
        with mock.patch.object(T.w, "_shadow_sink", real_sink):
            orig = T.run_conversation.__globals__["mock"].patch.object

            def patch_object(target, name, *a, **k):
                if target is w.requests and name == "post":
                    return orig(target, name, post)
                if target is w and name == "_shadow_sink":
                    return orig(target, name, real_sink)
                return orig(target, name, *a, **k)
            with mock.patch.object(T.mock.patch, "object", patch_object):
                run = T.run_conversation(THREAD, shadow=True, provider=adversarial)
        return {"sent": run.sent, "saved": run.saved, "owner": run.owner,
                "leads": run.leads, "inserts": len(inserts)}


# ══════════════════════════════════════════════════════════════════════════
# THE MIGRATION (static — never applied from here)
# ══════════════════════════════════════════════════════════════════════════

class TheMigration(unittest.TestCase):
    def columns(self):
        body = SQL_CODE.split("create table if not exists public.bairavi_shadow_interpretations (")[1]
        body = body.split("\n);")[0]
        return [m.group(1) for m in re.finditer(r"^\s{2}([a-z_]+)\s+(?!key)", body, re.M)
                if m.group(1) not in ("constraint", "unique", "check")]

    def test_columns_are_exactly_the_record_plus_id_and_created_at(self):
        self.assertEqual(set(self.columns()), set(I.RECORD_COLUMNS) | {"id", "created_at"})

    def test_no_forbidden_column_or_reference(self):
        low = SQL_CODE.lower()
        for banned in ("phone", "body", "wamid", "evidence text", "message_id", "references ",
                       "foreign key", "create trigger", "create policy"):
            self.assertNotIn(banned, low, banned)
        self.assertNotIn("delivery_location", low)

    def test_security_and_retention_statements(self):
        low = SQL_CODE.lower()
        for must in ("enable row level security",
                     "revoke all on public.bairavi_shadow_interpretations from public, anon, authenticated",
                     "revoke all on sequence public.bairavi_shadow_interpretations_id_seq from public, anon, authenticated",
                     "revoke update on public.bairavi_shadow_interpretations from service_role",
                     "grant insert, select, delete on public.bairavi_shadow_interpretations to service_role",
                     "security invoker",
                     "revoke execute on function public.bairavi_prune_shadow_interpretations(integer)\n  from public, anon, authenticated",
                     "grant execute on function public.bairavi_prune_shadow_interpretations(integer) to service_role",
                     "not diffs ? 'delivery_place'"):
            self.assertIn(must, low, must)
        self.assertNotIn("security definer", low)
        self.assertNotIn("grant update", low)
        self.assertNotIn("grant all", low)

    def test_it_is_marked_not_applied(self):
        self.assertIn("APPLIED: NO", SQL)


# ══════════════════════════════════════════════════════════════════════════
# THE DAILY PRUNE
# ══════════════════════════════════════════════════════════════════════════

class TheDailyPrune(unittest.TestCase):
    def test_digest_calls_the_prune_safely(self):
        src = open(os.path.join(ROOT, "api", "digest.py")).read()
        i = src.index("rpc/bairavi_prune_shadow_interpretations")
        block = src[src.rindex("try:", 0, i): src.index("except Exception", i) + 200]
        self.assertIn('"retain_days": 14', block)
        self.assertIn("timeout=5", block)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", block)
        self.assertIn("404", block)                          # function absent: skip
        self.assertIn("(ignored)", block)
        self.assertNotIn("r.text", block)                    # status only
        self.assertEqual(src.count("rpc/bairavi_prune_shadow_interpretations"), 1)   # no retry loop


# ══════════════════════════════════════════════════════════════════════════
# ISOLATION — observation only
# ══════════════════════════════════════════════════════════════════════════

class ShadowFeedsNothing(unittest.TestCase):
    SHADOW_FNS = ("shadow_interpret", "_shadow_interpret", "_shadow_sink", "_shadow_insert",
                  "shadow_turn_key", "_shadow_write_headers")
    FORBIDDEN = {"send_text", "save_messages", "save_message", "upsert_lead", "notify_owner",
                 "sync_lead_to_crm", "log_reply_to_crm", "_mirror_outbound_to_crm",
                 "record_first_seen", "_generate_ai_reply", "bairavi_model_reply",
                 "mark_ai_consulted", "send_welcome_menu"}

    def test_shadow_functions_call_no_production_side_effect(self):
        tree = ast.parse(open(os.path.join(ROOT, "api", "webhook.py")).read())
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name in self.SHADOW_FNS):
            names = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                     for c in ast.walk(fn) if isinstance(c, ast.Call)}
            self.assertFalse(names & self.FORBIDDEN, f"{fn.name}: {names & self.FORBIDDEN}")

    def test_nothing_reads_the_table(self):
        """The table name appears only where it is written (webhook) and pruned
        (digest). No SELECT, no GET, no reader anywhere in production code."""
        hits = []
        for dirpath, _, files in os.walk(ROOT):
            if any(p in dirpath for p in ("/tests", "/.git", "/node_modules", "/supabase")):
                continue
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(dirpath, f)
                    if "bairavi_shadow_interpretations" in open(path, errors="ignore").read():
                        hits.append(os.path.relpath(path, ROOT))
        # ops/learning_report.py is the OFFLINE reviewer the design names
        # ("with the secret, a reviewer can find the original message"): it
        # runs on the owner's Mac, reads for a weekly report, and nothing in
        # the live pipeline imports it (checked below). 2026-10-01.
        self.assertEqual(sorted(hits), ["api/webhook.py", "interpretation.py",
                                        "ops/learning_report.py"])
        for dirpath, _, files in os.walk(os.path.join(ROOT, "api")):
            for f in files:
                if f.endswith(".py"):
                    self.assertNotIn("learning_report", open(os.path.join(dirpath, f)).read(), f)
        for f in ("bairavi.py", "interpretation.py", "call_briefing.py", "call_log.py", "geo_escom.py"):
            self.assertNotIn("learning_report", open(os.path.join(ROOT, f)).read(), f)
        # interpretation.py only NAMES it in a comment; no code there touches it
        for line in open(os.path.join(ROOT, "interpretation.py")).read().splitlines():
            if "bairavi_shadow_interpretations" in line:
                self.assertTrue(line.strip().startswith("#"), line)
        # the webhook: one constant, used by exactly one POST; the digest only
        # calls the prune FUNCTION
        src = open(os.path.join(ROOT, "api", "webhook.py")).read()
        self.assertEqual(src.count('"bairavi_shadow_interpretations"'), 1)
        self.assertEqual(src.count("SHADOW_TABLE"), 2)
        self.assertNotIn("rest/v1/{SHADOW_TABLE}?select", src)
        self.assertNotIn("requests.get(f\"{SUPABASE_URL}/rest/v1/{SHADOW_TABLE}", src)

    def test_the_shadow_record_is_never_fed_back(self):
        src = open(os.path.join(ROOT, "api", "webhook.py")).read()
        for use in re.finditer(r"shadow_interpret\(", src):
            line = src[src.rindex("\n", 0, use.start()) + 1: src.index("\n", use.start())]
            self.assertNotIn("=", line.split("shadow_interpret(")[0], line)   # result unused


if __name__ == "__main__":
    unittest.main()
