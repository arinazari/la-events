#!/usr/bin/env python3
"""Tests for scripts/lib/catalog_meta.py — the version stamp behind the staleness check.

Run: python scripts/tests/test_catalog_meta.py   (also pytest-compatible)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import catalog_meta as CM  # noqa: E402


def _ev(venue, date, title):
    return {"venue": venue, "date": date, "title": title}


def test_version_is_order_independent():
    a = [_ev("X", "2026-06-20", "A"), _ev("Y", "2026-06-21", "B")]
    b = list(reversed(a))
    assert CM.version(a) == CM.version(b)


def test_version_ignores_volatile_seen_stamps():
    base = _ev("X", "2026-06-20", "A")
    noisy = dict(base, first_seen="2026-01-01", last_seen="2026-06-20", score=99)
    assert CM.version([base]) == CM.version([noisy])


def test_version_changes_on_add_drop_retitle_reschedule():
    a = [_ev("X", "2026-06-20", "A")]
    assert CM.version(a) != CM.version(a + [_ev("Z", "2026-06-22", "C")])      # add
    assert CM.version(a) != CM.version([])                                      # drop
    assert CM.version(a) != CM.version([_ev("X", "2026-06-20", "A2")])          # retitle
    assert CM.version(a) != CM.version([_ev("X", "2026-06-25", "A")])           # reschedule


def test_empty_catalog_is_stable():
    assert CM.version([]) == CM.version([])
    assert isinstance(CM.version([]), str) and len(CM.version([])) == 12


def test_write_then_read_roundtrips():
    cat = [_ev("X", "2026-06-20", "A")]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "catalog_meta.json"
        written = CM.write_meta(p, cat)
        read = CM.read_meta(p)
        assert read["version"] == written["version"] == CM.version(cat)
        assert read["count"] == 1
        assert "fetched_at" in read


def test_read_missing_is_empty_not_error():
    assert CM.read_meta("/nonexistent/catalog_meta.json") == {}


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
