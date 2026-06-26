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


def test_scene_facts_projects_facts_only():
    """scene_facts is the taste-NEUTRAL projection fed into the per-profile editor: facts + artist
    bios in, curator_note/energy out (those carry the root profile's taste voice)."""
    ev = {"title": "Rooftop Groove", "date": "2026-07-04", "venue": "Level 8", "lineup": ["Antal"]}
    k = E.event_key(ev)
    cache = {"events": {k: {"id": k, "type": "electronic", "subgenres": ["disco"],
                            "label_orbit": ["Rush Hour"], "setting": "rooftop",
                            "sounds_like": ["Hunee"], "description": "Daytime rooftop party.",
                            "curator_note": "Build the day around it.", "energy": "groove"}},
             "artists": {"antal": {"note": "Rush Hour boss."}}}
    sf = E.scene_facts(ev, cache)
    assert sf["subgenres"] == ["disco"] and sf["setting"] == "rooftop"
    assert sf["sounds_like"] == ["Hunee"] and sf["description"] == "Daytime rooftop party."
    assert [n["name"] for n in sf["artist_notes"]] == ["Antal"]
    assert "curator_note" not in sf and "energy" not in sf          # the personalization invariant
    # cache miss -> {}; artist-only (un-researched event) still folds the compounding bio
    assert E.scene_facts({"title": "Z", "date": "2026-07-05", "venue": "Q"}, cache) == {}
    bare = E.scene_facts({"title": "Antal b2b", "date": "2026-07-06", "venue": "X", "lineup": ["Antal"]}, cache)
    assert [n["name"] for n in bare["artist_notes"]] == ["Antal"] and "description" not in bare


def test_update_cache_stamps_full_tier():
    cache = {"events": {}, "artists": {}}
    k = E.event_key(EV)
    E.update_cache(cache, [{"id": k, "description": "rooftop groove"}], now="2026-06-17")
    assert cache["events"][k]["enriched_tier"] == "full"


def test_blurb_writes_then_full_upgrades_it():
    """A blurb record is an upgrade candidate: select_for_enrichment re-selects it, and a full
    pass overwrites it with the whole record. The one-way street."""
    ev = {"title": "Mid Tier Show", "date": "2026-07-09", "venue": "Gold Diggers"}
    k = E.event_key(ev)
    cache = {"events": {}, "artists": {}}
    E.update_blurb_cache(cache, [{"id": k, "description": "A one-liner."}], now="2026-06-17")
    assert cache["events"][k]["enriched_tier"] == "blurb"
    # climbs into the head -> full enrichment re-selects it (a blurb hit is NOT a cache hit here)
    assert [s["id"] for s in E.select_for_enrichment([ev], cache)] == [k]
    E.update_cache(cache, [{"id": k, "curator_note": "worth it", "subgenres": ["house"]}], now="2026-06-18")
    assert cache["events"][k]["enriched_tier"] == "full"
    assert cache["events"][k]["curator_note"] == "worth it"
    assert E.select_for_enrichment([ev], cache) == []   # now write-once again


def test_blurb_never_downgrades_full():
    """update_blurb_cache must not clobber a full record (incl. legacy-full with no tier)."""
    ev = {"title": "Already Rich", "date": "2026-07-10", "venue": "Zebulon"}
    k = E.event_key(ev)
    cache = {"events": {k: {"id": k, "curator_note": "the good stuff"}}, "artists": {}}  # legacy-full
    E.update_blurb_cache(cache, [{"id": k, "description": "thin one-liner"}], now="2026-06-17")
    assert cache["events"][k].get("curator_note") == "the good stuff"   # untouched
    assert "description" not in cache["events"][k] or cache["events"][k].get("curator_note")


def test_select_for_blurb_skips_only_cached():
    miss = {"title": "Needs A Blurb", "date": "2026-07-11", "venue": "1642"}
    has_detail = {"title": "Has Detail", "date": "2026-07-12", "venue": "The Lash",
                  "detail": "A source description — still gets a clean LLM line for a uniform card."}
    cached = {"title": "Done", "date": "2026-07-13", "venue": "Sound"}
    cache = {"events": {E.event_key(cached): {"id": E.event_key(cached), "enriched_tier": "blurb"}},
             "artists": {}}
    picks = E.select_for_blurb([miss, has_detail, cached], cache)
    # detail no longer skips — only an existing cache record does
    assert [p["title"] for p in picks] == ["Needs A Blurb", "Has Detail"]
    assert {p["id"] for p in picks} == {E.event_key(miss), E.event_key(has_detail)}


def test_blurb_skips_results_without_description():
    cache = {"events": {}, "artists": {}}
    k = E.event_key(EV)
    E.update_blurb_cache(cache, [{"id": k}], now="2026-06-17")   # no description -> no-op
    assert k not in cache["events"]


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
