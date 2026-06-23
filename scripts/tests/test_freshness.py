#!/usr/bin/env python3
"""Tests for the freshness / change-tracking spine: content_version, freshest-wins merge, diff.

Run: python scripts/tests/test_freshness.py   (also pytest-compatible)
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import catalog_meta as CM  # noqa: E402
from lib import pipeline as P  # noqa: E402
from lib.dedupe import merge  # noqa: E402


def _ev(**kw):
    base = {"title": "Antal", "venue": "Zebulon", "date": "2026-07-01"}
    base.update(kw)
    return base


# ── content_version: identity vs. content ─────────────────────────────────────
def test_content_version_moves_on_price_but_identity_does_not():
    a, b = [_ev(price="$20")], [_ev(price="$30")]
    assert CM.version(a) == CM.version(b)                    # same event identity
    assert CM.content_version(a) != CM.content_version(b)    # price moved → content moved


def test_content_version_moves_on_lineup_growth_and_time_shift():
    base = [_ev(lineup=["Antal"], start="21:00")]
    grew = [_ev(lineup=["Antal", "Hunee"], start="21:00")]
    later = [_ev(lineup=["Antal"], start="22:00")]
    assert CM.content_version(base) != CM.content_version(grew)
    assert CM.content_version(base) != CM.content_version(later)


def test_content_version_is_lineup_order_insensitive():
    assert CM.content_version([_ev(lineup=["A", "B"])]) == CM.content_version([_ev(lineup=["B", "A"])])


# ── merge: freshest-wins for volatile, richest-wins for descriptive ───────────
def test_merge_freshest_volatile_wins():
    old = _ev(price="$20", start="21:00", lineup=["Antal"])
    new = _ev(price="$25", start="22:00", lineup=["Antal", "Hunee"], status="sold out")
    m = merge(old, new)                                      # merge_new feeds (old, new)
    assert m["price"] == "$25" and m["start"] == "22:00" and m["status"] == "sold out"
    assert m["lineup"] == ["Antal", "Hunee"]


def test_merge_keeps_richer_lineup_over_a_sparse_refetch():
    old = _ev(lineup=["Antal", "Hunee", "Jex"])
    new = _ev(lineup=["Antal"])
    assert merge(old, new)["lineup"] == ["Antal", "Hunee", "Jex"]


def test_merge_does_not_let_null_clobber_a_known_price():
    assert merge(_ev(price="$20"), _ev(price=None))["price"] == "$20"


# ── diff_catalog: the change summary + the per-record stamps ──────────────────
def test_diff_catalog_flags_added_and_updated_and_stamps():
    old = [_ev(price="$20")]
    idx = P.content_index(old)
    new = [_ev(price="$25"), _ev(title="New Show", venue="Lodge Room", date="2026-07-02")]
    delta = P.diff_catalog(idx, new, today=date(2026, 6, 23))
    assert delta["added"] == 1 and delta["updated"] == 1
    upd = [e for e in new if e.get("changed_fields")]
    assert upd and "price" in upd[0]["changed_fields"]
    assert upd[0]["updated_at"] == "2026-06-23"
    assert delta["changes"][0]["fields"] == ["price"]


def test_diff_catalog_noop_when_unchanged():
    cat = [_ev(price="$20", lineup=["Antal"])]
    delta = P.diff_catalog(P.content_index(cat), cat, today=date(2026, 6, 23))
    assert delta["added"] == 0 and delta["updated"] == 0 and not delta["changes"]


# ── flag_stale: the ghost sweep ───────────────────────────────────────────────
def _future(days, **kw):
    base = {"title": "Show", "venue": "Zebulon", "sources": ["ra"]}
    base["date"] = (date(2026, 6, 23) + timedelta(days=days)).isoformat()
    base.update(kw)
    return base


def test_flag_stale_flags_a_dropped_event():
    today = date(2026, 6, 23)
    ghost = _future(5, last_seen=(today - timedelta(days=3)).isoformat())
    assert P.flag_stale([ghost], {"ra"}, today, horizon_days=120) == 1
    assert ghost["status"] == "unlisted"


def test_flag_stale_respects_guards():
    today = date(2026, 6, 23)
    seen = _future(5, last_seen=today.isoformat())                       # seen today → fine
    unfetched = _future(5, sources=["dice"], last_seen=(today - timedelta(days=5)).isoformat())
    far = _future(200, last_seen=(today - timedelta(days=5)).isoformat())  # beyond horizon
    assert P.flag_stale([seen, unfetched, far], {"ra"}, today, horizon_days=120) == 0
    assert "status" not in seen and "status" not in unfetched and "status" not in far
    # No successful structured fetch → judge nothing.
    ghost = _future(5, last_seen=(today - timedelta(days=9)).isoformat())
    assert P.flag_stale([ghost], set(), today, horizon_days=120) == 0


def test_flag_stale_clears_when_relisted():
    today = date(2026, 6, 23)
    back = _future(5, last_seen=today.isoformat(), status="unlisted")    # was flagged, seen again today
    P.flag_stale([back], {"ra"}, today, horizon_days=120)
    assert "status" not in back


def test_score_pool_drops_unlisted():
    from lib.config import load_taste, load_profile
    taste, profile = load_taste(), load_profile()
    today = date(2026, 6, 23)
    live = _future(3)
    dead = _future(3, title="Dead", venue="1642", status="unlisted")
    titles = {e["title"] for e in P.score_pool([live, dead], taste, profile, today=today)}
    assert "Show" in titles and "Dead" not in titles


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
    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
