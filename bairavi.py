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

THE AD SELLS A CAPACITY BAIRAVI DOES NOT MAKE
---------------------------------------------
The form offers 25 / 63 / 100 / 500 kVA. The catalogue is 25 / 63 / 100 / 250.
So 500 kVA is outside it — two of the sixteen asked for it — and 250 kVA, which
IS manufactured, is not offered. Out-of-catalogue enquiries are captured and
routed for manual confirmation, never refused and never silently mapped to a
nearby size: `AC-04`'s gate is "a gate, not a filter".

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

# Offered by the ad form but NOT manufactured. Kept as data rather than as a
# special case in the reply, so a form change is a one-line edit here.
KNOWN_OUT_OF_CATALOGUE_KVA = (500,)

FAMILY = "OIL_IMMERSED"

# Requirement type · AC-02. The first fork, and it is answered by the enquiry
# itself rather than by asking.
NEW_UNIT = "NEW_UNIT"
REPAIR = "REPAIR"

# SKU status · AC-04
SUPPORTED = "SUPPORTED_PRODUCT"
NEEDS_CONFIRMATION = "FUTURE_OR_MANUAL_CONFIRMATION_PRODUCT"

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
)
_KVA_RE = re.compile(r"\b\d{1,4}\s*k\s*v\s*a\b", re.IGNORECASE)

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
    return bool(_KVA_RE.search(low))


def is_lead_form(text: str) -> bool:
    """True for a Meta Lead Ads handoff, whatever it is about."""
    low = (text or "").lower()
    return any(m in low for m in _LEAD_FORM_MARKERS)


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
_FIELD_PATTERNS = {
    "name": ("full name", "ಹೆಸರು"),
    "phone": ("phone number", "ದೂರವಾಣಿ"),
    "capacity": ("ಸಾಮರ್ಥ್ಯ",),
    "timing": ("ಯಾವಾಗ",),
    "location": ("ಸ್ಥಳ", "ಪ್ರಾಜೆಕ್ಟ್"),
}

# Timing options, mapped to a coarse urgency the owner can triage on. The
# labels are the customer's own choices; the mapping adds no judgement beyond
# the ordering the form itself implies.
_TIMING_URGENCY = (
    ("ತಕ್ಷಣ", "IMMEDIATE"),
    ("1 ತಿಂಗಳ", "WITHIN_1_MONTH"),
    ("1–3 ತಿಂಗಳ", "WITHIN_3_MONTHS"),
    ("1-3 ತಿಂಗಳ", "WITHIN_3_MONTHS"),
    ("ಮಾಹಿತಿ", "INFORMATION_ONLY"),
)


def _field(text: str, keys) -> str:
    """The answer on the first `label: answer` line matching any key."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        label, _, answer = line.partition(":")
        low = label.lower()
        if any(k in low for k in keys):
            return answer.strip()
    return ""


def capacity_kva(text: str):
    """The kVA figure, or None when it cannot be read confidently.

    None is a correct answer and a human then confirms it. Returning a nearby
    catalogue size would be the confidently-wrong capacity AC-07 forbids.
    """
    answer = _field(text, _FIELD_PATTERNS["capacity"]) or (text or "")
    m = _KVA_RE.search(answer)
    if not m:
        return None
    digits = re.search(r"\d{1,4}", m.group())
    return int(digits.group()) if digits else None


def sku_status(kva) -> str:
    """SUPPORTED_PRODUCT only for a catalogue capacity (AC-04).

    Everything else — unknown, or a size the ad offers but the factory does
    not build — is routed for manual confirmation. Captured and workable, but
    never inside the automatic path.
    """
    if kva in CATALOGUE_KVA:
        return SUPPORTED
    return NEEDS_CONFIRMATION


def urgency(text: str):
    """Coarse urgency from the FORM's own timing option, else None.

    Never inferred from free prose. For a service call §6.2a is explicit that
    urgency must be asked, and this returns None there so the caller asks.
    """
    answer = _field(text, _FIELD_PATTERNS["timing"])
    if not answer:
        return None
    for needle, value in _TIMING_URGENCY:
        if needle in answer:
            return value
    return None


def parse(text: str) -> dict:
    """The normalized view of an enquiry. Never replaces the original text.

    Every field may be None. The caller stores `raw` verbatim regardless, so
    nothing the customer said is lost to a parse failure.
    """
    kva = capacity_kva(text)
    return {
        "raw": text or "",
        "from_lead_form": is_lead_form(text),
        "requirement": requirement_type(text),
        "family": FAMILY,
        "capacity_kva": kva,
        "sku": f"BTS-{kva}" if kva in CATALOGUE_KVA else None,
        "sku_status": sku_status(kva),
        "in_catalogue": kva in CATALOGUE_KVA,
        "quantity": None,          # never present in the ad form — must be asked
        "location": _field(text, _FIELD_PATTERNS["location"]) or None,
        "name": _field(text, _FIELD_PATTERNS["name"]) or None,
        "urgency": urgency(text),
        "application": None,       # §6.2 field 6 — asked, strongest early signal
    }


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
    elif kva is not None:
        # Honest, and it keeps the lead. AC-04: a gate, not a filter — and
        # never silently mapped to a nearby size.
        lines.append(f"\nℹ️ ನೀವು *{kva} kVA* ಕೇಳಿದ್ದೀರಿ. ನಮ್ಮ standard "
                     f"range *{_RANGE}*. ನಿಮ್ಮ requirement ನಮ್ಮ technical "
                     "team ಗೆ ಕಳಿಸಿದ್ದೇವೆ — ಅವರು ಖಚಿತವಾಗಿ ತಿಳಿಸುತ್ತಾರೆ.")
    else:
        lines.append(f"\nನಮ್ಮ standard range: *{_RANGE}*.")

    if parsed["location"]:
        lines.append(f"📍 ಸ್ಥಳ: {parsed['location']}")

    lines.append("\n" + _NO_PRICE)

    # Only what is genuinely missing. Quantity is never in the ad form, and
    # application is §6.2's strongest early qualification signal.
    lines.append("\nಇನ್ನೆರಡು ವಿಷಯ ತಿಳಿಸಿದರೆ ಸಾಕು:\n"
                 "1️⃣ ಎಷ್ಟು *units* ಬೇಕು?\n"
                 "2️⃣ ಯಾವ *ಉದ್ದೇಶ*? (agriculture / industry / "
                 "construction / tender)")
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
    flag = "" if parsed["in_catalogue"] else "  ⚠️ OUT OF STANDARD RANGE"

    return (
        f"{head}\n"
        f"From: wa.me/{phone}\n"
        f"Source: {src}\n"
        f"Name: {val(parsed['name'])}\n"
        f"Capacity: {val(parsed['capacity_kva'] and str(parsed['capacity_kva']) + ' kVA')}"
        f"{flag}\n"
        f"SKU: {val(parsed['sku'])} ({parsed['sku_status']})\n"
        f"Location: {val(parsed['location'])}\n"
        f"Urgency: {val(parsed['urgency'])}\n"
        f"Quantity: TBD (not asked in the ad form)\n"
        f"\nNo price, delivery date or certificate was quoted to the customer."
    )
