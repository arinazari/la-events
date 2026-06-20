#!/usr/bin/env python3
"""Merge an event-editor batch's verdicts into the shared cache (the step after the fan-out).

The event-editor agent returns a JSON array of verdicts (one per event, each with `id`). This
folds them into data/enrichment.json via editor.update_verdicts — validating each, stamping
judged_at, and recording score_at_judge from data/editor_pool.json so a later score drift
re-selects the event. Mirrors how scene-researcher results land via enrich.update_cache.

Usage:
  python scripts/merge_verdicts.py results.json [more.json ...]
  python scripts/merge_verdicts.py -                 # read one results array from stdin
  python scripts/merge_verdicts.py r.json --model claude-opus-4-8
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib import editor as ED  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _resolve(p: str) -> Path:
    p = Path(p)
    return p if p.is_absolute() else REPO / p


def _load_results(paths) -> list:
    """Flatten one-or-more results files (each a JSON array, or {verdicts|results: [...]})."""
    out = []
    for p in paths:
        text = sys.stdin.read() if p == "-" else _resolve(p).read_text()
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("verdicts") or data.get("results") or []
        out.extend(data)
    return out


def _score_map(editor_pool_path: Path) -> dict:
    """{id: deterministic score} from the editor pool, for the score_at_judge stamp."""
    if not editor_pool_path.exists():
        return {}
    ep = json.loads(editor_pool_path.read_text())
    return {e["id"]: e["score"] for e in ep.get("events", [])
            if e.get("id") is not None and e.get("score") is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+", help="event-editor results JSON file(s), or - for stdin")
    ap.add_argument("--cache", default="data/enrichment.json", help="shared enrichment/verdict cache")
    ap.add_argument("--editor-pool", default="data/editor_pool.json", help="source of score_at_judge")
    ap.add_argument("--model", default=None, help="stamp which model produced the verdicts")
    args = ap.parse_args()

    results = _load_results(args.results)
    scores = _score_map(_resolve(args.editor_pool))
    cache_path = _resolve(args.cache)

    cache = ED.load_cache(cache_path)
    before = len(cache.get("verdicts") or {})
    ED.update_verdicts(cache, results, scores=scores, model=args.model)
    ED.save_cache(cache, cache_path)
    after = len(cache.get("verdicts") or {})

    kept = sum(1 for r in results if ED.validate_verdict(r) is not None and r.get("id"))
    try:
        shown = cache_path.relative_to(REPO)
    except ValueError:
        shown = cache_path
    print(f"merge_verdicts: {len(results)} results ({kept} valid) -> "
          f"verdicts {before} -> {after} ({shown})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
