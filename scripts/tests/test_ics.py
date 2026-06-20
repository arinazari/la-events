#!/usr/bin/env python3
"""Tests for the calendar export — scripts/lib/ics.py + scripts/make_ics.py.

Run: python scripts/tests/test_ics.py
Covers VEVENT structure, TEXT escaping, 75-octet folding, datetime formatting, and the
CLI's contiguous end-time inference + bare-time/date combination.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib.ics import build_ics, _dt, _esc  # noqa: E402
import make_ics as M  # noqa: E402


def test_build_structure():
    ics = build_ics([
        {"summary": "Dinner — Santo", "start": "2026-06-20T19:30", "end": "2026-06-20T21:00",
         "location": "Santo, Silver Lake", "url": "https://resy.com/x"},
        {"summary": "Bradley Zero", "start": "2026-06-20T22:00", "end": "2026-06-21T00:00"},
    ], calname="Sat 6/20")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.rstrip().endswith("END:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == 2 and ics.count("END:VEVENT") == 2
    assert "DTSTART:20260620T193000" in ics and "DTEND:20260620T210000" in ics
    assert "SUMMARY:Dinner — Santo" in ics and "URL:https://resy.com/x" in ics
    assert "\r\n" in ics and "X-WR-CALNAME:Sat 6/20" in ics
    # every VEVENT has a DTSTAMP (UTC) and a UID
    assert ics.count("DTSTAMP:") == 2 and ics.count("UID:") == 2


def test_escaping_and_skip_bad_start():
    ics = build_ics([
        {"summary": "Drinks, then; fun", "start": "2026-06-20T18:00"},
        {"summary": "no start -> skipped", "start": "garbage"},
    ])
    assert "SUMMARY:Drinks\\, then\\; fun" in ics
    assert ics.count("BEGIN:VEVENT") == 1   # the bad-start event is dropped
    assert _esc("a\nb") == "a\\nb"


def test_dt_parsing():
    assert _dt("2026-06-20T19:30") == "20260620T193000"
    assert _dt("2026-06-20 19:30:45") == "20260620T193045"   # space + seconds
    assert _dt("2026-06-20T03:00Z") == "20260620T030000"     # trailing Z dropped (floating)
    assert _dt("nope") == "" and _dt(None) == ""


def test_line_folding_under_75_octets():
    long_desc = "x" * 300
    ics = build_ics([{"summary": "S", "start": "2026-06-20T18:00", "description": long_desc}])
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, repr(line)
    # a folded continuation line begins with a single space
    assert any(line.startswith(" ") for line in ics.split("\r\n"))


def test_infer_ends_contiguous_and_last():
    stops = [{"summary": "Dinner", "start": "2026-06-20T19:30"},
             {"summary": "Show", "start": "2026-06-20T22:00"}]
    out = M.infer_ends(stops, last_minutes=120)
    assert out[0]["end"] == "2026-06-20T22:00"        # dinner runs until the show
    assert out[1]["end"] == "2026-06-21T00:00"        # last + 120 min, rolls past midnight


def test_norm_start_combines_date():
    assert M._norm_start("19:30", "2026-06-20") == "2026-06-20T19:30"
    assert M._norm_start("2026-06-20T19:30", "") == "2026-06-20T19:30"   # full passes through


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
