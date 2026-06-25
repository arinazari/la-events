#!/usr/bin/env python3
"""Tests for scripts/build_radar.py — the 'on the radar' signal heuristic + ranking.

Run: python scripts/tests/test_radar.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_radar as BR  # noqa: E402

TRACKED = ["Antal", "Yaeji", "Ame"]   # 'Ame' is len 3 -> guarded out (no 'James' false-hit)


def test_signals_detected():
    fest = {"title": "Lightning in a Bottle Festival", "venue": "Buena Vista", "lineup": []}
    assert "festival" in BR.radar_signals(fest, TRACKED)
    big = {"title": "Some Act", "venue": "Kia Forum", "lineup": []}
    assert "big-venue" in BR.radar_signals(big, TRACKED)
    trk = {"title": "Club Night", "venue": "TBA", "lineup": ["Yaeji", "Local"]}
    assert any(s.startswith("tracked:") and "Yaeji" in s for s in BR.radar_signals(trk, TRACKED))
    edi = {"title": "X", "venue": "Y", "lineup": [], "editorial_mentions": ["LAist"]}
    assert "editorial" in BR.radar_signals(edi, TRACKED)


def test_no_false_signal():
    assert BR.radar_signals({"title": "James Blake Live", "venue": "The Echo", "lineup": ["James Blake"]},
                            TRACKED) == []          # 'Ame' (len 3) guarded; no big-venue/festival
    assert BR.radar_signals({"title": "Open Mic", "venue": "A Bar", "lineup": []}, TRACKED) == []


def test_rank_weights_editorial_over_big_venue():
    assert BR.radar_rank(5, ["editorial"]) > BR.radar_rank(5, ["big-venue"])
    assert BR.radar_rank(5, ["festival", "tracked:Antal"]) > BR.radar_rank(9, ["big-venue"])
    assert BR.radar_rank(9, ["big-venue"]) > BR.radar_rank(2, ["big-venue"])   # score breaks ties


def test_build_radar_respects_cutoff_and_ranks():
    today = date(2026, 6, 20)
    catalog = [
        {"title": "Near Fest", "venue": "X", "date": "2026-07-01", "lineup": []},   # < cutoff (11d) -> out
        {"title": "Far Festival", "venue": "X", "date": "2026-09-01", "lineup": []},  # festival, far -> in
        {"title": "Arena Show", "venue": "Kia Forum", "date": "2026-09-02", "lineup": []},  # big-venue -> in
        {"title": "Nothing Special", "venue": "A Bar", "date": "2026-09-03", "lineup": []},  # no signal -> out
    ]
    rows = BR.build_radar(catalog, {}, {}, today, cutoff_days=35, festivals="")  # catalog-only
    titles = [r["title"] for r in rows]
    assert "Near Fest" not in titles and "Nothing Special" not in titles
    assert titles[0] == "Far Festival"          # festival(2) outranks big-venue(1)
    assert set(titles) == {"Far Festival", "Arena Show"}


def test_curated_festivals_surface_and_gate():
    today = date(2026, 6, 25)
    doc = {"festivals": [
        {"name": "Outside Lands 2026", "location": "Golden Gate Park, San Francisco",
         "when": "2026-08-07..09", "status": "on_sale", "tickets": "http://ol"},
        {"name": "Portola 2026", "location": "Pier 80, San Francisco",
         "when": "2026-09-26..27", "status": "on_sale", "tickets": "http://p"},
        {"name": "Coachella 2027", "location": "Indio CA",
         "when": "2027-04-09..11 and 2027-04-16..18", "status": "lineup_pending", "tickets": "http://c"},
        {"name": "GALA Festival 2027", "location": "London", "when": "~2027-05", "status": "dormant"},
        {"name": "Past Fest", "location": "X", "when": "2026-01-01", "status": "on_sale"},
    ]}
    rows = BR._curated_rows(doc, {}, {}, today, [])
    titles = {r["title"] for r in rows}
    assert "Outside Lands 2026" in titles          # on_sale, future -> surfaced
    assert "Portola 2026" in titles
    assert "Coachella 2027" in titles              # lineup_pending is active -> surfaced
    assert "GALA Festival 2027" not in titles      # dormant -> held in the file
    assert "Past Fest" not in titles               # start date in the past -> held
    assert all("curated" in r["signals"] for r in rows)
    coach = next(r for r in rows if r["title"] == "Coachella 2027")
    assert coach["iso_date"] == "2027-04-09" and coach["link"] == "http://c"


def test_curated_dedupes_against_catalog_row():
    today = date(2026, 6, 25)
    doc = {"festivals": [{"name": "HARD Summer Music Festival", "location": "Inglewood",
                          "when": "2026-08-01", "status": "on_sale"}]}
    catalog_rows = [{"title": "HARD Summer 2026"}]            # same fest already in the LA catalog
    assert BR._curated_rows(doc, {}, {}, today, catalog_rows) == []   # not double-listed


def test_curated_merges_into_build_radar():
    today = date(2026, 6, 25)
    catalog = [{"title": "Arena Show", "venue": "Kia Forum", "date": "2026-09-02", "lineup": []}]
    # No festivals file -> catalog-only; an inline doc would need a path, so just assert the merge
    # point is reachable and curated outranks a bare big-venue when present.
    rows = BR.build_radar(catalog, {}, {}, today, cutoff_days=35, festivals="")
    assert [r["title"] for r in rows] == ["Arena Show"]       # festivals='' disables the merge
    assert BR.radar_rank(0, ["curated"]) > BR.radar_rank(9, ["big-venue"])  # curated leads big-venue


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
