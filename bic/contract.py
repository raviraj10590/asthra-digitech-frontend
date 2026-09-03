"""Channel-agnostic request/response contract.

Constitution Article VIII: interfaces are replaceable adapters; the BIC is not.
This module is the boundary that makes that true — WhatsApp, web, voice, email
and admin all speak BrainRequest/BrainResponse, so adding an interface is a new
adapter and never a core change.

Pure data. No I/O, no imports from the rest of the BIC, so it can never grow a
dependency on any single channel.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Attachment:
    """Inbound or outbound media, described independently of any channel."""
    kind: str                      # image | audio | video | document | sticker
    ref: Optional[str] = None      # channel-side id (e.g. WhatsApp media id)
    url: Optional[str] = None
    caption: Optional[str] = None
    mime: Optional[str] = None


@dataclass(frozen=True)
class BrainRequest:
    """One inbound turn, normalised.

    Frozen: an adapter builds this once and nothing downstream may rewrite it.
    `sender_id` in particular must stay exactly what the transport verified —
    Article II.1 depends on identity never being derived from message content.
    """
    channel: str                       # whatsapp | web | voice | email | admin
    sender_id: str                     # VERIFIED by the transport, never claimed
    text: str = ""
    attachments: List[Attachment] = field(default_factory=list)
    locale: Optional[str] = None
    thread_id: Optional[str] = None    # conversation key (phone, session, …)
    # Brain-local message reference (uuid4), NOT Meta's wamid: a wamid
    # base64-embeds the sender's number and must not reach a claim.
    message_id: Optional[str] = None   # provenance → claims.source_ref
    raw: Dict[str, Any] = field(default_factory=dict)   # original payload, debug only

    @property
    def has_text(self) -> bool:
        return bool((self.text or "").strip())


@dataclass
class BrainAction:
    """Something the caller should do beyond replying.

    1C emits only what today's code already does (send a document, send the
    welcome menu, notify the owner). Deliberately data, not behaviour: the Brain
    decides WHAT should happen, the adapter decides HOW on its channel.
    """
    kind: str                                    # send_document | send_menu | notify_owner | typing
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrainResponse:
    """The Brain's answer for one turn.

    `text` may be empty when the turn is handled entirely by actions (e.g. the
    welcome menu) or intentionally silent (paused chat) — mirroring current
    behaviour exactly rather than inventing a reply where none exists today.
    """
    text: str = ""
    actions: List[BrainAction] = field(default_factory=list)
    attachments: List[Attachment] = field(default_factory=list)
    confidence: Optional[float] = None
    needs_approval: bool = False
    # Diagnostics — never sent to a user. Used by the 1C old-vs-new comparison.
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_silent(self) -> bool:
        return not (self.text or "").strip() and not self.actions

    def add_action(self, kind: str, **payload) -> "BrainResponse":
        self.actions.append(BrainAction(kind=kind, payload=payload))
        return self
