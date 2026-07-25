#!/usr/bin/env python3
"""Build the 'on the radar' set — far-out events worth knowing about now.

The third tier of the consolidated daily digest (after the 14-day day-by-day window and the
month-of-weekends): festivals, big-venue shows, tracked-artist bookings, and editorially-hyped
events beyond the near horizon — the things you'd kick yourself for missing if you only looked
two weeks out. Deterministic (no API): a transparent signal heuristic over the catalog, ranked.

  data/radar.json   — ranked radar set the consolidated renderer reads (runtime artifact)
  radar-candidates.md (optional, --md) — a human-reviewable table to curate into festivals.yaml

Signals (per event): editorial mention, festival/multi-day, a tracked artist on the bill, an
arena/amphitheater booking. Tracked-name matching is whole-token (so 'Ame' doesn't hit 'James').

Usage:
  python scripts/build_radar.py                      # data/catalog.json -> data/radar.json
  python scripts/build_radar.py --cutoff-days 35 --md radar-candidates.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_taste, load_profile  # noqa: E402
from lib.scoring import score_event, parse_event_date, _scoring_cfg  # noqa: E402
from lib.dedupe import normalize  # noqa: E402  (run-collapse key for around-town)
from lib.pipeline import today_la  # noqa: E402
from lib.enrich import event_key  # noqa: E402  (stable key for the around-town/slate de-dupe)
from lib.affinity import tracked_hits, ambiguous_set  # noqa: E402  (lineup-first billed-name match)

REPO = Path(__file__).resolve().parent.parent

# Arena/amphitheater/stadium scale — a booking here signals a major touring act (broad, so it's
# the weakest signal). Mid-size clubs are deliberately excluded (they book nightly).
BIG_VENUE = ("hollywood bowl", "kia forum", "the forum", "crypto.com arena", "bmo stadium",
             "sofi stadium", "greek theatre", "intuit dome", "microsoft theater", "peacock theater",
             "honda center", "youtube theater", "toyota arena", "acrisure", "yaamava", "shrine",
             "dodger stadium", "rose bowl", "banc of california", "frost amphitheater")
FEST_TERMS = ("festival", "fest ", "fest)", "two-day", "three-day", "2-day", "3-day",
              "weekender", "block party")
# Civic/seasonal one-offs (Track B4) — the "make the city feel alive" class: notable for the
# city even when the taste score is ~0 (LA Marathon, a book festival, fireworks, a night
# market). These feed the digest's Around-town section, which is deliberately NOT taste-ranked.
# Kept tight to stay signal; grow it as real misses show up.
CIVIC_TERMS = ("marathon", "book fair", "book festival", "county fair", "state fair", "parade",
               "fireworks", "night market", "art walk", "open studios", "solstice", "equinox",
               "grand prix", "air show", "street fair", "food festival", "lantern festival",
               "car show", "county museum free")
# Signal -> weight for the radar rank (editorial/festival/tracked beat the broad big-venue).
SIGNAL_WEIGHT = {"editorial": 3, "festival": 2, "tracked": 2, "civic": 2, "big-venue": 1}


def radar_signals(ev: dict, tracked: list, ambiguous=frozenset()) -> list:
    """The radar signals an event fires (empty = not radar-worthy). Tracked-name matching is
    lineup-first (Track B3): whole-token in title+lineup for normal names; ambiguous word-like
    names (FISHER, Drama) must equal a lineup entry — a title like 'Fisher and Thames' can't
    badge the tech-house FISHER."""
    hay = json.dumps(ev, ensure_ascii=False).lower()
    vlow = (ev.get("venue") or "").lower()
    out = []
    if ev.get("editorial_mentions"):
        out.append("editorial")
    if any(t in hay for t in FEST_TERMS):
        out.append("festival")
    hits = sorted(tracked_hits(tracked, ev.get("title", ""), ev.get("lineup"),
                               ambiguous=ambiguous, min_len=4))
    if hits:
        out.append("tracked:" + ",".join(hits[:2]))
    if any(b in vlow for b in BIG_VENUE):
        out.append("big-venue")
    return out


def around_signals(ev: dict, tracked: list, ambiguous=frozenset()) -> list:
    """Signals for the near-window Around-town set (Track B4): everything radar fires PLUS the
    civic/seasonal class. An event qualifies regardless of its taste score — this is the
    city-pulse ('stay apprised'), not the taste lanes."""
    out = radar_signals(ev, tracked, ambiguous)
    hay = json.dumps(ev, ensure_ascii=False).lower()
    if any(t in hay for t in CIVIC_TERMS):
        out.append("civic")
    return out


def radar_rank(score: int, signals: list) -> float:
    """Rank key: summed signal weight (the spine) + a small score nudge. Higher = lead."""
    w = sum(SIGNAL_WEIGHT.get(s.split(":")[0], 0) for s in signals)
    return w + (score or 0) / 10.0


def build_radar(catalog: list, taste: dict, profile: dict, today, cutoff_days: int = 35) -> list:
    """Ranked radar set: events on/after today+cutoff_days that fire ≥1 signal, best-first."""
    tracked = [a for a in (taste.get("artists_tracked") or []) if a]
    amb = ambiguous_set(profile, taste)
    cutoff = today.toordinal() + cutoff_days
    out = []
    for ev in catalog:
        d = parse_event_date(ev)
        if d is None or d.toordinal() < cutoff:
            continue
        sig = radar_signals(ev, tracked, amb)
        if not sig:
            continue
        s = score_event(ev, taste, profile)["score"]
        link = next((l["url"] for l in (ev.get("links") or [])
                     if isinstance(l, dict) and l.get("url")), None)
        out.append({
            "id": ev.get("title"), "key": event_key(ev),
            "title": ev.get("title"), "venue": ev.get("venue"),
            "neighborhood": ev.get("neighborhood"), "date": ev.get("date"),
            "iso_date": d.isoformat(), "score": s, "signals": sig, "link": link,
            "lineup": ev.get("lineup") or [], "category": ev.get("category"),
        })
    out.sort(key=lambda e: (-radar_rank(e["score"], e["signals"]), e["iso_date"]))
    return out


def build_around_town(catalog: list, taste: dict, profile: dict, today, days: int = 14) -> list:
    """The near-window city-pulse set (Track B4): events in the next `days` days firing ≥1
    around_signals signal, regardless of taste score. Feeds the digest's Around-town section
    ('stay apprised' — LA Marathon, Kendrick at an arena, a night market), which the renderer
    de-dupes against the taste slate (this section is what the taste lanes DIDN'T surface).
    Rows carry a stable `key` (event_key) for that de-dupe. Three noise gates, each caught on
    live output: far-flung events are out entirely (the city-pulse is LA — profile far_terms;
    no festival waiver here, unlike scoring); film/comedy titles can't fire `civic` (the 1925
    film 'The Big Parade' is not a parade); multi-date runs collapse to their earliest date."""
    tracked = [a for a in (taste.get("artists_tracked") or []) if a]
    amb = ambiguous_set(profile, taste)
    far = _scoring_cfg(profile, taste)["far"]
    start, end = today.toordinal(), today.toordinal() + days
    out, seen_runs = [], set()
    for ev in sorted(catalog, key=lambda e: e.get("date") or "9999"):
        d = parse_event_date(ev)
        if d is None or not (start <= d.toordinal() < end):
            continue
        place = " ".join([ev.get("venue") or "", ev.get("neighborhood") or "",
                          ev.get("title") or ""]).lower()
        if any(f in place for f in far):
            continue
        sig = around_signals(ev, tracked, amb)
        if (ev.get("category") or "").lower() in ("film", "comedy") and "civic" in sig:
            sig.remove("civic")
        if not sig:
            continue
        run = (normalize(ev.get("title") or ""), normalize(ev.get("venue") or ""))
        if run in seen_runs:
            continue
        seen_runs.add(run)
        s = score_event(ev, taste, profile)["score"]
        link = next((l["url"] for l in (ev.get("links") or [])
                     if isinstance(l, dict) and l.get("url")), None)
        out.append({
            "key": event_key(ev), "title": ev.get("title"), "venue": ev.get("venue"),
            "neighborhood": ev.get("neighborhood"), "date": ev.get("date"),
            "iso_date": d.isoformat(), "score": s, "signals": sig, "link": link,
            "lineup": ev.get("lineup") or [], "category": ev.get("category"),
        })
    out.sort(key=lambda e: (-radar_rank(e["score"], e["signals"]), e["iso_date"]))
    return out


def _write_md(rows: list, path: Path, today) -> None:
    from collections import Counter
    sig = Counter(s.split(":")[0] for r in rows for s in r["signals"])
    L = [f"# Radar candidates — on the radar\n",
         f"_Generated {today.month}/{today.day}/{today.year} deterministically (no API). "
         f"{len(rows)} candidates. Signals: " + ", ".join(f"{k} {v}" for k, v in sig.most_common()) + "._\n",
         "_Review → fold keepers into `festivals.yaml`._\n"]
    cur = None
    for r in rows:
        ym = datetime.fromisoformat(r["iso_date"]).strftime("%B %Y")
        if ym != cur:
            cur = ym
            L += [f"\n## {ym}\n", "| Date | Sc | Event | Venue | Why | Link |", "|---|---|---|---|---|---|"]
        d = datetime.fromisoformat(r["iso_date"])
        L.append(f"| {d.strftime('%a')} {d.month}/{d.day} | {r['score']} | "
                 f"{(r['title'] or '')[:58].replace('|','/')} | {(r['venue'] or '')[:34].replace('|','/')} | "
                 f"{', '.join(r['signals'])} | {'[link]('+r['link']+')' if r['link'] else ''} |")
    path.write_text("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data/catalog.json")
    ap.add_argument("-o", "--out", default="data/radar.json")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    ap.add_argument("--cutoff-days", type=int, default=35, help="radar = events at least this far out")
    ap.add_argument("--md", default=None, help="also write a reviewable markdown table here")
    ap.add_argument("--around-days", type=int, default=14,
                    help="also build the near-window Around-town (city-pulse) set spanning this "
                         "many days (0 = skip)")
    ap.add_argument("--around-out", default="data/around_town.json",
                    help="Around-town set output (the consolidated renderer reads it)")
    args = ap.parse_args()

    def resolve(p):
        return REPO / p if not Path(p).is_absolute() else Path(p)

    catalog = json.loads(resolve(args.input).read_text())
    taste, profile = load_taste(args.taste), load_profile(args.profile)
    today = today_la()
    rows = build_radar(catalog, taste, profile, today, cutoff_days=args.cutoff_days)

    doc = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "today": today.isoformat(), "cutoff_days": args.cutoff_days,
           "count": len(rows), "events": rows}
    out_path = resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    if args.md:
        _write_md(rows, resolve(args.md), today)

    n_around = 0
    if args.around_days > 0:
        around = build_around_town(catalog, taste, profile, today, days=args.around_days)
        n_around = len(around)
        a_doc = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                 "today": today.isoformat(), "days": args.around_days,
                 "count": n_around, "events": around}
        a_path = resolve(args.around_out)
        a_path.parent.mkdir(parents=True, exist_ok=True)
        a_path.write_text(json.dumps(a_doc, indent=2, ensure_ascii=False) + "\n")

    print(f"build_radar {today}: {len(rows)} radar candidates (>{args.cutoff_days}d)"
          f"{f' + {n_around} around-town (<{args.around_days}d)' if args.around_days > 0 else ''} -> "
          f"{out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path}"
          f"{' + ' + args.md if args.md else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
