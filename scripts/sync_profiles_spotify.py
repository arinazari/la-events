#!/usr/bin/env python3
"""Sync friends' per-profile Spotify into data/spotify/<hash>.json (per-profile music layer).

The companion to fetch_spotify.py (which syncs Ari's OWN account from $SPOTIFY_REFRESH_TOKEN).
Friends connect Spotify in the dashboard; the concierge Worker stores their refresh token in KV
and exposes — to an authed caller only — the RAW listening payloads (the token itself never
leaves Cloudflare). This script asks the Worker who's connected, pulls each one's raw payloads,
and folds them through lib/affinity.build_affinity (the SAME builder fetch_spotify.py uses, so a
friend's music layer can't drift from Ari's) into data/spotify/<hash>.json. build_profiles.py
then scores that profile's feed against it.

The artifact is gitignored (data/spotify/ — it's a friend's listening; regenerated each run).
Only the derived feed (dashboard/data.<hash>.json) is ever committed.

Config (env or flags):
  SPOTIFY_SYNC_URL    base URL of the deployed Worker (e.g. https://la-events-concierge.x.workers.dev)
  SPOTIFY_SYNC_TOKEN  the Worker's SPOTIFY_SYNC_TOKEN secret (Bearer-presented to /spotify/*)

Usage:
  python scripts/sync_profiles_spotify.py                 # every connected profile
  python scripts/sync_profiles_spotify.py --only <hash>   # just this feed hash (the CI fast path)

Degrades gracefully: no URL/token -> SKIP (exit 0, never blocks a digest); one profile failing
is logged and skipped, the rest still sync.
"""

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.affinity import build_affinity  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
UA = "la-events/1.0 (+https://github.com/arinazari/la-events)"


def _get(base: str, path: str, token: str, params: dict = None) -> dict:
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def sync_one(base: str, token: str, h: str, out_dir: Path) -> str:
    """Pull one profile's raw payloads from the Worker and write its affinity artifact."""
    payload = _get(base, "/spotify/fetch", token, {"profile": h})
    affinity = build_affinity(payload.get("top"), payload.get("followed"), payload.get("recent"))
    out = out_dir / f"{h}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(affinity, indent=2, ensure_ascii=False) + "\n")
    na = len(affinity["artists"])
    core = sum(1 for a in affinity["artists"].values() if a["tier"] == "core")
    return f"{h}: {na} artists ({core} core) -> data/spotify/{h}.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync friends' Spotify -> data/spotify/<hash>.json")
    ap.add_argument("--url", default=os.environ.get("SPOTIFY_SYNC_URL"),
                    help="Worker base URL (or $SPOTIFY_SYNC_URL)")
    ap.add_argument("--token", default=os.environ.get("SPOTIFY_SYNC_TOKEN"),
                    help="Worker SPOTIFY_SYNC_TOKEN (or $SPOTIFY_SYNC_TOKEN)")
    ap.add_argument("--only", help="sync just this feed hash (default: every connected profile)")
    ap.add_argument("--out-dir", default=str(REPO / "data" / "spotify"))
    args = ap.parse_args()

    if not (args.url and args.token):
        print("SKIP: set SPOTIFY_SYNC_URL + SPOTIFY_SYNC_TOKEN to sync per-profile Spotify "
              "(friends just won't have a music layer until then).", file=sys.stderr)
        return 0

    out_dir = Path(args.out_dir)
    try:
        if args.only:
            hashes = [args.only.strip().lower()]
        else:
            hashes = list((_get(args.url, "/spotify/connected", args.token) or {}).get("connected") or [])
    except (HTTPError, URLError, ValueError) as e:
        print(f"WARN: couldn't reach the Worker ({e}); skipping per-profile Spotify.", file=sys.stderr)
        return 0

    if not hashes:
        print("No profiles have connected Spotify yet — nothing to sync.")
        return 0

    synced = 0
    for h in hashes:
        if not h:
            continue
        try:
            print("  " + sync_one(args.url, args.token, h, out_dir))
            synced += 1
        except (HTTPError, URLError, ValueError, KeyError) as e:
            print(f"  WARN: {h} failed ({e}); skipped.", file=sys.stderr)

    print(f"Synced {synced}/{len(hashes)} connected profile(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
