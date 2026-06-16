#!/usr/bin/env python3
"""Fetch Eventbrite events via curated organizers (the only robust path).

Eventbrite's discovery/browse surface (/d/...) sits behind an AWS WAF CAPTCHA — a plain
HTTP client can't get past it, and the public search API was retired. BUT individual
*event* pages and *organizer* pages are NOT walled and embed clean schema.org Event JSON-LD.

So this fetches a curated set of LA promoter/organizer pages, scrapes their event links,
and parses each event page (reusing the generic JSON-LD parser). Discovery of *which*
organizers to track happens out of band (a promoter's organizer id is exposed on any of
their event pages — add it to sources.yaml). Also accepts one-off --event URLs for the
flyer/link-capture flow.

Usage:
    python fetch_eventbrite.py --days 14 [-o events_eventbrite.json]   # organizers from sources.yaml
    python fetch_eventbrite.py --org https://www.eventbrite.com/o/we-love-kandy-tour-11369190113
    python fetch_eventbrite.py --event https://www.eventbrite.com/e/...-tickets-123456
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_jsonld as lj  # noqa: E402  (reuse fetch + JSON-LD Event parser)

EVENT_LINK = re.compile(r"https://www\.eventbrite\.com/e/[a-z0-9\-]+-tickets-\d+")
HOUSE = re.compile(r"house|techno|acid|rave|disco|hardstyle|warehouse|after\s?hours|dj|club", re.I)
MAX_EVENTS_PER_ORG = 12


def organizer_event_links(org_url: str) -> list:
    try:
        html = lj.fetch(org_url)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: organizer {org_url} failed: {e}", file=sys.stderr)
        return []
    # preserve order, de-dup
    seen, links = set(), []
    for m in EVENT_LINK.findall(html):
        if m not in seen:
            seen.add(m)
            links.append(m)
    return links[:MAX_EVENTS_PER_ORG]


def load_organizers() -> list:
    import yaml
    with open("sources.yaml") as f:
        reg = yaml.safe_load(f)
    orgs = []
    for s in reg.get("sources", []):
        if s.get("method") == "eventbrite":
            orgs.extend(s.get("organizers") or [])
    return orgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", action="append", default=[], help="organizer page URL(s)")
    ap.add_argument("--event", action="append", default=[], help="one-off event URL(s)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("-o", "--out", default="events_eventbrite.json")
    args = ap.parse_args()

    organizers = args.org or ([] if args.event else load_organizers())

    event_urls, seen = list(args.event), set(args.event)
    for org in organizers:
        for url in organizer_event_links(org):
            if url not in seen:
                seen.add(url)
                event_urls.append(url)
        time.sleep(0.5)  # be polite

    lo, hi = date.today(), date.today() + timedelta(days=args.days)
    events = []
    for url in event_urls:
        for ev in lj.scrape(url, "eventbrite"):
            ev["category"] = "electronic" if HOUSE.search(ev.get("title") or "") else "general"
            d = ev.get("date")
            try:
                in_window = bool(d) and lo <= datetime.strptime(d, "%Y-%m-%d").date() <= hi
            except ValueError:
                in_window = True
            if in_window:
                events.append(ev)
        time.sleep(0.4)

    # de-dup by id/url
    uniq, ids = [], set()
    for e in events:
        k = e.get("id") or e.get("url")
        if k in ids:
            continue
        ids.add(k)
        uniq.append(e)

    uniq.sort(key=lambda e: e.get("date") or "")
    with open(args.out, "w") as f:
        json.dump(uniq, f, indent=2)
    print(f"Wrote {len(uniq)} events from {len(organizers)} organizer(s) / "
          f"{len(event_urls)} event page(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
