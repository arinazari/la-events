#!/usr/bin/env python3
"""Tests for build_profiles.py's enrichment-freshness stamp (selfedit_block / enrich_paths_for).

The regression this guards: the owner's nightly verdicts land in data/verdicts/default.json
(their taste IS the root taste.yaml), and their per-hash digest copy is committed only AFTER
the nightly feed bake. Watching only the per-hash paths therefore stamped the owner's
enriched_at a day old in every deployed feed, keeping the dashboard's "Update available"
lit permanently.

Run: python scripts/tests/test_build_profiles.py   (also pytest-compatible)
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import build_profiles as BP  # noqa: E402

H = "aaaa1111bbbb2222"  # any 16-hex feed hash


def _sh(repo, *args, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run(args, cwd=str(repo), check=True, capture_output=True, text=True, env=e)


def _commit(repo, msg, date):
    _sh(repo, "git", "add", "-A")
    _sh(repo, "git", "commit", "-m", msg,
        env={"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})


def _mkrepo(tmp):
    repo = Path(tmp)
    _sh(repo, "git", "init", "-q")
    _sh(repo, "git", "config", "user.email", "t@example.com")
    _sh(repo, "git", "config", "user.name", "t")
    return repo


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_enrich_paths_friend_vs_owner():
    assert BP.enrich_paths_for(H) == [f"digests/{H}/latest.md", f"data/verdicts/{H}.json"]
    assert BP.enrich_paths_for(H, owner=True) == [
        f"digests/{H}/latest.md", f"data/verdicts/{H}.json", "data/verdicts/default.json"]


def test_owner_stamp_sees_same_run_default_verdicts():
    """Nightly ordering: verdicts (default.json) commit -> feed bake -> owner digest copy.
    At bake time the newest owner enrichment is TODAY's verdicts commit, not yesterday's
    digest copy — the owner-aware paths must stamp today."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        _write(repo, "taste.yaml", "categories: {}\n")
        _commit(repo, "seed", "2026-07-16T12:00:00Z")
        _write(repo, f"digests/{H}/latest.md", "# digest 7/17\n")
        _commit(repo, "wip: owner digest copy + stamp for daily digest run", "2026-07-17T12:35:00Z")
        _write(repo, "data/verdicts/default.json", "{\"v\": 1}\n")
        _commit(repo, "wip: event-editor verdicts for daily digest run", "2026-07-18T12:31:00Z")

        blk = BP.selfedit_block(repo, "taste.yaml", BP.enrich_paths_for(H, owner=True))
        assert blk["enriched_at"] == "2026-07-18"
        assert blk["reflected"] is True   # no taste edit since the verdicts ran

        # The pre-fix (friend-style) paths read a day behind — the bug this test guards.
        stale = BP.selfedit_block(repo, "taste.yaml", BP.enrich_paths_for(H))
        assert stale["enriched_at"] == "2026-07-17"


def test_owner_taste_edit_after_verdicts_reads_pending():
    """A concierge edit AFTER the latest LLM pass must still read pending for the owner —
    default.json widens the freshness sources, not the reflected bar."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        _write(repo, "taste.yaml", "artists_tracked: [Antal]\n")
        _commit(repo, "seed", "2026-07-16T12:00:00Z")
        _write(repo, "data/verdicts/default.json", "{\"v\": 1}\n")
        _commit(repo, "wip: event-editor verdicts for daily digest run", "2026-07-18T12:31:00Z")
        _write(repo, "taste.yaml", "artists_tracked: [Antal, Hunee]\n")
        _commit(repo, "concierge: track Hunee", "2026-07-18T20:00:00Z")

        blk = BP.selfedit_block(repo, "taste.yaml", BP.enrich_paths_for(H, owner=True))
        assert blk["reflected"] is False
        assert blk["diff_kind"] == "pending"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok {fn.__name__}")
    print(f"{len(fns)} passed")
