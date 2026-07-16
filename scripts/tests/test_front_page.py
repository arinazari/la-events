#!/usr/bin/env python3
"""Tests for build_dashboard.build_front_page — the dashboard's editorial home block.

The block is selection-only on top of final_rank (stamped in main() from rank_key): hero keys
per time-lens (lane-capped for diversity), per-lane shelf key-lists split near/ahead so the
two-zone rank can't starve the plan-ahead lens, and radar/around key-joins.

Run: python scripts/tests/test_front_page.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_dashboard as B  # noqa: E402

TODAY = date(2026, 7, 15)  # a Wednesday -> weekend = Fri 7/17 .. Sun 7/19


def ev(key, iso, lane, rank, tier=None, series=None, rep=None, score=5):
    e = {"key": key, "iso_date": iso, "lane": lane, "score": score,
         "is_past": False, "title": key, "venue": "V", "date": iso}
    if rank is not None:
        e["final_rank"] = rank
    if tier:
        e["verdict"] = {"tier": tier}
    if series:
        e["series_key"] = series
        e["series_rep"] = bool(rep)
    return e


def test_orders_by_final_rank_skips_skips_and_series_members():
    evs = [
        ev("a", "2026-07-16", "club:underground", 3),
        ev("b", "2026-07-17", "club:underground", 1),
        ev("c", "2026-07-18", "club:underground", 2, tier="skip"),
        ev("d", "2026-07-18", "film", 4, series="s1", rep=True),
        ev("e", "2026-07-19", "film", None, series="s1", rep=False),
    ]
    fp = B.build_front_page(evs, {}, TODAY)
    ug = next(s for s in fp["shelves"] if s["id"] == "underground")
    assert ug["near"] == ["b", "a"]      # THE feed rank orders; judged skip excluded
    fl = next(s for s in fp["shelves"] if s["id"] == "film")
    assert fl["near"] == ["d"]           # a series enters via its rep night only


def test_shelves_split_near_vs_ahead():
    """One global-rank cut would starve plan-ahead (two-zone rank_key puts judged/near events
    structurally first) — the near/ahead split is the guarantee."""
    evs = ([ev(f"near{i}", "2026-07-20", "live-music", i + 1) for i in range(3)]
           + [ev("far1", "2026-08-20", "live-music", 50)])
    fp = B.build_front_page(evs, {}, TODAY)
    lv = next(s for s in fp["shelves"] if s["id"] == "live")
    assert lv["near"] == ["near0", "near1", "near2"]
    assert lv["ahead"] == ["far1"]


def test_hero_is_lane_capped_for_diversity():
    evs = [ev(f"club{i}", "2026-07-17", "club:underground", i + 1, tier="must-see")
           for i in range(5)]
    evs += [ev("film1", "2026-07-17", "film", 10, tier="great")]
    fp = B.build_front_page(evs, {}, TODAY)
    hero = fp["hero"]["twoweeks"]
    assert sum(1 for k in hero if k.startswith("club")) <= B.FP_HERO_LANE_CAP
    assert "film1" in hero               # diversity: the film outlives lower-ranked club picks


def test_windows_shape_and_radar_join():
    w = B._fp_windows(TODAY)
    assert w["today"] == ("2026-07-15", "2026-07-15")
    assert w["weekend"] == ("2026-07-17", "2026-07-19")
    assert w["twoweeks"] == ("2026-07-15", "2026-07-28")
    evs = [ev("a", "2026-08-20", "club:underground", 1)]
    fp = B.build_front_page(evs, {}, TODAY,
                            radar_rows=[{"key": "a"}, {"key": "ghost"}])
    assert fp["radar"] == ["a"]          # joins only keys present in the feed


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
