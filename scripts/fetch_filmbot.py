#!/usr/bin/env python3
"""Fetch rep-cinema showtimes from Filmbot/Nightjar-powered venues.

Many indie/rep cinemas run on Nightjar's "Filmbot" platform (a WordPress plugin). The
public-facing calendar is JS-rendered — no static HTML/JSON-LD — but the widget is backed
by a clean REST API under the `nj/v1` namespace:

    {site}/wp-json/nj/v1/showtime/listings   -> films currently programmed (meta)
    {site}/wp-json/nj/v1/showtime?per_page=N  -> individual showtimes (one post each)

Each showtime post carries `_datetime` (unix ts of the screening), a title of the form
"Film Name – M/D/YY @ H:MM pm", `_sold_out`, programming `series`, and a ticket `link`.
This fetcher hits that API directly — same data a headless browser would render, but
deterministic and cheap.

Verified venue: Vidiots (vidiotsfoundation.org). Any other nj/v1 cinema works via --site.
New Bev / American Cinematheque are NOT Nightjar (different stacks) — see sources.yaml.

Usage:
    python fetch_filmbot.py --days 14 [--site https://vidiotsfoundation.org] [-o events_filmbot.json]
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import images  # noqa: E402  (nj/v1/show featured_media_url -> poster, free from a bulk call)

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata missing
    LA = timezone(timedelta(hours=-7))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# strip a trailing " – 6/16/26 @ 1:00 pm" (en-dash or hyphen) from showtime titles
TITLE_SUFFIX = re.compile(r"\s*[–—-]\s*\d{1,2}/\d{1,2}/\d{2,4}\s*@.*$")
FORMAT = re.compile(r"\b(70mm|35mm|16mm|DCP|IMAX|nitrate)\b", re.I)


def get(url: str):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def clean_title(raw: str) -> str:
    return TITLE_SUFFIX.sub("", html.unescape(raw or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="https://vidiotsfoundation.org",
                    help="base URL of a Nightjar/Filmbot cinema")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--pages", type=int, default=8, help="max API pages (100 showtimes each)")
    ap.add_argument("-o", "--out", default="events_filmbot.json")
    args = ap.parse_args()

    base = args.site.rstrip("/") + "/wp-json/nj/v1/showtime"

    # film metadata (runtime / rating / year) keyed by normalized name
    meta = {}
    venue = None
    try:
        listings = get(base + "/listings")
        venue = listings.get("theater_name")
        for m in listings.get("movies", []):
            meta[(m.get("movie_name") or "").lower()] = {
                "runtime": m.get("runtime") or None,
                "rating": m.get("rating") or None,
                "year": m.get("release_year") or None,
            }
    except Exception as e:  # noqa: BLE001
        print(f"WARN: listings fetch failed: {e}", file=sys.stderr)

    # Posters (dashboard's top-events row): the show CPT carries featured_media_url; a couple of
    # bulk nj/v1/show pages map show-id -> poster, joined to each showtime via showtime_to_show.
    # Free (no LLM), a few paginated GETs; any miss just means the card shows no photo.
    show_base = args.site.rstrip("/") + "/wp-json/nj/v1/show"
    posters = {}
    for spage in range(1, 5):  # 100 shows/page; a rep house rarely programs more than a few hundred
        try:
            batch = get(f"{show_base}?per_page=100&page={spage}")
        except Exception:  # noqa: BLE001 — no posters is a graceful degrade, never a block
            break
        if not isinstance(batch, list) or not batch:
            break
        for s in batch:
            sid, purl = s.get("id"), images.clean(s.get("featured_media_url"))
            if sid and purl:
                posters[sid] = purl
        if len(batch) < 100:
            break

    lo = datetime.now(LA).replace(hour=0, minute=0, second=0, microsecond=0)
    hi = lo + timedelta(days=args.days)
    lo_ts, hi_ts = lo.timestamp(), hi.timestamp()

    rows = []
    for page in range(1, args.pages + 1):
        try:
            batch = get(f"{base}?per_page=100&page={page}")
        except Exception as e:  # noqa: BLE001
            print(f"WARN: page {page} failed: {e}", file=sys.stderr)
            break
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break

    events, seen = [], set()
    for r in rows:
        try:
            ts = int(r.get("_datetime"))
        except (TypeError, ValueError):
            continue
        if not (lo_ts <= ts <= hi_ts):
            continue
        when = datetime.fromtimestamp(ts, LA)
        raw = r["title"]["raw"] if isinstance(r.get("title"), dict) else r.get("title")
        name = clean_title(raw)
        if not name:
            continue
        key = (when.date().isoformat(), name.lower(), when.strftime("%H:%M"))
        if key in seen:
            continue
        seen.add(key)
        m = meta.get(name.lower(), {})
        fmt = FORMAT.search(raw or "")
        series = r.get("_series") or []
        rel = r.get("showtime_to_show") or []       # -> the show/movie post id the poster is keyed by
        show_id = rel[0] if isinstance(rel, list) and rel else None
        events.append({
            "source": "filmbot",
            "id": f"filmbot-{r.get('id')}",
            "title": name,
            "date": when.date().isoformat(),
            "start": when.strftime("%H:%M"),
            "venue": venue,
            "category": "film",
            "format": fmt.group(1).upper() if fmt else None,
            "runtime": m.get("runtime"),
            "rating": m.get("rating"),
            "year": m.get("year"),
            "series": series if isinstance(series, list) else [series],
            "sold_out": bool(r.get("_sold_out")),
            "image": posters.get(show_id),  # per-film poster (featured_media_url) — free
            "url": r.get("link"),
        })

    events.sort(key=lambda e: (e["date"], e["start"]))
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    so = sum(1 for e in events if e["sold_out"])
    print(f"Wrote {len(events)} showtimes from {venue or args.site} ({so} sold out) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
