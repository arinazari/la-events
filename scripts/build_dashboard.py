#!/usr/bin/env python3
"""Build the dashboard data feed from the catalog + taste profile.

Reads a catalog JSON (deduped event records), taste.yaml, profile.yaml, and
sources.yaml, scores each event against the taste profile, folds in any cached
scene-researcher enrichment, and writes dashboard/data.json — the static feed the
dashboard (dashboard/index.html) loads. Scoring is imported from scripts/lib/scoring.py
— the SAME module the digest/run_digest.py use, so the dashboard's "recommended for
you" rating can't drift from the digest's ranking.

The feed has three parts:
  - events[]   — every catalog event, scored (+ rating/reasons), with enrichment folded
                 in when data/enrichment.json has a hit for it (curator note, type/
                 subgenre tags, artist notes, image).
  - config     — a structured snapshot of the editable knobs (taste.yaml content,
                 profile.yaml scoring mechanics, sources.yaml registry) so the
                 dashboard's Settings view can render current state and stage edits.
  - metadata   — generated_at, counts, the neighborhood/category facets for filters.

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
from collections import Counter
from datetime import date, datetime
from pathlib import Path

# Make `lib` importable regardless of cwd (scripts/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_yaml  # noqa: E402
from lib.scoring import score_event, score_to_rating, parse_event_date  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.enrich import load_cache, event_key  # noqa: E402
from lib.tagging import VOCAB as TAG_VOCAB  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Enrichment fields worth surfacing on the dashboard (scene-researcher output). The
# cache also stores id/enriched_at/confidence — internal plumbing the viewer ignores.
ENRICH_FIELDS = (
    "type", "subgenres", "label_orbit", "energy", "setting", "sounds_like",
    "artist_notes", "curator_note", "description", "image",
)


def build_config(taste: dict, profile: dict, sources: dict) -> dict:
    """A structured snapshot of the editable settings for the dashboard Settings view.

    Mirrors the split of concerns the repo already enforces:
      taste.yaml   = CONTENT  (what Ari likes)        -> config.taste
      profile.yaml = MECHANISM (weights/terms/geo)    -> config.scoring + config.home
      sources.yaml = REGISTRY                          -> config.sources
    The view stages edits against this and hands a precise change-set to the agent,
    which writes the real YAML — so the source of truth stays in the files, not here.
    """
    scoring = profile.get("scoring") or {}
    cats = taste.get("categories") or {}
    src_list = []
    for s in (sources.get("sources") or []):
        if not isinstance(s, dict):
            continue
        src_list.append({
            "name": s.get("name"),
            "category": s.get("category"),
            "method": s.get("method"),
            "priority": s.get("priority"),
            "status": s.get("status"),
        })
    return {
        "files": {"taste": "taste.yaml", "profile": "profile.yaml", "sources": "sources.yaml"},
        "taste": {
            "categories": {
                "high": cats.get("high") or [],
                "medium": cats.get("medium") or [],
                "low": cats.get("low") or [],
            },
            "boosts": taste.get("boosts") or [],
            "penalties": taste.get("penalties") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
            "comedians_loved": taste.get("comedians_loved") or [],
            "venues_loved": taste.get("venues_loved") or [],
            "pinned_series": taste.get("pinned_series") or [],
        },
        "scoring": {
            "category_weights": scoring.get("category_weights") or {},
            "rating_thresholds": scoring.get("rating_thresholds") or [],
            "near_home_neighborhoods": scoring.get("near_home_neighborhoods") or [],
            "groove_terms": scoring.get("groove_terms") or [],
            "eu_terms": scoring.get("eu_terms") or [],
            "penalty_terms": scoring.get("penalty_terms") or [],
            "far_terms": scoring.get("far_terms") or [],
            "spotify": scoring.get("spotify") or {},
            "feedback": scoring.get("feedback") or {},
        },
        "home": profile.get("home") or {},
        "sources": src_list,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="data/catalog.json",
                    help="catalog JSON to read (default: data/catalog.json)")
    ap.add_argument("-o", "--out", default="dashboard/data.json")
    ap.add_argument("--taste", default="taste.yaml")
    ap.add_argument("--profile", default="profile.yaml")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--enrichment", default="data/enrichment.json",
                    help="scene-graph cache to fold in (optional; skipped if absent)")
    args = ap.parse_args()

    def resolve(p):
        return (REPO / p) if not Path(p).is_absolute() else Path(p)

    catalog_path = resolve(args.input)
    out_path = resolve(args.out)
    taste_path = resolve(args.taste)
    profile_path = resolve(args.profile)
    sources_path = resolve(args.sources)
    enrichment_path = resolve(args.enrichment)

    if not catalog_path.exists():
        print(f"ERROR: catalog not found: {catalog_path}", file=sys.stderr)
        return 1

    with catalog_path.open() as f:
        catalog = json.load(f)
    taste = load_yaml(taste_path)
    profile = load_yaml(profile_path)
    sources = load_yaml(sources_path)

    # Dining layer (la-dining) — pass a trimmed restaurant list through to the feed so the
    # dashboard's concierge chat can fuse food + events into plans. Pure passthrough (no
    # scoring); graceful if data/dining.json is absent or malformed.
    dining = []
    dining_path = REPO / "data" / "dining.json"
    if dining_path.exists():
        try:
            with dining_path.open() as f:
                raw_dining = json.load(f)
            for r in (raw_dining if isinstance(raw_dining, list) else []):
                if not isinstance(r, dict) or not r.get("name"):
                    continue
                resv = r.get("reservations") or {}
                dining.append({
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "cuisine": r.get("cuisine") or [],
                    "neighborhood": r.get("neighborhood"),
                    "price": r.get("price"),
                    "occasion": r.get("occasion") or [],
                    "reservation_url": resv.get("url"),
                    "reservation_platform": resv.get("platform"),
                    "notes": r.get("notes"),
                })
        except (json.JSONDecodeError, OSError):
            dining = []

    # Spotify + feedback music layer (Phase C) — the same merged layer the digest scores
    # against (Spotify affinity folded with data/feedback.jsonl), so the dashboard stars match.
    # Graceful: absent/corrupt -> taste.yaml-only scoring.
    affinity = merged_affinity(REPO, profile)

    # Scene-researcher enrichment cache (Phase B) — fold the accumulated curator notes /
    # tags / artist notes / images onto matching events. Graceful: no file -> {} -> no-op.
    cache = load_cache(enrichment_path)
    enriched_events = cache.get("events") or {}

    is_sample = "sample" in catalog_path.name
    today = date.today()

    events = []
    enriched_hits = 0
    for ev in catalog:
        scored = score_event(ev, taste, profile, affinity)
        d = parse_event_date(ev)
        out = dict(ev)
        out["score"] = scored["score"]
        out["rating"] = score_to_rating(scored["score"], profile)
        out["reasons"] = scored["reasons"]
        out["iso_date"] = d.isoformat() if d else None
        out["is_past"] = bool(d and d < today)

        hit = enriched_events.get(event_key(ev)) if enriched_events else None
        if hit:
            out["enrichment"] = {k: hit[k] for k in ENRICH_FIELDS if hit.get(k)}
            enriched_hits += 1

        events.append(out)

    # Sort: upcoming first by date, then by rating desc within a date.
    events.sort(key=lambda e: (e["iso_date"] or "9999-12-31", -e["rating"]))

    neighborhoods = sorted({e["neighborhood"] for e in events if e.get("neighborhood")})
    categories = sorted({e["category"] for e in events if e.get("category")})

    # Multi-axis tag facets (scripts/lib/tagging.py) — only values actually present, each
    # with its count, so a future filter UI can render chips without re-scanning every event.
    def facet(axis, listish=False):
        c = Counter()
        for e in events:
            tags = e.get("tags") or {}
            v = tags.get(axis)
            for item in (v or []) if listish else ([v] if v else []):
                c[item] += 1
        return [{"value": k, "count": n} for k, n in c.most_common()]

    tag_facets = {
        "type": facet("type"),
        "genre": facet("genre", listish=True),
        "setting": facet("setting", listish=True),
        "vibe": facet("vibe", listish=True),
        "region": facet("region"),
        "vocab": TAG_VOCAB,
    }

    feed = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(catalog_path.relative_to(REPO)) if catalog_path.is_relative_to(REPO) else str(catalog_path),
        "is_sample": is_sample,
        "count": len(events),
        "enriched_count": enriched_hits,
        "neighborhoods": neighborhoods,
        "categories": categories,
        "tag_facets": tag_facets,
        "dining": dining,
        "taste": {
            "venues_loved": taste.get("venues_loved") or [],
            "artists_tracked": taste.get("artists_tracked") or [],
        },
        "config": build_config(taste, profile, sources),
        "events": events,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(feed, f, indent=2)
    rel_out = out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path
    print(f"Wrote {len(events)} events ({enriched_hits} enriched) -> {rel_out}"
          f"{' (SAMPLE data)' if is_sample else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
