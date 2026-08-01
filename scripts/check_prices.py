#!/usr/bin/env python3
"""Find the cheapest tickets for catalog events — the card's price-comparison data.

Resale floors routinely undercut face price (Kim Gordon: $19 all-in on Gametime vs ~$45
on Ticketmaster) and no source in the pipeline carries prices for most TM inventory, so
this is its own small pass. It fills data/ticket_prices.json (committed; keyed by
event_key), which build_dashboard folds onto feed rows as `price_check` — the dashboard
card then renders the comparison with the cheapest flagged and the check date shown.

What it can check by itself: Gametime (open API, all-in floors — the automated workhorse)
and SeatGeek (official API, only when SEATGEEK_CLIENT_ID is set), plus the catalog's own
listed price as the primary anchor. StubHub / Vivid Seats / TickPick are bot-walled from
datacenters — check those in a browser/session (--links prints prefilled searches) and
save finds with --record.

Usage:
    python scripts/check_prices.py --auto [--top 60] [--days 21]   # nightly: featured head + starred
    python scripts/check_prices.py --query "kim gordon"            # one act, fuzzy over the catalog
    python scripts/check_prices.py --key <event_key> [--key ...]
    python scripts/check_prices.py --links --query "kim gordon"    # print marketplace search URLs only
    python scripts/check_prices.py --record --key K --source stubhub --price 20 \
        [--url https://...] [--note "sec 102"] [--kind resale]

Degrades gracefully: a dead marketplace or network failure warns and moves on — this pass
never blocks a digest run. Politeness: one Gametime query per unique act (covers all their
LA dates), ~2 req/s max.
"""

import argparse
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import editor as ED  # noqa: E402
from lib import prices as PR  # noqa: E402
from lib.config import load_yaml  # noqa: E402
from lib.dedupe import normalize  # noqa: E402
from lib.enrich import event_key  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.pipeline import today_la  # noqa: E402
from lib.reactions import load_reactions, star_map  # noqa: E402
from lib.scoring import score_event  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _day_md(iso: str) -> str:
    """Ari's standing date convention: `Day M/D`, no leading zeros."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def _fmt_price(o: dict) -> str:
    p = o.get("price")
    core = "free" if p == 0 and o.get("kind") == "listed" else (f"${p:,.2f}".rstrip("0").rstrip(".") if p is not None else "?")
    return core


def select_events(catalog: list, args, today_iso: str) -> list:
    if args.key:
        want = set(args.key)
        return [ev for ev in catalog if event_key(ev) in want]
    if args.query:
        q = normalize(args.query)
        qtok = set(q.split())
        out = []
        for ev in catalog:
            if str(ev.get("date") or "") < today_iso or ev.get("status") == "unlisted":
                continue
            blob = normalize(" ".join([str(ev.get("title") or "")] +
                                      [str(x) for x in (ev.get("lineup") or [])] +
                                      [str(ev.get("venue") or "")]))
            if q in blob or (qtok and qtok <= set(blob.split())):
                out.append(ev)
        return sorted(out, key=lambda e: str(e.get("date")))
    # --auto: the featured head + starred, ranked exactly like the front page. Stamp the
    # same lib/scoring score the feed uses so rank_key isn't flying blind on raw rows.
    taste = load_yaml(REPO / "taste.yaml")
    profile = load_yaml(REPO / "profile.yaml")
    affinity = merged_affinity(REPO, profile)
    verdicts = ED.verdict_map(ED.load_verdicts(ED.verdict_path(None)))
    starred = set(star_map(load_reactions(REPO / "data" / "reactions.jsonl")).keys())
    scored = []
    for ev in catalog:
        if str(ev.get("date") or "")[:10] >= today_iso and ev.get("status") != "unlisted":
            scored.append(dict(ev, score=score_event(ev, taste, profile, affinity)["score"]))
    pool = PR.auto_pool(scored, verdicts, today_iso, days=args.days, starred=starred)
    picked, names = [], set()
    for ev in pool:
        name = PR.search_name(ev).lower()
        if name not in names and len(names) >= args.top:
            continue
        names.add(name)
        picked.append(ev)
    return picked


def check(events: list, store: dict, args) -> dict:
    """One Gametime query per unique act; SeatGeek per event when creds exist; the listed
    price recorded as the primary anchor. Returns run counters."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sg_id = os.environ.get("SEATGEEK_CLIENT_ID")
    by_name = {}
    for ev in events:
        by_name.setdefault(PR.search_name(ev), []).append(ev)
    n = {"events": len(events), "queries": 0, "options": 0, "failed": 0}
    for i, (name, group) in enumerate(sorted(by_name.items())):
        for ev in group:
            lo = PR.listed_option(ev, checked_at=now)
            if lo:
                PR.record(store, ev, lo)
                n["options"] += 1
        items = []
        if not args.no_gametime:
            if i:
                time.sleep(0.5)  # politeness — undocumented API, keep well under 2 req/s
            n["queries"] += 1
            try:
                items = PR.gametime_search(name)
            except Exception as e:  # noqa: BLE001 — one dead marketplace never blocks the run
                n["failed"] += 1
                print(f"  WARN gametime '{name}': {e}", file=sys.stderr)
        for ev in group:
            hit = PR.match_gametime(ev, items) if items else None
            opt = PR.gametime_option(hit, checked_at=now) if hit else None
            if opt:
                PR.record(store, ev, opt)
                n["options"] += 1
            if sg_id:
                try:
                    so = PR.seatgeek_option(ev, sg_id)
                    if so:
                        PR.record(store, ev, dict(so, checked_at=now))
                        n["options"] += 1
                except Exception as e:  # noqa: BLE001
                    n["failed"] += 1
                    print(f"  WARN seatgeek '{name}': {e}", file=sys.stderr)
    return n


def report(events: list, store: dict, show_links: bool) -> None:
    pmap = PR.price_map(store)
    for ev in events:
        key = event_key(ev)
        print(f"\n{ev.get('title')} · {_day_md(ev.get('date'))} · {ev.get('venue')}   [{key}]")
        entry = pmap.get(key)
        if entry:
            floor = entry["options"][0]
            for o in entry["options"]:
                mark = "  ← cheapest" if o is floor and len(entry["options"]) > 1 else ""
                bits = [f"  {_fmt_price(o):>8}  {o['source']}"]
                if o.get("kind") == "listed":
                    bits.append("listed")
                if o.get("note") and o["note"] != "all-in":
                    bits.append(o["note"])
                elif o.get("prefee") is not None:
                    bits.append(f"all-in (${o['prefee']:,.2f} before fees)")
                if o.get("url"):
                    bits.append(o["url"])
                print("  ".join(bits) + mark)
        else:
            print("  no prices on file")
        if show_links or not entry:
            links = "  ·  ".join(f"{l['label']} {l['url']}" for l in PR.compare_links(PR.search_name(ev)))
            print(f"  compare: {links}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = ap.add_argument_group("selection")
    sel.add_argument("--auto", action="store_true", help="featured head + starred (the nightly pass)")
    sel.add_argument("--query", help="fuzzy act/title/venue match over upcoming events")
    sel.add_argument("--key", action="append", help="exact event_key (repeatable)")
    sel.add_argument("--days", type=int, default=21, help="--auto window (default 21)")
    sel.add_argument("--top", type=int, default=60, help="--auto cap on unique acts queried (default 60)")
    ap.add_argument("--record", action="store_true", help="save one hand-found option (needs --key, --source, --price)")
    ap.add_argument("--source", help="--record: marketplace name, e.g. stubhub")
    ap.add_argument("--price", type=float, help="--record: dollars")
    ap.add_argument("--url", help="--record: listing URL")
    ap.add_argument("--note", help="--record: free-text note (e.g. 'incl fees', 'sec 102')")
    ap.add_argument("--kind", default="resale", choices=["resale", "listed"], help="--record row kind")
    ap.add_argument("--links", action="store_true", help="print marketplace search URLs, no fetching")
    ap.add_argument("--no-gametime", action="store_true")
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--store", default=PR.DEFAULT_STORE)
    ap.add_argument("--dry-run", action="store_true", help="fetch + report but don't write the store")
    args = ap.parse_args()

    import json
    cat_path = REPO / args.catalog if not Path(args.catalog).is_absolute() else Path(args.catalog)
    store_path = REPO / args.store if not Path(args.store).is_absolute() else Path(args.store)
    catalog = json.loads(cat_path.read_text())
    today_iso = today_la().isoformat()
    store = PR.load_store(store_path)

    if args.record:
        if not (args.key and len(args.key) == 1 and args.source and args.price is not None):
            print("--record needs exactly one --key plus --source and --price", file=sys.stderr)
            return 2
        events = select_events(catalog, args, today_iso)
        if not events:
            print(f"no catalog event with key {args.key[0]}", file=sys.stderr)
            return 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        PR.record(store, events[0], {"source": args.source, "kind": args.kind, "price": args.price,
                                     "url": args.url, "note": args.note, "checked_at": now})
        report(events, store, show_links=False)
        if not args.dry_run:
            PR.save_store(store, store_path)
            print(f"\nrecorded -> {args.store}")
        return 0

    if not (args.auto or args.query or args.key):
        ap.print_usage()
        print("pick a selection: --auto, --query, or --key", file=sys.stderr)
        return 2

    events = select_events(catalog, args, today_iso)
    if not events:
        print("no matching upcoming events")
        return 0
    if args.links:
        report(events, {"events": {}}, show_links=True)
        return 0

    n = check(events, store, args)
    dropped = PR.prune(store, today_iso)
    report(events, store, show_links=bool(args.query or args.key))
    print(f"\nchecked {n['events']} events ({n['queries']} gametime queries): "
          f"{n['options']} options recorded, {n['failed']} lookups failed"
          f"{f', {dropped} past events pruned' if dropped else ''}")
    if args.dry_run:
        print("dry run — store not written")
        return 0
    PR.save_store(store, store_path)
    print(f"wrote {args.store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
