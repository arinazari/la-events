"""Enrichment layer — the scene-researcher's deterministic data plumbing.

scene-researcher (Tier 1) turns a ranked candidate into scene intelligence: type/sub-genre
tags, artist notes, a curator's note, a clean description, and (top picks) an image. The LLM
does that; THIS module is the side-effect-free glue around it:

  event_key(ev)                    -> stable cache key (title+date+venue), no schema mutation
  load_cache / save_cache          -> the accumulating scene graph (data/enrichment.json)
  select_for_enrichment(cands,c)   -> candidates not yet cached (or stale, via refresh_days)
  merge_enrichment(cands, cache)   -> attach cached enrichment + fold cached artist bios onto any
                                      event that lists them (coverage compounds across runs)
  update_cache(cache, results)     -> fold a scene-researcher batch back in (events + artists)
  prune_cache(cache, catalog)      -> drop entries for events gone from the catalog (hygiene;
                                      keeps artist bios). Run by the daily routine, not the planner.

Cache (data/enrichment.json) — the moat-lite, accumulates across runs:
  { "events":  { "<key>": { ...enrichment..., "enriched_at": ISO } },
    "artists": { "<norm name>": { "note": str, "seen": ISO } } }

Enrichment record (scene-researcher output, per event):
  { id, type, subgenres[], label_orbit[], energy, setting, sounds_like[],
    artist_notes[{name,note}], curator_note, description,
    image{url,source,credit}  (top-N only), confidence }
"""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from .dedupe import normalize  # same normalizer used for dedupe keys

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE = REPO / "data" / "enrichment.json"


def event_key(ev: dict) -> str:
    """Stable 12-char key from title+date+venue. Computed on the fly — no catalog mutation."""
    t = normalize(ev.get("title", ""))
    v = normalize(ev.get("venue", ""))
    d = str(ev.get("date") or ev.get("iso_date") or "")[:10]
    return hashlib.sha1(f"{t}|{d}|{v}".encode("utf-8")).hexdigest()[:12]


def load_cache(path=DEFAULT_CACHE) -> dict:
    p = Path(path)
    if p.exists():
        c = json.loads(p.read_text())
        c.setdefault("events", {})
        c.setdefault("artists", {})
        return c
    return {"events": {}, "artists": {}}


def save_cache(cache: dict, path=DEFAULT_CACHE) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")


def _is_stale(hit: dict, refresh_days, today: date = None) -> bool:
    """True if a cached entry is older than refresh_days (or has no/garbled timestamp)."""
    if refresh_days is None:
        return False
    ea = str(hit.get("enriched_at") or "")[:10]
    try:
        d = date.fromisoformat(ea)
    except ValueError:
        return True
    return ((today or date.today()) - d).days >= refresh_days


def select_for_enrichment(candidates: list, cache: dict, refresh_days=None, today: date = None) -> list:
    """Candidates to (re)research: not cached yet, OR — when refresh_days is set — cached but
    stale (enriched_at older than refresh_days, the freshness knob). Each carries an `id`
    (= event_key) so the agent echoes it back for merging. Default (refresh_days=None) is
    write-once: only genuine misses, no re-research cost."""
    out = []
    for c in candidates:
        k = event_key(c)
        hit = cache["events"].get(k)
        if hit is None or _is_stale(hit, refresh_days, today):
            cc = dict(c)
            cc["id"] = k
            out.append(cc)
    return out


def prune_cache(cache: dict, catalog: list) -> tuple:
    """Drop event-enrichment entries whose event is no longer in the catalog (expired/removed) —
    cache hygiene so it tracks the live catalog instead of growing unbounded. Artist bios are
    KEPT: they're the durable scene knowledge, reused across events. Returns (cache, n_pruned)."""
    live = {event_key(ev) for ev in catalog}
    events = cache.get("events") or {}
    kept = {k: v for k, v in events.items() if k in live}
    pruned = len(events) - len(kept)
    cache["events"] = kept
    return cache, pruned


def cached_artist_notes(ev: dict, cache: dict) -> list:
    """Artist bios from the cache for any tracked name in this event's lineup/title.

    The scene graph's value compounds here: the ~N accumulated artist bios apply to EVERY
    event featuring those artists, not just the events individually researched. Conservative
    matching — exact normalized lineup entries, plus a length-guarded title substring for an
    artist not in the lineup — to avoid false hits on short names. Display name comes from the
    event's own lineup text (the cache key is lowercased/normalized)."""
    arts = cache.get("artists") or {}
    if not arts:
        return []
    out, seen = [], set()
    lineup = ev.get("lineup") or []
    if not isinstance(lineup, list):
        lineup = [str(lineup)]
    for a in lineup:
        k = normalize(a)
        if k and k in arts and k not in seen:
            out.append({"name": a.strip(), "note": arts[k].get("note")})
            seen.add(k)
    title_norm = normalize(ev.get("title", ""))
    for k, info in arts.items():
        if k and k not in seen and len(k) >= 5 and k in title_norm:
            out.append({"name": k.title(), "note": info.get("note")})
            seen.add(k)
    return out


def merge_enrichment(candidates: list, cache: dict) -> list:
    """Return candidates with cached enrichment attached under `enrichment` (+ stable `id`).

    A fully-researched event gets its whole cached record; ANY event whose lineup/title hits
    the artist cache also gets those artist notes folded in (free coverage from the scene graph),
    supplementing a partial event record or standing in as a lightweight `from_cache` enrichment."""
    out = []
    for c in candidates:
        cc = dict(c)
        k = event_key(c)
        cc["id"] = k
        hit = cache["events"].get(k)
        if hit:
            cc["enrichment"] = hit
        notes = cached_artist_notes(c, cache)
        if notes:
            if hit:
                have = {normalize(n.get("name", "")) for n in (hit.get("artist_notes") or [])}
                extra = [n for n in notes if normalize(n["name"]) not in have]
                if extra:
                    merged = dict(hit)
                    merged["artist_notes"] = (hit.get("artist_notes") or []) + extra
                    cc["enrichment"] = merged
            else:
                cc["enrichment"] = {"artist_notes": notes, "from_cache": True}
        out.append(cc)
    return out


# Taste-NEUTRAL factual enrichment fields safe to share into the PER-PROFILE editor pass.
# Deliberately EXCLUDES curator_note and energy: curator_note is written in the root profile's
# taste voice (scene-researcher reads taste.yaml first), and energy reads as taste-adjacent — so
# folding either into another profile's editor would leak one person's verdict into another's.
# Facts only ("what is this / who is playing"), never opinion.
SCENE_FACT_FIELDS = ("type", "subgenres", "label_orbit", "setting", "sounds_like", "description")


def scene_facts(ev: dict, cache: dict, max_artists: int = 8) -> dict:
    """A compact, taste-NEUTRAL projection of the SHARED enrichment for one event — the factual
    subset (SCENE_FACT_FIELDS + artist bios) safe to feed into the per-profile editor as read-only
    context so it judges unfamiliar lineups against verified facts instead of guessing / re-searching.
    Returns {} on a cache miss. Artist bios fold in from the compounding artist cache
    (cached_artist_notes), so even an un-researched event still tells the editor who its lineup is.
    Structurally cannot include curator_note/energy — only SCENE_FACT_FIELDS + artist_notes."""
    out = {}
    hit = (cache.get("events") or {}).get(event_key(ev))
    if hit:
        for f in SCENE_FACT_FIELDS:
            val = hit.get(f)
            if val:
                out[f] = val
    notes = cached_artist_notes(ev, cache)
    if hit and hit.get("artist_notes"):                 # supplement with the researched record's own
        have = {normalize(n.get("name", "")) for n in notes}
        notes = notes + [n for n in hit["artist_notes"] if normalize(n.get("name", "")) not in have]
    if notes:
        out["artist_notes"] = notes[:max_artists]
    return out


def update_cache(cache: dict, results: list, now: str = None) -> dict:
    """Fold a scene-researcher batch (list of enrichment records) into the cache.
    Events are keyed by `id`; artist notes accumulate by normalized name (reused next run)."""
    now = now or datetime.now().isoformat(timespec="seconds")
    for r in results:
        k = r.get("id")
        if not k:
            continue
        rec = dict(r)
        rec["enriched_at"] = now
        cache["events"][k] = rec
        for an in r.get("artist_notes") or []:
            name = normalize(an.get("name", ""))
            if name and name not in cache["artists"]:
                cache["artists"][name] = {"note": an.get("note"), "seen": now}
    return cache
