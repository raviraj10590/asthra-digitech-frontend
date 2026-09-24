"""The price rule after the owner's ruling of 2026-09-24.

Before: no reply may contain any price. Now: a reply may contain the owner's
four list prices — and nothing else that looks like money. Every figure must
be one of them, exactly as written in bairavi.PRICE_LIST, and followed by
"+ GST" (the GST rate was never stated, so no total may be computed). The
design package's 68,244 is still never a price.
"""
import re

import bairavi as b

OWNER_PRICES = {b.inr(amount) for amount, _star in b.PRICE_LIST.values()}
_MONEY = re.compile(r"(?:₹|\brs\.?|\binr\b|\brupees?\b)\s*([\d,]+)", re.I)


def owner_price_violations(text: str) -> list:
    """Every reason this text breaks the rule; empty when it complies."""
    t = text or ""
    problems = []
    if "68244" in t.replace(",", ""):
        problems.append("the design-package figure 68,244")
    if re.search(r"\blakh", t, re.I):
        problems.append("a 'lakh' amount (the list is written in full)")
    for m in _MONEY.finditer(t):
        amount = m.group(1).rstrip(",")
        if amount not in OWNER_PRICES:
            problems.append(f"an amount not on the owner's list: {m.group(0)!r}")
        elif not re.match(r"\s*\+\s*GST", t[m.end():m.end() + 10], re.I):
            problems.append(f"{m.group(0)!r} without '+ GST'")
    for word in ("discount", "offer price", "% off", "margin", "per kg"):
        if word in t.lower():
            problems.append(f"costing/discount wording: {word!r}")
    return problems


def assert_only_owner_prices(tc, text, msg=None):
    tc.assertEqual(owner_price_violations(text), [], msg or text[:200])
