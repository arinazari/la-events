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

REPO = Path(__file__).resolve().parent.parent

# How to invoke each structured fetcher. `needs` = required env vars (skip-with-reason if unset).
# Output is read from the `-o` temp file each script writes (list of records, or {"events": [...]}).
FETCHERS = [
    {"name": "Ticketmaster", "source": "ticketmaster", "script": "fetch_ticketmaster.py",
     "args": ["--days", "{days}"], "needs": ["TM_API_KEY"]},
    {"name": "Resident Advisor", "source": "ra", "script": "fetch_ra.py", "args": ["--days", "{days}"]},
    {"name": "19hz", "source": "19hz", "script": "fetch_19hz.py", "args": []},
    {"name": "Goldenvoice", "source": "goldenvoice", "script": "fetch_goldenvoice.py", "args": []},
    {"name": "Vidiots", "source": "vidiots", "script": "fetch_filmbot.py", "args": []},
    {"name": "Posh", "source": "posh", "script": "fetch_posh.py", "args": [], "needs": ["POSH_TOKEN"]},
    {"name": "Eventbrite", "source": "eventbrite", "script": "fetch_eventbrite.py", "args": []},
    {"name": "DICE", "source": "dice", "script": "fetch_dice.py", "args": []},
]


def run_fetcher(entry: dict, days: int, tmpdir: str) -> list:
    """Run one fetcher as a subprocess and return its normalized records. Raises on any failure."""
    for var in entry.get("needs", []):
        if not os.environ.get(var):
            raise RuntimeError(f"missing ${var}")
    out = Path(tmpdir) / f"{entry['source']}.json"
    args = [a.format(days=days) for a in entry["args"]]
    cmd = [sys.executable, str(REPO / "scripts" / entry["script"]), *args, "-o", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120, cwd=str(REPO))
    raw = json.loads(out.read_text())
    records = raw.get("events", raw) if isinstance(raw, dict) else raw
    return [P.normalize_record(r, entry["source"]) for r in records]


def fetch_all(selected: set, days: int) -> tuple:
    """Run the configured fetchers, collecting normalized records. Returns (incoming, report)."""
    report = {"ok": [], "failed": [], "skipped": []}
    incoming = []
    with tempfile.TemporaryDirectory() as tmp:
        for e in FETCHERS:
            if selected and e["source"] not in selected:
                report["skipped"].append(e["source"])
                continue
            try:
                recs = run_fetcher(e, days, tmp)
                incoming.extend(recs)
                report["ok"].append((e["source"], len(recs)))
            except Exception as ex:  # degrade gracefully — never block the run
                report["failed"].append((e["source"], str(ex).splitlines()[0][:120]))
    return incoming, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--candidates", default="data/candidates.json")
    ap.add_argument("--no-fetch", action="store_true", help="skip fetching; pipeline-only re-run")
    ap.add_argument("--sources", default="", help="comma list to fetch a subset (default: all)")
    ap.add_argument("--days", type=int, default=21, help="fetch window passed to fetchers")
    ap.add_argument("--window", type=int, default=None, help="candidate window in days (default: all upcoming)")
    ap.add_argument("--top", type=int, default=40, help="candidate set size for enrichment")
    ap.add_argument("--images", type=int, default=10, help="how many top candidates are flagged image_wanted")
    args = ap.parse_args()

    cat_path = REPO / args.catalog if not Path(args.catalog).is_absolute() else Path(args.catalog)
    cand_path = REPO / args.candidates if not Path(args.candidates).is_absolute() else Path(args.candidates)

    catalog = json.loads(cat_path.read_text()) if cat_path.exists() else []
    taste, profile = load_taste(), load_profile()
    today = P.today_la()

    report = {"ok": [], "failed": [], "skipped": []}
    incoming = []
    if not args.no_fetch:
        selected = {s.strip() for s in args.sources.split(",") if s.strip()}
        incoming, report = fetch_all(selected, args.days)
        incoming = [r for r in incoming if r.get("title") and r.get("date")]

    # Always dedupe (idempotent) — collapses incoming AND any pre-existing catalog dupes.
    catalog, stats = P.merge_new(catalog, incoming, today)
    catalog, expired = P.expire_past(catalog, today)
    P.stamp_seen(catalog, today)
    cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")

    candidates = P.select_candidates(catalog, taste, profile, today,
                                     window_days=args.window, top_n=args.top, image_n=args.images)
    cand_doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "window_days": args.window,
        "count": len(candidates),
        "image_wanted": sum(1 for c in candidates if c.get("image_wanted")),
        "sources": report,
        "candidates": candidates,
    }
    cand_path.write_text(json.dumps(cand_doc, indent=2, ensure_ascii=False) + "\n")

    # Run report.
    print(f"run_digest {today}: catalog {len(catalog)} "
          f"(+{stats['added']} new, {stats['merged']} merged, {expired} expired) "
          f"-> {len(candidates)} candidates ({cand_doc['image_wanted']} need images)")
    if report["ok"]:
        print("  fetched:", ", ".join(f"{s}:{n}" for s, n in report["ok"]))
    if report["failed"]:
        print("  failed: ", ", ".join(f"{s} ({e})" for s, e in report["failed"]))
    if report["skipped"]:
        print("  skipped:", ", ".join(report["skipped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
