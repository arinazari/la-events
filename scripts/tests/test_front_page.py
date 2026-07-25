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
    cu = next(s for s in fp["shelves"] if s["id"] == "culture")
    assert cu["near"] == ["d"]           # a series enters via its rep night only


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
    """The hero runs the shared top-picks policy over the REAL verdicts map (the production
    path in main()): tier-primary rank, then the lane cap displaces lower clubs for the film."""
    evs = [ev(f"club{i}", "2026-07-17", "club:underground", i + 1, tier="must-see",
              score=9 - i) for i in range(5)]
    evs += [ev("film1", "2026-07-17", "film", 10, tier="great", score=3)]
    vmap = {B.event_key(e): e["verdict"] for e in evs}
    fp = B.build_front_page(evs, vmap, TODAY)
    hero = fp["hero"]["twoweeks"]
    assert sum(1 for k in hero if k.startswith("club")) <= B.TOP_PICKS_LANE_CAP
    assert hero[:2] == ["club0", "club1"]  # tier-primary rank order, best clubs first
    assert "film1" in hero               # diversity: the film outlives lower-ranked club picks


def test_long_runs_move_to_nowrunning_and_leave_dated_surfaces():
    """A series rep whose remaining span >= FP_RUN_MIN_DAYS holds the fixed Now-running
    shelf instead of squatting a lane shelf (or the hero) for weeks; a short run stays."""
    run = ev("run", "2026-07-16", "stage", 1, tier="must-see", series="s1", rep=True)
    run["series"] = {"count": 20, "first": "2026-07-16", "last": "2026-08-30"}
    short = ev("short", "2026-07-17", "film", 2, series="s2", rep=True)
    short["series"] = {"count": 3, "first": "2026-07-17", "last": "2026-07-19"}
    fp = B.build_front_page([run, short], {}, TODAY)
    assert fp["nowrunning"] == ["run"]
    cu = next(s for s in fp["shelves"] if s["id"] == "culture")
    assert "run" not in cu["near"] and "short" in cu["near"]
    assert "run" not in fp["hero"]["twoweeks"]


def test_two_bookings_weeks_apart_are_not_a_run():
    """Span alone can't make a run — a party booked twice three weeks apart is two dated
    picks (FP_RUN_MIN_NIGHTS), not a season."""
    two = ev("two", "2026-07-17", "club:afters", 1, series="s1", rep=True)
    two["series"] = {"count": 2, "first": "2026-07-17", "last": "2026-08-08"}
    fp = B.build_front_page([two], {}, TODAY)
    assert fp["nowrunning"] == []
    af = next(s for s in fp["shelves"] if s["id"] == "afters")
    assert af["near"] == ["two"]


def test_closing_window_reenters_lane_shelf():
    """Remaining span under the threshold (the summary spans upcoming nights only) puts a
    run back on its lane shelf — 'closes Sunday' is dated news again."""
    closing = ev("closing", "2026-07-16", "stage", 1, series="s1", rep=True)
    closing["series"] = {"count": 5, "first": "2026-07-16", "last": "2026-07-20"}
    fp = B.build_front_page([closing], {}, TODAY)
    assert fp["nowrunning"] == []
    cu = next(s for s in fp["shelves"] if s["id"] == "culture")
    assert cu["near"] == ["closing"]


def test_culture_shelf_interleaves_lanes():
    """The merged shelf round-robins film/comedy/stage so the high-volume lane can't
    monopolize every prefix (the client windows+slices, so only prefix-mixing survives)."""
    evs = [ev(f"f{i}", "2026-07-16", "film", i + 1) for i in range(6)]
    evs += [ev("c1", "2026-07-17", "comedy", 20), ev("st1", "2026-07-18", "stage", 30)]
    fp = B.build_front_page(evs, {}, TODAY)
    cu = next(s for s in fp["shelves"] if s["id"] == "culture")
    assert set(cu["near"][:3]) == {"f0", "c1", "st1"}   # one per lane leads the list
    assert cu["near"][3:] == ["f1", "f2", "f3", "f4", "f5"]


def test_take_lifted_from_slot_with_doc_date():
    """The Take rides the feed structurally as {text, date}: the one-sentence teaser inside the
    invisible `<!-- take: … -->` comment slot, plus the doc's own date (so the chat welcome can
    honestly show WHICH day's read it is). An unfilled slot or a free-form (slot-less) doc
    yields None so the page falls back to its clipped lede heuristic."""
    filled = ("# LA Events — 2026-07-15\n*meta*\n\n"
              "<!-- take: Deep-house weekend — the pier goes off Saturday. -->\n"
              "The 2-4 sentence intro paragraph.\n\n## Don't miss\n")
    assert B.digest_take(filled) == {"text": "Deep-house weekend — the pier goes off Saturday.",
                                     "date": "2026-07-15"}
    assert B.digest_take("<!-- take: -->\n<!-- tier3:intro -->\n") is None   # unfilled scaffold
    assert B.digest_take("# Free-form profile digest\n\nJust prose.\n") is None
    assert B.digest_take("") is None
    # a multi-line teaser normalizes to one line; a doc with no dated H1 still yields the text
    assert B.digest_take("<!-- take: two\n   lines -->")["text"] == "two lines"
    assert B.digest_take("<!-- take: x -->")["date"] is None
    # the retired start/end markers never read as a take
    assert B.digest_take("<!-- take:start -->\nprose\n<!-- take:end -->\n") is None
    # an UNCLOSED take comment (LLM fill dropped its -->) must not swallow the next comment
    assert B.digest_take("<!-- take: forgot to close\n<!-- tier3:intro -->\n") is None
    fp = B.build_front_page([], {}, TODAY, take={"text": "the take", "date": "2026-07-15"})
    assert fp["take"] == {"text": "the take", "date": "2026-07-15"}
    assert B.build_front_page([], {}, TODAY)["take"] is None


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
