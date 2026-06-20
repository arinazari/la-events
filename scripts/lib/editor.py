"""Editor verdict plumbing — the thin-editor's deterministic glue (no LLM in this module).

The editor is a batched Claude pass at digest time (sibling of scene-researcher) that judges the
ranked pool and emits a per-event VERDICT layered on top of the deterministic score:

    {tier: must-see|great|solid|skip, lane?: str, adjust: -3..3, why: str, confidence: low|med|high}

assemble.py folds verdicts onto the slate — `tier` orders, `adjust` de-clusters the lumpy integer
scores (so the gap-cliff bites) and nudges within a tier, `lane` overrides the deterministic lane
(the editor catches headliner-draw the tags can't). THIS module is the side-effect-free plumbing:
which events to judge, the accumulating cache (a daily run judges only the delta), the {key:verdict}
map the assembler consumes, and contract validation for the LLM output.

Shares data/enrichment.json with enrich.py — verdicts under a third top-level key, same event_key:

    { "events": {...}, "artists": {...},
      "verdicts": { "<key>": { ...verdict, "score_at_judge": int, "judged_at": ISO, "model": str } } }

  editor_pool(scored, per_lane, floor)    -> ranked subset worth judging (PER-LANE, not a flat cut)
  select_for_verdict(pool, cache, ...)    -> pool minus already-judged (misses / stale / score-drift)
  verdict_map(cache)                      -> {event_key: verdict} for assemble()
  update_verdicts(cache, results, scores) -> fold a judging batch back in (validated)
  validate_verdict(v)                     -> coerce/validate one LLM verdict; None if unusable
  prune_verdicts(cache, catalog)          -> drop verdicts for events gone from the catalog
"""

from collections import defaultdict
from datetime import date, datetime

from .enrich import DEFAULT_CACHE, event_key, load_cache as _load_enrich, save_cache  # noqa: F401
from .assemble import event_lane

TIERS = ("must-see", "great", "solid", "skip")
CONFIDENCE = ("low", "med", "high")
ADJUST_MIN, ADJUST_MAX = -3, 3
_VERDICT_FIELDS = ("tier", "lane", "adjust", "why", "confidence")


def load_cache(path=DEFAULT_CACHE) -> dict:
    """enrich.load_cache + ensure the `verdicts` key exists (shared cache file)."""
    c = _load_enrich(path)
    c.setdefault("verdicts", {})
    return c


def editor_pool(scored: list, per_lane: int = 4, floor: int = 4) -> list:
    """The set worth spending LLM judgment on — PER-LANE, not a flat score cutoff.

    Union of (a) the top `per_lane` events of each lane *per day* and (b) everything scoring
    >= `floor`. (a) guarantees every lane's best gets judged even when its absolute scores sit
    below the electronic flood (the "theater never clears a flat 4" problem); (b) covers the
    high-absolute set. De-duped by event_key. Lane is the deterministic one (no verdicts yet)."""
    groups = defaultdict(list)
    for e in scored:
        groups[(e.get("iso_date"), event_lane(e))].append(e)

    picked = {}
    for evs in groups.values():
        for e in sorted(evs, key=lambda e: -(e.get("score") or 0))[:per_lane]:
            picked[event_key(e)] = e
    for e in scored:
        if (e.get("score") or 0) >= floor:
            picked[event_key(e)] = e
    return list(picked.values())


def _stale(hit: dict, ev: dict, refresh_days, today: date) -> bool:
    """Re-judge if the deterministic score moved since the verdict (new lineup, or feedback/
    affinity shifted it), or — when refresh_days is set — the verdict is older than that."""
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
