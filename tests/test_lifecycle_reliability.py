"""The three critical lifecycle fixes, and the multi-turn coverage that was
missing when the last defect got through.

WHAT THE AUDIT FOUND
--------------------
1. PAUSE PRECEDENCE. `BAIRAVI_TRANSFORMER` was evaluated before
   `ctx["paused"]`, so a transformer chat the owner had taken over with #stop
   still received bot replies — measured: replies=1 while paused=True, where
   an Asthra message in the same state correctly stayed silent. A pause is an
   OWNER INSTRUCTION; nothing a customer says may override it.

2. save_messages() DISCARDED ITS RESPONSE. requests.post does not raise on
   4xx/5xx, so a rejected transcript write reported success. The identical
   omission in upsert_lead ran 17 times in production and stored 0 rows. The
   transcript is the worst place for it: history IS the Brain's memory, and
   the Bairavi FLOW_MARKER lives in it.

3. fetch_context() FAILED OPEN to history=[]. A Supabase blip was therefore
   indistinguishable from a brand-new customer, so a mid-conversation caller
   would be handed the welcome menu and lose their business flow.

4. 2,814 tests, and exactly ONE file modelled a conversation. Every other
   branch was tested as one message into an empty history — the shape that
   missed the message-two defect. tests/conversation.py fixes that, and the
   multi-turn classes below use it.

Offline: no network, no provider, no database.
"""

import ast
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402
import bairavi as b                                            # noqa: E402
from conversation import (Conversation, lead_form, FOLLOWUPS,   # noqa: E402
                          PHONE)

WEBHOOK = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")


# PARSED ONCE. webhook.py is ~6,300 lines and ast.parse on it costs ~0.4s;
# calling it per assertion made these structural tests take 70 of the file's
# 81 seconds. A slow suite gets run less often, which is its own defect.
_BRANCH_ORDER = None


def branch_order():
    """Top-level branch conditions in run_client_pipeline, in order.

    STRUCTURAL, not behavioural. A behavioural test proves one path; this
    proves the PRECEDENCE, which is what actually broke — and it keeps
    holding when someone adds a branch later.
    """
    global _BRANCH_ORDER
    if _BRANCH_ORDER is None:
        src = io.open(WEBHOOK, encoding="utf-8").read()
        lines = src.splitlines()
        fn = [n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_client_pipeline"][0]
        _BRANCH_ORDER = [(n.lineno, lines[n.lineno - 1].strip())
                         for n in fn.body if isinstance(n, ast.If)]
    return _BRANCH_ORDER


def position_of(needle):
    for i, (_ln, text) in enumerate(branch_order()):
        if needle in text:
            return i
    raise AssertionError(f"branch {needle!r} not found")


# ══════════════════════════════════════════════════════════════════════════
# FIX 1 · PAUSE PRECEDENCE
# ══════════════════════════════════════════════════════════════════════════

class PausePrecedenceIsStructural(unittest.TestCase):

    def test_the_required_order_holds(self):
        """menu -> PAUSED -> business -> off-topic -> the rest."""
        self.assertLess(position_of("is_menu_request"),
                        position_of('ctx["paused"]'))
        self.assertLess(position_of('ctx["paused"]'),
                        position_of("bairavi.looks_like_transformer_enquiry"))
        self.assertLess(position_of("bairavi.looks_like_transformer_enquiry"),
                        position_of("is_off_topic"))

    def test_pause_outranks_every_content_based_branch(self):
        """Not just Bairavi — every branch that decides from what the CUSTOMER
        said must sit below the pause, or a future business reintroduces this
        bug. Expressed as a property over the branch list rather than a list
        of names, so a new branch is covered the day it is added."""
        pause = position_of('ctx["paused"]')
        content_driven = [(i, t) for i, (_ln, t) in enumerate(branch_order())
                          if "user_text" in t or "bairavi." in t]
        self.assertTrue(content_driven, "no content-driven branches found")
        for i, t in content_driven:
            if "is_menu_request" in t:
                continue          # the customer's own escape hatch
            self.assertGreater(i, pause,
                               f"content-driven branch above the pause: {t!r}")

    def test_the_pause_block_returns_unconditionally(self):
        """WHY THIS IS STRUCTURAL AND NOT BEHAVIOURAL. Order alone is not
        enough: a pause that sat first but fell through would still let a
        business branch answer. The unconditional return is what makes the
        pause DOMINATE everything below it, which is in turn why a mutation
        that re-adds a paused case to the Bairavi condition is dead code
        rather than a defect.
        """
        src = io.open(WEBHOOK, encoding="utf-8").read()
        fn = [n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_client_pipeline"][0]
        block = [n for n in fn.body
                 if isinstance(n, ast.If)
                 and "paused" in ast.unparse(n.test)][0]
        # The LAST statement of the body, at the body's own top level: a
        # return nested inside an if would not dominate.
        self.assertIsInstance(block.body[-1], ast.Return,
                              "the pause block can fall through to business "
                              "routing")
        self.assertEqual(block.orelse, [], "the pause has an else branch")

    def test_only_the_menu_escape_may_precede_the_pause(self):
        before = [t for _ln, t in branch_order()[:position_of('ctx["paused"]')]]
        for t in before:
            self.assertTrue("is_menu_request" in t or "BIC_AVAILABLE" in t,
                            f"{t!r} must not precede the pause check")


class PausedConversationsStaySilent(unittest.TestCase):

    def test_1_paused_first_transformer_enquiry(self):
        c = Conversation(paused=True)
        t = c.send(lead_form())
        self.assertTrue(t.silent, f"replied while paused: {t.reply!r}")
        self.assertEqual(t["leads"], [])
        self.assertEqual(t["first_seen"], [])

    def test_2_3_4_paused_transformer_followups(self):
        """The real keyword-free follow-ups, each while paused."""
        for msg in ("1 unit", "Agricultural", "Rate"):
            c = Conversation()
            c.send(lead_form())                 # establish the flow unpaused
            t = c.send(msg, paused=True)        # owner takes over mid-thread
            self.assertTrue(t.silent, f"{msg!r} got a reply while paused")

    def test_paused_every_real_followup(self):
        for msg in FOLLOWUPS:
            c = Conversation()
            c.send(lead_form())
            t = c.send(msg, paused=True)
            self.assertTrue(t.silent, msg)

    def test_5_unpaused_transformer_enquiry_still_answers_as_bairavi(self):
        t = Conversation().send(lead_form())
        self.assertIn("Bairavi", t.reply)
        self.assertEqual(t["menu"], [])

    def test_6_unpaused_transformer_followup_still_sticks(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("1 unit\nAgricultural")
        self.assertNotIn("Asthra", t.reply)
        self.assertIn("1 unit", t.reply)

    def test_7_menu_escapes_even_inside_an_active_transformer_flow(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("menu")
        self.assertEqual(len(t["menu"]), 1)

    def test_8_human_takeover_mid_conversation(self):
        """Turn 1 answered, owner runs #stop, turns 2 and 3 silent."""
        c = Conversation()
        first = c.send(lead_form())
        self.assertIn("Bairavi", first.reply)
        c.paused = True
        for msg in ("1 unit", "Rate"):
            t = c.send(msg)
            self.assertTrue(t.silent, msg)

    def test_a_paused_asthra_conversation_is_unaffected(self):
        """The control: pause already worked here and must keep working."""
        c = Conversation(paused=True)
        t = c.send("website beku")
        self.assertTrue(t.silent)

    def test_a_paused_turn_is_still_recorded(self):
        """Silence must not mean amnesia — the turn stays in the transcript."""
        c = Conversation(paused=True)
        t = c.send(lead_form())
        self.assertTrue(any(role == "user" for _p, role, _c in t["saved"]))


# ══════════════════════════════════════════════════════════════════════════
# FIX 2 · TRANSCRIPT PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════

class SaveMessagesClassifiesOutcomes(unittest.TestCase):

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.ok = 200 <= code < 300

    def save(self, resp=None, exc=None):
        from unittest import mock
        from contextlib import redirect_stdout
        target = mock.Mock(side_effect=exc) if exc else (lambda *a, **k: resp)
        buf = io.StringIO()
        with mock.patch.object(w.requests, "post", target), \
             redirect_stdout(buf):
            out = w.save_messages([(PHONE, "user", "hi")])
        return out, buf.getvalue()

    def test_a_2xx_is_success(self):
        for code in (200, 201, 204):
            out, _ = self.save(self.Resp(code))
            self.assertEqual(out, w.SAVE_OK, code)

    def test_4xx_and_5xx_are_persistence_failures(self):
        """requests.post does not raise on these — the whole point."""
        for code in (400, 401, 403, 404, 409, 500, 502):
            out, log = self.save(self.Resp(code))
            self.assertEqual(out, w.SAVE_PERSISTENCE_FAILURE, code)
            self.assertIn("SAVE_MESSAGES_FAILED", log)
            self.assertIn(f"status={code}", log)

    def test_timeout_and_connection_errors_are_network_failures(self):
        for exc in (TimeoutError("t"), ConnectionError("c"), OSError("o")):
            out, log = self.save(exc=exc)
            self.assertEqual(out, w.SAVE_NETWORK_FAILURE, exc)
            self.assertIn("SAVE_MESSAGES_NETWORK_FAILED", log)

    def test_the_three_states_are_distinct(self):
        self.assertEqual(len({w.SAVE_OK, w.SAVE_PERSISTENCE_FAILURE,
                              w.SAVE_NETWORK_FAILURE}), 3)

    def test_it_never_raises_so_a_customer_is_still_answered(self):
        for exc in (TimeoutError("t"), ValueError("v")):
            out, _ = self.save(exc=exc)
            self.assertIn(out, (w.SAVE_NETWORK_FAILURE,))

    def test_save_message_reports_the_real_outcome(self):
        """The singular wrapper must PROPAGATE, not swallow. It is one line,
        which is exactly why it is easy to leave returning SAVE_OK."""
        for status, want in ((200, w.SAVE_OK),
                             (401, w.SAVE_PERSISTENCE_FAILURE),
                             (500, w.SAVE_PERSISTENCE_FAILURE)):
            with mock.patch.object(w, "requests") as rq:
                rq.post.return_value = self.Resp(status)
                self.assertEqual(w.save_message(PHONE, "user", "x"), want,
                                 status)

    def test_an_unrecognised_outcome_is_treated_as_a_failure(self):
        """Fail loud on anything that is not explicitly SAVE_OK.

        This is not hypothetical: two pre-existing test stubs returned None
        (list.extend does), and under an `outcome != PERSISTENCE_FAILURE`
        style check a None would have read as a healthy write. Only the
        success value means success."""
        for outcome in (None, "", "OK", "ok", "unexpected", 0):
            sent = []
            with mock.patch.object(w, "notify_owner",
                                   lambda m, **k: sent.append(m)):
                w.warn_if_transcript_lost(PHONE, outcome, "test")
            self.assertEqual(len(sent), 1, f"{outcome!r} treated as success")

    def test_an_empty_write_is_success_not_failure(self):
        self.assertEqual(w.save_messages([]), w.SAVE_OK)

    def test_no_customer_content_reaches_the_log(self):
        """r.text echoes the rejected payload, which is the customer's own
        message. Only status, row count and a masked phone may appear."""
        from unittest import mock
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: self.Resp(400)), \
             redirect_stdout(buf):
            w.save_messages([(PHONE, "user", "SECRET_CUSTOMER_TEXT")])
        log = buf.getvalue()
        self.assertNotIn("SECRET_CUSTOMER_TEXT", log)
        self.assertNotIn(PHONE, log)
        self.assertIn("...0000", log)


class TranscriptLossIsVisible(unittest.TestCase):

    def test_a_failed_write_alerts_the_owner(self):
        c = Conversation(save_outcome=w.SAVE_PERSISTENCE_FAILURE)
        t = c.send(lead_form())
        self.assertTrue(any("Transcript not saved" in m for m in t["owner"]),
                        "the owner was never told the turn was lost")

    def test_the_customer_is_still_answered_when_the_write_fails(self):
        """Losing the record must not cost the customer their reply."""
        c = Conversation(save_outcome=w.SAVE_NETWORK_FAILURE)
        t = c.send(lead_form())
        self.assertIn("Bairavi", t.reply)

    def test_the_alert_names_the_consequence_not_just_the_error(self):
        c = Conversation(save_outcome=w.SAVE_PERSISTENCE_FAILURE)
        t = c.send(lead_form())
        alert = [m for m in t["owner"] if "Transcript not saved" in m][0]
        self.assertIn("next short reply", alert)
        self.assertIn("manually", alert)

    def test_the_alert_carries_no_customer_content(self):
        """An owner alert is prose for a human on a phone, and it is the one
        place a transcript could escape sideways: the turn that failed to save
        is right there in the caller's scope. Three internal notes have already
        reached customers in this system; the owner-facing direction gets the
        same discipline.

        The phone number IS allowed and is the only identifier permitted — the
        owner cannot open the chat without it.
        """
        secret = "Zq7-CUSTOMER-SENTENCE-Xy4"
        c = Conversation(save_outcome=w.SAVE_PERSISTENCE_FAILURE)
        t = c.send(lead_form(location=secret, name=secret))
        alerts = [m for m in t["owner"] if "Transcript not saved" in m]
        self.assertTrue(alerts, "no transcript-loss alert raised")
        for m in alerts:
            self.assertNotIn(secret, m, "customer content in the owner alert")
            # No structural dump: a locals()/dict repr both breaks the prose
            # and is how fields nobody audited get carried along.
            self.assertNotIn("{'", m)
            self.assertNotIn("'outcome'", m)

    def test_a_successful_write_produces_no_alert(self):
        t = Conversation().send(lead_form())
        self.assertFalse(any("Transcript not saved" in m for m in t["owner"]))

    def test_the_documented_consequence_is_reproduced_and_surfaced(self):
        """THE SCENARIO FROM THE BRIEF. Message 1 establishes the flow, the
        transcript write fails, message 2 is a keyword-free follow-up.

        The marker genuinely does not exist — history is the only shared
        memory, so no logic at message 2 can recover it without inventing a
        second store. What MUST be true is that the loss was not silent: the
        owner was told at message 1, while the customer was still live.
        """
        c = Conversation(save_outcome=w.SAVE_PERSISTENCE_FAILURE)
        first = c.send(lead_form())
        self.assertIn("Bairavi", first.reply)
        self.assertTrue(any("Transcript not saved" in m
                            for m in first["owner"]))
        self.assertEqual(c.history, [], "a failed write must not fake history")

    def test_a_working_write_keeps_stickiness(self):
        """The control for the test above — with persistence healthy the
        follow-up stays with Bairavi."""
        c = Conversation()
        c.send(lead_form())
        t = c.send("1 unit")
        self.assertNotIn("Asthra", t.reply)


# ══════════════════════════════════════════════════════════════════════════
# FIX 3 · DEGRADED CONTEXT
# ══════════════════════════════════════════════════════════════════════════

class FetchContextReportsDegradation(unittest.TestCase):

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.ok = 200 <= code < 300
            self.headers = {}

        def json(self):
            return []

    def fetch(self, resp=None, exc=None):
        from unittest import mock
        from contextlib import redirect_stdout
        target = mock.Mock(side_effect=exc) if exc else (lambda *a, **k: resp)
        with mock.patch.object(w.requests, "get", target), \
             redirect_stdout(io.StringIO()):
            return w.fetch_context(PHONE)

    def test_a_healthy_read_is_not_degraded(self):
        # `is False`, not assertFalse: None is also falsy, and a missing or
        # None flag would let `ctx["degraded"]` raise or read as "unknown"
        # somewhere else. The key is always present and always a bool.
        self.assertIs(self.fetch(self.Resp(200))["degraded"], False)

    def test_a_rejected_read_is_degraded(self):
        for code in (400, 401, 403, 500, 503):
            self.assertTrue(self.fetch(self.Resp(code))["degraded"], code)

    def test_a_network_failure_is_degraded(self):
        for exc in (TimeoutError("t"), ConnectionError("c")):
            self.assertTrue(self.fetch(exc=exc)["degraded"], exc)

    def test_degraded_still_returns_a_usable_ctx_shape(self):
        ctx = self.fetch(exc=TimeoutError("t"))
        for k in ("history", "paused", "recent_sys", "last_user", "degraded"):
            self.assertIn(k, ctx)

    def test_no_phone_or_body_reaches_the_failure_log(self):
        from unittest import mock
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w.requests, "get",
                               mock.Mock(side_effect=TimeoutError("boom"))), \
             redirect_stdout(buf):
            w.fetch_context(PHONE)
        log = buf.getvalue()
        self.assertIn("FETCH_CONTEXT_FAILED", log)
        self.assertNotIn(PHONE, log)


class DegradedContextRefusesToGuess(unittest.TestCase):

    def test_a_degraded_customer_is_not_treated_as_new(self):
        t = Conversation(degraded=True).send("1 unit")
        self.assertEqual(t["menu"], [], "welcome menu sent on a read failure")
        self.assertEqual(t["first_seen"], [], "first_seen_at asserted blindly")

    def test_a_keywordless_followup_gets_a_holding_reply_not_a_guess(self):
        for msg in ("1 unit", "Agricultural", "Rate", "Yes", "Tomorrow"):
            t = Conversation(degraded=True).send(msg)
            self.assertTrue(t.replied, msg)
            self.assertNotIn("Asthra DigiTech", t.reply, msg)
            self.assertNotIn("ASTHRA_AI_REPLY", t.reply, msg)

    def test_exactly_one_reply_is_sent(self):
        """The guard must return. Dropping the return sends the holding
        message AND then a guessed answer — the precise thing the holding
        message promises not to do."""
        t = Conversation(degraded=True).send("1 unit")
        self.assertEqual(len(t["sent"]), 1,
                         f"{len(t['sent'])} replies sent: {t['sent']}")

    def test_it_does_not_fall_through_to_off_topic(self):
        """off-topic would redirect a transformer buyer to website/social."""
        t = Conversation(degraded=True).send("1 unit")
        self.assertNotIn("social media", t.reply.lower())
        self.assertNotIn("website", t.reply.lower())

    def test_the_owner_is_alerted_while_the_customer_is_live(self):
        t = Conversation(degraded=True).send("Rate")
        self.assertTrue(any("history unreadable" in m for m in t["owner"]))
        self.assertTrue(any("manually" in m for m in t["owner"]))

    def test_the_holding_reply_exposes_no_internals(self):
        t = Conversation(degraded=True).send("1 unit")
        low = t.reply.lower()
        for banned in ("supabase", "database", "http", "error", "timeout",
                       "exception", "500", "401", "postgres"):
            self.assertNotIn(banned, low, banned)

    def test_a_self_identifying_message_still_routes_correctly(self):
        """THE DESIGN POINT. A lead form carries its own context, so it needs
        no history and must NOT be downgraded to a holding message."""
        t = Conversation(degraded=True).send(lead_form())
        self.assertIn("Bairavi", t.reply)
        self.assertEqual(t["first_seen"], [])

    def test_an_explicit_transformer_sentence_also_routes(self):
        t = Conversation(degraded=True).send("100 kVA transformer beku")
        self.assertIn("Bairavi", t.reply)

    def test_a_pause_still_outranks_degradation(self):
        """An owner instruction beats a read failure."""
        t = Conversation(degraded=True, paused=True).send("1 unit")
        self.assertTrue(t.silent)

    def test_menu_still_works_while_degraded(self):
        """The escape hatch is the ONE thing that must survive a read failure:
        it needs no history to answer, and it is how a customer gets out.

        Asserted exactly, not as `replied or menu` — that disjunction passed
        whichever way routing went, and let a mutation that dropped the
        degraded term from is_new_contact (sending the holding message instead
        of the menu) go unnoticed."""
        t = Conversation(degraded=True).send("menu")
        self.assertEqual(len(t["menu"]), 1, "menu not sent while degraded")
        self.assertEqual(t["sent"], [], "holding message sent instead of menu")

    def test_a_degraded_read_does_not_make_a_known_caller_look_new(self):
        """is_new_contact must stay False while degraded. It is computed before
        the holding guard and read by the MENU gate above it, so dropping the
        degraded term is observable even though the guard returns early."""
        self.assertIn('not ctx.get("degraded")',
                      io.open(WEBHOOK, encoding="utf-8").read().split(
                          "is_new_contact =")[1].split("\n")[0])

    def test_the_degraded_turn_is_still_recorded(self):
        t = Conversation(degraded=True).send("1 unit")
        self.assertTrue(any(role == "user" for _p, role, _c in t["saved"]))

    def test_degraded_is_audited_in_the_log(self):
        t = Conversation(degraded=True).send("1 unit")
        self.assertIn("CONTEXT_DEGRADED_HOLDING", t["stdout"])

    def test_the_guard_sits_after_business_routing(self):
        """Structural: self-identifying messages must reach their branch
        before the holding reply can swallow them."""
        self.assertLess(position_of("bairavi.looks_like_transformer_enquiry"),
                        position_of('ctx.get("degraded")'))
        self.assertLess(position_of('ctx.get("degraded")'),
                        position_of("is_off_topic"))


# ══════════════════════════════════════════════════════════════════════════
# FIX 4 · MULTI-TURN COVERAGE FOR EVERY BRANCH
# ══════════════════════════════════════════════════════════════════════════

class EveryBranchSurvivesASecondMessage(unittest.TestCase):
    """2,814 tests and one conversation file. This is the gap."""

    def test_bairavi_three_turns(self):
        c = Conversation()
        turns = c.thread(lead_form(), "1 unit", "Rate")
        for i, t in enumerate(turns, 1):
            self.assertNotIn("Asthra", t.reply or "", f"turn {i}")
        self.assertIn("quotation", turns[2].reply.lower())

    def test_asthra_new_contact_then_followup(self):
        c = Conversation()
        first = c.send("hello")
        self.assertEqual(len(first["menu"]), 1)
        self.assertEqual(len(first["first_seen"]), 1)
        second = c.send("website beku")
        self.assertNotIn("Bairavi", second.reply or "")

    def test_first_seen_is_asserted_once_across_a_thread(self):
        c = Conversation()
        c.thread("hello", "website beku", "how much?")
        total = sum(len(t["first_seen"]) for t in c.turns)
        self.assertEqual(total, 1, "first_seen_at asserted more than once")

    def test_branch_switch_transformer_then_website(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("I need a website for my company")
        self.assertNotIn("Bairavi", t.reply or "")

    def test_branch_switch_website_then_transformer(self):
        c = Conversation()
        c.send("website beku")
        t = c.send("100 kVA transformer beku")
        self.assertIn("Bairavi", t.reply)

    def test_menu_then_continue(self):
        c = Conversation()
        c.send("hello")
        self.assertEqual(len(c.send("menu")["menu"]), 1)
        self.assertTrue(c.send("website beku").replied)

    def test_a_thread_does_not_lose_turns(self):
        c = Conversation()
        c.thread(lead_form(), "1 unit", "Rate")
        users = [x for x in c.history if x["role"] == "user"]
        self.assertEqual(len(users), 3, "a branch forgot to save its turn")

    def test_rapid_followups_all_stay_in_flow(self):
        """Same-turn ordering is not modelled here, but every message must
        still resolve to the same business."""
        c = Conversation()
        c.send(lead_form())
        for msg in ("1 unit", "Agricultural", "Rate"):
            t = c.send(msg)
            self.assertNotIn("Asthra", t.reply or "", msg)

    def test_a_mid_thread_read_failure_does_not_reset_the_conversation(self):
        c = Conversation()
        c.send(lead_form())
        degraded = c.send("1 unit", degraded=True)
        self.assertEqual(degraded["menu"], [])
        self.assertEqual(degraded["first_seen"], [])
        # and once reads recover, the flow is intact
        recovered = c.send("Rate")
        self.assertNotIn("Asthra", recovered.reply or "")

    def test_a_mid_thread_write_failure_is_surfaced_not_hidden(self):
        c = Conversation()
        c.send(lead_form())
        t = c.send("1 unit", save_outcome=w.SAVE_PERSISTENCE_FAILURE)
        self.assertTrue(any("Transcript not saved" in m for m in t["owner"]))


class NothingElseRegressed(unittest.TestCase):

    def test_the_bairavi_product_model_is_untouched(self):
        self.assertEqual(b.CATALOGUE_KVA, (25, 63, 100, 250))
        self.assertEqual(b.PLANNED_KVA, (500,))
        self.assertEqual(b.sku_status(500), b.ROADMAP)
        self.assertEqual(b.sku_status(25), b.SUPPORTED)
        self.assertEqual(b.sku_status(9999), b.VERIFY)

    def test_provider_and_extraction_config_unchanged(self):
        import inspect
        self.assertEqual(w.DEEPSEEK_TIMEOUT_SECONDS, 35)
        self.assertEqual(w.GEMINI_MAX_TOKENS, 900)
        self.assertIn("if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):",
                      inspect.getsource(w.run_client_pipeline))

    def test_no_new_branch_id_was_invented(self):
        """The vocabulary is enforced by a DB CHECK constraint and this task
        forbids schema changes."""
        from bic import decision as d
        self.assertEqual(set(d.BRANCH_IDS), {
            "MENU_REQUEST", "OFF_TOPIC", "CHAT_PAUSED",
            "BROCHURE_REQUEST", "NEW_CONTACT", "BAIRAVI_TRANSFORMER"})

# ══════════════════════════════════════════════════════════════════════════
# AUDIT ITEM 5 · notify_owner() delivery is now observable
#
# NOT a new notification architecture (explicitly out of scope): a return
# value and one log line. WhatsApp remains the only channel, so a failed
# owner alert cannot be escalated — it can only be made greppable.
# ══════════════════════════════════════════════════════════════════════════

class OwnerAlertDeliveryIsObservable(unittest.TestCase):

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.ok = 200 <= code < 300

    def notify(self, send_result):
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w, "staff_and_owner_numbers",
                               lambda: ["910000000001"]), \
             mock.patch.dict(os.environ, {"OWNER_ALERT_TEMPLATE": ""}), \
             mock.patch.object(w, "send_text", lambda *a, **k: send_result), \
             redirect_stdout(buf):
            return w.notify_owner("test alert"), buf.getvalue()

    def test_a_delivered_alert_counts_one_recipient(self):
        n, out = self.notify(self.Resp(200))
        self.assertEqual(n, 1)
        self.assertNotIn("OWNER_ALERT_UNDELIVERED", out)

    def test_a_rejected_alert_counts_nobody(self):
        for code in (401, 403, 470, 500):
            n, out = self.notify(self.Resp(code))
            self.assertEqual(n, 0, code)
            self.assertIn("OWNER_ALERT_UNDELIVERED", out)
            self.assertIn(f"status={code}", out)

    def test_the_undelivered_line_carries_no_alert_text_or_number(self):
        """A log line about a failed alert must not become the leak the alert
        itself is careful not to be."""
        _n, out = self.notify(self.Resp(401))
        line = [l for l in out.splitlines()
                if "OWNER_ALERT_UNDELIVERED" in l][0]
        self.assertNotIn("test alert", line)
        self.assertNotIn("910000000001", line)

    def test_no_recipients_configured_is_not_reported_as_a_failure(self):
        """Zero staff numbers means nothing was attempted. Printing an
        undelivered alarm there would be a false alarm every single time."""
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w, "staff_and_owner_numbers", lambda: []), \
             redirect_stdout(buf):
            self.assertEqual(w.notify_owner("x"), 0)
        self.assertNotIn("OWNER_ALERT_UNDELIVERED", buf.getvalue())

    def test_an_offline_send_is_not_reported_as_undelivered(self):
        """send_text returns None when there is nothing to report (the
        offline/test path). Treating None as a rejection would print an
        undelivered alarm on every alert in every test run, which is how a
        log line stops meaning anything."""
        n, out = self.notify(None)
        self.assertEqual(n, 1)
        self.assertNotIn("OWNER_ALERT_UNDELIVERED", out)

    def test_a_template_delivery_also_counts(self):
        """The template path is the one that runs in production whenever
        OWNER_ALERT_TEMPLATE is configured — alerts outside the 24h window
        can ONLY go that way. It was untested; a mutation that stopped
        counting template sends reported every such alert as undelivered."""
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w, "staff_and_owner_numbers",
                               lambda: ["910000000001"]), \
             mock.patch.dict(os.environ,
                             {"OWNER_ALERT_TEMPLATE": "owner_alert_v1"}), \
             mock.patch.object(w, "_wa_post", lambda p: self.Resp(200)), \
             mock.patch.object(w, "send_text",
                               lambda *a, **k: self.fail(
                                   "fell back to text despite a template")), \
             redirect_stdout(buf):
            self.assertEqual(w.notify_owner("test alert"), 1)
        self.assertNotIn("OWNER_ALERT_UNDELIVERED", buf.getvalue())

    def test_a_rejected_template_falls_back_and_still_counts(self):
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with mock.patch.object(w, "staff_and_owner_numbers",
                               lambda: ["910000000001"]), \
             mock.patch.dict(os.environ,
                             {"OWNER_ALERT_TEMPLATE": "owner_alert_v1"}), \
             mock.patch.object(w, "_wa_post", lambda p: self.Resp(400)), \
             mock.patch.object(w, "send_text",
                               lambda *a, **k: self.Resp(200)), \
             redirect_stdout(buf):
            self.assertEqual(w.notify_owner("test alert"), 1)
        self.assertNotIn("OWNER_ALERT_UNDELIVERED", buf.getvalue())

    def test_existing_callers_are_unaffected(self):
        """Additive only: the value is returned, never required."""
        import inspect
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn("notify_owner(", src)
        self.assertNotIn("= notify_owner(", src)


if __name__ == "__main__":
    unittest.main()
