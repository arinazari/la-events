#!/usr/bin/env python3
"""Tests for scripts/render_digest.py — the day-grouped Markdown agenda renderer.

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
     "category": "electronic",
     "links": [{"source": "ra", "url": "https://ra.co/e/1"}, {"source": "ticketmaster", "url": "https://tm/1"}],
     "enrichment": {"type": "electronic", "curator_note": "Rooftop house as the sun drops.",
                    "artist_notes": [{"name": "Antal", "note": "Rush Hour boss"}]}},
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


def test_footer_notes_disclose_coverage_and_music():
    # A failed source (coverage gap) and a failed Spotify refresh both surface, kept distinct.
    sources = {"failed": [["dice", "exit 1"]],
               "spotify": {"ok": False, "note": "Spotify auth rejected (401) — refresh token may be revoked"}}
    notes = R._footer_notes({"sources": sources})
    assert any("Coverage gaps" in n and "dice (exit 1)" in n for n in notes)
    assert any("Ranking note" in n and "refresh token may be revoked" in n for n in notes)
    # A healthy layer adds no ranking note; nothing failed adds no footer at all.
    assert R._footer_notes({"sources": {"spotify": {"ok": True, "note": "Wrote Spotify affinity"}}}) == []
    assert R._footer_notes({}) == []
    # And it wires through the actual renderer footer (taste-only disclosure).
    md = R.render_markdown({"today": "2026-06-17", "candidates": [], "sources": sources}, [])
    assert "Ranking note" in md and "taste profile only" in md


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


def test_collapse_same_film_across_theaters():
    """A film groups by CORE TITLE across theaters (lib/series): one card, the other venue
    teased apart with its own ticket link, plus the external LA-showtimes search."""
    runs = [
        {"title": "The Odyssey (70mm)", "venue": "Vista Theater", "iso_date": "2026-06-19",
         "start": "20:00", "score": 6, "rating": 4, "category": "film",
         "links": [{"source": "vista", "url": "https://tix/vista"}]},
        {"title": "The Odyssey 70MM", "venue": "Egyptian Theatre", "iso_date": "2026-06-20",
         "start": "19:30", "score": 5, "rating": 4, "category": "film",
         "links": [{"source": "jsonld", "url": "https://tix/egyptian"}]},
    ]
    md = R.render_markdown({"today": "2026-06-17", "candidates": runs}, runs)
    assert md.count("The Odyssey") == 1                            # one card, not per-theater
    assert "Fri 6/19 + Sat 6/20" in md                             # both dates carried
    assert "also at [Egyptian Theatre](https://tix/egyptian)" in md  # venue teased apart, linked
    assert "more LA showtimes" in md and "google.com/search" in md   # theaters we don't fetch
    # …and two DIFFERENT films at one theater stay two cards.
    two = [
        {"title": "Starman", "venue": "Vista Theater", "iso_date": "2026-06-19", "score": 5,
         "rating": 4, "category": "film", "links": []},
        {"title": "The Petrified Forest", "venue": "Vista Theater", "iso_date": "2026-06-19",
         "score": 5, "rating": 4, "category": "film", "links": []},
    ]
    md2 = R.render_markdown({"today": "2026-06-17", "candidates": two}, two)
    assert "Starman" in md2 and "The Petrified Forest" in md2


def _dm_cands():
    great = {"title": "Great9", "iso_date": "2026-06-20", "venue": "V1", "score": 9,
             "category": "electronic", "links": [], "verdict": {"tier": "great", "why": "strong bill"}}
    ms = {"title": "MustSee3", "iso_date": "2026-06-19", "venue": "V2", "score": 3,
          "category": "electronic", "links": [],
          "verdict": {"tier": "must-see", "why": "the one to build plans around"},
          "enrichment": {"curator_note": "Rare LA date."}}
    return [great, ms]


def test_dont_miss_is_tier_primary_with_why_slots():
    """Track B4: the shelf is the top slice of the full ranking — tier beats raw score — and
    every item carries a prefilled why + a tier3 slot marker."""
    out = R._dont_miss_md(_dm_cands(), limit=1)
    md = "\n".join(out)
    assert "## Don't miss" in md
    assert "MustSee3" in md and "Great9" not in md      # must-see (score 3) beats great (score 9)
    assert "Rare LA date." in md                        # curator note preferred as the why
    assert "<!-- tier3:why" in md


def test_around_md_excludes_slate_and_caps():
    rows = [{"key": f"k{i}", "title": f"Civic{i}", "venue": "City", "iso_date": "2026-06-2" + str(i % 8),
             "signals": ["civic"], "link": None} for i in range(15)]
    out = R._around_md(rows, slate_keys={"k0"}, limit=12)
    md = "\n".join(out)
    assert "## Around town" in md and "not ranked to taste" in md
    assert "Civic0" not in md                           # already in the slate -> excluded
    assert md.count("- `") == 12                        # cap holds
    assert R._around_md([], set()) == []                # empty -> section omitted entirely


def test_consolidated_sections_follow_prefs_order():
    """The renderer honors digest.yaml `sections` (Track B4): inclusion, order, and the intro
    slot marker; day_by_day is never droppable."""
    cands = _dm_cands()
    doc = {"today": "2026-06-17", "meta": {}}
    md = R.render_consolidated_md("2026-06-17", [("Next two weeks", cands)], [], doc,
                                  dont_miss=R._dont_miss_md(cands),
                                  around=R._around_md([{"key": "x", "title": "Marathon",
                                                        "iso_date": "2026-06-21",
                                                        "signals": ["civic"], "link": None,
                                                        "venue": "DTLA"}], set()))
    assert "<!-- tier3:intro -->" in md
    assert md.index("## Don't miss") < md.index("## Next two weeks") \
        < md.index("## Around town") < md.index("## On the radar")
    # a prefs list that drops everything optional still renders the body
    md2 = R.render_consolidated_md("2026-06-17", [("Next two weeks", cands)], [], doc,
                                   dont_miss=R._dont_miss_md(cands), around=None,
                                   order=["day_by_day"])
    assert "## Don't miss" not in md2 and "## On the radar" not in md2
    assert "## Next two weeks" in md2


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
