"""Digest assembly — turn a scored pool into a day-grouped, diversity-filled, STABLE slate.

Selection layer on top of the deterministic score (scoring.py stays the absolute spine — the
dashboard depends on it; never mutated here). Three jobs raw `sort by -score` can't do:

  1. LANES, not the muddy `category`. "electronic" lumps a mainstream headliner room in with a
     warehouse afters and a rooftop day party — so the headliner crowds out the afters. We slate
     on a finer LANE derived from the existing multi-axis tags (tags.type/vibe/setting/scale):
     club splits into mainstream / afters / day / underground, and live-music splits big
     (hall/arena — taste.yaml's "mostly to stay informed" tier) vs. the rest, so the Bowl can't
     crowd Zebulon out of the live floor. Mood knob falls out for free: `mute` a lane (e.g.
     "no mainstream this weekend", "no arena shows") and it drops without touching anything else.
  2. Diversity by construction (slate-fill) — counts per lane emerge from merit (no firm
     numbers): fill to a per-day ceiling, cut at score-gap cliffs, with a diversity FLOOR that
     guarantees a taste of afters/day/live-music/film/stage without capping the strong lanes.
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
from .tagging import TYPES, billed_afters, parse_hours, tag_event

# Arena/amphitheater/stadium gazetteer — a booking here signals a mainstream-scale act. Pairs
# with the `amphitheater` setting tag and a high-price proxy; the editor's lane override is the
# real fix for headliner-draw the venue can't reveal (a big name in a small warehouse).
# tagging.VENUE_SCALE ('arena') supersets this list; it stays as a safety net for records
# tagged before the scale axis existed.
BIG_VENUE = ("hollywood bowl", "kia forum", "the forum", "crypto.com arena", "bmo stadium",
             "sofi stadium", "greek theatre", "intuit dome", "microsoft theater",
             "peacock theater", "honda center", "youtube theater", "toyota arena", "acrisure",
             "yaamava", "shrine", "dodger stadium", "rose bowl", "banc of california")

# THE canonical lane vocabulary (family = the part before ':'). Every non-club type is its
# own lane; club splits four ways; live-music splits big vs. the rest. This tuple is the one
# source of truth the other surfaces must agree with (editor.validate_verdict whitelists
# against it; render GROUPS family-match it; build_dashboard FP_MARQUEES/_fp_section route on it;
# .claude/agents/event-editor.md quotes it).
LANES = tuple(t for t in TYPES if t != "club") + (
    "live-music:big", "club:mainstream", "club:afters", "club:day", "club:underground")

# Per-day slate policy. NO firm per-lane numbers — how many afters vs. day vs. live-music
# emerges from the events' effective scores (which the editor's tier/adjust shape). Knobs:
#   gap        score-gap cliff that ends the merit run, so the slate isn't padded past a
#              quality drop-off (e.g. 3 standouts then junk -> 3 picks, not a forced 10).
#   guarantee  a diversity FLOOR (priority order): ensure at least one of each if a decent
#              pick exists — variety without capping the strong lanes.
#   caps       optional hard ceilings; empty by default (the firm-number knob, off).
# `club:mainstream` is intentionally NOT capped — a stacked-mainstream night can take several;
# the `mute` arg drops the lane when you're not feeling it.
# `live-music` in the guarantee is deliberately the BARE lane (exact match): since the
# live-music:big split, the floor guarantees a small/mid-room live pick — arena/hall shows
# enter on merit only, exactly matching taste.yaml's "mostly to stay informed".
DEFAULT_SLATE = {
    "gap": 3,
    "guarantee": ["club:afters", "club:day", "live-music", "film", "stage", "art"],
    "caps": {},
}

_TIER_RANK = {"must-see": 3, "great": 2, "solid": 1, None: 0, "skip": -2}


def _max_price(ev: dict):
    """Largest dollar figure in the price string (rough mainstream-scale proxy)."""
    nums = re.findall(r"\$\s?(\d+)", str(ev.get("price") or ""))
    return max((int(n) for n in nums), default=None)


def _big_scale(ev: dict, tags: dict) -> bool:
    """Hall/arena-tier venue: the tags.scale fact axis, with the legacy amphitheater-setting
    and BIG_VENUE checks as the safety net for pre-scale-axis tag blocks."""
    if tags.get("scale") in ("hall", "arena"):
        return True
    if "amphitheater" in (tags.get("setting") or []):
        return True
    venue = (ev.get("venue") or "").lower()
    return any(b in venue for b in BIG_VENUE)


def event_lane(ev: dict, verdicts: dict = None) -> str:
    """The slate lane for an event. An editor verdict's `lane` wins (it can see headliner draw
    and CHARACTER the venue can't reveal — an 80s night at Zebulon is club:mainstream); with
    two carve-outs: an off-vocab lane string is ignored (the cache is LLM-written and
    unvalidated historically), and a bare-FAMILY override ('live-music', from the pre-split
    vocab) defers to the more specific deterministic sub-lane in the same family — the editor
    meant "this is live music, not club", never "not big". Cross-family overrides always win.

    Otherwise derive from the multi-axis tags. The club split is semantic, not chronological
    (the old afters-on-any-10pm-start rule routed every real warehouse party to `afters` and
    left `underground` holding the residue):
      afters      — genuinely post-close (the semantic `afterhours` vibe: billed as afters,
                    dead-hours doors, or a run past 4am — a 10pm-4am Exchange mainstage IS
                    afters). An underground MAIN event (doors before midnight + warehouse-
                    grade signals) keeps its lane when the vibe is merely inferred from
                    hours — but an explicit afters BILLING (the promoter's own claim, e.g.
                    "HARDfest Afters") always lands here; afters is the party after the party.
      day         — day-party/sunset vibe or a rooftop/pool/outdoor room.
      underground — warehouse/diy room or a TBA-location drop, at any start time. Checked
                    BEFORE the scale/price rules so a stacked warehouse bill can't drift
                    into big rooms. Also the residual for ordinary small-room club nights.
      mainstream  — festival bills, hall/arena bookings, or the $70+ price proxy.
    live-music splits big (hall/arena — the "stay informed" tier) vs. the rest.

    Lanes (see LANES): club:{mainstream,afters,day,underground}, live-music[:big], film,
    stage, comedy, market, workshop, art, food-drink, community, other."""
    tags = ev.get("tags") or tag_event(ev)
    typ = tags.get("type") or "other"
    if typ == "club":
        vibe = set(tags.get("vibe") or [])
        setting = set(tags.get("setting") or [])
        price = _max_price(ev)
        underground = bool({"warehouse", "diy"} & setting) or "tba-location" in vibe
        start, _end = parse_hours(ev)
        main_event = start is not None and 9 <= start <= 23      # doors before midnight
        if "afterhours" in vibe and (billed_afters(ev) or not (underground and main_event)):
            det = "club:afters"
        elif "day-party" in vibe or "sunset" in vibe or (setting & {"rooftop", "pool", "outdoor"}):
            det = "club:day"
        elif underground:
            det = "club:underground"
        elif "festival" in vibe or _big_scale(ev, tags) or (price and price >= 70):
            det = "club:mainstream"
        else:
            det = "club:underground"
    elif typ == "live-music" and _big_scale(ev, tags):
        det = "live-music:big"
    else:
        det = typ

    v = (verdicts or {}).get(event_key(ev)) if verdicts else None
    vl = str(v.get("lane")) if v and v.get("lane") else None
    if vl and vl in LANES and not (":" in det and vl == det.split(":")[0]):
        return vl
    return det


def _resolve_per_day(per_day, iso_date: str) -> int:
    """per_day may be an int, or {'weekday': N, 'weekend': M} (Fri/Sat = weekend)."""
    if isinstance(per_day, dict):
        try:
            wknd = date.fromisoformat(iso_date[:10]).weekday() in (4, 5)
        except (ValueError, TypeError):
            wknd = False
        return per_day["weekend"] if wknd else per_day["weekday"]
    return per_day


def effective_key(ev: dict, verdicts: dict):
    """Deterministic ranking key: (tier, score+adjust, stable event_key tiebreak).
    The event_key tiebreak kills run-to-run thrash — equal-ranked events hold a fixed order."""
    v = verdicts.get(event_key(ev)) or {}
    return (
        _TIER_RANK.get(v.get("tier"), 0),
        (ev.get("score") or 0) + (v.get("adjust") or 0),
        event_key(ev),
    )


def _eff_score(ev: dict, verdicts: dict):
    """The score+adjust component (the gap rule and merit fill compare on this)."""
    return (ev.get("score") or 0) + ((verdicts.get(event_key(ev)) or {}).get("adjust") or 0)


# Additive tier weight for the GLOBAL rank (dashboard's final_rank), distinct from effective_key's
# tier-PRIMARY ordering. Within the slate a must-see leads its day outright (tier-primary, fine —
# the window is fully judged). Globally, mixing judged and unjudged events, an unjudged high score
# must not sink below a judged "solid" — so here tier is a bounded bonus on top of score+adjust.
RANK_TIER_BONUS = {"must-see": 6, "great": 3, "solid": 1, None: 0, "skip": -6}


def rank_score(ev: dict, verdicts: dict):
    """Scalar blend: score + adjust + a bounded tier bonus, so a must-see is strongly lifted but
    an unjudged score-12 still outranks a judged score-4 must-see (10). Used where judged and
    brand-new/unjudged events must compete fairly — the enrichment-head selection (Track B2)."""
    v = verdicts.get(event_key(ev)) or {}
    return (ev.get("score") or 0) + (v.get("adjust") or 0) + RANK_TIER_BONUS.get(v.get("tier"), 0)


def rank_key(ev: dict, verdicts: dict):
    """Two-zone ordering for the dashboard's final_rank (Track B2, LLM-first): judged non-skip
    events sort TIER-PRIMARY (the editor's call is the ranking; score+adjust orders within a
    tier), the unjudged tail (far-out / junk-lane / judged-any-second-now) sorts below them by
    raw score, and judged skips sink to the very bottom. Descending sort — higher tuple wins.

    Rationale vs rank_score's blend: the near window is fully judged (Track B1), so on the
    global list "judged" ≈ "near + surfaceable" and the far unjudged tail *should* rank below
    it in a default view (date filters cover plan-ahead)."""
    v = verdicts.get(event_key(ev)) or {}
    tier = v.get("tier")
    eff = (ev.get("score") or 0) + (v.get("adjust") or 0)
    if tier == "skip":
        return (0, 0, eff)
    if tier:
        return (2, _TIER_RANK.get(tier, 0), eff)
    return (1, 0, ev.get("score") or 0)


# ── One Don't-miss policy across surfaces (2026-07-16 redesign follow-up) ────────────────────
# The flagship digest's "Don't miss" shelf and the dashboard front page's hero row are the same
# product surface — the top handful across a window — so they select through ONE policy: walk in
# rank_key order (tier-primary, the editor's call; the exact expression final_rank is stamped
# from), one pick per program, and diversity caps so five club nights can't fill the shelf.
# Callers window their own pool (the digest spans its whole window; the hero picks per time
# lens) — the ordering, collapse rule, and knobs are what's shared.
TOP_PICKS_N = 6
TOP_PICKS_LANE_CAP = 2   # per exact lane within one pick set …
TOP_PICKS_FAM_CAP = 3    # … and per lane family (club:*)


def top_picks(pool: list, verdicts: dict = None, *, n: int = TOP_PICKS_N,
              lane_cap: int = TOP_PICKS_LANE_CAP, fam_cap: int = TOP_PICKS_FAM_CAP,
              series_of=None) -> list:
    """THE top-picks selection (digest Don't-miss shelf + front-page hero row): rank the pool
    by (rank_key, event_key) — identical to how the dashboard's final_rank is stamped, so the
    two surfaces can never disagree on order — then pick until `n`, skipping judged skips,
    duplicate keys, extra nights of an already-seen program (`series_of` keys a multi-night
    run/film program; its best-ranked night represents it, and a cap-blocked program is
    consumed, not deferred to a worse night), and anything past the lane/family diversity
    caps. A pre-stamped `lane` field is honored (feed rows carry event_lane's own output);
    otherwise the lane derives here."""
    verdicts = verdicts or {}
    ranked = sorted((e for e in pool if e.get("iso_date")),
                    key=lambda e: (rank_key(e, verdicts), event_key(e)), reverse=True)
    seen, programs, lane_n, fam_n, picks = set(), set(), Counter(), Counter(), []
    for e in ranked:
        k = event_key(e)
        if k in seen:
            continue
        seen.add(k)
        if (verdicts.get(k) or {}).get("tier") == "skip":
            continue
        prog = series_of(e) if series_of else None
        if prog:
            if prog in programs:
                continue
            programs.add(prog)
        lane = e.get("lane") or event_lane(e, verdicts)
        fam = lane.split(":")[0]
        if lane_n[lane] >= lane_cap or fam_n[fam] >= fam_cap:
            continue
        picks.append(e)
        lane_n[lane] += 1
        fam_n[fam] += 1
        if len(picks) >= n:
            break
    return picks


def slate_fill(day_evs: list, per_day: int, slate: dict, verdicts: dict,
               min_guarantee_score: int = 2) -> list:
    """One day's slate: merit-fill to per_day, cut at a score-gap cliff, then a diversity FLOOR.

    No firm per-lane numbers — the count per lane emerges from effective score (which the
    editor's tier/adjust shape, so the LLM effectively decides how many of each). A `gap` drop
    from the last pick ends the run early so the slate isn't padded with filler past a quality
    cliff. `caps` (optional, default none) can still impose a hard ceiling. Pass B guarantees
    each `guarantee` lane appears if a decent pick exists — appending when there's room, else
    swapping out the weakest pick from an over-represented lane."""
    ranked = sorted(day_evs, key=lambda e: effective_key(e, verdicts), reverse=True)
    if not ranked:
        return []
    caps = slate.get("caps") or {}
    gap = slate.get("gap")

    picks, used, lane_n, prev = [], set(), Counter(), None
    for e in ranked:                                   # merit fill, cut at a score cliff
        if len(picks) >= per_day:
            break
        eff = _eff_score(e, verdicts)
        if gap is not None and prev is not None and prev - eff > gap:
            break
        ln = event_lane(e, verdicts)
        if caps.get(ln) is not None and lane_n[ln] >= caps[ln]:
            continue
        picks.append(e); used.add(event_key(e)); lane_n[ln] += 1; prev = eff

    for gl in slate.get("guarantee", []):              # diversity FLOOR — append if room, else swap
        if any(event_lane(p, verdicts) == gl for p in picks):
            continue
        best = next((e for e in ranked
                     if event_lane(e, verdicts) == gl and event_key(e) not in used
                     and (e.get("score") or 0) >= min_guarantee_score), None)
        if not best:
            continue
        if len(picks) < per_day:
            picks.append(best); used.add(event_key(best)); lane_n[gl] += 1
            continue
        removable = sorted([p for p in picks if lane_n[event_lane(p, verdicts)] > 1],
                           key=lambda e: effective_key(e, verdicts))
        if not removable:
            continue
        drop = removable[0]
        picks.remove(drop); used.discard(event_key(drop)); lane_n[event_lane(drop, verdicts)] -= 1
        picks.append(best); used.add(event_key(best)); lane_n[gl] += 1

    return sorted(picks, key=lambda e: effective_key(e, verdicts), reverse=True)


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
