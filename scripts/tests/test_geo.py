#!/usr/bin/env python3
"""Tests for scripts/lib/geo.py — the night-planner travel engine.

Run: python scripts/tests/test_geo.py   (also pytest-compatible)
Covers place resolution (neighborhood / venue / home / coords), the walk-vs-drive
call, monotonic drive times, route totals, and that profile.yaml overrides apply.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.config import load_profile  # noqa: E402
from lib import geo  # noqa: E402

PROFILE = load_profile()


def test_resolve_neighborhood_and_home():
    assert geo.resolve("Silver Lake", PROFILE) is not None
    assert geo.resolve("silverlake", PROFILE) == geo.resolve("Silver Lake", PROFILE)
    assert geo.resolve("home", PROFILE) is not None
    assert geo.resolve("Atlantis", PROFILE) is None


def test_resolve_venue_via_neighborhood():
    # A known venue resolves to its neighborhood's centroid.
    assert geo.resolve("Zebulon", PROFILE) == geo.resolve("Frogtown", PROFILE)
    assert geo.resolve("The Echo", PROFILE) == geo.resolve("Echo Park", PROFILE)
    # Suffix tolerance: "Vista Theatre" still places in Los Feliz.
    assert geo.resolve("Vista Theatre", PROFILE) == geo.resolve("Los Feliz", PROFILE)


def test_resolve_coords_passthrough():
    assert geo.resolve((34.0, -118.0)) == (34.0, -118.0)


def test_walk_vs_drive():
    # Within Silver Lake → walk; Silver Lake → DTLA → drive.
    near = geo.hop("Silver Lake", "Silver Lake", PROFILE)
    assert near["mode"] == "walk" and near["minutes"] == 0
    far = geo.hop("Silver Lake", "DTLA", PROFILE)
    assert far["mode"] == "drive" and far["minutes"] >= 8


def test_drive_time_monotonic_and_floored():
    short = geo.drive_minutes(1, PROFILE)
    mid = geo.drive_minutes(5, PROFILE)
    long = geo.drive_minutes(15, PROFILE)
    assert short <= mid <= long
    assert short >= 8  # the floor


def test_unknown_place_is_graceful():
    leg = geo.hop("Silver Lake", "Narnia", PROFILE)
    assert leg["mode"] == "unknown" and leg["minutes"] is None
    assert "Narnia" in leg["note"]


def test_plan_route_totals():
    route = geo.plan_route(["home", "Bar Franca", "Zebulon", "home"], PROFILE)
    assert len(route["legs"]) == 3
    assert route["total_minutes"] > 0
    assert route["unplaced"] == []


def test_profile_overrides_gazetteer():
    """A profile.yaml geo block must override the code defaults."""
    custom = {"geo": {"neighborhoods": {"Testville": [34.05, -118.25]},
                      "venues": {"Test Club": "Testville"}}}
    assert geo.resolve("Test Club", custom) == (34.05, -118.25)
    # And the default LA gazetteer is replaced, not merged, when overridden.
    assert geo.resolve("Silver Lake", custom) is None


def test_venue_resolves_through_messy_neighborhood():
    """A venue/restaurant whose neighborhood string carries wrapper text still places
    (this is how travel.py resolves dining records like 'Echo Park / Silver Lake')."""
    custom = {"geo": {"neighborhoods": {"Highland Park": [34.11, -118.19]},
                      "venues": {"Jeffs Table": "Highland Park (NELA)"}}}
    assert geo.resolve("Jeffs Table", custom) == (34.11, -118.19)


def test_profile_travel_knobs_apply():
    fast = {"geo": {"travel": {"short_min_per_mile": 1.0, "park_buffer_min": 0, "drive_floor_min": 0}}}
    assert geo.drive_minutes(3, fast) < geo.drive_minutes(3, PROFILE)


# ── Location canonicalization (the "location column" polish) ──────────────────────

def test_display_neighborhood_acronyms_aliases_and_case():
    assert geo.display_neighborhood("dtla") == "DTLA"
    assert geo.display_neighborhood("downtown la") == "DTLA"      # alias consolidates
    assert geo.display_neighborhood("weho") == "West Hollywood"
    assert geo.display_neighborhood("mid-city") == "Mid-City"     # _norm drops the hyphen
    assert geo.display_neighborhood("east hollywood") == "East Hollywood"
    assert geo.display_neighborhood("HOLLYWOOD") == "Hollywood"   # repairs ALL-CAPS
    assert geo.display_neighborhood("") is None


def test_canonical_location_keeps_real_neighborhood():
    # A specific neighborhood already on the record is preserved (just display-fixed) —
    # never downgraded to a city bucket, even for far-flung cities.
    assert geo.canonical_location("Vidiots", "Eagle Rock", PROFILE) == "Eagle Rock"
    assert geo.canonical_location("Yaamava", "Highland", PROFILE) == "Highland"
    assert geo.canonical_location("House of Blues", "Anaheim", PROFILE) == "Anaheim"


def test_canonical_location_upgrades_city_level_via_venue():
    # The core fix: TM/JSON-LD city-level "Los Angeles" -> the venue's real neighborhood.
    assert geo.canonical_location("The Fonda Theatre", "Los Angeles", PROFILE) == "Hollywood"
    assert geo.canonical_location("The Echo", "Los Angeles", PROFILE) == "Echo Park"
    assert geo.canonical_location("Hollywood Pantages Theatre", "Los Angeles", PROFILE) == "Hollywood"


def test_canonical_location_upgrades_blank_via_venue():
    # Posh-style blank neighborhood, known venue -> resolved.
    assert geo.canonical_location("The Redwood Bar and Grill", None, PROFILE) == "DTLA"
    assert geo.canonical_location("129 E 3rd St", "", PROFILE) == "DTLA"


def test_canonical_location_non_la_city_from_parenthetical():
    # 19hz crams the city into the venue string; surface it instead of mislabeling LA.
    assert geo.canonical_location("Eq (San Diego) drum and bass", None, PROFILE) == "San Diego"
    assert geo.canonical_location("Sid The Cat (Pasadena/Los Angeles) indie", None, PROFILE) == "Pasadena"
    # A junk parenthetical is NOT mistaken for a place (allowlist guard).
    assert geo.canonical_location("Some Club (21+) techno", None, PROFILE) is None


def test_canonical_location_neighborhood_embedded_in_venue():
    # Many TBA/warehouse rows carry the neighborhood in the venue string itself.
    assert geo.canonical_location("TBA - DTLA Warehouse", "Los Angeles", PROFILE) == "DTLA"
    assert geo.canonical_location("TBA - Downtown LA", None, PROFILE) == "DTLA"
    assert geo.canonical_location("Pacific Electric", "Los Angeles", PROFILE) == "DTLA"
    # The single-word-hood token guard: a hood name embedded mid-word must NOT match.
    assert geo.canonical_location("Veniceland Arcade", "Los Angeles", PROFILE) == "Los Angeles"


def test_canonical_location_collapses_or_keeps_blank():
    # Unplaceable city-level collapses to ONE label; a true blank stays blank (the view
    # owns that fallback) — so we never invent a neighborhood we don't know.
    assert geo.canonical_location("Some Unknown Venue", "Los Angeles", PROFILE) == "Los Angeles"
    assert geo.canonical_location("TBA", None, PROFILE) is None


def test_canonical_location_is_idempotent():
    once = geo.canonical_location("The Wiltern", "Los Angeles", PROFILE)
    twice = geo.canonical_location("The Wiltern", once, PROFILE)
    assert once == twice == "Koreatown"


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
