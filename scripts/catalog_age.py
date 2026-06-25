#!/usr/bin/env python3
"""Hours since the catalog was last fetched — the freshness gate for the scheduled refresh.

The nightly `refresh-events` cron is a FALLBACK for the full LLM Routine: it should only do work
when the Routine didn't land a run, so its deterministic render never clobbers the Routine's richer
LLM digest. This reports the age of `data/catalog_meta.json`'s `fetched_at` (which `run_digest`
stamps on every completed run). With `--stale-after N` it becomes a gate:

    exit 0  → catalog is >= N hours old (or the stamp is missing/unreadable)  → RUN the fallback
    exit 1  → catalog was refreshed < N hours ago (Routine or manual already ran)  → SKIP

A missing/unreadable stamp counts as stale (fail safe: refresh rather than silently skip).

    python scripts/catalog_age.py                 # print age in hours (or "inf")
    python scripts/catalog_age.py --stale-after 20  # gate: exit 0 if stale, 1 if fresh
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

META = Path(__file__).resolve().parent.parent / "data" / "catalog_meta.json"


def age_hours(meta: dict = None, now=None):
    """Hours since `fetched_at`. Returns None if there's no readable, parseable stamp."""
    if meta is None:
        try:
            meta = json.loads(META.read_text())
        except (OSError, ValueError):
            return None
    fetched = (meta or {}).get("fetched_at")
    if not fetched:
        return None
    try:
        ts = datetime.fromisoformat(fetched)
    except ValueError:
        return None
    if ts.tzinfo is None:                       # be defensive about a naive stamp
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 3600


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stale-after", type=float, default=None,
                    help="hours; exit 0 when the catalog is at least this stale, else exit 1")
    args = ap.parse_args(argv)

    h = age_hours()
    if args.stale_after is None:
        print("inf" if h is None else f"{h:.1f}")
        return 0

    if h is None:
        print("catalog age: unknown (no readable fetched_at) → treat as stale, run fallback")
        return 0
    stale = h >= args.stale_after
    print(f"catalog last fetched {h:.1f}h ago; threshold {args.stale_after:.0f}h → "
          f"{'STALE — run fallback' if stale else 'FRESH — skip (a run already landed)'}")
    return 0 if stale else 1


if __name__ == "__main__":
    sys.exit(main())
