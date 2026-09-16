"""Bot health — the watcher that should have existed three incidents ago.

WHAT IT IS FOR, IN ORDER OF WHAT EACH ONE COST
----------------------------------------------
2026-09-08  The WhatsApp token hit its 60-day expiry. Every send returned 401.
            The bot was silent, nobody knew, and the evidence lived in a log
            with ~1h retention. Found by the owner noticing no reply.
2026-09-15  Transformer enquiries answered as the wrong company for three
            days. Found by the owner reading his own WhatsApp.
2026-09-16  "Is it broken or just quiet?" took four queries and a
            reconstruction of the hourly traffic pattern to answer.

THE TEST THAT MATTERS MOST IS THE FALSE-POSITIVE ONE
----------------------------------------------------
An alarm that fires every morning at 6am gets muted, and a muted alarm is
worse than none — it is the same silence with extra steps. The bot is
legitimately dead quiet 01:00-08:00 IST (zero inbound every night over the
measured week), so test_the_real_overnight_gap_does_not_alarm replays the
actual 19:01 -> 09:10 IST gap and requires silence.

Offline: no network, no provider, no database.
"""

import io
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import health as h                                            # noqa: E402

IST = h.IST
DIGEST = os.path.join(os.path.dirname(__file__), "..", "api", "digest.py")


def ist(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# ══════════════════════════════════════════════════════════════════════════
# 1 · the credential probe
# ══════════════════════════════════════════════════════════════════════════

class ProbeClassification(unittest.TestCase):

    def test_a_200_is_alive(self):
        self.assertEqual(h.classify_probe(200, True), h.OK)

    def test_401_is_the_2026_09_08_signature(self):
        self.assertEqual(h.classify_probe(401, False), h.DEAD)

    def test_403_is_also_dead(self):
        self.assertEqual(h.classify_probe(403, False), h.DEAD)

    def test_a_server_error_is_UNKNOWN_not_dead(self):
        """Crying wolf is how an alarm gets muted. A 500 at Meta's end is not
        a reason to tell the owner his token expired."""
        for code in (500, 502, 503, 429):
            self.assertEqual(h.classify_probe(code, False), h.UNKNOWN, code)

    def test_a_transport_failure_is_UNKNOWN(self):
        self.assertEqual(h.classify_probe(None, False), h.UNKNOWN)


# ══════════════════════════════════════════════════════════════════════════
# 2 · expiry — warn BEFORE, which is the whole point
# ══════════════════════════════════════════════════════════════════════════

class ExpiryClassification(unittest.TestCase):

    NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    def test_zero_means_a_permanent_system_user_token(self):
        """The answer to 'will this happen again?'"""
        state, days = h.classify_expiry(0, self.NOW)
        self.assertEqual(state, h.PERMANENT)
        self.assertIsNone(days)

    def test_a_token_expiring_inside_the_window_warns(self):
        soon = int((self.NOW + timedelta(days=4)).timestamp())
        state, days = h.classify_expiry(soon, self.NOW)
        self.assertEqual(state, h.EXPIRING)
        self.assertEqual(days, 4)

    def test_a_token_with_plenty_of_life_is_quiet(self):
        far = int((self.NOW + timedelta(days=45)).timestamp())
        state, days = h.classify_expiry(far, self.NOW)
        self.assertEqual(state, h.OK)
        self.assertEqual(days, 45)

    def test_an_already_expired_token_is_EXPIRED(self):
        past = int((self.NOW - timedelta(days=2)).timestamp())
        state, _ = h.classify_expiry(past, self.NOW)
        self.assertEqual(state, h.EXPIRED)

    def test_the_60_day_boundary_that_actually_bit(self):
        """A token issued 50 days ago with a 60-day life warns with 10 left."""
        exp = int((self.NOW + timedelta(days=10)).timestamp())
        state, days = h.classify_expiry(exp, self.NOW)
        self.assertEqual((state, days), (h.EXPIRING, 10))

    def test_missing_or_junk_is_UNKNOWN_never_an_assumption(self):
        for v in (None, "", "abc", [], {}):
            self.assertEqual(h.classify_expiry(v, self.NOW)[0], h.UNKNOWN, v)

    def test_the_warning_window_is_longer_than_a_weekend(self):
        self.assertGreaterEqual(h.EXPIRY_WARN_DAYS, 3)


# ══════════════════════════════════════════════════════════════════════════
# 3 · silence — judged in IST against the real pattern
# ══════════════════════════════════════════════════════════════════════════

class SilenceJudgement(unittest.TestCase):

    def test_the_real_overnight_gap_does_not_alarm(self):
        """THE FALSE-POSITIVE GUARD, and the most important test here.

        Measured 2026-09-16: last inbound 19:01 IST, checked at 09:10 IST the
        next morning — 14 wall-clock hours. Zero inbound messages occurred
        between 01:00 and 08:00 IST on any night of the measured week, so this
        gap is normal and an alarm here would fire every single morning.
        """
        abnormal, quiet = h.classify_silence(
            ist(2026, 9, 15, 19, 1), ist(2026, 9, 16, 9, 10))
        self.assertFalse(abnormal,
                         f"alarmed on a normal overnight gap ({quiet}h)")

    def test_a_full_dead_working_day_does_alarm(self):
        abnormal, quiet = h.classify_silence(
            ist(2026, 9, 15, 9, 0), ist(2026, 9, 15, 19, 0))
        self.assertTrue(abnormal)
        self.assertGreaterEqual(quiet, h.SILENCE_ALARM_HOURS)

    def test_a_short_daytime_lull_does_not_alarm(self):
        abnormal, _ = h.classify_silence(
            ist(2026, 9, 15, 12, 0), ist(2026, 9, 15, 15, 0))
        self.assertFalse(abnormal)

    def test_overnight_plus_a_dead_morning_alarms(self):
        """The case that must still work: silent overnight AND then nothing
        all morning is a real outage."""
        abnormal, quiet = h.classify_silence(
            ist(2026, 9, 15, 19, 0), ist(2026, 9, 16, 16, 0))
        self.assertTrue(abnormal)
        self.assertEqual(quiet, 7)

    def test_night_hours_are_not_counted_at_all(self):
        self.assertEqual(
            h.daytime_hours_between(ist(2026, 9, 15, 20, 0),
                                    ist(2026, 9, 16, 8, 0)), 0)

    def test_daytime_hours_are_counted_exactly(self):
        self.assertEqual(
            h.daytime_hours_between(ist(2026, 9, 15, 9, 0),
                                    ist(2026, 9, 15, 14, 0)), 5)

    def test_a_span_crossing_midnight_counts_only_its_daytime(self):
        # 17:00 -> next 11:00 = 2 evening hours (17,18) + 2 morning (9,10)
        self.assertEqual(
            h.daytime_hours_between(ist(2026, 9, 15, 17, 0),
                                    ist(2026, 9, 16, 11, 0)), 4)

    def test_a_bot_that_has_never_been_messaged_is_not_an_outage(self):
        self.assertEqual(h.classify_silence(None), (False, 0))

    def test_a_missing_timestamp_returns_zero_rather_than_crashing(self):
        """The None guard inside daytime_hours_between had NO test: mutation
        testing removed it and nothing failed, because classify_silence()
        returns early and never reaches it. A crash here would take out the
        whole health block — the one thing that is supposed to keep working
        when something else is broken."""
        for start, end in ((None, ist(2026, 9, 16, 12)),
                           (ist(2026, 9, 16, 12), None),
                           (None, None)):
            self.assertEqual(h.daytime_hours_between(start, end), 0)

    def test_a_future_or_equal_timestamp_is_zero_not_negative(self):
        t = ist(2026, 9, 15, 12, 0)
        self.assertEqual(h.daytime_hours_between(t, t), 0)
        self.assertEqual(h.daytime_hours_between(t, t - timedelta(hours=3)), 0)

    def test_the_window_matches_the_measured_traffic(self):
        self.assertEqual((h.DAY_START_IST, h.DAY_END_IST), (9, 19))


# ══════════════════════════════════════════════════════════════════════════
# 4 · what the owner reads
# ══════════════════════════════════════════════════════════════════════════

class TheMessage(unittest.TestCase):

    OKX = (h.PERMANENT, None)
    QUIET = (False, 2)

    def test_a_dead_token_is_loud_and_says_what_to_do(self):
        line = h.compose_health_line(h.DEAD, self.OKX, self.QUIET)
        self.assertIn("🚨", line)
        self.assertIn("401", line)
        self.assertIn("WHATSAPP_TOKEN", line)
        self.assertIn("redeploy", line.lower())

    def test_the_healthy_line_is_boring(self):
        line = h.compose_health_line(h.OK, self.OKX, self.QUIET)
        self.assertNotIn("🚨", line)
        self.assertIn("✅", line)
        self.assertIn("permanent", line)
        self.assertLess(len(line), 160, "a long healthy report gets skimmed")

    def test_an_expiring_token_states_the_days_left(self):
        line = h.compose_health_line(h.OK, (h.EXPIRING, 5), self.QUIET)
        self.assertIn("5d", line)
        self.assertIn("rotate", line.lower())

    def test_abnormal_silence_is_reported_in_daytime_hours(self):
        line = h.compose_health_line(h.OK, self.OKX, (True, 8))
        self.assertIn("8 daytime hours", line)
        self.assertIn("🚨", line)

    def test_an_unverified_probe_says_so_rather_than_claiming_health(self):
        line = h.compose_health_line(h.UNKNOWN, self.OKX, self.QUIET)
        self.assertIn("unverified", line)
        self.assertNotIn("✅", line)

    def test_no_secret_or_pii_reaches_the_message_or_the_record(self):
        """Credential SHAPES, not the word "token".

        The first version banned the substring "token=", which the record
        legitimately contains as "token=PERMANENT" — a state, not a secret.
        Banning the word would have forced the state field out of the record
        to satisfy a test that was measuring the wrong thing. What matters is
        that no credential VALUE and no phone number can appear, which is
        asserted by shape below and by the positive enum check after it.
        """
        import re
        for probe in (h.OK, h.DEAD, h.UNKNOWN):
            for exp in ((h.PERMANENT, None), (h.EXPIRING, 3), (h.UNKNOWN, None)):
                blob = (h.compose_health_line(probe, exp, (True, 9))
                        + " " + h.compose_record(probe, exp, (True, 9)))
                low = blob.lower()
                for banned in ("bearer ", "apikey", "supabase.co",
                               "eyj", "sk-", "aiza"):
                    self.assertNotIn(banned, low, banned)
                # Meta tokens start EAA and run for dozens of characters.
                self.assertIsNone(re.search(r"EAA[A-Za-z0-9]{10,}", blob))
                # No phone number, Indian or otherwise.
                self.assertIsNone(re.search(r"\+?\d{10,}", blob))

    def test_the_recorded_token_state_is_always_one_of_the_known_states(self):
        """The positive form of the check above: the value after token= is a
        state name from the enum, so it can never be a credential."""
        known = {h.PERMANENT, h.EXPIRING, h.EXPIRED, h.OK, h.UNKNOWN}
        for exp in ((h.PERMANENT, None), (h.EXPIRING, 3), (h.EXPIRED, -1),
                    (h.OK, 40), (h.UNKNOWN, None)):
            rec = h.compose_record(h.OK, exp, (False, 1))
            state = rec.split("token=")[1].split()[0]
            self.assertIn(state, known, rec)


class TheDurableRecord(unittest.TestCase):

    def test_it_is_greppable_and_carries_the_verdict(self):
        rec = h.compose_record(h.DEAD, (h.EXPIRED, -1), (True, 9),
                               datetime(2026, 9, 16, 3, 40, tzinfo=timezone.utc))
        self.assertIn("probe=DEAD", rec)
        self.assertIn("token=EXPIRED", rec)
        self.assertIn("silence_alarm=True", rec)
        self.assertIn("2026-09-16T03:40:00", rec)

    def test_it_omits_days_left_when_unknown(self):
        self.assertNotIn("days_left",
                         h.compose_record(h.OK, (h.PERMANENT, None), (False, 1)))


# ══════════════════════════════════════════════════════════════════════════
# 5 · the digest integration
# ══════════════════════════════════════════════════════════════════════════

class DigestIntegration(unittest.TestCase):

    def src(self):
        return io.open(DIGEST, encoding="utf-8").read()

    def test_the_probe_is_a_READ_and_never_a_send(self):
        """Probing by messaging someone would make the health check itself
        into traffic, and a daily 'still alive' message is spam."""
        src = self.src()
        block = src[src.index("def probe_whatsapp"):src.index("def last_inbound_at")]
        self.assertIn("requests.get", block)
        self.assertNotIn("requests.post", block)
        self.assertNotIn("/messages", block)

    def test_it_rides_the_existing_cron_and_adds_no_service(self):
        src = self.src().lower()
        for banned in ("redis", "celery", "rabbit", "sqs", "kafka",
                       "new cron", "apscheduler"):
            self.assertNotIn(banned, src, banned)

    def test_the_health_block_is_best_effort_and_cannot_break_the_digest(self):
        import ast
        tree = ast.parse(self.src())
        call = None
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "compose_health_line"):
                call = n
        self.assertIsNotNone(call, "the health line is never composed")
        protected = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Try) and any(c is call for c in ast.walk(n)):
                protected = any(hh.type is None
                                or getattr(hh.type, "id", "") == "Exception"
                                for hh in n.handlers)
        self.assertTrue(protected, "a health failure could break the digest")

    def test_the_durable_write_uses_the_service_role_key(self):
        """app_settings has RLS enabled with ZERO policies — verified against
        the live database. The anon key this module reads with is denied every
        write, and using it would reproduce the silent 401 that left `leads`
        empty for weeks."""
        src = self.src()
        block = src[src.index("def record_health"):src.index("def send_to_owner")]
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", block)
        self.assertIn("if not r.ok", block, "an unchecked write is a silent one")
        self.assertNotIn("SUPABASE_KEY", block, "anon cannot write this table")

    def test_it_only_escalates_a_real_problem(self):
        """A daily 'all fine' message is how an alert channel becomes noise."""
        src = self.src()
        i = src.index("line = health.compose_health_line")
        block = src[i:i + 600]
        self.assertIn("health.DEAD", block)
        self.assertIn("silence[0]", block)
        self.assertIn("send_to_owner(line)", block)

    def test_the_verdict_is_recorded_before_it_is_sent(self):
        """The circularity: if the token is dead the alert cannot arrive, so
        the durable row must already exist."""
        src = self.src()
        self.assertLess(src.index("record_health(health.compose_record"),
                        src.index("send_to_owner(line)"))

    def test_health_module_does_no_io(self):
        import ast
        mod = io.open(os.path.join(os.path.dirname(__file__), "..",
                                   "health.py"), encoding="utf-8").read()
        imports = set()
        for n in ast.walk(ast.parse(mod)):
            if isinstance(n, ast.Import):
                imports |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imports.add((n.module or "").split(".")[0])
        self.assertEqual(imports, {"datetime"},
                         f"health.py must stay pure; got {imports}")


class NothingElseMoved(unittest.TestCase):

    def test_the_other_digest_blocks_are_intact(self):
        src = io.open(DIGEST, encoding="utf-8").read()
        for marker in ("rpc/bic_rollup_tool_invocations",
                       "bic_pipeline_evidence.record(",
                       "bic_conversion_evidence.finalize(",
                       "bic_prune_replay_records"):
            self.assertIn(marker, src, marker)

    def test_the_bairavi_layer_is_untouched(self):
        import bairavi as b
        self.assertEqual(b.CATALOGUE_KVA, (25, 63, 100, 250))
        self.assertEqual(b.PLANNED_KVA, (500,))
        self.assertEqual(b.FLOW_MARKER, "[Bairavi transformer reply]")


if __name__ == "__main__":
    unittest.main(verbosity=2)
