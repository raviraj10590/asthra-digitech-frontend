"""The interpretation contract and its validator — architecture Step 1.

WHY THIS EXISTS (owner, 2026-09-25): "Asthra Brain should not become a giant
keyword/rule-based chatbot. LLM interprets. Brain validates and controls."
Today every customer message is understood by keyword tables in bairavi.py.
A future LLM will propose a meaning in the closed shape below; this module is
the Brain side that decides what of that proposal may enter the state machine.

NO LLM IS CALLED HERE, and nothing here is wired into the live webhook. Step 1
proves the seam: `from_parse` turns today's deterministic parse into the
contract, and `validate` turns any contract back into exactly the dict
parse_followup returns, so merged_state / outstanding / awaiting_after / the
composer / alerts / CRM consume it unchanged.

WHO OWNS WHAT
  Interpretation-owned (the LLM may propose; this validator checks):
    capacity_kva, quantity, application, delivery_location, callback,
    customer_question, asked_terms, asked_price, commercial_intent,
    is_ack, is_greeting
  Brain-owned (always computed deterministically from the text + context,
  whatever an interpreter says):
    delivery_same, delivery_mentioned, discom_approval_ask, callback_offered

Pure module: imports only re and bairavi. Never produces customer-facing text.
"""
import re

import bairavi as b

# ── THE CLOSED SCHEMA ─────────────────────────────────────────────────────

INTENTS = ("answer", "question", "greeting", "ack", "correction", "price_request",
           "quotation_request", "callback_choice", "off_topic", "unclear")
QUESTIONS = ("delivery_time", "delivery_area", "warranty", "payment", "transport",
             "who_are_you", "range", "discom_approval", "other")
FIELDS = ("capacity_kva", "quantity", "application", "delivery_place", "callback")

APPLICATIONS = tuple(sorted({v for _, v in b._APPLICATIONS}
                            | {v for _, v in b._APPLICATIONS_WHOLE_WORD}))
CALLBACKS = (b.CALLBACK_NOW, b.CALLBACK_EVENING, b.CALLBACK_TOMORROW)

# Question tags: contract <-> the Brain's own customer_question tags.
_Q_TO_TAG = {"delivery_time": b.QUESTION_DELIVERY_TIME,
             "delivery_area": b.QUESTION_DELIVERY_AREA,
             "who_are_you": b.QUESTION_WHO, "range": b.QUESTION_RANGE,
             "other": b.QUESTION_UNANSWERED}
_TAG_TO_Q = {v: k for k, v in _Q_TO_TAG.items()}
# The Brain's precedence when a message asks several things (customer_question).
_Q_ORDER = ("delivery_time", "delivery_area", "range", "who_are_you", "other")
_TERM_QUESTIONS = ("transport", "warranty", "payment")

# Where the Brain's own asked-for-a-quantity question is the context.
_BARE_NUMBER = re.compile(r"^\s*\d{1,3}\s*$")
_UNIT_WORD = re.compile(r"units?|nos?|pcs?|ಯುನಿಟ್|ನಗ", re.I)

# Rejection reasons are a fixed vocabulary, so they can be counted and logged
# without carrying customer text.
R_SCHEMA = "schema"
R_NO_EVIDENCE = "evidence_not_in_message"
R_VALUE_NOT_IN_EVIDENCE = "value_not_in_evidence"
R_NOT_IN_CATALOGUE_ENUM = "not_an_allowed_value"
R_CONTEXT = "not_valid_in_this_context"
R_NOT_A_PLACE = "not_a_place"
R_ESTABLISHED = "would_replace_established_fact"
R_AMBIGUOUS = "ambiguous"


# ── NORMALISATION ─────────────────────────────────────────────────────────

def _norm(s) -> str:
    """Case- and whitespace-insensitive, for evidence matching only."""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _in_message(evidence, text) -> bool:
    ev = _norm(evidence)
    return bool(ev) and ev in _norm(text)


def empty() -> dict:
    """A well-formed interpretation that says nothing."""
    return {"intent": "unclear", "fields": {}, "questions": [],
            "is_correction": False, "ambiguous": False}


def schema_errors(interp) -> list:
    """Everything wrong with the SHAPE. A malformed interpretation is not
    trusted in part: the validator treats it as empty()."""
    errs = []
    if not isinstance(interp, dict):
        return ["not an object"]
    extra = set(interp) - {"intent", "fields", "questions", "is_correction", "ambiguous"}
    if extra:
        errs.append(f"unknown keys: {sorted(extra)}")
    if interp.get("intent") not in INTENTS:
        errs.append("intent not allowed")
    fields = interp.get("fields", {})
    if not isinstance(fields, dict):
        errs.append("fields not an object")
    else:
        for name, slot in fields.items():
            if name not in FIELDS:
                errs.append(f"unknown field: {name}")
            elif slot is not None and (not isinstance(slot, dict)
                                       or set(slot) - {"value", "evidence"}):
                errs.append(f"bad slot: {name}")
    qs = interp.get("questions", [])
    if not isinstance(qs, list) or any(q not in QUESTIONS for q in qs):
        errs.append("questions not allowed")
    if not isinstance(interp.get("is_correction", False), bool):
        errs.append("is_correction not bool")
    amb = interp.get("ambiguous", False)
    if not (amb is False or amb in FIELDS):
        errs.append("ambiguous must be false or a field name")
    return errs


# ── DETERMINISTIC PARSE -> CONTRACT (the stand-in for a future LLM) ──────

def _evidence_for_number(text: str, n) -> str:
    m = re.search(rf"(?<!\d){int(n)}(?!\d)", text or "")
    return m.group(0) if m else ""


def from_parse(followup: dict, text: str, known: dict = None) -> dict:
    """Today's parse_followup result, expressed in the contract.

    Evidence is the shortest span of the message that carries the value;
    where the parser read a value without a literal span (a word count such
    as "single unit" -> 1), the whole message is the evidence.
    """
    known = known or {}
    fields = {}
    if followup.get("capacity_kva") is not None:
        cap = followup["capacity_kva"]
        fields["capacity_kva"] = {"value": cap,
                                  "evidence": _evidence_for_number(text, cap) or text}
    if followup.get("quantity") is not None:
        q = followup["quantity"]
        fields["quantity"] = {"value": q, "evidence": _evidence_for_number(text, q) or text}
    if followup.get("application"):
        fields["application"] = {"value": followup["application"], "evidence": text}
    if followup.get("delivery_location"):
        fields["delivery_place"] = {"value": followup["delivery_location"],
                                    "evidence": text}
    if followup.get("callback"):
        fields["callback"] = {"value": followup["callback"], "evidence": text}

    questions = [q for q in _TERM_QUESTIONS if q in (followup.get("asked_terms") or ())]
    tag = followup.get("customer_question")
    if tag in _TAG_TO_Q:
        questions.append(_TAG_TO_Q[tag])
    if followup.get("discom_approval_ask") is not None:
        questions.append("discom_approval")

    # The parser treats any explicit value that differs from an established
    # one as the customer's correction; the contract makes that explicit.
    is_correction = any(
        name in fields and known.get(key) not in (None, "", False)
        and fields[name]["value"] != known.get(key)
        for name, key in (("capacity_kva", "capacity_kva"), ("quantity", "quantity"),
                          ("application", "application"),
                          ("delivery_place", "delivery_location")))

    if followup.get("is_greeting"):
        intent = "greeting"
    elif followup.get("callback"):
        intent = "callback_choice"
    elif followup.get("commercial_intent") == b.QUOTATION_REQUEST:
        intent = "quotation_request"
    elif followup.get("commercial_intent") == b.PRICE_REQUEST:
        intent = "price_request"
    elif followup.get("is_ack"):
        intent = "ack"
    elif is_correction:
        intent = "correction"
    elif fields:
        intent = "answer"
    elif questions:
        intent = "question"
    else:
        intent = "unclear"
    return {"intent": intent, "fields": fields, "questions": questions,
            "is_correction": is_correction, "ambiguous": False}


# ── CONTRACT -> STATE-MACHINE DICT (the Brain's gate) ─────────────────────

def validate(interp, text: str, awaiting=(), known: dict = None) -> dict:
    """The parse_followup-shaped dict the existing state machine consumes.

    Every interpretation-owned value must survive: schema, evidence in the
    customer's own message, the allowed values, the awaiting context, the
    place checks, and the never-replace-without-correction rule. Anything that
    does not is dropped and named in `_rejected`. A value that cannot be
    decided is reported in `_ambiguous` for the flow to clarify — never
    guessed. No customer-facing text is produced here.
    """
    known = known or {}
    awaiting = tuple(awaiting or ())
    rejected = []
    if schema_errors(interp):
        rejected.append(("*", R_SCHEMA))
        interp = empty()

    # Brain-owned signals: computed exactly as today, whatever the interpreter said.
    brain = b.parse_followup(text, awaiting, known=known)
    out = {"quantity": None, "application": None, "capacity_kva": None,
           "callback": None, "asked_terms": (), "callback_offered": brain["callback_offered"],
           "delivery_location": None, "delivery_same": brain["delivery_same"],
           "delivery_mentioned": brain["delivery_mentioned"],
           "is_ack": False, "is_greeting": False,
           "asked_price": False, "commercial_intent": None,
           "discom_approval_ask": brain["discom_approval_ask"],
           "customer_question": None}
    ambiguous = interp.get("ambiguous") or None
    correction = bool(interp.get("is_correction"))
    fields = interp.get("fields") or {}

    def slot(name):
        s = fields.get(name)
        if not s or s.get("value") in (None, ""):
            return None
        if not _in_message(s.get("evidence"), text):
            rejected.append((name, R_NO_EVIDENCE))
            return None
        return s

    def keep(name, key, value):
        """The never-erase rule: an established fact changes only on an
        explicit correction."""
        old = known.get(key)
        if old not in (None, "", False) and value != old and not correction:
            rejected.append((name, R_ESTABLISHED))
            return None
        return value

    # capacity — the number must be in the evidence; any rating is kept (the
    # composer already answers planned / unrecognised ratings as VERIFY), but
    # nothing is ever mapped to a nearby size.
    s = slot("capacity_kva")
    if s:
        v = s["value"]
        if not isinstance(v, int) or isinstance(v, bool) or not str(v) in str(s["evidence"]):
            rejected.append(("capacity_kva", R_VALUE_NOT_IN_EVIDENCE))
        else:
            out["capacity_kva"] = keep("capacity_kva", "capacity_kva", v)

    # quantity — the awaiting question is authoritative.
    s = slot("quantity")
    if s:
        v = s["value"]
        bare = bool(_BARE_NUMBER.match(text or ""))
        if not isinstance(v, int) or isinstance(v, bool) or not (0 < v <= 999):
            rejected.append(("quantity", R_NOT_IN_CATALOGUE_ENUM))
        elif str(v) not in str(s["evidence"]) and v not in b._WORD_QTY.values():
            rejected.append(("quantity", R_VALUE_NOT_IN_EVIDENCE))
        elif bare and b.AWAITING_CALLBACK in awaiting:
            rejected.append(("quantity", R_CONTEXT))          # "2" = option two
        elif bare and b.AWAITING_DELIVERY in awaiting and b.AWAITING_QUANTITY not in awaiting:
            rejected.append(("quantity", R_AMBIGUOUS))        # "2" to "where?" — ask
            ambiguous = ambiguous or "quantity"
        elif (known.get("capacity_kva") == v and not _UNIT_WORD.search(text or "")):
            rejected.append(("quantity", R_CONTEXT))          # the kVA, repeated
        else:
            out["quantity"] = keep("quantity", "quantity", v)

    s = slot("application")
    if s:
        if s["value"] not in APPLICATIONS:
            rejected.append(("application", R_NOT_IN_CATALOGUE_ENUM))
        else:
            out["application"] = keep("application", "application", s["value"])

    # delivery place — a CANDIDATE that must pass the Brain's own place checks
    # and arrive in a context where a place is expected.
    s = slot("delivery_place")
    if s:
        v = str(s["value"]).strip()
        low = _norm(text)
        # The Brain itself joins the address parts of a multi-line answer with
        # ", " — so every PART must be the customer's words, not the whole.
        parts = [seg for seg in re.split(r",\s*", v) if seg.strip()]
        explicit = b._DELIVERY_STRICT_RE.search(text or "")   # "deliver to X"
        expected = (b.AWAITING_DELIVERY in awaiting or explicit
                    or any(b._label_matches(low, m) if m.isascii() else m in low
                           for m in b._ADMIN_MARKER))
        # A time is never a place ("ತಕ್ಷಣ", "immediately", "delivery yavaga"),
        # read from the Brain's own urgency table and when-words.
        is_time = (any(needle in _norm(v) for needle, _ in b._TIMING_URGENCY)
                   or any(w in _norm(v) for w in b._WHEN_WORDS))
        if not parts or not all(_in_message(seg, text) for seg in parts):
            rejected.append(("delivery_place", R_VALUE_NOT_IN_EVIDENCE))
        elif not expected:
            rejected.append(("delivery_place", R_CONTEXT))
        elif is_time or (not explicit and not all(b._is_place_like(seg) for seg in parts)):
            # An explicit "deliver to X" names the place outright, as today;
            # a bare answer must still look like a place.
            rejected.append(("delivery_place", R_NOT_A_PLACE))
        else:
            out["delivery_location"] = keep("delivery_place", "delivery_location", v)
    if out["delivery_location"]:
        out["delivery_same"] = False       # a named place supersedes "same place"

    # callback — a choice only where one was offered; otherwise only a whole
    # message that is itself a request to be called.
    s = slot("callback")
    if s:
        v = s["value"]
        whole = _norm(s["evidence"]) == _norm(text)
        if v not in CALLBACKS:
            rejected.append(("callback", R_NOT_IN_CATALOGUE_ENUM))
        elif b.AWAITING_CALLBACK in awaiting or (v == b.CALLBACK_NOW and whole):
            out["callback"] = v
        else:
            rejected.append(("callback", R_CONTEXT))

    # questions and intent
    qs = interp.get("questions") or []
    out["asked_terms"] = tuple(q for q in _TERM_QUESTIONS if q in qs)
    for q in _Q_ORDER:
        if q in qs:
            out["customer_question"] = _Q_TO_TAG[q]
            break
    intent = interp.get("intent")
    out["is_greeting"] = intent == "greeting"
    out["is_ack"] = intent in ("greeting", "ack")
    if intent == "quotation_request":
        out["commercial_intent"] = b.QUOTATION_REQUEST
        out["asked_price"] = True
    elif intent == "price_request":
        out["commercial_intent"] = b.PRICE_REQUEST
        out["asked_price"] = True

    out["_rejected"] = tuple(rejected)
    out["_ambiguous"] = ambiguous
    return out


def state_view(validated: dict) -> dict:
    """Only the keys parse_followup itself returns — what the state machine sees."""
    return {k: v for k, v in validated.items() if not k.startswith("_")}
