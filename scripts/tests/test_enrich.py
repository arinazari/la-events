#!/usr/bin/env python3
"""Tests for scripts/lib/enrich.py — the enrichment cache/merge plumbing.

Run: python scripts/tests/test_enrich.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import enrich as E  # noqa: E402

EV = {"title": "Sunset Sessions", "date": "2026-06-19", "venue": "Golden Hour at Level 8"}


def test_event_key_stable_and_distinct():
    k1 = E.event_key(EV)
    k2 = E.event_key(dict(EV))                       # same event -> same key
    k3 = E.event_key({**EV, "date": "2026-06-20"})   # different date -> different key
    assert k1 == k2 and len(k1) == 12
    assert k1 != k3
    # iso_date is accepted as a date fallback
    assert E.event_key({"title": "X", "venue": "Y", "iso_date": "2026-06-19"}) == \
           E.event_key({"title": "X", "venue": "Y", "date": "2026-06-19"})


def test_select_for_enrichment_finds_misses():
    cache = {"events": {E.event_key(EV): {"id": E.event_key(EV)}}, "artists": {}}
    other = {"title": "we own the night", "date": "2026-06-20", "venue": "TBA"}
    misses = E.select_for_enrichment([EV, other], cache)
    assert [m["title"] for m in misses] == ["we own the night"]   # EV already cached
    assert misses[0]["id"] == E.event_key(other)                  # carries the key


def test_merge_enrichment_attaches():
    k = E.event_key(EV)
    cache = {"events": {k: {"id": k, "curator_note": "the north star"}}, "artists": {}}
    [m] = E.merge_enrichment([EV], cache)
    assert m["id"] == k and m["enrichment"]["curator_note"] == "the north star"
    # cache miss -> no enrichment attached
    [m2] = E.merge_enrichment([{"title": "Z", "date": "2026-06-21", "venue": "Q"}], cache)
    assert "enrichment" not in m2


def test_update_cache_folds_events_and_artists():
    cache = {"events": {}, "artists": {}}
    k = E.event_key(EV)
    E.update_cache(cache, [{"id": k, "curator_note": "rooftop vinyl",
                            "artist_notes": [{"name": "Antal", "note": "Rush Hour boss"}]}], now="2026-06-17")
    assert cache["events"][k]["curator_note"] == "rooftop vinyl"
    assert cache["events"][k]["enriched_at"] == "2026-06-17"
    assert cache["artists"]["antal"]["note"] == "Rush Hour boss"   # keyed by normalized name


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
