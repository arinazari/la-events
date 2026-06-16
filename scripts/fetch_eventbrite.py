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

Growing the curated list (the mechanism that keeps coverage expanding over time):
    python fetch_eventbrite.py --harvest https://www.eventbrite.com/e/...-tickets-123456
        ^ extracts that event's organizer and appends it to sources.yaml (deduped).
          Use this whenever an Eventbrite link arrives via a text blast / IG / flyer.
    python fetch_eventbrite.py --scan-catalog
        ^ harvests organizers from every Eventbrite link already in data/catalog.json,
          so promoters surfaced opportunistically by other sources get tracked automatically.
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
ORG_LINK = re.compile(r"https://www\.eventbrite\.com/o/[a-z0-9\-]+-\d{6,}")
# curated organizers sometimes run multi-city — drop the obvious non-LA localities
NON_LA = {"san francisco", "oakland", "berkeley", "san diego", "new york",
          "brooklyn", "las vegas", "san jose", "sacramento", "philadelphia",
          "chicago", "atlanta", "miami", "phoenix", "seattle", "austin", "houston"}
HOUSE = re.compile(r"house|techno|acid|rave|disco|hardstyle|warehouse|after\s?hours|dj|club", re.I)
MAX_EVENTS_PER_ORG = 12
REGISTRY = "sources.yaml"


def organizer_name(org_url: str) -> str:
    """Human-friendly name from an organizer slug, for the registry comment."""
    slug = re.sub(r"-\d{6,}$", "", org_url.rsplit("/", 1)[-1])
    return slug.replace("-", " ").title()


def primary_organizer(html: str):
    """Return (url, name) of the event's OWN organizer from its Event JSON-LD.
    Deliberately ignores the 'related/recommended' organizer links Eventbrite also
    renders on the page — we only auto-track the actual promoter."""
    for block in lj.LDJSON.findall(html):
        try:
            d = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for obj in (d if isinstance(d, list) else [d]):
            if isinstance(obj, dict) and "Event" in str(obj.get("@type", "")):
                org = obj.get("organizer") or {}
                if isinstance(org, list):
                    org = org[0] if org else {}
                url = org.get("url") if isinstance(org, dict) else None
                if url and ORG_LINK.fullmatch(url):
                    return url, (org.get("name") or organizer_name(url))
    return None, None


def harvest_organizers(urls: list) -> dict:
    """Map {organizer_url: name} from event URLs (the event's own organizer only)
    or from organizer URLs passed directly."""
    found = {}
    for url in urls:
        if ORG_LINK.fullmatch(url):
            found[url] = organizer_name(url)
            continue
        try:
            html = lj.fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: could not fetch {url}: {e}", file=sys.stderr)
            continue
        org_url, name = primary_organizer(html)
        if org_url:
            found[org_url] = name
        else:
            print(f"WARN: no organizer found in JSON-LD for {url}", file=sys.stderr)
    return found


def registry_organizers(text: str) -> set:
    return set(ORG_LINK.findall(text))


def add_organizers_to_registry(new: dict) -> list:
    """Append new organizer URLs under the Eventbrite source's `organizers:` list,
    preserving the file's formatting/comments. Returns the URLs actually added."""
    with open(REGISTRY) as f:
        lines = f.readlines()
    existing = registry_organizers("".join(lines))
    to_add = {u: n for u, n in new.items() if u not in existing}
    if not to_add:
        return []
    # find the `organizers:` line that belongs to the eventbrite source
    idx = next((i for i, ln in enumerate(lines)
                if re.match(r"\s*organizers:\s*$", ln)), None)
    if idx is None:
        print("WARN: no `organizers:` list found in sources.yaml; not modifying.", file=sys.stderr)
        return []
    indent = re.match(r"(\s*)", lines[idx + 1]).group(1) if idx + 1 < len(lines) else "      "
    insert = [f"{indent}- {u}   # {n}\n" for u, n in to_add.items()]
    lines[idx + 1:idx + 1] = insert
    with open(REGISTRY, "w") as f:
        f.writelines(lines)
    return list(to_add)


def catalog_eventbrite_urls() -> list:
    try:
        cat = json.load(open("data/catalog.json"))
    except Exception:  # noqa: BLE001
        return []
    urls = []
    for rec in cat:
        for link in rec.get("links", []):
            u = link.get("url", "")
            if EVENT_LINK.match(u or ""):
                urls.append(u)
    return urls


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
    ap.add_argument("--harvest", action="append", default=[], metavar="URL",
                    help="add organizer(s) to sources.yaml from event/organizer URL(s) and exit")
    ap.add_argument("--scan-catalog", action="store_true",
                    help="harvest organizers from every Eventbrite link in data/catalog.json and exit")
    args = ap.parse_args()

    # --- organizer-harvesting mode (keeps the curated list growing) ---
    if args.harvest or args.scan_catalog:
        urls = list(args.harvest)
        if args.scan_catalog:
            urls += catalog_eventbrite_urls()
        if not urls:
            print("Nothing to harvest (no --harvest URLs and no Eventbrite links in catalog).")
            return 0
        added = add_organizers_to_registry(harvest_organizers(urls))
        if added:
            print(f"Added {len(added)} organizer(s) to {REGISTRY}:")
            for u in added:
                print(f"  + {u}")
        else:
            print("No new organizers (all already in sources.yaml).")
        return 0

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
            if (ev.get("neighborhood") or "").strip().lower() in NON_LA:
                continue  # multi-city organizer's non-LA event
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
