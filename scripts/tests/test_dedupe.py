#!/usr/bin/env python3
"""Tests for scripts/lib/dedupe.py — the known-duplicate set.

Run: python scripts/tests/test_dedupe.py   (also pytest-compatible)
Anchored on real catalog shapes: links are {source,url} dicts; same venue+date is
NOT enough to merge (distinct events share a room on a night).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.dedupe import is_duplicate, merge, dedupe, normalize, _venue_key  # noqa: E402

# Same real event across three sources (RA / DICE / TM), venue + title variants.
RA = {"title": "Midnight Lovers Day Party w/ Bradley Zero", "venue": "The Bridge",
      "date": "2026-06-20", "lineup": ["Bradley Zero", "Masha Mar"],
      "links": [{"source": "ra", "url": "https://ra.co/events/2415278"}],
      "sources": ["ra"], "ra_pick": True, "detail": "All-afternoon groove."}
DICE = {"title": "Midnight Lovers Day Party", "venue": "The Bridge LA",
        "date": "2026-06-20", "lineup": ["Bradley Zero"],
        "links": [{"source": "dice", "url": "https://dice.fm/event/abc"}],
        "sources": ["dice"], "detail": "Day party."}
TM = {"title": "Midnight Lovers w/ Bradley Zero", "venue": "Bridge",
      "date": "2026-06-20", "lineup": [],
      "links": [{"source": "tm", "url": "https://ticketmaster.com/xyz"}],
      "sources": ["ticketmaster"]}


def test_same_event_across_sources_is_duplicate():
    assert is_duplicate(RA, DICE)
    assert is_duplicate(RA, TM)
    assert is_duplicate(DICE, TM)


def test_distinct_events_same_venue_date_not_duplicate():
    # Three different World Cup parties at one bar the same night (real pattern).
    a = {"title": "FRA VS SEN", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    b = {"title": "ARG VS BRA", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    assert not is_duplicate(a, b)


def test_venue_normalization():
    assert _venue_key("The Echo") == _venue_key("Echo")
    assert normalize("Zebulon & Friends, L.A.") == "zebulon and friends l a"
    a = {"title": "ZEP No Enemies Tour", "venue": "The Echo", "date": "2026-06-19"}
    b = {"title": "ZEP (No Enemies Tour)", "venue": "Echo", "date": "2026-06-19"}
    assert is_duplicate(a, b)


def test_different_dates_not_duplicate():
    a = {"title": "Same Show", "venue": "Zebulon", "date": "2026-06-19", "lineup": []}
    b = {"title": "Same Show", "venue": "Zebulon", "date": "2026-06-26", "lineup": []}
    assert not is_duplicate(a, b)


def test_missing_date_is_conservative():
    a = {"title": "Mystery Warehouse", "venue": "TBA", "lineup": []}
    b = {"title": "Mystery Warehouse", "venue": "TBA", "lineup": []}
    assert not is_duplicate(a, b)  # no date -> don't merge


def test_merge_keeps_all_links_and_richest_fields():
    m = merge(merge(RA, DICE), TM)
    urls = {l["url"] for l in m["links"]}
    assert len(urls) == 3, urls                       # all three ticket links kept
    assert set(m["sources"]) == {"ra", "dice", "ticketmaster"}
    assert m["ra_pick"] is True                        # OR across records
    assert m["detail"] == "All-afternoon groove."      # richest (longest) description
    assert len(m["lineup"]) == 2                        # richest lineup


def test_merge_preserves_genre_from_either_record():
    # Genre is sparse (only some sources classify), so a merge must not lose it when the
    # base record lacks one — otherwise backfilling an existing genre-less catalog row from
    # a fresh TM fetch silently drops the genre. (Regression: dashboard genre line went blank.)
    base = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": []}
    tm = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": [], "genre": "Indie"}
    assert merge(base, tm)["genre"] == "Indie"     # backfilled from the incoming record
    assert merge(tm, base)["genre"] == "Indie"     # kept when the base already carries it


def test_dedupe_collapses_cluster():
    merged, report = dedupe([RA, DICE, TM])
    assert len(merged) == 1, [e["title"] for e in merged]
    assert len(report) == 2  # two absorbs into the kept record


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
