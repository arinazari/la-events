"""One-off: merge pre-fetched squarespace/ics/jsonld/editorial JSON into catalog.json.
Run once per digest, then `run_digest.py --no-fetch` redoes expire/tag/score/candidates.
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
    incoming.extend(rows)

incoming = [r for r in incoming if r.get("title") and r.get("date")]
print(f"layering {len(incoming)} incoming records from {len(sys.argv[1:])} files")

catalog, stats = P.merge_new(catalog, incoming, today)
cat_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
print("merge stats:", stats)
