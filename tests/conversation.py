"""A reusable multi-turn conversation driver for the client pipeline.

WHY THIS EXISTS
---------------
An audit of 2,814 tests found that exactly ONE file modelled a conversation —
the Bairavi file, written after a defect that only existed on message two.
Every other branch (menu, off-topic, brochure, new-contact, AI reply, paused)
was tested as a single message into an empty history, which is precisely the
shape that missed it.

The defect: the bot answered a transformer enquiry correctly, asked two
questions, and then told the customer "we are not a transformer company" when
they answered — because routing was evaluated per message and the follow-up
("1 unit", "Agricultural", "Rate") carried no keyword. No single-message test
could see it.

This driver accumulates history the way fetch_context would, so a test can
assert on turn two and turn three.

HOW HISTORY IS BUILT. Real history comes from save_messages(), so this
captures what the pipeline actually saved and feeds it back — rather than a
test-authored guess at what history "should" look like. A branch that forgets
to save its turn therefore shows up here as a lost conversation, which is
exactly the bug class in question.

Offline: every boundary is stubbed. No network, no provider, no database.
"""

import io
import os
import sys
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import webhook as w                                            # noqa: E402

PHONE = "910000000000"


class Turn(dict):
    """One turn's observable effects. A dict so tests read naturally."""

    @property
    def replied(self):
        return bool(self["sent"])

    @property
    def reply(self):
        return self["sent"][0] if self["sent"] else None

    @property
    def silent(self):
        return not self["sent"] and not self["menu"]


class Conversation:
    """Drive run_client_pipeline over several turns, accumulating history.

    paused / degraded are per-conversation defaults; either can be overridden
    for a single turn, which is how a mid-conversation takeover or a transient
    read failure is modelled.
    """

    def __init__(self, phone=PHONE, paused=False, degraded=False,
                 save_outcome=None, bic=False, ai_reply="ASTHRA_AI_REPLY"):
        self.phone = phone
        self.paused = paused
        self.degraded = degraded
        # None => the real SAVE_OK. Set to SAVE_PERSISTENCE_FAILURE /
        # SAVE_NETWORK_FAILURE to model a rejected transcript write.
        self.save_outcome = save_outcome
        self.bic = bic
        self.ai_reply = ai_reply
        self.history = []
        self.turns = []

    def send(self, text, paused=None, degraded=None, save_outcome=None):
        """One inbound customer message. Returns a Turn."""
        rec = {"sent": [], "menu": [], "owner": [], "leads": [],
               "first_seen": [], "saved": [], "branches": [], "stdout": ""}
        outcome = (self.save_outcome if save_outcome is None else save_outcome)

        def fake_save_messages(items):
            # Record the attempt either way; only APPEND to history when the
            # write "succeeded", so a failed write really does lose the turn.
            rec["saved"].extend(items)
            if outcome in (None, w.SAVE_OK):
                for _p, role, content in items:
                    self.history.append({"role": role, "content": content})
                return w.SAVE_OK
            return outcome

        ctx = {
            "history": list(self.history),
            "recent_sys": [],
            "paused": self.paused if paused is None else paused,
            "degraded": self.degraded if degraded is None else degraded,
            "vip_alerted": False, "lead_alerted": False, "last_user": {},
            "stored_messages": len(self.history),
        }

        buf = io.StringIO()
        with mock.patch.object(w, "fetch_memory", lambda s: {}), \
             mock.patch.object(w, "record_first_seen",
                               lambda *a, **k: rec["first_seen"].append(a)), \
             mock.patch.object(w, "send_text",
                               lambda to, t, **k: rec["sent"].append(t)), \
             mock.patch.object(w, "send_welcome_menu",
                               lambda to: rec["menu"].append(to)), \
             mock.patch.object(w, "send_followup_buttons", lambda *a, **k: None), \
             mock.patch.object(w, "upsert_lead",
                               lambda p, d: rec["leads"].append(d)), \
             mock.patch.object(w, "notify_owner",
                               lambda m, **k: rec["owner"].append(m)), \
             mock.patch.object(w, "save_messages", fake_save_messages), \
             mock.patch.object(w, "save_message",
                               lambda p, r, c: fake_save_messages([(p, r, c)])), \
             mock.patch.object(w, "maybe_alert_vip", lambda *a, **k: None), \
             mock.patch.object(w, "generate_reply",
                               lambda *a, **k: self.ai_reply), \
             mock.patch.object(w, "BIC_AVAILABLE", self.bic), \
             redirect_stdout(buf):
            w.run_client_pipeline(self.phone, text, ctx)

        rec["stdout"] = buf.getvalue()
        rec["in"] = text
        turn = Turn(rec)
        self.turns.append(turn)
        return turn

    def thread(self, *messages):
        """Convenience: send several messages, return the list of Turns."""
        return [self.send(m) for m in messages]


# ── Fixtures for the messages that actually arrive in production ──────────

CAP_Q = "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?"
WHEN_Q = "ನಿಮಗೆ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಯಾವಾಗ ಅಗತ್ಯವಿದೆ?"
LOC_Q = "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?"


def lead_form(capacity="A. 25 kVA", when="A.ತಕ್ಷಣ ಅಗತ್ಯವಿದೆ",
              location="Testpura", name="Test Person"):
    """The exact Meta Lead Ads shape — all five fields, as seen in all 16
    real production messages."""
    return (f"Hello! I filled out your form and would like to know more "
            f"about your business.\n\n"
            f"{WHEN_Q}: {when}\n{CAP_Q}: {capacity}\n"
            f"{LOC_Q}: {location}\nFull name: {name}\n"
            f"Phone number: 910000000000")


# The real keyword-free follow-ups customers sent, which is what broke.
FOLLOWUPS = ("1 unit", "Agricultural", "Rate", "1 unit\nAgricultural",
             "ನಮ್ಮಲ್ಲಿ ಲಯನ್ ದೂರ ಇದೆ ಕಾರಣ ಟಿ ಸಿ ಬೇಕಾಗಿದೆ")
