#!/usr/bin/env python3
"""Tests for scripts/profile_refresh_gate.py — the nightly taste-change gate.

The contract: a friend's per-profile pass runs when THEIR config changed since their last
enrichment (or they've never been enriched), never merely because the catalog moved. Owner is
exempt. Content-based: edit-then-revert reads unchanged. No git history -> gate closed (SKIP).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import profile_refresh_gate as G  # noqa: E402
from build_profiles import profile_hash  # noqa: E402

SALT = "la-events/v1:"


def _sh(repo, *args):
    subprocess.run(args, cwd=str(repo), check=True, capture_output=True, text=True)


def _commit(repo, msg):
    _sh(repo, "git", "add", "-A")
    _sh(repo, "git", "commit", "-m", msg)


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


LORI = {"username": "lori", "taste": "profiles/lori/taste.yaml"}
OWNER = {"username": "ari", "taste": "taste.yaml", "owner": True}


def test_owner_is_exempt():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        _write(repo, "taste.yaml", "categories: {}\n")
        _commit(repo, "seed")
        d = G.decide(repo, OWNER, SALT)
        assert d["decision"] == "OWNER"


def test_never_enriched_refreshes_once_then_settles():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        h = profile_hash("lori", SALT)
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal]\n")
        _commit(repo, "seed lori taste")
        # no enrichment ever committed -> first pass
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "REFRESH" and "never enriched" in d["reason"]
        # the pass lands its artifacts -> gate closes
        _write(repo, f"digests/{h}/latest.md", "# Lori digest\n")
        _write(repo, f"data/verdicts/{h}.json", "{}\n")
        _commit(repo, "rebuild: LLM digest + verdicts for profile " + h)
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "SKIP"
        assert d["enriched_at"]  # the date of the enrichment commit is reported


def test_catalog_style_commits_do_not_trigger_but_taste_edit_does():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        h = profile_hash("lori", SALT)
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal]\n")
        _write(repo, f"digests/{h}/latest.md", "# Lori digest\n")
        _write(repo, f"data/verdicts/{h}.json", "{}\n")
        _commit(repo, "seed + enrich")
        # A catalog/digest commit (the world moved, not her taste) must NOT open the gate.
        _write(repo, "data/catalog.json", "[]\n")
        _write(repo, "digests/latest.md", "# consolidated\n")
        _commit(repo, "digest: 2026-07-15 (nightly)")
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "SKIP"
        # Her own taste edit DOES.
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal, Peggy Gou]\n")
        _commit(repo, "concierge: track Peggy Gou for lori")
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "REFRESH"
        assert d["changed"] == ["profiles/lori/taste.yaml"]


def test_edit_then_revert_reads_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        h = profile_hash("lori", SALT)
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal]\n")
        _write(repo, f"digests/{h}/latest.md", "# Lori digest\n")
        _write(repo, f"data/verdicts/{h}.json", "{}\n")
        _commit(repo, "seed + enrich")
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal, Peggy Gou]\n")
        _commit(repo, "concierge: track Peggy Gou")
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal]\n")
        _commit(repo, "concierge: never mind")
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "SKIP"  # content-based, like the reflected badge


def test_feedback_and_digest_prefs_count_as_taste():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _mkrepo(tmp)
        h = profile_hash("lori", SALT)
        _write(repo, "profiles/lori/taste.yaml", "artists_tracked: [Antal]\n")
        _write(repo, f"digests/{h}/latest.md", "# Lori digest\n")
        _write(repo, f"data/verdicts/{h}.json", "{}\n")
        _commit(repo, "seed + enrich")
        _write(repo, f"data/feedback.{h}.jsonl", '{"reaction": "loved"}\n')
        _commit(repo, "feedback: lori loved a show")
        d = G.decide(repo, LORI, SALT)
        assert d["decision"] == "REFRESH"
        assert d["changed"] == [f"data/feedback.{h}.jsonl"]


def test_no_git_history_gates_closed():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)  # deliberately NOT a git repo
        _write(repo, "profiles.yaml",
               "salt: 'la-events/v1:'\nprofiles:\n  - username: lori\n    "
               "taste: profiles/lori/taste.yaml\n")
        r = subprocess.run(
            [sys.executable, str(Path(G.__file__).resolve()), "--repo", str(repo)],
            capture_output=True, text=True)
        assert r.returncode == 0
        assert "SKIP" in r.stdout and "gate closed" in r.stdout
        assert "WARN" in r.stderr
