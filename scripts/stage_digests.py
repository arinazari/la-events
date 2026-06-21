#!/usr/bin/env python3
"""Stage digests into the *published* dashboard tree (dashboard/digests/) at deploy time.

The dashboard fetches its digest relative to the page:
    ./digests/latest.md             -> the default / logged-out digest (newest)
    ./digests/index.json            -> the list of selectable past digests (newest first)
    ./digests/<date>.md             -> a specific past digest, picked from the modal's dropdown
    ./digests/<feed-hash>/latest.md -> the logged-in profile's digest
    ./digests/<feed-hash>/index.json + <feed-hash>/<date>.md -> that profile's past digests

This script populates those paths in `dashboard/` WITHOUT committing anything to the repo's
canonical `digests/` (the Pages deploy workflow runs it after build, before upload):

  dashboard/digests/latest.md         = the newest dated digest (digests/YYYY-MM-DD.md)
  dashboard/digests/<date>.md         = every dated digest (so the modal can show past ones)
  dashboard/digests/index.json        = [{path, file, date, title, latest}], newest first
  dashboard/digests/<hash>/...        = per-profile:
        owner:true profiles   -> the canonical digests (their taste IS the root taste, so their
                                  digest is the default one). The owner's index.json points back
                                  at the root-relative <date>.md files (no per-hash copies needed).
        friends with `digest:` -> their own <digest-dir>/*.md staged under the hash, plus an
                                  index.json with hash-prefixed paths.

Stdlib only (no pyyaml) so the deploy job needs no extra deps — profiles.yaml is a simple,
repo-controlled file, parsed line-by-line below.

Usage:
    python scripts/stage_digests.py                 # -> dashboard/digests/...
    python scripts/stage_digests.py --dest <dir>    # custom published dir
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SALT = "la-events/v1:"
DATED_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"


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


def digest_title(path: Path) -> str:
    """First ATX H1 (`# ...`) in the file, used as the dropdown label. Empty if none."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*#\s+(.*\S)\s*$", line)
            if m:
                return m.group(1).strip()
            if line.strip():           # bail at the first non-blank, non-heading line
                break
    except OSError:
        pass
    return ""


def build_index(dated, prefix: str = ""):
    """[{path, file, date, title, latest}] for `dated` (ascending paths), newest first.
    `prefix` is prepended to each path so the page can fetch it relative to ./digests/."""
    entries = [
        {"path": prefix + p.name, "file": p.name, "date": p.stem, "title": digest_title(p)}
        for p in sorted(dated)
    ]
    entries.reverse()                  # newest first (the page shows it as "latest")
    if entries:
        entries[0]["latest"] = True
    return entries


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(REPO / "dashboard" / "digests"))
    ap.add_argument("--digests", default=str(REPO / "digests"))
    ap.add_argument("--manifest", default=str(REPO / "profiles.yaml"))
    ap.add_argument("--repo", default=str(REPO))
    args = ap.parse_args(argv)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    digests = Path(args.digests)
    repo = Path(args.repo)

    dated = sorted(digests.glob(DATED_GLOB))
    # The default / logged-out digest: prefer the consolidated daily digest
    # (render_digest --consolidated -> digests/latest.md); fall back to the newest dated
    # ad-hoc digest for older setups that don't produce a consolidated one.
    consolidated = digests / "latest.md"
    default_src = consolidated if consolidated.is_file() else (dated[-1] if dated else None)
    if default_src:
        shutil.copy(default_src, dest / "latest.md")
        print(f"staged {default_src.name} -> {dest.name}/latest.md")
    for d in dated:                    # every dated digest, so the modal can show past ones
        shutil.copy(d, dest / d.name)
    default_index = build_index(dated)        # root-relative paths ("<date>.md") for the dropdown
    if dated:
        write_json(dest / "index.json", default_index)
        print(f"staged {len(dated)} dated digest(s) + index.json -> {dest.name}/")
    if not default_src:
        print("no digest found; the dashboard falls back to its bundled sample")

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print("no profiles.yaml; staged the default digest only")
        return 0
    salt, profiles = parse_profiles(manifest_path.read_text())
    for p in profiles:
        u = p.get("username")
        if not u:
            continue
        h = profile_hash(u, salt)
        is_owner = str(p.get("owner", "")).strip().lower() == "true"

        if is_owner and default_src:
            # Owner shares the canonical digests: copy latest.md for the logged-in view, and point
            # the per-hash index back at the root-relative <date>.md files (already staged above).
            (dest / h).mkdir(parents=True, exist_ok=True)
            shutil.copy(default_src, dest / h / "latest.md")
            write_json(dest / h / "index.json", default_index)
            print(f"staged owner digests -> {dest.name}/{h}/ (latest.md + index.json) ({u})")
            continue

        if p.get("digest"):
            digest_dir = repo / str(p["digest"]).strip("/")
            d_latest = digest_dir / "latest.md"
            d_dated = sorted(digest_dir.glob(DATED_GLOB))
            src_latest = d_latest if d_latest.is_file() else (d_dated[-1] if d_dated else None)
            if not src_latest:
                continue
            (dest / h).mkdir(parents=True, exist_ok=True)
            shutil.copy(src_latest, dest / h / "latest.md")
            for d in d_dated:                          # stage this profile's past digests
                shutil.copy(d, dest / h / d.name)
            if d_dated:
                write_json(dest / h / "index.json", build_index(d_dated, prefix=h + "/"))
            print(f"staged {p['digest']} -> {dest.name}/{h}/ ({u})")

    # Generic sweep: publish any per-profile digest written directly as digests/<hash>/latest.md
    # (the daily routine and the rebuild-profile workflow write there for friends that have no
    # explicit `digest:` field in profiles.yaml). Skip dirs already staged above.
    for d in sorted(digests.glob("*")):
        if not d.is_dir() or not re.fullmatch(r"[0-9a-f]{8,32}", d.name):
            continue
        latest = d / "latest.md"
        if not latest.is_file() or (dest / d.name / "latest.md").exists():
            continue
        (dest / d.name).mkdir(parents=True, exist_ok=True)
        shutil.copy(latest, dest / d.name / "latest.md")
        d_dated = sorted(d.glob(DATED_GLOB))
        for dd in d_dated:
            shutil.copy(dd, dest / d.name / dd.name)
        if d_dated:
            write_json(dest / d.name / "index.json", build_index(d_dated, prefix=d.name + "/"))
        print(f"swept digests/{d.name} -> {dest.name}/{d.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
