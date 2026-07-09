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
                 subgenre tags, artist notes).
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make `lib` importable regardless of cwd (scripts/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.config import load_yaml  # noqa: E402
from lib.scoring import score_event, score_to_rating, parse_event_date  # noqa: E402
from lib.feedback import merged_affinity  # noqa: E402
from lib.enrich import load_cache, merge_enrichment, event_key  # noqa: E402
from lib import editor as ED  # noqa: E402
from lib.assemble import rank_key, event_lane  # noqa: E402
from lib.tagging import VOCAB as TAG_VOCAB  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402
from lib.pipeline import today_la  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Enrichment fields worth surfacing on the dashboard (scene-researcher output). The
# cache also stores id/enriched_at/confidence — internal plumbing the viewer ignores.
ENRICH_FIELDS = (
    "type", "subgenres", "label_orbit", "energy", "setting", "sounds_like",
    "artist_notes", "curator_note", "description",
)


def music_block(affinity: dict) -> dict:
    """A compact self-report of the music layer this feed was actually scored against, so the
    dashboard can tell a connected-but-not-yet-applied Spotify (a stale ranking, or a failed
    per-profile sync) from a live one. `layer` is none / feedback / spotify / spotify+feedback;
    the counts are what fed the scorer. Purely additive — older viewers ignore it."""
    if not affinity:
        return {"layer": "none", "artists": 0, "genres": 0}
    return {"layer": affinity.get("source") or "spotify",
            "artists": len(affinity.get("artists") or {}),
            "genres": len(affinity.get("genres") or {})}


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
    ap.add_argument("--profile-hash", default=None,
                    help="feed hash of the profile being built — loads its OWN per-person music "
                         "layer (data/spotify/<hash>.json + data/feedback.<hash>.jsonl) instead of "
                         "the default/owner one. Omit for the canonical (Ari's) feed.")
    ap.add_argument("--verdicts", default=None,
                    help="editor verdict store to fold in (default: data/verdicts/<hash>.json for "
                         "this profile). Adds each event's verdict + final_rank to the feed.")
    ap.add_argument("--editor-pool-out", default=None,
                    help="also emit this profile's editor judging pool here (for the event-editor pass)")
    ap.add_argument("--editor-window", type=int, default=28)
    ap.add_argument("--editor-per-lane", type=int, default=0,
                    help="0 (default) = judge every slate-lane event in the window (LLM-first)")
    ap.add_argument("--editor-floor", type=int, default=4)
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
    # against (Spotify affinity folded with feedback), so the dashboard stars match. With a
    # --profile-hash this loads THAT profile's own per-person layer (per-profile Spotify), so a
    # friend's feed ranks to their music, not Ari's. Graceful: absent/corrupt -> taste-only.
    affinity = merged_affinity(REPO, profile, profile_hash=args.profile_hash)

    # Scene-researcher enrichment cache (Phase B) — fold the accumulated curator notes / tags /
    # artist notes / images onto matching events, AND cached artist bios onto ANY event that lists
    # those artists (parity with the digest's merge_enrichment). Graceful: no file -> no-op.
    cache = load_cache(enrichment_path)

    # Editor verdicts (per-profile) — the thin-editor's ranking judgment, folded onto each event so
    # the dashboard can show the final (verdict-adjusted) rank beside the deterministic score and
    # sort by either. Same verdict the digest slate uses; absent -> deterministic order only.
    vpath = resolve(args.verdicts) if args.verdicts else ED.verdict_path(args.profile_hash)
    verdicts = ED.verdict_map(ED.load_verdicts(vpath))

    is_sample = "sample" in catalog_path.name
    # LA-local today (NOT the runner's UTC date) — otherwise, in CI (UTC) past midnight UTC, events
    # still happening tonight in LA get marked is_past and lose their final_rank / highlight.
    today = today_la()

    # Fold the enrichment cache onto the whole catalog ONCE (order-preserving) instead of a
    # per-event merge_enrichment([ev]) call inside the loop — same result, O(N) not O(N) calls.
    merged_all = merge_enrichment(catalog, cache)

    events = []
    enriched_hits = 0
    for ev, merged in zip(catalog, merged_all):
        scored = score_event(ev, taste, profile, affinity)
        d = parse_event_date(ev)
        out = dict(ev)
        out["score"] = scored["score"]
        out["rating"] = score_to_rating(scored["score"], profile, taste)
        out["reasons"] = scored["reasons"]
        out["iso_date"] = d.isoformat() if d else None
        out["is_past"] = bool(d and d < today)

        enr = merged.get("enrichment")
        if enr:
            out["enrichment"] = {k: enr[k] for k in ENRICH_FIELDS if enr.get(k)}
            enriched_hits += 1

        v = verdicts.get(event_key(ev))
        if v:
            out["verdict"] = v                       # {tier, lane?, adjust, why, confidence}
        out["lane"] = event_lane(out, verdicts)      # verdict lane override else tag-derived

        events.append(out)

    # Final rank — each UPCOMING event's position by the two-zone rank_key (Track B2, LLM-first):
    # judged non-skip events tier-primary (the editor's call IS the ranking; score orders within a
    # tier), then the unjudged tail (far-out / junk lanes) by raw score, judged skips last. The
    # near window is fully judged (B1), so the default view leads with the LLM's ranking and the
    # far tail sorts below it (date filters cover plan-ahead). The dashboard shows final_rank
    # beside the deterministic score and sorts by either. Past events stay unranked.
    upcoming = [e for e in events if not e["is_past"]]
    for rank, e in enumerate(
            sorted(upcoming, key=lambda e: (rank_key(e, verdicts), event_key(e)), reverse=True), 1):
        e["final_rank"] = rank

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

    # The catalog version this feed was scored against — the dashboard compares it to the live
    # dashboard/catalog_meta.json to decide if this profile's ranking/digest is stale. Prefer the
    # stamp written by run_digest; fall back to recomputing from the catalog we just read.
    cat_meta = CM.read_meta(catalog_path.parent / "catalog_meta.json") or CM.build_meta(catalog)
    # Backfill content_version if the on-disk meta predates it, so a build-only path (build-profiles)
    # still stamps/publishes it — the dashboard staleness check keys off content_version now.
    if not cat_meta.get("content_version"):
        cat_meta["content_version"] = CM.content_version(catalog)

    feed = {
        # Timezone-aware (UTC) — the dashboard's "last data pull" parses this; a naive stamp is
        # read by the browser as local time and shows ~hours in the future for a PT viewer.
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": str(catalog_path.relative_to(REPO)) if catalog_path.is_relative_to(REPO) else str(catalog_path),
        "is_sample": is_sample,
        "catalog_version": cat_meta.get("version"),
        "catalog_content_version": cat_meta.get("content_version"),
        "catalog_fetched_at": cat_meta.get("fetched_at"),
        "count": len(events),
        "enriched_count": enriched_hits,
        "music": music_block(affinity),
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

    # Publish the live catalog version next to the feeds (any non-sample build refreshes it; the
    # content is identical regardless of which profile is built). The dashboard fetches this fresh
    # on every load to compare against each feed's `catalog_version`.
    if not is_sample and out_path.parent.is_dir():
        try:
            # Publish content_version (the staleness key) + this run's change delta (added/updated/
            # changes) so the dashboard can both flag "your ranking is stale" AND show what moved.
            meta_pub = {k: v for k, v in cat_meta.items()
                        if k in ("version", "content_version", "count", "fetched_at",
                                 "added", "updated", "changes") and v is not None}
            (out_path.parent / "catalog_meta.json").write_text(
                json.dumps(meta_pub, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"  WARN: could not publish catalog_meta.json: {e}", file=sys.stderr)

    # Optionally emit this profile's editor judging pool (the per-lane set worth LLM judgment),
    # so the event-editor pass can judge it and write per-profile verdicts. Reuses the per-profile
    # scoring just done — no second scoring path. The default-profile pool is also emitted by
    # run_digest; here it's per-profile, driven by build_profiles.
    if args.editor_pool_out:
        end_iso = (today + timedelta(days=args.editor_window)).isoformat()
        epool = [e for e in events if not e.get("is_past") and e.get("iso_date")
                 and e["iso_date"] <= end_iso and (e.get("score") or 0) >= 0]
        judge = ED.editor_pool(epool, per_lane=args.editor_per_lane, floor=args.editor_floor)
        ep_doc = ED.pool_doc(judge, today=today, window_days=args.editor_window,
                             per_lane=args.editor_per_lane, floor=args.editor_floor,
                             affinity=affinity, enrichment=cache)
        epath = resolve(args.editor_pool_out)
        epath.parent.mkdir(parents=True, exist_ok=True)
        epath.write_text(json.dumps(ep_doc, indent=2, ensure_ascii=False) + "\n")
        rel_ep = epath.relative_to(REPO) if epath.is_relative_to(REPO) else epath
        print(f"  + editor pool: {len(judge)} to judge -> {rel_ep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
