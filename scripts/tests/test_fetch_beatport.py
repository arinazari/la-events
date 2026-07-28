#!/usr/bin/env python3
"""Tests for scripts/fetch_beatport.py — the Beatportal listing + event-page JSON-LD path.

Run: python scripts/tests/test_fetch_beatport.py   (also pytest-compatible)
Fixtures mirror the live shapes verified 2026-07-27: unicode slugs in listing hrefs
(urlopen chokes on raw non-ascii), /events/page-<hex> router artifacts and /events?genre
filter links that must NOT be crawled, and the platform's JSON-LD quirks — `offers` is a
bare string (crashed fetch_jsonld.normalize before the guard), no top-level url field,
ticket links buried as <a href> in the description.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import fetch_jsonld as lj  # noqa: E402
from fetch_beatport import (  # noqa: E402
    parse_listing, record_from_rsvp_article, records_from_event_html, rsvp_article_urls)
from lib import pipeline as P  # noqa: E402

LISTING = (
    '<a href="/events/8z1qf6y-beatport-fridays-at-marquee-dayclub-me-n-\u00fc">x</a>'
    '<a href="/events/page-be973187e75fdbf9">rsc artifact</a>'
    '<a href="/events?genres=house">filter link</a>'
    '<a href="/events/8z1qf6y-beatport-fridays-at-marquee-dayclub-me-n-\u00fc">dupe</a>'
    '<a href="https://www.beatportal.com/events/0ogv2j0-keep-hush-x-spurs-house">abs</a>'
)

# Verbatim structure from the live Marquee Dayclub event page (2026-07-27), trimmed.
EVENT_HTML = """<html><head><script type="application/ld+json">{
 "@context": "https://schema.org",
 "@type": "Event",
 "name": "Beatport Fridays at Marquee Dayclub: me n \u00fc",
 "startDate": "2026-08-07T11:00:00-04:00",
 "endDate": "2026-08-07T18:00:00-04:00",
 "offers": " ",
 "performer": "me n \u00fc",
 "location": {
  "@type": "Place",
  "name": "Marquee Dayclub",
  "address": {"@type": "PostalAddress",
              "streetAddress": "3708 S Las Vegas Blvd, Las Vegas, NV 89109, USA"}
 },
 "image": "https://s3.eu-west-1.amazonaws.com/beatport-event-images/b0be2e59.png",
 "description": "<a href=\\"https://tickets.taogroup.com/e/marquee-dayclub-las-vegas-8-7-2026/tickets?utm_name=BEATPORT\\">Get Tickets Directly</a>\\n\\nMarquee Dayclub and Beatport are joining forces.",
 "organizer": {"@type": "Organization", "name": "Beatport US", "url": "artists/8z1qf6y"}
}</script></head><body></body></html>"""

PAGE_URL = "https://www.beatportal.com/events/8z1qf6y-beatport-fridays-at-marquee-dayclub-me-n-%C3%BC"


def test_parse_listing_extracts_encodes_and_dedupes():
    urls = parse_listing(LISTING)
    assert urls == [
        PAGE_URL,  # unicode slug percent-encoded, duplicate collapsed
        "https://www.beatportal.com/events/0ogv2j0-keep-hush-x-spurs-house",
    ]  # page- artifact and ?genres filter link excluded


def test_event_page_to_record():
    (rec,) = records_from_event_html(EVENT_HTML, PAGE_URL)
    assert rec["title"] == "Beatport Fridays at Marquee Dayclub: me n \u00fc"
    assert rec["date"] == "2026-08-07"
    assert rec["venue"] == "Marquee Dayclub"
    assert rec["category"] == "electronic"
    assert rec["lineup"] == ["me n \u00fc"]
    assert rec["organizer"] == "Beatport US"
    assert rec["url"] == PAGE_URL  # JSON-LD has no url field — page URL stamped
    assert rec["id"] == PAGE_URL  # unique per page; a name-keyed id collapses recurring titles
    assert [l["url"] for l in rec["links"]] == [
        PAGE_URL,
        "https://tickets.taogroup.com/e/marquee-dayclub-las-vegas-8-7-2026/tickets?utm_name=BEATPORT",
    ]
    assert rec["price_min"] is None  # offers was a junk string — must not crash or leak


def test_record_survives_pipeline_normalize():
    (rec,) = records_from_event_html(EVENT_HTML, PAGE_URL)
    n = P.normalize_record(rec, "beatport")
    assert n["date"] == "2026-08-07"
    assert n["start"] == "11:00"
    assert n["category"] == "electronic"
    assert n["venue"] == "Marquee Dayclub"
    assert len(n["links"]) == 2  # canonical page + seller link both preserved
    assert n["sources"] == ["beatport"]


def test_jsonld_normalize_tolerates_string_offers():
    # regression: beatportal stamps offers as " " — .get() on a str blew up normalize
    n = lj.normalize({"@type": "Event", "name": "x", "offers": " "}, "beatport")
    assert n["price_min"] is None


# ── Lane 2: "RSVP Now" article drops (Beatport Live free parties) ──────────────
# Modeled on the live 8/6/26 HARD Selects article (the LA event the /events listing
# never carried) and the older Odd Mob post whose doors line has an explicit year.

HOMEPAGE = (
    'href="/articles/1531717-rsvp-now-dj-seinfeld-salute-chloedees-beatport-live-x-hard-selects-takeover"'
    ' rsc:{\\"href\\":\\"/articles/1531717-rsvp-now-dj-seinfeld-salute-chloedees-beatport-live-x-hard-selects-takeover\\"}'
    ' href="/articles/1537686-rsvp-now-ela-minus-b2b-nick-leon-beatport-live-ny"'
    ' href="/articles/1168152-30-years-of-dj-kicks-inside-the-series"'
)

ARTICLE_LA = """<html><head>
<title>RSVP Now: DJ Seinfeld, salute, Chloëdees | Beatport Live x HARD Selects Takeover | Beatportal</title>
<meta property="og:title" content="RSVP Now: DJ Seinfeld, salute, Chloëdees | Beatport Live x HARD Selects Takeover | Beatportal"
<meta property="og:description" content="DJ Seinfeld, salute, and Chloëdees play Beatport Live x HARD Selects in Los Angeles on August 6. RSVP now for the HARD Summer weekend takeover at Beatport’s LA HQ."
<meta property="og:image" content="https://assets.beatportal.com/images/transforms/Beatport-Live-x-HARD-Selects-Takeover-2026.png"
</head><body>
<p>Beatport Live is back in Los Angeles on August 6.</p>
<a href="https://drop.cobrand.com/d/Beatport/salute_djseinfeld_chloedees">RSVP Here</a>
<p>* Pre-register via the link above for access to free tickets. This event is 21+.
Complimentary drinks provided. Ticket slots are *LIMITED* and do not guarantee entry
(first come, first served). Doors @ 7:00 pm on Thursday, August 6</p>
</body></html>"""

ARTICLE_URL = ("https://www.beatportal.com/articles/1531717-rsvp-now-dj-seinfeld-salute-"
               "chloedees-beatport-live-x-hard-selects-takeover")
TODAY = date(2026, 7, 28)


def test_homepage_sweep_finds_rsvp_articles_only():
    urls = rsvp_article_urls(HOMEPAGE)
    assert urls == [  # RSC-escaped duplicate collapsed; non-RSVP article ignored
        ARTICLE_URL,
        "https://www.beatportal.com/articles/1537686-rsvp-now-ela-minus-b2b-nick-leon-beatport-live-ny",
    ]


def test_rsvp_article_to_record():
    rec = record_from_rsvp_article(ARTICLE_LA, ARTICLE_URL, "Los Angeles", today=TODAY)
    assert rec["title"] == "Beatport Live x HARD Selects Takeover"
    assert rec["lineup"] == ["DJ Seinfeld", "salute", "Chloëdees"]
    assert rec["date"] == "2026-08-06"  # doors line, year inferred forward from today
    assert rec["start"] == "19:00"
    assert rec["venue"] == "TBA (RSVP)"
    assert rec["price"] == "free"
    assert rec["organizer"] == "Beatport Live"
    assert [l["url"] for l in rec["links"]] == [
        ARTICLE_URL, "https://drop.cobrand.com/d/Beatport/salute_djseinfeld_chloedees"]
    assert rec["links"][1]["label"] == "RSVP"
    assert "21+" in rec["detail"] and "LA HQ" in rec["detail"]
    n = P.normalize_record(rec, "beatport")
    assert (n["date"], n["start"], n["category"]) == ("2026-08-06", "19:00", "electronic")
    assert n["price"] == "free"


def test_rsvp_article_other_city_skipped():
    ny = ARTICLE_LA.replace("Los Angeles", "New York").replace("LA HQ", "NY HQ")
    assert record_from_rsvp_article(ny, ARTICLE_URL, "Los Angeles", today=TODAY) is None


def test_rsvp_article_explicit_year_honored():
    # older posts carry the year ("Doors @ 7:00 pm on Wednesday, November 12, 2025") —
    # must parse verbatim, not roll forward; the window filter drops past dates later
    old = ARTICLE_LA.replace("Thursday, August 6", "Wednesday, November 12, 2025")
    rec = record_from_rsvp_article(old, ARTICLE_URL, "Los Angeles", today=TODAY)
    assert rec["date"] == "2025-11-12"


def test_rsvp_article_undated_skipped():
    undated = ARTICLE_LA.replace("Doors @ 7:00 pm on Thursday, August 6", "").replace(
        "on August 6", "soon")
    assert record_from_rsvp_article(undated, ARTICLE_URL, "Los Angeles", today=TODAY) is None


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
