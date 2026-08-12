#!/usr/bin/env python3
"""Tests for scripts/fetch_roadhouse.py — the Roadhouse's hand-edited HTML calendar.

Run: python scripts/tests/test_fetch_roadhouse.py   (also pytest-compatible)
Fixtures are verbatim row shapes from the live page (2026-08-12). The parser scans <td>
cells in document order (the site's <tr>s are occasionally unclosed), keys events off the
"<i>Weekday, Month Nth - TIME</i>" heading, takes the year from the flyer image path
(images/2026/08aug/…), and must skip RESCHEDULED overlays and store-hours placeholders.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from fetch_roadhouse import parse_calendar, to_hhmm  # noqa: E402

LO, HI = date(2026, 8, 12), date(2027, 1, 12)


def row(img, main, right):
    return (f'<tr><td width="25%"><center><font color="white"><b>{img}</b></font></center></td>'
            f'<td width="50%"><font color="white" face="helvetica" size="3"><b>{main}</b></font></td>'
            f'<td width="25%"><center><font color="white"><b>{right}</b></font></center></td></tr>')


# Verbatim shapes from the live page.
TICKETED = row(
    '<img height="150" src="images/2026/08aug/sparta.png" width="150">',
    '<i>Tuesday, August 11th - 7PM</i><BR><BR>\nSparta<BR>If It Kills You<BR>J.R. Slayer',
    '$20<BR><BR>\n<a href="https://app.opendate.io/e/sparta-august-11-2026-717686" '
    'style="color:red" target="_NEW"><i>Buy tickets!</i></a>')

RESCHEDULED = row(
    '<img height="150" src="images/2026/08aug/fred3.PNG" width="150">',
    '<font face="helvetica" color="RED" size="5"><B>RESCHEDULED FOR 8/10</B></font><BR><BR>'
    '<font color="white"><b><i>Wednesday, August 12th - 6PM</i><BR><BR>\n'
    "Fred Armisen's Playlist, Live!</b></font>",
    '')

STORE_OPEN = row(
    '<img height="150" src="images/recordstoreopen.JPG" width="150">',
    '<i>Wednesday, August 12th  </i><BR><BR>\nRecord Store open 12-6pm;<BR>\n  bar &amp; venue closed.',
    '')

RANGE_TIME = row(
    '<img height="150" src="images/2026/08aug/triva2026.jpg" width="150">',
    '<i>Wednesday, August 19th - 6-7:30PM</i><BR><BR>\nVinyl Happy Hour',
    '')

TIERED = row(
    '<img height="150" src="images/2026/08aug/drunkkrcw.jpg" width="150">',
    '<i>Thursday, August 13th - 9PM</i><BR><BR>\nDrunk Horse<BR>Lost Goat<BR>Fingernail',
    '$12 ADVANCE<BR>$15 DOS<BR><BR><a href="https://link.dice.fm/abc123"><i>Buy tickets!</i></a>')

GUEST_NOTE = row(
    '<img height="150" src="images/2026/12dec/xmas.png" width="150">',
    '<i>Saturday, December 5th - 6PM</i><BR><BR>\nThee Holiday Show<BR><i>w/ Special Guest Opener</i>',
    '$15<BR><BR><a href="https://app.opendate.io/e/holiday-717999"><i>Buy tickets!</i></a>')

# Verbatim from the live page: acts separated by a bare newline AND a <BR>.
NEWLINE_SEP = row(
    '<img height="150" src="images/2026/08aug/chico.png" width="150">',
    '<i>Friday, August 14th - 6PM</i><BR><BR>\t\t\t    \nChico Detour\nThe Reflectors <BR>Agua',
    '<a href="https://link.dice.fm/o3c250393c82" style="color:red"><i>Buy tickets!</i></a>')

# Weekday hand-typo on the live page (Aug 24, 2026 is a Monday) — month+day must win.
WRONG_WEEKDAY = row(
    '<img height="150" src="images/2026/08aug/happys.png" width="150">',
    "<i>Thursday, August 24th - 6PM</i><BR><BR>\nHappy's Birthday<BR>Chromatic Cowboy",
    '$10 ADVANCE<BR>$12 DOS')


def test_ticketed_row_full_parse():
    (ev,) = parse_calendar(TICKETED, date(2026, 8, 1), HI)
    assert ev["title"] == "Sparta"
    assert ev["lineup"] == ["Sparta", "If It Kills You", "J.R. Slayer"]
    assert ev["date"] == "2026-08-11"
    assert ev["start"] == "19:00"
    assert ev["price"] == "$20"
    assert ev["url"] == "https://app.opendate.io/e/sparta-august-11-2026-717686"
    assert ev["venue"] == "Permanent Records Roadhouse"
    assert ev["neighborhood"] == "Cypress Park"


def test_rescheduled_row_skipped():
    assert parse_calendar(RESCHEDULED, LO, HI) == []


def test_store_hours_row_skipped():
    assert parse_calendar(STORE_OPEN, LO, HI) == []


def test_range_time_takes_start_with_inherited_meridiem():
    (ev,) = parse_calendar(RANGE_TIME, LO, HI)
    assert ev["title"] == "Vinyl Happy Hour"
    assert ev["start"] == "18:00"
    assert ev["price"] is None


def test_tiered_price_kept_as_text():
    (ev,) = parse_calendar(TIERED, LO, HI)
    assert ev["price"] == "$12 ADVANCE $15 DOS"
    assert ev["links"] == [{"source": "roadhouse", "url": "https://link.dice.fm/abc123"}]


def test_guest_note_goes_to_detail_not_lineup():
    (ev,) = parse_calendar(GUEST_NOTE, LO, HI)
    assert ev["lineup"] == ["Thee Holiday Show"]
    assert ev["detail"] == "w/ Special Guest Opener"
    assert ev["date"] == "2026-12-05"  # year from the image path


def test_newline_separated_acts_split_like_br():
    (ev,) = parse_calendar(NEWLINE_SEP, LO, HI)
    assert ev["title"] == "Chico Detour"
    assert ev["lineup"] == ["Chico Detour", "The Reflectors", "Agua"]
    assert ev["price"] is None  # free show — link only


def test_wrong_weekday_ignored_month_day_wins():
    (ev,) = parse_calendar(WRONG_WEEKDAY, LO, HI)
    assert ev["date"] == "2026-08-24"


def test_out_of_window_rows_skipped():
    assert parse_calendar(TICKETED, date(2026, 8, 12), HI) == []  # 8/11 is past


def test_year_rollover_without_image_hint():
    jan = row('<img src="images/nyeparty.jpg">',
              '<i>Saturday, January 10th - 9PM</i><BR><BR>\nNYE Hangover Band', '$10')
    (ev,) = parse_calendar(jan, date(2026, 12, 20), date(2027, 6, 1))
    assert ev["date"] == "2027-01-10"


def test_consecutive_rows_price_not_stolen_from_next_row():
    # An event row with NO third td (hand-edited rows drop it), followed by another
    # event: the next cell in document order is the next row's image — must not be
    # read as a price cell.
    two_td_row = ('<tr><td><img src="images/2026/08aug/sparta.png"></td>'
                  '<td><i>Tuesday, August 11th - 7PM</i><BR><BR>Sparta</td></tr>')
    events = parse_calendar(two_td_row + RANGE_TIME, date(2026, 8, 1), HI)
    assert [e["title"] for e in events] == ["Sparta", "Vinyl Happy Hour"]
    sparta = events[0]
    assert sparta["price"] is None and sparta["url"].startswith("http://roadhouse")


def test_to_hhmm_forms():
    assert to_hhmm("7PM") == "19:00"
    assert to_hhmm("7:30PM") == "19:30"
    assert to_hhmm("6-7:30PM") == "18:00"
    assert to_hhmm("12-6pm") == "12:00"
    assert to_hhmm("") is None
    assert to_hhmm(None) is None
    assert to_hhmm("TBA") is None


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
