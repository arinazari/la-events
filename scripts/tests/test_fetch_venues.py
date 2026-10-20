#!/usr/bin/env python3
"""Tests for the venue-feed fetchers' degrade/cancel contracts (no network — urlopen is stubbed).

Run: python scripts/tests/test_fetch_venues.py   (also pytest-compatible)
- fetch_squarespace: HTML-entity titles decoded; CANCELLED/POSTPONED retitles emitted with
  status "cancelled" (so the catalog row is hidden the same run); a dead site is reported in
  `failed_venues` (so run_digest won't ghost its rows) while live sites still emit.
- fetch_ics: RFC 5545 STATUS:CANCELLED (or a CANCELLED retitle) emitted with status "cancelled".
- fetch_eventbrite: a total outage (no organizer links / no event JSON-LD) exits 1, not "0 events".
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import fetch_eventbrite as EB  # noqa: E402
import fetch_ics as ICS  # noqa: E402
import fetch_squarespace as SQ  # noqa: E402


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_main(mod, argv):
    orig = sys.argv
    sys.argv = [mod.__name__, *argv]
    try:
        return mod.main()
    finally:
        sys.argv = orig


def test_squarespace_decodes_entities_marks_pulled_and_reports_dead_site():
    soon = int((datetime.now(SQ.LA) + timedelta(days=3)).timestamp() * 1000)
    items = [{"title": "Tony Guerrero &amp; Friends", "startDate": soon, "fullUrl": "/e/1"},
             {"title": "CANCELLED Community Care &amp; Self Care", "startDate": soon, "fullUrl": "/e/2"},
             {"title": "POSTPONED: Handmade Design Class", "startDate": soon, "fullUrl": "/e/3"}]

    def fake_urlopen(req, timeout=None):
        if "thesmell" in req.full_url:
            raise URLError("down")
        return _Resp(json.dumps({"items": items}).encode())

    orig = SQ.urlopen
    SQ.urlopen = fake_urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.json"
            assert _run_main(SQ, ["--days", "7", "-o", str(out)]) == 0   # partial ≠ total outage
            doc = json.loads(out.read_text())
    finally:
        SQ.urlopen = orig
    status = {e["title"]: e.get("status") for e in doc["events"]}
    assert status == {"Tony Guerrero & Friends": None,
                      "CANCELLED Community Care & Self Care": "cancelled",
                      "POSTPONED: Handmade Design Class": "cancelled"}
    assert doc["failed_venues"] == ["The Smell"]


def test_ics_marks_cancelled_events():
    now = datetime.now(ICS.LA)
    day = (now + timedelta(days=2)).strftime("%Y%m%d")
    body = (f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:{day}T200000\nSUMMARY:Live Band\nEND:VEVENT\n"
            f"BEGIN:VEVENT\nDTSTART:{day}T210000\nSUMMARY:Pulled Show\nSTATUS:CANCELLED\nEND:VEVENT\n"
            f"BEGIN:VEVENT\nDTSTART:{day}T220000\nSUMMARY:CANCELLED - Late Set\nEND:VEVENT\nEND:VCALENDAR\n")
    got = ICS.parse_feed(body, "Maui Sugar Mill Saloon", "Tarzana", "live_music", now, now + timedelta(days=7))
    assert [(e["title"], e.get("status")) for e in got] == [
        ("Live Band", None), ("Pulled Show", "cancelled"), ("CANCELLED - Late Set", "cancelled")]


def test_eventbrite_total_outage_exits_nonzero():
    """Every organizer page challenged/blocked (no event links) must exit 1, not write 0 events."""
    origs = (EB.organizer_event_links, EB.load_organizers, EB.lj.scrape, EB.time.sleep)
    EB.load_organizers = lambda: ["https://www.eventbrite.com/o/a-123456", "https://www.eventbrite.com/o/b-654321"]
    EB.time.sleep = lambda s: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "o.json")
            EB.organizer_event_links = lambda org: []
            assert _run_main(EB, ["--days", "7", "-o", out]) == 1
            # links found, but no event page carried JSON-LD (challenge pages) -> also an outage
            EB.organizer_event_links = lambda org: [org.replace("/o/", "/e/") + "-tickets-1"]
            EB.lj.scrape = lambda url, source: []
            assert _run_main(EB, ["--days", "7", "-o", out]) == 1
            # a real page with an out-of-window event is NOT an outage
            EB.lj.scrape = lambda url, source: [{"title": "Far", "date": "2099-01-01", "url": url}]
            assert _run_main(EB, ["--days", "7", "-o", out]) == 0
    finally:
        EB.organizer_event_links, EB.load_organizers, EB.lj.scrape, EB.time.sleep = origs


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
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
