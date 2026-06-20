"""Digest assembly — turn a scored pool into a day-grouped, diversity-filled, STABLE slate.

This is the selection layer that sits on top of the deterministic score (scoring.py stays
the absolute spine — the dashboard depends on it; we never mutate it here). Two jobs the raw
`sort by -score` can't do:

  1. Diversity by construction (slate-fill) — a day that's 40 techno nights shouldn't surface
     8 techno nights. We fill category slots so theater/film/live music get a look even when
     they score below the electronic flood (the "theater=4 in the 4+ set" problem). Diversity
     is a SELECTION concern, solved here, not a SCORING hack in scoring.py.
  2. Stability — picks are ordered by a deterministic key (score [+ optional LLM verdict],
     then event_key), so a fixed event keeps its position run-to-run instead of thrashing.

The optional `verdicts` map is the thin-editor hook: { event_key: {tier, adjust, ...} }. Absent,
assembly degrades to pure deterministic slate-fill (no API needed). Present, an LLM verdict can
promote/demote within the sort and pin tier order — without ever re-sorting the whole list itself.

  assemble(pool, verdicts=None, per_day=..., slate=...) -> [{date, picks:[ev,...]}, ...]
"""

from collections import Counter, defaultdict
from datetime import date

from .enrich import event_key

# Per-day diversity policy. `caps` bounds how many of one category a day can show (so the
# strong categories don't crowd everything out); `guarantee` lists categories to ensure at
# least one of — in priority order — IF a decent one exists that day. Tune freely; this is
# the taste knob, deliberately a plain dict so it's editable without touching the algorithm.
DEFAULT_SLATE = {
    "caps": {"electronic": 3, "party": 2, "comedy": 1},
    "guarantee": ["live_music", "music", "film", "theater", "art", "beer_food"],
}

# Coarse tier ordering from an LLM verdict (optional). Higher sorts first.
_TIER_RANK = {"must-see": 3, "great": 2, "solid": 1, None: 0, "skip": -2}


def norm_category(ev: dict) -> str:
    """Lowercased, synonym-folded category — fixes the `music`/`Music` split and `live music`."""
    c = (ev.get("category") or "general").strip().lower()
    return {"live music": "live_music", "livemusic": "live_music"}.get(c, c)


def _resolve_per_day(per_day, iso_date: str) -> int:
    """per_day may be an int, or {'weekday': N, 'weekend': M} (Fri/Sat = weekend)."""
    if isinstance(per_day, dict):
        try:
            wknd = date.fromisoformat(iso_date[:10]).weekday() in (4, 5)
        except (ValueError, TypeError):
            wknd = False
        return per_day["weekend"] if wknd else per_day["weekday"]
    return per_day


def _eff_key(ev: dict, verdicts: dict):
    """Deterministic ranking key: (tier, score+adjust, then a stable event_key tiebreak).

    The event_key tiebreak is what kills run-to-run thrash — equal-scored events keep a fixed
    relative order instead of depending on input iteration order."""
    v = verdicts.get(event_key(ev)) or {}
    return (
        _TIER_RANK.get(v.get("tier"), 0),
        (ev.get("score") or 0) + (v.get("adjust") or 0),
        event_key(ev),
    )


def slate_fill(day_evs: list, per_day: int, slate: dict, verdicts: dict,
               min_guarantee_score: int = 2) -> list:
    """One day's slate: merit-fill under per-category caps, then guarantee diversity slots.

    Pass A fills best-first up to per_day, honoring `caps`. Pass B ensures each `guarantee`
    category appears (if a pick scoring >= min_guarantee_score exists) by swapping out the
    weakest pick from an over-represented category — never dropping below per_day, never
    featuring junk just for variety. Returns picks in display order (best-first)."""
    ranked = sorted(day_evs, key=lambda e: _eff_key(e, verdicts), reverse=True)
    caps = slate.get("caps", {})

    picks, used, cat_n = [], set(), Counter()
    for e in ranked:                                   # Pass A — merit under caps
        if len(picks) >= per_day:
            break
        c = norm_category(e)
        if caps.get(c) is not None and cat_n[c] >= caps[c]:
            continue
        picks.append(e); used.add(event_key(e)); cat_n[c] += 1

    for gc in slate.get("guarantee", []):              # Pass B — guarantee diversity
        if any(norm_category(p) == gc for p in picks):
            continue
        best = next((e for e in ranked
                     if norm_category(e) == gc and event_key(e) not in used
                     and (e.get("score") or 0) >= min_guarantee_score), None)
        if not best:
            continue
        removable = sorted([p for p in picks if cat_n[norm_category(p)] > 1],
                           key=lambda e: _eff_key(e, verdicts))
        if not removable:
            continue
        drop = removable[0]
        picks.remove(drop); used.discard(event_key(drop)); cat_n[norm_category(drop)] -= 1
        picks.append(best); used.add(event_key(best)); cat_n[gc] += 1

    return sorted(picks, key=lambda e: _eff_key(e, verdicts), reverse=True)


def assemble(pool: list, verdicts: dict = None, per_day=8, slate: dict = None,
             min_guarantee_score: int = 2) -> list:
    """Group the scored pool by day and slate-fill each. `pool` = score_view dicts (have
    `iso_date`, `score`, `category`). Returns [{date, picks:[ev,...]}] in date order."""
    verdicts = verdicts or {}
    slate = slate or DEFAULT_SLATE
    by_day = defaultdict(list)
    for e in pool:
        if e.get("iso_date"):
            by_day[e["iso_date"]].append(e)
    return [
        {"date": d, "picks": slate_fill(by_day[d], _resolve_per_day(per_day, d),
                                        slate, verdicts, min_guarantee_score)}
        for d in sorted(by_day)
    ]
