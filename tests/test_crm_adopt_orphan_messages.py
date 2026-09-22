"""The messages that arrive before the client row exists must be adopted.

THE DEFECT, measured 2026-09-22. In every one of that day's eight
conversations, exactly the first two messages had `client_id` NULL. One of
those two is the Meta ad form submission -- capacity, location, name and
timeline, the most information-dense message in the thread. Opening that
lead in the CRM did not show it.

WHY. The CRM links a message to a client with a BEFORE INSERT trigger that
looks the phone up in `clients`. For a brand-new lead the first message IS
what creates the lead, so it arrives before any client row exists and the
trigger has nothing to find. From the third message on, it works.

THE FIX IS BOUNDED BY CONSTRUCTION. It runs only in the branch where this
phone had no client row at all, patches only rows whose `client_id` is
already NULL, and only for that exact phone. It is therefore not a
backfill, it cannot move a message between clients, and it never touches
the one duplicated phone -- which has two client rows and goes down the
other branch, where the CRM has deliberately refused to guess an owner.

Offline: every boundary is stubbed. No network, no database.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

PHONE = "919000000000"
NEW_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else []
        self.ok = 200 <= status < 300
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class TheNewClientIdIsRead(unittest.TestCase):

    def test_a_representation_body_yields_the_id(self):
        self.assertEqual(w._crm_new_client_id(Resp(201, [{"id": NEW_ID}])),
                         NEW_ID)

    def test_a_bare_object_also_yields_the_id(self):
        self.assertEqual(w._crm_new_client_id(Resp(201, {"id": NEW_ID})),
                         NEW_ID)

    def test_an_unexpected_body_yields_none_rather_than_raising(self):
        """Creating the lead is the important half and must not fail here."""
        for body in ([], [{}], "not json", 7, None):
            with self.subTest(body=body):
                self.assertIsNone(w._crm_new_client_id(Resp(201, body)))

    def test_a_body_that_cannot_be_parsed_yields_none(self):
        class Broken:
            ok = True
            def json(self):
                raise ValueError("not json")
        self.assertIsNone(w._crm_new_client_id(Broken()))


class TheAdoptionIsNarrow(unittest.TestCase):

    def _patch_call(self, client_id=NEW_ID, phone=PHONE, status=204):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "requests") as rq:
            rq.patch.return_value = Resp(status)
            buf = io.StringIO()
            with redirect_stdout(buf):
                w._crm_adopt_orphan_messages(phone, client_id)
            return rq, buf.getvalue()

    def test_it_targets_only_unlinked_rows_for_that_phone(self):
        rq, _ = self._patch_call()
        self.assertEqual(rq.patch.call_count, 1)
        params = rq.patch.call_args.kwargs["params"]
        self.assertEqual(params["phone"], f"eq.{PHONE}")
        self.assertEqual(params["client_id"], "is.null")

    def test_it_sets_only_the_client_id(self):
        """Nothing else about a stored message may be rewritten."""
        rq, _ = self._patch_call()
        self.assertEqual(rq.patch.call_args.kwargs["json"],
                         {"client_id": NEW_ID})

    def test_it_writes_to_the_messages_table(self):
        rq, _ = self._patch_call()
        self.assertIn("/rest/v1/whatsapp_messages", rq.patch.call_args.args[0])

    def test_it_does_nothing_without_a_client_id(self):
        rq, _ = self._patch_call(client_id=None)
        self.assertEqual(rq.patch.call_count, 0)

    def test_it_does_nothing_when_the_bridge_is_unconfigured(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", ""), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", ""), \
             mock.patch.object(w, "requests") as rq:
            w._crm_adopt_orphan_messages(PHONE, NEW_ID)
            self.assertEqual(rq.patch.call_count, 0)

    def test_a_failure_is_logged_without_the_phone_number(self):
        _, out = self._patch_call(status=500)
        self.assertIn("CRM_ADOPT_FAILED", out)
        self.assertIn("status=500", out)
        self.assertNotIn(PHONE, out)
        self.assertIn(PHONE[-4:], out)

    def test_an_exception_never_escapes(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "requests") as rq:
            rq.patch.side_effect = RuntimeError("boom")
            buf = io.StringIO()
            with redirect_stdout(buf):
                w._crm_adopt_orphan_messages(PHONE, NEW_ID)
            out = buf.getvalue()
        self.assertIn("CRM_ADOPT_ERROR", out)
        self.assertNotIn(PHONE, out)
        self.assertNotIn("boom", out)


class ItRunsOnlyWhenTheClientIsCreated(unittest.TestCase):
    """The bound that makes this safe rather than a backfill."""

    def _sync(self, existing_rows):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"), \
             mock.patch.object(w, "_crm_business_id", return_value=None), \
             mock.patch.object(w, "requests") as rq:
            rq.get.return_value = Resp(200, existing_rows)
            rq.post.return_value = Resp(201, [{"id": NEW_ID}])
            rq.patch.return_value = Resp(204)
            buf = io.StringIO()
            with redirect_stdout(buf):
                w.sync_lead_to_crm(PHONE, {"name": "X", "city": "Y"})
            return rq

    def test_a_new_lead_adopts_its_opening_messages(self):
        rq = self._sync(existing_rows=[])
        self.assertEqual(rq.post.call_count, 1)
        adopt = [c for c in rq.patch.call_args_list
                 if "whatsapp_messages" in c.args[0]]
        self.assertEqual(len(adopt), 1)
        self.assertEqual(adopt[0].kwargs["json"], {"client_id": NEW_ID})

    def test_an_existing_lead_adopts_nothing(self):
        """The duplicated phone lives here -- two client rows, 1,308 unlinked
        messages, and a CRM that has refused to guess an owner. This path
        must not guess either."""
        rq = self._sync(existing_rows=[{"id": "old-id", "notes": "",
                                        "business_id": None}])
        self.assertEqual(rq.post.call_count, 0)
        adopt = [c for c in rq.patch.call_args_list
                 if "whatsapp_messages" in c.args[0]]
        self.assertEqual(adopt, [])

    def test_a_failed_create_adopts_nothing(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"), \
             mock.patch.object(w, "_crm_business_id", return_value=None), \
             mock.patch.object(w, "requests") as rq:
            rq.get.return_value = Resp(200, [])
            rq.post.return_value = Resp(500, {"message": "nope"})
            buf = io.StringIO()
            with redirect_stdout(buf):
                w.sync_lead_to_crm(PHONE, {"name": "X"})
            adopt = [c for c in rq.patch.call_args_list
                     if "whatsapp_messages" in c.args[0]]
        self.assertEqual(adopt, [])

    def test_a_failed_create_is_not_trusted_even_if_it_echoes_a_row(self):
        """The status is the authority, not the body.

        Found by mutation: removing the `else:` guard changed nothing,
        because a PostgREST error body carries no id and the extractor
        returned None anyway. That made the guard untested rather than
        unnecessary -- a non-2xx response that happens to echo a row must
        still adopt nothing, or a rejected create could relabel messages.
        """
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.example"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "k"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner"), \
             mock.patch.object(w, "_crm_business_id", return_value=None), \
             mock.patch.object(w, "requests") as rq:
            rq.get.return_value = Resp(200, [])
            rq.post.return_value = Resp(409, [{"id": NEW_ID}])
            buf = io.StringIO()
            with redirect_stdout(buf):
                w.sync_lead_to_crm(PHONE, {"name": "X"})
            adopt = [c for c in rq.patch.call_args_list
                     if "whatsapp_messages" in c.args[0]]
        self.assertEqual(adopt, [])

    def test_the_create_asks_for_the_row_back(self):
        """return=minimal gives no id, and without the id there is nothing to
        adopt with."""
        rq = self._sync(existing_rows=[])
        self.assertEqual(
            rq.post.call_args.kwargs["headers"]["Prefer"], "return=representation")


class NoSchemaChangeAndNoMigration(unittest.TestCase):

    def test_no_new_migration_was_added(self):
        root = os.path.join(os.path.dirname(__file__), "..", "supabase",
                            "migrations")
        if not os.path.isdir(root):
            self.skipTest("no migrations directory")
        for name in os.listdir(root):
            self.assertNotIn("adopt", name.lower())
            self.assertNotIn("orphan", name.lower())

    def test_the_fix_issues_no_ddl(self):
        """EXECUTABLE CODE ONLY.

        A first version scanned the raw source and failed on the word
        "trigger" in this function's own docstring, which explains the CRM
        trigger the fix works around. Comments and string literals are
        stripped with `tokenize` so the assertion is about what the code
        DOES, not about what the prose mentions.
        """
        import inspect
        import tokenize
        import io as _io
        src = inspect.getsource(w._crm_adopt_orphan_messages)
        code = " ".join(
            tok.string for tok in tokenize.generate_tokens(
                _io.StringIO(src).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)).lower()
        for ddl in ("create", "alter", "drop", "trigger", "execute"):
            with self.subTest(ddl=ddl):
                self.assertNotIn(ddl, code)

    def test_it_is_a_patch_and_never_a_delete_or_insert(self):
        """One verb, on one table, setting one column."""
        import inspect
        src = inspect.getsource(w._crm_adopt_orphan_messages)
        self.assertIn("requests.patch(", src)
        for verb in ("requests.post(", "requests.delete(", "requests.put("):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, src)


if __name__ == "__main__":
    unittest.main()
