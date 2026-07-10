#!/usr/bin/env python3
"""Fetch live-music listings from DICE venue pages.

DICE's /browse page is JS-rendered (no Event JSON-LD in static HTML), but each
*venue* page — dice.fm/venue/<slug> — embeds schema.org MusicEvent JSON-LD with
startDate, performers, price, and ticket URL in the STATIC HTML. The catch: DICE
returns 403 to a default urllib User-Agent, so a real browser UA is mandatory.

This unlocks the eastside/indie live-music lane the structured APIs miss — Zebulon,
Gold Diggers, The Mint, 2220 Arts, Permanent Records, the Townhouse, The Virgil, etc.
The slug list is read from the DICE entry's `venues:` in sources.yaml — the registry
Discover mode actually grows — so a new slug there is fetched with NO code change.
VENUES below only carries display metadata (name, neighborhood); add a row when you
know them, or let the slug-derived fallback stand.

Usage:
    python fetch_dice.py --days 21 [-o events_dice.json]
    python fetch_dice.py --venues zebulon-y8bv,gold-diggers-n2mq --days 30
"""

import argparse
import html
import json
import os
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

# slug -> (display name, neighborhood) — metadata ONLY, not the fetch list (that's the
# `venues:` list on the DICE entry in sources.yaml). DICE's JSON-LD address is just
# "Los Angeles", so the neighborhood has to live here.
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
    "sid-the-cat-auditorium-2wr5m":     ("Sid The Cat Auditorium", "South Pasadena"),
    "catch-one-e582":                   ("Catch One", "Mid-City"),
    "only-the-wild-ones-mxvwr":         ("Only The Wild Ones", "Venice"),
}

# DICE slugs end in a short id ("sid-the-cat-auditorium-2wr5m") — strip it for the
# derived display name when a slug has no VENUES row yet.
_SLUG_ID = re.compile(r"-[a-z0-9]{4,6}$")


def _venue_meta(slug):
    return VENUES.get(slug) or (_SLUG_ID.sub("", slug).replace("-", " ").title(), None)


_REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sources.yaml")


def registry_slugs(path=_REGISTRY):
    """The DICE entry's `venues:` slug list from sources.yaml — the single source of truth
    Discover mode grows. Falls back to the built-in VENUES keys if the registry is missing
    or unreadable (never let a yaml hiccup zero out the DICE lane)."""
    try:
        import yaml
        with open(path) as f:
            srcs = yaml.safe_load(f)["sources"]
        slugs = next((s.get("venues") for s in srcs if s.get("method") == "dice"), None)
        if slugs:
            return [str(s).strip() for s in slugs if str(s).strip()]
    except Exception as e:  # noqa: BLE001
        print(f"WARN: sources.yaml unreadable ({e}); using built-in VENUES", file=sys.stderr)
    return list(VENUES)

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
    ap.add_argument("--venues", help="comma-separated DICE slugs (default: sources.yaml `venues:` list)")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("-o", "--out", default="events_dice.json")
    args = ap.parse_args()

    slugs = ([s.strip() for s in args.venues.split(",") if s.strip()]
             if args.venues else registry_slugs())
    venues = {s: _venue_meta(s) for s in slugs}

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
