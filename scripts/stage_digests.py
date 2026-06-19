#!/usr/bin/env python3
"""Stage digests into the *published* dashboard tree (dashboard/digests/) at deploy time.

The dashboard fetches its digest relative to the page:
    ./digests/latest.md            -> the default / logged-out digest
    ./digests/<feed-hash>/latest.md -> the logged-in profile's digest

This script populates those paths in `dashboard/` WITHOUT committing anything to the repo's
canonical `digests/` (the Pages deploy workflow runs it after build, before upload):

  dashboard/digests/latest.md        = the newest dated digest (digests/YYYY-MM-DD.md)
  dashboard/digests/<hash>/latest.md = per-profile:
        owner:true profiles   -> the canonical latest digest (their taste IS the root taste,
                                  so their digest is the default one — this is what makes the
                                  owner's logged-in view show a digest instead of "regenerate")
        friends with `digest:` -> their own <digest-dir>/latest.md, if present

Stdlib only (no pyyaml) so the deploy job needs no extra deps — profiles.yaml is a simple,
repo-controlled file, parsed line-by-line below.

Usage:
    python scripts/stage_digests.py                 # -> dashboard/digests/...
    python scripts/stage_digests.py --dest <dir>    # custom published dir
"""
import argparse
import hashlib
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SALT = "la-events/v1:"


def profile_hash(username: str, salt: str) -> str:
    """Same hash the page (Web Crypto) and build_profiles.py use."""
    return hashlib.sha256((salt + username.strip().lower()).encode("utf-8")).hexdigest()[:16]


def parse_profiles(text: str):
    """Minimal line parser for profiles.yaml -> (salt, [{username, owner, digest, ...}]).
    Deliberately tiny (no pyyaml): the file's shape is fixed and repo-controlled."""
    salt = DEFAULT_SALT
    profiles, cur = [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():  # top-level key
            m = re.match(r'salt:\s*["\']?(.+?)["\']?\s*$', line)
            if m:
                salt = m.group(1)
            cur = None
            continue
        m = re.match(r'\s*-\s*username:\s*["\']?([^"\'\s]+)', line)
        if m:
            cur = {"username": m.group(1)}
            profiles.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r'\s+(\w+):\s*["\']?(.*?)["\']?\s*$', line)
        if m and m.group(1) in ("name", "taste", "profile", "digest", "owner"):
            cur[m.group(1)] = m.group(2)
    return salt, profiles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(REPO / "dashboard" / "digests"))
    ap.add_argument("--digests", default=str(REPO / "digests"))
    ap.add_argument("--manifest", default=str(REPO / "profiles.yaml"))
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    digests = Path(args.digests)

    dated = sorted(digests.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"))
    latest = dated[-1] if dated else None
    if latest:
        shutil.copy(latest, dest / "latest.md")
        print(f"staged {latest.name} -> {dest.name}/latest.md")
    else:
        print("no dated digest found; the dashboard falls back to its bundled sample")

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print("no profiles.yaml; staged the default digest only")
        return 0
    salt, profiles = parse_profiles(manifest_path.read_text())
    for p in profiles:
        u = p.get("username")
        if not u:
            continue
        src = None
        if str(p.get("owner", "")).strip().lower() == "true" and latest:
            src = latest                                   # owner shares the canonical digest
        elif p.get("digest"):
            cand = REPO / str(p["digest"]).strip("/") / "latest.md"
            if cand.is_file():
                src = cand
        if not src:
            continue
        h = profile_hash(u, salt)
        (dest / h).mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest / h / "latest.md")
        print(f"staged {Path(src).name} -> {dest.name}/{h}/latest.md ({u})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
