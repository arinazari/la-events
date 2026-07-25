#!/usr/bin/env python3
"""Tests for scripts/fetch_19hz.py — the unclosed Title @ Venue <td>.

Run: python scripts/tests/test_fetch_19hz.py   (also pytest-compatible)
19hz's HTML never closes the Title @ Venue cell, so the genre-tags <td> that follows is
swallowed into it by the cell regex. The fetcher must split it back out: glued genre text
made venues like "Ace Mission Studios (Los Angeles) tech house", which defeated
cross-source dedupe (the HARD-afters double-card) and put tag noise in every venue line.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from fetch_19hz import parse_listing  # noqa: E402

# Verbatim row shape from the live listing (2026-07-20) — note the missing </td> after
# "(Los Angeles)": the genre cell rides inside the title/venue cell.
ROW_UNCLOSED = (
    "<tr><td>Sat: Aug 1 <br />(10pm-2am)</td>"
    "<td><a href='https://hard.frontgatetickets.com/event/mxqewxz783v0qzfu'>Mau P, Dreya V</a>"
    " @ Ace Mission Studios (Los Angeles)<td>tech house</td>"
    "<td>$95-105 | 21+</td><td></td><td></td>"
    "<td><div class='shrink'>2026/08/01</div></td></tr>"
)

LO, HI = date(2026, 7, 20), date(2026, 8, 10)


def test_swallowed_genre_td_split_out():
    (ev,) = parse_listing(ROW_UNCLOSED, LO, HI)
    assert ev["venue"] == "Ace Mission Studios (Los Angeles)"
    assert ev["genre"] == "tech house"
    assert ev["title"] == "Mau P, Dreya V"
    assert ev["date"] == "2026-08-01"
    assert ev["price"] == "$95-105"
    assert ev["age"] == "21+"
    assert ev["links"] == ["https://hard.frontgatetickets.com/event/mxqewxz783v0qzfu"]
    assert ev["afterhours_flag"]  # 10pm doors


def test_empty_genre_cell_yields_no_genre():
    (ev,) = parse_listing(ROW_UNCLOSED.replace("<td>tech house</td>", "<td></td>"), LO, HI)
    assert ev["venue"] == "Ace Mission Studios (Los Angeles)"
    assert ev["genre"] is None


def test_out_of_window_rows_skipped():
    assert parse_listing(ROW_UNCLOSED, date(2026, 8, 2), date(2026, 8, 16)) == []


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
