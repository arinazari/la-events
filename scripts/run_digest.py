#!/usr/bin/env python3
"""Deterministic digest core — the Tier-0 pipeline.

  fetch-all (parallel-able subprocess fetchers) -> normalize -> merge+dedupe ->
  expire past -> stamp seen -> score -> emit candidate set.

This replaces the fetch/dedupe/score that the skill used to do BY HAND each run.
Claude now only enriches (scene-researcher fan-out) + synthesizes the digest on top
of the candidate set this emits. Cheap, deterministic, safe to run daily.

Degrades gracefully: a fetcher that errors, times out, or is missing its API key is
skipped and listed in the run report — it never blocks the run (SKILL.md contract).

Outputs:
  data/catalog.json     — the durable, score-free store (merged/deduped/expired/seen-stamped)
  data/candidates.json  — scored, ranked, upcoming top-N for enrichment (runtime artifact)
  data/editor_pool.json — the per-lane set worth LLM ranking-judgment (runtime artifact; the
                          event-editor agent judges it and writes verdicts into enrichment.json)

Usage:
  python scripts/run_digest.py                     # fetch all, update catalog, emit candidates
  python scripts/run_digest.py --no-fetch          # re-run pipeline on the existing catalog only
  python scripts/run_digest.py --sources ra,dice   # fetch a subset
  python scripts/run_digest.py --window 7 --top 40 --images 10

The daily routine chains `build_dashboard.py` after this to refresh the dashboard feed.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib.config import load_taste, load_profile  # noqa: E402
from lib import pipeline as P  # noqa: E402
from lib import feedback as FB  # noqa: E402
from lib import editor as ED  # noqa: E402
from lib.tagging import tag_catalog  # noqa: E402
from lib import catalog_meta as CM  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# How to invoke each structured fetcher. `needs` = required env vars (skip-with-reason if unset).
# Output is read from the `-o` temp file each script writes (list of records, or {"events": [...]}).
FETCHERS = [
    {"name": "Ticketmaster", "source": "ticketmaster", "script": "fetch_ticketmaster.py",
     "args": ["--days", "{days}"], "needs": ["TM_API_KEY"], "far": True},
    {"name": "Resident Advisor", "source": "ra", "script": "fetch_ra.py", "args": ["--days", "{days}"]},
    {"name": "19hz", "source": "19hz", "script": "fetch_19hz.py", "args": []},
    {"name": "Goldenvoice", "source": "goldenvoice", "script": "fetch_goldenvoice.py", "args": []},
    {"name": "Vidiots", "source": "vidiots", "script": "fetch_filmbot.py", "args": []},
    {"name": "Vista Theater", "source": "vista", "script": "fetch_veezi.py",
     "args": ["--token", "20xhpa3yt2hhkwt4zjvfcwsaww", "--venue", "Vista Theater", "--days", "{days}"]},
    {"name": "New Beverly Cinema", "source": "newbev", "script": "fetch_veezi.py",
     "args": ["--token", "fmtswb0qqbym3de6c4bbsqj89m", "--venue", "New Beverly Cinema", "--days", "{days}"]},
    {"name": "Posh", "source": "posh", "script": "fetch_posh.py", "args": [], "needs": ["POSH_TOKEN"]},
    {"name": "Eventbrite", "source": "eventbrite", "script": "fetch_eventbrite.py", "args": []},
    {"name": "DICE", "source": "dice", "script": "fetch_dice.py", "args": []},
]


def fetch_window(entry: dict, days: int, far_days: int = None) -> int:
    """Days to fetch for one source. Far-capable sources (`far: True` — e.g. Ticketmaster, which
    date-windows internally) get the wide plan-ahead horizon; everyone else keeps the near window.
    far_days=None => the near window for all (today's single-speed behaviour). This is the seam of
    the two-speed fetch: full fidelity near-term, deterministic plan-ahead far (festivals, big tours,
    theater seasons) for the radar tier — without dragging the LLM editor/enrich windows out with it."""
    return far_days if (far_days and entry.get("far")) else days


def run_fetcher(entry: dict, days: int, tmpdir: str, far_days: int = None) -> list:
    """Run one fetcher as a subprocess and return its normalized records. Raises on any failure."""
    for var in entry.get("needs", []):
        if not os.environ.get(var):
            raise RuntimeError(f"missing ${var}")
    out = Path(tmpdir) / f"{entry['source']}.json"
    args = [a.format(days=fetch_window(entry, days, far_days)) for a in entry["args"]]
    cmd = [sys.executable, str(REPO / "scripts" / entry["script"]), *args, "-o", str(out)]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, cwd=str(REPO), text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(tail[-1][:160] if tail else f"exit {proc.returncode}")
    raw = json.loads(out.read_text())
    records = raw.get("events", raw) if isinstance(raw, dict) else raw
    return [P.normalize_record(r, entry["source"]) for r in records]


def fetch_all(selected: set, days: int, far_days: int = None) -> tuple:
    """Run the configured fetchers, collecting normalized records. Returns (incoming, report)."""
    report = {"ok": [], "failed": [], "skipped": []}
    incoming = []
    with tempfile.TemporaryDirectory() as tmp:
        for e in FETCHERS:
            if selected and e["source"] not in selected:
                report["skipped"].append(e["source"])
                continue
            try:
                recs = run_fetcher(e, days, tmp, far_days)
                incoming.extend(recs)
                report["ok"].append((e["source"], len(recs)))
            except Exception as ex:  # degrade gracefully — never block the run
                report["failed"].append((e["source"], str(ex).splitlines()[0][:120]))
    return incoming, report


def _clean_spotify_note(note: str) -> str:
    """Strip the degrade-marker prefix fetch_spotify.py prints so the footer/report read cleanly."""
    for p in ("WARN:", "SKIP:", "ERROR:"):
        if note.startswith(p):
            return note[len(p):].strip()
    return note.strip()


def load_affinity_layer(no_fetch: bool, report: dict, profile: dict) -> dict:
    """Sync Spotify (if creds present and we're fetching), then load the merged music layer.

    Merged = Spotify affinity (data/spotify_affinity.json, gitignored runtime state) folded
    with the feedback log (data/feedback.jsonl) — the one place this happens for both the
    digest and the dashboard. Degrades gracefully: any failure leaves the scorer on the
    taste.yaml-only path. The music layer only ever enriches. Returns the affinity dict or None.

    Records `report["spotify"]` as {"ok": bool, "note": str} so the run report + the digest
    footer can disclose a failed refresh (revoked token / API error) instead of swallowing it.
    """
    if not no_fetch and os.environ.get("SPOTIFY_REFRESH_TOKEN"):
        try:
            proc = subprocess.run([sys.executable, str(REPO / "scripts" / "fetch_spotify.py"),
                                   "-o", str(REPO / "data" / "spotify_affinity.json")],
                                  capture_output=True, timeout=120, cwd=str(REPO), text=True)
            lines = (proc.stdout or proc.stderr or "").strip().splitlines()
            note = lines[-1][:160] if lines else f"exit {proc.returncode}"
            # fetch_spotify.py degrades gracefully — missing creds, a revoked refresh token, or an
            # API error all exit 0 with a SKIP/WARN/ERROR line (so a dead music layer can never
            # block a digest). Health is therefore read from the message, not the exit code: only a
            # successful sync prints "Wrote Spotify affinity".
            ok = proc.returncode == 0 and note.startswith("Wrote Spotify affinity")
            report["spotify"] = {"ok": ok, "note": _clean_spotify_note(note)}
        except Exception as ex:  # noqa: BLE001
            report["spotify"] = {"ok": False, "note": f"sync failed: {str(ex).splitlines()[0][:100]}"}
    return FB.merged_affinity(REPO, profile)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--candidates", default="data/candidates.json")
    ap.add_argument("--no-fetch", action="store_true", help="skip fetching; pipeline-only re-run")
    ap.add_argument("--sources", default="", help="comma list to fetch a subset (default: all)")
    ap.add_argument("--days", type=int, default=21, help="near fetch window passed to fetchers")
    ap.add_argument("--far-days", type=int, default=None,
                    help="wide plan-ahead horizon (days) for far-capable sources (Ticketmaster); near "
                         "sources keep --days. Two-speed fetch: full-fidelity near, deterministic radar far.")
    ap.add_argument("--window", type=int, default=None, help="candidate window in days (default: all upcoming)")
    ap.add_argument("--top", type=int, default=100, help="full-enrichment head size (scene-researcher)")
    ap.add_argument("--blurb-pool", default="data/blurb_pool.json", help="cheap-tier blurb candidate output")
    ap.add_argument("--blurb-window", type=int, default=35, help="days the blurb (cheap-tier) pool spans")
    ap.add_argument("--blurb-top", type=int, default=200, help="cap on the blurb pool below the full head")
    ap.add_argument("--editor-pool", default="data/editor_pool.json", help="editor judging-set output")
    ap.add_argument("--editor-window", type=int, default=28, help="days the editor pool spans")
    ap.add_argument("--editor-per-lane", type=int, default=4, help="top-K per lane judged")
    ap.add_argument("--editor-floor", type=int, default=4, help="also judge everything scoring >= this")
    args = ap.parse_args()

    cat_path = REPO / args.catalog if not Path(args.catalog).is_absolute() else Path(args.catalog)
    cand_path = REPO / args.candidates if not Path(args.candidates).is_absolute() else Path(args.candidates)

    catalog = json.loads(cat_path.read_text()) if cat_path.exists() else []
    taste, profile = load_taste(), load_profile()
    today = P.today_la()
    # Snapshot the volatile-field state BEFORE the fetch so we can report exactly what this run
    # added vs. updated (price/time/lineup/status moves) — the "what changed, and when" signal.
    old_index = P.content_index(catalog)

    report = {"ok": [], "failed": [], "skipped": []}
    incoming = []
    if not args.no_fetch:
        selected = {s.strip() for s in args.sources.split(",") if s.strip()}
        incoming, report = fetch_all(selected, args.days, args.far_days)
        incoming = [r for r in incoming if r.get("title") and r.get("date")]

    # Always dedupe (idempotent) — collapses incoming AND any pre-existing catalog dupes.
    catalog, stats = P.merge_new(catalog, incoming, today)
    catalog, expired = P.expire_past(catalog, today)
    P.stamp_seen(catalog, today)
    # Canonicalize the location column (venue-resolve city-level/blank neighborhoods).
    P.normalize_locations(catalog, profile)
    # Stamp the deterministic multi-axis tags (type/genre/setting/vibe/region) onto every
    # record — recomputed each run, so re-tagging only needs a --no-fetch pass (lib/tagging.py).
    # Runs AFTER normalize_locations so the region tag reflects the canonicalized neighborhood.
    tag_catalog(catalog, profile)
    # Ghost sweep: events still future-dated but dropped from ALL their (successfully re-fetched)
    # sources get status:"unlisted" so they stop being recommended (score_pool drops them). Skipped
    # on --no-fetch (no fetched sources → no-op), so a pipeline-only re-run never ghosts anything.
    # NB: ghost-detection horizon stays the NEAR window (args.days), never --far-days. Far-horizon
    # plan-ahead events legitimately come and go from feeds (a venue hasn't listed November yet),
    # so judging their absence beyond the near window would false-flag them as unlisted.
    fetched_ok = {s for s, _ in report.get("ok", [])}
    stale_n = P.flag_stale(catalog, fetched_ok, today, horizon_days=args.days)
    # What moved since last run: stamps updated_at/changed_fields on changed records, returns the
    # {added, updated, changes} summary (must run AFTER tagging + flag_stale so the record is final).
    delta = P.diff_catalog(old_index, catalog, today)
    cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")

    # Stamp the catalog version (the dashboard staleness check keys off this). Lives beside the
    # catalog; build_dashboard reads it to tag each feed with the version it was built against.
    # `content_version` moves on price/time/lineup changes too (not just adds/drops); `delta`
    # carries this run's added/updated counts + a sample of what changed for the digest line.
    meta_path = cat_path.parent / "catalog_meta.json"
    cat_meta = CM.write_meta(meta_path, catalog, delta)

    affinity = load_affinity_layer(args.no_fetch, report, profile)
    candidates = P.select_candidates(catalog, taste, profile, today,
                                     window_days=args.window, top_n=args.top,
                                     affinity=affinity)
    cand_doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "window_days": args.window,
        "count": len(candidates),
        "affinity": ({"artists": len(affinity.get("artists", {})),
                      "genres": len(affinity.get("genres", {}))} if affinity else None),
        "sources": report,
        "candidates": candidates,
    }
    cand_path.write_text(json.dumps(cand_doc, indent=2, ensure_ascii=False) + "\n")

    # Editor pool — the per-lane set worth LLM ranking-judgment (lib/editor). Deterministic
    # selection over the same scored set; the event-editor agent judges this at digest time and
    # writes verdicts into enrichment.json, which assemble() then folds onto the slate.
    ep_path = REPO / args.editor_pool if not Path(args.editor_pool).is_absolute() else Path(args.editor_pool)
    pool = P.score_pool(catalog, taste, profile, today, window_days=args.editor_window, affinity=affinity)
    pool = [e for e in pool if (e.get("score") or 0) >= 0]          # negatives auto-skip; don't judge
    judge = ED.editor_pool(pool, per_lane=args.editor_per_lane, floor=args.editor_floor)
    ep_doc = ED.pool_doc(judge, today=today, window_days=args.editor_window,
                         per_lane=args.editor_per_lane, floor=args.editor_floor, affinity=affinity)
    ep_path.write_text(json.dumps(ep_doc, indent=2, ensure_ascii=False) + "\n")

    # Blurb pool — the cheap-tier (blurb-writer) candidate slice: upcoming events within
    # --blurb-window that rank BELOW the full-enrichment head, capped at --blurb-top. The fan-out
    # then runs enrich.select_for_blurb over this (only events with no cache record AND no usable
    # source detail actually cost a haiku call — the rest display raw detail for free). Bounded on
    # purpose; events past the window/cap fall back to source detail or nothing (logged below).
    bp_path = REPO / args.blurb_pool if not Path(args.blurb_pool).is_absolute() else Path(args.blurb_pool)
    head_keys = {P.event_key(c) for c in candidates}
    bpool = P.score_pool(catalog, taste, profile, today, window_days=args.blurb_window, affinity=affinity)
    bpool = [e for e in bpool if (e.get("score") or 0) >= 0 and P.event_key(e) not in head_keys]
    blurb_overflow = max(0, len(bpool) - args.blurb_top)
    blurb_cands = bpool[:args.blurb_top]
    bp_doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "window_days": args.blurb_window,
        "count": len(blurb_cands),
        "overflow": blurb_overflow,   # ranked below the cap -> raw-detail/no-blurb fallback
        "candidates": blurb_cands,
    }
    bp_path.write_text(json.dumps(bp_doc, indent=2, ensure_ascii=False) + "\n")

    # Run report.
    print(f"run_digest {today}: catalog {len(catalog)} (v{cat_meta['version']}/c{cat_meta['content_version']}) "
          f"(+{delta['added']} new, {delta['updated']} updated, {stale_n} unlisted, {stats['merged']} merged, {expired} expired) "
          f"-> {len(candidates)} candidates, {len(judge)} to judge, {len(blurb_cands)} blurb pool"
          f"{f' (+{blurb_overflow} overflow)' if blurb_overflow else ''}")
    if report["ok"]:
        print("  fetched:", ", ".join(f"{s}:{n}" for s, n in report["ok"]))
    if report["failed"]:
        print("  failed: ", ", ".join(f"{s} ({e})" for s, e in report["failed"]))
    if report["skipped"]:
        print("  skipped:", ", ".join(report["skipped"]))
    if args.far_days:
        far_srcs = ", ".join(e["source"] for e in FETCHERS if e.get("far"))
        print(f"  far horizon: {args.far_days}d for {far_srcs} (near {args.days}d for the rest)")
    if affinity:
        print(f"  music layer ({affinity.get('source', 'spotify')}): "
              f"{len(affinity.get('artists', {}))} artists, {len(affinity.get('genres', {}))} genres")
    sp = report.get("spotify")
    if isinstance(sp, dict) and not sp.get("ok"):
        # Surface a failed refresh even when feedback alone still produced an affinity layer above.
        print("  spotify: FAILED —", sp.get("note") or "refresh failed")
    elif isinstance(sp, dict) and not affinity:
        print("  spotify:", sp.get("note") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
