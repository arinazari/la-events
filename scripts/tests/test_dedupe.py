#!/usr/bin/env python3
"""Tests for scripts/lib/dedupe.py — the known-duplicate set.

Run: python scripts/tests/test_dedupe.py   (also pytest-compatible)
Anchored on real catalog shapes: links are {source,url} dicts; same venue+date is
NOT enough to merge (distinct events share a room on a night).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.dedupe import is_duplicate, merge, dedupe, normalize, _venue_key, _link_ids  # noqa: E402

# Same real event across three sources (RA / DICE / TM), venue + title variants.
RA = {"title": "Midnight Lovers Day Party w/ Bradley Zero", "venue": "The Bridge",
      "date": "2026-06-20", "lineup": ["Bradley Zero", "Masha Mar"],
      "links": [{"source": "ra", "url": "https://ra.co/events/2415278"}],
      "sources": ["ra"], "ra_pick": True, "detail": "All-afternoon groove."}
DICE = {"title": "Midnight Lovers Day Party", "venue": "The Bridge LA",
        "date": "2026-06-20", "lineup": ["Bradley Zero"],
        "links": [{"source": "dice", "url": "https://dice.fm/event/abc"}],
        "sources": ["dice"], "detail": "Day party."}
TM = {"title": "Midnight Lovers w/ Bradley Zero", "venue": "Bridge",
      "date": "2026-06-20", "lineup": [],
      "links": [{"source": "tm", "url": "https://ticketmaster.com/xyz"}],
      "sources": ["ticketmaster"]}


def test_same_event_across_sources_is_duplicate():
    assert is_duplicate(RA, DICE)
    assert is_duplicate(RA, TM)
    assert is_duplicate(DICE, TM)


def test_distinct_events_same_venue_date_not_duplicate():
    # Three different World Cup parties at one bar the same night (real pattern).
    a = {"title": "FRA VS SEN", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    b = {"title": "ARG VS BRA", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    assert not is_duplicate(a, b)


def test_venue_normalization():
    assert _venue_key("The Echo") == _venue_key("Echo")
    assert normalize("Zebulon & Friends, L.A.") == "zebulon and friends l a"
    a = {"title": "ZEP No Enemies Tour", "venue": "The Echo", "date": "2026-06-19"}
    b = {"title": "ZEP (No Enemies Tour)", "venue": "Echo", "date": "2026-06-19"}
    assert is_duplicate(a, b)


def test_different_dates_not_duplicate():
    a = {"title": "Same Show", "venue": "Zebulon", "date": "2026-06-19", "lineup": []}
    b = {"title": "Same Show", "venue": "Zebulon", "date": "2026-06-26", "lineup": []}
    assert not is_duplicate(a, b)


def test_missing_date_is_conservative():
    a = {"title": "Mystery Warehouse", "venue": "TBA", "lineup": []}
    b = {"title": "Mystery Warehouse", "venue": "TBA", "lineup": []}
    assert not is_duplicate(a, b)  # no date -> don't merge


def test_merge_keeps_all_links_and_richest_fields():
    m = merge(merge(RA, DICE), TM)
    urls = {l["url"] for l in m["links"]}
    assert len(urls) == 3, urls                       # all three ticket links kept
    assert set(m["sources"]) == {"ra", "dice", "ticketmaster"}
    assert m["ra_pick"] is True                        # OR across records
    assert m["detail"] == "All-afternoon groove."      # richest (longest) description
    assert len(m["lineup"]) == 2                        # richest lineup


def test_merge_demotes_tm_resale_link():
    # TM resale-marketplace URLs (/event/Z…) routinely dead-end — after a merge a working link
    # must sit at links[0] (the digest + dashboard surface the first link as THE ticket link).
    tmr = {"title": "LA Phil", "venue": "Hollywood Bowl", "date": "2026-07-11", "lineup": [],
           "links": [{"source": "ticketmaster", "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7-o3_"}]}
    hz = {"title": "LA Phil", "venue": "Hollywood Bowl", "date": "2026-07-11", "lineup": [],
          "links": [{"source": "19hz", "url": "https://www.hollywoodbowl.com/events/performances/1234"}]}
    m = merge(tmr, hz)
    assert m["links"][0]["url"].startswith("https://www.hollywoodbowl.com/")  # working link first
    assert m["links"][-1]["url"].endswith("/event/Z7r9jZ1A7-o3_")             # resale kept (dedupe id)
    # Primary TM links (non-Z ids) are NOT resale and must keep their position.
    tm = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": [],
          "links": [{"source": "ticketmaster", "url": "https://www.ticketmaster.com/event/09006437C99A49D6"}]}
    ra = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": [],
          "links": [{"source": "ra", "url": "https://ra.co/events/111"}]}
    assert merge(tm, ra)["links"][0]["url"].endswith("09006437C99A49D6")


def test_merge_preserves_genre_from_either_record():
    # Genre is sparse (only some sources classify), so a merge must not lose it when the
    # base record lacks one — otherwise backfilling an existing genre-less catalog row from
    # a fresh TM fetch silently drops the genre. (Regression: dashboard genre line went blank.)
    base = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": []}
    tm = {"title": "Show", "venue": "Echo", "date": "2026-06-20", "lineup": [], "genre": "Indie"}
    assert merge(base, tm)["genre"] == "Indie"     # backfilled from the incoming record
    assert merge(tm, base)["genre"] == "Indie"     # kept when the base already carries it


def test_merge_preserves_lineup_genre_from_either_record():
    # Same sparse-field rule for the TM attraction-level genre: the catalog base (always the
    # merge base `a`) never has it until a fetch backfills — dropping it would strand the
    # bare-name comedians in type `other` forever.
    base = {"title": "Trevor Noah", "venue": "Peacock", "date": "2026-08-20", "lineup": []}
    tm = {"title": "Trevor Noah", "venue": "Peacock", "date": "2026-08-20", "lineup": [],
          "lineup_genre": "Comedy"}
    assert merge(base, tm)["lineup_genre"] == "Comedy"
    assert merge(tm, base)["lineup_genre"] == "Comedy"
    assert "lineup_genre" not in merge(base, dict(base))    # stays sparse — no null stamping


def test_dedupe_collapses_cluster():
    merged, report = dedupe([RA, DICE, TM])
    assert len(merged) == 1, [e["title"] for e in merged]
    assert len(report) == 2  # two absorbs into the kept record


# Same festival across sources: titles AND venue strings vary, so the venue+title path misses it.
HARD_FG = {"title": "HARD Summer Music Festival", "venue": "Hollywood Park Grounds",
           "date": "2026-08-01", "lineup": ["Charlotte de Witte", "Chris Lorenzo", "John Summit", "Dom Dolla"],
           "links": [{"source": "fgtix", "url": "https://on.fgtix.com/trk/5oHm"}], "sources": ["fgtix"]}
HARD_RA = {"title": "HARD Summer 2026", "venue": "TBA - Hollywood Park adjacent to SoFi Stadium",
           "date": "2026-08-01", "lineup": ["Amelie Lens", "Charlotte de Witte"],
           "links": [{"source": "ra", "url": "https://ra.co/events/2378909"}], "sources": ["ra"]}


def test_cross_source_festival_is_duplicate():
    assert is_duplicate(HARD_FG, HARD_RA)              # same date + same core name + shared venue token
    m = merge(HARD_FG, HARD_RA)
    assert {l["url"] for l in m["links"]} == {"https://on.fgtix.com/trk/5oHm", "https://ra.co/events/2378909"}
    assert len(m["lineup"]) == 4                        # richest bill kept


def test_festival_different_days_not_duplicate():
    day2 = dict(HARD_FG, date="2026-08-02")             # multi-day fest: each day stays its own row
    assert not is_duplicate(HARD_FG, day2)


def test_different_festivals_same_day_not_duplicate():
    sway = {"title": "Hypnotique Presents: Sway Festival", "venue": "Teragram Ballroom",
            "date": "2026-08-01", "lineup": ["A", "B", "C", "D"]}
    assert not is_duplicate(HARD_FG, sway)              # different core names


def test_same_core_unrelated_venues_not_duplicate():
    # Generic core name + unrelated venues + no TBA -> conservative: don't merge (avoid false merge).
    a = {"title": "Summer Festival", "venue": "The Echo", "date": "2026-08-01", "lineup": ["A", "B", "C", "D"]}
    b = {"title": "Summer Festival", "venue": "Greek Theatre", "date": "2026-08-01", "lineup": ["E", "F", "G", "H"]}
    assert not is_duplicate(a, b)


# ── Ticket-link identity ───────────────────────────────────────────────────────

def test_link_ids_extracts_per_event_ids_case_preserved():
    ev = {"links": [
        {"source": "tm", "url": "https://www.ticketmaster.com/dillstradamus-hollywood-06-27-2026/event/09006437C99A49D6"},
        {"source": "19hz", "url": "https://www.ticketmaster.com/event/09006437C99A49D6"},  # bare form, same id
        {"source": "ra", "url": "https://ra.co/events/2471045"},
        {"source": "posh", "url": "https://posh.vip/e/bass-recovery-party?t=infohz"},       # query stripped
    ]}
    assert _link_ids(ev) == {"tm:09006437C99A49D6", "ra:2471045", "posh:bass-recovery-party"}


def test_link_ids_ignores_tracking_and_generic_links():
    # Promoter tracking links + venue homepages are shared by many events -> never identity.
    ev = {"links": [{"source": "fgtix", "url": "https://on.fgtix.com/trk/R4TZ"},
                    {"source": "site", "url": "https://exchangela.com/"}]}
    assert _link_ids(ev) == set()


def test_link_ids_case_sensitive_for_tm():
    # Real catalog pair: two DIFFERENT shows whose TM ids differ only in the final char's case.
    a = {"links": [{"url": "https://www.ticketmaster.com/event/Z7r9jZ1A7x71F"}]}  # Blues Traveler
    b = {"links": [{"url": "https://www.ticketmaster.com/event/Z7r9jZ1A7x71f"}]}  # Tchaikovsky
    assert not (_link_ids(a) & _link_ids(b))                # must NOT collide


def test_shared_link_merges_despite_divergent_venue_strings():
    # Bass Recovery shape: same posh page, venue strings too different for the fuzzy path.
    posh = {"title": "BASS RECOVERY DAY 1", "venue": "Secret DTLA Warehouse", "date": "2026-06-27",
            "lineup": [], "links": [{"source": "posh", "url": "https://posh.vip/e/bass-recovery"}], "sources": ["posh"]}
    nh = {"title": "Bass Recovery Day 1 (Unofficial Apocalypse Recovery Party)", "venue": "TBA (DTLA/Los Angeles)",
          "date": "2026-06-27", "lineup": [],
          "links": [{"source": "19hz", "url": "https://posh.vip/e/bass-recovery?t=infohz"}], "sources": ["19hz"]}
    assert is_duplicate(posh, nh)
    merged, report = dedupe([posh, nh])
    assert len(merged) == 1, [e["title"] for e in merged]
    assert set(merged[0]["sources"]) == {"posh", "19hz"}


def test_shared_tm_id_across_dates_collapses_to_nightof():
    # Dillstradamus shape: TM filed the post-midnight set on 6/28; 19hz has the night-of 6/27.
    nh = {"title": "Dillon Francis, Flosstradamus", "venue": "Hollywood Palladium", "date": "2026-06-27",
          "lineup": [], "links": [{"source": "19hz", "url": "https://www.ticketmaster.com/event/09006437C99A49D6"}],
          "sources": ["19hz"]}
    tm = {"title": "DILLSTRADAMUS (Dillon Francis B2B Flosstradamus)", "venue": "Hollywood Palladium",
          "date": "2026-06-28", "lineup": ["Dillstradamus"],
          "links": [{"source": "tm", "url": "https://www.ticketmaster.com/dillstradamus-06-27-2026/event/09006437C99A49D6"}],
          "sources": ["ticketmaster"]}
    merged, report = dedupe([nh, tm])
    assert len(merged) == 1, [(e["title"], e["date"]) for e in merged]
    assert merged[0]["date"] == "2026-06-27"            # earliest = night-of date wins
    assert {l["url"] for l in merged[0]["links"]} == {
        "https://www.ticketmaster.com/event/09006437C99A49D6",
        "https://www.ticketmaster.com/dillstradamus-06-27-2026/event/09006437C99A49D6"}


def test_tracking_link_does_not_collapse_multiday_festival():
    # Two-day festival sharing ONE Frontgate tracking link across both nights must stay two rows.
    day1 = {"title": "Day Trip Festival", "venue": "The Queen Mary", "date": "2026-06-27", "lineup": [],
            "links": [{"source": "fgtix", "url": "https://on.fgtix.com/trk/R4TZ"}], "sources": ["ticketmaster"]}
    day2 = dict(day1, date="2026-06-28")
    merged, report = dedupe([day1, day2])
    assert len(merged) == 2, [(e["title"], e["date"]) for e in merged]


# ── Placeholder-venue dedupe (TBA/secret warehouse, no shared link) ──────────────

def test_placeholder_venue_strong_title_merges():
    # Bass Recovery shape: a third source (RA) shares no link and its TBA venue string diverges
    # from the others' — but the title is the same event (one side appends the lineup).
    ra = {"title": "Bass Recovery Day 1 (Unofficial Apocalypse Recovery Party)", "venue": "TBA - DTLA Warehouse",
          "date": "2026-06-27", "lineup": [], "links": [{"source": "ra", "url": "https://ra.co/events/2471045"}],
          "sources": ["ra"]}
    nh = {"title": "Bass Recovery Day 1 (Unofficial Apocalypse Recovery Party) ft Rhino, Iguess, Masterpiece",
          "venue": "Secret DTLA Warehouse", "date": "2026-06-27", "lineup": [],
          "links": [{"source": "19hz", "url": "https://posh.vip/e/bass-recovery"}], "sources": ["19hz"]}
    assert is_duplicate(ra, nh)
    merged, _ = dedupe([ra, nh])
    assert len(merged) == 1, [e["title"] for e in merged]


def test_placeholder_venue_distinct_titles_not_merged():
    # Two DIFFERENT warehouse parties at TBA the same night must NOT merge on the weak venue alone.
    a = {"title": "Butterground", "venue": "TBA - DTLA", "date": "2026-06-27", "lineup": []}
    b = {"title": "Panic Room", "venue": "TBA (Los Angeles) techno", "date": "2026-06-27", "lineup": []}
    assert not is_duplicate(a, b)


def test_placeholder_venue_weak_title_not_merged():
    # Both TBA but the titles aren't a strong match (ratio < 0.85, no substantial substring) -> no merge.
    a = {"title": "Warehouse Techno Night", "venue": "TBA", "date": "2026-06-27", "lineup": []}
    b = {"title": "Warehouse House Party", "venue": "Secret Location", "date": "2026-06-27", "lineup": []}
    assert not is_duplicate(a, b)


def test_real_venue_unaffected_by_placeholder_path():
    # Distinct events at a REAL (non-placeholder) venue keep the strict venue+title requirement.
    a = {"title": "FRA VS SEN", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    b = {"title": "ARG VS BRA", "venue": "Dom Futbola", "date": "2026-06-16", "lineup": []}
    assert not is_duplicate(a, b)


# ── Shared-URL venue identity (the Yaamava / Dane Cook shape) ─────────────────────
# TM registers one room as two venue records and lists the same show once under each: two resale
# records with DIFFERENT Z ids (no shared per-event id) and venue strings the fuzzy path can't
# bridge — but both carry the same venueBoxOffice URL. Real 9/11 catalog pair.

YAAMAVA_THEATER = {"title": "Dane Cook (21+)", "venue": "Yaamava Theater", "date": "2026-09-11",
                   "lineup": ["Dane Cook"],
                   "links": [{"source": "venue", "url": "https://yaamava.com/yaamava-theater"},
                             {"source": "ticketmaster", "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7P3qe"}],
                   "sources": ["ticketmaster"]}
YAAMAVA_RESORT = {"title": "Dane Cook", "venue": "Yaamava Resort & Casino at San Manuel",
                  "date": "2026-09-11", "lineup": ["Dane Cook"],
                  "links": [{"source": "venue", "url": "https://yaamava.com/yaamava-theater"},
                            {"source": "ticketmaster", "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7Pwbd"}],
                  "sources": ["ticketmaster"]}


def test_shared_venue_url_bridges_divergent_venue_names():
    assert is_duplicate(YAAMAVA_THEATER, YAAMAVA_RESORT)
    merged, _ = dedupe([YAAMAVA_THEATER, YAAMAVA_RESORT])
    assert len(merged) == 1, [e["title"] for e in merged]
    m = merged[0]
    assert len({l["url"] for l in m["links"]}) == 3          # box office + both Z links kept
    assert m["links"][0]["url"] == "https://yaamava.com/yaamava-theater"  # resale links demoted


def test_shared_venue_url_needs_title_match():
    # Two different shows selling through the same box office the same night must NOT merge.
    other = dict(YAAMAVA_RESORT, title="Chayanne", lineup=["Chayanne"])
    assert not is_duplicate(YAAMAVA_THEATER, other)


def test_shared_venue_url_needs_same_date():
    # A two-night run shares the box-office URL across both nights; each night stays its own row.
    night2 = dict(YAAMAVA_RESORT, date="2026-09-12")
    assert not is_duplicate(YAAMAVA_THEATER, night2)


def test_shared_editorial_url_is_not_venue_identity():
    # A roundup URL names a LIST of events across venues (real shape: six 7/18 rows at six venues
    # share one discoverlosangeles.com page) — two similarly-titled items must NOT merge on it.
    roundup = "https://www.discoverlosangeles.com/things-to-do/the-best-things-to-do-in-la-this-weekend"
    a = {"title": "Jazz on the Lawn", "venue": "Burton Chace Park", "date": "2026-07-18",
         "lineup": [], "links": [{"source": "editorial", "url": roundup}], "sources": ["editorial"]}
    b = {"title": "Jazz on the Lawn (Santa Monica)", "venue": "Gandara Park", "date": "2026-07-18",
         "lineup": [], "links": [{"source": "editorial", "url": roundup}], "sources": ["editorial"]}
    assert not is_duplicate(a, b)
    # Same page as bare-string links (an accepted link shape) — still not identity.
    assert not is_duplicate(dict(a, links=[roundup]), dict(b, links=[roundup]))


def test_shared_tracking_or_profile_url_is_not_venue_identity():
    # A promoter's tracking link / Instagram profile is carried by EVERY event they run — a festival
    # and its same-day pre-party share one, and must stay two rows.
    fg = {"title": "HARD Summer 2026", "venue": "Hollywood Park Grounds", "date": "2026-08-01",
          "lineup": [], "links": [{"source": "goldenvoice", "url": "https://on.fgtix.com/trk/5oHm"}]}
    pre = {"title": "HARD Summer 2026 Pre Party", "venue": "Academy LA", "date": "2026-08-01",
           "lineup": [], "links": [{"source": "goldenvoice", "url": "https://on.fgtix.com/trk/5oHm"}]}
    assert not is_duplicate(fg, pre)


def test_shared_bare_domain_box_office_is_not_venue_identity():
    # A campus box office (ocfair.com, scfta.org) sells for every hall on the grounds — the same
    # act billed in two rooms the same night must NOT merge on the bare domain.
    amp = {"title": "Queen Nation - A Tribute to Queen", "venue": "Pacific Amphitheatre",
           "date": "2026-08-08", "lineup": ["Queen Nation"],
           "links": [{"source": "venue", "url": "https://ocfair.com"}]}
    hangar = {"title": "Queen Nation", "venue": "The Hangar", "date": "2026-08-08",
              "lineup": ["Queen Nation"], "links": [{"source": "venue", "url": "https://ocfair.com"}]}
    assert not is_duplicate(amp, hangar)
    # Junk URLs that normalize to nothing ('/', whitespace) are not identity either.
    assert not is_duplicate(dict(amp, links=[{"source": "venue", "url": "/"}]),
                            dict(hangar, links=[{"source": "venue", "url": " / "}]))


def test_shared_venue_page_companion_pair_stays_two_rows():
    # Same room's page on both rows, but "X" / "X Afterhours" are two gatherings — the companion
    # guard applies to the venue-page arm just as it does to the placeholder path.
    main = {"title": "Dirty Epic: Hard Techno", "venue": "Catch One", "date": "2026-08-15",
            "lineup": [], "links": [{"source": "venue", "url": "https://catch.one/events/dirty-epic"}]}
    afters = {"title": "Dirty Epic: Hard Techno Afterhours", "venue": "The Basement",
              "date": "2026-08-15", "lineup": [],
              "links": [{"source": "venue", "url": "https://catch.one/events/dirty-epic"}]}
    assert not is_duplicate(main, afters)


# ── One-sided placeholder + shared-headliner escapes (the Recollect Underground shapes) ──────────
# One weekly TBA party, four catalog rows: RA/flyer keeps "TBA - link in bio", 19hz briefly names
# the room (genre-suffixed venue string), posh re-lists under the bare series name — no shared
# ticket ids, venue strings unbridgeable, titles drifting from identical to headliner-only overlap.

RECOLLECT_RA = {"title": "Recollect Underground: LA Riots, Beast, Jacz, Lavenge, Max Rush",
                "venue": "TBA - Location Link in Bio on Instagram @recollectunderground",
                "date": "2026-07-10", "lineup": ["LA Riots", "Lavenge", "Max Rush"],
                "links": [{"source": "ra", "url": "https://ra.co/events/2469039"}],
                "sources": ["ra"], "first_seen": "2026-06-19", "last_seen": "2026-07-10"}
RECOLLECT_REVEAL = {"title": "Recollect Underground: LA Riots, Beast, Jacz, Lavenge, Max Rush",
                    "venue": "Los Globos (Los Angeles) tech house, deep house, minimal",
                    "date": "2026-07-10", "lineup": [],
                    "links": [{"source": "19hz", "url": "https://www.instagram.com/p/DZl9KXzKRBX/"}],
                    "sources": ["19hz"], "first_seen": "2026-06-30", "last_seen": "2026-06-30",
                    "status": "unlisted"}
RECOLLECT_POSH_OLD = {"title": "RECOLLECT UNDERGROUND W/ LA RIOTS",
                      "venue": "The Location will be revealed on the event date",
                      "date": "2026-07-10", "lineup": [],
                      "links": [{"source": "posh", "url": "https://posh.vip/e/recollect-underground-w-la-riots"}],
                      "sources": ["posh"], "first_seen": "2026-07-07", "last_seen": "2026-07-08",
                      "status": "unlisted"}
RECOLLECT_POSH_NEW = {"title": "RECOLLECT UNDERGROUND", "venue": "Warehouse",
                      "date": "2026-07-10", "lineup": [],
                      "links": [{"source": "posh", "url": "https://posh.vip/e/recollect-underground-2"}],
                      "sources": ["posh"], "first_seen": "2026-07-10", "last_seen": "2026-07-10"}


def test_one_sided_placeholder_venue_reveal_merges():
    # Identical titles, one side TBA, the other naming the room: the venue-reveal lifecycle.
    assert is_duplicate(RECOLLECT_RA, RECOLLECT_REVEAL)


def test_one_sided_placeholder_series_name_substring_merges():
    # The bare series name re-list ("RECOLLECT UNDERGROUND" ⊂ the lineup-billed title).
    assert is_duplicate(RECOLLECT_RA, RECOLLECT_POSH_NEW)


def test_both_placeholder_shared_headliner_merges():
    # 7/16 shape: RA and 19hz retitle the same secret party around different names — no strong
    # title match, but RA's billed headliner appears in 19hz's title. Both venues placeholders.
    ra = {"title": "RECOLLECT UNDERGROUND: SPECIAL GUEST CURRY FURY (B-DAY SET)",
          "venue": "TBA - Location Link in Bio on Instagram @recollectunderground",
          "date": "2026-07-16", "lineup": ["JAXX NOVEIRA", "Shredy"],
          "links": [{"source": "ra", "url": "https://ra.co/events/2475747"}], "sources": ["ra"]}
    nh = {"title": "Recollect Underground: Curry Fury Bday Bash, Blerry, Jaxx Noveira, King Leon, Shredy",
          "venue": "TBA (DTLA/Los Angeles) tech house, minimal, deep house",
          "date": "2026-07-16", "lineup": [],
          "links": [{"source": "19hz", "url": "https://posh.vip/e/recollect-underground-curry-fury-bday-bash"}],
          "sources": ["19hz"]}
    assert is_duplicate(ra, nh)


def test_conflicting_platform_ids_veto_headliner_tie():
    # Real 7/11 pair: the headliner's 7pm mini-documentary screening and his 10pm-4am rave, both
    # TBA venues, name shared via lineup/title — but two DISTINCT RA event pages. The platform
    # filing them separately outranks the (weakest) headliner tie.
    rave = {"title": "I LOVE DNB: Jumpin' Jack Frost + Ray Keith", "venue": "TBA",
            "date": "2026-07-11", "lineup": ["Jumpin Jack Frost", "Ray Keith"],
            "links": [{"source": "ra", "url": "https://ra.co/events/2441821"}], "sources": ["ra"]}
    doc = {"title": "Big, Bad & Heavy - Jumpin' Jack Frost Mini-Documentary Screening",
           "venue": "TBA - Worms Music Studio B", "date": "2026-07-11",
           "lineup": ["Jumping Jack Frost"],
           "links": [{"source": "ra", "url": "https://ra.co/events/2482797"}], "sources": ["ra"]}
    assert not is_duplicate(rave, doc)
    # Belt and suspenders: even without the id conflict, the companion-marker guard
    # ("documentary screening" on one side only) blocks the placeholder path.
    assert not is_duplicate(dict(rave, links=[]), dict(doc, links=[]))


def test_one_sided_headliner_alone_does_not_merge():
    # An artist playing a REAL venue can also be billed at someone's TBA afters the same night —
    # the headliner tie only counts when BOTH venues are placeholders.
    show = {"title": "Factory 93 presents: Beltran at Naud St", "venue": "1756 Naud St.",
            "date": "2026-07-11", "lineup": ["Beltran"]}
    tba = {"title": "Warehouse party w/ special guest Beltran", "venue": "TBA - DTLA",
           "date": "2026-07-11", "lineup": []}
    assert not is_duplicate(show, tba)


def test_afterparty_does_not_merge_into_main_event():
    # "X" and "X Afterparty" share a name stem (a ≥15-char substring!) but are two events.
    main = {"title": "Recollect Underground", "venue": "Los Globos", "date": "2026-07-10", "lineup": []}
    afters = {"title": "Recollect Underground Afterparty", "venue": "TBA - DTLA",
              "date": "2026-07-10", "lineup": []}
    assert not is_duplicate(main, afters)


def test_dedupe_collapses_recollect_cluster():
    # All four 7/10 rows fold into one live record: links from every source kept, and the two
    # ghost-flagged (stale) rows must NOT carry their `unlisted` status onto the live merge.
    merged, report = dedupe([RECOLLECT_RA, RECOLLECT_REVEAL, RECOLLECT_POSH_OLD, RECOLLECT_POSH_NEW])
    assert len(merged) == 1, [e["title"] for e in merged]
    m = merged[0]
    assert set(m["sources"]) == {"ra", "19hz", "posh"}
    assert len({l["url"] for l in m["links"]}) == 4
    assert "status" not in m                      # the stale unlisted flags don't ghost the live row
    assert m["first_seen"] == "2026-06-19"
    assert m["last_seen"] == "2026-07-10"


def test_merge_stale_unlisted_flag_does_not_ghost_live_record():
    # Healing an old dupe: the absorbed row went stale (ghost-flagged) while the kept row is still
    # re-seen — the merged record must stay live whichever side is the merge base.
    live = dict(RECOLLECT_RA, price="$10 pre")
    ghost = dict(RECOLLECT_REVEAL, price="$15")
    assert "status" not in merge(live, ghost)
    assert "status" not in merge(ghost, live)
    assert merge(live, ghost)["price"] == "$10 pre"   # volatile follows the fresher-seen side
    assert merge(ghost, live)["price"] == "$10 pre"


def test_merge_new_fetch_still_wins_volatiles():
    # merge_new semantics unchanged: incoming (stamped today) is the fresher side on tie/newer.
    old = {"title": "Show", "venue": "Echo", "date": "2026-07-20", "lineup": [],
           "price": "$10", "last_seen": "2026-07-09"}
    fetched = {"title": "Show", "venue": "Echo", "date": "2026-07-20", "lineup": [],
               "price": "$15", "last_seen": "2026-07-10"}
    assert merge(old, fetched)["price"] == "$15"
    # A fresher unlisted flag DOES stick (the reverse of the ghost case above)…
    assert merge(old, dict(fetched, status="unlisted"))["status"] == "unlisted"
    # …and a stale flag on the catalog side is cleared by a fresh re-listing.
    assert "status" not in merge(dict(old, status="unlisted"), fetched)


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
