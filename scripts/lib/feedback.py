"""Feedback loop — fold reactions into the music-affinity layer (Phase C).

Closes the loop so reactions move the weights AUTOMATICALLY instead of being hand-merged
into taste.yaml. Reactions live in data/feedback.jsonl (append-only); each line:

  {"ts": "2026-06-16", "kind": "loved", "artists": ["Chris Lake"], "note": "..."}
  {"ts": "2026-06-16", "kind": "hide",  "artists": ["Some Bro DJ"]}
  {"ts": "2026-06-16", "kind": "loved", "genres": ["deep house", "disco"]}
  {"ts": "2026-06-16", "kind": "clicked_ticket", "artists": ["Antal"]}   # implicit signal

kinds: loved / went (explicit +), clicked_ticket / added_calendar (implicit +, emitted by the
Phase B/D delivery surfaces once they exist), skipped (soft -), hide (hard "never show").

These aggregate into per-artist / per-genre nudges and fold into the affinity dict the scorer
already consumes (lib/affinity.py) — feedback is the third layer of the one scoring profile
(Spotify music affinity + taste.yaml human spine + feedback). Pure + tested; I/O lives in the
merged_affinity() loader that run_digest.py and build_dashboard.py share.
"""

import json
from pathlib import Path

from .affinity import normalize_name, _tier_for
from .enrich import event_key

# Per-reaction weight nudge applied to an artist/genre. Overridable via
# profile.yaml `scoring.feedback.weights`. `hide` is large + negative so it forces
# the `hidden` tier regardless of any Spotify weight underneath.
DEFAULT_WEIGHTS = {
    "loved": 2.0,
    "went": 1.5,
    "clicked_ticket": 0.5,
    "added_calendar": 0.5,
    "skipped": -0.5,
    "hide": -10.0,
}
HIDE_KINDS = {"hide", "never", "block"}


def _weights(profile: dict) -> dict:
    fb = ((profile or {}).get("scoring") or {}).get("feedback") or {}
    w = dict(DEFAULT_WEIGHTS)
    w.update(fb.get("weights") or {})
    return w


def load_feedback(path) -> list:
    """Read data/feedback.jsonl -> [reaction dicts]. Blank/`#`/malformed lines are skipped."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def aggregate(reactions: list, profile: dict = None) -> dict:
    """Collapse reactions into per-artist / per-genre weight deltas + the hide set."""
    w = _weights(profile)
    artist_delta, genre_delta, hide, names = {}, {}, set(), {}
    for r in reactions:
        kind = (r.get("kind") or "").lower()
        delta = w.get(kind, 0.0)
        for a in (r.get("artists") or []):
            key = normalize_name(a)
            if not key:
                continue
            names[key] = a.strip()
            artist_delta[key] = artist_delta.get(key, 0.0) + delta
            if kind in HIDE_KINDS:
                hide.add(key)
        for g in (r.get("genres") or []):
            gk = (g or "").strip().lower()
            if gk:
                genre_delta[gk] = genre_delta.get(gk, 0.0) + delta
    return {"artist_delta": artist_delta, "genre_delta": genre_delta, "hide": hide, "names": names}


def apply_feedback(affinity: dict, agg: dict) -> dict:
    """Fold aggregated feedback into an affinity dict (Spotify-derived or empty).

    Adds artists feedback knows but Spotify didn't; nudges weights of shared ones; forces the
    `hidden` tier for "never show"; and drops an artist whose weight feedback pushed below the
    `light` floor. Genres are nudged and clamped to [0, 1].
    """
    aff = affinity or {}
    artists = dict(aff.get("artists") or {})
    genres = dict(aff.get("genres") or {})
    names = agg.get("names", {})

    for key, delta in agg["artist_delta"].items():
        base = artists.get(key) or {"name": names.get(key, key), "sources": []}
        info = dict(base)
        info["weight"] = round(base.get("weight", 0.0) + delta, 2)
        info["sources"] = sorted(set(base.get("sources") or []) | {"feedback"})
        if key in agg["hide"]:
            info["tier"] = "hidden"
            artists[key] = info
        else:
            tier = _tier_for(info["weight"])
            if tier:
                info["tier"] = tier
                artists[key] = info
            elif key in artists:
                del artists[key]   # feedback drove it below the 'light' floor -> stop scoring it

    for gk, delta in agg["genre_delta"].items():
        genres[gk] = round(min(1.0, max(0.0, genres.get(gk, 0.0) + delta)), 3)

    had_music = bool(aff.get("artists") or aff.get("genres"))
    has_feedback = bool(agg["artist_delta"] or agg["genre_delta"])
    out = dict(aff)
    out["artists"], out["genres"] = artists, genres
    if has_feedback:
        out["source"] = "spotify+feedback" if had_music else "feedback"
    return out


def reacted_keys(reactions: list) -> dict:
    """{event_key: latest reaction ts} for rows that TARGET a specific event. The Worker stamps
    `event_key` on every dashboard-tap feedback row (star/less/seen/hide); artist/genre-level
    rows from the concierge/CLI carry none and don't gate verdicts. Latest ts wins — ISO strings
    compare lexicographically, full-timestamp or date-only alike."""
    out = {}
    for r in reactions:
        k = (r or {}).get("event_key")
        ts = str((r or {}).get("ts") or "").strip()
        if not k or not ts:
            continue
        if ts > out.get(k, ""):
            out[k] = ts
    return out


def stamp_reacted(events: list, reactions: list) -> int:
    """Stamp `reacted_at` onto events the user explicitly reacted to (matched by event key), so
    editor._stale re-judges exactly those regardless of the DRIFT_MIN score gate — one tap earns
    one targeted re-judge, while diffuse affinity ripples stay dampened. Mutates in place;
    returns how many events got stamped."""
    keys = reacted_keys(reactions)
    if not keys:
        return 0
    n = 0
    for e in events:
        ts = keys.get(event_key(e))
        if ts:
            e["reacted_at"] = ts
            n += 1
    return n


def affinity_paths(repo, profile_hash: str = None) -> tuple:
    """(spotify_affinity_path, feedback_path) for a profile — or the default/owner layer.

    Default/owner (no hash): the canonical data/spotify_affinity.json + data/feedback.jsonl
    (Ari's music layer, the one the digest scores against). A per-profile hash points at that
    profile's OWN layer instead — data/spotify/<hash>.json + data/feedback.<hash>.jsonl — so a
    friend's feed folds in THEIR Spotify + reactions, never Ari's. Hash is the same 16-hex feed
    key the dashboard and build_profiles.py use (sha256(salt + username)).
    """
    repo = Path(repo)
    if profile_hash:
        return (repo / "data" / "spotify" / f"{profile_hash}.json",
                repo / "data" / f"feedback.{profile_hash}.jsonl")
    return (repo / "data" / "spotify_affinity.json", repo / "data" / "feedback.jsonl")


def merged_affinity(repo, profile: dict = None, *, profile_hash: str = None) -> dict:
    """The shared loader: a Spotify affinity artifact + a feedback log -> one affinity dict.

    With no `profile_hash` this is the default/owner layer (data/spotify_affinity.json +
    data/feedback.jsonl) — what the digest and the logged-out dashboard score against. Pass a
    profile's feed hash to load THAT profile's own per-person layer instead (see affinity_paths),
    so a friend's ranking reflects their music + reactions, not Ari's.

    Returns None when neither layer has anything (scorer then runs the taste.yaml-only path).
    Graceful: a corrupt Spotify artifact is ignored. Used by run_digest.py + build_dashboard.py
    so the digest and the dashboard always score against the exact same merged profile.
    """
    sp_path, fb_path = affinity_paths(repo, profile_hash)
    spotify = None
    if sp_path.exists():
        try:
            spotify = json.loads(sp_path.read_text())
        except (ValueError, OSError):
            spotify = None
    reactions = load_feedback(fb_path)
    if not spotify and not reactions:
        return None
    return apply_feedback(spotify, aggregate(reactions, profile))
