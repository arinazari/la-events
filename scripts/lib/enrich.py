"""Enrichment layer — the scene-researcher's deterministic data plumbing.

scene-researcher (Tier 1) turns a ranked candidate into scene intelligence: type/sub-genre
tags, artist notes, a curator's note, a clean description, and (top picks) an image. The LLM
does that; THIS module is the side-effect-free glue around it:

  event_key(ev)                    -> stable cache key (title+date+venue), no schema mutation
  load_cache / save_cache          -> the accumulating scene graph (data/enrichment.json)
  select_for_enrichment(cands,c)   -> candidates needing FULL scene-research: not cached, stale,
                                      OR only blurb-tier so far (a blurb event that climbed into the
                                      head gets upgraded — see the tier model below)
  select_for_blurb(cands, cache)   -> cheap-tier candidates: no cache record AND no usable source
                                      `detail` to fall back on (blurb-writer gives them one line)
  merge_enrichment(cands, cache)   -> attach cached enrichment + fold cached artist bios onto any
                                      event that lists them (coverage compounds across runs)
  update_cache(cache, results)     -> fold a scene-researcher (FULL-tier) batch back in (events + artists)
  update_blurb_cache(cache, res)   -> fold a blurb-writer (cheap-tier) batch back in (never downgrades full)
  prune_cache(cache, catalog)      -> drop entries for events gone from the catalog (hygiene;
                                      keeps artist bios). Run by the daily routine, not the planner.

Cache (data/enrichment.json) — the moat-lite, accumulates across runs:
  { "events":  { "<key>": { ...enrichment..., "enriched_tier": full|blurb, "enriched_at": ISO } },
    "artists": { "<norm name>": { "note": str, "seen": ISO } } }

Two enrichment tiers share the events cache (keyed the same), so the dashboard reads one place:
  - `full`  (head, top ~100): the scene-researcher's whole scene-intelligence record (below).
  - `blurb` (mid): a blurb-writer one-liner — { id, description, enriched_tier:"blurb", confidence }.
A blurb record is an UPGRADE candidate: if its event later ranks into the full head,
select_for_enrichment re-selects it and scene-researcher overwrites it with a full record. The
reverse never happens (update_blurb_cache won't downgrade a full record). A record with NO
`enriched_tier` is legacy = full (only full scene-research ever wrote the cache before tiers).

Enrichment record (scene-researcher FULL output, per event):
  { id, type, subgenres[], label_orbit[], energy, setting, sounds_like[],
    artist_notes[{name,note}], curator_note, description,
    enriched_tier:"full", confidence }
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
    """Candidates needing FULL scene-research: not cached yet, only blurb-tier so far (a cheap-tier
    event that climbed into the head — upgrade it), OR — when refresh_days is set — cached but stale
    (enriched_at older than refresh_days, the freshness knob). Each carries an `id` (= event_key) so
    the agent echoes it back for merging. Default (refresh_days=None) is write-once for FULL records:
    only genuine misses + blurb-upgrades, no re-research cost. A record with no `enriched_tier` is
    legacy-full and never re-selected (pre-tiers, only full scene-research wrote the cache)."""
    out = []
    for c in candidates:
        k = event_key(c)
        hit = cache["events"].get(k)
        if hit is None or hit.get("enriched_tier") == "blurb" or _is_stale(hit, refresh_days, today):
            cc = dict(c)
            cc["id"] = k
            out.append(cc)
    return out


def select_for_blurb(candidates: list, cache: dict) -> list:
    """Cheap-tier candidates for the blurb-writer: every event with NO cache record yet (full or
    blurb). One clean factual line per event — cheap (haiku, no web), write-once. We do NOT skip
    events that carry source `detail`: a sanitized source blurb is an inconsistent voice and often
    marketing-toned, so the LLM line is worth its (tiny) cost for a uniform card. Raw `detail`
    stays as the display fallback for anything the blurb tier doesn't reach (overflow/failure).
    Caller passes the slice below the full head; each result carries its `id` for write-back."""
    out = []
    for c in candidates:
        k = event_key(c)
        if cache["events"].get(k) is not None:
            continue
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


def update_cache(cache: dict, results: list, now: str = None) -> dict:
    """Fold a scene-researcher (FULL-tier) batch (list of enrichment records) into the cache.
    Events are keyed by `id` and stamped `enriched_tier:"full"` (overwriting any prior blurb);
    artist notes accumulate by normalized name (reused next run)."""
    now = now or datetime.now().isoformat(timespec="seconds")
    for r in results:
        k = r.get("id")
        if not k:
            continue
        rec = dict(r)
        rec["enriched_at"] = now
        rec.setdefault("enriched_tier", "full")
        cache["events"][k] = rec
        for an in r.get("artist_notes") or []:
            name = normalize(an.get("name", ""))
            if name and name not in cache["artists"]:
                cache["artists"][name] = {"note": an.get("note"), "seen": now}
    return cache


def update_blurb_cache(cache: dict, results: list, now: str = None) -> dict:
    """Fold a blurb-writer (cheap-tier) batch into the cache as `blurb`-tier records, each
    {id, description, confidence?}. Never downgrades a FULL record (if the event got fully
    enriched in the same run, that wins) — so the upgrade path is one-way, full beats blurb."""
    now = now or datetime.now().isoformat(timespec="seconds")
    for r in results:
        k = r.get("id")
        if not k or not r.get("description"):
            continue
        existing = cache["events"].get(k)
        if existing and existing.get("enriched_tier") != "blurb":
            continue   # legacy-full or full -> don't clobber with a one-liner
        rec = {"id": k, "description": r["description"],
               "enriched_tier": "blurb", "enriched_at": now}
        if r.get("confidence"):
            rec["confidence"] = r["confidence"]
        cache["events"][k] = rec
    return cache
