#!/usr/bin/env python3
"""Tests for lib/festivals — the festivals.yaml watch-list data path — and the digest's
watch-list block (_watchlist_md). The loader itself is also exercised through
build_dashboard in test_front_page.test_festivals_watchlist_lift.

Run: python scripts/tests/test_festivals.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.festivals import festival_scope, pretty_when, timely  # noqa: E402
import render_digest as R  # noqa: E402


def test_festival_scope_heuristic_and_override():
    """Greater-LA locations -> local; everything else (incl. SD/Indio — overnight-shaped
    drives) -> travel; an explicit yaml scope always wins; junk explicit values fall back."""
    assert festival_scope("Great Park Live, Irvine (OC — ~45 mi, worth the drive)") == "local"
    assert festival_scope("Los Angeles State Historic Park") == "local"
    assert festival_scope("Exposition Park, LA") == "local"            # bare 'LA', word-bounded
    assert festival_scope("Golden Gate Park, San Francisco") == "travel"
    assert festival_scope("Waterfront Park, San Diego") == "travel"
    assert festival_scope("Empire Polo Club, Indio CA") == "travel"
    assert festival_scope("Peckham Rye Park, South London") == "travel"  # 'gala'/'Atlanta' safe too
    assert festival_scope("") == "travel"                              # unknown -> travel
    assert festival_scope("San Francisco", explicit="local") == "local"
    assert festival_scope("Los Angeles", explicit="TRAVEL") == "travel"
    assert festival_scope("Los Angeles", explicit="bogus") == "local"


def test_timely_gate_matches_the_yaml_relevance_contract():
    """Digest surfaces only items with a live ticket story; standing memory (annual_watch /
    dormant / unknown statuses) stays in the file and the dashboard view."""
    fests = [{"name": "A", "status": "on_sale"}, {"name": "B", "status": "announced"},
             {"name": "C", "status": "lineup_pending"}, {"name": "D", "status": "annual_watch"},
             {"name": "E", "status": "dormant"}, {"name": "F", "status": None}]
    assert [f["name"] for f in timely(fests)] == ["A", "B", "C"]


def test_pretty_when_uses_md_convention():
    assert pretty_when("2026-09-26..27") == "9/26–27"
    assert pretty_when("2026-08-07..09") == "8/7–9"     # range tail sheds its leading zero
    assert pretty_when("2027-04-09..11 and 2027-04-16..18") == "4/9–11 and 4/16–18"
    assert pretty_when("2026-08-29") == "8/29"
    assert pretty_when("typically late May") == "typically late May"
    assert pretty_when(None) == ""


def test_watchlist_md_block():
    rows = [{"name": "Portola 2026", "when": "2026-09-26..27", "status": "on_sale",
             "location": "Pier 80, San Francisco", "tickets": "https://portola.example",
             "why": "THE one for you."},
            {"name": "Coachella 2027", "when": "2027-04-09..11", "status": "lineup_pending",
             "location": "Indio CA", "tickets": None, "why": ""}]
    md = "\n".join(R._watchlist_md(rows))
    assert "**The watch-list**" in md
    assert "[Portola 2026](https://portola.example)" in md
    assert "9/26–27 · Pier 80, San Francisco" in md
    assert "**on sale**" in md and "THE one for you." in md
    assert "**Coachella 2027**" in md and "**lineup pending**" in md   # no link, no why tail
    assert R._watchlist_md([]) == []                                   # absent -> no block


def test_consolidated_render_carries_the_watchlist():
    rows = [{"name": "Portola 2026", "when": "2026-09-26..27", "status": "on_sale",
             "location": "Pier 80, SF", "tickets": "https://portola.example", "why": "w"}]
    md = R.render_consolidated_md("2026-07-25", [], [], {"meta": {}}, watchlist=rows)
    assert "## On the radar" in md and "Portola 2026" in md
    md_none = R.render_consolidated_md("2026-07-25", [], [], {"meta": {}})
    assert "The watch-list" not in md_none


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
