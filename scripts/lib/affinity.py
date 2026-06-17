"""Spotify-derived taste affinity — the *music* layer of the scoring profile.

Phase C. Spotify is the music affinity layer; it ENRICHES the durable human layer
(taste.yaml) and the feedback layer, and never overwrites them. This module is pure
(no network): `fetch_spotify.py` does the I/O and hands the raw payloads here.

Two halves:
  build_affinity(...)  -> the affinity artifact (artists{} + genres{}), written to
                          data/spotify_affinity.json by the sync, consumed by the scorer.
  artist_affinity(...) / genre_affinity(...) -> the scoring-facing readers the scorer calls
                          to turn that artifact into points + reasons.

Affinity artifact schema (data/spotify_affinity.json):
  {
    "generated_at": "2026-06-17T12:00:00",
    "source": "spotify",                       # or "spotify+feedback" after the feedback fold
    "artists": {                               # keyed by normalized (lowercased) name
      "antal": {"name": "Antal", "weight": 3.4, "tier": "core",
                "sources": ["top_long", "followed"]},
      ...
    },
    "genres": {"deep house": 1.0, "disco": 0.72, ...}   # 0..1, max-normalized
  }
"""

from datetime import datetime

# ── Sync-side weighting (how raw Spotify signals become a per-artist weight) ──────────
# How much each signal contributes. long_term = durable core taste; followed = explicit;
# recently-played = current rotation. These stack (an artist in several is your absolute core).
SOURCE_WEIGHTS = {
    "top_long": 3.0,      # /me/top/artists?time_range=long_term  (~years)
    "top_medium": 2.0,    # medium_term (~6 months)
    "top_short": 1.5,     # short_term  (~4 weeks)
    "followed": 2.0,      # /me/following?type=artist  (explicit follow)
    "recent": 1.0,        # /me/player/recently-played (per-play, capped)
}
WEIGHT_CAP = 6.0          # cap the summed per-artist weight so nothing runs away
RECENT_PLAY_CAP = 3       # at most this many plays of one artist count toward "recent"

# weight -> tier. Checked high-to-low; below `light` the artist is dropped from the artifact.
TIER_THRESHOLDS = (("core", 3.0), ("strong", 1.8), ("light", 0.8))

# ── Scoring-side defaults (how the artifact becomes points). Overridable via
# profile.yaml `scoring.spotify` so the mechanism isn't hardcoded (Phase A ethos). ──
DEFAULT_SCORING = {
    "tier_points": {"core": 2, "strong": 1, "light": 1, "hidden": -3},
    "artist_cap": 4,        # max total artist-affinity points per event
    "genre_points": 1,      # points when a high-affinity genre appears
    "genre_threshold": 0.5,  # min normalized genre affinity to count
    "genre_cap": 1,         # max genre points per event
    "min_name_len": 3,      # skip ultra-short names (avoid false substring matches)
}


def normalize_name(name: str) -> str:
    """Match key for an artist name: lowercased, whitespace-collapsed."""
    return " ".join((name or "").split()).lower()


def _tier_for(weight: float) -> str:
    for tier, threshold in TIER_THRESHOLDS:
        if weight >= threshold:
            return tier
    return ""


def _rank_decay(rank: int, n: int) -> float:
    """Top of a list counts most; tail tapers to ~0.4. rank is 0-based."""
    if n <= 1:
        return 1.0
    return max(0.4, 1.0 - (rank / n) * 0.6)


def build_affinity(top_artists: dict = None, followed: list = None,
                   recent_tracks: list = None, *, now: str = None) -> dict:
    """Fold raw Spotify payloads into the affinity artifact.

    top_artists: {"long_term": [artist...], "medium_term": [...], "short_term": [...]}
                 each artist = {"name", "genres": [...], ...} (Spotify /me/top/artists item)
    followed:    [artist...]  (Spotify /me/following items — carry genres)
    recent_tracks: [{"track": {"artists": [{"name"}...]}}...]  (no genres on these)

    Returns the artifact dict (artists keyed by normalized name; genres max-normalized 0..1).
    """
    top_artists = top_artists or {}
    followed = followed or []
    recent_tracks = recent_tracks or []

    # weight[name] = summed signal; meta[name] = {display, genres, sources{}}
    weight: dict = {}
    meta: dict = {}

    def bump(name, w, source, genres=None):
        key = normalize_name(name)
        if not key:
            return
        weight[key] = weight.get(key, 0.0) + w
        m = meta.setdefault(key, {"name": name.strip(), "genres": set(), "sources": set()})
        m["sources"].add(source)
        for g in (genres or []):
            m["genres"].add(g.lower())

    range_source = {"long_term": "top_long", "medium_term": "top_medium", "short_term": "top_short"}
    for time_range, source in range_source.items():
        artists = top_artists.get(time_range) or []
        n = len(artists)
        for rank, a in enumerate(artists):
            bump(a.get("name"), SOURCE_WEIGHTS[source] * _rank_decay(rank, n),
                 source, a.get("genres"))

    for a in followed:
        bump(a.get("name"), SOURCE_WEIGHTS["followed"], "followed", a.get("genres"))

    plays: dict = {}
    for t in recent_tracks:
        for a in ((t.get("track") or {}).get("artists") or []):
            key = normalize_name(a.get("name"))
            if not key:
                continue
            plays[key] = plays.get(key, 0) + 1
            if plays[key] <= RECENT_PLAY_CAP:
                bump(a.get("name"), SOURCE_WEIGHTS["recent"], "recent")

    artists_out: dict = {}
    genre_acc: dict = {}
    for key, w in weight.items():
        w = min(w, WEIGHT_CAP)
        tier = _tier_for(w)
        if not tier:
            continue
        m = meta[key]
        artists_out[key] = {
            "name": m["name"],
            "weight": round(w, 2),
            "tier": tier,
            "sources": sorted(m["sources"]),
        }
        for g in m["genres"]:                       # genre affinity = sum of its artists' weights
            genre_acc[g] = genre_acc.get(g, 0.0) + w

    top = max(genre_acc.values()) if genre_acc else 0.0
    genres_out = {g: round(v / top, 3) for g, v in
                  sorted(genre_acc.items(), key=lambda kv: -kv[1])} if top else {}

    return {
        "generated_at": now or datetime.now().isoformat(timespec="seconds"),
        "source": "spotify",
        "artists": artists_out,
        "genres": genres_out,
    }


# ── Scoring-side readers (called by lib/scoring.py) ───────────────────────────────────

def _scoring_cfg(profile: dict) -> dict:
    sp = ((profile or {}).get("scoring") or {}).get("spotify") or {}
    cfg = dict(DEFAULT_SCORING)
    cfg.update({k: v for k, v in sp.items() if k != "tier_points"})
    if "tier_points" in sp:
        tp = dict(DEFAULT_SCORING["tier_points"])
        tp.update(sp["tier_points"])
        cfg["tier_points"] = tp
    return cfg


def artist_affinity(hay: str, affinity: dict, profile: dict = None) -> tuple:
    """(points, reasons) for Spotify/feedback artists that appear in the event haystack.

    `hay` is the lowercased title+venue+detail+lineup blob the scorer already builds.
    Points are graded by tier and capped (artist_cap) so the music layer nudges without
    drowning the human spine. A "hidden" tier (from feedback "never show") down-ranks.
    """
    artists = (affinity or {}).get("artists") or {}
    if not artists:
        return 0, []
    cfg = _scoring_cfg(profile)
    tier_points = cfg["tier_points"]
    minlen = cfg["min_name_len"]

    pts, reasons, suppress = 0, [], 0
    for key, info in artists.items():
        if len(key) < minlen or key not in hay:
            continue
        tier = info.get("tier", "light")
        p = tier_points.get(tier, 0)
        name = info.get("name", key)
        if tier == "hidden":
            suppress += p                          # p is negative
            reasons.append(f"{p} you've hidden {name}")
        elif p:
            pts += p
            label = {"core": "core rotation", "strong": "heavy rotation",
                     "light": "on rotation"}.get(tier, "rotation")
            reasons.append(f"+{p} Spotify {label} ({name})")
    capped = min(pts, cfg["artist_cap"]) + suppress
    # Re-derive reasons total if the cap bit (keep them honest about the net).
    if pts > cfg["artist_cap"]:
        reasons.append(f"(capped artist affinity at +{cfg['artist_cap']})")
    return capped, reasons


def genre_affinity(hay: str, affinity: dict, profile: dict = None) -> tuple:
    """(points, reasons) when a high-affinity Spotify genre appears in the haystack. Conservative."""
    genres = (affinity or {}).get("genres") or {}
    if not genres:
        return 0, []
    cfg = _scoring_cfg(profile)
    hits = [g for g, v in genres.items() if v >= cfg["genre_threshold"] and g in hay]
    if not hits:
        return 0, []
    pts = min(cfg["genre_points"], cfg["genre_cap"])
    return pts, [f"+{pts} Spotify genre ({hits[0]})"]
