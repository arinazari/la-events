"""Merge Step-2 layered rows (webfetch venues / editorial / one-off JSON-LD) into catalog.json.
Run once per digest, then `run_digest.py --no-fetch` redoes expire/tag/score/candidates.

Rows may already be in catalog schema (`"sources": [...]`) or raw fetcher output (`"source": "x"`);
raw rows are normalized first so they carry `sources` — without it a row never counts toward
source freshness, so the venue would keep reading stale in the run report and digest footer.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from lib import pipeline as P

cat_path = REPO / "data" / "catalog.json"
catalog = json.loads(cat_path.read_text())
today = P.today_la()

incoming = []
for fname in sys.argv[1:]:
    p = Path(fname)
    if not p.exists():
        continue
    rows = json.loads(p.read_text())
    if isinstance(rows, dict):
        rows = rows.get("events", [])
    incoming.extend(r if r.get("sources") else P.normalize_record(r, r.get("source") or "webfetch")
                    for r in rows)

incoming = [r for r in incoming if r.get("title") and r.get("date")]
print(f"layering {len(incoming)} incoming records from {len(sys.argv[1:])} files")

catalog, stats = P.merge_new(catalog, incoming, today)
cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
print("merge stats:", stats)
