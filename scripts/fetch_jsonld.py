#!/usr/bin/env python3
"""Generic schema.org/Event JSON-LD scraper.

Many venue and aggregator pages embed event data as <script type="application/ld+json">
blocks (schema.org/Event and subtypes: MusicEvent, TheaterEvent, etc.). This fetches a
page, extracts every JSON-LD block, walks it (handling @graph, ItemList/itemListElement,
and plain arrays), and normalizes any Event-typed objects.

Usage:
    python fetch_jsonld.py --url https://www.eventbrite.com/d/ca--los-angeles/events/
    python fetch_jsonld.py --source "Eventbrite (LA browse)"   # look up url in sources.yaml
    python fetch_jsonld.py --all                               # every active method:jsonld source
    python fetch_jsonld.py --url URL --days 10 -o events_jsonld.json

NOTE: only works on pages that render JSON-LD server-side. JS-rendered calendars
(e.g. Vidiots via filmbot, New Bev) emit nothing here — they need a source-specific
fetcher. This script reports "0 events" cleanly in that case; it never blocks a run.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LDJSON = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def fetch(url: str) -> str:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except (HTTPError, URLError):
        # Some sites (e.g. Eventbrite) reject urllib's HTTP/1.1 fingerprint with a 405.
        # curl negotiates HTTP/2 and gets through — use it as a fallback when present.
        if not shutil.which("curl"):
            raise
        hdr_args = []
        for k, v in headers.items():
            hdr_args += ["-H", f"{k}: {v}"]
        out = subprocess.run(
            ["curl", "-sSL", "--compressed", "--max-time", "30", *hdr_args, url],
            capture_output=True, timeout=40,
        )
        if out.returncode != 0:
            raise
        return out.stdout.decode("utf-8", "replace")


def is_event(obj: dict) -> bool:
    # Schema.org Event subtypes mostly contain "Event" (MusicEvent, TheaterEvent…) — but not
    # all: Eventbrite marks the Rose Bowl Flea / 626 Night Market pages @type "Festival".
    t = obj.get("@type", "")
    types = t if isinstance(t, list) else [t]
    return any("Event" in str(x) or str(x) == "Festival" for x in types)


def walk(node, out: list):
    """Recursively collect Event-typed dicts from arbitrary JSON-LD shapes."""
    if isinstance(node, list):
        for x in node:
            walk(x, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            walk(node["@graph"], out)
        if "itemListElement" in node:
            walk(node["itemListElement"], out)
        if "item" in node and isinstance(node["item"], (dict, list)):
            walk(node["item"], out)
        if is_event(node):
            out.append(node)


def text(v):
    if isinstance(v, dict):
        return v.get("name") or v.get("@id") or None
    if isinstance(v, list) and v:
        return text(v[0])
    return v


def normalize(ev: dict, source: str) -> dict:
    loc = ev.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = loc.get("address") if isinstance(loc, dict) else {}
    if isinstance(addr, str):
        addr = {"streetAddress": addr}
    addr = addr or {}
    geo = (loc.get("geo") or {}) if isinstance(loc, dict) else {}
    offers = ev.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    start = ev.get("startDate") or ""
    return {
        "source": source,
        "id": text(ev.get("url")) or ev.get("@id") or text(ev.get("name")),
        "title": text(ev.get("name")),
        "date": start[:10] if start else None,
        "start": start or None,
        "end": ev.get("endDate") or None,
        "venue": text(loc.get("name")) if isinstance(loc, dict) else text(loc),
        "neighborhood": addr.get("addressLocality"),
        "address": addr.get("streetAddress"),
        "lat": geo.get("latitude"),
        "lng": geo.get("longitude"),
        "category": (ev.get("@type") if isinstance(ev.get("@type"), str) else None),
        "price_min": offers.get("lowPrice") or offers.get("price"),
        "detail": ev.get("description"),  # schema.org Event description (sanitized on normalize)
        "url": text(ev.get("url")),
    }


def scrape(url: str, source: str) -> list:
    try:
        html = fetch(url)
    except Exception as e:  # noqa: BLE001
        print(f"WARN: {source} fetch failed: {e}", file=sys.stderr)
        return []
    raw, seen, events = [], set(), []
    for block in LDJSON.findall(html):
        block = block.strip()
        try:
            raw.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    for d in raw:
        walk(d, events)
    norm, ids = [], set()
    for ev in events:
        n = normalize(ev, source)
        if n["id"] in ids or not n["title"]:
            continue
        ids.add(n["id"])
        norm.append(n)
    return norm


def load_sources():
    import yaml  # lazy: only needed for --source/--all
    with open("sources.yaml") as f:
        return yaml.safe_load(f)["sources"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[], help="page URL(s) to scrape")
    ap.add_argument("--source", help="source name in sources.yaml to look up")
    ap.add_argument("--all", action="store_true", help="all active method:jsonld sources")
    ap.add_argument("--days", type=int, default=0, help="filter to next N days (0 = no filter)")
    ap.add_argument("-o", "--out", default="events_jsonld.json")
    args = ap.parse_args()

    targets = [(u, urlparse(u).netloc) for u in args.url]
    if args.source or args.all:
        for s in load_sources():
            if s.get("method") != "jsonld":
                continue
            if args.all and s.get("status") == "active":
                targets.append((s["url"], s["name"]))
            elif args.source and s["name"] == args.source:
                targets.append((s["url"], s["name"]))

    if not targets:
        print("ERROR: pass --url, --source, or --all", file=sys.stderr)
        return 1

    all_events = []
    for url, name in targets:
        evs = scrape(url, name)
        print(f"  {name}: {len(evs)} events", file=sys.stderr)
        all_events.extend(evs)

    if args.days:
        lo, hi = date.today(), date.today() + timedelta(days=args.days)
        def keep(e):
            try:
                return lo <= datetime.strptime(e["date"], "%Y-%m-%d").date() <= hi
            except (TypeError, ValueError):
                return True  # keep undated rather than silently drop
        all_events = [e for e in all_events if keep(e)]

    with open(args.out, "w") as f:
        json.dump(all_events, f, indent=2)
    print(f"Wrote {len(all_events)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
