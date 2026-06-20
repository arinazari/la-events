"""Digest assembly — turn a scored pool into a day-grouped, diversity-filled, STABLE slate.

Selection layer on top of the deterministic score (scoring.py stays the absolute spine — the
dashboard depends on it; never mutated here). Three jobs raw `sort by -score` can't do:

  1. LANES, not the muddy `category`. "electronic" lumps a mainstream headliner room in with a
     warehouse afters and a rooftop day party — so the headliner crowds out the afters. We slate
     on a finer LANE derived from the existing multi-axis tags (tags.type/vibe/setting): club
     splits into mainstream / afters / day / underground. Mood knob falls out for free: `mute`
     a lane (e.g. "no mainstream this weekend") and it drops without touching anything else.
  2. Diversity by construction (slate-fill) — per-lane caps + guaranteed slots so afters, day
     parties, live music, film, stage surface instead of being buried under whichever lane floods.
  3. Stability — deterministic ordering key (score [+ optional verdict], then event_key), so a
     fixed event keeps its slot run-to-run instead of thrashing.

The optional `verdicts` map is the thin-editor hook: { event_key: {tier, adjust, lane, ...} }.
Absent → pure deterministic slate (no API). Present → an LLM verdict can promote/demote within
the sort, pin tier order, AND override the lane (the editor catches "this is a big mainstream
headliner" — a draw signal the deterministic tags can't see).

  assemble(pool, verdicts=None, per_day=..., slate=..., mute=...) -> [{date, picks:[ev]}, ...]
"""

import re
from collections import Counter, defaultdict
from datetime import date

from .enrich import event_key
from .tagging import tag_event

# Arena/amphitheater/stadium gazetteer — a booking here signals a mainstream-scale act. Pairs
# with the `amphitheater` setting tag and a high-price proxy; the editor's lane override is the
# real fix for headliner-draw the venue can't reveal (a big name in a small warehouse).
BIG_VENUE = ("hollywood bowl", "kia forum", "the forum", "crypto.com arena", "bmo stadium",
             "sofi stadium", "greek theatre", "intuit dome", "microsoft theater",
             "peacock theater", "honda center", "youtube theater", "toyota arena", "acrisure",
             "yaamava", "shrine", "dodger stadium", "rose bowl", "banc of california")

# Per-day diversity policy, keyed by LANE. `caps` bounds one lane's share so it can't flood;
# `guarantee` ensures at least one of each (priority order) if a decent one exists. The taste
# knob — edit freely. `club:mainstream` is capped at 1 and guaranteed, so Chris-Lake-scale shows
# stay visible in general without obfuscating the afters/day/underground lanes beside them.
DEFAULT_SLATE = {
    "caps": {
        "club:mainstream": 1, "club:day": 1, "club:afters": 2, "club:underground": 2,
        "comedy": 1,
    },
    "guarantee": ["club:afters", "club:day", "club:mainstream",
                  "live-music", "film", "stage", "art"],
}

_TIER_RANK = {"must-see": 3, "great": 2, "solid": 1, None: 0, "skip": -2}


def _max_price(ev: dict):
    """Largest dollar figure in the price string (rough mainstream-scale proxy)."""
    nums = re.findall(r"\$\s?(\d+)", str(ev.get("price") or ""))
    return max((int(n) for n in nums), default=None)


def event_lane(ev: dict, verdicts: dict = None) -> str:
    """The slate lane for an event. An editor verdict's `lane` wins (it can see headliner draw);
    otherwise derive deterministically from the multi-axis tags, splitting `club` into sub-lanes.

    Lanes: club:{mainstream,afters,day,underground}, live-music, film, stage, comedy, market,
    art, food-drink, community, other."""
    v = (verdicts or {}).get(event_key(ev)) if verdicts else None
    if v and v.get("lane"):
        return v["lane"]

    tags = ev.get("tags") or tag_event(ev)
    typ = tags.get("type") or "other"
    if typ != "club":
        return typ

    vibe = set(tags.get("vibe") or [])
    setting = set(tags.get("setting") or [])
    venue = (ev.get("venue") or "").lower()
    price = _max_price(ev)
    if "afterhours" in vibe:
        return "club:afters"
    if "day-party" in vibe or "sunset" in vibe or (setting & {"rooftop", "pool", "outdoor"}):
        return "club:day"
    if "amphitheater" in setting or any(b in venue for b in BIG_VENUE) or (price and price >= 70):
        return "club:mainstream"
    return "club:underground"


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
    """Deterministic ranking key: (tier, score+adjust, stable event_key tiebreak).
    The event_key tiebreak kills run-to-run thrash — equal-ranked events hold a fixed order."""
    v = verdicts.get(event_key(ev)) or {}
    return (
        _TIER_RANK.get(v.get("tier"), 0),
        (ev.get("score") or 0) + (v.get("adjust") or 0),
        event_key(ev),
    )


def slate_fill(day_evs: list, per_day: int, slate: dict, verdicts: dict,
               min_guarantee_score: int = 2) -> list:
    """One day's slate: merit-fill under per-lane caps, then guarantee diversity slots.

    Pass A fills best-first up to per_day honoring `caps`. Pass B ensures each `guarantee` lane
    appears (if a pick scoring >= min_guarantee_score exists) by swapping out the weakest pick
    from an over-represented lane — never below per_day, never junk for variety's sake."""
    ranked = sorted(day_evs, key=lambda e: _eff_key(e, verdicts), reverse=True)
    caps = slate.get("caps", {})

    picks, used, lane_n = [], set(), Counter()
    for e in ranked:                                   # Pass A — merit under caps
        if len(picks) >= per_day:
            break
        ln = event_lane(e, verdicts)
        if caps.get(ln) is not None and lane_n[ln] >= caps[ln]:
            continue
        picks.append(e); used.add(event_key(e)); lane_n[ln] += 1

    for gl in slate.get("guarantee", []):              # Pass B — guarantee diversity
        if any(event_lane(p, verdicts) == gl for p in picks):
            continue
        best = next((e for e in ranked
                     if event_lane(e, verdicts) == gl and event_key(e) not in used
                     and (e.get("score") or 0) >= min_guarantee_score), None)
        if not best:
            continue
        removable = sorted([p for p in picks if lane_n[event_lane(p, verdicts)] > 1],
                           key=lambda e: _eff_key(e, verdicts))
        if not removable:
            continue
        drop = removable[0]
        picks.remove(drop); used.discard(event_key(drop)); lane_n[event_lane(drop, verdicts)] -= 1
        picks.append(best); used.add(event_key(best)); lane_n[gl] += 1

    return sorted(picks, key=lambda e: _eff_key(e, verdicts), reverse=True)


def assemble(pool: list, verdicts: dict = None, per_day=8, slate: dict = None,
             mute=None, min_guarantee_score: int = 2) -> list:
    """Group the scored pool by day and slate-fill each. `pool` = score_view dicts (carry
    `iso_date`, `score`, `tags`). `mute` = lanes to drop entirely this run (mood knob, e.g.
    {"club:mainstream"}). Returns [{date, picks:[ev]}] in date order."""
    verdicts = verdicts or {}
    slate = slate or DEFAULT_SLATE
    mute = set(mute or ())
    by_day = defaultdict(list)
    for e in pool:
        if e.get("iso_date") and event_lane(e, verdicts) not in mute:
            by_day[e["iso_date"]].append(e)
    return [
        {"date": d, "picks": slate_fill(by_day[d], _resolve_per_day(per_day, d),
                                        slate, verdicts, min_guarantee_score)}
        for d in sorted(by_day)
    ]
