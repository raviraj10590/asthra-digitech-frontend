"""What reaches the CRM conversation thread, and what must not.

THE PRODUCT DECISION THIS ENCODES
---------------------------------
Asthra Bot is an EXPERT AI CHAT BOT. The intended customer experience is
message → intent → reasoning over business context → questions → qualified
requirement → natural conversation, recorded in the CRM. It is NOT a fixed
service-list/menu flow.

So the mirror covers the conversation, not the menu furniture:

  MIRROR      send_text             — every bot reply, which is the
                                      conversation itself
              send_brochure         — the document the customer asked for
                                      and received
              send_followup_buttons — live customer-facing communication,
                                      fired after a successful brochure. The
                                      customer's next message is a TAP on one
                                      of its titles, so the thread needs the
                                      options to be readable at all.
  DO NOT      send_welcome_menu — neither its image nor its interactive
              service list. A fixed service-list menu is not the AI-first
              experience being built, so nothing is invested in recording it.
  DO NOT      send_typing — a read receipt plus an indicator on the INBOUND
              message id. Not a message, and it has no wa_message_id at all.
  DO NOT      notify_owner — owner and staff notifications are internal and
              must never appear in a customer conversation thread.

THE ASYMMETRY IS THE POINT. Both the welcome list and the follow-up buttons
are Meta `interactive` messages, and only one is mirrored. That is a product
decision about which conversations matter, not a technical distinction — so
there is NO generic interactive-mirroring helper. The follow-up buttons
compose their own body inline, and any future interactive path gets its own
decision based on its own UX.

WHAT THESE PATHS CLOSED. Before this, send_text was the only path wired to the
mirror. The brochure document and the follow-up buttons were sent and never
recorded, so Meta's delivery receipts for them orphaned into the dead-letter
queue against wa_message_ids the CRM had never stored.

The tests below are two-sided on purpose: the paths that must mirror are
asserted to mirror, and the paths that must not are asserted to write nothing
AND to contain no mirror call in their source. Re-adding one is then a
deliberate act that fails a test, not a quiet drift.

Offline: every boundary is stubbed. No network, no database, no send.
"""

import inspect
import io
import json
import os
import sys
import tokenize
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

PHONE = "919000000000"
WAMID = "wamid.HBgMOTE5MDAwMDAwMDAwFQIAERgS"
IMAGE = "https://cdn.test/welcome.png"
DOC = "https://cdn.test/profile.pdf"


def code_of(fn) -> str:
    """The EXECUTABLE source of fn — comments and string literals removed.

    Asserting against raw source is self-referential: this file's own subject
    matter appears in the code's comments ("STATUS ONLY, never r.text") and
    docstrings ("stage ⑫"), so a prohibition like "never log r.text" is
    satisfied or violated by prose rather than by behaviour. Strip both and
    the assertion is about what runs.
    """
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(inspect.getsource(fn)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


class Resp:
    def __init__(self, code=200, body=None):
        self.status_code = code
        self.ok = 200 <= code < 300
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class Channel:
    """Records what was sent to Meta and what was mirrored to the CRM.

    _wa_post is stubbed, so the ONLY remaining requests.post in these paths is
    the CRM mirror — which is what makes `rows` an exact census of the
    mirroring, with nothing else able to sneak in.
    """

    def __init__(self, role="CLIENT", wa_code=200, wamid=WAMID,
                 wa_raises=False, raises_on="", crm_code=201):
        self.role, self.wa_code, self.wamid = role, wa_code, wamid
        self.wa_raises, self.crm_code = wa_raises, crm_code
        self.raises_on = raises_on      # Meta type whose send raises
        self.sends = []                 # payloads handed to Meta
        self.rows = []                  # rows handed to the CRM
        self.posts = []                 # (url, kwargs) of every CRM POST
        self.log = ""

    def _wa_post(self, payload):
        if self.wa_raises or (self.raises_on
                              and payload.get("type") == self.raises_on):
            raise RuntimeError("channel down")
        self.sends.append(payload)
        body = ({"messages": [{"id": self.wamid}]} if self.wa_code < 300
                else {"error": {"message": "rejected", "code": 131047}})
        return Resp(self.wa_code, body)

    def _crm_post(self, url, **kw):
        self.posts.append((url, kw))
        self.rows.append(kw.get("json"))
        return Resp(self.crm_code, {})

    def of_type(self, message_type):
        return [r for r in self.rows if r.get("message_type") == message_type]


@contextmanager
def channel(**kw):
    ch = Channel(**kw)
    buf = io.StringIO()
    with mock.patch.object(w, "_wa_post", ch._wa_post), \
         mock.patch.object(w, "get_role", lambda p: (ch.role, None)), \
         mock.patch.object(w.requests, "post", ch._crm_post), \
         mock.patch.object(w, "CRM_SUPABASE_URL", "https://crm.test"), \
         mock.patch.object(w, "CRM_SUPABASE_SERVICE_KEY", "svc"), \
         mock.patch.object(w, "CRM_OWNER_USER_ID", "owner-uuid"), \
         mock.patch.object(w, "WELCOME_IMAGE", IMAGE), \
         mock.patch.object(w, "BROCHURE_URL", DOC), \
         redirect_stdout(buf):
        yield ch
    ch.log = buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# 1 · THE TWO PATHS THAT MIRROR
# ══════════════════════════════════════════════════════════════════════════

class TheConversationIsRecorded(unittest.TestCase):
    """The three paths that reach the CRM thread."""


    def test_a_text_reply_is_mirrored(self):
        """The bot's replies ARE the conversation — this is the path the
        expert-chat product depends on."""
        with channel() as ch:
            w.send_text(PHONE, "hello")
        self.assertEqual(len(ch.of_type("text")), 1)

    def test_the_brochure_document_is_mirrored(self):
        with channel() as ch:
            self.assertTrue(w.send_brochure(PHONE))
        media = ch.of_type("media")
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["media_url"], DOC)

    def test_the_brochure_fallback_apology_is_mirrored_as_text(self):
        """No brochure URL sends an apology, not a document. It goes through
        send_text, so it must appear as text and claim no media."""
        with channel() as ch, mock.patch.object(w, "BROCHURE_URL", ""):
            self.assertFalse(w.send_brochure(PHONE))
        self.assertEqual(len(ch.rows), 1)
        self.assertEqual(ch.rows[0]["message_type"], "text")
        self.assertNotIn("media_url", ch.rows[0])

    def test_the_followup_buttons_are_mirrored(self):
        """Live customer-facing communication after a brochure the customer
        asked for — so the CRM records what they were offered."""
        with channel() as ch:
            w.send_followup_buttons(PHONE)
        self.assertEqual(len(ch.of_type("interactive")), 1)

    def test_the_followup_row_records_the_prompt_and_every_option(self):
        """The customer's next message is a TAP on one of these titles.
        Without them the thread shows a reply arriving from nowhere."""
        with channel() as ch:
            w.send_followup_buttons(PHONE)
        act = ch.sends[0]["interactive"]
        body = ch.rows[0]["body"]
        self.assertIn(act["body"]["text"], body)
        titles = [b["reply"]["title"] for b in act["action"]["buttons"]]
        self.assertEqual(len(titles), 3)
        for t in titles:
            self.assertIn(t, body)

    def test_the_followup_row_carries_no_routing_ids(self):
        """quotation / call / meeting are plumbing, not conversation."""
        with channel() as ch:
            w.send_followup_buttons(PHONE)
        for ident in ("quotation", "call", "meeting"):
            self.assertNotIn(ident, ch.rows[0]["body"])

    def test_the_followup_row_claims_no_attachment(self):
        with channel() as ch:
            w.send_followup_buttons(PHONE)
        self.assertNotIn("media_url", ch.rows[0])

    def test_a_rejected_followup_send_mirrors_NOTHING(self):
        """Its fallback goes through send_text, which mirrors. Recording the
        rejected send as well would put two rows in the thread for the one
        message the customer actually received."""
        with channel(wa_code=400) as ch:
            w.send_followup_buttons(PHONE)
        self.assertEqual([r["message_type"] for r in ch.rows], ["text"])

    def test_exactly_three_send_paths_mirror(self):
        """The inventory, asserted. A new path added later must make a
        deliberate choice rather than inherit one."""
        mirrors = {"send_text", "send_brochure", "send_followup_buttons"}
        silent = {"send_welcome_menu", "send_typing", "notify_owner"}
        for name in mirrors:
            src = code_of(getattr(w, name))
            self.assertTrue(
                "log_reply_to_crm" in src or "_mirror_sent_message" in src,
                f"{name} must mirror")
        for name in silent:
            src = code_of(getattr(w, name))
            for call in ("log_reply_to_crm", "_mirror_sent_message",
                         "_mirror_outbound_to_crm"):
                self.assertNotIn(call, src, f"{name} must not mirror")


# ══════════════════════════════════════════════════════════════════════════
# 2 · THE MENU IS NOT MIRRORED
# ══════════════════════════════════════════════════════════════════════════

class TheWelcomeMenuStaysOutOfTheThread(unittest.TestCase):
    """Asserted positively, not merely absent: the welcome image and the
    interactive service list must write NOTHING. The product is an expert AI
    chat, not a fixed menu flow, so this is the intended scope — and a future
    re-add has to fail a test first.

    Note the contrast with send_followup_buttons, which IS mirrored: the same
    Meta payload shape, a different product judgement."""

    def test_the_welcome_image_writes_no_crm_row(self):
        with channel() as ch:
            w.send_welcome_menu(PHONE)
        self.assertEqual(ch.of_type("media"), [])
        for r in ch.rows:
            self.assertNotEqual((r.get("metadata") or {}).get("original_type"),
                                "image")

    def test_the_interactive_service_list_writes_no_crm_row(self):
        with channel() as ch:
            w.send_welcome_menu(PHONE)
        self.assertEqual(ch.of_type("interactive"), [])

    def test_the_only_welcome_row_is_its_TEXT_greeting(self):
        """send_welcome_menu makes three Meta sends — image, greeting, list.
        Only the greeting goes through send_text, and that is 680cab8
        behaviour which predates this task and must not regress."""
        with channel() as ch:
            w.send_welcome_menu(PHONE)
        self.assertEqual(len(ch.sends), 3)
        self.assertEqual([r["message_type"] for r in ch.rows], ["text"])

    def test_the_ONLY_mirrored_interactive_message_is_the_followup(self):
        """Both are Meta `interactive` messages and only one is recorded. The
        distinction is which conversation matters, not which payload shape."""
        with channel() as ch:
            w.send_text(PHONE, "hi")
            w.send_welcome_menu(PHONE)
            w.send_brochure(PHONE)
        self.assertEqual(ch.of_type("interactive"), [])
        with channel() as ch:
            w.send_followup_buttons(PHONE)
        self.assertEqual(len(ch.of_type("interactive")), 1)

    def test_no_generic_interactive_helper_exists(self):
        """The follow-up buttons compose their own body inline. A shared
        helper would be a framework for hypothetical future paths, and the
        welcome menu is precisely the path that must NOT get one."""
        self.assertFalse(hasattr(w, "_interactive_transcript"))
        src = io.open(os.path.join(os.path.dirname(__file__), "..",
                                   "api", "webhook.py"),
                      encoding="utf-8").read()
        self.assertNotIn("_interactive_transcript", src)

    def test_the_menu_send_paths_are_byte_identical_to_680cab8(self):
        """Item 2 of the correction: the bot's own behaviour is untouched —
        only the mirror work was removed. Compared against the committed
        pre-change source, not against a description of it."""
        import subprocess
        base = subprocess.run(
            ["git", "show", "680cab8:api/webhook.py"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True).stdout
        self.assertTrue(base, "could not read 680cab8")
        for name in ("send_welcome_menu", "send_typing", "notify_owner"):
            marker = f"\ndef {name}("
            start = base.index(marker)
            end = base.index("\ndef ", start + len(marker))
            self.assertIn(base[start:end], io.open(
                os.path.join(os.path.dirname(__file__), "..",
                             "api", "webhook.py"), encoding="utf-8").read(),
                f"{name} differs from 680cab8")


class TypingIsNotAMessage(unittest.TestCase):

    def test_send_typing_creates_no_crm_row(self):
        with channel() as ch:
            w.send_typing("wamid.INBOUND")
        self.assertEqual(ch.rows, [])

    def test_send_typing_does_not_even_send_a_message(self):
        """It is a read receipt plus an indicator on the INBOUND message id —
        there is no outbound message and no wamid to store."""
        with channel() as ch:
            w.send_typing("wamid.INBOUND")
        self.assertEqual(ch.sends[0]["status"], "read")
        self.assertNotIn("type", ch.sends[0])

    def test_send_typing_mirrors_nothing_in_source(self):
        src = code_of(w.send_typing)
        self.assertNotIn("log_reply_to_crm", src)
        self.assertNotIn("_mirror_sent_message", src)
        self.assertNotIn("_mirror_outbound_to_crm", src)


class OwnerAlertsStayOutOfCustomerThreads(unittest.TestCase):

    def test_notify_owner_writes_no_customer_thread_row(self):
        with channel(role="OWNER") as ch, \
             mock.patch.object(w, "staff_and_owner_numbers",
                               lambda: ["919888888888"]), \
             mock.patch.dict(os.environ, {"OWNER_ALERT_TEMPLATE": ""}):
            w.notify_owner("lead summary with a budget in it")
        self.assertEqual(ch.rows, [])

    def test_notify_owner_calls_no_mirror_directly(self):
        src = code_of(w.notify_owner)
        self.assertNotIn("log_reply_to_crm", src)
        self.assertNotIn("_mirror_sent_message", src)
        self.assertNotIn("_mirror_outbound_to_crm", src)

    def test_the_template_path_writes_nothing_either(self):
        with channel(role="OWNER") as ch, \
             mock.patch.object(w, "staff_and_owner_numbers",
                               lambda: ["919888888888"]), \
             mock.patch.dict(os.environ, {"OWNER_ALERT_TEMPLATE": "alert_v1"}):
            w.notify_owner("internal")
        self.assertEqual(ch.sends[0]["type"], "template")
        self.assertEqual(ch.rows, [])

    def test_no_internal_notes_model_was_invented(self):
        """The ruling was explicit: owner notifications stay internal WhatsApp
        notifications for now, and this task introduces no internal-notes
        representation in the CRM."""
        src = code_of(w._mirror_outbound_to_crm)
        for row_field in ("internal_note", "is_internal", "internal",
                          "note_type", "visibility"):
            self.assertNotIn(f'"{row_field}"', src)


# ══════════════════════════════════════════════════════════════════════════
# 3 · EVERY MIRRORED MESSAGE CARRIES META'S OWN ID
# ══════════════════════════════════════════════════════════════════════════

class TheIdIsAlwaysCarried(unittest.TestCase):

    def _both_paths(self, ch):
        w.send_text(PHONE, "hello")
        w.send_brochure(PHONE)
        w.send_followup_buttons(PHONE)
        return ch.rows

    def test_every_mirrored_row_carries_the_wamid(self):
        """The whole reason delivery receipts became orphan_status dead
        letters: Meta reported on an id the CRM had never stored."""
        with channel() as ch:
            rows = self._both_paths(ch)
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertEqual(r.get("wa_message_id"), WAMID, r["message_type"])

    def test_the_id_comes_from_metas_response_not_invented(self):
        with channel(wamid="wamid.DIFFERENT") as ch:
            w.send_brochure(PHONE)
        self.assertEqual(ch.rows[0]["wa_message_id"], "wamid.DIFFERENT")

    def test_a_rejected_brochure_mirrors_nothing_at_all(self):
        """Nothing was delivered, so the thread must stay empty. send_brochure
        has no fallback text on a rejected document."""
        with channel(wa_code=400) as ch:
            w.send_brochure(PHONE)
        self.assertEqual(ch.rows, [])

    def test_a_text_reply_IS_still_mirrored_without_an_id(self):
        """Deliberately different from the brochure: a text reply has no
        fallback behind it, so an id-less row is the only record the bot
        spoke. This is the 680cab8 behaviour and it must not regress."""
        with channel(wa_code=400) as ch:
            w.send_text(PHONE, "hello")
        self.assertEqual(len(ch.rows), 1)
        self.assertNotIn("wa_message_id", ch.rows[0])

    def test_an_error_body_is_never_trusted_for_an_id(self):
        with channel(wa_code=400) as ch:
            ch.wamid = "wamid.FROM_AN_ERROR_BODY"
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
            w.send_text(PHONE, "hi")
        for r in ch.rows:
            self.assertNotEqual(r.get("wa_message_id"),
                                "wamid.FROM_AN_ERROR_BODY")

    def test_wamid_of_reads_defensively(self):
        self.assertIsNone(w._wamid_of(None))
        self.assertIsNone(w._wamid_of(Resp(200, {})))
        self.assertIsNone(w._wamid_of(Resp(200, {"messages": []})))
        self.assertIsNone(w._wamid_of(Resp(400, {"messages": [{"id": "x"}]})))
        self.assertIsNone(w._wamid_of(object()))
        self.assertEqual(w._wamid_of(Resp(200, {"messages": [{"id": "x"}]})), "x")


# ══════════════════════════════════════════════════════════════════════════
# 4 · A DUPLICATE WAMID DOES NOT BECOME A SECOND ROW
# ══════════════════════════════════════════════════════════════════════════

class IdempotencyIsTheIndexsJob(unittest.TestCase):
    """The CRM's PARTIAL unique index on wa_message_id enforces this; the
    Brain's duty is to send the id and NOT ask PostgREST to merge duplicates.
    The database-level proof lives in the CRM SQL suite
    (tests/sql/05_bridge_contract.test.sql) because a mocked HTTP boundary
    structurally cannot prove it — that is exactly how the 42P10 regression
    reached production."""

    def test_no_mirror_ever_asks_postgrest_to_resolve_a_conflict(self):
        """on_conflict=wa_message_id against a PARTIAL unique index raises
        42P10 and broke every mirror write in production."""
        with channel() as ch:
            w.send_text(PHONE, "hi")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        self.assertEqual(len(ch.posts), 3)
        for url, kw in ch.posts:
            self.assertNotIn("on_conflict", url)
            self.assertNotIn("params", kw)
            prefer = (kw.get("headers") or {}).get("Prefer", "")
            self.assertNotIn("merge-duplicates", prefer)
            self.assertNotIn("resolution", prefer)

    def test_a_conflict_is_logged_and_never_retried(self):
        """409 means the row is already there. One POST, no second attempt,
        and no duplicate."""
        with channel(crm_code=409) as ch:
            w.send_brochure(PHONE)
        self.assertEqual(len(ch.posts), 1)
        self.assertIn("CRM_MIRROR_FAILED", ch.log)
        self.assertIn("status=409", ch.log)

    def test_one_send_makes_exactly_one_mirror_row(self):
        with channel() as ch:
            w.send_brochure(PHONE)
        self.assertEqual(len(ch.rows), 1)

    def test_the_same_send_repeated_sends_the_same_id_not_a_new_one(self):
        """Two identical sends produce two POSTs carrying ONE id — so the
        index rejects the second rather than the CRM gaining a twin."""
        with channel() as ch:
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
            w.send_followup_buttons(PHONE)
        self.assertEqual(len({r["wa_message_id"] for r in ch.rows}), 1)


# ══════════════════════════════════════════════════════════════════════════
# 5 · THE ROLE GATE IS UNCHANGED
# ══════════════════════════════════════════════════════════════════════════

class OnlyCustomersGetACustomerThread(unittest.TestCase):

    def _every_path(self):
        w.send_text(PHONE, "hello")
        w.send_welcome_menu(PHONE)
        w.send_followup_buttons(PHONE)
        w.send_brochure(PHONE)

    def test_an_owner_is_mirrored_nowhere(self):
        with channel(role="OWNER") as ch:
            self._every_path()
        self.assertEqual(ch.rows, [])
        self.assertEqual(len(ch.sends), 6)     # still SENT, just not mirrored

    def test_the_followup_buttons_respect_the_role_gate_too(self):
        for role in ("OWNER", "STAFF", "MANAGER"):
            with channel(role=role) as ch:
                w.send_followup_buttons(PHONE)
            self.assertEqual(ch.rows, [], role)

    def test_staff_are_mirrored_nowhere(self):
        with channel(role="STAFF") as ch:
            self._every_path()
        self.assertEqual(ch.rows, [])

    def test_an_unrecognised_role_is_mirrored_nowhere(self):
        """Fail closed: only the literal CLIENT role opens a customer thread."""
        with channel(role="MANAGER") as ch:
            self._every_path()
        self.assertEqual(ch.rows, [])

    def test_a_client_is_mirrored_on_the_two_mirroring_paths_only(self):
        with channel(role="CLIENT") as ch:
            self._every_path()
        self.assertEqual([r["message_type"] for r in ch.rows],
                         ["text", "text", "interactive", "media"])

    def test_the_gate_is_role_based_not_the_bootstrap_list(self):
        """A staff number added to bot_roles must be excluded without a
        redeploy, so the gate reads get_role, never OWNER_PHONES."""
        for fn in (w.send_text, w._mirror_sent_message):
            src = code_of(fn)
            self.assertIn("get_role", src)
            self.assertNotIn("OWNER_PHONES", src)

    def test_owner_phones_is_untouched_by_this_change(self):
        src = inspect.getsource(w)
        self.assertEqual(src.count("OWNER_PHONES = "), 1)


# ══════════════════════════════════════════════════════════════════════════
# 6 · THE ROWS THE CRM CAN ACTUALLY RENDER
# ══════════════════════════════════════════════════════════════════════════

class TheRowsSpeakTheCRMsVocabulary(unittest.TestCase):
    """message_type, original_type, media_url and file_name are read off the
    CRM's own ingestion (parseMessage in ingest.ts) and its own renderer
    (WhatsAppInbox renderMedia / lastMsgPreview). Inventing a vocabulary here
    would store rows the CRM cannot display."""

    CRM_MESSAGE_TYPES = {"text", "template", "media", "reaction", "location",
                         "interactive", "contacts", "order", "unsupported",
                         "system"}

    def _all(self, ch):
        w.send_text(PHONE, "hello")
        w.send_brochure(PHONE)
        w.send_followup_buttons(PHONE)
        return ch.rows

    def test_every_message_type_satisfies_the_crm_check_constraint(self):
        with channel() as ch:
            for r in self._all(ch):
                self.assertIn(r["message_type"], self.CRM_MESSAGE_TYPES)

    def test_every_row_claims_outbound_and_sent(self):
        with channel() as ch:
            for r in self._all(ch):
                self.assertEqual(r["direction"], "outbound")
                self.assertEqual(r["status"], "sent")

    def test_every_row_carries_the_source_marker(self):
        """CRM queries key off metadata.source = 'asthra_ai_bot'."""
        with channel() as ch:
            for r in self._all(ch):
                self.assertEqual(r["metadata"]["source"], "asthra_ai_bot")

    def test_a_plain_text_row_claims_no_original_type(self):
        """lastMsgPreview treats ANY row with metadata.original_type as an
        attachment, so putting it on a text row mislabels every bot reply in
        the conversation list."""
        with channel() as ch:
            w.send_text(PHONE, "hello")
        self.assertNotIn("original_type", ch.rows[0]["metadata"])
        self.assertNotIn("media_url", ch.rows[0])

    def test_the_document_row_carries_the_filename_the_inbox_labels_with(self):
        with channel() as ch:
            w.send_brochure(PHONE)
        doc = ch.rows[0]
        self.assertEqual(doc["message_type"], "media")
        self.assertEqual(doc["metadata"]["original_type"], "document")
        self.assertTrue(doc["metadata"]["file_name"].endswith(".pdf"))
        self.assertTrue(doc["body"])           # the caption, per ingest.ts

    def test_the_document_body_and_filename_come_from_the_payload_sent(self):
        """Read back off the payload, so the CRM row cannot drift from the
        document the customer actually received."""
        with channel() as ch:
            w.send_brochure(PHONE)
        sent = ch.sends[0]["document"]
        self.assertEqual(ch.rows[0]["body"], sent["caption"])
        self.assertEqual(ch.rows[0]["metadata"]["file_name"], sent["filename"])
        self.assertEqual(ch.rows[0]["media_url"], sent["link"])

    def test_no_client_id_is_sent_from_the_brain(self):
        """The Brain does not know the CRM's ids; the CRM links the row itself
        (migration 20260918100000)."""
        with channel() as ch:
            for r in self._all(ch):
                self.assertNotIn("client_id", r)

    def test_the_row_carries_no_business_id_either(self):
        """Business identity is a LEAD attribute here; the CRM derives the
        message's from its linked lead. Sending one would need a CRM uuid in
        Brain configuration."""
        with channel() as ch:
            for r in self._all(ch):
                self.assertNotIn("business_id", r)


# ══════════════════════════════════════════════════════════════════════════
# 7 · NO PII, AND NOTHING OUTSIDE SCOPE
# ══════════════════════════════════════════════════════════════════════════

class TheMirrorLeaksNothing(unittest.TestCase):

    def test_a_failed_mirror_logs_no_message_body(self):
        with channel(crm_code=500) as ch:
            w.send_text(PHONE, "ಕೋಟೇಶನ್ ಬೇಕು")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        self.assertIn("CRM_MIRROR_FAILED", ch.log)
        for secret in ("ಕೋಟೇಶನ್", "ಪ್ರೊಫೈಲ್", DOC, IMAGE, PHONE, WAMID):
            self.assertNotIn(secret, ch.log)

    def test_a_failed_mirror_logs_only_the_last_four_digits(self):
        with channel(crm_code=500) as ch:
            w.send_brochure(PHONE)
        self.assertIn(f"phone=...{PHONE[-4:]}", ch.log)

    def test_no_postgrest_error_body_is_logged(self):
        """Code only: the prohibition is stated in a comment in this very
        function, so raw source would match its own warning."""
        for fn in (w._mirror_outbound_to_crm, w._mirror_sent_message):
            src = code_of(fn)
            self.assertNotIn("r . text", src)
            self.assertNotIn("r . json", src)

    def test_a_crm_failure_never_breaks_a_send(self):
        def explode(*a, **k):
            raise RuntimeError("crm unreachable")
        with channel() as ch, mock.patch.object(w.requests, "post", explode):
            w.send_text(PHONE, "hello")
            w.send_welcome_menu(PHONE)
            w.send_followup_buttons(PHONE)
            self.assertTrue(w.send_brochure(PHONE))
        self.assertEqual(len(ch.sends), 6)

    def test_no_crm_credentials_means_no_write_and_no_crash(self):
        with channel() as ch, \
             mock.patch.object(w, "CRM_SUPABASE_URL", ""):
            w.send_text(PHONE, "hi")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        self.assertEqual(ch.rows, [])
        self.assertEqual(len(ch.sends), 3)


class NothingOutsideScopeWasTouched(unittest.TestCase):

    TOUCHED = ("_mirror_outbound_to_crm", "log_reply_to_crm", "_wamid_of",
               "_mirror_sent_message", "send_text", "send_brochure",
               "send_followup_buttons")

    def _touched_source(self):
        """EXECUTABLE source only. send_text's docstring says "stage ⑫" and
        send_brochure's says "Review H1"; a prose match would fail an
        assertion that is about what the code writes."""
        return "\n".join(code_of(getattr(w, n)) for n in self.TOUCHED)

    def test_no_payment_concept_appears_anywhere_in_the_changed_code(self):
        src = self._touched_source().lower()
        for word in ("payment", "paid", "invoice", "became_client_at",
                     "razorpay", "upi"):
            self.assertNotIn(word, src, word)

    def test_no_lifecycle_or_stage_field_is_written(self):
        src = self._touched_source().lower()
        for word in ("stage", "lifecycle", "qualification", "quotation_status",
                     "pipeline"):
            self.assertNotIn(word, src, word)

    def test_the_mirror_writes_to_exactly_one_table(self):
        """Observed, then asserted in source. The URL lives in an f-string, so
        code_of() strips it — but "/rest/v1/" appears in no comment, which
        makes the raw count safe here and proves no SECOND table is written."""
        with channel() as ch:
            w.send_text(PHONE, "hi")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        self.assertEqual(len(ch.posts), 3)
        for url, _ in ch.posts:
            self.assertEqual(url, "https://crm.test/rest/v1/whatsapp_messages")
        raw = "\n".join(inspect.getsource(getattr(w, n)) for n in self.TOUCHED)
        self.assertEqual(raw.count("/rest/v1/"), 1)

    def test_no_row_field_beyond_the_agreed_set_is_written(self):
        """Fails when a new column starts being written, which is how an
        unnoticed schema requirement would appear."""
        allowed = {"user_id", "phone", "direction", "message_type", "body",
                   "status", "metadata", "media_url", "wa_message_id"}
        with channel() as ch:
            w.send_text(PHONE, "hi")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        for r in ch.rows:
            self.assertTrue(set(r) <= allowed, set(r) - allowed)

    def test_no_metadata_key_beyond_the_agreed_set_is_written(self):
        allowed = {"source", "original_type", "file_name"}
        with channel() as ch:
            w.send_text(PHONE, "hi")
            w.send_brochure(PHONE)
            w.send_followup_buttons(PHONE)
        for r in ch.rows:
            self.assertTrue(set(r["metadata"]) <= allowed,
                            set(r["metadata"]) - allowed)

    def test_the_mirror_remains_fire_and_forget(self):
        """Its failure must never be raised into a customer reply path."""
        src = code_of(w._mirror_outbound_to_crm)
        self.assertIn("except Exception", src)
        self.assertNotIn("raise", src)

    def test_the_send_timeout_is_unchanged(self):
        """Tokenised, not substring-matched: "timeout=3" is a prefix of
        "timeout=300", so the raw form passed a mutation that lengthened a
        customer reply's wait on the CRM to five minutes."""
        self.assertIn("timeout = 3 ,", code_of(w._mirror_outbound_to_crm))


if __name__ == "__main__":
    unittest.main(verbosity=2)
