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

    def test_19_the_conversion_metric_was_not_invented(self):
        """POLICY_REQUIRED: conversion window. Registering the ratio without a
        window would produce a confident, wrong number — worse than UNKNOWN."""
        import bic.registry  # noqa: F401
        src = io.open(os.path.join(os.path.dirname(__file__), "..",
                                   "bic", "goals.py"), encoding="utf-8").read()
        self.assertNotIn("conversion_rate@1\"", src.replace(
            gl.CONVERSION_RATE, "<declared-gap>"))
        for f in os.listdir(MIG):
            if f >= "20260907":
                sql = io.open(os.path.join(MIG, f), encoding="utf-8").read()
                self.assertNotIn("'conversion_rate'", sql,
                                 f"{f} registers the blocked metric")

    def test_19b_no_conversion_window_was_silently_defaulted(self):
        for mod in ("api/webhook.py", "bic/reasoning.py", "bic/goals.py",
                    "bic/pipeline_evidence.py"):
            code = module_code(mod)
            for bad in ("CONVERSION_WINDOW", "ATTRIBUTION_WINDOW",
                        "conversion_window_days", "WINDOW_DAYS"):
                self.assertNotIn(bad, code, f"{mod} invented a window")

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
