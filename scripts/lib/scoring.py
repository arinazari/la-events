"""Taste-ranking heuristic — the ONE place scoring lives.

Was inline in build_dashboard.py; extracted so build_dashboard.py, the future
run_digest.py orchestrator, and the digest all score identically (no drift).

score_event(ev, taste, profile) -> {"score": int, "reasons": [str]}
score_to_rating(score, profile) -> int  (1..5)

`taste` = taste.yaml content (artists_tracked, venues_loved, comedians_loved,
venues_banned). `profile` = profile.yaml mechanism (category weights, term
matchers, geo, rating thresholds).

The mechanism config (the `scoring:` block) may live in EITHER file, resolved
per key: profile.yaml's `scoring` first, else taste.yaml's `scoring`, else the
DEFAULT_* below (transcribed verbatim from the pre-refactor build_dashboard.py,
so scoring is behavior-preserving with neither file). This means a profile with
no profile.yaml is scored from its OWN taste.yaml — per-person tuning without a
separate mechanism file.
"""

import re
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
    _LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - zoneinfo always present on py3.9+
    _LA = None

from .affinity import artist_affinity, genre_affinity, tracked_hits, ambiguous_set

# ── Defaults (verbatim from pre-refactor build_dashboard.py) ─────────────────
DEFAULT_CATEGORY_WEIGHTS = {
    "electronic": 3,
    "party": 3,
    "film": 3,
    "music": 2,
    "live_music": 2,
    "theater": 2,
    "beer_food": 2,
    "comedy": 1,
    "art": 1,
    "pop": 1,
    "general": 1,
}

DEFAULT_NEAR_HOME = (
    "silver lake", "silverlake", "echo park", "los feliz", "east hollywood",
    "atwater village", "atwater", "frogtown", "elysian valley", "highland park",
    "eagle rock", "glassell park", "cypress park", "lincoln heights", "chinatown",
    "virgil village", "westlake", "historic filipinotown", "downtown", "dtla",
    "arts district",
)

DEFAULT_GROOVE_TERMS = (
    "vinyl", "all night", "open to close", "open-to-close", "groove", "disco",
    "soulful", "deep house", "balearic", "rooftop", "sunset", "golden hour",
    "open-air", "open air", "daytime", "day party", "poolside", "pool party",
)
# Person/city-specific groove terms (e.g. "beach") live in profile.yaml, not here — it replaces
# this generic baseline when present (see test_profile_preserves_code_defaults).

DEFAULT_EU_TERMS = (
    "fabric", "defected", "innervisions", "keinemusik", "hot creations", "rush hour",
    "running back", "anjuna", "afterlife", "dirtybird", "hot since", "solid grooves",
)

DEFAULT_PENALTY_TERMS = (
    "bottle service", "bottle-service", "vip table", "table service",
    "top 40", "top-40", "open format", "open-format", "hip hop", "hip-hop",
    "hardstyle", "gabber", "dubstep", "riddim", "brostep", "tribute", "cover band",
    "watch party", "world cup", "fifa", "sports bar", "trivia", "bingo", "open mic",
    "karaoke", "networking", "webinar", "workshop", "virtual", "zoom",
    "mega-rave", "mega rave", "edm festival",
)

DEFAULT_FAR_TERMS = (
    "anaheim", "santa ana", "irvine", "san diego", "temecula", "ventura",
    "riverside", "long beach", "costa mesa", "huntington beach",
)

# [min_score, rating], checked high-to-low; below all -> 1.
DEFAULT_RATING_THRESHOLDS = ((8, 5), (6, 4), (4, 3), (2, 2))


def _scoring_cfg(profile: dict, taste: dict = None) -> dict:
    """Resolve the scoring config per key: profile.yaml's `scoring` block first, then
    taste.yaml's `scoring` block (so a profile with no profile.yaml is scored from its own
    taste.yaml), then the DEFAULT_*."""
    sc = (profile or {}).get("scoring") or {}
    tc = (taste or {}).get("scoring") or {}

    def pick(key, default):
        v = sc.get(key)
        if v is None:
            v = tc.get(key)
        return default if v is None else v

    return {
        "category_weights": pick("category_weights", DEFAULT_CATEGORY_WEIGHTS),
        "near_home": {h.lower() for h in pick("near_home_neighborhoods", DEFAULT_NEAR_HOME)},
        "groove": tuple(pick("groove_terms", DEFAULT_GROOVE_TERMS)),
        "eu": tuple(pick("eu_terms", DEFAULT_EU_TERMS)),
        "penalty": tuple(pick("penalty_terms", DEFAULT_PENALTY_TERMS)),
        "far": tuple(pick("far_terms", DEFAULT_FAR_TERMS)),
        "rating_thresholds": [tuple(t) for t in pick("rating_thresholds", DEFAULT_RATING_THRESHOLDS)],
        "card_cap": pick("card_cap", 4),   # max points from the shared event card (0 disables)
    }


def parse_event_date(ev: dict):
    """Best-effort ISO date (datetime.date) for an event record.

    A timezone-aware datetime (e.g. Ticketmaster's UTC `dateTime`, ending "Z") is converted to
    America/Los_Angeles BEFORE the calendar date is taken: an evening LA show is already past
    midnight in UTC, so slicing the UTC date lands it a day late. Naive datetimes (DICE/RA emit
    local wall-clock with no offset) are treated as already-local and left untouched.
    """
    raw = ev.get("date") or ev.get("datetime") or ""
    if not raw:
        return None
    raw = str(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None and _LA is not None:
            dt = dt.astimezone(_LA)
        return dt.date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def score_event(ev: dict, taste: dict = None, profile: dict = None,
                affinity: dict = None, card: dict = None) -> dict:
    """Return {score, reasons[]} for an event. Mirrors the digest's ranking.

    `affinity` (optional) = the merged Spotify + feedback music layer (Phase C). When
    absent, scoring is byte-identical to the taste.yaml/profile.yaml-only path — the
    music layer only ever ENRICHES; it never replaces the human spine in taste.yaml.

    `card` (optional) = the shared enrichment's taste-neutral event card
    (enrich.CARD_FIELDS: draw/rarity/lineup_depth), scored as ONE bounded additive
    term (card_cap). Absent card -> byte-identical scores, same as affinity.
    """
    taste = taste or {}
    cfg = _scoring_cfg(profile, taste)
    reasons = []
    score = 0

    cat = (ev.get("category") or "general").lower()
    title = ev.get("title") or ""
    venue = (ev.get("venue") or "")
    vlow = venue.lower()
    hood = (ev.get("neighborhood") or "").lower().strip()
    lineup = ev.get("lineup") or []
    if not isinstance(lineup, list):
        lineup = [str(lineup)]
    hay = " ".join([title, venue, ev.get("detail") or "", str(lineup),
                    str(ev.get("organizers") or "")]).lower()

    tracked = [a for a in (taste.get("artists_tracked") or []) if a]
    loved = [v.lower() for v in (taste.get("venues_loved") or [])]
    comics = [c.lower() for c in (taste.get("comedians_loved") or [])]

    # Base category weight (comedy is special — suppressed unless a loved name).
    base = cfg["category_weights"].get(cat, 1)
    score += base
    if cat == "comedy":
        reasons.append("+1 comedy (low interest)")
        if any(c in hay for c in comics):
            score += 4
            reasons.append("+4 favorite comedian")
        else:
            score -= 2
            reasons.append("-2 comedy not generally wanted")
    else:
        lab = {3: "high", 2: "medium", 1: "low"}.get(base, "low")
        reasons.append(f"+{base} {cat.replace('_', ' ')} ({lab} interest)")

    # Tracked artist (+2 each; also the "tracked" badge) — matched where artists are BILLED
    # (title + lineup), not the venue/detail/promoter blob (Track B3: a bio mentioning a name
    # isn't a booking). Whole-token match so "Ame" doesn't fire inside "Amelie Lens"; names on
    # the ambiguous list (FISHER, Drama — words as well as artists) must equal a lineup entry,
    # since token presence can't tell FISHER from the unrelated duo "Fisher and Thames".
    hits = sorted(tracked_hits(tracked, title, lineup, ambiguous=ambiguous_set(profile, taste)))
    if hits:
        score += 2 * len(hits)
        reasons.append(f"+{2 * len(hits)} tracked artist ({', '.join(hits)})")

    # Loved venue (substring match — "2220 Arts" ~ "2220 Arts + Archives").
    if any(l in vlow for l in loved):
        score += 1
        reasons.append("+1 venue you love")

    # Film taste (taste.yaml `film:` block) — the MOVIE, not just the room (venues_loved already
    # covers the theater). Directors work like tracked artists (+2 each, matched wherever the
    # listing carries them); loved formats (+1 each) reward the print-and-projector draw ("70mm"
    # in the title beats a stream). Gated to film-typed events so a director's name in a club
    # bio or a "35mm slides" art talk can't fire. The same block rides in the event-editor's
    # taste brief, so the LLM layer can also weigh what it KNOWS about a film (director, rep-canon
    # status) beyond what the listing text says.
    film_cfg = taste.get("film") or {}
    if film_cfg and (cat == "film" or ((ev.get("tags") or {}).get("type")) == "film"):
        d_hits = [str(d) for d in (film_cfg.get("directors_tracked") or [])
                  if d and re.search(r"\b" + re.escape(str(d).lower()) + r"\b", hay)]
        if d_hits:
            score += 2 * len(d_hits)
            reasons.append(f"+{2 * len(d_hits)} tracked director ({', '.join(d_hits)})")
        f_hits = [str(f) for f in (film_cfg.get("formats_loved") or [])
                  if f and re.search(r"\b" + re.escape(str(f).lower()) + r"\b", hay)]
        if f_hits:
            score += len(f_hits)
            reasons.append(f"+{len(f_hits)} loved film format ({', '.join(f_hits)})")

    # Afterhours / warehouse / late start (catalog field is `afterhours`).
    if ev.get("afterhours") or ev.get("afterhours_flag"):
        score += 1
        reasons.append("+1 afterhours / late start")

    if ev.get("ra_pick"):
        score += 1
        reasons.append("+1 RA pick")

    # Rooftop / vinyl / groove setting, and European-label vibe.
    if any(g in hay for g in cfg["groove"]):
        score += 1
        reasons.append("+1 rooftop / vinyl / groove")
    if any(e in hay for e in cfg["eu"]):
        score += 1
        reasons.append("+1 European / label vibe")

    # Friday / Saturday night.
    d = parse_event_date(ev)
    if d and d.weekday() in (4, 5):
        score += 1
        reasons.append("+1 Friday/Saturday night")

    # Near home.
    if hood in cfg["near_home"]:
        score += 1
        reasons.append("+1 close to Silver Lake")

    # Editorial mentions (+1 each).
    mentions = ev.get("editorial_mentions") or []
    if mentions:
        score += len(mentions)
        reasons.append(f"+{len(mentions)} editorial mention ({', '.join(mentions)})")

    # Spotify + feedback music layer (Phase C) — graded artist/genre affinity, capped so
    # it nudges rather than dominates. Enriches the taste.yaml signals above; no-op if absent.
    if affinity:
        lineup_text = " ".join(str(a) for a in lineup).lower()
        name_text = title.lower() + " " + lineup_text          # where artists are actually billed
        a_pts, a_reasons = artist_affinity(name_text, lineup_text, affinity, profile)
        g_pts, g_reasons = genre_affinity(hay, affinity, profile)
        score += a_pts + g_pts
        reasons.extend(a_reasons + g_reasons)

    # Banned venue (hard down-rank).
    banned = [v.lower() for v in (taste.get("venues_banned") or []) if v]
    if any(b in vlow for b in banned):
        score -= 5
        reasons.append("-5 venue you've banned")

    # Penalties (each distinct term once).
    for term in cfg["penalty"]:
        if term in hay:
            score -= 2
            reasons.append(f"-2 {term}")
    # Far-flung penalty — WAIVED for festival-scale events. A marquee festival in the OC/SD/
    # Ventura orbit (Coachella, CRSSD, Daisy Chain Fields) is a worth-the-trip radar item, not a
    # far-flung club night, so it's judged on taste rather than auto-killed by geography. An
    # off-taste far festival still scores low on its own merits (no tracked artists / low category),
    # so waiving the geo penalty doesn't wrongly surface junk. Festival detection mirrors
    # build_radar's festival signal + tagging's "festival" vibe (whole word in the haystack, or an
    # explicit `festival: true` on a manual/curated capture).
    is_festival = bool(ev.get("festival")) or ("festival" in hay)
    if any(f in hay or f in hood for f in cfg["far"]):
        if is_festival:
            reasons.append("far-flung penalty waived (festival)")
        else:
            score -= 2
            reasons.append("-2 far from LA")

    # Shared event card (taste-neutral facts from enrichment): draw + rarity + a stacked
    # bill, as one capped term so the card refines the taste ranking, never drives it.
    if card and cfg["card_cap"] > 0:
        parts, cp = [], 0
        d = int(card.get("draw") or 0)
        if d > 0:
            cp += d
            parts.append(f"+{d} draw")
        r = int(card.get("rarity") or 0)
        if r > 0:
            cp += r
            parts.append(f"+{r} rare booking")
        if int(card.get("lineup_depth") or 0) >= 2:
            cp += 1
            parts.append("+1 stacked bill")
        cp = min(cp, cfg["card_cap"])
        if cp > 0:
            score += cp
            reasons.append(f"+{cp} event card ({', '.join(parts)})")

    return {"score": score, "reasons": reasons}


def score_to_rating(score: int, profile: dict = None, taste: dict = None) -> int:
    """Map a raw score to a 1-5 star 'recommended for you' rating."""
    thresholds = _scoring_cfg(profile, taste)["rating_thresholds"]
    for min_score, rating in sorted(thresholds, key=lambda t: -t[0]):
        if score >= min_score:
            return rating
    return 1
