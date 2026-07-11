#!/usr/bin/env python3
"""Tests for scripts/lib/profiles.py — the capability-token → feed-hash mapping (Track A1).

Run: python -m pytest scripts/tests/test_profiles.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.profiles import profile_hash, entry_hash, hash_names, DEFAULT_SALT  # noqa: E402


def test_profile_hash_fixture_parity():
    # The exact fixture backend/test-edits.mjs asserts (Web Crypto) — keep them in lockstep.
    assert profile_hash("aaaa000011112222", "la-events/v2:") == "a8de6e4309060de7"


def test_profile_hash_normalizes_case_and_whitespace():
    h = profile_hash(" AAAA000011112222 ", DEFAULT_SALT)
    assert h == profile_hash("aaaa000011112222", DEFAULT_SALT)
    assert len(h) == 16 and all(c in "0123456789abcdef" for c in h)


def test_salt_changes_the_hash():
    assert profile_hash("aaaa000011112222", "la-events/v2:") != \
        profile_hash("aaaa000011112222", "la-events/v3:")


def test_entry_hash_none_without_token():
    assert entry_hash({"username": "garo"}) is None
    assert entry_hash({}) is None
    assert entry_hash({"token": "aaaa000011112222"}, "la-events/v2:") == "a8de6e4309060de7"


def test_hash_names_maps_tokened_profiles_only():
    manifest = {
        "salt": "la-events/v2:",
        "profiles": [
            {"username": "lori", "name": "Lori", "token": "bbbb000011112222"},
            {"username": "garo", "name": "Garo"},          # tokenless -> no feed hash -> absent
            "junk",                                          # tolerated
            {"username": "raffi", "token": "cccc000011112222"},   # no display name -> username
        ],
    }
    names = hash_names(manifest)
    assert names[profile_hash("bbbb000011112222", "la-events/v2:")] == "Lori"
    assert names[profile_hash("cccc000011112222", "la-events/v2:")] == "raffi"
    assert len(names) == 2
