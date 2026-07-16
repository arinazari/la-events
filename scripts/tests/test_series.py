#!/usr/bin/env python3
"""Tests for scripts/lib/series.py — series/run consolidation keys + summaries.

Run: python -m pytest scripts/tests/test_series.py   (also runnable directly)
Anchored on the real shapes that motivated the module: the 15-night Odyssey (70mm)
run at the Vista stacking the top of the ranked view, and the same film screening
at two rep houses under different format tags.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.series import (film_core_title, group_series, is_film, series_key,  # noqa: E402
                        series_summary, showtimes_url)


def _film(title, date, venue="Vista Theater", **kw):
    ev = {"title": title, "date": date, "venue": venue, "category": "film",
          "tags": {"type": "film"}}
    ev.update(kw)
    return ev


# ── film core title: per-screening noise stripped, identity kept ────────────────────────

def test_format_noise_stripped():
    assert film_core_title("The Odyssey (70mm)") == "the odyssey"
    assert film_core_title("The Odyssey 70MM") == "the odyssey"
    assert film_core_title("Jaws 50th Anniversary (4K Restoration)") == "jaws"
    assert film_core_title("Heat (1995)") == "heat"


def test_qanda_variants_stripped():
    # dedupe.normalize turns "Q&A" into "qanda" and "Q + A" into "q a" — both must strip.
    assert film_core_title("Blow Out + Q&A") == "blow out"
    assert film_core_title("Blow Out Q and A") == "blow out"


def test_year_in_title_is_identity_not_noise():
    # A parenthesized year is a release tag; a bare year is part of the title.
    assert film_core_title("Blade Runner 2049") != film_core_title("Blade Runner")
    assert film_core_title("Blade Runner (1982)") == "blade runner"


def test_double_feature_titles_stay_distinct():
    a = film_core_title("Alien + Aliens Double Feature 35mm")
    b = film_core_title("Alien (35mm)")
    assert a != b


# ── series_key: films group cross-venue; everything else needs the same venue ───────────

def test_same_film_groups_across_venues_and_formats():
    a = _film("The Odyssey (70mm)", "2026-07-16", "Vista Theater")
    b = _film("The Odyssey 70MM", "2026-07-18", "Egyptian Theatre")
    assert series_key(a) == series_key(b) == "film:the odyssey"


def test_different_films_same_theater_do_not_group():
    a = _film("The Odyssey (70mm)", "2026-07-16")
    b = _film("Starman", "2026-07-17")
    assert series_key(a) != series_key(b)


def test_non_film_groups_by_title_and_venue_only():
    a = {"title": "Sunset Sessions", "venue": "Level 8", "date": "2026-07-17",
         "category": "electronic"}
    b = {"title": "Sunset Sessions", "venue": "Level 8", "date": "2026-07-24",
         "category": "electronic"}
    c = {"title": "Sunset Sessions", "venue": "The Bridge", "date": "2026-07-24",
         "category": "electronic"}
    assert series_key(a) == series_key(b)
    assert series_key(a) != series_key(c)  # same brand, different room = different booking


def test_untitled_records_are_ungroupable():
    assert series_key({"title": "", "venue": "Vista Theater"}) is None


def test_is_film_reads_tags_then_category():
    assert is_film({"tags": {"type": "film"}})
    assert is_film({"category": "Film"})
    assert not is_film({"category": "electronic", "tags": {"type": "club"}})


# ── grouping + the run summary carried by cards ──────────────────────────────────────────

def test_group_series_keeps_only_real_series():
    run = [_film("The Odyssey (70mm)", f"2026-07-{d}") for d in (16, 17, 18)]
    solo = [{"title": "One-off Party", "venue": "El Cid", "date": "2026-07-17",
             "category": "electronic"}]
    groups = group_series(run + solo)
    assert list(groups) == ["film:the odyssey"]
    assert len(groups["film:the odyssey"]) == 3


def test_series_summary_shape():
    members = [
        _film("The Odyssey (70mm)", "2026-07-17", start="22:30",
              links=[{"source": "vista", "url": "https://tix/1"}]),
        _film("The Odyssey (70mm)", "2026-07-16", start="20:00",
              links=[{"source": "vista", "url": "https://tix/0"}], detail="70MM SOLD OUT"),
        _film("The Odyssey 70MM", "2026-07-18", venue="Egyptian Theatre",
              links=[{"source": "jsonld", "url": "https://tix/2"}]),
    ]
    s = series_summary(members)
    assert s["count"] == 3
    assert (s["first"], s["last"]) == ("2026-07-16", "2026-07-18")
    assert s["venues"] == ["Vista Theater", "Egyptian Theatre"]
    assert [e["date"] for e in s["entries"]] == ["2026-07-16", "2026-07-17", "2026-07-18"]
    assert s["entries"][0]["sold_out"] is True          # detail carried the marker
    assert "sold_out" not in s["entries"][1]
    assert s["entries"][2]["url"] == "https://tix/2"


def test_showtimes_url_uses_core_title():
    url = showtimes_url("The Odyssey (70mm)")
    assert "showtimes" in url and "odyssey" in url and "70mm" not in url


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
