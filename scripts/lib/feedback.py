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


def merged_affinity(repo, profile: dict = None) -> dict:
    """The shared loader: data/spotify_affinity.json + data/feedback.jsonl -> one affinity dict.

    Returns None when neither layer has anything (scorer then runs the taste.yaml-only path).
    Graceful: a corrupt Spotify artifact is ignored. Used by run_digest.py + build_dashboard.py
    so the digest and the dashboard always score against the exact same merged profile.
    """
    repo = Path(repo)
    spotify = None
    sp = repo / "data" / "spotify_affinity.json"
    if sp.exists():
        try:
            spotify = json.loads(sp.read_text())
        except (ValueError, OSError):
            spotify = None
    reactions = load_feedback(repo / "data" / "feedback.jsonl")
    if not spotify and not reactions:
        return None
    return apply_feedback(spotify, aggregate(reactions, profile))
