#!/usr/bin/env python3
"""Tests for scripts/_layer_merge.py — folding Step-2 layered rows into the catalog.

Run: python scripts/tests/test_layer_merge.py   (also pytest-compatible)
- raw rows normalize (url -> links, time -> start) but keep extras like editorial_mentions;
- a roundup mention of an event a structured source carries lands on that row WITHOUT adding an
  "editorial" source (the core never re-fetches it, so it would switch off ghost detection);
- an editorial-only match merges normally (its details + last_seen update);
- a venue-less roundup item is skipped, never title-matched onto some other event.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import _layer_merge as L  # noqa: E402
from lib import pipeline as P  # noqa: E402

TODAY = date(2026, 10, 19)
TM = {"title": "Riot Ten w/ Codd Dubz", "date": "2026-11-14", "venue": "Avalon Hollywood",
      "sources": ["ticketmaster"], "links": [{"source": "ticketmaster", "url": "https://tm.example/e/1"}],
      "first_seen": "2026-10-01", "last_seen": "2026-10-19"}
MARKET = {"title": "Highland Park Night Market", "date": "2026-10-25", "venue": "York Blvd",
          "sources": ["editorial"], "editorial_mentions": ["LAist"], "start": None,
          "first_seen": "2026-10-18", "last_seen": "2026-10-18"}


def test_normalize_keeps_extras_and_maps_url_time():
    [n] = L.normalize_rows([{"title": "New Act", "date": "2026-11-02", "time": "20:00", "venue": "McCabe's",
                             "url": "https://mccabes.example/x", "sources": ["webfetch"], "end": "22:00"}])
    assert n["sources"] == ["webfetch"] and n["start"] == "20:00" and n["end"] == "22:00"
    assert n["links"] == [{"source": "webfetch", "url": "https://mccabes.example/x"}]
    [e] = L.normalize_rows([{"title": "Rose Bowl Flea", "date": "2026-11-08", "venue": "Rose Bowl",
                             "source": "editorial", "editorial_mentions": ["Time Out"]}])
    assert e["sources"] == ["editorial"] and e["editorial_mentions"] == ["Time Out"]


def test_mention_folds_onto_structured_row_without_adding_a_source():
    cat = [dict(TM)]
    inc = L.normalize_rows([{"title": "Riot Ten w/ Codd Dubz", "date": "2026-11-14", "venue": "Avalon Hollywood",
                             "sources": ["editorial"], "editorial_mentions": ["Time Out Los Angeles"]}])
    rest, folded, unplaced = L.fold_mentions(cat, inc)
    assert (rest, folded, unplaced) == ([], 1, 0)
    assert cat[0]["sources"] == ["ticketmaster"] and cat[0]["editorial_mentions"] == ["Time Out Los Angeles"]


def test_editorial_only_match_merges_and_venueless_item_is_skipped():
    cat = [dict(MARKET)]
    inc = L.normalize_rows([
        {"title": "Highland Park Night Market", "date": "2026-10-25", "venue": "York Blvd", "start": "17:00",
         "sources": ["editorial"], "editorial_mentions": ["LAist"]},
        {"title": "Halloween Party", "date": "2026-10-31", "venue": "", "sources": ["editorial"],
         "editorial_mentions": ["LAist"]},
    ])
    rest, folded, unplaced = L.fold_mentions(cat, inc)
    assert folded == 0 and unplaced == 1 and len(rest) == 1
    merged, _ = P.merge_new(cat, rest, TODAY)
    assert len(merged) == 1 and merged[0]["start"] == "17:00" and merged[0]["last_seen"] == TODAY.isoformat()


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
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
