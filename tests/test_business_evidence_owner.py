"""OWNER → real business evidence: the smallest safe bridge.

WHAT THIS SLICE IS
-------------------
"How many new enquiries did we get this month?" now answers from
biz.pipeline.new_enquiries_per_month@1 — the SAME knowledge.describe /
claims.current path #why and #service_interest already use. NOT OWNER GOAL,
NOT business-scoped 2H, NOT OWNER DECIDE/AUTHORIZE, NOT planning, NOT
autonomy. A direct factual read and nothing more.

THE TWO THINGS THAT MUST BOTH BE TRUE
--------------------------------------
1. owner_evidence_query() fires ONLY on an explicit count question — never
   a bare topic mention, never a diagnostic/strategic question, however the
   topic word appears inside it.
2. render_business_evidence() NEVER invents a number. Fresh evidence renders
   as current; stale evidence is shown but flagged, never as current;
   conflicted evidence is refused; missing evidence says so.

Offline: no network, no AI, no database. The end-to-end claims tests below
drive the REAL bic.knowledge / bic.claims / bic.party / bic.registry
machinery against an in-memory store — the same Harness pattern
test_first_seen_at.py established — so this proves the real read path, not
a mock of it.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                             # noqa: E402
from bic import claims as c, knowledge as k, party as p          # noqa: E402
from bic import pipeline_evidence as pe, registry as r           # noqa: E402
from tests.test_claims import ClaimsDb                           # noqa: E402

OWNER = "910000000001"
TENANT = "00000000-0000-0000-0000-000000000001"
BUSINESS_ID = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"
PREDICATE = pe.PREDICATE

REASONING = None   # falls through to generate_owner_reply — same sentinel
                   # test_owner_lookup_routing.py uses, for the same reason.


# ══════════════════════════════════════════════════════════════════════════
# PHASE 2 — the query boundary, in isolation
# ══════════════════════════════════════════════════════════════════════════

class QueryBoundaryPositive(unittest.TestCase):
    """Phase 2's four stated examples, and the robustness a real chat needs."""

    def test_the_four_stated_examples(self):
        for t in (
            "How many new enquiries did we get this month?",
            "How many enquiries this month?",
            "What are my new enquiries this month?",
            "How many new enquiries do we have this month?",
        ):
            with self.subTest(t=t):
                self.assertTrue(w.owner_evidence_query(t))

    def test_case_insensitive(self):
        self.assertTrue(w.owner_evidence_query("HOW MANY ENQUIRIES THIS MONTH?"))

    def test_punctuation_and_quotes(self):
        for t in ('"How many enquiries this month?"',
                  "How many enquiries this month?!?!",
                  "How many enquiries this month."):
            with self.subTest(t=t):
                self.assertTrue(w.owner_evidence_query(t))

    def test_irregular_whitespace(self):
        self.assertTrue(w.owner_evidence_query("how   many    enquiries"))

    def test_kannada_count_verb_with_english_topic(self):
        self.assertTrue(w.owner_evidence_query("ಈ ತಿಂಗಳು ಎಷ್ಟು enquiries ಬಂದಿವೆ?"))

    def test_inquiry_spelling_also_matches(self):
        self.assertTrue(w.owner_evidence_query("How many inquiries this month?"))


class QueryBoundaryNegative(unittest.TestCase):
    """Phase 7's required fall-throughs, verbatim."""

    def test_the_six_stated_diagnostic_questions(self):
        for t in (
            "Why are my enquiries low?",
            "What should I focus on this month?",
            "How can I get more customers?",
            "Should I increase my ad budget?",
            "Why did my enquiries fall?",
            "Which channel should I focus on?",
        ):
            with self.subTest(t=t):
                self.assertFalse(w.owner_evidence_query(t))

    def test_empty_and_whitespace(self):
        for t in ("", "   ", None):
            self.assertFalse(w.owner_evidence_query(t))

    def test_unrelated_lookup_does_not_qualify(self):
        self.assertFalse(w.owner_evidence_query("How many leads do I have today?"))


class AdversarialRouting(unittest.TestCase):
    """Phase 9's full list, exactly as specified."""

    def test_bare_topic_words_never_qualify(self):
        """The banned pattern this whole boundary exists to avoid: a bare
        mention is not a count question, however short the message is."""
        for t in ("enquiry", "enquiries", "new enquiry", "new enquiries",
                  "enquiry quality"):
            with self.subTest(t=t):
                self.assertFalse(w.owner_evidence_query(t))

    def test_reasoning_shaped_mentions_never_qualify(self):
        for t in ("why enquiries", "enquiries falling", "increase enquiries"):
            with self.subTest(t=t):
                self.assertFalse(w.owner_evidence_query(t))

    def test_ambiguous_request_without_a_count_verb_does_not_qualify(self):
        """Not a count question — no 'how many' / 'what are'. This is exactly
        why the bare-≤3-token shortcut owner_lookup_tool() uses would be
        WRONG here: this is 3 tokens and would have matched under that rule."""
        self.assertFalse(w.owner_evidence_query("more enquiries please"))

    def test_mixed_kannada_english(self):
        self.assertTrue(w.owner_evidence_query(
            "ಈ ತಿಂಗಳು ಎಷ್ಟು new enquiries ಬಂದಿವೆ?"))

    def test_reasoning_marker_wins_even_with_a_count_verb_present(self):
        self.assertFalse(w.owner_evidence_query(
            "How many enquiries should I focus on?"))


# ══════════════════════════════════════════════════════════════════════════
# PHASE 5 — model bypass, proved at the dispatcher
# ══════════════════════════════════════════════════════════════════════════

class DispatcherModelBypass(unittest.TestCase):
    """Mirrors test_owner_lookup_routing.py's DispatcherUsesTheRouter — the
    same proof style, extended to cover the model-call boundary explicitly.
    """

    def setUp(self):
        from contextlib import ExitStack
        self.calls = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        s = self.stack.enter_context
        s(mock.patch.object(w, "run_tool",
                            lambda sender, code, **kw: self.calls.append(("TOOL", code)) or f"TOOL:{code}"))
        s(mock.patch.object(w, "compose_status",
                            lambda sender, **kw: self.calls.append(("TOOL", "status")) or "TOOL:status"))
        s(mock.patch.object(w, "generate_owner_reply",
                            lambda *a, **kw: self.calls.append(("MODEL", None)) or "REASONING"))
        s(mock.patch.object(w, "save_message", lambda *a, **kw: None))
        s(mock.patch.object(w, "_find_pending_confirm", lambda ctx: None))
        self.ctx = {"history": [], "recent_sys": [], "paused": False,
                    "vip_alerted": False, "lead_alerted": False, "last_user": {}}

    def dispatch(self, text):
        self.calls.clear()
        return w.handle_owner_text(OWNER, "OWNER", "owner", text, self.ctx)

    def test_direct_evidence_query_reaches_the_tool_not_the_model(self):
        self.dispatch("How many new enquiries did we get this month?")
        self.assertEqual(self.calls, [("TOOL", "business_new_enquiries")])

    def test_direct_evidence_query_never_calls_generate_owner_reply(self):
        self.dispatch("How many enquiries this month?")
        self.assertNotIn(("MODEL", None), self.calls)

    def test_diagnostic_question_reaches_reasoning_not_the_evidence_tool(self):
        """Was ("MODEL", None). Diagnostic questions now reach the Business
        Reasoning Core, which answers from evidence and leaves the cause
        explicitly unresolved — strictly stronger than the bare model answer
        this previously asserted. The invariant that matters, that it must not
        hit the direct evidence tool, is unchanged and asserted below."""
        self.dispatch("Why are my enquiries low?")
        self.assertEqual(self.calls, [("TOOL", "business_reasoning")])

    def test_diagnostic_question_never_calls_the_evidence_tool(self):
        self.dispatch("Why did my enquiries fall?")
        self.assertNotIn(("TOOL", "business_new_enquiries"), self.calls)

    def test_evidence_query_checked_before_the_generic_lookup_router(self):
        """business_new_enquiries must win even though the generic
        owner_lookup_tool() runs in the same dispatcher — there must be
        exactly one route taken, not two competing matches."""
        self.dispatch("How many new enquiries do we have this month?")
        self.assertEqual(len(self.calls), 1)

    def test_leads_lookup_is_unaffected_by_the_new_gate(self):
        """The new gate must not shadow the pre-existing leads_today route."""
        self.dispatch("How many leads do I have today?")
        self.assertEqual(self.calls, [("TOOL", "leads_today")])


# ══════════════════════════════════════════════════════════════════════════
# PHASE 4 / 6 / 8 — the renderer: fresh, stale, missing, conflict, unavailable
# ══════════════════════════════════════════════════════════════════════════

def _value(value=9, verdict="FRESH", age_s=3600, bound_s=86400,
          valid_from="2026-09-03T04:28:34.910937+00:00",
          observed_at="2026-09-03T04:28:34.910937+00:00",
          confidence=0.70, tier=3, cap=0.70, unit="count",
          label="New enquiries per month (Brain-known)",
          claim_id="e81b7b2a-3c6d-4c63-9aea-38f5aa142058"):
    """One hand-built envelope value, matching bic/knowledge.py::_value()'s
    exact schema (verified against the real function's field list)."""
    return {
        "predicate": PREDICATE, "label": label, "value": value, "unit": unit,
        "cardinality": "single", "semantic_version": 1, "status": "ACTIVE",
        "confidence": confidence,
        "provenance": {"tier": tier, "cap": cap, "source": pe.SOURCE,
                       "source_kind": None, "asserted_by": pe.ASSERTED_BY},
        "valid_from": valid_from, "valid_until": "2026-10-01T00:00:00+00:00",
        "observed_at": observed_at,
        "freshness": {"verdict": verdict, "volatility_class": "fast",
                     "bound_seconds": bound_s, "age_seconds": age_s,
                     "observed_at": observed_at},
        "claim_id": claim_id,
    }


def _envelope(state="KNOWN", values=None, conflicts=None, reason=None,
             subject=BUSINESS_ID):
    return {
        "capability": "knowledge.describe", "state": state, "reason": reason,
        "subject": subject, "entity": subject,
        "identity": {"kind": "ORGANIZATION", "resolution_state": "PROVISIONAL"},
        "values": values or [], "conflicts": conflicts or [],
        "coverage": {"consulted": [PREDICATE], "known": [], "absent": [],
                     "unavailable": [], "unregistered": []},
        "degraded": False, "degradation": [],
    }


class RendererFresh(unittest.TestCase):

    def test_fresh_value_is_shown_as_current(self):
        text = w.render_business_evidence(_envelope(values=[_value(value=9)]))
        self.assertIn("9", text)
        self.assertIn("FRESH", text)
        self.assertNotIn("STALE", text)

    def test_the_number_comes_from_the_envelope_not_a_constant(self):
        """Phase 10 mutation #4 target: a hardcoded '9' would pass the test
        above but fail this one — a different value must render differently."""
        text = w.render_business_evidence(_envelope(values=[_value(value=42)]))
        self.assertIn("42", text)
        self.assertNotIn(" 9 ", text)

    def test_month_is_named_from_valid_from(self):
        text = w.render_business_evidence(_envelope(
            values=[_value(valid_from="2026-09-03T04:28:34+00:00")]))
        self.assertIn("September 2026", text)

    def test_confidence_and_tier_are_shown(self):
        text = w.render_business_evidence(_envelope(values=[_value()]))
        self.assertIn("0.7", text)
        self.assertIn("tier 3", text)

    def test_unit_is_shown(self):
        text = w.render_business_evidence(_envelope(values=[_value()]))
        self.assertIn("count", text)

    def test_no_internal_ids_exposed(self):
        env = _envelope(values=[_value()])
        text = w.render_business_evidence(env)
        self.assertNotIn(env["values"][0]["claim_id"], text)
        self.assertNotIn(BUSINESS_ID, text)


class RendererStale(unittest.TestCase):

    def test_stale_value_is_flagged_not_hidden(self):
        """Phase 3/8: STALE must not be presented as current, but the number
        is real evidence and is NOT fabricated away either."""
        text = w.render_business_evidence(_envelope(
            values=[_value(value=7, verdict="STALE", age_s=90000, bound_s=86400)]))
        self.assertIn("STALE", text)
        self.assertIn("7", text)

    def test_stale_value_does_not_read_as_current(self):
        text = w.render_business_evidence(_envelope(
            values=[_value(verdict="STALE", age_s=90000)]))
        self.assertIn("Not shown as current", text)


class RendererConflict(unittest.TestCase):

    def test_conflict_refuses_to_guess(self):
        """Phase 3: CONFLICTED → do not guess. No number in the reply."""
        env = _envelope(values=[_value(value=9), _value(value=3, claim_id="other")],
                        conflicts=[{"predicate": PREDICATE, "values": [9, 3],
                                    "cardinality": "single", "resolved": False}])
        text = w.render_business_evidence(env)
        self.assertIn("CONFLICT", text.upper())
        self.assertNotIn("9", text)
        self.assertNotIn("3", text)


class RendererMissingOrUnavailable(unittest.TestCase):

    def test_unknown_state_says_no_evidence_not_zero(self):
        """Phase 3: MISSING → state that evidence is unavailable. Must never
        read as 'zero enquiries' — that would be a fabricated number."""
        text = w.render_business_evidence(_envelope(state="UNKNOWN", values=[]))
        self.assertNotIn("0 count", text)
        self.assertIn("No enquiry evidence", text)

    def test_unavailable_state_is_distinct_from_unknown(self):
        """§6.2/§6.3 in spirit: an outage and a genuine absence must never
        share a message, or an outage silently reads as 'we have nothing'."""
        text = w.render_business_evidence(
            _envelope(state="UNAVAILABLE", reason="store_unavailable"))
        self.assertIn("UNAVAILABLE", text)
        self.assertIn("NOT the same as zero", text)

    def test_denied_state_shows_no_value(self):
        text = w.render_business_evidence(_envelope(state="DENIED"))
        self.assertIn("Not permitted", text)

    def test_zero_or_multiple_live_values_outside_conflicts_is_refused(self):
        """Defensive: claims.current() should never produce this shape for a
        single-cardinality predicate, but the renderer must not guess if it
        somehow does."""
        text = w.render_business_evidence(_envelope(values=[]))
        self.assertNotIn("📊", text)


# ══════════════════════════════════════════════════════════════════════════
# PHASE 1/3 — the real read path, end to end (no mocks of describe/claims)
# ══════════════════════════════════════════════════════════════════════════

class RealReadPathHarness(unittest.TestCase):
    """Drives bic.knowledge.describe -> bic.claims.current for real, against
    an in-memory store — the SAME Harness pattern test_first_seen_at.py
    established, reused rather than duplicated with a new fixture style.
    """

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for key, v in params.items():
                    if key in ("order", "limit"):
                        continue
                    v = str(v)
                    if v == "is.null" and row.get(key) is not None:
                        keep = False
                    elif v.startswith("eq.") and str(row.get(key)) != v[3:]:
                        keep = False
                if keep:
                    out.append(dict(row))
            return out

        self._p = [
            mock.patch.object(p, "select", party_select),
            mock.patch.object(r, "select", self.db.select),
            mock.patch.object(r, "insert", self.db.insert),
            mock.patch.object(r, "update", self.db.update),
            mock.patch.object(c, "select", self.db.select),
            mock.patch.object(c, "insert", self.db.insert),
            mock.patch.object(w, "BIC_AVAILABLE", True),
            mock.patch.object(w.bic_config, "is_configured", lambda: True),
        ]
        for x in self._p:
            x.start()

        r.register("biz.pipeline", "new_enquiries_per_month", 1, "QUANTITATIVE",
                  {"type": "number", "min": 0},
                  "New enquiries per month (Brain-known)", unit="count",
                  cardinality="single", volatility_class="fast",
                  applies_to=["ORGANIZATION"])
        r.activate("biz.pipeline", "new_enquiries_per_month", 1, "raviraj")

        self.parties.append({"tenant_id": TENANT, "knowledge_id": BUSINESS_ID,
                             "kind": "ORGANIZATION",
                             "resolution_state": "PROVISIONAL",
                             "merged_into": None})
        self.identifiers.append({"tenant_id": TENANT, "party_id": BUSINESS_ID,
                                 "channel": pe.SELF_CHANNEL,
                                 "identifier_value": TENANT,
                                 "identifier_class": "CONTACT",
                                 "valid_until": None})

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def _assert_claim(self, value, valid_from, valid_until=None):
        c.assert_claim(TENANT, BUSINESS_ID, PREDICATE, value,
                       source=pe.SOURCE, provenance_tier=pe.PROVENANCE_TIER,
                       asserted_by=pe.ASSERTED_BY, valid_from=valid_from,
                       valid_until=valid_until or valid_from + timedelta(days=1),
                       observed_at=valid_from)

    def test_fresh_claim_renders_the_real_current_value(self):
        now = datetime.now(timezone.utc)
        self._assert_claim(9, now - timedelta(hours=1))
        out = w.tool_business_new_enquiries(OWNER)
        self.assertIn("9", out)
        self.assertIn("FRESH", out)

    def test_later_claim_supersedes_the_earlier_one(self):
        """The exact defect this session already fixed once in production
        (identical valid_from -> permanent contest) must stay fixed: two
        claims at genuinely different instants must leave exactly one live."""
        now = datetime.now(timezone.utc)
        self._assert_claim(3, now - timedelta(hours=5))
        self._assert_claim(9, now - timedelta(hours=1))
        out = w.tool_business_new_enquiries(OWNER)
        self.assertIn("9", out)
        self.assertNotIn(" 3 ", out)

    def test_stale_claim_is_not_presented_as_current(self):
        """A month window that is still OPEN (valid_until weeks away) but
        whose last measurement is >24h old (age > the `fast` bound) — the
        production shape this defends: the digest missed a day, the claim
        is still the live one for the month, and it must render STALE."""
        now = datetime.now(timezone.utc)
        self._assert_claim(7, now - timedelta(hours=30),
                          valid_until=now + timedelta(days=5))
        out = w.tool_business_new_enquiries(OWNER)
        self.assertIn("STALE", out)

    def test_no_claim_yet_says_no_evidence(self):
        out = w.tool_business_new_enquiries(OWNER)
        self.assertIn("No enquiry evidence", out)

    def test_no_business_party_at_all_says_no_evidence_not_an_error(self):
        """Read-only resolution: the tool must not create the party it
        cannot find, and absence must read as 'no evidence', not a crash."""
        self.parties.clear()
        self.identifiers.clear()
        out = w.tool_business_new_enquiries(OWNER)
        self.assertIn("No enquiry evidence", out)

    def test_resolution_is_read_only_no_party_is_created(self):
        """Phase 1/4: business_subject() would INSERT via resolve_or_create.
        This tool must use find_by_identifier instead, so a query performs
        zero writes even when nothing exists yet."""
        self.parties.clear()
        self.identifiers.clear()
        before = len(self.parties)
        w.tool_business_new_enquiries(OWNER)
        self.assertEqual(len(self.parties), before)


# ══════════════════════════════════════════════════════════════════════════
# PHASE 6 — audit trail: the established mechanism, not a new one
# ══════════════════════════════════════════════════════════════════════════

class AuditTrailReusesTheRegistry(unittest.TestCase):
    """OWNER turns do not open a 3A Decision Record (only the CLIENT pipeline
    does — _bic_owner_turn wraps handle_owner_text with no open_turn() call).
    The established OWNER audit mechanism is bic_tool_invocations, written by
    bic_tools.invoke() -- the SAME path #why, #suffice and #commitments use.
    This proves the new tool rides that path rather than inventing another.
    """

    def test_the_tool_is_registered_in_bic_tools_handlers(self):
        self.assertIn("business_new_enquiries", w.bic_tools._HANDLERS)

    def test_the_dispatcher_calls_run_tool_not_the_handler_directly(self):
        with mock.patch.object(w, "run_tool") as rt:
            rt.return_value = "TOOL:business_new_enquiries"
            ctx = {"history": [], "recent_sys": [], "paused": False,
                  "vip_alerted": False, "lead_alerted": False, "last_user": {}}
            with mock.patch.object(w, "save_message"), \
                 mock.patch.object(w, "_find_pending_confirm", lambda c: None):
                w.handle_owner_text(OWNER, "OWNER", "owner",
                                    "How many enquiries this month?", ctx)
            rt.assert_called_once_with(
                OWNER, "business_new_enquiries",
                _fallback=w.tool_business_new_enquiries)

    def test_no_second_registry_or_audit_table_is_introduced(self):
        """The new migration inserts into bic_tool_defs only — no CREATE
        TABLE, mirroring test_capability_descriptor's own single-registry
        guarantee for this exact reason."""
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260903000022_bic_business_evidence_tool.sql")
        with open(path) as fh:
            sql = "\n".join(l for l in fh if not l.strip().startswith("--"))
        self.assertNotIn("create table", sql.lower())
        self.assertIn("insert into bic_tool_defs", sql.lower())

    def test_the_tool_is_owner_only_and_not_customer_safe(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations", "20260903000022_bic_business_evidence_tool.sql")
        with open(path) as fh:
            sql = fh.read()
        self.assertIn("'business_new_enquiries'", sql)
        self.assertRegex(sql, r"'OWNER',\s*1,\s*false,\s*false")


if __name__ == "__main__":
    unittest.main(verbosity=2)
