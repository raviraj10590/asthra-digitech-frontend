"""A fake WhatsApp send result for harnesses that stub send_text (Phase 2A).

send_text returns Meta's response, and the Bairavi path now ACTS on it: only
an ACCEPTED send (2xx carrying a message id) earns a FLOW_MARKER. A stub that
returns None is therefore an UNKNOWN delivery, not a neutral one. Harnesses
that model a normal conversation return accepted() so the conversation they
replay is the one a customer actually received.
"""


class Accepted:
    status_code = 200
    ok = True
    text = ""

    def json(self):
        return {"messages": [{"id": "wamid.TEST_ACCEPTED"}]}


class Rejected:
    ok = False
    text = ""

    def __init__(self, status_code=400):
        self.status_code = status_code

    def json(self):
        return {"error": {"code": 131047}}


def accepted(*_a, **_k):
    return Accepted()


def recorded(sink):
    """A send_text stub that appends the text to `sink` and is ACCEPTED."""
    def _send(to, text, **_k):
        sink.append(text)
        return Accepted()
    return _send
