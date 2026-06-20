#!/usr/bin/env python3
"""Tests for scripts/log_feedback.py — the concierge's feedback appender.

Run: python scripts/tests/test_log_feedback.py
Covers validation, the written line round-tripping through lib.feedback (so a logged
reaction actually moves the affinity layer), and the trailing-newline guard.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import log_feedback as LF  # noqa: E402
from lib.feedback import load_feedback, aggregate, apply_feedback  # noqa: E402


def test_build_record_valid():
    r = LF.build_record("loved", ["Antal", "Peggy Gou"], [], "great set")
    assert r["kind"] == "loved" and r["artists"] == ["Antal", "Peggy Gou"]
    assert r["note"] == "great set" and r["ts"]  # ts auto-filled
    assert "genres" not in r  # omitted when empty


def test_build_record_rejects_bad_kind_and_empty():
    for bad in [("flagrant", ["X"], []), ("loved", [], [])]:
        try:
            LF.build_record(*bad)
            assert False, f"should have raised for {bad}"
        except ValueError:
            pass


def test_append_roundtrips_through_feedback_loop():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "feedback.jsonl"
        LF.append_reaction(p, LF.build_record("loved", ["Antal"], [], ts="2026-06-19"))
        LF.append_reaction(p, LF.build_record("hide", ["Some Bro DJ"], [], ts="2026-06-19"))
        rx = load_feedback(p)
        assert len(rx) == 2
        agg = aggregate(rx)
        aff = apply_feedback(None, agg)
        # loved -> Antal present & positive; hide -> bro DJ forced to the hidden tier.
        assert any("antal" in k for k in aff["artists"])
        assert any(v.get("tier") == "hidden" for v in aff["artists"].values())


def test_append_fixes_missing_trailing_newline():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "feedback.jsonl"
        p.write_text('{"ts":"2026-06-18","kind":"loved","genres":["disco"]}')  # no newline
        LF.append_reaction(p, LF.build_record("loved", [], ["deep house"], ts="2026-06-19"))
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 2 and all(json.loads(l) for l in lines)  # both parse, didn't merge


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
    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
    sys.exit(1 if fails else 0)
