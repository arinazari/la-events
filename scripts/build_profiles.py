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


# ---------------------------------------------------------------------------
# Self-edit visibility (baked at build time, static-first)
# ---------------------------------------------------------------------------
# Surface HOW a profile's taste/profile YAML was adjusted (the concierge commits
# these edits) and WHETHER the latest adjustment has propagated into that profile's
# most recent *data enrichment* — the per-profile event-editor verdicts + the
# narrative digest the LLM pass commits. Both are derived from git here and baked
# into the feed, so the static dashboard can render a diff + a reflected/pending
# badge with no backend. Everything degrades to empty/None when git history is
# unavailable (e.g. a shallow CI checkout) — the page just hides the affordance.

# Automated re-rank/refresh/deploy commits — filtered out of the human-readable
# edit history so the list reads as *intent* (concierge + hand edits), not churn.
_AUTO_COMMIT_PREFIXES = ("build:", "rebuild:", "refresh:", "build(", "chore:", "deploy:")
_DIFF_LINE_CAP = 200


def _git(repo, *args):
    """Run a read-only git command; return stdout (str) or None on any failure."""
    try:
        r = subprocess.run(["git", *args], cwd=str(repo),
                           capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _last_commit(repo, paths):
    """Full SHA of the most recent commit touching any of `paths` (or None)."""
    out = _git(repo, "log", "-1", "--format=%H", "--", *paths)
    return (out or "").strip() or None


def _commit_date(repo, sha):
    """Committer date (YYYY-MM-DD) of `sha`, or None."""
    out = _git(repo, "show", "-s", "--format=%cI", sha) if sha else None
    return (out or "").strip()[:10] or None


def _cap_diff(text):
    lines = (text or "").splitlines()
    if len(lines) > _DIFF_LINE_CAP:
        lines = lines[:_DIFF_LINE_CAP] + ["@@ … diff truncated …"]
    return "\n".join(lines)


def _last_human_commit(repo, path):
    """SHA of the most recent NON-automated commit touching `path` (a concierge or hand
    edit), or None — mirrors the _edit_history filter so the 'latest change' diff and the
    history list always agree (a `build:`/`rebuild:` commit is not "your change")."""
    out = _git(repo, "log", "-n", "40", "--format=%H\x1f%s", "--", path)
    for line in (out or "").splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        if subject.strip().lower().startswith(_AUTO_COMMIT_PREFIXES):
            continue
        return sha.strip() or None
    return None


def _edit_history(repo, path, limit=6):
    """Recent human/concierge edits to `path`, newest first: [{date, summary}].
    Automated commits (re-rank/refresh/deploy) are dropped so it reads as intent."""
    out = _git(repo, "log", "-n", str(limit * 4), "--format=%cI\x1f%s", "--", path)
    hist = []
    for line in (out or "").splitlines():
        if "\x1f" not in line:
            continue
        iso, subject = line.split("\x1f", 1)
        subject = subject.strip()
        if subject.lower().startswith(_AUTO_COMMIT_PREFIXES):
            continue
        hist.append({"date": iso[:10], "summary": subject})
        if len(hist) >= limit:
            break
    return hist


def selfedit_block(repo, file_rel, enrich_paths):
    """Per-file visibility block for the dashboard's diff modal.

    Returns: {file, exists, history[], diff, diff_kind, reflected, enriched_at}.
      reflected  — the file is byte-identical between the last enrichment commit and
                   HEAD (content-based: an edit-then-revert correctly reads reflected).
                   None when it can't be determined (no git history / never enriched
                   is handled as not-reflected).
      diff_kind  — 'pending' (edits not yet in the enrichment), 'applied' (the latest
                   change, already live), or 'none'.
      diff       — a unified diff for that change (capped), '' when none.
      enrich_paths — the artifacts the LLM pass commits for this profile (its verdicts
                   + narrative digest); their last-commit time *is* "the most recent
                   data enrichment" we compare against.
    """
    block = {"file": file_rel, "exists": (repo / file_rel).exists(),
             "history": [], "diff": "", "diff_kind": "none",
             "reflected": None, "enriched_at": None}
    if not block["exists"]:
        return block  # e.g. a friend who hasn't created a personal profile.yaml yet
    block["history"] = _edit_history(repo, file_rel)
    edit_sha = _last_human_commit(repo, file_rel)        # the latest concierge/hand edit
    enr_sha = _last_commit(repo, list(enrich_paths))     # the latest enrichment (a rebuild: commit)
    block["enriched_at"] = _commit_date(repo, enr_sha)
    if enr_sha:
        pending = _cap_diff(_git(repo, "diff", f"{enr_sha}..HEAD", "--", file_rel) or "")
        if pending.strip():
            block.update(diff=pending, diff_kind="pending", reflected=False)
        else:
            applied = _cap_diff(_git(repo, "show", "--format=", edit_sha, "--", file_rel) or "") if edit_sha else ""
            block.update(diff=applied, diff_kind=("applied" if applied.strip() else "none"),
                         reflected=True)
    elif edit_sha:
        # No enrichment has ever been committed for this profile → the edit is, by
        # definition, not yet reflected. Show the latest change as the pending one.
        applied = _cap_diff(_git(repo, "show", "--format=", edit_sha, "--", file_rel) or "")
        block.update(diff=applied, diff_kind="pending", reflected=False)
    return block


def run_build(taste: str, profile: str, out: Path, profile_hash: str = None,
              editor_pool_out: str = None) -> bool:
    cmd = [sys.executable, str(BUILD), "--taste", taste, "--profile", profile, "-o", str(out)]
    if profile_hash:                       # load this profile's OWN music layer (per-profile Spotify)
        cmd += ["--profile-hash", profile_hash]
    if editor_pool_out:                    # emit this profile's editor judging pool for the LLM pass
        cmd += ["--editor-pool-out", editor_pool_out]
    print("  $ build_dashboard.py", "--taste", taste, "--profile", profile, "-o", out.name,
          *(["--profile-hash", profile_hash] if profile_hash else []),
          *(["--editor-pool-out", Path(editor_pool_out).name] if editor_pool_out else []))
    return subprocess.run(cmd, cwd=str(REPO)).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="profiles.yaml")
    ap.add_argument("--only", nargs="*", help="only build these usernames (skips the default feed)")
    ap.add_argument("--only-hash", nargs="*",
                    help="only build profiles whose feed hash matches (skips the default feed). "
                         "Lets the rebuild-profile workflow target a profile by its public hash, "
                         "since the dashboard only knows the hash, not the username.")
    ap.add_argument("--skip-default", action="store_true", help="don't rebuild dashboard/data.json")
    ap.add_argument("--inject-only", action="store_true",
                    help="don't re-score — only (re)inject the profile block (taste/profile YAML + "
                         "self_edit diff) into existing feeds. Safe backfill that preserves the scored "
                         "rows (and their Spotify ranking, which a standalone re-score would drop).")
    args = ap.parse_args()

    manifest = load_yaml(REPO / args.manifest) or {}
    salt = manifest.get("salt") or DEFAULT_SALT
    profiles = [p for p in (manifest.get("profiles") or []) if isinstance(p, dict) and p.get("username")]
    only = {u.strip().lower() for u in (args.only or [])}
    only_hash = {h.strip().lower() for h in (args.only_hash or [])}
    restricted = bool(only or only_hash)
    built = 0

    # Default feed (root taste/profile -> data.json), unless restricted to --only(-hash)/--skip-default.
    # --inject-only never touches the default feed (it carries no profile block).
    if not args.skip_default and not restricted and not args.inject_only:
        print("default -> dashboard/data.json")
        if run_build("taste.yaml", "profile.yaml", DASH / "data.json",
                     editor_pool_out=str(REPO / "data" / "editor_pool.json")):
            built += 1

    for p in profiles:
        u = p["username"]
        h = profile_hash(u, salt)
        if only and u.strip().lower() not in only:
            continue
        if only_hash and h.lower() not in only_hash:
            continue
        out = DASH / f"data.{h}.json"
        taste = p.get("taste") or "taste.yaml"
        is_owner = bool(p.get("owner"))
        print(f"{u} ({p.get('name') or u}) -> dashboard/data.{h}.json")
        # The owner shares the ROOT taste/profile/verdicts, so build their feed exactly like the
        # default (no per-hash verdict/Spotify lookup — those files don't exist for the owner) —
        # just written to the owner's hash + tagged with the owner block below.
        if args.inject_only:
            # Backfill: only (re)inject the profile block into the existing feed; no re-score.
            if not out.exists():
                print(f"  skip {u}: no existing feed to inject into (run a full build first)")
                continue
            ok = True
        elif is_owner:
            ok = run_build("taste.yaml", "profile.yaml", out)
        else:
            # Friend: their OWN profiles/<name>/profile.yaml if present, else ABSENT — the scorer
            # then falls back to their taste.yaml's `scoring` block (then DEFAULT_*). Friends do NOT
            # inherit the root (Ari's) profile.yaml, so a friend's taste.yaml fully drives their feed.
            profile = p.get("profile") or f"profiles/{u}/profile.yaml"
            ok = run_build(taste, profile, out, profile_hash=h,
                           editor_pool_out=str(REPO / "data" / f"editor_pool.{h}.json"))
        if not ok:
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
            # profile.yaml too: the concierge edits both (taste = artists/genres/venues;
            # profile = home/coords + scoring dials). Owner edits the root file; a friend
            # their own profiles/<name>/profile.yaml (may not exist until their first edit).
            profile_rel = "profile.yaml" if is_owner else (p.get("profile") or f"profiles/{u}/profile.yaml")
            try:
                block["profile_yaml"] = (REPO / profile_rel).read_text()
            except OSError:
                block["profile_yaml"] = None
            # How the concierge adjusted each file + whether that's reflected in this profile's
            # most recent enrichment. "Reflected" gates on the FULL LLM pass — the per-profile
            # narrative digest + verdicts — and uses the same bar for everyone, owner included. We
            # deliberately do NOT count the consolidated digest (digests/latest.md): a cheap
            # deterministic Refresh re-renders that without re-running the LLM, which would flip the
            # owner green before the AI actually reprocessed their taste.
            enrich_paths = [f"digests/{h}/latest.md", f"data/verdicts/{h}.json"]
            block["self_edit"] = {
                "taste": selfedit_block(REPO, taste, enrich_paths),
                "profile": selfedit_block(REPO, profile_rel, enrich_paths),
            }
            feed["profile"] = block
            out.write_text(json.dumps(feed, indent=2))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  WARN: could not inject profile block for {u}: {e}", file=sys.stderr)
        built += 1

    print(f"Built {built} feed(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
