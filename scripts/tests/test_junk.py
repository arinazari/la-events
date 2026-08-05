#!/usr/bin/env python3
"""Tests for the junk/scam-listing gate in scripts/lib/pipeline.py.

Run: python scripts/tests/test_junk.py   (also pytest-compatible)
Titles come from the real July 2026 spam waves (airline hotlines 2026-07-14,
RA-sourced insurance wave 2026-07-22..24) and the legit lookalikes that must
survive (venue "The Airliner", band "Delta By The Beach", "EARLY BIRDZ - Flight 012").
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ on path
from lib import pipeline as P  # noqa: E402

TODAY = date(2026, 7, 24)


def _ev(title, venue="Somewhere", date_s="2026-08-01", **extra):
    return {"title": title, "venue": venue, "date": date_s, "lineup": [],
            "links": [], "sources": ["ra"], **extra}


# ── is_junk_event: the historical spam shapes must each trip a rule ──────────────

def test_junk_insurance_customer_service_title():
    # RA-sourced insurance wave, 2026-07-22..24 (real title).
    r = P.is_junk_event(_ev("State Farm Insurance Customer Service Number — Direct Billing Access 2026"))
    assert r is not None, "State Farm customer-service spam must be junk"


def test_junk_insurance_brand_plus_action_title():
    # Same wave, no explicit "customer service" phrase — brand + policy/cancel action.
    r = P.is_junk_event(_ev("Allstate Insurance Cancel Policy Prevention — Save Your Coverage in 2026"))
    assert r is not None, "Allstate policy-cancel spam must be junk"


def test_junk_airline_hotline_title():
    # Airline-hotline wave shape, 2026-07-14 (~100 judged skip by event-editor).
    r = P.is_junk_event(_ev("Lufthansa Airlines Cancellation Policy — Refund Support Number +1-855-738-4113"))
    assert r is not None, "airline refund-hotline spam must be junk"


def test_junk_bare_phone_in_title():
    # A formatted phone in the title is disqualifying on its own — no brand needed.
    assert P.is_junk_event(_ev("Best Flight Deals 855-738-4113")) is not None
    assert P.is_junk_event(_ev("Call (800) 555-0147 for VIP tables")) is not None


def test_junk_airline_brand_without_phone():
    # Brand + service-action words, no phone at all — still spam.
    assert P.is_junk_event(_ev("JetBlue Airways Booking and Name Change Help")) is not None


# ── is_junk_event: legit lookalikes must ALL pass clean ──────────────────────────

def test_legit_venue_the_airliner():
    # Lincoln Heights venue — "Airliner" must not match the airline brand rule.
    assert P.is_junk_event(_ev("Sunset Sessions at The Airliner", venue="The Airliner")) is None


def test_legit_band_delta_by_the_beach():
    assert P.is_junk_event(_ev("Delta By The Beach")) is None


def test_legit_tour_title():
    assert P.is_junk_event(_ev("JOURNEY Final Frontier Tour", venue="Kia Forum")) is None


def test_legit_flight_number_style_title():
    # "Flight 012" carries digits + a travel word but no brand and no 3-3-4 phone.
    assert P.is_junk_event(_ev("EARLY BIRDZ - Flight 012")) is None


def test_legit_hotline_as_party_name():
    # "Hotline" as a party brand (Drake night) is fine — the keyword list stays narrow.
    assert P.is_junk_event(_ev("Hotline Bling Night", venue="The Short Stop")) is None


def test_legit_phones_in_detail_are_ignored():
    # Title-only policy: a box-office line in `detail` must never drop a real event.
    ev = _ev("Sam First Late Set", venue="Sam First",
             detail="Reservations: call the box office at (310) 555-0170.")
    assert P.is_junk_event(ev) is None


# ── drop_junk + merge_new integration ────────────────────────────────────────────

def test_drop_junk_splits_kept_and_dropped():
    records = [_ev("Delta By The Beach"),
               _ev("Allstate Insurance Cancel Policy Prevention — Save Your Coverage in 2026"),
               _ev("Hotline Bling Night")]
    kept, dropped = P.drop_junk(records)
    assert [e["title"] for e in dropped] == ["Allstate Insurance Cancel Policy Prevention — Save Your Coverage in 2026"]
    assert len(kept) == 2


def test_merge_new_drops_incoming_junk_and_sweeps_catalog():
    # Junk already committed to the catalog self-heals; junk in incoming never lands;
    # legit rows on both sides survive and stats carry the junk count.
    catalog = [_ev("Warehouse w/ Antal", venue="The Bridge"),
               _ev("United Airlines Cancellation Refund Number +1-855-738-4113",  # old wave, committed
                   first_seen="2026-07-14", last_seen="2026-07-14")]
    incoming = [_ev("State Farm Insurance Customer Service Number — Direct Billing Access 2026"),
                _ev("Totally Real Show", venue="Zebulon")]
    merged, stats = P.merge_new(catalog, incoming, TODAY)
    titles = {e["title"] for e in merged}
    assert titles == {"Warehouse w/ Antal", "Totally Real Show"}
    assert stats["junk"] == 2
    assert 1 <= len(stats["junk_titles"]) <= 5
    assert any("State Farm" in t for t in stats["junk_titles"])
    assert stats["incoming"] == 2


def test_merge_new_junk_stat_zero_on_clean_merge():
    # No junk anywhere -> junk count 0, no junk_titles key, existing stats intact.
    merged, stats = P.merge_new([_ev("Warehouse w/ Antal", venue="The Bridge")],
                                [_ev("Totally Real Show", venue="Zebulon")], TODAY)
    assert len(merged) == 2
    assert stats["junk"] == 0 and "junk_titles" not in stats
    assert stats["incoming"] == 1 and stats["added"] == 1


def test_merge_new_junk_titles_sample_is_bounded():
    incoming = [_ev(f"Allstate Insurance Cancel Policy Prevention {i} — Billing Support Number")
                for i in range(8)]
    _merged, stats = P.merge_new([], incoming, TODAY)
    assert stats["junk"] == 8
    assert len(stats["junk_titles"]) == 5


# ── 2026-08 shadow-eval additions: upsell/offer add-ons + venue placeholders ─────

def test_junk_ticketless_upgrade_row():
    # Real TM sibling row of the slayr show (2026-08 catalog).
    r = P.is_junk_event(_ev("slayr - VIP Ticketless Upgrade", venue="The Belasco"))
    assert r is not None, "TM ticketless-upgrade add-on must be junk"


def test_junk_carrier_offer_prefix_row():
    # Real carrier-presale row that a stale must-see verdict put at a profile's #1.
    r = P.is_junk_event(_ev("Verizon offer - Daisy Chain Fields", venue="Great Park Live"))
    assert r is not None, "carrier presale-offer listing must be junk"


def test_junk_venue_placeholder_row():
    # Real ra+tm merged placeholder: the "event" is just the room's name, nothing billed.
    r = P.is_junk_event(_ev("Hollywood Palladium", venue="Hollywood Palladium"))
    assert r is not None, "title==venue with no lineup must be junk"


def test_junk_self_titled_bill_with_lineup_survives():
    # A self-titled residency night IS real when someone is billed.
    r = P.is_junk_event(_ev("Hollywood Palladium", venue="Hollywood Palladium",
                            lineup=["Perfume Genius"]))
    assert r is None, "placeholder rule must not fire when a lineup is billed"


def test_junk_upsell_lookalikes_survive():
    # Band named Upgrade / a parking-lot party / an "offer" mid-title are all real events.
    for t in ("Upgrade — album release show", "Parking Lot Party w/ Dublab DJs",
              "What the Water Gave Me — final offer night"):
        assert P.is_junk_event(_ev(t)) is None, t


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
