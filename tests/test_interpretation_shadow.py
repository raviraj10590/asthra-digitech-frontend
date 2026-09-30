"""Step 2 — interpretation SHADOW MODE (2026-09-27).

The shadow interpreter observes a Bairavi follow-up AFTER production has
handled it, and only writes a telemetry record. These tests prove it has zero
authority: the same conversation run with shadow OFF and ON (with a fake,
adversarial interpreter) produces byte-identical replies, transcript rows,
owner alerts, lead writes and network calls.

No real provider is called anywhere in this file.
"""
import copy
import datetime
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bairavi as b  # noqa: E402
import interpretation as I  # noqa: E402
import webhook as w  # noqa: E402

NOW_ISO = datetime.datetime.now(datetime.timezone.utc).isoformat()
# A random per-run value — NOT the production secret, never a fixed string.
TEST_TURN_KEY = os.urandom(16).hex()


def contract(intent="answer", questions=(), correction=False, ambiguous=False, **fields):
    return {"intent": intent, "questions": list(questions), "is_correction": correction,
            "ambiguous": ambiguous,
            "fields": {k: {"value": v[0], "evidence": v[1]} for k, v in fields.items()}}


# ══════════════════════════════════════════════════════════════════════════
# HARNESS — the real webhook pipeline, every side effect captured
# ══════════════════════════════════════════════════════════════════════════

class Run:
    def __init__(self):
        self.sent, self.owner, self.leads, self.saved = [], [], [], []
        self.network, self.shadow = [], []


def run_conversation(messages, *, shadow=False, provider=None, clock_left=None):
    """Drive run_client_pipeline turn by turn, like fetch_context would."""
    run, history = Run(), []

    def net(kind):
        def f(*a, **k):
            run.network.append(kind)
            raise AssertionError(f"unexpected network call: {kind}")
        return f

    for text in messages:
        ctx = {"history": list(history), "recent_sys": [], "paused": False,
               "vip_alerted": False, "lead_alerted": False, "last_user": {}}
        saved = []
        env = {"SHADOW_INTERPRETATION": "on" if shadow else "off", "SHADOW_TURN_KEY": TEST_TURN_KEY}
        chain = [("deepseek", provider or (lambda m, t=None: ""))]
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(w, "fetch_memory", lambda s: {}), \
             mock.patch.object(w, "record_first_seen", lambda *a, **k: None), \
             mock.patch.object(w, "send_text", lambda to, t, **k: run.sent.append(t)), \
             mock.patch.object(w, "send_welcome_menu", lambda to: run.sent.append("<MENU>")), \
             mock.patch.object(w, "upsert_lead", lambda p, d: run.leads.append(copy.deepcopy(d))), \
             mock.patch.object(w, "notify_owner", lambda m, **k: run.owner.append(m)), \
             mock.patch.object(w, "save_messages", lambda rows: (saved.extend(rows), w.SAVE_OK)[1]), \
             mock.patch.object(w, "save_message", lambda *a, **k: (saved.append(a), w.SAVE_OK)[1]), \
             mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None), \
             mock.patch.object(w, "generate_reply", lambda *a, **k: "<ASTHRA>"), \
             mock.patch.object(w, "bairavi_model_reply", lambda *a, **k: ""), \
             mock.patch.object(w, "BIC_AVAILABLE", False), \
             mock.patch.object(w, "_provider_chain", lambda: chain), \
             mock.patch.object(w, "_shadow_sink", lambda r: run.shadow.append(r)), \
             mock.patch.object(w.requests, "post", net("post")), \
             mock.patch.object(w.requests, "get", net("get")), \
             mock.patch.object(w.requests, "patch", net("patch")):
            if clock_left is not None:
                w._TURN_CLOCK["deadline"] = w.time.monotonic() + clock_left
            else:
                w.start_turn_clock()
            w.run_client_pipeline("910000000077", text, ctx, message_id=f"wamid.{len(history)}")
        for row in saved:
            if len(row) == 3:
                history.append({"role": row[1], "content": row[2], "created_at": NOW_ISO})
        run.saved.extend(saved)
    w._TURN_CLOCK["deadline"] = None
    run.history = history
    return run


FORM = ("Hello! I filled out your form\n"
        "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
        "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: Sira\nFull name: Test")
THREAD = [FORM, "2 beku", "ಕೃಷಿ", "ಗುಜರಾತ್", "rate?", "quotation beku", "1", "K"]


def adversarial(messages, max_tokens=None):
    """An interpreter trying everything a real one might get wrong."""
    return json.dumps(contract(
        intent="quotation_request", questions=["warranty", "payment"], correction=True,
        capacity_kva=(250, "250 kVA"),                 # evidence not in the message
        quantity=(99, "99"), application=("MINING", "mining"),
        delivery_place=("Mysuru", "Mysuru"), callback=("now", "now")))


# ══════════════════════════════════════════════════════════════════════════
# 1-7, 10 · THE SAFETY BOUNDARY
# ══════════════════════════════════════════════════════════════════════════

class ShadowHasNoAuthority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = run_conversation(THREAD, shadow=False)
        cls.on = run_conversation(THREAD, shadow=True, provider=adversarial)

    def test_1_replies_are_byte_identical(self):
        self.assertEqual(self.on.sent, self.off.sent)

    def test_2_3_transcript_and_saved_facts_are_identical(self):
        self.assertEqual(self.on.saved, self.off.saved)
        self.assertEqual(b.established_from_history(self.on.history),
                         b.established_from_history(self.off.history))

    def test_4_lead_writes_are_identical(self):
        self.assertEqual(self.on.leads, self.off.leads)

    def test_5_no_network_call_at_all(self):
        """CRM messages, CRM leads, Supabase, Meta: every requests.* is a spy
        that would have failed the turn. Neither run made one."""
        self.assertEqual(self.on.network, [])
        self.assertEqual(self.off.network, [])

    def test_6_owner_alerts_are_identical(self):
        self.assertEqual(self.on.owner, self.off.owner)

    def test_shadow_actually_ran_in_the_on_run(self):
        self.assertGreaterEqual(len(self.on.shadow), 5)
        self.assertEqual(self.off.shadow, [])

    def test_9_the_adversarial_proposal_was_not_trusted(self):
        for rec in self.on.shadow:
            if rec["status"] == I.S_OK:
                acc = rec["accepted"]
                self.assertNotEqual(acc.get("capacity_kva"), 250)
                self.assertNotEqual(acc.get("application"), "MINING")
                self.assertNotEqual(acc.get("delivery_location"), "Mysuru")
                self.assertTrue(rec["rejected"])

    def test_7_a_crashing_interpreter_cannot_fail_the_webhook(self):
        def boom(m, t=None):
            raise RuntimeError("provider exploded")
        crash = run_conversation(THREAD, shadow=True, provider=boom)
        self.assertEqual(crash.sent, self.off.sent)
        self.assertEqual(crash.saved, self.off.saved)
        self.assertTrue(all(r["status"] == I.S_ERROR for r in crash.shadow))

    def test_malformed_output_cannot_fail_the_webhook(self):
        for raw in ("not json", "{", '{"intent": "buy", "fields": {}}', "[1,2]", None, ""):
            r = run_conversation(THREAD[:3], shadow=True, provider=lambda m, t=None, raw=raw: raw)
            self.assertEqual(r.sent, run_conversation(THREAD[:3]).sent)

    def test_the_shadow_record_carries_no_phone_no_body_no_wamid_no_place(self):
        for rec in self.on.shadow:
            blob = json.dumps(rec, ensure_ascii=False)
            for banned in ("910000000077", "0077", "quotation beku", "2 beku", "wamid.",
                           "Mysuru", "ಗುಜರಾತ್", "Sira", TEST_TURN_KEY):
                self.assertNotIn(banned, blob, banned)
            self.assertEqual(set(rec), set(I.RECORD_COLUMNS))


class TheInputsAreNotMutated(unittest.TestCase):
    def test_followup_known_and_history_are_untouched(self):
        history = [{"role": "user", "content": "63 kva", "created_at": NOW_ISO},
                   {"role": "assistant", "content": b.flow_marker((b.AWAITING_DELIVERY,)),
                    "created_at": NOW_ISO}]
        known = {"capacity_kva": 63}
        followup = b.parse_followup("2", (b.AWAITING_DELIVERY,), known=known)
        before = copy.deepcopy((history, known, followup))
        with mock.patch.dict(os.environ, {"SHADOW_INTERPRETATION": "on", "SHADOW_TURN_KEY": TEST_TURN_KEY}), \
             mock.patch.object(w, "_provider_chain", lambda: [("deepseek", adversarial)]), \
             mock.patch.object(w, "_shadow_sink", lambda r: None):
            w.start_turn_clock()
            out = w.shadow_interpret("910000000077", "2", history, followup, known, "wamid.x")
        self.assertIsNone(out)
        self.assertEqual((history, known, followup), before)
        w._TURN_CLOCK["deadline"] = None


# ══════════════════════════════════════════════════════════════════════════
# 8 · PROVIDER / DEADLINE
# ══════════════════════════════════════════════════════════════════════════

class ShadowObeysTheTurnDeadline(unittest.TestCase):
    def tearDown(self):
        w._TURN_CLOCK["deadline"] = None
        w._CHAIN_DEADLINE["t"] = None

    def _once(self, provider, left):
        recs = []
        with mock.patch.dict(os.environ, {"SHADOW_INTERPRETATION": "on", "SHADOW_TURN_KEY": TEST_TURN_KEY}), \
             mock.patch.object(w, "_provider_chain", lambda: [("deepseek", provider)]), \
             mock.patch.object(w, "_shadow_sink", recs.append):
            w._TURN_CLOCK["deadline"] = w.time.monotonic() + left
            w.shadow_interpret("910000000077", "2 units", [], b.parse_followup("2 units"), {},
                               "wamid.deadline")
        return recs

    def test_the_call_gets_at_most_the_shadow_budget(self):
        """The shadow's own cap (2026-10-01: DeepSeek-Flash needs longer than
        the 6 s live-interpretation budget), never the whole turn."""
        seen = []
        self._once(lambda m, t=None: seen.append(w.ai_seconds_left()) or "", left=40)
        self.assertLessEqual(seen[0], w.SHADOW_TIMEOUT_SECONDS + 0.01)
        self.assertGreater(w.SHADOW_TIMEOUT_SECONDS, w.INTERPRET_TIMEOUT_SECONDS)

    def test_never_more_than_the_turn_has_left(self):
        seen = []
        recs = self._once(lambda m, t=None: seen.append(w.ai_seconds_left()) or "", left=3.0)
        self.assertLessEqual(seen[0], 3.01)
        self.assertEqual(recs[0]["status"], I.S_PROVIDER_FAILED)

    def test_skipped_when_under_the_minimum(self):
        called = []
        recs = self._once(lambda m, t=None: called.append(1) or "", left=1.0)
        self.assertEqual(called, [])
        self.assertEqual(recs[0]["status"], I.S_SKIPPED_DEADLINE)
        self.assertEqual(set(recs[0]["comparison"].values()), {I.SKIPPED})

    def test_the_bounded_timeout_reaches_the_real_provider(self):
        captured = {}

        class FakeClient:
            def __init__(self, **kw):
                self.chat = mock.Mock()
                self.chat.completions.create.side_effect = (
                    lambda **k: captured.update(k) or (_ for _ in ()).throw(RuntimeError("x")))

        with mock.patch.dict(sys.modules, {"openai": mock.Mock(OpenAI=FakeClient)}), \
             mock.patch.object(w, "DEEPSEEK_API_KEY", "k"):
            self._once(w._call_deepseek, left=40)
        self.assertLessEqual(captured["timeout"], w.SHADOW_TIMEOUT_SECONDS + 0.01)
        self.assertEqual(captured["max_tokens"], w.SHADOW_MAX_TOKENS)

    def test_chain_deadline_and_truncation_flag_are_restored(self):
        w._LAST_AI_TRUNCATED["value"] = True

        def truncating(m, t=None):
            w._LAST_AI_TRUNCATED["value"] = False
            return '{"intent": "ack", "fields": {}, "questions": [], "is_correction": false, "ambiguous": false}'
        self._once(truncating, left=20)
        self.assertTrue(w._LAST_AI_TRUNCATED["value"])
        self.assertIsNone(w._CHAIN_DEADLINE["t"])

    def test_it_never_uses_the_decision_record_reply_chain(self):
        with mock.patch.object(w, "_generate_ai_reply",
                               side_effect=AssertionError("shadow must not use the reply chain")):
            recs = self._once(lambda m, t=None: "", left=20)
        self.assertEqual(recs[0]["status"], I.S_PROVIDER_FAILED)

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHADOW_INTERPRETATION", None)
            self.assertFalse(w.shadow_enabled())


# ══════════════════════════════════════════════════════════════════════════
# CONTEXT ACROSS TURNS
# ══════════════════════════════════════════════════════════════════════════

class TheShadowSeesTheLiveContext(unittest.TestCase):
    def test_each_turn_is_interpreted_with_the_awaiting_the_parser_had(self):
        briefs = []

        def spy(messages, t=None):
            briefs.append(messages[0]["content"])
            return ""
        run = run_conversation(["63 kva beku", "2 beku", "ಕೃಷಿ", "ಗುಜರಾತ್"], shadow=True, provider=spy)
        awaitings = [r["awaiting"] for r in run.shadow]
        self.assertEqual(len(awaitings), 3)                     # the 3 follow-ups
        # exactly the timed awaiting the production parser used, turn by turn
        history_at = []
        expected = []
        for msg in run.history:
            if msg["role"] == "user" and history_at and not b.is_lead_form(msg["content"]):
                expected.append(list(w.bairavi_awaiting(history_at)))
            history_at.append(msg)
        self.assertEqual(awaitings, expected)
        self.assertTrue(any(awaitings))                          # not all empty
        self.assertIn("capacity_kva", briefs[-1])               # known facts reach it
        # production state is the parser's, whatever the shadow proposed
        state = b.established_from_history(run.history)
        self.assertEqual(state["capacity_kva"], 63)
        self.assertEqual(state["quantity"], 2)
        self.assertEqual(state["application"], "AGRICULTURE")

    def test_a_perfect_interpreter_matches_the_parser_everywhere(self):
        """Feeding back the parser's own reading must compare as MATCH."""
        def echo_parser(messages, t=None):
            text = messages[-1]["content"]
            brief = messages[0]["content"]
            aw = brief.split("last question was about: ")[1].split(".\n")[0]
            awaiting = () if aw == "nothing" else tuple(aw.split(", "))
            import ast as _ast
            tail = brief.split("Already known: ")[1].rstrip(".")
            known = _ast.literal_eval(tail) if tail.startswith("{") else {}
            return json.dumps(I.from_parse(b.parse_followup(text, awaiting, known=known), text, known))
        run = run_conversation(["63 kva beku", "2 beku", "ಕೃಷಿ", "Hirekerur"], shadow=True,
                               provider=echo_parser)
        for rec in run.shadow:
            self.assertEqual(rec["status"], I.S_OK, rec)
            self.assertEqual(set(rec["comparison"].values()), {I.MATCH}, rec["diffs"])


# ══════════════════════════════════════════════════════════════════════════
# THE COMPARISON
# ══════════════════════════════════════════════════════════════════════════

def compare_for(text, interp, awaiting=(), known=None):
    known = known or {}
    parsed = b.parse_followup(text, awaiting, known=known)
    validated = I.validate(interp, text, awaiting, known)
    return I.compare(parsed, text, known, interp, validated)


class TheComparisonClasses(unittest.TestCase):
    def test_match(self):
        c = compare_for("63 kVA", contract(capacity_kva=(63, "63 kVA")))
        self.assertEqual(c["classes"]["capacity_kva"], I.MATCH)

    def test_shadow_only(self):
        # the parser does not read a lone "hundred units"; suppose the shadow does
        c = compare_for("need hundred units", contract(quantity=(100, "hundred units")))
        self.assertIn(c["classes"]["quantity"], (I.MATCH, I.PARSER_ONLY, I.SHADOW_ONLY))
        c = compare_for("Krushi", contract(), (b.AWAITING_PURPOSE,))
        self.assertEqual(c["classes"]["application"], I.PARSER_ONLY)

    def test_conflict(self):
        c = compare_for("ಕೃಷಿ ಅಥವಾ solar", contract(application=("SOLAR", "solar")))
        self.assertEqual(c["classes"]["application"], I.CONFLICT)
        self.assertEqual(c["diffs"]["application"], {"parser": "AGRICULTURE", "shadow": "SOLAR"})

    def test_correction_is_distinguished_from_unrelated_information(self):
        known = {"capacity_kva": 63}
        fix = compare_for("actually 100 kva beku",
                          contract(intent="correction", correction=True,
                                   capacity_kva=(100, "100 kva")), (), known)
        self.assertEqual(fix["classes"]["correction"], I.MATCH)
        self.assertEqual(fix["classes"]["capacity_kva"], I.MATCH)
        unrelated = compare_for("2 units beku", contract(quantity=(2, "2 units")), (), known)
        self.assertEqual(unrelated["classes"]["correction"], I.MATCH)       # neither says correction
        self.assertEqual(unrelated["classes"]["capacity_kva"], I.MATCH)     # 63 untouched on both
        unclaimed = compare_for("actually 100 kva beku", contract(capacity_kva=(100, "100 kva")),
                                (), known)
        self.assertEqual(unclaimed["classes"]["capacity_kva"], I.PARSER_ONLY)  # no correction: refused

    def test_brain_owned_signals_always_match(self):
        c = compare_for("ok", contract(intent="ack"), (b.AWAITING_DELIVERY,), {"location": "Sira"})
        for f in ("delivery_same", "discom", "delivery_mentioned"):
            self.assertEqual(c["classes"][f], I.MATCH, f)

    def test_invalid_and_skipped_are_their_own_classes(self):
        rec = I.shadow_record(status=I.S_INVALID, turn_key="t" * 32, awaiting=(), interp=None,
                              validated=I.validate(None, "x"))
        self.assertEqual(set(rec["comparison"].values()), {I.INVALID_SHADOW})
        rec = I.shadow_record(status=I.S_SKIPPED_DEADLINE, turn_key="t" * 32, awaiting=())
        self.assertEqual(set(rec["comparison"].values()), {I.SKIPPED})

    def test_evidence_is_described_never_stored(self):
        """Design B (2026-09-27): structure only; the transcript has the words."""
        long = "Sulekere village near Turuvekere " * 5
        rec = I.shadow_record(status=I.S_OK, turn_key="t" * 32, awaiting=(),
                              interp=contract(delivery_place=(long, long)),
                              validated=I.validate(contract(), "hi"), text=long,
                              comparison={"classes": {f: I.MATCH for f in I.COMPARED}, "diffs": {}})
        slot = rec["proposed"]["delivery_place"]
        self.assertEqual(set(slot), {"value", "evidence_found", "value_in_evidence",
                                     "evidence_len", "outcome"})
        self.assertIsNone(slot["value"])
        self.assertEqual(slot["evidence_len"], len(long))
        self.assertNotIn("Sulekere", json.dumps(rec, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════════════════
# THE NEGATIVE CASES — nothing unsupported becomes a fact
# ══════════════════════════════════════════════════════════════════════════

class NothingUnsupportedIsAccepted(unittest.TestCase):
    D = (b.AWAITING_DELIVERY,)

    def accepted(self, text, interp, awaiting=(), known=None):
        v = I.validate(interp, text, awaiting, known or {})
        return {k: v[k] for k in ("capacity_kva", "quantity", "application",
                                  "delivery_location", "callback") if v[k] is not None}, v

    def test_time_words_are_not_places(self):
        for t in ("immediately", "urgent", "delivery yavaga"):
            acc, _ = self.accepted(t, contract(delivery_place=(t, t)), self.D)
            self.assertNotIn("delivery_location", acc, t)

    def test_call_me_is_not_a_place(self):
        acc, _ = self.accepted("call me", contract(delivery_place=("call me", "call me")), self.D)
        self.assertEqual(acc, {})

    def test_next_week_is_not_a_place(self):
        """Was the known gap; closed by the owner's 2026-10-01 approval."""
        for t in ("next week", "month end"):
            acc, _ = self.accepted(t, contract(delivery_place=(t, t)), self.D)
            self.assertNotIn("delivery_location", acc, t)

    def test_bare_numbers_depend_on_the_question(self):
        for n in ("1", "2"):
            acc, v = self.accepted(n, contract(quantity=(int(n), n)), self.D)
            self.assertEqual(acc, {})
            self.assertEqual(v["_ambiguous"], "quantity")
            acc, _ = self.accepted(n, contract(quantity=(int(n), n)), (b.AWAITING_QUANTITY,))
            self.assertEqual(acc, {"quantity": int(n)})

    def test_repeated_kva_is_not_a_quantity(self):
        acc, _ = self.accepted("25", contract(quantity=(25, "25")), (b.AWAITING_PURPOSE,),
                               {"capacity_kva": 25})
        self.assertEqual(acc, {})

    def test_unknown_capacity_keeps_the_verify_path_and_is_never_mapped(self):
        acc, _ = self.accepted("500 kva", contract(capacity_kva=(500, "500 kva")))
        self.assertEqual(acc, {"capacity_kva": 500})
        acc, _ = self.accepted("500 kva", contract(capacity_kva=(250, "500 kva")))
        self.assertEqual(acc, {})

    def test_price_and_quotation_are_intents_not_facts(self):
        _, v = self.accepted("rate?", contract(intent="price_request"))
        self.assertTrue(v["asked_price"])
        self.assertEqual(v["commercial_intent"], b.PRICE_REQUEST)
        _, v = self.accepted("quotation beku", contract(intent="quotation_request"))
        self.assertEqual(v["commercial_intent"], b.QUOTATION_REQUEST)

    def test_delivery_place_and_application_when_supported(self):
        acc, _ = self.accepted("Hirekerur", contract(delivery_place=("Hirekerur", "Hirekerur")), self.D)
        self.assertEqual(acc, {"delivery_location": "Hirekerur"})
        acc, _ = self.accepted("ಕೃಷಿ", contract(application=("AGRICULTURE", "ಕೃಷಿ")))
        self.assertEqual(acc, {"application": "AGRICULTURE"})

    def test_callback_choice_only_when_offered(self):
        acc, _ = self.accepted("2", contract(callback=("evening", "2")), (b.AWAITING_CALLBACK,))
        self.assertEqual(acc, {"callback": "evening"})
        acc, _ = self.accepted("2", contract(callback=("evening", "2")), self.D)
        self.assertEqual(acc, {})

    def test_correction_needs_the_flag(self):
        known = {"capacity_kva": 63}
        acc, _ = self.accepted("actually 100 kva", contract(capacity_kva=(100, "100 kva")), (), known)
        self.assertEqual(acc, {})
        acc, _ = self.accepted("actually 100 kva",
                               contract(correction=True, capacity_kva=(100, "100 kva")), (), known)
        self.assertEqual(acc, {"capacity_kva": 100})

    def test_off_topic_yields_nothing(self):
        acc, v = self.accepted("cricket score enu?", contract(intent="off_topic"))
        self.assertEqual(acc, {})
        self.assertFalse(v["asked_price"])

    def test_malformed_unknown_intent_field_question(self):
        for bad in ("not json", None, {"intent": "buy_now", "fields": {}},
                    {"intent": "answer", "fields": {"price": {"value": 1, "evidence": "1"}}},
                    {"intent": "answer", "fields": {}, "questions": ["discount"]}):
            acc, v = self.accepted("63 kva 2 units", bad if isinstance(bad, dict) else None)
            self.assertEqual(acc, {})
            self.assertIn(("*", I.R_SCHEMA), v["_rejected"])

    def test_fabricated_place_evidence_and_absent_evidence(self):
        acc, v = self.accepted("Hirekerur", contract(delivery_place=("Mysuru", "Hirekerur")), self.D)
        self.assertEqual(acc, {})
        acc, v = self.accepted("Hirekerur", contract(delivery_place=("Mysuru", "Mysuru")), self.D)
        self.assertEqual(acc, {})
        self.assertIn(("delivery_place", I.R_NO_EVIDENCE), v["_rejected"])


class TheReader(unittest.TestCase):
    def test_parse_llm_json(self):
        self.assertEqual(I.parse_llm_json('```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})
        self.assertEqual(I.parse_llm_json('noise {"x": "say \\"hi\\""} more'), {"x": 'say "hi"'})
        for bad in (None, "", "no json", "{", "[1,2]", '{"a": }'):
            self.assertIsNone(I.parse_llm_json(bad), bad)

    def test_the_brief_asks_for_data_not_a_reply(self):
        brief = I.interpretation_brief((b.AWAITING_DELIVERY,), {"capacity_kva": 63, "name": "X"})
        self.assertIn("return ONLY a JSON object", brief)
        self.assertIn("never write a reply", brief)
        self.assertIn("delivery", brief)
        self.assertNotIn("'name'", brief)          # the name is not handed to the interpreter
        for q in I.QUESTIONS:
            self.assertIn(q, brief)


class ShadowRunsLast(unittest.TestCase):
    """Mutation run 2026-09-27: nothing pinned the ORDER. A shadow call before
    send_text would leave every output identical yet delay the customer's
    reply by up to INTERPRET_TIMEOUT_SECONDS."""

    def test_shadow_is_the_last_thing_a_turn_does(self):
        events = []
        history, NOW = [], NOW_ISO
        for text in (FORM, "2 beku", "ಕೃಷಿ", "K"):
            ctx = {"history": list(history), "recent_sys": [], "paused": False,
                   "vip_alerted": False, "lead_alerted": False, "last_user": {}}
            saved = []
            with mock.patch.dict(os.environ, {"SHADOW_INTERPRETATION": "on", "SHADOW_TURN_KEY": TEST_TURN_KEY}), \
                 mock.patch.object(w, "fetch_memory", lambda s: {}), \
                 mock.patch.object(w, "record_first_seen", lambda *a, **k: None), \
                 mock.patch.object(w, "send_text", lambda to, t, **k: events.append("send")), \
                 mock.patch.object(w, "upsert_lead", lambda p, d: events.append("lead")), \
                 mock.patch.object(w, "notify_owner", lambda m, **k: events.append("owner")), \
                 mock.patch.object(w, "save_messages",
                                   lambda rows: (saved.extend(rows), events.append("save"), w.SAVE_OK)[2]), \
                 mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None), \
                 mock.patch.object(w, "bairavi_model_reply", lambda *a, **k: ""), \
                 mock.patch.object(w, "BIC_AVAILABLE", False), \
                 mock.patch.object(w, "_provider_chain", lambda: [("deepseek", lambda m, t=None: "")]), \
                 mock.patch.object(w, "_shadow_sink", lambda r: events.append("shadow")):
                w.start_turn_clock()
                events.append("|")
                w.run_client_pipeline("910000000077", text, ctx, message_id="m")
            for row in saved:
                if len(row) == 3:
                    history.append({"role": row[1], "content": row[2], "created_at": NOW})
        w._TURN_CLOCK["deadline"] = None
        code = {"send": "R", "save": "T", "lead": "L", "owner": "O", "shadow": "h", "|": "|"}
        turns = "".join(code[e] for e in events).split("|")[1:]
        for t in turns[1:]:                            # every follow-up turn
            self.assertTrue(t.endswith("h"), f"shadow not last in turn: {t!r}")
            self.assertEqual(t.count("h"), 1)
        self.assertNotIn("h", turns[0])                # the opening form: no shadow


if __name__ == "__main__":
    unittest.main()
