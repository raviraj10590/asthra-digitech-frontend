"""Auto-suggest: the bot learns the owner's own answers, only with his yes
(owner chose it 2026-10-04, "auto sugest ... maadu" 2026-11-02).

    1. A customer asks something; the owner answers by hand from the CRM.
    2. The hourly sweep finds that pair and asks the owner on WhatsApp:
       "Next time someone asks this, may I answer it myself? #learn 12 / #skip 12"
    3. #learn 12 (optionally "#learn 12 <better wording>") approves it.
    4. From then on:
         Bairavi  — a customer question the evidence tables cannot answer, and
                    that closely matches an approved question, gets the owner's
                    approved answer word for word (no model in between).
         Asthra   — the approved pairs are given to the AI as the owner's own
                    answers to use.
    #learned lists them, #unlearn 12 removes one. Nothing is learned without
    the owner's yes, and nothing he did not write is ever offered.

Stored in the Brain's own table learned_answers (service role only).

Pure module: no network. api/webhook.py and api/nudge.py do the I/O.
"""
import re

ASTHRA, BAIRAVI = "asthra", "bairavi"
SUGGESTED, APPROVED, SKIPPED, REMOVED = "suggested", "approved", "skipped", "removed"

MAX_SUGGESTIONS_PER_RUN = 3
PAIR_WINDOW_HOURS = 2

# ── Which hand-written replies are answers worth offering ──────────────────
# Measured on the CRM's last 45 days of manual replies (2026-11-02): pasted
# build logs, API keys, whole template texts and "ok"/"hi" were all there.
_JUNK_ANSWER = re.compile(
    r"sk[-_][a-z0-9]|deploy|##|\|\s*\||```|daily performance report|https?://\S+\s*$",
    re.IGNORECASE)
_QUESTION_WORDS = (
    "?", "eshtu", "estu", "yestu", "ಎಷ್ಟು", "ಎಷ್ಟ", "yaavaga", "yavaga", "ಯಾವಾಗ", "enu", "ಏನು",
    "ideya", "idya", "ಇದೆಯಾ", "illva", "ilva", "ಇಲ್ವ", "barutta", "baruta", "ಬರುತ್ತ", "aagutta",
    "agutha", "aguthe", "ಆಗುತ್ತ", "kodtira", "ಕೊಡ್ತೀರ", "sigutta", "ಸಿಗುತ್ತ", "hege", "ಹೇಗೆ",
    "elli", "ಎಲ್ಲಿ", "yaaru", "ಯಾರು", "how", "what", "when", "where", "which", "why", "can you",
    "do you", "is there", "price", "rate", "cost", "gst", "ದರ", "ಹಣ", "charge", "fees", "extra")
_ACKS = {"ok", "okay", "k", "kk", "yes", "no", "hi", "hii", "hello", "means", "thanks", "thank you",
         "ಸರಿ", "ಹೌದು", "illa", "houdu", "sari"}


def is_question(text: str) -> bool:
    low = " ".join((text or "").lower().split())
    if len(low) < 6 or low.strip(" .!") in _ACKS:
        return False
    return any(w in low for w in _QUESTION_WORDS)


def is_answer(text: str) -> bool:
    t = (text or "").strip()
    if not 12 <= len(t) <= 400 or t.endswith("?"):
        return False                   # too short, a pasted essay, or the owner asking back
    return not _JUNK_ANSWER.search(t)


def pairs(messages: list, staff_last10=(), window_hours: int = PAIR_WINDOW_HOURS) -> list:
    """(question row, answer row) for each hand-written answer to a customer
    question. `messages`: CRM whatsapp_messages rows of ONE phone, oldest
    first, each with id, direction, body, created_at (datetime) and source
    (metadata.source; None = written by a person)."""
    out = []
    last_in = None
    for m in messages:
        if (m.get("phone") or "")[-10:] in staff_last10:
            continue
        if m.get("direction") == "inbound":
            last_in = m
            continue
        if m.get("source") is not None or m.get("message_type", "text") != "text":
            continue
        if not last_in or not is_question(last_in.get("body")) or not is_answer(m.get("body")):
            continue
        gap = (m["created_at"] - last_in["created_at"]).total_seconds()
        if 0 <= gap <= window_hours * 3600:
            out.append((last_in, m))
            last_in = None             # one answer per question: the first one
    return out


def suggestion_text(row: dict) -> str:
    """The owner's WhatsApp ask for one suggestion."""
    biz = "Bairavi" if row.get("business") == BAIRAVI else "Asthra"
    return (f"💡 Kalitukolla? #{row['id']} ({biz})\n"
            f"Customer keLiddu: \"{_clip(row['question'], 160)}\"\n"
            f"Neevu heLiddu: \"{_clip(row['answer'], 240)}\"\n\n"
            f"Mundina sala ide prashne bandre naane ee uttara heLla?\n"
            f"👉 #learn {row['id']}  (beku)   ·   #skip {row['id']}  (beda)\n"
            f"Badalaavane beku andre: #learn {row['id']} <hosa uttara>")


def _clip(t: str, n: int) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# ── Owner commands ──────────────────────────────────────────────────────────
_CMD_RE = re.compile(r"^#(learn|skip|unlearn)\s+#?(\d{1,9})\b\s*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_command(text: str):
    """('list', None, '') | (action, id, new_answer) | ('usage', None, '') | None."""
    s = (text or "").strip()
    if s.lower() in ("#learned", "#learnt"):
        return "list", None, ""
    m = _CMD_RE.match(s)
    if m:
        return m.group(1).lower(), int(m.group(2)), " ".join(m.group(3).split())
    if re.match(r"^#(learn|skip|unlearn)\b", s, re.IGNORECASE):
        return "usage", None, ""
    return None


USAGE = "❓ Usage: #learn 12 [better answer] · #skip 12 · #unlearn 12 · #learned"


def list_text(rows: list) -> str:
    if not rows:
        return "📚 Bot innoo yaava uttaravannu kalitilla."
    lines = [f"📚 Bot kalitiruva uttaragaLu ({len(rows)}):"]
    for r in rows[:15]:
        biz = "B" if r.get("business") == BAIRAVI else "A"
        lines.append(f"#{r['id']} [{biz}] {_clip(r['question'], 50)} → {_clip(r['answer'], 60)}")
    lines.append("\nTegeyalu: #unlearn <number>")
    return "\n".join(lines)


# ── Matching a new customer message to an approved question ────────────────
_FILLER = {"sir", "sar", "ಸರ್", "ji", "please", "pls", "plz", "hi", "hello", "namaskara", "ನಮಸ್ಕಾರ",
           "anna", "madam", "the", "a", "an", "is", "are", "to", "for", "of", "and", "me", "you",
           "your", "nimma", "ನಿಮ್ಮ", "ok", "okay"}
_TOKEN_RE = re.compile(r"[a-z0-9]+|[ಀ-೿]+")


def tokens(text: str) -> set:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _FILLER and len(t) > 1}


def best_match(text: str, approved: list):
    """The approved row whose question this message asks, or None.

    Conservative on purpose: at least 2 shared words, covering most of the
    learned question AND a fair part of the message — a long message that
    merely mentions "gst" is not the learned GST question."""
    mine = tokens(text)
    if len(mine) < 2:
        return None
    best, best_score = None, 0.0
    for row in approved:
        theirs = tokens(row.get("question"))
        shared = mine & theirs
        if len(shared) < 2 or not theirs:
            continue
        cover, focus = len(shared) / len(theirs), len(shared) / len(mine)
        if cover >= 0.6 and focus >= 0.4 and cover + focus > best_score:
            best, best_score = row, cover + focus
    return best


def prompt_block(approved: list) -> str:
    """The owner's approved answers, for the Asthra AI's system messages."""
    rows = [r for r in approved if r.get("business") == ASTHRA][:20]
    if not rows:
        return ""
    lines = ["OWNER-APPROVED ANSWERS — the MD's own replies. When the customer asks the same "
             "thing, give this answer (same facts; you may translate/rephrase politely):"]
    lines += [f"Q: {_clip(r['question'], 200)}\nA: {_clip(r['answer'], 400)}" for r in rows]
    return "\n".join(lines)
