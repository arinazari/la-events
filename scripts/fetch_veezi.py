#!/usr/bin/env python3
"""Fetch rep-cinema showtimes from Veezi-powered venues (Vista, New Beverly, ...).

Veezi (Vista Group's cinema POS) exposes a PUBLIC, server-rendered sessions page:

    https://ticketing.uswest.veezi.com/sessions?siteToken=<token>

Two gotchas (both confirmed in sources.yaml): use the NO-trailing-slash form (the
`/sessions/` slash variant trips a Cloudflare __cf_bm challenge -> 0 bytes), and send a
real browser UA. The page renders the FULL slate server-side as static HTML — the Veezi
web-service API itself is per-cinema token-gated, but this page isn't — so we parse it
directly. Verified 2026-06-25: Vista 191 sessions, New Beverly 115, via plain GET.

Markup is a stable Veezi template, identical across venues:

    <div class="film ">
      <h3 class="title">Film Name (70mm)</h3>
      <p><span class="censor">PG-13</span> ...rating reason / series note...</p>
      <p class="film-desc">synopsis</p>                 # optional
      <div class="sessions">
        <div class="date-container">
          <h4 class="date">Thursday 25, June</h4>        # no year -> inferred forward
          <ul class="session-times">
            <li><a href=".../purchase/3710?siteToken=..."><time>11:00 AM</time></a></li>
            <li><a class="sold-out-session"><time>7:30 PM</time></a>
                <span class="screen-attribute tickets-sold-out">SOLD OUT</span></li>
          </ul>
        </div>
      </div>
    </div>

Each session's /purchase/<id> is globally unique per venue -> stable id + dedupe key.
Emits the same normalized shape as fetch_filmbot.py (run_digest's normalizer keeps
title/date/start/venue/category/detail/url; format/rating/sold_out ride along as extras).

Usage:
    python fetch_veezi.py --token <siteToken> [--venue "Vista Theater"] --days 21 [-o out.json]
    python fetch_veezi.py --html saved_page.html --venue "Vista Theater"   # offline/debug
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date as _date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import images  # noqa: E402  (per-film <img class="poster"> src -> a clean absolute URL, free)

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata missing
    LA = timezone(timedelta(hours=-7))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://ticketing.uswest.veezi.com/sessions"  # NO trailing slash (slash -> Cloudflare cf_bm)
POSTER_ORIGIN = BASE.rsplit("/", 1)[0]  # https://ticketing.uswest.veezi.com — posters are root-relative (/Media/Poster?...)

FORMAT = re.compile(r"\b(70mm|35mm|16mm|nitrate|DCP|IMAX)\b", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}

# A film block runs from one `class="film "` marker to the next (class attr STARTING with
# `film` + closing quote — so `film-desc` / `film-poster` never match).
FILM_SPLIT = re.compile(r'<div\s+class="film\s*"')
TITLE_RE = re.compile(r'<h3 class="title">\s*(.*?)\s*</h3>', re.S)
CENSOR_RE = re.compile(r'<span class="censor">\s*(.*?)\s*</span>', re.S)
DESC_RE = re.compile(r'<p class="film-desc">\s*(.*?)\s*</p>', re.S)
# Per-film poster inside the block: <img class="poster" src="/Media/Poster?siteToken=…&code=…">.
# (The page-background <img class="body-background film-poster"> has no src and sits outside any
# film block, so this only ever matches the real per-film artwork.)
POSTER_RE = re.compile(r'<img[^>]*class="poster"[^>]*src="([^"]+)"', re.I)
# A date-container = its date header + the session list that immediately follows.
DATECTR_RE = re.compile(
    r'<h4 class="date">\s*(.*?)\s*</h4>\s*<ul class="session-times">(.*?)</ul>', re.S)
LI_RE = re.compile(r'<li>(.*?)</li>', re.S)
TIME_RE = re.compile(r'<time>\s*(.*?)\s*</time>', re.S)
HREF_RE = re.compile(r'<a\s+href="([^"]*?/purchase/(\d+)[^"]*)"')
TITLE_TAG_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.S)


def get(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def parse_time(raw: str):
    t = clean(raw).upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(t, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def fmt_hm(hm: str) -> str:
    """'19:30' -> '7:30pm' (the digest's compact time style) for the per-showtime link label."""
    h, m = (int(x) for x in hm.split(":"))
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def parse_date(raw: str, today: _date):
    """'Thursday 25, June' -> date. No year in the markup; Veezi lists only upcoming
    sessions, so pick the nearest forward year (handles the Dec->Jan boundary)."""
    m = re.search(r"(\d{1,2})\s*,\s*([A-Za-z]+)", clean(raw))
    if not m:
        return None
    day, mon = int(m.group(1)), MONTHS.get(m.group(2).lower())
    if not mon:
        return None
    for yr in (today.year, today.year + 1):
        try:
            cand = _date(yr, mon, day)
        except ValueError:
            return None
        if cand >= today:
            return cand
    return None


def venue_from_html(doc: str):
    m = TITLE_TAG_RE.search(doc)
    if not m:
        return None
    name = re.sub(r"\s*Show ?Times?\s*$", "", clean(m.group(1)), flags=re.I).strip()
    if name and name == name.upper():        # VISTA THEATER -> Vista Theater
        name = name.title()
    return name or None


def parse(doc: str, venue: str, token: str, days: int) -> list:
    today = datetime.now(LA).date()
    hi = today + timedelta(days=days)
    tok8 = (token or "local")[:8]

    events, seen = [], set()
    for blk in FILM_SPLIT.split(doc)[1:]:        # [0] is the preamble before the first film
        tm = TITLE_RE.search(blk)
        if not tm:
            continue
        title = clean(tm.group(1))
        if not title:
            continue
        cm, dm = CENSOR_RE.search(blk), DESC_RE.search(blk)
        rating = clean(cm.group(1)) if cm else None
        desc = clean(dm.group(1)) if dm else None
        fmt_m = FORMAT.search(title) or (FORMAT.search(desc) if desc else None)
        fmt = fmt_m.group(1).upper() if fmt_m else None
        # Poster (dashboard's top-events row): the film block's own artwork, root-relative -> absolute.
        pm = POSTER_RE.search(blk)
        poster = None
        if pm:
            src = html.unescape(pm.group(1))
            poster = images.clean(POSTER_ORIGIN + src if src.startswith("/") else src)

        for dc in DATECTR_RE.finditer(blk):
            d = parse_date(dc.group(1), today)
            if not d or not (today <= d <= hi):
                continue
            iso = d.isoformat()
            for li in LI_RE.finditer(dc.group(2)):
                lihtml = li.group(1)
                tmt = TIME_RE.search(lihtml)
                start = parse_time(tmt.group(1)) if tmt else None
                if not start:
                    continue
                hm = HREF_RE.search(lihtml)
                url = html.unescape(hm.group(1)) if hm else f"{BASE}?siteToken={token or ''}"
                pid = hm.group(2) if hm else None
                sold_out = ("sold-out-session" in lihtml) or ("tickets-sold-out" in lihtml)
                key = pid or f"{iso}-{start}-{title.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                # Fold format into detail so the cinema/analog-film tagging (and the digest)
                # see the print gauge; format/rating/sold_out also ride as extras.
                detail = " · ".join(x for x in (fmt, desc) if x) or None
                # Per-showtime link label ("7:30pm", "10:30pm · sold out"): when dedupe folds a
                # night's showtimes into one record, the accumulated purchase links stay
                # tellable-apart instead of rendering as N identical venue buttons. Only real
                # per-session hrefs get one — the no-href fallback is the venue's generic
                # schedule page, shared across sessions, and a session-specific label on it
                # would lie once a second session hits the same fallback.
                events.append({
                    "source": "veezi",
                    "id": f"veezi-{tok8}-{pid or key}",
                    "title": title,
                    "date": iso,
                    "start": start,
                    "venue": venue,
                    "category": "film",
                    "format": fmt,
                    "rating": rating,
                    "sold_out": sold_out,
                    "image": poster,  # per-film Veezi poster — free from the same page
                    "detail": detail,
                    "url": url,
                    "url_label": (fmt_hm(start) + (" · sold out" if sold_out else "")) if hm else None,
                })
    events.sort(key=lambda e: (e["date"], e["start"], e["title"]))
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Veezi cinema showtimes (Vista, New Beverly, ...)")
    ap.add_argument("--token", help="Veezi siteToken (from the venue's ticketing URL)")
    ap.add_argument("--venue", help="venue display name (default: derived from the page <title>)")
    ap.add_argument("--html", help="parse a local HTML file instead of fetching (offline/debug)")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_veezi.json")
    args = ap.parse_args()

    if args.html:
        with open(args.html, encoding="utf-8", errors="replace") as f:
            doc = f.read()
    elif args.token:
        doc = get(f"{BASE}?siteToken={args.token}")
    else:
        print("ERROR: pass --token (or --html for offline parse)", file=sys.stderr)
        return 2

    venue = args.venue or venue_from_html(doc) or "Unknown Cinema"
    events = parse(doc, venue, args.token, args.days)

    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    so = sum(1 for e in events if e["sold_out"])
    print(f"Wrote {len(events)} showtimes from {venue} ({so} sold out) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
