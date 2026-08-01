#!/usr/bin/env python3
"""Tests for scripts/lib/prices.py — the cheapest-ticket finder's deterministic core.

Run: python scripts/tests/test_prices.py   (also pytest-compatible)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.enrich import event_key  # noqa: E402
from lib import prices as PR  # noqa: E402


def _ev(title="Kim Gordon - Play Me Tour", date="2026-08-01", venue="Pacific Electric", **kw):
    return {"title": title, "date": date, "venue": venue, **kw}


def _gt_item(name="Kim Gordon", dt="2026-08-01T20:00:00", venue="Pacific Electric",
             metro="losangeles", total=1900, prefee=1600, url="https://gametime.co/e/1"):
    return {"event": {"name": name, "datetime_local": dt,
                      "min_price": {"total": total, "prefee": prefee}, "seo_url": url},
            "venue": {"name": venue, "metro": metro, "city": "Los Angeles", "state": "CA"}}


# ── search_name ─────────────────────────────────────────────────────────────────

def test_search_name_prefers_headliner():
    assert PR.search_name(_ev(lineup=["Kim Gordon", "SASAMI"])) == "Kim Gordon"


def test_search_name_strips_tour_tail_and_dressing():
    assert PR.search_name(_ev(title="Kim Gordon - Play Me Tour")) == "Kim Gordon"
    assert PR.search_name(_ev(title="An Evening with Herbie Hancock")) == "Herbie Hancock"
    assert PR.search_name(_ev(title="Overmono (DJ set)")) == "Overmono"
    assert PR.search_name(_ev(title="Caribou — Honey Tour")) == "Caribou"


def test_search_name_keeps_plain_titles_whole():
    assert PR.search_name(_ev(title="Silverlake Flea")) == "Silverlake Flea"
    # A dash tail that is NOT tour dressing still splits on the spaced dash…
    assert PR.search_name(_ev(title="Justice - Woven City")) == "Justice"
    # …but never guts a short head into nothing.
    assert PR.search_name(_ev(title="X - Y")) == "X - Y"


# ── compare links / listed price ────────────────────────────────────────────────

def test_compare_links_cover_the_marketplaces_and_quote():
    links = PR.compare_links("Kim Gordon")
    labels = [l["label"] for l in links]
    assert labels == ["StubHub", "SeatGeek", "Gametime", "TickPick", "Vivid Seats"]
    assert all("Kim+Gordon" in l["url"] for l in links)
    assert PR.compare_links("") == []


def test_listed_price_and_free_detection():
    assert PR.listed_price_min(_ev(price="$10 b4 12 / $20-27")) == 10.0
    assert PR.listed_price_min(_ev(price=None)) is None
    assert PR.is_free(_ev(price="free (RSVP)"))
    assert not PR.is_free(_ev(price="free w/rsvp / $16-26"))  # money present -> not free
    assert not PR.is_free(_ev(price="$54+"))


def test_listed_option_anchors_from_catalog_price():
    ev = _ev(price="$32-72", links=[{"source": "ra", "url": "https://ra.co/events/1"}])
    o = PR.listed_option(ev)
    assert (o["source"], o["kind"], o["price"], o["url"]) == ("ra", "listed", 32.0, "https://ra.co/events/1")
    assert PR.listed_option(_ev(price=None)) is None
    free = PR.listed_option(_ev(price="free (RSVP)", sources=["posh"]))
    assert free["price"] == 0.0 and free["source"] == "posh"


# ── gametime matching ───────────────────────────────────────────────────────────

def test_match_gametime_filters_metro_and_date():
    ev = _ev()
    items = [
        _gt_item(dt="2026-09-11T19:00:00"),                  # wrong date
        _gt_item(metro="newyork"),                            # wrong metro
        _gt_item(total=6500, prefee=5500),                    # right
    ]
    hit = PR.match_gametime(ev, items)
    assert hit and hit["event"]["min_price"]["total"] == 6500


def test_match_gametime_prefers_venue_overlap_over_name_only():
    ev = _ev()
    name_only = _gt_item(venue="The Bellwether", total=2500)
    venue_hit = _gt_item(venue="Pacific Electric Bldg", total=4100)
    assert PR.match_gametime(ev, [name_only, venue_hit]) is venue_hit


def test_match_gametime_rejects_unrelated_same_night_show():
    # Same metro + date but neither the venue nor the act matches ours.
    ev = _ev(title="Objekt at 1720", venue="1720", lineup=["Objekt"])
    other = _gt_item(name="Kim Gordon", venue="Pacific Electric")
    assert PR.match_gametime(ev, [other]) is None


def test_gametime_option_converts_cents_and_skips_empty():
    o = PR.gametime_option(_gt_item())
    assert (o["price"], o["prefee"], o["kind"], o["source"]) == (19.0, 16.0, "resale", "gametime")
    assert PR.gametime_option(_gt_item(total=0)) is None


def test_gametime_search_parses_injected_payload():
    payload = json.dumps({"events": [_gt_item()], "venues": []})
    items = PR.gametime_search("kim gordon", fetch=lambda url: payload)
    assert len(items) == 1 and items[0]["venue"]["metro"] == "losangeles"


# ── store: record / prune / price_map ───────────────────────────────────────────

def test_record_replaces_same_source_and_accumulates_others():
    store = {"events": {}}
    ev = _ev()
    PR.record(store, ev, {"source": "gametime", "price": 19.0, "url": "u1"}, checked_at="2026-08-01T01:00:00")
    PR.record(store, ev, {"source": "stubhub", "price": 20.0}, checked_at="2026-08-01T02:00:00")
    PR.record(store, ev, {"source": "gametime", "price": 24.0, "url": "u2"}, checked_at="2026-08-02T01:00:00")
    entry = store["events"][event_key(ev)]
    assert [o["source"] for o in entry["options"]] == ["stubhub", "gametime"]  # cheapest first
    assert entry["options"][1]["price"] == 24.0 and entry["options"][1]["url"] == "u2"
    assert entry["checked_at"] == "2026-08-02T01:00:00"


def test_prune_drops_past_events_only():
    store = {"events": {}}
    PR.record(store, _ev(date="2026-07-30"), {"source": "gametime", "price": 10})
    PR.record(store, _ev(date="2026-08-02"), {"source": "gametime", "price": 12})
    assert PR.prune(store, "2026-08-01") == 1
    assert len(store["events"]) == 1


def test_price_map_sorts_and_stamps():
    store = {"events": {}}
    ev = _ev()
    PR.record(store, ev, {"source": "seatgeek", "price": 31.0}, checked_at="2026-08-01T01:00:00")
    PR.record(store, ev, {"source": "gametime", "price": 19.0, "prefee": 16.0}, checked_at="2026-08-01T01:00:00")
    pm = PR.price_map(store)
    entry = pm[event_key(ev)]
    assert [o["source"] for o in entry["options"]] == ["gametime", "seatgeek"]
    assert entry["checked_at"] == "2026-08-01T01:00:00"
    assert PR.price_map({"events": {"k": {"options": []}}}) == {}


def test_store_roundtrip(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ticket_prices.json"
        store = {"events": {}}
        PR.record(store, _ev(), {"source": "gametime", "price": 19.0})
        PR.save_store(store, p)
        again = PR.load_store(p)
        assert again["events"] == store["events"]
        assert PR.load_store(Path(td) / "missing.json") == {"events": {}}


# ── auto_pool selection ─────────────────────────────────────────────────────────

def _tagged(title, date, venue, type_, price=None, **kw):
    return _ev(title=title, date=date, venue=venue, price=price,
               tags={"type": type_, "genre": [], "setting": [], "vibe": [], "scale": None},
               **kw)


def test_auto_pool_gates_lanes_free_skips_and_window():
    today = "2026-08-01"
    live = _tagged("Kim Gordon", "2026-08-02", "Pacific Electric", "live-music", price="$45", score=6)
    film = _tagged("Odyssey", "2026-08-02", "Vista", "film", score=9)
    free = _tagged("Beatport Live", "2026-08-03", "Secret", "club", price="free (RSVP)", score=8)
    far = _tagged("Portola Warmup", "2026-10-01", "Shrine", "live-music", score=7)
    ghost = _tagged("Ghost", "2026-08-02", "Nowhere", "live-music", score=5, status="unlisted")
    skip = _tagged("Arena Filler", "2026-08-04", "Crypto.com Arena", "live-music", score=4)
    verdicts = {event_key(skip): {"tier": "skip"}}
    pool = PR.auto_pool([live, film, free, far, ghost, skip], verdicts, today, days=21)
    assert [e["title"] for e in pool] == ["Kim Gordon"]


def test_auto_pool_stars_ride_any_horizon_and_lead():
    today = "2026-08-01"
    near = _tagged("Kim Gordon", "2026-08-02", "Pacific Electric", "live-music", score=9,
                   verd=None)
    far_star = _tagged("Portola Sat", "2026-10-01", "Pier 80", "film", score=1)  # off-lane AND far
    pool = PR.auto_pool([near, far_star], {}, today, days=21,
                        starred={event_key(far_star)})
    assert [e["title"] for e in pool] == ["Portola Sat", "Kim Gordon"]


def test_auto_pool_ranks_by_verdict_tier_first():
    today = "2026-08-01"
    a = _tagged("Solid Show", "2026-08-02", "Zebulon", "live-music", score=9)
    b = _tagged("Must See", "2026-08-03", "2220 Arts", "live-music", score=2)
    verdicts = {event_key(a): {"tier": "solid"}, event_key(b): {"tier": "must-see"}}
    pool = PR.auto_pool([a, b], verdicts, today, days=21)
    assert [e["title"] for e in pool] == ["Must See", "Solid Show"]


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ok  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
