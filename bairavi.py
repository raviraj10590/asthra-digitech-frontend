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
        if not stated_unit and low[digits_end:digits_end + 1].isalpha():
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
        return n
    return None

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
_PRICE_WORDS = ("rate", "price", "cost", "ದರ", "ಬೆಲೆ",
                "eshtu", "estu", "ಎಷ್ಟು",
                "amount", "how much", "howmuch", "kitna", "kitne",
                "ಎಷ್ಟಾಗುತ್ತೆ", "ಎಷ್ಟಾಗುತ್ತದೆ", "ಎಷ್ಟು ರೂ", "ಮೊತ್ತ")
# Already the bot's own words for this: the follow-up button is titled
# "📋 ಕೋಟೇಶನ್" and its id is "quotation".
_QUOTATION_WORDS = ("quotation", "quote", "ಕೋಟೇಶನ್")

# The union, kept under its original name because two other readers depend on
# it: the bare-delivery-answer filter and the `asked_price` field, whose
# meaning ("did they ask about money at all") is unchanged.
_PRICE_ASK = _PRICE_WORDS + _QUOTATION_WORDS


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
    if not asked:
        approved = [d for d, v in _DISCOM_APPROVAL_STATED.items()
                    if v == "APPROVED"]
        pending = [d for d, v in _DISCOM_APPROVAL_STATED.items()
                   if v == "IN_PROGRESS"]

    parts = []
    if approved:
        parts.append("✅ *" + "*, *".join(d.upper() for d in approved)
                     + "* approval ಆಗಿದೆ.")
    if pending:
        parts.append("*" + "*, *".join(d.upper() for d in pending) + "* — "
                     + _DISCOM_IN_PROGRESS_ETA_KN + " ಆಗುತ್ತದೆ ಎಂದು "
                     "ನಿರೀಕ್ಷಿಸುತ್ತಿದ್ದೇವೆ.")
    if unknown:
        parts.append("*" + "*, *".join(d.upper() for d in unknown) + "* ಬಗ್ಗೆ "
                     "ನಮ್ಮ engineer ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")
    return "\n".join(parts)


def commercial_intent(text: str):
    """QUOTATION_REQUEST, PRICE_REQUEST, or None.

    Quotation outranks price: "quotation ಬೇಕು, rate ಎಷ್ಟು?" is a quotation
    request that also mentions price, and the stronger act decides. The
    reverse precedence would silently downgrade a sales signal.

    PER-TURN, NEVER STATE. Deliberately absent from _PERSISTENT_FIELDS — a
    price asked four turns ago must not make every later reply a price reply.
    """
    low = (text or "").lower()
    if any(w in low for w in _QUOTATION_WORDS):
        return QUOTATION_REQUEST
    if any(w in low for w in _PRICE_WORDS):
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
_ACKNOWLEDGEMENTS = ("ok", "okay", "k", "hmm", "thanks", "thank you", "ok sir",
                     "sure", "fine", "ಸರಿ", "ಆಯ್ತು", "ಧನ್ಯವಾದ", "ಥ್ಯಾಂಕ್ಸ್",
                     "no", "illa", "ಇಲ್ಲ", "haan", "ha", "yes", "yep")

# Words that make a place name a STATEMENT about a place rather than an answer
# naming one. "I am from Gujarat" says where the customer is, not where the
# transformer goes, and the two are routinely different.
_NOT_A_BARE_ANSWER = ("ನಾನು", "ನಮ್ಮ", "my", "our", "i", "we",
                      "am", "is", "are", "not", "ಅಲ್ಲ",
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
    "ಸೈಟ್", "ಜಮೀನು", "ಗ್ರಾಮ", "ಹಳ್ಳಿ", "ನಗರ",
)

# Phrases that cannot occur inside a place name, so these may be matched
# anywhere in the message rather than only as the whole of it.
_NOT_A_PLACE_PHRASE = (
    "call me", "call back", "callback", "phone me", "whatsapp me",
    "message me", "ಕರೆ ಮಾಡಿ", "ಫೋನ್ ಮಾಡಿ",
    "dont know", "don't know", "do not know", "not sure", "no idea",
)


_TRIM = " \t\n.,!:-"

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
    """Could this text be the name of a place? Length is not consulted.

    THE LENGTH CAPS ARE GONE, and they were the defect. A 40-character,
    4-word ceiling was standing in for "does this look like a place", and on
    2026-09-22 it threw away the most complete address a customer can give:

        "ತುಮಕೂರು .ಜಿಲ್ಲೆ . ಗುಬ್ಬಿ ..ತಾಲ್ಲೂಕು... ಚೇಳೂರು ಹೋಬಳಿ. ಕುಲುಮೆಗುಡ್ಲು ಗ್ರಾಮ"

    113 characters — district, taluk, hobli and village, spelled out, twice,
    by a customer the bot then asked for the delivery place a fifth time.
    Raising the ceiling only moves the failure to the next character, so the
    ceiling is not the test. The owner's ruling on 2026-09-22 settles it:
    record the address the customer gave, in full, and never lose the
    district.

    What replaces it is the semantic filtering that was always doing the real
    work. None of it introduces place vocabulary: every rejection is either
    another field's answer, or a linguistic category — a question, an
    acknowledgement, a pronoun sentence, a refusal to answer. There is still
    no gazetteer, no transliteration and no canonical form.
    """
    low = raw.lower()

    # A question is not an answer — "Gujarat price?" asks something else.
    if "?" in raw:
        return False
    if any(w in low for w in _PRICE_ASK):
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
    if any(needle in low for needle, _ in _APPLICATIONS):
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
    if any(p in low for p in _NOT_A_PLACE_PHRASE):
        return False
    # Must contain an actual letter — a number or emoji is not a place.
    if not re.search(r"[^\W\d_]", raw):
        return False
    return True


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
    if _is_place_like(raw):
        return raw
    kept = [seg for seg in (part.strip(_TRIM)
                            for part in _SEGMENT_SPLIT.split(raw))
            if seg and _is_place_like(seg)]
    if not kept:
        return None
    return ", ".join(kept)

def parse_followup(text: str, awaiting=()) -> dict:
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
    low = (text or "").lower()
    cap = capacity_kva(text)

    # A capacity is not a quantity, and neither is a distance or a motor
    # rating. _read_quantity owns that rule and the delivery filter shares it.
    qty = _read_quantity(low, cap)
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
    # THE ANSWER TO THE QUESTION WE JUST ASKED. Only consulted when the
    # strict shapes found nothing and the previous reply did ask for delivery,
    # so a place named in any other context is still not treated as an
    # address.
    if dl is None and AWAITING_DELIVERY in (awaiting or ()):
        dl = _bare_delivery_answer(text)

    mentioned = bool(_DELIVERY_MENTION_RE.search(text or ""))

    # "Same place" answers the question without naming anywhere: it points at
    # the project location the form already captured, so it is recorded as a
    # confirmation rather than as an address.
    same = any(w in low for w in _SAME_PLACE) if not dl else False

    return {"quantity": qty, "application": app, "capacity_kva": cap,
            "delivery_location": dl, "delivery_same": same,
            "delivery_mentioned": mentioned,
            # Unchanged meaning and unchanged readers: "did they raise money
            # at all". commercial_intent says WHICH ask it was.
            "asked_price": any(w in low for w in _PRICE_ASK),
            "commercial_intent": commercial_intent(text),
            # None when no approval question was asked, which leaves every
            # reply exactly as it was.
            "discom_approval_ask": discom_approval_ask(text)}


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


# THE FIELDS THAT PERSIST ONCE THE CUSTOMER HAS ANSWERED THEM.
#
# asked_price is deliberately absent. It is a per-turn INTENT, not an
# established fact: a price asked four turns ago must not make every later
# reply a price reply. Everything here, by contrast, stays true until the
# customer says otherwise.
_PERSISTENT_FIELDS = ("capacity_kva", "quantity", "application", "location",
                      "delivery_location", "delivery_same",
                      "delivery_mentioned")


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
                else parse_followup(text, awaiting))
        state = merged_state(state, turn)
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
    if not (state.get("delivery_location") or state.get("delivery_same")
            or state.get("delivery_mentioned")):
        out.append(AWAITING_DELIVERY)
    if not state.get("application"):
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
    if field == AWAITING_CAPACITY:
        # The RANGE, not a guess. _RANGE is built from CATALOGUE_KVA, so the
        # list shown can never drift from the list manufactured — and kVA is
        # stated explicitly because customers write "24 kv" for a capacity.
        return f"ಎಷ್ಟು *kVA* ಬೇಕು? (ನಮ್ಮ range: {_RANGE})"
    if field == AWAITING_QUANTITY:
        return "ಎಷ್ಟು *units* ಬೇಕು?"
    raise ValueError(f"no question for {field!r}")


QUOTE_SIGNALLED = "quote_signalled=1"


def flow_marker(awaiting=(), quote_signalled: bool = False) -> str:
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
    return " ".join(parts)


def marker_awaiting(content: str) -> tuple:
    """Read back what a transcript row says the reply was waiting for."""
    text = content or ""
    if FLOW_MARKER not in text or "awaiting=" not in text:
        return ()
    raw = text.split("awaiting=", 1)[1].split()[0]
    valid = (AWAITING_DELIVERY, AWAITING_PURPOSE,
             AWAITING_CAPACITY, AWAITING_QUANTITY)
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


def compose_followup_reply(followup: dict, known: dict = None,
                           goal_def: dict = None) -> str:
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

    # THE QUESTION THEY ASKED, ANSWERED. A DISCOM approval question used to
    # get "we have received your message" and the form questions again.
    _approval = followup.get("discom_approval_ask")
    if _approval is not None:
        lines.append("\nDISCOM approval ಬಗ್ಗೆ:\n"
                     + approval_answer_kn(_approval))

    _intent = followup.get("commercial_intent")
    if followup["asked_price"]:
        # The question they actually asked. Answered with a real next step,
        # never a number — the evidence for one does not exist.
        lines.append("\nದರದ ಬಗ್ಗೆ: ನಮ್ಮ engineer ನಿಮ್ಮ requirement "
                     "(capacity, quantity, ಸ್ಥಳ) ನೋಡಿ ನಿಖರವಾದ quotation "
                     "ಕೊಡುತ್ತಾರೆ — ಸಾಮಾನ್ಯ ದರ ಹೇಳುವುದು ತಪ್ಪಾಗುತ್ತದೆ.")
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
    return (
        "🔌 *BAIRAVI — follow-up*\n"
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
        + (("Asked about DISCOM approval: "
            + (", ".join(d.upper() for d in followup["discom_approval_ask"])
               or "not named")
            + "\n") if followup.get("discom_approval_ask") is not None else "")
        + f"\nTheir words: {(text or '').strip()[:300]}\n"
        "\nNo price, delivery date or certificate was quoted to the customer."
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
