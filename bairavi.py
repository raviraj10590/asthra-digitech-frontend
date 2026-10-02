"""Bairavi Trans Solutions — the transformer enquiry layer.

WHY THIS EXISTS, MEASURED IN PRODUCTION
---------------------------------------
Between 2026-09-12 and 2026-09-15, sixteen Meta Lead Ads handoffs about
transformers reached this WhatsApp number. Fifteen of them were answered with
Asthra DigiTech's digital-marketing services menu — social media management,
websites, election campaigns — sent to people who had just said they need a
25 kVA transformer. The one correct reply went to the owner's own number,
because the OWNER path already recognises transformer enquiries as out of
scope. The customer path did not.

Worse than the wrong brand: the ad form had ALREADY ANSWERED the qualification
questions, and every answer was discarded. All sixteen carried, in the
customer's own words, their required capacity, their timeline, their project
location and their full name. Only five were persisted as leads at all.

WHAT THIS LAYER MAY AND MAY NOT SAY
-----------------------------------
Bairavi is a real manufacturer with a real evidence problem, and its own
product knowledge base (Module 03, `AC-05`) already ruled the boundary: status
permits a quotation, documented evidence enables it. Only BTS-100 has a GTP.
BTS-250 is in active production with no technical attribute documented at all.

So this layer NEVER states:

    price · lead time · BEE star rating · certifications (BIS/BEE/ISO/MESCOM)
    losses · impedance · dimensions · conductor sizes · any GTP value

None of those exist as evidence. Eleven of the sixteen leads chose "for
information and price list", so the pressure to invent a number here is real
and constant — which is exactly why the rule is absolute rather than a default.
`₹68,244` appears in the design package and is NOT a price: it is an Excel
calculator output at one day's material rates.

What it MAY state is §6.1's short list: capacity, voltage ratio, phase,
cooling type, applications. Oil-immersed only — `DRY_TYPE` has no GTP, drawing
or documentation anywhere (`C-13`), and no dry-type SKU may be created "not
even as a placeholder to make the catalogue look complete" (`AC-03`).

CURRENT RANGE AND PLANNED RANGE ARE DIFFERENT FACTS
---------------------------------------------------
The ad form offers 25 / 63 / 100 / 500 kVA. Manufacturing today is
25 / 63 / 100 / 250. Those are not the same list, and the difference is
deliberate on both sides:

  25 / 63 / 100 / 250   SUPPORTED_PRODUCT — made today
  500                   ROADMAP — Bairavi intends to build it, and the form
                        offers it on purpose. Two of the sixteen chose it.

So 500 kVA is NOT an out-of-range error and must not be handled as one. The
first version of this module did exactly that: it fell through the same branch
as a typo, so a customer picking the capacity the ad advertised got the same
reply as someone who typed 9999. A planned capacity and an unrecognised one
are different facts and now carry different statuses.

What a 500 kVA enquiry gets is both halves of the truth — it is planned, and
it is not manufactured today — plus a route to sales and engineering.
Promising it would be a transformer that cannot be delivered; refusing it
would throw away a real enquiry for a product the business has decided to
build.

Anything outside both lists is VERIFY: captured, never refused, and never
silently mapped to a nearby size. `AC-04`'s gate is "a gate, not a filter".

EXTRACTION IS ALLOWED TO FAIL
-----------------------------
`AC-07`: the original text is stored verbatim and the parsed fields are a
normalized view of it, never a replacement. Where a field cannot be read
confidently it stays None and a human confirms. Their sentence, which is the
same discipline the Brain applies everywhere else: "a blank field is correct, a
confidently wrong capacity is not."

Two fields are singled out as unreadable from a message even when they seem
obvious: for a service call, `issue_category` and `urgency`. A loose complaint
is not a diagnosis, and a wrong urgency reading either dispatches an engineer
needlessly or delays a real fault. Both are asked, never inferred.

NO I/O, NO MODEL, NO NETWORK. Pure functions over text, so the reply a customer
sees is decided by code that can be read and tested rather than generated.
"""

import hashlib
import re

# ── Catalogue · Module 03 §1.0a ───────────────────────────────────────────
# All four are `SUPPORTED_PRODUCT` and all four are OIL_IMMERSED. Supported
# does NOT mean documented: only BTS-100 has a GTP. That distinction is why
# nothing below carries a price, a loss figure or a delivery time.
CATALOGUE_KVA = (25, 63, 100, 250)

# PLANNED, NOT CURRENT. 500 kVA is in the ad form deliberately — Bairavi
# intends to manufacture it — so it is neither a mistake nor an out-of-range
# error, and the form must keep offering it.
#
# It is still NOT manufactured today, and the distance between "planned" and
# "available" is the whole reason this is a separate tuple rather than an
# extra entry in CATALOGUE_KVA. Adding it there would make the bot advertise
# a transformer that cannot be delivered, which is the one failure mode worse
# than sending the wrong services menu.
#
# THIS REPLACED DEAD CODE. The first version declared a constant like this
# and never read it, so 500 kVA fell through the same branch as a typo: a
# customer choosing the capacity the ad offered got the same reply as someone
# who typed 9999. Planned capacity and unrecognised capacity are different
# facts and now have different statuses.
PLANNED_KVA = (500,)

FAMILY = "OIL_IMMERSED"

# Requirement type · AC-02. The first fork, and it is answered by the enquiry
# itself rather than by asking.
NEW_UNIT = "NEW_UNIT"
REPAIR = "REPAIR"

# SKU status · AC-04 declares exactly this vocabulary:
#     sku_status ∈ { SUPPORTED_PRODUCT, VERIFY, ROADMAP, NOT_OFFERED }
# The first version used FUTURE_OR_MANUAL_CONFIRMATION_PRODUCT here, which is
# AC-03's FAMILY-level status — a different axis. Using the SKU vocabulary for
# a SKU means ROADMAP already exists for exactly the 500 kVA case.
#
# AC-04's gate applies to all three non-supported values: they are blocked
# from the automatic quotation path and routed for manual/technical
# confirmation. "A gate, not a filter" — the enquiry stays captured, visible
# and workable.
SUPPORTED = "SUPPORTED_PRODUCT"
ROADMAP = "ROADMAP"        # declared future capacity — 500 kVA today
VERIFY = "VERIFY"          # unrecognised capacity — a human confirms it

# ── Detection ─────────────────────────────────────────────────────────────
# The Meta Lead Ads handoff signature. Verified against all 16 production
# messages: every one opens with this sentence and carries five labelled
# fields. Matching the FORM rather than guessing from keywords is what makes
# this branch safe to put ahead of Asthra's own routing.
_LEAD_FORM_MARKERS = ("filled out your form", "filled in your form",
                      "filled your form")

# Transformer subject words, English and Kannada, including the two
# misspellings seen in production. `kva` is matched with a boundary so it
# cannot fire inside an unrelated word.
_SUBJECT = (
    "transformer", "transfarmer", "tranformer", "transfomer",
    "ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್", "ಟ್ರಾನ್ಸ್ಫಾರ್ಮರ್", "ಪರಿವರ್ತಕ",
    # TRADE VOCABULARY, learned from a real customer: "ಟಿ ಸಿ ಬೇಕಾಗಿದೆ" —
    # TC is a transformer centre. Kannada forms only; a bare English "tc"
    # is too short to match safely.
    "ಟಿ ಸಿ", "ಟಿಸಿ",
)
_KVA_RE = re.compile(r"\b(\d{1,4})\s*k\s*v\s*a\b", re.IGNORECASE)

# "100kv" — how a real customer wrote 100 kVA on 2026-09-17. The reply read it
# as no capacity at all, so a product Bairavi actually makes was answered as
# "needs verification".
#
# WHY THIS IS NOT SIMPLY ACCEPTING "kv". kV is a real and different unit, and
# 11 kV / 22 kV / 33 kV are THE standard Indian distribution voltages — so
# "11kv line ge TC beku" is a site SPEC, not a request for an 11 kVA
# transformer. Reading that as a capacity is exactly the confidently-wrong
# capacity AC-07 forbids.
#
# So a bare "kv" figure is trusted only when it is a capacity Bairavi actually
# makes or plans. That cannot misread a voltage class — none of 25/63/100/250/
# 500 is one — and it costs nothing elsewhere: an off-catalogue figure lands on
# VERIFY whether it was read or not, so the only thing at stake for those is
# whether the number reaches the owner as a field or as raw text, and the raw
# text is forwarded either way.
_KV_RE = re.compile(r"\b(\d{1,4})\s*k\s*v\b", re.IGNORECASE)
# The trailing \b is what keeps this off "kva": between "v" and "a" there
# is no word boundary, so "100kva" never matches here and is read by
# _KVA_RE instead. An earlier version added a (?!\s*a) lookahead as well,
# which looked harmless and silently broke "100kv agriculture" — the next
# word began with "a", so the capacity was lost from exactly the message
# that answered both questions at once.

# Repair signals. Deliberately narrow: these decide REPAIR vs NEW_UNIT, and
# a false REPAIR sends a buyer down a service conversation.
_REPAIR_HINTS = (
    "repair", "not working", "failed", "burnt", "burn", "fault", "faulty",
    "service", "breakdown", "leak", "heating", "heat agta", "problem",
    "ರಿಪೇರಿ", "ಕೆಟ್ಟು", "ಸುಟ್ಟು", "ಸಮಸ್ಯೆ", "ಬಿಸಿ",
)


def looks_like_transformer_enquiry(text: str) -> bool:
    """True when this message is about a transformer at all.

    Two independent routes. The lead-form route is exact and is what the ad
    traffic arrives as. The keyword route catches organic enquiries and the
    people who message again later without the form payload — and it requires
    a SUBJECT word or an explicit kVA figure, never a bare "price?".
    """
    low = (text or "").lower()
    if not low.strip():
        return False
    if any(s in low for s in _SUBJECT):
        return True
    return bool(_KVA_RE.search(low)) or _kv_as_kva(low) is not None


def is_lead_form(text: str) -> bool:
    """True for a Meta Lead Ads handoff, whatever it is about.

    The marker phrase comes from Meta's own template, so it is English even
    when the form is Kannada — and it changes if the template changes. The
    structural fallback recognises the handoff by its SHAPE instead: several
    "label: answer" lines, of which at least two carry labels we know. That
    does not depend on Meta's wording, and it is deliberately narrow — two
    recognised labels is more than a customer types by accident.
    """
    low = (text or "").lower()
    if any(m in low for m in _LEAD_FORM_MARKERS):
        return True
    return _looks_structurally_like_a_form(low)


def _looks_structurally_like_a_form(low: str) -> bool:
    labelled = [l for l in low.splitlines() if ":" in l]
    if len(labelled) < 3:
        return False
    hits = 0
    for field, keys in _FIELD_PATTERNS.items():
        for line in labelled:
            label = line.partition(":")[0]
            if any(_label_matches(label, k) for k in keys):
                hits += 1
                break
    return hits >= 2


def requirement_type(text: str) -> str:
    """NEW_UNIT or REPAIR, read from the enquiry (AC-02).

    NEW_UNIT is the default because that is what the ad sells and what a lead
    form means. A repair signal has to be present to override it — the wrong
    direction here costs either a needless dispatch or a delayed fault.
    """
    low = (text or "").lower()
    if is_lead_form(low):
        # A capacity-and-timeline form is a purchase enquiry by construction.
        return NEW_UNIT
    return REPAIR if any(h in low for h in _REPAIR_HINTS) else NEW_UNIT


# ── Parsing ───────────────────────────────────────────────────────────────
# The five labels present in all 16 production messages. Matched on a
# distinctive Kannada substring rather than the whole question, so a reworded
# form still parses.
# THE FORM'S QUESTION LABELS, in both languages.
#
# Three of these five used to be matched in Kannada ONLY, so rebuilding the
# Meta form in English would have left capacity, timing and location
# unreadable — messages arriving normally while every useful field came
# through blank. That is a worse failure than an outage, because it looks
# like working software.
#
# Ordered most specific first: _field takes the FIRST line whose label
# matches, so a bare "name" ahead of "full name" would happily return the
# answer to "Company name".
_FIELD_PATTERNS = {
    "name": ("full name", "ಹೆಸರು", "your name", "customer name", "name"),
    "phone": ("phone number", "ದೂರವಾಣಿ", "mobile number", "contact number",
              "whatsapp number", "phone", "mobile"),
    "capacity": ("ಸಾಮರ್ಥ್ಯ", "capacity", "kva", "rating", "transformer size",
                 "size"),
    "timing": ("ಯಾವಾಗ", "when do you", "when", "timeline", "how soon",
               "required by", "urgency"),
    "location": ("ಸ್ಥಳ", "ಪ್ರಾಜೆಕ್ಟ್", "location", "site", "city", "place",
                 "district", "where"),
    # WHERE THE TRANSFORMER ACTUALLY GOES — owner's ruling, 2026-09-17:
    # "our brain ask place actually to delivery tc this is important."
    #
    # Distinct from `location`, which answers "where is your project". For a
    # distribution transformer the delivery site is what decides transport
    # cost and whether a crane can reach it, and it is not always the project
    # address. Listed before `location` in the delivery lookup so a form that
    # asks BOTH does not return the project address for the delivery field.
    "delivery": ("ಡೆಲಿವರಿ", "ತಲುಪಿಸ", "delivery location", "delivery place",
                 "delivery address", "delivery point", "deliver to",
                 "delivery site", "unloading", "delivery"),
}

# Timing options, mapped to a coarse urgency the owner can triage on. The
# labels are the customer's own choices; the mapping adds no judgement beyond
# the ordering the form itself implies.
# Longest / most specific first: "1-3 months" contains "3 month", and
# matching the shorter one first would report the wrong window.
_TIMING_URGENCY = (
    ("ತಕ್ಷಣ", "IMMEDIATE"),
    ("immediate", "IMMEDIATE"),
    ("urgent", "IMMEDIATE"),
    ("1–3 ತಿಂಗಳ", "WITHIN_3_MONTHS"),
    ("1-3 ತಿಂಗಳ", "WITHIN_3_MONTHS"),
    ("1–3 month", "WITHIN_3_MONTHS"),
    ("1-3 month", "WITHIN_3_MONTHS"),
    ("3 month", "WITHIN_3_MONTHS"),
    ("1 ತಿಂಗಳ", "WITHIN_1_MONTH"),
    ("1 month", "WITHIN_1_MONTH"),
    ("within a month", "WITHIN_1_MONTH"),
    ("ಮಾಹಿತಿ", "INFORMATION_ONLY"),
    ("information", "INFORMATION_ONLY"),
    ("price list", "INFORMATION_ONLY"),
    ("quotation only", "INFORMATION_ONLY"),
    ("just looking", "INFORMATION_ONLY"),
)


def _label_matches(label: str, key: str) -> bool:
    """Does this question label carry this key?

    WORD BOUNDARIES, NOT SUBSTRINGS, for ASCII keys. "city" is a substring of
    "capacity", so plain containment read the answer to "Transformer capacity
    required" as the project location — a wrong field, silently, on a form
    that looked perfectly normal.

    Kannada keys stay substring matches: the script has no ASCII word
    boundaries to anchor on, and its labels do not collide.
    """
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", label) is not None
    return key in label


def _field(text: str, keys) -> str:
    """The answer on the first `label: answer` line matching any key."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        label, _, answer = line.partition(":")
        low = label.lower()
        if any(_label_matches(low, k) for k in keys):
            return answer.strip()
    return ""


def _kv_as_kva(text: str):
    """A "kv" figure that is safe to read as kVA, or None.

    Safe means: it is a capacity in the known product range. See _KV_RE for
    why a looser rule would misread 11 kV as 11 kVA.
    """
    for m in _KV_RE.finditer(text or ""):
        n = int(m.group(1))
        if n in CATALOGUE_KVA or n in PLANNED_KVA:
            return n
    return None


# kV IN KANNADA LETTERS. "25 ಕೆವಿ ದರ ಏನಿದೆ" (what is the 25 kV rate?) was
# read on 2026-09-23 as a quantity of TWENTY-FIVE units and no capacity at
# all. The unit is the same unit this module already reads in Latin letters,
# so it is rewritten to that spelling before the existing patterns run —
# longest spelling first, so "ಕೆವಿಎ" is not half-consumed as "ಕೆವಿ".
_KANNADA_KV = (("ಕೆ.ವಿ.ಎ", "kva"), ("ಕೆ ವಿ ಎ", "kva"), ("ಕೆವಿಎ", "kva"),
               ("ಕೆ.ವಿ", "kv"), ("ಕೆ ವಿ", "kv"), ("ಕೆವಿ", "kv"))


def _latin_kv(text: str) -> str:
    for kannada, latin in _KANNADA_KV:
        text = text.replace(kannada, latin)
    return text


def capacity_kva(text: str):
    """The kVA figure, or None when it cannot be read confidently.

    None is a correct answer and a human then confirms it. Returning a nearby
    catalogue size would be the confidently-wrong capacity AC-07 forbids.
    """
    answer = _latin_kv(_field(text, _FIELD_PATTERNS["capacity"]) or (text or ""))
    m = _KVA_RE.search(answer)
    if m:
        return int(m.group(1))
    # "kv" for kVA, accepted only inside the known product range.
    return _kv_as_kva(answer)


def sku_status(kva) -> str:
    """The AC-04 status for a capacity. Three outcomes, not two.

    SUPPORTED_PRODUCT  currently manufactured (25/63/100/250)
    ROADMAP            declared future capacity (500) — offered by the ad on
                       purpose, and not claimed as available
    VERIFY             anything else, including an unreadable capacity

    All three of the non-supported values are gated out of automatic
    quotation and routed for confirmation, so the practical handling is the
    same; what differs is what the owner is told, and whether the customer is
    left thinking a planned product is a stocked one.
    """
    if kva in CATALOGUE_KVA:
        return SUPPORTED
    if kva in PLANNED_KVA:
        return ROADMAP
    return VERIFY


def urgency(text: str):
    """Coarse urgency from the FORM's own timing option, else None.

    Never inferred from free prose. For a service call §6.2a is explicit that
    urgency must be asked, and this returns None there so the caller asks.
    """
    answer = _field(text, _FIELD_PATTERNS["timing"])
    if not answer:
        return None
    # Case-folded: the Kannada options are caseless, so this comparison was
    # never exercised until English options existed — and "Immediately" does
    # not contain "immediate" until it is lowered.
    low = answer.lower()
    for needle, value in _TIMING_URGENCY:
        if needle in low:
            return value
    return None


def parse(text: str) -> dict:
    """The normalized view of an enquiry. Never replaces the original text.

    Every field may be None. The caller stores `raw` verbatim regardless, so
    nothing the customer said is lost to a parse failure.
    """
    kva = capacity_kva(text)
    is_form = is_lead_form(text)
    raw_loc = _field(text, _FIELD_PATTERNS["location"]) or None
    loc, form_app = _form_location(raw_loc)
    # THE CUSTOMER'S OWN NAME IN THE LOCATION FIELD. On 2026-09-27 a customer
    # answered "where is the project?" with "Shivakumar sadashiva ambi" — his
    # own name (Full name: "shivakumar s ambi") — and the bot asked to deliver
    # to it. Compared with the form's own name answer only: no place list.
    if loc and _is_the_name(loc, _field(text, _FIELD_PATTERNS["name"])):
        loc = None
    # A PLACE WRITTEN BELOW THE FORM. On 2026-09-26 a customer left the
    # location answer empty and typed "ಮುದಿಗೆರೆ ಅಜ್ಜಂಪ" on its own line after
    # the last answer; the bot then asked "which place?". Only when the form's
    # own answer is empty, only unlabelled lines after the greeting, and only
    # if the existing place checks accept every one — no new vocabulary.
    if is_form and loc is None:
        extra = _unlabelled_form_lines(text)
        if extra and all(_is_place_like(x) for x in extra):
            loc = ", ".join(extra)
    delivery = _field(text, _FIELD_PATTERNS["delivery"]) or None
    urg = urgency(text)

    # A FORM THAT PARSES NOTHING IS A CONFIGURATION CHANGE, NOT A SHY
    # CUSTOMER. A Meta form always carries a capacity, a location and a
    # timing answer — they are its questions. If all three come through blank,
    # the form's labels have been rewritten, not left empty, and every
    # downstream field will be TBD until somebody notices.
    #
    # On 2026-09-17 that class of failure cost a day of guessing. It now says
    # so in the owner alert rather than presenting a page of blanks.
    form_unreadable = (bool(is_form) and kva is None and raw_loc is None
                       and urg is None)

    return {
        "raw": text or "",
        "from_lead_form": is_form,
        "form_unreadable": form_unreadable,
        "requirement": requirement_type(text),
        "family": FAMILY,
        "capacity_kva": kva,
        "sku": f"BTS-{kva}" if kva in CATALOGUE_KVA else None,
        "sku_status": sku_status(kva),
        # Two independent questions, deliberately not collapsed: is it made
        # today, and is it a capacity we have declared at all?
        "in_catalogue": kva in CATALOGUE_KVA,
        "planned": kva in PLANNED_KVA,
        "quantity": None,          # never present in the ad form — must be asked
        "location": loc,
        # None when the form does not ask. The reply then asks, because the
        # project address is not a safe stand-in for the delivery address.
        "delivery_location": delivery,
        "name": _field(text, _FIELD_PATTERNS["name"]) or None,
        "urgency": urg,
        # §6.2 field 6 — asked, strongest early signal. Also read from the
        # location field when the customer put their purpose there.
        "application": form_app,
    }


def _name_words(text) -> set:
    """Lower-case words of 3+ letters, invisible characters removed."""
    clean = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", str(text or "")).lower()
    return {w for w in re.findall(r"[^\W\d_]+", clean) if len(w) >= 3}


def _is_the_name(location, name) -> bool:
    """True when a location answer is, in the main, the customer's name:
    at least two of its words, and at least half of them, are name words."""
    loc_w, name_w = _name_words(location), _name_words(name)
    shared = loc_w & name_w
    # Or it IS the whole name: "Jagadish" for "Jagadish R" (live ...0962).
    # One shared word of a longer name stays a place ("Shivakumar").
    return bool(loc_w) and (loc_w == name_w
                            or (len(shared) >= 2 and 2 * len(shared) >= len(loc_w)))


def _unlabelled_form_lines(text: str) -> list:
    """Non-empty lines of a lead form that are not `label: answer` lines,
    skipping the first line (the form's own greeting)."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return [l for l in lines[1:] if ":" not in l]


def _form_location(value):
    """(location, application) from the ad form's location answer.

    THE FORM'S LOCATION FIELD IS FREE TEXT, AND CUSTOMERS ANSWER A DIFFERENT
    QUESTION IN IT. Two real forms on 2026-09-23:
        "home"          -> echoed back as "📍 ಸ್ಥಳ: home", then "deliver to home?"
        "ಅಗ್ರಿಕಲ್ಚರ್"   -> "📍 ಸ್ಥಳ: ಅಗ್ರಿಕಲ್ಚರ್" — the PURPOSE, in the place slot
    The same filter that decides whether a chat reply names a place decides
    here, so the two can never disagree. A purpose is kept as the purpose;
    anything else that is not a place is dropped, and the reply then asks
    where rather than confirming nonsense.
    """
    if not value:
        return None, None
    low = value.lower()
    app = _application_of(low)
    if app and not _is_place_like(value.strip(_TRIM)):
        # "Agriculture Kanakagiri" (live ...2829): the purpose AND the place.
        # Words that are themselves a purpose are removed; the rest may be
        # the place, judged by the same filter.
        rest = " ".join(w for w in value.split() if not _application_of(w.lower()))
        if rest and rest != value and _is_place_like(rest.strip(_TRIM)):
            return rest.strip(_TRIM), app
    if _is_place_like(value.strip(_TRIM)):
        return value, app
    return None, app


# ── Conversation continuity ───────────────────────────────────────────────
#
# THE BUG THIS CLOSES, MEASURED ON THREE REAL CUSTOMERS (2026-09-15)
# ------------------------------------------------------------------
# The first reply was correct for all three. Then two of them answered it and
# the bot contradicted itself:
#
#   BOT       (Bairavi) "…how many units? what purpose?"
#   CUSTOMER  "1 unit / Agricultural"
#   BOT       "ಕ್ಷಮಿಸಿ, ನಾವು Transformer ಕಂಪನಿ ಅಲ್ಲ" — we are NOT a transformer company
#
#   BOT       (Bairavi) "…"
#   CUSTOMER  "ನಮ್ಮಲ್ಲಿ ಲಯನ್ ದೂರ ಇದೆ ಕಾರಣ ಟಿ ಸಿ ಬೇಕಾಗಿದೆ" — we need a TC
#   BOT       "transformer matters are outside our scope"
#
# looks_like_transformer_enquiry() is evaluated PER MESSAGE. "1 unit",
# "Agricultural" and "Rate" carry no subject word and no kVA figure, so they
# fell past this branch into Asthra's off-topic guard.
#
# The reply itself causes it: it ends by asking two questions, which
# guarantees the next message is a short answer with no keyword in it. The
# design assumed every message is self-identifying, and that stops being true
# the moment the bot asks anything.
#
# NO NEW STATE. The branch already writes FLOW_MARKER as the assistant row,
# and fetch_context returns the last 20 turns including assistant messages —
# so the conversation already remembers. A second store would be a second
# truth that can disagree with the transcript.
FLOW_MARKER = "[Bairavi transformer reply]"

# Words that mean the customer has moved to Asthra's actual business. A
# transformer buyer who later wants a website is a real case, and stickiness
# must not trap them — the flow is sticky, not a prison.
_ASTHRA_EXIT = (
    "website", "web site", "social media", "instagram", "facebook page",
    "election", "chatbot", "app develop", "mobile app", "seo", "logo",
    "poster", "branding", "digital marketing", "ಜಾಹೀರಾತು", "ವೆಬ್‌ಸೈಟ್",
)


def wants_asthra_instead(text: str) -> bool:
    """True when the message is plainly about Asthra's services, not a
    transformer. Checked only to LEAVE the flow, never to enter it."""
    low = (text or "").lower()
    return any(w in low for w in _ASTHRA_EXIT)


def in_transformer_flow(history) -> bool:
    """True when an earlier turn in THIS conversation took the Bairavi branch.

    Read from the transcript rather than a flag, so it cannot drift out of
    step with what the customer was actually told. The window is whatever
    history the context already carries — a natural bound, not an invented
    timeout.
    """
    for msg in history or []:
        if (msg.get("role") == "assistant"
                and FLOW_MARKER in (msg.get("content") or "")):
            return True
    return False


# ── Follow-up capture ─────────────────────────────────────────────────────
# The two fields the ad form never carries and the first reply asks for. The
# answers arrived and were thrown away; now they are read.

# A NUMBER FOLLOWED BY A UNIT OF MEASUREMENT IS NOT A COUNT.
#
# The unit word here is optional, and must stay optional: a customer
# asked "how many?" answers "2", and that 2 is a real order. But with
# nothing else to stop it, ANY one-to-three digit number in the message
# became the quantity. Two real conversations on 2026-09-22:
#
#   "25 kv. 15 hp"                 -> 15 units   (15 hp is the PUMP motor)
#   "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ"            ->  5 units   (5 km is a DISTANCE)
#
# Quantity is the number a quotation is multiplied by, so this is the
# most expensive misread available here — the second customer was
# quoted for five transformers while describing how far away the village
# was. The fix is narrow on purpose: a figure is rejected only when the
# text right after it names a unit that CANNOT be a count. Everything
# else parses exactly as before.
#
# This names no places and adds no geography.
_MEASUREMENT_UNIT = (
    # motor rating — the one that produced "15 units"
    "hp", "bhp", "ಎಚ್\u200cಪಿ", "ಎಚ್ ಪಿ",
    # distance — the one that produced "5 units"
    "km", "kms", "ಕಿಮೀ", "ಕೀ ಮೀ", "ಕಿ ಮೀ", "ಕಿಲೋಮೀಟರ್", "ಕೀಮೀ",
    "meter", "metre", "mtr", "ft", "feet", "ಅಡಿ", "ಮೀಟರ್",
    # electrical — kv/kva were already handled by an ad-hoc span test,
    # which this table replaces
    "kv", "kva", "kw", "kwh", "mva", "volt", "volts", "amp", "amps",
    "ಕೆ.ವಿ.ಎ", "ಕೆ ವಿ ಎ", "ಕೆವಿಎ", "ಕೆ.ವಿ", "ಕೆ ವಿ", "ಕೆವಿ",
    "hz", "phase", "ಫೇಸ್",
    # land area, common in an agricultural enquiry
    "acre", "acres", "guntha", "gunta", "ಎಕರೆ", "ಗುಂಟೆ",
)

# WHY EACH ALTERNATIVE CARRIES ITS OWN LOOKAHEAD, not one trailing \b:
# Python's \b is a \w/non-\w transition, and the Kannada virama
# (U+0CCD, the last character of "ಯುನಿಟ್") is a combining mark, which is
# not \w. A trailing \b can therefore never match after it, so the two
# Kannada unit words never actually matched — a latent bug masked by the
# optional suffix, since the bare number matched instead.
_QTY_RE = re.compile(
    r"\b(?P<n>\d{1,3})\s*(?:"
    r"units?(?![a-z])|nos?(?![a-z])|pcs?(?![a-z])|pieces?(?![a-z])"
    # Permissive: Kannada inflects, and "2 ಯುನಿಟ್ಗಳು" is the natural
    # plural. A number immediately before this stem is a count.
    r"|ಯುನಿಟ್"
    # Strict: "ನಗ" is a prefix of "ನಗರ" (city), which appears in real
    # addresses, so it must be the whole word.
    r"|ನಗ(?![\u0C80-\u0CFF])"
    r")?", re.IGNORECASE)


_NOT_TRANSFORMERS = ("ಕಂಬ", "ಕಹಬ", "ಕಂಭ", "kamba", "kamb", "pole", "ಪೋಲ್",
                     "acre", "ekare", "ಎಕರೆ", "gunte", "ಗುಂಟೆ", "wire", "ವೈರ್")


def _read_quantity(low: str, cap=None):
    """How many units this text states, or None.

    ONE READER, TWO CALLERS. `parse_followup` needs the number; the delivery
    filter needs only to know whether there IS one, because a quantity answer
    is not a place. They used to disagree: the filter tested the raw regex,
    which matched any bare figure, so "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ" looked like a
    quantity answer and the address inside it was thrown away.
    """
    for m in _QTY_RE.finditer(low):
        n = int(m.group("n"))
        if not (0 < n <= 999) or n == cap:
            continue
        # AN EXPLICIT UNIT WORD WINS. If the customer named the unit
        # themselves — "2 units", "2 ಯುನಿಟ್" — the figure is a count and
        # nothing after it can change that. Found by a mutation: without
        # this, "2 ಯುನಿಟ್ ಕೀ ಮೀ" returned NO quantity, because the match
        # consumed the unit word and the measurement test then read the
        # "ಕೀ ಮೀ" that followed it. The customer had said "units" out loud.
        stated_unit = m.group().strip()[len(m.group("n")):].strip()
        # GLUED TO A WORD WE DO NOT RECOGNISE. "1st main road" was reading
        # as one unit, because the figure matched and the optional unit word
        # matched nothing, leaving "st". An ordinal, a house number or a
        # model number is written without a space; a count is not.
        digits_end = m.start() + len(m.group("n"))
        # PART OF A LONGER RUN OF DIGITS. The owner sent their own phone
        # number, 8884448141, and it was recorded as "888 units" — the
        # pattern takes at most three digits and there was nothing to stop
        # it biting the front off a ten-digit number. A count is a whole
        # number, not the first three digits of one.
        if low[digits_end:digits_end + 1].isdigit():
            continue
        before = low[m.start() - 1] if m.start() else ""
        if before == "+" or before.isdigit():
            continue
        if not stated_unit and low[digits_end:digits_end + 1].isalpha():
            continue
        # A NUMBERED LIST, NOT A COUNT. On 2026-09-24 a customer answered the
        # three questions as "1. near 3km. / 2. Agriculture. / 3. 25kv" and
        # was recorded as ordering 1 unit — the "1." that numbered their
        # first answer. A figure that opens a line and is followed by "." or
        # ")" is a list marker.
        line_start = low.rfind("\n", 0, m.start()) + 1
        if (not stated_unit and not low[line_start:m.start()].strip()
                and low[digits_end:digits_end + 1] in (".", ")")):
            continue
        if not stated_unit:
            # WHAT FOLLOWS A BARE FIGURE. The old test looked five characters
            # past the match for "kv" only, which is why "15 hp" and
            # "5 ಕೀ ಮೀ" got through. The table is consulted at the start of
            # the remaining text, so "15 hp" is a rating and "15 units" is
            # still fifteen.
            rest = low[m.end():].lstrip(" \t.-")
            if any(rest.startswith(u) for u in _MEASUREMENT_UNIT):
                continue
            # OTHER THINGS BEING COUNTED. "32 ಕಹಬ" (32 poles, ಕಂಬ misspelt;
            # live ...4109) was recorded as 32 transformers.
            if any(rest.startswith(u) for u in _NOT_TRANSFORMERS):
                continue
        return n
    # A COUNT IN WORDS. "Agriculture / Single unit" (2026-09-24) was stored as
    # the delivery address "Single unit". Only a number word WITH a unit word
    # after it, or "single" on its own, is read: "one" alone appears in
    # ordinary sentences and says nothing about how many.
    w = _WORD_QTY_RE.search(low)
    if w:
        return _WORD_QTY[w.group("w") or "single"]
    return None


_WORD_QTY = {"single": 1, "one": 1, "ondu": 1, "ಒಂದು": 1,
             "two": 2, "eradu": 2, "ಎರಡು": 2, "three": 3, "mooru": 3, "ಮೂರು": 3}
_WORD_QTY_RE = re.compile(
    r"(?<![\w\u0C80-\u0CFF])(?P<w>" + "|".join(_WORD_QTY) + r")\s*"
    r"(?:units?(?![a-z])|nos?(?![a-z])|tc(?![a-z])|transformers?(?![a-z])|ಯುನಿಟ್|ಟಿಸಿ)"
    r"|(?<![\w\u0C80-\u0CFF])(?P<single>single)(?![a-z])")

# Application vocabulary, English and Kannada. An allowlist: an unrecognised
# purpose stays None rather than being guessed, because "what it is for"
# drives qualification and a wrong value is worse than a blank one.
_APPLICATIONS = (
    # EV charging first, and unambiguous. Added because a real customer
    # answered "Charging Station ⛽" on 2026-09-17 and it read as no purpose at
    # all — the list offered them agriculture/industry/construction/tender, so
    # they went off-menu for a use case that was simply missing.
    ("charging", "EV_CHARGING"), ("ಚಾರ್ಜಿಂಗ್", "EV_CHARGING"),
    ("ev station", "EV_CHARGING"),
    ("agricultur", "AGRICULTURE"), ("agri", "AGRICULTURE"),
    ("ಕೃಷಿ", "AGRICULTURE"), ("pump", "AGRICULTURE"),
    # ಕೃಷಿ as typed without the vowel sign ಋ (live ...3350, 2026-10-01: "ಕ್ರುಷಿ"
    # twice, unread both times, answered by a company introduction).
    ("ಕ್ರುಷಿ", "AGRICULTURE"), ("ಕ್ರಷಿ", "AGRICULTURE"),
    # THE SAME WORDS AS CUSTOMERS TYPE THEM, 2026-09-23. Two real answers to
    # "what is it for?" were not read at all:
    #   "ಬೋರ್ ವೆಲ್ ಉದ್ದೇಶ" (borewell purpose) — stored as the DELIVERY address
    #   "ಅಗ್ರಿಕಲ್ಚರ್"       (agriculture, in Kannada letters) — asked again
    # A borewell pump is the commonest farm load there is. The English loan
    # words written in Kannada script are the same vocabulary this list
    # already holds in Latin — not transliteration, and no place names.
    ("borewell", "AGRICULTURE"), ("bore well", "AGRICULTURE"),
    ("ಬೋರ್ ವೆಲ್", "AGRICULTURE"), ("ಬೋರ್‌ವೆಲ್", "AGRICULTURE"),
    ("ಬೋರ್ವೆಲ್", "AGRICULTURE"), ("ಕೊಳವೆ ಬಾವಿ", "AGRICULTURE"),
    # "ಅಗ್ರಿ" is the stem and covers "ಅಗ್ರಿಕಲ್ಚರ್"; a separate entry for the
    # full word was dead weight, and a mutation removing it changed nothing.
    ("ಕೊಳವೆಬಾವಿ", "AGRICULTURE"),
    ("ಅಗ್ರಿ", "AGRICULTURE"), ("ಪಂಪ್", "AGRICULTURE"),
    ("ನೀರಾವರಿ", "AGRICULTURE"), ("irrigation", "AGRICULTURE"),
    ("ವ್ಯವಸಾಯ", "AGRICULTURE"),
    # After the agriculture needles on purpose: a "solar pump" is a farm
    # load, while a "solar plant" is its own segment.
    ("solar", "SOLAR"), ("ಸೋಲಾರ್", "SOLAR"),
    ("industr", "INDUSTRY"), ("ಕೈಗಾರಿಕೆ", "INDUSTRY"), ("factory", "INDUSTRY"),
    ("ಇಂಡಸ್ಟ್ರಿ", "INDUSTRY"), ("ಫ್ಯಾಕ್ಟರಿ", "INDUSTRY"),
    ("construct", "CONSTRUCTION"), ("ಕಟ್ಟಡ", "CONSTRUCTION"),
    ("tender", "TENDER"), ("ಟೆಂಡರ್", "TENDER"),
    ("domestic", "DOMESTIC"), ("house", "DOMESTIC"), ("ಮನೆ", "DOMESTIC"),
    ("commercial", "COMMERCIAL"), ("shop", "COMMERCIAL"),
    ("ಕಮರ್ಷಿಯಲ್", "COMMERCIAL"), ("ಶಾಪ್", "COMMERCIAL"),
    ("ಕನ್ಸ್ಟ್ರಕ್ಷನ್", "CONSTRUCTION"),
)

# QUANTITY DEFAULT — owner's ruling, 2026-09-17.
#
# "quantity is not must important. just ask them, if they don't tell anything
# assume it as single quantity only."
#
# So quantity is asked once in the opening reply and never chased. An
# unanswered quantity is ONE unit, which is the common case for a distribution
# transformer enquiry.
#
# WHAT THIS DOES NOT DO: it does not write 1 into the parsed fields. "The
# customer said one" and "the customer said nothing, so we assume one" are
# different facts, and the second is the one where a salesperson should
# confirm before quoting five. The parse keeps reporting None; the assumption
# is applied where a number is needed, and every place it surfaces says it was
# assumed.
DEFAULT_QUANTITY = 1

# WHOLE WORD ONLY. On 2026-09-23 "Ev ge" (for EV) was not read as a purpose,
# because only "charging" and "ev station" were known. "ev" cannot join the
# substring list above: it sits inside Devanahalli, Bevinahalli, every, never
# and level, and would read half the map as a charging station.
_APPLICATIONS_WHOLE_WORD = (("ev", "EV_CHARGING"),
                            # ಕೃಷಿ typed in English letters (2026-09-25:
                            # "Krushi", "Krusshi" were not understood and the
                            # purpose was asked twice more).
                            ("krushi", "AGRICULTURE"), ("krishi", "AGRICULTURE"),
                            ("krusshi", "AGRICULTURE"), ("krusi", "AGRICULTURE"),
                            ("kurshi", "AGRICULTURE"), ("krushi ge", "AGRICULTURE"),
                            ("vyavasaya", "AGRICULTURE"), ("vyavasaaya", "AGRICULTURE"),
                            ("raitha", "AGRICULTURE"), ("raita", "AGRICULTURE"))

# THE FARM ITSELF. On 2026-09-24 a customer gave "thota" as the project
# location and later "ತೋಟ" as the delivery place: ತೋಟ is "farm/plantation",
# not a place name. Read as a place it was stored as the address and the
# purpose was never inferred. These words name the SITE TYPE of an
# agricultural connection — farm, field, paddy, land — so they read as the
# purpose and are rejected as an address (a village is still needed).
# Whole words only: "thota" also begins place names such as Thotadahalli.
_FARM_WORDS = ("thota", "tota", "thotha", "ತೋಟ", "ತೋಟದ", "ತೋಟಕ್ಕೆ", "ತೋಟದಲ್ಲಿ",
               "farm", "farmland", "hola", "ಹೊಲ", "ಹೊಲಕ್ಕೆ", "ಹೊಲದ",
               "gadde", "ಗದ್ದೆ", "ಗದ್ದೆಗೆ", "jameenu", "jameen", "ಜಮೀನು", "ಜಮೀನಿಗೆ", "ಜಮೀನಿನ")
_WORD_RE = re.compile(r"[a-z0-9\u0C80-\u0CFF\u200c\u200d]+")


# MISSPELT, NOT UNKNOWN. On 2026-09-24 a customer answered the purpose
# question with "Agreeculture". It was stored as the delivery ADDRESS and the
# purpose was asked again. Customers type these words by ear; a Latin word
# within two edits of a known purpose word is that word. Long words only, so
# short place names cannot drift into a purpose.
_FUZZY_PURPOSE = (("agriculture", "AGRICULTURE"), ("agricultural", "AGRICULTURE"),
                  ("irrigation", "AGRICULTURE"), ("borewell", "AGRICULTURE"),
                  ("industrial", "INDUSTRY"), ("industry", "INDUSTRY"),
                  ("construction", "CONSTRUCTION"), ("commercial", "COMMERCIAL"),
                  ("domestic", "DOMESTIC"), ("charging", "EV_CHARGING"))
_FUZZY_MIN_LEN = 8


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, stopping early once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


# KANNADA IN LATIN LETTERS INFLECTS. "Krasige.bekku" (for farming) and
# "krushige beku" were not read (live ...1743, 2026-09-30): the whole-word
# table cannot see a stem with "-ge" on it. Stems at a word start, any ending.
_LATIN_FARM_STEM_RE = re.compile(
    r"(?<![a-z])(?:kr[ua]s{1,2}h?[iy]|krishi|kurshi|krash[iy]|raith|vyavasa|borewell)"
    # "Krish" alone (live ...1945) — but never Krishna, Krishnarajpet
    r"|(?<![a-z])krish(?![a-z])")
# "Beligalige niru hasalu" — to water the crops — is irrigation.
_WATERING_RE = re.compile(r"(?<![a-z])(?:niru|neeru|neer|nīru)\s+(?:hasal|hayis|haays|hakal|haakal|bidal)"
                          r"|ನೀರು\s*(?:ಹಾಯಿಸ|ಹಾಸ|ಹಾಕ|ಬಿಡ)")


def _application_of(low: str):
    """The purpose this text states, or None. The single reader for it."""
    # "Krasige.bekku." — dots typed between words are spaces.
    low = re.sub(r"[._]+", " ", low or "")
    if _LATIN_FARM_STEM_RE.search(low) or _WATERING_RE.search(low):
        return "AGRICULTURE"
    for needle, value in _APPLICATIONS:
        if needle in low:
            return value
    for needle, value in _APPLICATIONS_WHOLE_WORD:
        if _label_matches(low, needle):
            return value
    if any(w in _FARM_WORDS for w in _WORD_RE.findall(low)):
        return "AGRICULTURE"
    for word in re.findall(r"[a-z]+", low):
        if len(word) < _FUZZY_MIN_LEN:
            continue
        for target, value in _FUZZY_PURPOSE:
            if _edit_distance(word, target, 2) <= 2:
                return value
    return None


# Offered to the customer verbatim. Kept next to _APPLICATIONS so the list we
# SHOW can never drift from the list we can READ — the 2026-09-17 enquiry was
# offered four options and answered with a fifth.
_PURPOSE_OPTIONS = ("(agriculture / industry / construction / "
                    "EV charging / solar / tender)")

# WhatsApp keycap numerals, as whole strings. Each is three codepoints
# (digit + VS16 + combining enclosing keycap), which is why they are listed
# rather than sliced out of one string.
# Three, because the delivery question made the opening ask three items.
# zip() against a shorter tuple silently DROPS the extra question rather than
# erroring, which is exactly how the units ask disappeared once.
_NUMERALS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")

# A DELIVERY PLACE IS EXTRACTED ONLY FROM AN UNAMBIGUOUS SHAPE.
#
# Kannada puts the place BEFORE the verb — "Puttur ge deliver madi" means
# "deliver to Puttur" — so capturing whatever follows the delivery word read
# the place as "madi", the verb "do". A lorry sent to "madi" is precisely the
# confidently-wrong field AC-07 forbids, so extraction now requires either a
# colon (a form-style answer) or an explicit English preposition.
_DELIVERY_STRICT_RE = re.compile(
    r"(?:deliver(?:y)?|ಡೆಲಿವರಿ)\s*(?::|-)\s*(.{2,60})"
    r"|deliver(?:y)?\s+(?:to|at)\s+(.{2,60})", re.IGNORECASE)

# Anything that merely MENTIONS delivery. Enough to stop asking — the
# customer answered — but never enough to name a place. The owner reads their
# verbatim words, which the alert already carries.
_DELIVERY_MENTION_RE = re.compile(
    r"deliver|ಡೆಲಿವರಿ|ತಲುಪಿಸ|ಕಳಿಸ", re.IGNORECASE)

# "Same place", said in reply to "is the delivery address the same?". Only
# meaningful as a confirmation — it carries no place of its own, so the owner
# reads it against the project location the form already captured.
# CONFIRMATION, NOT AN ADDRESS. Two real customers on 2026-09-22 had the
# word "yes" recorded as the place to deliver to:
#
#   "Houdu"  -> delivery location "Houdu"   (ಹೌದು, in Latin letters)
#   "ಸೇಮ್"    -> delivery location "ಸೇಮ್"     ("same", in Kannada letters)
#
# Both spellings of both words were missing: the tuple already carried
# "ಹೌದು" in Kannada and "same" in Latin, so each word was recognised in
# exactly one of the two scripts customers actually type. This is the
# same mixed-script vocabulary the tuple always was — not a
# transliteration mechanism, and no place names are involved.
_SAME_PLACE = ("same place", "same address", "same location", "same",
               "ಸೇಮ್", "ಅದೇ ಸ್ಥಳ", "ಅದೇ", "ಹೌದು", "houdu", "howdu",
               "yes same", "same only")

# ── COMMERCIAL INTENT: TWO DIFFERENT ASKS ─────────────────────────────────
#
# "What does it cost?" and "send me a quotation" were one tuple, and they are
# not one act. A price question wants a number. A quotation request is the
# start of a commercial document — a sales process this system does not
# perform and must never claim to have performed.
#
# NEITHER can be answered with a figure. There is no authoritative Bairavi
# price source: the price list is recorded as `TBD` in the GTM source
# inventory, contradiction C-07 rules the ₹68,244 in the design package "not
# a confirmed commercial price", and §10's costing template is a FORMULA
# (factory cost × (1 + margin) + GST) whose material rates change daily and
# whose margin is a 10–18% range. A number produced from it would be an
# invention wearing a decimal point.
#
# So the split exists to change WHO ACTS, not to unlock a price:
#   PRICE_REQUEST      answer truthfully, collect what a quotation needs
#   QUOTATION_REQUEST  the same, PLUS raise the sales signal — issuing the
#                      quotation is a human process (owner ruling, D3=A)
PRICE_REQUEST = "PRICE_REQUEST"
QUOTATION_REQUEST = "QUOTATION_REQUEST"

# WHAT WAS MISSING. On 2026-09-21 a customer asked for the "Amount" and it
# was not read as a price question at all. "ಎಷ್ಟು" was already here, but it
# does not cover "ಎಷ್ಟಾಗುತ್ತೆ" — the two differ after "ಟ", so the substring
# test never matched the form people actually type.
#
# DELIBERATELY NOT ADDED: a bare "ಎಷ್ಟು" is already here and already
# ambiguous ("ಎಷ್ಟು units ಬೇಕು?" is the bot's own question), so no further
# bare quantity word joins it. Every term below can only be about money.
# WHAT CAME OUT, 2026-09-22. The bare words for "how much" — "ಎಷ್ಟು",
# "eshtu", "estu" — are also the words for "HOW MANY", and this module's own
# question is "ಎಷ್ಟು *units* ಬೇಕು?". They matched every counting question:
# "ನಿಮ್ಮ ಕಂಪನಿ ಎಷ್ಟು ವರ್ಷದಿಂದ ಇದೆ?" (how many years have you existed?) read as
# a request for a price, which answered a question nobody asked and blocked
# the answer to the real one.
#
# The compound forms stay, because each of them can only be about money:
# "ಎಷ್ಟಾಗುತ್ತೆ" (how much will it come to), "ಎಷ್ಟು ರೂ". And a bare "ಎಷ್ಟು" next
# to "ಬೆಲೆ" or "ದರ" is still caught, by those words.
_PRICE_WORDS = ("rate", "price", "cost", "ದರ", "ಬೆಲೆ",
                "amount", "how much", "howmuch", "kitna", "kitne",
                "ಎಷ್ಟಾಗುತ್ತೆ", "ಎಷ್ಟಾಗುತ್ತದೆ", "ಎಷ್ಟು ರೂ", "ಮೊತ್ತ",
                # The same English words, typed in Kannada letters (2026-09-26:
                # "ರೇಟ್" was not read as a price question, and the model then
                # told the customer it could not say the rate).
                "ರೇಟ್", "ರೇಟು", "ಪ್ರೈಸ್",
                # "ಹಣ" alone (live ...4599, 2026-10-01) got "the engineer will
                # tell you about money" instead of the price.
                "ಹಣ", "ದುಡ್ಡು", "duddu", "hana",
                # "Cast" (cost) and "Amuont" (amount), live ...3900, 2026-10-01:
                # both went to the model, which re-introduced the company.
                # Whole-word matches, so "broadcast" is unaffected.
                "cast", "amuont", "amout", "amont")
# Already the bot's own words for this: the follow-up button is titled
# "📋 ಕೋಟೇಶನ್" and its id is "quotation".
_QUOTATION_WORDS = ("quotation", "quote", "ಕೋಟೇಶನ್")

# The union, kept under its original name because two other readers depend on
# it: the bare-delivery-answer filter and the `asked_price` field, whose
# meaning ("did they ask about money at all") is unchanged.
_PRICE_ASK = _PRICE_WORDS + _QUOTATION_WORDS


def _mentions(low: str, words) -> bool:
    """Does the text contain one of these words?

    WHOLE WORDS for English (a plural "s"/"es" allowed), substrings for
    Kannada as everywhere in this module. On 2026-09-25 "Yavaga barate" —
    when will it come? — was answered with the price list, because "rate"
    sits inside "barate". Kannada script keeps substring matching: its words
    inflect, and there is no ASCII word boundary to lean on.
    """
    for w in words:
        if w.isascii():
            if re.search(rf"(?<![a-z]){re.escape(w)}(?:e?s)?(?![a-z])", low):
                return True
        elif w in low:
            return True
    return False


# ── DISCOM APPROVAL ───────────────────────────────────────────────────────
#
# On 2026-09-22 a customer asked "Sir, you have GESCOM approvel." and was
# answered with "we have received your message" and the same form questions
# again. A distribution-company approval question is not small talk: it is
# the question a serious buyer asks, because an unapproved transformer cannot
# be energised on that utility's network.
#
# THE STATUS BELOW IS OWNER-STATED EVIDENCE, 2026-09-22, in the owner's own
# words: "mescom aproval aagide gescom bescom 3 month olgade aagutte anta
# helbeku" — MESCOM approval is done; GESCOM and BESCOM will be done within
# three months; say that.
#
# NOTHING IS EXTRAPOLATED. Only these three utilities have a stated status.
# A question about any other one is answered with "our engineer will
# confirm", because inventing an approval is exactly the class of claim the
# evidence discipline forbids — the same rule that keeps a price out of this
# module. If the owner's position changes, this table changes; the reply is
# generated from it and nowhere else states it.
_DISCOM_APPROVAL_STATED = {
    "mescom": "APPROVED",
    "gescom": "IN_PROGRESS",
    "bescom": "IN_PROGRESS",
    # OWNER, 2026-10-01: "other than mscom whithin three month we get
    # permission for all others". CESC is also written CESCOM.
    "hescom": "IN_PROGRESS",
    "cesc": "IN_PROGRESS",
    "cescom": "IN_PROGRESS",
}
_DISCOM_IN_PROGRESS_ETA_KN = "3 ತಿಂಗಳೊಳಗೆ"

# Recognition vocabulary only — which utility the customer typed. Karnataka's
# distribution companies are proper nouns, and naming them here makes no
# claim about Bairavi; every claim comes from the table above.
_DISCOM_NAMES = ("mescom", "bescom", "gescom", "hescom", "cescom", "cesc",
                 "kptcl", "ಎಸ್ಕಾಂ", "escom")

# "approvel" is the customer's actual spelling, so this matches on the stem.
_APPROVAL_ASK = ("approv", "ಅನುಮೋದನೆ", "ಅಪ್ರೂವ", "empanel",
                 "vendor list", "registered vendor", "ಪರವಾನಗಿ")


def discom_approval_ask(text: str):
    """Which distribution companies an approval question named, or None.

    Returns a tuple of canonical lowercase names, empty when approval was
    asked about without naming one. None means no approval question at all,
    which is the common case and leaves every reply unchanged.
    """
    low = (text or "").lower()
    if not any(w in low for w in _APPROVAL_ASK):
        return None
    named = [d for d in _DISCOM_NAMES if d in low]
    # "cesc" is a substring of "cescom", and "escom" of every one of them.
    for broad, narrow in (("cesc", "cescom"), ("escom", "mescom"),
                          ("escom", "bescom"), ("escom", "gescom"),
                          ("escom", "hescom"), ("escom", "cescom")):
        if narrow in named and broad in named:
            named.remove(broad)
    return tuple(named)


def approval_answer_kn(asked) -> str:
    """What to tell the customer about DISCOM approval, in the bot's register.

    Generated from _DISCOM_APPROVAL_STATED, so the bot can never say more
    than the owner has said. A utility with no stated status is routed to a
    human rather than guessed at.
    """
    approved = [d for d in asked if _DISCOM_APPROVAL_STATED.get(d) == "APPROVED"]
    pending = [d for d in asked
               if _DISCOM_APPROVAL_STATED.get(d) == "IN_PROGRESS"]
    unknown = [d for d in asked if d not in _DISCOM_APPROVAL_STATED]

    # Asked without naming one: state everything that has a stated status.
    # "cescom" is CESC's other name; it is listed once.
    if not asked:
        approved = [d for d, v in _DISCOM_APPROVAL_STATED.items()
                    if v == "APPROVED" and d != "cescom"]
        pending = [d for d, v in _DISCOM_APPROVAL_STATED.items()
                   if v == "IN_PROGRESS" and d != "cescom"]

    parts = []
    if approved:
        parts.append("✅ *" + "*, *".join(d.upper() for d in approved)
                     + "* approval ಆಗಿದೆ.")
    if pending:
        parts.append("*" + "*, *".join(d.upper() for d in pending) + "* approval — "
                     + _DISCOM_IN_PROGRESS_ETA_KN + " ಆಗುತ್ತದೆ ಎಂದು "
                     "ನಿರೀಕ್ಷಿಸುತ್ತಿದ್ದೇವೆ.")
    if unknown:
        parts.append("*" + "*, *".join(d.upper() for d in unknown) + "* ಬಗ್ಗೆ "
                     "ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")
    return "\n".join(parts)


# ── QUESTIONS THIS LAYER CAN ANSWER ──────────────────────────────────────
#
# THE COMPLAINT, 2026-09-22, from the owner after testing the bot as a
# customer: "namma brain saakstu buddivantike irodu yaake simple question gu
# answer madoke oddadtide?" — the Brain has plenty of intelligence, why does
# it struggle to answer a simple question?
#
# The cause is in api/webhook.py: once in_transformer_flow() is true, every
# message goes to this module's deterministic composer and the AI is never
# reached. That gate exists for a good reason — the AI answered fifteen of
# sixteen transformer buyers with Asthra's digital-marketing menu, and there
# is no authoritative Bairavi price or specification source — so the fix is
# NOT to hand the flow to the model. An intelligent answer with no evidence
# behind it is exactly the ₹68,244 failure this module was built to prevent.
#
# The fix is to give the flow real facts. Everything below is either already
# approved customer-facing copy (the opening reply says who and where we are)
# or owner-stated evidence, and each answer is generated from one table so
# the bot can never say more than has been established.
#
# A question with no evidence behind it is answered honestly — an engineer
# will reply — AND flagged to the owner, instead of receiving the receipt
# that ignored it in production.

QUESTION_NAME = "their_name"
QUESTION_WHO = "who_we_are"
QUESTION_RANGE = "what_we_make"
QUESTION_DELIVERY_AREA = "delivery_area"
QUESTION_DELIVERY_TIME = "delivery_time"
QUESTION_UNANSWERED = "unanswered"

# WHEN WILL YOU DELIVER — owner's ruling 2026-09-24: "delivery time call
# with our team". On 2026-09-25 "Ayitu delivery Yavaga kodtira" was ignored
# and the purpose question sent instead. Detected as a WHEN word plus a
# delivery word, so "yavaga call madtira" is not mistaken for it.
_WHEN_WORDS = ("yavaga", "yaavaga", "yavag", "ಯಾವಾಗ", "when", "how many days",
               "how long", "estu dina", "eshtu dina", "ಎಷ್ಟು ದಿನ", "ಎಷ್ಟು ದಿನದಲ್ಲಿ")
_DELIVER_WORDS = ("deliver", "ಡೆಲಿವರಿ", "kodtira", "kodthira", "kodteera", "ಕೊಡ್ತೀರ",
                  "ಕೊಡುತ್ತೀರಾ", "supply", "ready", "ರೆಡಿ", "send", "kalisti", "ಕಳಿಸ್ತೀರ")
_DELIVERY_TIME_KN = ("ಡೆಲಿವರಿ ಸಮಯವನ್ನು ನಿಮ್ಮ order ವಿವರ ನೋಡಿ ನಮ್ಮ ತಂಡ ಕರೆಯಲ್ಲಿ "
                     "ಖಚಿತಪಡಿಸುತ್ತಾರೆ.")

# DELIVERY REACH — owner-stated, 2026-09-20, in the owner's own words:
# "sadyakke delivery irodu mescom limit in 2 month etaire karnataka delivery
# ide futute entire india delivey plan ide" — delivery is currently limited to
# the MESCOM area; the whole of Karnataka in two months; all India planned.
#
# THE MONTH COUNT IS DELIBERATELY NOT QUOTED TO THE CUSTOMER. "Two months"
# was true on the day it was said and becomes a false promise the moment it
# is still being sent a year later, with nothing in the code to notice. The
# serving area today does not decay, so that is what the customer is told,
# and a specific place is confirmed by a human. The owner's exact words and
# date stay here.
_DELIVERY_NOW_KN = ("ಈಗ ನಾವು *MESCOM* ವ್ಯಾಪ್ತಿಯಲ್ಲಿ ಡೆಲಿವರಿ ಮಾಡುತ್ತಿದ್ದೇವೆ. "
                    "ಕರ್ನಾಟಕದ ಉಳಿದ ಭಾಗಗಳಿಗೆ ವಿಸ್ತರಿಸುತ್ತಿದ್ದೇವೆ.")

_ASK_NAME = ("my name", "ನನ್ನ ಹೆಸರು", "who am i", "ನಾನು ಯಾರು",
             "nanna hesaru", "hesaru gotta")
_ASK_WHO = ("who are you", "who is this", "your company", "about your company",
            "about you", "company details", "where are you", "your address",
            "your factory", "ನಿಮ್ಮ ಕಂಪನಿ", "ನೀವು ಯಾರು", "ಎಲ್ಲಿದೆ",
            "ನಿಮ್ಮ ವಿಳಾಸ", "ಫ್ಯಾಕ್ಟರಿ",
            # "Ur from" (live ...1497, 2026-09-29) got "ಧನ್ಯವಾದಗಳು."
            "ur from", "you from", "where from", "which place are you",
            # "Nimdu tc yav company du" — whose make (live ...5711) — got
            # "ಧನ್ಯವಾದಗಳು."; the answer is that we manufacture it.
            "yav company", "yaav company", "which company", "company yavdu",
            "which brand", "yav brand", "ಯಾವ ಕಂಪನಿ", "yavdu company",
            "ಎಲ್ಲಿಂದ", "ಎಲ್ಲಿಯವರು", "ellinda", "ellinavru", "ellinavaru")
_ASK_RANGE = ("what do you make", "what do you manufacture", "which models",
              "what models", "your range", "available sizes", "which kva",
              "what kva", "which capacity", "your products",
              "ಯಾವ ಮಾಡೆಲ್", "ನಿಮ್ಮ range", "ಎಷ್ಟು kva ಇದೆ", "ಉತ್ಪನ್ನ")
_ASK_DELIVERY_AREA = ("do you deliver", "can you deliver", "deliver to",
                      "delivery available", "do you supply", "supply to",
                      "outside karnataka", "other state", "all india",
                      "ಡೆಲಿವರಿ ಇದೆಯಾ", "ಡೆಲಿವರಿ ಮಾಡುತ್ತೀರಾ", "ಕಳಿಸುತ್ತೀರಾ",
                      "ಸಪ್ಲೈ ಮಾಡುತ್ತೀರಾ",
                      # "ಲೊಕೇಶನ್ all ಓವರ್ ಕರ್ನಾಟಕ ನ" (live ...1709, 2026-10-01)
                      "all over karnataka", "all karnataka", "whole karnataka",
                      "ಓವರ್ ಕರ್ನಾಟಕ", "ಎಲ್ಲಾ ಕರ್ನಾಟಕ", "ಇಡೀ ಕರ್ನಾಟಕ", "karnataka full")


def customer_question(text: str):
    """Which answerable question this message asks, or None.

    QUESTION_UNANSWERED means it IS a question and none of the evidenced
    answers fit — which is a different outcome from None, and the one the
    owner needs to see.
    """
    low = (text or "").lower()
    if any(w in low for w in _WHEN_WORDS) and any(w in low for w in _DELIVER_WORDS):
        return QUESTION_DELIVERY_TIME
    for tag, vocabulary in ((QUESTION_NAME, _ASK_NAME),
                            (QUESTION_DELIVERY_AREA, _ASK_DELIVERY_AREA),
                            (QUESTION_RANGE, _ASK_RANGE),
                            (QUESTION_WHO, _ASK_WHO)):
        if any(w in low for w in vocabulary):
            return tag
    # A question mark is the only general signal available. Kannada questions
    # often carry no punctuation at all, so this under-detects on purpose:
    # a missed question falls through to the reply it would have got anyway.
    if "?" in (text or ""):
        return QUESTION_UNANSWERED
    return None


def _range_line_kn() -> str:
    """Built from the catalogue so the sentence cannot drift from the code."""
    offered = " / ".join(f"{k} kVA" for k in CATALOGUE_KVA)
    line = f"ನಮ್ಮ standard range: *{offered}*."
    if PLANNED_KVA:
        planned = " / ".join(f"{k} kVA" for k in PLANNED_KVA)
        line += f" ({planned} ಯೋಜನೆಯಲ್ಲಿದೆ.)"
    return line


def answer_question_kn(tag, known: dict = None) -> str:
    """The evidenced answer, or an honest referral. Never an invented fact."""
    known = known or {}
    if tag == QUESTION_NAME:
        name = known.get("name")
        if name:
            return f"ಹೌದು 🙏 ನಿಮ್ಮ ಹೆಸರು *{name}*."
        return ("ಕ್ಷಮಿಸಿ — ನಿಮ್ಮ ಹೆಸರು ಇನ್ನೂ ನಮ್ಮ ಬಳಿ ಇಲ್ಲ. "
                "ತಿಳಿಸಿದರೆ ದಾಖಲಿಸುತ್ತೇವೆ.")
    if tag == QUESTION_WHO:
        return ("*Bairavi Trans Solutions* — oil-immersed 3-phase "
                "distribution transformer ತಯಾರಕರು, Kadaba, ದಕ್ಷಿಣ ಕನ್ನಡ.\n"
                + _range_line_kn() + "\n" + value_line_kn((known or {}).get("capacity_kva")))
    if tag == QUESTION_RANGE:
        return _range_line_kn()
    if tag == QUESTION_DELIVERY_TIME:
        return _DELIVERY_TIME_KN
    if tag == QUESTION_DELIVERY_AREA:
        return (_DELIVERY_NOW_KN + " ನಿಮ್ಮ ಸ್ಥಳಕ್ಕೆ ಸಾಧ್ಯವೇ ಎಂದು ನಮ್ಮ "
                "engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")
    return ("ಈ ಪ್ರಶ್ನೆಗೆ ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ಉತ್ತರಿಸುತ್ತಾರೆ — "
            "ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಅವರಿಗೆ ತಲುಪಿಸಿದ್ದೇವೆ 🙏")


def unanswered_question(followup: dict) -> bool:
    """Did this message ask something the bot could not answer?

    ONE PREDICATE, TWO READERS: the reply decides whether to add a referral
    and the owner alert decides whether to raise a flag, and they must agree.
    They did not at first — "rate eshtu?" carries a question mark, so it was
    tagged unanswered and the owner was told the question went unanswered,
    while the reply had in fact answered it with the price referral.
    """
    if followup.get("customer_question") != QUESTION_UNANSWERED:
        return False
    return (followup.get("discom_approval_ask") is None
            and not followup.get("asked_price")
            and not followup.get("asked_terms"))


# ── WHEN THE MODEL MAY SPEAK, AND WHAT IT MAY NOT SAY ─────────────────────
#
# THE OWNER, 2026-09-22: "adru check maadidaga sariyagi uttara kodtilla
# munche asthra ge clear answers bartittu" — it still does not answer
# properly; Asthra used to give clear answers. Asked twice now, so the model
# comes into this flow.
#
# WHAT MADE THAT UNSAFE BEFORE was not the model's fluency, it was that
# nothing checked what came back. The model answered fifteen of sixteen
# transformer buyers with Asthra's digital-marketing menu, and the standing
# rule at the top of this module lists what has no evidence behind it: price,
# lead time, BEE rating, certifications, losses, impedance, dimensions,
# conductor sizes, any GTP value.
#
# So this adds the missing half: the model is asked ONLY where the
# deterministic composer has nothing, and every word it returns is checked
# against that list before a customer sees it. A reply that trips the check is
# discarded, not edited — and the honest referral goes out instead.
#
# The model is NEVER asked when an evidenced answer exists. Price, DISCOM
# approval, the catalogue, delivery reach and the qualification questions all
# answer themselves, and a fluent paraphrase of a fact is a chance to get the
# fact wrong.


def should_ask_model(followup: dict, known: dict = None) -> bool:
    """True when the composer has nothing to say and a human question remains.

    Deliberately narrow. Every branch that CAN answer from evidence keeps
    answering from evidence.
    """
    # PRICE AND APPROVAL STAY DETERMINISTIC. Both are hard evidence rules
    # with carefully worded answers, and a fluent paraphrase of "we cannot
    # quote a figure" is a chance to quote one.
    if followup.get("asked_price"):
        return False
    if followup.get("discom_approval_ask") is not None:
        return False
    if followup.get("is_ack"):
        return False
    if followup.get("declined"):
        return False
    # A call time is on record: confirming it is the answer, not a paraphrase.
    if followup.get("asks_call") and (known or {}).get("callback"):
        return False
    # A missed-call complaint is answered with an apology and a person.
    if followup.get("call_missed"):
        return False
    # A price objection has an owner-approved answer (value, then sales calls).
    if followup.get("asked_discount"):
        return False
    # The owner's ruling is the answer; a model paraphrase could add a number.
    if followup.get("customer_question") == QUESTION_DELIVERY_TIME:
        return False
    # THE OTHER QUESTIONS GO TO THE MODEL FIRST, and their evidenced answers
    # become the fallback rather than the first responder. A keyword match is
    # not the same as understanding the question: "ನಿಮ್ಮ ಕಂಪನಿ ಎಷ್ಟು ವರ್ಷದಿಂದ
    # ಇದೆ?" matched the who-we-are answer, which says where we are and what
    # we make and never mentions years. The model has those same facts in its
    # brief, so it can answer the question that was actually asked and fall
    # back to "our engineer will confirm" for the part it does not know.
    # Something was read from this message, so the reply has real content and
    # the qualification is moving. No need for a model.
    for field in ("capacity_kva", "quantity", "application",
                  "delivery_location"):
        if followup.get(field):
            return False
    if followup.get("delivery_same") or followup.get("callback") or followup.get("asked_terms"):
        return False
    return True


# WHAT A GENERATED REPLY MAY NOT CONTAIN. ASCII terms are matched on word
# boundaries through _label_matches, because "bis" sits inside "business" and
# a substring test would reject an ordinary sentence. Kannada terms are
# substring-matched, as everywhere else in this module.
_REPLY_BANNED_TERMS = (
    ("iso", "a certification"),
    ("bis", "a certification"),
    ("bee", "a certification"),
    ("ce mark", "a certification"),
    ("is 1180", "a certification"),
    ("warranty", "a warranty"),
    ("guarantee", "a warranty"),
    ("ವಾರಂಟಿ", "a warranty"),
    ("ಗ್ಯಾರಂಟಿ", "a warranty"),
    ("impedance", "a specification"),
    ("no-load loss", "a specification"),
    ("load loss", "a specification"),
    ("gtp", "a specification"),
    ("discount", "a commercial term"),
    # SIZING. "100 kVA transformer ... EV charging ಗೆ suitable ಆಗಿದೆ" went to a
    # customer on 2026-09-23. Whether a rating carries a load depends on the
    # load, which nobody here has measured; that judgement is the engineer's.
    ("suitable", "a sizing claim"), ("sufficient", "a sizing claim"),
    ("enough for", "a sizing claim"), ("ಸೂಕ್ತ", "a sizing claim"),
    ("ಸಾಕಾಗುತ್ತದೆ", "a sizing claim"), ("ಸಾಕಾಗುತ್ತೆ", "a sizing claim"),
    ("ರಿಯಾಯಿತಿ", "a commercial term"),
)

# A figure next to money, or the symbol itself. The bare words for "price"
# are allowed: "ಬೆಲೆ engineer ತಿಳಿಸುತ್ತಾರೆ" says nothing and is the answer we
# want. A NUMBER beside them is the claim.
_REPLY_MONEY_RE = re.compile(
    r"₹"
    # ASCII money words take a word boundary.
    r"|\b(?:rs|inr)\b\.?\s*\d"
    r"|\d\s*(?:rs|inr|rupees?|lakhs?|crores?)\b"
    # KANNADA MONEY WORDS TAKE NONE. A trailing \b cannot match after "ರೂ":
    # it ends in a combining vowel sign, which is not a \w character, so
    # there is no \w/non-\w transition to anchor on — the same class of bug
    # that silently disabled the Kannada unit words in _QTY_RE. "ಸುಮಾರು
    # 50000 ರೂ" was therefore not read as a price.
    r"|\d\s*(?:ರೂ|ಲಕ್ಷ|ಕೋಟಿ)",
    re.IGNORECASE)

# A figure next to a unit of time, which is a lead-time or delivery-date
# claim. kVA figures are untouched because no time unit follows them.
_REPLY_LEADTIME_RE = re.compile(
    r"\d+\s*(?:day|days|week|weeks|month|months|ದಿನ|ವಾರ|ತಿಂಗಳ)",
    re.IGNORECASE)


# Kannada typed in English letters ("Sari", "Krish", "beku"): the customer
# is a Kannada speaker, and an English paragraph is the wrong answer
# (live ...1945, 2026-10-01).
_LATIN_KANNADA = ("sari", "beku", "bekku", "idi", "houdu", "haudu", "krish", "krushi",
                  "nale", "sanje", "egale", "yestu", "eshtu", "madi", "kodi", "illa",
                  "hana", "duddu", "helu", "gottilla", "ide", "agutte", "aagutte", "bantha")


def _writes_latin_kannada(text) -> bool:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return any(w in _LATIN_KANNADA for w in words)


# "We can't share the price here" — said right after the price list was sent
# (live ...1709, 2026-10-01). Prices are public in this flow; a refusal is false.
_PRICE_REFUSAL_RE = re.compile(
    r"ಹಂಚಿಕೊಳ್ಳಲು ಸಾಧ್ಯವಿಲ್ಲ|ಹೇಳಲು ಸಾಧ್ಯವಿಲ್ಲ|ತಿಳಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ|"
    r"unable to (?:discuss|share)|can(?:no|')t (?:share|discuss)|not able to (?:share|discuss)",
    re.I)


_UNKEPT_PROMISE_RE = re.compile(
    r"\bsystem\b|ವ್ಯವಸ್ಥೆ|rate list|price list|ದರಪಟ್ಟಿ|ದರ ಪಟ್ಟಿ|ಬೆಲೆಪಟ್ಟಿ|ಬೆಲೆ ಪಟ್ಟಿ",
    re.I)
_WELCOME_RE = re.compile(r"ಸ್ವಾಗತ|\bwelcome\b", re.I)
_SELF_INTRO_RE = re.compile(
    r"ತಯಾರಕರು|ತಯಾರಿಸುತ್ತೇವೆ|ತಯಾರಿಕಾ ಘಟಕ|\bmanufactur", re.I)


def reply_violates_evidence(text: str, customer_text: str = None):
    """Why this generated reply may not be sent, or None if it may.

    Returns a short reason, so a refusal can be logged and counted rather
    than silently swallowed.
    """
    raw = text or ""
    low = raw.lower()
    if not raw.strip():
        return "empty"
    if _REPLY_MONEY_RE.search(raw):
        return "a price"
    if _PRICE_REFUSAL_RE.search(raw):
        return "refuses to share a price"
    if _REPLY_LEADTIME_RE.search(raw):
        return "a delivery time"
    for term, reason in _REPLY_BANNED_TERMS:
        if term.isascii():
            if _label_matches(low, term):
                return reason
        elif term in low:
            return reason
    # NOT OUR VOICE (owner, 2026-09-25: "answer is some not good"). The model
    # replied in Kannada written in English letters and used the informal
    # "neenu" — to a customer. Both are refused; the composed reply stands.
    if re.search(r"\bneenu\b|\bninu\b|ನೀನು", low):
        return "informal address"
    _latin_kn = ("namma", "nimma", "nimage", "ide ", "madidivi", "tilisu", "tilsu",
                 "helidri", "vishaya", "khachita", "svalpa", "dhanyavada")
    kannada_chars = sum(1 for ch in raw if "\u0c80" <= ch <= "\u0cff")
    if kannada_chars < 10 and sum(w in low for w in _latin_kn) >= 2:
        return "Kannada in English letters"
    # NOT IN KANNADA AT ALL. Two customers in two days got a whole English
    # paragraph from the model ("ಅಲ್ಲಿ ಒಂದು ಹಳ್ಳಿ" -> "We are a manufacturer
    # of..."; "No thanx" -> "Thank you for reaching out..."). The bot speaks
    # Kannada with English technical words; mostly-Latin prose is not that.
    # An English reply to a customer writing English is still fine (owner
    # retest 2026-09-25); only a customer who wrote in Kannada script is owed
    # a Kannada answer.
    latin_letters = sum(1 for ch in raw if "a" <= ch.lower() <= "z")
    wrote_kannada = (any("\u0c80" <= ch <= "\u0cff" for ch in (customer_text or ""))
                     or _writes_latin_kannada(customer_text))
    if wrote_kannada and latin_letters >= 40 and kannada_chars < latin_letters:
        return "not in Kannada"
    # A PROMISE NOTHING KEEPS. "The detailed rate list will be shared with
    # you by our system" / "ದರಪಟ್ಟಿಯನ್ನು ನಮ್ಮ ವ್ಯವಸ್ಥೆ ಕಳುಹಿಸುತ್ತದೆ" (live
    # ...5879 and ...8996, 2026-10-01). No system sends a rate list; the
    # price is in the composed reply already.
    if _UNKEPT_PROMISE_RE.search(raw):
        return "promises a document nobody sends"
    # A SECOND INTRODUCTION. Mid-conversation, a one-word answer ("Cast",
    # "ಕ್ರುಷಿ", "Bellikhandi") was met with "welcome to Bairavi… we are
    # manufacturers of…" (live, 2026-10-01). The opening reply already said
    # who we are; only a customer who asks gets it again.
    # Judged only against what the customer actually wrote: without it, an
    # introduction is an ordinary answer (the live path always passes it).
    if customer_text is not None and customer_question(customer_text) not in (
            QUESTION_WHO, QUESTION_RANGE):
        if _WELCOME_RE.search(raw):
            return "welcomes the customer again"
        if _SELF_INTRO_RE.search(raw):
            return "re-introduces the company"
    # A capacity we do not offer, stated as if we do.
    for figure in re.findall(r"(\d{2,4})\s*k\s*v\s*a", low):
        if int(figure) not in CATALOGUE_KVA and int(figure) not in PLANNED_KVA:
            return "a rating we do not offer"
    return None


def model_brief_kn(known: dict = None) -> str:
    """The system prompt for a Bairavi reply, built from the same tables the
    deterministic answers use, so the two cannot disagree.

    `known` is optional and additive. With it, the brief also states what
    this conversation has ALREADY established — which stops the model asking
    for things we hold. On 2026-09-22 it asked the owner for a name and a
    mobile number while replying to that very mobile number, and the number
    they sent back was then read as a quantity of 888 units.
    """
    offered = " / ".join(f"{k} kVA" for k in CATALOGUE_KVA)
    planned = " / ".join(f"{k} kVA" for k in PLANNED_KVA)
    approved = ", ".join(d.upper() for d, v in _DISCOM_APPROVAL_STATED.items()
                         if v == "APPROVED")
    pending = ", ".join(d.upper() for d, v in _DISCOM_APPROVAL_STATED.items()
                        if v == "IN_PROGRESS")
    return (
        "ನೀವು *Bairavi Trans Solutions* ನ WhatsApp ಸಹಾಯಕ. "
        "ನಾವು oil-immersed 3-phase distribution transformer ತಯಾರಕರು, "
        "Kadaba, ದಕ್ಷಿಣ ಕನ್ನಡ.\n"
        f"ನಮ್ಮ standard range: {offered}. ಯೋಜನೆಯಲ್ಲಿ: {planned}.\n"
        f"DISCOM approval: {approved} ಆಗಿದೆ; {pending} ನಿರೀಕ್ಷೆಯಲ್ಲಿ.\n"
        "ಡೆಲಿವರಿ: ಈಗ MESCOM ವ್ಯಾಪ್ತಿ; ಕರ್ನಾಟಕದ ಉಳಿದ ಭಾಗಗಳಿಗೆ ವಿಸ್ತರಣೆ ಆಗುತ್ತಿದೆ.\n"
        "ನಮ್ಮ ವಿಶೇಷತೆ (ಮಾಲೀಕರ ಮಾತು): premium transformer, Star rating "
        "(25 kVA 4 Star; 63/100/250 kVA 5 Star), best-grade aluminium winding, "
        "ಕಡಿಮೆ ನಷ್ಟ (lower losses). ನಾವು ಹೊಸ ಕಂಪನಿ — ವರ್ಷಗಳ ಅನುಭವ ಎಂದು ಹೇಳಬೇಡಿ.\n"
        "\n"
        "ನಿಯಮಗಳು — ಇವು ಕಡ್ಡಾಯ:\n"
        "1. ಬೆಲೆಯ ಅಂಕಿ ನೀವು ಬರೆಯಬೇಡಿ — ದರಪಟ್ಟಿಯನ್ನು ನಮ್ಮ ವ್ಯವಸ್ಥೆ ಕಳುಹಿಸುತ್ತದೆ. "
        "'ದರ ಹೇಳಲು ಸಾಧ್ಯವಿಲ್ಲ' ಎಂದು ಎಂದಿಗೂ ಹೇಳಬೇಡಿ.\n"
        "2. ಡೆಲಿವರಿ ಎಷ್ಟು ದಿನ/ವಾರ/ತಿಂಗಳು ಎಂದು ಹೇಳಬೇಡಿ.\n"
        "3. ISO / BIS / BEE / certificate / warranty / guarantee ಬಗ್ಗೆ "
        "ಏನೂ ಹೇಳಬೇಡಿ.\n"
        "4. Technical ಅಂಕಿಗಳು (loss values, impedance, ಅಳತೆ, ತೂಕ, GTP) ಹೇಳಬೇಡಿ.\n"
        "5. ಮೇಲಿನ range ನಲ್ಲಿ ಇಲ್ಲದ kVA ಇದೆ ಎಂದು ಹೇಳಬೇಡಿ.\n"
        "6. ಗೊತ್ತಿಲ್ಲದಿದ್ದರೆ: 'ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ' ಎಂದು ಹೇಳಿ.\n"
        "7. ಕನ್ನಡ ಲಿಪಿಯಲ್ಲೇ ಉತ್ತರಿಸಿ (ಗ್ರಾಹಕ English ನಲ್ಲಿ ಬರೆದರೆ ಮಾತ್ರ "
        "English). English ಅಕ್ಷರಗಳಲ್ಲಿ ಕನ್ನಡ ಬರೆಯಬೇಡಿ. ಯಾವಾಗಲೂ ಗೌರವದಿಂದ "
        "'ನೀವು' ಬಳಸಿ — 'ನೀನು' ಎಂದಿಗೂ ಬೇಡ. ವೃತ್ತಿಪರ ಶೈಲಿ, 1–3 ಚಿಕ್ಕ ವಾಕ್ಯ. "
        "ಈಗಾಗಲೇ ತಿಳಿದ ವಿವರಗಳನ್ನು ಪುನರಾವರ್ತಿಸಬೇಡಿ.\n"
        "8. Asthra DigiTech ನ ಸೇವೆಗಳ ಬಗ್ಗೆ ಮಾತನಾಡಬೇಡಿ — ಇದು "
        "transformer ವಿಚಾರಣೆ.\n"
        # THE NUMBER IS THE CONVERSATION. Asking a WhatsApp customer for
        # their mobile number is asking for the thing they are speaking
        # from, and on 2026-09-22 the reply to that ask was read as a
        # quantity of 888 units.
        "9. ಗ್ರಾಹಕರ WhatsApp ನಂಬರ್ ನಮ್ಮ ಬಳಿ ಈಗಾಗಲೇ ಇದೆ. "
        "ಎಂದಿಗೂ ಫೋನ್ ನಂಬರ್ ಕೇಳಬೇಡಿ.\n"
        "10. ಕೆಳಗೆ ಈಗಾಗಲೇ ತಿಳಿದಿರುವ ವಿವರ ಇದೆ — ಅದನ್ನು ಮತ್ತೆ ಕೇಳಬೇಡಿ.\n"
        "11. ಯಾವ kVA ಯಾವ load ಗೆ ಸೂಕ್ತ/ಸಾಕು ಎಂದು ಹೇಳಬೇಡಿ — ಅದು engineer "
        "ನಿರ್ಧಾರ."
        + _known_lines_kn(known)
    )


def _known_lines_kn(known: dict = None) -> str:
    """What this conversation has already established, for the brief.

    Only fields that are actually set, so the model is never handed a blank
    to fill in or a "TBD" to repeat back at the customer.
    """
    known = known or {}
    labels = (("name", "ಹೆಸರು"), ("capacity_kva", "ಸಾಮರ್ಥ್ಯ (kVA)"),
              ("quantity", "ಎಷ್ಟು units"), ("application", "ಉದ್ದೇಶ"),
              ("location", "ಸ್ಥಳ"), ("delivery_location", "ಡೆಲಿವರಿ ಸ್ಥಳ"))
    lines = [f"   - {label}: {known[field]}"
             for field, label in labels if known.get(field)]
    if not lines:
        return "\n   (ಇನ್ನೂ ಏನೂ ತಿಳಿದಿಲ್ಲ.)"
    return "\n" + "\n".join(lines)


def compose_model_reply(ai_text: str, followup: dict, known: dict = None,
                        customer_text: str = None):
    """(reply, refusal_reason) for a generated answer.

    The guard runs FIRST, so a reply that states a price or a certification
    never reaches a customer — it is discarded whole rather than edited,
    because a sentence with the claim removed is a sentence whose meaning
    nobody checked.

    When it passes, the outstanding qualification question is appended. The
    model answers what was asked; the flow still gets what it needs, and the
    conversation does not stall just because the customer changed the
    subject for one turn.
    """
    reason = reply_violates_evidence(ai_text, customer_text)
    if reason:
        return None, reason
    lines = [(ai_text or "").strip()]
    fields = outstanding(followup, known)
    if fields:
        lines.append("\n" + question_for(fields[0], known))
    return "\n".join(lines), None


# ASKING FOR A LOWER PRICE (owner-approved 2026-09-30). Live ...4996 wrote
# "ರೇಟ್ ಕಡಿಮೆ madabeku" and was sent the same price again. The bot never
# offers a discount; it says the team will call and the owner is alerted.
_DISCOUNT_WORDS = ("discount", "negotiable", "negotiate", "best price",
                   "final price", "last price", "ಡಿಸ್ಕೌಂಟ್",
                   # THE PRICE IS TOO HIGH — the same ask, said as an objection.
                   # "Too cost" (live ...2829) got the same price again, then
                   # the model said it could not discuss figures.
                   "costly", "expensive", "dubari", "ದುಬಾರಿ", "too cost",
                   # Said straight after a quote, these ARE about the price
                   # (live ...5879, 2026-10-01: "It's very High").
                   "very high", "too high", "very costly", "ತುಂಬಾ ಜಾಸ್ತಿ")
# "less" alone is also "less than a month": these count only beside a price word.
_LOWER_WORDS = ("less", "reduce", "kadime", "kammi", "ಕಡಿಮೆ", "ಕಮ್ಮಿ",
                "too", "jasti", "ಜಾಸ್ತಿ", "heavy", "high")


def asked_discount(text: str) -> bool:
    low = (text or "").lower()
    return (_mentions(low, _DISCOUNT_WORDS)
            or (_mentions(low, _LOWER_WORDS) and _mentions(low, _PRICE_WORDS)))


def commercial_intent(text: str):
    """QUOTATION_REQUEST, PRICE_REQUEST, or None.

    Quotation outranks price: "quotation ಬೇಕು, rate ಎಷ್ಟು?" is a quotation
    request that also mentions price, and the stronger act decides. The
    reverse precedence would silently downgrade a sales signal.

    PER-TURN, NEVER STATE. Deliberately absent from _PERSISTENT_FIELDS — a
    price asked four turns ago must not make every later reply a price reply.
    """
    low = (text or "").lower()
    if _mentions(low, _QUOTATION_WORDS):
        return QUOTATION_REQUEST
    if _mentions(low, _PRICE_WORDS):
        return PRICE_REQUEST
    return None

# ── A BARE ANSWER TO THE DELIVERY QUESTION ────────────────────────────────
#
# On 2026-09-20 the bot asked where to deliver. The customer answered
# "ಗುಜರಾತ್", then "Gujarat", and neither registered: _DELIVERY_STRICT_RE
# requires a colon or an explicit "deliver to/at", so a one-word reply — the
# way people actually answer a question — read as nothing. They were asked a
# fourth time and wrote "You mad".
#
# THE CONTEXT COMES FROM THE TRANSCRIPT, NOT FROM A LIST OF PLACES. The reply
# that asked the question already recorded what it was waiting for
# (flow_marker -> "awaiting=delivery"), and marker_awaiting() already reads it
# back for the hourly nudge. So "was the previous turn a delivery question?"
# is a fact this module can consult, and no gazetteer of states and cities is
# needed to answer it. That matters: the only geography the Brain owns is the
# Karnataka `constituencies` table, which is a POLITICAL dataset behind a
# network call, has no Gujarat in it, and would make this pure module
# impure. It is deliberately not used here.
#
# WITHOUT that context a bare place name stays unreadable, exactly as before —
# "Gujarat" in the middle of a conversation about capacity is not an address.
#
# THE TWO LENGTH LIMITS THAT USED TO LIVE HERE ARE GONE. _BARE_ANSWER_MAX_WORDS
# (4) and _BARE_ANSWER_MAX_CHARS (40) were a stand-in for "does this look like
# a place", and on 2026-09-22 they rejected a 113-character address that named
# district, taluk, hobli and village. See _is_place_like.

# Short replies that are NOT an answer to "where?". Recording one of these as
# an address is the AC-07 failure in its most expensive form: a lorry sent to
# "ok". Kept deliberately broad — a rejected answer costs one more question,
# a wrong one costs a delivery.
# "kk"/"okk"/"ಓಕೆ": how "ok" is actually typed. On 2026-09-24 "kk" was
# recorded as a delivery address.
_ACKNOWLEDGEMENTS = ("ok", "okay", "k", "kk", "okk", "okey", "oky", "okie", "oki", "ok ok", "ಓಕೆ", "sari", "aytu", "ayitu", "hmm", "thanks", "thank you", "ok sir",
                     "sure", "fine", "ಸರಿ", "ಆಯ್ತು", "ಧನ್ಯವಾದ", "ಥ್ಯಾಂಕ್ಸ್",
                     "no", "illa", "ಇಲ್ಲ", "haan", "ha", "yes", "yep")

# Words that make a place name a STATEMENT about a place rather than an answer
# naming one. "I am from Gujarat" says where the customer is, not where the
# transformer goes, and the two are routinely different.
# THE SAME CLASSES, IN THE SCRIPT CUSTOMERS ACTUALLY TYPE. Every entry
# below already had its Kannada-script counterpart in this list; the Latin
# spellings were simply missing, so three real messages on 2026-09-22 were
# recorded as delivery addresses:
#
#   "Nanna hesaru gotta"          (do you know my name)
#   "Nim boss jote matadbekuttu"  (I want to talk to your boss)
#   "Nimma company estu varshadinda ide"  (how many years has your company)
#
# Pronouns, question words and the copula — no place vocabulary, and each is
# matched as a whole word, so no place name that merely contains one is
# affected.
_NOT_A_BARE_ANSWER = ("ನಾನು", "ನಮ್ಮ", "my", "our", "i", "we",
                      "am", "is", "are", "not", "ಅಲ್ಲ",
                      # pronouns and possessives
                      "nanna", "nannu", "naanu", "nanu", "namma",
                      "nimma", "nim", "neevu", "nivu", "nange", "namge",
                      # SECOND PERSON, the informal forms. "Ninage huccha" (you
                      # are mad) was stored as a delivery address on
                      # 2026-09-23, and because established facts never
                      # erase, the bot stopped asking where to deliver for the
                      # rest of that conversation.
                      "ninage", "ninge", "ninna", "ninnu", "neenu", "ninu",
                      "nin", "nimge", "nimage",
                      # question words
                      "yaaru", "yaava", "yava", "eshtu", "estu", "yake",
                      "enu", "hege", "gotta", "gothaa",
                      # copula and the commonest verbs
                      "ide", "illa", "beku", "bekagide", "madi", "helli",
                      "why", "what", "how", "ಯಾಕೆ", "ಏನು",
                      # SECOND PERSON, added after review: "You mad" — the
                      # customer's actual words on 2026-09-20 — was being
                      # recorded as a delivery address. A sentence about a
                      # person is not a place, and no place name begins "you".
                      "you", "your", "u", "ನೀವು", "ನಿಮ್ಮ")

# POSITION, NOT PRESENCE. These four were in the list above, rejected
# wherever they appeared, to catch "from Gujarat" — a statement about where
# the customer IS rather than where the transformer goes. But they are also
# how Indian addresses are built, and on 2026-09-22 that cost two real
# addresses:
#
#   "Kadaba near tumkur"           rejected — and it IS the address
#   "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ. ..."       rejected — and it IS the address
#
# Both readings are right about their own case, and what separates them is
# where the word sits. Leading, it introduces an origin: "from Gujarat".
# Inside, it locates one part of an address against another: "Kadaba near
# tumkur". So these are rejected only at the START of the answer.
#
# Deliberately conservative at the margin: a bare "near tumkur" is still
# rejected and the question is asked again, which costs one message.
_LOCATIVE_PREFIX = ("from", "near", "ಇಂದ", "ಹತ್ತಿರ")

# ── A GREETING IS NOT AN ADDRESS, HOWEVER IT IS SPELLED ───────────────────
#
# On 2026-09-22 the owner messaged the bot as a customer and the first two
# things they wrote were recorded as the place to deliver to:
#
#   "Hii"      -> delivery location "Hii"
#   "Namaste"  -> delivery location "Namaste"
#
# "hi", "hello" and "ನಮಸ್ಕಾರ" were already rejected. The comparison is
# whole-answer and exact — which it must be, since "hi" is the start of
# Hirekerur — so every other spelling walked straight through. The damage
# compounds: with delivery filled, nothing was outstanding, so every reply
# for the rest of that conversation was a receipt with no question in it,
# and a real "ಬೆಂಗಳೂರು" two turns later was ignored because the bot was no
# longer waiting for anywhere.
#
# WHY A STEM LIST AND NOT MORE LITERALS. "Hii", "Hiii" and "Hellooo" are one
# spelling habit, not three words, so runs of a repeated letter are
# collapsed before comparing. That is spelling normalisation within one
# script — it maps nothing between scripts, builds no place vocabulary, and
# is not the transliteration this module is forbidden to invent. Kannada
# greetings are listed as themselves.
_GREETING = (
    "hi", "helo", "hey", "ha", "hai", "hlo", "hola",
    "namaste", "namaskara", "namaskar", "namste",
    "ನಮಸ್ಕಾರ", "ನಮಸ್ತೆ", "ನಮಸ್ಕಾರಗಳು",
    "good morning", "good evening", "good afternoon", "gm", "ge",
)


def _collapse_runs(text: str) -> str:
    """"hiii" -> "hi", "hellooo" -> "helo". One habit, not many words."""
    out = []
    for ch in text:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _is_greeting(low: str) -> bool:
    """Is this whole answer nothing but a greeting?

    Whole-answer only, like the table it serves: "Hirekerur" contains "hi"
    and is a real place, so a substring test here would reject it.

    No trimming here. A first version stripped punctuation again, and a
    mutation removing that strip failed no test — because _TRIM has already
    taken it off upstream, in _bare_delivery_answer and for every segment,
    and a "?" is rejected before this is reached. It was dead code, so it is
    gone rather than left as an untested branch.
    """
    squeezed = _collapse_runs(low)
    greetings = {_collapse_runs(g) for g in _GREETING}
    if squeezed in greetings:
        return True
    # "Hii namaste", "hi sir good morning": several greeting words and
    # nothing else (2026-09-25 — that reply got the call-back close).
    words = [w for w in re.split(r"[\s,!.🙏]+", squeezed) if w]
    polite = greetings | {"sir", "madam", "ji", "anna", "sar", "ಸರ್"}
    return len(words) > 1 and all(w in polite for w in words) and any(w in greetings for w in words)


# ── SEMANTIC CLASSES THAT ARE NOT A PLACE ─────────────────────────────────
#
# THE REVIEW BLOCKER. The first version of this filter rejected only
# acknowledgements, pronouns and other parsed fields, and let through every
# OTHER kind of non-answer. Asked where to deliver, a customer replying
# "ತಕ್ಷಣ" (immediately), "call me", "idk", "later" or "sir" had that recorded
# as the delivery ADDRESS. The monotonicity invariant then made it permanent,
# and the quotation signal reported the requirement set complete with
# "Delivery to: ತಕ್ಷಣ" — AC-07's confidently-wrong field, reached in one turn,
# and a regression against production, which simply kept asking.
#
# REUSED, NOT REINVENTED. Three of these classes are already vocabulary in
# this module and are consulted through their existing tables:
#
#   urgency          _TIMING_URGENCY   ("ತಕ್ಷಣ", "urgent", "immediate",
#                                       "information", "price list", …)
#   price/quotation  _PRICE_ASK
#   another service  _ASTHRA_EXIT
#   confirmation     _SAME_PLACE
#
# Only the four below had no table. They are LINGUISTIC categories — how
# people decline to answer a question — not business policy, and they
# introduce no place vocabulary of any kind. There is still no gazetteer, no
# transliteration and no canonical form anywhere in this module.
#
# MATCHED AS A WHOLE MESSAGE, not as a substring, because several are also
# fragments of real place names: word-boundary matching on "anna" would
# reject Anna Nagar, and on "hi" would reject Hirekerur. A bare answer is
# short by construction, so exact comparison is the precise test.
_NOT_A_PLACE_EXACT = (
    # urgency the timing table does not carry
    "soon", "asap", "later", "today", "tomorrow", "quick", "quickly",
    "ಇವತ್ತು", "ನಾಳೆ",
    # A WHEN, NOT A WHERE (owner-approved 2026-10-01)
    "next week", "this week", "next month", "this month", "month end",
    "end of month", "end of the month", "weekend", "week end", "after a week",
    "after a month", "ಮುಂದಿನ ವಾರ", "ಈ ವಾರ", "ಮುಂದಿನ ತಿಂಗಳು", "ಈ ತಿಂಗಳು",
    "ತಿಂಗಳ ಕೊನೆ", "ತಿಂಗಳ ಕೊನೆಗೆ", "mundina vara", "mundina tingalu",
    # uncertainty — a refusal to answer, not an answer
    "idk", "dunno", "maybe", "ಗೊತ್ತಿಲ್ಲ", "ತಿಳಿದಿಲ್ಲ",
    # greeting and terms of address
    "hi", "hello", "hey", "ನಮಸ್ಕಾರ", "sir", "madam", "sar", "bro", "boss",
    "anna", "ಸರ್", "ಅಣ್ಣ",
    # The SAME four classes as single bare words. Found by a mutation that
    # widened the phrase test and did not fail: "call me" was rejected while
    # a bare "call" was stored as an address. "ಕಳಿಸಿ" (send) was the worst of
    # them — it is already a _DELIVERY_MENTION_RE word, so it set
    # delivery_mentioned AND delivery_location to the verb itself.
    "call", "phone", "message", "whatsapp", "contact", "meet", "visit",
    "send", "ಕರೆ", "ಫೋನ್", "ಕಳಿಸಿ", "ತಲುಪಿಸಿ",
    "done", "ready", "fast", "any", "ok sir", "yes sir",
    # WHAT KIND OF SITE IT IS, not where it is. A real customer answered
    # "layout" on 2026-09-22 — describing a residential layout — and had
    # it recorded as the delivery address. These are only ever rejected
    # as the WHOLE answer: "Vidyaranyapura layout" is a real place and
    # still reads, because the comparison is exact.
    "layout", "site", "plot", "farm", "land", "village", "city", "town",
    "home", "house",
    # ABUSE IS NOT AN ADDRESS — the same reasoning as a refusal to answer.
    "huccha", "huchcha", "ಹುಚ್ಚ", "mad", "stupid", "idiot", "waste",
    "fraud", "fake",
    "ಸೈಟ್", "ಜಮೀನು", "ಗ್ರಾಮ", "ಹಳ್ಳಿ", "ನಗರ",
    # "I NEED IT" IN THE PLACE SLOT (owner-approved 2026-09-30; live
    # ...3476 answered "ನನಗೆ ಬೇಕಾ ಆಗಿದಿ" and was asked to deliver there).
    "ಬೇಕು", "ಬೇಕಾಗಿದೆ", "ಬೇಕಾಗಿದಿ", "need", "needed", "required", "beku",
)

# Phrases that cannot occur inside a place name, so these may be matched
# anywhere in the message rather than only as the whole of it.
_NOT_A_PLACE_PHRASE = (
    "call me", "call back", "callback", "phone me", "whatsapp me",
    "message me", "ಕರೆ ಮಾಡಿ", "ಫೋನ್ ಮಾಡಿ",
    "dont know", "don't know", "do not know", "not sure", "no idea",
    "ನನಗೆ ಬೇಕ", "ನಮಗೆ ಬೇಕ", "i need", "we need", "nanage beku", "namage beku",
)


_TRIM = " \t\n.,!:-"

# HOW LONG AN ANSWER MAY BE WITHOUT LOOKING LIKE AN ADDRESS.
#
# Removing the 40-character/4-word caps let a full address through, which is
# what the owner asked for. It also let a whole SENTENCE through: on
# 2026-09-22 "Nimma company estu varshadinda ide" (how many years has your
# company existed) was recorded as the delivery address. The old caps would
# have rejected it on the word count — so the caps were wrong about long
# addresses and right about long sentences.
#
# Both, then. A short answer is judged as before, on the semantic filters
# alone. A LONG answer must additionally carry a word that structures an
# address: a district, a taluk, a village, a road. Those are address
# STRUCTURE words, not place names — there is still no gazetteer here, and
# "ತುಮಕೂರು", "Kadaba" and "Bengaluru" appear in no list.
# SIX WORDS AND SIXTY CHARACTERS, chosen from the real answers rather than
# picked. The pronoun and question-word list above does the semantic work;
# this is only a net for long rambling text that happens to contain none of
# those words. Set tighter, at four words, it rejected two genuine address
# forms from production — "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ" (5 km from Chelur) and
# "Chelur inda 5 km Kulumegudlu" — which is the failure the caps caused in
# the first place.
_LONG_ANSWER_WORDS = 6
_LONG_ANSWER_CHARS = 60

_ADDRESS_MARKER = (
    # Kannada administrative structure, which is how the 113-character
    # production address was written
    "ಜಿಲ್ಲೆ", "ತಾಲ್ಲೂಕು", "ತಾಲೂಕು", "ಹೋಬಳಿ", "ಗ್ರಾಮ", "ಹಳ್ಳಿ", "ನಗರ",
    "ಪೋಸ್ಟ್", "ಬಡಾವಣೆ", "ರಸ್ತೆ", "ಕ್ರಾಸ್", "ಮುಖ್ಯರಸ್ತೆ",
    # the same words as customers type them in Latin script
    "district", "dist", "taluk", "taluq", "tq", "hobli", "village",
    "post", "pin", "road", "cross", "main", "layout", "nagar", "nagara",
    "colony", "extension", "circle", "street", "gram", "halli", "pura",
)


# The strict subset of _ADDRESS_MARKER that names an administrative unit.
_ADMIN_MARKER = ("ಜಿಲ್ಲೆ", "ತಾಲ್ಲೂಕು", "ತಾಲೂಕು", "ಹೋಬಳಿ", "ಗ್ರಾಮ",
                 "district", "dist", "taluk", "taluq", "tq", "hobli",
                 "village")


def _has_address_marker(low: str) -> bool:
    """Does this text carry a word that structures an address?

    ASCII markers are matched on word boundaries — "main" must not be found
    inside "remaining" — and Kannada markers as substrings, as everywhere
    else in this module.
    """
    return any(_label_matches(low, m) if m.isascii() else m in low
               for m in _ADDRESS_MARKER)

# WHERE ONE PART OF AN ANSWER ENDS AND THE NEXT BEGINS. Customers answer
# several questions in one message, and the address is usually only part of
# it. Splitting on the separators people actually type lets the address be
# kept while the rest is passed to the extractors that own it.
#
# A full stop only separates when whitespace or the end follows it, so a
# decimal and an initial stay intact. "।" is the Devanagari danda, which
# appears in Kannada typing on some keyboards.
_SEGMENT_SPLIT = re.compile(r"[\n\r,;/|।]+|\.+(?=\s|$)")



def _is_place_like(raw: str) -> bool:
    """Could this text be the name of a place?

    LENGTH IS NO LONGER THE TEST, BUT IT IS STILL A NET. Two production
    failures, a day apart, bound this from both sides.

    A flat 40-character, 4-word ceiling was standing in for "does this look
    like a place", and it threw away the most complete address a customer can
    give:

        "ತುಮಕೂರು .ಜಿಲ್ಲೆ . ಗುಬ್ಬಿ ..ತಾಲ್ಲೂಕು... ಚೇಳೂರು ಹೋಬಳಿ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"

    113 characters — district, taluk, hobli and village, spelled out twice by
    a customer who was then asked a fifth time. Raising the ceiling only
    moves that failure to the next character.

    Removing it entirely then let a whole SENTENCE through: "Nimma company
    estu varshadinda ide" (how many years has your company existed) was
    recorded as the delivery address. So the caps were wrong about long
    addresses and right about long sentences.

    The semantic filters below do the real work, and none of them introduces
    place vocabulary: every rejection is another field's answer or a
    linguistic category — a question, an acknowledgement, a pronoun
    sentence, a greeting, a refusal to answer. Length is consulted only at
    the end, and only to require that a LONG answer carry a word which
    structures an address (see _LONG_ANSWER_WORDS). There is still no
    gazetteer, no transliteration and no canonical form.
    """
    low = raw.lower()

    # ONE LETTER IS NOT A PLACE. "A" (the form's option letter) was recorded
    # as the delivery place on 2026-10-01 (live ...3900). No village name is a
    # single letter; Kannada vowel signs are not letters, so "ಊರು" still
    # counts two.
    if len(re.findall(r"[^\W\d_]", raw)) < 2:
        return False
    # A question is not an answer — "Gujarat price?" asks something else.
    if "?" in raw:
        return False
    if _mentions(low, _PRICE_ASK):
        return False
    # An acknowledgement, a yes/no, or "same place" — the last of which is
    # already recorded as a confirmation rather than an address.
    if low in _ACKNOWLEDGEMENTS or any(w == low for w in _SAME_PLACE):
        return False
    if any(w in low for w in _SAME_PLACE):
        return False
    # A statement about a place, not an answer naming one.
    if any(_label_matches(low, w) for w in _NOT_A_BARE_ANSWER):
        return False
    # An origin, not a destination — but only when it leads (see the note on
    # _LOCATIVE_PREFIX).
    first = low.split()[0] if low.split() else ""
    if first in _LOCATIVE_PREFIX or any(low.startswith(w)
                                        for w in _LOCATIVE_PREFIX):
        return False
    # Another field's answer. Purpose, capacity and quantity all have their
    # own extractors and must not be read as a place.
    if _application_of(low) is not None:
        return False
    if capacity_kva(raw) is not None:
        return False
    # A QUANTITY ANSWER IS NOT A PLACE. Through the shared reader, not the
    # raw pattern: the raw pattern matched any bare figure, so
    # "ಚೇಳೂರು ಇಂದ 5 ಕೀ ಮೀ" read as a quantity answer and the address inside
    # it was discarded. The reader knows 5 km is a distance and 15 hp a
    # rating, so those now reach the address.
    #
    # KNOWN LIMITATION, chosen deliberately. A readable quantity ANYWHERE in
    # the text disqualifies it, so an address whose house number stands alone
    # — "No.5 Gandhi Road", "12 Hosur Road" — is rejected and the question
    # is asked again. Narrowing this to "the text is nothing but a figure"
    # was tried and reverted: it made "೧ beku" ("I want 1") read as the
    # delivery address, which is AC-07's confidently-wrong field. A re-ask
    # costs one message; a wrong address costs a delivery. Ordinals and
    # glued house numbers ("1st main road", "2nd cross") are unaffected,
    # because _read_quantity does not read a figure glued to a word.
    if _read_quantity(low) is not None:
        return False
    # A BARE MEASUREMENT IS NOT A PLACE EITHER. "15 hp" passes every other
    # filter — it is correctly not a quantity, and it does contain a letter —
    # so segmenting "Hiladahalli. Ranibennur. ... 25 kv. 15 hp" kept the
    # motor rating as part of the address. Found while testing the segment
    # capture, not in production, but it is the same class of wrong field.
    figure = re.match(r"^\s*(\d{1,4})\s*(.+)$", low.strip(_TRIM))
    if figure and figure.group(2).strip(_TRIM) in _MEASUREMENT_UNIT:
        return False
    # URGENCY, from the table that already defines it. "ತಕ್ಷಣ" answers "when
    # do you need it", which is a different question from "where".
    if any(_label_matches(low, needle) for needle, _ in _TIMING_URGENCY):
        return False
    # Another Asthra service — a transformer buyer asking about a website is
    # not naming a delivery site.
    if any(_label_matches(low, w) for w in _ASTHRA_EXIT):
        return False
    # The classes with no existing table: a whole-answer comparison for the
    # single words, and an anywhere match for the phrases.
    if low in _NOT_A_PLACE_EXACT:
        return False
    if _is_greeting(low):
        return False
    if any(p in low for p in _NOT_A_PLACE_PHRASE):
        return False
    # "yavaga call madtira" (when will you call?) is about a call, not a site.
    if asks_about_call(low):
        return False
    # Must contain an actual letter — a number or emoji is not a place.
    if not re.search(r"[^\W\d_]", raw):
        return False
    # LONG ENOUGH TO BE A SENTENCE. See _LONG_ANSWER_WORDS: a long answer is
    # accepted only when something in it structures an address.
    if (len(raw.split()) > _LONG_ANSWER_WORDS
            or len(raw) > _LONG_ANSWER_CHARS):
        return _has_address_marker(low)
    return True


_LIST_MARKER = re.compile(r"^\s*\(?\d{1,2}\s*[.)\]:-]\s*")


def _bare_delivery_answer(text: str):
    """The customer's own words as the delivery place, or None.

    Only ever called when the previous reply asked for delivery. Everything
    it cannot read as an answer returns None, which re-asks the question.
    AC-07 — a blank field is correct, a confidently wrong address is not.

    Returns the text VERBATIM whenever the whole message is an address, so a
    full address is recorded exactly as the customer wrote it, district and
    all. Only when the message carries OTHER answers too is it reduced, to
    the parts that can be an address — because a customer who writes
    "Kadaba near tumkur / Agriculture use / 1 unit" has given the address,
    and rejecting the whole message over the other two lines loses it.

    No transliteration and no canonical form: the Brain has no place-name
    mapping to canonicalise against, and inventing one here would be a
    geography policy nobody has decided.
    """
    raw = (text or "").strip(_TRIM)
    if not raw:
        return None
    # NUMBERED ANSWERS. "1) ತೋಟ / 2) agriculture / 3) 25kVA" (2026-09-24)
    # was stored as the address "1) ತೋಟ": customers number their answers to
    # match our numbered questions, and the number is not part of any place.
    segments = [seg for seg in (_LIST_MARKER.sub("", part.strip(_TRIM)).strip(_TRIM)
                                for part in _SEGMENT_SPLIT.split(raw)) if seg]
    kept = [seg for seg in segments if _is_place_like(seg)]
    # VERBATIM ONLY WHEN THE WHOLE MESSAGE IS AN ADDRESS. Both conditions are
    # needed: the message as a whole must read as a place, and so must every
    # part of it. "Hii, Bengaluru" passes the first test — nothing in it
    # disqualifies the string — and would have been stored complete with the
    # greeting. Requiring every segment to qualify keeps a full address
    # exactly as typed and still drops a greeting the customer put in front
    # of it.
    # DEFENCE IN DEPTH, and honestly labelled. No input currently
    # distinguishes the two conditions: for the whole message to fail while
    # every segment passes, a disqualifying phrase would have to span a
    # separator, and the separators are what prevent that. Proven by
    # mutation — dropping the first conjunct failed no test. It is kept
    # because the whole-message test is the one that reads across segment
    # boundaries, and a structural test asserts both are still here.
    if _is_place_like(raw) and len(kept) == len(segments) and not _LIST_MARKER.match(raw):
        return raw
    if not kept:
        return None
    return ", ".join(kept)

# YES, TO "SAME PLACE?". When the project location is known, the delivery
# question is asked as a confirmation — "ಡೆಲಿವರಿ ಇದೇ ಸ್ಥಳಕ್ಕೆ ಆ — bammanjogi?"
# — and the natural answer is "Ok". On 2026-09-23 a customer answered exactly
# that and was not understood: "ok" is rejected as an address (correctly) and
# was not a same-place word, so the bot re-introduced the company and asked
# the identical question again. Only as the WHOLE answer, only when delivery
# is awaited, and only when there is a location to be the same as.
_AFFIRMATIONS = ("ok", "okay", "ok sir", "k", "kk", "okk", "okey", "oky", "okie", "oki", "ok ok", "ಓಕೆ", "sari", "aytu", "ayitu", "yes", "yes sir", "yeah", "yep",
                 "haan", "ha", "ಸರಿ", "ಆಯ್ತು", "correct", "right", "👍",
                 "ಹೌದು", "houdu", "howdu",
                 # "Idi" (it is) confirming "is this the place?" — live
                 # ...5711, 2026-09-29, was stored as the address "Idi".
                 "idi", "ide", "ಇದಿ", "ಇದೆ", "houdu idi", "haudu idi", "ಹೌದು ಇದೆ",
                 "adhe", "ade", "ಅದೇ",
                 # "Sare" — ಸರಿ typed as it is said (live ...3188, 2026-10-02,
                 # recorded as the delivery place "Sare").
                 "sare")


# THANKS, WITH A WORD OR TWO AROUND IT. "ಧನ್ಯವಾದಗಳು ಸಿಸ್ಟಮ್" (live ...3554)
# went to the model, which answered a question nobody asked.
_THANKS_STEMS = ("thank", "thanx", "thnx", "thnks", "thanku", "tq", "ty",
                 "dhanyavad", "ಧನ್ಯವಾದ", "ಥ್ಯಾಂಕ್")
_THANKS_FILLER = {"sir", "sar", "madam", "mam", "system", "ಸಿಸ್ಟಮ್", "ಸರ್", "ji",
                  "very", "much", "so", "ok", "okay", "you", "u", "ಸರಿ", "anna",
                  "ಅಣ್ಣ", "all", "for", "info", "information", "ಮಾಹಿತಿಗೆ", "🙏"}
# "No thanks" / "not interested": a close, answered once, and flagged.
_DECLINES = ("no thanks", "no thanx", "no thank you", "no thanku", "not interested",
             "not intrested", "no need", "not needed", "beda", "ಬೇಡ", "nange beda",
             "ನಮಗೆ ಬೇಡ", "ಬೇಡ ಸರ್", "beda sir")


# "ಸರಿ ಇದೆ" (yes, that's right; live ...1709) was stored as the ADDRESS.
# A reply made only of yes-words is a yes, however they are combined.
_AFFIRMATION_WORDS = {"ಸರಿ", "ಇದೆ", "ಇದಿ", "ಹೌದು", "ಅದೇ", "ಸರಿಯಾಗಿದೆ", "ok", "okay",
                      "yes", "sari", "idi", "ide", "houdu", "haudu", "howdu", "correct",
                      "right", "same", "sir", "sar", "ಸರ್", "ji", "adhe", "ade"}


def _all_affirmation_words(bare: str) -> bool:
    words = (bare or "").split()
    return len(words) >= 2 and all(w in _AFFIRMATION_WORDS for w in words)


# Kannada written in English letters, asking "how much / which / where".
# Stems that start no Karnataka place name; "yav-" (Yavagal) and a bare "?"
# ("Kadur?") are deliberately absent.
_QUESTION_WORD_RE = re.compile(
    r"(?<![a-z])(?:yesta|yestu|eshtu|estu|yestagutt|eshtagutt|estagutt)[a-z]*(?![a-z])"
    r"|(?<![a-z])(?:yenu|enu|hege|yake|yavaga|yavag)(?![a-z])|ಎಷ್ಟು|ಏನು|ಹೇಗೆ|ಯಾಕೆ|ಯಾವಾಗ")


def _is_thanks(bare: str) -> bool:
    words = (bare or "").split()
    if not words:
        return False
    if not any(w.startswith(_THANKS_STEMS) for w in words):
        return False
    return all(w.startswith(_THANKS_STEMS) or w in _THANKS_FILLER for w in words)


def is_decline(text: str) -> bool:
    bare = re.sub(r"[^\w\s\u0C80-\u0CFF]", " ", (text or "").lower())
    bare = " ".join(bare.split())
    return bare in _DECLINES


# ── A SHARED WHATSAPP LOCATION ────────────────────────────────────────────
# api/webhook.py turns a location pin into ONE transcript line (reverse
# geocoded by geo_escom.py) and passes it through the same reader as any
# message, so a replay of the conversation reaches the same state:
#     📍 Location: Halebeedu, Belur, Hassan | ESCOM: CESC | 13.21330,75.99440
LOCATION_PREFIX = "📍 Location:"
_LOCATION_RE = re.compile(r"^📍 Location: (?P<place>.*?) \| ESCOM: (?P<escom>[A-Z]+) "
                          r"\| (?P<lat>-?\d+\.\d+),(?P<lon>-?\d+\.\d+)$")


def location_text(place: str, escom, lat: float, lon: float) -> str:
    return (f"{LOCATION_PREFIX} {place} | ESCOM: {(escom or 'unknown').upper()} "
            f"| {lat:.5f},{lon:.5f}")


def parse_location_text(text: str):
    """(place or None, escom or None, lat, lon) for a location line, else None."""
    m = _LOCATION_RE.match((text or "").strip())
    if not m:
        return None
    escom = m.group("escom").lower()
    return (m.group("place").strip() or None, None if escom == "unknown" else escom,
            float(m.group("lat")), float(m.group("lon")))


# ── WHAT A VOICE REPLY SAYS ───────────────────────────────────────────────
# The same words as the text reply, made speakable: no WhatsApp formatting,
# no emoji, keycap digits read as digits, no links. Capped, because a voice
# note that runs for minutes is not a reply.
_KEYCAP = {"0️⃣": "0", "1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4",
           "5️⃣": "5", "6️⃣": "6", "7️⃣": "7", "8️⃣": "8", "9️⃣": "9"}
VOICE_MAX_CHARS = 600


def speech_text(reply: str) -> str:
    t = reply or ""
    for k, v in _KEYCAP.items():
        t = t.replace(k, v + ".")
    t = re.sub(r"https?://\S+|wa\.me/\S+", "", t)
    t = t.replace("*", "").replace("_", " ").replace("·", ",")
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]", "", t)
    parts = [re.sub(r"\s{2,}", " ", p).strip() for p in t.split("\n")]
    parts = [p for p in parts if p]
    t = " ".join(p if p[-1] in ".?!:,;" else p + "." for p in parts)
    if len(t) > VOICE_MAX_CHARS:
        t = t[:VOICE_MAX_CHARS].rsplit(" ", 1)[0]
    return t


def parse_followup(text: str, awaiting=(), known: dict = None) -> dict:
    """Quantity, application and whether a price was asked. None when unread.

    Deliberately NOT a general extractor. It reads the two fields the first
    reply asked for and nothing else; everything it cannot read confidently
    stays None and the owner alert prints TBD.

    `awaiting` is what the PREVIOUS reply asked for, from its transcript
    marker. Optional and additive: omitted, this behaves exactly as before.
    Supplied with AWAITING_DELIVERY, a bare one-word answer to the delivery
    question is finally readable — which is how customers actually answer,
    and the reason one of them had to say it four times.
    """
    # A LOCATION PIN IS ONLY A PLACE. Read before anything else: its
    # coordinates would otherwise look like a quantity ("13" units).
    _pin = parse_location_text(text)
    if _pin:
        out = parse_followup("", awaiting, known)
        out.update(delivery_location=_pin[0], delivery_mentioned=True,
                   delivery_same=False, is_ack=False, escom_area=_pin[1])
        return out
    low = (text or "").lower()
    cap = capacity_kva(text)

    # A capacity is not a quantity, and neither is a distance or a motor
    # rating. _read_quantity owns that rule and the delivery filter shares it.
    qty = _read_quantity(low, cap)
    # THE CAPACITY, REPEATED. Asked for the purpose, a 25 kVA customer
    # replied "25" and was recorded as ordering 25 units (2026-09-24). A bare
    # figure equal to the kVA we already hold is that kVA again; "25 units"
    # with the word still counts.
    known_kva = (known or {}).get("capacity_kva")
    if (qty is not None and known_kva is not None and qty == known_kva
            and not re.search(r"units?|nos?|pcs?|ಯುನಿಟ್|ನಗ", low)):
        qty = None
    app = _application_of(low)
    # WHERE TO DELIVER. An explicit delivery word is required: a bare place
    # name in a follow-up cannot be told apart from an application, a company
    # or a person, and a guessed delivery address is a lorry sent to the wrong
    # district.
    # EMOJI ARE NOT WORDS (2026-09-27: "🙏🏻" went to the model, and "Ok 👍"
    # answering "deliver to X?" was stored as the ADDRESS "Ok 👍"). A message
    # with no letters or digits is an acknowledgement; emoji around a word do
    # not hide the word. Computed BEFORE any place is read.
    bare = low.strip(_TRIM)
    no_words = bool(bare) and not re.search(r"\w", bare)
    # Kannada / Devanagari vowel signs and the virama are not \w, so the script
    # blocks are kept whole — only symbols and emoji are removed ("ಸರಿ" must
    # stay "ಸರಿ").
    bare = re.sub(r"\s+", " ", re.sub(r"[^\w\s\u0900-\u097F\u0C80-\u0CFF\u200c\u200d]", " ",
                                     bare)).strip() or bare
    thanks = _is_thanks(bare)
    plain_reply = (no_words or bare in _ACKNOWLEDGEMENTS or bare in _AFFIRMATIONS or thanks
                   or _all_affirmation_words(bare))
    dl = None
    m = _DELIVERY_STRICT_RE.search(text or "")
    if m:
        candidate = (m.group(1) or m.group(2) or "").strip(" :-.,\n")
        if candidate and not any(w == candidate.lower() for w in _SAME_PLACE) \
                and re.search(r"[^\W\d_]", candidate):
            dl = candidate
    # THE ANSWER TO THE QUESTION WE JUST ASKED. Only consulted when the
    # strict shapes found nothing and the previous reply did ask for delivery,
    # so a place named in any other context is still not treated as an
    # address.
    #
    # NOT WHEN THE ANSWER IS A QUESTION ABOUT *WHEN*. "delivery yavaga" /
    # "Ayitu delivery yavaga kodtira", sent while we were waiting for the
    # place, were answered as a delivery-time question AND stored as the
    # delivery address — permanently, and over a place already given (audit,
    # 2026-09-27). The question is detected by customer_question(), the same
    # reader that answers it; only this bare-answer path is skipped, so an
    # explicit "deliver to X" above and a taluk/district address below still
    # read exactly as before.
    # A QUESTION IS NOT AN ADDRESS: "Installation charge yestaguthe" (how
    # much is installation?, live ...4585) was stored as the delivery place.
    asking = (customer_question(text) is not None or bool(asked_terms(text))
              or _mentions(low, _PRICE_ASK) or bool(_QUESTION_WORD_RE.search(low)))
    if (dl is None and AWAITING_DELIVERY in (awaiting or ())
            and not asking and not plain_reply):
        dl = _bare_delivery_answer(text)
    # AN ADDRESS THAT SAYS WHAT IT IS. On 2026-09-23 a customer wrote
    # "ಹರಿಯಬ್ಬೆ,ಹಿರಿಯೂರು ತಾಲೂಕು,ಚಿತ್ರದುರ್ಗ ಜಿಲ್ಲೆ" — village, taluk, district —
    # at a moment the bot was not waiting for a place, so it was not read, and
    # the next reply asked where to deliver. A bare place name still needs the
    # question behind it (see above); text that names its own taluk or
    # district does not, because that is how an address is built and nothing
    # else is. Only the ADMINISTRATIVE markers count here — "road" or "main"
    # alone would not be enough without the question.
    if dl is None and any(
            _label_matches(low, m) if m.isascii() else m in low
            for m in _ADMIN_MARKER):
        dl = _bare_delivery_answer(text)

    mentioned = bool(_DELIVERY_MENTION_RE.search(text or ""))

    # "Same place" answers the question without naming anywhere: it points at
    # the project location the form already captured, so it is recorded as a
    # confirmation rather than as an address.
    same = any(w in low for w in _SAME_PLACE) if not dl else False
    if (not dl and not same and AWAITING_DELIVERY in (awaiting or ())
            and (known or {}).get("location")
            and (bare in _AFFIRMATIONS or _all_affirmation_words(bare))):
        same = True
    # A bare acknowledgement or greeting says nothing a model can answer, and
    # asking one produced a paragraph re-introducing the company to someone
    # who had just typed "Ok".
    is_greeting = _is_greeting(bare)
    is_ack = (bare in _ACKNOWLEDGEMENTS or bare in _AFFIRMATIONS or is_greeting
              or no_words or thanks or _all_affirmation_words(bare))

    callback = callback_request(text, awaiting)
    if callback and AWAITING_CALLBACK in (awaiting or ()) and len(low.split()) <= 2:
        qty = None  # "2" / "2️⃣" answering "when should we call?" is option two, not two units
    return {"quantity": qty, "application": app, "capacity_kva": cap,
            "callback": callback, "asked_terms": asked_terms(text),
            # The previous reply already carried the closing block; saying it
            # again is the "tell everything" the owner asked us to stop.
            "callback_offered": AWAITING_CALLBACK in (awaiting or ()),
            "delivery_location": dl, "delivery_same": same,
            "delivery_mentioned": mentioned,
            "is_ack": is_ack,
            "is_greeting": is_greeting,
            # Unchanged meaning and unchanged readers: "did they raise money
            # at all". commercial_intent says WHICH ask it was.
            "asked_price": _mentions(low, _PRICE_ASK),
            "asked_discount": asked_discount(text),
            "asks_call": asks_about_call(text),
            "call_missed": call_missed(text),
            "declined": is_decline(text),
            "escom_area": None,
            "commercial_intent": commercial_intent(text),
            # None when no approval question was asked, which leaves every
            # reply exactly as it was.
            "discom_approval_ask": discom_approval_ask(text),
            # None for an ordinary qualification answer, which is the common
            # case and leaves every reply unchanged.
            "customer_question": customer_question(text)}


# ── Reply composition ─────────────────────────────────────────────────────
# Kannada-first with English technical terms, matching how these customers
# actually write ("25kva or 63kva agriculture purpose"). Technical values are
# language-neutral (AC-07) — the numbers do not change with the language.

_RANGE = " / ".join(f"{k} kVA" for k in CATALOGUE_KVA)

# The one sentence that carries the whole evidence boundary. A customer who
# asked for a price list gets a real next step instead of a number, and the
# promise made is one the business can actually keep.
_NO_PRICE = ("ದರ ಮತ್ತು ಡೆಲಿವರಿ ಸಮಯ — ನಮ್ಮ engineer "
             "ನಿಮ್ಮ requirement ನೋಡಿ ನಿಖರವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")

# ── THE OWNER'S PRICE LIST — 2026-09-24 ──────────────────────────────────
#
# Stated by the owner in chat, verbatim: "warranty period 1 year after that
# service available. payment advance 50% and 50 on delivery. 25 kva price
# 95,000 plus gst for 4 star transformer, 2 lakh plus gst for 63kva, 100 kva
# 2.95 lakh plus gst" and then "63 and 100 kva 5 star, transportation
# included not installation, delivery time call with our team, 250 kva
# 5 star 4.95 lakh plus gst".
#
# WHY PRICES ARE NOW SHOWN FIRST: 32 of 110 form leads (30 days to
# 2026-09-24) chose "price list / info", and "our engineer will tell you"
# was where those conversations ended. The owner asked for it.
#
# WHAT IS STILL NOT STATED, AND THEREFORE NEVER WRITTEN: the GST rate (always
# "+ GST", never a total), a delivery time in days (the team confirms it on
# a call), the installation cost, a validity date, any discount. The model
# path's evidence guard still refuses money in generated text: prices come
# only from this table, through the composer.
PRICE_LIST = {25: (95_000, 4), 63: (200_000, 5), 100: (295_000, 5), 250: (495_000, 5)}


def inr(amount: int) -> str:
    """Indian grouping: 95000 -> "95,000", 200000 -> "2,00,000"."""
    s = str(int(amount))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


_SALES_TERMS = (
    "🚚 Transport ಸೇರಿದೆ (installation ಪ್ರತ್ಯೇಕ)\n"
    "🛡️ *1 ವರ್ಷ warranty* — ನಂತರವೂ service ಲಭ್ಯ\n"
    "💳 *50% advance*, ಉಳಿದ 50% ಡೆಲಿವರಿ ಸಮಯದಲ್ಲಿ\n"
    "🏭 ನೇರ ತಯಾರಕರಿಂದ (Kadaba) — ಮಧ್ಯವರ್ತಿ ಇಲ್ಲ\n"
    "✔️ MESCOM approved\n"
    "⏱️ ಡೆಲಿವರಿ ಸಮಯ — ನಮ್ಮ ತಂಡ call ನಲ್ಲಿ ಖಚಿತಪಡಿಸುತ್ತಾರೆ")


def price_line(kva: int) -> str:
    amount, star = PRICE_LIST[kva]
    return f"*{kva} kVA {star} Star* — *₹{inr(amount)} + GST*"


# ONE THING AT A TIME — owner, 2026-09-25: "in one message dont tell
# everything". The full block (price_block_kn) read as a brochure; a
# customer on a phone answers a short message with one question. So the
# opening carries the price in one line and one question, the terms come
# only when asked (each topic on its own line), and warranty + payment are
# said once, briefly, when the call is offered.
TERM_LINES = {
    # "Installation charge yestaguthe?" (live ...4585): the amount is the
    # engineer's to give (owner ruling 2026-10-01), so the line says who will.
    "transport": ("Transport ದರದಲ್ಲೇ ಸೇರಿದೆ; installation ಪ್ರತ್ಯೇಕ — ಅದರ ಮೊತ್ತವನ್ನು "
                  "ನಮ್ಮ engineer ಕರೆಯಲ್ಲಿ ತಿಳಿಸುತ್ತಾರೆ."),
    "warranty": "ನಮ್ಮ transformer ಗಳಿಗೆ *1 ವರ್ಷ warranty* ಇದೆ; ಅದರ ನಂತರವೂ service ಲಭ್ಯವಿದೆ.",
    "payment": "Payment: *50% advance*, ಉಳಿದ 50% ಡೆಲಿವರಿ ಸಮಯದಲ್ಲಿ.",
}
CLOSING_VALUE = ("ನಿಮ್ಮ requirement ಪ್ರಕಾರ ನಮ್ಮ engineer ನಿಮ್ಮೊಂದಿಗೆ "
                 "ಮಾತನಾಡಿ ಸಂಪೂರ್ಣ ವಿವರ ತಿಳಿಸುತ್ತಾರೆ.")
# Quantity, asked ONCE (owner, 2026-09-17: "just ask them, if they don't
# tell anything assume it as single quantity"). It rides on the closing
# message as one line instead of being a numbered question of its own.
# THE CLOSE, IN THE CUSTOMER'S OWN TERMS (owner, 2026-09-25: "sales ge
# conversion aago tara natural aagirbeku"). The form already told us how
# soon they need it; a salesperson would use that, so the close does too.
# Each line states only what the team will do — no delivery promise, no
# claim beyond the evidence.
_CLOSE_BY_URGENCY = {
    "IMMEDIATE": "ನಿಮಗೆ transformer ತಕ್ಷಣ ಬೇಕಾಗಿರುವುದರಿಂದ, ನಮ್ಮ engineer ಆದಷ್ಟು "
                 "ಬೇಗ ನಿಮ್ಮೊಂದಿಗೆ ಮಾತನಾಡುತ್ತಾರೆ.",
    "WITHIN_1_MONTH": "ನಿಮಗೆ ಒಂದು ತಿಂಗಳೊಳಗೆ ಬೇಕಾಗಿರುವುದರಿಂದ, ನಿಮ್ಮ ಸಮಯಕ್ಕೆ "
                      "ಸರಿಯಾಗಿ plan ಮಾಡಲು ನಮ್ಮ engineer ಮಾತನಾಡುತ್ತಾರೆ.",
    "INFORMATION_ONLY": "ದರದ ಜೊತೆಗೆ, ನಿಮ್ಮ site ಗೆ ಸರಿಯಾದ transformer ಬಗ್ಗೆ ನಮ್ಮ "
                        "engineer ಮಾರ್ಗದರ್ಶನ ನೀಡುತ್ತಾರೆ.",
}


def closing_line(state: dict) -> str:
    """The sentence before the call offer, by name and by urgency."""
    who = display_name((state or {}).get("name"))
    body = _CLOSE_BY_URGENCY.get((state or {}).get("urgency"), CLOSING_VALUE)
    return f"{who} ಅವರೇ, {body}" if who else body


QUANTITY_NOTE = "(1 ಕ್ಕಿಂತ ಹೆಚ್ಚು *units* ಬೇಕಿದ್ದರೆ ದಯವಿಟ್ಟು ತಿಳಿಸಿ.)"


# PROFESSIONAL TONE — owner, 2026-09-25: "dont tell price directly, if
# they ask price then only tell them price; overall conversation look like
# very professional way". The customer is addressed by name, sentences are
# complete and courteous, and emojis are kept to the few that carry meaning.
_PURPOSE_KN = {"AGRICULTURE": "ಕೃಷಿ", "INDUSTRY": "ಕೈಗಾರಿಕೆ",
               "CONSTRUCTION": "ಕಟ್ಟಡ ನಿರ್ಮಾಣ", "EV_CHARGING": "EV charging",
               "SOLAR": "solar", "TENDER": "tender", "DOMESTIC": "ಮನೆ ಬಳಕೆ",
               "COMMERCIAL": "ವಾಣಿಜ್ಯ"}


def display_name(name) -> str:
    """"PUNITH SINCHANA 2024" -> "Punith Sinchana". Letters only, two words at
    most; empty when nothing presentable is left."""
    # Kannada vowel signs and the virama are not \w: without the block,
    # "ಶಿವ ಕುಮಾರ್" fell apart into single letters and the name vanished.
    words = [w for w in re.findall(r"(?:[^\W\d_]|[\u0C80-\u0CE5\u0CF0-\u0CFF\u200c\u200d])+",
                                   (name or "").replace("\u200c", "").replace("\u200d", ""))
             if len(w) > 1][:2]
    return " ".join(w.capitalize() if w.isascii() else w for w in words)


# WHY BAIRAVI — the owner's own words, 2026-10-01: "bairavi trans solution
# supply premium transformer but we are new company five star best grade
# aluminium winding lower losses". The star rating per size is the price
# list's (25 kVA is 4 Star). No years in business are claimed: new company.
def value_line_kn(kva=None) -> str:
    stars = PRICE_LIST.get(kva, (None, None))[1] if kva in PRICE_LIST else None
    rating = f"*{stars} Star*" if stars else "*Star-rated*"
    return (f"⭐ {rating} premium transformer — best-grade aluminium winding, "
            "ಕಡಿಮೆ ನಷ್ಟ (lower losses), ವಿದ್ಯುತ್ ಉಳಿತಾಯ.")


def price_short_kn(kva=None) -> str:
    """The price in as few lines as possible: one for a size we make, the
    list otherwise. Transport is named because it changes the comparison."""
    if kva in PRICE_LIST:
        return (f"{price_line(kva)}\n"
                "Transport ದರದಲ್ಲೇ ಸೇರಿದೆ; installation ಪ್ರತ್ಯೇಕ.")
    return ("ನಮ್ಮ ದರಗಳು:\n"
            + "\n".join(f"• {price_line(k)}" for k in sorted(PRICE_LIST))
            + "\nTransport ದರದಲ್ಲೇ ಸೇರಿದೆ; installation ಪ್ರತ್ಯೇಕ.")


def price_block_kn(kva=None) -> str:
    """The price for their capacity with the terms, or the whole list.

    One capacity when we know it and make it; otherwise the full list, so a
    customer who wrote 60 kVA sees 63 and decides — never silently mapped.
    """
    if kva in PRICE_LIST:
        head = "💰 " + price_line(kva)
    else:
        head = "💰 *ನಮ್ಮ ದರಗಳು:*\n" + "\n".join(f"• {price_line(k)}" for k in sorted(PRICE_LIST))
    return head + "\n" + _SALES_TERMS


# ── CALL-BACK BOOKING ─────────────────────────────────────────────────────
#
# Once qualification is complete the reply ends with a choice, not a
# "we will contact you": which of three times the engineer should call.
# A choice is easier to answer than "do you want to buy?", and the answer
# goes to the owner as a call task. 88 of 110 leads had never been called
# by a person (30 days to 2026-09-24).
AWAITING_CALLBACK = "callback"
CALLBACK_NOW, CALLBACK_EVENING, CALLBACK_TOMORROW = "now", "evening", "tomorrow"
CALLBACK_LABEL_KN = {CALLBACK_NOW: "ಈಗಲೇ", CALLBACK_EVENING: "ಇಂದು ಸಂಜೆ", CALLBACK_TOMORROW: "ನಾಳೆ"}
CALLBACK_LABEL_EN = {CALLBACK_NOW: "NOW", CALLBACK_EVENING: "this evening", CALLBACK_TOMORROW: "tomorrow"}
CALLBACK_QUESTION = ("ನಿಮಗೆ ಯಾವಾಗ ಕರೆ ಮಾಡುವುದು ಅನುಕೂಲ?\n"
                     "1️⃣ ಈಗಲೇ\n2️⃣ ಇಂದು ಸಂಜೆ\n3️⃣ ನಾಳೆ")
CALL_HINT = "📞 ನೇರವಾಗಿ ಮಾತನಾಡಲು *CALL* ಎಂದು reply ಮಾಡಿ."
# The call offer AGAIN, after the full closing was already sent once.
CALLBACK_REMINDER = "ಕರೆ ಮಾಡಲು ಅನುಕೂಲವಾದ ಸಮಯ: 1️⃣ ಈಗಲೇ · 2️⃣ ಇಂದು ಸಂಜೆ · 3️⃣ ನಾಳೆ"

_CALL_WORDS = ("call", "call me", "phone", "phone me", "ಕಾಲ್", "ಕಾಲ್ ಮಾಡಿ", "ಫೋನ್",
               "ಫೋನ್ ಮಾಡಿ", "ಕರೆ", "ಕರೆ ಮಾಡಿ", "call madi", "call maadi", "phone madi")
_CALLBACK_CHOICE = {
    "1": CALLBACK_NOW, "now": CALLBACK_NOW, "ಈಗ": CALLBACK_NOW, "ಈಗಲೇ": CALLBACK_NOW,
    "ega": CALLBACK_NOW, "egale": CALLBACK_NOW, "immediately": CALLBACK_NOW,
    "2": CALLBACK_EVENING, "evening": CALLBACK_EVENING, "ಸಂಜೆ": CALLBACK_EVENING,
    "sanje": CALLBACK_EVENING, "today evening": CALLBACK_EVENING, "ಇಂದು ಸಂಜೆ": CALLBACK_EVENING,
    "3": CALLBACK_TOMORROW, "tomorrow": CALLBACK_TOMORROW, "ನಾಳೆ": CALLBACK_TOMORROW,
    "nale": CALLBACK_TOMORROW, "naale": CALLBACK_TOMORROW,
}


# QUESTIONS THE OWNER'S TERMS NOW ANSWER. "what about warranty?" used to get
# "our engineer will confirm"; since 2026-09-24 there is a stated answer.
_TERM_TOPIC = {
    "warranty": "warranty", "guarantee": "warranty", "ವಾರಂಟಿ": "warranty", "ಗ್ಯಾರಂಟಿ": "warranty",
    "service": "warranty", "ಸರ್ವಿಸ್": "warranty",
    "payment": "payment", "advance": "payment", "ಅಡ್ವಾನ್ಸ್": "payment", "ಪೇಮೆಂಟ್": "payment",
    "emi": "payment", "loan": "payment",
    "transport": "transport", "ಸಾಗಣೆ": "transport", "installation": "transport",
    "install": "transport", "ಇನ್‌ಸ್ಟಾಲೇಶನ್": "transport",
}


def asked_terms(text: str) -> tuple:
    """Which of the owner's terms this message asks about, in a fixed order."""
    low = (text or "").lower()
    hit = {topic for w, topic in _TERM_TOPIC.items()
           if (_label_matches(low, w) if w.isascii() else w in low)}
    return tuple(t for t in ("transport", "warranty", "payment") if t in hit)


_KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")


# "WILL YOU CALL NOW?" AFTER A CALL TIME WAS CHOSEN. Live ...5711 chose
# "now", then asked "Ivag cl madtiya" and got "the engineer will explain".
# Mentions a call inside a longer message; the bare "call" / "ಕಾಲ್ ಮಾಡಿ"
# asks stay with callback_request.
_ASK_CALL_WORDS = ("call", "cl", "kal", "phone", "ph", "ಕಾಲ್", "ಕರೆ", "ಫೋನ್")


def asks_about_call(text: str) -> bool:
    low = (text or "").lower()
    return len(low.split()) >= 2 and _mentions(low, _ASK_CALL_WORDS)


# THE PROMISED CALL DID NOT COME (live ...3188, 2026-10-02). Two hours after
# "our engineer will call you now", the customer sent "ಕರೆ ಮಾಡಿಲ್ಲ" (you have
# not called) and was answered "ಹೌದು" — YES — "the engineer will call now",
# the same promise again. A complaint needs an apology and a person, not a
# repeat; the owner alert flags it at the top.
_CALL_MISSED = ("ಕರೆ ಮಾಡಿಲ್ಲ", "ಕರೆ ಬಂದಿಲ್ಲ", "ಕಾಲ್ ಮಾಡಿಲ್ಲ", "ಕಾಲ್ ಬಂದಿಲ್ಲ",
                "ಫೋನ್ ಮಾಡಿಲ್ಲ", "ಫೋನ್ ಬಂದಿಲ್ಲ", "ಕರೆ ಮಾಡಲಿಲ್ಲ", "ಕಾಲ್ ಮಾಡಲಿಲ್ಲ",
                "call madilla", "call madlilla", "call madalilla", "call bandilla",
                "call barlilla", "call banilla", "phone madilla", "phone bandilla",
                "not called", "didn't call", "didnt call", "did not call",
                "no call", "nobody called", "no one called", "still waiting for call",
                "not received any call")


def call_missed(text: str) -> bool:
    low = (text or "").lower()
    return _mentions(low, _CALL_MISSED)


def callback_request(text: str, awaiting=()):
    """now / evening / tomorrow when the customer asked for a call, else None.

    "CALL" (or ಕಾಲ್ ಮಾಡಿ, phone me…) as the whole message is a request to be
    called now. A bare 1 / 2 / 3 is a choice ONLY when the last reply offered
    those three options — otherwise "2" is still a quantity.
    """
    bare = re.sub(r"[\s.!,🙏️⃣]+", " ", (text or "").lower()).strip()
    # "೩" is 3 in Kannada script (2026-09-26: offered 1/2/3, the customer
    # typed "೩" and was recorded as ordering 3 units). Same digit, same choice.
    bare = bare.translate(_KANNADA_DIGITS)
    if bare in _CALL_WORDS:
        return CALLBACK_NOW
    if AWAITING_CALLBACK in (awaiting or ()):
        if bare in _CALLBACK_CHOICE:
            return _CALLBACK_CHOICE[bare]
        for word, slot in _CALLBACK_CHOICE.items():
            if not word.isdigit() and word in bare:
                return slot
    return None


def compose_reply(parsed: dict) -> str:
    """What the customer sees. No price, no lead time, no certification.

    Acknowledges what the form already told us rather than asking it again —
    the fifteen mishandled leads were each asked to start over from a menu.
    """
    if parsed["requirement"] == REPAIR:
        return (
            "ನಮಸ್ಕಾರ 🙏 *Bairavi Trans Solutions* — transformer "
            "ತಯಾರಿಕೆ ಮತ್ತು ಸೇವೆ.\n\n"
            "ನಿಮ್ಮ transformer ಸಮಸ್ಯೆ ಬಗ್ಗೆ ತಿಳಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ. "
            "ನಮ್ಮ technical team ಪರಿಶೀಲಿಸಿ ಸಂಪರ್ಕಿಸುತ್ತಾರೆ.\n\n"
            "ಬೇಗ ಸಹಾಯ ಮಾಡಲು ಇಷ್ಟು ತಿಳಿಸಿ:\n"
            "1️⃣ ಇದು *ತಕ್ಷಣದ breakdown* ಆ ಅಥವಾ *planned* ಕೆಲಸ ಆ?\n"
            "2️⃣ Transformer ಇರುವ *ಸ್ಥಳ*\n"
            "3️⃣ ಸಾಧ್ಯವಾದರೆ transformer *ಸಾಮರ್ಥ್ಯ* (kVA)"
        )

    who = display_name(parsed.get("name"))
    lines = [f"ನಮಸ್ಕಾರ {who} ಅವರೇ 🙏" if who else "ನಮಸ್ಕಾರ 🙏",
             "*Bairavi Trans Solutions* (Kadaba) ಅನ್ನು ಸಂಪರ್ಕಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು."]

    kva = parsed["capacity_kva"]
    if parsed["in_catalogue"]:
        if parsed.get("urgency") == "IMMEDIATE":
            # Owner-approved wording (2026-09-27). A priority, never a date.
            lines.append(f"ನಿಮಗೆ *{kva} kVA* ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ *ತಕ್ಷಣ* ಬೇಕು ಎಂದು "
                         "ಗಮನಿಸಿದ್ದೇವೆ — ಆದ್ಯತೆ ಮೇಲೆ ಮುಂದುವರಿಸುತ್ತೇವೆ.")
        else:
            lines.append(f"ನಿಮ್ಮ *{kva} kVA* ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ವಿಚಾರಣೆ ನಮಗೆ ತಲುಪಿದೆ.")
    elif parsed["planned"]:
        # A CAPACITY THE AD OFFERS ON PURPOSE: planned, not made today.
        # Both halves said plainly — see the planned-capacity tests.
        lines.append(f"*{kva} kVA* ನಮ್ಮ *ಮುಂದಿನ ಯೋಜನೆ*ಯಲ್ಲಿದೆ — ಸದ್ಯಕ್ಕೆ "
                     "ತಯಾರಿಸುತ್ತಿಲ್ಲ. ನಿಮ್ಮ requirement ನಮ್ಮ engineering "
                     f"ತಂಡಕ್ಕೆ ಕಳಿಸಿದ್ದೇವೆ. ಸದ್ಯದ range: *{_RANGE}*.")
    elif kva is not None:
        # Never silently mapped to a nearby size (AC-04), never refused.
        lines.append(f"ನೀವು *{kva} kVA* ಕೇಳಿದ್ದೀರಿ — ನಮ್ಮ engineer ಪರಿಶೀಲಿಸಿ "
                     f"ತಿಳಿಸುತ್ತಾರೆ. ಸದ್ಯದ range: *{_RANGE}*.")
    else:
        lines.append(f"ನಮ್ಮ distribution transformer range: *{_RANGE}*.")

    # PRICE ONLY WHEN ASKED (owner, 2026-09-25). Choosing "price list / info"
    # on the form IS asking, so that answer carries it.
    if parsed.get("urgency") == "INFORMATION_ONLY":
        lines.append("\nನೀವು ದರ ಕೇಳಿದ್ದೀರಿ:\n"
                     + price_short_kn(kva if parsed["in_catalogue"] else None))

    # ONE QUESTION. Delivery first (it decides transport), purpose next;
    # quantity is asked once at the close.
    known = {"location": parsed["location"]}
    if parsed.get("delivery_location"):
        lines.append(f"ಡೆಲಿವರಿ ಸ್ಥಳ: {parsed['delivery_location']}")
        if not parsed.get("application"):
            lines.append("\n" + question_for(AWAITING_PURPOSE, known))
    else:
        lines.append("\n" + question_for(AWAITING_DELIVERY, known))
    return "\n".join(lines)


# THE FIELDS THAT PERSIST ONCE THE CUSTOMER HAS ANSWERED THEM.
#
# asked_price is deliberately absent. It is a per-turn INTENT, not an
# established fact: a price asked four turns ago must not make every later
# reply a price reply. Everything here, by contrast, stays true until the
# customer says otherwise.
# "name" joined this list so the customer's own name — which the ad form
# already carries and `parse` already reads — survives past the first turn.
# It was being extracted and then dropped, which is why the bot could not
# answer "ನನ್ನ ಹೆಸರು ಗೊತ್ತಾ?" with something it already knew.
_PERSISTENT_FIELDS = ("capacity_kva", "quantity", "application", "location",
                      "delivery_location", "delivery_same",
                      "delivery_mentioned", "name", "callback", "urgency")


def merged_state(known: dict, turn: dict = None) -> dict:
    """Established state, plus whatever this turn adds. Never less.

    THE INVARIANT THIS EXISTS TO ENFORCE: a field that has been established
    cannot become unestablished. It may only be REPLACED, and only by an
    explicit new value from the customer.

    A real conversation on 2026-09-20 is what this is for. The customer said
    "ಕೃಷಿ" (agriculture) and the flow correctly narrowed to awaiting=delivery.
    One message later — "ಗುಜರಾತ್", a place, nothing to do with purpose — it
    widened back to awaiting=delivery,purpose. The purpose had been read,
    acknowledged, and then silently forgotten, so the bot asked for it again.
    The customer answered twice more and then wrote "You mad".

    The cause was not the extractor: it read ಕೃಷಿ correctly. It was that
    `outstanding()` read `application` from the CURRENT message only, and no
    field had anywhere to live between turns. So this merge is the fix, and it
    is deliberately field-agnostic — there is no `if field == "purpose"`
    anywhere, because the next field to be forgotten would not be purpose.

    None / False / "" mean "this turn says nothing about it", which is not the
    same as "it is no longer true".
    """
    state = dict(known or {})
    for field in _PERSISTENT_FIELDS:
        value = (turn or {}).get(field)
        if value is None or value is False or value == "":
            continue           # nothing new — and NEVER erase what is known
        state[field] = value   # an explicit value supersedes the old one
    return state


DELIVERY_ASK_LIMIT = 2


def established_from_history(history) -> dict:
    """Everything this conversation has already told us, accumulated.

    The follow-up composer is otherwise stateless and would re-ask for
    something the customer gave in their first message — which is the exact
    discourtesy that lost the first fifteen leads. The transcript keeps the
    customer's own text, so the answers are recoverable without new storage.

    WAS: this scanned backwards for the most recent LEAD FORM and returned
    location and delivery_location from it alone. Every conversational turn in
    between was ignored, and the four fields the follow-up actually asks for —
    capacity, quantity, purpose, delivery — had no home at all. An answer
    given in a chat message survived exactly one turn.

    NOW: oldest turn first, merging each one forward, forms and chat messages
    alike. Later explicit values win because they arrive later; silence never
    wins. The transcript is still the only store (see FLOW_MARKER) — this adds
    no state, it reads what was already there.
    """
    state = {f: None for f in _PERSISTENT_FIELDS}
    # What the reply BEFORE each customer turn was waiting for, carried
    # forward as the walk proceeds. Without this the history replay would read
    # a bare "ಗುಜರಾತ್" as nothing while the live turn reads it as an address,
    # and the two would disagree about the same conversation.
    awaiting = ()
    ignored = {}
    for msg in list(history or []):        # OLDEST FIRST — merge forward
        role = msg.get("role")
        text = msg.get("content") or ""
        if role == "assistant":
            if FLOW_MARKER in text:
                awaiting = marker_awaiting(text)
            continue
        if role != "user":
            continue
        # A form answers different questions from a chat reply, so each is
        # read by its own extractor. Neither is trusted to invent a field.
        turn = (parse(text) if is_lead_form(text)
                else parse_followup(text, awaiting, known=state))
        before = {f: state.get(f) for f in _PERSISTENT_FIELDS}
        state = merged_state(state, turn)
        if (awaiting[:1] in ((AWAITING_DELIVERY,), (AWAITING_PURPOSE,))
                and before == {f: state.get(f) for f in _PERSISTENT_FIELDS}):
            ignored[awaiting[0]] = ignored.get(awaiting[0], 0) + 1
    # IGNORED TWICE: MOVE ON (owner-approved 2026-09-30; purpose too,
    # 2026-10-01). Live ...4996 was
    # asked "which place?" five times. An ask counts only when the reply
    # told us NOTHING new: a customer answering size, units or purpose
    # instead is still talking to us, and then gives the place (the
    # "ಗುಜರಾತ್" replay). After two ignored asks the place is left for the call.
    if ignored:
        state["ignored_asks"] = ignored
    if awaiting:
        state["last_asked"] = awaiting[0]
    return state


def effective_quantity(followup: dict, known: dict = None) -> tuple:
    """(quantity, was_assumed) under the owner's default.

    Returns the stated quantity when there is one, otherwise DEFAULT_QUANTITY
    with was_assumed True. Callers that show a number to a human must show the
    flag too — an assumed 1 and a stated 1 look identical otherwise, and only
    one of them is worth confirming.

    `known` is optional and additive: without it this reads the current turn
    exactly as before. With it, a quantity stated EARLIER in the conversation
    is still reported as stated. Printing "1 (assumed — not stated)" for a
    customer who did say "೧ beku" tells the salesperson to go and confirm
    something already answered, which is the same forgetting this fix is
    about — just on the owner's side of it.
    """
    qty = merged_state(known, followup).get("quantity")
    if qty is not None:
        return qty, False
    return DEFAULT_QUANTITY, True


# WHAT A REPLY IS WAITING FOR. Named, because three things now consume it:
# the reply that asks, the transcript row that records it, and the nudge an
# hour later that asks again. Three copies of the rule would drift.
AWAITING_DELIVERY = "delivery"
AWAITING_PURPOSE = "purpose"
# Added for the quotation requirement set. They are asked only when a
# commercial intent is present, because outside that the opening reply's own
# three questions already cover the flow.
AWAITING_CAPACITY = "capacity"
AWAITING_QUANTITY = "quantity"

# ── WHAT A QUOTATION NEEDS: READ FROM THE GOAL, NOT RESTATED HERE ─────────
#
# bic/goals.py already declares it — `transformer_quotation` names kva_rating,
# quantity, voltage and delivery_location as its required slots. A second list
# in this module would be a second truth, and the two would drift the first
# time the business changed one.
#
# The goal is INJECTED as a plain dict, never imported. bairavi.py stays a
# pure offline module with no dependency on the bic package, which is the same
# "injected, not imported" discipline bic/context.py uses for its describer.
QUOTATION_GOAL_ID = "transformer_quotation"

# Goal slot name -> the established fact that fills it, and the ask that
# collects it. VOLTAGE IS ABSENT ON PURPOSE.
#
# The goal declares `voltage` OBTAINABLE_BY_ASKING, but Bairavi's product
# knowledge base lists "voltage ratio · primary voltage · secondary voltage"
# among "the attribute set every SKU must eventually carry" — a PRODUCT
# attribute, not a customer answer. The standard is 11 kV / 433 V while real
# enquiries also say 22/0.433 kV, so which it is has not been decided
# (business decision D6, open).
#
# Asking the customer would implement D6=A by default; dropping the slot
# would implement D6=C. Neither is this module's call, so voltage is neither
# asked nor silently satisfied: it is reported as undecided in the owner
# signal, where a human can see the gap.
_SLOT_TO_ASK = {
    "kva_rating": AWAITING_CAPACITY,
    "quantity": AWAITING_QUANTITY,
    "delivery_location": AWAITING_DELIVERY,
}

# Which established facts satisfy each ask. Delivery matches the existing
# `outstanding` semantics exactly — a named place, "same place", or a mention.
_ASK_SATISFIED_BY = {
    AWAITING_CAPACITY: ("capacity_kva",),
    AWAITING_QUANTITY: ("quantity",),
    AWAITING_DELIVERY: ("delivery_location", "delivery_same",
                        "delivery_mentioned"),
}


def requirement_asks(goal_def) -> tuple:
    """The asks this module can collect for a quotation goal, in goal order.

    Slots the goal declares but this module cannot establish — voltage today —
    are skipped rather than guessed at, and `unaskable_slots` reports them.
    """
    out = []
    for slot_def in (goal_def or {}).get("required_slots") or ():
        ask = _SLOT_TO_ASK.get(slot_def.get("name"))
        if ask and ask not in out:
            out.append(ask)
    return tuple(out)


def unaskable_slots(goal_def) -> tuple:
    """Slots the goal requires that this module deliberately does not ask.

    Not a bug list — a visible record of an undecided business question. The
    owner signal prints it so a quotation is never assembled while quietly
    short of a slot the goal itself declares.
    """
    return tuple(s.get("name")
                 for s in (goal_def or {}).get("required_slots") or ()
                 if s.get("name") not in _SLOT_TO_ASK)


def missing_requirements(goal_def, state: dict = None) -> tuple:
    """Which quotation requirements are still genuinely unanswered.

    From the MERGED state, so a fact established four turns ago is never
    asked for again — the invariant the 2026-09-20 conversation was lost to.
    """
    state = state or {}
    return tuple(ask for ask in requirement_asks(goal_def)
                 if not any(state.get(f) for f in _ASK_SATISFIED_BY[ask]))


def outstanding(followup: dict, known: dict = None) -> tuple:
    """Which of the asked-for fields are still unanswered.

    Quantity is never here: the owner ruled an unstated quantity is one unit,
    so it is asked once and never chased.

    Computed from the MERGED state, not from this turn plus a couple of
    hand-picked history keys. The delivery test already consulted `known`;
    the purpose test did not, and read `application` from the current message
    alone — so a purpose established one turn earlier came back as
    outstanding and was asked for again. Merging first means neither field
    can regress, and a field added later is protected without editing this
    function.
    """
    state = merged_state(known, followup)
    out = []
    # The ignored asks so far (from the history) plus THIS reply, when it is
    # one and tells us nothing new. See established_from_history.
    known = known or {}
    ignored = dict(known.get("ignored_asks") or {})
    if (followup and known.get("last_asked")
            and all(state.get(f) == known.get(f) for f in _PERSISTENT_FIELDS)):
        ignored[known["last_asked"]] = ignored.get(known["last_asked"], 0) + 1
    if not (state.get("delivery_location") or state.get("delivery_same")
            or state.get("delivery_mentioned")
            # A quotation needs the place (transport), so it is still asked.
            or (ignored.get(AWAITING_DELIVERY, 0) >= DELIVERY_ASK_LIMIT
                and followup.get("commercial_intent") != QUOTATION_REQUEST)):
        out.append(AWAITING_DELIVERY)
    if not (state.get("application")
            or ignored.get(AWAITING_PURPOSE, 0) >= DELIVERY_ASK_LIMIT):
        out.append(AWAITING_PURPOSE)
    return tuple(out)


_TALUK_LABELS = {"tq", "tq.", "tal", "tal.", "taluk", "taluka", "tk", "tk."}
_DISTRICT_LABELS = {"dist", "dist.", "district", "dt", "dt."}


def place_display(location: str) -> str:
    """How a typed place is SHOWN. The stored value is never changed.

    Extra spaces go. When BOTH a taluk label and a district label are
    each followed by one word, the rest is the village and is shown first:
    "TQ Ramdurga  Dist Belgaum  Toranagatti" -> "Toranagatti, Ramdurga,
    Belgaum". Anything less certain is shown as typed; we do not know
    village names, so we never guess an order the labels do not state.
    """
    words = (location or "").replace(",", " ").split()
    tidy = " ".join((location or "").split())
    parts = {}
    rest = []
    i = 0
    while i < len(words):
        w = words[i].lower()
        kind = "t" if w in _TALUK_LABELS else "d" if w in _DISTRICT_LABELS else None
        if kind:
            if kind in parts or i + 1 >= len(words):
                return tidy
            nxt = words[i + 1].lower()
            if nxt in _TALUK_LABELS or nxt in _DISTRICT_LABELS:
                return tidy
            parts[kind] = words[i + 1]
            i += 2
            continue
        rest.append(words[i])
        i += 1
    if set(parts) != {"t", "d"}:
        return tidy
    return ", ".join(([" ".join(rest)] if rest else []) + [parts["t"], parts["d"]])


def question_for(field: str, known: dict = None) -> str:
    """The customer-facing question for one outstanding field."""
    known = known or {}
    if field == AWAITING_DELIVERY:
        if known.get("location"):
            return (f"ಡೆಲಿವರಿ ಸ್ಥಳ: *{place_display(known['location'])}* — ಇದು ಸರಿಯೇ? "
                    "ಬೇರೆ ಸ್ಥಳವಾದರೆ ದಯವಿಟ್ಟು ತಿಳಿಸಿ.")
        return "Transformer *ಡೆಲಿವರಿ* ಯಾವ *ಸ್ಥಳಕ್ಕೆ* ಬೇಕು? (ಊರು, ತಾಲ್ಲೂಕು)"
    if field == AWAITING_PURPOSE:
        return ("ಈ transformer ಯಾವ *ಉದ್ದೇಶ*ಕ್ಕೆ ಬೇಕು? "
                "(ಕೃಷಿ / ಕೈಗಾರಿಕೆ / ಕಟ್ಟಡ ನಿರ್ಮಾಣ / EV charging / solar / tender)")
    if field == AWAITING_CAPACITY:
        # The RANGE, not a guess. _RANGE is built from CATALOGUE_KVA, so the
        # list shown can never drift from the list manufactured — and kVA is
        # stated explicitly because customers write "24 kv" for a capacity.
        return f"ಎಷ್ಟು *kVA* ಬೇಕು? (ನಮ್ಮ range: {_RANGE})"
    if field == AWAITING_QUANTITY:
        return "ಎಷ್ಟು *units* ಬೇಕು?"
    if field == AWAITING_CALLBACK:
        return CALLBACK_QUESTION
    raise ValueError(f"no question for {field!r}")


QUOTE_SIGNALLED = "quote_signalled=1"


def reply_fingerprint(text: str) -> str:
    """A short stable identity for a reply body.

    Ten hex characters of a digest, which is plenty to tell "the same reply
    again" from "a different reply" and short enough to sit in a transcript
    marker. Whitespace-insensitive at the edges only — the body itself must
    match exactly, because two replies that differ by one asked field are
    genuinely different replies.
    """
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:10]


def marker_reply(content: str):
    """The fingerprint a transcript row records for its reply, or None."""
    text = content or ""
    if FLOW_MARKER not in text or "reply=" not in text:
        return None
    return text.split("reply=", 1)[1].split()[0] or None


def last_reply_fingerprint(history):
    """The fingerprint of the most recent Bairavi reply, or None.

    Read from the transcript the flow already writes, like every other piece
    of this module's state — no new table, and no in-process memory, which a
    serverless function does not keep between invocations anyway.
    """
    for msg in reversed(list(history or [])):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        if FLOW_MARKER in content:
            return marker_reply(content)
    return None


def flow_marker(awaiting=(), quote_signalled: bool = False,
                reply: str = None) -> str:
    """The transcript row written for a Bairavi reply.

    Carries what the reply is waiting for, so an hour later something can
    decide whether to ask again — WITHOUT new storage. FLOW_MARKER stays a
    prefix so in_transformer_flow() keeps matching it.

    `quote_signalled` records that the sales signal for a quotation request
    has already been raised. Kept HERE rather than in a new table for the
    reason stated at FLOW_MARKER: a second store would be a second truth that
    can disagree with the transcript. The real conversation on 2026-09-20
    asked for a rate twice in four minutes, so without this the owner gets a
    duplicate alert for one intent.
    """
    parts = [FLOW_MARKER]
    if awaiting:
        parts.append(f"awaiting={','.join(awaiting)}")
    if quote_signalled:
        parts.append(QUOTE_SIGNALLED)
    # The reply's own identity, so the next turn can tell whether it is about
    # to send the same thing again. Appended last and parsed by prefix, so
    # every existing reader is unaffected.
    if reply:
        parts.append(f"reply={reply_fingerprint(reply)}")
    return " ".join(parts)


def marker_awaiting(content: str) -> tuple:
    """Read back what a transcript row says the reply was waiting for."""
    text = content or ""
    if FLOW_MARKER not in text or "awaiting=" not in text:
        return ()
    raw = text.split("awaiting=", 1)[1].split()[0]
    valid = (AWAITING_DELIVERY, AWAITING_PURPOSE,
             AWAITING_CAPACITY, AWAITING_QUANTITY, AWAITING_CALLBACK)
    return tuple(f for f in raw.split(",") if f in valid)


def quote_already_signalled(history) -> bool:
    """Has the sales signal for a quotation request already gone out?

    Read from the transcript the flow already writes, like every other piece
    of this module's state.
    """
    for msg in reversed(list(history or [])):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        if FLOW_MARKER in content and QUOTE_SIGNALLED in content:
            return True
    return False


def awaiting_from_history(history) -> tuple:
    """What the most recent Bairavi reply said it was waiting for.

    The conversational context a bare answer needs, taken from the transcript
    the flow already writes — no new storage, and the same marker the hourly
    nudge reads. Returns () when the last Bairavi reply was waiting for
    nothing, or when this conversation has no Bairavi reply yet: in both cases
    a bare place name is correctly left unread.
    """
    for msg in reversed(list(history or [])):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        if FLOW_MARKER in content:
            return marker_awaiting(content)
    return ()


def compose_short_reask(followup: dict, known: dict = None) -> str:
    """The reply when the full one would be sent twice in a row, verbatim.

    Six real conversations in the 21 days to 2026-09-22 received the same
    reply twice within 65 seconds, three times in one case. The stateless
    design chose that on purpose — "a customer who twice says something
    unreadable is therefore asked twice" — and for the QUESTION that is
    right. Sending the identical 324-character block again is not: the
    customer already has it on screen, and a bot that repeats itself reads
    as broken.

    So the question is still asked, and only the question. Built from
    question_for(), which already owns the wording for every field, so this
    introduces no new customer-facing sentence beyond one short line.
    """
    fields = outstanding(followup, known)
    if not fields:
        return ("🙏 ಧನ್ಯವಾದ — ನಮ್ಮ *Bairavi Trans Solutions* ತಂಡ "
                "ಶೀಘ್ರದಲ್ಲೇ ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತಾರೆ.")
    return "🙏 ಇಷ್ಟು ಮಾತ್ರ ಬೇಕು:\n" + question_for(fields[0], known)


def compose_followup_reply(followup: dict, known: dict = None, *args, **kwargs) -> str:
    """The reply — and never a bare "ಧನ್ಯವಾದಗಳು." to someone waiting for a
    call. A lone thanks after "25" (live ...1709, 2026-10-01) read as the
    conversation being dropped; when a call time is on record it now says
    when the engineer will call."""
    reply = _compose_followup_reply(followup, known, *args, **kwargs)
    slot = merged_state(known, followup).get("callback")
    if reply.strip() == "ಧನ್ಯವಾದಗಳು." and slot in CALLBACK_LABEL_KN:
        reply = f"ಧನ್ಯವಾದಗಳು 🙏 ನಮ್ಮ engineer *{CALLBACK_LABEL_KN[slot]}* ನಿಮಗೆ ಕರೆ ಮಾಡುತ್ತಾರೆ."
    return reply


def _compose_followup_reply(followup: dict, known: dict = None,
                           goal_def: dict = None,
                           last_fingerprint: str = None) -> str:
    """The reply to a message inside an existing transformer conversation.

    NOT the opening reply. Re-greeting someone mid-conversation and re-listing
    the range reads as a bot that has forgotten them — and the original
    behaviour was worse still, telling them we are not a transformer company.

    IT ALSO MUST NOT BE A RECEIPT. On 2026-09-17 a customer was asked two
    questions, answered one of them ("Charging Station") and restated the
    capacity ("100kv"), and was told twice: "we have recorded your message,
    our team will contact you." Nothing was acknowledged, nothing confirmed,
    and the units the reply had asked for were never asked again — so the
    conversation ended with the bot having requested two things and captured
    neither.

    So this confirms what was actually read, and RE-ASKS whatever is still
    outstanding, with a reason to answer. A question the customer can act on
    beats a receipt they cannot.

    Stateless by design, like the rest of this module: it sees one message and
    re-asks from that alone. A customer who twice says something unreadable is
    therefore asked twice — which is the right failure, because the
    alternative is the silence that lost this enquiry.
    """
    lines = []

    # What was genuinely read. Never a field that stayed None — a claim to
    # have understood something we did not is worse than admitting we did not.
    got = []
    # A size they only repeat ("25 kva price sir") is not news to thank for.
    if (followup.get("capacity_kva") is not None
            and followup["capacity_kva"] != (known or {}).get("capacity_kva")):
        got.append(f"{followup['capacity_kva']} kVA")
    if followup["quantity"] is not None:
        got.append(f"{followup['quantity']} unit"
                   + ("s" if followup["quantity"] != 1 else ""))
    if followup["application"]:
        got.append(_PURPOSE_KN.get(followup["application"],
                                   followup["application"].replace("_", " ").lower())
                   + " ಉದ್ದೇಶ")
    if followup.get("delivery_location"):
        got.append(f"ಡೆಲಿವರಿ: {followup['delivery_location']}")
    elif followup.get("delivery_same"):
        got.append("ಡೆಲಿವರಿ ಇದೇ ಸ್ಥಳಕ್ಕೆ")

    _state_now = merged_state(known, followup)
    if followup.get("declined") and not got:
        # A courteous close, once. No more questions; the owner is told why.
        _who = display_name(_state_now.get("name"))
        return (("ಸರಿ " + _who + " ಅವರೇ 🙏" if _who else "ಸರಿ 🙏")
                + " ಸಂಪರ್ಕಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ಮುಂದೆ ಅಗತ್ಯವಿದ್ದರೆ ಯಾವಾಗ "
                "ಬೇಕಾದರೂ ಈ ನಂಬರ್‌ಗೆ ಸಂದೇಶ ಕಳಿಸಿ.")
    if followup.get("is_greeting") and not got:
        # "Hii namaste" is a hello, not an answer. It was met with the
        # call-back close on 2026-09-25; it gets a hello and the one open
        # question (or an offer to help), nothing more.
        _who = display_name(_state_now.get("name"))
        _hello = f"ನಮಸ್ಕಾರ {_who} ಅವರೇ 🙏" if _who else "ನಮಸ್ಕಾರ 🙏"
        _open = outstanding(followup, known)
        return (_hello + "\n" + (question_for(_open[0], known) if _open
                else "ಹೇಳಿ, ನಿಮ್ಮ transformer ವಿಚಾರದಲ್ಲಿ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?"))
    if got:
        lines.append("ಧನ್ಯವಾದಗಳು — *" + ", ".join(got) + "* ಗಮನಿಸಿದ್ದೇವೆ.")
        # FROM A LOCATION PIN: which supply company serves it, and our
        # approval there — generated from _DISCOM_APPROVAL_STATED only.
        if followup.get("escom_area"):
            lines.append(f"📍 ಈ ಸ್ಥಳ *{followup['escom_area'].upper()}* ವ್ಯಾಪ್ತಿಗೆ ಬರುತ್ತದೆ. "
                         + approval_answer_kn((followup["escom_area"],)))
    elif not (followup.get("asked_price") or followup.get("callback")
              or followup.get("asked_terms") or followup.get("call_missed")
              or (followup.get("asks_call") and (known or {}).get("callback"))):
        # A price question or a call choice is answered directly below; a
        # "message received" line above it is filler.
        lines.append("ಧನ್ಯವಾದಗಳು.")

    # THE QUESTION THEY ASKED, ANSWERED. A DISCOM approval question used to
    # get "we have received your message" and the form questions again.
    _approval = followup.get("discom_approval_ask")
    if _approval is not None:
        lines.append("\nDISCOM approval ಬಗ್ಗೆ:\n"
                     + approval_answer_kn(_approval))

    # OTHER QUESTIONS WE HAVE EVIDENCE FOR. Skipped when the message is a
    # price or approval question, because those have their own answers above
    # and a customer asking one thing should not be answered twice.
    _question = followup.get("customer_question")
    if _question == QUESTION_UNANSWERED:
        if unanswered_question(followup):
            lines.append("\n" + answer_question_kn(_question, known))
    elif _question is not None:
        lines.append("\n" + answer_question_kn(_question, known))

    _intent = followup.get("commercial_intent")
    if followup.get("asked_terms"):
        # Only the term they asked about — one line each.
        lines.append("\n" + "\n".join(TERM_LINES[t] for t in followup["asked_terms"]))
    _chosen = (known or {}).get("callback")
    if followup.get("call_missed"):
        _who = display_name(merged_state(known, followup).get("name"))
        lines.append(("ಕ್ಷಮಿಸಿ " + _who + " ಅವರೇ 🙏" if _who else "ಕ್ಷಮಿಸಿ 🙏")
                     + " ಕರೆ ತಡವಾಗಿದೆ. ನಿಮ್ಮ ವಿಚಾರವನ್ನು ನಮ್ಮ ತಂಡಕ್ಕೆ ಮತ್ತೊಮ್ಮೆ "
                     "ತುರ್ತಾಗಿ ತಿಳಿಸಿದ್ದೇವೆ — ಆದಷ್ಟು ಬೇಗ ಕರೆ ಮಾಡುತ್ತಾರೆ.")
    elif followup.get("asks_call") and _chosen and not followup.get("callback"):
        _who = display_name(merged_state(known, followup).get("name"))
        lines.append(("ಹೌದು " + _who + " ಅವರೇ" if _who else "ಹೌದು")
                     + f", ನಮ್ಮ engineer *{CALLBACK_LABEL_KN[_chosen]}* ನಿಮಗೆ "
                     "ಕರೆ ಮಾಡುತ್ತಾರೆ 🙏")
    if followup.get("asked_discount"):
        # Never a discount and never the same price again: a person calls.
        # The value answer first (owner's selling points), then a person.
        lines.append("\n" + value_line_kn(merged_state(known, followup).get("capacity_kva"))
                     + "\nದರದ ಬಗ್ಗೆ ನಮ್ಮ sales ತಂಡ ನಿಮಗೆ ನೇರವಾಗಿ ಕರೆ ಮಾಡಿ "
                     "ಮಾತನಾಡುತ್ತಾರೆ.")
    elif followup["asked_price"]:
        # The question they actually asked. Answered with a real next step,
        # never a number — the evidence for one does not exist.
        # THE PRICE THEY ASKED FOR, from the owner's list (2026-09-24).
        _kva = merged_state(known, followup).get("capacity_kva")
        lines.append("\n" + price_short_kn(_kva) + "\n" + value_line_kn(_kva))
        if _intent == QUOTATION_REQUEST:
            # Says a REQUEST was recorded and a human will act. Never that a
            # quotation exists — no quotation has been produced, and claiming
            # one is the specific falsehood the owner's D3=A ruling forbids.
            lines.append("ನಿಮ್ಮ quotation *ವಿನಂತಿ* ನಮ್ಮ sales ತಂಡಕ್ಕೆ "
                         "ರವಾನಿಸಿದ್ದೇವೆ.")

    # Only what is still outstanding, and only the two things the opening
    # reply asked for. The capacity is not re-asked: it comes from the ad form.
    # QUANTITY IS NOT CHASED. Per the owner's ruling it is asked once in the
    # opening reply and then assumed to be one. Re-asking a question whose
    # answer does not change what happens next is how a customer learns to
    # stop replying — and purpose, which does change what happens next, is
    # the one worth pressing.
    known = known or {}
    # WHAT TO ASK FOR.
    #
    # Ordinarily: whatever this conversation is still waiting for.
    #
    # On a commercial turn: the quotation's OWN requirements lead, read from
    # the goal definition (bic/goals.py) rather than restated here — asking
    # for the purpose before the capacity when somebody just asked the price
    # answers a question they did not ask. Anything already established is
    # absent from both lists, because both are computed from merged state.
    _state = merged_state(known, followup)
    _asks = list(outstanding(followup, known))
    if _intent and goal_def:
        _required = [a for a in missing_requirements(goal_def, _state)
                     if a not in _asks]
        _asks = _required + _asks
    missing = [question_for(f, known) for f in _asks]

    _callback = followup.get("callback")
    if _callback:
        _who = display_name(merged_state(known, followup).get("name"))
        lines.append(("ಸರಿ " + _who + " ಅವರೇ." if _who else "ಸರಿ.")
                     + f" ನಮ್ಮ engineer *{CALLBACK_LABEL_KN[_callback]}* ನಿಮಗೆ "
                     "ಕರೆ ಮಾಡಿ, ಡೆಲಿವರಿ ಸಮಯ ಮತ್ತು order ವಿವರಗಳನ್ನು ತಿಳಿಸುತ್ತಾರೆ.\n"
                     "ಧನ್ಯವಾದಗಳು 🙏")
    if missing:
        # ONE QUESTION PER MESSAGE (owner, 2026-09-25). The next one is asked
        # when this one is answered; the marker still records every field
        # outstanding, so an answer to either is read.
        lines.append("\n" + missing[0])
    elif (not _callback and not merged_state(known, followup).get("callback")
          and followup.get("callback_offered")):
        lines.append("\n" + CALLBACK_REMINDER)
    elif not _callback and not merged_state(known, followup).get("callback"):
        # EVERYTHING IS ANSWERED: the two terms that close a sale, once, and
        # the call — instead of "we will contact you", which asked nothing.
        _qty_known = merged_state(known, followup).get("quantity") is not None
        lines.append("\n" + closing_line(merged_state(known, followup))
                     + ("" if _qty_known else "\n" + QUANTITY_NOTE)
                     + "\n\n" + CALLBACK_QUESTION)
    full = "\n".join(lines).strip()

    # THE SAME REPLY TWICE IN A ROW. Checked here, at the single place the
    # reply is built, so no caller can send a repeat by forgetting to ask.
    # `last_fingerprint` is the previous reply's identity from the
    # transcript marker; omitted, this behaves exactly as before.
    if last_fingerprint and reply_fingerprint(full) == last_fingerprint:
        return compose_short_reask(followup, known)
    return full


def _quantity_line(followup: dict, known: dict = None) -> str:
    """"3" when they said three; "1 (assumed — not stated)" when they did not.

    The parenthetical is the whole point: it tells the salesperson whether
    there is anything to confirm.
    """
    qty, assumed = effective_quantity(followup, known)
    return f"{qty} (assumed — not stated)" if assumed else str(qty)


def delivery_line(followup: dict, known: dict = None) -> str:
    """Where the transformer goes, or why we do not know yet."""
    known = known or {}
    if followup.get("delivery_location"):
        return followup["delivery_location"]
    if followup.get("delivery_same"):
        loc = known.get("location")
        return (f"same as project location ({loc}) — confirmed" if loc
                else "same as project location — confirmed")
    if known.get("delivery_location"):
        return f"{known['delivery_location']} (from the form)"
    if followup.get("delivery_mentioned"):
        # They named somewhere, in a word order this cannot safely parse.
        # Their exact words are in the alert below — read those.
        return "stated in their own words below — not parsed, please read it"
    return "TBD — asked, not yet answered"


def compose_followup_alert(phone: str, followup: dict, text: str,
                           known: dict = None) -> str:
    """The owner's copy of a follow-up. Carries the customer's own words.

    The verbatim line matters: "ನಮ್ಮಲ್ಲಿ ಲಯನ್ ದೂರ ಇದೆ ಕಾರಣ ಟಿ ಸಿ ಬೇಕಾಗಿದೆ"
    is a site condition no parsed field would have captured, and it is the
    most useful sentence in that conversation.
    """
    def val(v):
        return v if v not in (None, "") else "TBD"
    _cb = followup.get("callback")
    return (
        # FIRST LINE: a broken promise outranks every other signal.
        ("📵🔥 *CALL MISSED* — customer says the promised call never came. "
         "Call now.\n" if followup.get("call_missed") else "")
        + (f"🔥📞 *CALL {CALLBACK_LABEL_EN[_cb].upper()}* — customer asked for a call\n" if _cb else "")
        + ("⏰📞 *WAITING FOR YOUR CALL* — customer asked again when you will call "
           f"(chose: {CALLBACK_LABEL_EN[(known or {})['callback']]})\n"
           if followup.get("asks_call") and (known or {}).get("callback")
           and not followup.get("call_missed") else "")
        + ("❌ *NOT INTERESTED* — customer declined; a call may still save it\n"
           if followup.get("declined") else "")
        + ("💰🔥 *PRICE NEGOTIATION* — customer asked for a lower price. "
           "Bot promised a call from sales; no discount was offered.\n"
           if followup.get("asked_discount") else "")
        + "🔌 *BAIRAVI — follow-up*\n"
        f"From: wa.me/{phone}\n"
        # Reported when a follow-up RESTATES it — "100kv" on 2026-09-17 was a
        # capacity the owner alert had no line for, so it reached him only
        # inside the verbatim text.
        f"Capacity restated: {val(followup.get('capacity_kva'))}"
        + (" kVA\n" if followup.get('capacity_kva') is not None else "\n")
        + f"Delivery to: {delivery_line(followup, known)}\n"
        + f"Quantity: {_quantity_line(followup, known)}\n"
        # From the MERGED state, symmetric with delivery_line above, which
        # has always consulted `known`. An application established earlier
        # printed as TBD here, so the owner could not see a purpose the bot
        # had already been told.
        + f"Application: {val(merged_state(known, followup).get('application'))}\n"
        f"Asked for price: {'YES' if followup['asked_price'] else 'no'}\n"
        # Only printed when asked, so the alert does not grow a line that is
        # "no" in almost every conversation. A buyer who asks this is
        # checking whether the transformer can be energised on their
        # network, and the owner should see it.
        # A QUESTION THE BOT COULD NOT ANSWER. Printed only then, because
        # that is the line a human has to act on: the customer asked
        # something real and got a referral, not an answer.
        + ("Asked a question we could not answer — please read their words\n"
           if unanswered_question(followup) else "")
        + (("Asked about DISCOM approval: "
            + (", ".join(d.upper() for d in followup["discom_approval_ask"])
               or "not named")
            + "\n") if followup.get("discom_approval_ask") is not None else "")
        + f"\nTheir words: {(text or '').strip()[:300]}\n"
        "\nQuoted to the customer: the owner's list price only (+ GST). No delivery date, discount or certificate."
    )


def compose_quotation_signal(phone: str, followup: dict, text: str,
                             known: dict = None, goal_def: dict = None) -> str:
    """The sales signal for a QUOTATION REQUEST. Owner/staff only.

    Says a request arrived and what is known about it. It does NOT contain a
    price, a total, a margin or a validity date, because none of those exists
    as evidence — and it never states that a quotation was produced. Issuing
    one is a human process (owner ruling, D3=A: the AI may collect and qualify
    a requirement, never issue a quotation).

    Deliberately reports THREE things a salesperson cannot get elsewhere:
      · which requirements are still missing, so the chase is specific
      · the SKU status, so a VERIFY capacity like 24 kVA is never worked as
        though it were a stocked 25 kVA
      · which slots the quotation goal requires that nobody asked, so an
        undecided business question stays visible instead of looking answered
    """
    state = merged_state(known, followup)
    kva = state.get("capacity_kva")
    qty, assumed = effective_quantity(followup, known)
    still_missing = missing_requirements(goal_def, state)
    unasked = unaskable_slots(goal_def)

    def val(v):
        return v if v not in (None, "") else "TBD"

    lines = [
        "🧾 *BAIRAVI — QUOTATION REQUEST*",
        f"From: wa.me/{phone}",
        "",
        f"Capacity: {val(kva)}" + (" kVA" if kva is not None else ""),
        f"SKU status: {sku_status(kva)}",
        f"Quantity: {qty}" + (" (assumed — not stated)" if assumed else ""),
        f"Delivery to: {delivery_line(followup, known)}",
        f"Application: {val(state.get('application'))}",
    ]
    if still_missing:
        lines.append("\n⚠️ Still missing for a quotation: "
                     + ", ".join(still_missing))
    else:
        lines.append("\n✅ Every requirement this bot can collect is answered.")
    if unasked:
        lines.append("ℹ️ Required by the goal but NOT asked (undecided): "
                     + ", ".join(unasked))
    if sku_status(kva) != SUPPORTED:
        lines.append("ℹ️ Capacity is not a currently manufactured rating — "
                     "confirm before quoting.")
    lines.append(f"\nTheir words: {(text or '').strip()[:300]}")
    lines.append("\n👉 Prepare the quotation. No price, total, margin, "
                 "validity or delivery date was given to the customer, and "
                 "no quotation has been generated.")
    return "\n".join(lines)


def compose_owner_alert(phone: str, parsed: dict) -> str:
    """The owner's copy. Carries the parsed view AND flags what is unresolved.

    `TBD` is printed rather than omitted: a missing capacity is a thing
    somebody must chase, and a silently absent line reads as "nothing to do".
    """
    def val(v):
        return v if v else "TBD"

    head = ("🔌 *BAIRAVI TRANSFORMER LEAD*"
            if parsed["requirement"] == NEW_UNIT
            else "🛠 *BAIRAVI SERVICE CALL*")
    src = "Meta ad form" if parsed["from_lead_form"] else "WhatsApp message"
    # THREE OUTCOMES, NOT TWO. "out of range" on a planned capacity reads as
    # an anomaly to chase; it is a real enquiry for a product the business has
    # decided to build, and the owner needs to see that difference.
    if parsed.get("form_unreadable"):
        # Above the capacity flag on purpose: if the form is unreadable then
        # the capacity is unknown for a REASON, and that reason is the thing
        # to act on.
        flag = ("  🚨 FORM NOT READ — every field came through blank, which "
                "means the Meta form's questions were changed. Fix the form "
                "or send me the new labels; the customer's own words are "
                "below and are unaffected.")
    elif parsed["in_catalogue"]:
        flag = ""
    elif parsed["planned"]:
        flag = "  📋 PLANNED CAPACITY — sales + engineering to assess"
    else:
        flag = "  ⚠️ CAPACITY NOT RECOGNISED — confirm with the customer"

    return (
        f"{head}\n"
        f"From: wa.me/{phone}\n"
        f"Source: {src}\n"
        f"Name: {val(parsed['name'])}\n"
        f"Capacity: {val(parsed['capacity_kva'] and str(parsed['capacity_kva']) + ' kVA')}"
        f"{flag}\n"
        f"SKU: {val(parsed['sku'])} ({parsed['sku_status']})\n"
        f"Location: {val(parsed['location'])}\n"
        f"Delivery to: {val(parsed.get('delivery_location')) if parsed.get('delivery_location') else 'TBD — asked in the reply'}\n"
        f"Urgency: {val(parsed['urgency'])}\n"
        f"Quantity: {DEFAULT_QUANTITY} (assumed — the ad form does not ask, "
        f"and the customer has not said)\n"
        f"\nNo price, delivery date or certificate was quoted to the customer."
    )


def is_silent_ack(followup: dict, awaiting=()) -> bool:
    """A bare "K"/"Ok" with nothing pending: no reply is owed.

    On 2026-09-24 a customer who had answered every question typed "K" and
    was sent "✅ ಧನ್ಯವಾದ — ನಿಮ್ಮ ಸಂದೇಶ ಸಿಕ್ಕಿದೆ" — a receipt for a receipt.
    Silence is right only when the message read nothing at all AND the last
    reply was not waiting for anything (an "Ok" to "same place?" is an
    answer, and is handled by delivery_same).
    """
    if not followup.get("is_ack") or awaiting or followup.get("is_greeting"):
        return False  # a greeting is always greeted back
    read_something = any(followup.get(k) for k in (
        "quantity", "application", "capacity_kva", "delivery_location",
        "delivery_same", "asked_price", "discom_approval_ask", "customer_question", "callback", "asked_terms"))
    return not read_something


def awaiting_after(followup: dict, known: dict = None) -> tuple:
    """What the reply just composed is waiting for — for the transcript marker.

    outstanding() plus the call-back choice, which is offered only once the
    qualification questions are all answered and no call time is known yet.
    Kept separate so outstanding() keeps meaning "qualification still open".
    """
    out = outstanding(followup, known)
    if not out and not merged_state(known, followup).get("callback"):
        return (AWAITING_CALLBACK,)
    # ONLY THE QUESTION THAT WAS ASKED. One question per message (owner,
    # 2026-09-25), so the marker names that one — the hourly nudge must never
    # chase a question the customer has not yet been shown. A purpose given
    # early is still read: application needs no awaiting to be recognised.
    return out[:1]


def opening_awaiting(parsed: dict) -> tuple:
    """The marker for the opening reply: the one question it asked."""
    known = {"location": parsed.get("location"),
             "delivery_location": parsed.get("delivery_location"),
             "application": parsed.get("application")}
    return outstanding({}, known)[:1]

