#!/usr/bin/env python3
"""Rough travel times between LA stops — the night-planner's sequencing helper.

Pass an ordered list of stops (neighborhood names, known venues, or "home"); prints
each leg's distance, mode (walk/drive), and rough minutes, plus the route total. Use
it to order dinner -> show -> afters and budget the clock. Estimates are deliberately
rough (straight-line + a congestion model) — see scripts/lib/geo.py. For an unplaced
stop, add it to profile.yaml `geo.venues`/`geo.neighborhoods` or eyeball it.

Examples:
  python scripts/travel.py "Bar Franca" "Zebulon" home
  python scripts/travel.py "Silver Lake" "DTLA" --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.config import load_profile  # noqa: E402
from lib import geo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Rough LA travel times between an ordered list of stops.")
    ap.add_argument("stops", nargs="+", help="ordered stops: neighborhood, venue, or 'home'")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    profile = load_profile()
    route = geo.plan_route(args.stops, profile)

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
