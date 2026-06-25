#!/usr/bin/env python3
"""Tests for scripts/catalog_age.py — the freshness gate behind the scheduled refresh fallback.

Run: python scripts/tests/test_catalog_age.py   (also pytest-compatible)
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import catalog_age as CA  # noqa: E402

NOW = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)


def test_age_hours_math_and_unreadable_stamp():
    assert abs(CA.age_hours({"fetched_at": "2026-06-25T08:00:00+00:00"}, now=NOW) - 4.0) < 1e-6
    assert CA.age_hours({"fetched_at": "2026-06-25T08:00:00"}, now=NOW) == 4.0   # naive → UTC
    assert CA.age_hours({"fetched_at": "2026-06-23T07:59:17+00:00"}, now=NOW) > 52   # ~52h
    assert CA.age_hours({}, now=NOW) is None                                    # no stamp
    assert CA.age_hours({"fetched_at": "not-a-date"}, now=NOW) is None          # unparseable


def test_gate_exit_codes():
    # The gate's contract: exit 0 = stale = run the fallback; exit 1 = fresh = skip.
    orig = CA.age_hours
    try:
        CA.age_hours = lambda *a, **k: 50.0
        assert CA.main(["--stale-after", "20"]) == 0      # stale → run
        CA.age_hours = lambda *a, **k: 4.0
        assert CA.main(["--stale-after", "20"]) == 1      # fresh → skip (a run already landed)
        CA.age_hours = lambda *a, **k: 20.0
        assert CA.main(["--stale-after", "20"]) == 0      # at threshold counts as stale (>=)
        CA.age_hours = lambda *a, **k: None
        assert CA.main(["--stale-after", "20"]) == 0      # unknown stamp → run (fail safe)
    finally:
        CA.age_hours = orig


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
