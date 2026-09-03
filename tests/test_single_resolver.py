"""Slice 1C — proof that legacy and Brain share ONE role resolver.

Owner requirement: replay must compare decisions from the SAME resolver, so a
disagreement can only mean a real logic difference — never two lookup
implementations differing.

Each test asserts legacy == Brain for the same sender under the same conditions.
Offline; the single DB query is replaced by an injected fetcher.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                      # noqa: E402
from bic import brain, identity          # noqa: E402
from bic.contract import BrainRequest, BrainResponse  # noqa: E402

OWNER = "910000000001"
STAFF = "919111111111"
UNKNOWN = "919222222222"


def brain_role(sender):
    """Role as the Brain sees it, via the injected flows."""
    seen = {}

    def capture(principal, request):
        seen["role"] = principal.role
        seen["degraded"] = principal.degraded
        return BrainResponse(text="")

    brain.handle(BrainRequest(channel="whatsapp", sender_id=sender, text="x"),
                 brain.Flows(owner=capture, client=capture))
    return seen


class TestOneResolver(unittest.TestCase):
    def setUp(self):
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        self.calls = []

    def tearDown(self):
        # IDENTITY IS MODULE-LEVEL STATE. configure() installs a fetcher for
        # the whole process, so a test that installs one and walks away
        # re-roles every later test's phone numbers. This module left a
        # fetcher returning STAFF for ANY number, which routed the webhook
        # lifecycle suite down the OWNER branch and failed five of its tests
        # ~130 tests later. Same save/restore discipline as
        # test_1c_closure_validation.py.
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def _fetch(self, rows):
        def f(phone):
            self.calls.append(phone)
            return rows.get(phone)
        return f

    # ── bootstrap owner ────────────────────────────────────────────────────
    def test_bootstrap_owner_legacy_equals_brain(self):
        identity.configure(self._fetch({}))
        self.assertEqual(w.get_role(OWNER)[0], "OWNER")
        self.assertEqual(brain_role(OWNER)["role"], "OWNER")
        self.assertEqual(self.calls, [], "bootstrap must not hit the database")

    # ── staff ──────────────────────────────────────────────────────────────
    def test_staff_legacy_equals_brain(self):
        identity.configure(self._fetch({STAFF: {"role": "STAFF", "label": "Priya"}}))
        legacy_role, legacy_label = w.get_role(STAFF)
        b = brain_role(STAFF)
        self.assertEqual(legacy_role, "STAFF")
        self.assertEqual(b["role"], "STAFF")
        self.assertEqual(legacy_label, "Priya")

    # ── unknown ────────────────────────────────────────────────────────────
    def test_unknown_legacy_equals_brain(self):
        identity.configure(self._fetch({}))
        self.assertEqual(w.get_role(UNKNOWN)[0], "CLIENT")
        self.assertEqual(brain_role(UNKNOWN)["role"], "CLIENT")

    # ── DB unavailable ─────────────────────────────────────────────────────
    def test_db_unavailable_both_degrade_identically(self):
        def boom(phone):
            raise RuntimeError("db down")
        identity.configure(boom)

        legacy_role, _ = w.get_role(UNKNOWN)
        b = brain_role(UNKNOWN)

        self.assertEqual(legacy_role, "CLIENT")
        self.assertEqual(b["role"], "CLIENT")
        self.assertTrue(b["degraded"], "degradation must be visible, not silent")

    def test_db_unavailable_does_not_escalate_staff(self):
        """An outage must never PROMOTE anyone."""
        def boom(phone):
            raise RuntimeError("db down")
        identity.configure(boom)
        self.assertEqual(w.get_role(STAFF)[0], "CLIENT")
        self.assertEqual(brain_role(STAFF)["role"], "CLIENT")

    # ── shared cache ───────────────────────────────────────────────────────
    def test_both_paths_share_one_cache(self):
        """The DB is queried ONCE; the Brain then reads the same cache entry."""
        identity.configure(self._fetch({STAFF: {"role": "STAFF", "label": "P"}}))

        w.get_role(STAFF)                    # populates the cache
        self.assertEqual(len(self.calls), 1)

        brain_role(STAFF)                    # must reuse it
        w.get_role(STAFF)
        self.assertEqual(len(self.calls), 1,
                         "duplicate DB lookup — the cache is not shared")

    def test_invalidation_clears_the_shared_cache(self):
        rows = {STAFF: {"role": "STAFF", "label": "P"}}
        identity.configure(self._fetch(rows))

        self.assertEqual(w.get_role(STAFF)[0], "STAFF")
        rows.pop(STAFF)                      # access revoked in the DB
        self.assertEqual(w.get_role(STAFF)[0], "STAFF", "still cached")

        w._invalidate_role(STAFF)            # what #removerole calls
        self.assertEqual(w.get_role(STAFF)[0], "CLIENT")
        self.assertEqual(brain_role(STAFF)["role"], "CLIENT",
                         "Brain must see the revocation too")

    def test_degraded_result_is_not_cached(self):
        """One blip must not pin a user to CLIENT for the whole TTL."""
        state = {"fail": True}

        def flaky(phone):
            if state["fail"]:
                raise RuntimeError("transient")
            return {"role": "STAFF", "label": "P"}

        identity.configure(flaky)
        self.assertEqual(w.get_role(STAFF)[0], "CLIENT")
        state["fail"] = False
        self.assertEqual(w.get_role(STAFF)[0], "STAFF")


class TestNoDuplication(unittest.TestCase):
    def test_webhook_has_no_second_cache(self):
        self.assertFalse(hasattr(w, "_role_cache"),
                         "webhook must not keep its own role cache")

    def test_webhook_has_no_second_bootstrap_list_logic(self):
        """OWNER_PHONES may still be read, but the resolver owns the decision."""
        import inspect
        src = inspect.getsource(w.get_role)
        self.assertIn("bic_identity.resolve_legacy", src,
                      "get_role must delegate to the canonical resolver")

    def test_identity_reuses_policy_primitives(self):
        """Bootstrap logic is imported from 1B, not redefined."""
        src = open(identity.__file__).read()
        self.assertIn("from .policy import", src)
        self.assertNotIn("OWNER_PHONE\"", src)



class TestLatencyInstrumentation(unittest.TestCase):
    """Performance Rules: measure before optimising. Measurement only."""

    def setUp(self):
        self._saved_fetcher = identity._fetch_row
        identity.clear_cache()
        identity.reset_stats()

    def tearDown(self):
        # IDENTITY IS MODULE-LEVEL STATE. configure() installs a fetcher for
        # the whole process, so a test that installs one and walks away
        # re-roles every later test's phone numbers. This module left a
        # fetcher returning STAFF for ANY number, which routed the webhook
        # lifecycle suite down the OWNER branch and failed five of its tests
        # ~130 tests later. Same save/restore discipline as
        # test_1c_closure_validation.py.
        identity.configure(self._saved_fetcher)
        identity.clear_cache()

    def test_counters_classify_correctly(self):
        identity.configure(lambda p: {"role": "STAFF", "label": "x"} if p == STAFF else None)
        identity.resolve(OWNER)          # bootstrap — no lookup
        identity.resolve(STAFF)          # miss
        identity.resolve(STAFF)          # hit
        s = identity.stats()
        self.assertEqual((s["bootstrap"], s["misses"], s["hits"]), (1, 1, 1))
        self.assertEqual(s["total_resolutions"], 3)

    def test_averages_are_none_until_sampled(self):
        """An unsampled counter must not look like a genuine 0 ms."""
        s = identity.stats()
        self.assertIsNone(s["hit_ms_avg"])
        self.assertIsNone(s["miss_ms_avg"])

    def test_degraded_is_counted(self):
        def boom(phone):
            raise RuntimeError("down")
        identity.configure(boom)
        identity.resolve(UNKNOWN)
        self.assertEqual(identity.stats()["degraded"], 1)

    def test_measurement_does_not_alter_resolution(self):
        identity.configure(lambda p: {"role": "STAFF", "label": "x"})
        before = identity.resolve(STAFF).role
        identity.reset_stats()
        self.assertEqual(identity.resolve(STAFF).role, before)


class TestDecisionHash(unittest.TestCase):
    def test_same_decision_same_hash(self):
        from bic import replay
        a = replay.Decision(route="owner", role="OWNER")
        b = replay.Decision(route="owner", role="OWNER")
        self.assertEqual(replay.decision_hash(a), replay.decision_hash(b))

    def test_different_decision_different_hash(self):
        from bic import replay
        a = replay.Decision(route="owner", role="OWNER")
        b = replay.Decision(route="client", role="CLIENT")
        self.assertNotEqual(replay.decision_hash(a), replay.decision_hash(b))


class TestDeprecatedResolver(unittest.TestCase):
    def test_policy_resolve_principal_is_marked_deprecated(self):
        from bic import policy
        doc = policy.resolve_principal.__doc__ or ""
        self.assertIn("@deprecated", doc)
        self.assertIn("bic.identity", doc)
        self.assertIn("REMOVAL CONDITIONS", doc)

    def test_production_path_does_not_call_deprecated_resolver(self):
        import inspect
        self.assertNotIn("resolve_principal", inspect.getsource(w.get_role))
        from bic import brain
        self.assertNotIn("policy.resolve_principal", open(brain.__file__).read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
