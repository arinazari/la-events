#!/usr/bin/env python3
"""Fetch LA events from Posh (posh.vip) via its authenticated tRPC API.

Posh has no anonymous LA feed — the explore search is an authenticated tRPC call. This
replicates the logged-in browser request:

    GET https://posh.vip/api/web/v2/trpc/events.fetchMarketplaceEvents?input=<json>
    header: x-jwt-token: <POSH_TOKEN>

`input` mirrors the explore filters: sort (Trending), when (Today|This Week|This Month|
Right Now), location preset (Los Angeles + lat/long), limit, clientTimezone. Posh marketplace
surfaces a lot of warehouse/afterhours/party events with TBA "revealed after approval"
locations — squarely on-profile — plus the promoter (groupName/groupUrl) on every event.

AUTH: needs a Posh session JWT in the POSH_TOKEN env var. The token is ~30-day-lived; when
it expires the API returns an auth error and this prints a clear message (and degrades to an
empty result, never blocking a digest). Re-capture from a logged-in browser's network tab
(events.fetchMarketplaceEvents request, x-jwt-token header) and update POSH_TOKEN.

Usage:
    export POSH_TOKEN=...    # session JWT
    python fetch_posh.py --days 10 [--when "This Month"] [--sort Trending] [-o events_posh.json]
"""

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover
    LA = timezone(timedelta(hours=-7))

BASE = "https://posh.vip/api/web/v2/trpc/events.fetchMarketplaceEvents"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TBA_HINTS = ("revealed", "after approval", "tba", "secret", "upon rsvp")


def min_price(tickets):
    prices = [t.get("price") for t in (tickets or [])
              if isinstance(t, dict) and not t.get("priceHidden") and t.get("price") is not None]
    prices = [p for p in prices if isinstance(p, (int, float))]
    if not prices:
        return None
    lo = min(prices)
    return "free" if lo == 0 else f"${lo:g}"


def venue_name(ev):
    v = ev.get("venue") or {}
    name = (v.get("name") or "").strip()
    if name:
        return name
    addr = (v.get("address") or "").strip()
    if not addr or any(h in addr.lower() for h in TBA_HINTS):
        return "TBA (drops after RSVP/approval)"
    return addr


def normalize(ev):
    start = ev.get("startUtc")
    when = None
    if start:
        try:
            when = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(LA)
        except ValueError:
            when = None
    lineup = []
    for a in (ev.get("lineup") or []):
        if isinstance(a, dict):
            lineup.append(a.get("name") or a.get("title"))
        elif isinstance(a, str):
            lineup.append(a)
    hour = when.hour if when else None
    return {
        "source": "posh",
        "id": f"posh-{ev.get('_id')}",
        "title": ev.get("name"),
        "date": when.date().isoformat() if when else None,
        "start": when.strftime("%H:%M") if when else None,
        "venue": venue_name(ev),
        "lineup": [a for a in lineup if a],
        "price": min_price(ev.get("tickets")),
        "afterhours_flag": hour is not None and (hour >= 22 or hour < 6),
        "promoter": ev.get("groupName"),
        "flyer": ev.get("flyer"),
        "url": f"https://posh.vip/e/{ev.get('url')}" if ev.get("url") else None,
    }


def fetch(when: str, sort: str, limit: int, token: str):
    payload = {
        "sort": sort,
        "when": when,
        "search": "",
        "location": {"type": "preset", "location": "Los Angeles",
                     "lat": 34.0522, "long": -118.2437},
        "secondaryFilters": [],
        "where": "Los Angeles",
        "limit": limit,
        "clientTimezone": "America/Los_Angeles",
    }
    url = f"{BASE}?input={urllib.parse.quote(json.dumps(payload))}"
    req = Request(url, headers={
        "x-jwt-token": token,
        "content-type": "application/json",
        "accept": "*/*",
        "user-agent": UA,
        "referer": "https://posh.vip/explore",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--when", default="This Month",
                    choices=["Today", "This Week", "This Month", "Right Now"])
    ap.add_argument("--sort", default="Trending")
    ap.add_argument("--days", type=int, default=10, help="post-filter window from today (LA)")
    ap.add_argument("--limit", type=int, default=150)
    ap.add_argument("-o", "--out", default="events_posh.json")
    args = ap.parse_args()

    token = os.environ.get("POSH_TOKEN")
    if not token:
        print("ERROR: set POSH_TOKEN (session JWT from a logged-in posh.vip request)", file=sys.stderr)
        return 1

    try:
        data = fetch(args.when, args.sort, args.limit, token)
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        if e.code in (401, 403):
            print(f"ERROR: POSH_TOKEN rejected ({e.code}) — likely expired; re-capture it. {body}",
                  file=sys.stderr)
        else:
            print(f"WARN: Posh fetch failed: {e.code} {body}", file=sys.stderr)
        json.dump([], open(args.out, "w"))
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"WARN: Posh fetch failed: {e}", file=sys.stderr)
        json.dump([], open(args.out, "w"))
        return 0

    if isinstance(data, dict) and data.get("error"):
        msg = data["error"].get("message", "")
        print(f"WARN: Posh API error: {msg}", file=sys.stderr)
        json.dump([], open(args.out, "w"))
        return 0

    events = data.get("result", {}).get("data", {}).get("events", [])
    lo = datetime.now(LA).date()
    hi = lo + timedelta(days=args.days)
    out, seen = [], set()
    for ev in events:
        n = normalize(ev)
        if not n["date"]:
            continue
        d = datetime.strptime(n["date"], "%Y-%m-%d").date()
        if not (lo <= d <= hi) or n["id"] in seen:
            continue
        seen.add(n["id"])
        out.append(n)

    out.sort(key=lambda e: (e["date"], e["start"] or ""))
    json.dump(out, open(args.out, "w"), indent=2)
    ah = sum(1 for e in out if e["afterhours_flag"])
    print(f"Wrote {len(out)} Posh events ({ah} afterhours) -> {args.out} "
          f"[{args.when}/{args.sort}, {len(events)} fetched]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
