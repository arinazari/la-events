#!/usr/bin/env python3
"""Fetch Goldenvoice / AEG events from their public AXS data feed.

Goldenvoice's website (goldenvoice.com/shows) is a client-rendered AEG "template15" site;
the event list is hydrated from a static JSON feed on Azure blob storage (no bot wall):

    https://aegwebprod.blob.core.windows.net/json/events/{site_id}/events.json

site_id 19 = Goldenvoice. The feed carries the full AXS event object: headliners/supporting
acts, venue, timezone-aware datetimes, price low/high, age, on-sale/presale dates, and AXS
ticket links. Covers Goldenvoice's LA rooms (Fonda, El Rey, The Roxy, The Novo, Shrine,
Greek, Belasco) plus Bay Area / SD venues — we filter to LA metro by venue city.

Usage:
    python fetch_goldenvoice.py --days 14 [--site-id 19] [-o events_goldenvoice.json]
    python fetch_goldenvoice.py --days 14 --all-cities   # skip the LA-metro filter
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    from datetime import timezone, timedelta as _td
    LA = timezone(_td(hours=-7))

FEED = "https://aegwebprod.blob.core.windows.net/json/events/{site_id}/events.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# LA-metro cities present in the GV feed (excludes Bay Area / San Diego / Santa Barbara rooms)
LA_CITIES = {
    "los angeles", "west hollywood", "hollywood", "inglewood", "pomona",
    "santa ana", "anaheim", "pasadena", "long beach",
}


def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def price(v):
    if not v:
        return None
    v = str(v).strip()
    return None if v in ("", "$0", "$0.00", "0") else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-id", default="19", help="AEG site id (19 = Goldenvoice)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--all-cities", action="store_true", help="skip LA-metro venue filter")
    ap.add_argument("-o", "--out", default="events_goldenvoice.json")
    args = ap.parse_args()

    url = FEED.format(site_id=args.site_id)
    try:
        req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"WARN: Goldenvoice feed fetch failed: {e}", file=sys.stderr)
        with open(args.out, "w") as f:
            json.dump([], f)
        return 0

    feed = data if isinstance(data, list) else (
        data.get("events") or next((v for v in data.values() if isinstance(v, list)), [])
    )

    now = datetime.now(LA)
    hi = now + timedelta(days=args.days)

    events, skipped_far = [], 0
    for e in feed:
        if not e.get("active") or e.get("private"):
            continue
        venue = e.get("venue") or {}
        city = (venue.get("city") or "").strip()
        if not args.all_cities and city.lower() not in LA_CITIES:
            skipped_far += 1
            continue
        iso = e.get("eventDateTimeISO") or e.get("eventDateTime")
        if not iso:
            continue
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=LA)
        if not (now.date() <= when.astimezone(LA).date() <= hi.date()):
            continue

        title = e.get("title") or {}
        headliner = strip_html(title.get("headlinersText") or title.get("eventTitleText"))
        supporting = strip_html(title.get("supportingText"))
        tk = e.get("ticketing") or {}
        lineup = [headliner] if headliner else []
        if supporting:
            lineup.append(re.sub(r"^with\s+", "", supporting, flags=re.I))

        events.append({
            "source": "goldenvoice",
            "id": f"gv-{e.get('eventId')}",
            "title": headliner or strip_html(title.get("eventTitleText")),
            "date": when.astimezone(LA).date().isoformat(),
            "start": when.astimezone(LA).strftime("%H:%M"),
            "venue": venue.get("title"),
            "neighborhood": city or None,
            "lineup": lineup,
            "category": "music",
            "age": e.get("age"),
            "price_low": price(e.get("ticketPriceLow")),
            "price_high": price(e.get("ticketPriceHigh")),
            "status": tk.get("status"),
            "onsale": e.get("onsaleDateTime"),
            "presale": e.get("presaleDateTime"),
            "url": tk.get("eventUrl") or tk.get("url") or tk.get("ticketURL"),
        })

    events.sort(key=lambda x: (x["date"], x["start"]))
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} LA events -> {args.out} (skipped {skipped_far} non-LA-metro)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
