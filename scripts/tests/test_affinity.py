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
                          normalize_name, tracked_hits, ambiguous_set)
from lib.config import load_taste, load_profile  # noqa: E402
from lib.scoring import score_event  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
SAMPLE = json.loads((REPO / "data" / "sample-spotify-affinity.json").read_text())
TASTE, PROFILE = load_taste(), load_profile()

# Fixed weights for the point-exact unit tests, so tuning profile.yaml's scoring.spotify
# (a knob) never breaks them. Integration tests below use the live PROFILE on purpose.
TP = {"scoring": {"spotify": {
    "tier_points": {"core": 2, "strong": 1, "light": 1, "hidden": -3},
    "artist_cap": 4, "genre_points": 1, "genre_threshold": 0.5, "genre_cap": 1,
    "min_name_len": 3, "ambiguous_names": ["train"]}}}


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
    pts, reasons = artist_affinity(name_text, "", SAMPLE, TP)
    # Two core artists = +2 +2 = 4, exactly at artist_cap (4) under the fixed test weights.
    assert pts == 4, (pts, reasons)
    assert any("Antal" in r for r in reasons)


def test_artist_affinity_respects_min_name_len():
    aff = {"artists": {"dj": {"name": "DJ", "tier": "core"}}}   # 2 chars < min_name_len(3)
    pts, _ = artist_affinity("a dj plays tonight", "", aff, TP)
    assert pts == 0


def test_ambiguous_name_requires_lineup():
    """Common-word band names (Train, Future, …) only count in the structured lineup."""
    aff = {"artists": {"train": {"name": "Train", "tier": "strong", "sources": ["followed"]}}}
    assert artist_affinity("train to tehran w/ namito", "", aff, TP)[0] == 0   # party title, no lineup
    assert artist_affinity("train to tehran", "train", aff, TP)[0] == 1        # billed (strong=1 in TP)


def test_whole_token_match_not_substring():
    aff = {"artists": {"hanson": {"name": "Hanson", "tier": "light", "sources": ["top_short"]}}}
    assert artist_affinity("paris chansons", "", aff, TP)[0] == 0   # 'hanson' inside 'chansons'
    assert artist_affinity("hanson live", "", aff, TP)[0] == 1


def test_hidden_tier_downranks():
    aff = {"artists": {"someone": {"name": "Someone", "tier": "hidden"}}}
    pts, reasons = artist_affinity("someone live tonight", "", aff, TP)
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


def test_tracked_hits_lineup_first_and_ambiguous_gate():
    """Track B3: ambiguous word-like names need an EXACT lineup entry; token presence in a title
    (or inside a longer act name) must not fire. Normal names keep whole-token title+lineup match."""
    amb = {"fisher", "drama"}
    # the audit's live false positive: FISHER badged 'Fisher and Thames' (a jazz duo)
    assert tracked_hits(["FISHER"], "Fisher and Thames - Sounds Of the 70s", [], amb) == set()
    assert tracked_hits(["FISHER"], "Sounds Of the 70s", ["Fisher and Thames"], amb) == set()
    # FISHER actually billed -> exact lineup entry matches
    assert tracked_hits(["FISHER"], "HARD Summer", ["FISHER", "Chris Lake"], amb) == {"FISHER"}
    # normal names: whole-token in title or lineup text, no substring bleed
    assert tracked_hits(["Antal"], "Antal all night long", [], amb) == {"Antal"}
    assert tracked_hits(["Ame"], "Amelie Lens at Grand Park", [], amb, min_len=2) == set()
    # composite billings split on b2b/vs (but never on 'and' — band names keep it)
    assert tracked_hits(["FISHER"], "HARD", ["FISHER b2b Chris Lake"], amb) == {"FISHER"}
    assert tracked_hits(["FISHER"], "HARD", ["Fisher and Thames b2b Someone"], amb) == set()
    # None lineup is an empty lineup, not the string 'None'
    assert tracked_hits(["None"], "no lineup here", None, amb, min_len=2) == set()


def test_ambiguous_set_resolves_profile_then_taste_then_default():
    prof = {"scoring": {"spotify": {"ambiguous_names": ["FISHER", " Drama "]}}}
    assert ambiguous_set(prof) == {"fisher", "drama"}
    taste = {"scoring": {"spotify": {"ambiguous_names": ["Train"]}}}
    assert ambiguous_set({}, taste) == {"train"}
    # no profile/taste list -> the baseline default (friend profiles without a profile.yaml
    # must still get the gate, not an empty set)
    base = ambiguous_set({})
    assert "fisher" in base and "drama" in base and "future" in base


# ── 2026-08 shadow-eval additions: accent folding + the historical Ame phantom class ──

def test_tracked_accent_fold_both_directions():
    # taste says ascii "Ame", the bill says "\u00c2me" — and the reverse. Both must hit.
    assert tracked_hits(["Ame"], "\u00c2me at Sound Nightclub", []) == {"Ame"}
    assert tracked_hits(["\u00c2me"], "AME all night long", ["AME"]) == {"\u00c2me"}


def test_tracked_ame_phantom_collisions_stay_dead():
    # June 2026: substring matching credited "Ame" on all of these (31 phantom verdicts).
    # The whole-token matcher must keep every one dead, accent folding must not revive them.
    for title in ("Chinese American Bear", "An American in Paris",
                  "The Americana at Brand block party", "Americana night at Pappy's",
                  "Wyatt Cote live at Pechanga"):
        assert tracked_hits(["Ame"], title, []) == set(), title


def test_artist_affinity_accent_folded_artifact_key():
    # Artifact keys are normalize_name output, but a pre-fix artifact may carry accented
    # keys ("\u00e2me") — matching must fold the stored key at use, not trust it.
    aff = {"artists": {"\u00e2me": {"name": "\u00c2me", "tier": "core", "weight": 4.0,
                                     "sources": ["followed"]}}}
    pts, reasons = artist_affinity("ame b2b dixon at sound", "ame b2b dixon", aff)
    assert pts > 0 and any("\u00c2me" in r for r in reasons)


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
