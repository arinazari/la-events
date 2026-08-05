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


def test_festival_waives_far_penalty():
    """A far-flung club night keeps the -2 geo penalty, but a festival-scale event in the same
    far city is judged on taste (penalty waived): a marquee festival is a worth-the-trip radar
    item, not a far club night. Detection is the explicit `festival: true` flag OR the word
    'festival' in the haystack (mirrors build_radar's festival signal)."""
    far_club = {"title": "Late night warehouse", "category": "party", "venue": "A Club",
                "neighborhood": "Irvine", "date": "2026-08-29"}
    r_club = score_event(far_club, TASTE, PROFILE)
    assert any("far from LA" in x for x in r_club["reasons"]), r_club
    # Same record flagged as a festival -> geo penalty waived (worth exactly +2), with a reason.
    r_flag = score_event({**far_club, "festival": True}, TASTE, PROFILE)
    assert not any("far from LA" in x for x in r_flag["reasons"]), r_flag
    assert any("waived (festival)" in x for x in r_flag["reasons"]), r_flag
    assert r_flag["score"] - r_club["score"] == 2, (r_club["score"], r_flag["score"])
    # Detection also fires off the word "festival" in the title (no explicit flag needed).
    r_word = score_event({**far_club, "title": "Some Music Festival"}, TASTE, PROFILE)
    assert not any("far from LA" in x for x in r_word["reasons"]), r_word


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


def test_taste_yaml_scoring_fallback():
    """A profile with no profile.yaml is scored from its OWN taste.yaml `scoring` block;
    profile.yaml takes precedence per key when both set it."""
    ev = {"title": "Some DJ", "category": "electronic", "venue": "X", "date": "2026-06-15"}
    taste_only = {"scoring": {"category_weights": {"electronic": 7}}}
    # taste.yaml's scoring block drives the weight when profile.yaml is empty.
    assert _scoring_cfg({}, taste_only)["category_weights"]["electronic"] == 7
    base_default = score_event(ev, {}, {})["score"]            # electronic default 3
    from_taste = score_event(ev, taste_only, {})["score"]      # 7 via taste fallback
    assert from_taste - base_default == 7 - 3, (base_default, from_taste)
    # profile.yaml wins over taste.yaml for a key both set.
    prof = {"scoring": {"category_weights": {"electronic": 5}}}
    assert _scoring_cfg(prof, taste_only)["category_weights"]["electronic"] == 5
    # taste fills a key the profile omits.
    assert "zzztest" in _scoring_cfg({}, {"scoring": {"groove_terms": ["zzztest"]}})["groove"]


def test_profile_preserves_code_defaults():
    """profile.yaml is the live, user-editable scoring config (the city-portable knob);
    the DEFAULT_* in scoring.py are the generic fallback used only when a key is absent.
    profile.yaml may EXTEND the baseline — e.g. Ari's 'beach' groove term (commit 8c0229c) —
    but must not silently DROP or CHANGE a baseline default, which would regress scoring with
    no one noticing. So: every code default must still be present; additions are allowed."""
    from lib.scoring import (DEFAULT_GROOVE_TERMS, DEFAULT_EU_TERMS,
                             DEFAULT_PENALTY_TERMS, DEFAULT_FAR_TERMS, DEFAULT_CATEGORY_WEIGHTS)
    cfg = _scoring_cfg(PROFILE)
    for name, default in [("groove", DEFAULT_GROOVE_TERMS), ("eu", DEFAULT_EU_TERMS),
                          ("penalty", DEFAULT_PENALTY_TERMS), ("far", DEFAULT_FAR_TERMS)]:
        dropped = set(default) - set(cfg[name])
        assert not dropped, f"profile.yaml {name}_terms dropped baseline default(s): {sorted(dropped)}"
    changed = {k: (cfg["category_weights"].get(k), v)
               for k, v in DEFAULT_CATEGORY_WEIGHTS.items() if cfg["category_weights"].get(k) != v}
    assert not changed, f"profile.yaml category_weights changed/dropped baseline (got, want): {changed}"


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


def test_film_taste_scores_the_movie_not_just_the_room():
    """taste.yaml `film:` block — a tracked director is +2 and a loved format (70mm/35mm print)
    is +1 each, on top of the venue/category signals. Uses the real taste.yaml (which seeds
    Nolan + 70mm), so this also proves the block is wired through config."""
    base = {"category": "film", "venue": "Vista Theater", "neighborhood": "Los Feliz",
            "date": "2026-07-17", "tags": {"type": "film"}}
    plain = score_event({**base, "title": "The Odyssey"}, TASTE, PROFILE)
    fmt = score_event({**base, "title": "The Odyssey (70mm)"}, TASTE, PROFILE)
    directed = score_event({**base, "title": "The Odyssey (70mm)",
                            "detail": "Christopher Nolan's epic, in true 70mm."}, TASTE, PROFILE)
    assert fmt["score"] == plain["score"] + 1
    assert any("loved film format" in x for x in fmt["reasons"])
    assert directed["score"] == fmt["score"] + 2
    assert any("tracked director" in x for x in directed["reasons"])


def test_film_taste_is_gated_to_film_events():
    """A club night whose blurb mentions '70mm' or a tracked director's name must not collect
    film-taste points — the block only fires on film-typed events."""
    ev = {"title": "Warehouse night — visuals on 70mm loops", "category": "electronic",
          "venue": "TBA", "date": "2026-07-18",
          "detail": "Inspired by Christopher Nolan soundtracks."}
    r = score_event(ev, TASTE, PROFILE)
    assert not any("film format" in x or "tracked director" in x for x in r["reasons"])


def test_film_block_absent_is_a_noop():
    """Profiles without a `film:` block (all friends today) score films exactly as before."""
    taste_nofilm = {k: v for k, v in TASTE.items() if k != "film"}
    ev = {"title": "The Odyssey (70mm)", "category": "film", "venue": "Vista Theater",
          "date": "2026-07-17", "detail": "Christopher Nolan"}
    r = score_event(ev, taste_nofilm, PROFILE)
    assert not any("film format" in x or "tracked director" in x for x in r["reasons"])


def test_tm_date_windows_defeat_the_1000_cap():
    # The far-horizon sweep windows the TM query so no single slice hits the 1000-result cap.
    import fetch_ticketmaster as tm
    from datetime import datetime, timezone
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)            # 181 days
    wins = tm.date_windows(start, end, chunk_days=30)
    assert wins[0][0] == start and wins[-1][1] == end          # fully covers [start, end]
    for (a, b), (c, d) in zip(wins, wins[1:]):
        assert a < b == c < d                                  # contiguous, forward, no gaps/overlap
    assert all((b - a).days <= 30 for a, b in wins)            # every slice under the chunk size
    assert len(wins) == 7                                      # 181 / 30 -> 7 slices
    # The default 21-day horizon collapses to ONE window — behaviour-preserving at the near default.
    assert len(tm.date_windows(start, datetime(2026, 1, 22, tzinfo=timezone.utc), 30)) == 1


# ── 2026-08 event card term ──────────────────────────────────────────────────────

def test_card_term_bounded_and_absent_card_identical():
    ev = {"title": "Somebody", "venue": "The Echo", "category": "music"}
    base = score_event(ev, {}, {})
    carded = score_event(ev, {}, {}, None, card={"draw": 2, "rarity": 1, "lineup_depth": 2})
    assert carded["score"] == base["score"] + 4
    assert any("event card" in r for r in carded["reasons"])
    maxed = score_event(ev, {}, {}, None, card={"draw": 3, "rarity": 2, "lineup_depth": 2})
    assert maxed["score"] == base["score"] + 4, "card term must cap (default card_cap=4)"
    off = score_event(ev, {}, {"scoring": {"card_cap": 0}}, None,
                      card={"draw": 3, "rarity": 2, "lineup_depth": 2})
    assert off["score"] == base["score"], "card_cap 0 disables the term"
    empty = score_event(ev, {}, {}, None, card={"draw": 0})
    assert empty["score"] == base["score"] and not any("event card" in r for r in empty["reasons"])
    assert score_event(ev, {}, {}, None, card=None)["score"] == base["score"]


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
