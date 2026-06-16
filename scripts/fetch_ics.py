#!/usr/bin/env python3
"""Fetch live-music listings from iCalendar (.ics) feeds.

Many small venues expose a real calendar feed — Tockify widgets
(tockify.com/api/feeds/ics/<slug>), Google Calendar, or a venue's own .ics.
This parses any RFC-5545 feed into normalized event records. Stdlib only.

Add feeds to FEEDS below (or pass --feeds name=url,...). Grow in Discover mode.

Usage:
    python fetch_ics.py --days 21 [-o events_ics.json]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    LA = timezone(timedelta(hours=-7))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# name -> (ics_url, neighborhood, category). Grow in Discover mode.
FEEDS = {
    "Maui Sugar Mill Saloon": ("https://tockify.com/api/feeds/ics/sugarmillsaloon",
                               "Tarzana", "live_music"),
}


def unfold(body):
    lines = []
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def unescape(v):
    return (v.replace("\\n", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\").strip())


def parse_dt(val, params):
    val = val.strip()
    try:
        if val.endswith("Z"):
            return (datetime.strptime(val, "%Y%m%dT%H%M%SZ")
                    .replace(tzinfo=timezone.utc).astimezone(LA))
        if "T" in val:
            dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
            tzid = params.get("TZID")
            if tzid:
                try:
                    return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone(LA)
                except Exception:
                    return dt.replace(tzinfo=LA)
            return dt.replace(tzinfo=LA)
        return datetime.strptime(val[:8], "%Y%m%d").replace(tzinfo=LA)
    except ValueError:
        return None


def parse_feed(body, venue, hood, category, now, hi):
    out, cur, in_ev = [], {}, False
    for line in unfold(body):
        if line == "BEGIN:VEVENT":
            in_ev, cur = True, {}
            continue
        if line == "END:VEVENT":
            in_ev = False
            dt = cur.get("_start")
            if dt and now.date() <= dt.date() <= hi.date():
                out.append({
                    "source": "ics",
                    "title": cur.get("SUMMARY"),
                    "date": dt.date().isoformat(),
                    "start": dt.strftime("%H:%M"),
                    "venue": venue,
                    "neighborhood": hood,
                    "lineup": [],
                    "category": category,
                    "price": None,
                    "url": cur.get("URL") or cur.get("_loc_url"),
                    "detail": cur.get("DESCRIPTION"),
                })
            continue
        if not in_ev or ":" not in line:
            continue
        key, val = line.split(":", 1)
        name, *parts = key.split(";")
        params = dict(p.split("=", 1) for p in parts if "=" in p)
        name = name.upper()
        if name == "DTSTART":
            cur["_start"] = parse_dt(val, params)
        elif name in ("SUMMARY", "DESCRIPTION", "URL", "LOCATION"):
            cur[name] = unescape(val)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds", help="name=url pairs, comma-separated (overrides built-in)")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_ics.json")
    args = ap.parse_args()

    feeds = FEEDS
    if args.feeds:
        feeds = {}
        for pair in args.feeds.split(","):
            if "=" in pair:
                n, u = pair.split("=", 1)
                feeds[n.strip()] = (u.strip(), None, "live_music")

    now = datetime.now(LA)
    hi = now + timedelta(days=args.days)
    events, failed = [], []
    for venue, (url, hood, cat) in feeds.items():
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "text/calendar,*/*"})
            with urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", "replace")
            if "BEGIN:VCALENDAR" not in body:
                failed.append(f"{venue} (not an ICS feed)")
                continue
            got = parse_feed(body, venue, hood, cat, now, hi)
            events.extend(got)
            print(f"  {venue}: {len(got)} events", file=sys.stderr)
        except (HTTPError, URLError) as e:
            failed.append(f"{venue} ({getattr(e, 'code', e)})")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{venue} ({e})")

    events.sort(key=lambda x: (x["date"], x["start"]))
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} events from {len(feeds) - len(failed)}/{len(feeds)} ICS feeds "
          f"-> {args.out}" + (f" | failed: {', '.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
