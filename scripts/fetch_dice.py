#!/usr/bin/env python3
"""Fetch live-music listings from DICE venue pages.

DICE's /browse page is JS-rendered (no Event JSON-LD in static HTML), but each
*venue* page — dice.fm/venue/<slug> — embeds schema.org MusicEvent JSON-LD with
startDate, performers, price, and ticket URL in the STATIC HTML. The catch: DICE
returns 403 to a default urllib User-Agent, so a real browser UA is mandatory.

This unlocks the eastside/indie live-music lane the structured APIs miss — Zebulon,
Gold Diggers, The Mint, 2220 Arts, Permanent Records, the Townhouse, The Virgil, etc.
Add slugs to VENUES below (or pass --venues) as Discover mode finds them.

Usage:
    python fetch_dice.py --days 21 [-o events_dice.json]
    python fetch_dice.py --venues zebulon-y8bv,gold-diggers-n2mq --days 30
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    from datetime import timezone, timedelta as _td
    LA = timezone(_td(hours=-7))

# Real Chrome UA is REQUIRED — DICE 403s the default urllib agent.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# slug -> (display name, neighborhood). DICE's JSON-LD address is just "Los Angeles",
# so we carry the neighborhood here. Grow this list in Discover mode.
VENUES = {
    "zebulon-y8bv":                     ("Zebulon", "Frogtown"),
    "gold-diggers-n2mq":                ("Gold Diggers", "East Hollywood"),
    "the-mint-5ggd":                    ("The Mint", "Mid-City"),
    "townhouse-venice-d8ve":            ("Del Monte Speakeasy", "Venice"),
    "the-virgil-39bl":                  ("The Virgil", "East Hollywood"),
    "2220-arts--archives-bdyv":         ("2220 Arts + Archives", "Historic Filipinotown"),
    "permanent-records-roadhouse-olyg": ("Permanent Records Roadhouse", "Cypress Park"),
    "the-silverlake-lounge-wb2v":       ("Silverlake Lounge", "Silver Lake"),
    "grand-star-jazz-club-6kx8":        ("Grand Star Jazz Club", "Chinatown"),
}

LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
ELECTRONIC_HINT = re.compile(
    r"\b(dj|techno|house|disco|rave|afters?|warehouse|club night|b2b|vinyl|selectors?)\b", re.I)


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def iter_events(obj):
    """Yield dicts whose @type looks like an Event, recursing graphs/lists."""
    if isinstance(obj, list):
        for x in obj:
            yield from iter_events(x)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.endswith("Event") for x in types if x):
            yield obj
        # DICE nests the MusicEvent array under a Place's "event" key.
        for k in ("event", "events", "@graph", "itemListElement", "item", "subEvent"):
            if k in obj:
                yield from iter_events(obj[k])


# NOTE (2026-06-17): DICE's venue JSON-LD now ships `offers: []` and NO `performer` field —
# the lineup is embedded in the event `name` (comma-separated). So performers()/price() return
# empty BY DESIGN now, not by bug; lineup is best parsed from the title at enrichment time.
def performers(ev):
    p = ev.get("performer")
    if not p:
        return []
    p = p if isinstance(p, list) else [p]
    out = []
    for x in p:
        name = x.get("name") if isinstance(x, dict) else str(x)
        if name:
            out.append(strip_html(name))
    return out


def price(ev):
    off = ev.get("offers")
    if not off:
        return None
    off = off[0] if isinstance(off, list) and off else off
    if not isinstance(off, dict):
        return None
    lo = off.get("lowPrice") or off.get("price")
    hi = off.get("highPrice")
    if lo in (None, "", "0", "0.00", 0):
        return "free" if off.get("price") in ("0", "0.00", 0) else None
    return f"${lo}-{hi}" if hi and hi != lo else f"${lo}"


def fetch_venue(slug, name, hood, now, hi):
    url = f"https://dice.fm/venue/{slug}"
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=45) as resp:
        body = resp.read().decode("utf-8", "replace")

    seen, out = set(), []
    for block in LDJSON_RE.findall(body):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for ev in iter_events(data):
            raw = ev.get("startDate")
            if not raw:
                continue
            try:
                when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            when = when.replace(tzinfo=LA) if when.tzinfo is None else when.astimezone(LA)
            if not (now.date() <= when.date() <= hi.date()):
                continue
            ev_url = ev.get("url") or url
            if ev_url in seen:
                continue
            seen.add(ev_url)
            title = strip_html(ev.get("name"))
            lineup = performers(ev)
            blob = f"{title} {' '.join(lineup)}"
            out.append({
                "source": "dice",
                "title": title,
                "date": when.date().isoformat(),
                "start": when.strftime("%H:%M"),
                "venue": name or ((ev.get("location") or {}).get("name")),
                "neighborhood": hood,
                "lineup": lineup,
                "category": "electronic" if ELECTRONIC_HINT.search(blob) else "music",
                "price": price(ev),
                "url": ev_url,
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", help="comma-separated DICE slugs (default: built-in VENUES)")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_dice.json")
    args = ap.parse_args()

    venues = {}
    if args.venues:
        for s in args.venues.split(","):
            s = s.strip()
            if s:
                venues[s] = VENUES.get(s, (s.replace("-", " ").title(), None))
    else:
        venues = VENUES

    now = datetime.now(LA)
    hi = now + timedelta(days=args.days)

    events, ok, failed = [], 0, []
    for slug, (name, hood) in venues.items():
        try:
            got = fetch_venue(slug, name, hood, now, hi)
            events.extend(got)
            ok += 1
            print(f"  {name}: {len(got)} events", file=sys.stderr)
        except (HTTPError, URLError) as e:
            failed.append(f"{slug} ({getattr(e, 'code', e)})")
            print(f"  WARN {name}: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{slug} ({e})")
            print(f"  WARN {name}: {e}", file=sys.stderr)

    events.sort(key=lambda x: (x["date"], x["start"]))
    with open(args.out, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Wrote {len(events)} events from {ok}/{len(venues)} DICE venues -> {args.out}"
          + (f" | failed: {', '.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
