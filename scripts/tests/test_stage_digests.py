#!/usr/bin/env python3
"""Tests for scripts/stage_digests.py — staging digests + index.json into the dashboard tree.

Run: python scripts/tests/test_stage_digests.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stage_digests as S  # noqa: E402

SALT = "la-events/v1:"


def _scaffold(root: Path):
    """A tiny repo: two root digests, a friend with their own dated digest dir, plus profiles."""
    digests = root / "digests"
    digests.mkdir(parents=True)
    (digests / "2026-06-12.md").write_text("# LA Events — Fri 6/12 → Fri 6/19\n\nOlder.\n")
    (digests / "2026-06-19.md").write_text("# LA Events — Fri 6/19 → Fri 6/26\n\nNewest.\n")

    friend_dir = root / "digests" / "demo"
    friend_dir.mkdir(parents=True)
    (friend_dir / "2026-06-19.md").write_text("# Demo digest — 6/19\n\nFriend's own.\n")
    (friend_dir / "latest.md").write_text("# Demo digest — 6/19\n\nFriend's own.\n")

    (root / "profiles.yaml").write_text(
        'salt: "la-events/v1:"\n'
        "profiles:\n"
        "  - username: ari\n"
        "    name: Ari\n"
        "    owner: true\n"
        "  - username: demo\n"
        "    name: Demo\n"
        "    digest: digests/demo\n"
        "  - username: nobody\n"      # no digest dir, not owner -> staged nothing
        "    name: Nobody\n"
    )
    return digests


def _run(root: Path):
    dest = root / "dashboard" / "digests"
    S.main([
        "--dest", str(dest), "--digests", str(root / "digests"),
        "--manifest", str(root / "profiles.yaml"), "--repo", str(root),
    ])
    return dest


def test_default_index_and_dated_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _scaffold(root)
        dest = _run(root)

        # latest.md is the newest dated digest
        assert (dest / "latest.md").read_text().startswith("# LA Events — Fri 6/19")
        # every dated digest is staged so the modal can show past ones
        assert (dest / "2026-06-12.md").is_file() and (dest / "2026-06-19.md").is_file()

        idx = json.loads((dest / "index.json").read_text())
        assert [e["date"] for e in idx] == ["2026-06-19", "2026-06-12"]    # newest first
        assert idx[0].get("latest") is True and "latest" not in idx[1]
        assert idx[0]["path"] == "2026-06-19.md"                            # root-relative
        assert idx[0]["title"] == "LA Events — Fri 6/19 → Fri 6/26"        # parsed H1


def test_consolidated_latest_wins_over_dated():
    # When a consolidated digests/latest.md exists (render_digest --consolidated), it is the
    # default/logged-out digest AND the owner's — not the newest dated ad-hoc file. Dated files
    # still feed the "past digests" dropdown index.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        digests = _scaffold(root)
        (digests / "latest.md").write_text("# LA Events — 2026-06-20\n\nConsolidated daily.\n")
        dest = _run(root)

        assert (dest / "latest.md").read_text().startswith("# LA Events — 2026-06-20")  # consolidated
        h = S.profile_hash("ari", SALT)
        assert (dest / h / "latest.md").read_text().startswith("# LA Events — 2026-06-20")  # owner too
        idx = json.loads((dest / "index.json").read_text())                # dropdown = dated files
        assert [e["date"] for e in idx] == ["2026-06-19", "2026-06-12"]


def test_owner_shares_root_index():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _scaffold(root)
        dest = _run(root)
        h = S.profile_hash("ari", SALT)

        # owner gets a logged-in latest.md + an index pointing back at the ROOT <date>.md files
        assert (dest / h / "latest.md").read_text().startswith("# LA Events — Fri 6/19")
        idx = json.loads((dest / h / "index.json").read_text())
        assert idx[0]["path"] == "2026-06-19.md"          # root-relative (not hash-prefixed)
        assert [e["date"] for e in idx] == ["2026-06-19", "2026-06-12"]


def test_friend_with_own_digest_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _scaffold(root)
        dest = _run(root)
        h = S.profile_hash("demo", SALT)

        assert (dest / h / "latest.md").read_text().startswith("# Demo digest")
        assert (dest / h / "2026-06-19.md").is_file()
        idx = json.loads((dest / h / "index.json").read_text())
        assert idx[0]["path"] == h + "/2026-06-19.md"     # hash-prefixed, fetched under the hash
        assert idx[0]["title"] == "Demo digest — 6/19"


def test_friend_without_digest_is_skipped():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _scaffold(root)
        dest = _run(root)
        h = S.profile_hash("nobody", SALT)
        assert not (dest / h).exists()                    # nothing staged for them


def test_digest_title_parsing():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.md"
        p.write_text("\n\n#   Spaced  Title  \n\nbody\n")
        assert S.digest_title(p) == "Spaced  Title"
        p.write_text("no heading here\n# too late\n")
        assert S.digest_title(p) == ""                    # bails at first non-heading line


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, "-", repr(e))
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
