#!/usr/bin/env python3
"""Fetch Beatport events (Beatport Tickets / Beatport Live) via beatportal.com.

Beatport's ticketing arm — Beatport Tickets, powered by Weeztix, including the touring
"Beatport Live" event/stage brand — lists events on beatportal.com/events. The store site
(beatport.com/events) is Cloudflare-walled, but Beatportal serves the SAME inventory
server-rendered (real Chrome UA required) and honors geo + date query params
(city_name / country_code / radius, ISO from / to — verified live 2026-07-27).

Architecture mirrors fetch_eventbrite.py: listing page -> event links -> per-event
schema.org Event JSON-LD (reusing fetch_jsonld's fetch + walker). Each event page embeds
one Event block (name, start/end, performer, venue + street address, image, organizer);
ticket links ride as <a href> inside the JSON-LD description (often an external seller
with a BEATPORT affiliate tag). The beatportal event page is kept as the canonical url.

TWO lanes feed this fetcher (verified live 2026-07-27/28):
  1. The ticketed /events listing (above) — Weeztix inventory, geo-filterable.
  2. "RSVP Now" ARTICLE drops — Beatport Live's own free parties (e.g. the 8/6/26
     "Beatport Live x HARD Selects Takeover": DJ Seinfeld, salute, Chloëdees at Beatport's
     LA HQ) are announced as beatportal.com/articles/<id>-rsvp-now-... posts with a
     drop.cobrand.com RSVP link, and NEVER appear on the /events listing. The homepage
     server-renders recent article links, so we sweep it for rsvp-now slugs, parse each
     article's formulaic facts (title "RSVP Now: <lineup> | <event name>", a
     "Doors @ H:MM pm on <weekday>, <Month> <D>[, <year>]" line, og:description dek,
     free/21+ boilerplate), and gate on the profile city. Venue is typically revealed at
     RSVP -> rows carry "TBA (RSVP)" (same accepted tradeoff as Posh TBA rows: if another
     source later lists the real venue, fuzzy dedupe may not join them).

Caveats recorded at wiring time (2026-07-27):
  - LISTING lane: LA inventory is EMPTY today. Los Angeles is one of Beatportal's six
    featured city filters (their preset: 34.0522/-118.2437 r100) and the US expansion is
    live in Vegas ("Beatport Fridays" Marquee residency), but no LA rows yet. That lane
    returns 0 cleanly until Beatport's LA listings appear — one cheap page fetch per run.
  - startDate offsets look unreliable (a Vegas dayclub stamped -04:00); the DATE part is
    what dedupe keys on, clock times are best-effort.
  - Listing pagination is infinite-scroll RSC; only the server-rendered first page
    (~40 cards) is read. Fine at LA volume — revisit if an LA page ever fills.

Usage:
    python fetch_beatport.py --days 21 [-o events_beatport.json]
    python fetch_beatport.py --city-name "Las Vegas"      # listing smoke-test on live data
City defaults come from profile.yaml sources.beatportal_city (fallback: Los Angeles/US/100).
"""

import argparse
import html as htmllib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_jsonld as lj  # noqa: E402  (reuse fetch + JSON-LD Event walker/normalizer)

BASE = "https://www.beatportal.com"
# Event hrefs are /events/<id>-<slug> with a short alnum id (7 chars today; 5-12 keeps
# slack). Router artifacts like /events/page-<hex> and filter links (/events?genres=...)
# fall out naturally: "page" is only 4 chars before its dash, and "?" stops the class.
EVENT_HREF = re.compile(r'href="(?:https://www\.beatportal\.com)?(/events/[a-z0-9]{5,12}-[^"?#]*)"')
DESC_HREF = re.compile(r'''href=["']?(https?://[^\s"'>]+)''')
# "RSVP Now" article drops (Beatport Live free parties). Slugs surface on the homepage in
# several encodings (relative hrefs, RSC-escaped strings) — match the bare path form.
RSVP_SLUG = re.compile(r'articles/(\d+)-(rsvp-now-[a-z0-9-]+)')
COBRAND = re.compile(r'https://drop\.cobrand\.com/[^\s"\\<>]+')
# "Doors @ 7:00 pm on Thursday, August 6" (older posts append ", 2025" — honor it)
DOORS = re.compile(r'Doors\s*@\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*on\s*'
                   r'(?:[A-Za-z]+day,?\s*)?([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?', re.I)
ON_DATE = re.compile(r'\bon\s+([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?')  # og:description fallback
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
MAX_EVENTS = 60
MAX_ARTICLES = 10
DEFAULT_CITY = {"city_name": "Los Angeles", "country_code": "US", "radius": "100"}


def _profile_city() -> dict:
    """Geo filter from profile.yaml (sources.beatportal_city); falls back to Beatportal's
    own Los Angeles preset. Same city-portability seam as ra_area_id / ticketmaster_dma_id."""
    try:
        from lib.config import load_profile
        v = (load_profile().get("sources") or {}).get("beatportal_city")
        if isinstance(v, dict) and v.get("city_name"):
            return {**DEFAULT_CITY, **{k: str(x) for k, x in v.items() if x is not None}}
    except Exception:  # noqa: BLE001 — config trouble never blocks a fetch
        pass
    return dict(DEFAULT_CITY)


def listing_url(city: dict, lo: date, hi: date) -> str:
    q = {"city_name": city["city_name"], "country_code": city["country_code"],
         "radius": city["radius"], "from": lo.isoformat(), "to": hi.isoformat()}
    return f"{BASE}/events?{urlencode(q)}"


def parse_listing(html: str) -> list:
    """Absolute, fetchable event-page URLs from the server-rendered listing, in page
    order, de-duped. Slugs can carry raw unicode (…me-n-ü) which urlopen chokes on —
    percent-encode, leaving pre-encoded %XX escapes alone."""
    seen, urls = set(), []
    for m in EVENT_HREF.finditer(html):
        path = quote(htmllib.unescape(m.group(1)), safe="/%:=&?")
        if path not in seen:
            seen.add(path)
            urls.append(BASE + path)
    return urls


def _lineup(performer) -> list:
    if isinstance(performer, dict):
        performer = performer.get("name")
    if isinstance(performer, str):
        performer = [performer]
    return [str(p.get("name") if isinstance(p, dict) else p).strip()
            for p in (performer or []) if p]


def records_from_event_html(html: str, page_url: str) -> list:
    """Parse one beatportal event page's JSON-LD into catalog-ready records."""
    events = []
    for block in lj.LDJSON.findall(html):
        block = block.strip()
        try:  # blocks are usually raw JSON; some renders HTML-escape them — unescape only then
            lj.walk(json.loads(block), events)
        except json.JSONDecodeError:
            try:
                lj.walk(json.loads(htmllib.unescape(block)), events)
            except json.JSONDecodeError:
                continue
    out = []
    for ev in events:
        n = lj.normalize(ev, "beatport")
        if not n.get("title"):
            continue
        n["url"] = n.get("url") or page_url  # JSON-LD carries no url field
        # lj.normalize's id falls back to the NAME when url is absent — always key on the
        # page URL instead, or recurring same-title events would collapse in the run dedupe.
        n["id"] = page_url
        n["category"] = "electronic"  # the whole platform is dance music
        lineup = _lineup(ev.get("performer"))
        if lineup:
            n["lineup"] = lineup
        org = ev.get("organizer")
        org_name = org.get("name") if isinstance(org, dict) else org
        if isinstance(org_name, str) and org_name.strip():
            n["organizer"] = org_name.strip()
        # canonical page first, then any seller links buried in the description HTML
        links = [{"source": "beatport", "url": n["url"]}]
        for t in DESC_HREF.findall(ev.get("description") or ""):
            if t not in (l["url"] for l in links):
                links.append({"source": "beatport", "url": t, "label": "tickets"})
        n["links"] = links
        out.append(n)
    return out


def _in_window(d: str, lo: date, hi: date) -> bool:
    """The server honors from/to, but re-check locally in case that quietly changes.
    Unparseable/absent dates are kept rather than silently dropped."""
    try:
        return not d or lo <= datetime.strptime(d, "%Y-%m-%d").date() <= hi
    except ValueError:
        return True


def rsvp_article_urls(homepage_html: str) -> list:
    """Recent 'RSVP Now' article URLs from the server-rendered homepage, de-duped by id."""
    seen, urls = set(), []
    for aid, slug in RSVP_SLUG.findall(homepage_html):
        if aid not in seen:
            seen.add(aid)
            urls.append(f"{BASE}/articles/{aid}-{slug}")
    return urls[:MAX_ARTICLES]


def _meta(html: str, prop: str):
    m = re.search(r'<meta property="og:%s" content="([^"]*)"' % re.escape(prop), html)
    return htmllib.unescape(m.group(1)).strip() if m else None


def _resolve_date(month_name: str, day: str, year, today: date):
    """A concrete date from prose parts. Explicit year is honored verbatim; otherwise
    assume this year, rolling forward when that's more than ~a month past (announcement
    posts describe near-future events, never year-old ones)."""
    mo = MONTHS.get((month_name or "").lower())
    if not mo:
        return None
    try:
        if year:
            return date(int(year), mo, int(day))
        d = date(today.year, mo, int(day))
        return d if (today - d).days <= 35 else date(today.year + 1, mo, int(day))
    except ValueError:
        return None


def record_from_rsvp_article(html: str, url: str, city_name: str, today: date = None) -> dict:
    """One catalog-ready record from an 'RSVP Now' article page, or None when the article
    is for another city / carries no parseable date."""
    today = today or date.today()
    title = _meta(html, "title") or ""
    desc = _meta(html, "description") or ""
    text = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S)
    text = htmllib.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text)))

    if city_name.lower() not in (title + " " + desc + " " + text).lower():
        return None  # another city's drop (e.g. Beatport Live NY)

    # "RSVP Now: <lineup> | <event name> | Beatportal"
    title = re.sub(r'\s*\|\s*Beatportal\s*$', '', title)
    title = re.sub(r'^\s*RSVP\s+Now:\s*', '', title, flags=re.I)
    lineup, event_name = [], title
    if "|" in title:
        names, event_name = title.rsplit("|", 1)
        event_name = event_name.strip()
        lineup = [n.strip() for n in re.split(r',\s*|\s+&\s+', names) if n.strip()]

    m = DOORS.search(text)
    start = None
    if m:
        hh, mm, ap = int(m.group(1)) % 12, m.group(2) or "00", m.group(3).lower()
        start = f"{hh + (12 if ap == 'p' else 0):02d}:{mm}"
        when = _resolve_date(m.group(4), m.group(5), m.group(6), today)
    else:
        d = ON_DATE.search(desc)
        when = _resolve_date(*d.groups(), today) if d else None
    if not when:
        return None  # undated hype post — nothing to catalog

    links = [{"source": "beatport", "url": url}]
    rsvp = COBRAND.search(html)
    if rsvp:
        links.append({"source": "beatport", "url": rsvp.group(0), "label": "RSVP"})

    free = bool(re.search(r'free\s+(?:tickets?|entry|rsvp)', text, re.I))
    bits = [desc] if desc else []
    logistics = []
    if free:
        logistics.append("Free with RSVP (limited slots, first come first served)")
    if re.search(r'\b21\+', text):
        logistics.append("21+")
    if "complimentary drinks" in text.lower():
        logistics.append("complimentary drinks")
    if logistics:
        bits.append("; ".join(logistics) + ".")
    return {
        "source": "beatport",
        "id": url,
        "title": event_name,
        "date": when.isoformat(),
        "start": start,
        "venue": "TBA (RSVP)",  # revealed on RSVP (drop.cobrand.com), like Posh TBA rows
        "category": "electronic",
        "lineup": lineup,
        "organizer": "Beatport Live",
        "price": "free" if free else None,
        "detail": " ".join(bits) or None,
        "image": _meta(html, "image"),
        "url": url,
        "links": links,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    city = _profile_city()
    ap.add_argument("--city-name", default=city["city_name"])
    ap.add_argument("--country-code", default=city["country_code"])
    ap.add_argument("--radius", default=city["radius"])
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_beatport.json")
    args = ap.parse_args()

    lo, hi = date.today(), date.today() + timedelta(days=args.days)
    url = listing_url({"city_name": args.city_name, "country_code": args.country_code,
                       "radius": args.radius}, lo, hi)
    try:
        listing = lj.fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: beatportal listing fetch failed: {e}", file=sys.stderr)
        return 1

    events, ids = [], set()
    urls = parse_listing(listing)[:MAX_EVENTS]
    for page_url in urls:
        try:
            page = lj.fetch(page_url)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: {page_url} failed: {e}", file=sys.stderr)
            continue
        for rec in records_from_event_html(page, page_url):
            if rec["id"] in ids or not _in_window(rec.get("date"), lo, hi):
                continue
            ids.add(rec["id"])
            events.append(rec)
        time.sleep(0.4)  # be polite

    # Lane 2 — Beatport Live "RSVP Now" article drops (never on the /events listing)
    try:
        art_urls = rsvp_article_urls(lj.fetch(BASE + "/"))
    except Exception as e:  # noqa: BLE001 — one lane down never kills the other
        print(f"WARN: beatportal homepage sweep failed: {e}", file=sys.stderr)
        art_urls = []
    for aurl in art_urls:
        try:
            rec = record_from_rsvp_article(lj.fetch(aurl), aurl, args.city_name, today=lo)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: {aurl} failed: {e}", file=sys.stderr)
            continue
        if rec and rec["id"] not in ids and _in_window(rec.get("date"), lo, hi):
            ids.add(rec["id"])
            events.append(rec)
        time.sleep(0.4)

    events.sort(key=lambda e: e.get("date") or "")
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} events from {len(urls)} event page(s) + "
          f"{len(art_urls)} RSVP article(s) ({args.city_name}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
