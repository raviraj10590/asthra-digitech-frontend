"""Conversion Evidence v1 — core.party.became_client_at@1.

THE AUDIT THAT FORCED THIS TO BE A NEW EVENT
--------------------------------------------
Nothing in the system recorded that a party had become a client. Every
candidate failed on evidence, not on taste:

    leads.status         3 rows, all 'new', created_at == updated_at on all
                         three, and no code anywhere writes the column
    bic_commitments      0 rows, never exercised
    bic_outcome_records  106 rows, all customer_reply
    bic_parties.kind     PERSON/ORGANIZATION, frozen at creation
    CRM `clients`        a row for EVERY extracted lead — the name asserts
                         precisely what it does not mean

So the tests below spend as much effort proving what does NOT create a
conversion as proving what does. That asymmetry is the point: the expensive
failure here is not a missing event, it is a fabricated one.

THE BUSINESS DEFINITION (OWNER RULING, 2026-09-07)
    A party is CONVERTED when the business records the FIRST PAYMENT RECEIVED.
    One per party. Permanent. Later payments create no new event. A refund
    does not erase the historical fact that the first payment occurred.

WHAT IS DELIBERATELY ABSENT: biz.pipeline.conversion_rate@1. The conversion
window is undefined and inventing one would produce a confident, wrong number.
test_the_conversion_metric_was_not_invented pins that.

Offline: no network, no provider, no database.
"""

import io
import os
import re
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402
from bic import context as cx, goals as gl                     # noqa: E402
from bic import reasoning as r                                 # noqa: E402

PRED = "core.party.became_client_at@1"
MIG = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")
SEED = os.path.join(MIG, "20260907000025_bic_seed_became_client_at.sql")
TOOL = os.path.join(MIG, "20260907000026_bic_first_payment_tool.sql")
WEBHOOK_SRC = os.path.join(os.path.dirname(__file__), "..", "api", "webhook.py")

PHONE = "919999000444"
OTHER = "919999000555"
PARTY = "kn-party-aaaa"
PARTY2 = "kn-party-bbbb"
TENANT = "00000000-0000-0000-0000-000000000001"


def _strip(text):
    """Executable tokens only — comments AND strings removed.

    Both matter here. This file's own prose explains at length what must never
    become a conversion signal, and every module it scans documents the same
    boundary in its docstrings. A plain grep matches that prose and passes for
    entirely the wrong reason."""
    import tokenize
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def executable_only(fn):
    import inspect
    return _strip(inspect.getsource(fn))


def module_code(relpath):
    root = os.path.join(os.path.dirname(__file__), "..")
    return _strip(io.open(os.path.join(root, relpath), encoding="utf-8").read())


class Store:
    """Minimal claim store that records exactly what assert_claim received."""

    def __init__(self, parties=None, existing=None):
        self.parties = parties if parties is not None else {PHONE: PARTY}
        self.existing = existing or {}
        self.writes = []

    def find(self, tenant, channel, value, **k):
        return self.parties.get(value)

    def survivor(self, tenant, kid):
        return kid

    def history(self, tenant, subject, predicate):
        return list(self.existing.get((subject, predicate), []))

    def assert_claim(self, tenant, subject, predicate_ref, value, **kw):
        rec = dict(tenant=tenant, subject=subject, predicate=predicate_ref,
                   value=value, **kw)
        self.writes.append(rec)
        self.existing.setdefault((subject, predicate_ref), []).insert(
            0, {"value": value})
        return rec


def run(text, sender=PHONE, store=None, configured=True, available=True):
    """Drive the REAL tool through the REAL command router."""
    store = store or Store()
    calls = []

    def fake_run_tool(sndr, code, _fallback=None, **args):
        calls.append((code, _fallback, args))
        return w.tool_record_first_payment(sndr, **args)

    with mock.patch.object(w, "BIC_AVAILABLE", available), \
         mock.patch.object(w.bic_config, "is_configured", lambda: configured), \
         mock.patch.object(w.bic_config, "DEFAULT_TENANT_ID", TENANT), \
         mock.patch.object(w.bic_party, "find_by_identifier", store.find), \
         mock.patch.object(w.bic_party, "resolve_survivor", store.survivor), \
         mock.patch.object(w.bic_claims, "history", store.history), \
         mock.patch.object(w.bic_claims, "assert_claim", store.assert_claim), \
         mock.patch.object(w, "run_tool", fake_run_tool):
        out = w.try_owner_command(sender, "OWNER", text)
    return out, store, calls


# ══════════════════════════════════════════════════════════════════════════
# 1-6 · the event itself
# ══════════════════════════════════════════════════════════════════════════

class TheEvent(unittest.TestCase):

    def test_1_a_confirmed_first_payment_creates_the_claim(self):
        out, store, _ = run(f"#paid {PHONE} confirm")
        self.assertEqual(len(store.writes), 1)
        wr = store.writes[0]
        self.assertEqual(wr["predicate"], PRED)
        self.assertEqual(wr["subject"], PARTY)
        self.assertIn("✅", out)

    def test_2_duplicate_is_idempotent_and_writes_nothing(self):
        store = Store(existing={(PARTY, PRED): [{"value": "2026-08-01T00:00:00+05:30"}]})
        out, store, _ = run(f"#paid {PHONE} confirm", store=store)
        self.assertEqual(store.writes, [])
        self.assertIn("Already recorded", out)
        self.assertIn("2026-08-01", out)

    def test_5_the_same_party_cannot_create_a_second_first_payment(self):
        store = Store()
        run(f"#paid {PHONE} confirm", store=store)
        run(f"#paid {PHONE} confirm", store=store)
        run(f"#paid {PHONE} 2026-01-01 confirm", store=store)
        self.assertEqual(len(store.writes), 1, "a second 'first' is a defect")

    def test_3_an_explicit_timestamp_is_preserved_as_world_time(self):
        out, store, _ = run(f"#paid {PHONE} 2026-08-15 confirm")
        wr = store.writes[0]
        self.assertTrue(wr["value"].startswith("2026-08-15"))
        self.assertEqual(wr["valid_from"].date().isoformat(), "2026-08-15")
        self.assertNotIn("observed_at", wr,
                         "observed_at must default to system time")

    def test_3b_a_future_payment_date_is_refused(self):
        future = (datetime.now(w.IST) + timedelta(days=3)).date().isoformat()
        out, store, _ = run(f"#paid {PHONE} {future} confirm")
        self.assertEqual(store.writes, [])
        self.assertIn("future", out)

    def test_3c_a_malformed_date_is_refused_not_guessed(self):
        out, store, _ = run(f"#paid {PHONE} 15-08-2026 confirm")
        self.assertEqual(store.writes, [])

    def test_4_the_lifecycle_is_permanent_and_single_in_the_registry(self):
        sql = io.open(SEED, encoding="utf-8").read()
        self.assertIn("'single'", sql)
        self.assertIn("'static'", sql)
        self.assertIn("'TEMPORAL'", sql)
        self.assertIn("became_client_at", sql)

    def test_6_different_parties_remain_independent(self):
        store = Store(parties={PHONE: PARTY, OTHER: PARTY2})
        run(f"#paid {PHONE} confirm", store=store)
        run(f"#paid {OTHER} confirm", store=store)
        self.assertEqual({x["subject"] for x in store.writes}, {PARTY, PARTY2})


# ══════════════════════════════════════════════════════════════════════════
# 7-10 · identity, tenancy, authorization
# ══════════════════════════════════════════════════════════════════════════

class IdentityAndAuthorization(unittest.TestCase):

    def test_7_the_claim_carries_the_configured_tenant(self):
        _, store, _ = run(f"#paid {PHONE} confirm")
        self.assertEqual(store.writes[0]["tenant"], TENANT)

    def test_7b_identity_is_looked_up_never_created(self):
        """resolve_or_create would mint a PROVISIONAL party, attaching revenue
        to someone never observed and manufacturing an identity as a side
        effect of recording a payment."""
        src = executable_only(w._paid_party)
        self.assertIn("find_by_identifier", src)
        self.assertIn("resolve_survivor", src)
        self.assertNotIn("resolve_or_create", src)
        self.assertNotIn("create", src.replace("resolve_or_create", ""))

    def test_7c_an_unknown_number_is_refused(self):
        store = Store(parties={})
        out, store, _ = run(f"#paid {OTHER} confirm", store=store)
        self.assertEqual(store.writes, [])
        self.assertIn("not known to the Brain", out)

    def test_7d_a_disputed_identity_raises_and_records_nothing(self):
        store = Store()
        def boom(*a, **k):
            raise RuntimeError("DISPUTED")
        store.survivor = boom
        out, store, _ = run(f"#paid {PHONE} confirm", store=store)
        self.assertEqual(store.writes, [])
        self.assertIn("could not be resolved safely", out)

    def test_8_9_10_authorization_is_the_registry_not_the_dispatch_site(self):
        """try_owner_command is reached by OWNER *and* STAFF, so the role gate
        cannot live here. It lives in bic_tool_defs.min_role='OWNER', and the
        command carries NO _fallback — so a registry outage refuses instead of
        letting STAFF through the legacy path."""
        sql = io.open(TOOL, encoding="utf-8").read()
        self.assertIn("'OWNER', 3, true, false", sql)
        self.assertIn("'record_first_payment'", sql)
        self.assertIn("'ACT'", sql)
        _, _, calls = run(f"#paid {PHONE} confirm")
        self.assertEqual(len(calls), 1)
        code, fallback, _ = calls[0]
        self.assertEqual(code, "record_first_payment")
        self.assertIsNone(fallback, "a fallback would be a STAFF write path")

    def test_the_dispatch_site_contains_no_second_role_check(self):
        src = executable_only(w.try_owner_command)
        seg = src[src.find("_PAID_RE"):src.find("_PAID_RE") + 400]
        self.assertNotIn("OWNER", seg)

    def test_an_outage_refuses_rather_than_writing(self):
        for kwargs in ({"available": False}, {"configured": False}):
            out, store, _ = run(f"#paid {PHONE} confirm", **kwargs)
            self.assertEqual(store.writes, [])
            self.assertIn("unavailable", out)


# ══════════════════════════════════════════════════════════════════════════
# 11-14 · what must NEVER create a conversion
# ══════════════════════════════════════════════════════════════════════════

class NothingElseIsAConversion(unittest.TestCase):

    def test_11_no_backfill_of_pre_existing_parties(self):
        sql = io.open(SEED, encoding="utf-8").read()
        self.assertIn("NO BACKFILL", sql)
        for banned in ("insert into bic_claims", "INSERT INTO BIC_CLAIMS",
                       "select knowledge_id", "from bic_parties"):
            self.assertNotIn(banned, sql,
                             "the seed must register a concept, never assert claims")

    def test_11b_the_only_writer_is_the_owner_command(self):
        code = module_code("api/webhook.py")
        self.assertEqual(code.count("BECAME_CLIENT_PREDICATE ,"), 1,
                         "exactly one assert_claim call site")

    def test_12_a_crm_row_does_not_create_a_conversion(self):
        src = executable_only(w.sync_lead_to_crm)
        self.assertNotIn("became_client", src)
        self.assertNotIn(PRED, src)

    def test_13_lead_status_does_not_create_a_conversion(self):
        src = executable_only(w.upsert_lead)
        self.assertNotIn("became_client", src)
        full = executable_only(w.maybe_alert_lead)
        self.assertNotIn("became_client", full)

    def test_14_a_customer_reply_does_not_create_a_conversion(self):
        src = executable_only(w.run_client_pipeline)
        self.assertNotIn("became_client", src)
        self.assertNotIn("record_first_payment", src)

    def test_no_language_inference_path_exists(self):
        """No natural-language payment detector. The owner names the party and
        confirms, or nothing is recorded."""
        code = module_code("api/webhook.py").lower()
        for phrase in ("payment_detected", "detect_payment", "infer_payment",
                       "looks_like_paid"):
            self.assertNotIn(phrase, code)
        self.assertNotIn("record_first_payment",
                         executable_only(w._generate_ai_reply))

    def test_a_customer_can_never_reach_the_command(self):
        sql = io.open(TOOL, encoding="utf-8").read()
        self.assertIn("customer_safe", sql)
        self.assertIn("'OWNER', 3, true, false", sql)


# ══════════════════════════════════════════════════════════════════════════
# 15-21 · the metric that was NOT built
# ══════════════════════════════════════════════════════════════════════════

class TheMetricIsBlockedOnPolicy(unittest.TestCase):

    def test_19_the_window_is_declared_once_and_is_30(self):
        """SUPERSEDES the previous slice's "metric must not exist" test. The
        window was POLICY_REQUIRED and is now ruled at 30 days, so the metric
        is legitimately registered. What must still hold is that 30 lives in
        exactly ONE place: a second copy is how 30 and 7 end up coexisting."""
        self.assertEqual(ce.WINDOW_DAYS, 30)
        code = module_code("bic/conversion_evidence.py")
        self.assertEqual(code.count("WINDOW_DAYS = 30"), 1)
        for mod in ("api/webhook.py", "bic/reasoning.py", "bic/goals.py",
                    "bic/pipeline_evidence.py"):
            self.assertNotIn("WINDOW_DAYS", module_code(mod),
                             f"{mod} holds a second copy of the window")

    def test_19b_no_second_window_was_smuggled_in(self):
        """A literal 30 anywhere in the arithmetic that is not WINDOW_DAYS
        would be a hardcoded window that the constant no longer controls."""
        import ast, inspect
        tree = ast.parse(inspect.getsource(ce.cohort))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, int)]
        self.assertNotIn(30, literals, "a bare 30 bypasses WINDOW_DAYS")
        self.assertIn("WINDOW_DAYS", executable_only(ce.window_end_for))

    def test_18_20_21_conversion_stays_a_declared_gap_never_zero(self):
        """Missing evidence is NOT zero. The review must keep reporting the
        gap, and no ratio may be computed."""
        gaps = [{"slot": s["name"], "predicate": s["predicate"],
                 "class": cx.UNKNOWABLE, "why": "x"}
                for s in gl.lookup("business_operating_review")["required_slots"][1:]]
        out = r.reason(self.packet(gaps), history=None)
        conv = [u for u in out["gaps"] if u["predicate"] == gl.CONVERSION_RATE]
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0]["evidence_class"], r.EV_UNKNOWABLE)
        self.assertNotIn("value", conv[0])
        blob = str(out)
        self.assertNotIn("conversion_rate@1': 0", blob)
        self.assertNotIn("0%", blob)

    def test_15_16_the_denominator_still_counts_distinct_parties(self):
        """Repeat enquiries must not multiply the denominator. first_seen_at
        is single-cardinality, which is what guarantees it."""
        import bic.pipeline_evidence as pe
        self.assertEqual(pe.SOURCE_PREDICATE, "core.party.first_seen_at@1")
        src = io.open(os.path.join(os.path.dirname(__file__), "..", "bic",
                                   "pipeline_evidence.py"), encoding="utf-8").read()
        self.assertIn("distinct_subjects_in_window", src)

    def test_26_the_existing_enquiry_metric_is_untouched(self):
        import bic.pipeline_evidence as pe
        self.assertEqual(pe.PREDICATE, "biz.pipeline.new_enquiries_per_month@1")
        self.assertEqual(pe.SOURCE_PREDICATE, "core.party.first_seen_at@1")


# ══════════════════════════════════════════════════════════════════════════
# 22-31 · provenance, review, reasoning, privacy
# ══════════════════════════════════════════════════════════════════════════

class ProvenanceAndSafety(unittest.TestCase):

    def test_22_provenance_is_tier_1_owner_confirmed_never_tier_0(self):
        """2C §6.1: tier 0 is an AUTHORITATIVE SYSTEM OF RECORD (bank, Tally).
        An owner typing a command is tier 1, cap 0.90."""
        _, store, _ = run(f"#paid {PHONE} confirm")
        wr = store.writes[0]
        self.assertEqual(wr["provenance_tier"], 1)
        self.assertEqual(wr["confidence"], 0.90)
        self.assertEqual(wr["source"], "owner_confirmation")

    def test_23_the_claim_is_attributable(self):
        _, store, _ = run(f"#paid {PHONE} confirm")
        self.assertTrue(store.writes[0]["asserted_by"])
        self.assertTrue(store.writes[0]["asserted_by"].startswith("owner:"))

    def test_no_financial_payload_ever_enters_a_claim(self):
        _, store, _ = run(f"#paid {PHONE} 2026-08-15 confirm")
        wr = store.writes[0]
        for banned in ("amount", "currency", "invoice", "txn", "transaction",
                       "card", "bank", "upi", "rupee"):
            self.assertNotIn(banned, str(wr).lower(), banned)
        self.assertEqual(set(wr) - {"tenant", "subject", "predicate", "value",
                                    "source", "provenance_tier", "asserted_by",
                                    "confidence", "valid_from"}, set())

    def test_31_no_pii_reaches_the_logs(self):
        """WHOLE print STATEMENTS, not lines. An f-string split across two
        lines puts `print(` on the first and the interpolation on the second,
        so a per-line scan reads clean while the phone still reaches the log —
        a mutation escaped exactly that way before this was tightened."""
        import ast, inspect
        tree = ast.parse(inspect.getsource(w.tool_record_first_payment).lstrip())
        prints = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "print"]
        self.assertTrue(prints, "the write must still be observable")
        SENSITIVE = {"target", "when", "sender", "knowledge_id"}
        for call in prints:
            for fv in [n for n in ast.walk(call)
                       if isinstance(n, ast.FormattedValue)]:
                used = {n.id for n in ast.walk(fv) if isinstance(n, ast.Name)}
                if not (used & SENSITIVE):
                    continue
                # Present, so it MUST be truncated — `knowledge_id[-4:]`, the
                # same discipline as phone[-4:] elsewhere. A bare name is the
                # leak; a 4-char suffix identifies nobody but still lets an
                # operator correlate one write with one party.
                self.assertIsInstance(
                    fv.value, ast.Subscript,
                    f"{used & SENSITIVE} logged untruncated")
                self.assertIsInstance(
                    fv.value.slice, ast.Slice,
                    f"{used & SENSITIVE} logged without a slice")

    def test_24_the_review_still_reports_conversion_as_a_gap(self):
        """Registered event, unregistered metric -> conversion is still
        UNKNOWABLE, and that is the honest state until the window is ruled."""
        g = gl.lookup("business_operating_review")
        self.assertIn(gl.CONVERSION_RATE,
                      [s["predicate"] for s in g["required_slots"]])

    def test_25_reasoning_has_no_conversion_special_case(self):
        """The engine must reason over conversion the same way it reasons over
        anything else — via the registry, with no name of its own in the code."""
        code = module_code("bic/reasoning.py").lower()
        for bad in ("conversion", "became_client", "first_payment"):
            self.assertNotIn(bad, code, f"hardcoded {bad} in reasoning")

    def test_27_business_focus_recommendation_remains_governed(self):
        self.assertEqual(len(gl.lookup("business_focus_recommendation")
                             ["required_slots"]), 5)
        self.assertNotEqual(w.REASONING_GOAL, "business_focus_recommendation")

    def test_28_no_unsupported_act(self):
        gaps = [{"slot": s["name"], "predicate": s["predicate"],
                 "class": cx.UNKNOWABLE, "why": "x"}
                for s in gl.lookup("business_operating_review")["required_slots"][1:]]
        out = r.reason(ProvenanceAndSafety.packet(None, gaps))
        self.assertEqual([x for x in out["recommendations"]
                          if x["kind"] == r.ACT], [])

    def test_29_30_the_consult_brief_is_still_packet_only(self):
        import inspect
        self.assertEqual(list(inspect.signature(w._reasoning_brief).parameters),
                         ["result", "question"])
        src = executable_only(w._reasoning_brief)
        for banned in ("fetch_owner_memory", "crm", "leads", "clients"):
            self.assertNotIn(banned, src, banned)

    # shared packet builder
    def packet(self, gaps):
        return {
            "packet_id": "p1", "tenant_id": TENANT, "subject": "org",
            "scope": cx.BUSINESS, "goal_ref": "business_operating_review",
            "assembly_state": "OK",
            "question": {"request": "q", "risk_tier": 2},
            "principal": {"principal_ref": "prn", "role": "OWNER",
                          "risk_tier_ceiling": 4},
            "evidence": {"facts": [], "relationships": [], "timeline": [],
                         "organizational_intelligence": {}},
            "boundaries": {},
            "epistemic": {"conflicts": [], "missing": [],
                          "coverage": {"planned": [], "retrieved": [],
                                       "absent": [], "unavailable": [],
                                       "unregistered": [], "out_of_scope": []},
                          "degradation": [],
                          "sufficiency": {"verdict": cx.REFUSE, "reason": "r",
                                          "risk_tier": 2, "gaps": list(gaps or [])}},
        }


TheMetricIsBlockedOnPolicy.packet = ProvenanceAndSafety.packet


# ══════════════════════════════════════════════════════════════════════════
# the confirmation gate
# ══════════════════════════════════════════════════════════════════════════

class ConfirmationIsExplicit(unittest.TestCase):

    def test_an_unconfirmed_command_writes_nothing(self):
        out, store, _ = run(f"#paid {PHONE}")
        self.assertEqual(store.writes, [])
        self.assertIn("#paid", out)
        self.assertIn("permanent", out.lower())

    def test_the_loose_confirm_words_cannot_trigger_it(self):
        """CONFIRM_WORDS includes a bare "ok" and "yes" — carrying a documented
        KNOWN HAZARD note. A permanent revenue fact must not ride on that."""
        for word in ("ok", "yes", "confirm", "haudu"):
            out, store, _ = run(word)
            self.assertEqual(store.writes, [])
        src = executable_only(w.tool_record_first_payment)
        self.assertNotIn("_stage_confirm", src)
        self.assertNotIn("CONFIRM_WORDS", src)

    def test_confirm_must_belong_to_this_command(self):
        out, store, _ = run(f"#paid {PHONE} something confirm")
        self.assertEqual(store.writes, [])

    def test_a_malformed_paid_command_explains_itself(self):
        out, store, _ = run("#paid")
        self.assertEqual(store.writes, [])
        self.assertIn("Usage", out)

    def test_the_command_is_advertised_in_help(self):
        self.assertIn("#paid", w.OWNER_COMMANDS_HELP)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ══════════════════════════════════════════════════════════════════════════
# THE DERIVED METRIC — biz.pipeline.conversion_rate@1
#
# The window was POLICY_REQUIRED in the previous slice and is now ruled:
#   event   first payment received
#   window  30 calendar days from the party's OWN first enquiry
#   basis   ENQUIRY COHORT
#
# The tests that matter most here are the ones about what the metric REFUSES
# to say: a cohort whose window is still open, and a cohort that predates the
# conversion event entirely. Both are cases where an easy number exists and is
# wrong.
# ══════════════════════════════════════════════════════════════════════════

from datetime import timezone                                  # noqa: E402
from bic import conversion_evidence as ce                      # noqa: E402

CONV_PRED = "biz.pipeline.conversion_rate@1"
SEED_RATE = os.path.join(MIG, "20260907000027_bic_seed_conversion_rate.sql")


def ts(s):
    return datetime.fromisoformat(s)


def cohort(enquiries, payments=None, now="2026-11-01T00:00:00+05:30",
           at="2026-08-15T00:00:00+05:30",
           epoch="2026-07-01T00:00:00+00:00"):
    """Drive the REAL producer over a synthetic claim store."""
    payments = payments or {}

    def reader(tenant, pred, subjects=None, window_start=None, window_end=None):
        if "first_seen" in pred:
            src = dict(enquiries)
            if window_start is not None:
                src = {k: v for k, v in src.items()
                       if window_start <= ts(v).astimezone(timezone.utc)
                       < window_end}
            return src
        return {k: v for k, v in payments.items()
                if subjects is None or k in subjects}

    with mock.patch.object(ce.claims, "valid_from_by_subject", reader), \
         mock.patch.object(ce.registry, "lookup_ref",
                           lambda r: {"activated_at": epoch} if epoch else None), \
         mock.patch.object(ce.config, "DEFAULT_TENANT_ID", TENANT):
        return ce.cohort(TENANT, at=ts(at), now=ts(now))


AUG = {"p1": "2026-08-02T10:00:00+05:30", "p2": "2026-08-10T10:00:00+05:30",
       "p3": "2026-08-20T10:00:00+05:30", "p4": "2026-08-28T10:00:00+05:30"}


class TheThirtyDayWindow(unittest.TestCase):

    def test_17_a_payment_within_30_days_counts(self):
        c = cohort(AUG, {"p1": "2026-08-05T10:00:00+05:30"})
        self.assertEqual(c["numerator"], 1)
        self.assertIn("p1", c["numerator_evidence"])

    def test_18_a_payment_exactly_on_day_30_counts(self):
        """INCLUSIVE. `<` and `<=` are one character apart and the difference
        silently drops every day-30 conversion."""
        c = cohort({"p2": AUG["p2"]}, {"p2": "2026-09-09T10:00:00+05:30"})
        self.assertEqual(c["numerator"], 1)

    def test_19_a_payment_on_day_31_does_not_count(self):
        c = cohort({"p2": AUG["p2"]}, {"p2": "2026-09-09T10:00:01+05:30"})
        self.assertEqual(c["numerator"], 0)
        self.assertEqual(c["rate"], 0.0)

    def test_20_a_payment_before_the_first_enquiry_cannot_count(self):
        """A pre-existing client. Counting it would credit an enquiry that
        caused nothing."""
        c = cohort({"p1": AUG["p1"]}, {"p1": "2026-07-01T10:00:00+05:30"})
        self.assertEqual(c["numerator"], 0)
        self.assertEqual(c["numerator_evidence"], [])

    def test_the_window_is_thirty_days_exactly(self):
        self.assertEqual(ce.WINDOW_DAYS, 30)
        seen = ts("2026-08-01T00:00:00+05:30")
        self.assertEqual(ce.window_end_for(seen),
                         ts("2026-08-31T00:00:00+05:30"))

    def test_the_window_runs_from_each_partys_own_enquiry(self):
        """Not from a cohort-wide boundary — that would be wrong for everyone
        but the first enquirer."""
        c = cohort(AUG, {"p4": "2026-09-25T10:00:00+05:30"})
        self.assertEqual(c["numerator"], 1, "p4 enquired 28 Aug; 25 Sep is day 28")


class CohortStateIsHonest(unittest.TestCase):

    def test_23_an_incomplete_cohort_is_provisional(self):
        c = cohort(AUG, {"p1": "2026-08-05T10:00:00+05:30"},
                   now="2026-09-10T00:00:00+05:30")
        self.assertEqual(c["state"], ce.PROVISIONAL)

    def test_24_a_closed_cohort_becomes_final(self):
        c = cohort(AUG, {"p1": "2026-08-05T10:00:00+05:30"},
                   now="2026-10-01T00:00:00+05:30")
        self.assertEqual(c["state"], ce.FINAL)

    def test_a_september_cohort_is_not_final_on_october_1(self):
        """The example named in the ruling."""
        sept = {"s1": "2026-09-25T10:00:00+05:30"}
        c = cohort(sept, at="2026-09-15T00:00:00+05:30",
                   now="2026-10-01T00:00:00+05:30")
        self.assertEqual(c["state"], ce.PROVISIONAL)
        self.assertEqual(c["window_closes_at"], ts("2026-10-25T10:00:00+05:30"))

    def test_a_provisional_cohort_still_reports_what_it_observed(self):
        """Real and useful — just never labelled final."""
        c = cohort(AUG, {"p1": "2026-08-05T10:00:00+05:30"},
                   now="2026-09-10T00:00:00+05:30")
        self.assertEqual(c["numerator"], 1)
        self.assertEqual(c["rate"], 0.25)
        self.assertEqual(c["state"], ce.PROVISIONAL)

    def test_only_a_final_cohort_is_ever_asserted(self):
        writes = []
        with mock.patch.object(ce.claims, "assert_claim",
                               lambda *a, **k: writes.append((a, k))), \
             mock.patch.object(ce, "business_subject", lambda t: "org"), \
             mock.patch.object(ce.claims, "current", lambda *a, **k: {"claims": []}):
            for now, expect in (("2026-09-10T00:00:00+05:30", 0),
                                ("2026-10-01T00:00:00+05:30", 1)):
                writes.clear()
                def reader(tenant, pred, subjects=None, window_start=None,
                           window_end=None):
                    if "first_seen" in pred:
                        return dict(AUG)
                    return {"p1": "2026-08-05T10:00:00+05:30"}
                with mock.patch.object(ce.claims, "valid_from_by_subject", reader), \
                     mock.patch.object(ce.registry, "lookup_ref",
                                       lambda r: {"activated_at": "2026-07-01T00:00:00+00:00"}), \
                     mock.patch.object(ce.config, "DEFAULT_TENANT_ID", TENANT):
                    ce.record(TENANT, at=ts("2026-08-15T00:00:00+05:30"),
                              observed_at=ts(now))
                self.assertEqual(len(writes), expect, now)


class MissingIsNeverZero(unittest.TestCase):

    def test_21_22_a_cohort_predating_the_event_is_not_measurable(self):
        """0 recorded conversions before the epoch means 'we were not
        recording', not 'nobody paid'."""
        c = cohort(AUG, {}, epoch="2026-09-07T00:00:00+00:00")
        self.assertFalse(c["measurable"])
        self.assertIsNone(c["numerator"])
        self.assertIsNone(c["rate"])
        self.assertIn("did not exist", c["reason"])

    def test_22b_an_unregistered_event_makes_nothing_measurable(self):
        c = cohort(AUG, {}, epoch=None)
        self.assertFalse(c["measurable"])
        self.assertIsNone(c["rate"])

    def test_the_epoch_is_read_from_the_registry_not_hardcoded(self):
        src = executable_only(ce.capability_epoch)
        self.assertIn("lookup_ref", src)
        code = module_code("bic/conversion_evidence.py")
        self.assertNotIn("2026-09-07", code, "a hardcoded epoch would drift")

    def test_27_28_no_division_by_zero_and_no_invented_rate(self):
        c = cohort({}, {})
        self.assertEqual(c["denominator"], 0)
        self.assertIsNone(c["rate"], "an empty month has no rate, not 0%")
        self.assertIn("no enquiries", c["reason"])

    def test_a_measured_zero_is_still_a_real_zero(self):
        """Distinct from unknown: the window closed, we WERE recording, and
        nobody paid. That is evidence."""
        c = cohort(AUG, {})
        self.assertTrue(c["measurable"])
        self.assertEqual(c["numerator"], 0)
        self.assertEqual(c["rate"], 0.0)


class CohortMembership(unittest.TestCase):

    def test_15_16_the_denominator_is_distinct_parties(self):
        c = cohort(AUG, {})
        self.assertEqual(c["denominator"], 4)
        self.assertEqual(len(set(c["denominator_evidence"])), 4)

    def test_16b_repeat_enquiries_cannot_inflate_the_denominator(self):
        """Guaranteed upstream: first_seen_at is `single` cardinality, and the
        reader takes the EARLIEST claim per subject."""
        self.assertIn("'single'", io.open(
            os.path.join(MIG, "20260816000012_bic_seed_first_seen_at.sql"),
            encoding="utf-8").read())
        src = module_code("bic/claims.py")
        self.assertIn("setdefault", src)

    def test_a_payment_from_outside_the_cohort_is_ignored(self):
        c = cohort({"p1": AUG["p1"]},
                   {"p1": "2026-08-05T10:00:00+05:30",
                    "stranger": "2026-08-06T10:00:00+05:30"})
        self.assertEqual(c["numerator"], 1)
        self.assertNotIn("stranger", c["numerator_evidence"])

    def test_25_26_both_sides_preserve_their_evidence(self):
        c = cohort(AUG, {"p1": "2026-08-05T10:00:00+05:30"})
        self.assertEqual(c["denominator_evidence"], ["p1", "p2", "p3", "p4"])
        self.assertEqual(c["numerator_evidence"], ["p1"])
        self.assertIsNotNone(c["window_closes_at"])


class TheMetricRegistration(unittest.TestCase):

    def test_the_rate_is_bounded_zero_to_one(self):
        sql = io.open(SEED_RATE, encoding="utf-8").read()
        self.assertIn("'min', 0", sql)
        self.assertIn("'max', 1", sql)
        self.assertIn("'ratio'", sql)
        self.assertIn("'QUANTITATIVE'", sql)
        self.assertIn("'single'", sql)

    def test_it_is_tier_3_derived_never_stronger_than_its_evidence(self):
        self.assertEqual(ce.PROVENANCE_TIER, 3)
        sql = io.open(SEED_RATE, encoding="utf-8").read()
        self.assertIn("ORGANIZATION", sql)

    def test_the_migration_is_registry_only(self):
        for f in ("20260907000025_bic_seed_became_client_at.sql",
                  "20260907000026_bic_first_payment_tool.sql",
                  "20260907000027_bic_seed_conversion_rate.sql"):
            sql = io.open(os.path.join(MIG, f), encoding="utf-8").read().upper()
            for banned in ("CREATE TABLE", "ALTER TABLE", "DROP ", "GRANT ",
                           "CREATE POLICY", "ROW LEVEL SECURITY"):
                self.assertNotIn(banned, sql, f"{f}: {banned}")

    def test_31_the_enquiry_metric_is_untouched(self):
        import bic.pipeline_evidence as pe
        self.assertEqual(pe.PREDICATE, "biz.pipeline.new_enquiries_per_month@1")
        self.assertEqual(pe.PROVENANCE_TIER, 3)

    def test_30_reasoning_consumes_it_generically(self):
        code = module_code("bic/reasoning.py").lower()
        for bad in ("conversion", "became_client", "cohort", "provisional"):
            self.assertNotIn(bad, code, f"hardcoded {bad} in reasoning")

    def test_29_the_review_slot_points_at_this_predicate(self):
        self.assertEqual(gl.CONVERSION_RATE, CONV_PRED)
        self.assertEqual(ce.PREDICATE, CONV_PRED)

    def test_35_no_financial_payload_in_the_producer(self):
        code = module_code("bic/conversion_evidence.py").lower()
        for banned in ("amount", "currency", "invoice", "transaction",
                       "card", "bank", "upi"):
            self.assertNotIn(banned, code, banned)

    def test_34_the_producer_reads_no_pii(self):
        code = module_code("bic/conversion_evidence.py").lower()
        for banned in ("phone", "name", "email", "wamid", "whatsapp_messages"):
            self.assertNotIn(banned, code, banned)


# ══════════════════════════════════════════════════════════════════════════
# claims.valid_from_by_subject — the new store read, driven for real
#
# Every test above mocks this function, which meant its OWN guards were never
# exercised: two mutations (retracted claims counted, tenant check removed)
# survived the entire suite. These drive the real function over a stubbed
# `select` so those guards are held by something.
# ══════════════════════════════════════════════════════════════════════════

from bic import claims as cl                                   # noqa: E402


class ValidFromBySubject(unittest.TestCase):

    def drive(self, rows, retracted=(), **kw):
        captured = {}

        def fake_select(table, params, timeout=None):
            captured.setdefault("calls", []).append((table, params))
            if table == cl.RETRACTIONS_TABLE:
                return [{"claim_id": c} for c in retracted]
            return rows

        with mock.patch.object(cl, "select", fake_select), \
             mock.patch.object(cl.registry, "parse_ref",
                               lambda ref: ("core.party", "first_seen_at", 1)):
            out = cl.valid_from_by_subject(TENANT, "core.party.first_seen_at@1",
                                           **kw)
        return out, captured

    def test_the_earliest_claim_wins_per_subject(self):
        """Both predicates this serves are `single` and permanent. Taking the
        later claim would move a party's window and could push a real
        conversion outside it."""
        out, _ = self.drive([
            {"claim_id": "c1", "subject": "p1", "valid_from": "2026-08-01T00:00:00+00:00"},
            {"claim_id": "c2", "subject": "p1", "valid_from": "2026-08-09T00:00:00+00:00"},
        ])
        self.assertEqual(out, {"p1": "2026-08-01T00:00:00+00:00"})

    def test_a_retracted_claim_is_not_evidence(self):
        out, _ = self.drive([
            {"claim_id": "c1", "subject": "p1", "valid_from": "2026-08-01T00:00:00+00:00"},
            {"claim_id": "c2", "subject": "p2", "valid_from": "2026-08-02T00:00:00+00:00"},
        ], retracted=("c1",))
        self.assertEqual(list(out), ["p2"])

    def test_a_retraction_falls_through_to_the_next_live_claim(self):
        out, _ = self.drive([
            {"claim_id": "c1", "subject": "p1", "valid_from": "2026-08-01T00:00:00+00:00"},
            {"claim_id": "c2", "subject": "p1", "valid_from": "2026-08-09T00:00:00+00:00"},
        ], retracted=("c1",))
        self.assertEqual(out, {"p1": "2026-08-09T00:00:00+00:00"})

    def test_a_tenant_is_required(self):
        with self.assertRaises(cl.ClaimError):
            cl.valid_from_by_subject("", "core.party.first_seen_at@1")

    def test_the_tenant_is_actually_sent_to_the_store(self):
        _, cap = self.drive([])
        table, params = cap["calls"][0]
        self.assertEqual(params["tenant_id"], f"eq.{TENANT}")

    def test_the_window_is_half_open(self):
        """An event at exactly window_end belongs to the NEXT window, so
        consecutive cohorts partition time with no double-count and no gap."""
        rows = [{"claim_id": "c1", "subject": "p1",
                 "valid_from": "2026-09-01T00:00:00+00:00"}]
        out, _ = self.drive(rows,
                            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                            window_end=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(out, {}, "an event at window_end is the next window's")

    def test_an_empty_subject_list_short_circuits(self):
        with mock.patch.object(cl, "select",
                               lambda *a, **k: self.fail("must not query")):
            self.assertEqual(
                cl.valid_from_by_subject(TENANT, "core.party.first_seen_at@1",
                                         subjects=[]), {})

    def test_the_subject_filter_is_sent_when_given(self):
        _, cap = self.drive([], subjects=["p1", "p2"])
        _, params = cap["calls"][0]
        self.assertIn("subject", params)
        self.assertIn("p1", params["subject"])
        self.assertTrue(params["subject"].startswith("in."))


class NumeratorMembershipIsEnforcedByTheLoop(unittest.TestCase):

    def test_only_cohort_members_can_convert(self):
        """The `subjects=` query filter is an optimisation; the correctness
        boundary is iterating the DENOMINATOR and looking payments up, never
        the reverse. A mutation that dropped the filter changed nothing, which
        is how this was found."""
        import ast, inspect
        tree = ast.parse(inspect.getsource(ce.cohort).lstrip())
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
        targets = []
        for lp in loops:
            it = lp.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute):
                targets.append((getattr(it.func.value, "id", ""), it.func.attr))
        self.assertIn(("enquired", "items"), targets,
                      "the numerator must iterate the cohort, not the payments")
