#!/usr/bin/env python3
"""Tests for scripts/lib/reactions.py — the stars log (Track A4) and its fold onto events.

Run: python -m pytest scripts/tests/test_reactions.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.reactions import load_reactions, star_map, stars_for  # noqa: E402


def _r(profile, key, kind, **kw):
    return {"ts": "2026-07-11", "profile": profile, "event_key": key, "kind": kind, **kw}


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
        {"kind": "loved", "artists": ["Antal"]},       # not a star kind
        "junk",
    ]
    assert star_map(rs) == {}


def test_stars_for_names_and_order():
    m = {"k1": {"h_lori", "h_raffi", "h_gone"}}
    names = {"h_lori": "Lori", "h_raffi": "Raffi"}    # h_gone rotated away — no name mapping
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
