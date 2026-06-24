#!/usr/bin/env python3
"""Tests for scripts/run_digest.py orchestration — the graceful-degradation contract.

Run: python scripts/tests/test_run_digest.py   (also pytest-compatible)
Does NOT touch the network: run_fetcher is monkeypatched so the test is deterministic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import run_digest as R  # noqa: E402


def _raise(*_a, **_k):
    raise RuntimeError("boom")


def test_fetch_all_degrades_gracefully():
    """A failing fetcher lands in `failed`; unselected ones in `skipped`; no crash, no records."""
    orig = R.run_fetcher
    R.run_fetcher = _raise
    try:
        incoming, report = R.fetch_all(selected={"ra"}, days=7)
    finally:
        R.run_fetcher = orig
    assert incoming == []
    assert [s for s, _ in report["failed"]] == ["ra"]
    assert report["failed"][0][1] == "boom"
    # everything except the selected source was skipped, nothing crashed the run
    assert "ticketmaster" in report["skipped"] and "dice" in report["skipped"]
    assert "ra" not in report["skipped"]


def test_fetch_window_two_speed():
    """Far-capable sources (TM) widen to --far-days; near sources keep --days; no far_days => near."""
    tm = next(e for e in R.FETCHERS if e["source"] == "ticketmaster")
    dice = next(e for e in R.FETCHERS if e["source"] == "dice")
    assert tm.get("far") is True and not dice.get("far")
    # two-speed: TM reaches the far horizon, DICE stays near
    assert R.fetch_window(tm, days=21, far_days=180) == 180
    assert R.fetch_window(dice, days=21, far_days=180) == 21
    # single-speed (far_days unset): everyone near — behaviour-preserving
    assert R.fetch_window(tm, days=21) == 21
    assert R.fetch_window(dice, days=21, far_days=None) == 21


def test_missing_api_key_is_a_clean_skip_reason():
    """run_fetcher refuses (raises) when a required env var is absent — caught upstream."""
    import os
    entry = {"name": "X", "source": "x", "script": "nope.py", "args": [], "needs": ["DEFINITELY_UNSET_VAR_xyz"]}
    os.environ.pop("DEFINITELY_UNSET_VAR_xyz", None)
    try:
        R.run_fetcher(entry, days=7, tmpdir="/tmp")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "DEFINITELY_UNSET_VAR_xyz" in str(e)


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
