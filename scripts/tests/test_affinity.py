#!/usr/bin/env python3
"""Tests for scripts/lib/affinity.py — the Spotify/feedback music layer (Phase C).

Run: python scripts/tests/test_affinity.py   (also pytest-compatible)
Covers (a) build_affinity folding raw payloads into the artifact, (b) the scoring-side
readers turning the artifact into capped points, and (c) the scorer staying byte-identical
when no affinity is passed (the music layer only ever enriches).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.affinity import (build_affinity, artist_affinity, genre_affinity,  # noqa: E402
                          normalize_name)
from lib.config import load_taste, load_profile  # noqa: E402
from lib.scoring import score_event  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
SAMPLE = json.loads((REPO / "data" / "sample-spotify-affinity.json").read_text())
TASTE, PROFILE = load_taste(), load_profile()


def test_build_affinity_weights_and_tiers():
    top = {
        "long_term": [{"name": "Antal", "genres": ["deep house", "disco"]},
                      {"name": "Palms Trax", "genres": ["house"]}],
        "medium_term": [{"name": "Peggy Gou", "genres": ["house"]}],
        "short_term": [{"name": "KAYTRANADA", "genres": ["r&b"]}],
    }
    followed = [{"name": "Antal", "genres": ["deep house"]}]      # Antal also followed => stacks
    recent = [{"track": {"artists": [{"name": "Moodymann"}]}}] * 5  # capped at RECENT_PLAY_CAP
    aff = build_affinity(top, followed, recent)

    # Antal: long_term rank0 (3.0*1.0) + followed (2.0) = 5.0 -> core
    antal = aff["artists"]["antal"]
    assert antal["tier"] == "core", antal
    assert antal["weight"] >= 4.0
    assert set(antal["sources"]) == {"top_long", "followed"}
    # Recent plays are capped so one artist can't dominate via repeats.
    assert aff["artists"]["moodymann"]["weight"] <= 3.0 * 1.0 + 0.01
    # Genres are present and max-normalized to 1.0 at the top.
    assert abs(max(aff["genres"].values()) - 1.0) < 1e-9
    # Keys are normalized (lowercased).
    assert "antal" in aff["artists"] and "Antal" not in aff["artists"]


def test_build_affinity_drops_below_light():
    # A single short_term tail entry (1.5 * 0.4 = 0.6) is below the `light` threshold (0.8) -> dropped.
    top = {"short_term": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}, {"name": "E"}]}
    aff = build_affinity(top)
    assert all(info["weight"] >= 0.8 for info in aff["artists"].values()), aff["artists"]


def test_artist_affinity_points_and_cap():
    name_text = "palms trax b2b antal at zebulon"
    pts, reasons = artist_affinity(name_text, "", SAMPLE, PROFILE)
    # Two core artists = +2 +2 = 4, exactly at artist_cap (4).
    assert pts == 4, (pts, reasons)
    assert any("Antal" in r for r in reasons)


def test_artist_affinity_respects_min_name_len():
    aff = {"artists": {"dj": {"name": "DJ", "tier": "core"}}}   # 2 chars < min_name_len(3)
    pts, _ = artist_affinity("a dj plays tonight", "", aff, PROFILE)
    assert pts == 0


def test_ambiguous_name_requires_lineup():
    """Common-word band names (Train, Future, …) only count in the structured lineup."""
    aff = {"artists": {"train": {"name": "Train", "tier": "strong", "sources": ["followed"]}}}
    assert artist_affinity("train to tehran w/ namito", "", aff, PROFILE)[0] == 0   # party title, no lineup
    assert artist_affinity("train to tehran", "train", aff, PROFILE)[0] == 1        # actually billed


def test_whole_token_match_not_substring():
    aff = {"artists": {"hanson": {"name": "Hanson", "tier": "light", "sources": ["top_short"]}}}
    assert artist_affinity("paris chansons", "", aff, PROFILE)[0] == 0   # 'hanson' inside 'chansons'
    assert artist_affinity("hanson live", "", aff, PROFILE)[0] == 1


def test_hidden_tier_downranks():
    aff = {"artists": {"someone": {"name": "Someone", "tier": "hidden"}}}
    pts, reasons = artist_affinity("someone live tonight", "", aff, PROFILE)
    assert pts == -3, (pts, reasons)
    assert any("hidden" in r for r in reasons)


def test_genre_affinity_conservative():
    pts, reasons = genre_affinity("a deep house all-nighter", SAMPLE, PROFILE)
    assert pts == 1 and any("deep house" in r for r in reasons)
    # Below-threshold genre doesn't fire.
    assert genre_affinity("an electronica set", SAMPLE, PROFILE)[0] == 0


def test_affinity_enriches_but_never_replaces():
    """Same event scored with and without affinity: affinity only adds, taste.yaml unchanged."""
    ev = {"title": "Antal all night long", "category": "electronic",
          "venue": "Zebulon", "date": "2026-06-20", "lineup": ["Antal"]}
    base = score_event(ev, TASTE, PROFILE)
    enriched = score_event(ev, TASTE, PROFILE, SAMPLE)
    assert enriched["score"] > base["score"]
    # Every base reason is still present (nothing overwritten) — affinity only appends.
    assert base["reasons"] == enriched["reasons"][:len(base["reasons"])]
    assert any("Spotify" in r for r in enriched["reasons"])


def test_no_affinity_is_byte_identical():
    ev = {"title": "Some DJ", "category": "electronic", "venue": "X", "date": "2026-06-15"}
    assert score_event(ev, TASTE, PROFILE) == score_event(ev, TASTE, PROFILE, None)


def test_normalize_name():
    assert normalize_name("  Floating   Points ") == "floating points"
    assert normalize_name("&ME") == "&me"


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
