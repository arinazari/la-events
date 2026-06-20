#!/usr/bin/env python3
"""Tests for scripts/lib/feedback.py — the feedback loop (Phase C).

Run: python scripts/tests/test_feedback.py   (also pytest-compatible)
Covers aggregation, folding into a Spotify affinity (and into an empty one), the `hidden`
override, the below-floor drop, and the merged_affinity loader / scorer end-to-end.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.feedback import (affinity_paths, aggregate, apply_feedback,  # noqa: E402
                          load_feedback, merged_affinity)
from lib.scoring import score_event  # noqa: E402
from lib.config import load_profile  # noqa: E402

PROFILE = load_profile()


def test_aggregate_collects_deltas_and_hide():
    rx = [
        {"kind": "loved", "artists": ["Chris Lake"], "genres": ["disco"]},
        {"kind": "hide", "artists": ["Some Bro DJ"]},
        {"kind": "skipped", "artists": ["Chris Lake"]},
    ]
    agg = aggregate(rx, PROFILE)
    assert round(agg["artist_delta"]["chris lake"], 2) == 1.5  # +2.0 loved - 0.5 skipped
    assert "some bro dj" in agg["hide"]
    assert agg["genre_delta"]["disco"] == 2.0


def test_apply_to_empty_affinity_creates_feedback_layer():
    agg = aggregate([{"kind": "loved", "artists": ["Chris Lake"]}], PROFILE)
    aff = apply_feedback(None, agg)
    assert aff["source"] == "feedback"
    cl = aff["artists"]["chris lake"]
    assert cl["tier"] == "strong" and "feedback" in cl["sources"]   # 2.0 -> strong tier


def test_feedback_stacks_onto_spotify_and_hide_overrides():
    spotify = {"artists": {"antal": {"name": "Antal", "weight": 2.0, "tier": "strong",
                                     "sources": ["top_long"]}},
               "genres": {}, "source": "spotify"}
    agg = aggregate([{"kind": "loved", "artists": ["Antal"]},
                     {"kind": "hide", "artists": ["Antal"]}], PROFILE)
    aff = apply_feedback(spotify, agg)
    assert aff["source"] == "spotify+feedback"
    assert aff["artists"]["antal"]["tier"] == "hidden"             # hide wins regardless of weight
    assert aff["artists"]["antal"]["weight"] == 2.0 + 2.0 - 10.0   # weight still folded


def test_skip_below_floor_drops_artist():
    spotify = {"artists": {"x": {"name": "X", "weight": 0.9, "tier": "light", "sources": ["recent"]}},
               "genres": {}}
    aff = apply_feedback(spotify, aggregate([{"kind": "skipped", "artists": ["X"]}], PROFILE))
    assert "x" not in aff["artists"]            # 0.9 - 0.5 = 0.4 < light floor -> dropped


def test_merged_affinity_none_when_empty(tmp_path=None):
    d = Path(tmp_path or tempfile.mkdtemp())
    (d / "data").mkdir(exist_ok=True)
    assert merged_affinity(d, PROFILE) is None


def test_merged_affinity_feedback_only(tmp_path=None):
    d = Path(tmp_path or tempfile.mkdtemp())
    (d / "data").mkdir(exist_ok=True)
    (d / "data" / "feedback.jsonl").write_text(
        '{"kind":"loved","artists":["Chris Lake"]}\n# a comment\n\n')
    aff = merged_affinity(d, PROFILE)
    assert aff and aff["source"] == "feedback" and "chris lake" in aff["artists"]


def test_loved_artist_scores_via_music_layer():
    ev = {"title": "Chris Lake presents Black Book", "category": "electronic",
          "venue": "Shrine", "date": "2026-06-20", "lineup": ["Chris Lake"]}
    aff = apply_feedback(None, aggregate([{"kind": "loved", "artists": ["Chris Lake"]}], PROFILE))
    base = score_event(ev, {}, PROFILE)
    boosted = score_event(ev, {}, PROFILE, aff)
    assert boosted["score"] > base["score"]
    # Feedback-origin -> the reason credits the pick, not Spotify (honest provenance).
    assert any("more like" in r and "Chris Lake" in r for r in boosted["reasons"])


def test_affinity_paths_default_vs_profile():
    """No hash -> the canonical (owner) layer; a hash -> that profile's own per-person layer."""
    sp, fb = affinity_paths("/repo")
    assert sp == Path("/repo/data/spotify_affinity.json") and fb == Path("/repo/data/feedback.jsonl")
    psp, pfb = affinity_paths("/repo", "deadbeefdeadbeef")
    assert psp == Path("/repo/data/spotify/deadbeefdeadbeef.json")
    assert pfb == Path("/repo/data/feedback.deadbeefdeadbeef.jsonl")


def test_merged_affinity_per_profile_layer(tmp_path=None):
    """A per-profile hash loads data/spotify/<hash>.json + data/feedback.<hash>.jsonl — and the
    owner's data/feedback.jsonl / spotify_affinity.json never bleed into a friend's feed."""
    d = Path(tmp_path or tempfile.mkdtemp())
    (d / "data" / "spotify").mkdir(parents=True, exist_ok=True)
    h = "0123456789abcdef"
    # Owner layer says "love Owner DJ"; the friend's layer says "love Friend DJ".
    (d / "data" / "feedback.jsonl").write_text('{"kind":"loved","artists":["Owner DJ"]}\n')
    (d / "data" / f"feedback.{h}.jsonl").write_text('{"kind":"loved","artists":["Friend DJ"]}\n')
    (d / "data" / "spotify" / f"{h}.json").write_text(json.dumps(
        {"source": "spotify", "genres": {},
         "artists": {"peggy gou": {"name": "Peggy Gou", "weight": 3.0, "tier": "core",
                                   "sources": ["top_long"]}}}))
    aff = merged_affinity(d, PROFILE, profile_hash=h)
    assert "peggy gou" in aff["artists"]          # friend's Spotify artist present
    assert "friend dj" in aff["artists"]          # friend's own feedback folded in
    assert "owner dj" not in aff["artists"]       # the owner's feedback did NOT leak in
    assert aff["source"] == "spotify+feedback"


def test_merged_affinity_profile_none_when_no_layer(tmp_path=None):
    """A profile with no per-person Spotify/feedback falls through to taste-only (None) — it does
    NOT silently inherit the owner's layer."""
    d = Path(tmp_path or tempfile.mkdtemp())
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / "data" / "feedback.jsonl").write_text('{"kind":"loved","artists":["Owner DJ"]}\n')
    assert merged_affinity(d, PROFILE, profile_hash="ffffffffffffffff") is None


def test_load_feedback_skips_garbage(tmp_path=None):
    d = Path(tmp_path or tempfile.mkdtemp())
    f = d / "fb.jsonl"
    f.write_text('{"kind":"loved","artists":["A"]}\nnot json\n   \n{"kind":"hide","artists":["B"]}\n')
    rx = load_feedback(f)
    assert len(rx) == 2


def test_committed_feedback_log_is_valid_jsonl():
    """The committed data/feedback.jsonl parses cleanly (comments skipped; may be empty)."""
    repo = Path(__file__).resolve().parent.parent.parent
    rx = load_feedback(repo / "data" / "feedback.jsonl")
    assert isinstance(rx, list)                       # no crash on the real file
    agg = aggregate(rx, PROFILE)                       # aggregate handles it (even when empty)
    assert set(agg) == {"artist_delta", "genre_delta", "hide", "names"}


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
