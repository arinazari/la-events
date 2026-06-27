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
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://app.ticketmaster.com/discovery/v2/events.json"

# TM marketing URLs embed the night-of date in the slug: .../<name>-<city>-<state>-MM-DD-YYYY/event/<id>
_SLUG_DATE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})/event/", re.I)


def _nightof_date(local_date, local_time, url):
    """Undo Ticketmaster's occasional post-midnight date-roll.

    TM sometimes files a late-night show under the calendar day of its *after-midnight* start
    (localDate 2026-06-28 @ localTime 03:00) while the event URL slug still carries the night-of
    date it's actually marketed under (.../06-27-2026/event/<id>). That mis-dates the show by a
    day and — worse — splits it from every other source (RA/19hz/the flyer) that bills it night-of,
    so it lands in the catalog twice. When the slug date is exactly the day before localDate and the
    start time is in the small hours, trust the slug (night-of) date. Every other case is untouched.
    """
    if not (local_date and local_time and url):
        return local_date
    m = _SLUG_DATE.search(url)
    if not m:
        return local_date
    mm, dd, yyyy = m.groups()
    try:
        ld = datetime.strptime(local_date, "%Y-%m-%d").date()
        sd = datetime.strptime(f"{yyyy}-{mm}-{dd}", "%Y-%m-%d").date()
        hour = int(str(local_time)[:2])
    except (ValueError, TypeError):
        return local_date
    if 0 <= hour < 6 and (ld - sd).days == 1:
        return sd.isoformat()
    return local_date


def _profile_dma(default="324"):
    """LA DMA id, lifted to profile.yaml (sources.ticketmaster_dma_id); falls back to 324."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from lib.config import load_profile
        return str((load_profile().get("sources") or {}).get("ticketmaster_dma_id") or default)
    except Exception:
        return default


LA_DMA = _profile_dma()
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
    # TM uses "Undefined"/"Other" as placeholders when it has no real genre — treat them as
    # no-genre so the dashboard's CATEGORY / GENRE line shows a real genre (Rock, Techno, …) or
    # nothing, never the literal word "Undefined".
    if genre and genre.strip().lower() in ("undefined", "other"):
        genre = None
    start = ev.get("dates", {}).get("start", {})
    attractions = (ev.get("_embedded") or {}).get("attractions") or []
    # Prefer venue-LOCAL date (+ time). TM's `dateTime` is UTC, which rolls an evening LA show past
    # midnight into the next calendar day; `localDate`/`localTime` are venue-local. Then undo TM's
    # own post-midnight roll (a 3am set filed on the next day) using the night-of date in the URL slug.
    local_date = _nightof_date(start.get("localDate"), start.get("localTime"), ev.get("url"))
    return {
        "source": "ticketmaster",
        "id": ev.get("id"),
        "title": ev.get("name"),
        "datetime": (f"{local_date}T{start['localTime']}"
                     if local_date and start.get("localTime")
                     else local_date or start.get("dateTime")),
        "local_time": start.get("localTime"),
        "venue": venue.get("name"),
        "neighborhood": (venue.get("city") or {}).get("name"),
        "lineup": [a.get("name") for a in attractions if a.get("name")],
        "lat": (venue.get("location") or {}).get("latitude"),
        "lng": (venue.get("location") or {}).get("longitude"),
        "category": seg,
        "genre": genre,
        "price_min": prices.get("min"),
        "price_max": prices.get("max"),
        "detail": ev.get("info"),  # TM event blurb (pleaseNote is logistics fine-print — skip; sanitized on normalize)
        "url": ev.get("url"),
        "onsale": (ev.get("sales", {}).get("public") or {}).get("startDateTime"),
        "status": ev.get("dates", {}).get("status", {}).get("code"),
    }


def date_windows(start_dt, end_dt, chunk_days=30):
    """Split [start, end] into consecutive <=chunk_days sub-windows.

    The Discovery API caps deep paging at size*page < 1000 per query (10 pages of 100), so a
    single wide date range silently drops the far tail once LA has >1000 events in it. Windowing
    keeps each slice under the cap, so a 6-month horizon returns its full set. With the default
    21-day horizon and 30-day chunks this yields exactly one window (behaviour-preserving)."""
    chunk_days = max(1, chunk_days)
    out, cur, step = [], start_dt, timedelta(days=chunk_days)
    while cur < end_dt:
        nxt = min(cur + step, end_dt)
        out.append((cur, nxt))
        cur = nxt
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--chunk-days", type=int, default=30,
                    help="split the fetch window into <=N-day slices (defeats the 1000-result/query cap)")
    ap.add_argument("--classification", default="music,comedy,arts & theatre",
                    help="comma-separated Discovery API segments")
    ap.add_argument("-o", "--out", default="events_tm.json")
    args = ap.parse_args()

    key = os.environ.get("TM_API_KEY")
    if not key:
        print("ERROR: set TM_API_KEY (free key at developer.ticketmaster.com)", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=args.days)

    events: dict[str, dict] = {}
    for cls in [c.strip() for c in args.classification.split(",") if c.strip()]:
        # Date-window each classification so no single query hits the API's 1000-result cap
        # (one window at the 21-day default; many for a 6-month horizon).
        for w_start, w_end in date_windows(now, end, args.chunk_days):
            page = 0
            while True:
                params = {
                    "apikey": key,
                    "dmaId": LA_DMA,
                    "classificationName": cls,
                    "startDateTime": w_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateTime": w_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "size": PAGE_SIZE,
                    "page": page,
                    "sort": "date,asc",
                }
                try:
                    data = fetch_page(params)
                except Exception as e:  # noqa: BLE001
                    print(f"WARN: {cls} {w_start:%m/%d}-{w_end:%m/%d} page {page} failed: {e}",
                          file=sys.stderr)
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
