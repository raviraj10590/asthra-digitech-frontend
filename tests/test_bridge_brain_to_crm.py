"""The Brain → CRM bridge must stop losing identity.

WHAT IT LOST
------------
`sync_lead_to_crm` sent name, phone and notes. `log_reply_to_crm` sent the
message body. Four things were dropped on the floor:

  business identity   the Bairavi branch records source='bairavi-transformer';
                      the bridge folded notes from service/budget/city only and
                      `clients` had no column for it. The word "Bairavi"
                      appeared zero times in the entire CRM codebase.
  lead source         same reason.
  wa_message_id       already in the send response at the call site, discarded.
                      1,239 delivery receipts became orphan_status dead letters
                      because Meta reported on an id the CRM never stored.
  client_id           1,852 of 1,997 CRM messages have none.

THE DATABASES STAY SEPARATE. Nothing here creates a cross-database foreign
key, and no CRM uuid is configured in the Brain: the Brain sends a slug it
already knows and the CRM resolves it over RPC, or refuses.

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
BAIRAVI_ID = "11111111-2222-3333-4444-555555555555"
ASTHRA_ID = "99999999-8888-7777-6666-555555555555"


class Resp:
    """Minimal stand-in for a requests Response."""

    def __init__(self, code=200, body=None):
        self.status_code = code
        self.ok = 200 <= code < 300
        self._body = body if body is not None else []
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def crm_env(fn):
    """Run with CRM credentials configured, since every write is gated on
    them being present."""
    def wrapper(*a, **k):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner-uuid"):
            return fn(*a, **k)
    return wrapper


# ══════════════════════════════════════════════════════════════════════════
# GOAL 1 · BUSINESS IDENTITY — resolved by the CRM, never configured here
# ══════════════════════════════════════════════════════════════════════════

class TheBrainSendsASlugNotAUuid(unittest.TestCase):

    def test_no_crm_uuid_is_configured_in_the_brain(self):
        """A CRM primary key in Brain configuration would be wrong in every
        other environment and need a redeploy to change."""
        for slug in w.CRM_BUSINESS_SLUG_BY_SOURCE.values():
            self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$", slug)
            self.assertNotRegex(
                slug, r"[0-9a-f]{8}-[0-9a-f]{4}-", "a uuid is not a slug")

    def test_the_bairavi_source_maps_to_the_bairavi_slug(self):
        self.assertEqual(
            w.CRM_BUSINESS_SLUG_BY_SOURCE["bairavi-transformer"],
            "bairavi-trans-solutions")

    def test_the_default_whatsapp_source_maps_to_asthra(self):
        """leads.source defaults to 'whatsapp' in the Brain's own schema."""
        self.assertEqual(
            w.CRM_BUSINESS_SLUG_BY_SOURCE["whatsapp"], "asthra-digitech")

    @crm_env
    def test_a_known_source_is_resolved_by_the_CRM(self):
        seen = {}

        def fake_post(url, **kw):
            seen["url"] = url
            seen["slug"] = kw["json"]["p_slug"]
            return Resp(200, BAIRAVI_ID)

        with mock.patch.object(w.requests, "post", fake_post), \
             redirect_stdout(io.StringIO()):
            got = w._crm_business_id("bairavi-transformer")

        self.assertEqual(got, BAIRAVI_ID)
        self.assertIn("/rpc/business_id_for_slug", seen["url"])
        self.assertEqual(seen["slug"], "bairavi-trans-solutions")

    @crm_env
    def test_an_unmapped_source_sends_no_slug_and_claims_no_business(self):
        """NOT a default tenant. Unassigned, and said out loud."""
        called = []
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: called.append(1)), \
             redirect_stdout(io.StringIO()) as out:
            self.assertIsNone(w._crm_business_id("some-new-campaign"))
        self.assertEqual(called, [], "it asked the CRM about an unmapped source")
        self.assertIn("CRM_BUSINESS_SLUG_UNMAPPED", out.getvalue())

    @crm_env
    def test_a_rejected_slug_claims_no_business(self):
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: Resp(400, {"message": "unknown"})), \
             redirect_stdout(io.StringIO()) as out:
            self.assertIsNone(w._crm_business_id("bairavi-transformer"))
        self.assertIn("CRM_BUSINESS_SLUG_REJECTED", out.getvalue())

    @crm_env
    def test_a_transport_failure_claims_no_business(self):
        def boom(*a, **k):
            raise TimeoutError("slow")
        with mock.patch.object(w.requests, "post", boom), \
             redirect_stdout(io.StringIO()) as out:
            self.assertIsNone(w._crm_business_id("bairavi-transformer"))
        self.assertIn("CRM_BUSINESS_SLUG_LOOKUP_FAILED", out.getvalue())

    def test_no_credentials_means_no_lookup_and_no_business(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", ""), \
             redirect_stdout(io.StringIO()):
            self.assertIsNone(w._crm_business_id("bairavi-transformer"))

    @crm_env
    def test_a_missing_or_blank_source_is_not_looked_up(self):
        called = []
        with mock.patch.object(w.requests, "post",
                               lambda *a, **k: called.append(1)), \
             redirect_stdout(io.StringIO()):
            for src in (None, "", "   "):
                self.assertIsNone(w._crm_business_id(src))
        self.assertEqual(called, [])


# ══════════════════════════════════════════════════════════════════════════
# GOAL 5 · TENANT ISOLATION
# ══════════════════════════════════════════════════════════════════════════

class ABairaviLeadNeverLandsInAnotherBusiness(unittest.TestCase):

    def sync(self, data, resolved=BAIRAVI_ID, existing=None):
        """Run sync_lead_to_crm and return the row it would have written."""
        wrote = {}

        def fake_get(url, **kw):
            return Resp(200, existing or [])

        def fake_post(url, **kw):
            if "/rpc/business_id_for_slug" in url:
                return Resp(200, resolved) if resolved else Resp(400, {})
            wrote["insert"] = kw["json"]
            return Resp(201)

        def fake_patch(url, **kw):
            wrote["patch"] = kw["json"]
            return Resp(204)

        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner-uuid"), \
             mock.patch.object(w.requests, "get", fake_get), \
             mock.patch.object(w.requests, "post", fake_post), \
             mock.patch.object(w.requests, "patch", fake_patch), \
             redirect_stdout(io.StringIO()):
            w.sync_lead_to_crm(PHONE, data)
        return wrote

    def test_a_bairavi_lead_carries_the_bairavi_business(self):
        row = self.sync({"source": "bairavi-transformer", "name": "X"})
        self.assertEqual(row["insert"]["business_id"], BAIRAVI_ID)
        self.assertEqual(row["insert"]["source"], "bairavi-transformer")

    def test_an_asthra_lead_carries_the_asthra_business(self):
        row = self.sync({"source": "whatsapp", "name": "X"}, resolved=ASTHRA_ID)
        self.assertEqual(row["insert"]["business_id"], ASTHRA_ID)
        self.assertEqual(row["insert"]["source"], "whatsapp")

    def test_a_rejected_slug_writes_the_lead_with_NO_business(self):
        """The lead is still captured — losing it would be worse — but it is
        unassigned and visible as such, never defaulted."""
        row = self.sync({"source": "bairavi-transformer", "name": "X"},
                        resolved=None)
        self.assertNotIn("business_id", row["insert"])
        self.assertEqual(row["insert"]["source"], "bairavi-transformer")

    def test_an_unmapped_source_writes_no_business(self):
        row = self.sync({"source": "mystery", "name": "X"}, resolved=None)
        self.assertNotIn("business_id", row["insert"])

    def test_a_business_the_CRM_already_decided_is_never_overwritten(self):
        """A human may have assigned it. The Brain's mapping does not outrank
        that."""
        row = self.sync({"source": "bairavi-transformer", "name": "X"},
                        existing=[{"id": "c1", "notes": "",
                                   "business_id": ASTHRA_ID}])
        self.assertNotIn("business_id", row.get("patch", {}))

    def test_an_unassigned_existing_lead_DOES_gain_the_business(self):
        row = self.sync({"source": "bairavi-transformer", "name": "X"},
                        existing=[{"id": "c1", "notes": "",
                                   "business_id": None}])
        self.assertEqual(row["patch"]["business_id"], BAIRAVI_ID)

    def test_an_existing_lead_gains_the_source(self):
        row = self.sync({"source": "bairavi-transformer", "name": "X"},
                        existing=[{"id": "c1", "notes": "",
                                   "business_id": None}])
        self.assertEqual(row["patch"]["source"], "bairavi-transformer")


# ══════════════════════════════════════════════════════════════════════════
# GOAL 3 · WHATSAPP MESSAGE IDENTITY
# ══════════════════════════════════════════════════════════════════════════

class TheMirrorCarriesTheMessagesOwnId(unittest.TestCase):

    def mirror(self, wamid=None):
        sent = {}

        def fake_post(url, **kw):
            sent["json"] = kw["json"]
            sent["params"] = kw.get("params") or {}
            sent["prefer"] = kw["headers"].get("Prefer", "")
            return Resp(201)

        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "owner-uuid"), \
             mock.patch.object(w.requests, "post", fake_post), \
             redirect_stdout(io.StringIO()):
            w.log_reply_to_crm(PHONE, "hello", wamid)
        return sent

    def test_the_id_reaches_the_crm(self):
        s = self.mirror("wamid.ABC123")
        self.assertEqual(s["json"]["wa_message_id"], "wamid.ABC123")

    def test_it_NEVER_asks_postgrest_to_resolve_the_conflict(self):
        """THE REGRESSION THIS CAUSED IN PRODUCTION.

        Asking for on_conflict=wa_message_id broke every mirror write:
        idx_wa_messages_wa_id is a PARTIAL unique index
        (WHERE wa_message_id IS NOT NULL), and Postgres rejects a partial
        index as an ON CONFLICT inference target unless the statement repeats
        the predicate — which the PostgREST parameter cannot express. Inserts
        failed with 42P10, replies were sent and never recorded, and Meta's
        receipts orphaned into the dead-letter queue.

        Idempotency is still ENFORCED by the index; it is simply not absorbed.
        """
        for wamid in ("wamid.ABC123", None):
            s = self.mirror(wamid)
            self.assertEqual(s["params"], {}, wamid)
            self.assertNotIn("merge-duplicates", s["prefer"], wamid)
            self.assertNotIn("on_conflict", s["prefer"], wamid)

    def test_without_an_id_the_field_is_omitted_entirely(self):
        s = self.mirror(None)
        self.assertNotIn("wa_message_id", s["json"])

    def test_client_id_is_deliberately_NOT_sent(self):
        """The Brain does not know the CRM's ids; the CRM links it on insert.
        Fetching one here would add a round trip to the reply path."""
        s = self.mirror("wamid.ABC123")
        self.assertNotIn("client_id", s["json"])

    def test_the_row_still_claims_outbound_sent(self):
        s = self.mirror("wamid.X")
        self.assertEqual(s["json"]["direction"], "outbound")
        self.assertEqual(s["json"]["status"], "sent")


class SendTextExtractsTheIdItAlreadyHas(unittest.TestCase):

    def send(self, response):
        got = {}
        with mock.patch.object(w, "_wa_post", lambda p: response), \
             mock.patch.object(w, "get_role", lambda to: ("CLIENT", None)), \
             mock.patch.object(w, "log_reply_to_crm",
                               lambda p, b, wamid=None: got.update(wamid=wamid)), \
             redirect_stdout(io.StringIO()):
            w.send_text(PHONE, "hi")
        return got.get("wamid")

    def test_it_reads_the_id_from_metas_response(self):
        self.assertEqual(
            self.send(Resp(200, {"messages": [{"id": "wamid.FROM_META"}]})),
            "wamid.FROM_META")

    def test_a_rejected_send_mirrors_without_an_id(self):
        """The attempt is still recorded — that is what makes a failed send
        visible — but nothing is invented for it."""
        self.assertIsNone(self.send(Resp(401, {"error": {}})))

    def test_an_error_response_body_is_not_trusted_for_an_id(self):
        """A non-2xx means the message was not accepted. Reading an id out of
        an error body would record a wa_message_id for a message that was
        never sent — and the unique index would then block the real one."""
        self.assertIsNone(
            self.send(Resp(400, {"messages": [{"id": "wamid.NOT_SENT"}]})))

    def test_a_malformed_response_does_not_break_the_reply(self):
        for body in ({}, {"messages": []}, {"messages": [{}]}, None, "junk"):
            self.assertIsNone(self.send(Resp(200, body)))

    def test_a_response_object_without_ok_does_not_break_the_reply(self):
        self.assertIsNone(self.send({"not": "a response"}))

    def test_owner_replies_are_still_never_mirrored(self):
        called = []
        with mock.patch.object(w, "_wa_post",
                               lambda p: Resp(200, {"messages": [{"id": "x"}]})), \
             mock.patch.object(w, "get_role", lambda to: ("OWNER", None)), \
             mock.patch.object(w, "log_reply_to_crm",
                               lambda *a, **k: called.append(1)), \
             redirect_stdout(io.StringIO()):
            w.send_text(PHONE, "internal")
        self.assertEqual(called, [])


# ══════════════════════════════════════════════════════════════════════════
# GOAL 4 · LEAD SYNC — one identity, unchanged semantics
# ══════════════════════════════════════════════════════════════════════════

class TheLeadIdentityIsNotDuplicated(unittest.TestCase):

    def test_the_brain_still_upserts_on_phone_only(self):
        """leads_phone_key is UNIQUE (phone), so merge-duplicates is
        constraint-backed. No second identity is introduced."""
        import inspect
        src = inspect.getsource(w.upsert_lead)
        self.assertIn("resolution=merge-duplicates", src)
        self.assertIn('"phone": phone', src)

    def test_the_crm_lookup_is_still_phone_plus_owner(self):
        import inspect
        src = inspect.getsource(w.sync_lead_to_crm)
        self.assertIn('"phone": f"eq.{phone}"', src)
        self.assertIn('"user_id": f"eq.{CRM_OWNER_USER_ID}"', src)

    def test_the_lookup_reads_business_id_or_overwrite_protection_is_dead(self):
        """The no-overwrite rule tests `rows[0].get("business_id")`. If the
        SELECT stops asking for the column, that read is always None and the
        rule silently inverts — a human's assignment would be overwritten by
        the Brain's mapping."""
        import inspect
        src = inspect.getsource(w.sync_lead_to_crm)
        self.assertIn("business_id", src.split('"select"')[1].split("}")[0])

    def test_no_new_lead_key_is_invented(self):
        import inspect
        src = inspect.getsource(w.sync_lead_to_crm)
        for invented in ("lead_uid", "external_id", "brain_lead_id",
                         "crm_lead_key"):
            self.assertNotIn(invented, src)

    def test_brain_lead_status_semantics_are_untouched(self):
        import inspect
        src = inspect.getsource(w.sync_lead_to_crm) + \
            inspect.getsource(w.upsert_lead)
        self.assertNotIn('"status"', src)
        self.assertNotIn("pipeline_stage", src)

    def test_no_payment_field_is_introduced(self):
        import inspect
        src = (inspect.getsource(w.sync_lead_to_crm)
               + inspect.getsource(w.log_reply_to_crm)
               + inspect.getsource(w._crm_business_id))
        for banned in ("paid", "payment", "became_client", "first_payment"):
            self.assertNotIn(banned, src.lower())


# ══════════════════════════════════════════════════════════════════════════
# PRIVACY · the bridge must not start logging customers
# ══════════════════════════════════════════════════════════════════════════

class TheBridgeLogsNoPII(unittest.TestCase):

    def test_the_slug_resolver_logs_only_slug_and_status(self):
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w.requests, "post",
                               lambda *a, **k: Resp(400, {"message": "x"})), \
             redirect_stdout(io.StringIO()) as out:
            w._crm_business_id("bairavi-transformer")
        line = out.getvalue()
        self.assertIn("status=400", line)
        self.assertNotIn(PHONE, line)
        self.assertNotIn("svc", line)

    def test_no_response_body_is_logged_by_the_resolver(self):
        import inspect
        src = inspect.getsource(w._crm_business_id)
        self.assertNotIn("r.text", src)

    def test_the_mirror_never_logs_the_message_body(self):
        def fake_post(url, **kw):
            return Resp(400, {"message": "rejected"})
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "o"), \
             mock.patch.object(w.requests, "post", fake_post), \
             redirect_stdout(io.StringIO()) as out:
            w.log_reply_to_crm(PHONE, "SECRET CUSTOMER TEXT", "wamid.X")
        line = out.getvalue()
        self.assertNotIn("SECRET CUSTOMER TEXT", line)
        # And the number itself: a redacted suffix is enough to act on.
        self.assertNotIn(PHONE, line)
        self.assertIn("...0000", line)

    def test_no_bridge_function_logs_a_postgrest_error_BODY(self):
        """PostgREST echoes the rejected row in its error body. For
        whatsapp_messages that row is the customer's message; for clients it
        is their name, phone and notes. Four call sites printed it — status
        and a redacted phone are all a human needs to act.
        """
        import inspect
        for fn in (w.log_reply_to_crm, w.sync_lead_to_crm, w._crm_business_id):
            src = inspect.getsource(fn)
            code = "\n".join(l for l in src.splitlines()
                             if not l.strip().startswith("#"))
            self.assertNotIn("r.text", code, fn.__name__)
            self.assertNotIn(".text}", code, fn.__name__)

    def test_a_failed_lead_sync_logs_no_customer_field(self):
        def fake_get(url, **kw):
            return Resp(500, {"message": "boom"})
        with mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
             mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
             mock.patch.object(w, "CRM_OWNER_USER_ID", "o"), \
             mock.patch.object(w.requests, "get", fake_get), \
             mock.patch.object(w.requests, "post",
                               lambda *a, **k: Resp(200, BAIRAVI_ID)), \
             redirect_stdout(io.StringIO()) as out:
            w.sync_lead_to_crm(PHONE, {"source": "bairavi-transformer",
                                       "name": "Real Person",
                                       "city": "Mangalore"})
        line = out.getvalue()
        self.assertIn("CRM_LEAD_LOOKUP_FAILED", line)
        for pii in ("Real Person", "Mangalore", PHONE):
            self.assertNotIn(pii, line)
        self.assertIn("...0000", line)          # redacted suffix only
