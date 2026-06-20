#!/usr/bin/env python3
"""Turn a night-planner itinerary into a calendar file (.ics).

The planner/concierge passes the ordered stops as JSON; this writes one .ics with a VEVENT per
stop (LA-local times). End times are inferred so the blocks are contiguous — each stop runs until
the next one starts, and the last stop gets a default duration — unless a stop sets its own `end`.

Stop fields: summary (required), start ("HH:MM" with --date, or "YYYY-MM-DDTHH:MM"), end?,
location?, url?, description?.

Examples:
  python scripts/make_ics.py --date 2026-06-20 --out /tmp/sat.ics --calname "Sat 6/20" --stops-json '[
    {"summary":"Dinner — Santo","start":"19:30","location":"Santo, Silver Lake","url":"https://resy.com/..."},
    {"summary":"Bradley Zero","start":"22:00","location":"The Bridge, Arts District","url":"https://ra.co/..."}]'
  python scripts/make_ics.py --stops-file plan.json --out plan.ics
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.ics import build_ics  # noqa: E402


def _norm_start(s: str, date: str) -> str:
    """Combine a bare 'HH:MM' with --date; pass full datetimes through (space -> 'T')."""
    s = str(s or "").strip().replace(" ", "T")
    if "T" not in s and date:        # bare time like "19:30"
        return f"{date}T{s}"
    return s


def _parse(dt: str):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(dt[:19] if len(dt) >= 19 else dt, fmt)
        except ValueError:
            continue
    return None


def infer_ends(stops: list, last_minutes: int) -> list:
    """Fill missing `end`s: each stop runs until the next starts; the last gets last_minutes."""
    out = [dict(s) for s in stops]
    for i, s in enumerate(out):
        if s.get("end"):
            continue
        cur = _parse(s.get("start", ""))
        if not cur:
            continue
        if i + 1 < len(out):
            nxt = _parse(out[i + 1].get("start", ""))
            s["end"] = out[i + 1]["start"] if (nxt and nxt > cur) else (cur + timedelta(minutes=last_minutes)).strftime("%Y-%m-%dT%H:%M")
        else:
            s["end"] = (cur + timedelta(minutes=last_minutes)).strftime("%Y-%m-%dT%H:%M")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build an .ics from night-planner stops.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stops-json", help="JSON array of stops")
    src.add_argument("--stops-file", help="path to a JSON array of stops")
    ap.add_argument("--date", default="", help="YYYY-MM-DD to prefix bare HH:MM starts")
    ap.add_argument("--calname", default="LA night")
    ap.add_argument("--last-minutes", type=int, default=120, help="duration for the final stop")
    ap.add_argument("--out", default="plan.ics", help="output path, or '-' for stdout")
    args = ap.parse_args()

    raw = Path(args.stops_file).read_text() if args.stops_file else args.stops_json
    try:
        stops = json.loads(raw)
        assert isinstance(stops, list)
    except (ValueError, AssertionError):
        print("error: --stops-json/--stops-file must be a JSON array of stops", file=sys.stderr)
        return 2
    if not stops:
        print("error: no stops given", file=sys.stderr)
        return 2

    for s in stops:
        s["start"] = _norm_start(s.get("start", ""), args.date)
    ics = build_ics(infer_ends(stops, args.last_minutes), calname=args.calname)

    if args.out == "-":
        sys.stdout.write(ics)
    else:
        Path(args.out).write_text(ics)
        print(f"wrote {ics.count('BEGIN:VEVENT')} events → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
