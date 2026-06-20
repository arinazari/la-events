#!/usr/bin/env python3
"""Prune the enrichment cache to the live catalog (hygiene).

Drops event-enrichment entries whose event is gone from data/catalog.json (expired or
removed); KEEPS the artist bios (durable scene knowledge, reused across events). Keeps the
cache from growing unbounded as events come and go.

Run by the DAILY ROUTINE after run_digest rebuilds the catalog — NOT by the night-planner
(which stays read-only to durable state). Pure logic lives in lib/enrich.prune_cache (tested).

  python scripts/prune_enrichment.py            # prune data/enrichment.json vs data/catalog.json
  python scripts/prune_enrichment.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.enrich import load_cache, save_cache, prune_cache  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _resolve(p):
    p = Path(p)
    return p if p.is_absolute() else REPO / p


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune the enrichment cache to the live catalog.")
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    enr_p = _resolve(args.enrichment)
    if not enr_p.exists():
        print("no enrichment cache yet — nothing to prune")
        return 0
    cat_p = _resolve(args.catalog)
    catalog = json.loads(cat_p.read_text()) if cat_p.exists() else []
    cache = load_cache(enr_p)
    n_ev, n_ar = len(cache.get("events", {})), len(cache.get("artists", {}))
    cache, pruned = prune_cache(cache, catalog)
    tag = " (dry-run)" if args.dry_run else ""
    print(f"enrichment: {n_ev} events / {n_ar} artist bios → pruned {pruned} orphaned event entries"
          f" ({len(cache['events'])} kept); artist bios untouched{tag}")
    if pruned and not args.dry_run:
        save_cache(cache, enr_p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
