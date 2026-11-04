"""How Karnataka customers write — shared by every bot the Brain runs.

Owner, 2026-11-04: "kannada elrigu onde alva, bhashe na brain itkodre olledu — next yava clients
hosa bot madoke order kotru allu use aagutte". What a customer MEANS in Kannada, Kanglish or
English, learned from live chats and stress tests: amounts and counter-offers, phone numbers,
the same name in two scripts, "call me" / "don't call", "I will pay", Kannada digits.

NOTHING HERE KNOWS A CLIENT. No price, product, place list or reply text: each bot keeps its own
facts and wording and asks this module only what the words mean. A new client's bot starts with
everything already learned here, and the tests in tests/test_kannada_understanding.py.
"""
import re


def mentions(low: str, words) -> bool:
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
        elif w == "ದರ":
            # "ದರ" (rate) sits inside the commonest conditionals, ಆದರೆ (but) / ಎಂದರೆ (if) / ಇದ್ದರೆ —
            # found 2026-10-25 when "dry type ನಿರ್ಮಿಸುವಿರಿ ಎಂದರೆ?" got the price list. The rate word
            # itself inflects ದರವು / ದರದ / ದರಕ್ಕೆ, never ದರೆ.
            if re.search("ದರ(?![ೆೇ])", low):
                return True
        elif w in low:
            return True
    return False

def name_words(text) -> set:
    """Lower-case words of 3+ letters, invisible characters removed.

    Kannada vowel signs and the virama are not \\w, so they are named
    explicitly: without them "ರವಿಕುಮಾರ್" fell apart into one-letter pieces and
    no Kannada name ever matched (live ...0143, 2026-10-30)."""
    clean = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", str(text or "")).lower()
    return {w for w in re.findall(r"(?:[^\W\d_]|[\u0C80-\u0CE3])+", clean) if len(w) >= 3}


# THE SAME NAME IN THE OTHER SCRIPT (live ...0765, 2026-11-04). Full name "Suresh Lamani", place
# field "ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ" — the bot asked "ನಿಮ್ಮ ಊರು ಸುರೇಶ್ ಹೀರಪ್ಪ ಲಮಾಣಿ ಅಲ್ವಾ?". Words are
# compared by their consonants only (ಸುರೇಶ್ / Suresh -> "srs"), so a script difference is no
# difference. A comparison key, never a spelling: nothing here is shown or stored.
KN_CONSONANT = {"ಕ": "k", "ಖ": "k", "ಗ": "g", "ಘ": "g", "ಙ": "n", "ಚ": "c", "ಛ": "c", "ಜ": "j", "ಝ": "j",
                 "ಞ": "n", "ಟ": "t", "ಠ": "t", "ಡ": "d", "ಢ": "d", "ಣ": "n", "ತ": "t", "ಥ": "t", "ದ": "d",
                 "ಧ": "d", "ನ": "n", "ಪ": "p", "ಫ": "p", "ಬ": "b", "ಭ": "b", "ಮ": "m", "ಯ": "y", "ರ": "r",
                 "ಲ": "l", "ವ": "v", "ಶ": "s", "ಷ": "s", "ಸ": "s", "ಹ": "h", "ಳ": "l"}
LATIN_DIGRAPH = (("sh", "s"), ("th", "t"), ("dh", "d"), ("ch", "c"), ("kh", "k"), ("gh", "g"),
                  ("ph", "p"), ("bh", "b"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks"), ("f", "p"))


def consonant_key(word: str) -> str:
    w = (word or "").lower()
    if w.isascii():
        for a, b_ in LATIN_DIGRAPH:
            w = w.replace(a, b_)
        key = "".join(c for c in w if c.isalpha() and c not in "aeiou")
    else:
        key = "".join(KN_CONSONANT.get(c, "") for c in w)
    return re.sub(r"(.)\1+", r"\1", key)


def is_the_name(location, name) -> bool:
    """True when a location answer is, in the main, the customer's name:
    at least two of its words, and at least half of them, are name words."""
    loc_w, name_w = name_words(location), name_words(name)
    shared = loc_w & name_w
    _name_keys = {k for k in map(consonant_key, name_w) if len(k) >= 2}
    _cross = {w for w in loc_w if w not in shared and consonant_key(w) in _name_keys}
    if len(shared | _cross) >= 2 and 2 * len(shared | _cross) >= len(loc_w):
        return True
    # Or it IS the whole name: "Jagadish" for "Jagadish R" (live ...0962).
    # One shared word of a longer name stays a place ("Shivakumar").
    # Or the same name with different initials: "ರವಿಕುಮಾರ್. ಜಿ. ಎಮ್" for
    # "ರವಿಕುಮಾರ್ ಜಿ. ಎಂ" — the long words agree, only the initials differ.
    loc_long = {w for w in loc_w if len(w) > 3}
    return bool(loc_w) and (loc_w == name_w
                            or (loc_long and loc_long == {w for w in name_w if len(w) > 3})
                            or (len(shared) >= 2 and 2 * len(shared) >= len(loc_w)))




KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")

# A RUPEE FIGURE IS A COUNTER-OFFER (live ...9249, 2026-11-04). "25000₹nane
# kodayhni" (I will give only ₹25,000 — for 100 kVA) answered "which place?"
# and was echoed back as the PLACE: "ಸರಿ, 25000₹nane kodayhni 👍". Only "45 k"
# and "2 lakh" were read as a budget; a plain or ₹ figure was not.
OFFER_RE = re.compile(r"(?:₹|(?<![a-z])rs\.?|(?<![a-z])inr|ರೂ\.?)\s*(\d[\d,]*)"
                       r"|(\d[\d,]*)\s*(?:₹|/-|rs(?![a-z])|rupees?|ರೂ)"
                       r"|(?<![\d.,])(\d{1,2}(?:,\d\d)*,\d{3}|\d{4,5})(?![\d.,])", re.I)
PHONE_IN_TEXT_RE = re.compile(r"(?:\+?91[\s-]?)?(?<!\d)\d{5}[\s-]?\d{5}(?!\d)")
# Money said about the terms, not the price: "Rs 5000 advance kodtini", "85000 + gst aa?".
TERMS_MONEY = ("advance", "ಅಡ್ವಾನ್ಸ್", "payment", "ಪೇಮೆಂಟ್", "emi", "loan", "gst", "ಜಿಎಸ್ಟಿ")


def offered_amount(text: str, list_prices=()):
    """The rupee figure the customer says they will pay, else None.

    Not an offer: a phone number, a figure under ₹5,000, a payment-terms
    question, and one of the owner's own prices (with or without 18% GST) —
    "85,000 alva?" repeats the price, it does not bargain.
    """
    low = PHONE_IN_TEXT_RE.sub(" ", (text or "").lower())
    if mentions(low, TERMS_MONEY):
        return None
    # SEVERAL FIGURES: THE LOWEST IS THEIR OFFER (2026-11-04 debate). "ಬೆಲೆ ₹70,000 … ಬೇರೆ ಕಂಪನಿ
    # ₹50,000 … ನಾನು ₹45,000 ಕೊಟ್ಟರೆ?" quotes a price and a rival before the offer; ₹70,000 went
    # to the owner. A buyer's own figure is the low one.
    found = []
    for m in OFFER_RE.finditer(low):
        digits = (m.group(1) or m.group(2) or m.group(3) or "").replace(",", "")
        if not digits.isdigit():
            continue
        n = int(digits)
        if not 5_000 <= n <= 10_000_000:
            continue
        if any(n in (price, round(price * 1.18)) for price in list_prices):
            continue
        found.append(n)
    return min(found) if found else None




# "CALL ME" INSIDE A LONGER MESSAGE (live ...2521, 2026-11-04): "99727 15155 ಕರೆ ಮಾಡಿ ವಿಷಯ
# ತಿಳಿಸಿ" (call this number and tell me) was asked "when shall we call?" again. The bare
# words were read only as the whole message.
CALL_ME_RE = re.compile(r"(?:ಕರೆ|ಕಾಲ್|ಫೋನ್)\s*ಮಾಡಿ(?!ಲ್ಲ|ಲಿಲ್ಲ|ದ)|(?<![a-z])(?:call|cal|coll|phone|kal)\s*(?:madi|maadi|"
                         r"madri|maadri|me|madu)(?![a-z])")
# "DON'T CALL" (live ...8314, 2026-11-04): "ಕರೆ madabedi" was answered with the call-time
# question again, and the owner had to write "sari kare madalla".
NO_CALL_RE = re.compile(
    r"(?:ಕರೆ|ಕಾಲ್|ಫೋನ್|kare|call|cal|coll|phone|kal)\s*(?:ಮಾಡಬೇಡಿ|ಮಾಡ್ಬೇಡಿ|ಬೇಡ|ಮಾಡಬೇಡ|madabedi|madbedi|"
    r"maadbedi|maadabedi|madbeda|madabeda|beda|bedi|bed)(?![a-z])"
    r"|(?:don'?t|do not|dont|no)\s*(?:call|phone)|(?:only|just)\s*(?:whatsapp|message|msg)"
    r"|whatsapp\s*(?:alli|alle|nalli|nalle|li)\s*(?:heli|tilisi|kalisi|maatadi)|ಮೆಸೇಜ್\s*ಮಾಡಿ\s*ಸಾಕು", re.I)


def refuses_call(text: str) -> bool:
    """They asked NOT to be called: answered on WhatsApp, never asked for a call time again."""
    return bool(NO_CALL_RE.search((text or "").lower()))




PAY_RE = re.compile(
    r"\b(i\s*(will|'ll|wil|shall|can)\s*pay|will\s*pay|ready\s*to\s*pay|"
    r"pay\s*(maad|mad|kodt|kodu|karunga|kardunga|now|today|tomorrow)\w*|"
    r"payment\s*(maad|mad|kodt|kodu|ready|details?|link|kalis|kals|send|haak|hak)\w*|"
    r"advance\s*(kodt|kodu|kodo|maad|mad|pay|ready|send|kalis|kals|haak|hak)\w*|"
    r"send\s*(the\s*|me\s*)?(payment|account|bank|upi|gpay|qr)|"
    r"account\s*(details?|number|no)|upi|g\s*pay|phone\s*pe|paytm|qr\s*code)\b"
    r"|ಪೇ\s*ಮಾಡ|ಪೇಮೆಂಟ್|ಅಡ್ವಾನ್ಸ್|ಹಣ\s*(ಕಳಿಸ|ಹಾಕ|ಕೊಡ|ಕಟ್ಟ)|ದುಡ್ಡು\s*(ಕಳಿಸ|ಹಾಕ|ಕೊಡ|ಕಟ್ಟ)",
    re.IGNORECASE)
NOT_PAYING = re.compile(
    r"\b(won'?t|will\s*not|can'?t|cannot|not|never|no|illa|alla|beda|aagalla|agalla|"
    r"maadalla|madalla|kodalla|later)\b|ಇಲ್ಲ|ಅಲ್ಲ|ಬೇಡ|ಆಗಲ್ಲ|ಕೊಡಲ್ಲ|ಮಾಡಲ್ಲ|\?",
    re.IGNORECASE)


def said_will_pay(text: str) -> bool:
    """True when the customer says they will pay (or asks where to pay).
    A refusal, a "later" or a question about paying is not that."""
    t = text or ""
    return bool(PAY_RE.search(t)) and not NOT_PAYING.search(t)




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
