#!/usr/bin/env python3
"""Find events that work for a GROUP — score the catalog against several people's profiles at once
and lay out a per-event, per-person score matrix for the concierge to reason over.

This is a DATA PROVIDER, not a ranker. Per Ari's call there are NO hard group rules: it surfaces
each person's score / ★rating / reasons for every shared upcoming event, plus a few convenience
aggregates (mean, floor/min, how many are into it, who'd veto), and leaves the *judgment* — who
matters most tonight, how to weigh a lukewarm friend, when a veto kills a pick — to the concierge.
"Find something me + Lori + Dr. Ganesan would all be into."

People are profiles.yaml usernames OR display names (case-insensitive — "Lori" resolves the same as
"lori", "Dr. Ganesan" the same as "vish"), so the concierge can pass whatever name Ari said
without a username-lookup step. "me" / "default" / the owner's username resolves to the ROOT
taste.yaml + profile.yaml (the canonical feed). Each person is scored against THEIR OWN taste,
profile mechanics, and music layer — exactly like build_profiles.py, reusing the same scorer, so a
group pick can't drift from that person's solo feed.

Profiles aren't private: if you can name someone who has a profile, you can plan with them (Ari's
call — knowing the username is permission enough). Someone with no profile? Plan without them, or
spin one up first.

Usage:
  python scripts/group_picks.py --people me lori vish --days 21
  python scripts/group_picks.py --people me,lori --from 2026-07-01 --to 2026-07-07 --json /tmp/g.json
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_yaml, load_taste, load_profile  # noqa: E402
from lib.pipeline import score_pool, today_la  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.enrich import event_key, load_cache, merge_enrichment  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SALT = "la-events/v1:"
OWNER_ALIASES = {"me", "default", "owner", "root", "self", "us"}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def profile_hash(username: str, salt: str) -> str:
    """Mirror of build_profiles.py / the dashboard hashing — keep all in sync if it changes."""
    return hashlib.sha256((salt + username.strip().lower()).encode("utf-8")).hexdigest()[:16]


def norm_name(s: str) -> str:
    """Normalize a display name for lookup: lowercase, drop . and , , collapse whitespace.
    So 'Dr. Ganesan', 'dr ganesan', and 'Dr Ganesan' all key the same; 'Lori' -> 'lori'."""
    return " ".join(re.sub(r"[.,]", " ", (s or "").lower()).split())


def resolve_member(person: str, by_user: dict, owner_entry: dict, salt: str, by_name: dict = None):
    """Resolve a requested person to {id, name, taste, profile, hash}, mirroring build_profiles.py:
    the owner (and the aliases) → root taste.yaml/profile.yaml, no per-hash music layer; a friend →
    their own profiles/<username>/taste.yaml + profile.yaml (+ their music layer via hash).

    A person matches by USERNAME or (via by_name) by DISPLAY NAME, case-insensitively — so the
    concierge can pass whatever name Ari used and skip a username-lookup step. Username wins on a
    tie. None = no such profile."""
    u = person.strip().lower()
    owner_user = (owner_entry or {}).get("username", "").strip().lower()
    if owner_entry and (u == owner_user or u in OWNER_ALIASES):
        return {"id": owner_user or "default", "name": owner_entry.get("name") or "You",
                "taste": owner_entry.get("taste") or "taste.yaml",
                "profile": owner_entry.get("profile") or "profile.yaml", "hash": None}
    if u in OWNER_ALIASES:                       # asked for "me"/default but no owner entry exists
        return {"id": "default", "name": "Default", "taste": "taste.yaml",
                "profile": "profile.yaml", "hash": None}
    entry = by_user.get(u) or (by_name or {}).get(norm_name(person))
    if not entry:
        return None
    canon = (entry.get("username") or u).strip().lower()   # the profile's real username, not the typed name
    if entry.get("owner"):
        return {"id": canon, "name": entry.get("name") or canon,
                "taste": entry.get("taste") or "taste.yaml",
                "profile": entry.get("profile") or "profile.yaml", "hash": None}
    return {"id": canon, "name": entry.get("name") or canon,
            "taste": entry.get("taste") or f"profiles/{canon}/taste.yaml",
            "profile": entry.get("profile") or f"profiles/{canon}/profile.yaml",
            "hash": profile_hash(canon, salt)}


def combine(pools: dict, members: list) -> list:
    """Join each member's scored pool by event_key into one matrix. pools: id -> [scored events].
    members: ordered [{id, name, ...}]. Returns one row per event present for ANYONE, carrying each
    member's score/rating/reasons + aggregates (mean/min/max/n_into/n_veto). Presentation-sorted by
    mean then date — but the full matrix is exposed so the concierge ranks with its own judgment."""
    ids = [m["id"] for m in members]
    by_member = {m["id"]: {event_key(e): e for e in pools.get(m["id"], [])} for m in members}
    rep, order, seen = {}, [], set()
    for mid in ids:                              # stable union of keys, first-seen order
        for k, e in by_member[mid].items():
            if k not in seen:
                seen.add(k); order.append(k); rep[k] = e
    rows = []
    for k in order:
        people, scores = {}, []
        for mid in ids:
            e = by_member[mid].get(k)
            if e is None:
                people[mid] = None
                continue
            sc = e.get("score") or 0
            people[mid] = {"score": sc, "rating": e.get("rating") or 0,
                           "reasons": (e.get("reasons") or [])[:3], "veto": sc < 0}
            scores.append(sc)
        if not scores:
            continue
        links = rep[k].get("links") or ([{"url": rep[k]["url"]}] if rep[k].get("url") else [])
        rows.append({
            "key": k, "title": rep[k].get("title"),
            "iso_date": rep[k].get("iso_date") or (str(rep[k].get("date") or "")[:10] or None),
            "venue": rep[k].get("venue"), "neighborhood": rep[k].get("neighborhood"),
            "price": rep[k].get("price"), "links": links, "people": people,
            "mean": round(sum(scores) / len(scores), 2), "min": min(scores), "max": max(scores),
            "n_into": sum(1 for s in scores if s > 0),
            "n_veto": sum(1 for mid in ids if people[mid] and people[mid]["veto"]),
        })
    rows.sort(key=lambda r: (-r["mean"], r["iso_date"] or "9999"))
    return rows


def _day(iso: str) -> str:
    if not iso or len(iso) < 10:
        return iso or "TBA"
    y, m, d = (int(x) for x in iso[:10].split("-"))
    from datetime import date
    return f"{DOW[date(y, m, d).weekday()]} {m}/{d}"


def _note(ev: dict) -> str:
    e = ev.get("enrichment") or {}
    if e.get("curator_note"):
        return e["curator_note"]
    notes = e.get("artist_notes") or []
    if notes and notes[0].get("note"):
        return f"{notes[0].get('name')} — {notes[0]['note']}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-person score matrix for group event planning.")
    ap.add_argument("--people", nargs="+", required=True,
                    help="profiles.yaml usernames (space- or comma-separated); 'me'/'default' = the owner")
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--enrichment", default="data/enrichment.json")
    ap.add_argument("--manifest", default="profiles.yaml")
    ap.add_argument("--days", type=int, default=21, help="window length when --to is not given")
    ap.add_argument("--from", dest="from_", default=None, help="ISO lower bound (inclusive)")
    ap.add_argument("--to", dest="to", default=None, help="ISO upper bound (inclusive)")
    ap.add_argument("--top", type=int, default=40, help="rows to show/emit (0 = all)")
    ap.add_argument("--json", dest="json_out", default=None, help="also write the full matrix here")
    args = ap.parse_args()

    def resolve(p):
        return REPO / p if not Path(p).is_absolute() else Path(p)

    catalog = json.loads(resolve(args.catalog).read_text())
    manifest = load_yaml(args.manifest) or {}
    salt = manifest.get("salt") or DEFAULT_SALT
    profiles = [p for p in (manifest.get("profiles") or []) if isinstance(p, dict) and p.get("username")]
    by_user = {p["username"].strip().lower(): p for p in profiles}
    by_name = {}                                 # display name -> entry, so "Lori" resolves like "lori"
    for p in profiles:
        n = norm_name(p.get("name") or "")
        if n and n not in by_name and n not in by_user:   # username wins on a tie; first name wins
            by_name[n] = p
    owner_entry = next((p for p in profiles if p.get("owner")), None)

    # Flatten comma-separated people, resolve + dedupe (preserve order).
    requested, members, unknown, seen_ids = [], [], [], set()
    for chunk in args.people:
        requested.extend(x for x in chunk.replace(",", " ").split() if x)
    for person in requested:
        m = resolve_member(person, by_user, owner_entry, salt, by_name)
        if m is None:
            unknown.append(person)
        elif m["id"] not in seen_ids:
            seen_ids.add(m["id"]); members.append(m)
    if unknown:
        known = ", ".join(sorted(by_user)) or "(none)"
        print(f"Unknown profile(s): {', '.join(unknown)}. Known usernames: {known}. "
              f"Use 'me' for the owner. Plan without them, or add a profile first.", file=sys.stderr)
    if len(members) < 1:
        print("No resolvable people — nothing to do.", file=sys.stderr)
        return 1

    today = today_la()
    if args.to:
        window_days = max(0, (__import__("datetime").date.fromisoformat(args.to[:10]) - today).days)
    else:
        window_days = args.days
    lo = args.from_ or today.isoformat()

    pools = {}
    for m in members:
        taste = load_taste(m["taste"])
        profile = load_profile(m["profile"])
        affinity = merged_affinity(REPO, profile, profile_hash=m["hash"])
        pool = score_pool(catalog, taste, profile, today, window_days=window_days, affinity=affinity)
        if args.from_:                            # score_pool starts at today; trim the front edge
            pool = [e for e in pool if (e.get("iso_date") or "") >= lo]
        pools[m["id"]] = pool

    rows = combine(pools, members)
    # Best-effort: fold cached enrichment onto the shown rows so the concierge gets a ready gloss.
    shown = rows if args.top == 0 else rows[:args.top]
    try:
        cache = load_cache(resolve(args.enrichment))
        enr = {e["key"]: e for e in merge_enrichment([r for r in shown], cache) if e.get("key")}
        for r in shown:
            r["note"] = _note(enr.get(r["key"], {}))
    except (OSError, json.JSONDecodeError, KeyError):
        for r in shown:
            r.setdefault("note", "")

    name_of = {m["id"]: m["name"] for m in members}
    span = f"{lo} → {args.to or (today + timedelta(days=window_days)).isoformat()}"
    who = " + ".join(name_of[m["id"]] for m in members)
    print(f"Group picks for {who} — {span}")
    print(f"{len(members)} people · {len(rows)} shared upcoming events · showing top {len(shown)} by average fit")
    if any(r["n_veto"] for r in shown):
        print("⛔ = a hard down-rank for that person (banned/penalized) — your call whether it kills the pick")
    print()
    for r in shown:
        loc = " ".join(x for x in (f"@ {r['venue']}" if r.get("venue") else "",
                                   f"({r['neighborhood']})" if r.get("neighborhood") else "") if x)
        per = " · ".join(
            f"{name_of[mid]} {p['score']:+g} ★{p['rating']}{'⛔' if p['veto'] else ''}" if p else f"{name_of[mid]} —"
            for mid, p in r["people"].items())
        print(f"  {_day(r['iso_date'])}  {r['title']} {loc}".rstrip())
        print(f"     avg {r['mean']:+g} · floor {r['min']:+g} · {r['n_into']}/{len(members)} into it  —  {per}")
        if r.get("note"):
            print(f"     {r['note']}")
        url = (r["links"][0].get("url") if r["links"] and isinstance(r["links"][0], dict) else None)
        if url:
            print(f"     {url}")
    print()

    if args.json_out:
        out = {"generated_for": [{"id": m["id"], "name": m["name"]} for m in members],
               "window": {"from": lo, "to": args.to or (today + timedelta(days=window_days)).isoformat()},
               "count": len(rows), "events": shown}
        Path(args.json_out).write_text(json.dumps(out, indent=2))
        print(f"wrote {len(shown)} rows -> {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
