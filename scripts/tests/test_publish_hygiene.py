#!/usr/bin/env python3
"""Tests for the published-data hygiene layer (Track A3): feeds ship neighborhood-level
location only — coords rounded to ~2 decimals, cross-streets never published.

Run: python -m pytest scripts/tests/test_publish_hygiene.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_dashboard import public_home  # noqa: E402
from build_profiles import sanitize_profile_text  # noqa: E402


def test_public_home_rounds_and_drops_cross_streets():
    home = {"neighborhood": "Silver Lake", "cross_streets": "Hyperion & Del Mar",
            "coords": [34.0906, -118.2717]}
    out = public_home(home)
    assert out == {"neighborhood": "Silver Lake", "coords": [34.09, -118.27]}
    assert "cross_streets" not in out


def test_public_home_tolerates_missing_and_junk():
    assert public_home(None) == {}
    assert public_home({}) == {}
    assert public_home({"coords": ["a", "b"]}) == {}
    assert public_home({"coords": [34.0906]}) == {}
    assert public_home({"neighborhood": "Glendale"}) == {"neighborhood": "Glendale"}


def test_sanitize_profile_text_rounds_coords_and_drops_cross_streets():
    text = ("home:\n"
            "  neighborhood: Glendale\n"
            "  cross_streets: Brand & Broadway\n"
            "  coords: [34.1469, -118.2554]   # central Glendale\n"
            "scoring:\n"
            "  category_weights:\n"
            "    live_music: 3\n")
    out = sanitize_profile_text(text)
    assert "cross_streets" not in out
    assert "[34.15, -118.26]" in out
    assert "live_music: 3" in out                      # untouched knobs survive verbatim
    assert out.endswith("\n")


def test_sanitize_profile_text_handles_diff_lines():
    diff = ("--- a/profiles/lori/profile.yaml\n"
            "+++ b/profiles/lori/profile.yaml\n"
            "+  cross_streets: Brand & Broadway\n"
            "-  coords: [34.146900, -118.255400]\n"
            "+  coords: [34.1469, -118.2554]\n")
    out = sanitize_profile_text(diff)
    assert "cross_streets" not in out
    assert "34.15" in out and "34.1469" not in out


def test_sanitize_profile_text_empty_passthrough():
    assert sanitize_profile_text("") == ""
    assert sanitize_profile_text(None) is None
