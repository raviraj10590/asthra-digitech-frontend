"""Owner CRM phase 2 (#fu #done #note #stage behind #confirm) and auto-suggest
(the bot learns the owner's own answers, only with his #learn). 2026-11-02."""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import learned as L          # noqa: E402
import owner_writes as ow    # noqa: E402

TODAY = date(2026, 11, 2)


class Phase2Parse(unittest.TestCase):
    def test_followups(self):
        self.assertEqual(ow.parse("#fu 4521 naale call for quote", TODAY),
                         (ow.FOLLOWUP, "4521", {"due": "2026-11-03", "note": "call for quote"}))
        self.assertEqual(ow.parse("#fu 4521 3 days", TODAY)[2]["due"], "2026-11-05")
        self.assertEqual(ow.parse("#fu 4521 15 nov site visit", TODAY)[2],
                         {"due": "2026-11-15", "note": "site visit"})
        self.assertEqual(ow.parse("#fu 4521 nov 15", TODAY)[2]["due"], "2026-11-15")
        self.assertEqual(ow.parse("#fu 4521 2026-12-01", TODAY)[2]["due"], "2026-12-01")
        self.assertEqual(ow.parse("#fu 4521 10 jan", TODAY)[2]["due"], "2027-01-10")
        self.assertEqual(ow.parse("#followup 4521 next week", TODAY)[2]["due"], "2026-11-09")

    def test_others(self):
        self.assertEqual(ow.parse("#done 4521", TODAY), (ow.DONE, "4521", {}))
        self.assertEqual(ow.parse("#note 4521 site visit Monday", TODAY),
                         (ow.NOTE, "4521", {"note": "site visit Monday"}))
        self.assertEqual(ow.parse("#stage 4521 won", TODAY), (ow.STAGE, "4521", {"stage": "Won"}))
        self.assertEqual(ow.parse("#stage 4521 site visit", TODAY)[2], {"stage": "Site Visit"})

    def test_wrong_use_gets_usage(self):
        for t in ("#fu 4521", "#fu 4521 someday", "#note 4521", "#stage 4521 maybe", "#fu", "#done"):
            with self.subTest(t=t):
                self.assertEqual(ow.parse(t, TODAY)[0], "usage")

    def test_not_a_phase2_command(self):
        for t in ("#today", "5711 called interested", "#price 4521 1000", "fu 4521 naale"):
            with self.subTest(t=t):
                self.assertIsNone(ow.parse(t, TODAY))

    def test_prompt_names_the_lead(self):
        lead = {"name": "Ravi", "phone": "919876544521", "pipeline_stage": "Interested"}
        self.assertIn("Ravi (…4521)", ow.confirm_prompt(ow.STAGE, lead, {"stage": "Won"}))
        self.assertIn("15 Nov 2026", ow.confirm_prompt(ow.FOLLOWUP, lead, {"due": "2026-11-15", "note": ""}))


class Phase2Wiring(unittest.TestCase):
    def test_a_write_is_staged_not_written(self):
        import webhook as w
        lead = {"id": "L1", "name": "Ravi", "phone": "919876544521", "notes": "", "pipeline_stage": "Lead"}
        with mock.patch.object(w, "CRM_SUPABASE_URL", "x"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "x"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "u"), \
             mock.patch.object(w, "_crm_leads_ending", return_value=[lead]), \
             mock.patch.object(w, "save_message") as sm, \
             mock.patch.object(w.requests, "patch") as patch, \
             mock.patch.object(w.requests, "post") as post:
            out = w.handle_owner_text("918861369951", "OWNER", "Owner", "#stage 4521 won",
                                      {"history": [], "recent_sys": []})
        self.assertIn("#confirm", out)
        self.assertIn("Ravi", out)
        self.assertTrue(sm.call_args[0][2].startswith("PENDING_CONFIRM::"))
        self.assertIn("crm_owner_write", sm.call_args[0][2])
        patch.assert_not_called()
        post.assert_not_called()

    def test_staff_cannot_stage(self):
        import webhook as w
        out = w._stage_owner_write("91x", "STAFF", ow.NOTE, "4521", {"note": "x"})
        self.assertIn("Only OWNER", out)


def msg(direction, body, minutes, source=None, mid=None):
    t = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return {"id": mid or f"m{minutes}", "phone": "919876544779", "direction": direction,
            "body": body, "created_at": t, "source": source, "message_type": "text"}


class Detector(unittest.TestCase):
    def test_the_owner_answer_to_a_question(self):
        got = L.pairs([msg("inbound", "Kk matte enadru extra fees barutta", 0),
                       msg("outbound", "transformer price idu plus kamba wire separate irutte", 2)])
        self.assertEqual(len(got), 1)

    def test_bot_replies_acks_and_junk_are_not_offered(self):
        self.assertEqual(L.pairs([msg("inbound", "gst estu aagutte", 0),
                                  msg("outbound", "GST 18% extra sir", 1, source="asthra_ai_bot")]), [])
        self.assertEqual(L.pairs([msg("inbound", "Means", 0),
                                  msg("outbound", "best rating transformers idu", 1)]), [])
        self.assertEqual(L.pairs([msg("inbound", "Nimma company estu varshadinda ide", 0),
                                  msg("outbound", "sk-nry-Hz... Transient 502 from the file API", 1)]), [])
        self.assertEqual(L.pairs([msg("inbound", "price eshtu", 0),
                                  msg("outbound", "nimma jille yavudu?", 1)]), [])

    def test_too_late_is_not_an_answer(self):
        self.assertEqual(L.pairs([msg("inbound", "price eshtu", 0),
                                  msg("outbound", "25 kva 85,000 plus gst", 300)]), [])

    def test_suggestion_names_the_commands(self):
        t = L.suggestion_text({"id": 12, "business": "bairavi", "question": "q", "answer": "a"})
        self.assertIn("#learn 12", t)
        self.assertIn("#skip 12", t)


class Commands(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(L.parse_command("#learn 12"), ("learn", 12, ""))
        self.assertEqual(L.parse_command("#learn #12 3 dina-alli barutte"), ("learn", 12, "3 dina-alli barutte"))
        self.assertEqual(L.parse_command("#skip 12"), ("skip", 12, ""))
        self.assertEqual(L.parse_command("#unlearn 3"), ("unlearn", 3, ""))
        self.assertEqual(L.parse_command("#learned"), ("list", None, ""))
        self.assertEqual(L.parse_command("#learn"), ("usage", None, ""))
        self.assertIsNone(L.parse_command("#leads"))


APPROVED = [{"id": 1, "business": "bairavi", "question": "Kk matte enadru extra fees barutta",
             "answer": "Kamba, wire, installation separate."},
            {"id": 2, "business": "bairavi", "question": "Mysore ge delivery eshtu dina",
             "answer": "3 dina-alli barutte."}]


class Matching(unittest.TestCase):
    def test_same_question_in_other_words(self):
        self.assertEqual(L.best_match("sir extra fees enadru barutta", APPROVED)["id"], 1)
        self.assertEqual(L.best_match("mysore ge delivery ge eshtu dina aagutte", APPROVED)["id"], 2)

    def test_a_different_question_does_not_match(self):
        for t in ("delivery", "subsidy ide na", "100 kva price eshtu sir please tell me today", "hi"):
            with self.subTest(t=t):
                self.assertIsNone(L.best_match(t, APPROVED))

    def test_prompt_block_only_asthra(self):
        self.assertEqual(L.prompt_block(APPROVED), "")
        block = L.prompt_block([{"business": "asthra", "question": "logo eshtu", "answer": "₹2,000 inda"}])
        self.assertIn("₹2,000", block)


class AsthraPromptUsesThem(unittest.TestCase):
    def test_generate_reply_carries_approved_answers(self):
        import webhook as w
        seen = {}
        def fake(messages, *a, **k):
            seen["m"] = messages
            return "ok"
        with mock.patch.object(w, "approved_answers",
                               return_value=[{"business": "asthra", "question": "logo eshtu",
                                              "answer": "₹2,000 inda"}]), \
             mock.patch.object(w, "_generate_ai_reply", side_effect=fake):
            w.generate_reply("91x", "logo eshtu", history=[])
        self.assertTrue(any("₹2,000 inda" in m["content"] for m in seen["m"] if m["role"] == "system"))


if __name__ == "__main__":
    unittest.main()


class OnlyTheBotsOwnBusinesses(unittest.TestCase):
    """Owner 2026-11-02: another client's chats are never learned from."""

    def _api(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "nudge_api", os.path.join(os.path.dirname(__file__), "..", "api", "nudge.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _resp(self, data):
        r = mock.Mock(ok=True)
        r.json.return_value = data
        r.raise_for_status.return_value = None
        return r

    def run_with(self, clients, slugs, flow=False):
        n = self._api()
        def get(url, **k):
            if url.endswith("/clients"):
                return self._resp(clients)
            if url.endswith("/businesses"):
                return self._resp([{"slug": s} for s in slugs])
            return self._resp([{"id": 1}] if flow else [])
        with mock.patch.object(n.requests, "get", side_effect=get):
            return n._business_of("919876544779", "https://crm", {})

    def test_another_client_is_skipped(self):
        self.assertIsNone(self.run_with([{"business_id": "x", "source": None}], ["sgr-navanagara"]))

    def test_bairavi_and_asthra(self):
        self.assertEqual(self.run_with([{"business_id": "b", "source": "bairavi-transformer"}],
                                       ["bairavi-trans-solutions"]), L.BAIRAVI)
        self.assertEqual(self.run_with([], []), L.ASTHRA)
        self.assertEqual(self.run_with([], [], flow=True), L.BAIRAVI)

    def test_unreadable_is_skipped(self):
        n = self._api()
        with mock.patch.object(n.requests, "get", side_effect=RuntimeError("down")):
            self.assertIsNone(n._business_of("91x", "https://crm", {}))
