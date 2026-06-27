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

AUTH: needs a Posh session JWT in the POSH_TOKEN env var. The token is ~30-day-lived; Posh
mints it at OTP login and lets it lapse — there is no refresh endpoint (verified against the
web client), so it must be re-captured by hand roughly monthly. When it expires this degrades
to an empty result AND exits non-zero, so run_digest files Posh under `failed` and the digest
footer flags it ("Coverage gaps: posh (POSH_TOKEN expired — re-capture it)"). It never blocks
the digest — run_digest catches each fetcher's failure per-source. Re-capture from a logged-in
browser's network tab (events.fetchMarketplaceEvents request, x-jwt-token header), update
POSH_TOKEN, and the flag clears on the next run.

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


# Surfaced verbatim in the digest footer's "Coverage gaps" line (run_digest takes the LAST
# stderr line as the failure reason). Keep it concise + actionable — the how-to is in the
# module docstring. Posh has no token refresh, so expiry is an expected ~monthly re-capture.
EXPIRED_MSG = "POSH_TOKEN expired — re-capture it"
# Posh returns auth failures as 200-with-error-body, not HTTP 401 — an expired/invalid token
# comes back as {"error": {"message": "Error authenticating."}}. Match that (and related
# phrasings) so expiry surfaces the actionable EXPIRED_MSG, not a generic "Posh API error".
_AUTH_HINTS = ("authenticat", "unauth", "jwt", "token", "session", "forbidden", "expired", "log in")


def degrade(out_path: str, footer_msg: str, detail: str = "") -> int:
    """Write an empty result and exit non-zero so run_digest files Posh under `failed`
    (→ digest footer flag). The LAST stderr line becomes the footer reason, so `footer_msg`
    is printed last and kept concise; `detail` (printed first) is for the run log only.
    Non-zero never blocks the digest — fetch_all catches each fetcher's failure per-source."""
    json.dump([], open(out_path, "w"))
    if detail:
        print(f"  posh detail: {detail}", file=sys.stderr)
    print(footer_msg, file=sys.stderr)
    return 2


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
        if e.code in (401, 403):  # expired/invalid session JWT — the ~monthly re-capture
            return degrade(args.out, EXPIRED_MSG, detail=f"auth {e.code}: {body}")
        return degrade(args.out, f"Posh fetch failed: HTTP {e.code}", detail=body)
    except Exception as e:  # noqa: BLE001  — network/parse/etc: a coverage gap, not a block
        return degrade(args.out, f"Posh fetch failed: {str(e).splitlines()[0][:120]}")

    if isinstance(data, dict) and data.get("error"):
        msg = (data["error"].get("message") or "").strip()
        if any(k in msg.lower() for k in _AUTH_HINTS):  # auth error returned 200-with-body
            return degrade(args.out, EXPIRED_MSG, detail=f"tRPC error: {msg[:160]}")
        return degrade(args.out, f"Posh API error: {msg[:120]}")

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
