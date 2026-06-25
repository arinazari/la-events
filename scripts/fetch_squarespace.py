#!/usr/bin/env python3
"""Fetch live-music listings from Squarespace event collections.

Squarespace sites expose any events/calendar collection as structured JSON at
<collection-url>?format=json-pretty — items carry startDate (ms epoch), title,
fullUrl, excerpt/body, and location. Cleaner than scraping the rendered page
(these venues serve no Event JSON-LD). Stdlib only.

Add sites to SITES below. Grow in Discover mode.

Usage:
    python fetch_squarespace.py --days 21 [-o events_squarespace.json]
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    LA = timezone(timedelta(hours=-7))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# venue name -> (events collection URL, neighborhood, category). Grow in Discover.
SITES = {
    "Junior High":   ("https://juniorhighlosangeles.com/calendar", "Glendale", "live_music"),
    "Vibrato Grill Jazz": ("https://www.vibratogrilljazz.com/music", "Bel Air", "live_music"),
    "The Smell":     ("https://www.thesmell.org/events", "DTLA", "live_music"),
    "The Circle OC": ("https://www.thecircleoc.com/upcoming-events", "Huntington Beach", "electronic"),
}

DATE_TITLE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)", re.I)


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch_site(venue, url, hood, category, now, hi):
    base = urlsplit(url)
    origin = f"{base.scheme}://{base.netloc}"
    sep = "&" if base.query else "?"
    req = Request(url + sep + "format=json-pretty",
                  headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))

    items = data.get("items") or data.get("upcoming") or []
    out = []
    for it in items:
        ms = it.get("startDate")
        if not ms:
            continue
        when = datetime.fromtimestamp(ms / 1000, tz=LA)
        if not (now.date() <= when.date() <= hi.date()):
            continue
        title = (it.get("title") or "").strip()
        detail = strip_html(it.get("excerpt") or it.get("body") or "")
        # Some venues (The Smell) title entries by date — use the body's first line instead.
        if DATE_TITLE.match(title) and detail:
            title = detail.split(". ")[0][:80]
        full = it.get("fullUrl") or ""
        out.append({
            "source": "squarespace",
            "title": title or None,
            "date": when.date().isoformat(),
            "start": when.strftime("%H:%M"),
            "venue": venue,
            "neighborhood": hood,
            "lineup": [],
            "category": category,
            "price": None,
            "url": (origin + full) if full.startswith("/") else (full or url),
            "detail": detail[:300] or None,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_squarespace.json")
    args = ap.parse_args()

    now = datetime.now(LA)
    hi = now + timedelta(days=args.days)
    events, failed = [], []
    for venue, (url, hood, cat) in SITES.items():
        try:
            got = fetch_site(venue, url, hood, cat, now, hi)
            events.extend(got)
            print(f"  {venue}: {len(got)} events", file=sys.stderr)
        except (HTTPError, URLError) as e:
            failed.append(f"{venue} ({getattr(e, 'code', e)})")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{venue} ({e})")

    events.sort(key=lambda x: (x["date"], x["start"]))
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} events from {len(SITES) - len(failed)}/{len(SITES)} "
          f"Squarespace sites -> {args.out}"
          + (f" | failed: {', '.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
