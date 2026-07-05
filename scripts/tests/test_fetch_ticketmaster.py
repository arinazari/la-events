#!/usr/bin/env python3
"""Tests for scripts/fetch_ticketmaster.py — the night-of date correction.

Run: python scripts/tests/test_fetch_ticketmaster.py   (also pytest-compatible)
TM occasionally files a late-night show under the calendar day of its post-midnight start
(localDate 6/28 @ 03:00) while the URL slug carries the night-of date (.../06-27-2026/event/<id>).
That split the show from every source that bills it night-of and double-listed it in the catalog.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from fetch_ticketmaster import normalize, _nightof_date  # noqa: E402

SLUG = "https://www.ticketmaster.com/dillstradamus-hollywood-california-06-27-2026/event/09006437C99A49D6"


def _ev(local_date, local_time, url):
    return {"id": "09006437C99A49D6", "name": "Dillstradamus", "url": url,
            "dates": {"start": {"localDate": local_date, "localTime": local_time}},
            "_embedded": {"venues": [{"name": "Hollywood Palladium"}], "attractions": []}}


def test_nightof_undoes_post_midnight_roll():
    # 3am set filed on 6/28, slug says 6/27 -> corrected back to the night-of date.
    assert _nightof_date("2026-06-28", "03:00:00", SLUG) == "2026-06-27"
    assert normalize(_ev("2026-06-28", "03:00:00", SLUG))["datetime"].startswith("2026-06-27T")


def test_evening_show_unchanged():
    # Normal 8pm show on its own night: hour >= 6 -> never touched, even with a slug date present.
    assert _nightof_date("2026-06-27", "20:00:00", SLUG) == "2026-06-27"
    assert normalize(_ev("2026-06-27", "20:00:00", SLUG))["datetime"] == "2026-06-27T20:00:00"


def test_no_slug_date_unchanged():
    # Bare /event/<id> URL (no date in slug) -> nothing to correct against, leave localDate as-is.
    bare = "https://www.ticketmaster.com/event/09006437C99A49D6"
    assert _nightof_date("2026-06-28", "03:00:00", bare) == "2026-06-28"
    assert normalize(_ev("2026-06-28", "03:00:00", bare))["datetime"].startswith("2026-06-28T")


def test_only_one_day_gap_corrected():
    # A two-day gap between slug and localDate isn't the roll pattern -> don't touch it.
    far = "https://www.ticketmaster.com/x-los-angeles-california-06-25-2026/event/ABC123DEF456"
    assert _nightof_date("2026-06-28", "03:00:00", far) == "2026-06-28"


def test_missing_time_unchanged():
    assert _nightof_date("2026-06-28", None, SLUG) == "2026-06-28"


# ── Resale-feed (TMR) records: prefer the real point of sale over the dead marketplace URL ──

def _resale_ev(outlets):
    return {"id": "Z7r9jZ1A7-o3_", "name": "Los Angeles Philharmonic",
            "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7-o3_",
            "dates": {"start": {"localDate": "2026-07-11", "localTime": "20:00:00"}},
            "outlets": outlets,
            "_embedded": {"venues": [{"name": "Hollywood Bowl"}], "attractions": []}}


def test_resale_record_prefers_box_office_outlet():
    ev = _resale_ev([{"url": "https://www.hollywoodbowl.com/events/performances/", "type": "venueBoxOffice"},
                     {"url": "https://www.ticketmaster.com/event/Z7r9jZ1A7-o3_", "type": "tmMarketPlace"}])
    n = normalize(ev)
    assert n["url"] == "https://www.hollywoodbowl.com/events/performances/"
    assert n["links"][0] == {"source": "venue", "url": "https://www.hollywoodbowl.com/events/performances/"}
    # marketplace URL kept second — its Z id is dedupe's per-event identity signal
    assert n["links"][1] == {"source": "ticketmaster", "url": "https://www.ticketmaster.com/event/Z7r9jZ1A7-o3_"}


def test_resale_record_without_box_office_untouched():
    n = normalize(_resale_ev([]))
    assert n["url"] == "https://www.ticketmaster.com/event/Z7r9jZ1A7-o3_"
    assert "links" not in n


def test_primary_record_never_rewritten():
    # Non-Z id = primary TM inventory; a venueBoxOffice outlet must NOT displace the working TM URL.
    n = normalize(_ev("2026-06-27", "20:00:00", SLUG) |
                  {"outlets": [{"url": "https://example.com/box", "type": "venueBoxOffice"}]})
    assert n["url"] == SLUG
    assert "links" not in n


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
