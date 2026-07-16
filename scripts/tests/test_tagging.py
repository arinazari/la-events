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


# ── watch parties, live-room guard, A&T ordering (the type-leak fixes) ────────────
def test_watch_party_is_community_not_music():
    """World Cup finals at a music venue is a sports event — from ANY branch."""
    assert T.tag_event(ev(category="electronic", sources=["ra"], venue="The Redwood Bar",
                          title="World Cup Final Watch Party"))["type"] == "community"
    assert T.tag_event(ev(category="Music", venue="Zebulon",
                          title="FIFA World Cup 2026 - Semi-Finals"))["type"] == "community"


def test_live_room_guard_beats_club_source_forcing():
    """RA lists every event at rock dives: a band bill at a known live room is live-music
    even via the ra/19hz/posh short-circuit — unless the title carries a real club signal."""
    band = ev(category="electronic", sources=["ra"], venue="The Redwood Bar And Grill",
              title="Boozewa, Jr Juggernaut")
    assert T.tag_event(band)["type"] == "live-music"
    dj = ev(category="electronic", sources=["ra"], venue="The Redwood Bar And Grill",
            title="The Hustle ~ Disco Party!")
    assert T.tag_event(dj)["type"] == "club"
    # …and an electronic genre keyword (incl. the 19hz annotation) also keeps it club
    tech = ev(category="electronic", sources=["19hz"],
              venue="The Mint (Los Angeles) tech house", title="Some Night")
    assert T.tag_event(tech)["type"] == "club"


def test_stage_genre_beats_comedy_blurb():
    """Oklahoma!'s detail calls it 'a comedy' — TM genre Theatre wins; a TITLE-level comedy
    signal still takes the comedy lane (JVN's tour is filed under Theatre)."""
    ok = ev(category="Arts & Theatre", genre="Theatre", title="Rodgers + Hammerstein's Oklahoma!",
            detail="This classic comedy is a triumph")
    assert T.tag_event(ok)["type"] == "stage"
    jvn = ev(category="Arts & Theatre", genre="Theatre",
             title="Jonathan Van Ness: Hot & Healed Comedy Tour")
    assert T.tag_event(jvn)["type"] == "comedy"


def test_lineup_genre_rescues_bare_name_comedians():
    """TM ships bare-name comedians as A&T/None at the event level but genre Comedy at the
    attraction level (fetch_ticketmaster's lineup_genre)."""
    e = ev(category="Arts & Theatre", lineup_genre="Comedy", title="Trevor Noah",
           lineup=["Trevor Noah"])
    assert T.tag_event(e)["type"] == "comedy"
    s = ev(category="Arts & Theatre", lineup_genre="Theatre", title="Some Touring Play")
    assert T.tag_event(s)["type"] == "stage"


def test_music_category_never_keyword_matches_market():
    """'TECHNO NIGHT MARKET' is a club night, not a flea market (the lone old market row)."""
    e = ev(category="party", sources=["posh"], title="TECHNO NIGHT MARKET | HEIDILICIOUS")
    assert T.tag_event(e)["type"] == "club"


def test_at_fallthrough_rescues_stage_and_regional_mexican():
    assert T.tag_event(ev(category="Arts & Theatre", title="BalletNow"))["type"] == "stage"
    assert T.tag_event(ev(category="Miscellaneous", title="The Nutcracker"))["type"] == "stage"
    e = ev(category="Arts & Theatre", title="HERENCIA DE PATRONES ft. BANDA MAGUEY")
    assert T.tag_event(e)["type"] == "live-music"


def test_edm_headliner_gazetteer_types_club():
    e = ev(category="Music", genre="Dance/Electronic", title="Marshmello",
           lineup=["Marshmello"], venue="Ventura County Fairgrounds")
    assert T.tag_event(e)["type"] == "club"
    # a live electronic band on the same TM genre stays live-music
    assert T.tag_event(ev(category="Music", genre="Dance/Electronic",
                          title="Tortoise"))["type"] == "live-music"


# ── genre: venue names no longer mint genres; penalty lanes detectable ────────────
def test_venue_name_does_not_mint_genre():
    """'House of Blues' minted 82 false blues tags (65% of all blues) via the venue field."""
    g = T.tag_event(ev(category="Music", genre="Rock", venue="House of Blues Anaheim",
                       title="The Green - Titles Tour"))["genre"]
    assert "blues" not in g and "house" not in g and "rock" in g
    # intentional venue-derived genre still flows via the explicit gazetteer
    g2 = T.tag_event(ev(category="live_music", venue="Harvelle's", title="Some Band"))["genre"]
    assert "blues" in g2


def test_19hz_venue_annotation_feeds_genre():
    e = ev(category="electronic", sources=["19hz"],
           venue="The Lexington (Los Angeles) tech house, minimal", title="Some Night")
    g = T.tag_event(e)["genre"]
    assert "tech-house" in g and "minimal" in g and "house" not in g


def test_hard_dance_penalty_lanes_detectable():
    g = T.tag_event(ev(category="electronic", title="GIRLS NIGHT OUT HARD TECHNO"))["genre"]
    assert "hard-techno" in g and "techno" not in g
    g2 = T.tag_event(ev(category="electronic", title="Candyland: hardstyle takeover"))["genre"]
    assert "hard-dance" in g2


def test_dub_split_from_dubstep_and_reggae():
    assert "dubstep" in T.tag_event(ev(category="electronic", title="riddim & dubstep night"))["genre"]
    assert "reggae" in T.tag_event(ev(category="electronic", title="dancehall party"))["genre"]
    g = T.tag_event(ev(category="electronic", title="dub techno all night"))["genre"]
    assert "dub" in g and "dubstep" not in g


def test_stage_and_comedy_subtypes():
    assert "theater" in T.tag_event(ev(category="Arts & Theatre", genre="Theatre",
                                       title="Hamilton (Touring)"))["genre"]
    assert "family" in T.tag_event(ev(category="Arts & Theatre", genre="Children's Theatre",
                                      title="Bluey's Big Play"))["genre"]
    assert "improv" in T.tag_event(ev(category="comedy", title="Improv Night"))["genre"]


# ── scale (the venue-tier fact axis) ──────────────────────────────────────────────
def test_scale_tiers():
    assert T.tag_event(ev(category="Music", venue="Hollywood Bowl", title="x"))["scale"] == "arena"
    assert T.tag_event(ev(category="Music", venue="The Wiltern", title="x"))["scale"] == "hall"
    assert T.tag_event(ev(category="Music", venue="Troubadour", title="x"))["scale"] == "room"
    assert T.tag_event(ev(category="jazz", venue="Sam First", title="x"))["scale"] == "bar"
    assert T.tag_event(ev(category="Music", venue="Somewhere New", title="x"))["scale"] is None


# ── vibe fixes ────────────────────────────────────────────────────────────────────
def test_all_night_set_vibe_with_nostalgia_guard():
    v = T.tag_event(ev(category="electronic", title="Markus Schulz (Open To Close)"))["vibe"]
    assert "all-night-set" in v
    v2 = T.tag_event(ev(category="electronic",
                        title="SATISFACTION (2010-2017 EDM bangers All Night Long!)"))["vibe"]
    assert "all-night-set" not in v2


def test_festival_vibe_is_title_only():
    v = T.tag_event(ev(category="electronic", title="HARD Summer Music Festival"))["vibe"]
    assert "festival" in v
    # venue names ('Festival of Arts') and bio prose no longer mint the vibe
    v2 = T.tag_event(ev(category="Arts & Theatre", genre="Theatre", title="Pageant Show",
                        venue="Festival of Arts", detail="a festival awaits them"))["vibe"]
    assert "festival" not in v2


def test_residency_regex_anchored():
    assert "residency" in T.tag_event(ev(category="electronic",
                                         title="Sirens del Sol: Poolside Residency"))["vibe"]
    assert "residency" not in T.tag_event(ev(category="Music", genre="Rock",
                                             title="PRESIDENT: North American Campaign"))["vibe"]


def test_qa_gated_to_screen_and_stage():
    f = ev(category="film", venue="Vidiots", title="The Princess Bride", detail="Q&A with Cary Elwes")
    v = T.tag_event(f)["vibe"]
    assert "q&a" in v and "guest-in-person" in v
    m = ev(category="Music", title="vaultboy", detail="VIP includes Q&A with the artist")
    assert "q&a" not in T.tag_event(m)["vibe"]


def test_matinee_derived_from_start_time():
    assert "matinee" in T.tag_event(ev(category="film", venue="Vista", start="14:00",
                                       title="Godzilla (1954)"))["vibe"]
    assert "matinee" not in T.tag_event(ev(category="film", venue="Vista", start="19:30",
                                           title="Godzilla (1954)"))["vibe"]


def test_free_rsvp_vibe_from_price():
    v = T.tag_event(ev(category="electronic", price="free w/rsvp b4 1 / $23-28", title="x"))["vibe"]
    assert "free" in v and "free-rsvp" in v


# ── region additions ──────────────────────────────────────────────────────────────
def test_region_additions():
    assert T.tag_event(ev(neighborhood="Koreatown"))["region"] == "hollywood"
    assert T.tag_event(ev(neighborhood="Palm Springs"))["region"] == "far"
    assert T.tag_event(ev(neighborhood="Westchester"))["region"] == "westside"
    assert T.tag_event(ev(neighborhood="Elysian Park"))["region"] == "eastside"
    assert T.tag_event(ev(neighborhood="Commerce"))["region"] == "eastside"   # not far


# ── review-pass regressions ───────────────────────────────────────────────────────
def test_watch_guard_spares_club_events():
    """A tournament word alone is not a watch party: DJ brunches, post-match club nights, and
    an EDM act's fan-zone set all stay club; explicit watch/match signals still move."""
    assert T.tag_event(ev(category="party", sources=["posh"],
                          title="Deep House Brunch: World Cup Edition - JJ Flores"))["type"] == "club"
    assert T.tag_event(ev(category="party", sources=["posh"],
                          title="Pisos Sobre Mesas: World Cup After Party"))["type"] == "club"
    assert T.tag_event(ev(category="electronic",
                          title="Loud Luxury - World Cup Fan Zone"))["type"] == "club"
    assert T.tag_event(ev(category="Music",
                          title="FIFA World Cup 2026 - Final"))["type"] == "community"


def test_comedy_subtype_not_from_venue_name():
    g = T.tag_event(ev(category="comedy", venue="Improv Comedy Club-Irvine",
                       title="Joe Comic Live"))["genre"]
    assert "improv" not in g


def test_scale_parish_beats_house_of_blues():
    assert T.tag_event(ev(category="Music", venue="House of Blues Anaheim", title="x"))["scale"] == "hall"
    assert T.tag_event(ev(category="Music", venue="The Parish at House of Blues Anaheim",
                          title="x"))["scale"] == "room"


def test_scale_casino_pool_party_not_arena():
    plain = ev(category="Music", venue="Morongo Casino Resort and Spa", title="Snoop Dogg")
    assert T.tag_event(plain)["scale"] == "arena"
    pool = ev(category="Music", venue="Morongo Casino Resort and Spa", title="Flamingo Friday",
              detail="Pool Parties are back at the Oasis pool featuring the hottest DJs")
    assert T.tag_event(pool)["scale"] is None


def test_live_room_guard_respects_tm_dance_genre():
    """A Dance/Electronic-classified record at a gazetteer live room is still a club act."""
    e = ev(category="Music", sources=["ticketmaster", "ra"], venue="The Fonda",
           genre="Dance/Electronic", title="jigitz (18 and Over)")
    assert T.tag_event(e)["type"] == "club"


def test_standup_podcast_detail_beats_tm_theatre_genre():
    e = ev(category="Arts & Theatre", genre="Theatre", venue="Teragram Ballroom",
           title="The Downside with Gianmarco Soresi",
           detail="Stand-up comedian and lifelong cynic Gianmarco Soresi. This is a podcast.")
    assert T.tag_event(e)["type"] == "comedy"


def test_festival_vibe_gated_off_stage_lanes():
    e = ev(category="Arts & Theatre", genre="Dance", title="The Nutcracker",
           organizers="Pacific Festival Ballet")
    assert "festival" not in T.tag_event(e)["vibe"]


def test_block_party_vibe_not_for_comedy():
    assert "block-party" not in T.tag_event(ev(category="comedy",
                                               title="COMEDY BLOCK PARTY"))["vibe"]


def test_dub_not_from_hyphenated_artist_or_venue_leak():
    e = ev(category="electronic", sources=["ra"], venue="Jungle Hollywood",
           title="Marques Wyatt, Colette at Jungle", lineup=["J-Dub", "Derrick Wize"])
    g = T.tag_event(e)["genre"]
    assert "dub" not in g and "dnb" not in g


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
