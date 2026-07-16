#!/usr/bin/env python3
"""Tests for scripts/lib/tagging.py — the deterministic multi-axis tagger.

Run: python scripts/tests/test_tagging.py   (also pytest-compatible)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import tagging as T  # noqa: E402


def ev(**kw):
    base = {"title": "", "venue": "", "neighborhood": None, "category": "general",
            "lineup": [], "sources": [], "start": None, "price": None}
    base.update(kw)
    return base


# ── type (MECE) ──────────────────────────────────────────────────────────────────
def test_ra_source_is_club_even_when_category_music():
    assert T.tag_event(ev(category="music", sources=["ra"], title="Some DJ"))["type"] == "club"


def test_electronic_category_is_club():
    assert T.tag_event(ev(category="electronic", title="warehouse techno"))["type"] == "club"


def test_ticketmaster_music_is_live_music():
    assert T.tag_event(ev(category="music", sources=["tm"], title="The Band"))["type"] == "live-music"


def test_cinema_keyword_overrides_mislabeled_category():
    # A screening that Ticketmaster tagged `music` must still type as film (real catalog bug).
    e = ev(category="music", venue="2220 Arts + Archives", title="Acropolis Cinema: a screening")
    assert T.tag_event(e)["type"] == "film"


def test_comedy_keyword_and_category():
    assert T.tag_event(ev(category="comedy", title="x"))["type"] == "comedy"
    assert T.tag_event(ev(category="music", title="Standup Night"))["type"] == "comedy"


def test_market_and_workshop_keywords():
    assert T.tag_event(ev(category="general", title="Silver Lake Flea Market"))["type"] == "market"
    assert T.tag_event(ev(category="general", title="Ceramics Workshop"))["type"] == "workshop"


# ── genre ────────────────────────────────────────────────────────────────────────
def test_specific_subgenre_beats_general_house():
    g = T.tag_event(ev(category="electronic", title="a night of tech house"))["genre"]
    assert "tech-house" in g and "house" not in g


def test_warehouse_does_not_match_house():
    g = T.tag_event(ev(category="electronic", title="warehouse rave"))["genre"]
    assert g == ["electronic"]  # no bogus "house" from "warehouse"; falls back to family


def test_club_with_no_subgenre_gets_family_tag():
    assert T.tag_event(ev(category="party", sources=["posh"], title="Friday Night"))["genre"] == ["electronic"]


def test_live_music_genre_from_venue_gazetteer():
    # Bare artist-name title -> venue gazetteer supplies the genre.
    g = T.tag_event(ev(category="live_music", venue="Vibrato Grill Jazz", title="Some Quartet"))["genre"]
    assert "jazz" in g


# ── setting ──────────────────────────────────────────────────────────────────────
def test_rooftop_and_warehouse_settings():
    assert "rooftop" in T.tag_event(ev(category="electronic", title="rooftop sunset session"))["setting"]
    assert "warehouse" in T.tag_event(ev(category="electronic", title="warehouse party"))["setting"]


def test_rep_cinema_venue_sets_cinema():
    assert T.tag_event(ev(category="film", venue="Vidiots", title="A Movie"))["setting"] == ["cinema"]


# ── vibe (the "afterhours"-style cross-cutting flags) ─────────────────────────────
def test_afterhours_from_flag_and_from_late_start():
    assert "afterhours" in T.tag_event(ev(category="electronic", afterhours=True, title="x"))["vibe"]
    assert "afterhours" in T.tag_event(ev(category="electronic", start="23:30", title="x"))["vibe"]


def test_day_party_only_for_daytime_club():
    assert "day-party" in T.tag_event(ev(category="electronic", start="14:00", title="x"))["vibe"]
    assert "day-party" not in T.tag_event(ev(category="music", sources=["tm"], start="14:00", title="x"))["vibe"]


def test_free_and_tba_and_queer_flags():
    assert "free" in T.tag_event(ev(category="electronic", price="free", title="x"))["vibe"]
    assert "tba-location" in T.tag_event(ev(category="electronic", venue="TBA", title="x"))["vibe"]
    assert "queer" in T.tag_event(ev(category="electronic", title="Pride warehouse party"))["vibe"]


def test_ra_pick_becomes_a_vibe():
    assert "ra-pick" in T.tag_event(ev(category="electronic", ra_pick=True, title="x"))["vibe"]


# ── region + near_home ───────────────────────────────────────────────────────────
def test_region_buckets():
    assert T.tag_event(ev(neighborhood="Silver Lake"))["region"] == "eastside"
    assert T.tag_event(ev(neighborhood="Anaheim"))["region"] == "far"
    assert T.tag_event(ev(neighborhood="Los Angeles"))["region"] is None  # generic -> honest null


def test_near_home_reads_profile_scoring_list():
    profile = {"scoring": {"near_home_neighborhoods": ["echo park"]}}
    assert T.tag_event(ev(neighborhood="Echo Park"), profile)["near_home"] is True
    assert T.tag_event(ev(neighborhood="Venice"), profile)["near_home"] is False


# ── profile override + structure ──────────────────────────────────────────────────
def test_profile_extends_venue_gazetteer():
    profile = {"tagging": {"venue_genre": {"My Spot": ["dub"]}}}
    g = T.tag_event(ev(category="live_music", venue="My Spot", title="bare name"), profile)["genre"]
    assert "dub" in g


def test_tag_catalog_stamps_every_record():
    cat = [ev(category="electronic", title="a"), ev(category="music", sources=["tm"], title="b")]
    T.tag_catalog(cat)
    assert all("tags" in r and r["tags"]["type"] in T.TYPES for r in cat)


def test_idempotent():
    e = ev(category="electronic", start="23:00", title="warehouse techno", neighborhood="DTLA")
    once = T.tag_event(e)
    twice = T.tag_event({**e, "tags": once})
    assert once == twice


# ── TM-cased categories + the Arts & Theatre split (the 65%-"other" fix) ─────────
def test_tm_cased_categories_resolve():
    """TM Discovery segments arrive capitalized and used to miss every branch → other."""
    assert T.tag_event(ev(category="Music", sources=["ticketmaster"], title="Osees"))["type"] == "live-music"
    assert T.tag_event(ev(category="Film", title="Some Screening"))["type"] == "film"
    assert T.tag_event(ev(category="jazz", venue="Sam First", title="Trio"))["type"] == "live-music"
    assert T.tag_event(ev(category="dance", title="A Dance Piece"))["type"] == "stage"


def test_tm_music_with_club_signal_still_clubs():
    # The club branch (source/keyword signal) outranks the live-music category mapping.
    assert T.tag_event(ev(category="Music", title="A DJ set in a warehouse"))["type"] == "club"


def test_arts_and_theatre_splits_on_tm_genre():
    assert T.tag_event(ev(category="Arts & Theatre", genre="Comedy", title="Ali Wong"))["type"] == "comedy"
    assert T.tag_event(ev(category="Arts & Theatre", genre="Theatre", title="Hamilton (Touring)"))["type"] == "stage"
    assert T.tag_event(ev(category="Arts & Theatre", genre="Performance Art", title="X"))["type"] == "stage"
    # genre-less A&T: keyword rescue, else honest other (bare-name comedians hide there)
    assert T.tag_event(ev(category="Arts & Theatre", title="The Phantom of the Opera (Touring)"))["type"] == "stage"
    assert T.tag_event(ev(category="Arts & Theatre", title="Trevor Noah"))["type"] == "other"
    assert T.tag_event(ev(category="Arts & Theatre", title="Pageant of the Masters"))["type"] == "art"
    assert T.tag_event(ev(category="Arts & Theatre", title="OC Fair: Concert Series"))["type"] == "community"


def test_venue_last_resort_only_for_signal_less_categories():
    # Undefined/empty category at a music-only room → live-music …
    assert T.tag_event(ev(category="Undefined", venue="The Fonda", title="Ninajirachi"))["type"] == "live-music"
    assert T.tag_event(ev(category="", venue="Zebulon", title="Some Band"))["type"] == "live-music"
    # … but a REAL category never defers to the venue (A&T comedy at a music room stays honest).
    assert T.tag_event(ev(category="Arts & Theatre", venue="The Fonda", title="A Comedian"))["type"] == "other"


def test_detail_blob_noise_cannot_retype_a_concert():
    """A music-category event only retypes off its TITLE/venue: a stray 'screening' or 'dj set'
    buried in the detail must not flip a concert to film/club (Bad Brains' real detail mentions
    a 'partial film screening' between sets)."""
    e = ev(category="Music", title="Bad Brains - 50th Anniversary Celebration",
           venue="The Regent Theater",
           detail="Guest of honor HR. DJ set by Mario C. Partial afro punk film screening.")
    assert T.tag_event(e)["type"] == "live-music"
    # …but a title-level cinema signal still wins (the original rescue case)
    e2 = ev(category="music", title="Acropolis Cinema: a screening", venue="2220 Arts")
    assert T.tag_event(e2)["type"] == "film"
    # and non-music categories keep the broad full-text guard
    e3 = ev(category="general", title="Community Evening",
            detail="a rooftop screening of a classic")
    assert T.tag_event(e3)["type"] == "film"


def test_tm_genre_maps_into_live_vocab():
    g = T.tag_event(ev(category="Music", genre="Hip-Hop/Rap", title="Yeat"))["genre"]
    assert "hip-hop" in g
    g2 = T.tag_event(ev(category="Music", genre="Dance/Electronic", title="Tortoise"))["genre"]
    assert "electronic" in g2
    # keyword hits still lead; the TM call appends
    g3 = T.tag_event(ev(category="Music", genre="Rock", title="a jazz evening"))["genre"]
    assert g3[0] == "jazz" and "rock" in g3


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
