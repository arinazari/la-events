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


def test_dont_miss_shares_the_front_page_diversity_policy():
    """One Don't-miss policy across surfaces (2026-07-16 follow-up): the digest shelf runs the
    same lib/assemble.top_picks as the dashboard hero, so five club nights can't fill it and a
    judged skip never makes it. Clubs mix sub-lanes (3 underground + 2 afters — the afters
    pair via dead-hours doors, the semantic split's evidence) so the FAMILY cap is what
    binds: 2 underground (lane cap) + 1 afters exhausts club:* at 3."""
    clubs = [{"title": f"Club{i}", "iso_date": "2026-06-20", "venue": f"V{i}", "score": 9 - i,
              "category": "electronic", "links": [],
              **({"start": "2am"} if i in (2, 3) else {}),
              "verdict": {"tier": "must-see", "why": "w"}} for i in range(5)]
    film = {"title": "RepFilm", "iso_date": "2026-06-21", "venue": "Vista", "score": 3,
            "category": "film", "links": [], "verdict": {"tier": "great", "why": "w"}}
    skip = {"title": "SkipMe", "iso_date": "2026-06-22", "venue": "V9", "score": 12,
            "category": "film", "links": [], "verdict": {"tier": "skip", "why": "w"}}
    picked = R._dont_miss_events(clubs + [film, skip])
    titles = [e["title"] for e in picked]
    assert "RepFilm" in titles                          # diversity: the film outlives lower clubs
    assert "SkipMe" not in titles                       # judged skip excluded
    assert sum(1 for t in titles if t.startswith("Club")) == 3   # family cap binds at 3


def test_dont_miss_collapses_multi_night_runs():
    """A residency/run enters the shelf ONCE via its best night (series_of=series_key wiring —
    title+venue for non-film), so a 15-night run can't eat several shelf slots."""
    run = [{"title": "Warehouse Residency", "iso_date": f"2026-06-{19 + i}", "venue": "Vault",
            "score": 9 - i, "category": "electronic", "links": [],
            "verdict": {"tier": "must-see", "why": "w"}} for i in range(3)]
    other = {"title": "OtherNight", "iso_date": "2026-06-20", "venue": "Elsewhere", "score": 2,
             "category": "live music", "links": [], "verdict": {"tier": "solid", "why": "w"}}
    picked = R._dont_miss_events(run + [other])
    assert [e["iso_date"] for e in picked if e["title"] == "Warehouse Residency"] == ["2026-06-19"]
    assert any(e["title"] == "OtherNight" for e in picked)


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
    # the invisible one-sentence take slot precedes the intro slot — the feed build lifts the
    # filled teaser (+ the doc date) into front_page.take; the unfilled scaffold yields no take
    assert md.index("<!-- take: -->") < md.index("<!-- tier3:intro -->")
    assert md.index("## Don't miss") < md.index("## Next two weeks") \
        < md.index("## Around town") < md.index("## On the radar")
    # a prefs list that drops everything optional still renders the body
    md2 = R.render_consolidated_md("2026-06-17", [("Next two weeks", cands)], [], doc,
                                   dont_miss=R._dont_miss_md(cands), around=None,
                                   order=["day_by_day"])
    assert "## Don't miss" not in md2 and "## On the radar" not in md2
    assert "## Next two weeks" in md2


def test_day_groups_key_off_lane_not_source_category():
    """The fix for the 'Other' misfile: an RA warehouse bill arrives with a useless source
    category but must land under Electronic & dance (lane club:*). A TBA warehouse MAIN
    event (11pm doors) is underground — the default club lane, no sub-lane chip — while a
    genuine post-close party gets the afters chip; a verdict lane override beats the tags."""
    ra = {"title": "WORK presents: Ken Ishii", "iso_date": "2026-06-19", "start": "23:00",
          "score": 8, "rating": 4, "venue": "TBA - Los Angeles", "category": "Event",
          "sources": ["ra"], "links": [], "afterhours": True}
    afters = {"title": "Nightshift After Hours", "iso_date": "2026-06-19", "start": "11pm-6am",
              "score": 7, "rating": 4, "venue": "The Lexington", "category": "Event",
              "sources": ["ra"], "links": [], "afterhours": True}
    misc = {"title": "Some Expo", "iso_date": "2026-06-19", "start": "10:00", "score": 4,
            "rating": 4, "venue": "Convention Center", "category": "Miscellaneous",
            "sources": ["ticketmaster"], "links": []}
    md = R.render_markdown({"today": "2026-06-17", "candidates": []}, [ra, afters, misc])
    assert "**Electronic & dance**" in md and "**Elsewhere**" in md
    assert md.index("**Electronic & dance**") < md.index("Ken Ishii") < md.index("**Elsewhere**")
    assert "afters" not in md.split("Ken Ishii")[1].split("\n")[0]
    assert "afters" in md.split("Nightshift")[1].split("\n")[0]
    # verdict lane override wins over tags
    lm = {"title": "Secret Rave", "iso_date": "2026-06-20", "start": "22:00", "score": 6,
          "rating": 4, "venue": "Somewhere", "category": "music", "sources": ["dice"],
          "links": [], "verdict": {"tier": "great", "lane": "club:afters", "why": "x"}}
    md2 = R.render_markdown({"today": "2026-06-17", "candidates": []}, [lm])
    assert "**Electronic & dance**" in md2 and "**Live music**" not in md2


def test_tier_scaled_rendering_and_also_row():
    """rating>=4 gets the two-line entry; rating 3 gets one line with the verdict why inline;
    rating<=2 collapses into the day's Also: row."""
    full = {"title": "Headliner", "iso_date": "2026-06-19", "start": "21:00", "score": 9,
            "rating": 5, "venue": "V", "category": "electronic", "links": [],
            "enrichment": {"curator_note": "The one to build the night around."}}
    comp = {"title": "SolidPick", "iso_date": "2026-06-19", "start": "22:00", "score": 5,
            "rating": 3, "venue": "V2", "category": "electronic", "links": [],
            "verdict": {"tier": "solid", "why": "fine bill, nothing rare"},
            "enrichment": {"curator_note": "Should not print — compact drops the note."}}
    tail = {"title": "TailEvent", "iso_date": "2026-06-19", "start": "20:00", "score": 1,
            "rating": 2, "venue": "V3", "category": "electronic",
            "links": [{"source": "ra", "url": "https://ra.co/e/9"}]}
    md = R.render_markdown({"today": "2026-06-17", "candidates": []}, [full, comp, tail])
    assert "The one to build the night around." in md
    assert "— *fine bill, nothing rare*" in md                     # inline why, same line
    assert "Should not print" not in md                            # compact = one line only
    assert "*Also:* [TailEvent](https://ra.co/e/9) (V3)" in md     # collapsed tail
    # a day of ONLY tail picks still promotes its best to a real line
    md2 = R.render_markdown({"today": "2026-06-17", "candidates": []}, [tail])
    assert "*Also:*" not in md2 and "TailEvent" in md2


def test_dont_miss_blurbs_not_repeated_in_day_body():
    """A Don't-miss pick appears in the day body starred but note-free (cross-reference,
    not verbatim repetition)."""
    ev = {"title": "BigNight", "iso_date": "2026-06-19", "start": "21:00", "score": 9,
          "rating": 5, "venue": "V", "category": "electronic", "links": [],
          "enrichment": {"curator_note": "Once-a-year booking."}}
    dm = R._dont_miss_md([ev])
    keys = frozenset(R.event_key(e) for e in R._dont_miss_events([ev]))
    md = R.render_consolidated_md("2026-06-17", [("Next two weeks", [ev])], [],
                                  {"today": "2026-06-17", "meta": {}},
                                  dont_miss=dm, dm_keys=keys)
    assert md.count("Once-a-year booking.") == 1                   # shelf only
    assert md.count("BigNight") == 2                               # shelf + day body


def test_weekends_ahead_compressed_with_pointer():
    evs = [{"title": f"Ev{i}", "iso_date": "2026-06-27", "start": "20:00", "score": 10 - i,
            "rating": 3, "venue": "V", "category": "electronic", "links": []}
           for i in range(6)]
    out = R._weekends_md(evs)
    md = "\n".join(out)
    assert "### Weekend of Fri 6/26" in md                         # Sat 6/27 anchors to Fri 6/26
    assert md.count("- `") == R.WEEKEND_TOP                        # top picks only
    assert "plus 2 more that weekend" in md
    assert "weekends/2026-06-26.md" in md                          # pointer to the full file
    assert "(+" not in md.split("\n")[1]                           # single-date: no dates suffix


def test_ops_banner_lives_in_footer_not_lede():
    md = R.render_consolidated_md("2026-06-17", [("Next two weeks", _dm_cands())], [],
                                  {"today": "2026-06-17", "meta": {}},
                                  notice={"status": "expired", "days": 0},
                                  dont_miss=R._dont_miss_md(_dm_cands()))
    assert "Posh token expired" in md
    assert md.index("## Don't miss") < md.index("Posh token expired")   # after the content
    assert md.index("\n---\n") < md.index("Posh token expired")         # in the footer block


def test_dont_miss_urgency_chips():
    tiered = {"title": "TieredShow", "iso_date": "2026-06-19", "venue": "V", "score": 9,
              "price": "$35 b4 11 / $47", "category": "electronic", "links": [],
              "verdict": {"tier": "must-see", "why": "w"}}
    tba = {"title": "TbaShow", "iso_date": "2026-06-20", "venue": "TBA - Los Angeles",
           "score": 8, "category": "electronic", "links": [],
           "verdict": {"tier": "must-see", "why": "w"}}
    md = "\n".join(R._dont_miss_md([tiered, tba]))
    assert "🎟 tiered pricing — buy early" in md
    assert "📍 location TBA — watch for the drop" in md


def test_tonight_and_tomorrow_section():
    ev_today = {"title": "TonightShow", "iso_date": "2026-06-17", "start": "21:00", "score": 8,
                "rating": 4, "venue": "V", "category": "electronic", "links": []}
    ev_tom = {"title": "TomorrowShow", "iso_date": "2026-06-18", "start": "20:00", "score": 7,
              "rating": 3, "venue": "V2", "category": "electronic", "links": []}
    ev_far = {"title": "FarShow", "iso_date": "2026-06-25", "start": "20:00", "score": 9,
              "rating": 5, "venue": "V3", "category": "electronic", "links": []}
    out = R._tonight_md([ev_today, ev_tom, ev_far], "2026-06-17")
    md = "\n".join(out)
    assert "## Tonight & tomorrow" in md and "<!-- tier3:call -->" in md
    assert "`Today 9pm`" in md and "`Tomorrow 8pm`" in md
    assert "FarShow" not in md                                     # 48h window only
    # a run spanning both nights lists once (today), and no events -> no section
    run = [dict(ev_today, title="Run"), dict(ev_today, title="Run", iso_date="2026-06-18")]
    md2 = "\n".join(R._tonight_md(run, "2026-06-17"))
    assert md2.count("Run") == 1 and "`Today" in md2
    assert R._tonight_md([ev_far], "2026-06-17") == []


def test_changes_section_lists_new_and_updated():
    old_ref = R.FETCH_REF
    R.FETCH_REF = "2026-06-17"
    try:
        new = {"title": "BrandNew", "iso_date": "2026-06-19", "venue": "V", "score": 6,
               "rating": 3, "category": "electronic", "links": [], "first_seen": "2026-06-17"}
        upd = {"title": "MovedShow", "iso_date": "2026-06-20", "venue": "V2", "score": 5,
               "rating": 3, "category": "electronic", "links": [], "first_seen": "2026-06-01",
               "updated_at": "2026-06-17", "changed_fields": ["lineup"]}
        quiet = {"title": "OldShow", "iso_date": "2026-06-21", "venue": "V3", "score": 5,
                 "rating": 3, "category": "electronic", "links": [], "first_seen": "2026-06-01"}
        md = "\n".join(R._changes_md([new, upd, quiet]))
        assert "## What changed" in md
        assert "**New to the slate**" in md and "🆕" in md and "BrandNew" in md
        assert "**Updated**" in md and "MovedShow" in md and "lineup" in md
        assert "OldShow" not in md
        assert R._changes_md([quiet]) == []                        # quiet day -> omitted
        # a newly announced multi-night run is ONE row (+N more dates), not one per night
        run = [dict(new, iso_date=d, date=d) for d in ("2026-06-19", "2026-06-20", "2026-06-21")]
        md2 = "\n".join(R._changes_md(run))
        assert md2.count("BrandNew") == 1 and "(+2 more dates)" in md2
    finally:
        R.FETCH_REF = old_ref


def test_consolidated_carries_new_sections_and_blueprint_slots():
    cands = _dm_cands()   # both events fall on 2026-06-19/20 (Fri/Sat)
    doc = {"today": "2026-06-17", "meta": {}}
    md = R.render_consolidated_md("2026-06-17", [("Next two weeks", cands)], [], doc,
                                  dont_miss=R._dont_miss_md(cands),
                                  tonight=["## Tonight & tomorrow\n", "<!-- tier3:call -->", ""],
                                  changes=["## What changed\n", "- x", ""])
    assert md.index("## Tonight & tomorrow") < md.index("## Don't miss") \
        < md.index("## What changed") < md.index("## Next two weeks")
    assert "<!-- tier3:blueprint 2026-06-19 -->" in md             # Friday gets a slot
    assert "<!-- tier3:blueprint 2026-06-20 -->" in md             # Saturday too
    # weekday days don't (shift the events to a Tuesday)
    tue = [dict(c, iso_date="2026-06-16") for c in cands]
    md2 = R.render_consolidated_md("2026-06-15", [("Next two weeks", tue)], [], doc)
    assert "tier3:blueprint" not in md2


def test_radar_rows_carry_gloss_slots():
    rows = [{"key": "rk1", "title": "Fest", "venue": "Park", "iso_date": "2026-08-22",
             "signals": ["festival"], "link": None}]
    md = "\n".join(R._radar_md(rows))
    assert "<!-- tier3:gloss rk1 -->" in md


def test_lane_of_applies_event_lane_guards():
    """_lane_of delegates to assemble.event_lane: a cached bare-family 'live-music' override on
    a hall-scale show refines to live-music:big (so the 'big venue' chip fires), and an
    off-vocab cached lane is ignored instead of flowing into the digest grouping."""
    base = {"title": "Gipsy Kings", "venue": "Greek Theatre", "date": "2026-08-01",
            "tags": {"type": "live-music", "scale": "arena", "vibe": [], "setting": [], "genre": []}}
    assert R._lane_of({**base, "verdict": {"lane": "live-music"}}) == "live-music:big"
    assert R._lane_of({**base, "verdict": {"lane": "bogus:lane"}}) == "live-music:big"
    assert R._lane_of({**base, "verdict": {"lane": "club:mainstream"}}) == "club:mainstream"


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
