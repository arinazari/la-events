#!/usr/bin/env python3
"""Rough travel times between LA stops — the night-planner's sequencing helper.

Pass an ordered list of stops (neighborhood names, event venues, dining restaurants,
or "home"); prints each leg's distance, mode (walk/drive), and rough minutes, plus the
route total. Use it to order dinner -> show -> afters and budget the clock. Estimates
are deliberately rough (straight-line + a congestion model) — see scripts/lib/geo.py.

Restaurant names resolve because this CLI augments the venue gazetteer with
restaurant->neighborhood from data/dining.json. For an unplaced stop, add it to
profile.yaml `geo.venues`/`geo.neighborhoods` or eyeball it.

Examples:
  python scripts/travel.py "home" "Quarter Sheets" "Zebulon" home
  python scripts/travel.py "Silver Lake" "DTLA" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.config import load_profile  # noqa: E402
from lib import geo  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def dining_aware_profile() -> dict:
    """Profile with the venue map augmented by restaurant->neighborhood from dining.json,
    so restaurant names (not just event venues) resolve to coordinates."""
    profile = load_profile() or {}
    geo_block = dict(profile.get("geo") or {})
    venues = dict(geo_block.get("venues") or geo.DEFAULT_VENUES)
    try:
        for r in json.loads((REPO / "data" / "dining.json").read_text()):
            if r.get("name") and r.get("neighborhood"):
                venues.setdefault(r["name"], r["neighborhood"])
    except (FileNotFoundError, ValueError):
        pass
    geo_block["venues"] = venues
    profile["geo"] = geo_block
    return profile


def main() -> int:
    ap = argparse.ArgumentParser(description="Rough LA travel times between an ordered list of stops.")
    ap.add_argument("stops", nargs="+", help="ordered stops: neighborhood, venue, restaurant, or 'home'")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    route = geo.plan_route(args.stops, dining_aware_profile())

    if args.json:
        print(json.dumps(route, indent=2, ensure_ascii=False))
        return 0

    for leg in route["legs"]:
        if leg["minutes"] is None:
            print(f"  {leg['from']}  →  {leg['to']}:  ?  ({leg['note']})")
        else:
            icon = "🚶" if leg["mode"] == "walk" else "🚗"
            print(f"  {leg['from']}  →  {leg['to']}:  {icon} {leg['mode']} "
                  f"~{leg['minutes']} min ({leg['miles']} mi)")
    print(f"  ── total: ~{route['total_minutes']} min moving, {route['total_miles']} mi")
    if route["unplaced"]:
        print(f"  ⚠ unplaced (estimate by hand): {', '.join(map(str, route['unplaced']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
