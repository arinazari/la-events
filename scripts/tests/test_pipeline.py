#!/usr/bin/env python3
"""Tests for scripts/lib/pipeline.py — the deterministic core transforms.

Run: python scripts/tests/test_pipeline.py   (also pytest-compatible)
Uses a fixed `today` for determinism (the sandbox clock is irrelevant).
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import pipeline as P  # noqa: E402

TODAY = date(2026, 6, 17)


def test_today_la_is_a_date():
    assert isinstance(P.today_la(), date)


def test_normalize_maps_common_shapes():
    raw = {"name": "Warehouse w/ Antal", "venue_name": "TBA",
           "datetime": "2026-06-20T22:30:00", "url": "https://ra.co/events/1",
           "artist": "Antal", "ra_pick": True}
    rec = P.normalize_record(raw, "ra")
    assert rec["title"] == "Warehouse w/ Antal"
    assert rec["venue"] == "TBA"
    assert rec["date"] == "2026-06-20"
    assert rec["start"] == "22:30"
    assert rec["lineup"] == ["Antal"]
    assert rec["links"] == [{"source": "ra", "url": "https://ra.co/events/1"}]
    assert rec["sources"] == ["ra"]
    assert rec["category"] == "electronic"   # SOURCE_CATEGORY default for ra
    assert rec["ra_pick"] is True


def test_normalize_reads_afterhours_flag():
    # Fetchers emit `afterhours_flag` (e.g. RA); normalize must carry it onto `afterhours`
    # so the scorer's warehouse/afterhours boost fires. (Regression: was dropped -> 0%.)
    assert P.normalize_record({"title": "W", "date": "2026-06-20", "afterhours_flag": True}, "ra")["afterhours"] is True
    assert P.normalize_record({"title": "W", "date": "2026-06-20", "afterhours": True}, "ra")["afterhours"] is True
    assert P.normalize_record({"title": "W", "date": "2026-06-20"}, "ra")["afterhours"] is False


def test_normalize_carries_genre_through():
    # Fetchers that classify (Ticketmaster: segment->category, genre->genre) emit a `genre`;
    # normalize must carry it onto the canonical schema so the dashboard's CATEGORY / GENRE
    # line has something to show. (Regression: was dropped -> the genre line was always blank.)
    rec = P.normalize_record({"title": "X", "date": "2026-06-20", "category": "Music", "genre": "Techno"}, "ticketmaster")
    assert rec["genre"] == "Techno"
    # No genre supplied -> key present but None, so the schema stays consistent across sources.
    assert P.normalize_record({"title": "Y", "date": "2026-06-20"}, "ra")["genre"] is None


def test_normalize_synthesizes_price_from_range():
    # Ticketmaster emits price_min/price_max, not a `price` string — synthesize one.
    P_ = P.normalize_record
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 25.0, "price_max": 75.0}, "ticketmaster")["price"] == "$25-75"
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 30, "price_max": 30}, "ticketmaster")["price"] == "$30"
    assert P_({"title": "X", "date": "2026-06-20", "price_min": 0, "price_max": 0}, "ticketmaster")["price"] == "free"
    assert P_({"title": "X", "date": "2026-06-20", "price": "$10"}, "19hz")["price"] == "$10"  # explicit wins
    assert P_({"title": "X", "date": "2026-06-20"}, "dice")["price"] is None


def test_normalize_passes_through_canonical_links():
    raw = {"title": "X", "date": "2026-06-20", "venue": "Y",
           "links": [{"source": "dice", "url": "https://dice.fm/e/1"}], "category": "live_music"}
    rec = P.normalize_record(raw, "dice")
    assert rec["links"] == [{"source": "dice", "url": "https://dice.fm/e/1"}]
    assert rec["category"] == "live_music"


def test_merge_new_dedupes_and_stamps():
    catalog = [{"title": "Midnight Lovers w/ Bradley Zero", "venue": "The Bridge",
                "date": "2026-06-20", "lineup": ["Bradley Zero"],
                "links": [{"source": "ra", "url": "https://ra.co/e/1"}], "sources": ["ra"],
                "first_seen": "2026-06-10", "last_seen": "2026-06-10"}]
    incoming = [
        {"title": "Midnight Lovers Day Party", "venue": "The Bridge LA", "date": "2026-06-20",
         "lineup": ["Bradley Zero"], "links": [{"source": "dice", "url": "https://dice.fm/e/2"}],
         "sources": ["dice"]},                                  # dup of catalog[0]
        {"title": "Totally Different Show", "venue": "Zebulon", "date": "2026-06-21",
         "lineup": [], "links": [], "sources": ["dice"]},        # new
    ]
    merged, stats = P.merge_new(catalog, incoming, TODAY)
    assert len(merged) == 2, [e["title"] for e in merged]
    assert stats["added"] == 1 and stats["merged"] == 1
    dup = next(e for e in merged if "Midnight" in e["title"])
    assert {l["url"] for l in dup["links"]} == {"https://ra.co/e/1", "https://dice.fm/e/2"}
    assert dup["first_seen"] == "2026-06-10"          # survives
    assert dup["last_seen"] == "2026-06-17"           # advances to today
    new = next(e for e in merged if "Different" in e["title"])
    assert new["first_seen"] == "2026-06-17" and new["last_seen"] == "2026-06-17"


def test_expire_past_keeps_future_and_undated():
    cat = [
        {"title": "past", "date": "2026-06-10"},
        {"title": "today", "date": "2026-06-17"},
        {"title": "future", "date": "2026-06-25"},
        {"title": "tba", "date": None},
    ]
    kept, n = P.expire_past(cat, TODAY)
    titles = {e["title"] for e in kept}
    assert n == 1 and titles == {"today", "future", "tba"}


def test_select_candidates_orders_and_windows():
    cat = [
        {"title": "elec", "category": "electronic", "venue": "A", "date": "2026-06-18"},  # +3
        {"title": "thtr", "category": "theater", "venue": "B", "date": "2026-06-19"},     # +2
        {"title": "past", "category": "electronic", "venue": "C", "date": "2026-06-10"},  # excluded
        {"title": "farout", "category": "electronic", "venue": "D", "date": "2026-09-01"},  # window-excluded
    ]
    cand = P.select_candidates(cat, taste={}, profile={}, today=TODAY,
                               window_days=30, top_n=10)
    titles = [c["title"] for c in cand]
    assert titles == ["elec", "thtr"]                 # upcoming, in-window, best-first
    assert all("score" in c and "rating" in c and "reasons" in c for c in cand)


def test_select_candidates_respects_top_n():
    cat = [{"title": f"e{i}", "category": "electronic", "venue": "V", "date": "2026-06-20"}
           for i in range(5)]
    cand = P.select_candidates(cat, {}, {}, today=TODAY, top_n=3)
    assert len(cand) == 3


def test_select_candidates_verdicts_order_the_head():
    """Track B2: with the verdict cache supplied, the editor's tier lifts an event into the
    head over a higher-raw-score unjudged one (rank_score = score + adjust + tier bonus)."""
    cat = [
        {"title": "kw", "category": "electronic", "venue": "A", "date": "2026-06-20"},   # raw +3
        {"title": "ms", "category": "theater", "venue": "B", "date": "2026-06-20"},      # raw +2
    ]
    ms_key = P.event_key({"title": "ms", "venue": "B", "date": "2026-06-20"})
    verdicts = {ms_key: {"tier": "must-see", "adjust": 0}}
    cand = P.select_candidates(cat, {}, {}, today=TODAY, top_n=1, verdicts=verdicts)
    assert [c["title"] for c in cand] == ["ms"]       # 2+6 beats unjudged 3
    # without verdicts, raw score still decides
    cand = P.select_candidates(cat, {}, {}, today=TODAY, top_n=1)
    assert [c["title"] for c in cand] == ["kw"]


def test_clean_detail_strips_html_and_boilerplate():
    raw = "<p>An all-vinyl rooftop party with <b>Antal</b>.</p>\nBuy tickets now!\n21+"
    assert P.clean_detail(raw) == "An all-vinyl rooftop party with Antal."
    assert P.clean_detail("<br><br>") is None          # nothing meaningful survives
    assert P.clean_detail("Tickets on sale Friday") is None  # pure boilerplate line
    assert P.clean_detail("") is None and P.clean_detail(None) is None
    long = "word " * 200
    out = P.clean_detail(long, max_len=50)
    assert len(out) <= 51 and out.endswith("…")        # capped on a word boundary


def test_normalize_sanitizes_detail():
    raw = {"name": "X", "venue": "Y", "date": "2026-06-20",
           "description": "<p>Deep house till late &amp; beyond.</p>"}
    rec = P.normalize_record(raw, "ra")
    assert rec["detail"] == "Deep house till late & beyond."


def _tm(date_s, start, slug, **extra):
    """A minimal TM-linked catalog row carrying the night-of date in its URL slug."""
    return {"title": "Show", "venue": "The Wiltern", "date": date_s, "start": start,
            "sources": ["tm", "ticketmaster"],
            "links": [{"source": "tm",
                       "url": f"https://www.ticketmaster.com/show-los-angeles-california-{slug}/event/ABC"}],
            **extra}


def test_reconcile_full_utc_row_recovers_local_date_and_time():
    # Kid Cudi signature: an evening LA show stored as its UTC dateTime (01:30 'next day').
    # slug 06-26-2026 = night-of; 2026-06-27T01:30Z → 2026-06-26 18:30 PDT.
    cat = [_tm("2026-06-27", "01:30", "06-26-2026")]
    assert P.reconcile_tm_dates(cat) == 1
    assert cat[0]["date"] == "2026-06-26"
    assert cat[0]["start"] == "18:30:00"


def test_reconcile_date_only_roll_keeps_local_time():
    # Stavros signature: venue-local time (19:00) but the date rolled a day forward.
    cat = [_tm("2026-06-26", "19:00:00", "06-25-2026")]
    assert P.reconcile_tm_dates(cat) == 1
    assert cat[0]["date"] == "2026-06-25"
    assert cat[0]["start"] == "19:00:00"           # already local — untouched


def test_reconcile_is_noop_when_slug_matches():
    cat = [_tm("2026-06-25", "19:00:00", "06-25-2026")]
    assert P.reconcile_tm_dates(cat) == 0
    assert cat[0]["date"] == "2026-06-25"


def test_reconcile_ignores_rows_without_a_tm_slug():
    cat = [{"title": "RA show", "date": "2026-06-26", "start": "22:00",
            "links": [{"source": "ra", "url": "https://ra.co/events/123"}]}]
    assert P.reconcile_tm_dates(cat) == 0
    assert cat[0]["date"] == "2026-06-26"           # non-TM dates are never touched


def test_reconcile_only_touches_the_one_day_roll():
    # A genuinely different date (slug says a week earlier) must NOT be clobbered.
    cat = [_tm("2026-06-26", "19:00:00", "06-19-2026")]
    assert P.reconcile_tm_dates(cat) == 0
    assert cat[0]["date"] == "2026-06-26"


def test_reconcile_is_idempotent():
    cat = [_tm("2026-06-27", "01:30", "06-26-2026"),
           _tm("2026-06-26", "19:00:00", "06-25-2026")]
    assert P.reconcile_tm_dates(cat) == 2
    assert P.reconcile_tm_dates(cat) == 0           # second pass finds nothing to fix
    assert [e["date"] for e in cat] == ["2026-06-26", "2026-06-25"]


def test_stale_sources_flags_a_frozen_source_only():
    cat = ([{"sources": ["ticketmaster"], "last_seen": "2026-06-19"} for _ in range(50)]
           + [{"sources": ["ra"], "last_seen": "2026-06-26"} for _ in range(50)]
           + [{"sources": ["tinysrc"], "last_seen": "2026-06-01"} for _ in range(3)])
    stale = P.stale_sources(cat, today=date(2026, 6, 26))
    flagged = {s for s, _d, _n in stale}
    assert "ticketmaster" in flagged                 # 7 days frozen, 50 rows → alarm
    assert "ra" not in flagged                        # refreshed today
    assert "tinysrc" not in flagged                   # below the min_count floor


def test_stale_sources_sees_through_crosslisted_fresh_outliers():
    # A dark source still shows a few fresh rows because another source cross-lists them (19hz/DICE
    # re-list a TM event and refresh its last_seen). The bulk (median) must still flag the outage —
    # a max-last_seen check would let those 5 outliers mask 1418 week-old rows (the real-world bug).
    cat = ([{"sources": ["ticketmaster"], "last_seen": "2026-06-19"} for _ in range(1418)]
           + [{"sources": ["ticketmaster", "dice"], "last_seen": "2026-06-26"} for _ in range(5)])
    stale = dict((s, d) for s, d, _n in P.stale_sources(cat, today=date(2026, 6, 26)))
    assert stale.get("ticketmaster") == 7            # median is still 2026-06-19, not the fresh max


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
