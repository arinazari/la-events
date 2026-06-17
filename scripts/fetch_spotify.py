#!/usr/bin/env python3
"""Sync Spotify listening into the music-affinity artifact (Phase C).

OAuth in a stateless cloud repo: store a long-lived REFRESH token as a secret (like
TM_API_KEY / POSH_TOKEN) and exchange it for a short-lived access token each run. The
related-artists + audio-features endpoints were restricted for new apps in late 2024, so
we lean only on top / followed / recently-played (which stay available).

Secrets (env vars — never commit):
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET   from your app at developer.spotify.com
  SPOTIFY_REFRESH_TOKEN                       minted once via the `--authorize` flow below

One-time setup (mint the refresh token):
  1. Create an app at developer.spotify.com; add redirect URI  http://127.0.0.1:8888/callback
  2. export SPOTIFY_CLIENT_ID=...  SPOTIFY_CLIENT_SECRET=...
  3. python scripts/fetch_spotify.py --authorize            # prints an auth URL — open + approve
  4. Spotify redirects to  http://127.0.0.1:8888/callback?code=XXXX   # copy XXXX from the URL bar
  5. python scripts/fetch_spotify.py --authorize --code XXXX  # prints the SPOTIFY_REFRESH_TOKEN to set

Each run (sync):
  python scripts/fetch_spotify.py [-o data/spotify_affinity.json]

Scopes: user-top-read user-follow-read user-read-recently-played.
Network: needs accounts.spotify.com + api.spotify.com on the environment allowlist.

Degrades gracefully: missing creds / auth failure -> clear message, no artifact written,
exit 0 (never blocks a digest; the scorer just runs without the music layer).
"""

import argparse
import base64
import json
import os
import sys
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.affinity import build_affinity  # noqa: E402

AUTH = "https://accounts.spotify.com"
API = "https://api.spotify.com/v1"
SCOPES = "user-top-read user-follow-read user-read-recently-played"
DEFAULT_REDIRECT = "http://127.0.0.1:8888/callback"
UA = "la-events/1.0 (+https://github.com/arinazari/la-events)"
REPO = Path(__file__).resolve().parent.parent


def _basic(cid: str, secret: str) -> str:
    return base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _token_request(form: dict, cid: str, secret: str) -> dict:
    req = Request(f"{AUTH}/api/token", data=urllib.parse.urlencode(form).encode(),
                  headers={"Authorization": f"Basic {_basic(cid, secret)}",
                           "Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def refresh_access_token(cid: str, secret: str, refresh_token: str) -> str:
    tok = _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, cid, secret)
    return tok["access_token"]


def api_get(path: str, token: str, params: dict = None) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_top_artists(token: str) -> dict:
    """Top artists across all three windows: long_term ~ years, medium ~ 6mo, short ~ 4wk."""
    return {tr: api_get("/me/top/artists", token, {"time_range": tr, "limit": 50}).get("items", [])
            for tr in ("long_term", "medium_term", "short_term")}


def fetch_followed(token: str) -> list:
    items, after = [], None
    while True:
        params = {"type": "artist", "limit": 50}
        if after:
            params["after"] = after
        data = api_get("/me/following", token, params).get("artists", {})
        batch = data.get("items", [])
        items.extend(batch)
        after = (data.get("cursors") or {}).get("after")
        if not after or not batch:
            break
    return items


def fetch_recent(token: str) -> list:
    return api_get("/me/player/recently-played", token, {"limit": 50}).get("items", [])


def cmd_authorize(args, cid: str, secret: str) -> int:
    redirect = args.redirect or DEFAULT_REDIRECT
    if not args.code:
        params = {"client_id": cid, "response_type": "code", "redirect_uri": redirect, "scope": SCOPES}
        print("Open this URL, approve, then copy the `code` query param from the redirect:\n")
        print(f"  {AUTH}/authorize?{urllib.parse.urlencode(params)}\n")
        print(f"Then run:  python scripts/{Path(__file__).name} --authorize --code <code>"
              f"{'' if redirect == DEFAULT_REDIRECT else f' --redirect {redirect}'}")
        return 0
    tok = _token_request({"grant_type": "authorization_code", "code": args.code,
                          "redirect_uri": redirect}, cid, secret)
    rt = tok.get("refresh_token")
    if not rt:
        print(f"ERROR: no refresh_token in response: {tok}", file=sys.stderr)
        return 1
    print("Success — set this as a secret (do NOT commit it):\n")
    print(f"  SPOTIFY_REFRESH_TOKEN={rt}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Spotify listening -> data/spotify_affinity.json")
    ap.add_argument("-o", "--out", default="data/spotify_affinity.json")
    ap.add_argument("--authorize", action="store_true",
                    help="one-time OAuth helper to mint a refresh token")
    ap.add_argument("--code", help="authorization code from the redirect (use with --authorize)")
    ap.add_argument("--redirect", help=f"OAuth redirect URI (default {DEFAULT_REDIRECT})")
    args = ap.parse_args()

    cid, secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and secret):
        print("SKIP: set SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET (Spotify app credentials).",
              file=sys.stderr)
        return 0

    if args.authorize:
        try:
            return cmd_authorize(args, cid, secret)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            print(f"ERROR: token exchange failed: {e.code} {body}", file=sys.stderr)
            return 1

    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN")
    if not refresh_token:
        print("SKIP: set SPOTIFY_REFRESH_TOKEN (run `--authorize` once to mint it).", file=sys.stderr)
        return 0

    try:
        token = refresh_access_token(cid, secret, refresh_token)
        top, followed, recent = fetch_top_artists(token), fetch_followed(token), fetch_recent(token)
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        if e.code in (401, 403):
            print(f"WARN: Spotify auth rejected ({e.code}) — refresh token may be revoked; "
                  f"re-run --authorize. {body}", file=sys.stderr)
        else:
            print(f"WARN: Spotify fetch failed: {e.code} {body}", file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001 — degrade gracefully, never block a digest
        print(f"WARN: Spotify fetch failed: {e}", file=sys.stderr)
        return 0

    affinity = build_affinity(top, followed, recent)
    out = Path(args.out) if Path(args.out).is_absolute() else REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(affinity, indent=2, ensure_ascii=False) + "\n")

    na, ng = len(affinity["artists"]), len(affinity["genres"])
    core = sum(1 for a in affinity["artists"].values() if a["tier"] == "core")
    print(f"Wrote Spotify affinity -> {out} ({na} artists, {core} core; {ng} genres) "
          f"[top:{sum(len(v) for v in top.values())} followed:{len(followed)} recent:{len(recent)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
