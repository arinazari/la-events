#!/usr/bin/env python3
"""Tests for build_dashboard.build_front_page — the dashboard's editorial home block.

The block is selection-only on top of final_rank (stamped in main() from rank_key). Shape
(Ari, 2026-08-01): two MARQUEE shelves — "Sets and shows" (music) and "Events" (comedy +
one-off happenings) — are the only featured surfaces (hero draws from them alone), plus five
category TABLES: Seasonal and repeating, Movies, Theater, Festivals, FYI.

Run: python scripts/tests/test_front_page.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_dashboard as B  # noqa: E402

TODAY = date(2026, 7, 15)  # a Wednesday -> weekend = Fri 7/17 .. Sun 7/19


def ev(key, iso, lane, rank, tier=None, series=None, rep=None, score=5, vibe=None, scale=None):
    e = {"key": key, "iso_date": iso, "lane": lane, "score": score,
         "is_past": False, "title": key, "venue": "V", "date": iso}
    if rank is not None:
        e["final_rank"] = rank
    if tier:
        e["verdict"] = {"tier": tier}
    if series:
        e["series_key"] = series
        e["series_rep"] = bool(rep)
    if vibe or scale:
        e["tags"] = {"vibe": list(vibe or []), "scale": scale}
    return e


def table(fp, sid):
    return next(t for t in fp["tables"] if t["id"] == sid)


def test_marquee_orders_by_final_rank_skips_skips_and_series_members():
    evs = [
        ev("a", "2026-07-16", "club:underground", 3),
        ev("b", "2026-07-17", "club:underground", 1),
        ev("c", "2026-07-18", "club:underground", 2, tier="skip"),
        ev("d", "2026-07-18", "live-music", 4, series="s1", rep=True),
        ev("e", "2026-07-19", "live-music", None, series="s1", rep=False),
    ]
    fp = B.build_front_page(evs, {}, TODAY)
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    assert sets["near"] == ["b", "a", "d"]   # THE feed rank orders; judged skip excluded,
    assert sets["kind"] == "marquee"         # a series enters via its rep night only


def test_marquee_split_near_vs_ahead():
    """One global-rank cut would starve plan-ahead (two-zone rank_key puts judged/near events
    structurally first) — the near/ahead split is the guarantee."""
    evs = ([ev(f"near{i}", "2026-07-20", "live-music", i + 1) for i in range(3)]
           + [ev("far1", "2026-08-20", "live-music", 50)])
    fp = B.build_front_page(evs, {}, TODAY)
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    assert sets["near"] == ["near0", "near1", "near2"]
    assert sets["ahead"] == ["far1"]


def test_comedy_and_oneoffs_are_events_not_sets():
    evs = [ev("c1", "2026-07-16", "comedy", 1), ev("art1", "2026-07-17", "art", 2),
           ev("club1", "2026-07-18", "club:underground", 3)]
    fp = B.build_front_page(evs, {}, TODAY)
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    events = next(s for s in fp["shelves"] if s["id"] == "events")
    assert sets["near"] == ["club1"]
    assert events["near"] == ["c1", "art1"]


def test_hero_is_lane_capped_and_marquee_only():
    """The hero runs the shared top-picks policy over the marquee pool only: lane-capped for
    diversity, and a top-ranked FILM can never take a featured slot — movies are listed in
    their table, not featured."""
    evs = [ev(f"club{i}", "2026-07-17", "club:underground", i + 2, tier="must-see",
              score=9 - i) for i in range(5)]
    evs += [ev("com1", "2026-07-17", "comedy", 10, tier="great", score=3)]
    evs += [ev("film1", "2026-07-17", "film", 1, tier="must-see", score=9)]
    vmap = {B.event_key(e): e["verdict"] for e in evs}
    fp = B.build_front_page(evs, vmap, TODAY)
    hero = fp["hero"]["twoweeks"]
    assert sum(1 for k in hero if k.startswith("club")) <= B.TOP_PICKS_LANE_CAP
    assert hero[:2] == ["club0", "club1"]  # tier-primary rank order, best clubs first
    assert "com1" in hero                # diversity: comedy outlives lower-ranked club picks
    assert "film1" not in hero           # movies are never featured
    assert "film1" in table(fp, "movies")["keys"]


def test_movies_table_orders_playing_by_closing_then_openings_by_date():
    """Open runs first, closing-soonest (urgency), then upcoming programs/one-nighters by
    opening date — regardless of rank."""
    closing = ev("closing", "2026-07-16", "film", 30, series="f1", rep=True)
    closing["series"] = {"count": 4, "first": "2026-07-10", "last": "2026-07-20"}
    longrun = ev("longrun", "2026-07-16", "film", 1, series="f2", rep=True)
    longrun["series"] = {"count": 20, "first": "2026-07-01", "last": "2026-08-30"}
    opens = ev("opens", "2026-07-25", "film", 2, series="f3", rep=True)
    opens["series"] = {"count": 10, "first": "2026-07-25", "last": "2026-08-10"}
    onenight = ev("onenight", "2026-07-18", "film", 3)
    fp = B.build_front_page([closing, longrun, opens, onenight], {}, TODAY)
    assert table(fp, "movies")["keys"] == ["closing", "longrun", "onenight", "opens"]
    for sh in fp["shelves"]:
        assert not ({"closing", "longrun", "opens", "onenight"}
                    & set(sh["near"] + sh["ahead"]))


def test_theater_table_takes_stage_runs_and_oneoffs():
    run = ev("season", "2026-07-16", "stage", 1, tier="must-see", series="s1", rep=True)
    run["series"] = {"count": 20, "first": "2026-07-14", "last": "2026-08-30"}
    one = ev("premiere", "2026-07-17", "stage", 2)
    fp = B.build_front_page([run, one], {}, TODAY)
    assert table(fp, "theater")["keys"] == ["season", "premiere"]
    assert fp["hero"]["twoweeks"] == []      # stage is never featured
    assert fp["shelves"] == []


def test_standing_series_go_seasonal_but_music_residencies_stay_sets():
    """A weekly market is 'Seasonal and repeating'; a weekly CLUB residency is still music —
    one rep card in Sets and shows (the card wears the run label)."""
    market = ev("flea", "2026-07-19", "market", 5, series="m1", rep=True)
    market["series"] = {"count": 8, "first": "2026-07-19", "last": "2026-09-06"}
    resid = ev("muzique", "2026-07-17", "club:mainstream", 1, series="r1", rep=True)
    resid["series"] = {"count": 6, "first": "2026-07-17", "last": "2026-08-21"}
    fp = B.build_front_page([market, resid], {}, TODAY)
    assert table(fp, "seasonal")["keys"] == ["flea"]
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    assert sets["near"] == ["muzique"]


def test_sparse_series_are_not_seasonal():
    """Density guard: a monthly party (3 nights over 2 months) is dated picks in Events,
    not a standing series."""
    sparse = ev("monthly", "2026-07-20", "community", 1, series="s1", rep=True)
    sparse["series"] = {"count": 3, "first": "2026-07-10", "last": "2026-08-30"}
    fp = B.build_front_page([sparse], {}, TODAY)
    assert table(fp, "seasonal")["keys"] == []
    events = next(s for s in fp["shelves"] if s["id"] == "events")
    assert events["near"] == ["monthly"]


def test_unopened_standing_market_is_still_seasonal():
    """No opened gate here (unlike the old Now-running shelf): a standing market that starts
    next month belongs in the Seasonal table with its next date, not among dated picks."""
    future = ev("nightmarket", "2026-08-10", "market", 1, series="s1", rep=True)
    future["series"] = {"count": 10, "first": "2026-08-10", "last": "2026-10-10"}
    fp = B.build_front_page([future], {}, TODAY)
    assert table(fp, "seasonal")["keys"] == ["nightmarket"]


def test_big_shows_split_by_editor_interest():
    """live-music:big: an editor must-see/great is featured music (Sets and shows); the
    unjudged/solid arena tier — and even judged SKIPS, excluded from every other surface —
    land in FYI, date-sorted."""
    hot = ev("hot", "2026-07-18", "live-music:big", 1, tier="must-see")
    meh = ev("meh", "2026-07-25", "live-music:big", 2, tier="solid")
    unj = ev("unjudged", "2026-07-20", "live-music:big", 3)
    skip = ev("stadium-skip", "2026-07-17", "live-music:big", 4, tier="skip")
    vmap = {B.event_key(e): e.get("verdict") for e in (hot, meh, unj, skip) if e.get("verdict")}
    fp = B.build_front_page([hot, meh, unj, skip], vmap, TODAY)
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    assert sets["near"] == ["hot"]
    assert table(fp, "fyi")["keys"] == ["stadium-skip", "unjudged", "meh"]  # date order
    assert "hot" in fp["hero"]["twoweeks"]


def test_festival_routing_destination_vs_local():
    """Festival-tagged rows split (Ari 2026-08-02): the DESTINATION class (hall/arena scale,
    the big-live lane, or a multi-day run) is table-only and never featured; the LOCAL
    one-day tier (a free block fest, a room-scale arts festival's night) is events-class —
    featured in the Events lane and hero-eligible, while STILL listed in the Festivals
    table (its scan is independent of sections, so the season list stays complete)."""
    fest = ev("hardsummer", "2026-08-01", "club:mainstream", 1, vibe=["festival"], scale="arena")
    block = ev("blockfest", "2026-07-18", "community", 2, vibe=["festival"])
    multi = ev("ohana", "2026-07-20", "live-music", 3, vibe=["festival"], series="oh", rep=True)
    multi["series"] = {"first": "2026-07-20", "last": "2026-07-22", "count": 3}
    club = ev("club1", "2026-07-17", "club:mainstream", 4)
    fp = B.build_front_page([fest, block, multi, club], {}, TODAY)
    assert table(fp, "festivals")["keys"] == ["blockfest", "ohana", "hardsummer"]  # date order, ALL listed
    sets = next(s for s in fp["shelves"] if s["id"] == "sets")
    events = next(s for s in fp["shelves"] if s["id"] == "events")
    for k in ("hardsummer", "ohana"):
        assert k not in sets["near"] + sets["ahead"] + events["near"] + events["ahead"]
        assert k not in fp["hero"]["twoweeks"]
    assert "blockfest" in events["near"]
    assert "blockfest" in fp["hero"]["twoweeks"]
    assert "club1" in sets["near"]


def test_festivals_table_rolls_up_sub_events():
    """A festival's per-night sub-events ("Windgrease Festival: <program>") share ONE table
    row — the earliest night represents the program. Distinct festivals keep their rows, and
    the leading article can't split the group."""
    subs = [ev(f"wg{i}", f"2026-08-{7 + i:02d}", "club:mainstream", i + 2, vibe=["festival"])
            for i in range(3)]
    subs[0]["title"] = "The Windgrease Festival: Full Festival Passes"
    subs[1]["title"] = "Windgrease Festival: Revolving Piano Concert"
    subs[2]["title"] = "Windgrease Festival: Wall of Synthprayer"
    hard = ev("hard", "2026-08-02", "club:mainstream", 1, vibe=["festival"])
    hard["title"] = "HARD Summer Music Festival"
    days = [ev("ow1", "2026-09-26", "club:mainstream", 9, vibe=["festival"]),
            ev("ow2", "2026-09-27", "club:mainstream", 10, vibe=["festival"])]
    days[0]["title"] = "Ocean Way Festival - 09/26 Saturday"    # per-day passes = one program
    days[1]["title"] = "Ocean Way Festival - 09/27 Sunday"
    fp = B.build_front_page(subs + [hard] + days, {}, TODAY)
    assert table(fp, "festivals")["keys"] == ["hard", "wg0", "ow1"]   # date order, one row per festival


def test_radar_leftovers_join_fyi_placed_rows_dont():
    """Radar rows not already placed in a section fold into FYI (resolved via the feed);
    a radar row that IS placed (e.g. a featured set) never duplicates into FYI."""
    placed = ev("placed", "2026-07-17", "club:underground", 1)
    farshow = ev("farshow", "2026-09-20", "other", 2)
    fp = B.build_front_page([placed, farshow], {}, TODAY,
                            radar_rows=[{"key": "placed"}, {"key": "farshow"},
                                        {"key": "ghost"}])
    # only rows NOT placed in any section join FYI; both are placed here, so FYI is empty
    assert table(fp, "fyi")["keys"] == []
    assert fp["radar"] == ["placed", "farshow"]   # the raw join still rides for the chat


def test_take_lifted_from_slot_with_doc_date():
    """The Take rides the feed structurally as {text, date}: the one-sentence teaser inside the
    invisible `<!-- take: … -->` comment slot, plus the doc's own date (so the chat welcome can
    honestly show WHICH day's read it is). An unfilled slot or a free-form (slot-less) doc
    yields None so the page falls back to its clipped lede heuristic."""
    filled = ("# LA Events — 2026-07-15\n*meta*\n\n"
              "<!-- take: Deep-house weekend — the pier goes off Saturday. -->\n"
              "The 2-4 sentence intro paragraph.\n\n## Don't miss\n")
    assert B.digest_take(filled) == {"text": "Deep-house weekend — the pier goes off Saturday.",
                                     "date": "2026-07-15"}
    assert B.digest_take("<!-- take: -->\n<!-- tier3:intro -->\n") is None   # unfilled scaffold
    assert B.digest_take("# Free-form profile digest\n\nJust prose.\n") is None
    assert B.digest_take("") is None
    # a multi-line teaser normalizes to one line; a doc with no dated H1 still yields the text
    assert B.digest_take("<!-- take: two\n   lines -->")["text"] == "two lines"
    assert B.digest_take("<!-- take: x -->")["date"] is None
    # the retired start/end markers never read as a take
    assert B.digest_take("<!-- take:start -->\nprose\n<!-- take:end -->\n") is None
    # an UNCLOSED take comment (LLM fill dropped its -->) must not swallow the next comment
    assert B.digest_take("<!-- take: forgot to close\n<!-- tier3:intro -->\n") is None
    fp = B.build_front_page([], {}, TODAY, take={"text": "the take", "date": "2026-07-15"})
    assert fp["take"] == {"text": "the take", "date": "2026-07-15"}
    assert B.build_front_page([], {}, TODAY)["take"] is None


def test_festivals_watchlist_lift():
    """festivals.yaml -> front_page.festivals: status:past filtered, dated items first (by
    first parseable date), undated annual-watch entries last; build_front_page passes the
    rows through verbatim (and emits [] when none are given)."""
    import os
    import tempfile
    yml = (
        "festivals:\n"
        "  - name: Portola 2026\n"
        "    location: Pier 80, SF\n"
        "    when: 2026-09-26..27\n"
        "    status: on_sale\n"
        "    tickets: https://portola.example\n"
        "    why: >\n      THE one for you.\n"
        "  - name: Old Fest\n"
        "    when: 2025-01-01\n"
        "    status: past\n"
        "  - name: GALA London\n"
        "    when: typically late May\n"
        "    status: annual_watch\n"
        "  - name: Hometown Fest\n"
        "    location: State Historic Park, Los Angeles\n"
        "    scope: travel\n"
        "    when: 2026-10-03\n"
        "    status: announced\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yml)
        p = f.name
    try:
        fests = B.load_festivals(p)
    finally:
        os.unlink(p)
    assert [x["name"] for x in fests] == ["Portola 2026", "Hometown Fest", "GALA London"]
    assert fests[0]["first_date"] == "2026-09-26" and fests[0]["status"] == "on_sale"
    assert fests[0]["why"] == "THE one for you."
    assert fests[0]["scope"] == "travel" and fests[0]["when_pretty"] == "9/26–27"
    assert fests[1]["scope"] == "travel"     # explicit scope beats the LA-location heuristic
    assert fests[2]["first_date"] is None
    assert fests[2]["scope"] == "travel"     # no location -> travel (watch-list skews destination)
    assert B.load_festivals("/nonexistent/festivals.yaml") == []
    fp = B.build_front_page([], {}, TODAY, festivals=fests)
    assert fp["festivals"] == fests
    assert B.build_front_page([], {}, TODAY)["festivals"] == []


def test_windows_shape_and_radar_join():
    w = B._fp_windows(TODAY)
    assert w["today"] == ("2026-07-15", "2026-07-15")
    assert w["weekend"] == ("2026-07-17", "2026-07-19")
    # the NEXT 3 WEEKS lens: through the third Sunday out (7/15 is a Wed → Sun 7/19 + 14d)
    assert w["twoweeks"] == ("2026-07-15", "2026-08-02")
    evs = [ev("a", "2026-08-20", "club:underground", 1)]
    fp = B.build_front_page(evs, {}, TODAY,
                            radar_rows=[{"key": "a"}, {"key": "ghost"}])
    assert fp["radar"] == ["a"]          # joins only keys present in the feed


def test_radar_artifact_freshness():
    """The rails' self-heal trigger: missing, unreadable, wrong-day, or older-than-catalog
    artifacts read as stale; a same-day artifact newer than the catalog reads as fresh."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "radar.json"
        assert not B._radar_artifacts_fresh([p], 0.0, TODAY)                    # missing
        p.write_text(json.dumps({"today": TODAY.isoformat()}))
        assert B._radar_artifacts_fresh([p], 0.0, TODAY)                        # fresh
        assert not B._radar_artifacts_fresh([p], p.stat().st_mtime + 1, TODAY)  # catalog newer
        p.write_text(json.dumps({"today": "2020-01-01"}))
        assert not B._radar_artifacts_fresh([p], 0.0, TODAY)                    # built another day
        p.write_text(json.dumps({"count": 3}))
        assert not B._radar_artifacts_fresh([p], 0.0, TODAY)                    # legacy: no stamp
        p.write_text("not json")
        assert not B._radar_artifacts_fresh([p], 0.0, TODAY)                    # unreadable


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
