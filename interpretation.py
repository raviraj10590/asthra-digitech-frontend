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
    delivery_same, delivery_mentioned, discom_approval_ask, callback_offered,
    asked_discount, asks_call, call_missed, asks_info, declined, escom_area (sales alerts and a
    location pin's supply area: never an interpreter's guess)

Pure module: imports only json, re and bairavi. Never produces customer-facing text.
"""
import json
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
           "asked_discount": brain["asked_discount"],
           "asks_call": brain["asks_call"],
           "call_missed": brain["call_missed"],
           "asks_info": brain["asks_info"],
           "declined": brain["declined"],
           "escom_area": brain["escom_area"],
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


# ══════════════════════════════════════════════════════════════════════════
# STEP 2 — SHADOW MODE: the pure parts (brief, reader, comparison, record)
#
# The interpreter is ASKED for structured data and nothing else; its answer
# is read by parse_llm_json, gated by validate(), compared with the
# authoritative parser, and only ever RECORDED. Nothing here reaches a
# customer, the transcript, the saved facts, the CRM or an owner alert.
#
# DESIGN B (owner-approved 2026-09-27): the record holds NO customer words.
# No evidence text, no delivery-place text, no message body, no phone, no
# WhatsApp message id, no raw model output. Evidence is described by
# structure only (found / value-in-evidence / length / outcome); the
# transcript stays the one place a human reads the actual message.
# ══════════════════════════════════════════════════════════════════════════

import hashlib

# ── versions — so results from different code are never mixed ────────────
RECORD_VERSION = 2          # the row layout (1 was the Step 2 log line)
VALIDATOR_VERSION = "v3"    # bump on ANY change to validate()'s rules
                            # v2 (2026-10-03): call_missed passed through, Brain-owned
                            # v3 (2026-10-03): asks_info passed through, Brain-owned

# Status of one shadow turn — a fixed vocabulary.
S_OK = "ok"
S_INVALID = "invalid_shadow"
S_PROVIDER_FAILED = "provider_failed"
S_SKIPPED_DEADLINE = "skipped_deadline"
S_ERROR = "shadow_error"
STATUSES = (S_OK, S_INVALID, S_PROVIDER_FAILED, S_SKIPPED_DEADLINE, S_ERROR)

# Comparison classes (owner's spec, 2026-09-27).
MATCH, SHADOW_ONLY, PARSER_ONLY, CONFLICT = "MATCH", "SHADOW_ONLY", "PARSER_ONLY", "CONFLICT"
INVALID_SHADOW, SKIPPED = "INVALID_SHADOW", "SKIPPED"
COMPARED = ("intent", "question_type", "capacity_kva", "quantity", "application",
            "delivery_place", "callback", "correction", "delivery_same",
            "discom", "delivery_mentioned")

# Delivery-place outcomes: the ONLY thing ever recorded about a place.
PLACE_ACCEPTED, PLACE_NOT_A_PLACE, PLACE_CONTEXT = "accepted", "not_a_place", "context"
PLACE_NO_EVIDENCE, PLACE_REJECTED = "no_evidence", "rejected"
_PLACE_OUTCOME = {R_NOT_A_PLACE: PLACE_NOT_A_PLACE, R_CONTEXT: PLACE_CONTEXT,
                  R_NO_EVIDENCE: PLACE_NO_EVIDENCE, R_VALUE_NOT_IN_EVIDENCE: PLACE_NO_EVIDENCE}

# The template WITHOUT runtime context; its hash is prompt_version.
_BRIEF_TEMPLATE = (
    "You read ONE WhatsApp message from a customer of a transformer "
    "manufacturer and return ONLY a JSON object. No other text. You never "
    "write a reply to the customer.\n"
    "Schema:\n"
    '{{"intent": one of {intents},\n'
    ' "fields": {{field: {{"value": ..., "evidence": "<exact words copied from '
    'the message>"}}}} using only these fields: {fields},\n'
    ' "questions": list from {questions},\n'
    ' "is_correction": true only if the customer explicitly changes a fact '
    "already known,\n"
    ' "ambiguous": false, or the field name if the message could mean two '
    "things}}\n"
    "Rules: capacity_kva and quantity are integers; application is one of "
    "{applications}; callback is one of {callbacks}. Leave out any field the "
    "message does not state. Never guess. Evidence must be copied exactly "
    "from the message.\n"
    "The business's last question was about: {awaiting}.\n"
    "Already known: {known}."
)


def _short_hash(text: str, n: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def contract_version() -> str:
    """Deterministic: changes exactly when the schema's allowed values do."""
    blob = json.dumps({"intents": INTENTS, "questions": QUESTIONS, "fields": FIELDS,
                       "applications": APPLICATIONS}, sort_keys=True)
    return "c1-" + _short_hash(blob, 8)


def prompt_version() -> str:
    """12 hex of the template alone — no customer context, never the prompt."""
    return _short_hash(_BRIEF_TEMPLATE, 12)


def interpretation_brief(awaiting=(), known: dict = None) -> str:
    """The interpreter's system prompt. It asks for ONE JSON object in the
    closed schema; it asks for no reply, no advice and no decision."""
    known = {k: v for k, v in (known or {}).items()
             if k in ("capacity_kva", "quantity", "application", "location",
                      "delivery_location", "delivery_same", "callback")
             and v not in (None, "", False)}
    return _BRIEF_TEMPLATE.format(
        intents=", ".join(INTENTS), fields=", ".join(FIELDS),
        questions=", ".join(QUESTIONS), applications=", ".join(APPLICATIONS),
        callbacks=", ".join(CALLBACKS), awaiting=", ".join(awaiting) or "nothing",
        known=known or "nothing")


def parse_llm_json(raw):
    """The first JSON object in a model's text, or None. Never raises."""
    t = re.sub(r"```(?:json)?", "", str(raw or ""))
    start = t.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(t[start:i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _question_type(v: dict) -> tuple:
    qs = list(v.get("asked_terms") or ())
    if v.get("customer_question"):
        qs.append(_TAG_TO_Q.get(v["customer_question"], v["customer_question"]))
    return tuple(sorted(qs))


def _comparable(v: dict, intent, correction) -> dict:
    return {"intent": intent,
            "question_type": _question_type(v) or None,
            "capacity_kva": v.get("capacity_kva"),
            "quantity": v.get("quantity"),
            "application": v.get("application"),
            "delivery_place": v.get("delivery_location"),
            "callback": v.get("callback"),
            "correction": bool(correction) or None,
            "delivery_same": bool(v.get("delivery_same")) or None,
            "discom": v.get("discom_approval_ask"),
            "delivery_mentioned": bool(v.get("delivery_mentioned")) or None}


def classify(parser_value, shadow_value) -> str:
    empty_p = parser_value in (None, "", (), [])
    empty_s = shadow_value in (None, "", (), [])
    if empty_p and empty_s:
        return MATCH
    if empty_p:
        return SHADOW_ONLY
    if empty_s:
        return PARSER_ONLY
    return MATCH if parser_value == shadow_value else CONFLICT


def compare(parser_followup: dict, text: str, known: dict,
            interp: dict, validated: dict) -> dict:
    """Field-by-field classes, plus both sides' values where they differ —
    EXCEPT the delivery place, whose values are never carried (Design B)."""
    parser_contract = from_parse(parser_followup, text, known)
    p = _comparable(parser_followup, parser_contract["intent"],
                    parser_contract["is_correction"])
    accepted_correction = bool(interp.get("is_correction")) and any(
        validated.get(k) is not None for k in ("capacity_kva", "quantity",
                                               "application", "delivery_location"))
    s = _comparable(validated, interp.get("intent"), accepted_correction)
    classes = {f: classify(p[f], s[f]) for f in COMPARED}
    diffs = {f: {"parser": p[f], "shadow": s[f]} for f in COMPARED
             if classes[f] != MATCH and f != "delivery_place"}
    return {"classes": classes, "diffs": diffs}


def field_report(interp, text: str, validated: dict) -> dict:
    """Design B: what was proposed, described WITHOUT the customer's words.

    value              the proposed value for capacity/quantity/application/
                       callback (integers or fixed vocabulary); ALWAYS None for
                       delivery_place — the place text is never recorded
    evidence_found     the evidence appears in the customer's message
    value_in_evidence  the value appears in its own evidence
    evidence_len       length of the evidence span (characters)
    outcome            "accepted", or the validator's fixed-vocabulary reason;
                       for delivery_place one of accepted / not_a_place /
                       context / no_evidence / rejected
    """
    fields = interp.get("fields") if isinstance(interp, dict) else None
    if not isinstance(fields, dict):
        return {}
    reasons = {f: r for f, r in (validated or {}).get("_rejected", ()) if f != "*"}
    accepted_key = {"delivery_place": "delivery_location"}
    out = {}
    for name, slot in fields.items():
        if name not in FIELDS or not isinstance(slot, dict):
            continue
        value, evidence = slot.get("value"), slot.get("evidence")
        ev = str(evidence or "")
        accepted = (validated or {}).get(accepted_key.get(name, name)) is not None
        if name == "delivery_place":
            outcome = (PLACE_ACCEPTED if accepted
                       else _PLACE_OUTCOME.get(reasons.get(name), PLACE_REJECTED))
            rec_value = None
        else:
            outcome = "accepted" if accepted else reasons.get(name, "rejected")
            rec_value = value if isinstance(value, (int, str)) and not isinstance(value, bool) else None
            if isinstance(rec_value, str) and rec_value not in APPLICATIONS + CALLBACKS:
                rec_value = None                      # only vocabulary values, never free text
        out[name] = {"value": rec_value,
                     "evidence_found": _in_message(ev, text),
                     "value_in_evidence": bool(value is not None and ev
                                               and _norm(value) in _norm(ev)),
                     "evidence_len": len(ev),
                     "outcome": outcome}
    return out


# The columns of public.bairavi_shadow_interpretations the writer fills
# (id and created_at are the database's own). A test pins this against the
# migration so the two cannot drift.
RECORD_COLUMNS = ("business", "turn_key", "record_version", "contract_version",
                  "validator_version", "prompt_version", "provider", "model", "status",
                  "error_class", "awaiting", "latency_ms", "budget_ms", "deadline_left_ms",
                  "intent", "questions", "is_correction", "proposed", "accepted",
                  "rejected", "ambiguous", "comparison", "conflict_fields", "diffs")


def _ms(seconds):
    return None if seconds is None else int(round(seconds * 1000))


def shadow_record(*, status, turn_key, awaiting, provider=None, model=None,
                  latency_ms=None, budget_s=None, left_s=None, interp=None,
                  validated=None, comparison=None, text="", error_class=None) -> dict:
    """One Design B row. `text` is used only to compute evidence structure and
    is never itself placed in the record."""
    is_dict = isinstance(interp, dict)
    if status in (S_OK, S_INVALID) and is_dict:
        intent = interp.get("intent") if interp.get("intent") in INTENTS else None
        qs = interp.get("questions")
        questions = [q for q in qs if q in QUESTIONS] if isinstance(qs, list) else None
        corr = interp.get("is_correction") if isinstance(interp.get("is_correction"), bool) else None
        proposed = field_report(interp, text, validated)
    else:
        intent = questions = corr = proposed = None
    accepted = None
    if validated is not None:
        accepted = {k: validated.get(k) for k in ("capacity_kva", "quantity", "application",
                                                  "callback") if validated.get(k) is not None}
        accepted["delivery_place_accepted"] = validated.get("delivery_location") is not None
    classes = (comparison["classes"] if comparison
               else {f: SKIPPED for f in COMPARED} if status == S_SKIPPED_DEADLINE
               else {f: INVALID_SHADOW for f in COMPARED})
    return {
        "business": "bairavi",
        "turn_key": turn_key,
        "record_version": RECORD_VERSION,
        "contract_version": contract_version(),
        "validator_version": VALIDATOR_VERSION,
        "prompt_version": prompt_version(),
        "provider": provider,
        "model": model,
        "status": status,
        "error_class": (str(error_class)[:40] if error_class else None),
        "awaiting": list(awaiting or ()),
        "latency_ms": latency_ms,
        "budget_ms": _ms(budget_s),
        "deadline_left_ms": _ms(left_s),
        "intent": intent,
        "questions": questions,
        "is_correction": corr,
        "proposed": proposed,
        "accepted": accepted,
        "rejected": [[f, r] for f, r in (validated or {}).get("_rejected", ())],
        "ambiguous": (validated or {}).get("_ambiguous") if validated else None,
        "comparison": classes,
        "conflict_fields": sorted(f for f, c in classes.items() if c == CONFLICT),
        "diffs": (comparison or {}).get("diffs") or None,
    }
