#!/usr/bin/env python3
"""Build the dashboard data feed from the catalog + taste profile.

Reads a catalog JSON (deduped event records) and taste.yaml, scores each event
against the taste profile, and writes dashboard/data.json — the static feed the
dashboard (dashboard/index.html) loads. Scoring here MIRRORS the digest's ranking
heuristic so the dashboard's "recommended for you" rating matches the digest.

Usage:
    python scripts/build_dashboard.py                      # from data/catalog.json
    python scripts/build_dashboard.py -i data/sample-catalog.json   # demo data
    python scripts/build_dashboard.py -o dashboard/data.json

The dashboard is a pure viewer: it does NOT score. Re-run this after every digest
(or whenever the catalog changes) to refresh what the dashboard shows.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # degrade gracefully — taste lists just go empty
    yaml = None

REPO = Path(__file__).resolve().parent.parent

# Category -> base weight, mirroring taste.yaml high/medium/low. Comedy is LOW
# (only loved comedians surface — handled in score_event), NOT a 3 like dance music.
CATEGORY_WEIGHT = {
    "electronic": 3,
    "party": 3,        # club / warehouse / afterhours party
    "film": 3,         # rep & arthouse cinema
    "music": 2,        # live music (catalog's term)
    "live_music": 2,
    "theater": 2,
    "beer_food": 2,
    "comedy": 1,
    "art": 1,
    "pop": 1,
    "general": 1,
}

# Neighborhoods that are walkable / a short drive from Silver Lake (Hyperion & Del
# Mar). Eastside + DTLA. Matched case-insensitively against an event's neighborhood.
NEAR_SILVERLAKE = {
    "silver lake", "silverlake", "echo park", "los feliz", "east hollywood",
    "atwater village", "atwater", "frogtown", "elysian valley", "highland park",
    "eagle rock", "glassell park", "cypress park", "lincoln heights", "chinatown",
    "virgil village", "westlake", "historic filipinotown", "downtown", "dtla",
    "arts district",
}

# +1 boosts (mirror the digest): rooftop/vinyl/groove setting, and European-label vibe.
GROOVE_TERMS = (
    "vinyl", "all night", "open to close", "open-to-close", "groove", "disco",
    "soulful", "deep house", "balearic", "rooftop", "sunset", "golden hour",
    "open-air", "open air", "daytime", "day party", "poolside", "pool party",
)
EU_TERMS = (
    "fabric", "defected", "innervisions", "keinemusik", "hot creations", "rush hour",
    "running back", "anjuna", "afterlife", "dirtybird", "hot since", "solid grooves",
)

# -2 penalties: the expanded non-priority list from taste.yaml (off-taste programming).
PENALTY_TERMS = (
    "bottle service", "bottle-service", "vip table", "table service",
    "top 40", "top-40", "open format", "open-format", "hip hop", "hip-hop",
    "hardstyle", "gabber", "dubstep", "riddim", "brostep", "tribute", "cover band",
    "watch party", "world cup", "fifa", "sports bar", "trivia", "bingo", "open mic",
    "karaoke", "networking", "webinar", "workshop", "virtual", "zoom",
    "mega-rave", "mega rave", "edm festival",
)
# -2: far-flung (not worth the trip by default).
FAR_TERMS = (
    "anaheim", "santa ana", "irvine", "san diego", "temecula", "ventura",
    "riverside", "long beach", "costa mesa", "huntington beach",
)


def load_yaml(path: Path) -> dict:
    if yaml is None or not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def parse_event_date(ev: dict):
    """Best-effort ISO date (YYYY-MM-DD) for an event record."""
    raw = ev.get("date") or ev.get("datetime") or ""
    if not raw:
        return None
    raw = str(raw)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def score_event(ev: dict, taste: dict) -> dict:
    """Return {score, reasons[]} for an event, mirroring the digest's ranking."""
    reasons = []
    score = 0

    cat = (ev.get("category") or "general").lower()
    title = ev.get("title") or ""
    venue = (ev.get("venue") or "")
    vlow = venue.lower()
    hood = (ev.get("neighborhood") or "").lower().strip()
    lineup = ev.get("lineup") or []
    if not isinstance(lineup, list):
        lineup = [str(lineup)]
    hay = " ".join([title, venue, ev.get("detail") or "", str(lineup),
                    str(ev.get("organizers") or "")]).lower()

    tracked = [a for a in (taste.get("artists_tracked") or []) if a]
    loved = [v.lower() for v in (taste.get("venues_loved") or [])]
    pinned = [p.lower() for p in (taste.get("pinned_series") or [])]
    comics = [c.lower() for c in (taste.get("comedians_loved") or [])]

    # Base category weight (comedy is special — suppressed unless a loved name).
    base = CATEGORY_WEIGHT.get(cat, 1)
    score += base
    if cat == "comedy":
        reasons.append("+1 comedy (low interest)")
        if any(c in hay for c in comics):
            score += 4
            reasons.append("+4 favorite comedian")
        else:
            score -= 2
            reasons.append("-2 comedy not generally wanted")
    else:
        lab = {3: "high", 2: "medium", 1: "low"}.get(base, "low")
        reasons.append(f"+{base} {cat.replace('_', ' ')} ({lab} interest)")

    # Tracked artist — match title OR lineup (+2 each; also the "tracked" badge).
    hits = sorted({a for a in tracked if a.lower() in hay})
    if hits:
        score += 2 * len(hits)
        reasons.append(f"+{2 * len(hits)} tracked artist ({', '.join(hits)})")

    # Pinned series (e.g. Sunset Sessions) — always surface.
    if any(p in hay for p in pinned):
        score += 5
        reasons.append("+5 pinned series")

    # Loved venue (substring match — "2220 Arts" ~ "2220 Arts + Archives").
    if any(l in vlow for l in loved):
        score += 1
        reasons.append("+1 venue you love")

    # Afterhours / warehouse / late start (catalog field is `afterhours`).
    if ev.get("afterhours") or ev.get("afterhours_flag"):
        score += 1
        reasons.append("+1 afterhours / late start")

    if ev.get("ra_pick"):
        score += 1
        reasons.append("+1 RA pick")

    # Rooftop / vinyl / groove setting, and European-label vibe.
    if any(g in hay for g in GROOVE_TERMS):
        score += 1
        reasons.append("+1 rooftop / vinyl / groove")
    if any(e in hay for e in EU_TERMS):
        score += 1
        reasons.append("+1 European / label vibe")

    # Friday / Saturday night.
    d = parse_event_date(ev)
    if d and d.weekday() in (4, 5):
        score += 1
        reasons.append("+1 Friday/Saturday night")

    # Near Silver Lake.
    if hood in NEAR_SILVERLAKE:
        score += 1
        reasons.append("+1 close to Silver Lake")

    # Editorial mentions (+1 each) — present once editorial signals are wired in.
    mentions = ev.get("editorial_mentions") or []
    if mentions:
        score += len(mentions)
        reasons.append(f"+{len(mentions)} editorial mention ({', '.join(mentions)})")

    # Banned venue (hard down-rank).
    banned = [v.lower() for v in (taste.get("venues_banned") or []) if v]
    if any(b in vlow for b in banned):
        score -= 5
        reasons.append("-5 venue you've banned")

    # Penalties (each distinct term once).
    for term in PENALTY_TERMS:
        if term in hay:
            score -= 2
            reasons.append(f"-2 {term}")
    if any(f in hay or f in hood for f in FAR_TERMS):
        score -= 2
        reasons.append("-2 far from LA")

    return {"score": score, "reasons": reasons}


def score_to_rating(score: int) -> int:
    """Map a raw score to a 1-5 star 'recommended for you' rating."""
    if score >= 8:
        return 5
    if score >= 6:
        return 4
    if score >= 4:
        return 3
    if score >= 2:
        return 2
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data/catalog.json",
                    help="catalog JSON to read (default: data/catalog.json)")
    ap.add_argument("-o", "--out", default="dashboard/data.json")
    ap.add_argument("--taste", default="taste.yaml")
    args = ap.parse_args()

    catalog_path = (REPO / args.input) if not Path(args.input).is_absolute() else Path(args.input)
    out_path = (REPO / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    taste_path = (REPO / args.taste) if not Path(args.taste).is_absolute() else Path(args.taste)

    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    with catalog_path.open() as f:
        catalog = json.load(f)
    taste = load_yaml(taste_path)

    is_sample = "sample" in catalog_path.name
    today = date.today()

    events = []
    for ev in catalog:
        scored = score_event(ev, taste)
        d = parse_event_date(ev)
        out = dict(ev)
        out["score"] = scored["score"]
        out["rating"] = score_to_rating(scored["score"])
        out["reasons"] = scored["reasons"]
        out["iso_date"] = d.isoformat() if d else None
        out["is_past"] = bool(d and d < today)
        events.append(out)

    # Sort: upcoming first by date, then by rating desc within a date.
    events.sort(key=lambda e: (e["iso_date"] or "9999-12-31", -e["rating"]))

    neighborhoods = sorted({e["neighborhood"] for e in events if e.get("neighborhood")})
    categories = sorted({e["category"] for e in events if e.get("category")})

    feed = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(catalog_path.relative_to(REPO)) if catalog_path.is_relative_to(REPO) else str(catalog_path),
        "is_sample": is_sample,
        "count": len(events),
        "neighborhoods": neighborhoods,
        "categories": categories,
        "taste": {
            "venues_loved": taste.get("venues_loved") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
        },
        "events": events,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(feed, f, indent=2)
    print(f"Wrote {len(events)} events -> {out_path.relative_to(REPO)}"
          f"{' (SAMPLE data)' if is_sample else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
