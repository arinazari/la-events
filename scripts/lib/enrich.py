"""Enrichment layer — the scene-researcher's deterministic data plumbing.

scene-researcher (Tier 1) turns a ranked candidate into scene intelligence: type/sub-genre
tags, artist notes, a curator's note, a clean description, and (top picks) an image. The LLM
does that; THIS module is the side-effect-free glue around it:

  event_key(ev)                    -> stable cache key (title+date+venue), no schema mutation
  load_cache / save_cache          -> the accumulating scene graph (data/enrichment.json)
  select_for_enrichment(cands,c)   -> candidates not yet cached (the batch to research)
  merge_enrichment(cands, cache)   -> attach cached enrichment onto candidates (for rendering)
  update_cache(cache, results)     -> fold a scene-researcher batch back in (events + artists)

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
from datetime import datetime
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


def select_for_enrichment(candidates: list, cache: dict) -> list:
    """Candidates whose key isn't cached yet — the batch to hand the scene-researcher.
    Each carries an `id` (= event_key) so the agent echoes it back for merging."""
    out = []
    for c in candidates:
        k = event_key(c)
        if k not in cache["events"]:
            cc = dict(c)
            cc["id"] = k
            out.append(cc)
    return out


def merge_enrichment(candidates: list, cache: dict) -> list:
    """Return candidates with cached enrichment attached under `enrichment` (+ stable `id`)."""
    out = []
    for c in candidates:
        cc = dict(c)
        k = event_key(c)
        cc["id"] = k
        hit = cache["events"].get(k)
        if hit:
            cc["enrichment"] = hit
        out.append(cc)
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
