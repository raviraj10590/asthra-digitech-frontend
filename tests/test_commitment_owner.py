"""The OWNER consumer that CLOSES a 2B commitment.

Stage ⑮ could create commitments and nothing could resolve one, so a
production promise would sit in `made` forever. These tests cover the
smallest owner-only path that closes it — and, more importantly, every way
that path must REFUSE.

The sharp ones:
  · a CUSTOMER must never reach any of it (policy allowlist, Article VI)
  · a terminal commitment never moves again, and the RPC is never called
  · an ambiguous reference closes nothing, because `met` cannot be undone
  · marking a promise met does NOT complete the customer's Goal

Offline: no network, no AI, no database.
"""

import ast
import os
import pathlib
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import webhook as w                                               # noqa: E402
from bic import commitment as cm                                  # noqa: E402
from bic import policy, tools                                     # noqa: E402
from tests.test_commitment import FakeRpc, FakeStore              # noqa: E402

OWNER = "910000000001"
CUSTOMER = "919555555555"
TENANT = w.bic_config.DEFAULT_TENANT_ID
PARTY = "11111111-2222-3333-4444-555555555555"
MIGRATION = os.path.join(os.path.dirname(__file__), "..", "supabase",
                         "migrations", "20260825000019_bic_commitment_tools.sql")

# The registry rows exactly as the migration declares them. Primed rather than
# read from a database, and cross-checked against the migration text below —
# so a test cannot pass against permissions the migration never granted.
REGISTRY = {
    "commitments_list": {"code": "commitments_list", "min_role": "OWNER",
                         "customer_safe": False, "active": True,
                         "audit_level": "basic", "timeout_seconds": 10},
    "commitment_resolve": {"code": "commitment_resolve", "min_role": "OWNER",
                           "customer_safe": False, "active": True,
                           "audit_level": "full", "timeout_seconds": 10},
}


def a_commitment(**over):
    base = dict(tenant_id=TENANT, party=PARTY, obligation="DELIVER_PENDING_REPLY",
                due_on=datetime.now(timezone.utc) + timedelta(hours=4),
                owner="agent:brain", decision_ref="dec-1")
    base.update(over)
    return cm.make(**base)


class Base(unittest.TestCase):
    """Real dispatch, real policy, real domain — fake store and fake RPC."""

    def setUp(self):
        self.store = FakeStore()
        self.rpc = FakeRpc(self.store)
        for target, fn in (("insert", self.store.insert),
                           ("select", self.store.select),
                           ("rpc", self.rpc)):
            p = mock.patch.object(cm, target, fn)
            p.start()
            self.addCleanup(p.stop)

        self._cache = dict(tools._REGISTRY_CACHE)
        self._exp = tools._REGISTRY_EXPIRES
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE.update(REGISTRY)
        tools._REGISTRY_EXPIRES = 1e18
        self.addCleanup(self._restore)

        p = mock.patch.object(w, "BIC_AVAILABLE", True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(w.bic_config, "is_configured", lambda: True)
        p.start()
        self.addCleanup(p.stop)

    def _restore(self):
        tools._REGISTRY_CACHE.clear()
        tools._REGISTRY_CACHE.update(self._cache)
        tools._REGISTRY_EXPIRES = self._exp

    def given(self, **over):
        c = cm.save(a_commitment(**over))
        return c, cm.reference(c)

    def owner_says(self, text, sender=OWNER, role="OWNER"):
        return w.try_owner_command(sender, role, text)

    def state(self, ref=None):
        return self.store.rows[0]["lifecycle"]


# ══════════════════════════════════════════════════════════════════════
# LISTING
# ══════════════════════════════════════════════════════════════════════

class Listing(Base):

    def test_owner_can_list_commitments(self):
        _, ref = self.given()
        out = self.owner_says("#commitments")
        self.assertIn(ref, out)
        self.assertIn("DELIVER_PENDING_REPLY", out)

    def test_the_listing_shows_lifecycle_and_deadline(self):
        self.given()
        out = self.owner_says("#commitments")
        self.assertIn(cm.MADE, out)
        self.assertIn("IST", out)

    def test_the_listing_shows_the_accountable_owner(self):
        self.given()
        self.assertIn("agent:brain", self.owner_says("#commitments"))

    def test_an_overdue_commitment_is_marked(self):
        self.given(due_on=datetime.now(timezone.utc) + timedelta(seconds=1),
                   at=datetime.now(timezone.utc) - timedelta(hours=1))
        # Force it past due by moving the row's deadline into the past.
        self.store.rows[0]["due_on"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertIn("OVERDUE", self.owner_says("#commitments"))

    def test_a_current_commitment_is_not_marked_overdue(self):
        self.given()
        self.assertNotIn("OVERDUE", self.owner_says("#commitments"))

    def test_empty_is_stated_plainly_not_left_blank(self):
        self.assertIn("No outstanding", self.owner_says("#commitments"))

    def test_terminal_commitments_are_not_listed_as_outstanding(self):
        c, _ = self.given()
        cm.record_transition(c, cm.IN_PROGRESS, reason="started")
        moved = dict(c, lifecycle=cm.IN_PROGRESS)
        cm.record_transition(moved, cm.MET, reason="done")
        self.assertIn("No outstanding", self.owner_says("#commitments"))

    def test_the_listing_and_the_digest_read_the_same_source(self):
        """§7 — one commitment source, not two."""
        digest_src = pathlib.Path(os.path.join(
            os.path.dirname(__file__), "..", "api", "digest.py")).read_text()
        self.assertIn("bic_commitment.overdue(", digest_src)
        listing = ast.parse(pathlib.Path(os.path.join(
            os.path.dirname(__file__), "..", "api", "webhook.py")).read_text())
        names = {n.attr for n in ast.walk(listing)
                 if isinstance(n, ast.Attribute)}
        self.assertIn("outstanding", names)
        # Both live in bic/commitment.py against bic_commitments.
        self.assertEqual(cm.TABLE, "bic_commitments")


# ══════════════════════════════════════════════════════════════════════
# AUTHORIZATION
# ══════════════════════════════════════════════════════════════════════

class Authorization(Base):

    def _denied(self, code, **args):
        p = policy.Principal(CUSTOMER, "CLIENT", TENANT)
        return tools.invoke(p, code, **args)

    def test_a_customer_cannot_list_commitments(self):
        self.assertTrue(self._denied("commitments_list").denied)

    def test_a_customer_cannot_resolve_a_commitment(self):
        _, ref = self.given()
        res = self._denied("commitment_resolve", ref=ref, action="met")
        self.assertTrue(res.denied)
        self.assertEqual(self.state(), cm.MADE, "denial must not mutate")

    def test_a_denied_customer_never_reaches_the_rpc(self):
        _, ref = self.given()
        self._denied("commitment_resolve", ref=ref, action="met")
        self.assertEqual(self.rpc.calls, 0)

    def test_staff_cannot_resolve_a_commitment(self):
        """min_role OWNER — STAFF is below it."""
        p = policy.Principal(OWNER, "STAFF", TENANT)
        _, ref = self.given()
        res = tools.invoke(p, "commitment_resolve", ref=ref, action="met")
        self.assertTrue(res.denied)
        self.assertEqual(self.state(), cm.MADE)

    def test_an_owner_is_allowed(self):
        p = policy.Principal(OWNER, "OWNER", TENANT)
        allowed, _ = policy.may_invoke(p, REGISTRY["commitment_resolve"])
        self.assertTrue(allowed)

    def test_the_customer_path_never_dispatches_owner_commands(self):
        """try_owner_command is only reached from the OWNER/STAFF route."""
        src = pathlib.Path(os.path.join(os.path.dirname(__file__), "..",
                                        "api", "webhook.py")).read_text()
        body = src[src.index("def run_client_pipeline"):]
        body = body[:body.index("\ndef ")]
        self.assertNotIn("try_owner_command", body)
        self.assertNotIn("commitment_resolve", body)

    def test_the_migration_grants_owner_only_and_not_customer_safe(self):
        """The primed registry above must match what the migration declares —
        otherwise these tests prove permissions nobody granted."""
        sql = pathlib.Path(MIGRATION).read_text()
        self.assertEqual(len(re.findall(r"'OWNER', \d", sql)), 2)
        self.assertNotIn("true, true", sql)
        for code in ("commitments_list", "commitment_resolve"):
            self.assertIn(f"'{code}'", sql)

    def test_no_second_authorization_system(self):
        """Both tools go through run_tool → policy.may_invoke, like every
        other tool. No bespoke role check in the command handlers."""
        src = pathlib.Path(os.path.join(os.path.dirname(__file__), "..",
                                        "api", "webhook.py")).read_text()
        fn = src[src.index("def tool_commitment_resolve"):]
        fn = fn[:fn.index("\n_VERDICT_ICON")]
        for bypass in ("BOOTSTRAP_OWNERS", "OWNER_PHONE", 'role ==', "get_role("):
            self.assertNotIn(bypass, fn)


# ══════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════════

class Lifecycle(Base):

    def test_owner_can_start(self):
        _, ref = self.given()
        out = self.owner_says(f"#commitment {ref} start")
        self.assertIn(cm.IN_PROGRESS, out)
        self.assertEqual(self.state(), cm.IN_PROGRESS)

    def test_owner_can_meet_after_starting(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        out = self.owner_says(f"#commitment {ref} met")
        self.assertEqual(self.state(), cm.MET)
        self.assertIn("met", out)

    def test_met_directly_from_made_is_refused(self):
        """2B: nothing is met without having been worked on."""
        _, ref = self.given()
        out = self.owner_says(f"#commitment {ref} met")
        self.assertEqual(self.state(), cm.MADE)
        self.assertIn("⛔", out)

    def test_owner_can_waive_from_made(self):
        _, ref = self.given()
        out = self.owner_says(f"#commitment {ref} waive client withdrew")
        self.assertEqual(self.state(), cm.WAIVED)
        self.assertIn(cm.WAIVED, out)

    def test_owner_can_waive_from_in_progress(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        self.owner_says(f"#commitment {ref} waive no longer needed")
        self.assertEqual(self.state(), cm.WAIVED)

    def test_missed_is_not_an_offered_action(self):
        """A miss is a judgement about the past, not a command next to met."""
        self.assertNotIn("miss", w.COMMITMENT_ACTIONS)
        _, ref = self.given()
        out = self.owner_says(f"#commitment {ref} missed")
        self.assertEqual(self.state(), cm.MADE)
        self.assertIn("Unknown action", out)

    def test_renegotiate_is_not_an_offered_action(self):
        self.assertNotIn("renegotiate", w.COMMITMENT_ACTIONS)

    def test_only_2b_approved_transitions_are_offered(self):
        self.assertEqual(set(w.COMMITMENT_ACTIONS.values()),
                         {cm.IN_PROGRESS, cm.MET, cm.WAIVED})

    def test_every_change_writes_exactly_one_transition_row(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        self.assertEqual(len(self.store.transitions), 1)
        self.owner_says(f"#commitment {ref} met")
        self.assertEqual(len(self.store.transitions), 2)

    def test_it_goes_through_the_rpc_not_a_bare_update(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        self.assertEqual(self.rpc.calls, 1)
        # FakeStore.update raises if anything attempts a direct UPDATE.
        self.assertEqual(self.state(), cm.IN_PROGRESS)


class Waiver(Base):

    def test_a_waiver_without_a_reason_is_refused(self):
        _, ref = self.given()
        out = self.owner_says(f"#commitment {ref} waive")
        self.assertEqual(self.state(), cm.MADE)
        self.assertIn("reason", out)

    def test_a_waiver_records_an_actor(self):
        """2B: waived '(requires approver)'."""
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} waive client withdrew")
        self.assertEqual(self.store.transitions[-1]["actor"],
                         w.COMMITMENT_OWNER_ACTOR)

    def test_the_actor_is_an_agent_reference_not_a_phone(self):
        """migration 18: actor is 'Bounded, non-PII: an AGENT reference'."""
        actor = w.COMMITMENT_OWNER_ACTOR
        self.assertTrue(actor.startswith("agent:"))
        self.assertFalse(any(ch.isdigit() for ch in actor))

    def test_the_owners_phone_never_reaches_the_transition_row(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} waive client withdrew")
        blob = repr(self.store.transitions[-1])
        self.assertNotIn(OWNER, blob)

    def test_the_reason_is_recorded_on_the_transition(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} waive client withdrew")
        self.assertIn("client withdrew", self.store.transitions[-1]["reason"])

    def test_a_non_waiver_transition_carries_no_actor(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        self.assertIsNone(self.store.transitions[-1]["actor"])


# ══════════════════════════════════════════════════════════════════════
# IDEMPOTENCY
# ══════════════════════════════════════════════════════════════════════

class Idempotency(Base):

    def _met(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        self.owner_says(f"#commitment {ref} met")
        return ref

    def test_met_twice_is_deterministic_and_changes_nothing(self):
        ref = self._met()
        before = len(self.store.transitions)
        out = self.owner_says(f"#commitment {ref} met")
        self.assertIn("already met", out)
        self.assertEqual(len(self.store.transitions), before)

    def test_met_twice_never_calls_the_rpc_again(self):
        ref = self._met()
        calls = self.rpc.calls
        self.owner_says(f"#commitment {ref} met")
        self.assertEqual(self.rpc.calls, calls)

    def test_the_repeated_answer_is_byte_identical(self):
        ref = self._met()
        self.assertEqual(self.owner_says(f"#commitment {ref} met"),
                         self.owner_says(f"#commitment {ref} met"))

    def test_already_waived_is_deterministic(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} waive done")
        out = self.owner_says(f"#commitment {ref} waive again")
        self.assertIn("already waived", out)
        self.assertEqual(self.state(), cm.WAIVED)

    def test_waive_after_met_is_refused(self):
        ref = self._met()
        out = self.owner_says(f"#commitment {ref} waive too late")
        self.assertEqual(self.state(), cm.MET)
        self.assertIn("already met", out)

    def test_start_after_waived_is_refused(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} waive done")
        out = self.owner_says(f"#commitment {ref} start")
        self.assertEqual(self.state(), cm.WAIVED)
        self.assertIn("already waived", out)

    def test_start_twice_is_refused_by_the_domain(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        before = len(self.store.transitions)
        out = self.owner_says(f"#commitment {ref} start")
        self.assertEqual(len(self.store.transitions), before)
        self.assertIn("⛔", out)


# ══════════════════════════════════════════════════════════════════════
# REFERENCE RESOLUTION
# ══════════════════════════════════════════════════════════════════════

class References(Base):

    def test_a_reference_is_stable_for_a_commitment(self):
        c, ref = self.given()
        self.assertEqual(cm.reference(c), ref)
        self.assertEqual(cm.reference(self.store.rows[0]), ref)

    def test_a_reference_is_not_the_raw_uuid(self):
        c, ref = self.given()
        self.assertNotIn(str(c["commitment_id"]), ref)
        self.assertLess(len(ref), len(str(c["commitment_id"])))

    def test_a_reference_is_case_insensitive(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref.lower()} start")
        self.assertEqual(self.state(), cm.IN_PROGRESS)

    def test_the_prefix_may_be_omitted(self):
        _, ref = self.given()
        self.owner_says(f"#commitment {ref[2:]} start")
        self.assertEqual(self.state(), cm.IN_PROGRESS)

    def test_a_reference_beginning_with_c_survives_prefix_stripping(self):
        """REGRESSION. normalise_reference used to strip any leading "C",
        eating the first hex digit of roughly one reference in sixteen. Pinned
        with a fixed id rather than left to a random uuid, which is why the
        original bug only showed up intermittently."""
        c, _ = self.given()
        self.store.rows[0]["commitment_id"] = "cafe1234-0000-0000-0000-000000000000"
        ref = cm.reference(self.store.rows[0])
        self.assertEqual(ref, "C-CAFE1234")
        self.assertEqual(cm.normalise_reference(ref), "CAFE1234")
        self.assertEqual(cm.normalise_reference("CAFE1234"), "CAFE1234")
        self.owner_says("#commitment CAFE1234 start")
        self.assertEqual(self.state(), cm.IN_PROGRESS)

    def test_an_unknown_reference_changes_nothing(self):
        self.given()
        out = self.owner_says("#commitment C-DEADBEEF met")
        self.assertEqual(self.state(), cm.MADE)
        self.assertIn("No commitment", out)

    def test_a_too_short_reference_is_refused(self):
        """A one-character prefix could match a promise nobody meant."""
        self.given()
        out = self.owner_says("#commitment C-1 met")
        self.assertEqual(self.state(), cm.MADE)
        self.assertIn("at least", out)

    def test_an_ambiguous_reference_closes_nothing(self):
        """`met` is terminal — guessing here is unrecoverable."""
        c1, _ = self.given()
        c2, _ = self.given(party="22222222-3333-4444-5555-666666666666")
        shared = "AB12CD34"
        for row in self.store.rows:
            row["commitment_id"] = shared + str(row["commitment_id"])[8:]
        out = self.owner_says(f"#commitment {shared} met")
        # Asserted on the AMBIGUITY wording specifically. "No commitment
        # matches …" also contains the word "match", so a looser assertion
        # here would pass even if the reference resolved to nothing.
        self.assertIn("Use more characters", out)
        self.assertIn("2 commitments match", out)
        self.assertEqual(self.rpc.calls, 0)
        self.assertTrue(all(r["lifecycle"] == cm.MADE for r in self.store.rows))

    def test_a_wrong_tenant_commitment_is_invisible(self):
        self.given()
        self.store.rows[0]["tenant_id"] = "99999999-9999-9999-9999-999999999999"
        ref = cm.reference(self.store.rows[0])
        out = self.owner_says(f"#commitment {ref} met")
        self.assertIn("No commitment", out)
        self.assertEqual(self.store.rows[0]["lifecycle"], cm.MADE)

    def test_tenant_isolation_on_the_listing(self):
        self.given()
        self.store.rows[0]["tenant_id"] = "99999999-9999-9999-9999-999999999999"
        self.assertIn("No outstanding", self.owner_says("#commitments"))


# ══════════════════════════════════════════════════════════════════════
# MALFORMED INPUT
# ══════════════════════════════════════════════════════════════════════

class Malformed(Base):

    def setUp(self):
        super().setUp()
        self.c, self.ref = self.given()

    def assert_unchanged(self, out):
        self.assertEqual(self.state(), cm.MADE)
        self.assertEqual(self.rpc.calls, 0)
        self.assertIsNotNone(out)

    def test_bare_command_explains_usage(self):
        out = self.owner_says("#commitment")
        self.assert_unchanged(out)
        self.assertIn("Usage", out)

    def test_reference_without_action(self):
        self.assert_unchanged(self.owner_says(f"#commitment {self.ref}"))

    def test_unknown_action(self):
        out = self.owner_says(f"#commitment {self.ref} obliterate")
        self.assert_unchanged(out)
        self.assertIn("Unknown action", out)

    def test_action_without_reference(self):
        self.assert_unchanged(self.owner_says("#commitment met"))

    def test_garbage_arguments(self):
        for text in ("#commitment ; drop table", "#commitment ** met",
                     "#commitment  " , "#commitmentmet"):
            with self.subTest(text=text):
                self.owner_says(text)
        self.assertEqual(self.state(), cm.MADE)
        self.assertEqual(self.rpc.calls, 0)

    def test_a_store_outage_leaves_the_commitment_untouched(self):
        with mock.patch.object(cm, "select",
                               side_effect=cm.DbError("supabase down")):
            out = self.owner_says(f"#commitment {self.ref} start")
        self.assertIn("UNAVAILABLE", out)
        self.assertEqual(self.state(), cm.MADE)

    def test_an_rpc_outage_reports_no_change(self):
        with mock.patch.object(cm, "rpc", side_effect=cm.DbError("down")):
            out = self.owner_says(f"#commitment {self.ref} start")
        self.assertIn("unchanged", out)
        self.assertEqual(self.state(), cm.MADE)

    def test_an_rpc_returning_nothing_is_treated_as_not_applied(self):
        with mock.patch.object(cm, "rpc", lambda *a, **k: None):
            out = self.owner_says(f"#commitment {self.ref} start")
        self.assertIn("⛔", out)
        self.assertEqual(self.state(), cm.MADE)


# ══════════════════════════════════════════════════════════════════════
# BOUNDARIES — goal, 2I, PII, the LLM
# ══════════════════════════════════════════════════════════════════════

class Boundaries(Base):

    def source(self):
        """CODE of the two commitment tools, with comments and string
        literals removed. These functions EXPLAIN in prose why they do not
        touch goal_lifecycle or 2I, and a raw-text scan would read that
        explanation as the violation it warns against."""
        src = pathlib.Path(os.path.join(os.path.dirname(__file__), "..",
                                        "api", "webhook.py")).read_text()
        tree = ast.parse(src)
        wanted = {"tool_commitments_list", "tool_commitment_resolve",
                  "_commitment_due_text", "_commitment_party_ref"}
        out = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in wanted:
                class Blank(ast.NodeTransformer):
                    def visit_Constant(self, n):
                        if isinstance(n.value, str):
                            return ast.copy_location(ast.Constant(value=""), n)
                        return n
                out.append(ast.unparse(Blank().visit(node)))
        self.assertEqual(len(out), len(wanted), "functions not found")
        return "\n".join(out)

    def test_meeting_a_commitment_does_not_complete_the_goal(self):
        """§10 — and here it CANNOT: the goal instance was EPHEMERAL (3B
        §1.2) and stopped existing with its turn. Even persisted, is_complete
        requires ACTIVE + delivered, and ⑮ left it BLOCKED."""
        _, ref = self.given()
        self.owner_says(f"#commitment {ref} start")
        out = self.owner_says(f"#commitment {ref} met")
        self.assertIn("not marked complete", out)

    def test_it_never_touches_goal_lifecycle(self):
        for banned in ("goal_lifecycle", "complete(", "COMPLETED"):
            self.assertNotIn(banned, self.source())

    def test_closing_a_commitment_writes_no_outcome(self):
        """2I is what the WORLD did. This is what WE did about a promise."""
        for banned in ("outcome", "expect_customer_reply", "observe_"):
            self.assertNotIn(banned, self.source())

    def test_closing_a_commitment_writes_no_claim(self):
        for banned in ("bic_claims", "claims.", "assert_claim"):
            self.assertNotIn(banned, self.source())

    def test_no_outcome_or_claim_row_is_written(self):
        """FakeStore raises on ANY table other than bic_commitments and
        bic_commitment_transitions, so an outcome or claim write would blow
        up here rather than pass unnoticed. Recorded explicitly: exactly one
        commitment and exactly two transitions, and nothing else."""
        tables = []
        real_insert = self.store.insert

        def spy(table, row, timeout=None):
            tables.append(table)
            return real_insert(table, row, timeout=timeout)

        with mock.patch.object(cm, "insert", spy):
            _, ref = self.given()
            self.owner_says(f"#commitment {ref} start")
            self.owner_says(f"#commitment {ref} met")
        self.assertEqual(set(tables), {cm.TABLE})
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(len(self.store.transitions), 2)

    def test_the_llm_cannot_resolve_a_commitment(self):
        """I5. The action comes from a closed map keyed by an exact word, and
        nothing here consults a model."""
        for banned in ("generate_reply", "openai", "gemini", "llm", "prompt"):
            self.assertNotIn(banned, self.source().lower())

    def test_the_action_vocabulary_is_closed(self):
        self.assertEqual(set(w.COMMITMENT_ACTIONS),
                         {"start", "met", "waive"})

    def test_free_text_cannot_become_an_action(self):
        _, ref = self.given()
        for phrase in ("done", "it is met", "close it", "finished"):
            with self.subTest(phrase=phrase):
                self.owner_says(f"#commitment {ref} {phrase}")
        self.assertEqual(self.state(), cm.MADE)

    def test_the_listing_leaks_no_pii(self):
        self.given()
        out = self.owner_says("#commitments")
        for banned in (CUSTOMER, OWNER, "wamid", "source_ref", "@"):
            self.assertNotIn(banned, out)

    def test_the_listing_shows_no_raw_uuid(self):
        c, _ = self.given()
        out = self.owner_says("#commitments")
        self.assertNotIn(str(c["commitment_id"]), out)
        self.assertNotIn(str(PARTY), out)
        self.assertNotIn(TENANT, out)

    def test_the_party_is_shown_as_an_opaque_handle(self):
        self.given()
        out = self.owner_says("#commitments")
        self.assertRegex(out, r"party P-[0-9A-F]{8}")

    def test_the_resolve_reply_shows_no_raw_uuid(self):
        c, ref = self.given()
        out = self.owner_says(f"#commitment {ref} start")
        self.assertNotIn(str(c["commitment_id"]), out)
        self.assertNotIn(str(PARTY), out)

    def test_the_audit_allowlist_excludes_the_free_text_reason(self):
        """`reason` is owner-typed and may name a person; the security event
        is reconstructable without it, and 2B keeps it on the transition."""
        allow = tools._ARG_ALLOWLIST["commitment_resolve"]
        self.assertIn("ref", allow)
        self.assertIn("action", allow)
        self.assertNotIn("reason", allow)


class ExistingCommandsUnchanged(Base):

    def test_why_is_unchanged(self):
        with mock.patch.object(w, "run_tool",
                               lambda s, code, **k: f"CALLED:{code}"):
            self.assertEqual(self.owner_says("#why"), "CALLED:knowledge_why")

    def test_suffice_is_unchanged(self):
        with mock.patch.object(w, "run_tool",
                               lambda s, code, **k: f"CALLED:{code}|{k.get('goal_id')}"):
            self.assertEqual(self.owner_says("#suffice social_media_enquiry"),
                             "CALLED:knowledge_suffice|social_media_enquiry")

    def test_commitment_commands_do_not_shadow_other_hashes(self):
        with mock.patch.object(w, "run_tool",
                               lambda s, code, **k: f"CALLED:{code}"):
            self.assertEqual(self.owner_says("#leads"), "CALLED:leads_today")
            self.assertEqual(self.owner_says("#clients"),
                             "CALLED:crm_list_clients")

    def test_help_lists_the_new_commands(self):
        self.assertIn("#commitments", w.OWNER_COMMANDS_HELP)
        self.assertIn("#commitment <ref>", w.OWNER_COMMANDS_HELP)

    def test_an_unknown_hash_command_still_falls_through(self):
        self.assertIn("Unknown command", self.owner_says("#nonsense"))
