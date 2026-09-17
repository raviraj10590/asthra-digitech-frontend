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


def capacity_kva(text: str):
    """The kVA figure, or None when it cannot be read confidently.

    None is a correct answer and a human then confirms it. Returning a nearby
    catalogue size would be the confidently-wrong capacity AC-07 forbids.
    """
    answer = _field(text, _FIELD_PATTERNS["capacity"]) or (text or "")
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
    loc = _field(text, _FIELD_PATTERNS["location"]) or None
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
    form_unreadable = bool(is_form) and kva is None and loc is None and urg is None

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
        "application": None,       # §6.2 field 6 — asked, strongest early signal
    }


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

_QTY_RE = re.compile(
    r"\b(\d{1,3})\s*(?:units?|nos?|pcs?|pieces?|ಯುನಿಟ್|ನಗ)?\b", re.IGNORECASE)

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
    # After the agriculture needles on purpose: a "solar pump" is a farm
    # load, while a "solar plant" is its own segment.
    ("solar", "SOLAR"), ("ಸೋಲಾರ್", "SOLAR"),
    ("industr", "INDUSTRY"), ("ಕೈಗಾರಿಕೆ", "INDUSTRY"), ("factory", "INDUSTRY"),
    ("construct", "CONSTRUCTION"), ("ಕಟ್ಟಡ", "CONSTRUCTION"),
    ("tender", "TENDER"), ("ಟೆಂಡರ್", "TENDER"),
    ("domestic", "DOMESTIC"), ("house", "DOMESTIC"), ("ಮನೆ", "DOMESTIC"),
    ("commercial", "COMMERCIAL"), ("shop", "COMMERCIAL"),
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
_NUMERALS = ("1️⃣", "2️⃣", "3️⃣")

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
_SAME_PLACE = ("same place", "same address", "same location", "same",
               "ಅದೇ ಸ್ಥಳ", "ಅದೇ", "ಹೌದು", "yes same", "same only")

# A price request. Worth recognising so the reply answers the question that
# was actually asked instead of repeating the intake prompt.
_PRICE_ASK = ("rate", "price", "cost", "quotation", "quote", "ದರ", "ಬೆಲೆ",
              "eshtu", "estu", "ಎಷ್ಟು")


def parse_followup(text: str) -> dict:
    """Quantity, application and whether a price was asked. None when unread.

    Deliberately NOT a general extractor. It reads the two fields the first
    reply asked for and nothing else; everything it cannot read confidently
    stays None and the owner alert prints TBD.
    """
    low = (text or "").lower()
    cap = capacity_kva(text)

    # A CAPACITY IS NOT A QUANTITY, and this guard had a hole. It tested the
    # span for "kva" only, so once "kv" became readable as a capacity,
    # "100 kv" parsed as 100 UNITS — the single most damaging misread
    # available here, and one this change would have introduced. Testing for
    # "kv" covers both spellings, and a figure that IS the capacity is
    # excluded outright.
    #
    # Scanning every match rather than only the first also means "250kv 3
    # units" now yields 3 instead of giving up at 250.
    qty = None
    for m in _QTY_RE.finditer(low):
        n = int(m.group(1))
        span = low[m.start():m.start() + len(m.group()) + 5]
        if "kv" in span or not (0 < n <= 999) or n == cap:
            continue
        qty = n
        break
    app = None
    for needle, value in _APPLICATIONS:
        if needle in low:
            app = value
            break
    # WHERE TO DELIVER. An explicit delivery word is required: a bare place
    # name in a follow-up cannot be told apart from an application, a company
    # or a person, and a guessed delivery address is a lorry sent to the wrong
    # district.
    dl = None
    m = _DELIVERY_STRICT_RE.search(text or "")
    if m:
        candidate = (m.group(1) or m.group(2) or "").strip(" :-.,\n")
        if candidate and not any(w == candidate.lower() for w in _SAME_PLACE) \
                and re.search(r"[^\W\d_]", candidate):
            dl = candidate
    mentioned = bool(_DELIVERY_MENTION_RE.search(text or ""))

    # "Same place" answers the question without naming anywhere: it points at
    # the project location the form already captured, so it is recorded as a
    # confirmation rather than as an address.
    same = any(w in low for w in _SAME_PLACE) if not dl else False

    return {"quantity": qty, "application": app, "capacity_kva": cap,
            "delivery_location": dl, "delivery_same": same,
            "delivery_mentioned": mentioned,
            "asked_price": any(w in low for w in _PRICE_ASK)}


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

    lines = ["ನಮಸ್ಕಾರ 🙏 *Bairavi Trans Solutions* — "
             "oil-immersed 3-phase distribution transformer ತಯಾರಕರು "
             "(Kadaba, Dakshina Kannada)."]

    kva = parsed["capacity_kva"]
    if parsed["in_catalogue"]:
        # Confirm what they chose. This is the whole point: they already told
        # us, and being asked again is what lost the first fifteen.
        lines.append(f"\n✅ ನಿಮ್ಮ requirement: *{kva} kVA* "
                     "— ಇದು ನಮ್ಮ standard range ನಲ್ಲಿದೆ.")
    elif parsed["planned"]:
        # A CAPACITY THE AD OFFERS ON PURPOSE. It must not read as a mistake
        # and it must not read as available. Both halves are said plainly:
        # planned, and not manufactured today. Saying only the first would
        # promise a transformer that cannot be delivered; saying only the
        # second would turn a real enquiry into a rejection.
        lines.append(f"\nℹ️ ನೀವು *{kva} kVA* ಕೇಳಿದ್ದೀರಿ. ಇದು ನಮ್ಮ "
                     "*ಮುಂದಿನ ಯೋಜನೆ*ಯಲ್ಲಿರುವ capacity — "
                     "ಸದ್ಯಕ್ಕೆ ತಯಾರಿಸುತ್ತಿಲ್ಲ.\n"
                     f"ಸದ್ಯದ manufacturing range: *{_RANGE}*.\n"
                     "ನಿಮ್ಮ requirement ನಮ್ಮ sales ಮತ್ತು engineering team ಗೆ "
                     "ಕಳಿಸಿದ್ದೇವೆ — ಅವರು ಪರಿಶೀಲಿಸಿ ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")
    elif kva is not None:
        # An unrecognised capacity. Never silently mapped to a nearby size
        # (AC-04 is a gate, not a filter), and never refused.
        lines.append(f"\nℹ️ ನೀವು *{kva} kVA* ಕೇಳಿದ್ದೀರಿ. ಸದ್ಯದ "
                     f"manufacturing range *{_RANGE}*. ನಿಮ್ಮ requirement ನಮ್ಮ "
                     "technical team ಗೆ ಕಳಿಸಿದ್ದೇವೆ — ಅವರು ಖಚಿತವಾಗಿ "
                     "ತಿಳಿಸುತ್ತಾರೆ.")
    else:
        lines.append(f"\nಸದ್ಯದ manufacturing range: *{_RANGE}*.")

    if parsed["location"]:
        lines.append(f"📍 ಸ್ಥಳ: {parsed['location']}")

    lines.append("\n" + _NO_PRICE)

    # Only what is genuinely missing. Quantity is never in the ad form, and
    # application is §6.2's strongest early qualification signal.
    # Ordered by what it costs us not to know. The delivery place decides
    # transport and site access; purpose is the qualification signal; quantity
    # defaults to one and is asked once, last, because the owner ruled it is
    # not important.
    asks = []
    if parsed.get("delivery_location"):
        # The form already told us. Confirm rather than ask again — being
        # asked twice for something already given is what lost the first
        # fifteen leads.
        lines.append(f"🚚 ಡೆಲಿವರಿ ಸ್ಥಳ: {parsed['delivery_location']}")
    elif parsed["location"]:
        # A project address is not a delivery address, but it is the obvious
        # candidate — so this confirms instead of asking cold, which is one
        # word to answer instead of a sentence.
        asks.append(f"🚚 TC *ಡೆಲಿವರಿ* ಇದೇ ಸ್ಥಳಕ್ಕೆ ಆ — *{parsed['location']}*? "
                    "ಬೇರೆ ಆದರೆ ಆ ಸ್ಥಳ ತಿಳಿಸಿ.")
    else:
        asks.append("🚚 TC *ಡೆಲಿವರಿ* ಯಾವ ಸ್ಥಳಕ್ಕೆ ಬೇಕು?")

    asks.append("ಯಾವ *ಉದ್ದೇಶ*? " + _PURPOSE_OPTIONS)
    asks.append("ಎಷ್ಟು *units* ಬೇಕು?")

    lines.append("\nಇಷ್ಟು ತಿಳಿಸಿದರೆ ಸಾಕು:")
    assert len(asks) <= len(_NUMERALS), "an ask would be silently dropped"
    for numeral, ask in zip(_NUMERALS, asks):
        lines.append(f"{numeral} {ask}")
    return "\n".join(lines)


def established_from_history(history) -> dict:
    """What the ad form in this conversation already told us.

    The follow-up composer is otherwise stateless and would re-ask for
    something the customer gave in their first message — which is the exact
    discourtesy that lost the first fifteen leads. The transcript keeps the
    customer's own form text, so the answer is recoverable without new
    storage.
    """
    for msg in reversed(list(history or [])):
        if msg.get("role") != "user":
            continue
        text = msg.get("content") or ""
        if is_lead_form(text):
            p = parse(text)
            return {"location": p["location"],
                    "delivery_location": p["delivery_location"]}
    return {"location": None, "delivery_location": None}


def effective_quantity(followup: dict) -> tuple:
    """(quantity, was_assumed) under the owner's default.

    Returns the stated quantity when there is one, otherwise DEFAULT_QUANTITY
    with was_assumed True. Callers that show a number to a human must show the
    flag too — an assumed 1 and a stated 1 look identical otherwise, and only
    one of them is worth confirming.
    """
    qty = followup.get("quantity")
    if qty is not None:
        return qty, False
    return DEFAULT_QUANTITY, True


# WHAT A REPLY IS WAITING FOR. Named, because three things now consume it:
# the reply that asks, the transcript row that records it, and the nudge an
# hour later that asks again. Three copies of the rule would drift.
AWAITING_DELIVERY = "delivery"
AWAITING_PURPOSE = "purpose"


def outstanding(followup: dict, known: dict = None) -> tuple:
    """Which of the asked-for fields are still unanswered.

    Quantity is never here: the owner ruled an unstated quantity is one unit,
    so it is asked once and never chased.
    """
    known = known or {}
    out = []
    if not (followup.get("delivery_location") or followup.get("delivery_same")
            or followup.get("delivery_mentioned")
            or known.get("delivery_location")):
        out.append(AWAITING_DELIVERY)
    if not followup.get("application"):
        out.append(AWAITING_PURPOSE)
    return tuple(out)


def question_for(field: str, known: dict = None) -> str:
    """The customer-facing question for one outstanding field."""
    known = known or {}
    if field == AWAITING_DELIVERY:
        if known.get("location"):
            return (f"🚚 TC *ಡೆಲಿವರಿ* ಇದೇ ಸ್ಥಳಕ್ಕೆ ಆ — *{known['location']}*?")
        return "🚚 TC *ಡೆಲಿವರಿ* ಯಾವ ಸ್ಥಳಕ್ಕೆ ಬೇಕು?"
    if field == AWAITING_PURPOSE:
        return "ಯಾವ *ಉದ್ದೇಶ*? " + _PURPOSE_OPTIONS
    raise ValueError(f"no question for {field!r}")


def flow_marker(awaiting=()) -> str:
    """The transcript row written for a Bairavi reply.

    Carries what the reply is waiting for, so an hour later something can
    decide whether to ask again — WITHOUT new storage. FLOW_MARKER stays a
    prefix so in_transformer_flow() keeps matching it.
    """
    if not awaiting:
        return FLOW_MARKER
    return f"{FLOW_MARKER} awaiting={','.join(awaiting)}"


def marker_awaiting(content: str) -> tuple:
    """Read back what a transcript row says the reply was waiting for."""
    text = content or ""
    if FLOW_MARKER not in text or "awaiting=" not in text:
        return ()
    raw = text.split("awaiting=", 1)[1].split()[0]
    valid = (AWAITING_DELIVERY, AWAITING_PURPOSE)
    return tuple(f for f in raw.split(",") if f in valid)


def compose_followup_reply(followup: dict, known: dict = None) -> str:
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
    if followup.get("capacity_kva") is not None:
        got.append(f"{followup['capacity_kva']} kVA")
    if followup["quantity"] is not None:
        got.append(f"{followup['quantity']} unit"
                   + ("s" if followup["quantity"] != 1 else ""))
    if followup["application"]:
        got.append(followup["application"].replace("_", " ").lower())
    if followup.get("delivery_location"):
        got.append(f"ಡೆಲಿವರಿ {followup['delivery_location']}")
    elif followup.get("delivery_same"):
        got.append("ಡೆಲಿವರಿ ಇದೇ ಸ್ಥಳ")

    if got:
        lines.append("✅ ಧನ್ಯವಾದ — ದಾಖಲಿಸಿದ್ದೇವೆ: *" + ", ".join(got) + "*.")
    else:
        lines.append("✅ ಧನ್ಯವಾದ — ನಿಮ್ಮ ಸಂದೇಶ ಸಿಕ್ಕಿದೆ.")

    if followup["asked_price"]:
        # The question they actually asked. Answered with a real next step,
        # never a number — the evidence for one does not exist.
        lines.append("\nದರದ ಬಗ್ಗೆ: ನಮ್ಮ engineer ನಿಮ್ಮ requirement "
                     "(capacity, quantity, ಸ್ಥಳ) ನೋಡಿ ನಿಖರವಾದ quotation "
                     "ಕೊಡುತ್ತಾರೆ — ಸಾಮಾನ್ಯ ದರ ಹೇಳುವುದು ತಪ್ಪಾಗುತ್ತದೆ.")

    # Only what is still outstanding, and only the two things the opening
    # reply asked for. The capacity is not re-asked: it comes from the ad form.
    # QUANTITY IS NOT CHASED. Per the owner's ruling it is asked once in the
    # opening reply and then assumed to be one. Re-asking a question whose
    # answer does not change what happens next is how a customer learns to
    # stop replying — and purpose, which does change what happens next, is
    # the one worth pressing.
    known = known or {}
    # The delivery place leads, because not knowing it is what stops a
    # quotation: transport and site access are priced from it.
    missing = [question_for(f, known) for f in outstanding(followup, known)]

    if missing:
        lines.append("\nಇನ್ನೊಂದು ವಿಷಯ ತಿಳಿಸಿ:" if len(missing) == 1
                     else "\nಇಷ್ಟು ತಿಳಿಸಿದರೆ ಸಾಕು:")
        assert len(missing) <= len(_NUMERALS), "a question would be dropped"
        # A tuple, not a sliced string: each keycap is three codepoints
        # (digit + VS16 + combining enclosing keycap), so slicing by 2 tore
        # them in half and produced "1️" and "⃣2" on the customer's phone.
        for numeral, q in zip(_NUMERALS, missing):
            lines.append(f"{numeral} {q}")
        # A reason to reply, not a demand. This is the sentence that turns an
        # unanswered question into an answered one.
        lines.append("\nಇದು ತಿಳಿದರೆ ನಮ್ಮ engineer ನಿಖರವಾದ quotation "
                     "ಕೊಡಲು ಸಾಧ್ಯ.")

    lines.append("\nನಮ್ಮ *Bairavi Trans Solutions* ತಂಡ ಶೀಘ್ರದಲ್ಲೇ "
                 "ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತಾರೆ 🙏")
    return "\n".join(lines)


def _quantity_line(followup: dict) -> str:
    """"3" when they said three; "1 (assumed — not stated)" when they did not.

    The parenthetical is the whole point: it tells the salesperson whether
    there is anything to confirm.
    """
    qty, assumed = effective_quantity(followup)
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
    return (
        "🔌 *BAIRAVI — follow-up*\n"
        f"From: wa.me/{phone}\n"
        # Reported when a follow-up RESTATES it — "100kv" on 2026-09-17 was a
        # capacity the owner alert had no line for, so it reached him only
        # inside the verbatim text.
        f"Capacity restated: {val(followup.get('capacity_kva'))}"
        + (" kVA\n" if followup.get('capacity_kva') is not None else "\n")
        + f"Delivery to: {delivery_line(followup, known)}\n"
        + f"Quantity: {_quantity_line(followup)}\n"
        f"Application: {val(followup['application'])}\n"
        f"Asked for price: {'YES' if followup['asked_price'] else 'no'}\n"
        f"\nTheir words: {(text or '').strip()[:300]}\n"
        "\nNo price, delivery date or certificate was quoted to the customer."
    )


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
