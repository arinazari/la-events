#!/usr/bin/env python3
"""Per-profile nightly refresh gate — friends' LLM passes run on TASTE change, not catalog change.

Policy (2026-07): a friend's personalized layer — their deterministic feed rebuild, per-profile
event-editor verdicts, and narrative digest — is NOT reapplied every night just because the events
catalog moved. It refreshes only when:

  1. that profile's own config changed since its last enrichment — taste.yaml / profile.yaml /
     digest.yaml (format prefs) / their feedback log — i.e. the person's taste, not the world; or
  2. the person clicks "Update my ranking & digest" on the dashboard (rebuild-profile.yml — the
     manual path, unchanged and always available); the dashboard nudges them with a popup when
     their ranking is 3+ days old.

This gate is the deterministic decision for (1): the nightly routine runs it once and only spends
feed rebuilds + LLM calls on the profiles it prints REFRESH for. "Changed since last enrichment"
is the same git-derived bar as the dashboard's reflected/pending badge (build_profiles.py
selfedit_block): content-based against the last commit that touched the profile's enrichment
artifacts (digests/<hash>/latest.md + data/verdicts/<hash>.json), so an edit-then-revert reads
unchanged. A profile that has NEVER been enriched refreshes once (its first pass), then settles
into the gate.

The owner is exempt (decision OWNER): their taste IS the root taste.yaml, which the nightly run
always re-scores (default feed + consolidated digest); their per-hash digest is a cheap copy.

Usage:
    python scripts/profile_refresh_gate.py                 # one line per profile + summary
    python scripts/profile_refresh_gate.py --json out.json # also write machine-readable decisions

Output lines:  <DECISION>  <username>  <hash>  (<reason>)   with DECISION in REFRESH|SKIP|OWNER.
Exit code is always 0 — the gate informs the routine; it never blocks it. If git history is
unavailable (shallow/broken clone) every friend SKIPs with a loud warning: the manual Update
button and the dashboard's 3-day nudge still cover them, which beats silently burning the full
LLM fan-out on a clone we can't gate.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from build_profiles import DEFAULT_SALT, _commit_date, _git, _last_commit, profile_hash  # noqa: E402
from lib.config import load_yaml  # noqa: E402


def watched_paths(p: dict, feed_hash: str) -> list:
    """The files whose change means "this person's taste moved": their taste YAML, their own
    profile.yaml (geo + scoring dials), their digest format prefs, and their reaction log —
    the same per-person config surface the concierge edits. Sources/events are deliberately
    NOT here; catalog movement alone never triggers a nightly per-profile pass."""
    u = p["username"]
    return [
        p.get("taste") or "taste.yaml",
        p.get("profile") or f"profiles/{u}/profile.yaml",
        p.get("digest_prefs") or f"profiles/{u}/digest.yaml",
        f"data/feedback.{feed_hash}.jsonl",
    ]


def enrich_paths(feed_hash: str) -> list:
    """The artifacts only a per-profile LLM pass commits — their last commit IS the most recent
    enrichment. Keep in sync with build_profiles.py (the reflected/pending badge uses the same)."""
    return [f"digests/{feed_hash}/latest.md", f"data/verdicts/{feed_hash}.json"]


def decide(repo: Path, p: dict, salt: str) -> dict:
    """One profile's decision: {username, hash, decision, reason, enriched_at, changed[]}."""
    u = p["username"]
    h = profile_hash(u, salt)
    out = {"username": u, "hash": h, "decision": "SKIP", "reason": "", "enriched_at": None,
           "changed": []}
    if p.get("owner"):
        out.update(decision="OWNER",
                   reason="owner — rides the nightly default feed + consolidated digest")
        return out
    enr_sha = _last_commit(repo, enrich_paths(h))
    out["enriched_at"] = _commit_date(repo, enr_sha)
    if not enr_sha:
        out.update(decision="REFRESH", reason="never enriched — first pass")
        return out
    # Content-based, like the dashboard's reflected badge: an edit that was reverted reads clean.
    diff = _git(repo, "diff", "--name-only", f"{enr_sha}..HEAD", "--", *watched_paths(p, h))
    changed = [ln.strip() for ln in (diff or "").splitlines() if ln.strip()]
    if changed:
        out.update(decision="REFRESH", changed=changed,
                   reason=f"taste changed since enrichment {out['enriched_at']}: "
                          + ", ".join(changed))
    else:
        out["reason"] = f"no taste/profile change since enrichment {out['enriched_at']}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="profiles.yaml")
    ap.add_argument("--repo", default=str(REPO), help="repo root (tests point this elsewhere)")
    ap.add_argument("--only", nargs="*", help="limit to these usernames")
    ap.add_argument("--json", dest="json_out", help="also write the decisions as JSON to this path")
    args = ap.parse_args()

    repo = Path(args.repo)
    manifest = load_yaml(repo / args.manifest) or {}
    salt = manifest.get("salt") or DEFAULT_SALT
    profiles = [p for p in (manifest.get("profiles") or [])
                if isinstance(p, dict) and p.get("username")]
    only = {u.strip().lower() for u in (args.only or [])}
    if only:
        profiles = [p for p in profiles if p["username"].strip().lower() in only]

    # No usable git history -> gate everything closed, loudly. The manual Update path (and the
    # dashboard's 3-day nudge) still cover every profile; a blind full fan-out would not be "gated".
    git_ok = bool((_git(repo, "rev-parse", "HEAD") or "").strip())
    if not git_ok:
        print("WARN: no git history here — SKIPping all friend profiles (gate needs a real clone; "
              "manual Update still works).", file=sys.stderr)

    decisions = []
    for p in profiles:
        if git_ok:
            d = decide(repo, p, salt)
        else:
            h = profile_hash(p["username"], salt)
            d = {"username": p["username"], "hash": h,
                 "decision": "OWNER" if p.get("owner") else "SKIP",
                 "reason": ("owner — rides the nightly default feed + consolidated digest"
                            if p.get("owner") else "git history unavailable — gate closed"),
                 "enriched_at": None, "changed": []}
        decisions.append(d)
        print(f"{d['decision']:<8} {d['username']:<14} {d['hash']}  ({d['reason']})")

    n = {"REFRESH": 0, "SKIP": 0, "OWNER": 0}
    for d in decisions:
        n[d["decision"]] += 1
    print(f"-- {n['REFRESH']} to refresh · {n['SKIP']} skipped (taste unchanged) · "
          f"{n['OWNER']} owner")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(decisions, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
