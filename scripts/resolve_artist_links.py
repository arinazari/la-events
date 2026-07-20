#!/usr/bin/env python3
"""Resolve lineup / scene-graph artists to Spotify artist pages -> data/artist_links.json.

Thin CLI over lib/artist_links.refresh() — run_digest calls the same refresh on every run
(creds-gated, capped), so this exists for manual/backfill runs:

    SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python scripts/resolve_artist_links.py --max-new 500

Degrades gracefully: no creds or a dead API prints a SKIP/WARN line and exits 0.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from lib import artist_links as AL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new", type=int, default=AL.MAX_NEW_DEFAULT,
                    help=f"lookup cap for this run (default {AL.MAX_NEW_DEFAULT})")
    args = ap.parse_args()
    print(f"artist links: {AL.refresh(REPO, max_new=args.max_new)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
