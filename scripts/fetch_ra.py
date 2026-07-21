#!/usr/bin/env python3
"""Fetch LA events from Resident Advisor's (unofficial) GraphQL API.

Usage:
    python fetch_ra.py --days 7 [--area 23] [-o events_ra.json]

AREA_ID: RA's internal area number for Los Angeles. Believed to be 23, but VERIFY
once: open https://ra.co/events/us/losangeles, watch the network tab for the
GraphQL POST, and read `variables.filters.areas.eq`. Update DEFAULT_AREA if needed.

This is an unofficial endpoint — be polite (one request/page, small page count,
real User-Agent). Schema can change without notice; if it 4xx/5xxs, fall back to
scraping the JSON-LD embedded in ra.co event pages.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import images  # noqa: E402  (RA flyerFront -> a clean image URL, free on the same GraphQL POST)

ENDPOINT = "https://ra.co/graphql"


def _profile_area(default=23):
    """RA LA area id, lifted to profile.yaml (sources.ra_area_id); falls back to 23."""
    try:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from lib.config import load_profile
        v = (load_profile().get("sources") or {}).get("ra_area_id")
        return int(v) if v is not None else default
    except Exception:
        return default


DEFAULT_AREA = _profile_area()  # Los Angeles — overridable via profile.yaml / --area
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

QUERY = """
query GET_EVENT_LISTINGS($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      id
      listingDate
      event {
        id
        title
        date
        startTime
        endTime
        contentUrl
        flyerFront
        attending
        venue { id name contentUrl area { name } }
        artists { name }
        pick { blurb }
      }
    }
    totalResults
  }
}
"""


def gql(variables: dict) -> dict:
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = Request(
        ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Referer": "https://ra.co/events/us/losangeles",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.load(resp)


def normalize(listing: dict) -> dict:
    ev = listing.get("event") or {}
    venue = ev.get("venue") or {}
    start = ev.get("startTime") or ""
    # crude afterhours heuristic: starts at/after 22:00 or 00:00-06:00
    hour = None
    if "T" in start:
        try:
            hour = int(start.split("T")[1][:2])
        except (ValueError, IndexError):
            hour = None
    afterhours = hour is not None and (hour >= 22 or hour < 6)
    return {
        "source": "resident_advisor",
        "id": ev.get("id"),
        "title": ev.get("title"),
        "date": ev.get("date"),
        "start": ev.get("startTime"),
        "end": ev.get("endTime"),
        "venue": venue.get("name"),
        "neighborhood": (venue.get("area") or {}).get("name"),
        "lineup": [a.get("name") for a in (ev.get("artists") or [])],
        "attending": ev.get("attending"),
        "ra_pick": bool(ev.get("pick")),
        "detail": (ev.get("pick") or {}).get("blurb"),  # RA editorial pick blurb (sanitized on normalize)
        "afterhours_flag": afterhours,
        "image": images.clean(ev.get("flyerFront")),  # RA event flyer (imgproxy CDN) — free on the same query
        "url": f"https://ra.co{ev.get('contentUrl', '')}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--area", type=int, default=DEFAULT_AREA)
    ap.add_argument("-o", "--out", default="events_ra.json")
    args = ap.parse_args()

    gte = date.today().isoformat()
    lte = (date.today() + timedelta(days=args.days)).isoformat()

    events, page = [], 1
    while True:
        variables = {
            "filters": {
                "areas": {"eq": args.area},
                "listingDate": {"gte": gte, "lte": lte},
            },
            "pageSize": 50,
            "page": page,
        }
        try:
            data = gql(variables)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: page {page} failed: {e}", file=sys.stderr)
            break
        listings = (data.get("data", {}).get("eventListings") or {}).get("data") or []
        if not listings:
            break
        events.extend(normalize(l) for l in listings)
        total = data["data"]["eventListings"].get("totalResults") or 0
        if page * 50 >= total or page >= 10:
            break
        page += 1

    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    ah = sum(1 for e in events if e["afterhours_flag"])
    print(f"Wrote {len(events)} events ({ah} flagged afterhours) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
