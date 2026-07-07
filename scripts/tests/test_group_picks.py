#!/usr/bin/env python3
"""Tests for scripts/group_picks.py — the per-person matrix join + profile resolution.

Run: python scripts/tests/test_group_picks.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import group_picks as G  # noqa: E402


def _ev(title, score, rating, iso="2026-07-04", venue=None, reasons=None):
    v = venue or (title + " hall")
    return {"title": title, "date": iso, "venue": v, "iso_date": iso,
            "score": score, "rating": rating, "reasons": reasons or []}


MEMBERS = [{"id": "a", "name": "Ana"}, {"id": "b", "name": "Bo"}]


def test_combine_builds_matrix_and_aggregates():
    x_a, x_b = _ev("X night", 10, 5), _ev("X night", 4, 3)        # same event for both
    y_a, y_b = _ev("Y night", 2, 2), _ev("Y night", -3, 0)        # Bo vetoes Y
    pools = {"a": [x_a, y_a], "b": [x_b, y_b]}
    rows = G.combine(pools, MEMBERS)
    assert len(rows) == 2
    x = next(r for r in rows if r["title"] == "X night")
    assert x["people"]["a"]["score"] == 10 and x["people"]["b"]["score"] == 4
    assert x["mean"] == 7.0 and x["min"] == 4 and x["max"] == 10
    assert x["n_into"] == 2 and x["n_veto"] == 0
    y = next(r for r in rows if r["title"] == "Y night")
    assert y["people"]["b"]["veto"] is True and y["n_veto"] == 1
    assert y["n_into"] == 1 and y["mean"] == -0.5


def test_combine_handles_event_present_for_only_one():
    pools = {"a": [_ev("Solo", 6, 4)], "b": []}
    rows = G.combine(pools, MEMBERS)
    assert len(rows) == 1
    r = rows[0]
    assert r["people"]["b"] is None and r["people"]["a"]["score"] == 6
    assert r["mean"] == 6 and r["n_into"] == 1


def test_combine_sorted_by_mean_desc():
    pools = {
        "a": [_ev("Low", 0, 1), _ev("High", 10, 5), _ev("Mid", 6, 4)],
        "b": [_ev("Low", 0, 1), _ev("High", 8, 5), _ev("Mid", 4, 3)],
    }
    titles = [r["title"] for r in G.combine(pools, MEMBERS)]
    assert titles == ["High", "Mid", "Low"]


def test_resolve_member_owner_alias_and_friend():
    by_user = {
        "ari": {"username": "ari", "name": "Ari", "owner": True, "taste": "taste.yaml"},
        "lori": {"username": "lori", "name": "Lori", "taste": "profiles/lori/taste.yaml",
                 "profile": "profiles/lori/profile.yaml"},
    }
    owner = by_user["ari"]
    salt = "la-events/v1:"

    me = G.resolve_member("me", by_user, owner, salt)
    assert me["id"] == "ari" and me["taste"] == "taste.yaml" and me["profile"] == "profile.yaml"
    assert me["hash"] is None
    # owner addressed by username resolves the same way
    assert G.resolve_member("ari", by_user, owner, salt)["profile"] == "profile.yaml"

    lori = G.resolve_member("lori", by_user, owner, salt)
    assert lori["taste"] == "profiles/lori/taste.yaml"
    assert lori["profile"] == "profiles/lori/profile.yaml"
    assert lori["hash"] == G.profile_hash("lori", salt)

    assert G.resolve_member("nobody", by_user, owner, salt) is None


def test_friend_without_explicit_paths_falls_back_to_convention():
    by_user = {"dr_ganesan": {"username": "dr_ganesan", "name": "Dr. Ganesan"}}
    m = G.resolve_member("dr_ganesan", by_user, None, "la-events/v1:")
    assert m["taste"] == "profiles/dr_ganesan/taste.yaml"
    assert m["profile"] == "profiles/dr_ganesan/profile.yaml"
    assert m["hash"] == G.profile_hash("dr_ganesan", "la-events/v1:")


def test_resolve_by_display_name_not_just_username():
    # The whole point of the fix: passing a friend's display NAME resolves to their profile
    # (no username-lookup step), and lands on the SAME id/paths/hash as passing the username.
    lori = {"username": "lori", "name": "Lori", "taste": "profiles/lori/taste.yaml"}
    by_user = {"lori": lori}
    by_name = {G.norm_name("Lori"): lori}
    m = G.resolve_member("Lori", by_user, None, "la-events/v1:", by_name)
    assert m is not None, "display name should resolve"
    assert m["id"] == "lori"                                   # canonical username, not the typed name
    assert m["taste"] == "profiles/lori/taste.yaml"
    assert m["hash"] == G.profile_hash("lori", "la-events/v1:")
    # identical to resolving by username
    assert m == G.resolve_member("lori", by_user, None, "la-events/v1:", by_name)


def test_resolve_by_name_normalizes_punctuation_and_case():
    dg = {"username": "dr_ganesan", "name": "Dr. Ganesan", "taste": "profiles/dr_ganesan/taste.yaml"}
    by_user = {"dr_ganesan": dg}
    by_name = {G.norm_name("Dr. Ganesan"): dg}
    for typed in ("Dr. Ganesan", "dr ganesan", "DR  GANESAN"):
        m = G.resolve_member(typed, by_user, None, "la-events/v1:", by_name)
        assert m is not None and m["id"] == "dr_ganesan", f"{typed!r} should resolve"


def test_username_wins_over_a_colliding_name():
    # If one profile's name equals another's username, the username match takes precedence.
    lori = {"username": "lori", "name": "Lori"}
    other = {"username": "somebody", "name": "lori"}       # display name collides with lori's username
    by_user = {"lori": lori, "somebody": other}
    by_name = {G.norm_name("Somebody"): other}             # "lori" name NOT added (it's a username)
    m = G.resolve_member("lori", by_user, None, "la-events/v1:", by_name)
    assert m["id"] == "lori"


def test_unknown_name_still_returns_none():
    by_user = {"lori": {"username": "lori", "name": "Lori"}}
    by_name = {G.norm_name("Lori"): by_user["lori"]}
    assert G.resolve_member("Nobody", by_user, None, "la-events/v1:", by_name) is None


def test_profile_hash_stable_16_hex():
    h = G.profile_hash("Lori", "la-events/v1:")
    assert h == G.profile_hash("lori", "la-events/v1:")          # case-insensitive
    assert len(h) == 16 and all(c in "0123456789abcdef" for c in h)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all group_picks tests passed")
