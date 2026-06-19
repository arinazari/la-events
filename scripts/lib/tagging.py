"""Deterministic multi-axis event tagger — pure and testable.

The catalog used to carry a single muddy `category` (assigned per-fetcher, so `music`
vs `electronic` vs `party` vs `live_music` overlapped) plus two booleans (`afterhours`,
`ra_pick`). That can't express "all-vinyl rooftop house," because kind, sound, and
format were collapsed onto one axis. This module derives FIVE orthogonal axes from
signals already on the record — source, category, start time, price, a venue gazetteer,
and title/lineup keywords — and stamps them under a `tags` block:

    tags.type     one of TYPES (MECE)            — what KIND of thing it is
    tags.genre[]  controlled genre vocab          — the SOUND / content
    tags.setting[] controlled setting vocab       — the ROOM
    tags.vibe[]   cross-cutting flags             — afterhours, free, queer, b2b, ...
    tags.region   one coarse geographic bucket    — eastside / dtla / westside / ...
    tags.near_home bool                            — walkable / short drive from home

Two-tier population by design: this is the cheap deterministic BASELINE over every
event; the scene-researcher overlay refines genre/subgenre for the top picks, drawing
from the same vocabulary (so the two can't drift). `category`, `afterhours`, `ra_pick`
are left untouched for scoring back-compat — `scoring.py` still keys off them.

Same idiom as geo.py / scoring.py: the vocab + gazetteer below are DEFAULTS; profile.yaml
(`tagging.venue_genre`, `tagging.venue_setting`, `tagging.regions`) extends them, and the
`near_home` set is reused straight from `scoring.near_home_neighborhoods`. City-portable
without code changes.

Public API:
  tag_event(event, profile=None)  -> dict   # the tags block for one record
  tag_catalog(catalog, profile)   -> catalog # stamp tags onto every record in place
  VOCAB                            -> dict   # the controlled vocabularies (for facets/docs)
"""

import re

# ── Axis 1: TYPE — exactly one per event, MECE (the cleaned `category`) ───────────
TYPES = ("club", "live-music", "film", "stage", "comedy", "market", "workshop",
         "art", "food-drink", "community", "other")

# ── Axis 2: GENRE — ordered (tag, pattern) rules; specific BEFORE general so
#    "tech-house" wins over "house". `\b...\b` keeps "house" out of "warehouse". ──
GENRE_ELECTRONIC = [
    ("tech-house", r"tech[\s-]?house"), ("deep-house", r"deep[\s-]?house"),
    ("afro-house", r"afro[\s-]?house|afrohouse"), ("melodic", r"melodic"),
    ("progressive", r"progressive|prog house"), ("house", r"house"),
    ("techno", r"techno"), ("minimal", r"minimal"), ("acid", r"acid"),
    ("electro", r"electro(?!nic)"), ("disco", r"disco|italo|nu-?disco"),
    ("trance", r"trance"), ("dnb", r"dnb|drum[\s&]?and[\s&]?bass|drum ?& ?bass|jungle"),
    ("dub", r"dub|dubstep|reggae|dancehall"), ("ambient", r"ambient|downtempo"),
    ("amapiano", r"amapiano"), ("garage", r"ukg|uk garage"),
    ("breakbeat", r"breakbeat|breaks"), ("bass", r"bass music|bassline"),
]
GENRE_LIVE = [
    ("jazz", r"jazz"), ("funk-soul", r"funk|soul|motown|r&b|rnb"),
    ("hip-hop", r"hip[\s-]?hop|rap"), ("punk", r"punk|hardcore"),
    ("metal", r"metal"), ("indie", r"indie"), ("folk", r"folk|americana|singer[\s-]?songwriter"),
    ("rock", r"rock|garage"), ("country", r"country"),
    ("latin", r"latin|cumbia|salsa|reggaeton|mariachi|banda"),
    ("experimental", r"experimental|noise|avant"),
    ("classical", r"classical|orchestra|symphony|chamber|philharmonic"),
    ("blues", r"blues"), ("pop", r"pop(?![\s-]?up)"),
]
GENRE_FILM = [
    ("rep/arthouse", r"vidiots|new bev|cinematheque|brain dead|aero|egyptian"),
]

# ── Axis 3: SETTING & Axis 2 hints by venue — high-confidence venues only.
#    Eclectic rooms (Zebulon, Gold Diggers) are deliberately LEFT to enrichment. ──
VENUE_GENRE = {
    "vibrato grill jazz": ["jazz"], "vibrato": ["jazz"], "sam first": ["jazz"],
    "the mint": ["jazz", "blues"], "mccabe": ["folk"],
    "the smell": ["punk", "experimental"], "the redwood": ["rock"],
}
VENUE_SETTING = {
    "vidiots": ["cinema"], "new beverly": ["cinema"], "vista": ["cinema"],
    "aero": ["cinema"], "egyptian": ["cinema"], "academy museum": ["cinema"],
    "cinematheque": ["cinema"],
    "del monte speakeasy": ["speakeasy"], "the smell": ["diy"],
    "pantages": ["theater"], "ahmanson": ["theater"], "wiltern": ["theater"],
    "el rey": ["theater"], "fonda": ["theater"], "regent": ["theater"],
    "the theatre at ace": ["theater"], "orpheum": ["theater"],
    "greek theatre": ["amphitheater"], "hollywood bowl": ["amphitheater"],
    "ford theatre": ["amphitheater"],
}
REP_CINEMA = ("vidiots", "new beverly", "vista", "cinematheque", "brain dead",
              "aero", "egyptian", "academy museum")

# ── Axis 5: REGION — coarse buckets over the messy neighborhood field ─────────────
REGIONS = {
    "eastside": {"silver lake", "silverlake", "echo park", "los feliz", "east hollywood",
        "atwater village", "atwater", "frogtown", "elysian valley", "highland park",
        "eagle rock", "glassell park", "cypress park", "lincoln heights", "virgil village",
        "historic filipinotown", "mount washington", "boyle heights", "thai town"},
    "dtla": {"dtla", "downtown", "downtown la", "arts district", "chinatown",
        "little tokyo", "westlake"},
    "hollywood": {"hollywood", "west hollywood", "weho", "thai town"},
    "westside": {"venice", "santa monica", "culver city", "mar vista", "west la",
        "westwood", "bel air", "brentwood", "marina del rey", "sawtelle", "playa vista"},
    "valley": {"glendale", "burbank", "north hollywood", "noho", "studio city",
        "sherman oaks", "van nuys", "tarzana", "pasadena", "south pasadena", "encino"},
    "south-bay": {"long beach", "san pedro", "torrance", "redondo beach", "inglewood"},
    "far": {"anaheim", "santa ana", "irvine", "san diego", "temecula", "ventura",
        "riverside", "costa mesa", "huntington beach", "oxnard", "yucaipa",
        "thousand oaks", "palm desert", "ojai", "pioneertown", "brea", "rowland heights"},
}

# The full controlled vocabulary, exported so build_dashboard can publish facets and
# the scene-researcher can be pointed at the same lists (one source of truth).
VOCAB = {
    "type": list(TYPES),
    "genre": [t for t, _ in GENRE_ELECTRONIC] + [t for t, _ in GENRE_LIVE]
             + ["rep/arthouse", "electronic"],
    "setting": ["rooftop", "warehouse", "outdoor", "listening-bar", "club", "bar",
                "theater", "amphitheater", "cinema", "speakeasy", "diy", "pool", "gallery"],
    "vibe": ["afterhours", "day-party", "sunset", "all-vinyl", "b2b", "residency",
             "queer", "drag", "burlesque", "tribute", "album-release", "festival",
             "analog-film", "q&a", "tba-location", "ra-pick", "free", "sold-out",
             "21+", "18+", "all-ages"],
    "region": list(REGIONS.keys()),
}

_CINEMA_KW = re.compile(r"\b(screening|matin[eé]e|double feature|q&a|q & a|35mm|70mm|16mm|"
                        r"film series|cinema)\b", re.I)
_COMEDY_KW = re.compile(r"\b(comedy|stand[\s-]?up|standup|improv|open mic)\b", re.I)
_MARKET_KW = re.compile(r"\b(market|flea|bazaar|farmers|swap meet|vintage fair)\b", re.I)
_WORKSHOP_KW = re.compile(r"\b(workshop|class|seminar)\b", re.I)
_DJ_KW = re.compile(r"\b(dj set|b2b|warehouse|rave|afters?|day party)\b", re.I)


def _hay(ev: dict) -> str:
    """Lowercased search text: title + organizers + detail + venue + lineup."""
    parts = [ev.get("title") or "", ev.get("organizers") or "",
             ev.get("detail") or "", ev.get("venue") or ""]
    parts += [str(a) for a in (ev.get("lineup") or [])]
    return " ".join(parts).lower()


def _hour(ev: dict):
    s = ev.get("start")
    if s and re.match(r"^\d{1,2}:", str(s)):
        try:
            return int(str(s).split(":")[0])
        except ValueError:
            return None
    return None


def _uniq(seq):
    """Order-preserving dedupe (genre priority matters)."""
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _cfg(profile: dict) -> dict:
    """Gazetteer + buckets from profile.yaml, merged onto the code defaults (geo idiom)."""
    profile = profile or {}
    tg = profile.get("tagging") or {}
    venue_genre = {**VENUE_GENRE, **{k.lower(): v for k, v in (tg.get("venue_genre") or {}).items()}}
    venue_setting = {**VENUE_SETTING, **{k.lower(): v for k, v in (tg.get("venue_setting") or {}).items()}}
    regions = {k: set(v) for k, v in REGIONS.items()}
    for k, v in (tg.get("regions") or {}).items():
        regions.setdefault(k, set()).update(x.lower() for x in v)
    near = {n.lower() for n in ((profile.get("scoring") or {}).get("near_home_neighborhoods") or [])}
    return {"venue_genre": venue_genre, "venue_setting": venue_setting,
            "regions": regions, "near_home": near}


def _resolve_type(ev: dict, hay: str) -> str:
    """The one MECE kind. Keyword guards override a mislabeled source category
    (e.g. an Acropolis Cinema 'screening' that Ticketmaster tagged `music`)."""
    cat = ev.get("category")
    srcs = set(ev.get("sources") or [])
    if cat == "film" or _CINEMA_KW.search(hay):
        return "film"
    if cat == "comedy" or _COMEDY_KW.search(hay):
        return "comedy"
    if cat == "theater":
        return "stage"
    if _MARKET_KW.search(hay):
        return "market"
    if _WORKSHOP_KW.search(hay):
        return "workshop"
    if cat in ("electronic", "party") or (srcs & {"ra", "19hz", "posh"}) or _DJ_KW.search(hay):
        return "club"
    if cat in ("music", "live_music"):
        return "live-music"
    return {"art": "art", "general": "other"}.get(cat, "other")


def _genre(ev: dict, typ: str, hay: str, cfg: dict) -> list:
    out = []
    venue = (ev.get("venue") or "").lower()
    if typ == "club":
        for tag, pat in GENRE_ELECTRONIC:
            if re.search(r"\b(" + pat + r")\b", hay):
                out.append(tag)
        if any(t.endswith("-house") for t in out):
            out = [t for t in out if t != "house"]  # "tech house" -> tech-house, not +house
        if not out:
            out.append("electronic")          # source-implied, subgenre unknown -> enrichment refines
    elif typ == "live-music":
        for tag, pat in GENRE_LIVE:
            if re.search(r"\b(" + pat + r")\b", hay):
                out.append(tag)
        if not out:                            # bare artist-name title -> fall back to the venue gazetteer
            for vk, gs in cfg["venue_genre"].items():
                if vk in venue:
                    out.extend(gs)
    elif typ == "film":
        if any(r in venue for r in REP_CINEMA):
            out.append("rep/arthouse")
    return _uniq(out)


def _setting(ev: dict, hay: str, cfg: dict) -> list:
    out = []
    venue = (ev.get("venue") or "").lower()
    for vk, ss in cfg["venue_setting"].items():
        if vk in venue:
            out.extend(ss)
    if any(r in venue for r in REP_CINEMA):
        out = ["cinema"]
    if re.search(r"\brooftop\b", hay):
        out.append("rooftop")
    if re.search(r"\bwarehouse\b", hay):
        out.append("warehouse")
    if re.search(r"\b(outdoor|open[\s-]?air|backyard|patio|garden|courtyard)\b", hay):
        out.append("outdoor")
    if re.search(r"\b(pool|poolside)\b", hay):
        out.append("pool")
    if re.search(r"\b(listening bar|listening room|all[\s-]?vinyl)\b", hay):
        out.append("listening-bar")
    if re.search(r"\b(gallery|museum)\b", hay):
        out.append("gallery")
    return _uniq(out)


def _vibe(ev: dict, typ: str, hay: str) -> list:
    out = []
    hour = _hour(ev)
    price = str(ev.get("price") or "").lower()
    if ev.get("afterhours") or (hour is not None and (hour >= 22 or hour < 5)):
        out.append("afterhours")
    if typ == "club" and hour is not None and 11 <= hour <= 16:
        out.append("day-party")
    if re.search(r"\b(sunset|golden hour)\b", hay):
        out.append("sunset")
    if re.search(r"\b(all[\s-]?vinyl|vinyl[\s-]?only)\b", hay):
        out.append("all-vinyl")
    if re.search(r"\bb2b\b", hay):
        out.append("b2b")
    if re.search(r"\bresidency|resident\b", hay):
        out.append("residency")
    if re.search(r"\b(queer|lgbtq|pride|gay|sapphic)\b", hay):
        out.append("queer")
    if re.search(r"\bdrag\b", hay):
        out.append("drag")
    if re.search(r"\bburlesque\b", hay):
        out.append("burlesque")
    if re.search(r"\btribute|cover band\b", hay):
        out.append("tribute")
    if re.search(r"\b(album|record|ep) release\b", hay):
        out.append("album-release")
    if re.search(r"\bfestival\b", hay):
        out.append("festival")
    if re.search(r"\b(35mm|70mm|16mm)\b", hay):
        out.append("analog-film")
    if re.search(r"\bq&a|q & a\b", hay):
        out.append("q&a")
    venue = (ev.get("venue") or "").lower()
    if "tba" in venue or re.search(r"\b(location )?tba\b|drops? (after|day)", hay):
        out.append("tba-location")
    if ev.get("ra_pick"):
        out.append("ra-pick")
    if "free" in price:
        out.append("free")
    if re.search(r"\bsold out\b", hay):
        out.append("sold-out")
    if re.search(r"\b21\s?\+|21 and over\b", hay):
        out.append("21+")
    elif re.search(r"\b18\s?\+|18 and over\b", hay):
        out.append("18+")
    elif re.search(r"\ball ages\b", hay):
        out.append("all-ages")
    return _uniq(out)


def _region(ev: dict, cfg: dict):
    nb = (ev.get("neighborhood") or "").lower().strip()
    if not nb:
        return None, False
    region = next((name for name, hoods in cfg["regions"].items() if nb in hoods), None)
    return region, nb in cfg["near_home"]


def tag_event(ev: dict, profile: dict = None) -> dict:
    """Derive the five-axis `tags` block for one catalog record. Pure; deterministic."""
    cfg = _cfg(profile)
    hay = _hay(ev)
    typ = _resolve_type(ev, hay)
    region, near_home = _region(ev, cfg)
    return {
        "type": typ,
        "genre": _genre(ev, typ, hay, cfg),
        "setting": _setting(ev, hay, cfg),
        "vibe": _vibe(ev, typ, hay),
        "region": region,
        "near_home": near_home,
    }


def tag_catalog(catalog: list, profile: dict = None) -> list:
    """Stamp `tags` onto every record in place (idempotent — recomputed each run)."""
    for ev in catalog:
        ev["tags"] = tag_event(ev, profile)
    return catalog
