"""WhatsApp (Meta Cloud API) adapter — translation only.

    Meta payload → BrainRequest        (parse)
    BrainResponse → Meta sends         (render)

Contains NO business logic, NO policy decisions and NO tool calls. It knows the
shape of Meta's JSON and nothing about what any message means.

Deliberately has no dependency on webhook.py: senders are passed in, so this
module stays testable offline and the dependency direction stays one-way.
"""

from typing import Any, Dict, Optional

from bic.contract import Attachment, BrainRequest, BrainResponse

# Meta message types that carry media rather than text.
_MEDIA_KINDS = ("image", "audio", "video", "document", "sticker")


def parse(payload: Dict[str, Any]) -> Optional[BrainRequest]:
    """Meta webhook JSON → BrainRequest.

    Returns None for anything that is not an inbound message — status
    callbacks (delivery/read receipts) and malformed payloads — mirroring the
    current early-return behaviour exactly.
    """
    try:
        value = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return None

    if "statuses" in value:          # delivery/read receipt, not a message
        return None

    messages = value.get("messages") or []
    if not messages:
        return None

    msg = messages[0]
    sender = msg.get("from")
    if not sender:
        return None

    msg_type = msg.get("type", "")
    text = ""
    attachments = []

    if msg_type == "text":
        text = (msg.get("text") or {}).get("body", "") or ""
    elif msg_type == "interactive":
        # Button/list replies carry their payload in a nested object. The
        # adapter surfaces the ids; deciding what they MEAN is business logic
        # and stays in the existing handlers.
        iact = msg.get("interactive") or {}
        sub = iact.get("button_reply") or iact.get("list_reply") or {}
        text = sub.get("title", "") or ""
        attachments.append(Attachment(kind=f"interactive:{iact.get('type', '')}",
                                      ref=sub.get("id"), caption=sub.get("title")))
    elif msg_type in _MEDIA_KINDS:
        media = msg.get(msg_type) or {}
        attachments.append(Attachment(kind=msg_type,
                                      ref=media.get("id"),
                                      caption=media.get("caption"),
                                      mime=media.get("mime_type")))

    return BrainRequest(
        channel="whatsapp",
        sender_id=sender,                 # VERIFIED by Meta — never message content
        text=text,
        attachments=attachments,
        thread_id=sender,                 # one conversation per phone number
        message_id=msg.get("id"),
        raw={"type": msg_type},
    )


def render(response: BrainResponse, request: BrainRequest, *, send_text) -> None:
    """BrainResponse → Meta sends.

    `send_text` is injected so this module never imports webhook.py.

    Only non-empty text is sent. An empty-text response is NOT an error: it
    means the turn was fully handled by the flow itself (today's client
    pipeline sends its own menus and documents inline) or was intentionally
    silent (a paused chat). Sending a blank message here would be a visible
    behaviour change, which 1C must not introduce.
    """
    text = (response.text or "").strip()
    if text:
        send_text(request.sender_id, response.text)
