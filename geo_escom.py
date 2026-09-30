"""A shared WhatsApp location -> place, ESCOM area, distance (owner request 2026-10-01).

Customers type places we cannot read ("Idi", "Fre.aitti.sar", "TQ Ramdurga
Dist Belgaum Toranagatti"). A location pin is exact. From it we get the
village / taluk / district (reverse geocoding, done by api/webhook.py) and,
from the district, which electricity supply company serves it — the thing a
farmer most needs to know, because an unapproved transformer cannot be
energised on that company's network.

WHAT IS FACT HERE
  District -> ESCOM is public Karnataka geography (five ESCOMs, by district).
  The APPROVAL status is NOT here: bairavi._DISCOM_APPROVAL_STATED is the one
  owner-stated table, and the reply is generated from it.
  Distance is a straight line from Kadaba town, shown to the OWNER only, and
  labelled approximate — it is not a delivery promise.

Pure: no network.
"""
import math
import re

# Karnataka's five ESCOMs by district. Keys are normalised district names
# (lower case, letters only); several spellings are listed because the
# geocoder returns old and new names ("Belgaum" / "Belagavi").
_ESCOM_BY_DISTRICT = {}
for _escom, _districts in {
    "mescom": ("dakshina kannada", "udupi", "shivamogga", "shimoga", "chikkamagaluru",
               "chikmagalur", "chikkamagalur"),
    "cesc": ("mysuru", "mysore", "chamarajanagar", "chamarajanagara", "mandya", "hassan",
             "kodagu", "coorg"),
    "bescom": ("bengaluru urban", "bangalore urban", "bengaluru", "bangalore",
               "bengaluru rural", "bangalore rural", "ramanagara", "ramanagaram",
               "bengaluru south", "kolar", "chikkaballapura", "chikballapur",
               "chikkaballapur", "tumakuru", "tumkur", "chitradurga", "davanagere",
               "davangere"),
    "hescom": ("belagavi", "belgaum", "bagalkote", "bagalkot", "vijayapura", "bijapur",
               "dharwad", "gadag", "haveri", "uttara kannada", "karwar"),
    "gescom": ("kalaburagi", "gulbarga", "bidar", "raichur", "koppal", "ballari", "bellary",
               "yadgir", "yadagiri", "vijayanagara", "vijayanagar"),
}.items():
    for _d in _districts:
        _ESCOM_BY_DISTRICT[_d] = _escom

# Kadaba town, Dakshina Kannada (approximate centre). Owner-facing distance only.
KADABA = (12.7703, 75.4520)


def _norm(name: str) -> str:
    low = (name or "").lower()
    low = re.sub(r"\b(district|dist\.?|taluk|taluka)\b", " ", low)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", low)).strip()


def escom_for(district: str, state: str = "Karnataka"):
    """'mescom' / 'cesc' / 'bescom' / 'hescom' / 'gescom', or None when the
    state is not Karnataka or the district is not recognised."""
    if state and _norm(state) != "karnataka":
        return None
    return _ESCOM_BY_DISTRICT.get(_norm(district))


def distance_km(lat: float, lon: float, origin=KADABA) -> int:
    """Great-circle distance in whole km (haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (origin[0], origin[1], lat, lon))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return round(2 * 6371 * math.asin(math.sqrt(h)))


def place_from_address(addr: dict, name: str = "", address: str = "") -> dict:
    """{place, district, state} from a reverse-geocoder address (Nominatim
    jsonv2 'address'), falling back to what WhatsApp itself sent."""
    addr = addr or {}
    local = (addr.get("village") or addr.get("hamlet") or addr.get("town")
             or addr.get("suburb") or addr.get("city") or addr.get("neighbourhood") or "")
    taluk = addr.get("county") or addr.get("subdistrict") or ""
    district = addr.get("state_district") or addr.get("district") or ""
    state = addr.get("state") or ""
    parts = []
    for p in (local, taluk, district):
        p = re.sub(r"\s+(taluk|taluka|taluku|district)$", "", (p or "").strip(), flags=re.I)
        if p and p.lower() not in (x.lower() for x in parts):
            parts.append(p)
    place = ", ".join(parts) or (name or "").strip() or (address or "").strip()
    return {"place": place[:60], "district": district, "state": state}


# The transcript line itself is bairavi.location_text / parse_location_text,
# because the Bairavi reader must understand it on replay and bairavi.py
# imports only re and hashlib.


def maps_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
