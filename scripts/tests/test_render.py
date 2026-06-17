#!/usr/bin/env python3
"""Tests for scripts/render_digest.py — day-grouped renderers (.md + .html).

Run: python scripts/tests/test_render.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_digest as R  # noqa: E402

DOC = {"generated_at": "2026-06-17T09:00:00", "today": "2026-06-17",
       "sources": {"failed": [["dice", "exit 1"]]}, "candidates": []}
CANDS = [
    {"title": "Sunset Sessions", "iso_date": "2026-06-19", "start": "17:00", "score": 11,
     "rating": 5, "venue": "Golden Hour at Level 8", "neighborhood": "DTLA", "price": "free",
     "category": "electronic", "image_wanted": True,
     "links": [{"source": "ra", "url": "https://ra.co/e/1"}, {"source": "ticketmaster", "url": "https://tm/1"}],
     "enrichment": {"type": "electronic", "curator_note": "Rooftop house as the sun drops.",
                    "artist_notes": [{"name": "Antal", "note": "Rush Hour boss"}],
                    "image": {"url": "https://img/1.jpg"}}},
    {"title": "Mad Max: Fury Road", "iso_date": "2026-06-19", "start": "2026-06-19T16:00:00", "score": 6,
     "rating": 4, "venue": "Vidiots", "neighborhood": "Eagle Rock", "price": "$15", "category": "film",
     "links": [{"source": "vidiots", "url": "https://vidiots/1"}]},
]


def test_helpers():
    assert R.stars(5) == "★★★★★" and R.stars(3) == "★★★☆☆"
    assert R.day_label("2026-06-19") == "Fri 6/19"
    assert R.day_header("2026-06-19") == "Friday · June 19"
    assert R.fmt_time("17:00") == "5pm" and R.fmt_time("21:30") == "9:30pm"
    assert R.fmt_time("2026-06-19T16:00:00") == "4pm"     # ISO datetime
    assert R.fmt_time("5pm-10pm") == "5pm-10pm"            # display range passes through
    assert R.fmt_time(None) == ""


def test_markdown_is_day_grouped_with_variety():
    md = R.render_markdown(DOC, CANDS)
    assert "Don't-miss" not in md and "Don't miss" not in md        # no top section
    assert "## Friday · June 19" in md                              # day header
    assert "**Electronic & dance**" in md and "**Film**" in md      # category variety
    assert "⭐" in md                                                # pick flag (Sunset, rating 5)
    assert "`5pm`" in md and "`4pm`" in md                          # times rendered (incl. ISO)
    assert "Mad Max: Fury Road" in md                               # non-electronic surfaced
    assert "Rooftop house as the sun drops." in md                  # curator note
    assert "dice (exit 1)" in md                                    # footer


def test_html_is_day_grouped_with_uppercase_tags():
    html = R.render_html(DOC, CANDS)
    assert html.startswith("<!doctype html>")
    assert 'class="grp"' in html and "Electronic &amp; dance" in html
    assert "Friday · June 19" in html
    assert "⭐ PICK" in html                                         # inline pick tag
    assert ">RA<" in html and ">TICKETMASTER<" in html              # uppercase source tags
    assert '<img class="thumb"' in html                            # hero thumb on the pick
    assert "Rooftop house as the sun drops." in html


def test_collapse_multidate_runs():
    runs = [
        {"title": "Chris Lake", "venue": "LA State Historic Park", "iso_date": "2026-06-19",
         "start": "5pm", "score": 8, "rating": 5, "category": "electronic", "links": []},
        {"title": "Chris Lake", "venue": "LA State Historic Park", "iso_date": "2026-06-20",
         "start": "5pm", "score": 9, "rating": 5, "category": "electronic", "links": []},
    ]
    md = R.render_markdown({"today": "2026-06-17", "candidates": runs}, runs)
    assert md.count("Chris Lake") == 1                              # one entry, not per-day
    assert "Fri 6/19 + Sat 6/20" in md                             # date span
    assert "Saturday" not in md                                    # placed once, earliest day


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
