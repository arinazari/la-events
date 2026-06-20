#!/usr/bin/env python3
"""Tests for scripts/lib/enrich.py — the enrichment cache/merge plumbing.

Run: python scripts/tests/test_enrich.py
"""

import sys
from datetime import date
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


def test_merge_folds_cached_artist_notes_on_uncached_event():
    """The coverage win: an event with no event-cache entry still gets artist glosses
    for any lineup name the artist cache knows (free, compounding scene-graph reuse)."""
    cache = {"events": {}, "artists": {"peggy gou": {"note": "Korean-Berlin house, Gudu boss"}}}
    ev = {"title": "Club Night", "date": "2026-07-04", "venue": "Sound", "lineup": ["Peggy Gou", "Local Opener"]}
    [m] = E.merge_enrichment([ev], cache)
    assert m["enrichment"]["from_cache"] is True
    assert m["enrichment"]["artist_notes"] == [{"name": "Peggy Gou", "note": "Korean-Berlin house, Gudu boss"}]


def test_merge_supplements_event_hit_with_cache_artists():
    """A researched event keeps its record but gains cache notes for lineup names it missed."""
    ev = {"title": "B2B Night", "date": "2026-07-05", "venue": "The Lash", "lineup": ["Antal", "Hunee"]}
    k = E.event_key(ev)
    cache = {"events": {k: {"id": k, "artist_notes": [{"name": "Antal", "note": "Rush Hour boss"}]}},
             "artists": {"hunee": {"note": "Rush Hour digger, joyful selector"}}}
    [m] = E.merge_enrichment([ev], cache)
    names = [n["name"] for n in m["enrichment"]["artist_notes"]]
    assert "Antal" in names and "Hunee" in names   # original + supplemented, no dupes
    assert len(names) == 2


def test_cached_artist_notes_no_false_match():
    cache = {"events": {}, "artists": {"ame": {"note": "Innervisions"}}}  # short name
    ev = {"title": "Some Game Night", "date": "2026-07-06", "venue": "X", "lineup": ["DJ Someone"]}
    assert E.cached_artist_notes(ev, cache) == []   # 'ame' must not match 'game'/'someone'


def test_prune_cache_drops_orphans_keeps_artists():
    """Hygiene: event entries for events gone from the catalog are dropped; artist bios stay."""
    live = {"title": "Live Show", "date": "2026-07-07", "venue": "Zebulon"}
    gone = {"title": "Old Show", "date": "2026-05-01", "venue": "El Rey"}
    cache = {"events": {E.event_key(live): {"id": "x"}, E.event_key(gone): {"id": "y"}},
             "artists": {"antal": {"note": "Rush Hour boss"}}}
    cache, pruned = E.prune_cache(cache, [live])   # only `live` is in the catalog now
    assert pruned == 1
    assert E.event_key(live) in cache["events"] and E.event_key(gone) not in cache["events"]
    assert cache["artists"]["antal"]["note"] == "Rush Hour boss"   # durable, kept


def test_select_refresh_days_reselects_stale():
    ev = {"title": "Recur", "date": "2026-07-08", "venue": "El Cid"}
    k = E.event_key(ev)
    cache = {"events": {k: {"id": k, "enriched_at": "2026-06-01T00:00:00"}}, "artists": {}}
    today = date(2026, 6, 19)
    assert E.select_for_enrichment([ev], cache) == []                       # write-once: skip
    assert E.select_for_enrichment([ev], cache, refresh_days=90, today=today) == []   # 18d < 90
    stale = E.select_for_enrichment([ev], cache, refresh_days=7, today=today)         # 18d >= 7
    assert [s["id"] for s in stale] == [k]


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
