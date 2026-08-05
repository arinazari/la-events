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
  select_for_verdict(pool, cache, ...)    -> pool minus already-judged (misses / stale / score drift >= DRIFT_MIN)
  verdict_map(cache)                      -> {event_key: verdict} for assemble()
  update_verdicts(cache, results, scores) -> fold a judging batch back in (validated)
  validate_verdict(v)                     -> coerce/validate one LLM verdict; None if unusable
  prune_verdicts(cache, catalog)          -> drop verdicts for events gone from the catalog
"""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .enrich import event_key, scene_facts
from .assemble import LANES, event_lane
from .affinity import _token_pat, fold
from .series import group_series

REPO = Path(__file__).resolve().parent.parent.parent
VERDICTS_DIR = REPO / "data" / "verdicts"

TIERS = ("must-see", "great", "solid", "skip")
CONFIDENCE = ("low", "med", "high")
ADJUST_MIN, ADJUST_MAX = -3, 3
WHY_MAX = 280            # verdict `why` budget — rendered verbatim in compact digest lines

# Score-drift re-judge threshold: a cached verdict is re-judged only when the deterministic score
# has moved by at least this much since it was judged. Scores ripple by ±1 all the time without
# changing what the editor would say — one reaction folds into affinity and nudges every matching
# event, a small policy tweak re-scores a whole category — and exact-match drift once flipped ~75
# owner verdicts "stale" at once, turning one Update click into a 27-minute judging flood
# (2026-08-01). Creep still triggers: a kept verdict's score_at_judge is NOT refreshed, so two +1
# steps accumulate to Δ2 against the stored score and re-select.
DRIFT_MIN = 2
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


def resolve_store_hash(profile_hash: str, manifest: dict):
    """Map a profile FEED hash to its verdict-STORE hash. The owner's store is the default
    (returns None -> data/verdicts/default.json): their taste IS the root taste, and the nightly
    judge, the feed build, and render_digest all read the default store for them. An on-demand
    rebuild only knows the owner's public feed hash, so without this mapping its merged verdicts
    land in a per-hash file no ranking consumer reads (the 2026-08-01 owner Update judged 75
    events into exactly that dead store). Any other hash — or an empty manifest — passes
    through unchanged."""
    if not profile_hash or not isinstance(manifest, dict):
        return profile_hash
    salt = manifest.get("salt") or "la-events/v1:"
    want = str(profile_hash).strip().lower()
    for p in manifest.get("profiles") or []:
        if p and p.get("owner") and p.get("username"):
            h = hashlib.sha256((salt + str(p["username"]).strip().lower()).encode("utf-8")) \
                .hexdigest()[:16]
            if h == want:
                return None
    return profile_hash


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
                skip_lanes=NON_SLATE_LANES, today: date = None) -> list:
    """The set worth spending LLM judgment on.

    Hygiene first (2026-08 shadow-eval): rows dated before `today` and junk listings
    (pipeline.is_junk_event — upsells, placeholders, spam) never enter the pool. Both
    classes were reaching the editor and burning verdicts on non-events ("past event"
    skips, a must-see'd presale-offer row). Undated rows pass — TBA is not past.

    `per_lane=0` (the default — LLM-first recall mode, Track B1): EVERY slate-lane event in the
    window is judged, so the deterministic score never gates what the editor sees. Non-slate
    lanes (skip_lanes — market stalls, workshops) still only enter via the `floor` score, so
    junk lanes aren't judged wholesale. The verdict cache keeps this affordable: only the daily
    delta actually costs calls.

    `per_lane>0` (legacy shape, kept for cheap ad-hoc runs): union of (a) the top `per_lane`
    events of each lane *per day* and (b) everything scoring >= `floor`. De-duped by event_key;
    lane is the deterministic one (no verdicts yet)."""
    from .pipeline import is_junk_event   # local: keep lib import graph acyclic
    cutoff = (today or date.today()).isoformat()
    kept = []
    for e in scored:
        d = str(e.get("date") or e.get("iso_date") or "")[:10]
        if d and d < cutoff:
            continue
        if is_junk_event(e):
            continue
        kept.append(e)
    scored = kept
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
    name_text = fold(title + " " + " ".join(str(a) for a in lineup))

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
    # Selection bookkeeping, not editor input (no EDITOR_INPUT_VERSION bump): rides the record so
    # select_for_verdict sees it when the agent loads the pool doc (feedback.stamp_reacted put it
    # on the scored event; _record would otherwise drop it).
    if ev.get("reacted_at"):
        rec["reacted_at"] = ev["reacted_at"]
    return rec


# The taste keys worth embedding in the pool doc — the editor's BRIEF (Track B3). The editor is
# the ranker now; the human-authored taste content rides in its input so the judgment is hermetic
# (no repo Read needed) and per-profile pools carry that profile's own brief. Additive context —
# deliberately NOT part of EDITOR_INPUT_VERSION (prior verdicts were judged by an agent that Read
# taste.yaml itself; a bump would re-judge ~1,000 cached verdicts for near-zero delta).
_TASTE_BRIEF_KEYS = ("narrative", "categories", "boosts", "penalties", "artists_tracked",
                     "venues_loved", "comedians_loved", "film")


def taste_brief(taste: dict) -> dict:
    """The distilled taste profile embedded in the editor's pool doc."""
    return {k: (taste or {}).get(k) for k in _TASTE_BRIEF_KEYS if (taste or {}).get(k)}


def _series_context(judge: list) -> dict:
    """{event_key: series note} for pool events that are one night of a multi-night run (or the
    same film across theaters — lib/series grouping). The editor needs this to spend its top
    tiers on PROGRAMS, not nights: without it, every night of a 15-night 70mm run reads as a
    fresh marquee event and five of them come back must-see. Additive record context — like the
    taste brief, deliberately NOT an EDITOR_INPUT_VERSION bump (film-score changes big enough to
    matter re-select the affected verdicts via score drift anyway)."""
    out = {}
    for members in group_series(judge).values():
        ms = sorted(members, key=lambda e: str(e.get("iso_date") or e.get("date") or ""))
        venues = []
        for m in ms:
            v = m.get("venue")
            if v and v not in venues:
                venues.append(v)
        for i, e in enumerate(ms, 1):
            note = {"nights": len(ms), "night": i,
                    "first": str(ms[0].get("iso_date") or ms[0].get("date") or "")[:10],
                    "last": str(ms[-1].get("iso_date") or ms[-1].get("date") or "")[:10]}
            if len(venues) > 1:
                note["venues"] = venues
            out[event_key(e)] = note
    return out


def pool_doc(judge: list, *, today, window_days, per_lane, floor, affinity: dict = None,
             enrichment: dict = None, taste: dict = None) -> dict:
    """Build the editor-pool document run_digest/build_dashboard write for the agent to judge.
    Includes the profile's Spotify lane (`profile_affinity`) so the editor judges with it, the
    profile's `taste_profile` brief (Track B3 — the editor is the ranker; this is its brief),
    and — when `enrichment` (the shared scene cache) is passed — a per-event factual `scene`
    block. Records that are one night of a series carry a `series` note (night i of n, span,
    venues) so the editor judges the program once instead of must-seeing every night."""
    sctx = _series_context(judge)
    records = []
    for e in judge:
        rec = _record(e, affinity, enrichment)
        s = sctx.get(rec["id"])
        if s:
            rec["series"] = s
        records.append(rec)
    doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat() if hasattr(today, "isoformat") else today,
        "window_days": window_days,
        "per_lane": per_lane,
        "floor": floor,
        "count": len(judge),
        "events": records,
    }
    brief = taste_brief(taste)
    if brief:
        doc["taste_profile"] = brief
    summary = affinity_summary(affinity)
    if summary:
        doc["profile_affinity"] = summary
    return doc


# ── Verdict cache ─────────────────────────────────────────────────────────────────────

def _stale(hit: dict, ev: dict, refresh_days, today: date) -> bool:
    """Re-judge if the editor's input SHAPE changed since the verdict (input_version bump — e.g. the
    scene block was added, so an old blind verdict must be re-judged once), if the deterministic
    score moved by >= DRIFT_MIN (a real lineup/feedback shift — ±1 ripples keep the verdict, and
    since score_at_judge stays put on a kept verdict, creep accumulates and re-selects at Δ2), or —
    when refresh_days is set — the verdict is older than that. A legacy verdict with no
    input_version reads as version-mismatched and re-judges once, then carries the current stamp."""
    if hit.get("input_version") != EDITOR_INPUT_VERSION:
        return True
    # An explicit reaction on THIS event (a dashboard tap → feedback row with event_key, stamped
    # onto the record as `reacted_at` by feedback.stamp_reacted) forces a re-judge no matter how
    # little the score moved: DRIFT_MIN dampens diffuse ripples, never a direct tap. Compare at
    # the stamp's own precision — full-ISO stamps are exact (stable once judged_at passes them);
    # legacy date-only stamps are day-granular (a same-day tap re-judges on each pass that day,
    # bounded to that one event, gone once the Worker's full-ISO ts rolls out).
    ra = str(ev.get("reacted_at") or "").strip()[:19]
    if ra:
        ja = str(hit.get("judged_at") or "")[:19]
        if not ja or ra >= ja[:len(ra)]:
            return True
    saj = hit.get("score_at_judge")
    if saj is not None and abs((ev.get("score") or 0) - saj) >= DRIFT_MIN:
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
    """Events still needing a verdict: never judged, score-drifted (>= DRIFT_MIN), or (with
    refresh_days) stale. Each carries `id` (= event_key) for the editor to echo back.
    Default = write-once delta."""
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
    Clamps `adjust` to [-3, 3], defaults `confidence` to 'med', keeps `why` if present, and
    keeps `lane` only when it's in the canonical assemble.LANES vocabulary — an off-vocab lane
    string would flow verbatim into every surface (assemble/render/dashboard use it raw)."""
    if not isinstance(v, dict) or v.get("tier") not in TIERS:
        return None
    out = {"tier": v["tier"]}
    if v.get("lane") and str(v["lane"]) in LANES:
        out["lane"] = str(v["lane"])
    try:
        adj = int(v.get("adjust") or 0)
    except (TypeError, ValueError):
        adj = 0
    out["adjust"] = max(ADJUST_MIN, min(ADJUST_MAX, adj))
    if v.get("why"):
        # Word-boundary clamp: the why is now rendered verbatim in compact digest lines, so a
        # hard slice that cuts mid-word ("badly undersco") reads as a bug. Cut at the last space
        # inside the budget and mark the elision.
        why = str(v["why"])
        if len(why) > WHY_MAX:
            why = why[:WHY_MAX].rsplit(" ", 1)[0].rstrip(" ,;—-") + " …"
        out["why"] = why
    out["confidence"] = v["confidence"] if v.get("confidence") in CONFIDENCE else "med"
    return out


def update_verdicts(cache: dict, results: list, scores: dict = None, now: str = None,
                    model: str = None) -> dict:
    """Fold a judging batch (verdict dicts, each with `id` = event_key) into the cache. Stamps
    `judged_at`, `model`, and `score_at_judge` (from `scores[key]`, or the result's own `score`)
    so a later score drift (>= DRIFT_MIN) re-selects it. Invalid verdicts are skipped."""
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
