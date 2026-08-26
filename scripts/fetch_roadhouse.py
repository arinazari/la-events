#!/usr/bin/env python3
"""Fetch events from the Permanent Records Roadhouse's own calendar (Cypress Park).

The venue's hand-authored page is the calendar of record: ticketing migrated from DICE
to Opendate (app.opendate.io) mid-2026, so the DICE venue slug now catches only a sliver
(4 events vs ~55 on the page, checked 2026-08-12), and the unticketed programming — free
in-stores (Fred Armisen's Playlist, Live!), vinyl happy hours, comedy, trivia — never
hits any ticketing feed at all.

Site quirks the parser is built around:
  - HTTP ONLY. The host doesn't answer https, so the WebFetch tool (which force-upgrades
    to https) cannot read it — this has to be a urllib fetcher, not a webfetch source.
  - 1996-vintage hand-edited HTML tables: no JSON-LD, occasionally unclosed <tr>s. The
    row PATTERN is stable though: image cell | main cell (optional RED status overlay +
    "<i>Weekday, Month Nth - TIME</i>" + <BR>-separated lineup) | price/tickets cell.
    We scan <td> cells in DOCUMENT ORDER (immune to broken row boundaries): a cell with
    a date heading is an event, the next cell — unless it's an image or another date —
    is its price/tickets.
  - No year on dates; the flyer image paths carry it (images/2026/08aug/…) — used as the
    year hint, else nearest-future rollover. Weekday names are hand-typed and sometimes
    WRONG ("Thursday, August 24th" on a Monday) — month+day is the truth, weekday ignored.
  - RESCHEDULED/CANCELLED shows stay listed under the old date with a red overlay — those
    rows are skipped (the listed date is not happening); "Record Store open / venue
    closed" placeholder rows are skipped too.

Usage:
    python fetch_roadhouse.py --days 150 [-o events_roadhouse.json]
"""

import argparse
import html
import json
import re
import sys
from datetime import date, timedelta
from urllib.request import Request, urlopen

URL = "http://roadhouse.permanentrecordsla.com/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
VENUE = "Permanent Records Roadhouse"
NEIGHBORHOOD = "Cypress Park"

CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
# Acts are one-per-source-line but the hand-typed separator wavers between <BR> and a
# bare newline ("Chico Detour\nThe Reflectors <BR>Agua" on the live page) — split on both.
BR = re.compile(r"<br\s*/?>|\n", re.I)
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
IMGYEAR = re.compile(r"images/(20\d{2})/", re.I)
# "<i>Wednesday, August 19th - 6-7:30PM</i>" — weekday required (so italic lineup notes
# like "w/ Special Guest Opener" never match), ordinal + time optional, weekday IGNORED.
DATE_I = re.compile(
    r"<i>\s*(?:Mon|Tues?|Wednes|Thurs?|Fri|Satur|Sun)day\s*,\s*"
    r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:-\s*([^<]*?))?\s*</i>",
    re.I)
STATUS_SKIP = re.compile(r"\b(rescheduled|cancell?ed|postponed|moved to)\b", re.I)
CLOSED = re.compile(r"record\s+store\s+open|venue\s+closed", re.I)
# Lineup lines that are billing notes, not artist names — kept as detail, not lineup.
# `feat` needs its boundary/suffix so bands named "Feathers"/"Featherweight" stay billed.
NOTE_LINE = re.compile(r"^(w/|with\s|feat(\.|uring)?\b|plus\s|\+\s|special\s+guest)", re.I)

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9  # the one common 4-letter abbreviation


def strip(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").strip()


def to_hhmm(timetext):
    """'7PM' -> '19:00'; '6-7:30PM' -> '18:00' (start of range, meridiem inherited from
    the range end); '12-6pm' -> '12:00'. None when there's no parseable clock time."""
    if not timetext:
        return None
    meridiems = re.findall(r"(am|pm)", timetext, re.I)
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", timetext, re.I)
    if not m or not meridiems:
        return None
    h, mins = int(m.group(1)), int(m.group(2) or 0)
    mer = (m.group(3) or meridiems[0]).lower()
    if not (1 <= h <= 12):
        return None
    return f"{h % 12 + (12 if mer == 'pm' else 0):02d}:{mins:02d}"


def infer_date(month: int, day: int, anchor: date, img_src: str):
    """Resolve the year-less month/day. The flyer image path (images/2026/08aug/…) is the
    site's own year stamp — but flyers get REUSED for months (the same triva2026.jpg rides
    every trivia row Aug→Dec), so a hint that lands meaningfully in the past is a stale
    reused flyer, not a past event: ignore it and fall through to nearest-future
    inference (else every January+ recurring row would silently drop from October on)."""
    ym = IMGYEAR.search(img_src or "")
    if ym:
        try:
            d = date(int(ym.group(1)), month, day)
            if d >= anchor - timedelta(days=45):
                return d
        except ValueError:
            pass  # e.g. Feb 29 under a stale year — fall through
    for year in (anchor.year, anchor.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:  # Feb 29 in a non-leap year — try the next
            continue
        if d >= anchor - timedelta(days=45):
            return d
    return None


def parse_calendar(page: str, lo: date, hi: date) -> list:
    """Parse the calendar HTML into event dicts dated within [lo, hi]. `lo` doubles as
    the year-inference anchor (today, on a live run)."""
    cells = CELL.findall(page)
    events = []
    for i, cell in enumerate(cells):
        dm = DATE_I.search(cell)
        if not dm:
            continue
        if STATUS_SKIP.search(strip(cell)):
            continue  # rescheduled/cancelled — the listed date is not happening
        month = MONTHS.get(dm.group(1).lower())
        if not month:
            continue
        img_prev = cells[i - 1] if i > 0 and "<img" in cells[i - 1].lower() else ""
        img_m = re.search(r'src=["\']([^"\']+)["\']', img_prev)
        d = infer_date(month, int(dm.group(2)), lo, img_m.group(1) if img_m else "")
        if not d or not (lo <= d <= hi):
            continue

        # Lineup: everything after the date heading, one act per <BR> line.
        lines = [strip(l) for l in BR.split(cell[dm.end():])]
        lines = [l for l in lines if l]
        if not lines or CLOSED.search(" ".join(lines)):
            continue  # store-hours placeholder, not an event
        artists = [l for l in lines if not NOTE_LINE.match(l)]
        notes = [l for l in lines if NOTE_LINE.match(l)]
        if not artists:
            # A bill can't be ALL billing-notes — a solo act named "With Confidence" or
            # "Plus One" just tripped the note heuristic. Keep the lines as the bill
            # rather than silently dropping the event.
            artists, notes = lines, []

        # Price/tickets ride in the NEXT cell — unless that cell is the next row's
        # image or its own date heading (hand-edited rows sometimes drop the third td).
        price, links = None, []
        if i + 1 < len(cells) and "<img" not in cells[i + 1].lower() \
                and not DATE_I.search(cells[i + 1]):
            ptext = re.sub(r"buy\s+tickets?!?", " ", strip(cells[i + 1]), flags=re.I)
            ptext = re.sub(r"\s+", " ", ptext).strip(" .!")
            if re.search(r"sold\s*out", ptext, re.I):
                notes.append("SOLD OUT")
                ptext = re.sub(r"sold\s*out", " ", ptext, flags=re.I).strip()
            price = ptext or None
            seen = set()
            for href in HREF.findall(cells[i + 1]):
                if href.startswith("#") or href in seen:
                    continue
                seen.add(href)
                links.append(href)

        title = artists[0]
        events.append({
            "source": "roadhouse",
            "id": f"roadhouse-{d.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', title.lower())[:40]}",
            "title": title,
            "date": d.isoformat(),
            "start": to_hhmm(dm.group(3)),
            "venue": VENUE,
            "neighborhood": NEIGHBORHOOD,
            "category": "live_music",
            "lineup": artists,
            "price": price,
            "detail": "; ".join(notes) or None,
            "links": [{"source": "roadhouse", "url": u} for u in links],
            "url": links[0] if links else URL,
        })

    # de-dup identical (date, title, start) — reposted rows
    seen, uniq = set(), []
    for e in events:
        k = (e["date"], e["title"].lower(), e["start"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=150,
                    help="window; the page lists ~4 months out, so far-horizon capable")
    ap.add_argument("-o", "--out", default="events_roadhouse.json")
    args = ap.parse_args()

    try:
        req = Request(URL, headers={"User-Agent": UA})
        with urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"WARN: roadhouse fetch failed: {e}", file=sys.stderr)
        with open(args.out, "w") as f:
            json.dump([], f)
        # Non-zero ON PURPOSE: run_digest then records a FAILED fetch (run continues,
        # footer lists it). Exiting 0 with [] would count as ok:0, put 'roadhouse' in
        # fetched_ok, and the ghost sweep would unlist the venue's entire future
        # calendar as "dropped from its source".
        return 1

    today = date.today()
    uniq = parse_calendar(page, today, today + timedelta(days=args.days))
    with open(args.out, "w") as f:
        json.dump(uniq, f, indent=2)
    print(f"Wrote {len(uniq)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
