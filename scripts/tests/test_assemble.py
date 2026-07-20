#!/usr/bin/env python3
"""Tests for scripts/lib/assemble.py — lanes, the elastic slate, and the two ranking keys.

Run: python scripts/tests/test_assemble.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import assemble as A  # noqa: E402

AFTERS = {"type": "club", "vibe": ["afterhours"], "setting": [], "genre": []}
DAY = {"type": "club", "vibe": ["day-party"], "setting": [], "genre": []}
UG = {"type": "club", "vibe": [], "setting": [], "genre": []}
FILM = {"type": "film", "vibe": [], "setting": [], "genre": []}
STAGE = {"type": "stage", "vibe": [], "setting": [], "genre": []}


def _ev(title, tags, score, d="2026-07-04", venue=None, price=None):
    return {"title": title, "date": d, "venue": venue or (title + " hall"), "price": price,
            "score": score, "iso_date": d, "tags": tags}


LIVE = {"type": "live-music", "vibe": [], "setting": [], "genre": []}


def test_event_lane_splits_club():
    assert A.event_lane(_ev("a", AFTERS, 5)) == "club:afters"
    assert A.event_lane(_ev("d", DAY, 5)) == "club:day"
    assert A.event_lane(_ev("u", UG, 5)) == "club:underground"
    assert A.event_lane(_ev("m", UG, 5, price="$80")) == "club:mainstream"   # price proxy
    assert A.event_lane(_ev("s", STAGE, 5)) == "stage"                       # non-club -> type


def test_event_lane_splits_live_music_on_scale():
    """Hall/arena live shows take the :big sub-lane; everything else stays the bare lane
    (which the guarantee floor exact-matches — so the floor is the small/mid-room floor)."""
    assert A.event_lane(_ev("small", LIVE, 5)) == "live-music"
    assert A.event_lane(_ev("hall", {**LIVE, "scale": "hall"}, 5)) == "live-music:big"
    assert A.event_lane(_ev("bowl", LIVE, 5, venue="Hollywood Bowl")) == "live-music:big"
    # scale=room/bar is NOT big
    assert A.event_lane(_ev("bar", {**LIVE, "scale": "bar"}, 5)) == "live-music"


def test_club_scale_after_vibes():
    """Venue scale reads AFTER the vibe rules: a hall-venue afters stays afters (a 10pm-4am
    Exchange mainstage is not mainstream-by-venue), but a plain hall club night is."""
    hall_afters = _ev("x", {**AFTERS, "scale": "hall"}, 5)
    assert A.event_lane(hall_afters) == "club:afters"
    hall_plain = _ev("y", {**UG, "scale": "hall"}, 5)
    assert A.event_lane(hall_plain) == "club:mainstream"
    fest = _ev("z", {**UG, "vibe": ["festival"]}, 5)
    assert A.event_lane(fest) == "club:mainstream"       # festival bills are mainstream-draw


def test_event_lane_verdict_override():
    ev = _ev("u", UG, 5)
    v = {A.event_key(ev): {"lane": "club:mainstream"}}
    assert A.event_lane(ev, v) == "club:mainstream"   # editor sees headliner draw the tags can't


WH = {"type": "club", "vibe": ["afterhours", "tba-location"], "setting": ["warehouse"], "genre": []}


def test_event_lane_warehouse_main_event_stays_underground():
    """An 11pm-6am TBA warehouse bill is the MAIN event — doors before midnight keeps it
    underground even though its run past 4am earns the afterhours vibe."""
    e = _ev("thermal", WH, 8)
    e["start"] = "11pm-6am"
    assert A.event_lane(e) == "club:underground"


def test_event_lane_post_close_is_afters():
    """Dead-hours doors = genuinely post-close: afters wins even with warehouse signals."""
    e = _ev("renegade", WH, 8)
    e["start"] = "2am"
    assert A.event_lane(e) == "club:afters"


def test_event_lane_billed_afters_beats_main_event_exception():
    """An explicit afters BILLING is the promoter's own claim — it lands in afters even
    with warehouse signals and doors before midnight (e.g. a festival's TBA afterparty)."""
    e = _ev("Saturday HARDfest Afters", WH, 8)
    e["start"] = "22:00"
    assert A.event_lane(e) == "club:afters"


def test_event_lane_pricey_warehouse_not_mainstream():
    """Underground signals beat the $70+ price proxy — a stacked warehouse bill isn't a big room."""
    wh = {"type": "club", "vibe": [], "setting": ["warehouse"], "genre": []}
    assert A.event_lane(_ev("big bill", wh, 8, price="$85")) == "club:underground"


def test_verdict_lane_family_refinement_and_vocab_guard():
    # a bare-family override (pre-split vocab) defers to the same-family deterministic sub-lane
    big = _ev("b", {**LIVE, "scale": "hall"}, 5)
    v = {A.event_key(big): {"lane": "live-music"}}
    assert A.event_lane(big, v) == "live-music:big"
    # …but a cross-family correction always wins (the editor fixing a type leak)
    club_band = _ev("c", UG, 5)
    v2 = {A.event_key(club_band): {"lane": "live-music"}}
    assert A.event_lane(club_band, v2) == "live-music"
    # a SPECIFIC same-family override wins too (mainstream character at a small venue)
    ug = _ev("n", UG, 5)
    v3 = {A.event_key(ug): {"lane": "club:mainstream"}}
    assert A.event_lane(ug, v3) == "club:mainstream"
    # off-vocab strings from the unvalidated cache are ignored
    v4 = {A.event_key(ug): {"lane": "clubz:mega"}}
    assert A.event_lane(ug, v4) == "club:underground"


def test_lanes_vocab_covers_types_and_sublanes():
    assert set(A.LANES) >= {"live-music", "live-music:big", "club:mainstream", "club:afters",
                            "club:day", "club:underground", "film", "stage", "comedy",
                            "market", "workshop", "art", "food-drink", "community", "other"}
    assert "club" not in A.LANES                       # club only exists as sub-lanes


def test_effective_key_tier_primary():
    """Within the slate, tier dominates: a must-see leads its day over a higher raw score."""
    low_ms = _ev("low", UG, 4)
    high = _ev("high", UG, 9)
    v = {A.event_key(low_ms): {"tier": "must-see"}}
    assert A.effective_key(low_ms, v) > A.effective_key(high, {})


def test_rank_score_additive():
    """Globally, tier is a bounded bonus: a must-see lifts hard but doesn't bury a big raw score."""
    ms = _ev("ms", UG, 4)
    v = {A.event_key(ms): {"tier": "must-see"}}
    assert A.rank_score(ms, v) == 10                       # 4 + must-see(6)
    assert A.rank_score(ms, v) > A.rank_score(_ev("n9", UG, 9), {})    # 10 > 9
    assert A.rank_score(ms, v) < A.rank_score(_ev("n12", UG, 12), {})  # 10 < 12
    assert A.rank_score(_ev("sk", UG, 8), {A.event_key(_ev("sk", UG, 8)): {"tier": "skip"}}) == 2


def test_rank_key_two_zone():
    """Dashboard ordering (Track B2): judged non-skip beats ANY unjudged (tier-primary);
    unjudged sorts by raw score in the middle; judged skips sink below everything."""
    solid2 = _ev("solid2", UG, 2)
    skip8 = _ev("skip8", UG, 8)
    v = {A.event_key(solid2): {"tier": "solid"},
         A.event_key(skip8): {"tier": "skip"}}
    unjudged12 = _ev("n12", UG, 12)
    # judged solid score-2 > unjudged score-12 > judged skip score-8
    assert A.rank_key(solid2, v) > A.rank_key(unjudged12, v) > A.rank_key(skip8, v)
    # within the judged zone, tier is primary: a score-3 must-see beats a score-9 great
    ms3, gr9 = _ev("ms3", UG, 3), _ev("gr9", UG, 9)
    v2 = {A.event_key(ms3): {"tier": "must-see"}, A.event_key(gr9): {"tier": "great"}}
    assert A.rank_key(ms3, v2) > A.rank_key(gr9, v2)


def test_slate_elastic_no_lane_cap():
    """A stacked-afters night takes many afters — no firm per-lane number."""
    day = [_ev(f"a{i}", AFTERS, 6) for i in range(8)]
    picks = A.slate_fill(day, 5, A.DEFAULT_SLATE, {})
    assert len(picks) == 5 and all(A.event_lane(p) == "club:afters" for p in picks)


def test_slate_diversity_floor():
    """Even an afters-dominated night guarantees a taste of another lane if a decent one exists."""
    day = [_ev(f"a{i}", AFTERS, 7) for i in range(6)] + [_ev("film1", FILM, 4)]
    lanes = [A.event_lane(p) for p in A.slate_fill(day, 5, A.DEFAULT_SLATE, {})]
    assert "film" in lanes and lanes.count("club:afters") >= 1


def test_slate_gap_cuts_filler():
    """A score cliff ends the run early instead of padding to per_day."""
    day = [_ev("top", AFTERS, 12), _ev("a2", AFTERS, 11)] + [_ev(f"lo{i}", AFTERS, 4) for i in range(5)]
    picks = A.slate_fill(day, 10, {"gap": 3, "guarantee": [], "caps": {}}, {})
    assert len(picks) == 2          # 12, 11, then a 7-point drop to 4 cuts the rest


def test_assemble_mute_drops_lane():
    days = A.assemble([_ev("m", UG, 9, price="$80"), _ev("u", UG, 8)],
                      mute={"club:mainstream"}, per_day=5)
    lanes = [A.event_lane(p) for p in days[0]["picks"]]
    assert "club:mainstream" not in lanes and "club:underground" in lanes


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
