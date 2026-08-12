#!/usr/bin/env python3
"""Tests for scripts/digest_voice.py — the render+voice digest plumbing.

Run: python scripts/tests/test_digest_voice.py   (subprocess-driven: exit codes ARE the contract —
splice must fail loudly and leave the scaffold as the shippable fallback)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DV = [sys.executable, str(REPO / "scripts" / "digest_voice.py")]
HASH = "f9097a7ff01d7b4d"   # lori — a real profiles.yaml entry for resolve_profile

SCAFFOLD = """# LA Events — 2026-08-04
*2 picks across 2 days · ⭐ = top pick · ranked for your taste*
*Checked Sun 8/2*

## Tuesday · August 4

**Live music**
- `8pm` ⭐ **[Alpha Show](https://x.test/a)** — The Echo, Echo Park
  Alpha description line to be compressed.

- *Also:* [Side Thing](https://x.test/s) (Zebulon)

## Wednesday · August 5

- `9pm` **[Beta Night](https://x.test/b)** — Zebulon · $10
"""


def _setup(tmp):
    scaf = Path(tmp) / "scaffold.md"
    scaf.write_text(SCAFFOLD)
    return scaf, Path(tmp) / "picks.md", Path(tmp) / "out.md", Path(tmp) / "cache.json"


def _prep(scaf, picks, cache):
    return subprocess.run(DV + ["prep", "--hash", HASH, "--scaffold", str(scaf),
                                "--out", str(picks), "--cache", str(cache)],
                          capture_output=True, text=True)


def _splice(scaf, whys, out, cache):
    return subprocess.run(DV + ["splice", "--hash", HASH, "--scaffold", str(scaf),
                                "--whys", str(whys), "--out", str(out),
                                "--cache", str(cache), "--today", "Tue 8/5"],
                          capture_output=True, text=True)


def test_prep_numbers_picks_and_reports_json():
    with tempfile.TemporaryDirectory() as tmp:
        scaf, picks, _, cache = _setup(tmp)
        r = _prep(scaf, picks, cache)
        assert r.returncode == 0, r.stderr
        doc = picks.read_text()
        assert "1. [Tue 8/4]" in doc and "Alpha Show" in doc
        assert "2. [Wed 8/5]" in doc and "Beta Night" in doc
        assert "ctx: Alpha description" in doc
        assert "Side Thing" not in doc.split("PICKS")[1]      # Also rows are not work
        meta = json.loads(r.stdout.strip().splitlines()[-1])
        assert meta["picks"] == 2 and meta["todo"] == 2 and meta["cached"] == 0


def test_splice_appends_whys_verifies_and_caches():
    with tempfile.TemporaryDirectory() as tmp:
        scaf, picks, out, cache = _setup(tmp)
        whys = Path(tmp) / "whys.json"
        whys.write_text(json.dumps({"intro": "The take.", "regen_clause": "test run",
                                    "whys": [{"i": 1, "t": "Alpha Show", "why": "alpha why"},
                                             {"i": 2, "t": "Beta Night", "why": "beta why"}]}))
        r = _splice(scaf, whys, out, cache)
        assert r.returncode == 0, r.stderr
        md = out.read_text()
        assert "— *alpha why.*" in md and "— *beta why.*" in md
        assert "## Tue 8/4" in md and "## Wed 8/5" in md      # Day M/D headers
        assert "**Live music**" not in md                     # lane subheads dropped
        assert "Alpha description line" not in md             # ctx compressed away
        assert "*Digest regenerated Tue 8/5 — test run." in md
        assert "[Side Thing](https://x.test/s)" in md         # Also rows intact
        # link sequence preserved exactly
        import re
        seq = lambda t: re.findall(r"\]\((https?://[^)\s]+)\)", t)
        assert seq(SCAFFOLD) == seq(md)
        # cache now covers both picks -> a re-prep has nothing to write
        r2 = _prep(scaf, picks, cache)
        meta = json.loads(r2.stdout.strip().splitlines()[-1])
        assert meta["cached"] == 2 and meta["todo"] == 0


def test_splice_fails_on_title_misalignment():
    with tempfile.TemporaryDirectory() as tmp:
        scaf, _, out, cache = _setup(tmp)
        whys = Path(tmp) / "whys.json"
        whys.write_text(json.dumps({"intro": "x", "whys": [
            {"i": 1, "t": "Totally Wrong Title", "why": "w"},
            {"i": 2, "t": "Beta Night", "why": "w"}]}))
        r = _splice(scaf, whys, out, cache)
        assert r.returncode != 0 and "misalignment" in (r.stderr + r.stdout)
        assert not out.exists(), "a failed splice must not write output"


def test_splice_fails_on_missing_why():
    with tempfile.TemporaryDirectory() as tmp:
        scaf, _, out, cache = _setup(tmp)
        whys = Path(tmp) / "whys.json"
        whys.write_text(json.dumps({"intro": "x", "whys": [
            {"i": 1, "t": "Alpha Show", "why": "w"}]}))
        r = _splice(scaf, whys, out, cache)
        assert r.returncode != 0 and "no why" in (r.stderr + r.stdout)
        assert not out.exists()


def test_taste_change_invalidates_cache():
    with tempfile.TemporaryDirectory() as tmp:
        scaf, picks, out, cache = _setup(tmp)
        whys = Path(tmp) / "whys.json"
        whys.write_text(json.dumps({"intro": "x", "whys": [
            {"i": 1, "t": "Alpha Show", "why": "w1"},
            {"i": 2, "t": "Beta Night", "why": "w2"}]}))
        assert _splice(scaf, whys, out, cache).returncode == 0
        stale = json.loads(cache.read_text())
        stale["taste_hash"] = "0000000000000000"              # simulate a taste edit
        cache.write_text(json.dumps(stale))
        meta = json.loads(_prep(scaf, picks, cache).stdout.strip().splitlines()[-1])
        assert meta["cached"] == 0 and meta["todo"] == 2, "taste change must invalidate whys"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, "-", repr(e))
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
