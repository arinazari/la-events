"""Editor verdict plumbing — the thin-editor's deterministic glue (no LLM in this module).

The editor is a batched Claude pass at digest time (sibling of scene-researcher) that judges the
ranked pool and emits a per-event VERDICT layered on top of the deterministic score:

    {tier: must-see|great|solid|skip, lane?: str, adjust: -3..3, why: str, confidence: low|med|high}

assemble.py folds verdicts onto the slate — `tier` orders, `adjust` de-clusters the lumpy integer
scores (so the gap-cliff bites) and nudges within a tier, `lane` overrides the deterministic lane.
THIS module is the side-effect-free plumbing: which events to judge, the per-event editor record
(with the Spotify/feedback affinity surfaced so the LLM can use it), the accumulating cache, the
{key:verdict} map the assembler consumes, and contract validation for the LLM output.

PER-PROFILE. A verdict is taste-dependent (Ari's must-see is a friend's skip), so verdicts live in
their OWN per-profile file — data/verdicts/<profile_hash>.json (default profile: data/verdicts/
default.json) — NOT in the shared enrichment.json (that's scene facts, which are cross-profile).

  editor_pool(scored, per_lane, floor)    -> ranked subset worth judging (PER-LANE, not a flat cut)
  pool_doc(judge, ..., affinity, profile) -> the editor-pool doc (records + the profile's Spotify lane)
  verdict_path / load_verdicts / save_verdicts  -> per-profile verdict store I/O
  select_for_verdict(pool, cache, ...)    -> pool minus already-judged (misses / stale / score-drift)
  verdict_map(cache)                      -> {event_key: verdict} for assemble()
  update_verdicts(cache, results, scores) -> fold a judging batch back in (validated)
  validate_verdict(v)                     -> coerce/validate one LLM verdict; None if unusable
  prune_verdicts(cache, catalog)          -> drop verdicts for events gone from the catalog
"""

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .enrich import event_key, scene_facts
from .assemble import event_lane
from .affinity import _token_pat

REPO = Path(__file__).resolve().parent.parent.parent
VERDICTS_DIR = REPO / "data" / "verdicts"

TIERS = ("must-see", "great", "solid", "skip")
CONFIDENCE = ("low", "med", "high")
ADJUST_MIN, ADJUST_MAX = -3, 3
_VERDICT_FIELDS = ("tier", "lane", "adjust", "why", "confidence")

# Lanes that never surface in the going-out slate — judged only if they clear the floor, never
# via per-lane inclusion (keeps the judging set focused on surfaceable events, not market stalls).
NON_SLATE_LANES = ("other", "workshop", "community", "market")

_RECORD_FIELDS = ("title", "venue", "neighborhood", "date", "start", "category",
                  "price", "score", "reasons", "tags")

# Bumped whenever the editor RECORD shape changes (the LLM's input), so already-judged verdicts
# get re-judged once against the new context — `_stale` re-selects any verdict stamped with an
# older version. (1 = baseline; 2 = adds the shared-enrichment `scene` block from scene_facts.)
EDITOR_INPUT_VERSION = 2


# ── Per-profile verdict store ─────────────────────────────────────────────────────────

def verdict_path(profile_hash: str = None) -> Path:
    """data/verdicts/<hash>.json — the default profile is `default.json`."""
    return VERDICTS_DIR / f"{profile_hash or 'default'}.json"


def load_verdicts(path=None, profile_hash: str = None) -> dict:
    """Load a profile's verdict cache: {"verdicts": {key: verdict}} (empty if absent)."""
    p = Path(path) if path else verdict_path(profile_hash)
    if p.exists():
        c = json.loads(p.read_text())
        c.setdefault("verdicts", {})
        return c
    return {"verdicts": {}}


def save_verdicts(cache: dict, path=None, profile_hash: str = None) -> None:
    p = Path(path) if path else verdict_path(profile_hash)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")


# ── Selection: who to judge ───────────────────────────────────────────────────────────

def editor_pool(scored: list, per_lane: int = 0, floor: int = 4,
                skip_lanes=NON_SLATE_LANES) -> list:
    """The set worth spending LLM judgment on.

    `per_lane=0` (the default — LLM-first recall mode, Track B1): EVERY slate-lane event in the
    window is judged, so the deterministic score never gates what the editor sees. Non-slate
    lanes (skip_lanes — market stalls, workshops) still only enter via the `floor` score, so
    junk lanes aren't judged wholesale. The verdict cache keeps this affordable: only the daily
    delta actually costs calls.

    `per_lane>0` (legacy shape, kept for cheap ad-hoc runs): union of (a) the top `per_lane`
    events of each lane *per day* and (b) everything scoring >= `floor`. De-duped by event_key;
    lane is the deterministic one (no verdicts yet)."""
    skip = set(skip_lanes)
    picked = {}
    if per_lane and per_lane > 0:
        groups = defaultdict(list)
        for e in scored:
            ln = event_lane(e)
            if ln in skip:
                continue
            groups[(e.get("iso_date"), ln)].append(e)
        for evs in groups.values():
            for e in sorted(evs, key=lambda e: -(e.get("score") or 0))[:per_lane]:
                picked[event_key(e)] = e
    else:
        for e in scored:
            if event_lane(e) not in skip:
                picked[event_key(e)] = e
    for e in scored:
        if (e.get("score") or 0) >= floor:
            picked[event_key(e)] = e
    return list(picked.values())


# ── The editor record: deterministic context + Spotify affinity, surfaced for the LLM ──

def affinity_hint(ev: dict, affinity: dict) -> dict:
    """Per-event Spotify/feedback signal for the editor — which billed artists are in the user's
    affinity (name + tier + weight) and which high-affinity genres appear. Richer than the capped
    score reason: lets the editor reason about rotation depth and judge unfamiliar lineups."""
    if not affinity:
        return None
    artists = affinity.get("artists") or {}
    genres = affinity.get("genres") or {}
    title = ev.get("title") or ""
    lineup = ev.get("lineup") or []
    if not isinstance(lineup, list):
        lineup = [str(lineup)]
    name_text = (title + " " + " ".join(str(a) for a in lineup)).lower()

    hit_a = [{"name": info.get("name", key), "tier": info.get("tier"), "weight": info.get("weight")}
             for key, info in artists.items()
             if len(key) >= 3 and _token_pat(key).search(name_text)]
    hit_a.sort(key=lambda a: -(a.get("weight") or 0))

    hay = name_text + " " + " ".join((ev.get("tags") or {}).get("genre") or [])
    hit_g = [g for g, v in genres.items() if v >= 0.5 and g in hay]

    if not hit_a and not hit_g:
        return None
    hint = {}
    if hit_a:
        hint["artists"] = hit_a[:6]
    if hit_g:
        hint["genres"] = hit_g[:4]
    return hint


def affinity_summary(affinity: dict, n_artists: int = 20, n_genres: int = 12) -> dict:
    """Profile-level Spotify lane for the editor prompt — the user's top artists/genres, so the
    editor can weigh an unfamiliar lineup against what they actually listen to."""
    if not affinity:
        return None
    artists = sorted((affinity.get("artists") or {}).values(), key=lambda a: -(a.get("weight") or 0))
    return {
        "source": affinity.get("source"),
        "top_artists": [{"name": a.get("name"), "tier": a.get("tier")} for a in artists[:n_artists]],
        "top_genres": list((affinity.get("genres") or {}).keys())[:n_genres],  # artifact is pre-sorted
    }


def _record(ev: dict, affinity: dict, enrichment: dict = None) -> dict:
    """Compact event record for the event-editor agent — deterministic score/reasons/tags, the
    derived lane (overridable by the verdict), the per-event affinity hint, and (when the shared
    enrichment cache is supplied) a taste-NEUTRAL `scene` block of facts about the event/lineup so
    the editor judges unfamiliar names against verified facts instead of re-deriving them. The
    `scene` block is the SAME shared enrichment for every profile (no taste leak — see
    enrich.scene_facts); only `affinity` + the profile's taste personalize the verdict."""
    rec = {"id": event_key(ev)}
    for f in _RECORD_FIELDS:
        rec[f] = ev.get(f)
    rec["lineup"] = ev.get("lineup") or []
    rec["lane"] = event_lane(ev)
    hint = affinity_hint(ev, affinity)
    if hint:
        rec["affinity"] = hint
    if enrichment is not None:
        scene = scene_facts(ev, enrichment)
        if scene:
            rec["scene"] = scene
    return rec


def pool_doc(judge: list, *, today, window_days, per_lane, floor, affinity: dict = None,
             enrichment: dict = None) -> dict:
    """Build the editor-pool document run_digest/build_dashboard write for the agent to judge.
    Includes the profile's Spotify lane (`profile_affinity`) so the editor judges with it, and —
    when `enrichment` (the shared scene cache) is passed — a per-event factual `scene` block."""
    doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat() if hasattr(today, "isoformat") else today,
        "window_days": window_days,
        "per_lane": per_lane,
        "floor": floor,
        "count": len(judge),
        "events": [_record(e, affinity, enrichment) for e in judge],
    }
    summary = affinity_summary(affinity)
    if summary:
        doc["profile_affinity"] = summary
    return doc


# ── Verdict cache ─────────────────────────────────────────────────────────────────────

def _stale(hit: dict, ev: dict, refresh_days, today: date) -> bool:
    """Re-judge if the editor's input SHAPE changed since the verdict (input_version bump — e.g. the
    scene block was added, so an old blind verdict must be re-judged once), if the deterministic
    score moved (new lineup, or feedback/affinity shifted it), or — when refresh_days is set — the
    verdict is older than that. A legacy verdict with no input_version reads as version-mismatched
    and re-judges once, then carries the current stamp."""
    if hit.get("input_version") != EDITOR_INPUT_VERSION:
        return True
    saj = hit.get("score_at_judge")
    if saj is not None and (ev.get("score") or 0) != saj:
        return True
    if refresh_days is None:
        return False
    ja = str(hit.get("judged_at") or "")[:10]
    try:
        d = date.fromisoformat(ja)
    except ValueError:
        return True
    return ((today or date.today()) - d).days >= refresh_days


def select_for_verdict(pool: list, cache: dict, refresh_days=None, today: date = None) -> list:
    """Events still needing a verdict: never judged, score-drifted, or (with refresh_days) stale.
    Each carries `id` (= event_key) for the editor to echo back. Default = write-once delta."""
    verdicts = cache.get("verdicts") or {}
    out = []
    for e in pool:
        k = event_key(e)
        hit = verdicts.get(k)
        if hit is None or _stale(hit, e, refresh_days, today):
            ee = dict(e)
            ee["id"] = k
            out.append(ee)
    return out


def verdict_map(cache: dict) -> dict:
    """{event_key: verdict} (contract fields only) for assemble()."""
    return {
        k: {f: v[f] for f in _VERDICT_FIELDS if f in v}
        for k, v in (cache.get("verdicts") or {}).items()
    }


def validate_verdict(v: dict):
    """Coerce one raw LLM verdict to the contract; return None if unusable (bad/missing tier).
    Clamps `adjust` to [-3, 3], defaults `confidence` to 'med', keeps `lane`/`why` if present."""
    if not isinstance(v, dict) or v.get("tier") not in TIERS:
        return None
    out = {"tier": v["tier"]}
    if v.get("lane"):
        out["lane"] = str(v["lane"])
    try:
        adj = int(v.get("adjust") or 0)
    except (TypeError, ValueError):
        adj = 0
    out["adjust"] = max(ADJUST_MIN, min(ADJUST_MAX, adj))
    if v.get("why"):
        out["why"] = str(v["why"])[:200]
    out["confidence"] = v["confidence"] if v.get("confidence") in CONFIDENCE else "med"
    return out


def update_verdicts(cache: dict, results: list, scores: dict = None, now: str = None,
                    model: str = None) -> dict:
    """Fold a judging batch (verdict dicts, each with `id` = event_key) into the cache. Stamps
    `judged_at`, `model`, and `score_at_judge` (from `scores[key]`, or the result's own `score`)
    so a later score drift re-selects it. Invalid verdicts are skipped."""
    cache.setdefault("verdicts", {})
    now = now or datetime.now().isoformat(timespec="seconds")
    scores = scores or {}
    for r in results:
        k = r.get("id")
        v = validate_verdict(r)
        if not k or v is None:
            continue
        v["judged_at"] = now
        v["input_version"] = EDITOR_INPUT_VERSION   # so a later record-shape bump re-judges this
        if k in scores:
            v["score_at_judge"] = scores[k]
        elif "score" in r:
            v["score_at_judge"] = r["score"]
        if model:
            v["model"] = model
        cache["verdicts"][k] = v
    return cache


def prune_verdicts(cache: dict, catalog: list) -> tuple:
    """Drop verdicts for events no longer in the catalog (hygiene). Returns (cache, n_pruned)."""
    live = {event_key(ev) for ev in catalog}
    verdicts = cache.get("verdicts") or {}
    kept = {k: v for k, v in verdicts.items() if k in live}
    pruned = len(verdicts) - len(kept)
    cache["verdicts"] = kept
    return cache, pruned
