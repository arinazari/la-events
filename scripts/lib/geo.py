"""Rough travel/timing engine for the night-planner (offline, deterministic).

The night-planner sequences dinner -> show -> afters; it needs *rough* LA travel
times, not turn-by-turn directions. We estimate from straight-line (haversine)
distance between neighborhood centroids (or known venues) and a simple congestion
model. Good enough to decide "walk or drive?", order the stops sensibly, and budget
the clock — without an API call on every plan.

Same idiom as scoring.py: the LA gazetteer + knobs below are DEFAULTS; profile.yaml
(`home.coords`, `geo.travel`, `geo.neighborhoods`, `geo.venues`) overrides them, so
the engine is city-portable without code changes. Resolution is forgiving: a place
can be a neighborhood name OR a known venue (catalog records are often venue-rich but
neighborhood-poor — 291 blank / 113 city-level at last count), normalized for "The",
punctuation, and common suffixes.

Public API:
  resolve(place, profile=None)            -> (lat, lon) | None
  haversine_miles(a, b)                   -> float
  drive_minutes(miles, profile=None)      -> int
  walk_minutes(miles, profile=None)       -> int
  hop(a, b, profile=None)                 -> dict   # one leg
  plan_route(stops, profile=None)         -> dict   # ordered legs[] + totals
"""

from math import asin, cos, radians, sin, sqrt

# ── Defaults: an LA gazetteer + travel knobs (override in profile.yaml) ───────────
# Neighborhood centroids (lat, lon). Eastside/near-home is dense (that's home turf);
# the rest is coarse but enough to budget a hop and flag "worth the drive?".
DEFAULT_HOME = (34.0906, -118.2717)  # Silver Lake, ~Hyperion & Del Mar

DEFAULT_NEIGHBORHOODS = {
    # eastside / near home
    "silver lake": (34.0869, -118.2702), "silverlake": (34.0869, -118.2702),
    "echo park": (34.0782, -118.2606), "los feliz": (34.1075, -118.2890),
    "east hollywood": (34.0905, -118.2920), "virgil village": (34.0905, -118.2860),
    "thai town": (34.1010, -118.2920), "atwater village": (34.1187, -118.2606),
    "atwater": (34.1187, -118.2606), "frogtown": (34.1080, -118.2540),
    "elysian valley": (34.1080, -118.2540), "highland park": (34.1156, -118.1926),
    "eagle rock": (34.1397, -118.2120), "glassell park": (34.1110, -118.2270),
    "cypress park": (34.0940, -118.2240), "mount washington": (34.1110, -118.2150),
    "lincoln heights": (34.0700, -118.2090), "chinatown": (34.0640, -118.2370),
    "boyle heights": (34.0337, -118.2100),
    # SGV (major dining region just east)
    "alhambra": (34.0953, -118.1270), "san gabriel": (34.0961, -118.1058),
    "monterey park": (34.0625, -118.1228), "arcadia": (34.1397, -118.0353),
    "rosemead": (34.0805, -118.0728), "rowland heights": (33.9762, -117.9053),
    # downtown core
    "dtla": (34.0440, -118.2510), "downtown": (34.0440, -118.2510),
    "downtown la": (34.0440, -118.2510), "arts district": (34.0410, -118.2330),
    "historic filipinotown": (34.0640, -118.2790), "westlake": (34.0590, -118.2790),
    "koreatown": (34.0580, -118.3000), "ktown": (34.0580, -118.3000),
    "university park": (34.0250, -118.2840),
    # central / mid-city / hollywood
    "hollywood": (34.1016, -118.3267), "west hollywood": (34.0900, -118.3850),
    "weho": (34.0900, -118.3850), "mid-city": (34.0480, -118.3500),
    "mid city": (34.0480, -118.3500), "mid-wilshire": (34.0620, -118.3400),
    "miracle mile": (34.0620, -118.3500), "larchmont": (34.0750, -118.3240),
    "fairfax": (34.0790, -118.3610),
    # westside
    "beverly hills": (34.0736, -118.4004), "culver city": (34.0211, -118.3965),
    "mar vista": (34.0000, -118.4300), "venice": (33.9900, -118.4600),
    "santa monica": (34.0195, -118.4912), "west la": (34.0400, -118.4400),
    "sawtelle": (34.0400, -118.4450), "brentwood": (34.0520, -118.4730),
    # valley
    "north hollywood": (34.1722, -118.3789), "noho": (34.1722, -118.3789),
    "studio city": (34.1395, -118.3870), "sherman oaks": (34.1510, -118.4490),
    "burbank": (34.1808, -118.3090), "glendale": (34.1425, -118.2551),
    "pasadena": (34.1478, -118.1445), "south pasadena": (34.1161, -118.1503),
    # farther afield (kept coarse — mostly to say "that's a haul")
    "inglewood": (33.9617, -118.3531), "long beach": (33.7701, -118.1937),
    "san pedro": (33.7361, -118.2922), "anaheim": (33.8366, -117.9143),
    "pomona": (34.0551, -117.7500), "malibu": (34.0259, -118.7798),
}

# Venue -> neighborhood, for catalog records that are blank/city-level. Grows as needed;
# the planner can web-look-up anything missing. Keys are normalized (see _norm).
DEFAULT_VENUES = {
    "zebulon": "frogtown", "vidiots": "eagle rock", "vista theatre": "los feliz",
    "vista": "los feliz", "lodge room": "highland park",
    "2220 arts archives": "historic filipinotown", "2220 arts": "historic filipinotown",
    "el cid": "silver lake", "echo": "echo park", "echoplex": "echo park",
    "the echo": "echo park", "teragram ballroom": "westlake", "teragram": "westlake",
    "moroccan lounge": "arts district", "troubadour": "west hollywood",
    "roxy": "west hollywood", "roxy theatre": "west hollywood",
    "whisky a go go": "west hollywood", "fonda theatre": "hollywood", "fonda": "hollywood",
    "greek theatre": "los feliz", "the greek theatre": "los feliz",
    "hollywood bowl": "hollywood", "novo": "dtla", "the novo": "dtla",
    "shrine auditorium": "university park", "shrine expo hall": "university park",
    "regent theater": "dtla", "the regent": "dtla", "mayan": "dtla", "the mayan": "dtla",
    "gold diggers": "east hollywood", "virgil": "virgil village", "the virgil": "virgil village",
    "mint": "mid-city", "the mint": "mid-city",
    "permanent records roadhouse": "cypress park", "permanent records": "cypress park",
    "grand star jazz club": "chinatown", "grand star": "chinatown",
    "el rey theatre": "mid-wilshire", "el rey": "mid-wilshire",
    "wiltern": "koreatown", "the wiltern": "koreatown", "belasco": "dtla", "the belasco": "dtla",
    "exchange la": "dtla", "exchange": "dtla", "the bellwether": "dtla",
    "catch one": "mid-city", "1720": "arts district", "sound": "hollywood",
    "sound nightclub": "hollywood", "academy la": "hollywood", "academy": "hollywood",
    "avalon": "hollywood", "hollywood palladium": "hollywood", "palladium": "hollywood",
    "los globos": "silver lake", "the satellite": "silver lake", "gold room": "echo park",
    "the short stop": "echo park", "club tee gee": "atwater", "footsies": "cypress park",
    "la cita": "dtla", "harvard stone": "east hollywood", "the lash": "dtla",
    "bar franca": "silver lake", "the bridge": "dtla",
    "level 8": "dtla", "golden hour at level 8": "dtla",
}

DEFAULT_TRAVEL = {
    "walk_max_miles": 0.8,       # at/under this straight-line, prefer walking
    "walk_min_per_mile": 20.0,   # ~3 mph
    "drive_floor_min": 8,        # any drive costs at least this (parking, getting going)
    "park_buffer_min": 6,        # find parking + walk from the car
    "short_min_per_mile": 4.0,   # surface streets, lights (~15 mph effective)
    "long_min_per_mile": 2.4,    # some freeway on longer hops (~25 mph effective)
    "short_threshold_miles": 4,  # beyond this, the tail is freeway-paced
}


def _norm(s: str) -> str:
    """Normalize a place string for lookup: lowercase, drop 'the', '+', '&', punctuation."""
    s = (s or "").strip().lower()
    if s.startswith("the "):
        s = s[4:]
    out = []
    for ch in s:
        if ch.isalnum() or ch == " ":
            out.append(ch)
        elif ch in "+&/-'.":
            out.append(" ")
    return " ".join("".join(out).split())


def _geo_cfg(profile: dict) -> dict:
    """Resolve gazetteer + knobs from profile.yaml, falling back to DEFAULT_*."""
    profile = profile or {}
    geo = profile.get("geo") or {}
    home = (profile.get("home") or {}).get("coords") or DEFAULT_HOME
    hoods = {_norm(k): tuple(v) for k, v in (geo.get("neighborhoods") or DEFAULT_NEIGHBORHOODS).items()}
    venues = {_norm(k): _norm(v) for k, v in (geo.get("venues") or DEFAULT_VENUES).items()}
    travel = {**DEFAULT_TRAVEL, **(geo.get("travel") or {})}
    return {"home": tuple(home), "neighborhoods": hoods, "venues": venues, "travel": travel}


def resolve(place, profile: dict = None):
    """(lat, lon) for a neighborhood name OR known venue, else None.

    'home' resolves to the configured home coords. A venue resolves via its mapped
    neighborhood. Matching is normalized and tolerant of substrings (venue strings
    carry suffixes like 'Theatre', 'Lounge')."""
    if place is None:
        return None
    if isinstance(place, (tuple, list)) and len(place) == 2:
        return (float(place[0]), float(place[1]))
    cfg = _geo_cfg(profile)
    key = _norm(str(place))
    if not key:
        return None
    if key in ("home", "house", "my place"):
        return cfg["home"]
    if key in cfg["neighborhoods"]:
        return cfg["neighborhoods"][key]
    if key in cfg["venues"]:
        return cfg["neighborhoods"].get(cfg["venues"][key])
    # substring fallback: longest known venue/neighborhood contained in the string
    for table in (cfg["venues"], cfg["neighborhoods"]):
        hits = [name for name in table if name and (name in key or key in name)]
        if hits:
            best = max(hits, key=len)
            return cfg["neighborhoods"].get(table[best]) if table is cfg["venues"] else cfg["neighborhoods"][best]
    return None


def haversine_miles(a, b) -> float:
    """Great-circle miles between (lat, lon) points a and b."""
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * asin(sqrt(h)) * 3958.8


def drive_minutes(miles: float, profile: dict = None) -> int:
    """Rough door-to-door drive time. Piecewise: surface streets, then freeway-paced
    on the tail of longer hops; a parking buffer and a floor keep short hops honest."""
    t = _geo_cfg(profile)["travel"]
    if miles <= 0:
        return 0
    thr = t["short_threshold_miles"]
    if miles <= thr:
        mins = t["park_buffer_min"] + miles * t["short_min_per_mile"]
    else:
        mins = t["park_buffer_min"] + thr * t["short_min_per_mile"] + (miles - thr) * t["long_min_per_mile"]
    return int(round(max(t["drive_floor_min"], mins)))


def walk_minutes(miles: float, profile: dict = None) -> int:
    t = _geo_cfg(profile)["travel"]
    return int(round(max(0, miles) * t["walk_min_per_mile"]))


def walkable(miles: float, profile: dict = None) -> bool:
    return miles <= _geo_cfg(profile)["travel"]["walk_max_miles"]


def hop(a, b, profile: dict = None) -> dict:
    """One leg between two places (names, venues, or coords). mode: walk | drive | unknown."""
    ca, cb = resolve(a, profile), resolve(b, profile)
    leg = {"from": a, "to": b}
    if not ca or not cb:
        unplaced = a if not ca else b
        leg.update({"miles": None, "mode": "unknown", "minutes": None,
                    "note": f"couldn't place '{unplaced}' — estimate by hand or web-look it up"})
        return leg
    mi = round(haversine_miles(ca, cb), 1)
    if walkable(mi, profile):
        leg.update({"miles": mi, "mode": "walk", "minutes": walk_minutes(mi, profile)})
    else:
        leg.update({"miles": mi, "mode": "drive", "minutes": drive_minutes(mi, profile)})
    return leg


def plan_route(stops, profile: dict = None) -> dict:
    """Sequence an ordered list of stops into legs + totals.

    `stops` is a list of place strings (or coords). Returns {legs, total_minutes,
    total_miles, unplaced} — unplaced flags stops the gazetteer couldn't locate."""
    legs, total_min, total_mi, unplaced = [], 0, 0.0, []
    for i in range(len(stops) - 1):
        leg = hop(stops[i], stops[i + 1], profile)
        legs.append(leg)
        if leg["minutes"] is not None:
            total_min += leg["minutes"]
            total_mi += leg["miles"] or 0
        else:
            for end in (stops[i], stops[i + 1]):
                if resolve(end, profile) is None and end not in unplaced:
                    unplaced.append(end)
    return {"legs": legs, "total_minutes": total_min,
            "total_miles": round(total_mi, 1), "unplaced": unplaced}
