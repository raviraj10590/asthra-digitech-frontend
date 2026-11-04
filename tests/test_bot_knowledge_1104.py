"""Owner, 2026-11-04 ("1,2,3 maadu", item 2): prices and service facts live in
the CRM's bot_knowledge table, edited by the owner, read by the bot at reply
time (cached five minutes) and placed right after the static prompt."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")

import asthra_deal as d  # noqa: E402
import webhook as w  # noqa: E402

ROWS = [{"topic": "AI WhatsApp bot", "body": "Setup ₹9,999 one time + ₹1,499 a month."},
        {"topic": "Website", "body": "From  ₹3,000.\nFinal price on requirement."}]


class KnowledgeBlock(unittest.TestCase):
    def test_rows_become_one_block_that_wins(self):
        b = d.knowledge_block(ROWS)
        self.assertIn("• AI WhatsApp bot: Setup ₹9,999 one time + ₹1,499 a month.", b)
        self.assertIn("• Website: From ₹3,000. Final price on requirement.", b)
        self.assertIn("THIS wins", b)
        self.assertIn("Never mention GST", b)

    def test_empty_rows_no_block(self):
        self.assertEqual(d.knowledge_block([]), "")
        self.assertEqual(d.knowledge_block([{"topic": " ", "body": "x"}]), "")


class FetchKnowledge(unittest.TestCase):
    def setUp(self):
        w._knowledge_cache.clear()
        p = mock.patch.multiple(w, CRM_SUPABASE_URL="https://crm.example", CRM_SUPABASE_SERVICE_KEY="k")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: w._knowledge_cache.clear())

    def resp(self, rows, ok=True):
        r = mock.Mock(ok=ok)
        r.json.return_value = rows
        return r

    def test_reads_active_asthra_rows_and_caches(self):
        with mock.patch.object(w.requests, "get", return_value=self.resp(ROWS)) as get, \
             mock.patch.object(w, "ai_seconds_left", return_value=60):
            self.assertEqual(w.fetch_knowledge(), ROWS)
            self.assertEqual(w.fetch_knowledge(), ROWS)
        self.assertEqual(get.call_count, 1)                      # second call from cache
        params = get.call_args[1]["params"]
        self.assertEqual((params["business"], params["active"]), ("eq.asthra", "is.true"))
        self.assertTrue(get.call_args[0][0].endswith("/rest/v1/bot_knowledge"))

    def test_a_failed_read_keeps_the_last_good_rows(self):
        w._knowledge_cache["asthra"] = {"at": 1.0, "rows": ROWS}  # stale, so it re-reads
        with mock.patch.object(w.requests, "get", side_effect=OSError("down")), \
             mock.patch.object(w, "ai_seconds_left", return_value=60), \
             mock.patch.object(w.time, "monotonic", return_value=10_000.0):
            self.assertEqual(w.fetch_knowledge(), ROWS)

    def test_no_crm_config_no_read(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", ""), mock.patch.object(w.requests, "get") as get:
            self.assertEqual(w.fetch_knowledge(), [])
            get.assert_not_called()

    def test_the_block_reaches_the_model_after_the_prompt(self):
        seen = {}

        def ai(messages, fallback, **_):
            seen["m"] = messages
            return "ಸರಿ sir"
        with mock.patch.object(w, "fetch_knowledge", return_value=ROWS), \
             mock.patch.object(w, "fetch_customer_said", return_value=([], False)), \
             mock.patch.object(w, "fetch_team_sent", return_value=[]), \
             mock.patch.object(w, "_generate_ai_reply", side_effect=ai):
            w.generate_reply("910000000000", "bot eshtu?", history=[])
        self.assertEqual(seen["m"][0]["content"], w.SYSTEM_PROMPT)
        self.assertIn("OWNER'S LATEST KNOWLEDGE", seen["m"][1]["content"])


if __name__ == "__main__":
    unittest.main()
