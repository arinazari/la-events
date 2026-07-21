#!/usr/bin/env python3
"""Tests for scripts/lib/reactions.py + scripts/lib/profiles.py — the stars log and its fold.

Run: python scripts/tests/test_reactions.py   (also pytest-compatible)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.reactions import load_reactions, star_map, stars_for, hidden_map, is_hidden  # noqa: E402
from lib.profiles import profile_hash, hash_names  # noqa: E402


def _r(profile, key, kind, **kw):
    return {"ts": "2026-07-21", "profile": profile, "event_key": key, "kind": kind, **kw}


def test_star_map_last_wins_per_profile_and_event():
    rs = [
        _r("aaa", "k1", "star"),
        _r("bbb", "k1", "star"),
        _r("aaa", "k1", "unstar"),      # aaa's later unstar clears their star
        _r("aaa", "k2", "star"),
        _r("bbb", "k2", "star"),
        _r("bbb", "k2", "hide"),        # hide clears bbb's star too
    ]
    m = star_map(rs)
    assert m["k1"] == {"bbb"}
    assert m["k2"] == {"aaa"}


def test_star_map_drops_fully_unstarred_events_and_junk():
    rs = [
        _r("aaa", "k1", "star"),
        _r("aaa", "k1", "unstar"),
        _r("aaa", "", "star"),                        # no key
        _r("", "k2", "star"),                         # no profile
        {"kind": "loved", "artists": ["Antal"]},      # not a star kind
        "junk",
    ]
    assert star_map(rs) == {}


def test_hidden_map_last_wins_and_is_per_profile():
    rs = [
        _r("aaa", "k1", "hide"),
        _r("bbb", "k1", "hide"),
        _r("aaa", "k1", "unhide"),      # aaa took their hide back
        _r("bbb", "k2", "hide"),
        _r("bbb", "k2", "star"),        # starring clears bbb's hide on k2
    ]
    m = hidden_map(rs)
    assert m["k1"] == {"bbb"}           # aaa un-hid; bbb still hides k1
    assert "k2" not in m                # bbb's later star cleared the hide
    assert is_hidden(m, "k1", "bbb") is True
    assert is_hidden(m, "k1", "aaa") is False
    assert is_hidden(m, "k1", None) is False   # logged-out has no hides


def test_star_and_hide_are_mutually_exclusive():
    # A hide clears a star; a later star clears the hide — never both at once for one person.
    rs = [_r("aaa", "k1", "star"), _r("aaa", "k1", "hide")]
    assert star_map(rs) == {}                   # the hide cleared the star
    assert hidden_map(rs)["k1"] == {"aaa"}
    rs2 = [_r("aaa", "k1", "hide"), _r("aaa", "k1", "star")]
    assert hidden_map(rs2) == {}                # the star cleared the hide
    assert star_map(rs2)["k1"] == {"aaa"}


def test_stars_for_names_and_order():
    m = {"k1": {"h_lori", "h_raffi", "h_gone"}}
    names = {"h_lori": "Lori", "h_raffi": "Raffi"}    # h_gone unmapped — no name
    out = stars_for(m, names, "k1")
    assert [s["name"] for s in out] == ["friend·h_go", "Lori", "Raffi"]
    assert all(set(s) == {"name", "hash"} for s in out)
    assert stars_for(m, names, "missing") == []


def test_load_reactions_tolerant_jsonl():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "reactions.jsonl"
        p.write_text('{"profile":"aaa","event_key":"k1","kind":"star"}\n'
                     "# comment\n"
                     "not json\n"
                     '{"profile":"bbb","event_key":"k1","kind":"star"}')
        rs = load_reactions(p)
        assert len(rs) == 2
        assert star_map(rs)["k1"] == {"aaa", "bbb"}
        assert load_reactions(Path(td) / "absent.jsonl") == []


def test_hash_names_matches_the_shared_hashing():
    # Same salt+scheme as build_profiles.profile_hash and the Worker — a known pair.
    manifest = {"salt": "la-events/v1:", "profiles": [
        {"username": "lori", "name": "Lori"},
        {"username": "garo"},                          # no name -> falls back to username
        {"nope": 1},                                   # skipped (no username)
    ]}
    names = hash_names(manifest)
    assert names[profile_hash("lori", "la-events/v1:")] == "Lori"
    assert names[profile_hash("garo", "la-events/v1:")] == "garo"
    assert len(names) == 2


def _run():
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok  " + name)
            passed += 1
    print(f"\nall {passed} reactions tests passed")


if __name__ == "__main__":
    _run()
