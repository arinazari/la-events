#!/usr/bin/env python3
"""Tests for scripts/lib/scoring.py.

Run: python scripts/tests/test_scoring.py   (also pytest-compatible)
Covers the heuristic against the real taste.yaml/profile.yaml, plus a proof that
profile.yaml is actually consumed (tweaking it changes the score).
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.config import load_taste, load_profile  # noqa: E402
from lib.scoring import score_event, score_to_rating, _scoring_cfg, parse_event_date  # noqa: E402

TASTE = load_taste()
PROFILE = load_profile()


def test_rating_thresholds():
    assert score_to_rating(9, PROFILE) == 5
    assert score_to_rating(8, PROFILE) == 5
    assert score_to_rating(7, PROFILE) == 4
    assert score_to_rating(4, PROFILE) == 3
    assert score_to_rating(2, PROFILE) == 2
    assert score_to_rating(1, PROFILE) == 1
    assert score_to_rating(-3, PROFILE) == 1


def test_tracked_electronic_scores_high():
    ev = {"title": "Peggy Gou all night long", "category": "electronic",
          "venue": "The Bridge", "date": "2026-06-20", "lineup": ["Peggy Gou"]}
    r = score_event(ev, TASTE, PROFILE)
    # +3 electronic, +2 tracked (Peggy Gou), +1 groove ("all night"), +1 Sat
    assert r["score"] >= 7, r
    assert any("tracked artist" in x for x in r["reasons"])


def test_comedy_suppressed_unless_loved():
    base = {"category": "comedy", "venue": "The Improv", "date": "2026-06-18"}
    unloved = score_event({**base, "title": "Open Mic Night"}, TASTE, PROFILE)
    loved = score_event({**base, "title": "Stavros Halkias Live"}, TASTE, PROFILE)
    assert loved["score"] > unloved["score"]
    assert any("favorite comedian" in x for x in loved["reasons"])


def test_penalty_terms_and_far():
    ev = {"title": "Bottle service VIP table night", "category": "party",
          "venue": "A Club", "neighborhood": "Anaheim", "date": "2026-06-19"}
    r = score_event(ev, TASTE, PROFILE)
    assert any("bottle service" in x for x in r["reasons"])
    assert any("far from LA" in x for x in r["reasons"])


def test_profile_is_actually_consumed():
    """Proof the config lift works: overriding the profile changes the score,
    so scoring reads profile.yaml rather than silently using code defaults."""
    ev = {"title": "Some DJ", "category": "electronic", "venue": "X", "date": "2026-06-15"}
    base = score_event(ev, TASTE, PROFILE)["score"]
    bumped_profile = {"scoring": {"category_weights": {"electronic": 99}}}
    bumped = score_event(ev, TASTE, bumped_profile)["score"]
    assert bumped - base == 99 - 3, (base, bumped)  # electronic default weight is 3
    # And the resolved cfg reflects the override.
    assert _scoring_cfg(bumped_profile)["category_weights"]["electronic"] == 99


def test_defaults_match_profile():
    """profile.yaml must transcribe the code defaults verbatim (behavior-preserving)."""
    from lib.scoring import (DEFAULT_GROOVE_TERMS, DEFAULT_EU_TERMS,
                             DEFAULT_PENALTY_TERMS, DEFAULT_FAR_TERMS, DEFAULT_CATEGORY_WEIGHTS)
    cfg = _scoring_cfg(PROFILE)
    assert tuple(cfg["groove"]) == DEFAULT_GROOVE_TERMS
    assert tuple(cfg["eu"]) == DEFAULT_EU_TERMS
    assert tuple(cfg["penalty"]) == DEFAULT_PENALTY_TERMS
    assert tuple(cfg["far"]) == DEFAULT_FAR_TERMS
    assert cfg["category_weights"] == DEFAULT_CATEGORY_WEIGHTS


def test_parse_event_date_tm_utc_evening_is_local_day():
    # Ticketmaster emits a UTC `dateTime`: a 7pm PDT show is 02:00Z the NEXT day. The calendar
    # date must be the LA-local day, not the UTC one. (Regression: TM events landed a day late.)
    assert parse_event_date({"datetime": "2026-06-18T02:00:00Z"}) == date(2026, 6, 17)
    assert parse_event_date({"datetime": "2026-06-18T02:00:00+00:00"}) == date(2026, 6, 17)
    # A noon PDT show (19:00Z same day) is unambiguous either way — sanity.
    assert parse_event_date({"datetime": "2026-06-17T19:00:00Z"}) == date(2026, 6, 17)


def test_parse_event_date_naive_local_is_untouched():
    # DICE/RA emit local wall-clock with no offset -> treated as already-local, never shifted.
    assert parse_event_date({"datetime": "2026-06-20T17:00:00.000"}) == date(2026, 6, 20)
    assert parse_event_date({"date": "2026-06-20"}) == date(2026, 6, 20)
    assert parse_event_date({}) is None


def test_tm_fetcher_normalize_prefers_local_date():
    # The TM fetcher must store the venue-LOCAL date/time, so the pipeline date is the LA day.
    import fetch_ticketmaster as tm  # scripts/ is on the path
    ev = {"name": "Show", "_embedded": {"venues": [{"name": "Troubadour"}]},
          "dates": {"start": {"localDate": "2026-06-17", "localTime": "19:00:00",
                              "dateTime": "2026-06-18T02:00:00Z"}}}
    rec = tm.normalize(ev)
    assert rec["datetime"] == "2026-06-17T19:00:00", rec["datetime"]
    assert parse_event_date(rec) == date(2026, 6, 17)


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
