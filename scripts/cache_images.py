#!/usr/bin/env python3
"""Cache enrichment hero images into the repo (data/images/) so digests don't hotlink-rot.

Runs after the scene-researcher enrichment, before render_digest. Idempotent: only fetches
images not already cached. Updates data/enrichment.json with image['cached'] paths.

Usage:
  python scripts/cache_images.py                          # data/enrichment.json -> data/images/
  python scripts/cache_images.py --enrichment X --dest Y
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.enrich import load_cache, save_cache  # noqa: E402
from lib.images import cache_enriched_images  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--dest", default="data/images")
    args = ap.parse_args()

    dest = REPO / args.dest if not Path(args.dest).is_absolute() else Path(args.dest)
    cache = load_cache(args.enrichment)
    n = cache_enriched_images(cache, dest)
    save_cache(cache, args.enrichment)
    total = sum(1 for e in cache.get("events", {}).values() if (e.get("image") or {}).get("cached"))
    print(f"cached {n} new image(s) -> {args.dest} ({total} total cached)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
