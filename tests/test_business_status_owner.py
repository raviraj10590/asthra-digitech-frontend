"""OWNER descriptive business status — evidence-bound, advisory only.

WHAT THIS SLICE IS
------------------
The first OWNER question answered from the BUSINESS packet rather than from
the model's general knowledge:

    routing -> business_month_review -> business-scoped 2H -> sufficiency
            -> packet-only CONSULT -> DECIDE -> narration

It DESCRIBES. It does not recommend, authorize or execute.
`business_focus_recommendation` stays blocked on its own missing evidence and
is never reached from here.

THE TWO PROPERTIES THAT MATTER MOST
-----------------------------------
1. CONSULT runs ONLY after sufficiency passes. A model asked to describe a
   business whose evidence the gate has just refused would fill the gap from
   general knowledge — the exact failure an evidence-bound answer must never
   make. Insufficient evidence therefore makes NO provider call at all.
2. The model sees the packet and nothing else. generate_owner_reply feeds
   owner memory, an archive recall, a live CRM/leads snapshot and the recent
   conversation; every one is an unverified business assertion and none of
   them appears in this brief.

Offline: injected narrator, in-memory store. No provider, no network.
"""

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                              # noqa: E402
from bic import claims as c, context as cx, decide as dcd        # noqa: E402
from bic import goals as gl, knowledge, party as p               # noqa: E402
from bic import pipeline_evidence as pe, policy, registry as r   # noqa: E402
from tests.test_claims import ClaimsDb                           # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
ORG_A = "5c7c2f56-fb8c-40b8-9f77-18ff7533672a"
ORG_B = "6d8d3067-0c9d-41c9-8e88-29ff8644783b"
OWNER = "910000000001"
BIZ = gl.NEW_ENQUIRIES


# ══════════════════════════════════════════════════════════════════════════
# 1 · routing — a third narrow gate, not a second classifier
# ══════════════════════════════════════════════════════════════════════════

class Routing(unittest.TestCase):

    def test_the_supported_descriptive_questions_route_here(self):
        for t in ("What is the business status this month?",
                  "How are enquiries this month?",
                  "Give me the current business situation.",
                  "business update please",
                  "how is the business doing"):
            with self.subTest(t=t):
                self.assertTrue(w.owner_business_status_query(t))

    def test_diagnostic_and_strategic_questions_still_fall_through(self):
        """The OWNER routing fix must not be undone: reasoning markers win."""
        for t in ("Why are my enquiries low?",
                  "What should I focus on this month?",
                  "How can I improve the business?",
                  "Which channel should I focus on?",
                  "Should I increase my ad budget?"):
            with self.subTest(t=t):
                self.assertFalse(w.owner_business_status_query(t))

    def test_a_bare_topic_mention_is_not_a_status_question(self):
        for t in ("business", "enquiries", "status of my ads"):
            with self.subTest(t=t):
                self.assertFalse(w.owner_business_status_query(t))

    def test_the_three_owner_gates_are_mutually_exclusive(self):
        """status / count / generic-lookup must never both claim a message."""
        cases = {
            "What is the business status this month?": ("status",),
            "How many enquiries this month?": ("count",),
            "How are enquiries this month?": ("status",),
            "Show my clients": ("lookup",),
            "Why are my enquiries low?": (),
        }
        for text, expected in cases.items():
            got = []
            if w.owner_business_status_query(text):
                got.append("status")
            if w.owner_evidence_query(text):
                got.append("count")
            if w.owner_lookup_tool(text):
                got.append("lookup")
            self.assertEqual(tuple(got), expected, text)

    def test_no_second_classifier_was_introduced(self):
        """STRUCTURAL: the gate is a phrase list plus the SHARED reasoning
        markers. It cannot reach a model, and it reuses the existing override
        rather than defining a second notion of "this is reasoning"."""
        import inspect
        src = inspect.getsource(w.owner_business_status_query)
        for banned in ("openai", "OpenAI", "deepseek", "gemini",
                       "chat.completions", "generate_reply"):
            self.assertNotIn(banned, src)
        self.assertIn("_REASONING_MARKERS", src)


# ══════════════════════════════════════════════════════════════════════════
# 2 · the CONSULT brief — packet-only, no PII
# ══════════════════════════════════════════════════════════════════════════

def fact(value="9", conf=0.70, tier=3, cap=0.70, verdict="FRESH",
         claim_id="aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"):
    return {"predicate": BIZ, "label": "New enquiries per month",
            "value": value, "unit": "count", "cardinality": "single",
            "semantic_version": 1, "status": "ACTIVE", "confidence": conf,
            "provenance": {"tier": tier, "cap": cap,
                           "source": "bic.claims/first_seen_at",
                           "source_kind": None, "asserted_by": "agent:brain"},
            "valid_from": "2026-09-03T04:28:34+00:00",
            "valid_until": "2026-10-01T00:00:00+00:00",
            "observed_at": "2026-09-03T04:28:34+00:00",
            "freshness": {"verdict": verdict, "volatility_class": "fast",
                          "bound_seconds": 86400, "age_seconds": 3600,
                          "observed_at": "2026-09-03T04:28:34+00:00"},
            "claim_id": claim_id}


def packet(facts=None, gaps=None, verdict="PROCEED", conflicts=None):
    return cx.FrozenPacket({
        "packet_id": "p1", "tenant_id": TENANT, "subject": ORG_A,
        "scope": cx.BUSINESS, "goal_ref": "business_month_review",
        "assembly_state": "OK",
        "question": {"request": "status", "risk_tier": 2},
        "principal": {"principal_ref": "prn_x", "role": "OWNER",
                      "risk_tier_ceiling": 4},
        "evidence": {"facts": list(facts or []), "relationships": [],
                     "timeline": [], "organizational_intelligence": {}},
        "boundaries": {},
        "epistemic": {
            "conflicts": list(conflicts or []), "missing": [],
            "coverage": {"planned": [BIZ], "retrieved": [], "absent": [],
                         "unavailable": [], "unregistered": [],
                         "out_of_scope": []},
            "degradation": [],
            "sufficiency": {"verdict": verdict, "reason": "r",
                            "risk_tier": 2, "gaps": list(gaps or [])},
        },
    })


class ConsultBrief(unittest.TestCase):

    def test_the_brief_contains_the_evidence_values(self):
        brief = w._business_consult_brief(packet([fact()]), "status?")
        blob = str(brief)
        self.assertIn("9", blob)
        self.assertIn("tier 3", blob)
        self.assertIn("FRESH", blob)

    def test_the_brief_names_unmeasured_slots_and_forbids_estimating(self):
        brief = w._business_consult_brief(
            packet([fact()], gaps=[{"slot": "conversion_rate",
                                    "class": cx.UNKNOWABLE, "why": "x"}]),
            "status?")
        blob = str(brief)
        self.assertIn("conversion_rate", blob)
        self.assertIn("NOT MEASURED", blob)
        self.assertIn("may NOT estimate", blob)

    def test_the_brief_forbids_the_four_undefined_metrics_by_name(self):
        blob = str(w._business_consult_brief(packet([fact()]), "status?"))
        for banned in ("revenue", "conversion", "pipeline value", "capacity"):
            self.assertIn(banned, blob.lower())
        self.assertIn("not measured", blob.lower())

    def test_no_pii_reaches_the_model(self):
        """No phone, no transcript, no claim_id, no subject id."""
        blob = str(w._business_consult_brief(packet([fact()]), "status?"))
        for secret in (OWNER, ORG_A, "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"):
            self.assertNotIn(secret, blob, secret)

    def test_no_owner_memory_archive_or_crm_snapshot_reaches_the_model(self):
        """STRUCTURAL: the brief builder takes only a packet and a question,
        so it cannot include the sources generate_owner_reply injects."""
        import inspect
        params = list(inspect.signature(w._business_consult_brief).parameters)
        self.assertEqual(params, ["packet", "question"])
        src = inspect.getsource(w._business_consult_brief)
        for banned in ("fetch_owner_memory", "recall_from_archive",
                       "owner_business_snapshot", "ctx[", "history"):
            self.assertNotIn(banned, src)


# ══════════════════════════════════════════════════════════════════════════
# 3 · end to end against the REAL 2H / knowledge / claims stack
# ══════════════════════════════════════════════════════════════════════════

class RealStack(unittest.TestCase):

    def setUp(self):
        self.db = ClaimsDb()
        self.parties, self.identifiers = [], []
        self.consults = []

        def party_select(table, params, timeout=None):
            rows = self.parties if table == p.PARTIES_TABLE else self.identifiers
            out = []
            for row in rows:
                keep = True
                for k, v in params.items():
                    if k in ("order", "limit"):
                        continue
                    v = str(v)
                    if v == "is.null" and row.get(k) is not None:
                        keep = False
                    elif v.startswith("eq.") and str(row.get(k)) != v[3:]:
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

        for tenant, org in ((TENANT, ORG_A), (OTHER_TENANT, ORG_B)):
            self.parties.append({"tenant_id": tenant, "knowledge_id": org,
                                 "kind": "ORGANIZATION",
                                 "resolution_state": "PROVISIONAL",
                                 "merged_into": None})
            self.identifiers.append({"tenant_id": tenant, "party_id": org,
                                     "channel": pe.SELF_CHANNEL,
                                     "identifier_value": tenant,
                                     "identifier_class": "CONTACT",
                                     "valid_until": None})

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def claim(self, value, when, tenant=TENANT, subject=ORG_A, until=None):
        c.assert_claim(tenant, subject, BIZ, value, source=pe.SOURCE,
                       provenance_tier=pe.PROVENANCE_TIER,
                       asserted_by=pe.ASSERTED_BY, valid_from=when,
                       valid_until=until or when + timedelta(days=20),
                       observed_at=when)

    def status(self, narration="You received 9 new enquiries this month.",
               tenant=TENANT):
        def narrator(pk, q):
            self.consults.append({"packet": pk, "question": q})
            return narration
        with mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", tenant), \
             redirect_stdout(io.StringIO()):
            return w.tool_business_status(OWNER, question="business status?",
                                          narrator=narrator)

    # ── 1 · fresh evidence -> descriptive answer ────────────────────────
    def test_fresh_evidence_produces_a_descriptive_answer(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        out = self.status()
        self.assertIn("9", out)
        self.assertIn("FRESH", out)
        self.assertIn("Advisory only", out)
        self.assertEqual(len(self.consults), 1)

    def test_the_narration_is_included_when_it_validates(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertIn("You received 9 new enquiries", self.status())

    def test_the_value_is_read_not_hardcoded(self):
        self.claim(41, datetime.now(timezone.utc) - timedelta(hours=1))
        out = self.status(narration="Forty one enquiries so far.")
        self.assertIn("41", out)

    # ── 2 · missing evidence -> epistemic limitation, no invention ──────
    def test_missing_evidence_gives_an_epistemic_reply_and_no_consult(self):
        """CONSULT must not run when sufficiency failed."""
        out = self.status()
        self.assertEqual(self.consults, [], "provider was consulted anyway")
        self.assertIn("RETRIEVE", out)
        self.assertNotIn("🗣", out)

    def test_missing_evidence_invents_no_number(self):
        out = self.status()
        self.assertNotIn("9", out)
        for banned in ("revenue", "conversion rate", "pipeline value"):
            self.assertNotIn(banned, out.lower())

    # ── 4 · registered-but-unmeasured -> RETRIEVE ───────────────────────
    def test_registered_but_unmeasured_is_reported_as_retrieve(self):
        out = self.status()
        self.assertIn("measured, but not currently available", out)

    # ── 6 · tenant isolation ────────────────────────────────────────────
    def test_tenant_isolation(self):
        now = datetime.now(timezone.utc)
        self.claim(9, now - timedelta(hours=1), tenant=TENANT, subject=ORG_A)
        self.claim(77, now - timedelta(hours=1),
                   tenant=OTHER_TENANT, subject=ORG_B)
        a = self.status(tenant=TENANT)
        self.assertIn("9", a)
        self.assertNotIn("77", a)

    # ── 8 · advisory only ───────────────────────────────────────────────
    def test_the_reply_states_it_authorises_nothing(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertIn("No action has been taken or authorised",
                      self.status())

    def test_no_internal_ids_reach_the_owner(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        out = self.status()
        self.assertNotIn(ORG_A, out)
        self.assertNotIn(OWNER, out)

    # ── 11 · narration validation still enforced ────────────────────────
    def test_a_hallucinated_number_is_refused_and_the_records_stand(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        out = self.status(narration="Revenue reached 250000 this month.")
        self.assertIn("Narration refused", out)
        self.assertNotIn("250000", out)
        self.assertIn("9", out)          # the real figure still shown

    def test_certainty_language_is_refused(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))
        out = self.status(narration="It is certainly 9 enquiries.")
        self.assertIn("Narration refused", out)

    def test_a_narrator_failure_degrades_to_the_deterministic_rendering(self):
        self.claim(9, datetime.now(timezone.utc) - timedelta(hours=1))

        def boom(pk, q):
            raise RuntimeError("provider down")
        with mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", TENANT), \
             redirect_stdout(io.StringIO()):
            out = w.tool_business_status(OWNER, question="status?",
                                         narrator=boom)
        self.assertIn("9", out)

    # ── structured result ───────────────────────────────────────────────
    def test_the_structured_result_is_advisory_and_additive(self):
        pk = packet([fact()], gaps=[{"slot": "x", "class": cx.UNKNOWABLE,
                                     "why": "y"}])
        res = w.business_status_result(pk, "prose", dcd.PROCEED)
        self.assertEqual(sorted(res), [
            "action_required", "advisory", "evidence_refs", "gaps",
            "narration_rejected", "outcome", "reason", "risk_tier", "text"])
        self.assertTrue(res["advisory"])
        self.assertFalse(res["action_required"])
        self.assertEqual(res["risk_tier"], 2)
        self.assertEqual(res["evidence_refs"],
                         ["aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"])


# ══════════════════════════════════════════════════════════════════════════
# 4 · what must NOT have changed
# ══════════════════════════════════════════════════════════════════════════

class RecommendationStaysBlocked(unittest.TestCase):

    def test_the_focus_goal_still_requires_all_five_slots(self):
        g = gl.lookup("business_focus_recommendation")
        self.assertEqual(len(g["required_slots"]), 5)
        self.assertEqual(g["scope"], cx.BUSINESS)

    def test_the_status_command_never_reaches_the_recommendation_goal(self):
        import inspect
        src = inspect.getsource(w.tool_business_status)
        self.assertNotIn("business_focus_recommendation", src)
        self.assertEqual(w.BUSINESS_STATUS_GOAL, "business_month_review")

    def test_the_status_reply_recommends_nothing(self):
        pk = packet([fact()])
        out = w.render_business_status(pk, None, outcome=dcd.PROCEED)
        for word in ("recommend", "you should", "focus on", "suggest"):
            self.assertNotIn(word, out.lower())


class ExistingBehaviourUnchanged(unittest.TestCase):

    def test_client_decide_is_unchanged(self):
        """decide() was not modified at all — CLIENT adjudication is
        byte-identical."""
        g = gl.lookup("social_media_enquiry")
        pk = packet(verdict="PROCEED")
        pk = dict(pk); pk["goal_ref"] = "social_media_enquiry"
        self.assertEqual(dcd.decide(g, pk, "REPLY")["outcome"], dcd.PROCEED)
        self.assertEqual(dcd.decide(g, pk, None)["outcome"], dcd.REFUSE)

    def test_authorize_still_defaults_to_client_only(self):
        """The additive expected_role parameter must not have loosened the
        default for anyone."""
        g = gl.lookup("social_media_enquiry")
        pk = dict(packet()); pk["goal_ref"] = "social_media_enquiry"
        client = policy.Principal("919555555555", "CLIENT", TENANT)
        owner = policy.Principal(OWNER, "OWNER", TENANT)
        self.assertTrue(dcd.authorize(client, pk, g, TENANT)["allowed"])
        self.assertFalse(dcd.authorize(owner, pk, g, TENANT)["allowed"])

    def test_the_owner_status_path_never_calls_authorize(self):
        """AUTHORIZE/EXECUTE are untouched: the status reply is advisory and
        authorizes nothing, so it must not invoke the authorization stage."""
        import inspect
        src = inspect.getsource(w.tool_business_status)
        self.assertNotIn("authorize", src)

    def test_the_status_tool_is_owner_only_and_not_customer_safe(self):
        path = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations",
                            "20260904000023_bic_business_status_tool.sql")
        with open(path) as fh:
            sql = fh.read()
        self.assertIn("'business_status'", sql)
        self.assertRegex(sql, r"'OWNER',\s*1,\s*false,\s*false")
        code = "\n".join(l for l in sql.splitlines()
                         if not l.strip().startswith("--"))
        self.assertNotIn("create table", code.lower())

    def test_lead_pipeline_functions_were_not_touched(self):
        """This task must not have altered the lead defect surface."""
        import inspect
        for fn in (w.upsert_lead, w.extract_lead_info,
                   w._record_extraction_guard):
            self.assertTrue(callable(fn))
        src = inspect.getsource(w.run_client_pipeline)
        self.assertIn(
            "if depth >= 4 and (depth < 8 or (depth // 2) % 2 == 0):", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
