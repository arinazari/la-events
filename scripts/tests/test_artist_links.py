#!/usr/bin/env python3
"""Tests for scripts/lib/artist_links.py — the direct ▶ listen link cache.

Run: python scripts/tests/test_artist_links.py   (also pytest-compatible)
Offline only: normalization (which must mirror the dashboard's _artistNorm),
candidate selection (theater lineups are show titles — never resolved), the
strict accept rule shape, and the feed fold. No network calls.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.artist_links import (  # noqa: E402
    norm_name, _fold, wanted_names, feed_map, load, save, refresh,
)


def test_norm_mirrors_dashboard_artistnorm():
    # lowercase, ONE trailing parenthetical stripped, whitespace collapsed — the JS twin.
    assert norm_name("EMBRZ (IE)") == "embrz"
    assert norm_name("  Mau  P ") == "mau p"
    assert norm_name("Rodney (2)") == "rodney"
    assert norm_name("Sam (a) (b)") == "sam (a)"       # one strip only, like the JS regex
    assert norm_name("Kornél Kovács") == "kornél kovács"  # diacritics KEPT in the key
    assert norm_name(None) == ""


def test_fold_is_comparison_only():
    assert _fold("kornél kovács") == "kornel kovacs"
    assert _fold(norm_name("RÜFÜS DU SOL")) == "rufus du sol"


def test_wanted_names_gates_on_music_categories():
    today = "2026-07-20"
    catalog = [
        {"category": "electronic", "date": "2026-07-25", "lineup": ["Mau P", "VTSS"]},
        {"category": "arts & theatre", "date": "2026-07-25",
         "lineup": ["The Phantom of the Opera (Touring)"]},        # show title — never resolved
        {"category": "electronic", "date": "2026-01-01", "lineup": ["Past Artist"]},
        {"category": "music", "date": "2026-08-01", "lineup": ["EMBRZ (IE)"]},
    ]
    enrichment = {"events": {"x": {"artist_notes": [{"name": "Stavroz", "note": "…"}]}},
                  "artists": {"cut chemist": {"note": "…"}}}
    w = wanted_names(catalog, enrichment, today)
    assert "mau p" in w and "vtss" in w
    assert "embrz" in w and w["embrz"] == "EMBRZ (IE)"
    assert "the phantom of the opera" not in w
    assert "past artist" not in w
    assert "stavroz" in w            # scene-graph artists always resolve
    assert "cut chemist" in w


def test_feed_map_covers_only_upcoming_feed_artists():
    cache = {
        "mau p": {"name": "Mau P", "spotify": "https://open.spotify.com/artist/AAA"},
        "stavroz": {"name": "Stavroz", "spotify": "https://open.spotify.com/artist/BBB"},
        "vtss": {"name": "VTSS", "spotify": None},                  # cached miss -> excluded
        "unrelated": {"name": "X", "spotify": "https://open.spotify.com/artist/CCC"},
    }
    events = [
        {"is_past": False, "lineup": ["Mau P", "VTSS"],
         "enrichment": {"artist_notes": [{"name": "Stavroz", "note": "…"}]}},
        {"is_past": True, "lineup": ["Unrelated"]},                 # past -> contributes nothing
    ]
    m = feed_map(cache, events)
    assert m == {"mau p": "https://open.spotify.com/artist/AAA",
                 "stavroz": "https://open.spotify.com/artist/BBB"}


def test_refresh_degrades_without_creds(monkeypatch=None):
    import os
    old_id, old_sec = os.environ.pop("SPOTIFY_CLIENT_ID", None), os.environ.pop("SPOTIFY_CLIENT_SECRET", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            note = refresh(Path(td), now=datetime(2026, 7, 20))
            assert note.startswith("SKIP:")
            assert not (Path(td) / "data" / "artist_links.json").exists()
    finally:
        if old_id:
            os.environ["SPOTIFY_CLIENT_ID"] = old_id
        if old_sec:
            os.environ["SPOTIFY_CLIENT_SECRET"] = old_sec


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data" / "artist_links.json"
        save(p, {"mau p": {"name": "Mau P", "spotify": None, "checked": "2026-07-20T00:00:00"}})
        c = load(p)
        assert c["mau p"]["spotify"] is None
        assert load(Path(td) / "missing.json") == {}
        (Path(td) / "bad.json").write_text("{not json")
        assert load(Path(td) / "bad.json") == {}


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
