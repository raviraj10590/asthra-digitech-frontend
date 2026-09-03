"""OWNER dispatch: a topic mention is not a capability request.

THE BUG THIS FIXES
------------------
The dispatcher matched bare substrings:

    if any(w in low for w in ("lead", "ಲೀಡ್")):
        return run_tool(sender, "leads_today", ...)

So "why are my leads low?" — a diagnostic question — came back as a NUMBER,
and "which client should I prioritize?" came back as a LIST. It also fired on
`leader`, `leading` and `misleading`, because a substring has no word
boundary. Production has been answering strategy questions with counts.

THE RULE
--------
A deterministic tool fires only when the message is TOOL-SHAPED:

  1. the topic appears as a WHOLE WORD
  2. the message asks for the thing — a lookup verb, or a bare topic
  3. NO reasoning marker is present

Condition 3 is what makes it safe, and the asymmetry is deliberate: routing a
lookup to reasoning costs a slow answer, routing a diagnostic to a count tool
gives a WRONG answer. Under-triggering is the correct failure mode.

Every test below asserts the EXACT route. Asserting "not leads_today" would
pass for every possible outcome including a crash, which is the kind of
assertion that lets a bug like this ship.

Offline: no network, no AI, no database.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                               # noqa: E402

REASONING = None          # None means "fall through to generate_owner_reply"


class Base(unittest.TestCase):
    def route(self, text):
        return w.owner_lookup_tool(text)

    def assertRoute(self, text, expected):
        got = self.route(text)
        self.assertEqual(
            got, expected,
            f"{text!r} routed to {got!r}, expected {expected!r}")


# ── the four stated success criteria ───────────────────────────────────

class SuccessCriteria(Base):

    def test_how_many_leads_is_a_lookup(self):
        self.assertRoute("How many leads do I have today?", "leads_today")

    def test_why_are_my_leads_low_is_reasoning(self):
        self.assertRoute("Why are my leads low?", REASONING)

    def test_show_my_clients_is_a_lookup(self):
        self.assertRoute("Show my clients", "crm_list_clients")

    def test_which_client_to_prioritize_is_reasoning(self):
        self.assertRoute("Which client should I prioritize?", REASONING)


# ── lookups that must keep working ─────────────────────────────────────

class LookupsPreserved(Base):

    def test_client_list_phrasings(self):
        for t in ("Show my clients", "List my clients", "Give me my client list",
                  "clients", "show clients"):
            with self.subTest(t=t):
                self.assertRoute(t, "crm_list_clients")

    def test_lead_count_phrasings(self):
        for t in ("How many leads do I have today?", "Show today's lead count",
                  "leads", "show leads"):
            with self.subTest(t=t):
                self.assertRoute(t, "leads_today")

    def test_status_phrasings(self):
        for t in ("status", "show status", "health"):
            with self.subTest(t=t):
                self.assertRoute(t, "status")

    def test_roles_phrasings(self):
        for t in ("list roles", "show roles", "roles"):
            with self.subTest(t=t):
                self.assertRoute(t, "roles_list")

    def test_case_and_punctuation_and_spacing(self):
        for t in ("SHOW MY CLIENTS", "  show   my   clients  ",
                  "show my clients!!!"):
            with self.subTest(t=t):
                self.assertRoute(t, "crm_list_clients")


# ── diagnostic / strategic must reach reasoning ────────────────────────

class ReasoningPreserved(Base):

    def test_diagnostic_questions(self):
        for t in ("Why are my leads low?", "Are my leads dropping?",
                  "Why did this client leave?", "Why is this client unhappy?",
                  "How can I improve my leads?"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_strategy_and_prioritisation(self):
        for t in ("Which client should I prioritize?",
                  "Which client is most important?",
                  "What should I do about my leads?",
                  "What should I focus on this month?",
                  "Should I spend more on ads?"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_negation_does_not_trigger_a_tool(self):
        for t in ("I don't need more leads.", "The lead quality is poor.",
                  "I don't want to work with this client."):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_a_topic_inside_an_unrelated_word(self):
        """The substring bug: `lead` matched `leader`, `leading`, `misleading`."""
        for t in ("Who is the market leader?", "That is misleading.",
                  "Leading agencies do this.", "Our clientele is growing.",
                  "Leadership training?"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_topic_mentioned_but_nothing_requested(self):
        for t in ("What is the status of the BBMP campaign?",
                  "The campaign status of BBMP is pending",
                  "Should I take the business online?",
                  "Tell me about my client Santhosh",
                  "I met a client yesterday"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)


# ── context-dependent short messages ───────────────────────────────────

class ShortAndContextDependent(Base):

    def test_bare_acknowledgements_never_hit_a_tool(self):
        for t in ("Yes", "Okay", "Fine", "Do it", "Tomorrow", "Why?",
                  "Which one?", "Then what?", "Show me"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_continuations_defer_to_the_path_that_has_context(self):
        """"What about leads?" mentions the topic in three tokens, so the
        bare-lookup rule would fire — but it means "carry on from the last
        turn", and the router cannot see that turn."""
        for t in ("What about leads?", "How about clients?",
                  "Then what about leads?", "any update on leads?"):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)

    def test_empty_and_whitespace(self):
        for t in ("", "   ", None):
            with self.subTest(t=t):
                self.assertRoute(t, REASONING)


# ── Kannada and mixed script ───────────────────────────────────────────

class Multilingual(Base):

    def test_kannada_lookups(self):
        self.assertRoute("ನಮ್ಮ ಗ್ರಾಹಕರನ್ನು ತೋರಿಸು", "crm_list_clients")
        self.assertRoute("ಲೀಡ್ ಎಷ್ಟು ಇದೆ?", "leads_today")

    def test_kannada_diagnostics_reach_reasoning(self):
        self.assertRoute("ಲೀಡ್ ಏಕೆ ಕಡಿಮೆ?", REASONING)
        self.assertRoute("ಗ್ರಾಹಕ ಯಾಕೆ ಬಿಟ್ಟು ಹೋದರು?", REASONING)

    def test_mixed_script_lookup(self):
        self.assertRoute("leads ಎಷ್ಟು?", "leads_today")


# ── the router itself ──────────────────────────────────────────────────

class RouterProperties(Base):

    def test_it_calls_no_model_and_no_network(self):
        import inspect, io, tokenize
        code = "".join(
            t.string for t in tokenize.generate_tokens(
                io.StringIO(inspect.getsource(w.owner_lookup_tool)).readline)
            if t.type not in (tokenize.COMMENT, tokenize.STRING))
        for banned in ("requests", "generate_", "openai", "deepseek", "gemini",
                       "run_tool", "invoke"):
            self.assertNotIn(banned, code)

    def test_it_is_deterministic(self):
        for t in ("Show my clients", "Why are my leads low?", "leads"):
            with self.subTest(t=t):
                self.assertEqual([self.route(t) for _ in range(5)],
                                 [self.route(t)] * 5)

    def test_it_returns_only_known_tools_or_none(self):
        allowed = {None, "leads_today", "crm_list_clients", "status", "roles_list"}
        for t in ("leads", "clients", "status", "roles", "Why?", "anything else",
                  "Which client should I prioritize?"):
            with self.subTest(t=t):
                self.assertIn(self.route(t), allowed)

    def test_hash_commands_are_handled_before_this_router(self):
        """`#commitments` never reaches here — try_owner_command returns first.
        Pinned so the ordering cannot be reversed silently."""
        import inspect
        src = inspect.getsource(w.handle_owner_text)
        self.assertLess(src.index("try_owner_command"),
                        src.index("owner_lookup_tool"))


# ── each guard isolated ────────────────────────────────────────────────
# The suite above used sentences carrying SEVERAL markers ("why … low",
# "which … should"), so deleting any one marker still passed. These pin one
# marker at a time, in a sentence that is otherwise tool-shaped.

class EachMarkerIsLoadBearing(Base):

    def test_why_alone_blocks_a_tool_shaped_sentence(self):
        self.assertRoute("Show me why leads matter", REASONING)

    def test_should_alone_blocks_a_tool_shaped_sentence(self):
        self.assertRoute("Show me the clients I should call", REASONING)

    def test_prioritise_alone_blocks_a_tool_shaped_sentence(self):
        self.assertRoute("List the clients to prioritise", REASONING)
        self.assertRoute("List the clients to prioritize", REASONING)

    def test_recommend_alone_blocks_a_tool_shaped_sentence(self):
        self.assertRoute("Show me the leads you recommend", REASONING)

    def test_compare_alone_blocks_a_tool_shaped_sentence(self):
        self.assertRoute("List my clients and compare them", REASONING)


# ── the DISPATCHER must actually use the router ────────────────────────
# Testing owner_lookup_tool() alone cannot see a dispatcher that ignores it.
# These drive handle_owner_text and assert which tool really ran.

class DispatcherUsesTheRouter(Base):

    def setUp(self):
        from unittest import mock
        from contextlib import ExitStack
        self.calls = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        s = self.stack.enter_context
        s(mock.patch.object(w, "run_tool",
                            lambda sender, code, **k: self.calls.append(code) or f"TOOL:{code}"))
        s(mock.patch.object(w, "compose_status",
                            lambda sender, **k: self.calls.append("status") or "TOOL:status"))
        s(mock.patch.object(w, "generate_owner_reply",
                            lambda *a, **k: self.calls.append("REASONING") or "REASONING"))
        s(mock.patch.object(w, "save_message", lambda *a, **k: None))
        s(mock.patch.object(w, "_find_pending_confirm", lambda ctx: None))
        self.ctx = {"history": [], "recent_sys": [], "paused": False,
                    "vip_alerted": False, "lead_alerted": False, "last_user": {}}

    def dispatch(self, text):
        self.calls.clear()
        w.handle_owner_text("910000000001", "OWNER", "owner", text, self.ctx)
        return self.calls[0] if self.calls else None

    def test_diagnostic_reaches_reasoning_through_the_dispatcher(self):
        self.assertEqual(self.dispatch("Why are my leads low?"), "REASONING")

    def test_prioritisation_reaches_reasoning_through_the_dispatcher(self):
        self.assertEqual(self.dispatch("Which client should I prioritize?"),
                         "REASONING")

    def test_lookup_reaches_the_tool_through_the_dispatcher(self):
        self.assertEqual(self.dispatch("How many leads do I have today?"),
                         "leads_today")

    def test_client_lookup_reaches_the_tool_through_the_dispatcher(self):
        self.assertEqual(self.dispatch("Show my clients"), "crm_list_clients")

    def test_status_reaches_compose_status(self):
        self.assertEqual(self.dispatch("status"), "status")

    def test_substring_only_mention_reaches_reasoning(self):
        """The exact production bug, asserted end to end."""
        self.assertEqual(self.dispatch("Who is the market leader?"), "REASONING")

    def test_exactly_one_route_is_taken(self):
        self.dispatch("Why are my leads low?")
        self.assertEqual(len(self.calls), 1)
