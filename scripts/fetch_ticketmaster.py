#!/usr/bin/env python3
"""Fetch LA events from the Ticketmaster Discovery API.

Usage:
    export TM_API_KEY=yourkey   # free: developer.ticketmaster.com
    python fetch_ticketmaster.py --days 7 [--classification music,comedy] [-o events_tm.json]

Covers Ticketmaster, TicketWeb, Universe, FrontGate inventory. LA = dmaId 324.
Rate limits on free tier: 5000 calls/day, 5 req/sec.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
LA_DMA = "324"
PAGE_SIZE = 100


def fetch_page(params: dict) -> dict:
    url = f"{BASE}?{urlencode(params)}"
    with urlopen(url, timeout=30) as resp:
        return json.load(resp)


def normalize(ev: dict) -> dict:
    venue = (ev.get("_embedded", {}).get("venues") or [{}])[0]
    prices = (ev.get("priceRanges") or [{}])[0]
    classifications = ev.get("classifications") or [{}]
    seg = classifications[0].get("segment", {}).get("name")
    genre = classifications[0].get("genre", {}).get("name")
    start = ev.get("dates", {}).get("start", {})
    return {
        "source": "ticketmaster",
        "id": ev.get("id"),
        "title": ev.get("name"),
        "datetime": start.get("dateTime") or start.get("localDate"),
        "local_time": start.get("localTime"),
        "venue": venue.get("name"),
        "neighborhood": (venue.get("city") or {}).get("name"),
        "lat": (venue.get("location") or {}).get("latitude"),
        "lng": (venue.get("location") or {}).get("longitude"),
        "category": seg,
        "genre": genre,
        "price_min": prices.get("min"),
        "price_max": prices.get("max"),
        "url": ev.get("url"),
        "onsale": (ev.get("sales", {}).get("public") or {}).get("startDateTime"),
        "status": ev.get("dates", {}).get("status", {}).get("code"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--classification", default="music,comedy,arts & theatre",
                    help="comma-separated Discovery API segments")
    ap.add_argument("-o", "--out", default="events_tm.json")
    args = ap.parse_args()

    key = os.environ.get("TM_API_KEY")
    if not key:
        print("ERROR: set TM_API_KEY (free key at developer.ticketmaster.com)", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    events: dict[str, dict] = {}
    for cls in [c.strip() for c in args.classification.split(",") if c.strip()]:
        page = 0
        while True:
            params = {
                "apikey": key,
                "dmaId": LA_DMA,
                "classificationName": cls,
                "startDateTime": start,
                "endDateTime": end,
                "size": PAGE_SIZE,
                "page": page,
                "sort": "date,asc",
            }
            try:
                data = fetch_page(params)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: {cls} page {page} failed: {e}", file=sys.stderr)
                break
            for ev in data.get("_embedded", {}).get("events", []):
                events[ev["id"]] = normalize(ev)
            pg = data.get("page", {})
            page += 1
            # Discovery API caps deep paging at size*page < 1000
            if page >= min(pg.get("totalPages", 0), 1000 // PAGE_SIZE):
                break
            time.sleep(0.25)  # stay under 5 req/sec

    out = sorted(events.values(), key=lambda e: e.get("datetime") or "")
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(out)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
