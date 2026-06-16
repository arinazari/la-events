#!/usr/bin/env python3
"""Fetch LA electronic/dance events from 19hz.info.

19hz is the canonical grassroots LA dance-music calendar (clubs, warehouses, festivals).
No API or JSON-LD — it's HTML tables. Columns:
    Date/Time | Event Title @ Venue | Tags | Price | Age | Organizers | Links | (sortdate)
The trailing hidden cell carries a YYYY/MM/DD sort date, which we use as the source of
truth for the date; the visible Date/Time cell gives the time-of-day.

Usage:
    python fetch_19hz.py --days 14 [-o events_19hz.json]
"""

import argparse
import html
import json
import re
import sys
from datetime import date, datetime, timedelta
from urllib.request import Request, urlopen

URL = "https://19hz.info/eventlisting_LosAngeles.php"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
DATECELL = re.compile(r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b")
TIME = re.compile(r"\(([^)]*\d[^)]*)\)")

# afterhours heuristic: any start hour >= 10pm or <= 5am, or explicit late tokens
LATE = re.compile(r"\b(after\s?hours|warehouse|all night|2am|3am|4am|5am|6am|late)\b", re.I)


def strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def parse_time(cell_text: str):
    m = TIME.search(cell_text)
    return m.group(1).strip() if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("-o", "--out", default="events_19hz.json")
    args = ap.parse_args()

    try:
        req = Request(URL, headers={"User-Agent": UA})
        with urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: 19hz fetch failed: {e}", file=sys.stderr)
        with open(args.out, "w") as f:
            json.dump([], f)
        return 0

    lo, hi = date.today(), date.today() + timedelta(days=args.days)
    events = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        # 19hz data rows are: Date/Time | Title @ Venue | Price|Age | Organizers | Links | sortdate
        if len(cells) < 6:
            continue
        dm = DATECELL.search(cells[-1])
        if not dm:
            continue
        try:
            d = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        except ValueError:
            continue
        if not (lo <= d <= hi):
            continue

        dt_text = strip(cells[0])
        title_venue = strip(cells[1])
        if " @ " in title_venue:
            title, venue = title_venue.rsplit(" @ ", 1)
        else:
            title, venue = title_venue, None
        info = strip(cells[2])  # "price | age", either side may be blank
        price, age = (info.split("|", 1) + [""])[:2] if info else ("", "")
        price, age = price.strip() or None, age.strip() or None
        organizers = strip(cells[3]) or None
        time_str = parse_time(dt_text)
        links = HREF.findall(cells[4]) + HREF.findall(cells[1])
        # de-dup links, keep order, drop 19hz-internal anchors
        seen, clean = set(), []
        for l in links:
            if l.startswith("#") or l in seen:
                continue
            seen.add(l)
            clean.append(l)

        blob = f"{title} {organizers or ''} {dt_text}"
        afterhours = bool(LATE.search(blob))
        if time_str:
            hm = re.search(r"(\d{1,2})\s*(am|pm)", time_str, re.I)
            if hm:
                h = int(hm.group(1)) % 12 + (12 if hm.group(2).lower() == "pm" else 0)
                if h >= 22 or h <= 5:
                    afterhours = True

        events.append({
            "source": "19hz",
            "id": f"19hz-{d.isoformat()}-{abs(hash(title_venue)) % 10**8}",
            "title": title.strip(),
            "date": d.isoformat(),
            "start": time_str,
            "venue": venue.strip() if venue else None,
            "organizers": organizers,
            "price": price,
            "age": age,
            "afterhours_flag": afterhours,
            "links": clean,
            "url": clean[0] if clean else URL,
        })

    # de-dup identical (date,title,venue)
    seen, uniq = set(), []
    for e in events:
        k = (e["date"], (e["title"] or "").lower(), (e["venue"] or "").lower())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    with open(args.out, "w") as f:
        json.dump(uniq, f, indent=2)
    ah = sum(1 for e in uniq if e["afterhours_flag"])
    print(f"Wrote {len(uniq)} events ({ah} flagged afterhours) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
