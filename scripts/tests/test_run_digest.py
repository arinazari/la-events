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
    ra = next(e for e in R.FETCHERS if e["source"] == "ra")
    assert tm.get("far") is True and not ra.get("far")
    # two-speed: TM reaches the far horizon, RA stays near
    assert R.fetch_window(tm, days=21, far_days=180) == 180
    assert R.fetch_window(ra, days=21, far_days=180) == 21
    # single-speed (far_days unset): everyone near — behaviour-preserving
    assert R.fetch_window(tm, days=21) == 21
    assert R.fetch_window(ra, days=21, far_days=None) == 21


def _run_affinity_with_fake_spotify(stdout, returncode=0):
    """Drive load_affinity_layer with a stubbed fetch_spotify subprocess + a present token,
    and return the recorded report['spotify']. Restores the globals it touches."""
    import os

    class _Proc:
        pass
    proc = _Proc(); proc.returncode = returncode; proc.stdout = stdout; proc.stderr = ""
    orig_run, orig_tok = R.subprocess.run, os.environ.get("SPOTIFY_REFRESH_TOKEN")
    R.subprocess.run = lambda *a, **k: proc
    os.environ["SPOTIFY_REFRESH_TOKEN"] = "present"
    try:
        report = {}
        R.load_affinity_layer(no_fetch=False, report=report, profile={})
        return report.get("spotify")
    finally:
        R.subprocess.run = orig_run
        if orig_tok is None:
            os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)
        else:
            os.environ["SPOTIFY_REFRESH_TOKEN"] = orig_tok


def test_spotify_refresh_failure_is_recorded_not_swallowed():
    """A revoked token (fetch_spotify exits 0 with a WARN line) is recorded ok=False — the
    digest footer reads this to disclose the degraded ranking instead of hiding it."""
    sp = _run_affinity_with_fake_spotify(
        "WARN: Spotify auth rejected (401) — refresh token may be revoked; re-run --authorize.")
    assert isinstance(sp, dict) and sp["ok"] is False
    assert "refresh token may be revoked" in sp["note"]
    assert not sp["note"].startswith("WARN")          # marker prefix stripped for clean display


def test_spotify_success_is_marked_ok():
    sp = _run_affinity_with_fake_spotify(
        "Wrote Spotify affinity -> data/spotify_affinity.json (42 artists, 9 core; 3 genres)")
    assert isinstance(sp, dict) and sp["ok"] is True


def test_clean_spotify_note_strips_markers():
    assert R._clean_spotify_note("SKIP: set SPOTIFY_CLIENT_ID …") == "set SPOTIFY_CLIENT_ID …"
    assert R._clean_spotify_note("Wrote Spotify affinity -> x") == "Wrote Spotify affinity -> x"


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
