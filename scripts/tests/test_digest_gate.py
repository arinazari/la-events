#!/usr/bin/env python3
"""Tests for scripts/digest_gate.py — signature stability + the decide/stamp/skip cycle."""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
import digest_gate as G  # noqa: E402


def _ev(title, rank, tier=None, iso="2999-07-01"):
    e = {"title": title, "venue": "Zebulon", "iso_date": iso, "final_rank": rank, "rating": 5}
    if tier:
        e["verdict"] = {"tier": tier}
    return e


def _feed(events):
    return {"events": events}


def test_signature_stable_and_sensitive_to_rank_and_tier():
    a = _feed([_ev("Antal", 1), _ev("Hunee", 2)])
    assert G.feed_signature(a) == G.feed_signature(_feed([_ev("Antal", 1), _ev("Hunee", 2)]))
    assert G.feed_signature(a) != G.feed_signature(_feed([_ev("Antal", 2), _ev("Hunee", 1)]))  # rank swap
    assert G.feed_signature(a) != G.feed_signature(_feed([_ev("Antal", 1, "must-see"), _ev("Hunee", 2)]))  # tier


def test_signature_moves_when_digest_prefs_change():
    """A pure FORMAT change (same picks) must move the signature so it regenerates once."""
    base = _feed([_ev("Antal", 1), _ev("Hunee", 2)])
    plain = G.feed_signature(base)
    brief = _feed([_ev("Antal", 1), _ev("Hunee", 2)])
    brief["profile"] = {"digest_prefs": {"length": "brief"}}
    detailed = _feed([_ev("Antal", 1), _ev("Hunee", 2)])
    detailed["profile"] = {"digest_prefs": {"length": "detailed"}}
    assert plain != G.feed_signature(brief)              # adding prefs moves it
    assert G.feed_signature(brief) != G.feed_signature(detailed)   # different prefs differ
    # stable for the same prefs regardless of key order
    again = _feed([_ev("Antal", 1), _ev("Hunee", 2)])
    again["profile"] = {"digest_prefs": {"length": "brief"}}
    assert G.feed_signature(brief) == G.feed_signature(again)


def test_signature_ignores_past_events():
    fut = _feed([_ev("Antal", 1)])
    with_past = _feed([_ev("Antal", 1),
                       {"title": "Old", "iso_date": "2000-01-01", "is_past": True, "final_rank": 2}])
    assert G.feed_signature(fut) == G.feed_signature(with_past)


def test_upsert_freshness_line_is_idempotent():
    md = "# Digest for X\n\nSome picks here.\n"
    line1 = G.FRESH_PREFIX + "regenerated Mon 6/22 — picks updated.*"
    out1 = G.upsert_freshness_line(md, line1)
    assert line1 in out1
    line2 = G.FRESH_PREFIX + "regenerated Mon 6/22 · checked Tue 6/23 · no new picks since.*"
    out2 = G.upsert_freshness_line(out1, line2)
    assert line2 in out2 and line1 not in out2          # replaced, not duplicated
    assert out2.count(G.FRESH_PREFIX) == 1


def _run(feed, md, mode):
    argv = ["digest_gate.py", mode, "--feed", str(feed), "--md", str(md)]
    old = sys.argv
    sys.argv = argv
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            G.main()
        return buf.getvalue().strip()
    finally:
        sys.argv = old


def test_decide_stamp_skip_cycle():
    d = Path(tempfile.mkdtemp())
    feed, md = d / "data.json", d / "latest.md"
    feed.write_text(json.dumps(_feed([_ev("Antal", 1)])))
    md.write_text("# Digest\n\nbody\n")

    assert _run(feed, md, "decide").startswith("REGENERATE")   # no prior signature
    assert _run(feed, md, "stamp").startswith("STAMPED")
    assert _run(feed, md, "decide").startswith("SKIP")          # unchanged -> skip
    assert "no new picks since" in md.read_text()

    feed.write_text(json.dumps(_feed([_ev("Antal", 1), _ev("New", 2)])))   # picks changed
    assert _run(feed, md, "decide").startswith("REGENERATE")


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
