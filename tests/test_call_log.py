"""Owner call outcomes typed on WhatsApp (owner request 2026-09-30)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import call_log as c  # noqa: E402
import webhook as w  # noqa: E402


NOT_PARSED = object()


class Parse(unittest.TestCase):
    def test_outcomes(self):
        for text, stage in (
            ("5711 called interested", c.INTERESTED),
            ("2829 lost price", c.LOST),
            ("2829 called, not interested", c.LOST),
            ("3554 no answer", c.NO_ANSWER),
            ("3554 not picking", c.NO_ANSWER),
            ("4028 quote sent", c.NEGOTIATION),
            ("1743 site visit tomorrow", c.SITE_VISIT),
            ("4109 order confirmed", c.WON),
            ("4109 advance paid", c.WON),
            ("0440 called", c.CONTACTED),
            ("0440 call later", c.CONTACTED),
            ("919742662829 lost", c.LOST),
            ("4109 border area", NOT_PARSED),       # "order" inside "border" is not an order
            ("+91 5711 interested", NOT_PARSED),    # a space inside the number
        ):
            p = c.parse(text)
            if stage is NOT_PARSED:
                self.assertIsNone(p, text)
                continue
            self.assertIsNotNone(p, text)
            self.assertEqual(p[1], stage, text)

    def test_not_an_outcome(self):
        for text in ("hello", "#leads", "5711", "9845 ge message madi", "how many leads today",
                     "2026 sales report", "25 kva price", "5711 advance kodtini anta helidru"):
            self.assertIsNone(c.parse(text), text)

    def test_the_owners_words_are_kept(self):
        self.assertEqual(c.parse("2829 lost price too high")[2], "lost price too high")


LEAD = {"id": "u1", "name": "Sudarshan Gowda", "phone": "918431945711",
        "notes": "Service: transformer", "pipeline_stage": "Lead"}


class ThroughTheOwnerHandler(unittest.TestCase):
    def run_owner(self, text, rows, patch_ok=True):
        calls = {"patch": []}

        class R:
            def __init__(self, data=None, ok=True):
                self._d, self.ok, self.status_code = data, ok, 200 if ok else 500
            def json(self): return self._d
            def raise_for_status(self):
                if not self.ok: raise RuntimeError("http")

        def get(url, **k):
            self.assertIn("/rest/v1/clients", url)
            return R(rows)

        def patch(url, **k):
            calls["patch"].append(k)
            return R(ok=patch_ok)

        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"), \
             mock.patch.object(w.requests, "get", get), \
             mock.patch.object(w.requests, "patch", patch), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None), \
             mock.patch.object(w, "_bic_enabled", lambda: False):
            out = w.handle_owner_text("918861369951", "OWNER", "Owner", text, {})
        return out, calls["patch"]

    def test_interested(self):
        out, patches = self.run_owner("5711 called interested", [LEAD])
        self.assertEqual(out, "✅ Sudarshan Gowda (…5711) → *Interested*")
        body = patches[0]["json"]
        self.assertEqual(body["pipeline_stage"], "Interested")
        self.assertIn("last_contacted_at", body)
        self.assertTrue(body["notes"].startswith("Service: transformer\n🔥 "))
        self.assertIn("call: Interested — called interested", body["notes"])
        self.assertEqual(patches[0]["params"], {"id": "eq.u1"})

    def test_no_answer_keeps_the_stage(self):
        out, patches = self.run_owner("5711 no answer", [LEAD])
        self.assertIn("no answer noted", out)
        body = patches[0]["json"]
        self.assertNotIn("pipeline_stage", body)
        self.assertNotIn("last_contacted_at", body)
        self.assertIn("📵", body["notes"])

    def test_two_leads_match(self):
        other = dict(LEAD, id="u2", name="Other", phone="919000005711")
        out, patches = self.run_owner("5711 lost", [LEAD, other])
        self.assertIn("2 leads end with 5711", out)
        self.assertEqual(patches, [])

    def test_none_match(self):
        out, patches = self.run_owner("5711 lost", [])
        self.assertIn("No lead in the CRM ends with 5711", out)
        self.assertEqual(patches, [])

    def test_the_database_like_match_is_rechecked(self):
        """PostgREST 'like *5711' is trusted only after an endswith check."""
        stray = dict(LEAD, phone="915711000000")
        out, patches = self.run_owner("5711 lost", [stray])
        self.assertIn("No lead", out)

    def test_save_failure_is_reported(self):
        out, _ = self.run_owner("5711 interested", [LEAD], patch_ok=False)
        self.assertIn("Could not save", out)

    def test_other_owner_messages_are_untouched(self):
        with mock.patch.object(w, "tool_call_outcome", side_effect=AssertionError("called")), \
             mock.patch.object(w, "_find_pending_confirm", lambda ctx: None):
            self.assertIn("Owner/staff commands", w.handle_owner_text("9", "OWNER", "O", "#help", {}))


if __name__ == "__main__":
    unittest.main()
