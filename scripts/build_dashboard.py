#!/usr/bin/env python3
"""Build the dashboard data feed from the catalog + taste profile.

Reads a catalog JSON (deduped event records), taste.yaml, and profile.yaml, scores
each event against the taste profile, and writes dashboard/data.json — the static
feed the dashboard (dashboard/index.html) loads. Scoring is imported from
scripts/lib/scoring.py — the SAME module the digest/run_digest.py use, so the
dashboard's "recommended for you" rating can't drift from the digest's ranking.

Usage:
    python scripts/build_dashboard.py                      # from data/catalog.json
    python scripts/build_dashboard.py -i data/sample-catalog.json   # demo data
    python scripts/build_dashboard.py -o dashboard/data.json

The dashboard is a pure viewer: it does NOT score. Re-run this after every digest
(or whenever the catalog changes) to refresh what the dashboard shows.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Make `lib` importable regardless of cwd (scripts/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_yaml  # noqa: E402
from lib.scoring import score_event, score_to_rating, parse_event_date  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data/catalog.json",
                    help="catalog JSON to read (default: data/catalog.json)")
    ap.add_argument("-o", "--out", default="dashboard/data.json")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    args = ap.parse_args()

    catalog_path = (REPO / args.input) if not Path(args.input).is_absolute() else Path(args.input)
    out_path = (REPO / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    taste_path = (REPO / args.taste) if not Path(args.taste).is_absolute() else Path(args.taste)
    profile_path = (REPO / args.profile) if not Path(args.profile).is_absolute() else Path(args.profile)

    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    with catalog_path.open() as f:
        catalog = json.load(f)
    taste = load_yaml(taste_path)
    profile = load_yaml(profile_path)

    # Spotify + feedback music layer (Phase C) — the same merged layer the digest scores
    # against (Spotify affinity folded with data/feedback.jsonl), so the dashboard stars match.
    # Graceful: absent/corrupt -> taste.yaml-only scoring.
    affinity = merged_affinity(REPO, profile)

    is_sample = "sample" in catalog_path.name
    today = date.today()

    events = []
    for ev in catalog:
        scored = score_event(ev, taste, profile, affinity)
        d = parse_event_date(ev)
        out = dict(ev)
        out["score"] = scored["score"]
        out["rating"] = score_to_rating(scored["score"], profile)
        out["reasons"] = scored["reasons"]
        out["iso_date"] = d.isoformat() if d else None
        out["is_past"] = bool(d and d < today)
        events.append(out)

    # Sort: upcoming first by date, then by rating desc within a date.
    events.sort(key=lambda e: (e["iso_date"] or "9999-12-31", -e["rating"]))

    neighborhoods = sorted({e["neighborhood"] for e in events if e.get("neighborhood")})
    categories = sorted({e["category"] for e in events if e.get("category")})

    feed = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(catalog_path.relative_to(REPO)) if catalog_path.is_relative_to(REPO) else str(catalog_path),
        "is_sample": is_sample,
        "count": len(events),
        "neighborhoods": neighborhoods,
        "categories": categories,
        "taste": {
            "venues_loved": taste.get("venues_loved") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
        },
        "events": events,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(feed, f, indent=2)
    rel_out = out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path
    print(f"Wrote {len(events)} events -> {rel_out}"
          f"{' (SAMPLE data)' if is_sample else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
