#!/usr/bin/env python3
"""Tests for scripts/render_digest.py — the .md + .html renderers.

Run: python scripts/tests/test_render.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_digest as R  # noqa: E402

DOC = {
    "generated_at": "2026-06-17T09:00:00", "today": "2026-06-17",
    "sources": {"failed": [["dice", "exit 1"]]},
    "candidates": [],
}
CANDS = [
    {"title": "Sunset Sessions", "iso_date": "2026-06-19", "start": "17:00", "score": 11,
     "rating": 5, "venue": "Golden Hour at Level 8", "neighborhood": "DTLA", "price": "free",
     "category": "electronic", "image_wanted": True,
     "links": [{"source": "ra", "url": "https://ra.co/e/1"}, {"source": "dice", "url": "https://dice.fm/e/1"}],
     "enrichment": {"type": "electronic", "curator_note": "The rooftop-vinyl north star.",
                    "artist_notes": [{"name": "Antal", "note": "Rush Hour boss"}],
                    "image": {"url": "https://img/1.jpg"}}},
    {"title": "Comedy Thing", "iso_date": "2026-06-20", "start": "20:00", "score": 2,
     "rating": 2, "venue": "The Club", "category": "comedy", "links": []},
]


def test_helpers():
    assert R.stars(5) == "★★★★★" and R.stars(3) == "★★★☆☆"
    assert R.day_label("2026-06-19") == "Fri 6/19"
    assert R.fmt_time("17:00") == "5pm" and R.fmt_time("21:30") == "9:30pm"


def test_markdown_structure():
    md = R.render_markdown(DOC, CANDS)
    assert "## Don't-miss" in md
    assert "### Fri 6/19" in md and "### Sat 6/20" in md      # day-by-day headers
    assert "★★★★★" in md
    assert "[**Sunset Sessions**](https://ra.co/e/1)" in md    # linked title
    assert "The rooftop-vinyl north star." in md               # curator note
    assert "Antal — Rush Hour boss" in md                      # gloss
    assert "dice (exit 1)" in md                               # footer coverage gap


def test_html_structure():
    html = R.render_html(DOC, CANDS)
    assert html.startswith("<!doctype html>")
    assert 'class="chip"' in html and "Electronic" in html
    assert '<img src="https://img/1.jpg"' in html              # hero image for image_wanted
    assert 'href="https://ra.co/e/1"' in html                  # ticket button
    assert "The rooftop-vinyl north star." in html
    assert "Fri 6/19" in html and "Sat 6/20" in html


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
