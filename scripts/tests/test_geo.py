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


def test_profile_travel_knobs_apply():
    fast = {"geo": {"travel": {"short_min_per_mile": 1.0, "park_buffer_min": 0, "drive_floor_min": 0}}}
    assert geo.drive_minutes(3, fast) < geo.drive_minutes(3, PROFILE)


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
