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
from lib.scoring import score_event, parse_event_date  # noqa: E402
from lib.pipeline import today_la  # noqa: E402
from lib.affinity import _token_pat  # noqa: E402  (whole-token matcher — no 'Ame' in 'James')

REPO = Path(__file__).resolve().parent.parent

# Arena/amphitheater/stadium scale — a booking here signals a major touring act (broad, so it's
# the weakest signal). Mid-size clubs are deliberately excluded (they book nightly).
BIG_VENUE = ("hollywood bowl", "kia forum", "the forum", "crypto.com arena", "bmo stadium",
             "sofi stadium", "greek theatre", "intuit dome", "microsoft theater", "peacock theater",
             "honda center", "youtube theater", "toyota arena", "acrisure", "yaamava", "shrine",
             "dodger stadium", "rose bowl", "banc of california", "frost amphitheater")
FEST_TERMS = ("festival", "fest ", "fest)", "two-day", "three-day", "2-day", "3-day",
              "weekender", "block party")
# Signal -> weight for the radar rank (editorial/festival/tracked beat the broad big-venue).
SIGNAL_WEIGHT = {"editorial": 3, "festival": 2, "tracked": 2, "big-venue": 1}


def radar_signals(ev: dict, tracked: list) -> list:
    """The radar signals an event fires (empty = not radar-worthy)."""
    hay = json.dumps(ev, ensure_ascii=False).lower()
    vlow = (ev.get("venue") or "").lower()
    name_text = (ev.get("title", "") + " " + str(ev.get("lineup") or "")).lower()
    out = []
    if ev.get("editorial_mentions"):
        out.append("editorial")
    if any(t in hay for t in FEST_TERMS):
        out.append("festival")
    hits = sorted({a for a in tracked if len(a) >= 4 and _token_pat(a.lower()).search(name_text)})
    if hits:
        out.append("tracked:" + ",".join(hits[:2]))
    if any(b in vlow for b in BIG_VENUE):
        out.append("big-venue")
    return out


def radar_rank(score: int, signals: list) -> float:
    """Rank key: summed signal weight (the spine) + a small score nudge. Higher = lead."""
    w = sum(SIGNAL_WEIGHT.get(s.split(":")[0], 0) for s in signals)
    return w + (score or 0) / 10.0


def build_radar(catalog: list, taste: dict, profile: dict, today, cutoff_days: int = 35) -> list:
    """Ranked radar set: events on/after today+cutoff_days that fire ≥1 signal, best-first."""
    tracked = [a for a in (taste.get("artists_tracked") or []) if a]
    cutoff = today.toordinal() + cutoff_days
    out = []
    for ev in catalog:
        d = parse_event_date(ev)
        if d is None or d.toordinal() < cutoff:
            continue
        sig = radar_signals(ev, tracked)
        if not sig:
            continue
        s = score_event(ev, taste, profile)["score"]
        link = next((l["url"] for l in (ev.get("links") or [])
                     if isinstance(l, dict) and l.get("url")), None)
        out.append({
            "id": ev.get("title"), "title": ev.get("title"), "venue": ev.get("venue"),
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
    print(f"build_radar {today}: {len(rows)} radar candidates (>{args.cutoff_days}d) -> "
          f"{out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path}"
          f"{' + ' + args.md if args.md else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
