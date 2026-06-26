#!/usr/bin/env python3
"""Tests for scripts/lib/editor.py — the thin-editor verdict cache/selection plumbing.

Run: python scripts/tests/test_editor.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import editor as ED  # noqa: E402


def _ev(title, tags, score, d="2026-07-04"):
    """Minimal scored+tagged event. `tags` drives event_lane; score/iso_date drive selection."""
    return {"title": title, "date": d, "venue": title + " hall",
            "score": score, "iso_date": d, "tags": tags}


CLUB_U = {"type": "club", "vibe": [], "setting": [], "genre": []}      # club:underground
STAGE = {"type": "stage", "vibe": [], "setting": [], "genre": []}      # stage
OTHER = {"type": "other", "vibe": [], "setting": [], "genre": []}      # non-slate lane


def test_validate_verdict_coerces_and_rejects():
    assert ED.validate_verdict({"tier": "bogus"}) is None              # bad tier -> drop
    assert ED.validate_verdict("nope") is None
    v = ED.validate_verdict({"tier": "great", "adjust": 9, "lane": "club:afters",
                             "why": "x", "confidence": "nonsense"})
    assert v["adjust"] == 3                                            # clamped to +3
    assert v["lane"] == "club:afters" and v["why"] == "x"
    assert v["confidence"] == "med"                                    # invalid -> default
    assert ED.validate_verdict({"tier": "skip"})["adjust"] == 0        # adjust defaults to 0


def test_editor_pool_per_lane_includes_thin_lane_below_floor():
    """The per-lane floor: a lane's best gets judged even when it scores below the global floor;
    sub-floor events in a flooded lane are dropped."""
    pool = [_ev("U7", CLUB_U, 7), _ev("U6", CLUB_U, 6), _ev("U5", CLUB_U, 5),
            _ev("U3", CLUB_U, 3), _ev("Stage2", STAGE, 2), _ev("Other3", OTHER, 3)]
    keys = {ED.event_key(e) for e in ED.editor_pool(pool, per_lane=3, floor=4)}
    assert ED.event_key(_ev("Stage2", STAGE, 2)) in keys     # thin lane's best, despite score 2
    assert ED.event_key(_ev("U3", CLUB_U, 3)) not in keys    # below floor AND outside lane top-3
    assert ED.event_key(_ev("U7", CLUB_U, 7)) in keys        # high-absolute via floor
    assert ED.event_key(_ev("Other3", OTHER, 3)) not in keys  # non-slate lane, below floor -> skipped


def test_select_for_verdict_finds_misses_and_carries_id():
    ev = _ev("Afters", CLUB_U, 5)
    cache = {"verdicts": {}}
    [m] = ED.select_for_verdict([ev], cache)
    assert m["id"] == ED.event_key(ev)
    # once judged, write-once skips it
    ED.update_verdicts(cache, [{"id": ED.event_key(ev), "tier": "great"}],
                       scores={ED.event_key(ev): 5}, now="2026-06-19T00:00:00")
    assert ED.select_for_verdict([ev], cache) == []


def test_select_for_verdict_reselects_on_score_drift():
    ev = _ev("Drifter", CLUB_U, 5)
    k = ED.event_key(ev)
    cache = {"verdicts": {k: {"tier": "solid", "score_at_judge": 5,
                              "input_version": ED.EDITOR_INPUT_VERSION,
                              "judged_at": "2026-06-19T00:00:00"}}}
    assert ED.select_for_verdict([ev], cache) == []          # score unchanged -> skip
    ev2 = dict(ev); ev2["score"] = 8                          # lineup/feedback moved the score
    assert [m["id"] for m in ED.select_for_verdict([ev2], cache)] == [k]


def test_select_for_verdict_refresh_days():
    ev = _ev("Recur", CLUB_U, 5)
    k = ED.event_key(ev)
    cache = {"verdicts": {k: {"tier": "solid", "score_at_judge": 5,
                              "input_version": ED.EDITOR_INPUT_VERSION,
                              "judged_at": "2026-06-01T00:00:00"}}}
    today = date(2026, 6, 19)
    assert ED.select_for_verdict([ev], cache, refresh_days=90, today=today) == []   # 18d < 90
    stale = ED.select_for_verdict([ev], cache, refresh_days=7, today=today)         # 18d >= 7
    assert [s["id"] for s in stale] == [k]


def test_update_and_verdict_map_round_trip():
    ev = _ev("Main", CLUB_U, 6)
    k = ED.event_key(ev)
    cache = {"verdicts": {}}
    ED.update_verdicts(cache, [{"id": k, "tier": "must-see", "lane": "club:mainstream",
                                "adjust": 2, "why": "headliner", "confidence": "high"}],
                       scores={k: 6}, now="2026-06-19T00:00:00", model="test")
    stored = cache["verdicts"][k]
    assert stored["score_at_judge"] == 6 and stored["model"] == "test"
    assert stored["judged_at"] == "2026-06-19T00:00:00"
    m = ED.verdict_map(cache)[k]
    assert m == {"tier": "must-see", "lane": "club:mainstream", "adjust": 2,
                 "why": "headliner", "confidence": "high"}    # contract fields only (no bookkeeping)


def test_update_skips_invalid_and_idless():
    cache = {"verdicts": {}}
    ED.update_verdicts(cache, [{"tier": "great"},                       # no id
                               {"id": "k1", "tier": "bogus"},           # bad tier
                               {"id": "k2", "tier": "solid"}])
    assert list(cache["verdicts"]) == ["k2"]


def test_prune_verdicts_drops_orphans():
    live = _ev("Live", CLUB_U, 5, d="2026-07-07")
    gone = _ev("Gone", CLUB_U, 5, d="2026-05-01")
    cache = {"verdicts": {ED.event_key(live): {"tier": "solid"},
                          ED.event_key(gone): {"tier": "skip"}}}
    cache, pruned = ED.prune_verdicts(cache, [live])
    assert pruned == 1
    assert ED.event_key(live) in cache["verdicts"] and ED.event_key(gone) not in cache["verdicts"]


AFF = {"source": "spotify+feedback",
       "artists": {"antal": {"name": "Antal", "weight": 3.4, "tier": "core", "sources": ["top_long"]},
                   "hunee": {"name": "Hunee", "weight": 2.0, "tier": "strong", "sources": ["followed"]}},
       "genres": {"deep house": 1.0, "disco": 0.72, "techno": 0.3}}


def test_affinity_hint_matches_lineup_and_genre():
    ev = {"title": "Deep House Rooftop", "lineup": ["Antal", "DJ Nobody"],
          "tags": {"genre": ["deep-house"]}}
    h = ED.affinity_hint(ev, AFF)
    assert [a["name"] for a in h["artists"]] == ["Antal"]      # Antal billed, Hunee not
    assert h["artists"][0]["tier"] == "core"
    assert "deep house" in h["genres"]                         # high-affinity genre in the title
    assert ED.affinity_hint({"title": "Generic Night", "lineup": []}, AFF) is None
    assert ED.affinity_hint(ev, None) is None                  # no affinity -> no hint


def test_affinity_summary_ranks_by_weight():
    s = ED.affinity_summary(AFF)
    assert s["source"] == "spotify+feedback"
    assert [a["name"] for a in s["top_artists"]] == ["Antal", "Hunee"]   # weight desc
    assert s["top_genres"][0] == "deep house"                            # artifact pre-sorted
    assert ED.affinity_summary(None) is None


def test_pool_doc_carries_affinity_and_summary():
    ev = {"title": "Antal All Night", "date": "2026-07-04", "venue": "Warehouse",
          "lineup": ["Antal"], "score": 9, "iso_date": "2026-07-04",
          "tags": {"type": "club", "vibe": ["afterhours"], "genre": []}}
    doc = ED.pool_doc([ev], today=date(2026, 7, 4), window_days=28, per_lane=4, floor=4, affinity=AFF)
    assert doc["profile_affinity"]["top_artists"][0]["name"] == "Antal"
    rec = doc["events"][0]
    assert rec["id"] == ED.event_key(ev) and rec["lane"] == "club:afters"
    assert rec["affinity"]["artists"][0]["name"] == "Antal"


def test_record_folds_scene_facts_but_never_curator_note():
    """The enrich->editor handoff: factual scene block in, taste-flavored curator_note/energy out."""
    ev = {"title": "Antal All Night", "date": "2026-07-04", "venue": "Warehouse",
          "lineup": ["Antal"], "score": 9, "iso_date": "2026-07-04", "tags": {"type": "club"}}
    k = ED.event_key(ev)
    cache = {"events": {k: {"id": k, "subgenres": ["disco", "deep house"], "setting": "warehouse",
                            "description": "All-night warehouse party.",
                            "curator_note": "Worth building the whole night around — Ari's lane.",
                            "energy": "peak"}},
             "artists": {"antal": {"note": "Rush Hour boss — Dutch digger."}}}
    doc = ED.pool_doc([ev], today=date(2026, 7, 4), window_days=28, per_lane=4, floor=4,
                      affinity=AFF, enrichment=cache)
    scene = doc["events"][0]["scene"]
    assert scene["subgenres"] == ["disco", "deep house"] and scene["setting"] == "warehouse"
    assert scene["description"] == "All-night warehouse party."
    assert [n["name"] for n in scene["artist_notes"]] == ["Antal"]   # compounding artist bio folds in
    # the personalization invariant — opinion fields must NOT leak into another profile's editor
    assert "curator_note" not in scene and "energy" not in scene
    # no enrichment passed -> no scene block (prior behavior preserved exactly)
    plain = ED.pool_doc([ev], today=date(2026, 7, 4), window_days=28, per_lane=4, floor=4, affinity=AFF)
    assert "scene" not in plain["events"][0]
    # cache miss -> no scene block
    miss = ED.pool_doc([{**ev, "title": "Unknown Night"}], today=date(2026, 7, 4), window_days=28,
                       per_lane=4, floor=4, enrichment={"events": {}, "artists": {}})
    assert "scene" not in miss["events"][0]


def test_input_version_bump_reselects_legacy_verdicts():
    """Adding the scene block (an input_version bump) must force a one-time re-judge of every
    already-judged verdict — recurring artists are exactly the already-cached set, so without this
    the new context would reach only never-judged events."""
    ev = _ev("Legacy", CLUB_U, 5)
    k = ED.event_key(ev)
    # legacy verdict: score matches, but no input_version stamp (judged before the scene block)
    cache = {"verdicts": {k: {"tier": "solid", "score_at_judge": 5, "judged_at": "2026-06-19T00:00:00"}}}
    assert [m["id"] for m in ED.select_for_verdict([ev], cache)] == [k]   # re-selected despite no drift
    # re-judging stamps the current version -> stable thereafter
    ED.update_verdicts(cache, [{"id": k, "tier": "great"}], scores={k: 5})
    assert cache["verdicts"][k]["input_version"] == ED.EDITOR_INPUT_VERSION
    assert ED.select_for_verdict([ev], cache) == []


def test_verdict_store_round_trip(tmp=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "p.json"
        cache = {"verdicts": {}}
        ED.update_verdicts(cache, [{"id": "k1", "tier": "great", "adjust": 2}], scores={"k1": 6})
        ED.save_verdicts(cache, p)
        back = ED.load_verdicts(p)
        assert back["verdicts"]["k1"]["tier"] == "great"
        assert ED.load_verdicts(Path(d) / "missing.json") == {"verdicts": {}}   # absent -> empty


def test_verdict_path_per_profile():
    assert ED.verdict_path("abc123").name == "abc123.json"
    assert ED.verdict_path().name == "default.json"
    assert ED.verdict_path("abc123").parent.name == "verdicts"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
