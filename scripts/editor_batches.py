#!/usr/bin/env python3
"""Plan the event-editor fan-out: one self-contained batch file per parallel agent.

Reads a profile's editor pool, selects what still needs judging (editor.select_for_verdict against
that profile's verdict store — only new/changed events cost a call), and writes
data/editor_batches/<profile-hash|default>/batch-N.json. Each file carries its records, the taste
brief, the Spotify lane, and its own `results_path`: an event-editor agent reads its file, writes
its verdicts to that path, and replies with one summary line. Then merge them all:

  python scripts/merge_verdicts.py data/editor_batches/<key>/*.results.json [--profile-hash H]

Prints ONE JSON line (counts, batch/results paths, the merge command) — the orchestrator never needs
the pool or the verdicts in its own context. The profile's batch dir is cleared first, so a stale
results file from an earlier run can't be merged over fresher verdicts.

Usage:
  python scripts/editor_batches.py                                                  # nightly, default profile
  python scripts/editor_batches.py --profile-hash H --top 40 --batches 2            # nightly, a REFRESH profile
  python scripts/editor_batches.py --profile-hash H --top 40 --cap 24 --batches 4   # the Update click
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ on path
from lib import editor as ED  # noqa: E402
from lib.config import load_yaml  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BATCH_ROOT = REPO / "data" / "editor_batches"


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile-hash", default=None,
                    help="profile feed hash (default profile if omitted)")
    ap.add_argument("--pool", default=None,
                    help="editor pool doc (default: data/editor_pool[.<hash>].json)")
    ap.add_argument("--top", type=int, default=0,
                    help="consider only the N highest-scoring pool events (0 = the whole pool)")
    ap.add_argument("--cap", type=int, default=0,
                    help="judge at most N, highest score first; the rest is backlog (0 = no cap)")
    ap.add_argument("--batches", type=int, default=0,
                    help="split into at most K batches (default: --batch-size events each)")
    ap.add_argument("--batch-size", type=int, default=ED.BATCH_SIZE)
    ap.add_argument("--refresh-days", type=int, default=None,
                    help="also re-judge verdicts older than N days (default: write-once)")
    args = ap.parse_args()

    h = args.profile_hash
    pool_path = Path(args.pool) if args.pool else \
        REPO / (f"data/editor_pool.{h}.json" if h else "data/editor_pool.json")
    if not pool_path.exists():
        print(json.dumps({"error": f"no editor pool at {_rel(pool_path)}", "judging": 0,
                          "batches": []}))
        return 1
    doc = json.loads(pool_path.read_text())
    # The owner's feed hash judges into the default store (editor.resolve_store_hash), exactly
    # as merge_verdicts resolves it — select against the store the merge will write.
    store_h = ED.resolve_store_hash(h, load_yaml(REPO / "profiles.yaml"))
    cache = ED.load_verdicts(profile_hash=store_h)
    plan = ED.plan_batches(doc, cache, top=args.top, cap=args.cap, batches=args.batches,
                           batch_size=args.batch_size, refresh_days=args.refresh_days)

    out_dir = BATCH_ROOT / (h or "default")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    files = []
    for b in plan["batches"]:
        out_dir.mkdir(parents=True, exist_ok=True)
        bp = out_dir / f"batch-{b['batch']}.json"
        rp = out_dir / f"batch-{b['batch']}.results.json"
        body = {"batch": b["batch"], "of": b["of"], "results_path": _rel(rp),
                **{k: v for k, v in b.items() if k not in ("batch", "of")}}
        bp.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n")
        files.append({"file": _rel(bp), "results": _rel(rp), "n": b["count"]})

    merge = (f"python scripts/merge_verdicts.py {_rel(out_dir)}/*.results.json"
             + (f" --profile-hash {h}" if h else "")) if files else None
    print(json.dumps({"profile": h, "pool": _rel(pool_path),
                      **{k: plan[k] for k in ("considered", "selected", "judging", "backlog")},
                      "batches": files, "merge": merge}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
