#!/usr/bin/env python3
"""Build the per-profile dashboard feeds for the profile switcher.

Reads profiles.yaml (the profile registry) and, for the DEFAULT (repo-root taste.yaml /
profile.yaml) plus each listed profile, runs build_dashboard.py to score the catalog against
THAT profile's taste and write its feed:

    default      -> dashboard/data.json
    <username>   -> dashboard/data.<hash>.json     (hash = profile_hash(username))

where profile_hash = first 16 hex of sha256(salt + lowercased username). The dashboard hashes
the typed username the same way (Web Crypto, same salt) to locate the file, so the username acts
as the access key. Each per-profile feed gets a small self-describing "profile" block injected
({name, hash, [digest]}) so the page can show the display name and find the profile's digest
without ever reading this manifest.

Scoring is NOT reimplemented here — it shells out to build_dashboard.py, which uses the same
scoring module the digest uses. So a profile's "recommended for you" can't drift from the digest.

Usage:
    python scripts/build_profiles.py                 # default + every profile
    python scripts/build_profiles.py --only demo     # just these usernames (skips default)
    python scripts/build_profiles.py --skip-default  # every profile, leave data.json untouched
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "scripts" / "build_dashboard.py"
DASH = REPO / "dashboard"

sys.path.insert(0, str(REPO / "scripts"))
from lib.config import load_yaml  # noqa: E402

DEFAULT_SALT = "la-events/v1:"


def profile_hash(username: str, salt: str) -> str:
    """Mirror of the page's hashing — keep both in sync if you change it."""
    return hashlib.sha256((salt + username.strip().lower()).encode("utf-8")).hexdigest()[:16]


def run_build(taste: str, profile: str, out: Path) -> bool:
    cmd = [sys.executable, str(BUILD), "--taste", taste, "--profile", profile, "-o", str(out)]
    print("  $ build_dashboard.py", "--taste", taste, "--profile", profile, "-o", out.name)
    return subprocess.run(cmd, cwd=str(REPO)).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="profiles.yaml")
    ap.add_argument("--only", nargs="*", help="only build these usernames (skips the default feed)")
    ap.add_argument("--skip-default", action="store_true", help="don't rebuild dashboard/data.json")
    args = ap.parse_args()

    manifest = load_yaml(REPO / args.manifest) or {}
    salt = manifest.get("salt") or DEFAULT_SALT
    profiles = [p for p in (manifest.get("profiles") or []) if isinstance(p, dict) and p.get("username")]
    only = {u.strip().lower() for u in (args.only or [])}
    built = 0

    # Default feed (root taste/profile -> data.json), unless restricted to --only / --skip-default.
    if not args.skip_default and not only:
        print("default -> dashboard/data.json")
        if run_build("taste.yaml", "profile.yaml", DASH / "data.json"):
            built += 1

    for p in profiles:
        u = p["username"]
        if only and u.strip().lower() not in only:
            continue
        h = profile_hash(u, salt)
        out = DASH / f"data.{h}.json"
        taste = p.get("taste") or "taste.yaml"
        profile = p.get("profile") or "profile.yaml"
        print(f"{u} ({p.get('name') or u}) -> dashboard/data.{h}.json")
        if not run_build(taste, profile, out):
            print(f"  ERROR: build failed for {u}", file=sys.stderr)
            continue
        # Inject the self-describing profile block so the page needs only the hash. Includes the
        # raw taste.yaml text so the popup can show "your taste" read-only (no extra fetch).
        try:
            feed = json.loads(out.read_text())
            block = {"name": p.get("name") or u, "hash": h}
            if p.get("owner"):
                block["owner"] = True   # the dashboard reads this to unlock admin-only settings
            if p.get("digest"):
                block["digest"] = p["digest"]
            try:
                block["taste_yaml"] = (REPO / taste).read_text()
            except OSError:
                pass
            feed["profile"] = block
            out.write_text(json.dumps(feed, indent=2))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  WARN: could not inject profile block for {u}: {e}", file=sys.stderr)
        built += 1

    print(f"Built {built} feed(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
