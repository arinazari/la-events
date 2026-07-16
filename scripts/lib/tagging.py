"""Deterministic multi-axis event tagger — pure and testable.

The catalog used to carry a single muddy `category` (assigned per-fetcher, so `music`
vs `electronic` vs `party` vs `live_music` overlapped) plus two booleans (`afterhours`,
`ra_pick`). That can't express "all-vinyl rooftop house," because kind, sound, and
format were collapsed onto one axis. This module derives SIX orthogonal axes from
signals already on the record — source, category, start time, price, a venue gazetteer,
and title/lineup keywords — and stamps them under a `tags` block:

    tags.type     one of TYPES (MECE)            — what KIND of thing it is
    tags.genre[]  controlled genre vocab          — the SOUND / content
    tags.setting[] controlled setting vocab       — the ROOM
    tags.scale    bar | room | hall | arena       — the venue TIER (None = unknown)
    tags.vibe[]   cross-cutting flags             — afterhours, free, queer, b2b, ...
    tags.region   one coarse geographic bucket    — eastside / dtla / westside / ...
    tags.near_home bool                            — walkable / short drive from home

Two-tier population by design: this is the cheap deterministic BASELINE over every
event; the scene-researcher overlay refines genre/subgenre for the top picks, drawing
from the same vocabulary (so the two can't drift). `category`, `afterhours`, `ra_pick`
are left untouched for scoring back-compat — `scoring.py` still keys off them.

`scale` is a FACT axis (venue tier), not a taste call: lib/assemble consumes it for the
two lane decisions that need it (live-music:big, club:mainstream) and everything else —
facets, editor records — gets it as context. Character-vs-size mismatches in both
directions (a Berghain-tier booking at a big-room club; an 80s night at Zebulon) stay
the event-editor's lane-override job, per Track B.

Same idiom as geo.py / scoring.py: the vocab + gazetteer below are DEFAULTS; profile.yaml
(`tagging.venue_genre`, `tagging.venue_setting`, `tagging.venue_scale`, `tagging.regions`)
extends them, and the `near_home` set is reused straight from
`scoring.near_home_neighborhoods`. City-portable without code changes.

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
#    "tech-house" wins over "house" and "hard techno" never reads as the refined
#    techno lane. `\b...\b` keeps "house" out of "warehouse". The hard-dance /
#    dubstep tags exist so taste.yaml's penalty lanes (hardstyle/gabber/riddim/
#    brostep) are DETECTABLE — before this, "GIRLS NIGHT OUT HARD TECHNO" tagged
#    as loved `techno`, inverting the signal. ──────────────────────────────────────
GENRE_ELECTRONIC = [
    ("tech-house", r"tech[\s-]?house"), ("deep-house", r"deep[\s-]?house"),
    ("afro-house", r"afro[\s-]?house|afrohouse"), ("melodic", r"melodic"),
    ("progressive", r"progressive|prog house"), ("house", r"house"),
    ("hard-techno", r"hard[\s-]?techno"),
    ("hard-dance", r"hardstyle|gabber|happy[\s-]?hardcore|hard[\s-]?dance|hardcore|donk"),
    ("techno", r"techno"), ("minimal", r"minimal"), ("acid", r"acid"),
    ("electro", r"electro(?!nic)"), ("disco", r"disco|italo|nu-?disco"),
    ("psytrance", r"psy[\s-]?trance"), ("trance", r"trance"),
    ("dnb", r"dnb|drum[\s&]?and[\s&]?bass|drum ?& ?bass|jungle"),
    ("dubstep", r"dubstep|riddim|brostep"),      # penalized lane — split from boosted dub
    ("reggae", r"reggae|dancehall"),
    ("dub", r"dub"),
    ("ambient", r"ambient|downtempo"),
    ("amapiano", r"amapiano"), ("garage", r"ukg|uk garage|speed garage|garage"),
    ("breakbeat", r"breakbeat|breaks"), ("bass", r"bass music|bassline"),
    ("edm", r"edm|big[\s-]?room"),
]
# specific-implies-general pairs: when the specific tag fired, the general word it
# contains is noise ("tech house" -> tech-house, not +house; "hard techno" != techno).
_GENRE_SHADOWS = {"tech-house": "house", "deep-house": "house", "afro-house": "house",
                  "hard-techno": "techno", "psytrance": "trance"}
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
# Stage subtype — title-only keyword rules (a detail blurb calling Oklahoma! "a comedy"
# must not add subtypes either); the TM genre map below does the heavy lifting (94% of
# stage rows carry a TM genre).
GENRE_STAGE = [
    ("musical", r"\bmusical\b"), ("ballet", r"ballet|nutcracker"), ("opera", r"\bopera\b"),
]
# Comedy subtype — makes the taste.yaml "open-mics" penalty and the improv/standup
# distinction machine-visible (all 181 comedy rows had empty genre before).
GENRE_COMEDY = [
    ("improv", r"\bimprov\b|improvised"), ("open-mic", r"open[\s-]?mic"),
    ("standup", r"stand[\s-]?up|standup"), ("sketch", r"\bsketch\b"),
    ("podcast", r"\bpodcast\b|\btaping\b"),
]

# Ticketmaster Discovery `genre` names → the controlled live vocab. TM's taxonomy arrives
# capitalized ("Rock", "Hip-Hop/Rap"); an explicit map is safer than folding the field into
# the keyword haystack (which would also expose those words to the vibe/setting regexes).
TM_GENRE_LIVE = {
    "rock": "rock", "pop": "pop", "hip-hop/rap": "hip-hop", "latin": "latin",
    "country": "country", "r&b": "funk-soul", "metal": "metal", "alternative": "indie",
    "folk": "folk", "jazz": "jazz", "classical": "classical", "blues": "blues",
    "reggae": "reggae", "dance/electronic": "electronic", "world": "world",
    "folk/acoustic/americana": "folk", "edm": "electronic",
}

# TM "Arts & Theatre" genres that are unambiguously stage acts. The genre-less remainder is
# contaminated (bare-name comedians next to touring musicals), so it does NOT blanket-map —
# unmatched A&T stays `other` (honest null) unless a stage keyword or the attraction-level
# `lineup_genre` (fetch_ticketmaster) rescues it.
TM_STAGE_GENRES = {
    "theatre", "children's theatre", "miscellaneous theatre", "dance", "classical",
    "opera", "performance art", "magic & illusion", "circus & specialty acts",
    "variety", "multimedia", "puppetry",
}
# …and their mapping into the stage subtype vocab (tags.genre for type=stage).
TM_GENRE_STAGE = {
    "theatre": "theater", "miscellaneous theatre": "theater", "children's theatre": "family",
    "dance": "dance", "classical": "classical", "opera": "opera",
    "performance art": "performance-art", "magic & illusion": "magic",
    "circus & specialty acts": "circus", "variety": "variety", "puppetry": "puppetry",
    "multimedia": "performance-art",
}
_STAGE_KW = re.compile(r"\(touring\)|\b(ballet|circus|stage show|the musical)\b", re.I)
# TITLE-only stage words — `broadway` must never scan the full hay (venue names like "The
# United Theater on Broadway" would retype bare-name comedians), and `ballet` here is
# prefix-only so "BalletNow" matches.
_STAGE_TITLE_KW = re.compile(r"\bballet|\b(broadway|nutcracker|the musical|opera)\b", re.I)
# Title-level live-music rescues for the genre-less A&T / Miscellaneous fall-throughs
# (regional-Mexican bookings and festival runs TM files under Arts & Theatre).
_LIVE_TITLE_KW = re.compile(r"\b(banda|corridos?|cumbia|sonidero|mariachi|music festival)\b", re.I)

# Categories that explicitly say "this is a music event" — keyword type-guards for these scan
# only title+venue (see _resolve_type), so detail-blob noise can't retype a concert.
MUSIC_CATS = frozenset(("music", "live_music", "jazz", "electronic", "party"))

# ── Axis 3: SETTING & Axis 2 hints by venue — high-confidence venues only.
#    Eclectic rooms' GENRE (Zebulon, Gold Diggers) is deliberately LEFT to enrichment;
#    their setting (a bar is a bar) is safe to stamp. ──────────────────────────────
VENUE_GENRE = {
    "vibrato grill jazz": ["jazz"], "vibrato": ["jazz"], "sam first": ["jazz"],
    "the mint": ["jazz", "blues"], "mccabe": ["folk"],
    "the smell": ["punk", "experimental"], "the redwood": ["rock"],
    "harvelle": ["blues", "funk-soul"], "maui sugar mill": ["blues", "rock"],
    "alva's showroom": ["jazz"], "del monte speakeasy": ["jazz"],
    "permanent records": ["punk", "rock"],
}
VENUE_SETTING = {
    # cinemas / theaters / amphitheaters (the original tier)
    "vidiots": ["cinema"], "new beverly": ["cinema"], "vista": ["cinema"],
    "aero": ["cinema"], "egyptian": ["cinema"], "academy museum": ["cinema"],
    "cinematheque": ["cinema"],
    "del monte speakeasy": ["speakeasy"], "the smell": ["diy"],
    "pantages": ["theater"], "ahmanson": ["theater"], "wiltern": ["theater"],
    "el rey": ["theater"], "fonda": ["theater"], "regent": ["theater"],
    "the theatre at ace": ["theater"], "orpheum": ["theater"],
    "greek theatre": ["amphitheater"], "hollywood bowl": ["amphitheater"],
    "ford theatre": ["amphitheater"],
    # clubs (big-room and small) — before this tier the `club` setting was emitted 0 times
    "sound nightclub": ["club"], "exchange la": ["club"], "academy la": ["club"],
    "avalon": ["club"], "catch one": ["club"], "the circle oc": ["club"],
    "time nightclub": ["club"], "dragonfly": ["club"], "kiss kiss bang bang": ["club"],
    "jungle hollywood": ["club"], "grand star": ["club"], "the echo": ["club"],
    "echoplex": ["club"], "1720": ["warehouse"],
    # listening bars (a HIGH taste lane that previously matched ONCE, by keyword)
    "sam first": ["listening-bar"], "bar franca": ["listening-bar"],
    "only the wild ones": ["listening-bar"], "gold line": ["listening-bar"],
    "in sheep's clothing": ["listening-bar"],
    # live-music bars (the sources.yaml bar/restaurant lane)
    "gold diggers": ["bar"], "the dresden": ["bar"], "the baked potato": ["bar"],
    "vibrato": ["bar"], "the mint": ["bar"], "the redwood": ["bar"],
    "the lexington": ["bar"], "the airliner": ["bar"], "slipper clutch": ["bar"],
    "zebulon": ["bar"], "the virgil": ["bar"], "permanent records": ["bar"],
    "harvelle": ["bar"], "mccabe": ["bar"], "venice west": ["bar"],
    "alva's showroom": ["bar"], "maui sugar mill": ["bar"], "high tide": ["bar"],
    "el cid": ["bar"], "townhouse": ["speakeasy"],
    # diy rooms
    "junior high": ["diy"], "sid the cat": ["diy"], "2220 arts": ["diy"],
    "coaxial": ["diy"],
    # outdoor fixtures
    "state historic park": ["outdoor"], "grand park": ["outdoor"],
    "pershing square": ["outdoor"], "cinespia": ["outdoor"],
}
REP_CINEMA = ("vidiots", "new beverly", "vista", "cinematheque", "brain dead",
              "aero", "egyptian", "academy museum", "cinespia",
              "palm springs cultural center")

# ── Axis 4: SCALE — the venue TIER, a pure fact axis. Explicit gazetteer only (no
#    name-keyword sweep: "Garden Amphitheatre" is a Garden Grove punk shed and "Libbey
#    Bowl" seats 1,300 — a /bowl|amphitheat/ sweep would file both as arenas).
#    hall ≈ the 1,500+ rooms and big-room clubs; room ≈ the 300–1,500 live rooms
#    (the taste-HIGH tier); bar ≈ the bar/listening rooms. `amphitheater` setting
#    also implies arena. lib/assemble maps hall+arena → live-music:big / club:mainstream. ──
VENUE_SCALE = {
    **{v: "arena" for v in (
        "hollywood bowl", "kia forum", "the forum", "crypto.com arena", "bmo stadium",
        "sofi stadium", "greek theatre", "intuit dome", "microsoft theater",
        "peacock theater", "honda center", "youtube theater", "toyota arena", "acrisure",
        "yaamava", "shrine", "dodger stadium", "rose bowl", "banc of california",
        "morongo", "pechanga", "agua caliente", "fantasy springs", "pacific amphitheatre",
        "glen helen", "cerritos center")},
    **{v: "hall" for v in (
        "wiltern", "hollywood palladium", "the bellwether", "the novo", "belasco",
        "avalon", "house of blues", "walt disney concert hall", "orpheum",
        "the theatre at ace", "dolby theatre", "pantages", "ahmanson", "dorothy chandler",
        "royce hall", "saban", "exchange la", "academy la", "time nightclub",
        "the circle oc", "hollywood park grounds")},
    **{v: "room" for v in (
        "troubadour", "fonda", "el rey", "the regent", "roxy", "whisky a go go",
        "the echo", "echoplex", "zebulon", "moroccan lounge", "teragram", "lodge room",
        "masonic lodge", "catch one", "sound nightclub", "1720", "the smell",
        "2220 arts", "pappy", "lewis family playhouse")},
    **{v: "bar" for v in (
        "sam first", "vibrato", "the mint", "mccabe", "alva's showroom", "harvelle",
        "maui sugar mill", "del monte speakeasy", "junior high", "permanent records",
        "the redwood", "gold diggers", "high tide", "the virgil", "townhouse",
        "venice west", "sid the cat", "the lexington", "the dresden", "the baked potato",
        "in sheep's clothing", "bar franca", "only the wild ones", "slipper clutch",
        "the airliner")},
}

# Last-resort TYPE signal: rooms that only ever host live music, consulted ONLY when the
# category says nothing at all (Undefined / general / empty) — theaters that also host comedy
# arrive as "Arts & Theatre" and must never leak in. Profile-extensible (`tagging.venue_type_live`).
VENUE_TYPE_LIVE = ("troubadour", "fonda", "pappy", "el rey", "pacific amphitheatre",
                   "alva's showroom", "zebulon", "the smell", "2220 arts", "gold diggers",
                   "moroccan lounge", "teragram", "the echo", "masonic lodge", "lodge room",
                   "venice west", "harvelle", "maui sugar mill", "sid the cat")
# …and the Broadway-house equivalent: rooms that only ever host stage productions (a jsonld
# Pantages row arrives as category "Event" — The Who's Tommy typed `other` without this).
VENUE_TYPE_STAGE = ("pantages", "ahmanson", "mark taper", "dorothy chandler", "segerstrom")

# Bare-name EDM headliners TM files under Music/Dance-Electronic with no club signal in the
# text — a Marshmello fairgrounds date is a dance event, not a band show. Recurring names
# only; the residue is the event-editor lane override's job. Profile-extensible
# (`tagging.edm_headliners`).
EDM_HEADLINERS = ("marshmello", "zeds dead", "steve aoki", "kaskade", "illenium",
                  "tiesto", "tiësto", "david guetta", "martin garrix", "alesso",
                  "dj snake", "deadmau5", "skrillex", "excision", "subtronics",
                  "afrojack", "dillon francis", "slander", "seven lions")

# ── Axis 5: REGION — coarse buckets over the messy neighborhood field ─────────────
REGIONS = {
    "eastside": {"silver lake", "silverlake", "echo park", "los feliz", "east hollywood",
        "atwater village", "atwater", "frogtown", "elysian valley", "elysian park",
        "highland park", "eagle rock", "glassell park", "cypress park", "lincoln heights",
        "virgil village", "historic filipinotown", "mount washington", "boyle heights",
        "thai town"},
    "dtla": {"dtla", "downtown", "downtown la", "arts district", "chinatown",
        "little tokyo", "westlake", "university park", "exposition park", "pico-union"},
    "hollywood": {"hollywood", "west hollywood", "weho",
        "fairfax", "beverly grove",   # central cluster folded in (New Beverly, Brain Dead)
        "koreatown", "mid-city", "mid-wilshire", "miracle mile", "hancock park",
        "larchmont"},                 # …plus the K-town/Mid-City central belt
    "westside": {"venice", "santa monica", "culver city", "mar vista", "west la",
        "westwood", "bel air", "brentwood", "marina del rey", "sawtelle", "playa vista",
        "westchester", "beverly hills", "malibu"},
    "valley": {"glendale", "burbank", "north hollywood", "noho", "studio city",
        "sherman oaks", "van nuys", "tarzana", "pasadena", "south pasadena", "encino",
        "san fernando", "alhambra", "temple city", "arcadia"},
    "south-bay": {"long beach", "san pedro", "torrance", "redondo beach", "inglewood"},
    "far": {"anaheim", "santa ana", "irvine", "san diego", "temecula", "ventura",
        "riverside", "costa mesa", "huntington beach", "oxnard", "yucaipa",
        "thousand oaks", "palm desert", "ojai", "pioneertown", "brea", "rowland heights",
        "laguna beach", "palm springs", "rancho mirage", "cabazon", "coachella", "indio",
        "cerritos", "la mirada", "garden grove", "fullerton", "san juan capistrano",
        "mission viejo", "dana point", "san bernardino", "highland", "rancho cucamonga",
        "ontario", "fontana", "corona", "pomona", "commerce", "pico rivera",
        "santa barbara", "paso robles", "san luis obispo", "palmdale", "bakersfield"},
}

# The full controlled vocabulary, exported so build_dashboard can publish facets and
# the scene-researcher can be pointed at the same lists (one source of truth).
VOCAB = {
    "type": list(TYPES),
    "genre": [t for t, _ in GENRE_ELECTRONIC] + [t for t, _ in GENRE_LIVE]
             + [t for t, _ in GENRE_STAGE] + [t for t, _ in GENRE_COMEDY]
             + ["rep/arthouse", "electronic", "world", "theater", "family", "dance",
                "performance-art", "magic", "circus", "variety", "puppetry"],
    "setting": ["rooftop", "warehouse", "outdoor", "listening-bar", "club", "bar",
                "theater", "amphitheater", "cinema", "speakeasy", "diy", "pool", "gallery"],
    "scale": ["bar", "room", "hall", "arena"],
    "vibe": ["afterhours", "day-party", "sunset", "all-vinyl", "all-night-set", "b2b",
             "residency", "queer", "drag", "burlesque", "tribute", "album-release",
             "festival", "analog-film", "q&a", "guest-in-person", "matinee",
             "block-party", "pop-up", "boat-party", "tba-location", "ra-pick", "free",
             "free-rsvp", "sold-out", "21+", "18+", "all-ages"],
    "region": list(REGIONS.keys()),
}

_CINEMA_KW = re.compile(r"\b(screening|matin[eé]e|double feature|q&a|q & a|35mm|70mm|16mm|"
                        r"film series|cinema)\b", re.I)
_COMEDY_KW = re.compile(r"\b(comedy|stand[\s-]?up|standup|improv|open mic)\b", re.I)
_MARKET_KW = re.compile(r"\b(market|flea|bazaar|farmers|swap meet|vintage fair)\b", re.I)
_WORKSHOP_KW = re.compile(r"\b(workshop|class|seminar)\b", re.I)
# NB: `afters` must stay PLURAL-only — `afters?` matched the plain word "after" in any
# detail blob ("After witnessing his father…" typed The Who's Tommy as club).
_DJ_KW = re.compile(r"\b(dj set|b2b|warehouse|rave|afters|after[\s-]?part(?:y|ies)|day party)\b",
                    re.I)
# Sports watch parties (title-only): a World Cup final at a warehouse is still not a rave.
# The pattern recurs every Super Bowl/Dodgers run, scattering rows across the music lanes.
_WATCH_KW = re.compile(r"\bwatch part(y|ies)\b|\bworld cup\b|\bfifa\b|\bfan zone\b|"
                       r"\bsemi-?finals?\b|\bquarter-?finals?\b", re.I)
# Title-level club signals — used by the live-room guard: an RA/19hz listing at a rock dive
# is a band bill UNLESS the title itself says club night.
_CLUB_TITLE_KW = re.compile(r"^\s*dj\b|\bdj (set|night)\b|\b(with|w/)\s+dj\b|"
                            r"\b(dance|disco|house) party\b|\brave\b|\bb2b\b|\bwarehouse\b|"
                            r"\bafters\b|\bday party\b|\bdisko\b|\bafrobeats\b|\bamapiano\b", re.I)
# Any electronic-genre keyword (the GENRE_ELECTRONIC patterns, \b-bounded) — the other half
# of the live-room guard.
_ELECTRONIC_KW = re.compile(r"\b(" + "|".join(p for _, p in GENRE_ELECTRONIC) + r")\b", re.I)
# 19hz leaves its genre annotation in the venue string ("The Lexington (Los Angeles) tech
# house, minimal") — extract it so genre scanning can use it WITHOUT scanning venue names
# (which mint false genres: "House of Blues" was 65% of all blues tags).
_19HZ_VENUE_NOTE = re.compile(r"\([^)]*\)\s+([a-z0-9 ,&/+'-]+)$")


def _hay(ev: dict) -> str:
    """Lowercased search text: title + organizers + detail + venue + lineup."""
    parts = [ev.get("title") or "", ev.get("organizers") or "",
             ev.get("detail") or "", ev.get("venue") or ""]
    parts += [str(a) for a in (ev.get("lineup") or [])]
    return " ".join(parts).lower()


def _venue_genre_note(ev: dict) -> str:
    """The 19hz genre annotation embedded in the venue string, if any ('' otherwise)."""
    if "19hz" not in (ev.get("sources") or []):
        return ""
    m = _19HZ_VENUE_NOTE.search(str(ev.get("venue") or "").lower())
    return m.group(1) if m else ""


def _genre_hay(ev: dict) -> str:
    """Genre-scan text: like _hay but WITHOUT the venue name (venue names mint false
    genres — 'House of Blues', 'Jungle Hollywood'), keeping only 19hz's embedded genre
    annotation. Venue-derived genre lives exclusively in the VENUE_GENRE gazetteer."""
    parts = [ev.get("title") or "", ev.get("organizers") or "",
             ev.get("detail") or "", _venue_genre_note(ev)]
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
    venue_scale = {**VENUE_SCALE, **{k.lower(): v for k, v in (tg.get("venue_scale") or {}).items()}}
    regions = {k: set(v) for k, v in REGIONS.items()}
    for k, v in (tg.get("regions") or {}).items():
        regions.setdefault(k, set()).update(x.lower() for x in v)
    near = {n.lower() for n in ((profile.get("scoring") or {}).get("near_home_neighborhoods") or [])}
    venue_type_live = tuple(VENUE_TYPE_LIVE) + tuple(
        v.lower() for v in (tg.get("venue_type_live") or []))
    edm = tuple(EDM_HEADLINERS) + tuple(v.lower() for v in (tg.get("edm_headliners") or []))
    return {"venue_genre": venue_genre, "venue_setting": venue_setting,
            "venue_scale": venue_scale, "regions": regions, "near_home": near,
            "venue_type_live": venue_type_live, "edm_headliners": edm}


def _live_rooms(cfg: dict):
    """Venues whose default booking is live bands (for the club-source guard):
    the last-resort live rooms plus every venue the genre gazetteer knows."""
    cfg = cfg or {}
    return tuple(cfg.get("venue_type_live") or VENUE_TYPE_LIVE) + tuple(
        (cfg.get("venue_genre") or VENUE_GENRE).keys())


def _resolve_type(ev: dict, hay: str, cfg: dict = None) -> str:
    """The one MECE kind. Keyword guards override a mislabeled source category
    (e.g. an Acropolis Cinema 'screening' that Ticketmaster tagged `music`).

    Category matching is case-NORMALIZED: Ticketmaster's Discovery segments arrive capitalized
    ("Music", "Arts & Theatre", "Film") and used to miss every branch — ~65% of the catalog fell
    to `other` on that alone. TM's separate `genre` field disambiguates "Arts & Theatre" (comedy
    vs stage); its "Music" rows stay live-music (even genre Dance/Electronic is ~half live acts —
    club still needs a real club signal, which the club branch below already checks first)."""
    cat = str(ev.get("category") or "").strip().lower()
    tm_genre = str(ev.get("genre") or "").strip().lower()
    # attraction-level TM genre (fetch_ticketmaster `lineup_genre`) — where TM actually says
    # "Comedy" for the bare-name comedians whose EVENT classification is a useless
    # "Arts & Theatre"/Miscellaneous (Trevor Noah, Dane Cook… — 60% of the old `other` bucket).
    lu_genre = str(ev.get("lineup_genre") or "").strip().lower()
    srcs = set(ev.get("sources") or [])
    title_l = str(ev.get("title") or "").lower()
    venue_l = str(ev.get("venue") or "").lower()
    # An explicit music category narrows the keyword guards to TITLE+VENUE: a stray mention in
    # the DETAIL blob must not retype a concert (Bad Brains' detail mentions a "partial film
    # screening" between sets; club-night blurbs mention alley night markets). Everything else
    # keeps the broad full-text guard — that's what rescues a mislabeled screening.
    kw_hay = (" ".join([title_l, venue_l]) if cat in MUSIC_CATS else hay)
    if _WATCH_KW.search(title_l):
        return "community"
    if cat == "film" or _CINEMA_KW.search(kw_hay):
        return "film"
    # A&T rows WITH an authoritative TM stage genre: the genre outranks blurb keywords —
    # Oklahoma!'s detail calls it "a comedy" but it is Theatre. A TITLE-level comedy signal
    # still wins (JVN's "Comedy Tour" is filed under Theatre).
    if cat == "arts & theatre" and tm_genre in TM_STAGE_GENRES:
        return "comedy" if _COMEDY_KW.search(title_l) else "stage"
    if (cat == "comedy" or tm_genre == "comedy" or lu_genre == "comedy"
            or _COMEDY_KW.search(kw_hay)):
        return "comedy"
    if cat in ("theater", "dance"):
        return "stage"
    if cat == "arts & theatre":
        if lu_genre in TM_STAGE_GENRES:
            return "stage"
        # Two title-only micro-rules (TITLE, not the full blob — a detail merely mentioning
        # the fair must not retype a genre-less A&T event).
        if "pageant of the masters" in title_l:
            return "art"
        if "oc fair" in title_l:
            return "community"
        if _STAGE_KW.search(hay) or _STAGE_TITLE_KW.search(title_l):
            return "stage"
        if _LIVE_TITLE_KW.search(title_l):
            return "live-music"              # regional-Mexican bookings / festival runs
        return "other"                       # bare-name comedians hide here — honest null
    # Music-category rows never keyword-match into market/workshop: a real flea market does
    # not arrive as category 'party' ("TECHNO NIGHT MARKET" is a club night, not a market).
    if cat not in MUSIC_CATS and _MARKET_KW.search(kw_hay):
        return "market"
    if cat not in MUSIC_CATS and _WORKSHOP_KW.search(kw_hay):
        return "workshop"
    if cat in ("electronic", "party") or (srcs & {"ra", "19hz", "posh"}) or _DJ_KW.search(kw_hay):
        # Live-room guard: RA/19hz list every event at rock dives (The Redwood: 40 band bills
        # typed club before this), and the source short-circuit made them all "club". A known
        # live room stays live-music unless the TITLE carries a club signal or any electronic
        # genre keyword appears (incl. 19hz's embedded genre annotation).
        if (any(v in venue_l for v in _live_rooms(cfg))
                and not _CLUB_TITLE_KW.search(title_l)
                and not _ELECTRONIC_KW.search(_genre_hay(ev))):
            return "live-music"
        return "club"
    if cat in ("music", "live_music", "jazz"):
        # TM Music/Dance-Electronic bare-name DJ headliners are dance events, not band shows —
        # the recurring names via a gazetteer; a party-styled title is the generic signal.
        if tm_genre == "dance/electronic":
            names = " ".join([title_l] + [str(a).lower() for a in (ev.get("lineup") or [])])
            edm = (cfg or {}).get("edm_headliners") or EDM_HEADLINERS
            if any(n in names for n in edm):
                return "club"
            if re.search(r"\brave\b|\b(dance|disco) party\b|\bdisko\b", title_l):
                return "club"
        return "live-music"
    if cat in ("", "undefined", "general", "miscellaneous", "event"):
        rooms = (cfg or {}).get("venue_type_live") or VENUE_TYPE_LIVE
        if any(v in venue_l for v in rooms):
            return "live-music"
        if any(v in venue_l for v in VENUE_TYPE_STAGE):
            return "stage"                   # a jsonld Pantages row arrives as category "Event"
        if _STAGE_KW.search(title_l) or _STAGE_TITLE_KW.search(title_l):
            return "stage"                   # The Nutcracker arrives as category Miscellaneous
        if _LIVE_TITLE_KW.search(title_l):
            return "live-music"
    return {"art": "art"}.get(cat, "other")


def _genre(ev: dict, typ: str, hay: str, cfg: dict) -> list:
    out = []
    venue = (ev.get("venue") or "").lower()
    ghay = _genre_hay(ev)
    if typ == "club":
        for tag, pat in GENRE_ELECTRONIC:
            if re.search(r"\b(" + pat + r")\b", ghay):
                out.append(tag)
        # specific beats the general word it contains ("tech house" -> tech-house, not +house)
        shadowed = {_GENRE_SHADOWS[t] for t in out if t in _GENRE_SHADOWS}
        out = [t for t in out if t not in shadowed]
        if not out:
            out.append("electronic")          # source-implied, subgenre unknown -> enrichment refines
    elif typ == "live-music":
        for tag, pat in GENRE_LIVE:
            if re.search(r"\b(" + pat + r")\b", ghay):
                out.append(tag)
        tm = TM_GENRE_LIVE.get(str(ev.get("genre") or "").strip().lower())
        if tm:
            out.append(tm)                     # TM's own genre call, after any keyword hits
        if not out:                            # bare artist-name title -> fall back to the venue gazetteer
            for vk, gs in cfg["venue_genre"].items():
                if vk in venue:
                    out.extend(gs)
    elif typ == "stage":
        tm = TM_GENRE_STAGE.get(str(ev.get("genre") or "").strip().lower())
        if tm:
            out.append(tm)
        title_l = str(ev.get("title") or "").lower()
        for tag, pat in GENRE_STAGE:
            if re.search(pat, title_l):
                out.append(tag)
    elif typ == "comedy":
        for tag, pat in GENRE_COMEDY:
            if re.search(pat, hay):
                out.append(tag)
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


def _scale(ev: dict, setting: list, cfg: dict):
    """The venue tier — explicit gazetteer, else amphitheater-setting => arena, else None."""
    venue = (ev.get("venue") or "").lower()
    for vk, tier in cfg["venue_scale"].items():
        if vk in venue:
            return tier
    if "amphitheater" in (setting or []):
        return "arena"
    return None


def _vibe(ev: dict, typ: str, hay: str) -> list:
    out = []
    hour = _hour(ev)
    price = str(ev.get("price") or "").lower()
    title_l = str(ev.get("title") or "").lower()
    if ev.get("afterhours") or (hour is not None and (hour >= 22 or hour < 5)):
        out.append("afterhours")
    if typ == "club" and hour is not None and 11 <= hour <= 16:
        out.append("day-party")
    if re.search(r"\b(sunset|golden hour)\b", hay):
        out.append("sunset")
    if re.search(r"\b(all[\s-]?vinyl|vinyl[\s-]?only)\b", hay):
        out.append("all-vinyl")
    # single-DJ marathon sets — a NAMED taste boost ("open-to-close") that was machine-
    # invisible before; nostalgia parties ("2010s bangers All Night Long!") excluded.
    if (typ == "club"
            and re.search(r"open[\s-]?to[\s-]?close|all[\s-]?night\s?(long|set)|\[all night|"
                          r"extended set", hay)
            and not re.search(r"(19|20)\d0s|(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}|"
                              r"\bbangers\b|\bclassics\b|throwback", title_l)):
        out.append("all-night-set")
    if re.search(r"\bb2b\b", hay):
        out.append("b2b")
    if re.search(r"\b(residency|residencies)\b|\bresident\b(?!\s+advisor)", hay):
        out.append("residency")
    if re.search(r"\b(queer|lgbtq|pride|gay|sapphic)\b", hay):
        out.append("queer")
    if re.search(r"\bdrag\b", hay):
        out.append("drag")
    if re.search(r"\bburlesque\b", hay):
        out.append("burlesque")
    if re.search(r"\b(tributes?|cover band)\b", hay):
        out.append("tribute")
    if re.search(r"\b(album|record|ep) release\b", hay):
        out.append("album-release")
    # TITLE/organizer only: 75% of the old full-hay matches were venue-name noise
    # ("Festival of Arts" minted 52 Pageant-of-the-Masters festival vibes) or bio prose.
    if re.search(r"\bfestival\b", title_l + " " + str(ev.get("organizers") or "").lower()):
        out.append("festival")
    if re.search(r"\b(35mm|70mm|16mm)\b", hay):
        out.append("analog-film")
    # q&a gated to the screen/stage lanes: 7 of 11 old hits were live-music VIP-package
    # upsell text ("Q&A with" in a meet-and-greet tier), not the film-guest signal.
    if typ in ("film", "comedy", "stage") and re.search(r"\bq&a|q & a\b", hay):
        out.append("q&a")
    if typ == "film" and re.search(r"\bin person\b|\bin attendance\b|\bin conversation\b|"
                                   r"\bintroduced by\b|q ?& ?a with", hay):
        out.append("guest-in-person")
    if typ == "film" and hour is not None and 9 <= hour < 17:
        out.append("matinee")
    if re.search(r"\bblock party\b", hay):
        out.append("block-party")
    if re.search(r"\bpop[\s-]?up\b", hay):
        out.append("pop-up")
    if re.search(r"\bboat party\b|\byacht party\b|catalina classic cruises", hay):
        out.append("boat-party")
    venue = (ev.get("venue") or "").lower()
    if "tba" in venue or re.search(r"\b(location )?tba\b|drops? (after|day)", hay):
        out.append("tba-location")
    if ev.get("ra_pick"):
        out.append("ra-pick")
    if "free" in price:
        out.append("free")
        if "rsvp" in price:
            out.append("free-rsvp")           # the afterhours-scene entry pattern
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
    """Derive the six-axis `tags` block for one catalog record. Pure; deterministic."""
    cfg = _cfg(profile)
    hay = _hay(ev)
    typ = _resolve_type(ev, hay, cfg)
    setting = _setting(ev, hay, cfg)
    region, near_home = _region(ev, cfg)
    return {
        "type": typ,
        "genre": _genre(ev, typ, hay, cfg),
        "setting": setting,
        "scale": _scale(ev, setting, cfg),
        "vibe": _vibe(ev, typ, hay),
        "region": region,
        "near_home": near_home,
    }


def tag_catalog(catalog: list, profile: dict = None) -> list:
    """Stamp `tags` onto every record in place (idempotent — recomputed each run)."""
    for ev in catalog:
        ev["tags"] = tag_event(ev, profile)
    return catalog
