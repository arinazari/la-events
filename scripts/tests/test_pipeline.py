#!/usr/bin/env python3
"""Tests for scripts/lib/pipeline.py — the deterministic core transforms.

Run: python scripts/tests/test_pipeline.py   (also pytest-compatible)
Uses a fixed `today` for determinism (the sandbox clock is irrelevant).
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import pipeline as P  # noqa: E402

TODAY = date(2026, 6, 17)


def test_today_la_is_a_date():
    assert isinstance(P.today_la(), date)


def test_normalize_maps_common_shapes():
    raw = {"name": "Warehouse w/ Antal", "venue_name": "TBA",
           "datetime": "2026-06-20T22:30:00", "url": "https://ra.co/events/1",
           "artist": "Antal", "ra_pick": True}
    rec = P.normalize_record(raw, "ra")
    assert rec["title"] == "Warehouse w/ Antal"
    assert rec["venue"] == "TBA"
    assert rec["date"] == "2026-06-20"
    assert rec["start"] == "22:30"
    assert rec["lineup"] == ["Antal"]
    assert rec["links"] == [{"source": "ra", "url": "https://ra.co/events/1"}]
    assert rec["sources"] == ["ra"]
    assert rec["category"] == "electronic"   # SOURCE_CATEGORY default for ra
    assert rec["ra_pick"] is True


def test_normalize_reads_afterhours_flag():
    # Fetchers emit `afterhours_flag` (e.g. RA); normalize must carry it onto `afterhours`
    # so the scorer's warehouse/afterhours boost fires. (Regression: was dropped -> 0%.)
    assert P.normalize_record({"title": "W", "date": "2026-06-20", "afterhours_flag": True}, "ra")["afterhours"] is True
    assert P.normalize_record({"title": "W", "date": "2026-06-20", "afterhours": True}, "ra")["afterhours"] is True
    assert P.normalize_record({"title": "W", "date": "2026-06-20"}, "ra")["afterhours"] is False


def test_normalize_carries_genre_through():
    # Fetchers that classify (Ticketmaster: segment->category, genre->genre) emit a `genre`;
    # normalize must carry it onto the canonical schema so the dashboard's CATEGORY / GENRE
    # line has something to show. (Regression: was dropped -> the genre line was always blank.)
    rec = P.normalize_record({"title": "X", "date": "2026-06-20", "category": "Music", "genre": "Techno"}, "ticketmaster")
    assert rec["genre"] == "Techno"
    # No genre supplied -> key present but None, so the schema stays consistent across sources.
    assert P.normalize_record({"title": "Y", "date": "2026-06-20"}, "ra")["genre"] is None


def test_normalize_synthesizes_price_from_range():
    # Ticketmaster emits price_min/price_max, not a `price` string — synthesize one.
    P_ = P.normalize_record
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 25.0, "price_max": 75.0}, "ticketmaster")["price"] == "$25-75"
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 30, "price_max": 30}, "ticketmaster")["price"] == "$30"
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 0, "price_max": 0}, "ticketmaster")["price"] == "free"
    assert P_({"title": "X", "date": "2026-06-20", "price": "$10"}, "19hz")["price"] == "$10"  # explicit wins
    assert P_({"title": "X", "date": "2026-06-20"}, "dice")["price"] is None


def test_normalize_passes_through_canonical_links():
    raw = {"title": "X", "date": "2026-06-20", "venue": "Y",
           "links": [{"source": "dice", "url": "https://dice.fm/e/1"}], "category": "live_music"}
    rec = P.normalize_record(raw, "dice")
    assert rec["links"] == [{"source": "dice", "url": "https://dice.fm/e/1"}]
    assert rec["category"] == "live_music"


def test_merge_new_dedupes_and_stamps():
    catalog = [{"title": "Midnight Lovers w/ Bradley Zero", "venue": "The Bridge",
                "date": "2026-06-20", "lineup": ["Bradley Zero"],
                "links": [{"source": "ra", "url": "https://ra.co/e/1"}], "sources": ["ra"],
                "first_seen": "2026-06-10", "last_seen": "2026-06-10"}]
    incoming = [
        {"title": "Midnight Lovers Day Party", "venue": "The Bridge LA", "date": "2026-06-20",
         "lineup": ["Bradley Zero"], "links": [{"source": "dice", "url": "https://dice.fm/e/2"}],
         "sources": ["dice"]},                                  # dup of catalog[0]
        {"title": "Totally Different Show", "venue": "Zebulon", "date": "2026-06-21",
         "lineup": [], "links": [], "sources": ["dice"]},        # new
    ]
    merged, stats = P.merge_new(catalog, incoming, TODAY)
    assert len(merged) == 2, [e["title"] for e in merged]
    assert stats["added"] == 1 and stats["merged"] == 1
    dup = next(e for e in merged if "Midnight" in e["title"])
    assert {l["url"] for l in dup["links"]} == {"https://ra.co/e/1", "https://dice.fm/e/2"}
    assert dup["first_seen"] == "2026-06-10"          # survives
    assert dup["last_seen"] == "2026-06-17"           # advances to today
    new = next(e for e in merged if "Different" in e["title"])
    assert new["first_seen"] == "2026-06-17" and new["last_seen"] == "2026-06-17"


def test_expire_past_keeps_future_and_undated():
    cat = [
        {"title": "past", "date": "2026-06-10"},
        {"title": "today", "date": "2026-06-17"},
        {"title": "future", "date": "2026-06-25"},
        {"title": "tba", "date": None},
    ]
    kept, n = P.expire_past(cat, TODAY)
    titles = {e["title"] for e in kept}
    assert n == 1 and titles == {"today", "future", "tba"}


def test_select_candidates_orders_flags_and_windows():
    cat = [
        {"title": "elec", "category": "electronic", "venue": "A", "date": "2026-06-18"},  # +3
        {"title": "thtr", "category": "theater", "venue": "B", "date": "2026-06-19"},     # +2
        {"title": "past", "category": "electronic", "venue": "C", "date": "2026-06-10"},  # excluded
        {"title": "farout", "category": "electronic", "venue": "D", "date": "2026-09-01"},  # window-excluded
    ]
    cand = P.select_candidates(cat, taste={}, profile={}, today=TODAY,
                               window_days=30, top_n=10, image_n=1)
    titles = [c["title"] for c in cand]
    assert titles == ["elec", "thtr"]                 # upcoming, in-window, best-first
    assert cand[0]["image_wanted"] is True            # top image_n
    assert cand[1]["image_wanted"] is False
    assert all("score" in c and "rating" in c and "reasons" in c for c in cand)


def test_select_candidates_respects_top_n():
    cat = [{"title": f"e{i}", "category": "electronic", "venue": "V", "date": "2026-06-20"}
           for i in range(5)]
    cand = P.select_candidates(cat, {}, {}, today=TODAY, top_n=3)
    assert len(cand) == 3


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
